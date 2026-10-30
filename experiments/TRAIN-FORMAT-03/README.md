# TRAIN-FORMAT-03: a vocabulary taught words first, into an instance holding nothing

**Why.** TRAIN-FORMAT-01 taught one sentence, TRAIN-FORMAT-02 one word. This is the first run of the order itself on
a store that held nothing: closed classes, then the words a set of sentences uses recorded whole, then those
sentences recorded whole, then what the store reads and says. The owner (2026-10-30), of the main instance all models
are made from: teach the words and their meanings and structures as the first session, nothing else, then the
sentences -- the order determined to work better than teaching sentences first. Main had never had it; it had 0 word
records, 0 sentences recorded whole and 0 word groups before the wipe of 2026-10-30.

**What was taught, in three passes through the one teaching path** (`scripts/teach.py`, `lyric_db`, wiped to zero
that morning):

| | taught | teaching | reacting | wall |
|---|---|---:|---:|---:|
| 1 | `--source closed-classes`: 264 words' classes in 15 finite classes, 11 sentences saying what each punctuation mark is for | 8.6 s | 2,191 s | 37 min |
| 2 | `--source records`: 11 words recorded whole, the whole vocabulary of the four sentences | 2.4 s | 14 s | 57 s |
| 3 | `--source records`: 4 sentences recorded whole | 0.9 s | 13 s | 55 s |

10 of the 11 words were held; `.` was refused for "no form", which is right -- `ClosedClassSource` states its class
and a sentence recorded whole skips punctuation when it teaches classes. 4 of 4 sentences were held. Competence in
`general` went 0.611 -> 0.711 -> 0.794 over the three passes, every reviewed question answered right.

**THE FIRST TEACH INTO AN EMPTY STORE DOES NOT HANG, AND ITS COST IS NOT PROPORTIONAL.** 2,191 s of reacting after
pass 1 against 14 s after pass 2 and 13 s after pass 3, with pass 2 writing more memories than pass 1 wrote facts:
the long one is the substrate perceiving its own first boot (62 documents, 63 percepts, 61 memory_media, 804 hot
rows), paid once. An earlier 28-minute teach that looked non-terminating was this.

**What it reads and says** (`check.py`, read only; `sure` is `Reading.sure`, the share of every whole reading of the
sentence that is this one; `SAID sure` is the new `how_surely` out-parameter of `Grammar.say`):

| given | read | says first | sure |
|---|---|---|---:|
| `This stinks.` | `done_by(?v0, ?previous) & instance_of(?v0, reek)` | `They stinks.` | 1.000 |
| `I am intelligent.` | `has_property(?speaker, intelligent)` | `I is intelligent.` | 1.000 |
| `The whistle blew.` | `done_by(?v0, ?v1) & instance_of(?v1, happening whistle) & instance_of(?v0, exhaust blow) & precedes(?v0, ?now)` | `The whistle blew.` | 0.997 |
| `They misled me.` | `done_by(?v0, ?previous) & done_to(?v0, ?speaker) & instance_of(?v0, misinform)` | `They misled i.` | 1.000 |
| `The person stinks.` never taught | `done_by(?v0, ?v1) & instance_of(?v1, person) & instance_of(?v0, reek)` | `The people stinks.` | 0.562 |
| `I misled the whistle.` never taught | `done_by(?v0, ?speaker) & done_to(?v0, ?v1) & instance_of(?v0, misinform)` | `I misled the whistle.` | 1.000 |
| `The whistle is intelligent.` never taught | `instance_of(?v0, happening whistle) & has_property(?v0, intelligent)` | `The whistle being intelligent.` | 1.000 |
| `This sparkles.` CONTROL, `sparkle` never taught | `done_by(?v0, ?previous) & instance_of(?v0, sparkles)` | `They sparkles.` | 0.915 |
| `The whistle juggled Tom.` CONTROL, `juggle` and `tom` never taught | `done_by(?v0, ?v1) & done_to(?v0, tom) & instance_of(?v0, juggled)` | `The whistle juggled Tom.` | 0.898 |

Warm 8 s, every read 0.0 s, every say 0.0-1.3 s, from 10 words and 4 sentences.

