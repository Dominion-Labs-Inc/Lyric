# GRAMMAR-01: what a sentence means, read by English's grammar

**Claim.** What a sentence means, in Lyric's meaning language, is read by a grammar: each word's category (what it
combines with and what it makes) and meaning, combined by general rules, the meaning of the whole built from the
meanings of its parts. What is learned from sentences taught with their meanings is only what words themselves hold:
the link each of a verb's places makes, what each preposition, possessive, adjective and adverb says, what "is a"
says.

**Why.** The composers before this one (`core/semantics/composition.py`, PMB-01, and the readers before it) learned
English as sentences remembered and read a new sentence by the remembered ones most like it. Real sentences are
rarely enough like any: measured on the PMB's dev split (2026-10-20), the most specific situations met decided 71% of
what a word stands for (2% wrong) but only 16% of what two words hold together; the rest was decided by coarser
situations, wrong 9% to 75% of the time. Teaching more did not change that (eight times the data, 0.2 points). A
compiler reads a program it has never seen, the first time, by a grammar and the meaning of each piece; the PMB's own
meanings were first made that way (a categorial grammar and Boxer).

**How** (`core/semantics/grammar.py`, `data/grammar/english.json`, lab notebook 2026-10-21 (31)):
- **The words.** English's grammar words ("the", "is", "who", "not", "if", "can") are taught as data, each way of
  reading one a category and a meaning: "is" before a doing (`(S[dcl]\NP)/(S[ng]\NP)`, during now), before a thing
  (`(S[dcl]\NP)/NP`, `equals`), and so on. Every other word's categories come from what kind of word it is and how it
  is used: a verb's forms and frames (with an object, two, a "to" clause), a noun, a name, an adjective.
- **The rules** combine categories, the same for every word: application, composition, the crossing only a word's
  entry allows ("was not a student"), words joined by "and", sentences one after another. Nothing in them is English.
- **Which reading.** Every reading the grammar allows is built once (a chart); of the readings of the whole, the one
  whose words are used most as they are used is taken, each word's evidence for each way of reading it counted from
  how it is used ("is" before a doing 180 times, before a thing 763), a word seldom seen read as words spelled like it
  are. Exact over the chart, never multiplied out, no cap.
- **The meaning** is spelled out in the meaning language as `docs/TEACHING.md` says it: a happening's time, a denied
  happening, a degree, a past state, a thing said of a kind (`isa(whale, mammal)`, `capable_of(bird, fly)`), what an
  "if" says must hold, whom "his" stands for (the nearest one before it it may be).
- **Learned** from the lessons and the PMB's gold training sentences, each read by the grammar and its meaning's terms
  aligned to its words: per verb and place, per preposition (and per verb with it), per noun owned, per adjective,
  per adverb, per what "is" joins. A word whose own uses say nothing takes what is said of the kind memory holds it to
  be ("Austrian": of Austria, a country, as "British" is of Britain); nothing said of either, the grammar's link
  (`linking`; a preposition held as its word). Each link decided is counted by where it came from.

**What it measures** (files only, no store): the PMB's dev split as PMB-01 measures it, the same three ways (strict;
senses aside, each kind and name a word says named as the grammar names that word, a kind on a line of no words of
its own named by its thing's word, as PMB-01 names them; the one spoken of before unnamed), whole meanings right and
facts' precision, recall and F1; how many sentences the grammar read whole and gave a meaning, and why each missed one
was missed (not read; read, the meaning language has no words for it yet; read wrong); and of the links decided, by
the word's own uses, by what memory holds it a kind of, by the grammar's rule, how many the meaning holds. The prose of
UNDERSTANDS-PROSE-01 read, kept beside the record.

| Bar | |
|---|---|
| Learned from the lessons and the PMB's gold training sentences | more dev meanings right whole, senses aside, than the composer learned from the same (PMB-01 `20261020T210127Z`: 33.6%) |
| | more right, strict, than the composer (16.1%) |
| Each word's category chosen beside the words around it, from the PMB's checked derivations (from `20261026T043416Z`) | more dev meanings right whole, senses aside, than each word's category chosen out of context (`20261025T173519Z`: 366/884, 41.4%) |

Words come from files, standing in for memory (`words.py`): how often each word is used each way, each verb's forms
and frames, from UD English EWT's training part; names, kinds, what an adjective is of, times and names of words
together, from WordNet. From `20261026T043416Z` what each word takes beside the words around it comes from the PMB's
gold CCG derivations (release 4.0.0, `teaching_sources.PMBDerivationSource`: 8,679 sentences, release 5.1.0's dev and
test documents never held), held before the taught sentences are learned from, as main holds them
(`GrammarView.hold_derived`). On main the same questions go to memory.

