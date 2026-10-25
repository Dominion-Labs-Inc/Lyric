# Experiments

Each experiment has its own folder with a short `README.md`: what it tests, how to run it, and what its
saved results say. Run everything from the Lyric folder with `./venv_lyric/bin/python3`.

**Where results go.**
- **Newer experiments** save every run through `_evidence.py` to `<folder>/results/<UTC timestamp>.json`,
  with a short `.md` summary beside it built from the same data. A run never overwrites an earlier
  one: a second run in the same second gets a `_2` suffix.
- **Older experiments** either only print, or write one fixed file (`manifest.json`, `result.json`,
  `last_run.txt`) that each run replaces.

The standing record of measurements is `docs/research/BENCHMARKS.md`; session notes are in
`docs/research/LAB_NOTEBOOK.md`.

**Which database.** `lyric_db` is the main model's store: it holds only what the substrate was taught on
purpose, so nothing is run against it to try things out. `lyric_dev` has exactly the same structure (copied
2026-09-27) and is the sandbox for build, test and experiment runs:
- run with `POSTGRES_DATABASE=lyric_dev`
- tests use it by default (`tests/conftest.py`)
- `scripts/reset_dev_store.py` empties the whole sandbox line and can empty nothing else

**Releases.** The model is taught in development and served, frozen, from a numbered release in staging and
production (`docs/research/SEPARATION_MAP.md` §9). Every database of a line is named from its development
database:
- `<line>_model_v<N>`: a release, read-only;
- `<line>_model_registry`: every release and its status;
- `<line>_{staging,production}_{runtime,user_context,learning}`: what a serving environment keeps.

`scripts/release.py` cuts, stages, promotes, rolls back and verifies releases, and takes what production kept into
development. An experiment that serves a release works on the sandbox line: the sandbox reset drops the releases
its runs cut.

Most experiment scripts default to `lyric_db` with `os.environ.setdefault`, so an outer
`POSTGRES_DATABASE=lyric_dev` sends them to the sandbox. A lesson is taught into `lyric_db` only once it has
been verified in the sandbox, and that run names `lyric_db` on purpose.

## Governance — the constitution

| Experiment | What it tests | Saved runs |
|---|---|---|
| [CONSTITUTION-01](CONSTITUTION-01/) | The constitution judging real acts, with intent taken from real reasoning | `results/` |
| [CONSTITUTION-02](CONSTITUTION-02/) | The same under noise, coercion, forged intent, evasion, laundering, TOCTOU | `results/` |
| [CONSTITUTION-03](CONSTITUTION-03/) | A determined adversary, in campaigns (8/8 checks since 2026-09-20) | `results/` |
| [GOVERNANCE-ABSORPTION-01](GOVERNANCE-ABSORPTION-01/) | **Retired 2026-09-26.** The old gate and the constitution on the same acts; its final run (0 regressions) licensed deleting the old gate | `results/` |
| [GOVERNANCE-MONITOR-01](GOVERNANCE-MONITOR-01/) | **Retired 2026-09-26** (module deleted). `RuntimeGovernance.monitor()` as a live monitor | printed only |
| [INPUT-VALIDATION-01](INPUT-VALIDATION-01/) | **Retired 2026-09-26** (module deleted). The OLD gate's input validation (not the constitution's) | printed only |
| [systems/GOV-ABLATION-01](systems/GOV-ABLATION-01/) | Whether the promotion gate stops a false rule from gaining authority to act | see its README |
| [systems/GOV-CASCADE-01](systems/GOV-CASCADE-01/) | Whether one injected error contaminates authority as derivations get deeper | see its README |
| [THREAT-SENSE-01](THREAT-SENSE-01/) | Whether the substrate FEELS a threat, and whether feeling it changes what it does | `results/` + `.md` |
| [HARM-01](HARM-01/) | Law 3 against a definition of harm, interest by interest, and the ordering rule: the safer route outranks both the destructive form and a flat refusal | `results/` + `.md` |
| [THREAT-SENSE-02](THREAT-SENSE-02/) | Whether the substrate knows WHAT it is attacked with, and answers a campaign against a target in proportion (quarantine, escalating, human-lifted) | `results/` + `.md` |
| [CONSOLIDATION-01](CONSOLIDATION-01/) | Standing check: the Constitution is the ONE authority — nothing reaches the deleted governance and security modules — and every capability it absorbed works | `results/` + `.md` |
| [BEARING-01](BEARING-01/) | What the substrate perceives may move belief, affect and intent — and never permission | `results/` + `.md` |
| [TASK-GATE-01](TASK-GATE-01/) | A route the constitution replanned is planned again without the refused act, a step of a pursuit it sent back does not start, and the task boundary refuses nothing else | `results/` + `.md` |
| [TASK-GATE-02](TASK-GATE-02/) | Whether the task gate asks INTENT if the pursuit a task serves is still live, and refuses nothing whose pursuit is live | `results/` + `.md` |
| [PURSUIT-01](PURSUIT-01/) | Whether every piece of work carries the intent it serves, and its pursuit ends with what ended it — the constitution's verdict, never `abandoned` | `results/` + `.md` |
| [DOMAIN-DISCOVERY-01](DOMAIN-DISCOVERY-01/) | Whether the substrate DECIDES which domains exist, or only files whatever string a caller passed | `results/` + `.md` |

## Identity, users and concurrency

