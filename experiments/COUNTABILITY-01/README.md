# COUNTABILITY-01: whether a noun sense is counted, decided by what it is a kind of

**Claim.** Whether a noun sense is counted, decided by the hand-labelled senses of its kind, finds more of the
uncounted senses a hand-made lexicon holds than the word's uses in real text. The source's chain is right more
often than calling every sense counted, or than real text alone, on senses whose labels it was not given.

**Why.** WordNet says what a noun names, never whether it is counted. A fact said with the wrong one is wrong English,
and the reader then learns it ("A table is a furniture."). Step 1 of `docs/research/GENERALIZING_BY_KIND.md` states a
sense's use (`WordNetSource.use_of`):
1. Only ever plural ("clothes") or one in both ("deer"), from real text.
2. Else the sense's own label in the Bochum English Countability Lexicon (BECL 2.1, CC BY 4.0).
3. Else the word uncounted in real text, where the sense is the one the word is mostly used in.
4. Else what the labelled senses of its nearest kind carry, within the Tolerance Principle (`_sense_uses`).
5. Else the word's uses in the Brown corpus (`_uses`).

This measures that before it is relied on.

**What it does.** Offline: no store and no substrate. BECL's 9,537 counted or uncounted senses are held out five
ways by word. Each fold's senses are decided by a source given only the other folds' labels, so neither the sense nor
any sense written with the same word is labelled for it. Five rules decide each held-out sense:

| | Rule |
|---|---|
| A | Every sense counted |
| B | The Brown model alone: the word's uses in real text |
| C | The kind alone: the labelled senses of its nearest kind |
| D | The kind, then the word's uses: the order first built |
| E | The source's chain (`use_of`): the word uncounted first for its main sense, then the kind, then the word |

"Overall" takes what a rule leaves undecided as counted, so every rule is scored on all 9,537.

**Run** (from the Lyric folder; needs `BECL_2.1_master.csv` under `~/nltk_data/corpora/becl/`):

```
./venv_lyric/bin/python3 experiments/COUNTABILITY-01/experiment.py
```

**Results** (`results/<UTC timestamp>.json`, `.md` and transcript):

| | Decides | Right where it decides | Uncounted found (of 2,212) | Overall |
|---|---|---|---|---|
| A | 100% | 76.8% | 0 | 76.8% |
| B | 70.8% | 87.6% | 293 | 79.2% |
| C | 91.4% | 88.5% | 1,234 | 84.6% |
| D | 95.1% | 87.3% | 1,282 | 85.1% |
| E | 95.1% | 87.5% | 1,316 | 85.3% |

- **`20261002T122644Z`, 3/3.** The first chain, the kind before the word (D's order); overall 85.2%.
  - Its errors shared patterns: "advice", "rice" and "coffee" are uncounted in Brown, but their kinds (a proposal;
    grains and beverages) outvoted it.
  - A scratch comparison of six orders (no record) put them all between 85.0% and 85.5%. Where the kind and Brown
    disagree, Brown's "count" against the kind's "mass" is close to a coin flip (129 against 146 for a word's main
    sense).
  - Brown's "mass" against the kind's "count" goes to Brown about two to one. Brown's "mass" needs a majority of
    uses past the Tolerance Principle; its "count" needs one counted use. So the word's uncounted use was put
    first for its main sense.
- **`20261002T123320Z`, 3/4.** The new order (E). The fourth check failed, 8,139 against 8,140, for two reasons,
  neither of them about E:
  - D, written into the experiment, decided capitalized words by their kind, where the source gives them no use.
  - The kind was not the same in every process. A sense with two kinds took the first that tells in the order
    NLTK hands them over, which is a set's. The kinds are now taken in one order (`_ordered`), and `_sense_uses`
    was checked identical across two processes with different hash seeds.
- **`20261002T123452Z`, 4/4.** E 8,138 against D 8,119; uncounted found 1,316 against 1,282.

**What the record also shows:**
- **Where the chain is wrong.** Abstract nouns hold most of the 1,133 errors, in both directions: acts (285), communication
  (105), attributes (108), states (98) and cognition (92). For those, neither a kind nor real text tells much, as
  Bond and Vatikiotis-Bateson (2002) found for ontology alone.
- **Capitals.** A word WordNet writes capitalized is given no use. That leaves out 137 labelled senses, of which
  only 3 are named things; the rest are kinds ("Albanian", "Apostle"), and their kind takes 123 of 131 right. This
  is the proper-noun question in `docs/research/COMPREHENSION_SCOPE.md`: a named thing is not counted, but a kind
  written with a capital is.
- **BECL's both and neither.** The source states BECL's 697 senses labelled both as count 319, mass 339, none 39.
  Its 315 labelled neither are none 169, count 102, mass 40, plural 4.
- **Probes.** "fish" the food is still counted. Its kind, food, is split, so the word's single counted use in Brown
  decides it. "rice", "coffee" and "advice" are now uncounted; military baggage (`impedimenta.n.02`) is counted.

**Known limits:**
- BECL labels senses of 7,050 words. A held-out word's kind is labelled from other words, so the figures hold for
  words outside BECL to the degree those words are like BECL's.
- Nothing here is taught. What the reader and the main model make of these uses is measured by SENSE-01 and the
  lessons, not here.

**Fourth run (`20261002T172023Z`, after the Brown model counts by the Tolerance Principle too), 4/4.** Brown used to count a
word on a single counted use, beside any number of uncounted ones, while it called a word uncounted only past the
Tolerance Principle. Taught, that said "Gasoline is fuel." with "fuel" stated counted, and "meat" and "illness" the
same. Counted is now decided as uncounted is: the uncounted uses at most N / ln N, or none. Brown states 412 fewer
words counted (9,907).

| | Decides | Right where it decides | Overall |
|---|---|---|---|
| B | 67.2% (was 70.8%) | 89.4% (was 87.6%) | 79.2% |
| E | 94.4% (was 95.1%) | 87.9% (was 87.5%) | 85.3% (unchanged) |

What it no longer decides it decided about as often wrong as right. A word no source states is then used as the
words the reader holds are ("meat", "fuel": uncounted, from the lessons).

**Taken back the same day (fifth run, `20261002T190214Z`, 4/4: the third run's table above).** Brown counts a word
on any counted use again. Taught, the fourth run's rule left "property" (an attribute) with no stated use; the
reader then guessed from its ending, as "beauty" and "safety", and said "A manner is property.". The reason for
the rule was a check in SENSE-01 misjudging "Gasoline is fuel."; that check now judges a word per concept, as the
sayer does, and no longer needs it.

**Also changed: a record's uses are stated under the whole name.** "long bone", counted, and "bone", the stuff,
end in one word and were one key. A name of two words or more that ends in the word of one of its own kinds
("bedroom furniture", "long bone") is used as that kind's word is (`WordNetSource._kind_named`).

**Sixth run (`20261003T031802Z`, 4/4), with a rule F: as E, but the word uncounted in real text decides every
unlabelled sense of it, not only its main sense.** Asked because the indication sense of "evidence" is stated
counted by its kind's vote and taught so ("Every evidence is an indication."), while "evidence" is uncounted in
Brown and in both its labelled senses.

| | Decides | Right where it decides | Uncounted found | Overall |
|---|---|---|---|---|
| E | 95.1% | 7,933 (87.5%) | 1,316 | 85.3% |
| F | 95.1% | 7,931 (87.5%) | 1,353 | 85.3% |

F says 76 more senses uncounted: 37 rightly, 39 wrongly. It is no better, and the source keeps E. The word's real
text speaks for its main sense; for its other senses it is right about as often as the kind.

