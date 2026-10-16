#!/usr/bin/env python3
"""FRESH-LESSON-02 — FRESH-LESSON-01's checks, on a second lesson written after FRESH-LESSON-01's first run and the
fixes it led to, and frozen before this one's first run.

The fixes were made against FRESH-LESSON-01's own questions, so passing it again shows little. This lesson has other
words, other facts and two other new shapes ("X is found in Y", "X comes from Y"), and asks its own questions; every
expected meaning and answer is written here before the run. The checks and the runner are FRESH-LESSON-01's.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/FRESH-LESSON-02/experiment.py
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
    name="FRESH-LESSON-02",
    lesson=HERE / "lesson.json",
    contradiction=HERE / "contradiction.json",
    domain="fresh_lesson_02",
    contested="zanth isa cat",
    new_words=["zanth", "plib", "morv", "trilp", "gorn", "sefa", "lumo", "drax", "quorp"],
    in_taught_shapes=[
        ("A gorn is not a dog.", tell(("isa", "gorn", "dog", False))),
        ("Is a plib a cat?", ask([("isa", "plib", "cat", True)])),
        ("What is a morv?", ask([("isa", "morv", "?x", True)], ["?x"])),
        ("Where is the plib?", ask([("located_in", "plib", "?x", True)], ["?x"])),
        ("Yuli has a morv.", tell(("owns", "yuli", "morv", True))),
        ("Plibs are fast.", tell(("has_property", "plib", "fast", True))),
        ("The zanth is near the table.", tell(("near", "zanth", "table", True))),
        ("A morv is not a cat.", tell(("isa", "morv", "cat", False))),
    ],
    in_new_shapes={
        "is found in": [
            ("A lumo is found in a bag.", tell(("located_in", "lumo", "bag", True))),
            ("A zanth is found in a kitchen.", tell(("located_in", "zanth", "kitchen", True))),
            ("A plib is found in a city.", tell(("located_in", "plib", "city", True))),
        ],
        "comes from": [
            ("A trilp comes from a box.", tell(("comes_from", "trilp", "box", True))),
            ("A zanth comes from a city.", tell(("comes_from", "zanth", "city", True))),
            ("A gorn comes from a kitchen.", tell(("comes_from", "gorn", "kitchen", True))),
        ],
    },
    questions=[
        ("What is a zanth?", "says a zanth is a cat", lambda r: "cat" in r),
        ("Is a zanth a cat?", "yes", lambda r: r.startswith("yes")),
        ("Is a zanth a dog?", "no", lambda r: r.startswith("no")),
        ("Is a zanth an animal?", "yes: a zanth is a cat, a cat an animal", lambda r: r.startswith("yes")),
        ("Can a zanth climb?", "yes: cats can climb", lambda r: r.startswith("yes")),
        ("Can a plib run?", "yes: dogs can run", lambda r: r.startswith("yes")),
        ("Is a morv a vehicle?", "yes: a morv is a car, a car a vehicle", lambda r: r.startswith("yes")),
        ("What is a morv made of?", "metal", lambda r: "metal" in r),
        ("Is Yuli a person?", "yes: Yuli is a boy, a boy a person", lambda r: r.startswith("yes")),
        ("Who owns the zanth?", "Yuli", lambda r: "yuli" in r),
        ("Is the plib near the door?", "yes", lambda r: r.startswith("yes")),
        ("Is a morv fast?", "not known: 'I do not know whether ...'", lambda r: r.startswith("i do not know")),
        ("Where is a trilp found?", "in a city (a question shape never taught)", lambda r: "city" in r),
        ("Where does a lumo come from?", "a city (a question shape never taught)", lambda r: "city" in r),
    ],
    after_contradiction=("Is a zanth a cat?", "still yes: the weaker source dents the belief, not the answer",
                         lambda r: r.startswith("yes")),
    claim=("Taught a second lesson no experiment has taught or tested, written after the first one's fixes, Lyric holds "
           "every fact it states as a fact, a belief and a memory; reads sentences it was never taught, in shapes it "
           "had and in two it learned from three sentences each; answers questions from what was taught, including "
           "who holds a relation to a thing, and says it does not know what was never stated; keeps it across a "
           "restart; does not grow surer from being told again; and keeps its answer when a weaker source says "
           "otherwise, while the belief moves."),
    hypothesis=("Any fact refused, missing from the graph or moving no belief; any sentence read otherwise than written "
                "here; a new shape read before it was taught or not read after; a wrong, made-up or crashed answer; a "
                "reading lost on restart; a belief moved by the same lesson again, or not moved by the contradiction; "
                "an answer turned by the weaker source; or a write to the main store, each shows here."),
)


if __name__ == "__main__":
    sys.exit(asyncio.run(fresh.run(MATERIAL)))
