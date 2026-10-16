# QUESTION-FORMS-03: questions about kinds, parts, members, materials and opposites, and "Is it true that ...?"

**Why.** UNDERSTANDS-WORDNET-01's first run (2026-10-11) asked the main model about what WordNet taught it. These
forms read 0 times in 419:
- "Is a beroe a kind of ctenophore?"
- "Is a flower part of an angiosperm?"
- "Is occupied the opposite of unoccupied?"
- "Is it true that an investigator is an expert?"

The reader built readings from unrelated pieces instead. "kind" was read as the category, "the ... of" as a
superlative, and "a" as the ampere, giving 11 to 55 readings the listener could not tell apart. Or it gave one wrong
reading.

None of english_01 to 39 asks these questions. They teach the statements ("A robin is a kind of bird.", "A wheel is
part of a car.", "Hot is the opposite of cold."), and WordNet's facts were taught through those statements. The only
questions of this kind they teach are "Is a robin a bird?" and "Are robins birds?". FRESH-LESSON-01 to -03 found that
a statement's shape does not bring its question. english_31 then taught questions beside what they ask, and
`data/lessons/english_40.json` does the same here (112 sentences, 78 of them questions).

**What it checks.** On a copy of main (made from `lyric_db` just before the run; it refuses `lyric_db`):
- **A.** english_40 is learned, none refused, and every sentence of it reads as taught.
- **B.** 21 questions in english_40's forms that were never taught, using words WordNet taught main (`HELD_OUT`,
  frozen before the first run), read as written. Each word must be taken to name a thing that word names, in the facts
  asked. They are also measured before english_40.
- **C.** Of 600 sentences english_01 to 39 teach (a seeded sample, fixed before the first run), none that read as
  taught before english_40 reads otherwise after. A sample, because reading all of them as the conversation does,
  with memory at hand, takes over two hours a pass on main.
- **D.** The main model's store is untouched.

Each sentence is read as the conversation reads it: the listener takes one reading with memory at hand
(`derived_reader.heard`).

Plural questions are measured, not checked: main holds few plurals as plurals ("hawks" is no form of hawk to it;
LAB_NOTEBOOK 2026-10-11 (2)). Teaching word forms comes separately.

**Run** (on a fresh copy of main):

    POSTGRES_DATABASE=lyric_check2 ./venv_lyric/bin/python3 experiments/QUESTION-FORMS-03/experiment.py

**Runs:**

- **2026-10-11, first full run** (`results/20261011T065653Z`, on `lyric_check2`, a fresh copy of main): **4/6.**
  Main untouched (8,541,178 rows before and after); the run's log had no error.
  - english_40 was learned, none refused.
  - **Never-taught questions in its forms: 0 of 21 before english_40, 20 of 21 after.**
  - No sentence of english_01 to 39 that read as taught before reads otherwise after (381 of the 600 sampled read
    as taught before; that main reads only 64% of the lessons' own sentences as taught is a finding of its own).
  - FAILED: 108 of 112 of english_40's own sentences read with the lesson's concept names. The four were all
    "raptor", which main holds as WordNet's `bird of prey`: "Is an owl a kind of raptor?" read isa(owl, bird of
    prey), the right meaning under main's name for it. A now reads word by word as B does; the strict count is
    kept as a measure.
  - FAILED: "Is a lockstitch a kind of stitch?" read "a lockstitch" as one new name. "lockstitch" is held only as
    "Lockstitch" (taught where a sentence began), so it reads only loosely, and the loose reading is searched only
    when nothing reads exactly; and "a" no longer counted as structure, WordNet having taught it the ampere. Fixed:
    a word held frames are built with more than it names things with is structure in a new name
    (`builds_more_than_it_names`); the reader's 99 tests pass.
