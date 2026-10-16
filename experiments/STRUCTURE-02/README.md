# STRUCTURE-02: how many of the lessons' meaning roles fall on phrases

**Claim.** The meaning roles of the sentences the main model was taught fall on phrases of the structure it learned
from a treebank, so frames learned over phrases can read them as they were taught.

**Why.** The reader learned whole sentence frames with slots, and prose fails where nothing between words and frames
says which words form a phrase (`docs/research/READING_PROSE_AT_SCALE.md`). The owner chose (2026-10-16) that Lyric
learns phrase structure from a treebank; STRUCTURE-01 measured that structure. Before frames are learned over phrases,
this measures the ceiling they can reach: the research's first measurement (§5).

**What it measures** (read only, from the store's own views, warmed from memory). Each sentence of the English lessons
(`data/lessons/english_NN.json`) is read as the learner reads a taught pair (`readings_of`, strictly, to the meaning
it was taught with). Where it reads through a frame with slots, the words each slot holds are found as the reader
finds them (`_chunkings`, `_slot_fillings`, `_composed_meaning`), and the sentence is read for its structure
(`StructureView`). Each slot is tested twice:

| Test | A slot passes when |
|---|---|
| One phrase | exactly one of its words depends on a word outside them (a slot of one word always does) |
| Attached as the meaning says | going up from that word, the first other slot met, if any, is one the meaning says something of together with it, in one fact |

"Tom kicked the ball in the house." with "house" under "ball" fails the second test when the house is where the
kicking was; "The ball near the box is red." with "box" under "ball" passes it. Only the slots are tested: what a
frame writes itself is not.

The share of sentences whose every slot passes both is the ceiling. **No bar:** it measures. It also reports each
test by the kind of thing a slot holds (`_role_of_slot`: kind, quality, doing, name, closed, thing), how each slot's
phrase depends on the rest (`_relations.json`), every sentence with a slot that fails (`_missed.json`), and checks
the store was not written to.

**Run** (from the Lyric folder; starts no substrate; about 5 minutes to load, then the lessons read once):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-02/experiment.py
```

**Results:** `results/<UTC timestamp>.json` and `.md`, `_missed.json` and `_relations.json` beside them, and
`results/run.log`.
