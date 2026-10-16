#!/usr/bin/env python3
"""FRESH-LESSON-03 — FRESH-LESSON-01's checks, on a third lesson written after the fixes FRESH-LESSON-01 and -02 led
to, and frozen before this one's first run.

Those fixes were made against the first two lessons' own questions. This lesson has other words (one, "larth", ends
in -th and is taught in the plural, "Larths"), other facts, two other new shapes ("X is kept in Y", "X sleeps in Y")
and its own questions; every expected meaning and answer is written here before the run. The checks and the runner
are FRESH-LESSON-01's.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/FRESH-LESSON-03/experiment.py
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("fresh_lesson_01", ROOT / "experiments" / "FRESH-LESSON-01" / "experiment.py")
fresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fresh)
tell, ask = fresh.tell, fresh.ask

MATERIAL = dict(
    name="FRESH-LESSON-03",
    lesson=HERE / "lesson.json",
    contradiction=HERE / "contradiction.json",
    domain="fresh_lesson_03",
    contested="larth isa horse",
    new_words=["larth", "fosk", "brell", "jimp", "quib", "smeb", "gloth", "voth", "prenk", "dorv"],
    in_taught_shapes=[
        ("A brell is not a horse.", tell(("isa", "brell", "horse", False))),
        ("Is a fosk a flower?", ask([("isa", "fosk", "flower", True)])),
        ("What is a jimp?", ask([("isa", "jimp", "?x", True)], ["?x"])),
        ("Where is the jimp?", ask([("located_in", "jimp", "?x", True)], ["?x"])),
        ("Talo has a jimp.", tell(("owns", "talo", "jimp", True))),
        ("Fosks are heavy.", tell(("has_property", "fosk", "heavy", True))),
        ("The larth is near the chair.", tell(("near", "larth", "chair", True))),
        ("A jimp is not a flower.", tell(("isa", "jimp", "flower", False))),
    ],
    in_new_shapes={
        "is kept in": [
            ("A larth is kept in a school.", tell(("located_in", "larth", "school", True))),
            ("A fosk is kept in a box.", tell(("located_in", "fosk", "box", True))),
            ("A brell is kept in a room.", tell(("located_in", "brell", "room", True))),
        ],
        "sleeps in": [
            ("A larth sleeps in a box.", tell(("located_in", "larth", "box", True))),
            ("A fosk sleeps in a room.", tell(("located_in", "fosk", "room", True))),
            ("A quib sleeps in a school.", tell(("located_in", "quib", "school", True))),
        ],
    },
    questions=[
        ("What is a larth?", "says a larth is a horse", lambda r: "horse" in r),
        ("Is a larth a horse?", "yes", lambda r: r.startswith("yes")),
        ("Is a fosk a horse?", "no", lambda r: r.startswith("no")),
        ("Is a larth an animal?", "yes, and 'larth' in the plural is 'larths', as taught",
         lambda r: r.startswith("yes") and "larthes" not in r),
        ("Can a larth run?", "yes: horses can run", lambda r: r.startswith("yes")),
        ("Is a brell a plant?", "yes: a brell is a flower, a flower a plant", lambda r: r.startswith("yes")),
        ("What is a jimp made of?", "glass", lambda r: "glass" in r),
        ("Is Talo a person?", "yes: Talo is a teacher, a teacher a person", lambda r: r.startswith("yes")),
        ("Who owns the larth?", "Talo", lambda r: "talo" in r),
        ("Is the jimp behind the door?", "yes", lambda r: r.startswith("yes")),
        ("Is a larth red?", "not known: 'I do not know whether ...'", lambda r: r.startswith("i do not know")),
        ("Where is a quib kept?", "in a room (a question shape never taught)", lambda r: "room" in r),
        ("Where does a voth sleep?", "in a room (a question shape never taught)", lambda r: "room" in r),
    ],
    after_contradiction=("Is a larth a horse?", "still yes: the weaker source dents the belief, not the answer",
                         lambda r: r.startswith("yes")),
    claim=("Taught a third lesson no experiment has taught or tested, written after the first two lessons' fixes, Lyric "
           "holds every fact it states as a fact, a belief and a memory; reads sentences it was never taught, in "
           "shapes it had and in two it learned from three sentences each; answers questions from what was taught, "
           "including who holds a relation to a thing, writes a word's plural as it was taught, and says it does not "
           "know what was never stated; keeps it across a restart; does not grow surer from being told again; and "
           "answers a fact a weaker source denied as the belief in it stands, once."),
    hypothesis=("Any fact refused, missing from the graph or moving no belief; any sentence read otherwise than written "
                "here; a new shape read before it was taught or not read after; a wrong, made-up or crashed answer; a "
                "plural written otherwise than taught; a reading lost on restart; a belief moved by the same lesson "
                "again, or not moved by the contradiction; an answer turned, or contradicted, by the weaker source; or "
                "a write to the main store, each shows here."),
)


if __name__ == "__main__":
    sys.exit(asyncio.run(fresh.run(MATERIAL)))
