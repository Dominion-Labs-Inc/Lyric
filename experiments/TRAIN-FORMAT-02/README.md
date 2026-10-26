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
- **Held, read by no part of reading yet:** what each sense means (its definition), its examples.
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

