"""UNDERSTANDS-PROSE-01: reading prose and reasoning over it.

Short texts written as their sources write them -- an encyclopedia entry, a science explanation, a webpage, code
documentation, mathematics, premises and a rule, history, a paper abstract, a security log, a news item
(`texts.json`) -- each told sentence by sentence in a conversation of its own, then asked questions that need what
it said: what it says outright, and what follows from it (the Eiffel Tower is in France because it is in Paris).

Scored as a reader is: how many sentences it understood whole; how many it said back as it was told; and of the
questions, how many it answered right, how many it did not answer (it does not know, or did not read), and how
many it answered WRONG -- a wrong answer is worse than none, and is counted apart.

A SENTENCE UNDERSTOOD WHOLE IS ONE THE READER MADE A MEANING OF, asked of the reading. It was asked of the
reply's wording until 2026-11-05 -- any reply holding none of six phrases like "I don't know '" counted -- which
tests that something was said, not that anything was read, and passed everything confident
(`understood_whole`). These texts carry no meaning taught with them, so nothing here can judge that the meaning
is the SENTENCE'S: a reading that is confident and wrong passes, and that limit is reported with the number.

WHAT EACH WAS READ AS, AND WHY EACH ANSWER WAS GIVEN, is kept in the transcript: each reading (marked where it was
composed), and what the reasoner was asked and said for each question. A sentence or question that
stops the conversation is kept with what stopped it, counted apart, and the run goes on.

ASKED WITHOUT BEING REMEMBERED, SO IT RUNS ON MAIN: each conversation is held with `remembers=False`, keeps what it
is told for as long as it lasts, and writes nothing to the store; the server's own counters before and after say so.

UNDERSTANDS-PROSE-02 runs this same harness (`main`) on texts of its own, held out from all of this.

Run (from the Lyric folder; starts no substrate):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-01/experiment.py
"""
import asyncio
import contextlib
import io
import json
import logging
import math
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
CLAIM = ("the substrate reads prose as its sources write it and reasons over what it read: it understands the "
         "sentences, answers what they say and what follows, and does not answer wrongly what it did not understand")

#: Fixed before the run: what a reader that understood would reach.
BARS = {
    "sentences understood": (0.90, False),
    "questions answered right": (0.80, False),
    "questions answered wrong (must be low)": (0.02, True),
}
#: How a reply says it did not read or does not know: no answer, not a wrong one.
NOT_ANSWERED = ("I don't know", "I do not know", "I understood", "I hold nothing", "I don't hold", "I know these words",
                "I remember", "I read that more than one way", "Part of that")


def say(*a):
    print(*a, flush=True)


#: How a reply to a telling says it was not read whole: a word left over, a way of putting words never taught, a word
#: never met, more than one way to take it, or a part about nothing it can name.
UNREAD = ("I understood '", "I know these words", "I don't know '", "I read that more than one way",
          "Part of that is about", "part of that is about")


def readings_of(conversation, text):
    """What `text` was read as, each utterance's readings written canonically, a composed one marked; what stopped
    the reading, where something did."""
    try:
        return [[("composed: " if getattr(r, "composed", False) else "") + r.meaning.canonical() for r in u.readings]
                for u in conversation._read(text)]
    except Exception as e:
        return f"STOPPED: {type(e).__name__}: {e}"


#: How a telling is acknowledged with what was stored (`autonomous_coordinator`): the sentences said back follow it.
SAID_BACK = "Noted - "


def said_back(conversation, sentence, reply, readings):
    """Whether what it said back MEANS what it was told: the acknowledgement read again, against the reading of
    the telling. True, False, or None where it acknowledged with no sentence of its own to read.

    A reader shows what it took a sentence to mean by saying it back, and a reply that means something else is a
    failure no count of readings can see: "Ken or Yumi sang." is a whole reading, and a whole reading of the
    wrong thing, for a telling joined by "and". Compared as meanings and not as words, so a sentence said back
    in other words of the same meaning counts ("Ken and Yumi were singing.").

    IT UNDER-REPORTS RATHER THAN FLATTERS. Only the first line is read, and only up to what the acknowledgement
    says; a reply carrying more than it was told (what the store already held, an opposite on record) compares
    as False, and a meaning said back that this cannot line up counts against saying, never for it."""
    said = (reply or "").strip().splitlines()[0].strip() if (reply or "").strip() else ""
    if not said.startswith(SAID_BACK):
        return None
    said = said[len(SAID_BACK):].strip()
    if not said or not isinstance(readings, list) or not readings:
        return None
    told = {meaning for utterance in readings for meaning in utterance}
    back = readings_of(conversation, said)
    if not isinstance(back, list) or not back:
        return False
    return {meaning for utterance in back for meaning in utterance} == told


