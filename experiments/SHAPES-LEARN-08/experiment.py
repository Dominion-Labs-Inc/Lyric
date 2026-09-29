#!/usr/bin/env python3
"""SHAPES-LEARN-08 — WordNet's nouns, taught through the one teaching path and said by the substrate itself.

Part 3 of the last step in `docs/research/SHAPES_CHANGE_MAP.md` (§11f), on a sample. A WordNet record carries what
is so (`isa(child, parent)`) and the words WordNet writes each sense with; the substrate says it through the frames
it was taught (`TeachingPass._said`), so no sentence is written from a template, and each pair teaches the word, its
kind and its fact. A named thing ("Paris") is taught as a fact only: no frame taught yet says a name.

  A  TEACH      the five lessons, then a uniform sample of WordNet's records, through the one teaching path
  B  SAID       the nouns' facts said through the frames taught, in WordNet's words; none refused
  C  WORDS      every noun taught reads in a question never taught ("What is an ocelot?") to the sense taught
  D  FACTS      the facts taught are held: the reasoning authority answers yes; for pairs WordNet does not relate, no
  E  SAY        facts taught are said, and what is said reads back to them
  F  TAUGHT     every sentence of the five lessons still reads to its meaning
  G  COST       seconds per record, and what all of WordNet's records would take (measured)
  H  MAIN       the main model's store is untouched

Runs in the SANDBOX (`torinai_dev`), emptied first by `scripts/reset_dev_store.py`; the lessons and the sample are
kept.

Run: ./venv_torin/bin/python3 experiments/SHAPES-LEARN-08/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import random
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

LESSONS = [ROOT / "data" / "lessons" / f"english_0{n}.json" for n in (1, 2, 3, 4, 5)]
DOMAIN = "shapes_learn_08"
SAMPLE = 3000
SEED = 20260929

EV = RunRecord(
    "SHAPES-LEARN-08",
    claim=("Taught WordNet's nouns through its one teaching path, the substrate says each fact through the frames it "
           "was taught, in WordNet's words, and learns from what it said: every noun taught reads in a question it "
           "was never taught, the facts are held, and what it says of them reads back to them."),
    hypothesis=("A pair refused; a noun taught that a question never taught does not read to its sense; a fact taught "
                "that is not held, or a pair WordNet does not relate answered yes; a fact said that reads back to "
                "another meaning; a lesson sentence that no longer reads; or a write to the main store would each "
                "show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


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
        return await _run(db, main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


def _meanings(sentence):
    from core.semantics import derived_reader as dr
    return [{r.meaning.canonical() for r in u.readings} for u in dr.read_text(sentence)]


async def _run(db, main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.learning.teaching import Report, TeachingPass
    from core.learning.teaching_sources import LessonSource, WordNetSource
    from core.memory import get_memory_agent
    from core.reasoning.concept_graph_reasoning import answer_over_graph
    from core.reasoning.relation_algebra import TRUE
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import Meaning, MeaningFact
    from core.semantics.relation_types import SemanticRelation
    agent = await get_memory_agent()
    learning = get_learning_authority()

    say_line("== A. The five lessons, then WordNet, through the one teaching path ==")
    taught = []
    for path in LESSONS:
        source = LessonSource(str(path))
        lesson = list(source.records())
        report = await TeachingPass(source, domain=DOMAIN, sample=False).run(learning)
        taught.extend(lesson)
        check(f"{path.name} is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
              f"{report.patterns}")
    wordnet = TeachingPass(WordNetSource(), domain=DOMAIN, limit=SAMPLE, sample=True, seed=SEED)
    harvest = wordnet._harvest(Report(source="wordnet", domain=DOMAIN))
    nouns = [r for r in harvest if r.meaning is not None]
    names = [r for r in harvest if r.meaning is None and r.subject]
    glosses = [r for r in harvest if not r.subject]
    say_line(f"    the sample: {len(harvest)} records -- {len(nouns)} nouns' facts, {len(names)} named things' facts, "
             f"{len(glosses)} definitions")
    # What the pass will say, with the view as the pass finds it (its own pairs are learned after all are said).
    spoken = [(r, TeachingPass._said(r)) for r in nouns]
    report = await wordnet.run(learning)
    for line in report.lines():
        say_line(f"    {line}")

    say_line("\n== B. Said through the frames taught ==")
    said = report.meanings.get("said", 0)
    check("the nouns' facts are said through the frames taught, in WordNet's words",
          said + report.meanings.get("not_said", 0) == len(nouns) and said == sum(1 for _, s in spoken if s)
          and said >= 0.9 * len(nouns), f"said {said} of {len(nouns)}; {report.meanings}")
    check("no pair said is refused", report.patterns.get("refused") == 0, f"{report.patterns}")
    EV.metric("nouns said", f"{said}/{len(nouns)}")

    say_line("\n== C. Every noun taught, in a question never taught ==")
    view = agent.pattern_inventory()
    words_read, missed = 0, []
    asked = 0
    for record, sentence in spoken:
        if not sentence:
            continue
        word = dict(record.words).get(record.subject, record.subject)
        article = view.shape_before("a", word[:1]) if word[:1].isalpha() else "a"
        question = f"What is {article} {word}?"
        wanted = Meaning("ask", (MeaningFact("isa", record.subject, "?x"),), ("?x",)).canonical()
        got = _meanings(question)
        asked += 1
        if len(got) == 1 and wanted in got[0]:
            words_read += 1
        elif len(missed) < 12:
            missed.append((question, [sorted(g) for g in got]))
    for question, got in missed:
        say_line(f"    unread or misread: {question!r} -> {got}")
    check("every noun taught reads in a question never taught, to the sense taught", words_read == asked,
          f"{words_read}/{asked}")
    EV.metric("nouns taught that read in a question never taught", f"{words_read}/{asked}")

    say_line("\n== D. The facts are held ==")
    rng = random.Random(SEED)
    facts = [r for r in nouns + names if r.subject and r.obj]
    probed = rng.sample(facts, min(200, len(facts)))
    held = 0
    for record in probed:
        answer = await answer_over_graph(db, record.subject, SemanticRelation.ISA, record.obj, max_hops=4)
        held += answer.verdict == TRUE
    check("the reasoning authority answers yes to the facts taught", held == len(probed), f"{held}/{len(probed)}")
    related = {(r.subject, r.obj) for r in facts}
    subjects = [r.subject for r in facts]
    objects = [r.obj for r in facts]
    controls, guard = [], 0
    while len(controls) < 200 and guard < 20000:
        guard += 1
        s, o = rng.choice(subjects), rng.choice(objects)
        if s != o and (s, o) not in related:
            controls.append((s, o))
    invented = 0
    for s, o in controls:
        answer = await answer_over_graph(db, s, SemanticRelation.ISA, o, max_hops=4)
        invented += answer.verdict == TRUE
    check("for pairs WordNet does not relate it does not answer yes", invented == 0,
          f"{invented}/{len(controls)} answered yes")
    EV.metric("facts held", f"{held}/{len(probed)}")
    EV.metric("unrelated pairs answered yes", f"{invented}/{len(controls)}")

    say_line("\n== E. Facts taught, said back ==")
    back, shown = 0, 0
    for record, _ in [(r, s) for r, s in spoken if s][:200]:
        sentences = dr.say(record.meaning)
        ok = bool(sentences) and any(record.meaning.canonical() in got for got in _meanings(sentences[0]))
        back += ok
        if shown < 8:
            say_line(f"    {'ok ' if ok else 'BAD'} {record.meaning.canonical()} -> {sentences[:1]}")
            shown += 1
    total = min(200, sum(1 for _, s in spoken if s))
    check("each fact taught is said, and what is said reads back to it", back == total, f"{back}/{total}")

    say_line("\n== F. The lessons still read ==")
    unread = [r.sentence for r in taught
              if not [x for x in dr.read(r.sentence) if x.meaning.canonical() == r.meaning.canonical()][:1]]
    check("every taught sentence of the five lessons reads to its meaning", not unread, f"{unread[:5]}")

    say_line("\n== G. The cost ==")
    per_record = report.seconds / max(1, len(harvest))
    offered = sum(1 for _ in WordNetSource().records())
    say_line(f"    {report.seconds:.1f} s for {len(harvest)} records: {per_record * 1000:.0f} ms each; all "
             f"{offered:,} of WordNet's records would take about {per_record * offered / 3600:.1f} h at this rate")
    EV.metric("seconds per WordNet record", round(per_record, 4))
    EV.metric("hours for all of WordNet's records, at this rate", round(per_record * offered / 3600, 2))

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-08 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
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
