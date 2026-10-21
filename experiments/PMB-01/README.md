# PMB-01: what a sentence means, composed over its structure, learned from the Parallel Meaning Bank

**Claim.** What a sentence means, in Lyric's meaning language, is composed over its structure: what each word stands
for, and the facts each two words the structure joins within two steps hold, learned from sentences aligned word by
word to their meanings.

**Why.** The composer before this one decided each word's standing and every pair of the sentence's words apart, from
the situations met nearby. Measured on main (lab notebook 2026-10-20 (26)), it composed 3.0% of the PMB's held-out
English whole learned from the lessons, 8.0% with the PMB's gold training sentences, 8.2% with its silver ones too:
eight times the data, 0.2 points. The design was the limit. The handoff's next step: rebuild the composer to compose,
learned from the PMB, whose meanings were built that way and corrected by hand.

**How** (`core/semantics/composition.py`, lab notebook 2026-10-20 (27)):
- **Aligned by the data.** Each PMB line holds the characters of the words it stands for and marks its grammar's
  words ("the", "in"); `pmb_meanings.meaning_of` says which lines say each term (`Said.anchors`), and
  `composition.words_by_anchors` finds the word of each line in Lyric's own reading. A lesson is aligned by its names.
- **Each word's standing**: nothing, a thing, a known thing, a thing of no kind said ("it", the "and" of two things), a
  name, a situation's term, what is asked (with or without a kind), or what another word stands for ("who", "his").
- **Facts only between near words**: of the PMB's facts joining two words, 62% join words one step apart in Lyric's
  structure and 98% at most two. Decided as the upper word's piece (its name, the relations and markers down to the
  other), then the lower word's ("when"), then a word between ("has", "is"), then classes.
- **Which word another stands for**, decided over every word with a term, nearest first; **a word's facts with a term
  no word says** (its time); **a denied kind**; **the words that deny**, learned, never listed ("n't", "not",
  "never", "nobody"; "does" is not one); **one meaning**: a fact the facts held would contradict is not held.

**What it measures** (files only, no store): the PMB's dev split (`split/en/dev/standard.sbn`), each sentence said
whole in the meaning language, composed and compared two ways: **strict**, each kind named as Lyric names the WordNet
sense the PMB gives; **senses aside**, each kind and name a word says named as the composer names that word (the
composer names a word by its word; the PMB a sense, "took" `utilize take`; 48% of the dev kinds differ so). Each way:
whole meanings right, and the facts' precision, recall and F1 (each variable put as what it is an instance of).
Since `20261020T185728Z` a third way, senses aside with the one spoken of before (`?previous`) taken as a thing of no
kind, as the PMB leaves a pronoun its document does not tie: the composer says such a word as the lessons and the
conversation do. Learned from the lessons only (what main held before), with the PMB's gold training sentences, and
with `--silver` its silver ones too. The prose of UNDERSTANDS-PROSE-01, composed learned from all, is kept beside the record.

| Bar | |
|---|---|
| Learned from the PMB's gold sentences | dev whole meanings right, strict, above the composer before this one on main (8.0%) |
| | more right than learned from the lessons alone |
| With the silver sentences (`--silver`) | more right than with the gold alone |

Names come from files: a word's plain form by WordNet, else by the treebank's lemmas; a word the treebank never used
limited to the classes WordNet gives it. On main the names are memory's.

**Run** (from the Lyric folder; about five minutes, `--silver` about forty):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PMB-01/experiment.py --silver
```

with `test_data/syntax/UD_English-EWT` (`--data DIR`), the PMB release 5.1.0 in `test_data/semantics/pmb/pmb-5.1.0`
(`--pmb DIR`; https://pmb.let.rug.nl/releases/pmb-5.1.0.zip, never pushed), the lessons in `data/lessons/`, and WordNet
for `nltk`. The Parallel Meaning Bank: University of Groningen, annotations ODC-BY 1.0; attribute it (Abzianidze et
al. 2017, "The Parallel Meaning Bank") in any public use of it or of what is built from it.

**Results:** `results/<UTC timestamp>.json` and `.md`, the prose composed (`_prose.json`) and 300 of the dev sentences
not composed right senses aside (`_missed.json`).

**Runs** (dev: 884 sentences said whole of 1,194; senses aside, strict in brackets; facts F1 senses aside):

| Run | Where | The lessons | + PMB gold training | + PMB silver training |
|---|---|---|---|---|
| `20261020T164055Z` | the Mac, files only | 7.2% (4.6%), F1 49.0% | 42.1% (19.5%), F1 79.3% | 46.9% (20.8%), F1 82.9% |
| `20261020T185728Z` | the Mac, files only; a pronoun the lessons say as the one spoken of before says it so, a happening that did not happen said as the lessons say it (lab notebook 2026-10-20 (28)); in brackets after the strict figure, the one spoken of before scored as unnamed | 7.1% (4.5%; 7.9%), F1 51.3% | 33.9% (16.2%; 40.7%), F1 79.4% | 37.6% (17.3%; 44.7%), F1 82.7% |
| `20261020T210127Z` | the Mac, files only; a subject stands for nothing only under the verbs it was learned to ("It rains."), a word of its head's own line stands for nothing, whether a word is written in a shape of its name weighed for which word a pronoun stands for (lab notebook 2026-10-20 (30)) | 7.1% (4.5%; 7.9%), F1 51.6% | 33.6% (16.1%; 40.6%), F1 79.3% | 36.4% (16.7%; 44.0%), F1 82.3% |
| `20261021T025534Z` | the Mac, files only; the PMB's meanings say an order as a request and a role as the kind said (`pmb_meanings`, lab notebook 2026-10-21 (32)), no silver; measured beside GRAMMAR-01 `20261021T025251Z` (20.0%, 39.3%, 49.4%) | 7.6% (4.8%; 8.5%), F1 52.1% | 32.9% (15.7%; 39.7%), F1 78.7% | |

The composer before this one (6266d3a), measured the same way in scratch on the same 884 sentences: 6.6% (4.0%),
16.5% (9.3%), 15.6% (9.2%); facts F1 53.6%, 64.6%, 64.8%. On main (2026-10-20 (26), 842 sentences, strict): 3.0%,
8.0%, 8.2%.

