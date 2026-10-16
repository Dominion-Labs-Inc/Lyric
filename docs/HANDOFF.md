# Handoff: Lyric reading and understanding English (2026-10-14, updated 2026-10-16 evening)

For an engineer, and their Claude Code session, picking this work up. Read this first, then the lab notebook entries
2026-10-13 (4), 2026-10-14 (1), 2026-10-16 (1), 2026-10-16 (2), 2026-10-16 (6), (7) and (8) in
`docs/research/LAB_NOTEBOOK.md`.
The previous handoff (2026-10-01) is in git history.

**A cloud session (no Mac, no store) reads main through the API gateway** (§5, "From a cloud session"): the cloud
environment holds `GATEWAY_BASE` and `LYRIC_STORE_TOKEN`. That is how a session checks a run the owner started.

**Start here: `docs/research/READING_PROSE_AT_SCALE.md`, then the lab notebook 2026-10-16 (5).** The step-by-step
plan in §4 patches one piece of English per step, and the owner judged it not the right fix (2026-10-16). The
research names the shared cause, a reader with no phrase layer between words and frames. **The owner chose that Lyric
learns phrase structure itself from a treebank**, taught into the main model through the learning authority. Built:
`core/semantics/structure.py`, `TreebankSource`, `learn_structure`, `MemoryAgent.remember_analysed`. **The treebank is
taught into main** (2026-10-16, finished 13:53, after the worthiness filter stopped declining what is taught: lab
notebook 2026-10-16 (6)): memories 1,418,592 → 1,431,010, beliefs 1,193,764 → 1,206,181; the pass's review answered
179 of 200 right. Main holds **12,544** memories tagged `analysed_sentence` in `memory_hot.memory_hot`, every sentence
of the treebank's training part (counted read only, as `lyric_reader`). **`experiments/STRUCTURE-01` passed on main**
(2026-10-16, 9 of 9, nothing written; lab notebook 2026-10-16 (7)): dev classes 91.8%, UAS 73.2%, LAS 66.3%; test
92.0%, 73.7%, 67.0%. The treebank's files read with the same code give the same to four places, so memory holds what
was taught, and the structure reader can be measured in a cloud session from the files. A tie is now decided by the
next situation, not by the class's name (2026-10-16 (8); from the files: dev 92.0% / 73.6% / 66.9%, test 92.3% /
73.8% / 67.5%). Open: in 4 of the 33 prose sentences the main verb is read as a noun (a word the treebank never used
is decided by its ending alone; a noun-or-verb word beside a noun reads as a compound). **Next:** constructions
learned over phrases.

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
- **Before any push**, look at what it sends: `git rev-list --count origin/main..main`, and
  `git log origin/main..main --format=%B | grep -ci co-authored-by` must be 0.
- Git state (2026-10-16 evening): GitHub's main holds everything, through STRUCTURE-01's records; the owner's Mac
  pulls it. Commits made from a cloud session carry its git identity as author and no trailers.
- **Every push reaches the Mac.** A cloud session pushes its branch and fast-forwards GitHub's main to it
  (`git push origin HEAD:main`, after the checks above), then gives the owner the pull with its `cd`:
  `cd ~/"Dominion Labs/Lyric"` then `git pull --ff-only origin main`. Before that, it checks through the gateway (`files?path=`) that the files the pull
  changes are on the Mac as its last commit holds them, so the pull is not refused; after it, that the Mac has them.
- **The API gateway is its own repository, `Dominion-Labs-Inc/dominion-labs`**: the folder `services/api-gateway` of
  the Dominion Labs folder, made a git repository of its own (2026-10-16), pushed to GitHub, pulled back into that
  folder. The Dominion Labs folder itself is not pushed: it holds Lyric (its own repository), a ClickHouse store,
  logs, `data/` and other repositories; a push of it tried to send 2.79 GB and failed. The gateway's `.gitignore` keeps
  out `.env`, keys, its virtual environments, logs and `*-bak` copies; check with `git ls-files` before any commit.
