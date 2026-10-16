#!/usr/bin/env python3
"""QUESTION-FORMS-01 — questions with "does", "do" and a word left at the end, taught (english_31), asked of things
no lesson named.

FRESH-LESSON-01 to -03 found that a statement shape learned from a lesson ("A snorf lives in a house.") does not bring
its question ("Where does a snorf live?"), and that no lesson had taught such a question at all: of the 2,636
sentences of english_01-30, none asks "Where does ...?", "Who does ... belong to?" or "Where is ... kept?". english_31
teaches 14 of them, each beside the sentence that tells what it asks. Here, on the emptied sandbox, the 31 lessons are
taught, then a lesson of facts with new words, and questions are asked through the conversation:

  A  in shapes english_31 asks about (lives in, belongs to, is kept in, comes from, sleep in), of new words: each is
     read and answered from the facts;
  B  in shapes no lesson asks about (hides in, grows in, rests in): measured, whether a question form taught with
     some verbs carries to another.
  C  the main model is untouched, checked where main was still (when it is taught alongside, its move is
     noted).

Every expected answer is written here before the run.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/QUESTION-FORMS-01/experiment.py
"""
import asyncio
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("fresh_lesson_01", ROOT / "experiments" / "FRESH-LESSON-01" / "experiment.py")
fresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fresh)

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

#: The lessons QUESTION-FORMS-01 and -02 were written with: english_01-31. Later lessons are not theirs.
WITH = [path for path in fresh.LESSONS if path.name <= "english_31.json"]

TAUGHT_SHAPES = [
    ("Where does a fip live?", "in a kitchen", lambda r: "kitchen" in r),
    ("Who does the plonk belong to?", "Nella", lambda r: "nella" in r),
    ("Where is the trel kept?", "in a bag", lambda r: "bag" in r),
    ("Where does a snell come from?", "a city", lambda r: "city" in r),
    ("Where do brabs sleep?", "in boxes", lambda r: "box" in r),
]
UNTAUGHT_SHAPES = [
    ("Where does a kelt hide?", "in a box", lambda r: "box" in r),
    ("Where does a morp grow?", "in a city", lambda r: "city" in r),
    ("Where does the blip rest?", "in the bag", lambda r: "bag" in r),
]


async def run(material) -> int:
    """The lessons, `material`'s facts, then its questions: each group checked (`gated`) or measured."""
    EV = RunRecord(material["name"], claim=material["claim"], hypothesis=material["hypothesis"])
    DOMAIN = material["domain"]
    fresh.EV = EV
    check = fresh.check
    started = time.time()
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")], capture_output=True,
                           text=True, cwd=str(ROOT))
    main_before = await fresh._sense.main_store_rows()
    system, coord = await boot()
    d = db()
    where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox, emptied first", where["d"] == "lyric_dev" and reset.returncode == 0,
          f"connected to {where['d']}; reset exit {reset.returncode}")
    try:
        refused = {}
        for path in WITH:
            report, total = await fresh.teach(path, path.name, DOMAIN)
            if report.patterns.get("refused") or report.patterns.get("total") != total:
                refused[path.name] = report.patterns
        check(f"the {len(WITH)} lessons are learned, none refused", not refused,
              f"{refused}" if refused else f"{WITH[-1].name} the last")
        report, total = await fresh.teach(material["lesson"], "the facts", DOMAIN)
        check("the facts are learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == total, f"{report.patterns}")
        conversation = coord.conversation(material["name"])
        answers = []
        for group, questions, gate in material["groups"]:
            right = 0
            for question, expected, test in questions:
                reply = await fresh.asking(conversation, question)
                answers.append({"asked": question, "reply": reply, "shapes": group})
                ok = test(reply.strip().lower())
                right += ok
                fresh.say(f"    > {question}\n    < {reply}")
                if gate:
                    check(f"{question!r}: {expected}", ok, reply[:160])
            EV.metric(f"{group}: answered right", f"{right}/{len(questions)}")
        EV.metric("answers", answers)
    finally:
        await shutdown(system)
    main_after = await fresh._sense.main_store_rows()
    if main_after == main_before:
        check("the main model's store is untouched", True, fresh._sense.main_store_change(main_before, main_after))
    else:
        # Not a check: the main model may be taught by its own process while this runs, so a change cannot be put
        # down to this run (as ENGLISH-01). Recorded, for whoever reads the record to tell whose write it was.
        EV.note("the main model's store moved during the run (it may have been taught alongside): "
                + fresh._sense.main_store_change(main_before, main_after))
        fresh.say("  main moved during the run; recorded as a note, not a check")
    passed = sum(1 for c in EV.checks if c.passed)
    fresh.say(f"\n==== {material['name']}: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    await EV.verify_database()
    fresh.say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


MATERIAL = dict(
    name="QUESTION-FORMS-01", lesson=HERE / "lesson.json", domain="question_forms_01",
    groups=[("shapes english_31 asks about", TAUGHT_SHAPES, True),
            ("shapes no lesson asks about", UNTAUGHT_SHAPES, False)],
    claim=("Taught questions with 'does', 'do' and a word left at the end beside the sentences they ask about "
           "(english_31), Lyric reads and answers such questions about new words in those shapes."),
    hypothesis=("A question in a shape english_31 teaches, about a new word, read otherwise or answered wrongly, or a "
                "write to the main store, shows here. Whether the forms carry to verbs no lesson asks about is "
                "measured, not assumed."))


if __name__ == "__main__":
    sys.exit(asyncio.run(run(MATERIAL)))
