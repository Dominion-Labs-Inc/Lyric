#!/usr/bin/env python3
"""SHAPES-LEARN-04 — it asks about what it cannot read, is answered by example, and reads what it asked about.

Part 1 of step 3b in `docs/research/SHAPES_CHANGE_MAP.md` (§11c): no sentence is thrown away. A sentence that does
not read whole is read in parts, the words nothing held has are named, and the reply asks about them. The answers
are given the way English is taught here: sentence-meaning pairs through the ONE teaching path, never the sentences
it asked about.

  A  TEACH      the first lesson (`data/lessons/english_01.json`), as SHAPES-LEARN-03 teaches it
  B  ASK        told four sentences the lesson never taught, it reads none of them whole; every reply says what it
                understood and asks about the rest, none says it could not read; each is remembered as said
  C  ANSWER     the second lesson (`data/lessons/english_02.json`): "and", "or", "true", "my ... is not a ...,
                he is ...", by example; none of the four sentences is in it
  D  READ       the four read whole, to the meanings they have; what the lessons never taught stays unread whole
  E  TOLD AGAIN the conversation is told them again: what it notes is said with the sentences it was taught, never
                the store's words or a template's; a pronoun points within the text; a question is not recited back
  F  PROSE      NLU-01's 300 sentences: utterances read whole, and pieces read whole or in parts (measured)
  G  NOTHING    reading wrote nothing
  H  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`. What it leaves is kept: both
lessons, and the conversation remembered.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-04/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from core.semantics.derived_reader import Meaning, MeaningFact as F  # noqa: E402

FIRST = ROOT / "data" / "lessons" / "english_01.json"
SECOND = ROOT / "data" / "lessons" / "english_02.json"
DOMAIN = "shapes_learn_04"


def _m(act, *facts, asked=()):
    """A meaning from facts written `relation subject object`: `!` before a denied relation, `either ` before an
    alternative; `_` stands for a space inside a name."""
    out = []
    for fact in facts:
        alternative = fact.startswith("either ")
        relation, subject, obj = (fact[7:] if alternative else fact).split()
        out.append(F(relation.lstrip("!"), subject.replace("_", " "), obj.replace("_", " "),
                     not relation.startswith("!"), alternative=alternative))
    return Meaning(act, tuple(out), tuple(asked))


#: What it is told, and what each utterance of it means once the answers are taught.
ASKED_ABOUT = [
    ("The door is open and the window is closed.",
     [_m("tell", "has_property door open", "has_property window closed")]),
    ("My dog is not a cat, he is a dog.",
     [_m("tell", "instance_of ?x dog", "owned_by ?x ?speaker", "!instance_of ?x cat"),
      _m("tell", "instance_of ?previous dog")]),
    ("Is the stove hot or cold?",
     [_m("ask", "either has_property stove hot", "either has_property stove cold")]),
    ("It is not true that the door is open.",
     [_m("tell", "!has_property door open")]),
]
#: What neither lesson taught, which must not read whole after them either.
NEVER_TAUGHT = ["the the the", "The door is open or the window is closed.", "I think the tank is full."]

EV = RunRecord(
    "SHAPES-LEARN-04",
    claim=("Told sentences it cannot read whole, the substrate says what it understood and asks about what it did "
           "not, and remembers what was said. Answered by example through its one teaching path, with none of those "
           "sentences, it reads the sentences it asked about."),
    hypothesis=("A reply that refuses instead of reading what it can; a telling not remembered; one of the four "
                "sentences inside the answering lesson; one of them unread or read to the wrong meaning after it; "
                "an untaught shape read whole; a reading that writes; or any write to the main store would each "
                "show here. The prose sample is measured, not checked."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main_store_rows() -> int:
    """Rows in the main model's store, counted over its own connection."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="lyric_db")
    try:
        n = 0
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') and table_type='BASE TABLE'"):
            n += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
        return n
    finally:
        await c.close()


