# Why the grammar reads badly: the diagnostics (2026-10-25/26)

Three scripts, files only, no store, each building the grammar as GRAMMAR-01 does (about three minutes). They answer
what is wrong, not whether a change helped; nothing in Lyric was changed for them. Lab notebook 2026-10-26 (51). The
three since (`verb_places.py`, `participles.py`, `several_words.py`) ask what the PMB's gold says of a kind of word,
against each way of deciding it; they build no grammar and take about a minute.

| Script | What it measures |
|---|---|
| `taught_fit.py train/gold` | how many of its own taught sentences (PMB gold training, a seeded 1,000) the grammar reads back right |
| `every_reading.py train/gold 1000` | every reading the grammar can build of each (a chart keeping every distinct reading, not the surest of each category), whether one gives the taught meaning, why not; and the chosen reading checked word by word against the PMB 4.0.0 gold CCG derivation |
| `prose_joins.py [N] [--without-structure]` | of N (200) sentences of published prose analysed by hand and held out (UD English PUD), how many content words the chosen reading joins to the word the analysis joins them to |
| `categories.py dev/standard` | each held-out word: the gold category, the categories the grammar lists and derives (`Grammar._unary`) for it, the one its reading uses |
| `verb_places.py train` | each place of each verb of a split's gold documents, named as the grammar names it, against the link the PMB gives its role: by what word records gave before, by the VerbNet frames of the gold sense, of the word, and of WordNet's most used sense |
| `participles.py train` | each word of a split's gold documents written as a participle or an -ing form, standing where either a quality or a doing may stand: what the gold says it is, and of the gold's qualities how many each way of deciding catches, and of what it calls qualities how many are ones |
| `several_words.py train` | every concept of a split's gold documents whose words are several, by shape (a name, a noun, a verb, a quality, an adverb) and by whether the language has them as one word: how many each way of deciding catches, and of every run of words the sentences say how many of those each way calls one concept are ones; and the link the gold makes where a name stands right before a thing |

From 2026-10-26 (52) `taught_fit.py` and `categories.py` hold the training derivations first, as GRAMMAR-01 and main do
(`PMBDerivationSource`, `GrammarView.hold_derived`): taught sentences read back 414 -> 424 of 1,000; held-out words in
the derivation's category, compared strictly, 3,230 -> 3,364 of 5,044 (64.0% -> 66.7%), offered and another chosen
822 -> 726. `every_reading.py` was not run again.

The gold derivations are the PMB's 4.0.0 release (`test_data/semantics/pmb/pmb-4.0.0.zip`, 2.8 GB, kept out of git;
its English gold `en.parse.tags`, `en.raw` and `en.status` extracted to `pmb-4.0.0/data/en/gold`, 10,715 documents).
Each word there carries its CCG category in that sentence, its part of speech, lemma, WordNet sense and VerbNet role.
The 5.1.0 release Lyric was taught from carries meanings only.