**Four findings.**

**(1) Composition is real from ten words.** All three arrangements never taught read whole and said the sentence they
were given back, `I misled the whistle.` among them. The sentence layer is not a lookup.

**(2) The sentence layer covers the word layer's missing forms.** The prediction written before the run was that
`This stinks.` and `They misled me.` would fail, `stink`'s record holding only `stink` and `stunk` and `mislead`'s
only `mislead` and `misleading` -- UD EWT and GUM attest what an analyst happened to write, which is the root of the
`word_forms` gap measured on the old main (3,703 bases with forms against 94,262 with classes). Both read. A sentence
recorded whole teaches the written form as well as the base (`MemoryAgent._learn_record_words`), so the sentence
layer supplies the forms the word layer lacks. The prediction was wrong.

**(3) HOW SURELY IS NOT HOW WELL.** `how_surely` reports `Reading.sure`, which is 1.000 for a sentence with exactly
one whole reading -- so `They stinks.`, `I is intelligent.` and `They misled i.` all score 1.000, and `They stinks.`
is ranked above `This stinks.` The number is honest about what it measures and does not rank good output above bad.
Only `The person stinks.` discriminated at all (0.562 `people`, 0.266 `person`, 0.142 `persons`), and it still put
the wrong one first. Saying has no agreement between a subject and a finite verb and no case for pronouns, which is
the `data/grammar/english.json` defect where `i`/`me`/`myself` are one `NP.?speaker` and `you`/`yourself` one
`NP.?listener`; this run shows it is not a matter of how much has been taught.

**(4) THE CONTROLS DID NOT FAIL.** A sentence holding a word the store has never seen reads whole at 0.915 and 0.898,
with a concept minted from the surface string (`instance_of(?v0, sparkles)`), and `tom` resolved from nothing --
confirmed by query: no `word_class` row and no concept for `sparkles`, `juggled` or `tom`. `Reading.sure` is
sureness about STRUCTURE among the readings built, not about vocabulary, so an unknown word costs it nothing. The
0.5 that an unknown construction sits at is the construction prior, a different number; nothing reports doubt about
a word never seen.

**A defect of the builder, found and fixed here.** `build.py` took each word under what the sentence record calls its
lemma. The PMB's gold annotation sometimes writes the lemma as the form: of the 182 words of 62 gold sentences, 8
records were refused for "no form" -- `.` `?` `"` `!`, which is right, and `sucks` `ran` `wiped`, which is not,
because UD's form rows are keyed by base and the real bases `suck` `run` `wipe` were never in the vocabulary at all.
Three of the 62 sentences therefore had a verb no word record ever taught. The builder now takes the base WordNet
gives for the class the sentence used the word as (`morphy`, the same authority the record's senses come from) and
asks for no record at all for punctuation and symbols. `pinocchio` holds no forms either and WordNet knows no base
for it: a name outside the treebanks is taught by the sentence layer, which keeps names' classes and what they name.

**Run**

```
OUT=data/records/pmb_gold.jsonl HOW_MANY=100 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-03/build.py
./venv_lyric/bin/python3 scripts/teach.py --source closed-classes --domain general
./venv_lyric/bin/python3 scripts/teach.py --source records --records data/records/small_11_words.jsonl --domain general
./venv_lyric/bin/python3 scripts/teach.py --source records --records experiments/TRAIN-FORMAT-03/small_4_sentences.jsonl --domain general
./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-03/check.py
```

`HOW_MANY=0` for the whole gold split. The word records are not committed: one is about half a megabyte and
`build.py` rebuilds them from the PMB, WordNet and UD in `test_data/`. The four sentence records are
(`small_4_sentences.jsonl`, 5 kB).

**Results:** `results/` holds the three teaching logs and the read-and-say log of 2026-10-30, as printed.

**Open, for the owner:** the closed-class source carries 11 content sentences whose nouns and verbs (`comma`,
`separates`, `clause`) only a word session teaches, so 7 of them were told and not read in pass 1. They carry no
`blamed`, so no evidence was written against any class, and teaching the source again after the word session would
land them.
