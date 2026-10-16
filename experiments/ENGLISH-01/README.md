# ENGLISH-01: Phase 1 of the English curriculum, the writing system

**Why.** Phase 1 of `docs/research/ENGLISH_CURRICULUM.md` teaches the writing system, one mark per lesson, the marks
web English uses most first. `survey.py` counted them in UD English EWT's 12,544 training sentences (2026-10-05):

| mark | sentences | its uses, most first |
|---|---|---|
| . | 8,573 | ends a statement |
| , | 4,401 | between joined parts 2,184; after an opening clause 978 or phrase 699; a second name 364 |
| ' | 1,937 | n't 645; 's for whose 549; 's for is 254; 'll, 'm, 've |
| - | 1,155 | inside words, ranges, asides |
| ( ) | about 770 | asides, second names |
| ? | 754 | questions |
| " | 660 | what someone said 263; words held apart |
| : | 541 | before what explains or lists; headings; times |
| ! | 527 | |
| ... / -- / ; | 212 / 185 / 129 / 78 | |

english_01–31 already teach the question mark (564 sentences) and some commas (71, mostly after "if"), and no colon,
semicolon, quotation mark, ellipsis or abbreviation. english_32 teaches the comma: between three or four things, with
and without a comma before "and"; between two sentences joined by "and" or "but"; after when it happened, or a "when"
or "because", said first; and around a second name for something ("Tom, the teacher, is tall."). Each meaning is one
an earlier lesson teaches without the comma, and every word is one the lessons have.

**What it checks.** On the emptied sandbox: english_01–31, then english_32, then:
- **A.** english_32 is learned, none refused, and every sentence reads as taught.
- **B.** 18 never-taught sentences with the comma in the same uses (`HELD_OUT`, frozen before the first run) read as
  written. Also measured before english_32.
- **C.** Every sentence english_01–31 teach still reads as taught.
- **D.** The main model is untouched, where it was still. When it was being taught alongside, its move is a note.

