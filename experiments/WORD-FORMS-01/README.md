# WORD-FORMS-01: English plurals taught, and read from Lyric's own memory

**Why.** UNDERSTANDS-WORDNET-01's first run (2026-10-11) asked "Are coiners sources?" and was told "No. No coiners
is a source." Three things went wrong:
1. The reader took "coiners" as a new name.
2. The answer turned it into `coiner` by asking WordNet at runtime (`lexical_normalization._wordnet_singular`).
3. That reached only `coiner`, the forger. The strong disjointness assumption then answered no, and the coiner of
   words was never considered.

On main, the plural ending `s` read 517 of the 6,914 words it applies to rightly, so it was not productive. WordNet's
own words ending as plurals do ("glass", "lens", "species") outnumbered the plurals the lessons showed. WordNet's pass
had said plurals only of the nouns no change makes ("Mice are rodents.").

`WordNetExamplesSource` (`scripts/teach.py --source wordnet-examples --part n`; `word-forms` when this ran) says the plural of every counted noun sense in a fact
WordNet holds of it: about 44,000 sentences such as "Hawks are birds of prey." and "Hawks are militarists.". The
teacher writes each sentence in the frame the lessons teach a kind said of many in. The plural is spelled by
evidence, in this order:
1. WordNet's exceptions;
2. the Brown corpus;
3. a form the CMU dictionary writes;
4. the word's last sound;
5. its letters, only where they settle the spelling.

**What it checks.** On a copy of main the word forms were taught to, read only:
- **A.** Every plural said is held for the sense it was said for.
- **B.** Lyric's own singular of a word agrees with WordNet's on at least 99% of the plurals taught and the nouns
  held. That 99% is the bar, set before the run, for `singularise` to stop asking WordNet at runtime.
- **C.** Plurals never taught, of nouns held, read through a productive shape: measured.
- **D.** Plural questions read as written: "Are hawks raptors?", "Are coiners sources?", "Are titmice birds?" and
  others.

**Run** (on a copy of main the word forms were taught to):

    POSTGRES_DATABASE=lyric_check2 ./venv_lyric/bin/python3 experiments/WORD-FORMS-01/experiment.py

**Runs:**
