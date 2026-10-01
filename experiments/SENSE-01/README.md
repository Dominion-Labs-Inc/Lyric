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
     the last 24 things talked of. Connected means a fact between the two or between their near kinds, or a near kind
     they share.
  3. **How often the word was met naming each thing.** That is WordNet's tagged uses from the Brown corpus (240,754
     uses over 33,151 word–sense pairs, `WordNetSource.usage`, `learn_usage`), plus the lessons' uses. One witness
     carries its count, so the same source again moves nothing.

  When none of that tells them apart, the meaning is left open. Meanings that differ in what is said of what are
  never picked between.

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

**Runs:** none yet.

**Known limits:**
- **Definitions are still sentences without their meaning.** They are read or dropped, and only definitions of the
  sense a word names are offered. Giving each definition and example its meaning is the next step.
- **Frames for parts, members, materials and opposites were taught with a few examples each.** Those facts are
  said only where the frame takes the words; the rest are taught as facts alone.
- **What the listener knows is what it was taught.** WordNet's relations do not hold that food is eaten or that
  money is kept in a bank; an LLM knows them from text. WordNet's definitions state them ("eat: take in solid
  food"), and they become knowledge once each definition is taught with its meaning. Until then, K's last two
  sentences are expected to fail, and are kept in the bar.