The comma on EWT's own held-out sentences waits for Phase 2: their words are not taught yet.

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/ENGLISH-01/experiment.py`

**Runs:**

- **2026-10-05, first run** (`results/20261005T174331Z`): **5/6.** Main was being taught english_01–31 alongside, so
  its move is noted, not checked.
  - english_32: learned, none refused (26 learned, 17 already understood); 44 of 44 read as taught.
  - **Never-taught sentences with the comma: 0 of 18 before english_32, 18 of 18 after.**
  - FAILED: 2,659 of 2,664 earlier sentences read as taught. The five read whole in two ways that tie, and the
    listener does not choose:
    - "Tom helped himself.", "Rex helped himself.", "The cat hurt itself.", "The dog hurt itself.": english_13's
      reflexives were learned as names. "Tom helped himself." was taught through the frame "?slot0 helped ?slot1.",
      already held from "Tom helped Rex.", with a new filler "himself" naming Tom; "Rex helped himself." then made a
      second "himself", naming Rex. So "Tom helped himself." also reads as Tom helping Rex.
    - "The dog chased a cat.": read as chasing the cat kind (through "chased the ?slot0", "a" for "the") and as
      chasing a cat, and the two suppose as much.
- **After the first run:**
  - Reflexives: a new word or phrase that names, with no word of its own for it, what another place of the same
    sentence names points back to that place, and is not held as a name (`item_based_lexical`, `phrase_in_slot`,
    `_points_back`). "Tom helped himself." now teaches "?slot0 helped himself.", generalized to "?slot0 ?slot1
    himself.".
  - english_29's three "a" objects ("Rex saw a cat.", "Tom ate an apple.", "Tom made a cake.") rewritten as some one
    thing, as english_22 writes them.
  - english_33, the apostrophe (48 sentences), and its 16 never-taught sentences (`HELD_OUT_33`, frozen before its
    first run) added; the experiment teaches and measures each Phase 1 lesson in turn.
- **2026-10-05, second run** (`results/20261005T182252Z`): **8/10.** Main untouched (68,187 rows).
  - english_32 and english_33 learned, none refused; 44 of 44 and 48 of 48 read as taught.
  - Never taught: the comma 18 of 18; **the apostrophe 15 of 16**: "Horses don't swim." did not read.
  - Earlier lessons: 2,663 of 2,664. The reflexives read as taught. "The dog chased a cat." still read two ways.
- **After the second run:**
  - **A phrase's word read through another said in its place supposed nothing.** "a" and "the" are said in each
    other's place where meanings do not tell them apart (`synonyms_of`), so "chased the ?slot0" read "chased a cat"
    and tied with "The ?slot0 chased a ?slot1.", taught for it. A frame's word read so was already supposed
    (`_said_for`); a phrase's now is too, carried through every filling (`_Filling.said_for`). In memory, english_01–33
    then read 2,756 of 2,756 as taught.
  - **"Horses don't swim." is a gap in the shapes english_01–31 teach, not in the apostrophe.** A bare plural doing
    something was taught only as "Dogs bark.", "Cats run." and "Birds fly.", each kept as a frame of its own ("Dogs
    ?slot0."), since a frame keeps a word of its own and "?slot0 ?slot1." has none. So "Horses run." and "Cows
    swim." do not read either. Tried in memory with frames of slots alone allowed: "Horses run." and "Horses don't
    swim." read, but "Cats sleep." stopped reading, "Cows swim." still did not, and run-on reading took 2.4 times as
    long. Not kept. A frame of slots alone ("?slot0 ?slot1.") is real English, and is Phase 3's to learn, from many
    frames of one shape (the Tolerance Principle), not from one sentence.
- **2026-10-05, third run** (`results/20261005T185549Z`): **9/10.** Main untouched (68,187 rows).
  - **Every sentence english_01–31 teach reads as taught: 2,664 of 2,664.**
  - english_32: 44 of 44; never taught, the comma 18 of 18. english_33: 48 of 48; never taught, the apostrophe 15
    of 16 ("Horses don't swim.", the shape gap above).
- **After the third run:**
  - **english_34, the colon and the semicolon** (19 sentences): a colon before the things a group holds ("Tom has
    three animals: a dog, a cat and a bird.", a group with a count and members, as english_08 writes a group), and a
    semicolon between two sentences. Its 8 never-taught sentences (`HELD_OUT_34`) frozen before its first run.
  - A sentence the reader reads as several ("Tom ran; Rex walked.", two sentences a semicolon joins) is measured by
    what they say together, each one's unknowns kept apart (`taken`); before, only its last utterance was compared.
  - In memory, english_01–34: 2,775 of 2,775 taught; never taught, comma 18 of 18, apostrophe 15 of 16, colon and
    semicolon 8 of 8.
- **2026-10-05, fourth run** (`results/20261005T191602Z`): **12/13.** Main untouched (68,187 rows).

  | lesson | taught, read as taught | never taught, before the lesson | after |
  |---|---|---|---|
  | english_32, the comma | 44 of 44 | 0 of 18 | 18 of 18 |
  | english_33, the apostrophe | 48 of 48 | 10 of 16 | 15 of 16 |
  | english_34, the colon and the semicolon | 19 of 19 | 6 of 8 | 8 of 8 |

  - Every sentence english_01–31 teach reads as taught: 2,664 of 2,664.
  - The one failure is "Horses don't swim.", the shape gap above (Phase 3).
  - Some apostrophe and semicolon sentences read before their lessons: english_01–31 already teach "It's", "You're",
    "can't", and two sentences a semicolon joins read as two.
- **After the fourth run:**
  - **english_35, a title with a period** (28 sentences): "Dr. Smith", "Mr. Park", "Mrs. Jones", "Ms. Kim" say what
    the named person is. Its first version kept every title sentence whole (0 of 8 never taught, in memory): each
    differed from the others in two places, and a name never met cannot be a slot. Rewritten as the earlier lessons
    are, one change at a time, with each name first said alone ("Smith is tall."): the learner then holds
    "?slot0. ?slot1", "Dr" for a doctor and "Mr" for a man (8 of 8 in memory). Its 8 never-taught sentences were
    frozen before its first version and not changed.
  - **english_36, parentheses, dashes and "!"** (21 sentences): a second name in parentheses or between dashes, as
    english_32 says it between commas, and "!" ending a statement, which says what the statement says.
- **2026-10-05, fifth run** (`results/20261005T204427Z`): **18/19.** Main untouched (68,187 rows).

  | lesson | taught | never taught, before | after |
  |---|---|---|---|
  | english_32, the comma | 44 of 44 | 0 of 18 | 18 of 18 |
  | english_33, the apostrophe | 48 of 48 | 10 of 16 | 15 of 16 |
  | english_34, the colon and the semicolon | 19 of 19 | 6 of 8 | 8 of 8 |
  | english_35, a title with a period | 28 of 28 | 0 of 8 | 8 of 8 |
  | english_36, parentheses, dashes and "!" | 21 of 21 | 4 of 9 | 9 of 9 |

  - Every sentence english_01–31 teach reads as taught: 2,664 of 2,664. The one failure is "Horses don't swim.".
- **After the fifth run:**
  - **english_37, money, measures written short, and dates** (21 sentences): "$" before a number is that many dollars,
    "m" after one that many meters, "on October 5" the day something happened.
  - **A new number needed a word of its construction's own to stand by.** "$" is a mark, so "$?slot0" had none, and
    "Tom has $4.25." did not read while "$2.50" was taught. A number written as a number is no guess at where a name
    begins and ends, and needs no anchor (`_anchored`). In memory: 8 of 8 never taught. Tests 110/110.
- **2026-10-05, sixth run** (`results/20261005T210957Z`): **21/22.** Main untouched (68,187 rows).
  - english_37: learned, none refused; 21 of 21 read as taught; never taught, 1 of 8 before, **8 of 8 after**.
  - english_32–36 as in the fifth run; every sentence english_01–31 teach reads as taught (2,664 of 2,664).
  - The one failure is "Horses don't swim.", a sentence shape for Phase 3.
- **After the sixth run:**
  - **"Horses don't swim." fixed.** A frame read off one sentence keeps a word of its own; but a frame differing
    from a held one only in its one word ("Dogs ?slot0." held, "Cats run." said) shows that place filled two ways,
    and substitution now opens it: "?slot0 ?slot1.", with what stood in the held frame's slot standing in the same
    slot of the new one. The rule moved from what a construction may be (`Pattern`) to how one is learned
    (`_repair`): only substitution makes a frame with no word of its own. Such a frame takes, besides what was
    linked to it, only what has stood where its own fillers stood (`stood_beside`), which now looks where a concept
    stood in any of its words ("sleeps" for "sleep"). In memory: "Horses run.", "Cows swim.", "Birds sing.",
    "Horses don't swim." read; "Hello there." does not. "Cats sleep." no longer reads: "sleep" was only ever taught
    with a place ("Cats sleep in houses."), and the per-subject frame that took any verb on its kind alone is no
    longer made. Run-on reading of 60 words: 3.74 s in memory, from 0.93 s.
  - **Days and times read by their writing.** english_37's never-taught dates were all dates it teaches, so they
    showed taught dates read, not dates. A date no lesson had ("October 6") read as "October" plus 6. Now: the
    literals reader reads clock times ("7:30", "7 a.m.", "19:30" as "7:30 p.m."); a run of words writing a day or a
    time is named by it, needs no anchor and is no new word; a day or time written in a sentence is a filler when
    learning, never a word of the construction ("?slot0 on ?slot1", not "?slot0 on March 12"); and the sayer writes
    one back as English writes it ("Tom walked on October 6."). A day without a year is held as ISO 8601 writes it
    ("--10-06"): "10-06" read back as 10 - 6. Four sentences with dates no lesson has were added to HELD_OUT_37.
  - **english_38, times of day, the ellipsis and the slash** (17 sentences) and its 7 never-taught sentences.
  - In memory, english_01–38: 2,862 of 2,862 taught; every never-taught set read as written, the apostrophe 16 of 16.
- **2026-10-05, seventh run** (`results/20261005T224420Z`, english_32–38): **24/25.**
  - Every Phase 1 lesson read as taught, and every never-taught set read as written: **the apostrophe 16 of 16**,
    "Horses don't swim." among them.
  - FAILED: 2,660 of 2,664 earlier sentences. "Tom kicked the ball.", "Rex kicked the box.", "Tom opened the door.",
    "Rex opened the box." read two ways that tie: as taught, and as a kicking at no time, through the new
    "?slot0 ?slot1." (which says nothing of time) with "kicked the ball" in its slot. "kicked" was linked in
    "?slot0 the ?slot1" from sentences whose frame said "before now" ("Tom kicked the ball into the box."), and read
    in a frame that does not, its time was dropped for nothing.
- **After the seventh run:**
  - **A word inside a phrase that says more than its concept** ("kicked": a kicking before now) is supposed where
    the reading places what it names nowhere by what the word says (`_unsaid`). Only words in a phrase's slots are
    judged: a word in a sentence frame's own slot was linked with that frame ("If it rained, the dog would bark.",
    where "rained" says no time), and a word is placed by the relation it says, against anything ("The cat had
    climbed.", before another time). A first version, judging every word and asking for "before now" exactly,
    made 14 taught sentences tie, and was not kept.
  - **A phrase proposed into a slot is judged by the word it writes first**, as one word is and as saying already
    judges it (`reading`, `written_against`).
  - On the seventh run's store: the four read one way, as taught. In memory, english_01–38: 2,862 of 2,862 taught,
    every never-taught set as written. Tests: derived reading, conversation, written mathematics 165/165.
- **2026-10-05, eighth run** (`results/20261005T232632Z`): **25/25.** Main untouched (68,187 rows).

  | lesson | taught | never taught, before | after |
  |---|---|---|---|
  | english_32, the comma | 44 of 44 | 0 of 18 | 18 of 18 |
  | english_33, the apostrophe | 48 of 48 | 10 of 16 | **16 of 16** |
  | english_34, the colon and the semicolon | 19 of 19 | 6 of 8 | 8 of 8 |
  | english_35, a title with a period | 28 of 28 | 0 of 8 | 8 of 8 |
  | english_36, parentheses, dashes and "!" | 21 of 21 | 4 of 9 | 9 of 9 |
  | english_37, money, measures and dates | 21 of 21 | 7 of 12 | 12 of 12 |
  | english_38, times of day, the ellipsis and the slash | 17 of 17 | 3 of 7 | 7 of 7 |

  - Every sentence english_01–31 teach reads as taught: 2,664 of 2,664.
- **After the eighth run: english_39, quotation marks** (17 sentences) and its 8 never-taught sentences. What someone
  said is held as said, never as true (`docs/TEACHING.md` §12b): the quotation is set apart ("“…”"), read on its
  own, and its facts are marked `said`. A pair with a quotation is learned as two, the sentence around it and the
  quotation, and counted once. In memory, english_01–39: 2,879 of 2,879 taught; the quotations 8 of 8.
- **2026-10-05, ninth run: crashed** (no results record; log `work/run9.log`). english_32–36 passed, each lesson
  read as taught and each never-taught set as written. Teaching english_37, remembering what "--03-12" was said of
  stopped the run: that memory's content begins with the day in quotation marks, the reader now reads a quotation
  on its own, and it read the day as a kind ("?slot0.", a doing of the kind "--03-12"). A number is refused as a
  kind or a quality; a day was not, and putting the words back (`_worded`) wrote it as "-03-12", a number, which
  the meaning refused by raising.
- **After the ninth run:** a day or a time is refused as a kind or a quality, as a number is: nothing is a March 12,
  or 7 p.m. as it is red. No lesson holds one so. In memory, english_01–39: 2,879 of 2,879 taught, every
  never-taught set read as written, and every "said of" content english_01–39 store read without failing.
- **2026-10-06, tenth run** (`results/20261006T003046Z`): **28/28.** Every Phase 1 lesson learned, none refused,
  and read as taught; every never-taught set read as written (english_37's dates included, and the quotations 8 of
  8); 2,664 of 2,664 earlier sentences read as taught. Main untouched (68,187 rows, english_01–31 as taught on
  2026-10-05).
- **After the tenth run: what a sentence does not tell as so** (the teammate's decision, 2026-10-05). "Tom said
  that the dog barked." held the barking as so, as `Tom said, "The dog barked."` no longer did; so did what someone
  thinks, hopes or asks, wants, likes or tries to do, what a doing is for, and what something is too big or big
  enough to do. The mark is now `unasserted` (it was `said`), and english_15, 18 and 20 mark 77 sentences' facts
  with it ("knows that", "started to", "let" and "because" tell theirs as so). A phrase filling a place a frame
  holds as not told as so is not told as so either (`_composed`, as a condition's is), which six sentences needed
  ("Tom says that the dog will bark.", "will bark" a phrase told as so elsewhere). Three faults in saying found on
  the way, two of them older: a phrase linked in a frame's place said its first word in any shape ("Tom asked Rex
  to opened the door.", first); a place borrowed the shapes of places writing the same concepts otherwise ("Tom
  wants swims.", from "Tom says that the dog ?slot3."); and a word saying more than its concept passed as a
  plural ("Tom wants swam."). In memory, english_01–39: 2,879 of 2,879 taught, every never-taught set as written.
  Tests: derived reading, conversation, written mathematics 168/168. "Tom wants swimming." is said second, after
  "Tom wants to swim.": "wants" stands where "likes" does ("?slot0 ?slot1 to ?slot2."), and no lesson shows it does
  not take "-ing".
- **2026-10-06, eleventh run** (`results/20261006T011447Z`): **28/28**, with english_15, 18 and 20 marking what is
  not told as so. english_01–31 learned, none refused; every Phase 1 lesson learned, none refused, and read as
  taught; every never-taught set read as written; 2,664 of 2,664 earlier sentences read as taught. Main untouched
  (68,187 rows). Phase 1 is complete on the sandbox, and main was emptied and taught english_01–39 next
  (MAIN-ENGLISH-01).
- **After the eleventh run: which word is heard after which** (`docs/TEACHING.md` §12c). The sayer put a word in a
  shape no lesson puts after the word before it ("Tom may opens the box." first; "Rex kicked the ball not." and
  "The fip does did not chase the kelt." among the others). The learner now keeps, for every sentence it learns,
  each word heard right after another, and memory holds them (one memory a word, "Heard after might: open, ...").
  A sentence whose filler stands where nothing like it was ever heard is not said where another sentence for the
  meaning has none (statistical preemption, Goldberg 2006; Boyd and Goldberg 2011); among the rest, fewer words
  stood where only something like them was heard come first.
- **2026-10-06, twelfth run** (`results/20261006T111625Z`, log `work/run.log`): **28/28**, the learner hearing.
  Every Phase 1 lesson learned, none refused, and read as taught; every never-taught set read as written; 2,664 of
  2,664 earlier sentences read as taught. Pairs not heard before, per lesson: english_35 15, 36 0 (each pair of its
  21 sentences was heard in an earlier lesson, as counting the lessons' own words shows), 37 31, 38 15, 39 1.
  Main untouched (62,710 rows).
- **2026-10-06, thirteenth run** (`results/20261006T135653Z`, log `work/run.log`): **28/28**, the learner keeping
  what followed each word and each two words (`docs/TEACHING.md` §12c), after UNASSERTED-01's fifth and sixth runs
  (the sayer and the answerer changed with it; reading did not). Everything read as in the twelfth run. Words
  and pairs not heard before, per lesson: english_35 38, 36 0, 37 68, 38 30, 39 1. Main untouched.
- **After the thirteenth run: "the X" is a known thing** (`docs/TEACHING.md` §12d, 2026-10-06). The lessons wrote
  "The door is open." as `has_property(door, open)`, the same as a fact about every door, so a person's "The printer is
  broken." would read as one about every printer (`docs/research/SEPARATION_MAP.md` §11). `scripts/known_the.py`
  rewrote 1,060 sentences of english_01–39: "the X" is a variable, `given instance_of(?t, X)`, and the sentence's facts
  are said of it. The never-taught sets' expected meanings, written before, are read through the same rule
  (`known_the.known`).
- **2026-10-07, fourteenth run** (`results/20261007T034447Z`): **28/28** with the rewritten lessons. Every lesson
  learned, none refused, and read as taught; every never-taught set read as written; 2,664 of 2,664 earlier sentences
  read as taught. Main untouched (64,476 rows): it still holds the lessons as taught on 2026-10-06, "the X" as the kind.
