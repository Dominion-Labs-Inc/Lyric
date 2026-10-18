# GROUPS-01: whether word groups counted from raw text help the structure reader

**Claim.** Words grouped by the company they keep, counted from raw text, help the structure reader read: a word it
met rarely or never in the treebank is weighed by the words that stand where it does.

**Why.** The reader's errors fall most on words it met few times (lab notebook 2026-10-18). An LLM knows a rare word
by the words around it in a great deal of text. Lyric can know the same by counting: no model, a table of word to
group, as readable as the text's own counts.

**How** (`core/semantics/word_groups.py`): every word of WikiText-103's raw training text (about 100 million words of
Wikipedia, CC BY-SA) is put in one of a number of groups so that the counts of which group follows which say the text
best: the exchange algorithm over a class bigram model (Brown et al. 1992; Kneser & Ney 1993; Martin, Liermann & Ney
1998). 256 groups and 48, for the 100,000 most frequent words. The structure reader (`core/semantics/structure.py`),
learned from UD English EWT's training part, reads with each word's two groups beside it (`StructureView.grouping`).

**What it measures** (files only, no store): on EWT dev and PUD (1,000 sentences of Wikipedia analysed by hand),
without and with the groups: classes, UAS, LAS, and UAS on the words met fewer than ten times in training.

| Bar (from the scratch measurements that came first: +0.9 points on both) | |
|---|---|
| With the groups | UAS at least 0.5 points higher on EWT dev and on PUD |

MiniLM's vectors grouped the same way (k-means, 256 and 48) were measured beside them in scratch and read no better:
EWT dev 79.1–79.2%, PUD 75.4–76.3%, against the counted groups' 79.2% and 76.4% (lab notebook 2026-10-18).

**Run** (from the Lyric folder; about half an hour):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GROUPS-01/experiment.py --raw DIR
```

with `--raw` holding WikiText-103's raw training text as parquet (`wikitext-103-raw-v1`, `text` column), and
`test_data/syntax/` holding `UD_English-EWT` and `UD_English-PUD` (`--data DIR`). The tables are written to
`data/word_groups/` (`--out DIR`; not in the repository) as `groups_256.tsv` and `groups_48.tsv`.

**Results:** `results/<UTC timestamp>.json` and `.md`.