def understood_whole(understanding, readings=None) -> bool:
    """Whether a told sentence was read whole: THE READER MADE A MEANING OF EVERY PART OF IT (`readings`, as
    `readings_of` gives them), and the reply does not say it failed to.

    ASKED OF THE READING AND NOT OF THE REPLY'S WORDING. This was the reply alone -- a non-empty reply holding
    none of six phrases like "I don't know '" counted as understood -- which is a test that something was said,
    not that anything was read. Everything confident passed it. Measured on 2026-11-05, it scored
    "Noted - Africa straddles Equator 1." as understood (the store's own name for a thing, spelled into the
    reply); it scored "Noted - Yumi and Ken sang." as understood of "Ken and Yumi sang."; it scored
    "Noted - Ken or Yumi sang." as understood of a telling joined by "and"; and it scores
    "Africa is the second-largest continent." as understood of a reading that asserts Africa is the LARGEST
    continent. Three defects were found and fixed that day and this number could not have moved for any of them,
    nor for breaking them again.

    `readings` is what `readings_of` gave for the same sentence: one list of readings for each utterance of it,
    each written canonically, or a string where the reading stopped. A sentence is read whole where every
    utterance has a reading -- that the reader produced a meaning of it, which is the thing being claimed. It
    does NOT say the meaning is the sentence's: these texts carry no meaning taught with them to compare
    against, so nothing here can judge that, and a reading that is confident and wrong still passes. That is a
    limit of this measure and is reported with it, not hidden."""
    reply = (understanding.reply or "").strip()
    if not reply or any(marker in reply for marker in UNREAD):
        return False
    return isinstance(readings, list) and bool(readings) and all(bool(r) for r in readings)


def said(word, reply) -> bool:
    """Whether a reply says `word` where a word of it begins ("droplet" in "droplets"), a number only whole: the "5"
    of 10.0.0.5 or of 47068 does not say 5."""
    start = r"(?<![0-9A-Za-z.,])" if word[0].isdigit() else r"(?<![0-9A-Za-z])"
    end = r"(?![0-9])" if word[-1].isdigit() else ""
    return re.search(start + re.escape(word.lower()) + end, reply.lower()) is not None


def interval(k, n, z=1.96):
    """The 95% (Wilson) interval of k in n."""
    if not n:
        return 0.0, 1.0
    p, spread = k / n, z * z / n
    middle = (p + spread / 2) / (1 + spread)
    half = z * math.sqrt(p * (1 - p) / n + spread / (4 * n)) / (1 + spread)
    return max(0.0, middle - half), min(1.0, middle + half)


def scored(question, understanding) -> str:
    """right, not answered, or wrong. A question asking what, who or how many is answered only where an answer was
    given (`understanding.answers`), as a yes or no is only by a verdict. Scored by its words alone, a reply naming
    what it holds nothing of was an answer: "I hold 10.0.0.5 but nothing said about it yet." was right for "How many
    failed attempts were there?" (five), by the "5" in the address (2026-10-21); since, a word is found only where a
    word of the reply begins, and a number only whole (`said`)."""
    gold = question["answer"]
    reply = (understanding.reply or "").strip()
    verdicts = [a.verdict for a in (understanding.answers or []) if a.verdict is not None]
    if isinstance(gold, str):
        wanted = gold == "yes"
        if not verdicts:
            return "not answered"
        return "right" if all(v is wanted for v in verdicts) else "wrong"
    if not understanding.answers:
        return "not answered"
    if any(said(word, reply) for word in gold):
        return "right"
    if not reply or reply.startswith(NOT_ANSWERED):
        return "not answered"
    return "wrong"