**Prose joins (2026-10-26 (55)):** the readings chosen joined 54.9% of PUD's content words (200 sentences, 2,146
words) as the analysis by hand does; Lyric's structure view, learned from EWT's training part and scored the same way,
72.5%. Two readings joining the same words otherwise scored the same, and the chart kept the first it built (146 of
221 joins in 20 sentences of UNDERSTANDS-PROSE-02's prose). With the structure view's joins weighed
(`Grammar._joined`): 68.0%.

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

**`verb_places.py`** (2026-10-29, lab notebook (77)): each place of each verb of the PMB's gold documents of a split,
named as the grammar names it, against the link the PMB gives its role: by what word records gave before (PropBank's
function tags over the word's senses), by the VerbNet frames of the gold sense (else the word's, else before), and of
WordNet's most used sense. Train: objects 80.8%, 86.5%, 85.4%; subjects 90.7%, 92.7%, 92.0%. With the Experiencer
rule of (78) (an Experiencer beside a doer what it is done to), objects 81.8% and 86.8%, subjects unmoved; it prints
each place's own gold links, and of a passive's places a second reading as the active names them (`as the active`: its
subject the verb's object, its "by" the subject) and Lyric's own convention (`a doer said`).

**A passive's subject (78):** the PMB links it `done_to` 49% of the time, `done_by` 42% (678 of the train
documents' places), by the verb: a Patient for "injure" and "soak", a Theme alone (which the meaning language reads as
who does it) for "speak" and "elect". `done_to` whatever else is said, which the reader says, is right 49% of the
time; "done_to where a doer is said with it, else done_by" 56.5%; the frames, asked for the place as the active names
it, 29.6% (asked so they answer for the Agent's place, not for the one affected).

**`several_words.py`** (2026-10-29, lab notebook (79)): of the 9,552 gold train documents, 1,586 concepts are one
word of several — 420 a name ("New York", "Second World War", "Leaning Tower of Pisa"), 747 a thing ("hair dryer",
"peace treaty", "red wine"), 238 a verb ("split up", "picked up", "ran into"), 105 an adverb ("in vain", "out of the
blue"), 76 a quality ("fed up", "in love", "out of print"). WordNet spells **every one** of the 1,166 that are not
names as one word, in one of three spellings (as written 97.8% of the things, the last word as its base 11.7%, run
together 8.8%), so memory taught from WordNet holds them all; the names it spells 45.5% of, and a capitalised run
catches 77.6%. Of the 44,993 runs of two words the sentences say only 3.7% are one concept, against which: WordNet
as written calls 1,852 one and 58.6% are, the last word's base 122 and 81.1% are, run together 753 and 14.1% are, a
capitalised run 487 and 61.2% are. A further 663 concepts cover several words without being one word of the language,
the annotation lumping an adverb or a preposition into a span ("Call again." `call.v.03`, "insured with"
`insure.v.03`, "ten o'clock" `time.n.08`).

Two things about the gold's spelling, not the language's, hid most of the verbs: a verb's particle is marked as a word
of the sentence's grammar, so "filled *out*" left one word behind, and a verb of several words carries its form on the
first word where WordNet spells the base ("filled out" `fill_out.v.03`, "fell in love" `fall_in_love.v.01`). Counted
without either, verbs of several words are 31; with the particle counted back in, 60; with the first word's verb as a
spelling too, 238. Memory needs neither correction, holding the forms of a word of several words as it holds a word's
("grew up" under `grow up`, `WordRecord.forms`).

**A name of several words (79):** 252 of the gold's 420 (60.0%) are runs whose words the treebank writes as something
other than a name ("the European Constitution": "European" an adjective, "Constitution" a noun); only 74 (17.6%) have
every word written as a name. And a capitalised run is as likely to be one name either way — of the two-word runs it
calls one, 59.1% are where the words are written otherwise against 68.5% where they are written as names. The grammar
scores a run as sure as each of its words is held a name (`Lexicon._together`), which is why "the European
Constitution" is offered at -4.97 against -0.35 for "European" an adjective and "Constitution" a noun, and loses. Of
each word inside a capitalised run (4,214) the gold makes a name of 50.9%, a thing of 16.5%, a doing of 5.2%.

**A name right before a thing (79)**, 1,574 places: 44.1% one concept or no two things, 44.3% no link at all between
them, then `comes_from` 3.9%, `has_member` 3.1%, `part_of` 1.5%, `owned_by` 1.5%, `creates` 0.8% ("Do you like IKEA
furniture?"), `located_in` 0.3%. No link is the commonest reading, and the reader's `received_by` is none of them.

**`participles.py`** (2026-10-29, lab notebook (78)): of the words written as a participle or an -ing form in the
9,552 gold train documents, what the gold says where either a quality or a doing may stand, and what each way of
deciding catches. After a form of "be" an -ed word is a quality 27% of the time (179 of 664), before a noun 68% (27 of
40), after "be" an -ing word 2% (13 of 614). An adjective sense spelled as the word (WordNet) catches 95.5% of the
qualities after "be" and 96.3% before a noun, and calls a quality rightly 36.6% and 89.7% of the time; how often the
treebank writes the word as an adjective catches 57.0% and 66.7%, rightly 74.5% and 94.7%. So the sense says whether
the word may be a quality and the word's uses say whether it is one here, which is what the grammar does with a word
memory holds: the entry is offered because memory holds the class, and weighed by how often the word is used that way.
