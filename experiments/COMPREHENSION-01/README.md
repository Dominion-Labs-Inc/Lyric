# COMPREHENSION-01: the questions that failed on 2026-09-19, asked again

**Claim.** The questions that failed on 2026-09-19 are answered as an LLM answers them:
- a greeting is greeted;
- a yes/no question with no answer is declined without reciting;
- a place asked for is answered with a place, or declined;
- a word with one sense anyone means is not asked about;
- recall is about what was asked.

**Why.** `docs/research/COMPREHENSION_SCOPE.md` §3 and §4 measured these against the live substrate on 2026-09-19:
- "hello" gave "A hello is an airline. It is a greeting.";
- "is a grandfather clock a beer?" recited clock facts, then beer facts;
- "where is a dog?" was answered with senses instead of places;
- the reply asked "Which dog do you mean?";
- asked about bass, recall gave a fact about an embassy.

Since then the reader, the lessons (english_01–29) and the listener have all changed under them, and nothing measured
them again.

**What it does.** On the sandbox (`lyric_dev`), with the lessons held already:
1. **Teaches first.** english_30 (what is said when something is not known; what follows a greeting or thanks),
   then WordNet's records about the words asked of, into the shared mind, as SENSE-01 teaches K's words: every
   sense each word writes, the kinds above them, and how often each names each thing. That teaching stays in the
   sandbox.
2. **Asks.** One speaker asks through `Conversation.understand`, the one turn, with no look-up.
3. **Removes** everything the speaker's turns wrote, after a snapshot.

| | Asked | An LLM |
|---|---|---|
| A | "hello"; "thank you" | "Hello."; "You are welcome." |
| B | "is a grandfather clock a beer?"; control "is a grandfather clock a clock?"; "is a canine a domestic animal?" | "No. …", nothing about beer; "Yes. …"; not no: "A dog is a canine. A dog is a domestic animal." |
| C | "where is a dog?"; told "The dog is in the kennel." (as english_01 says where things are); asked again; "is the dog big?"; told a name nothing holds is a mammal, "is it a beer?" | "I do not know where the dog is."; "The dog is in the kennel."; "I do not know whether the dog is big."; no |
| D | "what is a dog?" | no question of which dog; "A dog is a canine. A dog is a domestic animal." |
| E | "what is a bass?" | recalls nothing for "bass" that only contains it ("ambassador") |
| F | every reply | anything recited as remembered names what was asked |
| G | | the main model untouched; the speaker's rows removed |

After teaching and before asking, it also checks that the nouns asked of are held as counted things and that no
fact was said through the frame "?slot0 is body of ?slot1." (the defect of the second run, below).

**Run** (from the Lyric folder; boots the substrate on the sandbox):

```
./venv_lyric/bin/python3 experiments/COMPREHENSION-01/experiment.py
```

**Results:** `results/<UTC timestamp>.json`, `.md` and transcript.

**First run (`20261002T124158Z`, 11/19).** 2,504 WordNet records taught first, none refused; main untouched; the
speaker's rows removed.

| 2026-09-19 | Now | Said |
|---|---|---|
| "hello" looked up as a thing | not looked up; not greeted either | "Part of that is about something I have no name for yet, so I did not hold it." |
| "is a grandfather clock a beer?" recited clock and beer facts | nothing about beer; neither no nor declined | "I remember: A grandfather clock is a pendulum clock. I hold things about grandfather clock that I have not been taught to say yet." (The control is "Yes.") |
| "where is a dog?" answered with senses | the same | "Dog can mean a carnivore canine or a domestic animal. Which dog do you mean?" |
| "Which dog do you mean?" over-fired | the same, for "what is a dog?" | as above |
| recall about "bass" gave an embassy | recall gives bass memories only | "A bass is a musical instrument." |

Of the eight failures, five are the substrate's: the four rows above that are not fixed, plus "says it does not hold
where". Three were the experiment's own, from two causes, both corrected since; a later run will count them:
- **F (recited memories name what was asked)** skipped words of three letters, so "dog" did not count as asked, and
  "I remember: A dog is a canine." after "where is a dog?" was counted as off the subject.
- **The kennel telling** was "A dog is found in a kennel.". No lesson teaches "is found in", so it did not read, and
  neither "the speaker's context holds it" nor "asked again: the kennel" could be tested. It now says it as english_01
  does: "The dog is in the kennel.".

The cause the four question items share, and what was built for it, is in
`docs/research/REPLYING_TO_WHAT_IS_MEANT.md`.

**Second run (`20261002T140422Z`, 20/22),** after the reply answers what was meant. english_30 is taught first from
this run on.
- **Right:** "hello" → "Hi."; "thank you" → "You are welcome."; "is a grandfather clock a beer?" → "No. A
  grandfather clock is not a beer."; no question of which dog.
- **Wrong, and what each was:**
  - "where is a dog?" → "I do not know where the domestic dog is.", and after "The dog is in the kennel.", "The
    domestic dog is inside the dog house.". The reader's view held every noun as a plural, so "dog" was never
    said as it is (below).
  - "what is a dog?" → the kennel sentence. The reply saw only a concept's first four relations, in the order of
    their names, and "defined with" took all four.
  - "is a canine a domestic animal?" → "A canine is a carnivore.": not "No", but another subject.
- **What the run did to the sandbox.** The substrate says each fact taught and learns from what it said. With nouns
  taken as plurals it said many facts through a wrong frame, "?slot0 is body of ?slot1.". That frame did not exist
  before this experiment's first run (3 memories); this run added 1,012. They are still held.

