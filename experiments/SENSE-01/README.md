# SENSE-01: the listener takes each word in the sense meant

**The defect it gates.** A word names several things: "fish" an animal and a food, "person" a human being, a human
body and a grammatical category. Once WordNet's senses were taught beside the lessons, everyday sentences read two
ways: "All fish can swim.", "A trillion is a number.", "A Bostonian is a person.". Every place that needed one
meaning then gave up, so the sentence was not understood and stated nothing. The reader reports every meaning a
sentence can have, and says which one was meant is the listener's to decide. That listener had never been built.
This is the gate before all of WordNet goes into the main model.

**What changed.**
- **The listener** is `derived_reader.meant`, with memory asked first (`heard`, `listening`,
  `MemoryAgent.listening_evidence`). Among meanings that differ only in which thing a word names, it takes them by
  this evidence, in order:
  1. **What memory knows of what is said.** A fact held of the things themselves counts 2; one held of what they are
     kinds of, on either side, counts 1. An event counts as its kind: "Tom ate the fish." is weighed as eating done to
     fish.
  2. **How each sense connects to the rest of what is said and to what was talked of before.** The conversation keeps
     the last 24 things talked of. Connected means a fact between the two or between their near kinds (a definition
     linked to its senses among them: `defined_with`, from the Princeton WordNet Gloss Corpus), a near kind they
     share, or the thing itself talked of before (one sense per discourse).
  3. **How each sense fits where its word stands** (`Reading.supposed`).
  4. **One activation, for what memory has counted.** Each construction's base level, `ln(1 + uses)`, from WordNet's
     tagged uses from the Brown corpus (240,754 uses over 33,151 word–sense pairs, `WordNetSource.usage`,
     `learn_usage`) and the lessons' uses, plus how much more likely each sense is given what the sentence's other
     word is said of (`MemoryAgent.said_selection`: Brown's 76,776 adjective–noun, verb–object and subject–verb
     uses, `WordNetSource.said_of`, and every sentence learned with its meaning). Both are in nats, so they add.
     SENSE-SAID-01 chose this over ranking what a word is said of first.

  When none of that tells them apart, the meaning is left open, unless the senses are one coarse sense in memory
  (one a near kind of the other, or both of one thing), which is understood. Meanings that differ in what is said
  of what are never picked between.

  Every reading that can wait for memory listens this way: the conversation (with what was talked of), a told
  sentence, a stored memory read as a claim, perceived text, statements ingested, the teaching pass, reasoning
  questions and premises. Readings that cannot wait use usage alone. A claim's shape is the same whichever sense
  was meant.
- **The ear hands on words that sound alike.** Where the ratio test cannot separate two or three taught words, the
  span carries them as `close`. The ways what was said can be heard (`heard_texts`) go to `heard_which`, which takes
  the way that reads and that memory supports.
- **Senses are named apart where they disagree.** Within each part of speech:
  - **The lessons' words.** The sense the lessons use a word in, as their teacher states it in
    `data/lessons/senses.json` ("table" the furniture, "number" the quantity, "Tom" no WordNet sense), is named by
    the word. The lessons hold no facts of their own, so memory cannot say which thing their "table" was.
  - **Every other word.** The sense the word names most often is named by the word: by tagged use, then a thing's
    common name before a person's ("crane" the machine, not Stephen Crane), then WordNet's order.
  - **The rest** are named by what they are first a kind of ("solid food fish"), never taking a name WordNet already
    gives.
  - **Numbers** are named by their value ("1000000000000"), as the lessons name them. A number is no kind, so
    nothing is taught as a kind of one.
- **All of WordNet** (`WordNetSource`): every part of speech, and every word a sense is written with. It teaches:
  - kinds and named things;
  - parts, members and materials;
  - opposites and likenesses;
  - what verbs require and cause.

  That is 264,215 records, the same in every process.

**What it checks.**

