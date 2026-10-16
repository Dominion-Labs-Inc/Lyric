# Handoff: Lyric reading and understanding English (2026-10-14, updated 2026-10-16)

For an engineer, and their Claude Code session, picking this work up. Read this first, then the lab notebook entries
2026-10-13 (4) and 2026-10-14 (1) in `docs/research/LAB_NOTEBOOK.md`. The previous handoff (2026-10-01) is in git
history.

## 1. What Lyric is

Lyric is a cognitive substrate, not an LLM. It learns English from lessons (sentences taught with their meaning)
and from WordNet. It keeps what it learns as memory (one memory agent writes and reads all of it), holds beliefs with
evidence, and reasons over a concept graph. No neural model reads or writes for it; an LLM may only ever teach it.

- Code: `core/`. Runtime: `./venv_lyric/bin/python3` from the `Lyric/` folder.
- Stores: Postgres on port 5433. `lyric_db` is the **main model**; `lyric_dev` is the **sandbox**.
- The reader and listener: `core/semantics/derived_reader.py`. Lessons: `data/lessons/english_NN.json` (41 files).
- Teaching: `scripts/teach.py`, run through `scripts/teach_and_watch.sh production|sandbox --source …`.
  Sources are in `core/learning/teaching_sources.py`; the pass is in `core/learning/teaching.py`.
- Learning: `core/learning/unified_learning_system.py`. Memory: `core/agents/memory_agent.py`.
- **What is learned is split by what it is about.** Something about a particular user ("my dog is Rex") stays in that
  user's context. General knowledge (what a dog is) goes to the main model, for every instance; if Lyric lacks it,
  it learns it in the background. The memory agent already routes this way.

## 2. Rules that hold for every session

**Stores and runs**
- `lyric_db` (main) is never written without the owner's explicit word. Runs on main start on the owner's word, and
  the owner starts them. Tests run on `lyric_dev` only; other sessions may share it.
- Before giving the owner any run command, run a small batch yourself on the sandbox.
- Say what a run is (what it does, which store, how long) before asking for it.
- **Protected modules: editing one halts a running substrate.** They are `autonomous_coordinator`,
  `intent_authority`, `threat_sense`, `meta_learning` and `config/constitution_triggers.json`. Edit them only when
  `pgrep -f "[Pp]ython3? scripts/teach\.py|experiment\.py|core\.main"` shows nothing.
- Never cap, time out or patch around a process that will not finish: trace it. Never `pg_dump` a store while a run
  teaches it.
- Start and stop services only with `stop.sh` / `start.sh`; restarts are the owner's. A teach run stops with
  `kill -INT <pid>`, as `scripts/teach_and_watch.sh` says.
- No sub-agents or multi-agent workflows on Lyric. Never message other sessions.
- No full test suites: run the targeted test files, once.
- Commands given to the owner to paste have no `#` comments in them.

**How the system is built**
- Model-free: no LLM and no added learned parameters. Solve gaps with memory, beliefs, counts and readable rules.
- Teach first, then test. Teach only the lessons needed.
- The memory agent is the only writer of memory. **A belief must name the memory it is about** (`memory_id`), or
  `_write_belief_row` refuses to store it, with only a warning the teaching pass's quiet output hides.
- No stubs, no fallbacks, no fake results. Root causes only. Extend existing systems. Delete dead code. Never
  remove a capability without the owner's word.
- Don't hand the owner lists of what is left; do the work.

**Records and git**
- Every experiment gets a RunRecord (`experiments/_evidence.py`), a README and a row in `experiments/README.md`.
  Every session gets a lab notebook entry.
- Commit only when the owner asks. No AI attribution. Never put the owner's name, or quotes of the owner, in the
  repo. Datasets are never pushed. Never copy the GitHub token in `Lyric/.env.production`.

## 3. Where it stands (2026-10-16)

**The goal** is readiness for new knowledge. Lyric must read prose as it is written (paragraphs, papers, webpages,
code documentation, mathematics), understand it, and reason over it. Language should then grow from lessons and
from experience, not from reader code written one sentence shape at a time.

### Measured on main

