#!/usr/bin/env python3
"""QUESTION-FORMS-02 — questions about what happens and what happened, with happenings held as events.

QUESTION-FORMS-01 found a question form taught with some verbs ("Where does Tom live?") read for new words and not
for other verbs ("Where does a kelt hide?"), because the meanings dropped the verb; and that a told happening ("The wug
ate a fep.") was held as nothing at all. Since then (2026-10-04, decided by the teammate) a happening a lesson tells
of is held as one event of its verb's kind (`teaching.told_events`), questions about events are answered from the
events held (`Conversation._asked_of_events`), and english_31 writes happenings as events, as english_14 does. Here,
on the emptied sandbox, the 31 lessons, then facts with new words (`lesson.json`, frozen before the first run), then
questions through the conversation, every group checked:

  A  in shapes english_31 asks about, of new words;
  B  in shapes no lesson asks about (hides in, grows in, rests in);
  C  about things that happened: what was done, who did it, and whether it was done.

Every expected answer is written here before the run. The runner is QUESTION-FORMS-01's.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/QUESTION-FORMS-02/experiment.py
"""
import asyncio
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("question_forms_01",
                                               ROOT / "experiments" / "QUESTION-FORMS-01" / "experiment.py")
forms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(forms)


def answered(word):
    """The answer names `word`, said as an answer: a memory recited ("I remember: ...") is recall, not the question
    understood (FRESH-LESSON-02's third run passed two questions that way)."""
    return lambda r: word in r and not r.startswith("i remember")


MATERIAL = dict(
    name="QUESTION-FORMS-02",
    lesson=HERE / "lesson.json",
    domain="question_forms_02",
    groups=[
        ("shapes english_31 asks about", [
            ("Where does a fip live?", "in a kitchen", answered("kitchen")),
            ("Where does a snell come from?", "a city", answered("city")),
            ("Who does the plonk belong to?", "Nella", answered("nella")),
            ("Where is the trel kept?", "in a bag", answered("bag")),
            ("Where do brabs sleep?", "in boxes", answered("box")),
        ], True),
        ("shapes no lesson asks about", [
            ("Where does a kelt hide?", "in a box", answered("box")),
            ("Where does a morp grow?", "in a city", answered("city")),
            ("Where does the blip rest?", "in the bag", answered("bag")),
        ], True),
        ("things that happened", [
            ("What did the kelt chase?", "the blip", answered("blip")),
            ("Who chased the blip?", "the kelt", answered("kelt")),
            ("Did the fip kick the trel?", "yes", lambda r: r.startswith("yes")),
            ("What did the fip kick?", "the trel", answered("trel")),
        ], True),
    ],
    claim=("With happenings held as events, Lyric answers questions about where something happens in shapes english_31 "
           "teaches and in shapes no lesson asks about, and questions about what happened: what was done, who did it, "
           "and whether it was done."),
    hypothesis=("Any question in these groups read otherwise or answered wrongly, or a write to the main store, shows "
                "here."),
)


if __name__ == "__main__":
    sys.exit(asyncio.run(forms.run(MATERIAL)))
