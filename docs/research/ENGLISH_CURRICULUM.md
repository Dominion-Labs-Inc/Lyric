# Teaching Lyric full English: the lesson plan

Written 2026-10-03. Living: each phase's results are added under it as it is run.

## 1. The target

Lyric reads any English sentence, whatever its form:
- paragraphs and conjunctions;
- African American English, slang and abbreviations;
- every punctuation mark;
- every kind of word.

It reads them right and answers like a scholar: full basic American English first, then advanced.

"Full" is checked against one inventory of English grammar: the 20 chapters of *The Cambridge Grammar of the English
Language* (Huddleston and Pullum 2002). Among them are:
- the verb, complements, noun phrases, adjectives and adverbs, prepositions, adjuncts;
- negation, clause types, reported speech, relative clauses, comparatives;
- non-finite clauses, coordination, information packaging, deixis and anaphora;
- inflection, word formation and punctuation.

A phase is done when every chapter it covers has lessons, and its held-out test passes.

## 2. How Lyric learns English (what the plan has to fit)

- **One teaching path.** Every record goes through `TeachingPass` to the learning authority, and from there to
  memory, beliefs and domains (`docs/TEACHING.md`).
- **A sentence shape is learned only from a sentence paired with its meaning.** Lyric cannot learn English by
  reading English it does not know (ENGLISH-LESSON-01). A meaning is:
  - a speech act: tell, ask or request;
  - facts in the domain system's link kinds.

  "The dog has barked." is an event of barking, done by the dog, before now.
- **Words come from dictionaries:** classes, senses, forms, countability and pronunciation.
- **Text without meanings is for measuring**, and for counting how words are used once their shapes are known. It
  does not teach shapes.
- **Every source must allow commercial use.** CHILDES, GUM and CORAAL do not, unless licensed.
- **Every phase is measured on held-out sentences**, with a RunRecord and a bar set before the run.

## 3. What is on this machine

| Source | What it holds (counted 2026-10-03) | Licence | Used today | Role in the plan |
|---|---|---|---|---|
| WordNet 3.0 (NLTK) | 117,659 senses, 148,730 words, 117,659 definitions, 48,339 example sentences | WordNet licence, commercial use allowed | K's slice on the sandbox | Phase 2: every word sense |
| WordNet Gloss Corpus | each definition's words linked to their senses | WordNet licence | definition links | Phase 2 |
| english_01 to english_30 | 2,636 sentences, each with its meaning (tell 1,968 / ask 537 / request 131) | written for Lyric | sandbox; english_01–27 on main | Phase 3 base |
| `senses.json` | which sense 46 lesson words mean | written for Lyric | yes | Phase 2 |
| BECL 2.1 | 11,869 noun senses, counted or not | CC BY 4.0 | countability | Phase 2 |
| CMU Pronouncing Dictionary | 123,455 words | BSD-style | pronunciations | Phase 2, Phase 9 |
| Brown corpus | 1,161,192 words, 57,340 sentences, 15 genres of edited American English (1961), each word tagged with its part of speech | NLTK's index: "May be used for non-commercial purposes." | countability, plural spellings, prepositions, what words are said of, how often each word is used (`WordNetSource`, `PronunciationSource`) | kept: the owner decided on 2026-10-04 that Brown is used |
| ConceptNet 5.7 | 3,423,004 edges between 1,165,190 English terms | CC BY-SA 4.0 | earlier passes | after English (world knowledge) |
| OpenAssistant oasst1 | 39,283 English messages, 15,200 written by people asking | Apache 2.0 | no | Phase 5: how people ask |
| Anthropic hh-rlhf | people's turns with model replies | MIT | no | Phase 5, people's turns only |
| LibriSpeech, its alignments, MSWC | read speech; words said alone | CC BY 4.0 | SPEECH-02 to -05 | Phase 9 |
| Other Hugging Face sets (medical dialogue, LLaVA, HC3, SciQ and others) | domain questions, or text written by models | several non-commercial | no | not used for English |
| NLTK punkt, perceptron tagger | trained models | | no | never part of Lyric |