| Experiment | What it tests | Saved runs |
|---|---|---|
| [ACTOR-IDENTITY-01](ACTOR-IDENTITY-01/) | What a person teaches is scoped to their verified identity, not the session | printed only |
| [FRONTDOOR-IDENTITY-01](FRONTDOOR-IDENTITY-01/) | The front door binds the verified identity to the conversation | printed only |
| [SELF-PARTITION-01](SELF-PARTITION-01/) | **Retired 2026-10-07** (promotion by a second teller removed; the script is deleted). One shared mind plus separate per-user context, with promotion when users corroborate | printed only |
| [TASK-RESULT-01](TASK-RESULT-01/) | Fetching a job's result, visible only to the person who asked | printed only |
| [PER-USER-CONCURRENCY-01](PER-USER-CONCURRENCY-01/) | Several tasks per user, shared fairly under a global cap | printed only |
| [TOOLS-EXTERNAL-01](TOOLS-EXTERNAL-01/) | No tool is hardcoded to the substrate: chaos tools archived, security tools read the logs they are told to (an outside log database, or the substrate's own when named), file tools take their folder, AgentSO tools guarded | `results/` |
| [AGENTS-01](AGENTS-01/) | The substrate deploys agents of itself through its coordinator: findings returned, only granted tools used, refused past the allowance, collected without waiting, failures honest | `results/` |
| [OUTSIDE-DB-01](OUTSIDE-DB-01/) | The database tools (`postgres_query`, `mysql_query`) work on an outside database they are given and refuse the substrate's own server; the 13 that ran on its own database are archived | `results/` |
| [TASKS-AT-ONCE-01](TASKS-AT-ONCE-01/) | Sixty tasks at once inside the queue authority's one budget, three per person at most; work past that waits and is done | `results/` |
| [WORK-TALK-01](WORK-TALK-01/) | The conversation knows the substrate's own work: what it is doing, whether it finished, stop it (waiting or running), told once what it found | `results/` |
| [MESSAGE-01](MESSAGE-01/) | The substrate speaks first: unasked, at a set moment, once, to every front end of that person; held for the next turn when none listens; still owed after a restart | `results/` |
| [CAPABILITY-EMERGE-01](CAPABILITY-EMERGE-01/) | A capability emerges only as a method lifted from experience (since 2026-10-07 from the first task of its shape that worked, see FIFTY-01); it unlocks by how reliably it worked (world first, then each person) and can be withdrawn; done for a person, each act waits for their go-ahead ("Yes."/"No.") until it is unlocked for them; the constitution still judges every act; a held job survives a restart | `results/` |
| [EXPECT-01](EXPECT-01/) | Lyric learns what a person's world does on its own and expects it by a learned time: a change left undone lapses by its own reading as the world departing, answered as her operating mode allows (Observe tells, Assist offers, Delegate forms a goal); a miss told apart by what was observed is its own mistake and it learns; a tendency is never acted on; a waiting expectation survives a restart; charging every miss to the regularity (ablation) loses the departures | `results/` + `.md` |
| [EXPECT-02](EXPECT-02/) | EXPECT-01 at a powered scale (5 seeds, 45 worlds, ~180 departures) beside an engineered absence rule and two mined-rule systems behind the same mode gate. Run 10, 22/22: departures answered 0.91 (others 0.99-1.0); none of 313 never-handled files, 0.2% of late filings (mined ~8%), no 50% tendency, and none of 600 files acted against after a habit changed (engineered 600, mined ~190); Delegate and Assist put right 52 of 52 | `results/` + `.md` + `_cases.json` |
| [SYSTEM-QUEUE-01](SYSTEM-QUEUE-01/) | The queue authority alone: one owner of work, pool and scheduler; every public method has one job and a caller | `results/` + `.md` |
| [CHAT-CONCURRENCY-01](CHAT-CONCURRENCY-01/) | How many people can chat at once | printed only |
| [LOOKUP-SINGLEFLIGHT-01](LOOKUP-SINGLEFLIGHT-01/) | Many callers asking about the same unknown cause one lookup | printed only |

## Learning, motivation and affect

| Experiment | What it tests | Saved runs |
|---|---|---|
| [OPERATOR-REMOVAL-01](OPERATOR-REMOVAL-01/) | Learning a removal operator from the substrate's own deletions | `results/` |
| [TOOLDOMAIN-01](TOOLDOMAIN-01/) | A domain the substrate can act in and learn from, with nothing written by hand: the act names its domain, practice in a given sandbox teaches the operator, ordinary work files demonstrations | `results/` + `.md` (from 2026-09-28) |
| [TEACH-ACTION-01](TEACH-ACTION-01/) | A curriculum of acts in a sandbox it may practise in, and whether experience separates copy from move | `results/` + `.md` (from 2026-09-28) |
| [CAPABILITY-BENCHMARK-01](CAPABILITY-BENCHMARK-01/) | The capability benchmark: harness check (`experiment.py`) and measurement (`full_suite.py`) | `results/` (full suite) |
| [CAPABILITY-BASELINE-01](CAPABILITY-BASELINE-01/) | Capability baselines and regression tracking | printed only |
| [MOTIVATION-CLOSEDLOOP-01](MOTIVATION-CLOSEDLOOP-01/) | Closing one pursuit changes which pursuit comes next | printed only |
| [INTRINSIC-EVENTDRIVEN-01](INTRINSIC-EVENTDRIVEN-01/) | Intrinsic pursuit is triggered by events, not a timer | printed only |
| [INTEGRATION-LOOP-01](INTEGRATION-LOOP-01/) | The full know → do → frontier loop on a real task | printed only |
| [AFFECT-WIRING-01](AFFECT-WIRING-01/) | Approach and avoidance pressures now change behaviour | printed only |
| [INTEGRITY-01](INTEGRITY-01/) | Integrity measured as coherence, not success | printed only |
| [systems/EPISTEMIC-AFFECT-01](systems/EPISTEMIC-AFFECT-01/) | Changes in knowledge become feeling, in one direction only | `last_run.txt` |
| [SELFSTATE-01](SELFSTATE-01/) | Whether what the substrate KNOWS feeds its self-state, or only what it DOES | `results/` |
| [FEELING-OBJECT-01](FEELING-OBJECT-01/) | Whether a feeling can name what it is ABOUT, and whether a faded doubt leaves its question | `results/` + `.md` |
| [ARBITER-WIRING-01](ARBITER-WIRING-01/) | The behaviour arbiter deciding from measured pressures and real capacity | `results/` |
| [DRIVES-01](DRIVES-01/) | Each drive measured from something real, or honestly unmeasured | `results/` |
| [RULE-EVIDENCE-01](RULE-EVIDENCE-01/) | Whether a rule can say how sure it is, and whether the act carries it to the judgement | `results/` + `.md` |
| [RULE-AUTHORITY-01](RULE-AUTHORITY-01/) | 1,000 hidden worlds: whether a learned rule gets the authority to act only when evidence has seen it work and nothing contradicts it | `results/` + `.md` + `_worlds.json` (from 2026-10-01) |

## Planning

| Experiment | What it tests | Saved runs |
|---|---|---|
| [PLANNING-01](PLANNING-01/) | One owner for each kind of plan (temporal reasoning for state goals, the execution plan adapter for goals in words), and every planning path verified honest — proved plans grounded, unreachable goals yield no plan, template plans declare where their numbers came from | `results/` |
| [REPLAN-02](REPLAN-02/) | Knocked off course by a world its learned rule no longer fits, the substrate refutes the rule, replans from where the file really is, and still gets it there | `results/` + `.md` (JSON only before 2026-09-26) |
| [REPLAN-03](REPLAN-03/) | Its own operator, learned by practice in a directory it was given, pursued while the world changes under it: replans when something else moves the file, does not claim a goal the world refused | `results/` |
| [REPLAN-01](REPLAN-01/) | A pursuit whose rule the world refutes plans again inside itself, over what is still validated; one with nothing new is not planned again, and one whose world cannot be read is never planned against an invented world | `results/` |
| [RESEARCH-WRITE-01](RESEARCH-WRITE-01/) | A goal in words, set as the substrate's own (`set_goal`): its pursuit decomposes it, researches the topic, writes what it learned to the file it names, and reads it back before the goal is closed | `results/` + `.md` |

Record: `docs/research/BENCHMARKS.md` §6.

## Intent — reasoning's own account of what it is doing

| Experiment | What it tests | Saved runs |
|---|---|---|
| [INTENT-01](INTENT-01/) | The intent authority + store: formed on engagement, refreshed not rebuilt, goal-in-thread tree, content/shape split, restart survival | `results/` |
| [INTENT-02](INTENT-02/) | The bridge forms intent on every real `reason()` — formation, refresh, goal parenting, concurrency, latency, restart | `results/` |
| [RECONCILE-01](RECONCILE-01/) | Whoever owns a pursuit closes its intent once, from the world — plan, standalone operator (including refused), declared-tool operation; plan steps close nothing | `results/` |

Design: `docs/design/INTENT_AUTHORITY.md`. Record: `docs/research/BENCHMARKS.md` §5.

## Knowledge and domains

| Experiment | What it tests | Saved runs |
|---|---|---|
| [DOM-KG-01](DOM-KG-01/) | A knowledge gap versus a missing operator | `result.json` |
| [BORROWED-KNOWLEDGE-01](BORROWED-KNOWLEDGE-01/) | Borrowing a prior from a related domain | printed only |
| [OPERABILITY-BAR-01](OPERABILITY-BAR-01/) | The earned half of the operability bar | printed only |
| [ENV-INVESTIGATE-01](ENV-INVESTIGATE-01/) | Scanning the environment into knowledge | printed only |
| [SYSML-01](SYSML-01/) | A system's SysML v2 model written from its legacy documents (inventories, cable run sheet, interface document): every element sourced, disagreements kept, accepted by the OMG pilot implementation | `results/` + `.md` + `.sysml` |
| [systems/KNOW-50](systems/KNOW-50/) | 50 questions about what it was taught | `manifest.json` |
| [systems/VERIFY-01](systems/VERIFY-01/) | A snapshot of every faculty's pipeline as it runs today | see its README |

## Perception (`systems/`)

| Experiment | What it tests | Last saved outcome |
|---|---|---|
| [PERCEIVE-01](systems/PERCEIVE-01/) | Sensor, image and video structure become knowledge | pass (2026-09-13) |
| [PERCEIVE-02](systems/PERCEIVE-02/) | Sight over real files | pass (2026-09-13) |
| [PERCEIVE-03](systems/PERCEIVE-03/) | Learning to name what it sees | pass, 5/5 (2026-09-17) |
| [PERCEIVE-04](systems/PERCEIVE-04/) | Remembering a picture | pass (2026-09-13); **8/8** (2026-09-29): its summary and sight trace, never the photograph; the memory is forgotten after |
| [PERCEIVE-05](systems/PERCEIVE-05/) | One perception pipeline, with perception kept in memories | pass (2026-09-09); **9/9** (2026-09-29): the perception faculty is the one admitter; runs in `lyric_dev` and removes what it wrote |
| [DEVICE-01](systems/DEVICE-01/) | Lyric learns a device it operates through as it learns where it runs: a new kind of device is an environment domain, what exists there (and what does not) is its own knowledge, the person's device, settings and positions are theirs | **20/20** (2026-10-03). The first run's 13/20 found 2 real defects, both fixed: `is_a` is refused by the learning door (a device is now `instance_of` its model), and a position's points and signs were lost in its name (now `25.762N 80.192W`) |
| [PERCEIVE-EVAL](systems/PERCEIVE-EVAL/) | Perceive and name, measured | naming recall 1.0, abstention 100%, 0 hallucinations (2026-09-17) |
| [HEAR-01](HEAR-01/) | Hearing on sight's own path: real recordings heard, believed, remembered, named by induction; known sounds; a clip seen and heard | pass, 42/42 (2026-09-28) |
| [RECALL-01](RECALL-01/) | Remembering is rebuilding: a hearing kept as a trace (no recording) and a seeing as a gist, rebuilt from memory and perceived as the same | pass, 11/11 (2026-09-28) |
| [SPEECH-01](SPEECH-01/) | Spoken words and voices taught by hearing an example, each lesson the same hearing memory as any other; heard in running speech through `hear()` as the words said, in whose voice; firm readings right | pass, 30/30 (2026-09-28) |
| [SPEECH-02](SPEECH-02/) | The lessons' own words taught by hearing them said (MSWC, LibriSpeech), several speakers each, and heard said by untaught speakers: every lesson a hearing in the shared mind, read back exactly; a firm reading right | `results/` + transcript |
| [SPEECH-03](SPEECH-03/) | Offline: taught the sounds words are made of (phones from LibriSpeech's aligned times, 40 speakers) and nothing of the words, the word that fits a stretch best by its phones is the word an untaught speaker said more often than whole-word matching reached | `results/` + transcript |
| [SPEECH-04](SPEECH-04/) | The substrate taught the sounds words are made of by hearing sentences told which sound is said when (`learn_phones`) and how words are said (CMUdict through the teaching pass): each lesson a hearing kept and read back exactly; words from untaught speakers heard by their sounds, a firm name right | `results/` + transcript |
| [SPEECH-05](SPEECH-05/) | A trained phone recogniser that reports only which sounds were said (no words, no language model), with Lyric's own pronunciations, word search and listener: words said by untaught people heard well enough to follow a sentence | `results/` (`20261003T220404Z` 7/8: 76.7% of sentence words, 47.3% of words alone; a firm name wrong 16 of 557), `work/` (offline) |
| [FRESH-LESSON-01](FRESH-LESSON-01/) | Taught one lesson no experiment has tested (new words, two new sentence shapes), Lyric holds its facts as facts, beliefs and memories, reads sentences it was never taught, answers from what it was taught without making anything up, keeps it across a restart, and moves a belief when told otherwise | `results/` |
| [FRESH-LESSON-02](FRESH-LESSON-02/) | FRESH-LESSON-01's checks on a second lesson written after its fixes and frozen before its own run: other words, facts, shapes ("is found in", "comes from") and questions | `results/` |
| [FRESH-LESSON-03](FRESH-LESSON-03/) | FRESH-LESSON-01's checks on a third lesson written after the first two lessons' fixes: other words (one taught in a -th plural), facts, shapes ("is kept in", "sleeps in") and questions | `results/` |
| [QUESTION-FORMS-01](QUESTION-FORMS-01/) | Questions with "does", "do" and a word left at the end, taught by english_31 beside the sentences they ask about, are read and answered about new words; whether they carry to verbs no lesson asks about is measured | `results/` |
| [QUESTION-FORMS-02](QUESTION-FORMS-02/) | With happenings held as events (teaching.told_events), Lyric answers where something happens in shapes english_31 teaches and in shapes no lesson asks about, and what happened: what was done, who did it, whether it was done | `results/` |
| [MAIN-ENGLISH-01](MAIN-ENGLISH-01/) | After the English lessons were taught into the emptied main model (english_01–31, then english_01–39), main reads every sentence they teach with the meaning it was taught, and Phase 1's never-taught sentences as written, from its own store, and the reading writes nothing | `results/` |
| [READ-LONG-01](READ-LONG-01/) | How long the reader takes on sentences of 8 to 60 words with no punctuation, transcripts and run-on speech of taught words, and whether they read whole (ENGLISH_CURRICULUM Phase 0) | `measure.log`, `measure_run_on.log` |
| [ENGLISH-01](ENGLISH-01/) | Phase 1, the writing system's marks: taught english_32–39 after english_01–31 (comma, apostrophe, colon and semicolon, titles, parentheses and dashes, money and dates, times, quotation marks), Lyric reads each mark's commonest uses in web English in sentences it was taught and in ones it was not, keeping what earlier lessons taught; EWT survey of every mark | `results/` |
| [UNASSERTED-01](UNASSERTED-01/) | Told what someone said or wants, a happening denied, or one that might be, Lyric does not answer them as happened; told what happened, it does (`MeaningFact.unasserted`, TEACHING.md §12b) | `results/` |
| [SENSES-TOGETHER-01](SENSES-TOGETHER-01/) | Each sense measures in its own process: hear, see and reason at the same time in every combination, results right, reasoning not queued behind perceiving | **16/16** (2026-09-29, after the perception manager was folded into the faculty; loop at most 92 ms). Before that rerun: 11/16, the answer check was case-sensitive (the word now opens the answer) and the loop 102 ms beside another session's live run. Earlier: **16/16** (2026-09-29, after the reader switch landed; loop held at most 30 ms together). Earlier: 15/16 (loop 116 ms, database layer), then 12/16 (one chained answer, from the reader switch in progress) |
| [SONGS-01](SONGS-01/) | Music heard with no model: songs taught by hearing and known through a room and a codec, key and tempo as annotated, a sung melody's notes, recalled as the same notes, speech heard as no music | **25/25** (2026-09-29, fourth run, with songs taught by humming and known hummed by another). Before: **20/20** (2026-09-29, third run). The first run's 17/20 found 2 real defects, both fixed at the root: a plain tone passed the landmark floor (now distinct landmarks); names lost a leading article in the shared identity rule (A major -> major; names now keep their words) |
| [MEMORY-SOUND-01](MEMORY-SOUND-01/) | Memory recalls a sound by the sound itself: heard before (in words, graph, belief), through a room and a codec, a song taught later names its earlier hearing, injected by sound, a person's hearing only for that person; what is heard and seen within a pursuit is part of its one memory | **23/23** (2026-09-29). Found and fixed: the media store moved a sound to a second memory of the same bytes. **23/23** again after the rename and the perception change |
| [MEMORY-SIGHT-01](MEMORY-SIGHT-01/) | Memory recalls a picture by the picture: a seeing keeps its summary and sight trace, never the photograph; the same picture and another view of the same thing are known as seen before; naming reaches back; injected by sight; a person's only for them | **17/17** (2026-09-29); 15/17 first, while the embedding model's path was broken |
| [TUNES-01](TUNES-01/) | A song taught from one person humming it is known hummed by another, in their own key and pace, no model (HumTrans; TEST heard once against 355 taught tunes) | whole hums 95.1% right first, 85.1% named, 100% right when named; half hums 84.0%, 59.5%, 99.3%; untaught hums named 0.1% / 2.3% (2026-09-29) |
| [MELODY-01](MELODY-01/) | The melody of a full mix, no model (salience, a Viterbi path, voicing), and a song taught from its mix known from its melody sung alone (MDB-melody-synth; TEST heard once) | frames: pitch 47.2%, overall 56.6% (YIN on the mix: 11.4%, 29.6%); end to end: 59.4% right first, 40.6% named, 100% right when named; never-taught melodies named 3.1% (2026-09-29) |
| [READ-01](READ-01/) | Reading is the substrate's own sense, beside sight and hearing and at once with them: any document read, known again by its text, what a person's document says kept to their context, one moment one memory | **27/27** (2026-09-30) |
| [LIVE-01](LIVE-01/) | Always listening and looking: keeps only what is said to it by its taught name (and firmly heard talk that follows), drops the rest inside the ear; kept speech heard, remembered in words, looked at, answered through the front door | pass, 17/17 (2026-09-28); **18/18** (2026-09-29): now teaches the fact it asks about, and checks the spoken answer is yes. With the name "Lyric": 12/18, then **18/18**. The ear let go of the start of a first sound still going on, so "Lyric" (one half-second sound) lost its opening; fixed in `Ear._let_go`. What was asked is what follows the name. It teaches "a cat is a mammal", so nothing it is asked is looked up on the web |

## Education ladder (`edu/`)

See [edu/README.md](edu/README.md).

Several of these scripts import modules that have since been deleted: `core.model_policy`, and
`core.services.unified_llm` (the LLM teacher, retired on 2026-09-13), and for EDU-16 `core.semantics.lexicon` (deleted when word classes moved into memory) and `core.semantics.class_induction` (backed up to `archive/superseded_language_2026-09-27/`). The affected scripts are
CSP-AGI-1, EDU-04, EDU-05, EDU-06, EDU-07, EDU-08, EDU-09, EDU-12, EDU-13, EDU-14, EDU-15, EDU-16 and
[systems/SESSION-01](systems/SESSION-01/). Their saved results stand as recorded, but the scripts do
not run as written.

## Shared worlds and tools

| File | What it is |
|---|---|
| `_evidence.py` | Run records: a new JSON file per run, plus its `.md` summary |
| `e2e_world.py`, `e2e_common.py` | A real filesystem world: rooms are directories |
| `archive_world.py`, `warehouse_world.py` | Further real worlds in other domains, with different predicates |
| `warehouse_stochastic.py`, `warehouse_latent.py`, `warehouse_complex.py` | The EDU warehouse with unreliable outcomes, a hidden cause, or twelve conditions |
| `computation_world.py` | A world where the values a plan needs do not exist until it runs |
| `data_world.py` | A data environment: values are held, operations compute, and `observe()` reads back what is there |
| `list_machine.py` | A machine that supplies instructions, not answers |
| `sentence_machine.py` | Moved to `core.semantics.sentence_machine` |
| `archive_teach.py` | Learns the ARCHIVE operator from real execution |
| `kite_teach.py`, `kite_evaluate.py`, `kite_ablation.py` | KITE-17: teach, evaluate, and test whether the capability lives in the learned rules |
| `substrate_baseline.py` | Freezes what the substrate held before an experiment taught it |
| `verify_wiring.py` | Evidence for the evidence-source wiring (writes `WIRING_EVIDENCE.json`) |
| `world/habitat.py` | A contained sandbox world (`world/sandbox/`) that exercises every faculty |

## System isolation (`SYSTEM-*`)

Each core system on its own, on the live substrate, through its own authority: one instance and one
construction site, its contract exercised with real writes that are removed by id, and its callable surface
audited. Runs report **behaviour** (pass/fail) apart from **wiring** findings (public methods nothing in
`core/` calls) and **completeness** findings (bodies that raise, return a literal, or are empty) —
`_isolation.py`. SYSTEM-QUEUE-01 is listed under *Identity, users and concurrency*.

| Experiment | What it tests | Saved runs |
|---|---|---|
| [SYSTEM-REASONING-01](SYSTEM-REASONING-01/) | Reasoning answers what it holds with no model and refuses what it cannot ground | `results/` + `.md` |
| [SYSTEM-LEARNING-01](SYSTEM-LEARNING-01/) | One learning door; demonstrations become a rule; strategy outcomes and predictions are real learning | `results/` + `.md` |
| [SYSTEM-BELIEFS-01](SYSTEM-BELIEFS-01/) | Beliefs move with evidence and must be grounded; known unknowns survive restart and resolve only when learned | `results/` + `.md` |
| [SYSTEM-MEMORY-01](SYSTEM-MEMORY-01/) | Stored, found, superseded, forgotten on request, never merged; a user's memory is theirs by meaning, wording and tag | `results/` + `.md` |
| [SYSTEM-DOMAIN-01](SYSTEM-DOMAIN-01/) | A domain exists once, competence moves progress, a gap is detected | `results/` + `.md` |
| [SYSTEM-SEMANTICS-01](SYSTEM-SEMANTICS-01/) | The one write door: admitted once, refused when unrepresentable, conditionals held | `results/` + `.md` |
| [SYSTEM-INTENT-01](SYSTEM-INTENT-01/) | A pursuit formed once per key, refreshed, reconciled, forgotten | `results/` + `.md` |
| [SYSTEM-PERCEPTION-01](SYSTEM-PERCEPTION-01/) | Sensing, and sight end to end on a real photograph | `results/` + `.md` |
| [SYSTEM-SELF-01](SYSTEM-SELF-01/) | Appraisal, the arbiter and motivation, each one authority | `results/` + `.md` |
| [SYSTEM-HEALTH-01](SYSTEM-HEALTH-01/) | One health and one recovery authority; an unknown component refused; a failure and its history recorded | `results/` + `.md` |
| [SYSTEM-EXECUTION-01](SYSTEM-EXECUTION-01/) | Rules, bindings and tools: judged, then done; the unknown refused | `results/` + `.md` |
| [SYSTEM-CONVERSATION-01](SYSTEM-CONVERSATION-01/) | What a speaker tells of their own things (names the world does not hold) is theirs: held in their context, answered back to them only, remembered as theirs; their context refuses what the world's door refuses. Since 2026-10-07 a kind told goes to the world's gate (see SPLIT-01) | `results/` + `.md` |
| [INSTANCES-01](INSTANCES-01/) | Many instances of the model, one store: no lost belief evidence or strategy outcome, a resolution is final, a job runs once | `results/` + `.md` |
| [TEACH-AND-DO-01](TEACH-AND-DO-01/) | A small lesson through the one teaching path, then real work on it: answered back, a gap looked up on the web, a document read, a planned summary written, code run; which learning stores moved | `results/` + `.md` |
| [LEARNED-WORK-01](LEARNED-WORK-01/) | Teach a new domain (cathodic protection), then watch the substrate on it: what it knows and does not, what it says it can do, multi-step work built on the lesson, an inspection report to judge, and whether it is different after trying | `results/` + transcript |
| [ENGLISH-LESSON-01](ENGLISH-LESSON-01/) | First American English lesson on the wiped store: a University of Illinois preschool lesson's sentences taught through the one teaching path, what it read and held, and its answers | `results/` + transcript |
| [ATTEST-01](ATTEST-01/) | **Retired 2026-09-27** (imports `core.semantics.lexicon`, deleted when word classes moved into memory). Whether reading earned a word its class in the lexicon | printed only |
| [POS-01](POS-01/) | **Retired 2026-09-27** (imports the deleted lexicon). Whether teaching took a word's class from what was known rather than from an article | printed only |
| [SHAPES-BASELINE-01](SHAPES-BASELINE-01/) | What the sentence and word shapes written into the code do with nothing learned: 45 sentences (preschool, questions, commands, a paragraph, joined clauses, African American English, slang, abbreviations, punctuation) and word forms (contractions, plurals, past tenses) | `results/` + transcript |
| [SHAPES-LEARN-01](SHAPES-LEARN-01/) | Step 1 of the shapes plan, in the sandbox: sentences taught with their meaning become patterns (memory), scored (beliefs), in the English domain; their facts held; taught sentences read and are said back; re-teaching counts once per source; the main store untouched | `results/` + transcript |
| [SHAPES-LEARN-02](SHAPES-LEARN-02/) | Step 2 of the shapes plan, in the sandbox: a kindergarten lesson taught one pair at a time becomes holophrases, item-based constructions with slots, lexical fillers and the links between them (the Leuven method, all seven repairs in the paper's order), held in memory and scored by beliefs; sentences never taught but made of seen parts read and are said; unseen pairings and shapes are refused; word kinds emerge untold | `results/` + transcript |
| [SHAPES-LEARN-03](SHAPES-LEARN-03/) | Step 3, parts 1 and 2 of the shapes plan, in the sandbox: the first English lesson (`data/lessons/english_01.json`, 228 examples) taught through the one path states nothing about the world; the engine then reads sentences never taught (fillers of a learned kind, new names in known frames, sentences without capitals or marks, a paragraph) to the meaning they have, says the kind of each utterance, and leaves the untaught unread; SHAPES-BASELINE-01 and NLU-01's prose measured beside the written reader | `results/` + transcript |
| [SHAPES-LEARN-04](SHAPES-LEARN-04/) | Part 1 of step 3b (every sentence gets a reading), in the sandbox: told sentences it cannot read whole, the substrate says what it understood, asks about the words it does not know, and remembers what was said; answered by example through the one teaching path (`data/lessons/english_02.json`: and, or, true, my ... is not a ..., he is ...), with none of those sentences, it reads the sentences it asked about; NLU-01's prose measured whole and in parts | `results/` + transcript |
| [SHAPES-LEARN-05](SHAPES-LEARN-05/) | Part 2 of step 3b (phrases in slots), in the sandbox: taught noun phrases by example (`data/lessons/english_03.json`: words before a thing, several of them, where a thing is, whose it is), the substrate reads noun phrases never taught -- other words in a learned phrase, phrases inside phrases, phrases in frames they were never taught in -- to the meaning they have, and every sentence of the three lessons still reads; NLU-01's prose measured whole and in parts | `results/` + transcript |
| [SHAPES-LEARN-06](SHAPES-LEARN-06/) | Step 5 of the shapes plan (saying through what was taught), in the sandbox: taught a sentence for every link kind (`data/lessons/english_04.json`), the substrate says facts of those kinds with the sentences it was taught and each reads back to what it meant; it reads sentences of those kinds never taught; its conversation notes and answers with them, about a name it never met | `results/` + transcript |
| [SHAPES-LEARN-07](SHAPES-LEARN-07/) | Step 4 of the shapes plan (word shapes), in the sandbox: taught plurals, possessives and contractions by example (`data/lessons/english_05.json`), the substrate finds the changes at a word's end from the fillers it holds, each in its context, reads plurals, possessives and contractions it was never taught to the meaning they have, reads words never met one to a slot, and says a concept in the shape its slot takes, every sentence reading back to what it meant; NLU-01's prose measured whole and in parts | `results/` + transcript |
| [SHAPES-LEARN-08](SHAPES-LEARN-08/) | Part 3 of the last step (every English word), in the sandbox, on a sample of WordNet: each noun fact is said by the substrate through the frames it was taught, in WordNet's words, and learned from what it said; every noun taught reads in a question never taught, the facts are held (negative control included), and facts said read back; the cost measured by stage | `results/` + transcript |
| [SHAPES-LEARN-09](SHAPES-LEARN-09/) | Part 2's first lessons and saying new words by use, in the sandbox: english_01–07 taught (function words, names, words without "a", kinds of people written with a capital), never-taught sentences with them read, and WordNet's nouns in a sample said as words used like them are (no name or uncounted word after "a", no counted word bare, "a"/"an" by the next letter); SHAPES-LEARN-08's faults said rightly | `results/` + transcript |
| [SHAPES-LEARN-10](SHAPES-LEARN-10/) | The gate before all of WordNet goes into the main model: SHAPES-LEARN-08 again after the lessons, with the engine as it now is, and English's "a"/"an" checked on every sentence said; nouns read in never-taught questions, facts held (negative control), said back | `results/` + transcript |
| [SENSE-01](SENSE-01/) | The gate before all of WordNet goes into the main model, with the listener: each word taken in the sense meant (what memory holds, then how often the word names each thing); WordNet's senses of the lessons' words and every kind of WordNet record taught after the lessons; every lesson sentence taken as before, the blocker sentences in the lessons' sense, facts said and taken back | `results/` + transcript |
| [SENSE-COVERAGE-01](SENSE-COVERAGE-01/) | Every sense of a word reaches the listener, wherever the word stands: each sense reported in its own frames, none left out of its siblings' frames for how well it fits there; misses counted by why. Read-only on the sandbox | `results/` + transcript |
| [SENSE-SAID-01](SENSE-SAID-01/) | What a word is said of (Brown) added to how often a sense is met (WordNet) as one activation takes more of the senses WordNet's authors tagged in its definitions than frequency alone; taken first, with frequency only on a tie, fewer. Offline, no store | `results/` + transcript |
| [COMPREHENSION-01](COMPREHENSION-01/) | The questions that failed on 2026-09-19 (`docs/research/COMPREHENSION_SCOPE.md` §3–4), asked again through the conversation on the sandbox after WordNet's records about their words are taught: a greeting greeted, a yes/no with no answer declined without reciting, a place asked for answered or declined, no question of which sense for a word one sense of which anyone means, recall about what was asked. 30/30 on 2026-10-02 and 10-03 (`20261003T012321Z`, `20261003T052358Z`) | `results/` + transcript |
| [COUNTABILITY-01](COUNTABILITY-01/) | Whether a noun sense is counted, decided by the hand-labelled senses of its kind (BECL), finds more of the lexicon's uncounted senses than the word's uses in real text, and the source's chain (`WordNetSource.use_of`) is right more often than calling every sense counted or than real text alone, on senses held out by word. Offline, no store | `results/` + transcript |
| [SEPARATION-01](SEPARATION-01/) | Staging serves release 1 of the model taught in the sandbox, and keeps runtime, the model and each person's context apart: the lesson is in the release; a person's facts and memories are in user context; the substrate's own new memory waits in the learning store and is never read back; no search, answer or research for one owner reaches another's; the release, development and the main line are unchanged | `results/` + transcript |
| [RELEASE-01](RELEASE-01/) | The release lifecycle on the sandbox line: cut (read-only, checksummed, with the code it was cut with), staged before promoted, tampering and other code refused, production serving with nothing refused and its own learning refused, the release unchanged by serving, production's memory and recalls taken into development and carried by release 2, rollback | `results/` + transcript |
| [CANARY-01](CANARY-01/) | What a person gives the substrate through its real doors (a telling of a name the world does not hold, the same through their work context under an organization, a question answered by reasoning, a word looked up, a job run to its end, an image carrying a QR code) stays in their context: markers planted in them are found in no memory row of anyone else's, another person asking about them is told neither (and, the control, is answered what the person told of a kind), the substrate's own note is its own, and tables with no owner column that hold a marker are reported. Each experience (job, turn, reasoning, look-up, seeing) waits in the pool as its owner's, each part saying where it came from. Taught english_01-39 after the sandbox is emptied | `results/` + transcript |
| [PATHS-01](PATHS-01/) | One writer per shared store, the ingress reached only through the learning authority, one Conversation class that can never be the substrate, and the authorities deciding what a write depends on | printed + `results/` |
| [PATHS-02](PATHS-02/) | Lyric (the coordinator and its Conversation) puts no claim into knowledge: it hands what it meets to memory's intake, memory splits it, the learning authority is the one door into the world; the Conversation names no learning; one conversation path. Read from the source with Python's parser, and one live telling | `results/` + `.md` |
| [SPLIT-01](SPLIT-01/) | Memory splits what Lyric meets by what it is about: sixteen cases, each with its destination frozen before the run (world, personal, work under the organization, the speaker's, nothing), through memory's real intake | `results/` + `.md` |
| [ORG-01](ORG-01/) | A person's Shared World Context is composed, not stored: World Knowledge, their Personal Context and their authorized organizations' Work Context. Work is the organization's (memories too); a coworker is answered from it and never from another's personal context; an outsider from neither; unlinking removes it from the person and the organization keeps it; an unverified work context is refused | `results/` + `.md` |
| [FIFTY-01](FIFTY-01/) | What Lyric overcomes for one person it does again at once, for them and for anyone: the first task of a shape that worked is the world's method with nothing of its person in it, the fix that overcame a failure is kept on it, and the next task (hers, or another person's) is given the fix before it acts; another person's task recalls nothing of hers | `results/` + `.md` |
| [TRUTH-01](TRUTH-01/) | The gate judges a claim by its evidence, not its teller: one witness a candidate used for everyone, two settle it, the same witness once, a revised word withdrawn, six sites not overturned by five people, one person overturned by two, a page or site counted once, one person's flood waits | `results/` + `.md` |
| [UNDERSTANDS-WORDNET-01](UNDERSTANDS-WORDNET-01/) | Whether the main model understands what WordNet taught it, graded with WordNet as the answer key only: taught facts asked new ways, facts inferred, unrelated pairs and made-up words (no false yes), each sense, parts, opposites and "What is X?", each question its own conversation, nothing looked up | `results/` |
| [UNDERSTANDS-PROSE-01](UNDERSTANDS-PROSE-01/) | Whether the main model reads prose as its sources write it and reasons over it: ten short texts (encyclopedia, science, webpage, code documentation, mathematics, premises, history, paper abstract, security log, news) told to a conversation that keeps them in working memory only, then asked what they say, what follows and what they deny; wrong answers counted apart | `results/` |
| [UNDERSTANDS-PROSE-02](UNDERSTANDS-PROSE-02/) | Whether the main model reads prose nobody fitted it to: UNDERSTANDS-PROSE-01's claim and harness on 50 texts taken as published (Wikipedia, GOV.UK, the Python documentation, arXiv, Loghub's logs, Wikinews, the US Constitution), drawn by a fixed seed, with 456 questions written before any was read; sized to about five points either way, each measure reported with its 95% interval | `results/` |
| [STRUCTURE-01](STRUCTURE-01/) | Whether the main model holds how the words of a sentence go together, learned from a treebank (UD English EWT's training part, each sentence kept as analysed, its standing a belief), and reads held-out sentences by it: classes, the word each depends on and as what, read from the store's own view; and the prose sentences' phrases | `results/` |
| [STRUCTURE-02](STRUCTURE-02/) | How many of the lessons' meaning roles fall on phrases of the structure learned from the treebank: each lesson sentence read strictly as taught, each slot of its frame tested on the structure read (its words one phrase; attached to what the meaning ties it to). The ceiling a phrase layer gives the reader | `results/` |
| [PROPBANK-01](PROPBANK-01/) | Whether every role PropBank gives the English Web Treebank (its annotations, with UD's words) is said in Lyric's meaning language: each argument a fact in a link kind it has, a rule its words settle, or nothing; the rest a named gap or listed; and whether WordNet names each happening | `results/` |
| [ROLES-01](ROLES-01/) | Whether argument-structure constructions learned over phrases (PropBank's roles on the treebank's training part, in the meaning language) say each held-out argument's part, over UD's structure and over Lyric's own, against the path alone | `results/` |
| [ROLES-02](ROLES-02/) | Whether the view learned from PropBank finds a happening's held-out arguments end to end (candidates up the structure, those heading none learned as such) and says each, over UD's structure and over Lyric's own | `results/` |
| [COMPOSE-01](COMPOSE-01/) | Whether what a sentence means is composed from its structure, learned from the lessons with PropBank's arguments behind them: the lessons held out ten ways, and the prose of UNDERSTANDS-PROSE-01 composed | `results/` |
| [SELF-TEACH-01](SELF-TEACH-01/) | Whether the structure reader teaches itself from raw text: Wikipedia sentences it read, kept where its two ways of reading agree, learned from beside the treebank, measured on EWT dev and PUD against the reader without them; and how right the readings it agrees on are | `results/` |
| [GROUPS-01](GROUPS-01/) | Whether words grouped by the company they keep, counted from raw text (WikiText-103, the exchange algorithm, no model), help the structure reader: learned from EWT train with each word's groups beside it, measured on EWT dev and PUD, rare words apart | `results/` |
| [STRUCTURE-03](STRUCTURE-03/) | Whether more hand-analysed English raises the structure reader: EWT alone, with Atis and ESL Spoken, with GUM, with every treebank the teaching pass takes, and with the counted word groups too, on EWT dev, PUD and GUM's held-out test | `results/` |
| [QUESTION-FORMS-03](QUESTION-FORMS-03/) | Questions about kinds, parts, members, materials and opposites, and "Is it true that ...?", taught (english_40) on a copy of main: its own sentences and never-taught questions with WordNet's words read as written, and no earlier lesson sentence lost | `results/` |
| [SENSES-01](SENSES-01/) | Whether a bound on the sense combinations of each grouping of the words (the N supposing least, then met most often) lets every sentence finish reading and leaves the listener's choice as it was: every lesson sentence and every prose sentence and question read with no bound and with each N, the readings handed to the listener, its choice and the seconds compared | `results/` (superseded by PACKED-01: the bound is gone) |
| [PACKED-01](PACKED-01/) | Whether the reader keeping each word's senses together, with the listener choosing over the structure, hands the listener exactly the readings the reader building every reading did, chooses as it chose, and finishes where it does not: every lesson and every prose sentence and question, both ways in one load, readings, choices, lessons read as taught and seconds compared | `results/` |
| [PMB-01](PMB-01/) | Whether what a sentence means is composed over its structure, each word's standing and each near pair's facts learned from sentences aligned word by word to their meanings: the Parallel Meaning Bank's dev split composed, strict and senses aside, learned from the lessons, then its gold training sentences, then its silver ones; the prose of UNDERSTANDS-PROSE-01 composed | `results/` |
| [GRAMMAR-01](GRAMMAR-01/) | Whether what a sentence means is read by English's grammar (each word's category and meaning, combined by general rules; what words hold learned from sentences taught with their meanings) better than the composer composes it: the Parallel Meaning Bank's dev split read as PMB-01 measures it, how many read whole, why each miss was missed, and each link decided by the word's own uses, by its kind, or by the grammar's rule with how often the meaning holds it; the prose of UNDERSTANDS-PROSE-01 read | `results/` |
| [WORD-FORMS-01](WORD-FORMS-01/) | The plural of every counted noun sense taught (`WordNetExamplesSource`, its nouns): each held for its sense, Lyric's own singular agreeing with WordNet's on 99% (the bar for `singularise` to stop asking WordNet), plurals never taught read through a shape, plural questions read as written | `results/` |
| [SPLITS-01](SPLITS-01/) | Whether the reader asking the chart where the words split between a form's slots (never making a covering with a slot nothing stands in), keeping each run of words by a number, making each construction's key once and the grammar making only the combinations its chart keeps, reads every sentence exactly as before: a looked-up page's paragraphs, every prose sentence and question and every lesson read both ways in one load, every utterance and reading compared whole, lessons also read strictly, seconds each way | `results/` |
| [READ-LEARN-01](READ-LEARN-01/) | Whether Lyric's English gets better by reading: the grammar as memory builds it scored on the Parallel Meaning Bank's dev split, then reading the PMB's silver text alone (2,000, 5,000, 10,000 sentences), each sentence's use of its words counted as much as the reading was sure, and scored again after each stretch; new words known counted | `results/` (FAIL: words learned, the dev split read no better) |

## Other folders

- `results/` — the KITE-17 ablation. `kite17_ablation.json` is the valid run.
  `kite17_ablation_INVALID_run1.json` is invalid because of a configuration isolation failure; its
  `.md` says why.
- `baselines/` — `pre_kite.json`, what the substrate held before KITE-17 was taught; and
  `kite_taught.json`, the rules that teaching produced.
- `cleanup/` — the rule-identity cleanup of 2026-08-19 and the script that quarantined a rule artefact.

**Still writing fixed filenames** (each run replaces the last): `kite_ablation.py`, `kite_teach.py`,
`substrate_baseline.py`, `verify_wiring.py`, the EDU manifests, and the `systems/` manifests.
