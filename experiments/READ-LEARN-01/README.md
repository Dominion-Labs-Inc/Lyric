# READ-LEARN-01: whether Lyric's English gets better by reading

**Claim.** Reading teaches, as a book teaches its reader: how a sentence Lyric reads and is sure of used its words is
counted beside the treebank's (`grammar.GrammarView._learn_from_reading`, inside `grammar.reading_teaches`), so a word
met in reading is known from then on and how words are used is learned from what is read; memory keeps what was read
(`MemoryAgent.keep_grammar_learning`, `read_english`), so a start does not forget it. With nothing but reading between
them, the grammar reads held-out English better after reading than before.

**Why.** A person who reads gets better at the language without being taught each sentence's meaning. Lyric learned
English only from sentences taught with their meanings (the lessons, the PMB's gold sentences) and the treebank's
counts; what it read in a conversation, a document or a page taught it nothing.

**What it measures** (files only, no store): the grammar built as memory builds it (the English Web Treebank's
counts, WordNet, learned from the lessons and the PMB's gold training sentences), scored on the PMB's dev split as
GRAMMAR-01 scores it (whole meanings right, senses aside; facts' precision, recall and F1). It then reads the PMB's
silver documents, their text alone and never their meanings, none of them a dev sentence, each cut into sentences
after the marks most of whose uses end a treebank sentence (as `derived_reader.read_text` cuts a text where an
utterance can end), and is scored again on the same dev split after 2,000, 5,000 and 10,000 sentences. Scoring teaches
nothing; only what is read inside `reading_teaches` does.

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

| Run | Read | Read whole | New words known | Dev right whole | Facts precision / recall / F1 | Outcome |
|---|---|---|---|---|---|---|
| `20261025T151307Z` | 0 | | | 362 of 884 (40.9%) | 82.7% / 80.9% / 81.8% | |
| | 2,000 | 1,761 | 769 | 364 (41.2%) | 82.7% / 80.7% / 81.7% | |
| | 5,000 | 4,396 | 1,707 | 364 (41.2%) | 82.4% / 80.6% / 81.5% | |
| | 10,000 | 8,858 | 3,112 | 364 (41.2%) | 82.5% / 80.6% / 81.5% | **FAIL** 1/2 |

## Finding

Reading teaches words: 3,112 words met in reading are known after it that were not, and kept. It does not make the
dev split read better: two more meanings right whole after the first 2,000 sentences and none after, and the facts
read slightly less right (F1 −0.3). Counting how its own readings used each word, Lyric counts its own mistakes too.

Why it cannot: of the 884 dev sentences, 860 are read whole before any reading; what is missed is the meaning of
sentences read whole. Of the 300 misses GRAMMAR-01 kept (`20261024T203755Z_missed.json`), 66 differ from the PMB's
meaning only in a pronoun Lyric takes to point back ("He broke my nose!": `?previous`; the PMB writes an unknown of its
own). The rest are which link a phrase makes: "Tom taught at Harvard." read as Harvard taught, "Where are the Pribilof
Islands?" read as `equals`, "Boston, Massachusetts" as a group of two, a question's tag ("doesn't he?"), what an "if"
says. Which part of speech a word is, the only thing reading counted, decides none of these.

Learning from its own meanings does no better (a run outside the repository, 2,000 sentences, each sentence read
whole also learned from as if taught the meaning Lyric read it as): 364 right whole, F1 81.7%, the same as counting
uses alone. A reader that strengthens the meanings it already chooses keeps choosing them.

What a reader would need to learn from text: a phrase's link decided by what the things it joins are (a place, a
person, a time, an institution), and the kinds of things each verb's places and each preposition's object hold
learned from what is read. The grammar decides a preposition's link by the verb, the word and whether its object is a
time (`grammar.spell_out`, a `prep` piece), never by what else the object is, so nothing Lyric reads of a thing
can change how a sentence about it is read.
