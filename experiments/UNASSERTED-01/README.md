# UNASSERTED-01: what a telling does not tell as so is not answered as so

**Why.** On 2026-10-05 the teammate decided that what someone said is held as said, never as true, first for
quotations and then for "Tom said that the dog barked." and what someone thinks, believes, hopes or asks. The same
holds for what someone wants, likes or tries to do, what a doing is for, and what something is or is not enough to
do: the lessons mark such facts `unasserted` (`MeaningFact.unasserted`, `docs/TEACHING.md` §12b), and a happening
not told as so is not held as one (`teaching.told_events`). Lessons are taught as examples, so this shows where a
telling is held as fact and a question is answered from it.

**What it checks.** On the emptied sandbox: english_01–31, then nine facts with new words (`lesson.json`, frozen
before the first run), then six questions through the conversation, each checked:

- **A.** A chase that happened ("The kelt chased the blip.") is answered as happened: "Did the kelt chase the
  blip?" yes, and "What did the kelt chase?" the blip.
- **B.** A running the kelt said happened ("The kelt said that the blip ran.") and a kick the fip wants ("The fip
  wants to kick the trel.") are not answered as happened.
- **C.** A chase denied ("The fip did not chase the kelt.") and one that might be ("The kelt might chase the fip.")
  are not answered as happened. The lessons write these with the meaning itself (`false`, `possible`), not the mark.

Not answered as happened: the reply does not begin "yes" and does not say the happening outright.

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/UNASSERTED-01/experiment.py`

**Runs:**

- **2026-10-06, first run** (`results/20261006T013703Z`, before the answerer was fixed): **7/9.** Main was being
  emptied and taught english_01–39 alongside, so its move is a note, not a check.
  - A: "Did the kelt chase the blip?" "Yes. The blip was chased by the kelt."
  - B: "Did the blip run?" and "Did the fip kick the trel?" were not answered as happened (each "I remember: ...").
  - **C, failed:** "Did the fip chase the kelt?" "Yes. The kelt was chased by the fip.", told that the fip did
    not; "Did the kelt chase the fip?" "Yes. The fip was chased by the kelt.", told that the kelt might. The answer
    from the events held (`Conversation._asked_of_events`) checked that an event held everything the question
    named, and said "yes" over whatever else it held: here, that it was `false`, or `possible`.
  - **A check too loose:** "What did the kelt chase?" was answered "The fip was chased by the kelt. The blip was
    chased by the kelt." and passed, since the check looked for the chase of the fip said only actively. The
    checks now look for a happening said outright in either voice.
  - Every answer ended "I hold nothing for 2026-10-06T01:55:07Z.": the moment the question was asked, the
    situation's `?now`, was looked up as a concept (`Conversation.resolve`). QUESTION-FORMS-02's runs show it too.
- **After the first run:** an event held with a quality the question does not name is said with it, and is no
  "yes"; the moment it is is not looked up.
- **2026-10-06, second run** (`results/20261006T015631Z`, log `work/run2.log`): **9/9**, main taught alongside (noted).
  A: "Yes. The blip was chased by the kelt.", and "What did the kelt chase?" "The blip was chased by the kelt.".
  B and C were answered with something remembered ("I remember: The fip wants to kick the trel."): the denied and
  the possible chases, said with their qualities, could not be said, and no "yes" was given.
- **After the second run:** what happened was said in the passive, where QUESTION-FORMS-02 had said "The kelt
  chased the blip.": a phrase linked in a frame's place had its first word held against the place, and "chased"
  was. Saying now judges a phrase's words against the meaning, as reading does (`_unsaid`), instead. The sayer
  also composes a phrase inside a phrase, as reading reads one, where the two state the meaning's facts once each
  and the inner is linked where it stands: "The fip did not chase the kelt." is said back where it was read so.
- **2026-10-06, third run** (`results/20261006T024152Z`): **10/10**, main still. A: "Yes. The kelt chased the
  blip." and "The kelt chased the blip." B and C as before. In this run's store the denied chase was read with
  "did not" and "chased the" each saying "before now" (one fact in the reading), which saying does not say twice
  ("did not chased"); the answer is something remembered, not the denial. Saying it needs to know which word goes
  after which inside a phrase, which the view does not keep (ENGLISH-01's README, after the tenth run).
- **2026-10-06, fourth run** (`results/20261006T104443Z`, log `work/run4.log`): **9/10**, the learner hearing which
  word follows which (`docs/TEACHING.md` §12c); main untouched (62,710 rows). A: "Yes. The kelt chased the blip." and
  "The kelt chased the blip.". The one failure is the check's: "Did the blip run?" "I remember: The kelt said that
  the blip ran." reports the saying, and the check looked for "the blip ran" anywhere in the reply. It now looks
  for a sentence beginning with the happening. The denied and the possible chase were each answered with another
  thing remembered ("I remember: The kelt might chase the fip." for the denial; "I remember: The kelt chased the
  blip." for the possible one), so neither is answered as happened, nor as told.
- **After the fourth run:** a happening with a quality is answered as told, first with its moment and, where that
  cannot be said, without it (`Conversation._asked_of_events`); and a phrase inside a phrase is composed where a
  frame's place is linked to it (`_phrases_holding_phrases`), as reading reads it.
- **2026-10-06, fifth run** (`results/20261006T114526Z`, log `work/run5.log`): **10/10** by its checks, with three
  faults they do not look for, each fixed after it:
  - "Did the fip chase the kelt?" "The fip did not chased the kelt.": the denial was read in this store with "did
    not ?slot0" holding a phrase whose fillers say a doing before now ("chased", "kicked"), and "chase" was linked
    there; said back, the phrase's shape kept "chased", and "chased" after "not" was like "opened" after "has not".
    Hearing now keeps what followed each two words, and a word linked to a slot and heard right after the words
    before it is said there (`docs/TEACHING.md` §12c).
  - "What did the kelt chase?" "The kelt might chase the fip. The kelt chased the blip.": the possible chase, said
    with its quality since the fourth run, came first. An event answering the question as it asks is now the
    answer, and one told with another quality only where none does.
  - "Did the blip run?" "I remember: A blip is an animal.": recall handed it up before "The kelt said that the
    blip ran.", and the first remembered claim was recited. The one naming most of what the question names is now.
  On the same store after the fixes, through the conversation: "The fip did not chase the kelt.", "The kelt chased
  the blip.", "I remember: The kelt said that the blip ran.", "The kelt might chase the fip.". Tests: derived
  reading, conversation, written mathematics, relations 192/192.
- **2026-10-06, sixth run** (`results/20261006T124321Z`, log `work/run6.log`): **10/10**, hearing kept with the
  two words before. A: "Yes. The kelt chased the blip.", "The kelt chased the blip."; B: "I remember: The kelt said
  that the blip ran.", "I remember: The fip wants to kick the trel."; C: "The fip did not chase the kelt.". One
  answer wrong, though not as happened: "Did the kelt chase the fip?" "The kelt did might chase the fip.". Asked at
  a time, the possible chase is said at that time first, and in this run's store a sentence did ("might" right
  after "did", never heard there); it was the only one, so nothing preempted it.
- **After the sixth run:** an event with a quality is said first where a sentence puts every word where words like
  it were heard, at the time asked or at none (`say`, `heard`), and only then as best it can.
- **2026-10-06, seventh run** (`results/20261006T132713Z`, log `work/run7.log`): **10/10**, every answer as told.
  A: "Yes. The kelt chased the blip.", "The kelt chased the blip."; B: "I remember: The kelt said that the blip
  ran.", "I remember: The fip wants to kick the trel."; C: "The fip did not chase the kelt.", "The kelt might chase
  the fip.". Main untouched (62,710 rows). Tests after it: 192/192.
- **After the seventh run: "the X" is a known thing** (`docs/TEACHING.md` §12d). The lesson's "The kelt chased the
  blip." held a chase of the kinds `kelt` and `blip`. `lesson.json` is rewritten by the rule english_01–39 were
  (`scripts/known_the.py --file`): "the kelt" is `given instance_of(?t0, kelt)`. The teaching path holds a lesson's
  known thing as the one of its kind Lyric's lessons know (`kelt_1`, `teaching.known_in_lesson`), and the
  conversation finds it when asked (`Conversation._known_of`; `docs/research/SEPARATION_MAP.md` §11.10).
- **2026-10-07, eighth run** (`results/20261007T043327Z`, log `work/run8.log`): **5/10**. Every question answered
  "Yes.", the five not told as happened included: a yes/no answered by any held fact of the question, and "the
  blip" found to be `blip_1` made "`blip_1` is a blip" one of them, which holds. What a known thing is picks it out
  and is not asked (`Conversation.asked`); a particular said back is "the blip" (`derived_reader.as_known`), and
  nothing is listed of it but what is held besides its kind.
- **2026-10-07, ninth run** (`results/20261007T051435Z`, log `work/run9.log`): **10/10**, every answer as told but
  one: "Did the blip run?" "I remember: The kelt chased the blip.". Asked after two turns about the kelt, recall
  offered "The kelt chased the blip." three times (three memories hold that sentence) beside its own records of
  how words are used ("Heard after chase: the"), and the saying was not among the three. Recall now offers each
  wording once and leaves the language's own records out (`live_recall._one_of_each`; `said_of` and
  `heard_after` beside `language_pattern` in `MemoryFilter.EXEMPT_EVENT_TAGS`), and a turn chooses among eight
  remembered things, not three. Asked in the run's order on its store: "I remember: The kelt said that the blip
  ran.". Tests 229/229.
- **2026-10-07, tenth run** (`results/20261007T053856Z`, log `work/run10.log`): **10/10**, every answer as told:
  "Yes. The kelt chased the blip.", "The kelt chased the blip.", "I remember: The kelt said that the blip ran.", "I
  remember: The fip wants to kick the trel.", "The fip did not chase the kelt.", "The kelt might chase the fip.".
  Main untouched (64,476 rows).