| | |
|---|---|
| A | Every lesson, then WordNet: every record about a sense of the lessons' and these sentences' words, the kinds above them, and a uniform sample of 2,000 of the rest; then WordNet's word usage. None refused. |
| B | What a thing is a kind of is said through the frames taught, in WordNet's words, with "a"/"an" as English has them. The other relations are measured. |
| C | Each word taught reads in a never-taught question: to its sense where the word names it, one way where its senses are named apart. |
| D | The kinds taught are held; unrelated pairs are not. |
| E | Each fact said is taken back, by the listener with memory at hand, as the fact taught, a sense named apart included. |
| F | No lesson sentence the listener took before WordNet is lost: each is taken as before, or in another sense of one word (listed). |
| G | "All fish can swim.", "A trillion is a number.", "Every cat is an animal.", "A Bostonian is a person." are each taken in the lessons' sense. |
| H | Every never-taught sentence the lessons read right before WordNet is still read right. |
| K | **The bar is an LLM's.** 16 sentences an LLM takes the right way without thinking, decided by what is known ("A mouse is a device."), by the conversation before ("An elephant is an animal." then "The trunk is long."), and by how a word is used. Two need knowledge WordNet's relations do not hold: "Tom ate the fish." (food is eaten) and "The bank is big." after "Tom has money.". Words that sound alike, heard the way that makes sense ("A mouse is a rodent." against "A moose is a rodent."). |
| I | Seconds per record. |
| J | The main model is untouched. |

**Run** (from the Lyric folder; it empties the sandbox first):

```
./venv_lyric/bin/python3 experiments/SENSE-01/experiment.py
```

`--k-only` measures K alone on the sandbox as it stands (no reset, no lessons; they must be held already; with `--fresh` the sandbox is emptied and the lessons taught first). It teaches WordNet's
records about K's own words (every sense each writes), the kinds above them, and the kinds of what K's words are said
of with a uniform sample of 100 more words per relation; WordNet's usage; what words are said of; then K and J.
`--listen-only` teaches nothing and measures K and J on the sandbox a `--k-only` run left: for a change to the
listener alone.

**Runs:**
- 2026-10-01 (full run): stopped during WordNet's word classes, before any check; no record.
- 2026-10-01, `--k-only` (`results/20261001T165100Z.json`), on the sandbox left by the stopped run (english_01–27,
  52,251 word classes): **K 7/16, heard 1/2.** 1,111 records in 214 s (0.19 s each), none refused; usage landed on
  666 of 33,149 word–sense pairs (32,483 name no construction yet). Main untouched.
  - Taken right: bat, crane (both), bank (slope), plant, fish (swim), trunk after "A tree is a plant.".
  - Taken wrong: "mouse" three times as `person mouse`; "table" as `array table`; "trunk" after an elephant as
    `baggage trunk`; "wing" as `helping wing` after a plane and after a bird; "bank" after money as the slope.
    "Tom ate the fish." read as a request with "Tom ate" as the act. "A mouse is a rodent." against "A moose is a
    rodent." left open.
- 2026-10-01, `--k-only --fresh` (`results/20261001T173607Z.json`), after WordNet's facts were said as English says
  them and its irregular plurals were taught: **K 8/16, heard 2/2.** "A mouse is a rodent." right; the computer
  mouse, wing (`stage wing`), the elephant's trunk, table, bank and "Tom ate the fish." still wrong.
- 2026-10-01, `--k-only --fresh` (`results/20261001T184343Z.json`), with english_28, the uncounted uses, twin frames as
  one place and the teacher's written names: **K 11/16, heard 2/2.** Wing (both) and the computer mouse after a
  computer now right; "A mouse is a device.", table, the elephant's trunk, bank and "Tom ate the fish." still wrong.
- 2026-10-01, `--k-only --fresh` (`results/20261001T194530Z.json`), after the full check of senses set aside before
  the listener and WordNet deciding plurals at the door: **K 13/16, heard 2/2.** Left: table, bank (knowledge),
  "Tom ate the fish." (reading).
- 2026-10-01, `--k-only --fresh` (`results/20261001T203502Z.json`), after every sense of the words read reaches the
  listener and how a sense fits is evidence: **K 13/16, heard 2/2**, unchanged.

- 2026-10-01, `--k-only --fresh` (`results/20261001T225549Z.json`), with english_29 and the language fixes of the day:
  **K 14/16, heard 2/2.** "Tom ate the fish." and "The bank is big." after money now right; "A crane is a device."
  (memory held the bird crane a device, through "bird" and "watch" sharing a concept with their verbs) and "The
  table is red." wrong.
- 2026-10-02, `--k-only --fresh` (`results/20261002T005558Z.json`), after one concept per sense across parts of
  speech: **K 15/16.** The crane and the table right; the tree's trunk taken as the elephant's.
- 2026-10-02, `--listen-only` (`results/20261002T015759Z.json`), after relatedness leaves out the word a thing's own
  fact pairs it with: **K 16/16, heard 2/2**, main untouched.
