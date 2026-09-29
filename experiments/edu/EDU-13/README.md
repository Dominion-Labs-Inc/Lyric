# EDU-13 — deriving a way to read, instead of writing one

**What it tests.** Whether the substrate can derive how to read a sentence from sentence/meaning pairs,
treating a reading as a program over a sequence of words (using `list_machine` and procedure
synthesis). It then reads sentences, and words, it never saw.
- Both affirmative and negated readings are derived.
- On held-out sentences, the result is compared with the six-regex extractor.

**Run:** `./venv_lyric/bin/python3 experiments/edu/EDU-13/reading.py`

**Results.** `reading.json` (recorded 2026-08-24): passed; all 7 held-out sentences read correctly.

**Status.** It does not run as written: it imports `core.model_policy`, which has been removed.
