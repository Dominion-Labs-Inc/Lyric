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

---

## Read and said again after the agreement path was fixed (2026-10-30, lab notebook (90))

The same `check.py`, same store, nothing re-taught: `results/check_after_agreement.log` beside the first
`results/check.log`. Finding (1) above -- "how surely is not how well" -- is what five defects in agreement turned
out to be, every one of them scoring **no evidence exactly as it scores perfect agreement**, `0.0`.

| given | said first, before | said first, after |
| --- | --- | --- |
| `I am intelligent.` | `Me are intelligent.` | `I am intelligent.` |
| `We are intelligent.` | `Ourselves is intelligent.` | `We are intelligent.` |
| `The person stinks.` | `The people stinks.` | `The person stinks.` |
| `This stinks.` | `They stinks.` | `He stinks.` |
| `He is intelligent.` | `They are intelligent.`, with `Him is`, `Them is`, `Her is` among the eight | `They are intelligent.`, those three gone |

`They are intelligent.` for a meaning that says only "the one spoken of before" is a preference and not an error:
the meaning carries no number, and `He is intelligent.` is in the eight.

**What each was.** (a) A subject form no subject anywhere was ever written with was passed over by `_agreed`, so
every accusative pronoun agreed with every verb as well as it is possible to agree -- of this store's 11,295
subjects, three are accusative. (b) `_said_by` found a grammar word only for the speaker or the listener, so
`we`/`us`/`ourselves`, which carry `NP.g` with `has_member(g, ?speaker)`, were never found, never weighed and never
kept apart. (c) The copula's forms share one `use`, so frequency docked `am` 2.5 nats against `are`, and agreement
is capped at nothing and could never repay it. (d) Nothing said what number a demonstrative or an indefinite pronoun
is. (e) With no subjects held of a verb the estimate is exactly 1 for every subject, and this store holds a subject
of 19 finite forms.

**Still open here.** `They misled me.` is said back as `They misled i.`: nothing weighs an object's case, memory
counting subjects, determiners' nouns and what a copula said a thing to be and nothing else. And the controls'
`This sparkles.` says `They sparkles.`, `sparkles` being minted from its own letters with no held form, so there is
nothing to weigh it by -- which is the same finding as (2) above, now with a name.

**Not confirmed end to end.** The demonstratives' and indefinites' stated forms reach memory only when
`--source closed-classes` is taught again, a live write and the owner's to start, so this store still says
`This am intelligent.` for a third-person meaning. Run through the real `_agreed` against this store's own subject
counts, every stated form picks the right copula (`this` → `is` 0.00, `am` -5.76; `these` → `are` 0.00, `is` -3.00).

## A sixth and seventh way, and a measurement that needed no teach (2026-10-30, lab notebook (91))

**The forms can be measured without being taught.** `ClosedClassSource.word_forms()` yields nothing but `WordForms`
records and `HeldForms.hold` is pure in-memory, so holding the stated paradigm on a live read-only view of this store
is a faithful stand-in for teaching it: the same objects, the same reader, the same `say`, and nothing written. This
store holds forms for 39 words; the 77 stated forms over them bring it to 53.
`results/check_raised_subject.log` is that run, each sentence said before and after the forms are held.

| given | before the stated forms | after |
| --- | --- | --- |
| `Nobody is intelligent.` | `Nothing am intelligent.` | **`Nothing is intelligent.`** |
| `I am intelligent.` | `I am intelligent.` | `I am intelligent.` |
| `The person stinks.` | `The person stinks.` | `The person stinks.` |
| `The people stink.` | `The people stink.` | `The people stink.` |

**Both changes are necessary and neither suffices.** The weighing below makes agreement apply to a denying subject at
all; the stated forms give `nothing` the number agreement needs. With the weighing in and the forms held out, the
same meaning still says `Nothing am intelligent.`, which makes the closed-class teach load-bearing rather than
bookkeeping — the first output that moves only when the stated forms are there.

**What was wrong.** The words that deny are stated **already raised** (`nothing`, `nobody`, `none`:
`S[F].e/(S[F].e\NP.x)`), so they take their verb's phrase rather than being taken by it, and agreement was weighed
only at the two rules where a subject is *taken*, both of which require the subject to be one category and not a
function. While `Nothing am intelligent.` was built agreement was asked 58 times and `am` was not one of the
questions. Weighing forward application alone changed nothing, because the cheapest derivation composes the subject
with the copula before the copula takes its adjective (`>B`, -0.084) instead of applying to the finished phrase
(`>`, -5.839 with the penalty in): **the unweighed route was the cheap one, and only `am` was ever offered to
`nothing` among the copula's finite forms.** Both rules now weigh it.

