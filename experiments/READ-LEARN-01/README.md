# READ-LEARN-01: whether Lyric's English gets better by reading

**Claim.** Reading teaches, as a book teaches its reader: how a sentence Lyric reads and is sure of used its words is
counted beside the treebank's (`grammar.GrammarView._learn_from_reading`, inside `grammar.reading_teaches`), so a word
met in reading is known from then on and how words are used is learned from what is read; memory keeps what was read
(`MemoryAgent.keep_grammar_learning`, `read_english`), so a start does not forget it. From `20261025T173519Z`, what a
sentence read says a thing is ("Tom is a teacher.") memory takes in and the grammar knows at once
(`MemoryAgent.link_concepts`, `Words.hear_kind`), and a preposition's link is decided by what its thing is
(`grammar.Lexicon.selected`). With nothing but reading between them, the grammar reads held-out English better after
reading than before.

**Why.** A person who reads gets better at the language without being taught each sentence's meaning. Lyric learned
English only from sentences taught with their meanings (the lessons, the PMB's gold sentences) and the treebank's
counts; what it read in a conversation, a document or a page taught it nothing.

**What it measures** (files only, no store): the grammar built as memory builds it (the English Web Treebank's
counts, WordNet, learned from the lessons and the PMB's gold training sentences), scored on the PMB's dev split as
GRAMMAR-01 scores it (whole meanings right, senses aside; facts' precision, recall and F1). It then reads the PMB's
silver documents, their text alone and never their meanings, none of them a dev sentence, each cut into sentences
after the marks most of whose uses end a treebank sentence (as `derived_reader.read_text` cuts a text where an
utterance can end), and is scored again on the same dev split after 2,000, 5,000 and 10,000 sentences. Scoring teaches
nothing; only what is read inside `reading_teaches` does. Standing in for memory, the experiment gives the grammar's
words each kind a sentence read whole tells of a thing (`told_kinds`); a named thing's as `instance_of`, as memory holds
a particular (from `20261025T192738Z`; on main a text Lyric reads for itself still hands a name's kind on as `isa`, see
the finding).

| Bar | |
|---|---|
| More dev meanings right whole after reading than before (senses aside) | |
| The facts read no less right after reading (F1) | |

**Run** (from the Lyric folder; about 90 minutes, most of it the reading):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/READ-LEARN-01/experiment.py [--read 2000,5000,10000]
```

with `test_data/semantics/pmb/pmb-5.1.0` and `test_data/syntax/UD_English-EWT` (datasets, not in the repository).

## Runs

Dev right whole of 884 (senses aside) and facts F1, before reading and after each stretch:

| Run | What reading taught | 0 | 2,000 | 5,000 | 10,000 | Outcome |
|---|---|---|---|---|---|---|
| `20261025T151307Z` | how words are used | 362, 81.8% | 364, 81.7% | 364, 81.5% | 364, 81.5% | **FAIL** 1/2 |
| `20261025T173519Z` | and what things are, a name's kind as `isa`; prepositions decided by kinds | 366, 81.9% | 369, 81.9% | 358, 81.5% | 357, 81.4% | **FAIL** 0/2 |
| `20261025T192738Z` | a name's kind as `instance_of` | 366, 81.9% | 369, 81.9% | 369, 81.7% | 369, 81.8% | **FAIL** 1/2 |
| `20261025T201431Z` | uses counted only of words the treebank holds nothing of (not kept) | 366, 81.9% | 367, 81.8% | 365, 81.8% | 362, 81.5% | **FAIL** 0/2 |

New words known after 10,000: 3,112, 3,118, 3,106, 3,093. Kinds of things taken in: none, 1,059, 1,021, 1,097.

## Finding

Reading teaches words: about 3,100 words met in reading are known after 10,000 sentences that were not, and kept. It
does not make the dev split read better: every way tried moves it a few sentences either way, and the facts read are
slightly less right.

**How words are used** (`20261025T151307Z`): of the 884 dev sentences, 860 are read whole before any reading; what is
missed is the meaning of sentences read whole. Of the 300 misses GRAMMAR-01 kept (`20261024T203755Z_missed.json`), 66
differ from the PMB's meaning only in a pronoun Lyric takes to point back ("He broke my nose!": `?previous`; the PMB
writes an unknown of its own). The rest are which link a phrase makes: "Tom taught at Harvard." read as Harvard taught,
"Where are the Pribilof Islands?" read as `equals`, "Boston, Massachusetts" as a group of two, a question's tag
("doesn't he?"), what an "if" says. Which part of speech a word is decides none of these. Learning from its own meanings
as if taught them (a run outside the repository, 2,000 sentences) did the same as counting uses: 364, F1 81.7%. A
reader that strengthens the meanings it already chooses keeps choosing them.

**What things are** (`20261025T173519Z` on). The grammar now decides a preposition's link by what its thing is
(GRAMMAR-01 `20261025T173519Z`: 362 → 366 right whole), so what Lyric learns a thing is can change how a sentence
about it reads. Read as `isa`, a name's kind made the name a kind to the grammar (`GraphKnowledge.capitalized`: held a
kind of something and an instance of nothing, a noun): "Tom is a competent nurse." was read, and after it "We trusted
Tom." told of trusting a tom; nine dev sentences about Tom were lost (`20261025T173519Z`, 357). Held as `instance_of`, a
particular's kind as memory holds one, Tom stays named, and what reading told of him is used: "The chicken is pecking
at Tom." reads as done to Tom, a person, no longer where the pecking was (`20261025T192738Z`, a scratch diagnostic on
5,000 sentences: 4 right that were wrong, 1 wrong that was right). Counting uses only of words the treebank holds
nothing of (a word it holds is read as its counts say, so its reading counted is its counts counted again) did worse,
not better (`20261025T201431Z`), and is not kept.

**Most of what reading takes in as what things are is a misreading.** Of the 531 kinds taken in by 5,000 sentences,
a few were said ("Tom is a competent nurse.": Tom a nurse; "Amman, the capital": a capital); most come from the
grammar's reading of a kind followed by a word as that kind named so ("the river Thames", "the function sorted",
`Grammar._combine`, "named"), firing on a compound or a misparse: "The oil spill polluted the bay." took a spill to be
an oil, "I had to stop Tom from ..." Tom a stop, "... saw Mary and John kissing." Mary a saw, "between 27 September and
3 October" September a place. They pile up as more is read, and the dev split reads worse by 10,000 sentences
(`20261025T201431Z`: 362). On main the same reading writes the same kinds to the world when Lyric reads a text for
itself (a look-up's page: lyric_dev holds `balancer isa into` from one, 2026-10-21); a person's document and a
person's telling are held as theirs and do not reach the grammar.

**Next.** What a sentence says a thing is ("is", or between commas) is what memory takes in as what it is, a named
thing's as an instance, never what the grammar took a compound to be: the reading's names and what said each fact
carried from the grammar to where a text read for itself is taken in. And the grammar's compounds ("oil spill") read
as one kind of thing, not a kind and its name.
