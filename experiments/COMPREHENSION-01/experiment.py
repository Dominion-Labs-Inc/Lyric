#!/usr/bin/env python3
"""COMPREHENSION-01 — the questions that failed on 2026-09-19, asked again through the conversation, on the sandbox.

`docs/research/COMPREHENSION_SCOPE.md` §3 and §4 measured these against the live substrate on 2026-09-19, none of them
about rendering:
  * a greeting was looked up as a concept: "hello" gave "A hello is an airline. It is a greeting.";
  * a yes/no question with no answer recited facts instead of declining: "is a grandfather clock a beer?" gave clock
    facts, then beer facts;
  * a locative question lost to ambiguity: "where is a dog?" was answered with senses instead of places;
  * sense detection over-fired: "Which dog do you mean?", because "dog" held several unchained kinds;
  * recall recited records as memories, and asked about bass, recalled a fact about an embassy.
Since then the reader, the lessons (english_01–29) and the listener have changed under all of it. This asks again.

Teach first: english_30 (what is said when a place is not known; what follows a greeting or thanks), then WordNet's
records about the words asked of (every sense each writes, the kinds above them, how often each names each thing),
into the sandbox's shared mind, as SENSE-01 teaches K's words. The earlier lessons must be held already. Then one
speaker asks, through `Conversation.understand`, the one turn, with no look-up. The bar is an LLM's: each check says
what an LLM does with the question.

  A  "hello": greeted back, not looked up as a thing; "thank you": a welcome, not thanks back
  B  "is a grandfather clock a beer?": no, or declined, and nothing recited about beer; "is a grandfather clock a
     clock?": yes; "is a canine a domestic animal?": not no, the dog is both
  C  "where is a dog?": no question of which dog; "I do not know where the dog is.". Told "The dog is in the
     kennel.", then asked again: "The dog is in the kennel.". "is the dog big?": "I do not know whether the dog is
     big.". Told a name nothing holds is a mammal, "is it a beer?": no
  D  "what is a dog?": no question of which dog; the dog an LLM means
  E  "what is a bass?": what recall hands up, and what is recited as remembered, is about a bass
  F  every "I remember:" in any reply names what was asked
  G  the main model is untouched, and everything the speaker's turns wrote is removed

Run: ./venv_lyric/bin/python3 experiments/COMPREHENSION-01/experiment.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import random
import re
import string
import sys
import time
from datetime import datetime, timezone

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

_spec = importlib.util.spec_from_file_location("sense_01", ROOT / "experiments" / "SENSE-01" / "experiment.py")
_sense = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sense)

N = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
#: A name nothing holds, told to be a mammal by the speaker.
NONCE = f"vex{N}"
SESSION = f"COMPREHENSION-01-{N}"
DOMAIN = "comprehension_01"
#: The words the questions ask about, taught from WordNet before anything is asked.
WORDS = {"hello", "dog", "clock", "grandfather clock", "beer", "bass", "kennel"}
EV = RunRecord(
    "COMPREHENSION-01",
    claim=("The questions that failed on 2026-09-19 are answered as an LLM answers them: a greeting greeted, a yes/no "
           "with no answer declined without reciting, a place asked for answered with a place or declined, a word one "
           "sense of which anyone means not asked about, and recall about what was asked."),
    hypothesis=("A greeting looked up, a recital after a yes/no, senses offered for a place or a definition, or a "
                "memory recalled for a word it only contains would each fail here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class _NotTaught(Exception):
    """The records would be said wrongly, so the run stops before it teaches them."""


def sentences(reply: str):
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", reply or "") if s.strip()]


def senses_offered(reply: str, word: str) -> bool:
    low = reply.lower()
    return f"which {word} do you mean" in low or f"{word} can mean" in low


async def main() -> int:
    main_before = await _sense.main_store_rows()
    system, coord = await boot()
    d = db()
    where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "lyric_dev", f"connected to {where['d']}")
    actor = None
    asked = []
    try:
        from core.learning import get_learning_authority
        from core.learning.teaching import TeachingPass
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        view = await agent.language_view()
        say_line("== Taught first: english_30, then WordNet's records about the words asked of ==")
        check("the lessons are held already", len(view) > 0, f"{len(view)} constructions and links in the view")
        # What is said when a place is not known, and what follows a greeting or thanks: english_30, taught here
        # where the sandbox does not hold it yet.
        from core.learning.teaching_sources import LessonSource
        lesson = LessonSource(str(ROOT / "data" / "lessons" / "english_30.json"))
        taught = await TeachingPass(lesson, domain=DOMAIN, sample=False).run(get_learning_authority())
        check("english_30 is learned, none refused",
              taught.patterns.get("refused") == 0 and taught.patterns.get("total") == len(list(lesson.records())),
              f"{taught.patterns}")
        source = _sense.GateSource(set(WORDS), sample=0)
        harvest = list(source.records())
        # SAID RIGHT, BEFORE ANYTHING IS TAUGHT (`said_wrongly`): what the substrate says of each fact is what it
        # learns English from, and two runs of this experiment taught the sandbox wrong sentences that way.
        wrong = _sense.said_wrongly(harvest)
        check("every fact is said as its words are used, before anything is taught", not wrong,
              f"{len(wrong)} wrong: {wrong[:4]}" if wrong else "")
        if wrong:
            raise _NotTaught()
        started = time.time()
        since = datetime.now(timezone.utc)
        built_from = _sense.frame_words()
        report = await TeachingPass(source, domain=DOMAIN, sample=False).run(get_learning_authority())
        say_line(f"    {len(harvest)} records about {sorted(WORDS)}, their senses and the kinds above them, "
                 f"in {time.time() - started:.0f} s")
        for line in report.lines():
            say_line(f"    {line}")
        guarded, other = await _sense.refused_facts(d, since, DOMAIN)
        EV.metric("facts refused: about a word that names nothing", guarded)
        check("nothing taught is refused: no sentence, and no fact but about a word the lessons use only to build "
              "sentences", report.patterns.get("refused") == 0 and not other,
              f"sentences {report.patterns.get('refused')}; facts refused otherwise {len(other)}: {other[:4]}; "
              f"about such words {len(guarded)}")
        EV.metric("records taught", len(harvest))
        # THE NOUNS ASKED OF ARE COUNTED THINGS. Once every noun in the view was taken as a plural (a frame holding
        # mostly other words for its concepts was taken to take a shape), and what was taught was then said, and
        # learned, wrongly: "Chore is body of work.". Checked before anything is asked.
        view = await agent.language_view()
        uses = {word: view.used_as(word) for word in ("dog", "clock", "beer", "kennel")}
        check("the nouns asked of are held as counted things, none as a plural",
              all(use == "count" for use in uses.values()), f"{uses}")
        wrong = [p.surface for p in view.item_based() if "is body of" in p.surface]
        check("no fact was said through a frame that is no English", not wrong, f"{wrong[:3]}")
        # What the learner made of it (`frames_wrongly`): saying first cannot show it.
        odd = _sense.frames_wrongly(built_from)
        check("no frame made while it was taught holds a fact's word", not odd,
              f"{len(odd)}: {odd[:4]}" if odd else "")

        conversation = coord.conversation(SESSION)
        actor = conversation._actor

        async def ask(sentence):
            understanding = await conversation.understand(sentence, look_up=False)
            reply = type(conversation).say(understanding)
            remembered = [str(m) for m in (understanding.remembered or [])]
            asked.append({"said": sentence, "reply": reply, "remembered": remembered[:12]})
            say_line(f"\n    > {sentence}\n    < {reply}")
            if remembered:
                say_line(f"      recall handed up {len(remembered)}: "
                         + " | ".join(m.replace("\n", " ")[:70] for m in remembered[:4]))
            return reply, remembered

        say_line("\n== A. A greeting ==")
        reply, _ = await ask("hello")
        low = reply.lower()
        check("A: 'hello' is not looked up as a thing",
              not any(p in low for p in ("a hello is", "hello can mean", "hold hello", "hold nothing for hello",
                                         "search")), reply[:140])
        check("A: 'hello' is greeted back", re.match(r"^(hello|hi|hey|good (morning|afternoon|evening))\b", low),
              reply[:140])
        reply, _ = await ask("thank you")
        check("A: thanks are answered with a welcome, not with thanks", "welcome" in reply.lower(), reply[:140])

        say_line("\n== B. A yes/no question with no answer ==")
        reply, _ = await ask("is a grandfather clock a beer?")
        low = reply.lower()
        check("B: answered no, or declined",
              low.startswith("no") or "hold nothing" in low or "don't" in low or "do not" in low, reply[:140])
        check("B: nothing is recited about beer",
              not any(re.match(r"^(a |an |the )?beers?\b", s.lower()) for s in sentences(reply)), reply[:200])
        reply, _ = await ask("is a grandfather clock a clock?")
        check("B: control, 'is a grandfather clock a clock?' answered yes", reply.lower().startswith("yes"),
              reply[:140])
        reply, _ = await ask("is a canine a domestic animal?")
        check("B: 'is a canine a domestic animal?' is not answered no: the dog is both",
              not reply.lower().startswith("no"), reply[:140])
        check("B: it answers with what is both, the dog, and not with what a canine is",
              "dog" in reply.lower() and "carnivore" not in reply.lower(), reply[:140])
        check("B: it calls the dog a dog, the word most used for it, and the canine as it was asked",
              reply.strip() == "A dog is a canine. A dog is a domestic animal.", reply[:140])

        say_line("\n== C. Where a thing is ==")
        reply, _ = await ask("where is a dog?")
        check("C: 'where is a dog?' offers no senses", not senses_offered(reply, "dog"), reply[:200])
        check("C: nothing told of where, it says it does not know where, in the speaker's word for it",
              reply.strip() == "I do not know where the dog is.", reply[:200])
        # Said as the lessons say where a thing is ("The book is in the box.", english_01).
        reply, _ = await ask("The dog is in the kennel.")
        told = await d.execute_query(
            "SELECT subj, rel, obj FROM unified.scoped_concept_relations WHERE scope_actor = $1",
            (actor,), fetch_all=True) or []
        held = [(r["subj"], r["rel"], r["obj"]) for r in told]
        check("C: told 'The dog is in the kennel.', the speaker's context holds it",
              any(s == "dog" and o == "kennel" for s, _, o in held), f"{held}")
        reply, _ = await ask("where is a dog?")
        check("C: asked again, the kennel, said as the speaker said it",
              reply.strip() == "The dog is in the kennel.", reply[:200])
        reply, _ = await ask("is the dog big?")
        check("C: a yes/no nothing held decides is said not to be known",
              reply.strip() == "I do not know whether the dog is big.", reply[:200])
        reply, _ = await ask(f"a {NONCE} is a mammal")
        reply, _ = await ask(f"is a {NONCE} a beer?")
        check("C: a thing only told of is not a kind its own kind excludes: no, a mammal is no beer",
              reply.lower().startswith("no"), reply[:200])

        say_line("\n== D. A word one sense of which anyone means ==")
        reply, _ = await ask("what is a dog?")
        check("D: 'what is a dog?' asks no question of which dog", not senses_offered(reply, "dog"), reply[:200])
        check("D: says the dog an LLM means (a canine, a domestic animal), called a dog",
              "a dog is a canine" in reply.lower() and "a dog is a domestic animal" in reply.lower()
              and "domestic dog" not in reply.lower(), reply[:200])

        say_line("\n== E. Recall about what was asked ==")
        reply, remembered = await ask("what is a bass?")
        inside = [m for m in remembered if re.search(r"bass", m, re.I) and not re.search(r"\bbass(es)?\b", m, re.I)]
        about = [m for m in remembered if re.search(r"\bbass(es)?\b", m, re.I)]
        EV.metric("E: memories recall handed up", len(remembered))
        EV.metric("E: of them naming a bass", len(about))
        check("E: recall hands up nothing that holds 'bass' only inside another word (ambassador, embassy)",
              not inside, f"{len(inside)} of {len(remembered)}: " + " | ".join(m[:60] for m in inside[:3]))
        check("E: what recall hands up names a bass", len(about) == len(remembered),
              f"{len(about)} of {len(remembered)}")

        say_line("\n== F. What is recited as remembered ==")
        recited = []
        for turn in asked:
            # The words that name something: every word of what was asked but the ones that name nothing.
            words = set(re.findall(r"[a-z]+", turn["said"].lower())) - {
                "a", "an", "the", "is", "are", "what", "where", "who", "which", "how", "do", "does", "you", "i"}
            for line in re.findall(r"I remember: ([^\n]*)", turn["reply"]):
                recited.append((turn["said"], line, any(w in line.lower() for w in words)))
        EV.metric("F: recited as remembered", len(recited))
        check("F: every 'I remember:' names what was asked", all(ok for _, _, ok in recited),
              "; ".join(f"{s!r}: {line[:60]}" for s, line, ok in recited if not ok) or f"{len(recited)} recited")
    except _NotTaught:
        say_line("    NOTHING IS TAUGHT OR ASKED: what would be said of the records is wrong English, and would be "
                 "learned")
    finally:
        try:
            if actor:
                left = await _clean(d, actor)
                check("G: everything the speaker's turns wrote is removed", sum(left.values()) == 0, f"{left}")
        finally:
            await shutdown(system)

    main_after = await _sense.main_store_rows()
    check("G: the main model's store is untouched", main_after == main_before,
          _sense.main_store_change(main_before, main_after))
    EV.metric("turns", asked)
    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# COMPREHENSION-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


#: What a speaker's turns write, by the column that names the speaker.
_BY_SPEAKER = (
    ("scoped_concept_relations", "unified.scoped_concept_relations", "scope_actor", "id"),
    ("scoped_beliefs", "unified.scoped_beliefs", "scope_actor", "id"),
    ("memory_hot", "memory_hot.memory_hot", "user_id", "memory_id"),
    ("experience_pool", "unified.experience_pool", "owner", "item_id"),
)


async def _clean(d, actor):
    """Snapshot, then delete, everything written for this run's speaker; what is left after."""
    snap = {}
    for name, table, column, _ in _BY_SPEAKER:
        snap[name] = [dict(r) for r in (await d.execute_query(
            f"SELECT * FROM {table} WHERE {column} = $1", (actor,), fetch_all=True) or [])]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "data" / "snapshots" / f"comprehension_01_{N}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, default=str, indent=1))
    EV.note(f"residue snapshot: {path.relative_to(ROOT)}")
    EV.metric("rows removed", {k: len(v) for k, v in snap.items()})
    for name, table, column, _ in _BY_SPEAKER:
        await d.execute_query(f"DELETE FROM {table} WHERE {column} = $1", (actor,))
    left = {}
    for name, table, column, _ in _BY_SPEAKER:
        row = await d.execute_query(f"SELECT count(*) AS n FROM {table} WHERE {column} = $1", (actor,),
                                    fetch_one=True)
        left[name] = int(row["n"])
    return left


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
