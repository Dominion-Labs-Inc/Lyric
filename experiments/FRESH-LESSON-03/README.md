# FRESH-LESSON-03: FRESH-LESSON-01's checks, on a third lesson written after the first two lessons' fixes

**Why.** FRESH-LESSON-01 and -02 found faults in answering and in saying a word's plural, fixed against their own
questions. This third lesson was written after those fixes and frozen before its own first run: other words (larth,
fosk, brell, jimp, talo, quib, smeb, gloth, voth, prenk, dorv; "larth" ends in -th and is taught as "Larths"), other
facts, two other new shapes ("X is kept in Y", "X sleeps in Y"), and its own questions. The checks and the runner
are FRESH-LESSON-01's, with the after-contradiction answer now also checked for not denying the fact as well.

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/FRESH-LESSON-03/experiment.py`

**Runs:**

- **2026-10-04, first run** (`results/20261004T164222Z`): **30/32**. Main untouched (290,096 rows).
  - Every learning, reading, restart and again check passes.
  - Every answer passes:
    - "Yes. Larths are animals." (the plural as taught);
    - "Talo has a larth.";
    - "I do not know whether the larth is red.";
    - asked again after the contradiction, "Yes. A larth is a horse.", once, while the belief moved from 0.997 to 0.970.
  - FAILED, as on the first two lessons: the question forms of the new shapes ("Where is a quib kept?", "Where does a voth sleep?"), which no lesson teaches.
- **2026-10-04, second run** (`results/20261004T195618Z`): 31/32, and **not a valid run of this lesson**.
  - The runner taught every lesson file, english_31 among them, written after this lesson was frozen. english_31 says
    "is kept in" and "sleeps in" as happenings (a keeping, a sleeping: events); this lesson says them as where a thing
    is. Taught both, the reader held two meanings for one shape:
    - "A larth sleeps in a box." read two ways that suppose as much, so it was read as neither (2 of 3 for the shape);
    - "Where is a quib kept?" and "Where does a voth sleep?" were read as asking about a happening, and none was held,
      so each was answered by a memory recited ("I remember: A quib is kept in a room."). The check passed both on
      the word "room".
- **After the second run, the runner** (FRESH-LESSON-01's `experiment.py`):
  - teaches the 30 lessons the three lessons were frozen with (`FROZEN_WITH`), and counts them in its check's name;
  - takes a memory recited as no answer (`answered`), as QUESTION-FORMS-02 does.
- **2026-10-04, third run** (`results/20261004T201145Z`): **30/32**, as the first. Main untouched (290,096 rows).
  - With the 30 lessons it was frozen with, every learning, reading, restart and again check passes, both new shapes
    3 of 3, and every answer as in the first run.
  - FAILED, as in the first run: the question forms no lesson of the 30 teaches. "Where is a quib kept?" was read
    with "quib kept" taken as a new name ("I don't hold quib kept yet."); "Where does a voth sleep?" was not read.
    english_31 teaches these forms, and QUESTION-FORMS-02 answers them (16/16).