## 4. What the reader does today (sandbox, read only, 2026-10-03)

"Reads" means a reading was found, not that it was checked right.

| Reads | Does not read |
|---|---|
| "The box was opened by Tom." | `Tom said, "The dog barked."` |
| "The dog barked; the cat ran." | "Dr. Smith is here." |
| "What a big dog!" | "I can't open the box." |
| "The dog barked, didn't it?" | "The dog (a big one) barked." |
| "The dog barked. The cat ran." | "Tom has three pets: a dog, a cat and a bird." |
| "Tom has a dog. It barked." | "That movie was lit." |
| "She nice." / "He be working." (meaning not checked) | "idk where the dog is" |
| | "Hi Tom, can you send me the file by Friday? Thanks!" |
| | a 19-word sentence with no punctuation |

Some failures are only words the sandbox's slice of WordNet lacks ("send", "Friday", "pets"). Speech comes
with no punctuation: 44- to 55-word sentences did not finish reading in over 70 minutes (SPEECH-06).

**Measured 2026-10-07, after Phase 1** (LAB_NOTEBOOK 2026-10-07 (5)). Of 150 held-out sentences people wrote
(oasst1), 20 found a reading and about 8 were read right. 59.1% of their word tokens, and 444 of 2,802 distinct words,
are words the lessons used.

## 5. What has to be downloaded

| Source | What it holds | Licence | For |
|---|---|---|---|
| UD English EWT | 16,622 sentences, 254,820 words of web English: blogs, newsgroups, email, reviews, answers. Each sentence's structure was annotated by people | CC BY-SA 4.0 | Phases 1 and 4 |
| Wiktionary, English (kaikki.org extraction) | 1,390,507 words, 3.1 GB: senses, inflected forms, pronunciations, labels such as slang, informal, abbreviation and African American English | CC BY-SA 4.0 and GFDL | Phases 2 and 6 |
| Simple English Wikipedia | plain encyclopedic prose | CC BY-SA 4.0 | Phase 7, measuring |
| Project Gutenberg | books in the public domain | public domain in the US | Phase 8, measuring |
| FrameNet 1.7 | over 1,000 frames, 10,000 word senses, 100,000 annotated sentences | to confirm from the release's own README | Phase 8, if allowed |

Not usable without a commercial licence:
- GUM (CC BY-NC-SA 4.0);
- CORAAL, African American English speech (CC BY-NC-SA 4.0; some parts can be licensed commercially on request);
- CHILDES.

## 6. The lessons, in order

Every phase runs the same way:
1. Built and measured on the sandbox.
2. Taught whole on main.
3. Main measured, read only.
4. Then the next phase.

### Phase 0. Ready the store and the reader (no teaching)

- With the owner's go: wipe `lyric_db`. **Done 2026-10-04 22:10Z**, with no backup at the owner's word: 341 tables,
  290,096 rows to 0, and the three production databases (already empty).
- The reader reads long sentences in bounded time. Bar: a 60-word sentence with no punctuation reads, or is found
  not to read, in under 5 seconds.
- Teaching speed is measured on a sample. It is about 9 records a second today: WordNet's 638,000 records take
  about 20 hours. Wiktionary's size needs it faster.

### Phase 1. The writing system

The lessons are written the way english_01–30 were: each sentence with its meaning.

**Punctuation.** Each mark gets its own lesson, and its examples are checked against EWT's use of the mark:
- end marks: period, question mark, exclamation mark;
- the comma: in lists, between clauses, after an opening word, before a name spoken to;
- the colon, the semicolon;
- quotation marks: what was said, read as said;
- the apostrophe: possession and contraction;
- the hyphen, the dash, parentheses, the ellipsis, the slash.

**Capital letters:** where a sentence begins, names, "I", titles.

**Abbreviations written with periods:** Dr., Mr., Mrs., St., a.m., p.m., e.g., i.e., etc.

**Numbers in writing:** numerals, ordinals, dates, times, money, percentages and measures.