async def main(experiment="UNDERSTANDS-PROSE-01", here=HERE, claim=CLAIM, start=1, end=None, only=None,
               part=None) -> int:
    """Tells and asks the texts of `here`/texts.json, from text number `start` to `end` (the last, when None), only
    the numbers in `only` where it is given (`part` names them), and writes the run to `here`/results. Each text is told in a conversation of its own, so a run stopped between texts goes on exactly
    from the next."""
    (here / "results").mkdir(exist_ok=True)
    # WHAT THE SUBSTRATE IS DOING IS SEEN WHILE IT DOES IT, not read out of a file afterwards. Kept to the file
    # alone, a run showed its ten lines of told-and-asked and nothing of the reading, the admitting, the saying or
    # why any of them gave up, and work in the substrate was done by reading the log from outside with the run
    # already over (2026-11-04). The stream is taken here, so what the harness quietens for its own output
    # (`redirect_stdout`) does not quieten this.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s: %(message)s',
                        handlers=[logging.FileHandler(here / "results" / "run.log", mode="w"),
                                  logging.StreamHandler(sys.stdout)])
    from experiments._evidence import RunRecord
    EV = RunRecord(experiment, claim=claim, hypothesis="each measure reaches its bar, fixed before the run (BARS)",
                   results_dir=here / "results")
    texts = json.loads((here / "texts.json").read_text())
    from core.semantics import derived_reader
    composing = "on" if derived_reader.COMPOSING else "off"
    EV.note(f"reading by English's grammar {composing}: an utterance no taught frame reads is "
            f"{'read by the grammar memory reads with (core/semantics/grammar.py; on by default, LYRIC_COMPOSE=0 turns it off)' if composing == 'on' else 'left unread'}")
    say(f"reading by English's grammar {composing} (on by default; LYRIC_COMPOSE=0 turns it off)")
    if derived_reader.COMPOSING and derived_reader.COMPOSING_FORCED:
        EV.note("an utterance every frame reads only by supposing more than any lesson read as taught is read by the "
                "grammar instead (on by default; LYRIC_COMPOSE_FORCED=0 turns it off)")
        say("utterances frames read only by supposing read by the grammar (LYRIC_COMPOSE_FORCED=0 turns it off)")
    quiet = io.StringIO()
    say("loading memory, the beliefs and the language view (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.autonomous.autonomous_coordinator import get_conversation
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        agent = await get_memory_agent()
        await agent.initialize()
        await get_uncertainty_system().load_from_db()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
        db = await get_unified_db()
        if not getattr(db, "initialized", False):
            await db.initialize()
    EV.check("the run is on the store it says", await EV.verify_database() is not None,
             f"connected to {EV.verified_database}")

    async def written():
        rows = await db.execute_query(
            "SELECT schemaname || '.' || relname AS name, n_tup_ins + n_tup_upd + n_tup_del AS n "
            "FROM pg_stat_user_tables")
        return {row["name"]: int(row["n"]) for row in rows or ()}
    before = await written()

    # WHY EACH ANSWER WAS GIVEN: what the reasoner was asked, and what it said and by which route, watched, not changed.
    from core.reasoning.neural_bridge import get_neural_bridge
    bridge, reasoned = get_neural_bridge(), []
    reason = bridge.reason

    async def watched(request):
        result = await reason(request)
        reasoning = getattr(request, "reading", None)
        reasoned.append({"asked": [f.render() for f in reasoning.facts] if reasoning is not None else None,
                         "answer": result.answer, "route": (result.metadata or {}).get("route"),
                         "steps": list(result.reasoning_steps or [])[:8]})
        return result
    bridge.reason = watched

    async def understand(conversation, said):
        """The conversation's understanding of what was said, or what stopped it."""
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                return await conversation.understand(said, look_up=False), None
        except Exception as e:
            import traceback
            frames = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.endswith(".py")][-4:]
            where = " < ".join(f"{Path(f.filename).name}:{f.lineno}" for f in reversed(frames))
            return None, f"{type(e).__name__}: {e} ({where})"

    sentences = read = stopped = 0
    said_as_told = had_a_reply = 0
    tally = {"right": 0, "not answered": 0, "wrong": 0, "stopped": 0}
    by_kind = {}
    transcript = []
    # KEPT AS IT GOES: each sentence and question is written the moment it is done, so a run stopped part-way keeps
    # all it did. UNDERSTANDS-PROSE-02's first run was stopped after 14 hours on one sentence, and its transcript,
    # written only at the end, was lost.
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    going = (here / "results" / f"{stamp}_transcript.jsonl").open("a")

    def kept(entry):
        transcript.append(entry)
        going.write(json.dumps(entry, default=str) + "\n")
        going.flush()
    end = end or len(texts)
    if start > 1 or end < len(texts):
        EV.note(f"texts {start} to {end} only, of {len(texts)}: the rest run apart")
    if only is not None:
        EV.note(f"{part or 'part'}: texts {sorted(only)} only, of {len(texts)}")
    for n, text in list(enumerate(texts))[start - 1:end]:
        if only is not None and n + 1 not in only:
            continue
        say(f"\n=== {text['name']} ({text['kind']})")
        conversation = get_conversation(f"{experiment.lower().replace('-', '_')}_{n}", remembers=False)
        kind = by_kind.setdefault(text["kind"], {"read": 0, "of": 0, "right": 0, "asked": 0, "wrong": 0})
        for sentence in text["text"]:
            started = time.perf_counter()
            u, stop = await understand(conversation, sentence)
            # READ ONCE AND USED FOR BOTH, the judgment and the transcript, so the sentence is not read twice.
            readings = readings_of(conversation, sentence)
            whole = u is not None and understood_whole(u, readings)
            sentences += 1
            read += whole
            stopped += stop is not None
            kind["of"] += 1
            kind["read"] += whole
            reply = (u.reply or "") if u is not None else f"STOPPED: {stop}"
            line = f"  told  {'read  ' if whole else 'UNREAD'} {sentence!r} ({time.perf_counter() - started:.1f}s)"
            say(line + (f"\n          -> {reply.strip()[:160]!r}" if not whole else ""))
            # AND WHETHER WHAT IT SAID BACK MEANS WHAT IT WAS TOLD. A telling is acknowledged by saying back what
            # was stored, so the reply is the one place a reader shows what it took the sentence to mean -- and
            # a reply meaning something else is a failure no count of READINGS can see: "Ken or Yumi sang." is a
            # whole reading of a telling joined by "and". Reported beside the reading, never folded into it:
            # a sentence read right and said back badly is a defect of saying, and the two are not one number.
            faithful = said_back(conversation, sentence, reply, readings)
            said_as_told += faithful is True
            had_a_reply += faithful is not None
            kept({"text": text["name"], "told": sentence, "read": whole, "reply": reply,
                  "said_back_as_told": faithful, "readings": readings})
        for question in text["questions"]:
            started = time.perf_counter()
            del reasoned[:]
            u, stop = await understand(conversation, question["q"])
            result = scored(question, u) if u is not None else "stopped"
            tally[result] += 1
            kind["asked"] += 1
            kind["right"] += result == "right"
            kind["wrong"] += result == "wrong"
            reply = (u.reply or "") if u is not None else f"STOPPED: {stop}"
            say(f"  asked {question['q']!r} -> {result.upper() if result != 'right' else 'right'} "
                f"({time.perf_counter() - started:.1f}s)\n          -> {reply.strip()[:200]!r}")
            kept({"text": text["name"], "asked": question["q"], "gold": question["answer"],
                               "result": result, "reply": reply, "readings": readings_of(conversation, question["q"]),
                               "answers": [{"about": a.about, "relation": a.relation, "others": list(a.others),
                                            "verdict": a.verdict, "support": list(a.support),
                                            "conclusion": a.conclusion} for a in (u.answers if u else [])],
                               "reasoned": list(reasoned)})
        await asyncio.sleep(0)

    asked = sum(tally.values())
    values = {"sentences understood": (read, sentences),
              "questions answered right": (tally["right"], asked),
              "questions answered wrong (must be low)": (tally["wrong"], asked)}
    say("\nresults:")
    for label, (bar, must_be_low) in BARS.items():
        k, n = values[label]
        value = k / max(1, n)
        low, high = interval(k, n)
        ok = value <= bar if must_be_low else value >= bar
        EV.check(f"{label} {'≤' if must_be_low else '≥'} {bar:.0%}", ok,
                 f"{k}/{n} = {value:.1%} (95% interval {low:.1%} to {high:.1%})")
        EV.metric(label, round(value, 4), unit="fraction", note=f"{k}/{n}; 95% interval {low:.1%} to {high:.1%}")
        say(f"  {label:42} {k}/{n} = {value:.1%}  [{low:.1%}, {high:.1%}]  (bar {'≤' if must_be_low else '≥'} {bar:.0%})")
    # SAID BACK AS TOLD, reported and given no bar: it is new on 2026-11-05 and a bar is fixed BEFORE a run, not
    # chosen once the number is known. It is a measure of SAYING, which the sentences-understood bar is not.
    EV.metric("said back as told", round(said_as_told / max(1, had_a_reply), 4), unit="fraction",
              note=f"{said_as_told}/{had_a_reply} acknowledgements read back to the meaning of the telling")
    say(f"  {'said back as told (no bar: new)':42} {said_as_told}/{had_a_reply} = "
        f"{said_as_told / max(1, had_a_reply):.1%}")
    EV.note("sentences understood is asked of the READING: that the reader made a meaning of every part of the "
            "sentence. These texts carry no meaning taught with them, so nothing here judges whether that meaning "
            "is the sentence's, and a reading that is confident and wrong passes it.")
    EV.check("nothing told or asked stopped the conversation", stopped + tally["stopped"] == 0,
             f"{stopped} told, {tally['stopped']} asked")
    EV.metric("told or asked and stopped", stopped + tally["stopped"], unit="sentences")
    say(f"  {'stopped':42} {stopped} told, {tally['stopped']} asked")
    for kind, k in by_kind.items():
        line = (f"{kind}: sentences {k['read']}/{k['of']}, questions right {k['right']}/{k['asked']}, "
                f"wrong {k['wrong']}")
        say(f"    {line}")
        EV.note(line)
    going.close()
    (here / "results" / f"{stamp}_transcript.json").write_text(json.dumps(transcript, indent=1, default=str))

    # NOTHING WRITTEN: the server's counters, a moment after the last question, against the ones before the first.
    await asyncio.sleep(1)
    after = await written()
    moved = {name: after[name] - before.get(name, 0) for name in after if after[name] != before.get(name, 0)}
    EV.check("the reading and the questions wrote nothing to the store", not moved,
             "; ".join(f"{name} +{n}" for name, n in sorted(moved.items())) or "no table written to")
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
