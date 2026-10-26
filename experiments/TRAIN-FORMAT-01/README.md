# TRAIN-FORMAT-01: one sentence recorded whole teaches every part of reading

**Why.** Lyric learned English from about ten sources, each written its own way (UD treebanks in CoNLL-U, the PMB's
CCG derivations in Prolog and its meanings in SBN, the lessons' JSON, PropBank, WordNet, ...), each part of reading
from one of them, the layers joined by conventions written by hand (`_without_taken`, `_said_of_a_thing`, the PMB
meaning conversion, `MARKING`). The owner (2026-10-26): find exactly how the data must be structured for Lyric to
learn, as a model is taught from one standard dataset format, in an instance of its own (`lyric_dev2`), one sentence
first, verified thoroughly, before a set of 50 to 100.

**The format** (`core/learning/teaching_sources.py`: `SentenceRecord`, `RecordWord`, `RecordFact`; one JSON object a
line, `records.jsonl`). Every layer by word position:

| Layer | Field | Who learns from it |
|---|---|---|
| the sentence, where it came from, taught or held out | `id`, `text`, `source`, `licence`, `split` | |
| each word: where it is, as written, its base | `words[].at, start, end, form, lemma` | the forms held (`word_forms`), the grammar's names |
| its class, part of speech, form features | `class`, `tag`, `features` | the structure reader, the word classes memory holds |
| its WordNet sense, semantic tag | `sense`, `semtag` | (held; read by nothing yet) |
| its category in a categorial grammar | `category` | English's grammar (`Lexicon.hear_derived`) |
| what it is joined to and as what, as a treebank says it | `head`, `relation` | the structure reader (`StructureView`) |
| its VerbNet roles | `roles` | (held; read by nothing yet) |
| how the words were combined | `tree` | English's grammar (a verb's places, `_learn_places_derived`) |
| names of several words | `names` | English's grammar (a name one word), the structure reader (`flat`) |
| what is said: telling, asking or requesting; what is asked | `act`, `asked` | |
| the meaning, in Lyric's meaning language, each fact with the words saying it | `facts[]` (+ `positive`, `given`, `condition`, `alternative`, `unasserted`) | English's grammar's links (`Grammar.learn`) |
| each term of the meaning and the words saying it (what a pronoun stands for: its term's words) | `terms` | the grammar's alignment; what each word names (`MemoryAgent.name_of`) |

A record is checked whole before memory takes it (`SentenceRecord.problems`): every word at its characters of the
text, with its base, class, category and relation; one word the sentence's own and no word joined round in a circle;
the derivation combining every word once; every term of the meaning said by a word; every fact with the words saying
it. One that fails is refused, never held, and counted refused.

**Built from the PMB's checked data, by conversion, not by hand** (`record_of_pmb`): release 4.0.0's gold derivation
and 5.1.0's gold meaning of the same sentence. The one place the PMB's ways are put as Lyric's: a word's class from its
part of speech; what it is joined to from how the derivation combined it (a modifier, and a word that only marks
another, joined to what they take); as what, from how; a name of several words its words. Two faults of the data as
Lyric held it were found making the first record: the meaning and its alignment number their unknowns apart (the
medal `?v1` in one, the fastening `?v1` in the other), and the alignment points at a phrase's characters, not a word.

**Taught** through the one teaching path (`scripts/teach.py --source records --records FILE`; `learn_records`;
`MemoryAgent.remember_records`): one memory each record (tag `sentence_record`), read by none as a claim; at every warm
each layer goes to the part of reading that learns from it.

**Run** (from the Lyric folder, on lyric_dev2):

```
PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 scripts/teach.py --source records --records experiments/TRAIN-FORMAT-01/records.jsonl
PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-01/experiment.py
```

Part one checks the store and each part of reading (read only); part two tells and asks `texts.json` through
Lyric's front door as UNDERSTANDS-PROSE-01's harness does.

**Runs (2026-10-26, lyric_dev2: Lyric's tables, nothing taught before; a start seeds 752 concepts of its own):**

- **The record:** "Roy fastened the medal with a pin." (`pmb/p24/d3535`), whole; written and read back the same; its
  meaning the PMB's checked meaning, its derivation the PMB's checked derivation.
- **First teaching:** stopped: a record held no `claim()`, the belief every taught thing stands on. The memory was
  kept first; taught again, its belief held. A record refused was counted as none refused (`"refused": 0` written in
  `_learn_held`): fixed.
- **First verification** (`20261026T192819Z`, `20261026T192820Z`): 11 of 12 store checks; read back with the medal
  `medal` (the record names it `award decoration`); 4 of 5 questions, "Who fastened the medal?" not answered ("I don't
  know 'Who', 'fastened', 'the' and 'medal' yet"). Three faults, each general: a word of the grammar's own that no
  sentence held, capitalised, was a name (`HeldWords._uses_of`); memory's word classes held nothing of the record;
  what a word names was taken from no record. Fixed: `HeldWords._uses_of`, `MemoryAgent._learn_record_words`,
  `name_of`.
- **Second verification:** every store check (15); read back as taught; "Who fastened the medal?" `Roy.`; "What did
  Roy fasten?" answered `Award decoration.`: the thing's own name, where the speaker said "medal". A reading by
  English's grammar held no word the speaker called anything by (`derived_reader._said_by_words`, fixed), and an
  answer's things are listed by their own names, never the speaker's words (the conversation's protected module:
  staged, applied once main's run ended).
