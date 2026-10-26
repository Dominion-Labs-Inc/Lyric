# Why the grammar reads badly: the diagnostics (2026-10-25/26)

Three scripts, files only, no store, each building the grammar as GRAMMAR-01 does (about three minutes). They answer
what is wrong, not whether a change helped; nothing in Lyric was changed for them. Lab notebook 2026-10-26 (51).

| Script | What it measures |
|---|---|
| `taught_fit.py train/gold` | how many of its own taught sentences (PMB gold training, a seeded 1,000) the grammar reads back right |
| `every_reading.py train/gold 1000` | every reading the grammar can build of each (a chart keeping every distinct reading, not the surest of each category), whether one gives the taught meaning, why not; and the chosen reading checked word by word against the PMB 4.0.0 gold CCG derivation |
| `categories.py dev/standard` | each held-out word: the gold category, the categories the grammar lists and derives (`Grammar._unary`) for it, the one its reading uses |

From 2026-10-26 (52) `taught_fit.py` and `categories.py` hold the training derivations first, as GRAMMAR-01 and main do
(`PMBDerivationSource`, `GrammarView.hold_derived`): taught sentences read back 414 -> 424 of 1,000; held-out words in
the derivation's category, compared strictly, 3,230 -> 3,364 of 5,044 (64.0% -> 66.7%), offered and another chosen
822 -> 726. `every_reading.py` was not run again.

The gold derivations are the PMB's 4.0.0 release (`test_data/semantics/pmb/pmb-4.0.0.zip`, 2.8 GB, kept out of git;
its English gold `en.parse.tags`, `en.raw` and `en.status` extracted to `pmb-4.0.0/data/en/gold`, 10,715 documents).
Each word there carries its CCG category in that sentence, its part of speech, lemma, WordNet sense and VerbNet role.
The 5.1.0 release Lyric was taught from carries meanings only.

## What they found

**Taught = unseen.** The grammar reads back 414 of 1,000 sentences it was taught (41.4%), what it reads of sentences
never seen (dev 41.4%). Learning (`Grammar.learn`) labels the links of the reading the grammar's word counts prefer,
whatever the taught meaning says; the chart keeps one reading per category per stretch, the surest by word counts
(`Grammar.chart`). Nothing taught changes which reading is chosen.

**The 1,000 taught sentences**, the one spoken of before scored as an unknown of its own (the PMB writes a pronoun so):

| | Sentences |
|---|---|
| read right | 565 |
| right reading built, another chosen | 52 |
| right things joined, a link named wrong | 82 |
| no reading joins the right things | 217 |
| no whole reading | 22 |
| too many readings to finish (past 20,000 signs) | 62 |

Of the 217, against the gold derivation: 86 a word read as another kind of word ("herself", "of Mary's", "got his
watch fixed", "plastic tumbler"); 72 every word read as the derivation reads it, the meaning said another way ("his
ignorance" `owned_by` for `creates`, "studying English" `done_to` for `about`; 5 the scoring's: a pronoun's kind named
by its word); 30 a name or phrase of several words split ("Burt Lancaster", "in love", "by no means"); 29 no
derivation in 4.0.0.

**Held-out words** (dev, 5,044 compared with the gold derivation): 64.0% the same category, 21.5% the same said
another way (a name N there, NP here; a preposition the verb's there, an adjunct here; "my uncle"'s relational
categories), 10.6% a category the grammar offers but another chosen, 3.9% a category it does not offer (particles
"up", "away"; a noun before a noun; "n't"; "'s"; "himself"; "Half", "All"; "around 20"), 6.3% words split
otherwise. The check calls some equivalent analyses different (95 sentences read right show a word read otherwise).

**Why a sentence fails:** each word's error multiplies. About 85% of words right in sentences of five to six words is
about 40% of sentences right, what is measured.

**Published, on this kind of data:** Boxer, the rule-based CCG with a parser trained on 40,000 hand-annotated
sentences that made the PMB's meanings, 74.3 (PMB 2.1.0, van Noord et al. 2018); neural parsers 83.6 then, 89 to 92
on PMB5's standard test (sentences of five words on average), 5 to 44 on its long texts (61 words).