- **Lessons: 2,874 of 2,882** read as taught (2,866 before the listener's counts were held), read only, with
  `logs/handoff_2026_10_14/check_forms.py`. Its log is clean and main's write counters did not move. The 8 misses,
  each read to another sense or a wrong name: valve ("device valve"), ponies (the horse pony), singing (the creation
  art), bus (the car bus), "Rex picked up the book." (the product book), equality (the law of nature principle),
  dress (attire), "Where is a cow found?" ("cow found" as one name). Review and plural questions: 13 of 14 ("Are
  Anglo-Indians a kind of English person?" does not read). "The cat jogged." now decides (run, jog).
- **Prose: UNDERSTANDS-PROSE-01, first run** (`results/20261014T190758Z.md`, 26 minutes, nothing written): **4 of 33
  sentences** understood, **8 of 37 questions** right, **4 wrong**. All three bars fail (90%, 80%, at most 2%). The
  run included the composition change below; no clean run without it was taken, and none of the 4 sentences read
  depends on it. Why sentences failed (several hit more than one):

  | Missing piece | Sentences | Example |
  |---|---|---|
  | A question word in front | 7 | "What absorbs the light?" (understood "absorbs the light", not "What") |
  | A name it does not hold | 7 | blowhole, Eiffel Tower, network traffic: "something I have no name for yet" |
  | A pronoun as the subject | 6 | "They live in the ocean." (understood all but "They") |
  | "of" between things | 6 | "the capital of France", "a list of common passwords" |
  | "and" joining things | 4 | "carbon dioxide and water", "typed and garbage-collected" |
  | Hyphenated words | 3 | "high-level", "general-purpose", "object-oriented" |
  | Two readings it will not choose between | 4 | "The function sorted returns a new list." |

  The wrong answers:
  - Three are the strong disjointness assumption (`concept_graph_reasoning._kinds_exclude`), confirmed on main with
    the reasoner's own answer and basis: "Is Python a programming language?" (python held as a boa), "Is key a
    function?" (key held as a device), "Is chlorophyll green?". Each pair meets only at "entity". In each case the
    conversation had just been told something about that subject and could not read it.
  - "Is chlorophyll green?" reads only as "a kind of green" (the colour, a park, a site, vegetable greens): none of
    its four readings asks whether chlorophyll has the quality green. A reader or listener defect, open.
  - The fourth is the harness's scoring: "What is the largest animal on Earth?" got a recital ("I hold largest but
    nothing said about it yet. ...") that `scored` counts as wrong, not as unanswered. Left as is; the owner decides.
  - "Is the tank full?" was not answered although both valve sentences were read: a rule told in a conversation
    does not reach the reasoner with the fact told beside it.
- **Prose, second run, after phase 1 step 1** (`results/20261016T002042Z.md`, 18 minutes, nothing written):
  sentences 4 of 33, right 8 of 37, **wrong 0 of 37** (the wrong-answer bar passes). Three wrong answers were fixed
  by step 1: "Is Python a programming language?" and "Is key a function?" now answer "I do not know whether ...", and
  "Is chlorophyll green?" recites what it holds. The fourth, "What is the largest animal on Earth?", changed by
  chance: its recital began "I remember:" this time, which `scored` counts as unanswered. The scoring weakness stands.
- **Constitution halt on main, still standing.** Since 2026-10-14 08:49 `lyric_db` holds a constitution halt
  (`integrity violation: source_modified in core.agents.autonomous.autonomous_coordinator`): a substrate was teaching
  main when that file changed on disk. Every boot of main restores it. Only a human can lift it.

### Done 2026-10-14 (2) and 2026-10-15 (nothing committed)

1. **The listener's counts are on main.** `teach_and_watch.sh production --source listening --domain english`:
   `listening counted : {'observed': 19, 'withdrawn': 0, 'refused': 0, 'total': 20, 'sentences': 3054}`, +19 beliefs,
   no traceback; the only CRITICAL in the run's log is the standing halt above.
2. **Composition: adjuncts found in held frames** (`core/semantics/derived_reader.py`).
   - `Adjunct`, `_adjunct_of`: a held frame that is another held frame with a run of words added right after one of
     its slots, its meaning the other's with facts added of what that slot stands for, shows an adjunct ("on the
     ?slot1" from "The ?slot0 is ?slot1." and "The ?slot0 on the ?slot1 is ?slot2."). `happening`: it says what only
     a happening has (`_HAPPENING`); `of_happening`: its frames said it of one.
   - The view finds them as frames arrive (`PatternInventory._note_adjuncts`, `adjuncts_after`, `begins_adjunct`),
     never from everything held again. The lessons alone show 116.
   - Reading (only with `extend`, never in learning): what stands in a slot followed by an adjunct stands there as
     one (`_slot_fillings` → `_adjunct_fillings`, `_adjoined`), the adjunct's own slots filled as the longer frame's
     are; and adjuncts after all a frame reads are said of what it tells happened (`_analyses` → `_tails`,
     `_with_tail`). Each adjunct used is a link proposed (`Reading.proposed`), so a reading through held frames
     always ranks first.
   - Offline, never taught, read right: "The cat ran into the box in the morning.", "Tom kicked the ball into the
     box in the morning.", "Tom opened the box with a key in the morning."; "The dog ate the bone in the house." reads
     both ways.
   - Tests: `tests/test_derived_reading.py` and `tests/test_word_forms.py`, 130 passed; two new tests
     (`test_adjuncts_found_in_held_frames_read_sentences_never_taught`,
     `test_what_only_a_happening_has_is_never_said_of_a_thing`) pass.
   - Not yet: "and" lists inside one slot, and adjuncts that begin with a slot or a mark.
3. **`check_forms.py` stops the memory loops after warming**, as the experiment does, so a read of main writes
   nothing; confirmed by main's counters.

### Done 2026-10-14 (1), still holding

WordNet usage counts land on verb forms; a plural reads as every sense of its stem; the listener adds its evidence in
nats (`weighed`, `listening_worths`, counts held as beliefs grounded on one memory); kinds of number are decided by
arithmetic; `Conversation(remembers=False)` holds what it is told in working memory and writes nothing;
`experiments/UNDERSTANDS-PROSE-01` built. Details in the lab notebook, 2026-10-14 (1).

## 4. The plan to close the gap (agreed 2026-10-15)

Three phases. Mark each step when done, with its measurement.

**Phase 1: fixes no lesson can make (code).**

1. **[done 2026-10-16: wrong answers 4 → 0 on UNDERSTANDS-PROSE-01, 3 of them by this step] No disjointness "No"
   about what the conversation could not read.** The
   closed world over kinds holds only while memory knows what the subject is. A conversation that was just told
   something about the subject and could not read it knows it does not. Everywhere else the rule stands ("Is a
   grandfather clock a beer?" is still No).
   - `Conversation._not_taken_in` (protected module, edited with no substrate running): each telling read only in
     part (`teach`), or with a fact about something it has no name for yet (`_telling`), as said; as recent as the
     turns. Sent with every question to the reasoner (`task_metadata["not_taken_in"]`).
   - `neural_bridge._answer_over_concept_graph` passes it to `answer_over_graph(..., not_taken_in=)`;
     `_kinds_exclude` declines when either term's name is said in one of them (`_named_in_any`: words, case and
     number aside, since an unread telling reached no concepts).
   - Tests: `test_no_closed_world_on_what_the_asker_said_and_was_not_taken_in`
     (`tests/test_relation_types_and_algebra.py`, 24 passed); `test_conversation.py`, `test_reasoning_owner.py`,
     `test_perception_owner.py`, 26 passed on `lyric_dev`. The sandbox holds no concept graph, so the path from the
     conversation to the rule is tested at each end only, until the prose run on main.
   - Measured on UNDERSTANDS-PROSE-01 (2026-10-16): the three disjoint answers became unanswered; right stayed 8;
     sentences stayed 4.
   - Scope: only this conversation's own unread tellings. A remembered conversation also keeps them in memory
     (`take_in_unread`); a later conversation does not consult those yet.
2. **A rule told in a conversation reaches the reasoner** with the facts told beside it ("Is the tank full?").
3. **Hyphenated words read as one word in a strict reading** ("high-level", "general-purpose"), as they already do
   in a loose one.
4. **Trace why names main holds are refused** ("blowhole" and "Eiffel Tower" are in WordNet, yet the reply was
   "something I have no name for yet"). Fix what the trace shows.
5. **"and" joins things in one slot** ("carbon dioxide and water": both done the same thing).

**Phase 2: lessons for the pieces prose uses (data; sandbox first, main on the owner's word).**

| Lesson | Teaches | Sentences it would open |
|---|---|---|
| Questions | What / Who / When / How many / Does in front of statements it reads | 7 |
| Pronoun subjects | They / It / Its standing where a name stands | 6 |
| "of" | the capital of France, a list of passwords, two of them | 6 |
| "and" lists | A and B; A, B and C | 4 |
| Superlatives | the largest animal on Earth | 1, now misread |

- Write each as pairs, the sentence without the piece and with it, so the reader finds the piece (`_adjunct_of`)
  and reuses it in every sentence.
- Decisions for the owner: "capital of" and superlatives have no link kind in the meaning language yet; add one, or
  say them in kinds that exist.
- If pronoun subjects do not generalize from pairs, the reader needs one change: a pronoun standing where a thing
  stands, bound to what was just said.

**Phase 3: production closes the rest.** A sentence it cannot read goes on the known unknowns; in a conversation it
asks what the part it missed means; a composed reading that memory or definitions confirm is learned through the
learning path, held as a belief that can be revised. The proof is the share of unread sentences falling with no code
change. Check first what of this already exists (the unread reply, `detect_knowledge_gap`, `learn_from_feedback`).

**How progress is measured.**
- UNDERSTANDS-PROSE-01 stays held out: no lesson is written from its sentences. Add a second held-out set of
  different texts.
- Every round: the prose texts, the lessons (`check_forms.py`) and the never-taught probes, read only on main.

**Open, smaller (from 2026-10-14):** "Are Anglo-Indians a kind of English person?" does not read; lessons lost to
another true sense under the new listener (valve, singing, dress, "Rex picked up the book."); `scored` in
UNDERSTANDS-PROSE-01 counts a recital that answers nothing as wrong unless it begins with one of `NOT_ANSWERED`.

## 5. How to run things

**Read-only on main.** Loading main takes about 5 minutes and 8 GB; reading all lessons about 25–30 minutes. Give
background shell tasks a 2-hour limit (`timeout` 7200000), or they are stopped at 30 minutes.

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 <script>
```

**The sandbox:** the same with `POSTGRES_DATABASE=lyric_dev`.

**Teaching** (the owner runs main):

```
scripts/teach_and_watch.sh production --source <source> --domain english
```

**Scripts from this session** are in `logs/handoff_2026_10_14/`. Run them from the `Lyric/` folder; they read and
write `logs/`.

| Script | What it does |
|---|---|
| `check_forms.py` | Verb sentences, review and plural questions, and all lessons; writes the misses to `logs/check_forms_lessons_missed.json` |
| `listener_measure.py` with `listener_eval.py` | Each kept reading weighed with the listener's own code, the old rule replayed verbatim, worths counted, and scored on lessons, held-out lessons, never-taught probes and questions. Needs `structure_probes_after.json` and `questions_gold.json` beside it. `listener_main.json` is today's measurement |
| `why_choice2.py`, `why_lessons.py` | Every reading and its evidence for chosen sentences |
| `readiness_probe.py`, `working_probe.py` | Texts told to a no-memory conversation, then questions |

**UNDERSTANDS-PROSE-01 on main** takes about 26 minutes and is started by the owner: a session's attempt to start
it on main was refused by the permission check. Read-only scripts that load the reader's view only
(`check_forms.py`) were allowed.

**Stack dumps** of a running teach: `kill -USR1 <pid>` writes `logs/stack_teach_<pid>.txt`. The macOS `sample`
command works on your own processes; `py-spy` needs root.

## 6. Pitfalls found this session

- **Beliefs with no `memory_id` are silently not stored** (see §2).
- **A study harness can differ from the system it studies.** A dump that rebuilt the reader's kept readings itself
  disagreed with the real check by 17 lessons. Measure with the reader's own functions (`_read_pieces`, `weighed`).
- **`time.time()` can tie.** A belief witness withdrawn and observing again at the same instant is ignored, so give
  each count its own observation id.
- **A change "says more" only of the part its phrases are about.** Asking it of every word made every plural say
  "done by what was spoken of".
- **A run measures the code on disk when it started.** The first prose run started after the composition change was
  saved, so it measured the change, not a baseline. Check a run's start time against the last edit.
- **`kinds_above` and `held_below` take names as the store holds them** (`programming_language`); `answer_over_graph`
  normalises first (`normalize_term`). Called with "programming language", they find nothing.
- **The disjointness rule closes the world at the very top.** Kinds that meet only at "entity" are answered No, so a
  sense memory does not hold, or a misreading, becomes a confident wrong answer.