- 2026-10-02, `--k-only --fresh` (`results/20261002T145000Z.json`), on a sandbox emptied after COMPREHENSION-01's
  second run taught it wrong sentences, with english_30 and a reader that no longer takes every noun as a plural
  (`PatternInventory._written_otherwise`): **K 16/16, heard 2/2, 37/37**, main untouched. 37 facts about "power",
  "name" and "front" were refused and no check saw it: the pass admitted a fact before it learned its sentence.
  The pass now learns the sentence first.
- 2026-10-02, `--k-only --fresh` (`results/20261002T165030Z.json`): **stopped by its new first check, 34/35;
  nothing of WordNet taught.** From this run every record is said first, with nothing written (`said_wrongly`),
  and nothing is taught if a counted word would stand bare. It flagged 36 sentences. Most were right English the
  check misjudged ("Gasoline is fuel."); the rest came from a name's use being stated under its last word, so
  "long bone" and "bone" the stuff were one key. Uses are stated under the whole name now.
- 2026-10-02, `--k-only --fresh` (`results/20261002T173238Z.json`): **K 16/16, heard 2/2, 38/39.** The new check
  "no fact is refused" failed on 9 of 13,800:
  - one a defect: the source counted a name's words by spaces where the door also parts them at a hyphen
    (`_term_words` now counts as the door does);
  - eight refused by the door as designed, about words the lessons use only to build sentences ("be", "have",
    "near", "lot"). The check now passes those, names them, and fails on any other refusal.

  This run also taught two wrong sentences ("A manner is property."), found afterwards. Their cause, the Brown
  model counting by the Tolerance Principle, is taken back (`experiments/COUNTABILITY-01/README.md`).
- 2026-10-02, `--k-only --fresh` (`results/20261002T191346Z.json`), with that taken back, the list of names the
  concept resolver refused deleted, and a counted word never said bare: **K 16/16, heard 2/2, 38/39.**
  - Every one of 14,010 records said right before anything was taught; no pair and no fact refused, but the
    eight about sentence-building words ("parking lot is a lot" among them).
  - **The failed check is the main store's row count: 290,095 before, 290,096 after.** The row is not this run's.
    The live substrate was started on the main database at 16:13 local, during the run, and its start seeded the
    one row of `unified.appraisal_state`, a table added that afternoon. Read from the main store afterwards,
    read-only: that row is the only one newer than the run's start, and the only connection to the main database
    was the live substrate's.
  - The check now names each table whose count moved (`main_store_change`), so a record says where.

From the run after it, two more checks: the say-first check judges both ways (a counted name bare; an uncounted or
plural-only name after "a", "an", "each" or "every"), and after teaching, no frame the learner made holds a fact's
word (`frames_wrongly`). Why: `docs/research/LAB_NOTEBOOK.md`, 2026-10-02 (5).
- 2026-10-02, `--k-only --fresh` (`results/20261002T234125Z.json`), with the sayer taking the source's use for the
  record's own sense, a source's word for its own sense written as it is, the teacher's whole names passed to the
  learner, names with a preposition used as their head, and plurals spelled as English writes them: **K 16/16,
  heard 2/2, 40/40**, main untouched (290,096 rows before and after).
  - Every one of 13,986 records said right first, judged both ways.
  - No frame made while teaching holds a fact's word.
  - No pair refused; no fact refused but 7 about words the lessons use only to build sentences.
  - Teaching took 4,979 s, against 3,238 s and 4,044 s in the two rebuilds before it; an offline simulation was
    running beside it for its first 8 minutes.
  - A run begun at 19:16 was stopped before it taught WordNet: it had loaded the reader as it was before the last
    fix.
- 2026-10-03, `--k-only --fresh` (`results/20261003T034014Z.json`), after a word's use became the thing's under
  that word (`PatternInventory.used_as(word, value)`): **K 16/16, heard 2/2, 40/40**, main untouched. The same
  counts as the run before: 13,986 records said right first, no frame with a fact's word, 7 facts refused about
  sentence-building words. Teaching took 5,136 s.

**Known limits:**
- **Definitions are still sentences without their meaning.** They are read or dropped, and only definitions of the
  sense a word names are offered. Giving each definition and example its meaning is the next step.
- **Frames for parts, members, materials and opposites were taught with a few examples each.** Those facts are
  said only where the frame takes the words; the rest are taught as facts alone.
- **What the listener knows is what it was taught.** "Tom has money." does not read (possessive "has" is never
  taught), so after it the bank has nothing talked of to be related to; "Tom ate the fish." is read as a request
  ("ate" is taught only without an object). Both are kept in the bar.
