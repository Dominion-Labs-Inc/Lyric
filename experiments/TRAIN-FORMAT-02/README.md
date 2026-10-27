# TRAIN-FORMAT-02: one word recorded whole teaches every part of reading the word

**Why.** TRAIN-FORMAT-01 taught one sentence; "Roy painted the medal." was then read with "painted" a word nobody
knew. A sentence teaches how known words go together, never a word it does not hold. The owner (2026-10-26): teach
words and their meanings first, one word, verified fully, before more words; language learning does not touch beliefs
or domains (facts do).

**The format** (`core/learning/teaching_sources.py`: `WordRecord`, `WordForm`, `WordSense`, `WordUse`, `WordPlace`;
one JSON object a line, read by `RecordSource.word_records`; built by `word_record_of`, never by hand):

| Layer | Field | From | Who learns from it |
|---|---|---|---|
| every way the word is written, as which class, what form, how often | `forms[]` | UD English EWT and GUM (their analysts' lemmas and features) | the forms held (`word_forms`: "painted" of `paint`, past and participle), the word classes memory holds |
| every meaning: WordNet sense, class, Lyric's name for it, definition, what it is a kind of, how often used, examples, frames | `senses[]` | WordNet 3.0; Lyric's sense names (`WordNetSource._sense_names`) | what the word names as each class (`MemoryAgent.name_of`); the grammar's frames (`verb_frames`) |
| how the verb is used: each PropBank sense and its places (who fills each, its function, the prepositions its examples say) | `uses[]` | PropBank frames | the grammar's places (`role`: the subject `done_by`, the object `done_to`) |

The one convention, in the converter: a WordNet frame as the grammar's frame ("Somebody %s something": transitive);
PropBank's ARG0 the subject the doing is done by, its ARG1 the object it is done to where its examples say it bare;
every other place kept as written, with no link. PropBank's senses are kept apart from WordNet's: no source says which
is which.

**Taught** through the one teaching path (`teach.py --source records`, words before sentences;
`learn_word_records`; `MemoryAgent.remember_word_records`): one memory each word (tag `word_record`), read by none as
a claim, refused and counted refused where it does not hold together (`WordRecord.problems`).

**Run** (lyric_dev2, holding TRAIN-FORMAT-01's sentence):

```
PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 scripts/teach.py --source records --records experiments/TRAIN-FORMAT-02/records.jsonl
PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-02/experiment.py
```

**The word:** "paint": 7 forms (paint the noun and the verb; painted past, participle and passive; painting;
paints), 7 senses (paint.n.01 `coating paint`, "a substance used as a coating"; key.n.09; rouge.n.01; paint.v.01
`paint` "make a painting", intransitive and transitive; paint.v.02 `coat paint`; paint.v.03 `represent paint`;
paint.v.04 `cover paint`), 3 PropBank uses (put paint on a surface; create pictures with paint; depict). Not in either
treebank: the noun's plural "paints".

**Runs (2026-10-26):**
- Converting found two faults of the converter, fixed: WordNet's frames read from their strings, where the verb
  stands in place of `%s`, were all "intransitive"; a PropBank sense was put with the WordNet sense used most, which
  paired "put paint on a surface" with "make a painting" (now kept apart, `uses`).
- Taught: 1 word remembered, 0 refused, log 2,975 lines, no tracebacks or warnings. The teaching report counted taught
  statements as "words" (`admitted_proposition`): renamed, and the words and sentences recorded counted.
- First verification (`results/`): 20 of 21 store, reader and reading checks; through the front door 7 of 7 right, 0
  wrong. Missed: "Roy painted the medal with paint." read "with" as `word_with`, the link named by its word, though
  the sentence taught "with" `done_with`: the grammar counted its word-named link as one saying, and one taught
  sentence tied with it and lost (`grammar._weighed`). By the grammar's own definition a worded link commits to no
  kind and gives way where the kind is known: it now counts as none.
- **Second verification** (worded links no saying): **every store, reader and reading check (21)**: the record whole
  and read back the same; one memory, read by none as a claim; its senses, what each means and is a kind of, held;
  every form a form of `paint`; each form's class known; the verb named `paint`, the noun `coating paint`; "painted"
  read as past and participle, "paints" as the third person, "painting" as -ing; both frames; the subject `done_by`, the
  object `done_to`. Never taught, each read right: "Roy painted the medal." (past), "Roy paints the medal." (present,
  not past), "Roy is painting the medal." (now), "The medal was painted." (passive), "Roy painted." (no object), "Roy
  painted the medal with paint." (`done_with`, the paint `coating paint`). Through the front door **7 of 7 right, none
  wrong**: "Who painted the box?" Roy; "What did Roy paint?" Box; "Did Roy paint the box?" Yes; told "The medal was
  painted by Roy.", "Who painted the medal?" Roy, "Was the medal painted?" Yes; told "Roy paints.", "Does Roy paint?"
  Yes, "Who paints?" Roy. TRAIN-FORMAT-01's sentence on the same store: every check, 5 of 5. GRAMMAR-01 383 (F1
  82.6%) and taught_fit 420, as before the change.
- **What each sense is a kind of, read by the grammar** (`GrammarView.hold_word` into the words' knowledge, which
  the grammar asks deciding a link by what a thing is): `coating paint` a coating and a coloring material, the verb
  `paint` an act of creating, `coat paint` a coating, `rouge` makeup; taken back with the record. Two faults found
  doing it, each general: an empty `GraphKnowledge` was taken for none (`knowledge or Knowledge()`, it has a length),
  so in a store holding no concepts every kind taken in went nowhere; and, once it held, a word memory holds as a
  class was named by itself before what a record names it (`HeldWords._name` now asks `MemoryAgent.recorded_name`
  first). Every check again (the kinds' among them), 7 of 7; TRAIN-FORMAT-01 every check, 5 of 5; GRAMMAR-01 383,
  taught_fit 420.
- **PropBank's senses joined to WordNet's through VerbNet** (VerbNet 3.3 downloaded through NLTK, 4 MB): a
  PropBank sense's links to VerbNet classes, each VerbNet member's WordNet senses; each WordNet sense takes the
  PropBank sense joined to fewest WordNet senses. paint.v.01 "make a painting" is paint.02 "create pictures with
  paint" (create-26.4-1-1), paint.v.02 "coat with paint" is paint.01 "put paint on a surface" (coloring-24), paint.v.03
  is paint.03 "depict, describe" (characterize-29.2); paint.v.04 none. One list of senses: each with its places. Every
  kind up WordNet's chain held (`coating paint`: coating, coloring material, artifact covering, material, artifact,
  substance, ...). Each place's link by its function tag and preposition, only where they agree (`_PLACE_LINKS`):
  "for" after "paint" is `done_for` (paint.02's "benefactive", tagged a goal, said "for" and "in": "in" disagrees,
  no link); a doer after "by" `done_by`. What may fill each place held as PropBank's description's word (art, surface,
  painter) and VerbNet's restrictions (+concrete a physical entity, +animate a living thing).
- **Re-taught** (the record corrected in place, one memory): every check (23), 7 of 7, none wrong; "Roy painted the
  medal for Tom." not tested: "for" was never taught to lyric_dev2 (the grammar's own "for" is only "a tool for
  cutting"), and a preposition is a word to teach like any other. Function words need records too, and WordNet has
  none: theirs come from the treebanks' uses.
- **Which sense a sentence means: not built, and why.** PropBank's descriptions and VerbNet's restrictions cannot
  tell "painted the wall" from "painted a portrait": WordNet holds no wall, fence or door a kind of surface, "portrait"
  first means a word picture, and every candidate is concrete. Built on them, the choice would fall back to the sense
  used most. The evidence that can tell them apart is sentences tagged with senses (SemCor, WordNet's own; the PMB's
  gold senses).
- **Which sense a sentence means, chosen** (`Lexicon.sense_of`, in `spell_out`): each verb sense weighed by how
  often it is used and, for each place filled, by how many things it was seen used with there are of the most
  specific kind the filler shares with any of them (class-based selection, Resnik 1993). The evidence: SemCor
  (downloaded through NLTK, 4.7 MB), WordNet's own sense-tagged text: 39 uses of the verb, the subject and object of
  each found by the structure reader (9 found: a porch and a model `coat paint`, a painting, an area, a day, nothing
  `represent paint`, a subject and a manner `paint`); and every sentence recorded whole, each verb in the sense its
  meaning names with what fills its places (`SentenceRecord.verb_uses`, `GrammarView.hold_use`). "wall" and
  "picture" recorded as words for the test (their kinds). Never taught, read as the hand-tagged data says: "Roy
  painted the wall." `coat paint` (the wall a structure, as the porch); "Roy painted a picture." `represent paint`
  (an artifact creation, as the painting: SemCor's annotators tagged "paint pictures" so). Every check (37), 9 of 9.
  The evidence is thin (9 things seen with 3 senses): each word and sentence recorded adds to it.
- **What may fill each place counts in the sense chosen** (`Lexicon.sense_wants`): a filler of a kind PropBank's
  description names is evidence for the sense; one of no kind VerbNet restricts the place to, against it.
- **What a word means, answered** (`MemoryAgent.word_meanings`, gathered in `Conversation.understand`, a worked answer
  built there, `_meanings_said`): "What does paint mean?" every sense, most used first ("to make a painting; to apply
  paint to; ...; a substance used as a coating ..."); "What is a wall?" its kind in WordNet's word and what it means
  ("A wall is a partition: an architectural partition ..."). An answer's thing is answered (`spoken_for`, a name of
  several words whole): "Paint is a coating: ..." was followed by "I hold nothing for coating paint.".
- **Each word read back in its own examples** (`GrammarView.review_word`, at teaching, `reviewed` in the report and
  the log): 46 examples of the four words; 22 read, 2 in their sense; the words they hold that nothing taught yet
  holds (artists, blue, brick, city, rooms, yellow, ...), the words to teach next; every example whose words are all
  taught read whole, in its sense.
- **Found doing it, general: taught language recalled as knowledge.** "What is a wall?" took 148 s: the reasoner
  read the word's record, recalled as a premise, as a claim (109 million combinations in the chart). The sentences
  derived by hand (since 2026-10-26 (52), on main all 8,679), the records and what reading taught were left out of
  what recall holds back (`memory_filter`) and out of `IMPORTANCE_BY_KIND`; now held back, 0.6 as their peers, and a
  test holds every kind of taught language memory keeps held back. "What is a wall?" 0.1 s.
- **Every check (40), 13 of 13 through the front door, none wrong**; TRAIN-FORMAT-01 every check, 5 of 5;
  GRAMMAR-01 383; tests 79 passed (tests/test_conversation.py's 2 failing before this session fail as before).
- **Every field now:** read by a part of reading, or kept as where a link came from (`who`, `function`,
  `prepositions`, `bare`, `verbnet`: the converter's grounds for each place's slot and link). In the sentence record
  `semtag`, `sense` and `roles` repeat what the meaning's terms and the word records carry: read by nothing.
- **A word WordNet has none of: "for"** (the format now holds every word; `_CLOSED_CLASSES`). Its classes as UD's
  treebanks used it (a preposition 3,154 times, a subordinator 289, a conjunction 5); its uses named as the grammar's
  entries name them, counted as the grammar counts an analysed sentence (`HeldWords.use_of` over the treebanks'
  sentences holding it: a preposition of a doing 1,885, of a thing 980, of a quality 244, `sub` 231, `mark:purpose`
  54, ...); what it says joining a doing to a thing, over every PropBank argument it opens (`_propbank_joins`,
  through `_PLACE_LINKS`): `done_for` 283, `has_purpose` 199. Every word's uses are counted so ("paint" a verb, a
  noun; "painting" as a noun is the word "painting", not "paint": a use is a word's where its form is the word as that
  class). The grammar takes both (`GrammarView.hold_word`: `form_uses`, `prep`). Taught with "paint" (corrected):
  every check (27), 9 of 9 through the front door, none wrong: "Roy painted the medal for Tom." and "Roy fastened
  the medal for Tom." (a verb no record joined it to) read `done_for`; told "Roy painted the box for Tom.", "Who did
  Roy paint the box for?" Tom, "Did Roy paint the box for Tom?" Yes. TRAIN-FORMAT-01 every check, 5 of 5; GRAMMAR-01
  383.

- **Reasoning over what the words mean (2026-10-26 night, the owner: "the one record means nothing if the reasoning
  is not working, which is part of the language").** Traced through the authorities: learning (`learn_word_records`)
  and memory (one memory a record, warmed into the grammar) held; the reasoning owner (`NeuralSymbolicBridge.reason`)
  was handed **no premise** for "Is a wall a structure?" (the records' kinds reached the grammar only), and told "A wall
  is a partition. A partition is a structure." it said yes, chaining the two: the reasoning was sound, what it was
  handed was not. Now memory hands it what the words mean (`MemoryAgent.word_kinds`, each premise from the word
  record saying it, `_held_premises`), and a happening told is met by its kinds (`_Held.kinds`); a word asked may mean
  any of its senses, the one the thing told bears on (`word_senses_alike`, lexical cohesion, Morris and Hirst 1991):
  "Did Roy make something?" of a picture painted (`represent paint`, a kind of `to make`); the kind asked in "Is a
  picture a representation?" read as the representation a picture is (`representation.n.02`). Where neither is held a
  kind of the other, what the words hold to be both (`word_held_as_both`: "Is a structure a wall?", a wall), else what
  each is ("Is a picture a wall?": a picture a representation, a wall a partition), never a "no": two kinds may hold of
  one thing. No belief and no domain is made of a word's meaning. Words taught for it: "coat" (`to coat`), "make",
  "representation". The reply no longer says it holds nothing of a word recorded, of what a yes is said of, or "nothing
  said about" a doer told.
- **Found teaching them, in the format:** a sense Lyric's naming could not tell apart was recorded under its word
  (four senses of "make" all `make`): the naming now tells such a sense apart as it does across parts of speech, after
  every sense named before (`_sense_names`: 570 of 845 senses unnamed named, no name held before changed; recorded in
  `data/lessons/wordnet_names.tsv.gz`), and one still unnamed is not recorded (`make.v.30`, used 0 times); a sense's
  examples were WordNet's for all its words ("do nothing" an example of `make`): only those writing the word; forms the
  treebanks' analysts marked miswritten (`Typo=Yes`: "madea", "makke") were forms: none (`forms_from_conllu`).
  GRAMMAR-01, compared sentence by sentence with the naming before: 27 more dev sentences and 189 more gold training
  sentences have every sense named; senses aside 383/884 -> 386/911, strict 200 -> 199 (2 gained; 3 lost, each a link
  learned from the larger training set: "worked with Hooper" read `done_to`, the gold a second doer).
- **Measured** (`results/20261027T021648Z`, `20261027T021653Z`): store, reader and reasoning checks **55 of 56**;
  through the front door **21 of 21 right, none wrong** (the 13 before and "Is a wall a structure?", "Is a wall an
  artifact?", "Is paint a substance?", "Did Roy coat the wall?", "Did Roy paint a structure?", "Did Roy make
  something?", "Is a picture a representation?", "Did Roy paint a representation?"); no yes where none follows ("Is a
  wall a substance?", "Did Roy coat the picture?", "Did Roy make something?" of the wall). TRAIN-FORMAT-01 every
  check, 5 of 5. **The check failing:** two examples whose words are all taught read, not in their sense: "a second coat
  of paint" (`coat` the garment, not the layer: a noun's sense is its most used, never chosen by the words beside it)
  and "We made it!" (`make it`, to reach). **Not right yet:** on lyric_dev2 nothing taught says "X is a Y", so such an
  answer is said by its kind's name ("Structure."), and "What is a wall?" is answered by a sentence written by hand in
  `_meanings_said` ("A wall is a partition: ..."), not by what Lyric was taught to say; and each record taught is a
  belief in the `english` belief domain (`_learn_held`, as every kind of language held whole is), which nothing reads.
- **2026-10-27: language makes no belief, and the meaning answer written by hand is gone** (the owner's yes to both).
  Every language item held whole had been a belief in the `english` belief domain, made by the learning authority
  (`_learn_held`, `learn_structure`) and read by nothing; each correction left one more (22 on lyric_dev2 for 8 items,
  8 for "paint"). Now none is made: memory holds the item, the knowledge ledger records it taught, in no domain; the 22
  on lyric_dev2 let go. "What is a wall?" had been answered by a sentence written in the code (`_meanings_said`: "A wall
  is a partition: ..."); traced, reasoning was handed the premises ("wall isa partition", ...) and answered nothing, as
  it answers only what it derives and a kind held is no derivation. Now the question's reading answers it from what the
  words hold (`_meanings_held`): a thing asked to be what a kind is, by the nearest kind (`equals(?a, ?b) &
  instance_of(?a, wall) ? ?b`: `wall isa partition`), a word asked what it means, by what each sense it is used in
  means; each answer said as any held relation is, by what Lyric was taught to say it with, else by its name.
- **Measured** (`results/20261027T122740Z`, `20261027T122745Z`): checks **55 of 56** (the one failing as before, sense in
  context); front door **21 of 21, none wrong**: "What is a wall?" "Partition.", "What is paint?" "Coating.", "What is a
  picture?" "Representation.", "What does paint mean?" each sense used by its definition, a line each. Taught again
  through `teach.py`: beliefs 2 -> 2, none in `english`. TRAIN-FORMAT-01 every check, 5 of 5. **Not right yet:** nothing
  taught on lyric_dev2 says "X is a Y" or "X means Y", so these answers are said by name; what "mean" asks is read by
  its concept (`instance_of(?e, mean)`, the word "mean" itself not taught).