- Dataset batches 5 to 9
  (`test_data/music/giantsteps`, `humtrans`, `test_data/speech/LibriSpeech`, `test_data/vision/ukbench`) stay on
  disk, untracked and in `.gitignore`. The local branch `backup/main-before-one-commit-2026-10-16` still holds them:
  never push it. GitHub's pull request #1 (2026-08-29 to 09-02) still carries old `Co-Authored-By: Claude` lines;
  only GitHub Support can remove it.

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
  | Hyphenated words (measured 2026-10-16: not the cause; the comma and "and" beside them are) | 3 | "high-level", "general-purpose", "object-oriented" |
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
- **Prose, third run, after phase 1 step 2** (`results/20261016T125637Z.md`, 26 minutes, nothing written):
  sentences 4 of 33, right **9** of 37, wrong 1 of 37. "Is the tank full?" is answered from the rule and the fact
  told beside it. The one wrong is the `scored` weakness on "What is the largest animal on Earth?", the same recital
  without its "I remember:" line.
- **Prose, fourth run, after phase 1 step 4** (`results/20261016T140446Z.md`, 25 minutes, nothing written):
  sentences **7** of 33, right 9 of 37, wrong 0 of 37. The three sentences newly read hold main's misreadings of them
  (step 4).
- **Constitution halt on main, still standing.** Since 2026-10-14 08:49 `lyric_db` holds a constitution halt
  (`integrity violation: source_modified in core.agents.autonomous.autonomous_coordinator`): a substrate was teaching
  main when that file changed on disk. Every boot of main restores it. Only a human can lift it; a session never
  does. The listening pass taught main with it standing.

### Done 2026-10-16 (6) (committed and pushed)

1. **What is taught is not judged for keeping.** The treebank pass on main stopped at 11:06: the worthiness filter's
   complexity threshold declined an analysed sentence (`analysed_sentence` was never an exempt tag). Now
   `MemoryFilter.EXEMPT_ORIGINS` exempts everything that came through teaching, asked at store time only, so recall is
   unchanged; `analysed_sentence` joins the taught-language tags held out of recall as knowledge. Tests:
   `tests/test_memory_worthiness_semantics.py`, 31 passed. Lab notebook 2026-10-16 (6).
2. **The treebank is taught into main** (finished 13:53; 12,544 sentences held as analysed; numbers above).
3. **The gateway's Lyric Store API** (`dominion-labs`, `lyric_store_api.py`): read-only routes over `lyric_db` and
   `lyric_dev` and the files runs leave (§5). Read only three ways over: the `lyric_reader` role (granted
   `pg_read_all_data` and `pg_read_all_stats`), read-only sessions, `default_transaction_read_only`; 15 s statement
   and 2 s lock timeouts; at most 1000 rows; no route takes SQL. 56 checks against a real Postgres.
4. **Cloudflare cached a token-gated answer and served it to anyone** (`cf-cache-status: HIT` on
   `api.dmnlabs.org`): its cache keys by URL, never by the token. Fixed three ways: the Lyric Store routes say
   `no-store` on every answer; the gateway marks every `/api/` or JSON answer that sets no `Cache-Control` as
   `no-store` (`shared_cache.py`, outermost middleware); and a Cloudflare Cache Rule, "Never cache API answers" (URI
   path starts with `/api/`: bypass cache, the last rule), with the cache purged. Checked from a cloud session: no
   token is refused (401), `cf-cache-status: DYNAMIC`.

