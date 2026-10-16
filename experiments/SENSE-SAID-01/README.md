# SENSE-SAID-01: what a word is said of, put together with how often a sense is met

**Claim.** What a word is said of, added to how often each sense is met as one activation, takes more of the senses
WordNet's authors tagged than how often each sense is met alone. Taken first, with frequency only on a tie, it takes
fewer.

**Why.** The listener (`derived_reader.meant`) weighs two counted kinds of evidence for a word that names several
things. One is how often each thing has been met under the word, its base level. The other is how much more likely
each thing is given what the sentence's other word is said of (`MemoryAgent.said_selection`, after Resnik 1997):
red is said of physical things, so "The table is red." is the furniture. The first build took what a word is said
of first, as a rank of its own, and that let a difference of a thousandth undo a sense met a hundred times more.
This measures which way of putting them together takes the sense meant, before it is relied on.

**What it does.** Offline: no store and no substrate. It takes every adjective–noun and verb–object pair in
WordNet's hand-tagged definitions (the Princeton WordNet Gloss Corpus) where the noun is tagged by hand with one
sense and has two or more, and the Brown corpus says the adjective or verb of something. That is 12,654 pairs. Each
rule picks one of the noun's senses:

| | Rule |
|---|---|
| A | The most frequent sense alone (WordNet's tagged counts) |
| B | The strict order: what the word is said of first (Resnik's association), frequency only on a tie |
| C | One activation, `ln(1 + uses) + ln(P(k|w) / P(k))`, at the kind Resnik's association picks |
| D | One activation, at the sense's most specific kind anything is said of |
| E | One activation, averaged over every kind the sense is: the listener's |

`P(k|w)` counts one use more, spread as anything is, as the listener does. There are three sources, none of them
the test: what words are said of comes from Brown (`WordNetSource.said_of`), how often a sense is met from WordNet's
counts (SemCor), and the kinds from WordNet. The definitions were tagged by hand, apart from all three.

**Run** (from the Lyric folder; it needs the gloss corpus under NLTK's data, as `WordNetSource` does):

```
./venv_lyric/bin/python3 experiments/SENSE-SAID-01/experiment.py
```

**Runs:**
- 2026-10-01 (`results/20261001T214822Z.json`): **2/2.** 76,776 uses of 8,150 words; 12,654 pairs. The same
  figures on a second run (the kinds are summed in one order; an earlier run's two pairs in 3,078 came out of the
  order a set handed them over in).

  | Rule | verb–object (3,078) | coarse | adjective–noun (9,576) | coarse |
  |---|---|---|---|---|
  | A | 56.6% | 67.5% | 57.4% | 68.6% |
  | B | 44.6% | 55.6% | 42.5% | 53.6% |
  | C | 56.5% | 67.4% | 54.6% | 66.5% |
  | D | 53.1% | 65.2% | 55.1% | 66.4% |
  | E | **58.3%** | **69.1%** | **58.8%** | **69.8%** |

  Coarse: the pick in the tagged sense's lexicographer class ("noun.artifact", "noun.food").
  The listener took B until this run; it now takes E. Resnik (1997) reported the same shape: selection alone
  44.3% on verb–object against 58.2% for the most frequent sense.

**Known limits.**
- These are WordNet's fine senses. An LLM's bar is a coarse one (WORD_SENSES.md §2.4).
- The pairs are found by Brown's and the corpus's part-of-speech tags, next to each other only.
- The kinds are WordNet's own. The listener's are memory's, which hold what WordNet taught.