**Withdrawn from the section above.** Its before/after rows for `He is intelligent.` and the demonstratives compared
strings against a meaning that cannot distinguish them: `he`, `she`, `they`, `this`, `these` and `that` all read to
`has_property(?previous, intelligent)`, carrying no number, person or gender. The ungrammatical outputs are gone;
the sentence identity was never recoverable by any fix to saying.

**Still open here.** `Someone is intelligent.` is said back as `Anybody intelligent.`, a sentence with no verb which
**reading takes back to the meaning asked for** (`results/check_offered_back.log` holds every whole offered to
reading and what reading made of it) — reading being too permissive, not saying. `Everybody is intelligent.` says
`Person is intelligent.`

## A thing's case belongs to the place it stands in (2026-10-30, lab notebook (92))

Objects are counted when a teach runs, so `results/check_places_and_objects.log` fills the new table from the same
treebanks the teach reads and holds it on a read-only view of this store — the stand-in above, applied to a table
instead of a paradigm. **21,034 things stood after a verb in 34 kinds over 3,361 forms.**

| given | before | after |
| --- | --- | --- |
| `They misled me.` | `They misled i.` | **`They misled me.`** |
| `We misled them.` | `Ourselves misled this.` | **`We misled him.`** |
| `This sparkles.` | `They sparkles.` | **`He sparkles.`** |
| `They sparkle.` | — | **`They sparkle.`** |

No earlier result moved: `I am intelligent.`, `We're intelligent.`, `Nothing is intelligent.`,
`They're intelligent.`, `The person stinks.`, `The people stink.` and `You're intelligent.` are all unchanged.

**What was wrong.** An English verb in the past agrees in nothing — `misled` is `Tense=Past|VerbForm=Fin` — so the
subject's weighing had nothing to work with and returned the same nothing for every subject, taking the subject's
case with it. What a verb agrees in and what marks a place are now weighed apart, by what memory already holds: a
verb is written with a number and a person and never with a case. And what stood after a verb was counted nowhere,
so a fourth table now runs beside the three, filled in the treebank pass that already walked objects to find which
features mark a case and then dropped them.

**For the re-teach.** The object table writes when a teach runs, so a store taught before this change holds none of
it and the measurements above need the stand-in; a store taught after holds it for real. This is the change that
had to land before the full re-teach rather than after.

**Closed since (notebook (94)).** `They misled us.` was said back as `They misled ourselves.`, and the two
paragraphs that stood here named the wrong cause twice over. What stopped it: saying could not say a thing twice in
one sentence, and `ourselves`, `myself`, `yourself` and `yourselves` were stated as the very entry of `us`, `me`
and `you`, saying nothing of standing for a thing already in the sentence. Both are built. The one spoken of before
is said as often as it stands in a place, a thing filling two places of one happening is said twice, the mark is
stated for the four that lacked it, a group the speaker is one of counts as a thing the sentence has named (which
is what reading needed to bind `ourselves` at all), and a thing stands after a verb only as its form says it may.
`They misled themselves.`, `We misled ourselves.`, `I misled myself.`, `They misled us.`, `Tom misled Tom.` and
`I washed myself.` are now said back exactly, and `Myself wash myself.` and `Themselves are intelligent.` are
refused by reading. Still open: saying a name's second mention with a pronoun (`Tom misled himself.` is said
`Tom misled Tom.`), which is pronominalisation and not binding.

**Was open here, and measured (notebook (93)).** `They misled us.` is said back as `They misled ourselves.`,
and the paragraph that stood here named the wrong cause. The forms **are** marked — memory holds `ourselves` as
`Case=Acc|Number=Plur|Person=1|PronType=Prs|Reflex=Yes` and `us` without the `Reflex` — but nothing weighs the mark,
the features weighed being those a **subject** is written with and nothing standing reflexively as a subject. Of the
34 kinds of thing standing after a verb, **none names `Reflex`**: the treebanks' reflexive objects were counted as
plain accusatives by the same filter. Widening it is not the fix, since it would make `us` win by frequency and would
then prefer `them` over `themselves` where the reflexive is required.

What stops the reflexive is not the refusal of a pronoun of its own sentence (lifting it changes nothing) but that
**a thing may not be said twice in one sentence**: `Tom misled Tom.` fails exactly as `Tom misled himself.` does,
and the same meaning with another term in the second place is said back exactly. Reading already binds, so both
halves a fix would need are there; what is missing is saying asking whether the thing after the verb is the thing
before it, and being able to spend a term twice when it is. **A capability, left to the owner.** Not urgent to a
teach: a taught sentence carries its meaning from the record, not from reading.

## The account before the teach (notebook (95))

