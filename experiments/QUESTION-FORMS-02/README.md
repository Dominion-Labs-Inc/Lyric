# QUESTION-FORMS-02: questions about what happens and what happened, with happenings held as events

**Why.** QUESTION-FORMS-01 found:
- a question form taught with some verbs was read for new words but not for other verbs, because the meanings dropped
  the verb;
- a told happening ("The wug ate a fep.") was held as nothing.

On 2026-10-04 the teammate decided that a happening a lesson tells of is held as one event of its verb's kind. Built:
- `teaching.told_events` names it from its telling;
- `Conversation._asked_of_events` answers from the events held, said as the telling;
- `english_31` writes happenings as events, as english_14 does.

**What it checks.** On the emptied sandbox, the 31 lessons, then facts with new words (`lesson.json`, frozen before the
first run), then questions through the conversation, every group checked:
- **A.** Shapes english_31 asks about, of new words.
- **B.** Shapes no lesson asks about (hides in, grows in, rests in).
- **C.** Things that happened: "What did the kelt chase?", "Who chased the blip?", "Did the fip kick the trel?",
  "What did the fip kick?".
- The main model untouched.

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/QUESTION-FORMS-02/experiment.py`

**Runs:**

- **2026-10-04, first run** (`results/20261004T183539Z`): **7/16**. Main untouched (290,096 rows before and after).
  - The 31 lessons and the facts were learned, none refused. Every happening was held as one event (`chase_838bdc70`,
    `rest_00695727`, ...), and every question was read as asked: "Where does the blip rest?" as
    `done_by(?v0, blip) & instance_of(?v0, rest) & located_in(?v0, ?v1)`, asking `?v1`.
  - Answered: "The plonk belongs to Nella.", "The trel is kept in a bag.", "Brabs sleep in boxes.".
  - **The other 9 fell back to a memory recited** ("I remember: The blip rests in the bag."). Two faults:
    - **The answer could not be worded.** The event that answers was found, but `say` gave nothing for its telling.
      The reader reads "The blip rests in the bag." as a frame with a phrase in one slot ("The ?slot0 ?slot1." and
      "?slot0 in the ?slot1"); the sayer said only frames with a word in every slot, so it could not say a sentence the
      reader reads.
    - **The past was asked of the event.** A question's time is bound to the clock (`precedes(?v0, 2026-10-04T...)`),
      and the answerer required the event to hold that fact. When an event happened is not held, so no past question
      found its event.
- **After the first run:**
  - `derived_reader.say` composes as the reader does (`_compositions`): a frame with a phrase in one slot, the phrase's
    own slots filled as a frame's are, a phrase standing for a thing describing the thing the slot is the kind of.
    The view indexes frames and phrases by the kinds of fact they state, so the search touches only frames that can
    fit.
  - `Conversation._asked_of_events` leaves a question's situation (`?now`) out of what the event must hold, and keeps
    it in the answer, so the past is said in the past ("The kelt chased the blip.").
- **2026-10-04, second run** (`results/20261004T191005Z`): **16/16**. Main untouched (290,096 rows).
  - Every question answered from the events held, said as the telling:
    - "A fip lives in a kitchen.", "A snell comes from the city.", "The plonk belongs to Nella.",
      "The trel is kept in a bag.", "Brabs sleep in boxes.";
    - in shapes no lesson asks about: "The kelt hides in the box.", "A morp grows in the city.",
      "The blip rests in the bag.";
    - of things that happened: "The kelt chased the blip." (asked what, and who), "Yes. The fip kicked the trel.",
      "The fip kicked the trel.".
  - "a city" and "the city" mean the same here: the meanings hold no difference between them, so the answer may say
    either.
- **After the second run.** The sayer's other sentences, below the first, were traced. Four faults, each fixed:
  - **A phrase said where only reading would suppose it.** "Tom Some of the lives in the city.": a phrase not linked to
    the slot is now said only where it may be read (`_alike`) and stood beside the slot's own (`stood_beside`), and
    with the word it writes first written as the slot's own are ("The kelt does chased the blip.").
  - **A doing held as a plural.** The use model counted every filler of a slot taking a shape as a plural, "kicked" and
    "chases" among them, so "chases" was in the shape of a slot saying a chasing before now ("The kelt chases the
    blip."). A slot naming a kind of happening (`_names_a_doing`: its kind's instance is done by or to something)
    gives no plural. `EVENT_PARTICIPANTS` moved to the meaning language (`derived_reader`).
  - **A word said in another shape than its slot's.** With no word of the kind in the slot's shape, the sayer said one
    in any shape. Now the concept goes in another frame.
  - **A word written as its name where the slot's own are written otherwise.** "The fip kick trel.", where only "drank"
    and "ate" stand: a word or a name written as it is goes only where the slot's own are written so
    (`written_against`).
  - Tests: derived reading, conversation and the event test, 111/111.
- **2026-10-04, third run** (`results/20261004T194518Z`): **16/16**, after those fixes. The same answers as the second
  run. Main untouched (290,096 rows).
- **2026-10-06** (`results/20261006T025754Z`): **16/16**, after the sayer's changes of 2026-10-06 (what is not told
  as so, a phrase inside a phrase, phrase words judged against the meaning): every answer as before. Each answer no
  longer ends "I hold nothing for <the moment asked>." (the question's `?now` was looked up as a concept).
- **2026-10-06, the learner hearing** (`results/20261006T105952Z`): **16/16**, every answer as before, with the
  learner keeping which word it heard after which (`docs/TEACHING.md` §12c; "heard": 37 for the facts). Main
  untouched (62,710 rows).
- **2026-10-06, the two words before** (`results/20261006T130411Z`): **16/16**, every answer as before, with the
  learner keeping what followed each two words, the answerer giving an event that answers as asked before one told
  with another quality, and a remembered claim chosen by what it names of the question. Main untouched (62,710
  rows).
- **After the 2026-10-06 runs: "the X" is a known thing** (`docs/TEACHING.md` §12d). `lesson.json` is rewritten by
  the rule english_01–39 were (`scripts/known_the.py --file`): its five sentences with "the".
- **2026-10-07, first run** (`results/20261007T041827Z`): **12/16**. "Where does a fip live?" and the three others
  with "a" did not read: english_31 taught that question with a name, "the", a plural and a mass word, and "a fip"
  had read only because "the dog" and "a dog" meant the same. english_31 now teaches it ("Where does a dog live?" and
  two more). The other answers were "Yes." alone (see UNASSERTED-01's eighth run).
- **2026-10-07, second run** (`results/20261007T045832Z`): **16/16**, every answer said: "A fip lives in a
  kitchen.", "A snell comes from a city.", "The plonk belongs to Nella.", "The trel is kept in a bag.", "The blip
  rests in the bag.", "The kelt chased the blip.", "Yes. The fip kicked the trel.". Main untouched.
- **2026-10-07, third run** (`results/20261007T055441Z`): **16/16**, the same answers, with recall offering each
  wording once and leaving the language's own records out. Main untouched.
