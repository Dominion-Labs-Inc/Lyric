# SELF-TEACH-01: whether the structure reader teaches itself from raw text

**Claim.** The structure reader teaches itself from raw text: it reads sentences no one analysed, keeps the readings
its two ways of reading agree on, and reads held-out text better for having learned from them.

**Why.** Doubling the hand-analysed text the reader learns from raised it by 3.2 points of UAS (lab notebook
2026-10-17 (13)), and hand-analysed text is scarce; raw text is not. An LLM learns from raw text alone. If agreement
picks out readings right enough to learn from, Lyric can learn structure the same way, with counts.

**How** (`core/semantics/structure.py`): the reader decides a sentence's structure two ways at once, a transition beam
and a whole-tree pair model, and combines them. Each alone gives every word a head
(`StructureView.readings_apart`); the share of words they give the same head is the sentence's agreement. Learned
from UD English EWT's training part (12,544 sentences), the reader reads 200,000 sentences of Wikipedia
(WikiText-103's raw training text, CC BY-SA), keeps those agreeing on at least a bar of their words, and is learned
again from the treebank and them.

**What it measures** (files only, no store):
- how far agreement can be trusted: EWT dev and PUD read the same way, the sentences agreeing at each bar, their
  length, and how right their readings are;
- the reader learned again with self-taught text at several bars and sizes, on EWT dev and PUD (1,000 Wikipedia
  sentences analysed by hand), UAS and LAS, against the reader without it.

| Bar (fixed before the run) | |
|---|---|
| As much self-taught text as the treebank's training part | gains at least half a doubling's UAS on EWT dev (1.6 points) |

**Run** (from the Lyric folder; about two hours on four cores):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/SELF-TEACH-01/experiment.py --raw DIR
```

with `--raw` holding WikiText-103's raw training text as parquet (`wikitext-103-raw-v1`, `text` column) and `test_data/syntax/`
holding `UD_English-EWT` and `UD_English-PUD` (`--data DIR`).

**Results:** `results/<UTC timestamp>.json` and `.md`.
