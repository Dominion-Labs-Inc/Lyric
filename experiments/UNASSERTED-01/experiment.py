#!/usr/bin/env python3
"""UNASSERTED-01 — what a telling does not tell as so is not answered as so.

Since 2026-10-05 (decided by the teammate) what someone said, thought, asked or wants is marked as not told as so
(`MeaningFact.unasserted`, `docs/TEACHING.md` §12b): "The kelt said that the blip ran." tells a saying, and that the
blip ran is the kelt's to have said. A happening told of is held as one event of its verb's kind
(`teaching.told_events`), and a question about what happened is answered from the events held
(`Conversation._asked_of_events`). Here, on the emptied sandbox, english_01-31, then facts with new words
(`lesson.json`, frozen before the first run), then questions through the conversation, every one checked:

  A  a chase that happened is answered as happened (the control);
  B  a running the kelt said happened and a kick the fip wants are not answered as happened;
  C  a chase denied ("The fip did not chase the kelt.") and one that might be ("The kelt might chase the fip.")
     are not answered as happened.

Every expected answer is written here before the run. The runner is QUESTION-FORMS-01's.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/UNASSERTED-01/experiment.py
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


def not_as_happened(*outright):
    """Not answered as happened: no "yes", and no sentence of the reply saying the happening outright, in either
    voice (`outright`); a sentence reporting it ("the kelt said that the blip ran") does not. The first run's check
    named only the active voice, and passed "The fip was chased by the kelt." for a chase that only might be; the
    fourth's looked for the words anywhere, and failed "I remember: The kelt said that the blip ran.": both corrected
    after them."""
    def check(reply):
        sentences = [s.strip().removeprefix("i remember:").strip() for s in reply.split(".")]
        return not reply.startswith("yes") and not any(s.startswith(said) for s in sentences for said in outright)
    return check


MATERIAL = dict(
    name="UNASSERTED-01",
    lesson=HERE / "lesson.json",
    domain="unasserted_01",
    groups=[
        ("what happened", [
            ("Did the kelt chase the blip?", "yes", lambda r: r.startswith("yes")),
            ("What did the kelt chase?", "the blip; a chase of the fip not said as happened",
             lambda r: "blip" in r and not_as_happened("the kelt chased the fip", "the fip was chased by the kelt")(r)
             and not r.startswith("i remember")),
        ], True),
        ("what was said or wanted", [
            ("Did the blip run?", "not as happened: the kelt said so", not_as_happened("the blip ran")),
            ("Did the fip kick the trel?", "not as happened: the fip wants to",
             not_as_happened("the fip kicked", "was kicked by the fip")),
        ], True),
        ("what was denied or might be", [
            ("Did the fip chase the kelt?", "not as happened: the fip did not",
             not_as_happened("the fip chased the kelt", "the kelt was chased by the fip")),
            ("Did the kelt chase the fip?", "not as happened: the kelt might",
             not_as_happened("the kelt chased the fip", "the fip was chased by the kelt")),
        ], True),
    ],
    claim=("Told what someone said or wants, and a happening denied or one that might be, Lyric does not answer them "
           "as happened; told what happened, it does."),
    hypothesis=("A question about something said, wanted, denied or possible answered as happened, the happening "
                "that was told not answered as happened, or a write to the main store, shows here."),
)


if __name__ == "__main__":
    sys.exit(asyncio.run(forms.run(MATERIAL)))