**Run** (from the Lyric folder; about two minutes):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/experiment.py
```

with `test_data/syntax/UD_English-EWT` (`--data DIR`; the counts read from it kept beside it,
`grammar_words_held.pkl`), the PMB release 5.1.0 in `test_data/semantics/pmb/pmb-5.1.0` (`--pmb DIR`; never pushed)
and release 4.0.0's English gold extracted in `test_data/semantics/pmb/pmb-4.0.0` (never pushed),
the lessons in `data/lessons/`, and WordNet for `nltk`. The Parallel Meaning Bank: University of Groningen,
annotations ODC-BY 1.0; attribute it (Abzianidze et al. 2017) in any public use of it or of what is built from it.

**Results:** `results/<UTC timestamp>.json` and `.md`, the prose read (`_prose.json`) and 300 of the dev sentences
not read right senses aside (`_missed.json`).

**Runs** (dev: 884 sentences said whole of 1,194; learned from the lessons and the PMB's gold training sentences):

| Run | Read whole / given a meaning | Strict | Senses aside | Unnamed | Facts F1 (senses aside) | Links: own / kind / rule, share the meaning holds |
|---|---|---|---|---|---|---|
| `20261021T004110Z` | 854 / 845 | 19.5% | 39.7% | 49.7% | 80.9% | 1,395 (80.9%) / 101 (63.4%) / 153 (49.0%) |
| `20261021T012601Z` | 854 / 845 | 20.1% | 39.8% | 49.9% | 80.8% | 1,385 (80.3%) / 79 (68.4%) / 178 (43.3%) |
| `20261021T025251Z` | 857 / 852 | 20.0% | 39.3% | 49.4% | 80.6% | 1,409 (79.9%) / 76 (65.8%) / 176 (42.6%) |
| `20261024T181237Z` | 860 / 856 | 20.5% | 41.0% | 52.1% | 81.8% | 1,414 (80.3%) / 81 (70.4%) / 173 (43.9%) |
| `20261025T173519Z` | 860 / 856 | 20.8% | 41.4% | 52.7% | 81.9% | 1,344 (82.9%) / 148 (56.8%) / 173 (43.9%) |
| `20261026T043416Z` | 865 / 860 | 23.1% | 42.8% | 54.1% | 82.4% | 1,400 (81.4%) / 162 (57.4%) / 162 (42.6%) |
| `20261026T044408Z` | 865 / 860 | 23.0% | 43.2% | 54.5% | 82.4% | 1,396 (81.7%) / 163 (57.1%) / 162 (43.2%) |
| `20261026T125030Z` | 865 / 860 | 23.0% | 43.6% | 55.0% | 82.5% | 1,391 (82.1%) / 164 (57.3%) / 167 (41.9%) |
| `20261026T182351Z` (`--without-structure`) | 865 / 860 | 23.0% | 43.6% | 55.0% | 82.5% | 1,392 (82.0%) / 164 (57.3%) / 165 (42.4%) |
| `20261026T184453Z` | 865 / 860 | 22.6% | 43.3% | 54.8% | 82.6% | 1,395 (81.7%) / 169 (55.6%) / 164 (42.1%) |

From `20261026T043416Z` each word's category is chosen beside the words around it, as the PMB's checked CCG derivations
say (`Lexicon.hear_derived`, `_in_context`, `_frame_evidence`; lab notebook 2026-10-26 (52)): each derivation word
named by the grammar's own entries, its way weighed by the derivations' uses of it (a word they never hold as before)
and by the word before and after it; a verb's frame by the word after it. `20261026T044408Z`: each word's evidence its
share of the word's ways, and a clause taken with no "that" named as the grammar's clause. Of the dev words, the
reading now uses the derivation's way for 90.3% (each word's evidence alone 92.7%, out of context 78.3%), its frame
for 93.7% of verbs; the derivation's category, compared strictly, 66.7% from 64.0%. The grammar reads back 424 of
1,000 taught sentences, from 414 (`diagnostics/taught_fit.py`). From `20261026T125030Z` a taught sentence whose derivation is held
learns its verbs' places and its prepositions' links from the derivation's structure, each link as its meaning says
(`Grammar._learn_places_derived`; lab notebook 2026-10-26 (53)).

From `20261026T184453Z` which word takes which is weighed by the structure view's joins (`Grammar._joined`,
`StructureView.joins`; lab notebook 2026-10-26 (55)): each combination adds the view's log likelihood that its one
word is joined to the other, each stretch by the word it is about as the treebanks join words, for words that do not
only mark another. Before, two readings joining the same words otherwise scored the same, and the chart kept the first
it built. On published prose held out (UD English PUD, 200 sentences, `diagnostics/prose_joins.py`) the readings join
68.0% of content words as the analysis by hand does, from 54.9%; here dev moves within noise (43.6% -> 43.3%, F1 82.5%
-> 82.6%), the PMB's five-word sentences having little to join otherwise. `--without-structure` reads as before. The
PMB derivations' own joins, counted, were tried first and measured worse on prose (lab notebook (55)); every sentence
missed is saved (`<stamp>_missed.json`), as met.

From `20261025T173519Z` a preposition's link is decided by what its thing is where no sentence taught it of the very
doing or thing it is said of (`Lexicon.selected`, `prep_to`: "Vance worked with Hooper." with a person, "Tom taught at
Harvard." where; lab notebook 2026-10-25 (50)): 7 links right that were wrong, 1 wrong that was right ("The chicken is
pecking at Tom.": "at" a name memory holds nothing of read as where).

From `20261021T012601Z` the words are read as main reads them (`grammar_words.HeldWords`: the treebank's sentences as
main holds them, analysed, with no features; the forms each word is written in; WordNet's links as taught), not from
the treebank's features directly. From `20261021T025251Z` the PMB's meanings say an order as a request and "Tom is a
workaholic." as `isa(tom, workaholic)` (a role is the kind said), as the lessons do (`pmb_meanings`); the composer
measured on the same (PMB-01 `20261021T025534Z`, lessons and gold): 15.7%, 32.9%, 39.7%, F1 78.7%. The lessons, learned
from, read right whole 47.7% (52.6% senses aside), from 31.8%: the meaning language's conventions said (lab notebook
2026-10-21 (32)). At `20261024T181237Z` a thing said of a doing with no preposition is read as a preposition's thing is
("One morning the dog ran to the park.": `during`), as often as the treebank says its word so (`obl:unmarked`); against
the run before it on the same code otherwise (`20261021T173701Z`: 359 right senses aside, F1 81.3%), 362 and 81.8%
(lab notebook 2026-10-24 (45)).

The composer, same dev set, PMB-01: learned from the lessons and gold 16.1% / 33.6% / 40.6%, F1 79.3%; with the
silver sentences too (22 times the data) 16.7% / 36.4% / 44.0%, F1 82.3%. Learned from the gold sentences alone (no
lessons, scratch, 2026-10-21) the grammar read 20.4% / 40.6% / 50.7%: where the lessons and the PMB say one thing two
ways (`isa(rice, food)` against `equals`; `located_at` against `located_in`) the dev set holds the PMB's way. The
lessons, held out, read right whole: 23.9%; learned from: 31.8%.

**On a store, with the comparison's conventions aligned (2026-10-28, lab notebook (70)).** `on_store.py` reads the dev
sentences with the reader a store holds after a warm (read only); `taught_words_test.json` lists 100 dev documents
whose words are all among 228 (77 with a gold meaning), taught to lyric_dev2 as words recorded whole. Two comparisons
added beside the others, applied alike to the gold and the reading: `pronouns_as_unknowns` (Lyric reads "he", "it",
"this" as the one spoken of before, `?previous`; the PMB writes an unknown) and `named_by_their_words` (a kind or
quality named by the word of the sentence it is a sense of, so which sense was chosen is set aside; `senses_aside`
takes a word's first sense and counted a sense chosen from a verb's places wrong). On the 77: main (12,544 UD
sentences) 33 by their words (F1 73.7%), 29 kinds aside (76.1%); lyric_dev2 (245 words recorded whole, 6,137 PMB
sentences recorded whole) 35 (75.7%), 33 (77.2%).

**Words joined by hyphens (2026-10-29, lab notebook (72)).** `hyphenated_test.json` lists the 25 dev documents with a
word joined by a hyphen (15 with a gold meaning), their words taught to lyric_dev2. `words_of_sentence` counts a
hyphened word as a word of the sentence in each of its spellings ("bullet-proof", `bulletproof`, "bullet proof"), so
"by their words" sets its sense aside as it does any word's; the 77 by it: lyric_dev2 37 (F1 77.3%) before the rule,
37 (77.7%) after; main 33 (73.7%) before, 32 (73.0%) after (main holds no hyphened word: lab notebook (72)). The hyphen
set: lyric_dev2 4 (56.7%) to 7 (80.0%); main 3 (53.6%) to 1 (59.7%).

**Degree (2026-10-29, lab notebook (73)).** `degree_test.json` lists the 20 dev documents whose gold says a quality's
degree ("very smooth"), their words taught to lyric_dev2. A derivation's word is now named by the grammar's entry its
category is most exactly (`_exactness`): "very" had been counted an adverb of a doing in every derivation. Degree set:
lyric_dev2 1 to 12 by their words, main 2 to 13; the 77: lyric_dev2 37 to 39 (F1 78.9%), main 35 to 38 (78.7%), main
counted after its WordNet word classes were taught whole.

**Denials (2026-10-29, lab notebook (74)).** `denial_test.json`: the 13 dev documents denying a thing ("nobody",
"nothing", "not a"). Each set is now read in one run of all four together and scored per set (the gold made afresh by
the conversion of the day, `pmb_meanings`, which now says a thing said not to be a kind denied with its qualities). By
their words: lyric_dev2 the 77 42 (F1 80.2%), denials 6 of 13; main 39 (79.1%), 4 of 13.

**"A kind of" (2026-10-29, lab notebook (75)).** `kind_of_test.json`: the 10 dev documents with "kind of" and a gold
meaning. By their words: lyric_dev2 5 of 10, the 77 43 (F1 81.0%); main 6 of 10, the 77 40 (79.9%).

**Times of the clock (2026-10-29, lab notebook (76)).** `clock_test.json`: the 9 dev documents saying a time of the clock
with a gold meaning. By their words a time's half of the day is set aside where the sentence's words do not say it
(the PMB's annotators chose it: "at six" 18:00). Clock set: lyric_dev2 6 of 9, main 5; the 77: lyric_dev2 44 (F1
81.5%), main 40 (79.9%).

**A verb's places by its frame (2026-10-29, lab notebook (77)).** A verb's place linked by the VerbNet frame of the
sense read that best fits the places said (`Lexicon.framed`), where no taught sentence said it. Research first:
`diagnostics/verb_places.py`, each verb place of the PMB's 9,552 train documents against the PMB's link (objects 80.8%
now, 85.4% by the most used sense's frames, 86.5% by the gold sense's). lyric_dev2 re-taught its verbs: the 77 46 (F1
82.1%); main 40 (79.9%), unchanged.

**Several words that are one word (2026-10-29, lab notebook (79)).** `several_words_test.json`: the 101 dev
documents whose gold makes one concept of several words that is not a name (61 things, 25 verbs, 11 qualities, 9
adverbs). Research first: `diagnostics/several_words.py` over the 9,552 train documents — 1,586 concepts are one word
of several (420 a name, 747 a thing, 238 a verb, 105 an adverb, 76 a quality), and WordNet spells every one of the
1,166 that are not names as one word, so memory taught from WordNet holds them all; against that, of the 44,993 runs
of two words the sentences say only 3.7% are one concept. Built: `Lexicon._together` asks memory what it holds
several words as (`Words.known_words`, `MemoryAgent._held_names`: each kind of word, with its name, in place of the
two questions asked of one class each) and offers that kind's entries, so a quality ("fed up"), an adverb ("in
vain") and a thing are read as one word and not a thing alone; a verb of several words is asked for under the words
as written, where it is held, and not only under the verb's name, which is the thing's ("grow" `cultivate grow`, so
"Where did Golda Meir grow up?" read no whole); a run may open with a capital ("Easter egg", "At last, we arrived");
and it is asked with the last word as the word it is a form of ("gold medals" `gold medal`). By their words on
lyric_dev2, the 75 words taught and the rule: the several-words set 13 of 87 to 44 of 101, the 77 49 to 50, hyphen 6
to 5 (the one loss is the measure's naming of a sense, not the reading), every other set unmoved. Found, not fixed: a
name of several words, which the grammar scores as sure as each of its words is held a name although the gold says a
capitalised run is one name 59% of the time whatever its words are usually written as.

**Participles (2026-10-29, lab notebook (78)).** `participle_test.json`: the 18 dev documents whose gold says a
quality by a word written as a participle or an -ing form, standing where either a quality or a doing may stand. A
participle says a quality where memory holds the word as an adjective, which is a word of its own in WordNet
(`chained.s.01`, `developed.a.02`): lyric_dev2 held "chain" and not "chained", so every entry was the verb's; its 18
such words are taught now. Research first: `diagnostics/participles.py` over the 9,552 train documents — after a form
of "be" an -ed word is a quality 27% of the time and before a noun 68%, an adjective sense spelled as the word catches
95% of the gold's qualities and the treebank's adjective uses say whether it is one here. Built: an Experiencer said
beside a doer is what the happening is done to (`pmb_meanings.happening_link`, in the conversion and in VerbNet's
frames; the PMB's gold writes it so in every one of the 45 documents saying both), so "I've been stung by a hornet."
is done to the speaker and done by the hornet. By their words on lyric_dev2: the 77 46 to 49 (F1 82.1% to 84.1%),
degree 12 to 13 of 20, the participle set 9 of 18, every other set unmoved, nothing lost. `on_store.py` now takes
several sets at once (`WORDS_TEST` separated by commas) and scores each on its own.