Chasing single sentences stopped here, because the whole account was taken at last and it says the grammar is not
what is holding main back. **Main holds forms for 39 base words** (53 with the stated closed classes) against the
3,703 the notebook records of it, **subjects of 19 verbs**, **no object counts at all**, and 53 MB on disk: it was
reset and holds only the small confirmation run. **Over 400 of the PMB's gold training sentences, read only: 7 read
exactly the meaning they are annotated with.** 241 read to another meaning, 79 read nothing with the grammar
reaching no whole, and **66 read nothing for want of a word memory does not hold** — `dog`, `book`, `box`, `piano`,
`window`, `money`, `egg`, and the names `tom` (22 of the 66 on its own), `john`, `joe`, `roy`, `pacino`, `freud`.
Nothing is wrong with the grammar in those 66. Of the 7 that read right, 4 said back word for word.

So the next thing is the full teach, and the 241 are the measure to take after it, not before. `sweep.log` holds
the run; `sweep.py` in the session scratchpad holds how it was taken, and it is cheap to take again on a taught
store.

## The teach, and the blocker it exposed (notebook (96))

The teach ran: `build.py` with `HOW_MANY=0`, then `teach.py --source closed-classes`, then
`teach.py --source records --records data/records/pmb_gold.jsonl`. The build wrote **3,662 word records and 6,137
sentence records, 101.7 MB, in under an hour** -- not the five hours the account before it projected, because that
projection came from a 302-word sample dominated by heavy verbs while the real list is frequency-sorted.

**Main after the teach, read only:**

| | before | after |
|---|---|---|
| forms for base words | 39 | 39,898 |
| subjects | 19 verbs | 31,155 over 1,251 verbs |
| things after a verb | 0 | 17,309 |

**Reading, the same 400 gold sentences:** 108 read exactly the annotated meaning (**up from 7**), 279 read to
another meaning, 8 no whole reading (**down from 79**), 1 a number that is neither kind nor quality, 1 no word held
for a name. The account's conclusion holds at root: the dominant cause of bad reading was an untaught store.

**Saying does not scale to a taught store, and the sweep cannot finish because of it.** The saying pass was killed
after 58 minutes and 15.9 GB of resident memory on one meaning. Measured since: a verb enters a place with all 31
of its frames (`try`: 200 entries over 12 forms, against `problem`'s 4 over 4; widest place over the 400: 510
entries); the chart reaches 40,000 items with 666,485 waiting and **zero whole sentences ever completed**, so
`read_back` is never reached. Full account and cause in lab notebook (96). Until it is fixed, `sweep.py`'s saying
section will not return on a taught store.

### `REUSE`, and why rebuilding meanings is cheap

`build.py` takes `REUSE`, a previous build's file whose **word** records are taken as they stand. A word's record is
built from the word and WordNet alone, never from what a sentence means: changing the meanings and recounting gave
**the same 6,137 sentences, 3,875 words and 190 bases**, so the word pass -- the whole cost of a build -- need not
run again. Rebuilding after a change to `pmb_meanings.py` therefore costs the nine-second sentence pass:

```
OUT=data/records/pmb_gold.jsonl REUSE=data/records/pmb_gold.jsonl HOW_MANY=0 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-03/build.py
```

`REUSE` may name the file being written: it is read whole before anything is written, and the build writes beside
and moves over, so a build that dies leaves the file it was replacing intact.

## Why saying does not come back, and what it is really doing (notebook (97))

(96) left saying as the blocker with one named step: measure packing against `to_come`. Both are the wrong end.

Main reads **108** of the 400 PMB gold sentences to exactly the meaning they are annotated with. Saying those 108
meanings back, each bounded at 10,000 items taken so a meaning that cannot finish is named rather than left running
(`say_charged.log`, `say_both_orders.log`):

| | word for word | said otherwise | stuck, 0 read back | nothing | gave up |
|---|---|---|---|---|---|
| as it stands | 11 | 57 | 26 | 7 | 1 |
| most-complete first | 13 | 57 | 26 | 7 | 1 |
| estimate charged per place | 11 | 61 | 28 | 7 | 1 |

A stuck meaning is **not** one that fails to build a sentence. It builds hundreds and reading refuses every one
(`say_stuck.log`): `Tom is writing a letter.` makes 274 whole sentences and reads back 0; `I lost my sunglasses.`
465 and 0; `I am intelligent.`, which works, survives on 2 of 75. What it calls a whole sentence is a noun phrase --
`a letter written by Tom`, `a letter wrote by Tom` (`say_refused.log`) -- and reading is right: a noun phrase
asserts nothing and the tense is gone. Since `read_back` is the only gate that lets `SAID_AT_MOST` stop the loop, a
read-back rate of nought becomes an unbounded search. **The hang is a symptom of the disagreement.**

