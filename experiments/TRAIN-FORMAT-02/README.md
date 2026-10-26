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
- **Held, read by no part of reading yet:** what each sense means (its definition) and what it is a kind of, its
  examples, each PropBank place's who and function, the senses beyond the most used of each class (which sense a
  sentence means is not decided from them).

