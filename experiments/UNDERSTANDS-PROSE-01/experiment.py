"""UNDERSTANDS-PROSE-01: reading prose and reasoning over it.

Short texts written as their sources write them -- an encyclopedia entry, a science explanation, a webpage, code
documentation, mathematics, premises and a rule, history, a paper abstract, a security log, a news item
(`texts.json`) -- each told sentence by sentence in a conversation of its own, then asked questions that need what
it said: what it says outright, and what follows from it (the Eiffel Tower is in France because it is in Paris).

Scored as a reader is: how many sentences it understood whole; and of the questions, how many it answered right,
how many it did not answer (it does not know, or did not read), and how many it answered WRONG -- a wrong answer is
worse than none, and is counted apart.

WHAT EACH WAS READ AS, AND WHY EACH ANSWER WAS GIVEN, is kept in the transcript: each reading (marked where it was
composed), and what the reasoner was asked and said for each question. A sentence or question that
stops the conversation is kept with what stopped it, counted apart, and the run goes on.

ASKED WITHOUT BEING REMEMBERED, SO IT RUNS ON MAIN: each conversation is held with `remembers=False`, keeps what it
is told for as long as it lasts, and writes nothing to the store; the server's own counters before and after say so.

Run (from the Lyric folder; starts no substrate):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/UNDERSTANDS-PROSE-01/experiment.py
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
LOG = HERE / "results" / "run.log"
LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(LOG, mode="w")])

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


def understood_whole(understanding) -> bool:
    """Whether a told sentence was read whole, as the reply to it says: a telling taken in is "Noted", and has no
    reading of its own to show."""
    reply = (understanding.reply or "").strip()
    return bool(reply) and not any(marker in reply for marker in UNREAD)


def scored(question, understanding) -> str:
    """right, not answered, or wrong."""
    gold = question["answer"]
    reply = (understanding.reply or "").strip()
    verdicts = [a.verdict for a in (understanding.answers or []) if a.verdict is not None]
    if isinstance(gold, str):
        wanted = gold == "yes"
        if not verdicts:
            return "not answered"
        return "right" if all(v is wanted for v in verdicts) else "wrong"
    if any(word.lower() in reply.lower() for word in gold):
        return "right"
    if not reply or reply.startswith(NOT_ANSWERED):
        return "not answered"
    return "wrong"


async def main() -> int:
    from experiments._evidence import RunRecord
    EV = RunRecord("UNDERSTANDS-PROSE-01",
                   claim="the substrate reads prose as its sources write it and reasons over what it read: it "
                         "understands the sentences, answers what they say and what follows, and does not answer "
                         "wrongly what it did not understand",
                   hypothesis="each measure reaches its bar, fixed before the run (BARS)")
    texts = json.loads((HERE / "texts.json").read_text())
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
    tally = {"right": 0, "not answered": 0, "wrong": 0, "stopped": 0}
    by_kind = {}
    transcript = []
    for n, text in enumerate(texts):
        say(f"\n=== {text['name']} ({text['kind']})")
        conversation = get_conversation(f"understands_prose_01_{n}", remembers=False)
        kind = by_kind.setdefault(text["kind"], {"read": 0, "of": 0, "right": 0, "asked": 0, "wrong": 0})
        for sentence in text["text"]:
            started = time.perf_counter()
            u, stop = await understand(conversation, sentence)
            whole = u is not None and understood_whole(u)
            sentences += 1
            read += whole
            stopped += stop is not None
            kind["of"] += 1
            kind["read"] += whole
            reply = (u.reply or "") if u is not None else f"STOPPED: {stop}"
            line = f"  told  {'read  ' if whole else 'UNREAD'} {sentence!r} ({time.perf_counter() - started:.1f}s)"
            say(line + (f"\n          -> {reply.strip()[:160]!r}" if not whole else ""))
            transcript.append({"text": text["name"], "told": sentence, "read": whole, "reply": reply,
                               "readings": readings_of(conversation, sentence)})
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
            transcript.append({"text": text["name"], "asked": question["q"], "gold": question["answer"],
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
        ok = value <= bar if must_be_low else value >= bar
        EV.check(f"{label} {'≤' if must_be_low else '≥'} {bar:.0%}", ok, f"{k}/{n} = {value:.1%}")
        EV.metric(label, round(value, 4), unit="fraction", note=f"{k}/{n}")
        say(f"  {label:42} {k}/{n} = {value:.1%}  (bar {'≤' if must_be_low else '≥'} {bar:.0%})")
    EV.check("nothing told or asked stopped the conversation", stopped + tally["stopped"] == 0,
             f"{stopped} told, {tally['stopped']} asked")
    EV.metric("told or asked and stopped", stopped + tally["stopped"], unit="sentences")
    say(f"  {'stopped':42} {stopped} told, {tally['stopped']} asked")
    for kind, k in by_kind.items():
        line = (f"{kind}: sentences {k['read']}/{k['of']}, questions right {k['right']}/{k['asked']}, "
                f"wrong {k['wrong']}")
        say(f"    {line}")
        EV.note(line)
    (HERE / "results").mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (HERE / "results" / f"{stamp}_transcript.json").write_text(json.dumps(transcript, indent=1, default=str))

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