Measured on held-out EWT sentences that use each mark. Bar: each mark read right in at least 90% of them.

**Results (2026-10-05 and -06, ENGLISH-01).** EWT's sentences are mostly words no lesson has taught yet, so each lesson
is measured first on never-taught sentences of the lessons' words, frozen before its first run; EWT's own held-out
sentences come after Phase 2.

| lesson | what it teaches | never taught, before | after |
|---|---|---|---|
| english_32 | the comma: lists, joined sentences, what is said first, a second name | 0 of 18 | 18 of 18 |
| english_33 | the apostrophe: n't, 's, 're, 'm, 'll, 've; whose | 10 of 16 | 16 of 16 |
| english_34 | the colon before a group's members; the semicolon | 6 of 8 | 8 of 8 |
| english_35 | a title with a period: Dr., Mr., Mrs., Ms. | 0 of 8 | 8 of 8 |
| english_36 | parentheses and dashes around a second name; "!" | 4 of 9 | 9 of 9 |
| english_37 | money ($), measures written short (m), dates | 7 of 12 | 12 of 12 |
| english_38 | times of day, the ellipsis, the slash | 3 of 7 | 7 of 7 |
| english_39 | quotation marks: what someone said, held as said | 0 of 8 | 8 of 8 |

ENGLISH-01's eighth run (2026-10-05), on the emptied sandbox: 25/25, and every sentence english_01–31 teach still
reads as taught.

- "Horses don't swim." first failed: a bare plural doing something was held as a frame for each subject taught
  ("Dogs ?slot0."). Fixed: substitution opens a frame's one word into a slot when two frames show it filled two
  ways ("?slot0 ?slot1."). 16 of 16 in memory.
- english_38 teaches times of day ("at 7:30 p.m."), the ellipsis and the slash; the literals reader reads clock
  times, and days and times are read and said by their writing.
- english_39 teaches quotation marks. What someone said is held as said, never as true (the owner's decision,
  2026-10-05); so is what someone thinks, asks or wants, what a doing is for, and what something is enough to do:
  english_15, 18 and 20 mark those facts as not told as so (`MeaningFact.unasserted`, TEACHING.md §12b).
