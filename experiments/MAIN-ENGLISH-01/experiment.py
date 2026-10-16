#!/usr/bin/env python3
"""MAIN-ENGLISH-01 — the main model after the English lessons were taught into it, read only.

ENGLISH_CURRICULUM.md has every phase taught whole on main and then main measured, read only, before the next. The
main store was emptied on 2026-10-04 and english_01-31 taught into it on 2026-10-05 (`scripts/teach.py --source
lesson`, `data/teaching_runs/main_english_01_31.log`): the first run. With Phase 1 built and passed on the sandbox
(ENGLISH-01), main was emptied again and english_01-39 taught into it (`data/teaching_runs/main_english_01_39.log`).
This reads, from main's own store:

  A  every sentence the lessons teach, each read with the meaning it was taught (checked: all of them);
  B  Phase 1's never-taught sentences (ENGLISH-01's `PHASE_1`), each mark in the uses its lesson teaches with words
     the lessons have, each read as written (checked, as on the sandbox);
  C  the 24 sentences FRESH-LESSON-01 to -03 wrote in shapes the lessons teach, with words no lesson has, each read
     as written there (measured: main holds none of those lessons' facts, so the words are new names here);
  D  main's store, counted before and after: the reading wrote nothing to what main knows. The profiler's timings of
     the substrate's own work (`unified.performance_logs`) are kept whenever it runs, and are noted.

A sentence is taken as ENGLISH-01 takes it: one meaning, or what its utterances say together where the reader reads
it as several ("Tom ran; Rex walked.").

Run (reads lyric_db, writes nothing to it):
    ./venv_lyric/bin/python3 experiments/MAIN-ENGLISH-01/experiment.py
"""
import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ["POSTGRES_DATABASE"] = "lyric_db"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_sense = _load("sense_01", ROOT / "experiments" / "SENSE-01" / "experiment.py")
_fresh = _load("fresh_lesson_01", ROOT / "experiments" / "FRESH-LESSON-01" / "experiment.py")
_english = _load("english_01", ROOT / "experiments" / "ENGLISH-01" / "experiment.py")

#: The lessons taught into main: Phase 0 (english_01-31) and Phase 1 (english_32-39).
LESSONS = [path for path in _fresh.LESSONS if path.name <= "english_31.json"] + [path for path, *_ in _english.PHASE_1]
FRESH = [ROOT / "experiments" / name / "experiment.py"
         for name in ("FRESH-LESSON-01", "FRESH-LESSON-02", "FRESH-LESSON-03")]
taken = _english.taken

EV = RunRecord("MAIN-ENGLISH-01",
               claim=("Taught english_01-39 through the one teaching path, the main model reads every sentence the "
                      "lessons teach with the meaning it was taught, and Phase 1's never-taught sentences as written, "
                      "from its own store."),
               hypothesis=("A taught sentence read otherwise or not at all, a never-taught Phase 1 sentence read "
                           "otherwise than written, or a write to the main store by the reading, shows here. "
                           "Sentences in taught shapes with words no lesson has are measured."))


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def taught() -> list:
    """`(lesson, sentence, canonical meaning)` for every record of the lessons taught into main."""
    from core.semantics.derived_reader import Meaning
    out = []
    for path in LESSONS:
        for record in json.loads(path.read_text())["records"]:
            out.append((path.name, record["sentence"], Meaning.from_dict(record["meaning"]).canonical()))
    return out


def never_taught() -> list:
    """`(experiment, sentence, canonical meaning)` for the fresh lessons' sentences in taught shapes."""
    from core.semantics.derived_reader import Meaning
    out = []
    for path in FRESH:
        material = _load(path.parent.name.lower().replace("-", "_"), path).MATERIAL
        out.extend((path.parent.name, sentence, _english.known_the.known(sentence, Meaning.from_dict(meaning)).canonical())
                   for sentence, meaning in material["in_taught_shapes"])
    return out


async def main() -> int:
    started = time.time()
    before = await _sense.main_store_rows()
    from core.database import get_database_manager
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics.derived_reader import Meaning
    manager = get_database_manager()
    await manager.initialize()
    await manager.assert_database_identity("lyric_db")
    await get_uncertainty_system().load_from_db()
    view = await (await get_memory_agent()).language_view()
    EV.metric("constructions and links in main's view", len(view))
    check("the reading is of the main store", await EV.verify_database() == "lyric_db",
          f"the server answered {EV.verified_database!r}")

    say("\n== A. Every sentence the lessons teach ==")
    rows = taught()
    wrong = []
    by_lesson = {}
    for lesson, sentence, meaning in rows:
        got = taken(sentence)
        right = got == meaning
        by_lesson.setdefault(lesson, [0, 0])[0] += right
        by_lesson[lesson][1] += 1
        if not right:
            wrong.append({"lesson": lesson, "sentence": sentence, "taught": meaning, "read": got})
    EV.metric("taught sentences read as taught, by lesson", {k: f"{a}/{b}" for k, (a, b) in by_lesson.items()})
    EV.metric("taught sentences read otherwise", wrong)
    for item in wrong[:20]:
        say(f"    {item['lesson']}: {item['sentence']!r} read {item['read']!r}")
    check(f"every sentence {LESSONS[0].stem}-{LESSONS[-1].stem[-2:]} teach is read as taught", not wrong,
          f"{len(rows) - len(wrong)} of {len(rows)}")

    say("\n== B. Phase 1's never-taught sentences ==")
    for path, mark, held_out in _english.PHASE_1:
        # Written before "the X" was a known thing (docs/TEACHING.md §12d), read as the lessons now write it.
        read = [(sentence, _english.known_the.known(sentence, Meaning.from_dict(meaning)).canonical(), taken(sentence))
                for sentence, meaning in held_out]
        off = [(sentence, got) for sentence, written, got in read if got != written]
        for sentence, got in off:
            say(f"    {sentence!r} read {got!r}")
        EV.metric(f"never taught, {mark}", [{"sentence": s, "written": w, "read": g} for s, w, g in read])
        check(f"never-taught sentences with {mark} read as written", not off, f"{len(read) - len(off)} of {len(read)}")

    say("\n== C. Sentences in taught shapes with words no lesson has (measured) ==")
    items = never_taught()
    read = [(where, sentence, meaning, taken(sentence)) for where, sentence, meaning in items]
    right = sum(1 for *_, meaning, got in read if got == meaning)
    for where, sentence, meaning, got in read:
        if got != meaning:
            say(f"    {where}: {sentence!r} read {got!r}")
    EV.metric("never-taught sentences in taught shapes read as written", f"{right}/{len(read)}")
    EV.metric("never-taught readings", [{"from": w, "sentence": s, "written": m, "read": g} for w, s, m, g in read])
    say(f"  {right} of {len(read)} read as written")

    after = await _sense.main_store_rows()
    # The profiler times the substrate's own work and keeps it (`performance_profiler._persist_metrics`), read back
    # after a restart and by the health monitor: running, the substrate records how its reading went. Every other
    # table holds what main knows, and the reading must leave it as it was.
    timings = {t for t in {*before, *after} if t.startswith("unified.performance_logs")}
    knowledge_before = {t: n for t, n in before.items() if t not in timings}
    knowledge_after = {t: n for t, n in after.items() if t not in timings}
    check("the reading wrote nothing to what main knows", knowledge_after == knowledge_before,
          _sense.main_store_change(knowledge_before, knowledge_after))
    EV.note("the profiler's timings of the reading: "
            + _sense.main_store_change({t: before.get(t, 0) for t in timings}, {t: after.get(t, 0) for t in timings}))
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n==== MAIN-ENGLISH-01: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
