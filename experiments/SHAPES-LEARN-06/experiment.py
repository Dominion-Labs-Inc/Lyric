#!/usr/bin/env python3
"""SHAPES-LEARN-06 — it says what it holds with the sentences it was taught, and reads every kind it can say.

Step 5 of `docs/research/SHAPES_CHANGE_MAP.md` (§11d). The engine that reads is the one that speaks: a held fact is
said through a construction it was taught, never a template over a relation's label, and what it says reads back to
what it meant. A lesson for every link kind no lesson had taught (`data/lessons/english_04.json`) gives it the
sentences for them.

  A  TEACH      the four lessons (english_01 to english_04) through the one teaching path, none refused
  B  TAUGHT     every taught sentence of the four still reads to its meaning
  C  SAY        facts of the new kinds, never taught as such, are said, and each sentence reads back to exactly
                the meaning it was said for
  D  READ       sentences of those kinds never taught read to the meaning they have
  E  TALK       told a fact about a name it has never met, the conversation notes it as it was taught to say it,
                answers what it is for and whether it is with the fact said, and denies nothing it holds
  F  NOTHING    reading and saying wrote nothing
  G  MAIN       the main model's store is untouched

Runs in the SANDBOX (`torinai_dev`), emptied first by `scripts/reset_dev_store.py`. The conversation's fact is about
a nonce name and is removed by it; the four lessons are kept.

Run: ./venv_torin/bin/python3 experiments/SHAPES-LEARN-06/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from core.semantics.derived_reader import Meaning, MeaningFact as F  # noqa: E402

LESSONS = [ROOT / "data" / "lessons" / f"english_0{n}.json" for n in (1, 2, 3, 4)]
DOMAIN = "shapes_learn_06"
N = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
V = f"vex{N}"


def _fact(relation, subject, obj, positive=True):
    return Meaning("tell", (F(relation, subject, obj, positive),))


#: Facts of the kinds english_04 teaches, none of them a lesson's own sentence.
SAID = [_fact("used_for", "saw", "cutting"), _fact("requires", "bike", "air"), _fact("causes", "heat", "smoke"),
        _fact("eats", "goat", "grass"), _fact("contains", "bag", "pen"), _fact("produces", "bee", "milk"),
        _fact("member_of", "singer", "team"), _fact("owns", "boy", "car")]
#: Sentences of those kinds never taught, and what each means.
READ = [
    ("A saw is used for cutting.", _fact("used_for", "saw", "cutting")),
    ("A bike requires air.", _fact("requires", "bike", "air")),
    ("A goat eats grass.", _fact("eats", "goat", "grass")),
    ("The bag contains a pen.", _fact("contains", "bag", "pen")),
    ("Does a cat eat grass?", Meaning("ask", (F("eats", "cat", "grass"),))),
    ("What is a pen used for?", Meaning("ask", (F("used_for", "pen", "?x"),), ("?x",))),
    ("What causes pressure loss?", Meaning("ask", (F("causes", "?x", "pressure loss"),), ("?x",))),
]

EV = RunRecord(
    "SHAPES-LEARN-06",
    claim=("The engine that reads is the one that speaks: taught a sentence for every link kind, the substrate says "
           "facts of those kinds with the sentences it was taught, what it says reads back to what it meant, it "
           "reads sentences of those kinds never taught, and its conversation notes and answers with them."),
    hypothesis=("A lesson pair refused; a taught sentence that no longer reads; a fact not said, or said as a "
                "sentence reading back to another meaning; a probe unread or misread; a reply speaking the store's "
                "words or failing to say the fact; a reading or saying that writes; or a write to the main store "
                "would each show here."))
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
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="torinai_db")
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
    check("the run is in the sandbox", where["d"] == "torinai_dev", f"connected to {where['d']}")
    if where["d"] != "torinai_dev":
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
        say_line(f"    torin> {reply}".replace("\n", "\n           "))
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

    say_line("== A. The four lessons, through the one teaching path ==")
    taught = []
    for path in LESSONS:
        lesson, report = await _teach(path, learning)
        taught.extend(lesson)
        check(f"{path.name} is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
              f"{report.patterns}")
    view = agent.pattern_inventory()
    size = len(view)

    say_line("\n== B. Every taught sentence still reads to its meaning ==")
    unread = [r.sentence for r in taught
              if not [x for x in dr.read(r.sentence) if x.meaning.canonical() == r.meaning.canonical()][:1]]
    check("every taught sentence of the four lessons reads to its meaning", not unread, f"{unread[:5]}")

    say_line("\n== C. Saying facts of the new kinds ==")
    said_right = 0
    for meaning in SAID:
        said = dr.say(meaning)
        back = [r.meaning.canonical() for r in dr.read(said[0])] if said else []
        ok = bool(said) and back == [meaning.canonical()]
        said_right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {meaning.canonical()} -> {said[:1]}")
    check("each is said, and what is said reads back to exactly what it meant", said_right == len(SAID),
          f"{said_right}/{len(SAID)}")

    say_line("\n== D. Reading sentences of those kinds never taught ==")
    read_right = 0
    for sentence, wanted in READ:
        got = [u.readings[0].meaning.canonical() if u.readings else None for u in dr.read_text(sentence)]
        ok = got == [wanted.canonical()]
        read_right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {sentence!r} -> {got}")
    check("each reads whole, to the meaning it has", read_right == len(READ), f"{read_right}/{len(READ)}")

    say_line("\n== E. A conversation about a name it has never met ==")
    conversation = coord.conversation(f"SHAPES-LEARN-06-{N}")
    replies = await _talk(conversation, [f"A {V} is used for cutting.", f"What is a {V} used for?",
                                         f"Is a {V} used for cutting?", f"Is a {V} used for writing?"])
    fact = f"A {V} is used for cutting."
    check("what it was told is noted as it was taught to say it", fact in replies[0], replies[0][:160])
    check("asked what it is for, it says the fact", fact in replies[1], replies[1][:160])
    check("asked whether it is, it says yes and the fact", replies[2].startswith("Yes.") and fact in replies[2],
          replies[2][:160])
    check("asked about what it was never told, it does not say yes", not replies[3].lower().startswith("yes"),
          replies[3][:160])
    joined = " | ".join(replies)
    check("no reply speaks the store's own words", not any(bad in joined for bad in ("used_for", "used for a "
                                                                                      "cutting", " isa ")),
          joined[:300])

    say_line("\n== F. Reading and saying wrote nothing ==")
    check("the view is as teaching left it", len(agent.pattern_inventory()) == size,
          f"{size} -> {len(agent.pattern_inventory())}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    await _clean(db, [conversation._actor])
    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-06 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


async def _clean(db, actors):
    """Everything named by this run's nonce, or scoped to its speaker."""
    like = f"%{N}%"
    concepts = [r["concept_id"] for r in await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE name ILIKE $1", (like,), fetch_all=True) or []]
    if concepts:
        await db.execute_query("DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
                               "OR target_concept_id = ANY($1::text[])", (concepts,))
        for table in ("concept_domains", "concept_evidence", "concept_aliases"):
            await db.execute_query(f"DELETE FROM unified.{table} WHERE concept_id = ANY($1::text[])", (concepts,))
        await db.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])", (concepts,))
    for table, column in (("unified.beliefs", "claim"), ("unified.experience_pool", "parts::text"),
                          ("memory_hot.memory_hot", "content")):
        await db.execute_query(f"DELETE FROM {table} WHERE {column} ILIKE $1", (like,))
    for table in ("scoped_beliefs", "scoped_concept_relations"):
        await db.execute_query(f"DELETE FROM unified.{table} WHERE scope_actor = ANY($1::text[])", (actors,))
    left = await db.execute_query(
        "SELECT (SELECT count(*) FROM unified.concepts WHERE name ILIKE $1) + "
        "(SELECT count(*) FROM memory_hot.memory_hot WHERE content ILIKE $1) AS n", (like,), fetch_one=True)
    EV.note(f"Cleanup by nonce {N}: {len(concepts)} concepts; {left['n']} left.")


if __name__ == "__main__":
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    print(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main()))
