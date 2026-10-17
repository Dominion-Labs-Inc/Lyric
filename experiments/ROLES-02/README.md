# ROLES-02: which phrases are a happening's arguments, and what each is said in, end to end

**Claim.** Of the words around a happening, the view learned from PropBank finds those that head its arguments and
says what each is said in, in Lyric's meaning language, with nothing given but the happening.

**Why.** ROLES-01 gave the arguments and measured only what each is said in. Composing what a sentence means (the
handoff's plan, step 3) needs both: which phrases are arguments, and what each is.

**How** (`core/semantics/argument_structure.py`): the words that may head an argument (`candidates`) are the
happening's dependents and, going up the structure from it, each word above it and that word's dependents (the
pruning of dependency role labelling, Zhao, Chen, Kit & Zhou 2009): 99.6% of the training part's argument heads are
among them. Each candidate is met as a phrase (`phrase`: the word with all that depends on it) in the situations
ROLES-01 uses, and learned with what it was said in, or `NONE` where it heads no argument; read by the most specific
situation met (`ArgumentStructureView.arguments`).

**What it measures** (files only, no store): learned from PropBank's training part over UD's structure; on dev and
test, every happening PropBank marks (auxiliaries, `be.02` and light verbs are no happening), over UD's structure and
over Lyric's own (`StructureView`, learned from the same training part): precision, recall and F1 of the argument
heads found, and of the heads found and said right. A relative pronoun or continuation (which takes its argument's
part) and an argument the mapping does not say are left out on both sides. No bar: measured.

**Run** (from the Lyric folder; about ten minutes):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ROLES-02/experiment.py
```

with `test_data/syntax/` holding `propbank-release`, `propbank-frames` and `UD_English-EWT` (`--data DIR` reads them
from elsewhere).

**Results:** `results/<UTC timestamp>.json` and `.md`.

**Runs** (F1; precision and recall in the record):

| Run | Where | dev, UD's structure: heads / said | dev, Lyric's | test, UD's | test, Lyric's |
|---|---|---|---|---|---|
| `20261017T173945Z` | a cloud session, code 1ac6aac | 92.9% / 76.3% | 76.2% / 58.7% | 93.2% / 76.7% | 78.1% / 60.9% |

Over UD's structure, finding the heads is nearly solved (93%); saying each loses 16 points more, as ROLES-01 found
with the arguments given (80.5%). Over Lyric's structure (UAS 79.5% on test) both lose about 15 points: the structure
is what costs most.
