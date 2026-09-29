#!/usr/bin/env python3
"""SHAPES-LEARN-07 — word shapes: a word written another way is read as the word it is, and said in the slot's shape.

Step 4 of `docs/research/SHAPES_CHANGE_MAP.md` (§11e). The changes at a word's end ("Dogs" → `dog`, "Flies" → `fly`,
"Foxes" → `fox`) are found from the fillers held, each in its context of letters, scored as Albright & Hayes score
theirs and applied to words never seen in that shape while within Yang's tolerance threshold. An apostrophe inside a
word begins a piece of its own, so possessives and contractions are learned once, over every word. A lesson of
plurals, possessives and contractions (`data/lessons/english_05.json`) is taught after the four before it.

  A  TEACH      the five lessons (english_01 to english_05) through the one teaching path, none refused
  B  TAUGHT     every taught sentence of the five still reads to its meaning
  C  SHAPES     the shapes found: the plural endings are productive, each in its context; an irregular form is not
  D  READ       plurals, possessives and contractions never taught read whole, to the meaning they have
  E  NEW        words never met stand one to a slot in a frame with a word of its own; a run of them does not
  F  SAY        a concept held only as a singular is said in a plural slot in that slot's shape, and every sentence
                said reads back to exactly what it meant
  G  UNREAD     shapes no lesson taught stay unread whole
  H  PROSE      NLU-01's 300 sentences: utterances read whole, and words read whole or in parts (measured)
  I  NOTHING    reading and saying wrote nothing
  J  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`; the five lessons are kept.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-07/experiment.py
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

LESSONS = [ROOT / "data" / "lessons" / f"english_0{n}.json" for n in (1, 2, 3, 4, 5)]
DOMAIN = "shapes_learn_07"


def _tell(*facts):
    return Meaning("tell", tuple(F(*f) for f in facts))


def _ask(facts, asked=()):
    return Meaning("ask", tuple(F(*f) for f in facts), tuple(asked))


#: Sentences never taught, and what each means: plurals of words held only as they are named (or held in no plural
#: that ending makes), possessives over owners never taught with one, contractions in sentences never taught, and a
#: concept's own name where only a shaped form of it is held.
READ = [
    ("Cups are red.", _tell(("has_property", "cup", "red"))),
    ("Churches are big.", _tell(("has_property", "church", "big"))),
    ("Pennies are small.", _tell(("has_property", "penny", "small"))),
    ("Horses are tall.", _tell(("has_property", "horse", "tall"))),
    ("Foxes are red.", _tell(("has_property", "fox", "red"))),
    ("Glasses are big.", _tell(("has_property", "glass", "big"))),
    ("Dishes are small.", _tell(("has_property", "dish", "small"))),
    ("Can horses swim?", _ask([("capable_of", "horse", "swim")])),
    ("The fox is red.", _tell(("has_property", "fox", "red"))),
    ("The boy's cup is red.", _tell(("instance_of", "?x", "cup"), ("owned_by", "?x", "boy"),
                                    ("has_property", "?x", "red"))),
    ("The teacher's ball is blue.", _tell(("instance_of", "?x", "ball"), ("owned_by", "?x", "teacher"),
                                          ("has_property", "?x", "blue"))),
    ("It's green.", _tell(("has_property", "?previous", "green"))),
    ("The window isn't open.", _tell(("has_property", "window", "open", False))),
    ("A robin isn't a fish.", _tell(("isa", "robin", "fish", False))),
    ("Birds can't swim.", _tell(("capable_of", "bird", "swim", False))),
    ("I'm nice.", _tell(("has_property", "?speaker", "nice"))),
    ("They're green.", _tell(("has_property", "?previous", "green"))),
    ("Where's the cup?", _ask([("located_in", "cup", "?x")], ["?x"])),
    ("What's an eagle?", _ask([("isa", "eagle", "?x")], ["?x"])),
]

#: Facts about concepts held only as they are named, and the plural each takes in the plural slot.
SAID = [
    (_tell(("has_property", "church", "big")), "Churches are big."),
    (_tell(("has_property", "penny", "small")), "Pennies are small."),
    (_tell(("has_property", "fox", "red")), "Foxes are red."),
    (_tell(("has_property", "bus", "red")), "Buses are red."),
    (_tell(("has_property", "glass", "big")), "Glasses are big."),
    (_tell(("has_property", "horse", "big")), "Horses are big."),
    (_tell(("has_property", "cup", "red")), "Cups are red."),
    (_tell(("capable_of", "horse", "swim")), "Horses can swim."),
]

#: What no lesson taught, whole: a run of words that is no sentence, a clause inside a phrase, a list, and a run of
#: words never met standing in one slot.
NEVER_TAUGHT = ["the the the", "The cup that is on the table is hot.", "Red, blue, and green are colors!",
                "Its queues are now built without persistence."]

EV = RunRecord(
    "SHAPES-LEARN-07",
    claim=("Word shapes are learned from the fillers held, never told: taught plurals, possessives and contractions "
           "by example through its one teaching path, the substrate reads a word written in a learned shape as the "
           "word it is, reads possessives and contractions it was never taught, says a concept in the shape its slot "
           "takes, and every sentence it says reads back to what it meant."),
    hypothesis=("A lesson pair refused; a taught sentence that no longer reads; a plural ending not found, or an "
                "irregular form taken for a shape; a probe unread or misread; a plural said in a shape it does not "
                "take, or a sentence said that reads back to another meaning; a shape never taught read whole; a "
                "reading or saying that writes; or a write to the main store would each show here."))
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
        return await _run(main_before)
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


def _meanings(sentence):
    from core.semantics import derived_reader as dr
    return [u.readings[0].meaning.canonical() if u.readings else None for u in dr.read_text(sentence)]


async def _run(main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.memory import get_memory_agent
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    learning = get_learning_authority()

    say_line("== A. The five lessons, through the one teaching path ==")
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
    check("every taught sentence of the five lessons reads to its meaning", not unread, f"{unread[:5]}")

    say_line("\n== C. The shapes found from the fillers ==")
    shapes = view.word_shapes()
    productive = sorted((change for change in shapes if view.productive(change)),
                        key=lambda change: (-shapes[change][0], change))
    for change in productive:
        right, covered = shapes[change]
        say_line(f"    {change[0]!r:>8} -> {change[1]!r:<6} reads {right} of the {covered} words it applies to")
    EV.metric("productive shapes", len(productive))
    EV.metric("shapes", {f"{w}->{n}": list(shapes[(w, n)]) for w, n in productive})
    plural = {("s", ""), ("ies", "y"), ("xes", "x"), ("ches", "ch"), ("sses", "ss"), ("ys", "y")}
    check("the plural endings are productive, each in its context", plural <= set(productive),
          f"missing {sorted(plural - set(productive))}")
    irregular = [("mice", "mouse"), ("children", "child"), ("men", "man"), ("teeth", "tooth"), ("geese", "goose")]
    taken = [pair for pair in irregular if view.written_in_shape(*pair)]
    check("an irregular form is a word of its own, not a shape", not taken, f"{taken}")

    say_line("\n== D. Plurals, possessives and contractions never taught ==")
    read_right = 0
    for sentence, wanted in READ:
        got = _meanings(sentence)
        ok = got == [wanted.canonical()]
        read_right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {sentence!r} -> {got}")
    check("each reads whole, to the meaning it has", read_right == len(READ), f"{read_right}/{len(READ)}")
    EV.metric("never-taught probes read as they mean", f"{read_right}/{len(READ)}")

    say_line("\n== E. Words never met ==")
    (rain,) = dr.read_text("Rain causes floods.")
    new = sorted(lx.value for lx in rain.readings[0].new) if rain.readings else []
    say_line(f"    'Rain causes floods.' -> {[r.meaning.canonical() for r in rain.readings[:1]]}, new: {new}")
    check("two words never met stand one to a slot in a frame with one word of its own",
          rain.understood and new == ["Rain", "floods"] and rain.readings[0].meaning.facts[0].relation == "causes",
          f"{new}")

    say_line("\n== F. Saying in the slot's shape ==")
    said_right = 0
    for meaning, plural_sentence in SAID:
        said = dr.say(meaning)
        back = {sentence: _meanings(sentence) for sentence in said}
        wrong = [sentence for sentence, got in back.items() if got != [meaning.canonical()]]
        ok = plural_sentence in said and not wrong
        said_right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {meaning.canonical()} -> {list(said)}"
                 + (f"; reads back otherwise: {wrong}" if wrong else ""))
    check("each is said in the plural slot's shape, and everything said reads back to what it meant",
          said_right == len(SAID), f"{said_right}/{len(SAID)}")
    EV.metric("facts said in the slot's shape, reading back", f"{said_right}/{len(SAID)}")

    say_line("\n== G. What no lesson taught ==")
    still = [s for s in NEVER_TAUGHT if all(u.understood for u in dr.read_text(s))]
    check("shapes no lesson taught stay unread whole", not still, f"{still}")

    say_line("\n== H. Real prose (NLU-01's 300 sentences) ==")
    sys.path.insert(0, str(ROOT / "experiments" / "nlu"))
    from _nlu_lib import real_prose
    prose = real_prose(limit=300)
    whole = pieces = read_whole = read_parts = 0
    for sentence in prose:
        utterances = dr.read_text(sentence, parts=True)
        if utterances and all(u.understood for u in utterances):
            whole += 1
            say_line(f"    whole: {sentence!r} -> {[u.readings[0].meaning.canonical() for u in utterances]}")
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

    say_line("\n== I. Reading and saying wrote nothing ==")
    check("the view is as teaching left it", len(agent.pattern_inventory()) == size,
          f"{size} -> {len(agent.pattern_inventory())}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-07 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
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