- A day was read as a kind ("--03-12", reading a memory's quotation) and the reading crashed: a day or a time is
  now refused as a kind or a quality, as a number is.

ENGLISH-01's eleventh run (2026-10-06): 28/28. Every Phase 1 lesson read as taught, every never-taught set as
written, and english_01–31's 2,664 sentences still as taught. **Phase 1 is complete on the sandbox**; main was
emptied again and taught english_01–39 (MAIN-ENGLISH-01).

### Phase 2. Every word

| What | From | About how many |
|---|---|---|
| Every sense, definition, example, and kind of each sense | WordNet with the Gloss Corpus | 638,000 records (about 20 h) |
| Every word, its forms, its senses' labels (slang, informal, abbreviation, African American English, regional), contractions, interjections | Wiktionary | 1,390,507 words; records to count at download |
| How each word is said | CMU Pronouncing Dictionary | 123,455 words |
| Which nouns are counted | BECL, WordNet | 11,869 senses |
| The words English builds sentences from | the closed classes (`ClosedClassSource`) | small |

- Measured as the share of the words in held-out EWT and oasst1 text that Lyric holds. Bar: 99% of word tokens.
- K (SENSE-01) and COMPREHENSION-01 are run again: 16/16 and 30/30 must still hold.
- Main is then compressed, as `MEMORY_COMPACTION_PLAN.md` sets out.

### Phase 3. Basic sentence shapes

english_01–30 cover statements, denials, questions, requests, tenses, comparisons, causes and times, relative
clauses, conditionals, numbers and arithmetic, and "I do not know". New lessons cover what the grammar inventory
lists that they do not:
- passives;
- every question form: yes or no, wh-, tag, indirect, echo;
- every kind of negation;
- all twelve tense and aspect forms, and the modals;
- imperatives of every kind;
- "there is", possessives, superlatives;
- infinitives and "-ing" forms, phrasal verbs;
- coordination and subordination with every common conjunction.

Measured on held-out lesson sentences and on EWT sentences of the same shapes. Bar: 95% read with the right meaning.

### Phase 4. Real written English (EWT)

The 12,544 training sentences are taught with their meanings derived from the people's annotation, by a new format
reader (`UDSource`). It maps the annotated relations to the link kinds, the same way ConceptNet's relations are
mapped, and decides nothing else.

Measured on EWT's held-out 2,001 dev and 2,077 test sentences: read whole, and meaning in agreement with the
annotation. A bar is set from Phase 3's result before the run.

### Phase 5. Conversation

- Greetings, thanks, apologies, polite requests, email and text openings and closings ("Hi Tom,", "Thanks!").
- Questions and requests as people write them: lessons from the forms found in oasst1's 15,200 messages from
  people asking, and hh-rlhf's people's turns.

Measured on held-out messages. Bar: the act (tell, ask or request) right in 95%, read whole in 80%.

### Phase 6. Varieties of English

**African American English,** from published descriptions (Green 2002; Labov 1969):
- the copula left out ("She nice.");
- habitual "be" ("He be working.");
- completive "done", remote "BIN";
- negative concord, "ain't";
- existential "it".

Each is taught with its meaning. "He be working." says he works habitually, not that he is working now.

**Also in this phase:**
- slang and informal words, from Wiktionary's labels;
- texting abbreviations ("idk", "btw", "lol");
- spelling as it is typed: no capitals, no final period.

Measured on SHAPES-BASELINE-01's dialect, slang and command sentences, enlarged with held-out ones. Bar: the meaning
right, not only read, in 90%.

### Phase 7. Paragraphs

- Several sentences read as one account:
  - pronouns that point back across sentences;
  - linking words ("however", "therefore", "then");
  - lists, and dialogue inside a story.
- Measured on paragraphs from Simple English Wikipedia: each "it", "he" and "they" taken to the right thing, and
  questions on what the paragraph says answered.

### Phase 8. Advanced English

- Long sentences with clauses inside clauses, nouns made from verbs, academic linking words, hedging ("it seems
  that"), passives in prose.
- FrameNet's annotated sentences for who did what to whom, if its licence allows.
- Measured on held-out Gutenberg and Wikipedia prose: share read whole and right, and questions on it answered. This
  is the "reads like a scholar" bar, set before the run.

### Phase 9. Spoken English

Pronunciations come from Phase 2. Hearing is SPEECH-05's (76.7% of sentence words). The listener settles words that
sound alike once Phases 3 to 7 give it the English to choose by (SPEECH-06). Measured on SPEECH-05's sentences:
- what the listener chooses;
- words right after it chooses.

## 7. What has to be built for this

| Piece | Phase |
|---|---|
| The reader in bounded time on long sentences | 0 |
| Faster teaching, measured | 0, for 2 |
| `WiktionarySource`, a format reader | 2 |
| Meanings for what the meaning form cannot yet hold: parentheses, a person spoken to ("Hi Tom"), lists, links between sentences | 1, 5, 7 |
| `UDSource`, a format reader | 4 |
| Held-out test sets and an experiment with a RunRecord per phase (ENGLISH-01 onward) | every phase |

## 8. Time, on today's teaching speed

- Phases 1, 3, 5, 6 and 7: a few thousand lesson sentences each, minutes to teach.
- Phase 2: about 20 hours for WordNet, 4 hours for pronunciations, and days for Wiktionary unless teaching is made
  faster.
- Phase 4: under an hour.

The writing of the lessons and the code in §7 is most of the work.

## References

- Green, L. J. (2002). *African American English: A Linguistic Introduction.* Cambridge University Press.
- Huddleston, R., Pullum, G. K. (2002). *The Cambridge Grammar of the English Language.* Cambridge University Press.
- Labov, W. (1969). Contraction, deletion, and inherent variability of the English copula. *Language* 45(4): 715–762.
- Silveira, N., et al. (2014). A gold standard dependency corpus for English. *LREC 2014* (UD English EWT).
