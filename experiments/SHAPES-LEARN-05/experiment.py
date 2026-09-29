#!/usr/bin/env python3
"""SHAPES-LEARN-05 — phrases in slots: a thing said with the words around it, read in every frame of its kind.

Part 2 of step 3b in `docs/research/SHAPES_CHANGE_MAP.md` (§11c). A slot holds a phrase as well as a word: a phrase
names a thing and may say more about it ("my small red cup", "the book on the table", "the teacher's hat"). Phrases
are learned from taught pairs by the same repairs as sentences (item-based → phrase), and a phrase learned in one
slot is read in every slot of its kind, nested in other phrases.

  A  TEACH      the three lessons (`data/lessons/english_01.json`, `english_02.json`, `english_03.json`) through
                the one teaching path; none refused; the third learns phrases
  B  TAUGHT     every taught sentence of all three still reads to its meaning
  C  PROBES     noun phrases never taught read to the meaning they have: other words in a learned phrase, phrases
                inside phrases, phrases in frames they were never taught in
  D  UNTAUGHT   shapes no lesson taught stay unread whole
  E  PROSE      NLU-01's 300 sentences: utterances read whole, and words read whole or in parts (measured)
  F  NOTHING    reading wrote nothing
  G  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`. What it leaves is kept: the three
lessons.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-05/experiment.py
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

LESSONS = [ROOT / "data" / "lessons" / f"english_0{n}.json" for n in (1, 2, 3)]
DOMAIN = "shapes_learn_05"


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


#: Noun phrases no lesson taught, and what each means.
PROBES = [
    ("This is my big blue ball.", _m("tell", "instance_of ?shown ball", "owned_by ?shown ?speaker",
                                     "has_property ?shown big", "has_property ?shown blue")),
    ("The small box is closed.", _m("tell", "instance_of ?x box", "has_property ?x small", "has_property ?x closed")),
    ("The cup on the table is hot.", _m("tell", "instance_of ?x cup", "located_at ?x table", "has_property ?x hot")),
    ("The teacher's sock is blue.", _m("tell", "instance_of ?x sock", "owned_by ?x teacher", "has_property ?x blue")),
    ("Tie your small red sock.", _m("request", "instance_of ?e tying", "done_by ?e ?listener", "done_to ?e ?x",
                                    "instance_of ?x sock", "owned_by ?x ?listener", "has_property ?x small",
                                    "has_property ?x red")),
    ("Is the small cup hot?", _m("ask", "instance_of ?x cup", "has_property ?x small", "has_property ?x hot")),
    ("Where is the big box?", _m("ask", "instance_of ?x box", "has_property ?x big", "located_in ?x ?y",
                                 asked=("?y",))),
    ("My big red hat is cold.", _m("tell", "instance_of ?x hat", "owned_by ?x ?speaker", "has_property ?x big",
                                   "has_property ?x red", "has_property ?x cold")),
    ("The pen on the chair is big.", _m("tell", "instance_of ?x pen", "located_at ?x chair", "has_property ?x big")),
]
#: Shapes no lesson taught, which must not read whole.
NEVER_TAUGHT = ["the the the", "The cup that is on the table is hot.", "Red, blue, and green are colors!"]

EV = RunRecord(
    "SHAPES-LEARN-05",
    claim=("A slot holds a phrase as well as a word. Taught noun phrases by example through its one teaching path, "
           "the substrate reads noun phrases it was never taught -- other words in a learned phrase, phrases inside "
           "phrases, phrases in frames they were never taught in -- to the meaning they have, and every sentence it "
           "was taught before still reads."),
    hypothesis=("A lesson pair refused; a taught sentence that no longer reads; a probe unread or read to the wrong "
                "meaning; an untaught shape read whole; a reading that writes; or any write to the main store would "
                "each show here. The prose sample is measured, not checked."))

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

    say_line("== A. The three lessons, through the one teaching path ==")
    taught = []
    phrase_repairs = 0
    for path in LESSONS:
        lesson, report = await _teach(path, learning)
        taught.extend(lesson)
        check(f"{path.name} is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
              f"{report.patterns}")
        phrase_repairs += report.patterns.get("repair_phrase_in_slot", 0)
    view = agent.pattern_inventory()
    counted = {"holophrase": len(view.holophrases()), "item_based": len(view.item_based()),
               "phrase": len(view.phrases()), "lexical": len(view.lexicals()), "link": len(view.links())}
    say_line(f"    the view holds {counted}")
    check("phrases were learned, by the phrase repair", phrase_repairs > 0 and counted["phrase"] > 0,
          f"{phrase_repairs} repairs, {counted['phrase']} phrases")
    for name, value in counted.items():
        EV.metric(f"constructions: {name}", value)

    say_line("\n== B. Every taught sentence still reads to its meaning ==")
    unread = [r.sentence for r in taught
              if not [x for x in dr.read(r.sentence) if x.meaning.canonical() == r.meaning.canonical()][:1]]
    check("every taught sentence of the three lessons reads to its meaning", not unread, f"{unread[:5]}")

    size = len(view)
    say_line("\n== C. Noun phrases never taught ==")
    right = 0
    for sentence, wanted in PROBES:
        utterances = dr.read_text(sentence)
        got = [u.readings[0].meaning.canonical() if u.readings else None for u in utterances]
        ok = got == [wanted.canonical()]
        right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {sentence!r}\n          -> {got}")
    check("each reads whole, to the meaning it has", right == len(PROBES), f"{right}/{len(PROBES)}")
    EV.metric("noun-phrase probes read as they mean", f"{right}/{len(PROBES)}")

    say_line("\n== D. What no lesson taught ==")
    still = [s for s in NEVER_TAUGHT if all(u.understood for u in dr.read_text(s))]
    check("shapes no lesson taught stay unread whole", not still, f"{still}")

    say_line("\n== E. Real prose (NLU-01's 300 sentences) ==")
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

    say_line("\n== F. Reading wrote nothing ==")
    check("the view is as teaching left it", len(agent.pattern_inventory()) == size,
          f"{size} -> {len(agent.pattern_inventory())}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-05 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
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
