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
| [TASK-GATE-01](TASK-GATE-01/) | A route the constitution replanned is withdrawn, and the task boundary refuses nothing else | `results/` + `.md` |
| [TASK-GATE-02](TASK-GATE-02/) | Whether the task gate asks INTENT if the pursuit a task serves is still live, and refuses nothing whose pursuit is live | `results/` + `.md` |
| [PURSUIT-01](PURSUIT-01/) | Whether every piece of work carries the intent it serves, and its pursuit ends with what ended it — the constitution's verdict, never `abandoned` | `results/` + `.md` |
| [DOMAIN-DISCOVERY-01](DOMAIN-DISCOVERY-01/) | Whether the substrate DECIDES which domains exist, or only files whatever string a caller passed | `results/` + `.md` |

## Identity, users and concurrency

| Experiment | What it tests | Saved runs |
|---|---|---|
| [ACTOR-IDENTITY-01](ACTOR-IDENTITY-01/) | What a person teaches is scoped to their verified identity, not the session | printed only |
| [FRONTDOOR-IDENTITY-01](FRONTDOOR-IDENTITY-01/) | The front door binds the verified identity to the conversation | printed only |
| [SELF-PARTITION-01](SELF-PARTITION-01/) | One shared mind plus separate per-user context, with promotion when users corroborate | printed only |
| [TASK-RESULT-01](TASK-RESULT-01/) | Fetching a job's result, visible only to the person who asked | printed only |
| [PER-USER-CONCURRENCY-01](PER-USER-CONCURRENCY-01/) | Several tasks per user, shared fairly under a global cap | printed only |
| [TOOLS-EXTERNAL-01](TOOLS-EXTERNAL-01/) | No tool is hardcoded to the substrate: chaos tools archived, security tools read the logs they are told to (an outside log database, or the substrate's own when named), file tools take their folder, AgentSO tools guarded | `results/` |
| [AGENTS-01](AGENTS-01/) | The substrate deploys agents of itself through its coordinator: findings returned, only granted tools used, refused past the allowance, collected without waiting, failures honest | `results/` |
| [OUTSIDE-DB-01](OUTSIDE-DB-01/) | The database tools (`postgres_query`, `mysql_query`) work on an outside database they are given and refuse the substrate's own server; the 13 that ran on its own database are archived | `results/` |
| [TASKS-AT-ONCE-01](TASKS-AT-ONCE-01/) | Sixty tasks at once inside the queue authority's one budget, three per person at most; work past that waits and is done | `results/` |
| [WORK-TALK-01](WORK-TALK-01/) | The conversation knows the substrate's own work: what it is doing, whether it finished, stop it (waiting or running), told once what it found | `results/` |
| [MESSAGE-01](MESSAGE-01/) | The substrate speaks first: unasked, at a set moment, once, to every front end of that person; held for the next turn when none listens; still owed after a restart | `results/` |
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
| [PLANNING-01](PLANNING-01/) | One planning authority, and every planning path verified honest — proved plans grounded, unreachable goals yield no plan, template plans declare where their numbers came from | `results/` |
| [REPLAN-02](REPLAN-02/) | Knocked off course by a world its learned rule no longer fits, the substrate refutes the rule, replans from where the file really is, and still gets it there | `results/` + `.md` (JSON only before 2026-09-26) |
| [REPLAN-03](REPLAN-03/) | Its own operator, learned by practice in a directory it was given, pursued while the world changes under it: replans when something else moves the file, does not claim a goal the world refused | `results/` |

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
| [PERCEIVE-EVAL](systems/PERCEIVE-EVAL/) | Perceive and name, measured | naming recall 1.0, abstention 100%, 0 hallucinations (2026-09-17) |
| [HEAR-01](HEAR-01/) | Hearing on sight's own path: real recordings heard, believed, remembered, named by induction; known sounds; a clip seen and heard | pass, 42/42 (2026-09-28) |
| [RECALL-01](RECALL-01/) | Remembering is rebuilding: a hearing kept as a trace (no recording) and a seeing as a gist, rebuilt from memory and perceived as the same | pass, 11/11 (2026-09-28) |
| [SPEECH-01](SPEECH-01/) | Spoken words and voices taught by hearing an example, each lesson the same hearing memory as any other; heard in running speech through `hear()` as the words said, in whose voice; firm readings right | pass, 30/30 (2026-09-28) |
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
| [SYSTEM-LEARNING-01](SYSTEM-LEARNING-01/) | One learning door; demonstrations become a rule; strategy outcomes, predictions and retry waits are real learning | `results/` + `.md` |
| [SYSTEM-BELIEFS-01](SYSTEM-BELIEFS-01/) | Beliefs move with evidence and must be grounded; known unknowns survive restart and resolve only when learned | `results/` + `.md` |
| [SYSTEM-MEMORY-01](SYSTEM-MEMORY-01/) | Stored, found, superseded, forgotten on request, never merged; a user's memory is theirs by meaning, wording and tag | `results/` + `.md` |
| [SYSTEM-DOMAIN-01](SYSTEM-DOMAIN-01/) | A domain exists once, competence moves progress, a gap is detected | `results/` + `.md` |
| [SYSTEM-SEMANTICS-01](SYSTEM-SEMANTICS-01/) | The one write door: admitted once, refused when unrepresentable, conditionals held | `results/` + `.md` |
| [SYSTEM-INTENT-01](SYSTEM-INTENT-01/) | A pursuit formed once per key, refreshed, reconciled, forgotten | `results/` + `.md` |
| [SYSTEM-PERCEPTION-01](SYSTEM-PERCEPTION-01/) | Sensing, and sight end to end on a real photograph | `results/` + `.md` |
| [SYSTEM-SELF-01](SYSTEM-SELF-01/) | Appraisal, the arbiter and motivation, each one authority | `results/` + `.md` |
| [SYSTEM-HEALTH-01](SYSTEM-HEALTH-01/) | One health and one recovery authority; an unknown component refused; recovery waits learned | `results/` + `.md` |
| [SYSTEM-EXECUTION-01](SYSTEM-EXECUTION-01/) | Rules, bindings and tools: judged, then done; the unknown refused | `results/` + `.md` |
| [SYSTEM-CONVERSATION-01](SYSTEM-CONVERSATION-01/) | What a speaker tells is theirs: held in their context, answered back to them only, remembered as theirs | `results/` + `.md` |
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
| [SEPARATION-01](SEPARATION-01/) | Staging serves release 1 of the model taught in the sandbox, and keeps runtime, the model and each person's context apart: the lesson is in the release; a person's facts and memories are in user context; the substrate's own new memory waits in the learning store and is never read back; no search, answer or research for one owner reaches another's; the release, development and the main line are unchanged | `results/` + transcript |
| [RELEASE-01](RELEASE-01/) | The release lifecycle on the sandbox line: cut (read-only, checksummed, with the code it was cut with), staged before promoted, tampering and other code refused, production serving with nothing refused and its own learning refused, the release unchanged by serving, production's memory and recalls taken into development and carried by release 2, rollback | `results/` + transcript |
| [CANARY-01](CANARY-01/) | What a person gives the substrate through its real doors (a telling, a question answered by reasoning, a word looked up, a job run to its end, an image carrying a QR code) stays in their context: markers planted in them are found in no memory row of anyone else's, the substrate's own note is its own, and tables with no owner column that hold a marker are reported. Each experience (job, turn, reasoning, look-up, seeing) waits in the pool as its owner's, each part saying where it came from | `results/` + transcript |

## Other folders

- `results/` — the KITE-17 ablation. `kite17_ablation.json` is the valid run.
  `kite17_ablation_INVALID_run1.json` is invalid because of a configuration isolation failure; its
  `.md` says why.
- `baselines/` — `pre_kite.json`, what the substrate held before KITE-17 was taught; and
  `kite_taught.json`, the rules that teaching produced.
- `cleanup/` — the rule-identity cleanup of 2026-08-19 and the script that quarantined a rule artefact.

**Still writing fixed filenames** (each run replaces the last): `kite_ablation.py`, `kite_teach.py`,
`substrate_baseline.py`, `verify_wiring.py`, the EDU manifests, and the `systems/` manifests.