**Why every noun was a plural.** A slot was "written otherwise than by name" when most of its one-word fillers were
not their concept's name, and a slot written otherwise is taken to take a shape. In "A ?slot0 is a ?slot1." 3,730
of 4,842 words were not their concept's name: 1,863 other words for the concept ("peril" for `hazard`), 1,412 the
word of a sense named apart ("wall" for `object wall`). The domain system was checked and is not part of it: no name
is held as more than one concept (0 of 8,788). `PatternInventory._written_otherwise` now asks whether the words
written as names are few enough to be exceptions (the Tolerance Principle).

**Third run (`20261002T143236Z`, 23/23).** Every check passed, and two replies were still wrong, so the checks were
too loose:
- "where is a dog?" → "I do not know where domestic dog is.": no "the", and not the speaker's word. Counting words
  the speaker had not used counted "the" as one and "domestic" (said earlier, of an animal) as none.
- "what is a dog?" → "A domestic dog is a canine. …": a word met 5 times before one met 350.

The checks now ask for the sentence itself.

**Fourth run:** stopped while teaching; no record. The sandbox still held the second run's wrong sentences, so it was
emptied (`scripts/reset_dev_store.py`) and rebuilt by `SENSE-01 --k-only --fresh`.

**Fifth run (`20261002T155914Z`, 26/28), on the rebuilt sandbox.** The replies asked for are said as an LLM says
them: "Hello."; "You are welcome."; "I do not know where the dog is."; "The dog is in the kennel."; "I do not know
whether the dog is big."; "A dog is a canine. A dog is a domestic animal.". Two checks failed, and the run itself
taught wrong sentences again:
- **"?slot0 is body of ?slot1." was back.** A name of several words had been made to take the use of its last
  word, so "body of water" was used as "water" is and said bare: "Stream is body of water.". It is used as its
  head is now ("body").
- **"Kennel is outbuilding."** Sentences had been ranked by use before score, and the much-used bare frame came
  first for a word new to the view. That ranking is taken back.
- **Behind both: nothing said a counted word does not stand bare.** A dry run on that sandbox, nothing written,
  said 410 of 2,261 facts so ("Soul is organism."). A slot now admits no counted word where a sentence begins, nor
  where a held frame says the same with a counting word before the slot; the teaching pass does not say a sentence
  that begins with a word its source states is counted.
- **"is a grandfather clock a beer?" was "I do not know whether…", not "No."** The clock's kinds stopped at "object
  whole": the concept resolver refused the name "object" from a list written into it, so nothing above was
  reached and the two shared no kind. The list is deleted.

From this run on, the experiment says every record first, with nothing written (`said_wrongly`), and teaches and
asks nothing if a counted word would stand bare.

**Sixth run (`20261002T185550Z`, 4/5): stopped at the say-first check, nothing taught.** 116, then 84, sentences
flagged. Most were the check's own errors:
- It judged a word's use across all its senses: "travel" held for one sense said nothing of "Travel is a motion.".
- It judged a name after "are" ("Alewives are fish.").

One was real: the rebuild before it had taught "A manner is property." (`experiments/COUNTABILITY-01/README.md`,
fifth run).

**Seventh run (`20261002T202323Z`, 4/5), on the sandbox rebuilt by SENSE-01 `20261002T191346Z`: stopped at the
say-first check, nothing taught.** 58 sentences flagged ("Travel is a motion.", "Control is an activity."). The
check still took the view's use of a word, drawn from every sense written with it, over the source's statement
for the record's own sense. Fixed in the check, and in the sayer, which made the same mistake the other way: "A
substance is a matter.". The check now also judges an uncounted or plural-only name after "a", "an", "each" or
"every".

After teaching, a new check asks that no frame the learner made holds a fact's word (`frames_wrongly`). An offline
simulation found nine such frames ("A ?slot0 ?slot1 is news."); their causes are in `docs/research/LAB_NOTEBOOK.md`,
2026-10-02 (5).

**Eighth run (`20261003T012321Z`, 30/30), on the sandbox rebuilt by SENSE-01 `20261002T234125Z` (40/40, K 16/16).**
Every record said right before anything was taught, nothing refused, no frame with a fact's word. Every reply asked
for is said as an LLM says it:

| Asked | Said |
|---|---|
| "hello"; "thank you" | "Hello."; "You are welcome." |
| "is a grandfather clock a beer?" | "No. A grandfather clock is not a beer." |
| "is a grandfather clock a clock?" | "Yes. A grandfather clock is a clock." |
| "is a canine a domestic animal?" | "A dog is a canine. A dog is a domestic animal." |
| "where is a dog?" | "I do not know where the dog is." |
| told "The dog is in the kennel.", asked again | "The dog is in the kennel." |
| "is the dog big?" | "I do not know whether the dog is big." |
| a name nothing holds, told a mammal: "is it a beer?" | "No. A vexojbzp is not a beer." |
| "what is a dog?" | "A dog is a canine. A dog is a domestic animal." |

Recall about "bass" hands up 3 bass memories and nothing that holds "bass" inside another word; nothing is recited
off the subject; the speaker's rows are removed; main untouched (290,096 rows before and after).

**Ninth run (`20261003T052358Z`, 30/30)**, on the sandbox rebuilt by SENSE-01 `20261003T034014Z`, after a word's use
became the thing's under that word: every reply the same as the eighth run's.