### Done 2026-10-14 (2) to 2026-10-16 (committed and pushed, 67f0faa4)

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
2. **[done 2026-10-16: right 8 → 9 on UNDERSTANDS-PROSE-01, "Is the tank full?"] A rule told in a conversation
   reaches the reasoner** with the facts told beside it ("Is the tank full?"). Two defects, each enough to block it:
   - A person's rule was held only as their belief in a claim string ("if valve_1 has_property closed then tank_1
     has_property full"), and `_answer_over_held_rules` read only the world's rules (`held_conditionals`) and the
     world's facts. Now the rule's two clauses are held in the person's context as the world holds a rule's
     (`unified.scoped_conditionals`, in `user_context`; working memory when not remembered:
     `MemoryAgent.hold_scoped_rule`, `working_rules`), through `ScopedContextStore.observe_rule`. Reasoning for a
     person reads their rules too (`rules_for_actor`) and their facts (`load_subgraph(..., actor=)`).
   - A yes/no question about a known thing never reached the reasoner: once "the tank" is found (`tank_1`),
     `MeaningFact.renamed` drops `given` by design, so "Is the tank full?" counted as two facts and `goal_fact` gave
     None. `Conversation._reasoned_answers` (protected module, edited with no substrate running) now sets aside
     the fact naming each known thing it found, and asks the one fact left.
   - Tests: `test_a_persons_rule_is_reasoned_over_for_them_and_no_one_else` (`tests/test_reasoning_owner.py`,
     remembered and not, for the teller only; cleans up its rows) and
     `test_a_question_about_a_known_thing_asks_the_reasoner_the_one_fact_asked` (`tests/test_conversation.py`).
     `test_conversation.py`, `test_reasoning_owner.py`, `test_postgres_config_authority.py`: 34 passed on
     `lyric_dev`.
   - On the sandbox, all ten texts (a probe with the experiment's own scoring, nothing recorded): "Is the tank full?"
     is "Yes. The tank is full.", "Is the tank empty?" stays unanswered, the other questions about "the X" (the
     method, the account, the server, the company) stay unanswered. One wrong, "What absorbs the light?", is the
     `scored` weakness below (a recital counted wrong), on a path this step does not touch.
   - Measured on UNDERSTANDS-PROSE-01 on main (`results/20261016T125637Z.md`, 26 minutes, nothing written):
     sentences 4 of 33, right **9** of 37 ("Is the tank full?": "Yes. The tank is full."), wrong 1 of 37. The wrong
     one is "What is the largest animal on Earth?" again: the same recital as the run before, without the
     "I remember:" line recall put first that time, so `scored` counts it wrong. It flips with recall's order from
     run to run; the wrong-answer bar (≤ 2%) fails on it alone.
3. **[not a defect, measured on main 2026-10-16] Hyphenated words read as one word in a strict reading.** They
   already do. Read only on main (nothing written): "Python is high-level.", "... general-purpose.",
   "... object-oriented.", "... garbage-collected." and "Tom is well-known." each read with the hyphenated word as one
   word ("high-level" is held as `high` `-` `level`, the pieces a sentence makes); "Python is a high-level language."
   reads `isa(python, high-level language)`. The three prose sentences fail on what joins words, and fail the same
   with no hyphen: "Python is a popular, general programming language." (a comma between modifiers) and "Python is
   typed and collected." ("and" between properties) are unread too. Both are step 5. Seen on the way, a misreading
   left for the undecided-readings work: "Python is a general-purpose language." reads "Python is" as something
   owned by python and "a" as the angstrom.
4. **[done 2026-10-16: sentences 4 → 7 on UNDERSTANDS-PROSE-01, all three held as misread] Trace why names main
   holds are refused** ("blowhole" and "Eiffel
   Tower" are in WordNet, yet the reply was "something I have no name for yet"). Fix what the trace shows.
   - Traced on main, read only (nothing written): no name was refused. The reply is `Conversation._telling`'s for a
     fact that still holds a variable after binding, and every telling of a happening has one: the happening itself
     (`instance_of(?v0, bark)`). "The dog barked." and "Tom kicked the ball." were refused the same way, so no
     happening told in a conversation was ever held, and none could be asked about.
   - Teaching already names a told happening (`teaching.told_events`, decided 2026-10-04: one event, named by its
     kind and its telling; "some shoe" stays open). `_telling` (protected module, edited with no substrate running)
     now names each happening the same way, from the meaning with its known things found (so a kick of another ball
     is another kicking, and the same telling again names the same one), as a particular of the teller's context.
     `_incoming_relations` also reads the speaker's own context (`edges_naming`), so "What did Tom kick?" finds the
     kicking that points at Tom.
   - Sandbox, remembered and not: "Tom kicked the ball." then "Did Tom kick the ball?" is "Yes. Tom kicked the
     ball.", "What did Tom kick?" and "Who kicked the ball?" are "Tom kicked the ball.", "Did the dog bark?" is "Yes.
     The dog barked."; "Did Tom kick the box?" is not answered. Remembered, the kicking is held in the teller's
     context only (`scoped_concept_relations`); the world holds nothing of it.
   - All ten texts on the sandbox (probe, nothing recorded): sentences 4 → 6 of 33, right 7, wrong 1 (the same
     `scored` case).
   - Tests: `test_a_happening_told_is_held_as_one_event_of_the_tellers`,
     `test_what_a_speaker_told_points_at_a_thing_from_their_own_context` (`tests/test_conversation.py`);
     `test_conversation.py`, `test_reasoning_owner.py`, `test_postgres_config_authority.py`: 36 passed on
     `lyric_dev`.
   - Still open, for the owner: an unknown that is not a happening stays unheld, as decided 2026-10-04 ("A dog
     barked.", "a new method", "three engineers", "a blowhole"). Holding them means naming each as a new particular of
     the teller's context. And a held happening is said back by its stored name ("Noted - I'll hold that about
     kick_99d12979."), as a particular already is ("... about ball_1."): a held fact that cannot be said alone falls
     back to its name.
   - Measured on UNDERSTANDS-PROSE-01 on main (`results/20261016T140446Z.md`, 25 minutes, nothing written):
     sentences 4 → **7** of 33, right 9 of 37, wrong **0** of 37. The three sentences now read are all held as main
     misreads them, which the refusal had hidden: "The company hired three engineers in May." is held as engineers
     that are hired, the engineers taken for the happening (said back "An engineer 2608b000 is hired."); "The blue
     whale is the largest animal on Earth." with "animal" a happening; "Guido van Rossum began working on Python in
     the late 1980s." with the working done by the listener. `told_events` names any unknown of a kind that something
     is done by or to: right of a taught meaning, which is given; of a misreading it names what the misreading made a
     happening. Wrong went 1 → 0 only because "What is the largest animal on Earth?" began "I remember:" again (the
     `scored` weakness). The misreadings are the undecided and misread readings' work, not this step's.
5. **"and" joins things in one slot** ("carbon dioxide and water": both done the same thing), and so does a comma
   between modifiers ("a high-level, general-purpose programming language"; "structured, object-oriented and
   functional programming").

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

**Scripts from these sessions** are in `logs/handoff_2026_10_14/`. `logs/` is ignored by git, so they exist only on
this machine. Run them from the `Lyric/` folder; they read and write `logs/`.

| Script | What it does |
|---|---|
| `check_forms.py` | Verb sentences, review and plural questions, and all lessons; writes the misses to `logs/check_forms_lessons_missed.json` |
| `listener_measure.py` with `listener_eval.py` | Each kept reading weighed with the listener's own code, the old rule replayed verbatim, worths counted, and scored on lessons, held-out lessons, never-taught probes and questions. Needs `structure_probes_after.json` and `questions_gold.json` beside it. `listener_main.json` is today's measurement |
| `why_choice2.py`, `why_lessons.py` | Every reading and its evidence for chosen sentences |
| `readiness_probe.py`, `working_probe.py` | Texts told to a no-memory conversation, then questions |

**From a cloud session** (no Mac, no store): the API gateway (repository `dominion-labs`, `lyric_store_api.py`)
reads both stores and the records runs leave, read only, under `$GATEWAY_BASE/api/admin/lyric-store/`, with the
header `X-Lyric-Store-Token: $LYRIC_STORE_TOKEN` (both set in the cloud environment). Routes: `stores`;
`{store}/tables`; `{store}/tables/{table}?schema=` (columns, indexes); `{store}/tables/{table}/rows` and `/count`
(filters `eq.<column>=`, `like.<column>=`, `contains.<column>=<json>`, e.g. `contains.tags=["analysed_sentence"]` on
`schema=memory_hot`, table `memory_hot`); `{store}/activity` (who is connected: a teach run shows here);
`{store}/writes` (write counters: read before and after a run); `files?path=` (folders and text files under
`experiments/`, `docs/`, `logs/`; `&tail=N` for a log's end). This is how a session checks what the owner ran.
Every command given to the owner starts with `cd ~/"Dominion Labs/Lyric"`, which works from any folder; never assume
where the owner's terminal is. Left in `services/api-gateway`, a run finds no `./venv_lyric`. Left in the Dominion Labs
folder, a pull pulls the wrong repository: that folder is a git repository of its own whose `origin` is
`dominion-labs` (the gateway's), and its history diverges from it, so `git pull --ff-only origin main` there is
refused, and a push from there would try to send the whole folder (§2).

```
curl -s -H "X-Lyric-Store-Token: $LYRIC_STORE_TOKEN" "$GATEWAY_BASE/api/admin/lyric-store/stores"
curl -s -H "X-Lyric-Store-Token: $LYRIC_STORE_TOKEN" "$GATEWAY_BASE/api/admin/lyric-store/files?path=logs/treebank_production_run.log&tail=40"
```

- Never print `$LYRIC_STORE_TOKEN`, and never put it in a file, a commit or a message.
- The gateway runs on the Mac from `services/api-gateway` (its `start.sh` loads the Dominion Labs folder's `.env`,
  which holds `LYRIC_STORE_PG_PASSWORD` and `LYRIC_STORE_TOKEN`); restarts are the owner's. A change to the gateway is
  pushed to `dominion-labs` and pulled there, then the owner restarts it.
- Every new GET route that answers one person's data sets `Cache-Control: no-store` or relies on `shared_cache.py`:
  Cloudflare caches by URL (§6).
- On the Mac, `psql` is not on the PATH: use `/opt/homebrew/opt/postgresql@16/bin/psql` with the options
  `scripts/watch_teaching.sh` uses, or `-U lyric_reader` with `PGPASSWORD` from the `.env` for reading only.

**UNDERSTANDS-PROSE-01 on main** takes about 26 minutes and is started by the owner: a session's attempt to start
it on main was refused by the permission check. Read-only scripts that load the reader's view only
(`check_forms.py`) were allowed.

**Stack dumps** of a running teach: `kill -USR1 <pid>` writes `logs/stack_teach_<pid>.txt`. The macOS `sample`
command works on your own processes; `py-spy` needs root.

## 6. Pitfalls found this session

- **Beliefs with no `memory_id` are silently not stored** (see §2).
- **The worthiness filter judged what was taught.** A memory not exempt by tag or origin goes through the complexity
  threshold; `learn_word_classes` and `learn_pronunciations` count a decline as skipped and say nothing. Teaching is
  exempt by origin now (2026-10-16 (6)); how many word classes and pronunciations earlier passes lost is not measured.
  A new kind of taught memory needs no tag of its own to be kept, but one recall must not answer from needs its tag in
  `EXEMPT_EVENT_TAGS`.
- **Cloudflare caches by URL.** It never sees the token, cookie or user a request carried, so anything it holds goes to
  everyone. A route that answers one person's data must say `no-store` (the gateway now does by default for `/api/`
  and JSON).
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
- **A known thing loses its `given` mark once it is named** (`MeaningFact.renamed`, by design). After binding, the
  fact saying what it is reads like any asked fact; whatever needs to tell them apart must do it where what was
  found is known (`Conversation._reasoned_answers`).
- **A person's tellings and the world's are read by different calls.** A reasoner that reads only the world's store
  (`held_conditionals`, `load_subgraph` without `actor`) never sees what a person told; pass the `actor` it was asked
  for.