async def main() -> int:
    main_before = await main_store_rows()
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "lyric_dev", f"connected to {where['d']}")
    if where["d"] != "lyric_dev":
        return 1
    import contextlib
    import io
    boot_log = io.StringIO()
    with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
        from core.main import get_system
        system = get_system()
        await system.start()
    check("the substrate is running", system.autonomous_coordinator is not None and system.running)
    try:
        return await _run(db, system.autonomous_coordinator, main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


async def _teach(path, learning):
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import LessonSource
    source = LessonSource(str(path))
    lesson = list(source.records())
    report = await TeachingPass(source, domain=DOMAIN, sample=False).run(learning)
    for line in report.lines():
        say_line(f"    {line}")
    return lesson, report


async def _talk(conversation, sentences):
    replies = []
    for sentence in sentences:
        understanding = await conversation.understand(sentence, look_up=False)
        reply = type(conversation).say(understanding)
        replies.append(reply)
        say_line(f"    you>   {sentence}")
        say_line(f"    lyric> {reply}".replace("\n", "\n           "))
    return replies


async def _remembered(db, sentence) -> int:
    row = await db.execute_query("SELECT count(*) AS n FROM memory_hot.memory_hot WHERE content LIKE $1",
                                 (f"%{sentence}%",), fetch_one=True)
    return int(row["n"])


async def _run(db, coord, main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.memory import get_memory_agent
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    learning = get_learning_authority()
    told = [sentence for sentence, _ in ASKED_ABOUT] + NEVER_TAUGHT[:1]

    say_line("== A. The first lesson, through the one teaching path ==")
    first, report = await _teach(FIRST, learning)
    check("the first lesson is learned, none refused",
          report.patterns.get("refused") == 0 and report.patterns.get("total") == len(first), f"{report.patterns}")

    say_line("\n== B. Told what it cannot read whole ==")
    before = {sentence: dr.read_text(sentence) for sentence in told}
    check("none of the four reads whole", not any(
        all(u.understood for u in before[s]) for s, _ in ASKED_ABOUT), "")
    conversation = coord.conversation("SHAPES-LEARN-04")
    replies = await _talk(conversation, told)
    check("every reply reads what it can and asks about the rest; none refuses",
          all("could not read" not in r and ("I understood" in r or "I don't know" in r or "I know these words" in r)
              for r in replies), "")
    asked_word = {"and": "and" in replies[0], "true": "true" in replies[3]}
    check("it asks about the word it does not know", all(asked_word.values()), f"{asked_word}")
    remembered = [await _remembered(db, s) for s in told]
    check("each is remembered as said", all(remembered), f"{remembered}")

    say_line("\n== C. The answers, by example ==")
    second, report = await _teach(SECOND, learning)
    check("the answering lesson is learned, none refused",
          report.patterns.get("refused") == 0 and report.patterns.get("total") == len(second), f"{report.patterns}")
    taught = {r.sentence for r in first + second}
    check("none of the four sentences is in either lesson", not any(s in taught for s, _ in ASKED_ABOUT), "")
    check("every answer is an example: nothing it states is held",
          report.meanings.get("example") == len(second)
          and sum(v for k, v in report.meanings.items() if k != "example") == 0, f"{report.meanings}")
    for name, runs in sorted((k[len("repair_"):], v) for k, v in report.patterns.items() if k.startswith("repair_")):
        EV.metric(f"answering lesson repair: {name}", runs)

    view = agent.pattern_inventory()
    size = len(view)
    say_line("\n== D. What it asked about, read again ==")
    right = 0
    for sentence, wanted in ASKED_ABOUT:
        utterances = dr.read_text(sentence)
        got = [u.readings[0].meaning.canonical() if u.readings else None for u in utterances]
        ok = got == [w.canonical() for w in wanted] and all(len({r.meaning.canonical() for r in u.readings}) == 1
                                                            for u in utterances)
        right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {sentence!r}\n          -> {got}")
    check("each of the four reads whole, to the meaning it has", right == len(ASKED_ABOUT),
          f"{right}/{len(ASKED_ABOUT)}")
    still = [s for s in NEVER_TAUGHT if all(u.understood for u in dr.read_text(s))]
    check("what neither lesson taught stays unread whole", not still, f"{still}")

    say_line("\n== E. Told again: what it says back, said as it was taught to say it ==")
    again = await _talk(conversation, [sentence for sentence, _ in ASKED_ABOUT])
    joined = " | ".join(again)
    check("what was noted is said with the sentences it was taught",
          "The door is open." in again[0] and "The window is closed." in again[0], again[0][:160])
    check("no reply speaks the store's own words or a template's",
          not any(bad in joined for bad in ("has property", "not has", " isa ", "is an open", "is a closed",
                                            "nothing said about it")), joined[:300])
    check('"he" in the same text points at the dog, which has no name here: nothing is held of anything else',
          "no name for yet" in again[1] and "window" not in again[1].lower() and "door" not in again[1].lower(),
          again[1][:200])
    check("a question is not recited back as a memory", "I remember: Is the stove" not in again[2], again[2][:160])

    say_line("\n== F. Real prose (NLU-01's 300 sentences) ==")
    sys.path.insert(0, str(ROOT / "experiments" / "nlu"))
    from _nlu_lib import real_prose
    prose = real_prose(limit=300)
    whole = pieces = read_whole = read_parts = 0
    for sentence in prose:
        utterances = dr.read_text(sentence, parts=True)
        whole += bool(utterances) and all(u.understood for u in utterances)
        for u in utterances:
            n = sum(1 for p in u.pieces if any(ch.isalnum() for ch in p.text))
            pieces += n
            if u.understood:
                read_whole += n
            else:
                read_parts += sum(1 for part in u.partial for p in part.pieces if any(ch.isalnum() for ch in p.text))
    say_line(f"    utterances read whole: {whole}/{len(prose)}; words read: {read_whole} in whole sentences and "
             f"{read_parts} in parts, of {pieces}")
    EV.metric("prose read whole", f"{whole}/{len(prose)}")
    EV.metric("prose words read in whole sentences", f"{read_whole}/{pieces}")
    EV.metric("prose words read in parts", f"{read_parts}/{pieces}")

    say_line("\n== G. Reading wrote nothing ==")
    check("the view is as teaching left it", len(agent.pattern_inventory()) == size,
          f"{size} -> {len(agent.pattern_inventory())}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-04 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    print(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main()))