A noun phrase counts as finished because `filled == full` asks only that every THING the meaning names has a word.
What the grammar words spend is checked against `most` as a cap, never as a requirement: of `Tom is writing a
letter.` all 102 whole candidates spent `done_to`=0 and `during`=0, and of `My parents are aged.` all 80 spent
`has_property`=0 (`say_spent.log`). The fix is a coverage mask over the meaning's FACTS, as `filled` is one over
its places -- Kay 1996's completeness condition, which `grammar.py` cites and enforces for things alone. It cannot
be `used == most`: `i 'm intelligent` reads back correctly while spending `has_property`=0, because the adjective's
own place carries that fact and not a grammar word.

### The five links no word is offered for

A mask built before these would silence 17 of the 108 rather than fix them (`say_uncoverable.log`):

| link | meanings | what it is in English |
|---|---|---|
| `owned_by` | 6 | the possessive: *my* sunglasses, *her* room, *your* surname, mine |
| `isa` | 5 | a name predicated of a kind: Tom is a gentleman, Verga is a famous writer |
| `has_degree` | 3 | *How tall...*, *slightly* hungry |
| `has_count` | 2 | *three* paintings, *a hundred* employees |
| `state_of` | 1 | The show was exciting. |

`instance_of` is offered 162 times and `isa` never: the copula says a variable is a kind and cannot say a NAME is
one, which is why `Verga is a famous writer.` came back `Verga're a famous author Verga.`. Seven of the 28 stuck
meanings hold such a fact, so no candidate of theirs can ever read back.

### What was disproven, and why none of it was kept

- The frame filter of (96) is not the lever: `_unary`'s `ng=>NP` makes "Dick tried solving the problem." real
  English, so a thing-taking frame bound to one of the meaning's doings is reachable and must not be filtered.
- The agenda's order is not the fix. Reversing its two keys to most-complete-first is what the loop's own comment
  says it does, and on the widest meaning it turned 0 sentences into 4 with a chart a tenth the size
  (`say_order.log`: 325,136 items kept and 0 said against 30,607 kept and 4 said, `Dick vainly attempted solving
  the problem.`). Over the 108 it lost nothing and gained two -- but unstuck 2 of 28 and failed two capability
  tests, because the loop keeps the FIRST `SAID_AT_MOST` read back and not the best.
- A tighter estimate is not the fix. `to_come` is admissible and is the null outside estimate for all but the
  words; charging each place what a place had cost (Caraballo and Charniak 1998) made the widest meaning return on
  its own in 2,048 s and unstuck nought of the 108.
- Packing is cleared: the key's surface parts cost under 1% (325,136 against 323,108).

`Dick tried to solve the problem, in vain.` does not read back to its annotated meaning, so it was never in the
sweep's saying pass; (96) calling it a sentence the sweep stalled on is wrong -- the stall was a direct `say` call.

## Saying could not say a possessive at all (notebook (98))

(97) named five links no word is offered to say. Taking the whole route from a link to a word instead of one link at
a time: **saying's only route is prepositions.** `Lexicon.saying(link)` reads the `prep`, `prep_to` and `prep_of`
tables and nothing else, and the loop budgeting a link keeps an entry only `if entry.cls == "PREPOSITION"`.

The break is **one unknown piece kind**. `_piece_says` lists the kinds saying understands -- `given`, `past`, `be`,
`deny`, `fact`, `pron` -- and its docstring says "none for any other piece". `poss` was not among them, so a
possessive's piece said nothing, and `_says_of` turns a nothing into `None` for the whole entry. `my`, `your`,
`his`, `her`, `their`, `mine` and `'s` were offered for **no meaning whatever**: saying has never been able to say a
possessive, while reading has read them all along from the same piece (`spell_out`'s `poss`) through the same table
(`data/grammar/english.json`'s `linking`: `"possessive": "owned_by"`).

Fixed both halves: a `poss` piece says as many `owned_by` facts as the meaning holds, and is bound to the thing it
owns, only to a fact of the named owner where the word names one. Over the 108 gold sentences main reads exactly
(`say_poss.log`):

| | word for word | said otherwise | stuck, 0 read back | nothing | gave up |
|---|---|---|---|---|---|
| before | 11 | 61 | **28** | 7 | 1 |
| a possessive can be said | 11 | 63 | **26** | 7 | 1 |

`I lost my sunglasses.` went from stuck at 10,000 items with 0 read back to 2.0 s, 1,413 items, 8 read back.
Word for word did not move because the right sentence is ranked **third**, behind `I've lost my sunglasses.`, and
the tally counts `said[0]` alone -- ranking is the next thing to measure.

Two corrections to (97): its 11/57/26/7/1 baseline were cells of the two-order joint table, not marginals (the
marginals are 11/61/28/7/1, so the charged estimate was identical to the order as it stands, not worse); and `isa`
was wrongly counted as a missing link, since `_piece_says`'s `be` kind covers it.
