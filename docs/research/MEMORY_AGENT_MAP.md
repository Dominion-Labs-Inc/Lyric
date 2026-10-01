# The memory agent, the one writer of memory: the change map

Requirements, 2026-09-27, in order:
1. Everything goes to memory. So the memory agent is made substantially more intelligent, and a pool is added that
   the memory agent pulls from and filters, to meet the standards it holds, plus this logic. The logic is
   `SEPARATION_MAP.md` §10: what production learns and what stays a person's. The design is §10.6.
2. The design is accepted.
3. The six writers found go against the authority systems. The memory agent is the only one that writes memories.

The rule for a change this size applies: map everything that has to change before building, and leave nothing half
done. Nothing in this map is built.

## 1. What memory is

Memory is everything the substrate holds: the entire substrate's memory. There is no knowledge
graph beside it.

| Kind | Tables |
|---|---|
| Memories | `memory_hot`, `memory_cold`, `archive_log`, `memory_media` |
| Concepts and links | `concepts`, `concept_relations`, `concept_evidence`, `concept_aliases`, `evidence_envelopes`, `concept_domains`, `concept_identity_relations`, `sense_taxonomy` |
| Beliefs | `beliefs`, `calibration_data`, `domain_volatility`, `known_unknowns` |
| Rules and demonstrations | `learned_rules`, `learned_rule_evidence`, `rule_projections`, `rule_supersessions`, `rule_authority_events`, `held_conditionals`, `operator_demonstrations`, `operator_induction_pending` |
| Domains | `domains`, `domain_mappings`, `knowledge_transfers`, `mapping_usage_events`, `domain_controllability` |
| What reasoning produced | `reasoning_arguments`, `reasoning_arg_claims`, `reasoning_arg_fallacies`, `reasoning_temporal_propositions`, `reasoning_temporal_causal_links`, `hypotheses`, `experiments`, `evidence`, `schemas`, `analogies`, `concept_mappings` |
| Perception | `vision_instances`, `perceptions` |
| A person's context | `scoped_concept_relations`, `scoped_beliefs`, `user_beliefs`, and a person's rows of the memory tables and `known_unknowns` |
| The record of learning | `knowledge_updates`, `knowledge_consumption` |
| Trained recognisers, training examples | `clause_classifiers`, `security_training_examples` |

These are not memory: runtime's operational records (tasks, the queue, telemetry, health), and the tools' tables.

Two runtime tables hold something learned. They are classified in M2:
- `meta_learning_strategies`: which strategy works for which kind of task;
- `failed_task_fingerprints`: tasks that failed before, holding the person's request text.

## 2. Who writes it today (measured 2026-09-27)

Every statement in `core/` was read, the way `scripts/separation_map.py` reads them, with no database touched.
- **87 statements write memory tables.**
  - 10 are the memory agent's own storage (`postgres_storage.py`, `media_store.py`).
  - **77, in 23 components, bypass it.** The first count, 73 in 22, read only the database manager's calls. It
    missed four statements:
    - `releases.take` writes on its own connections: it marks taken memories, adds production's questions to
      development's, and adds recorded use to access counts;
    - `rule_store.forget` names each referencing table at run time.
- **23 places hand content to the memory agent.**
  - 6 decide whose it is themselves.
  - 17 say nothing, so it becomes the substrate's own, even when it came from a person.
- **One script writes memory directly:** `scripts/fetch_sense_taxonomy.py`, through `sense_taxonomy.load_edges`.
- **Found with no caller:** `security_training_pipeline.train_security_model`, and its two hand-offs to the memory
  agent.
- Raw connections (`get_connection`) outside the database layer touch only runtime (directives, intents).

## 3. The target

1. **One writer: the memory agent's own.** Nothing new is built beside it: the memory agent already has a
   writer, and it already has a ledger.
   - The memory agent already writes memories through `store_memory` and its write queue, backed by its storage
     (`PostgresStorage`, `MediaStore`). That writer is extended to the other kinds: each statement that writes a
     memory table becomes one of the memory agent's own write methods, grouped by kind.
   - Its write methods need only the database, so a component can hand something to the memory agent without
     starting its recall, its loops or its embedding model. `memory_agent()` returns the process's memory agent
     without starting it; `get_memory_agent()` starts it, as before.
   - The knowledge ledger moves under the memory agent (`core/memory/knowledge_ledger.py`). It is not copied.
   - Nothing else writes memory.
2. **Others compute, and the memory agent writes.** Each component keeps its work:
   - the learning authority decides what is learned;
   - the belief system computes posteriors;
   - induction finds rules;
   - the domain master files concepts;
   - the reasoning engines reason;
   - perception sees.

   Each hands its result to the memory agent, through one write per kind of memory. What a component holds in its
   own process (the belief system's beliefs, a rule cache) stays with it.
3. **Experiences enter the pool** (`SEPARATION_MAP.md` §10.6). The memory agent decides whose each part is, from
   where it came from. No caller names an owner.
4. **Every write carries its reason and evidence.** The memory agent keeps the record of it, which is the ledger's
   job folded in.
5. **Instance safety moves with the statements.** The versioned belief writes, the atomic counters and the leases
   (INSTANCES-01) move unchanged.
6. **A check enforces it.** A scanner, like `scripts/separation_map.py`, fails when any statement outside the memory
   agent writes a memory table, or any caller names an owner.

## 4. Each writer, and what it becomes

**Direct writers (73 statements).**

| Component | Writes today | Keeps | Hands the memory agent |
|---|---|---|---|
| Concept ingestion (`domain/concept_ingestion.py`, 7) | concepts, links, their evidence, aliases, evidence envelopes | reading a proposition into canonical concepts | concepts and links, with their evidence |
| Cognitive ingress (`semantics/cognitive_ingress.py`, 2) | aliases; a taught conditional as a held rule | the door's tests | the alias; the held rule |
| Concept identity (`domain/concept_identity.py`, 3) | domain memberships, identity relations | identity resolution | memberships and identity links |
| Domain master (`integration/universal_domain_master.py`, 7, plus 1 in a retired function) | concept vectors, filing concepts into subjects, what the substrate's actions move, correspondences between domains | encoding, filing, operability | vectors, filings, controllability evidence, correspondences |
| Domain registry (`domain/domain_registry.py`, 5) | domains, mappings, transfers and whether they helped, mapping use | the domains' structure | the same |
| Belief system (`reasoning/bayesian_uncertainty.py`, 6) | beliefs (versioned), their deletion, calibration, volatility, unanswered questions | posteriors, decay, calibration | belief rows, with the version they replace; calibration; volatility; questions with their owner |
| Rule store and rule authority (`learning/rule_store.py`, 10; `learning/rule_authority.py`, 2) | rules, their evidence, projections, supersessions, status, forgetting, authority changes | induction, validation, authority | rules with their evidence, and every change of status |
| Demonstration store (`learning/demonstration_store.py`, 3) | each action's before, action and after, and what waits for induction | nothing | the pool: an action is an experience. Its ground record follows its owner; induction reads it lifted |
| Scoped context store (`learning/scoped_context_store.py`, 3) | a person's told facts and their beliefs, and the promotion flag | nothing | the person's context, placed by the memory agent. Promotion because another person agrees goes (decided 09-26) |
| Coordinator (`_learn_about_user`, 1) | beliefs about the speaker | nothing | the same, as the person's context |
| Knowledge ledger (`learning/knowledge_ledger.py`, 4) | what was learned, what used it, whether behaviour changed | nothing | folded into the memory agent's record of every write |
| Reasoning (argumentation 3, temporal 2, hypotheses 3, abstraction 2, analogy 2) | arguments, temporal propositions and causal links, hypotheses and experiments, schemas, analogies | the reasoning | what it produced. What was produced for a person goes through the pool. Abstraction clusters episodes, so it reads only what the split has made the substrate's |
| Perception (`perception/perception_faculty.py`, 2) | known image instances | seeing | the pool: a percept is an experience. A learned instance is written only once it passes |
| Clause classifiers (`learning/unified_learning_system.py` `save_classifiers`, 1) | trained recognisers | training | the trained recogniser |
| Sense taxonomy (`reasoning/sense_taxonomy.py`, 2, run by a script) | the taxonomy | nothing | through the memory agent, as teaching |
| Security training (`security/security_training_pipeline.py`, 1) | training examples | nothing | no caller found; still to be decided |

**Hand-offs to the memory agent (23).** They go through the pool, naming no owner.

| Where | Sites | Names an owner today |
|---|---|---|
| Task execution (coordinator): the outcome record, a failed task's account, what a task found and the tools it used (`capture_task_outcome`, the leak of §10.1), predictions, goals, images, answers from what is held, constitutional checks | 10, plus `capture_task_outcome` | 3 |
| Conversation (`cognitive_ingress._remember`) | 1 | 1 |
| Teaching (`learn_from_example`, `learn_word_classes`, `_store_language_item`) | 3 | 1 |
| Reasoning (abstract reasoning, the neural bridge, hypotheses, cross-domain) | 4 | 1 |
| Perception (`evidence_producers._remember_percept`), domains (`_remember_domain`) | 2 | 0 |
| Security training, with no caller | 2 | 0 |
| Releases (`take`: development taking production's memories) | 1 | 0 |

The release tool's copying of whole databases (`releases.cut`, `prepare_environment`) and the reset script's
emptying of the sandbox do not write memories. `releases.take` does, and is among the 77.

## 5. Build order

Nothing is switched halfway. Each step ends with every caller it touches switched and verified.

| Step | Built | Verified by |
|---|---|---|
| **M1. One writer** (**done 2026-09-27**, §7) | Every memory-table statement becomes one of the memory agent's write methods, and each component calls the memory agent. The ledger moves under it. Behaviour is unchanged: callers still name owners until M2 | The new scanner: no writer outside the memory agent. SHAPES-LEARN-01 and 02, SEPARATION-01, RELEASE-01, INSTANCES-01, and the test suites touching the moved code, pass as before |
| **M2. The pool** | Producers hand experiences over as structure, with each part's origin. The memory agent decides whose, and callers stop naming owners. `capture_task_outcome` goes through the split, which closes the leak. The two learned runtime tables are classified. Every write records its reason and evidence in the ledger, and intrinsic motivation reads what was learned from there, instead of only a learning-progress rate that resets at every restart | The canary test. SEPARATION-01 extended |
| **M3. The lift, the residue test, the gate** | The lift and the residue test in the memory agent. Candidates go to the learning authority. The belief system admits them by kind of evidence, with the decisions of `SEPARATION_MAP.md` §10.5. The belief check (`SEPARATION_MAP.md` §6) lands here | LEARNED-WORK-01 shows learning from work. The transfer test |
| **M4. Production learning** | A working copy of the release that production learns into (`SEPARATION_MAP.md` §10) | RELEASE-01 and SEPARATION-01: production learns from its experience, and the release stays byte-for-byte what was cut |

## 6. Open

- Decisions 1 to 8, in `SEPARATION_MAP.md` §10.5 and §10.6.
- **9. Reading memory.** May components keep reading memory tables directly? Proposed: yes for now. The rule is
  about writing, and the owner rule already governs every read of a person's rows.
- **10. The taxonomy script** goes through the memory agent, like teaching. Proposed: yes.
- **11. Security training** has no caller: keep it and route it, or retire it? Still to be decided.

## 7. As built: M1, one writer (2026-09-27)

**The memory agent writes all of memory.**
- `MemoryAgent` gained its write methods, one per statement, in one section (THE REST OF MEMORY) beside the writer it
  already had. They cover concepts and links, beliefs, rules and demonstrations, domains, what reasoning produced,
  perception, a person's context, the record of what was learned, trained recognisers, and what development takes
  from a serving environment.
- Each statement moved unchanged: the same SQL, parameters and options, on the same database manager.
- `memory_agent()` returns the process's memory agent without starting it. Writing needs only the database, so
  writing a belief does not load the embedding model or start the loops.
- The knowledge ledger moved to `core/memory/knowledge_ledger.py`. Its stamping, batches and reads are unchanged;
  its writes are the memory agent's.

**The 23 components** keep their work and call the memory agent. Where a function took a database only to write,
the parameter went:
- `rule_authority.mark_consumed`, with its two callers updated;
- `releases.take`'s own connection to development.

**The check.** `scripts/separation_map.py` finds every string in `core/` that writes a memory table, whatever runs
it, and exits 1 when one is outside the memory agent. Today it reports:
- memory written outside the memory agent: **0**;
- scripts that write memory directly: **5**, listed and not failed.

`tests/test_memory_writers.py` runs the check, and proves it finds a write run by a raw connection or with its
table named at run time. The frozen-refusal count moved from 66 to 65, because two identical statements are now one
method.

**Verified.**

| Run | Result |
|---|---|
| The 59 test files touching the changed code, sandbox | Before: 486 pass, 29 fail, 3 error. After: every test gives the same outcome. Two tests read a writer's source for its SQL, and now read it where it lives |
| The planning-engine tests, the chaos adapter tests, `test_memory_writers.py` | all pass |
| SHAPES-LEARN-01 | 35/35 (`20260927T222914Z`) |
| INSTANCES-01, now pinned to the sandbox | 11/11 (`20260927T223131Z`) |
| SHAPES-LEARN-02 | 32/32 (`20260927T223143Z`) |
| SEPARATION-01, staging | 33/33 (`20260927T223402Z`) |
| RELEASE-01 | 29/29 (`20260927T223525Z`). `take` moved a memory and its recall count, and a second `take` took nothing |
| Taking a serving environment's open question | Production kept none in RELEASE-01, so it was run directly on the sandbox: taken once, not again, held as the substrate's own, removed |

The main store held 207 rows before every run and after it.

**Found while moving, not fixed.** M1 changes no behaviour.
- **Five hand-run scripts write memory directly:** `reset_dev_store`, `repair_double_counted_beliefs`,
  `rebuild_isa_wordnet`, `purge_legacy_fixture_concepts` and `migrate_clean_data`. Whether they go through the
  memory agent is still to be decided.
- **`relink_dangling_edges` always reports 0 links attached.** It counts a result only when it is a number, and a
  write returns its status text.
- **Hypothesis evidence is written with `collected_at.isoformat()` into a timestamp column.** This is the defect its
  two neighbouring writes had fixed, so each such write most likely raises and is swallowed.
- **`crystallize_taxonomic_domains` moves concepts without marking them updated.** The declarative refile does mark
  them.
- **`core/memory/agent.py` is a one-line empty class,** `AsyncMemoryAgent: pass`.
- **Tables are still created by the components that read them.** M2 moves their definitions to the memory agent,
  when it adds the owner and origin of each part.


## 8. M2 mapped: whose work it is, and the pool (2026-09-27, before building)

### 8.1 What happens today (read in the code)

**"Whose work this is" already exists and is bound too narrowly.** `intent_authority` keeps it in a context
(`set_acting_actor`, from `task.actor`), and the tool registry reads it. It is bound only around one tool run
(`_run_tool`, `_act_on_grounded_operator`). Everything else a task does for a person runs outside it: its
validation, its outcome memories, a person's question and its answer, and reasoning done for them. The memory agent
never reads it; each caller names an owner or names none.

**The hand-offs, and whose they are today.**

| Hand-off | What it holds | Owner today |
|---|---|---|
| a task's outcome record (`_store_task_outcome_meta_memory`) | the request, the result, the method, the fix | the task's actor, whole |
| a failed task's account (`_execute_and_validate_task`) | the request, and why it failed | the task's actor |
| what a task found, and its tools (`memory_agent.capture_task_outcome`) | the request, summary, findings, file names, tools used | nobody. **Latent:** it reads `summary`, `key_findings` and `tool_results`, which no task result carries, so it stores nothing today |
| a reasoning answer (`neural_bridge._capture_reasoning_memory`, run on every standalone answer) | the question and the answer | the actor its caller put in the request (`task_metadata`), passed as `**owner`; the conversation passes it, so a person's question is theirs. Callers that put no actor in the request would file it as the substrate's (latent). Corrected 09-27: first reported as a leak |
| an image seen (`see` → `remember_image`) | what is in a picture, given by path | **nobody. `see` takes no identity, so a person's image is filed as the substrate's (live; CANARY-01)** |
| `reason_about`, `make_enhanced_prediction`, `perform_cross_domain_reasoning` | "I was asked: …" with the question | nobody. No caller in `core/` today, so the leak is latent |
| abstract reasoning (`_store_in_memory`), a told proposition (`_remember`), an exchange (`_answer_from_what_is_held`), a learning example (`learn_from_example`) | a person's words | their owner, named by the caller |
| curiosity goals, predictions about a domain, constitutional checks, domains, teaching, taken memories, hypotheses' experiments, cross-domain insight | the substrate's own work | the substrate |

**Measured by CANARY-01 before any change** (`20260927T230245Z`, 10/12):
- The only live leak in memory rows is the image `see` makes.
- A person's reasoned claim lands in `reasoning_arg_claims` and `reasoning_arguments`, which have no owner column
  (M2b).
- The task-end record wrote nothing.

**Writes through the memory agent's other methods that carry a person's material:**
- demonstrations, which keep the person's paths with no owner;
- told facts and beliefs about the speaker, which are the person's;
- open questions, which carry their owner since S3;
- concepts that research finds, which do not record whose question led to them.

### 8.2 The design, in three verified steps

**M2a. Every hand-off says where it came from; the memory agent decides whose it is.** This was first mapped as
binding "whose work this is" around a person's work, for the memory agent to read. Instead, each hand-off passes
its information to the memory agent, explicitly:
- **Every hand-off to the memory agent carries an `Origin`:** what it came through (the door or the work), and the
  person it came from, or none for the substrate's own. `person` has no default, so "none" is a decision.
- **The memory agent decides whose memory it is from the origin, and keeps the origin with it.** Callers stop naming
  owners.
- **A hand-off with no origin is refused.** Nothing falls back to the substrate's own, which is how a person's words
  used to land there.
- **The doors pass what they know:**
  - `see` takes the identity of whoever gave the image, as the front door does. It has no default, so a caller says
    whether the seeing is the substrate's own.
  - A reasoning request says whose reasoning it is, and the bridge keeps no reasoning memory without that.
  - The `store_memory` tool is run for whoever's task it is part of, and refuses outside one.
  - A learning example says whose experience it is.
- **Check: CANARY-01.** Markers go through the real doors (a telling, a question answered by reasoning, a job, an
  image). No memory row outside the person's context may hold one.

**M2b. The pool and the split.**
- **An experience is handed over as structure:** its parts, each with its origin (the person, the world, the
  substrate), and its evidence.
  - task execution: the request, steps, tool runs, errors, fixes, result and checks;
  - research: the question, the queries, the sources and what each said;
  - conversation: what was said and answered;
  - perception, and reasoning done for someone.
- **The person's parts are stored in their context at once.**
- **The substrate's parts become candidates in the pool.**
  - The pool is durable, per owner, and claimed with a lease across instances.
  - Its items are never recalled as knowledge until M3 decides them.
  - A person's item stays in their context store until it is lifted.
- **The memory agent pulls each item from the pool,** woken on arrival. It applies its standards (worth keeping,
  already held, new against memory) and records its decision on the item.
- **The memory tables' definitions move to the memory agent,** with the owner and origin columns they now need.
- **The two learned runtime tables are classified:**
  - strategy counts, which are learned knowledge;
  - failed-task records, which hold a person's request.
- **Check:** the canary test, run for each kind of experience: a coding task, a research question, a design, an
  experiment and a told fact.
  - Markers stay in the person's context, the pool's items for them included.
  - The substrate's candidates wait, and none is recalled as knowledge.

**M2c. Every write recorded; motivation reads it.**
- Every write through the memory agent records its reason and evidence in the ledger.
- Intrinsic motivation reads what was learned from the ledger, instead of only a learning-progress rate that resets
  at every restart.
- **Check:** every write in a run has its ledger row, and motivation's measure of learning survives a restart.

After M2: **M3** lifts the candidates, tests them for residue and gates them (decisions 1–8). The proof
that tasks, research, coding, design and experiments are separated by the logic of `SEPARATION_MAP.md` §10
is the experiment built there. It is written before M3 is built, so it is not shaped to what was built.

### 8.3 As built: M2a, every hand-off says where it came from (2026-09-27)

**Built.**
- **`Origin`** (`core/memory/utils/interfaces.py`, exported from `core.memory`) holds what a hand-off came through
  and the person it came from, or none for the substrate's own. `person` has no default.
- **The memory agent decides whose a memory is from the origin.**
  - `store_memory` and `enqueue_memory` require an origin and refuse anything else.
  - The owner is the origin's person.
  - The origin is kept with the memory.
  - A queued write takes the owner when it is handed over, not when it is written.
- **The storing pipeline is unchanged,** behind the door (`_store_memory`).
- **Every hand-off passes its origin:**
  - a task's outcome record and a failed task's account: `Origin.of(task.actor, "task")`;
  - the exchange and a told sentence that did not read: the conversation's speaker;
  - `see`: the identity it is given. It now takes `actor_identity`, with no default, as the front door does;
  - reasoning: the actor its request carries;
  - a learning example: its `actor`, now a required field of `LearningExample`;
  - `reason_about`, `make_enhanced_prediction` and `perform_cross_domain_reasoning`: the caller's origin, now
    required;
  - lessons, curiosity goals, predictions about the system, constitutional checks, domains, hypotheses,
    cross-domain insight, percepts, security training, and memories taken from a serving environment: the
    substrate's own.
- **The bridge keeps no reasoning memory when its request does not say whose reasoning it is.** The causal
  analyser and the capability benchmark say "the substrate's own". The reasoning tool passes the actor of the task
  its run is part of.
- **The `store_memory` tool** stores for whoever's task it is run in, and refuses outside one.
- **The memory agent is constructed in one place** (`memory_agent()`). SYSTEM-MEMORY-01 found the second
  construction site that M1 had added.

**The check.** `scripts/separation_map.py` fails any hand-off in `core/` that says no origin or names an owner:
0 today. `tests/test_memory_writers.py` covers the check, the refusal, and ownership following the origin (7
tests).

**Verified.**

| Run | Result |
|---|---|
| CANARY-01 before | 10/12 (`20260927T230245Z`): the image `see` made of a person's picture was the substrate's |
| CANARY-01 after | **12/12** (`20260927T234542Z`) |
| Test files touching the code, sandbox | every test the same as the baseline (29 fail and 3 error, as before); 52 added tests pass |
| SHAPES-LEARN-01 / 02 | 35/35 (`20260927T234629Z`), 32/32 (`20260927T234725Z`) |
| INSTANCES-01, SEPARATION-01, RELEASE-01 | 11/11 (`20260927T234713Z`), 33/33 (`20260927T234810Z`), 29/29 (`20260927T234934Z`) |
| SYSTEM-MEMORY-01 | 18/18 (`20260927T235317Z`) |

The main store held 207 rows before every run and after it.

**Tests and experiments changed, and why** (never changed to pass instead of the code). Every change
follows from an interface that now requires a caller to say where a memory or image came from.
- **37 files make one mechanical change** (script, in the notebook). A call of a changed door states where its
  content came from:
  - the harness's own material is the substrate's own, named after the experiment or test;
  - its images are seen as the substrate's own (`actor_identity=None`);
  - the four calls that named a person as owner now give that person as the origin: SEPARATION-01, RELEASE-01's
    `serve.py`, and SYSTEM-MEMORY-01 twice.
- **`test_domain_expansion_chain`:** its learning example says it is the substrate's.
- **`test_abstraction_connectivity` and `test_memory_worthiness_semantics`:** they read the storing pipeline's
  source for what it calls, so they now read it where it sits (`_store_memory`).

**Found.**
- **The reasoning bridge already filed a person's question as theirs.** It passed the request's actor as `**owner`,
  and the first scan missed that. The earlier report of a leak there was wrong.
- **The task-end record (`capture_task_outcome`) never fires.** It reads fields no task result carries, so the
  substrate keeps no record of what a task found or which tools worked. This belongs to learning from work (M3).
- **A person's reasoned claim lands in `reasoning_arg_claims` and `reasoning_arguments`,** which have no owner
  column (M2b).
- **The companion's `/img` sends a picture to the local chat model, not to `see`,** so a picture shared there never
  reaches the substrate.


## 9. M2b mapped: experiences, the pool and the split (2026-09-27, before building)

### 9.1 What an experience is, and where each kind forms today

| Kind | Where it forms | Its parts, by where each came from |
|---|---|---|
| a task (coding, a design and an experiment are tasks) | the end of `_execute_and_validate_task`. On success it calls `capture_task_outcome`, which reads fields no result carries and so keeps nothing; a failure keeps only its outcome record | **the person:** the request (`task.description`), and their files and data as the tools read them. **The substrate:** the steps (`tool_plan`), each tool run (`tools_run`), the errors (`failure_history`), the fix that worked (`retry_method_structured`). **The world:** the checks (`completion_evidence`, fresh re-observations), and tool outputs about things outside the person's material |
| research | `_research_phrase` | **the person:** the phrase they asked about. **The substrate:** the query. **The world:** each page and what it said, and the finding |
| conversation | the front door and `Conversation.understand` | **the person:** what they said. **The substrate:** the answer and how it was reached |
| perception | `see` | **the person:** the image, when they gave it. **The world:** what was perceived in it |
| reasoning for someone | the neural bridge | **the person:** the question and their premises. **The substrate:** the steps and the answer |

### 9.2 The design

- **`Experience`** (beside `Origin`) holds:
  - its kind;
  - its origin (whose work it was);
  - its parts, each with a role, its content, and where it came from (the person, the world or the substrate);
  - its evidence (the outcome and the checks).
- **`memory_agent.remember_experience(experience)`** is the hand-off. The person's episode is written as it is today,
  by the records the producers already make. The experience goes into the pool as a candidate, in its owner's store.
- **The pool is `unified.experience_pool`, a per-owner table** whose definition the memory agent holds. The
  substrate's rows live in the model, or the learning store when frozen; a person's live in their context. Each row
  holds:
  - its id and owner;
  - its kind and what it came through;
  - its parts and evidence;
  - its status (waiting, claimed, decided);
  - its lease (by whom, until when);
  - the decision, and its times.
- **Nothing recalls the pool.** Its items are candidates, not knowledge, and no reader of memory reads it.
- **The memory agent's pool worker** is woken on arrival and claims waiting items with a lease, as the task queue
  does. It applies its standards and records its decision on the item:
  - *nothing to learn:* no part from the substrate or the world, or no outcome;
  - *already held:* the same experience, fingerprinted by its parts, is already a candidate; it is merged and its
    evidence counted;
  - *candidate:* it waits for M3's lift, residue test and gate.
- **Task experiences come first.** `capture_task_outcome` is the memory agent's existing intake for a finished task.
  It becomes the task experience's intake, reading the real parts on success and on failure; a failure's errors are
  experience. The semantic and procedural memories it was written to make, and never made, are superseded by the
  candidate.

### 9.3 Build order within M2b

| Step | Built | Verified by |
|---|---|---|
| **M2b-1** | `Experience`, the pool and its worker; task experiences on success and on failure | CANARY-01 extended. A person's task with an error and a fix: the pool item is theirs and holds their markers, the substrate's own task's item is its own, nothing in the pool is recalled as knowledge, and the worker's decisions are recorded |
| **M2b-2** | research, conversation, perception and reasoning experiences | CANARY-01, one check per kind |
| **M2b-3** | the other kinds of memory by owner: arguments, temporal knowledge, hypotheses, perceptions, demonstrations. Every write carries its origin, and a person's goes to their context. The two learned runtime tables are classified | CANARY-01: no owner-less table holds a person's marker |

Then M2c (every write in the ledger; motivation reads it), M3 (the lift, the residue test and the gate, with
decisions 1–8) and M4 (production learning).

### 9.4 As built: M2b-1, task experiences into the pool (2026-09-28)

**Built.**
- **`Experience` and `Part`** (`core/memory/utils/interfaces.py`, exported from `core.memory`).
  - Each part has a role, its content, and where it came from: the person, the world or the substrate.
  - An experience has its kind, its origin, its parts and its evidence, and refuses to be made without an origin.
  - Its fingerprint is its kind and what the substrate and the world contributed, not whose it was.
- **The pool, `unified.experience_pool`,** is a per-owner table whose definition the memory agent holds.
  - `remember_experience` files an experience in its owner's store: a person's in their context, the substrate's
    own in the model (the learning store when frozen). It then wakes the worker.
  - The worker starts and stops with the memory agent's loops. It claims waiting items with a lease (`FOR UPDATE
    SKIP LOCKED`, 120 s), in the stores it may change.
  - It decides each item and records why: *nothing to learn*, *already held* (counted on the held one), or
    *candidate* (waits for the lift, the residue test and the gate).
- **`capture_task_outcome` is the task experience's intake.** The task loop hands every finished task over, on
  success and now also on failure. Its parts:

  | Part | From |
  |---|---|
  | the request, the result, and what the tools returned from a person's material | the person |
  | the steps and the tool runs, and the fix that worked | the substrate |
  | the errors and the checks that confirmed the outcome; tool output on the substrate's own work | the world |

  It used to read fields no task result carries, and kept nothing.

**Verified.**

| Run | Result |
|---|---|
| `tests/test_experience_pool.py` (new, sandbox) | 4/4: an experience says whose it was; one fingerprint whoever it was for; a task's parts and where each came from; the worker's three decisions, and a person's item under them |
| Test files touching the code | every test the same as the baseline, and 56 added pass |
| CANARY-01 | **18/18** (`20260928T001000Z`). The person's job is in the pool as theirs, holding their marker: 3 parts theirs, 2 the substrate's, 2 the world's (the checks), decided a candidate. A job of the substrate's own is its own (4 of its parts, 3 of the world's, none of anyone's). The substrate's recall finds nothing of the person's job |
| SHAPES-LEARN-01 / 02 | 35/35 (`20260928T001051Z`), 32/32 (`20260928T001147Z`) |
| INSTANCES-01, SEPARATION-01, RELEASE-01 | 11/11 (`20260928T001135Z`), 33/33 (`20260928T001231Z`), 29/29 (`20260928T001355Z`) |
| SYSTEM-MEMORY-01 | 18/18 (`20260928T001738Z`) |

**Tests changed.** `test_release_environments` pins the tables the learning store holds; the pool is added, because
the substrate's own candidates wait there when frozen.

### 9.5 As built: M2b-2, research, conversation, perception and reasoning experiences (2026-09-28)

**One rule for whose each part is.** It is stated once, at `PART_SOURCES`, and applied through `Origin.theirs` and
`Origin.material`. The task intake uses it too, with the same labels as M2b-1.

| Part | From |
|---|---|
| what the person gave (their words, request, files, image), what came back from their material, and what they were given back (a result, a reply, an answer) | the person |
| what the world answered by itself (a page read, a finding, an error met, a check), and what came back from the substrate's own material | the world |
| what the substrate did (its steps, the query it sent, the pages it chose to read, its derivations, how it placed and answered what it was given), and on its own work, what it asked and answered | the substrate |

**Built.**

| Kind | Handed over by | Its parts | Its outcome |
|---|---|---|---|
| conversation | `Conversation.understand`, at every exit, and a verdict turn (`_take_feedback`) | what was said, what the speaker told, the answers and the reply (theirs); the route: what it placed and how, what it could not place, what it looked up, how it answered (its own) | answered or not; held or not; confirmed or corrected |
| research | `_research_phrase`, at every exit | the word asked about (theirs); the query and each page it chose to read (its own); each page and what it said, the finding, an error (the world's) | found, nothing found, failed, declined; with the number of pages, and whether the finding was admitted |
| perception | `see`, at both exits | the image, what was seen in it and what it recognised (theirs when they gave it, the world's when it looked for itself); how it saw (its own) | the percept's standing (ACT, VERIFY, ABSTAIN), or nothing sensed |
| reasoning | the neural bridge's capture | the question, an image given, and the answer (theirs); each premise by where it came from; the steps (its own) | the bridge's reason code, or verified / unverified |

- **Premises.**
  - A premise the substrate holds (a concept, a rule, a belief) is its own.
  - A premise the speaker told (`context`) is theirs, and so is a caller's own sentence.
  - A recalled memory is counted as the asker's, because the premise does not say whose the memory is.
- **A refusal is an experience.** The bridge now hands over a reasoning that found no answer, as a failed task is
  handed over. It is still never a memory.
- **A hand-over whose store fails is reported.** It does not cost the person their reply or fail the seeing. A
  fault in the code is raised, as everywhere.
- **The look-up of a finding is unchanged.** It is still admitted at once under the substrate's account (one page,
  one sentence) and also waits in the pool. M3's gate for world facts replaces the first.

**Changed from the map (§9.1), and why.**
- §9.1 gave the answer to a person's question as the substrate's. As built, what a person is given back (a reply, an
  answer, a result) is theirs, as a task's result already was in M2b-1. It is about them, and the hard filter keeps
  it with them. How the answer was reached is the substrate's.
- §9.1 gave what was perceived in a person's image as the world's. As built it is theirs: what came back from their
  material is theirs, as a tool's output from their file is.

**Found while building, not changed here.** CANARY-01's image now carries a marker in a QR code, which the vision
faculty reads into what it saw. The marker reached the substrate's own memory and knowledge by two routes, neither
touched by this step. Before this, nothing from an image could be traced.
- **The memory agent stamps recent perceptions on every memory it writes, whoever's the memory is**
  (`_store_memory`, "CONTEMPORANEOUS PERCEPTION"). Each perception from the last 120 seconds is attached whole
  (for an image, what was seen in it; for a document, its text) to `thinking_state.perceptual_state`. In the run,
  the person's image was stamped on 131 of the substrate's own memories. By the same code, one person's perception
  would be stamped on another person's memories formed within the window.
- **`see` admits a person's image as the substrate's own knowledge.** `process_input` → `submit_image` has no owner:
  the image's structure, and the QR text as a detection, went into `unified.concepts`, `concept_relations`,
  `concept_aliases`, `concept_domains`, `concept_evidence`, `evidence_envelopes`, `beliefs` and `perceptions`.

Both are perceptions by owner, which is M2b-3. The fix proposed:
- a perception carries its origin;
- the memory agent stamps a memory only with perceptions of the same owner;
- what a person's image shows goes to their context, as what they tell does.

Also found:
- `submit_research_result` (`core/domain/evidence_producers.py`) has no caller.
- The look-up sends the person's word out (`what is <word>`). That is decision 7 in `SEPARATION_MAP.md` §10.5.
- A part is kept whole, so a document seen for a person is kept whole in their pool item. This is the material the
  residue test will check a lesson against.
- A recalled memory's owner is not carried on its premise. In the run, the substrate's own lesson "bird isa animal"
  reached the reasoning as a recalled memory and was counted as the person's. That errs toward the person, but it is
  inexact. Carrying the memory's owner onto the premise would make it exact.
- A reply to an unplaced word says "I'll run a more targeted search". Whether a search follows for a word no
  domain holds is not checked yet.

**Verified.**

| Run | Result |
|---|---|
| `tests/test_experience_pool.py` | 8/8. The 4 added cover the rule for whose each part is, a turn, a look-up (found, and failed), and a reasoning (proved, refused, and the substrate's own) |
| Test files touching the code, plus the conversation, reasoning and vision tests | every test the same as before the change (31 fail and 3 error, all failing before it too), and the 4 added pass |
| CANARY-01 | **31/32**, twice (`20260928T005213Z`, `20260928T010444Z`). Every pool check passes: the person's telling, question, reasoning, look-up and seeing are theirs, each part where it came from; the substrate's own question is its own; recall finds nothing of theirs. The one failure is the image leak above |
| SHAPES-LEARN-01 / 02 | 35/35 (`20260928T005500Z`), 32/32 (`20260928T005556Z`) |
| INSTANCES-01, SEPARATION-01, RELEASE-01 | 11/11 (`20260928T005544Z`), 33/33 (`20260928T005641Z`), 29/29 (`20260928T005806Z`) |
| SYSTEM-MEMORY-01 | 18/18 (`20260928T010150Z`) |
| SYSTEM-CONVERSATION-01 | 35/37 in the sandbox as it was (`20260928T010225Z`): "is a vex… an animal" needs "a mammal is an animal", which neither the sandbox nor the main store holds. With that one lesson taught into the sandbox, 37/37 (`20260928T010624Z`). Its 18 turns and reasonings were each in the pool under the speaker they came from |
| SEE-LOOP-01, SYSTEM-PERCEPTION-01, SYSTEM-REASONING-01 | 23/23 (`20260928T010248Z`), 18/18 (`20260928T010307Z`), 8/8 (`20260928T010333Z`) |
| CHAT-CONCURRENCY-01, TASK-RESULT-01 | 6/6, every user answered from 1 to 64 at once (`20260928T010356Z`); 9/9 (`20260928T010437Z`) |
| `scripts/separation_map.py` | nothing written outside the memory agent; every hand-off says where it came from |

**Harness changes.** No existing test was changed.
- CANARY-01 (listed in its README): a question about a word nothing holds; the image's marker in a QR code; a
  stored image's owner read through its memory (`unified.memory_media` only); the pool checks per kind; a question
  of the substrate's own.
- SYSTEM-CONVERSATION-01 and SYSTEM-PERCEPTION-01 remove what they write and check that nothing is left. Their
  lists did not include the pool, so since M2b-1 their "nothing left" was true only of the tables they knew. The pool
  is added to both, and nothing is left: 37/37 (`20260928T010828Z`, 18 pool rows removed) and 18/18
  (`20260928T010852Z`).

### 9.6 As built: M2b-3, first part — a person's image stays theirs (2026-09-28)

On the leak §9.5 found: the image leak is fixed first.

**Where a person's image went (mapped from `see`, before building).** Nine places took it, with no owner, into
the substrate's own memory or knowledge:

| # | Where | Into |
|---|---|---|
| 1 | `process_input` → `hold_perception` | `unified.perceptions`, in the model |
| 2 | `process_input` → `submit_image` → concept ingestion and the learning fan-out | the shared graph, its beliefs and the vocabulary |
| 3 | the perception hub, read by `_store_memory` | the perceptual stamp on every memory formed within 120 s, whoever's it was |
| 4 | `recognise_sensed` → `learn_fact` (rule naming) | the shared graph and beliefs |
| 5 | `recognise_sensed` → `detect_knowledge_gap` | the substrate's own open questions |
| 6 | `recognise_sensed` → `learning.recognize` (clause classifier) | the shared graph and beliefs |
| 7 | `recognise_sensed` → `describe_kind` | what the substrate holds of a kind |
| 8 | `perceive` (a pixel classifier) → `learning.recognize`, `note_perception` | the shared graph, and the stamp |
| 9 | `_react_percept` (VERIFY) → `detect_knowledge_gap` | the substrate's own open questions |

Its memory, its picture and its pool item were already theirs. Sensing adds nothing to the instance library (only
`learn_instance` does), and events are not stored.

**Built.** One rule: a person's percept goes where their words go. The substrate's own seeing is unchanged.
- **Whose it is travels with it.** `PerceptionData.origin`. `process_input`, `note_perception`,
  `coord.process_input`, `perceive`, `recognise_sensed` and `perceive_sensed` take it, with no default. The
  perception producers (`submit_image`, `submit_video`, `submit_sensor_reading`, `submit_perception`) take it
  too.
- **The row is theirs.** `unified.perceptions` is per-owner (`PER_OWNER_TABLES`), has an `owner` column, and is
  created in every store its rows are kept in. `hold_perception` writes a person's to their context.
  `search_perceptions` reads the substrate's own unless a person's are asked for. (Retired 2026-09-29 with the
  perception manager: the percept is the memory of perceiving, which is already its owner's.)
- **What it shows goes to their context** (`_admit_perceived`). Each edge of the observation goes through the
  learning authority's router (`learn_fact(actor=…)`) to their context, as a told fact does. Nothing enters the
  shared graph, its beliefs or the vocabulary.
- **It is never promoted.** The promotion gate lifts a person's claim into the shared mind when another person, or
  the substrate, holds it. It no longer lifts what a person's work produced (PERCEPTION, INDUCED_RULE): two people
  showing the same picture do not put it in the shared mind. Told facts are unchanged; how they may be promoted is
  still an open decision.
- **Recognition names into their context.** The substrate's own rules and classifier name what is in a person's
  image from what was just seen in it: their blobs are not in the shared graph to be read back. `learning.recognize`
  takes `actor` and, from the caller, the observation the features rest on (`lineage`). The names, the questions
  left open and a VERIFY's follow-up are theirs. A percept is judged by what its owner holds (`_held_posterior`,
  `ScopedContextStore.belief`).
- **The kind does not learn from a person's image.** `describe_kind` runs only on the substrate's own seeing. A
  person's image reaches the substrate's knowledge only as an experience, through the lift and the gate.
- **The stamp keeps to its owner** (`MemoryAgent._perceptual_state`). A memory is stamped only with perceptions of
  its own owner, each saying whose it was. A person's memory does not carry the substrate's environment either.
- **`scripts/separation_map.py`** also finds a perception door (`see`, `process_input`, `note_perception`) that
  does not say whose the perception is.

**Found and fixed on the way.**
- **My regression from M2a.** M2a made `see`'s `actor_identity` required and missed the environment scan's call.
  Since then the scan has raised TypeError at its first image, and every entry after that image went unread. The
  scan now says the seeing is its own. The scanner rule above would have caught it.
- **Question gaps never registered.** `_register_domain_gap` called `self._actor()`, but `_actor` is a property, so
  it raised TypeError on every call, and the caller logged it at debug level. It is called as a property now, and
  the caller raises a fault in the code instead of hiding it. From now on, an unanswered in-domain question is
  registered as a known unknown, in the asker's context.

**Verified.**

| Run | Result |
|---|---|
| Test files touching the code, plus `tests/test_perception_owner.py` (new) | every test the same as after M2b-2 (31 fail and 3 error, failing before too), and 4 added pass: the scanner finds a perception that does not say whose it is; the stamp keeps to its owner; a person's image goes to their context and never the shared graph (the fake service replaced at its source, so both halves are real); two people showing the same picture do not promote it (sandbox) |
| CANARY-01 | **39/39**, twice (`20260928T014624Z`, `20260928T021238Z`). Nothing of the person's image is in a table of the substrate's own; their memories, perception row, pool item and context hold it (60 edges in their context); every stamp matches its memory's owner, and their memory formed while their image was in view carries it. Before: 31/32 (`20260928T010444Z`) |
| SEE-LOOP-01, SYSTEM-PERCEPTION-01, RECOGNISE-01, RECOGNISE-02, FRAME-01 | 23/23, 18/18, 33/33, 24/24, 14/14 |
| FALSIFY-01, MEMORY-PERCEPT-01, systems/PERCEIVE-01, PERCEIVE-05, PERCEIVE-SEE-01 | 8/8 (324 sightings), 15/15, pass, pass, pass |
| systems/EPISTEMIC-AFFECT-01 | 5/5 after two stale premises were corrected (below); it last ran on 09-09 |
| systems/PERCEIVE-02 | not run: it reads two files from a user's Desktop (`Founder Video.mp4` and a face photo) that are no longer there |
| SHAPES-LEARN-01 / 02, INSTANCES-01, SEPARATION-01, RELEASE-01 | 35/35, 32/32, 11/11, 33/33, 29/29 (the release cut keeps only the substrate's own perception rows) |
| SYSTEM-MEMORY-01, SYSTEM-REASONING-01, TASK-RESULT-01, CHAT-CONCURRENCY-01 | 18/18, 8/8, 9/9, 6/6 |
| SYSTEM-CONVERSATION-01 | 37/37 with "a mammal is an animal" taught into the sandbox (`20260928T021215Z`) |
| `scripts/separation_map.py` | nothing written outside the memory agent; every hand-off and perception door says where it came from |

**Tests and harness changed.**
- `test_release_environments` pins the learning store's tables: `unified.perceptions` is added, because the
  substrate's own perceptions are kept there when frozen.
- Seven calls say whose the perception is (`Origin.own(...)`), since the doors now require it: `scripts/teach.py`;
  `experiments/verify_wiring.py`; SEE-LOOP-01, MEMORY-PERCEPT-01, systems/PERCEIVE-01, PERCEIVE-05 and
  EPISTEMIC-AFFECT-01.
- CANARY-01:
  - while the person's image is in view they give a second job, so a memory of theirs forms in the window it is
    stamped in (their follow-up question had merged into an earlier memory, which is not re-stamped);
  - the checks above;
  - "the memory `see` made of their image" reads that memory by the id the percept carries back, not by time and
    tag. The environment scan now sees images again, so the substrate's own vision memory forms at the same time.
- EPISTEMIC-AFFECT-01:
  - it read `perceive`'s result as a dict, which `PerceptJudged` replaced;
  - it expected the first drain in a process to set the baseline and report nothing, but the boot now primes the
    baseline (`core/main.py`), so it checks that instead.

**Open.**
- A merged memory is not re-stamped with what was being perceived when it was seen again.
- PERCEIVE-02 needs replacement files, or the originals. The repo has a real video (`test_data/jellyfish_real_10s.mp4`)
  and real photographs (`data/vision_flan/images/`).
- M2b-3 continues: arguments (the person's reasoned claims are still in owner-less `reasoning_arg_*` tables),
  temporal knowledge, hypotheses, demonstrations.

### 9.7 As built: M2b-3, the rest — what reasoning writes down is whoever's reasoning it was (2026-09-28)

Step 3 approved.

**Where a person's reasoning went (mapped before building).** Three engines are shared by every conversation and
wrote what they held into owner-less tables of the model, and read all of it back:
- **Arguments.** `FormalArgumentationSystem` (one per process) checks every reasoning answer for fallacies. It
  wrote each claim, argument and fallacy to `reasoning_arg_*`.
- **Temporal knowledge.** `TemporalReasoningSystem`, inside the causal and temporal-logic strategies, wrote
  propositions and causal links to `reasoning_temporal_*`.
- **Hypotheses.** `HypothesisTestingSystem`, fed by the abductive strategy and the `generatehypothesis` tool, wrote
  hypotheses, experiments and evidence. The epistemic engine then took a stalled hypothesis up as the substrate's
  own work, whoever proposed it.

Two runtime tables were unclassified: `scoped_intents` and `failed_task_fingerprints`.

**Built.** One rule, the same as §9.6: a person's reasoning is theirs; the substrate keeps and reads back only its
own.
- **The memory agent writes each record with whose it is.** `hold_argument_claim`, `hold_argument`,
  `hold_fallacy`, `hold_temporal_proposition`, `hold_causal_link`, `hold_hypothesis`, `hold_experiment` and
  `hold_hypothesis_evidence` take an origin, write an `owner` column, and write to the owner's store
  (`write_store`).
- **The shared engines let go of a person's records.** Each engine persists every record, then drops a person's
  from its working set. It reads back only the substrate's own (`owner IS NULL`, from the model), so one person's
  claims never inform another's reasoning. The fallacy check takes the actor from the request: a person's claim is
  theirs and kept; reasoning that does not say whose it is gets checked and kept by no one.
- **Temporal knowledge** is created with the actor as owner, in both the causal and the temporal-logic strategy.
  A causal link is its cause's.
- **A person's hypothesis is theirs.** Its belief goes to their context (`ScopedContextStore.observe_claim`); the
  substrate's own keeps `create_belief`. A revision keeps its owner. The abductive strategy registers the best
  explanation as the actor's. The `generatehypothesis` tool reads the acting actor, and refuses outside a task,
  where no one would own the hypothesis.
- **The substrate's own work is its own.** The epistemic engine no longer takes up a person's stalled hypothesis.
  Its file-write evidence no longer carries the path written (`delta_bytes=…`).
- **Failed work is whose work it was.** `failed_task_fingerprints` has an owner. A person's are kept in their
  context, and only the substrate's own are read back as "do not queue again".
- **`PER_OWNER_TABLES`** now also holds nine tables whose substrate rows are kept in the model:
  - `perceptions`;
  - `reasoning_arg_claims`, `reasoning_arguments`, `reasoning_arg_fallacies`;
  - `reasoning_temporal_propositions`, `reasoning_temporal_causal_links`;
  - `hypotheses`, `experiments`, `evidence`.

  It also holds two tables whose substrate rows are kept in runtime: `scoped_intents` and
  `failed_task_fingerprints`.

**Found and fixed on the way.**
- **Hypothesis evidence was never saved.** Its timestamp was written as text into a timestamp column. It is a
  datetime now, as the other two saves use.

**Verified.**

| Run | Result |
|---|---|
| `tests/test_reasoning_owner.py` (new) | 5/5, on the sandbox: a person's argument is kept as theirs and let go by the shared engine; temporal knowledge is whoever's reasoning made it; a person's hypothesis is theirs and believed in their context; the substrate does not take up a person's stalled hypothesis; a person's failed work is recorded as theirs and not read back |
| `tests/test_release_environments.py` | the learning store's pinned tables include the eight step-3 tables |
| CANARY-01 | 57/57 (`s3_run3`). The person's argument, cause and explanation exist, in their context; nothing of theirs is in a table of the substrate's own |
| regression, 2026-09-28 | SYSTEM-REASONING-01 8/8, INTENT-04 15/15, CONSTITUTION-01 39/39, CONSTITUTION-02 23/23, PLANNING-01 39/39, RECONCILE-01 27/27, OPERATOR-REMOVAL-01 21/21, RECOGNISE-01 33/33, SYSTEM-PERCEPTION-01 18/18, PERCEIVE-01 pass, and the core set |
| INTENT-03, CONSTITUTION-03 | failed at the time. Neither cause was step 3. INTENT-03 planned in the teaching directory, because the hand-written filesystem domain held one directory per process. CONSTITUTION-03 used an operator it never declared. Both were fixed by the collapse of that domain (LAB_NOTEBOOK, 2026-09-28): 13/13 and 8/8 |

**Tests and harness changed.**
- `tests/test_reasoning_owner.py` is new.
- `test_release_environments` pins eight more learning-store tables.
- CANARY-01:
  - a reasoning scenario (`reason_about`, with premises and a rule written with an arrow, since rules in a
    request count only in that form);
  - the question "what would cause…", which is what the abductive strategy answers;
  - a check per label that nothing of the person's is in a table of the substrate's own;
  - checks that their argument, cause and explanation exist.

  The writing-job measurement was removed: Law 2 refuses a person's declared modifying plan, so the check passed
  without measuring anything.

**Open.**
- **Demonstrations.** A person's demonstrations and the changes observed with them go into the shared model and
  concept graph. The tool world (`tool_domain._WORLDS`) is one per domain for the whole process, so it mixes the
  places different people's acts touched. Proposed:
  - per-owner tool worlds;
  - a person's demonstrations kept in their context;
  - then either **(A)** induce only from the substrate's own until M3's residue test, which is recommended because
    a rule lifted from a person's work can keep their path as a constant; or **(B)** induce from everyone's, as
    §10.4 is written, with no concept projection for rules drawn from people's work.
- **`meta_learning_strategies`** should move to the model at M4. Moving it now would stop production adapting its
  strategy counts.
- **The `generatehypothesis` tool now refuses outside a task.**
- **Law 2 refuses a person's declared modifying tool plan** ("would modify with no account of why"), including a
  `write_file` or `generatehypothesis` job. This is still open.
- **Residue in the main store:** 5 `reasoning_arg_claims` and 5 `reasoning_arguments` rows with no owner, written
  2026-09-27 02:37 UTC ("Generally, patterns involving 'shoe isa' tend to occur"). They are most likely test
  residue. Reported, not deleted.

## 10. M3 mapped: learning from experience (2026-09-28, before building)

**The direction, in the order it was given.**
- **The substrate runs autonomously**, and the constitution judges the substrate's *intentions*, not approved
  actions: what matters is that the substrate has the right intentions, whatever the action.
- **Before it acts on its own, it must hold a high belief** that it is doing the right thing. It reaches that belief
  by reasoning: is it allowed, what would happen, can it be undone.
- **The laws that judged the act itself keep their content.** It moves into that reasoning.
- **Capabilities roll out to users in stages**, as the model grows confident in experience. Users can still set
  their level of autonomy, privacy and permissions; that is second-class. The work now is making the system safe
  before deployment.
- **What a user tells about themselves is theirs, and never applies to other users.** Research, coding, system
  maintenance and repair, and methods learned by trial and error, web searches and user suggestions, are world
  knowledge.
- **A tool run moves beliefs not only about what it does but about its success and failure, as everything else
  does. Failure moves belief too, but not the way success does.**
- **Tool use is already captured in memories.** A tool-specific learning path was built and reverted the same day,
  unrun: tools are not separated out.

### 10.1 What happens today (measured in the sandbox and read in the code)

- **Everything waits, and nothing is learned from it.** The pool holds 65 tasks (57 the substrate's own), 25
  look-ups, 215 conversations, 192 reasonings and 1 seeing. All of them are decided as candidate, already held, or
  nothing to learn.
- **The substrate's own work is learned from directly, by learners that already exist:**
  - operator induction, from demonstrations;
  - domain expansion and transfer, from the task-outcome memory (`OUTCOME_OBSERVED`);
  - operating reliability per domain, from the operating verdict (`_operating_verdict`, the credit gate);
  - the completion belief, from each run's own report and a fresh look at the world (`_observe_completion_evidence`);
  - look-up findings, admitted at once (one page, one sentence);
  - perceptions and taught facts, through the learning fan-out.
- **What nothing learns:**
  - beliefs about how the substrate's own acts go: what each step does, and whether it works. 0 beliefs from 87 tool
    runs;
  - anything from a person's experience. Their experience is theirs, and no lift takes the general part out;
  - a gate for world facts. A look-up is still one page, one sentence.
- **The memory a task forms is cut.** `_store_task_outcome_meta_memory` keeps the result as text cut at 500
  characters.
  - In the sandbox, 40 of 60 task memories are cut, and none keeps a plan's steps (which tools ran and how each went).
  - The method is kept only for a declared tool plan.
  - A plan's own report is one line, "handler", not a line per step.
- **The pool holds a second record of the same task.** `capture_task_outcome` assembles it separately from the task's
  fields, and it misses the same runs:
  - only a declared tool plan's runs are in it (`tools_run`);
  - a proved operator, a reading step and an artefact write are recorded at the registry and not attributed to their
    task, because only `_run_tool` binds the acting task.
- **The operating verdict goes to the domain and not into the record**, so a failure does not say what caused it.
- **A belief's first observation counts twice.** In `BayesianUncertaintySystem.observe_claim` and the scoped
  store's, a new claim's prior is set from the observation and the same observation is then applied again. One
  successful run would make a belief 99%, and after five a failure no longer moves it.

### 10.2 The design

**One path.** The memory agent takes each candidate through the lift and the residue test, then hands what survives
to the learning authority. The belief system is the gate. The learners above stay: M3 adds what nothing learns and
does not learn again what they do.

**Whose.**
- A person's part stays theirs: what they said, gave or are, their files, data and project content, and facts about
  them.
- What the substrate learned by doing is world knowledge once lifted: methods, fixes, tool behaviour, research
  findings, and suggestions that proved out.
- §10.2 of `SEPARATION_MAP.md` counted "designs and methods" as the person's, and §10.5 decision 4 kept "a method the
  person brought" as theirs. Both change: their design and project content stay theirs, and the method, once it
  works, is world knowledge.

**The lift.** A person's particulars become variables. They are found by their parts' origin, and by comparing
experiences of the same shape (`rule_induction.anti_unify`). Only what the outcome depended on stays. For the
substrate's own experience there is nothing to lift.

**The residue test.** A term whose only source is a person's material makes the lesson theirs.

**What a task yields.**
- The steps and what each did.
- Whether the task worked, and the fix that got past a failure.
- A belief for each: that the step does what it did, and that it works, resting on a memory.
  - For the substrate's own task, that memory is its task-outcome memory.
  - For a person's task, it is the substrate's own memory of the lifted lesson. Their memory stays in their context.

**How a belief moves (point 14).**
- Each outcome is one witness.
- A success raises the belief a little. A failure lowers it by more, and only the belief of whoever caused it, as the
  operating verdict and the run's failure category say.
- A failure the world caused lowers neither.
- A new claim starts even, and its first observation is applied once.

**What it feeds.**
- The reasoning before an act: what would happen, and how surely.
- The belief the constitution will judge.
- The confidence that capability stages unlock on.

### 10.3 Build order

| Step | Built | Verified by |
|---|---|---|
| **M3-1** | The belief kernel counts a first observation once, in both stores. The task's memory, a row like every other memory, keeps the whole task in its `raw_event`, the memory system's own place for an event's record, instead of a result cut at 500 characters: every step with its tool and outcome, the checks and the verdict. No new kind of memory and no record beside it (there is no separate task memory). The pool only queues that memory; it holds no second copy. The lift and the residue test for tasks. Beliefs about each step, for the substrate's own tasks and, lifted, for a person's | a new targeted experiment, run once; CANARY-01 and SEPARATION-01 extended so no term of a person's material appears in anything learned; LEARNED-WORK-01 re-run (a second attempt goes differently) |
| **M3-2** | Research: the gate for world facts replaces one page, one sentence (§10.5 decision 1) | the same, for look-ups |
| **M3-3** | Conversations, seeings and reasonings: what each yields that is the substrate's | the same |

**Still open (`SEPARATION_MAP.md` §10.5):** 1 (the bar for a world fact), 3 (production trying a candidate
method), 5 (a person deleting their material), 6 (a person confirming their task), 7 (research sending their words
out). Decision 2 (a method is learned once it works again) becomes the belief's: one success moves it a little.
Decision 4 changes as above.

### 10.4 As built: M3-1, first part — a task's memory is its whole record, one memory per task (2026-09-28)

On the task memories: the memory is a complete task record. One run's eight rows were unacceptable: the memory
agent was not merging memories or summarising them (this task failed this many times, for this reason). Task
memories match the current memory system; no new methods are invented.

**What the memory was.** A task's memory kept its result as text cut at 500 characters:
- 40 of 60 task memories in the sandbox were cut, and none kept a plan's steps;
- the two failure paths kept no result at all;
- every run of the same task was a row of its own, because records are exempt from merging (merging had once hidden
  their counts);
- the pool held a second copy of each task, assembled separately from the task's fields.

**Built.**
- **The task's memory keeps the whole task** in its `raw_event`, the memory system's own place for a record, under
  `experience`:
  - the request;
  - every tool run with what came back;
  - the errors, the fix and the checks;
  - the result, with a plan's steps inside it;
  - the verdict (`_operating_verdict`: whether the outcome counts, and what it was read from).

  All three paths that end a task keep it, failures included. `MemoryAgent.task_experience` builds it (it was the
  body of `capture_task_outcome`).
- **The pool queues the memory and holds no copy.** `remember_experience(experience, memory_id=…)` stores a
  reference: `experience_pool.memory_id`, with `parts` left empty. The worker reads the parts from the memory's
  record, for the occurrence the item is about. A queued memory that is gone leaves nothing to learn.
- **A task asked again is merged into the memory that holds it** (`MemoryAgent._merge_occurrence`).
  - "The same task" is the same request from the same owner (`task_identity`).
  - The record keeps every occurrence, with the latest on top and counts beside them (`merge_task_outcome`).
  - The content is said over all occurrences (`task_outcome_account`), for example: "I was asked to put report.txt
    in archive. I did it 5 times. I could not, because …". A reason is the same however its measurements came out.
  - Once, it reads as it always did. The 500-character result is no longer pasted into the words; it is in the
    record, whole.
  - `update_memory` may now rewrite a memory's `thinking_state`.
- **Every reader counts occurrences, not rows:**
  - the domain grouping (`_task_outcomes_by_field`, one SQL row per occurrence);
  - the recall of similar tasks (`_extract_task_outcomes`);
  - the domain success rate (`get_domain_performance_stats`, through `task_outcomes_from_memory`);
  - domain expansion, which takes a memory up again when an occurrence arrives after it was expanded.

**Verified, each run once.**

| Run | Result |
|---|---|
| `tests/test_experience_pool.py` | 9/9. The hand-over test now builds the experience; the new test queues a memory and decides it from its record, and a queued memory that is gone leaves nothing to learn. The first run of the new test failed on the test's own race: storing a memory starts the pool worker, which claimed the items first. It now runs in shadow mode, as other harnesses do |
| `tests/test_task_memory_merge.py` (new) | 6/6: the same request is the same task; once, it is said as always; asked again, it says how often and why; every occurrence reads back as a record; the store keeps one memory per task and owner (3 occurrences in one, a person's the same task in their own); a reason is the same however its numbers came out |
| `tests/test_domain_expansion_chain.py` | 11/11 |
| CREDIT-01 | 26/26 before the merge (`20260928T203440Z`) and after it (`20260928T204453Z`). After it, the run's tasks are 2 memories instead of 8: "put report.txt in archive", 5 done and 1 not (6 occurrences), and "paint the report red", 2 not; the pool holds 6 and 2 items pointing at them |

**Not done.**
- The task memories written before this say no identity, so they are not merged with the new ones: 68 in the
  sandbox, and those in the main store. Merging them is a data change, not made.
- A memory in the cold tier is not looked up for a merge; the task asked again after 60 days starts a new memory.
- The failure reasons are the task loop's own text ("Max retries exceeded: …"), long and machine-worded.
- The rest of M3-1: the double count in the belief kernel, splitting a plan's steps into parts of their own, the
  lift and the residue test, and the beliefs.

**Stopped the same day.** "Every task gets a memory" was false: the substrate may run 10 tools in a row in one
session or one task, and a design task, a system maintenance task or a user request may need several tasks in one
run. So when a memory starts has to be reasoned out.

**Verified:**
- A proved plan is a chain of separate queued tasks, and each stores its own memory.
- Nothing ties one run's memories together: a memory is stamped with its intent only while a tool runs, and 0 of 70
  task memories carry one.
- Merging by the request's wording merges separate runs and cannot gather a run's different tasks.

The trigger, the `identity` the task loop stamped, is removed, so nothing merges. The merge code is left idle, to be
re-keyed or deleted once it is decided where a memory starts and stops. The whole-task record and the pool's
reference stay.

### 10.5 Where a memory starts and stops (decided, then mapped, 2026-09-28)

**Decided:**
- For users, that is one pursuit.
- When the substrate works on itself, it always plans; it never just acts. Its work has the same shape, and
  everything within that pursuit is one memory.
- Memories that overlap are recall's to handle; writes are not constrained.

**Read in the code.**
- **The intent tree already marks a run.**
  - Work is taken on with an intent (`intend`): a user's request (a root, nothing parents it); knowledge refresh,
    repair, exploration (one per drive) and agent work (each a root of its own).
  - A goal raised while working is a child intent (`parent_intent_id`). A proved plan's steps carry the plan's intent.
  - A pursuit ends at `conclude_pursuit`, or at the plan's reconciliation for a planned route.
- **Memory does not follow it.**
  - A memory is formed per queued task, at its end, so a plan's steps are a memory each.
  - Look-ups, turns, seeings and reasonings are memories of their own.
  - Nothing ties a pursuit's memories together: 0 of 70 task memories carry an intent.
- **The substrate's own work does not plan.**
  - A repair is one task, "Fix <error> in <source>: <message>".
  - A knowledge refresh is one task with a written brief.
  - Exploration is one task per drive.
  - Each goes straight into the task paths (the knowledge loop, or the honest gap). Only work that names a state to
    reach is planned.

**What the decision asks for.**
1. **A memory per pursuit.** It is formed when the pursuit is taken on. Each task, step, tool run and sub-goal within
   it is added as it ends; a task finds its pursuit by walking its intent up to the root. It is closed with the
   pursuit's outcome when the pursuit concludes. No task has a memory of its own, and separate pursuits are never
   merged.
2. **The substrate's own work always plans.** Repair, knowledge refresh and exploration become pursuits that go
   through planning (goal, plan, steps), the same shape as a user's.
3. **What other faculties form within a pursuit** (a look-up, a reasoning done for it) belongs to that pursuit's
   memory.
4. **Writes are not constrained.** Overlap between pursuits is recall's to bring together.

**Merging removed (2026-09-28):** the memory agent does not merge near-identical memories, or memories at all. When
the substrate runs the same tool calls or hits the same errors within one pursuit, that is summarised inside the
memory; the substrate can do the same thing two days in a row, and merging was wiping one of those memories.
- **Removed from the memory agent:**
  - the write-time merge by likeness (0.75), with `_find_similar_memories`, `_could_be_the_same_claim`,
    `_subject_of` and `_merge_memory_content`;
  - the background `consolidate_old_duplicates` (0.85), with `_cluster_by_similarity` and `_consolidate_cluster`,
    which nothing called;
  - the idle request-keyed merge (`_merge_occurrence`, `merge_task_outcome`, `task_identity`).
- `IMemoryConsolidation` no longer declares `consolidate_old_duplicates`. As an abstract method it would have left the
  memory agent unconstructable.
- **What merging had done in the sandbox:** 116 memories were merged from others, one of them from 39.
- **Kept for the pursuit memory:** reading several tasks out of one memory (`task_occurrences`,
  `task_outcomes_from_memory`); saying them with repeats counted (`task_outcome_account`, where a reason is the same
  however its numbers came out); and `update_memory` rewriting a memory's record.
- **Verified, each run once:**
  - `tests/test_task_memory.py` (new) 4/4: the same thing on two days is two memories, and "A kidney is an organ" and
    "A liver is an organ" are two;
  - the memory write-path tests 33/33.
- NLU-13's "merge safety" family is now "kept apart": the cases stand as what recall must keep apart.

**Found on the way, fixed:** a destroy pattern in the constitution's act reading was a raw string cut short by `""`,
so `echo "" > file` (emptying a file) was not read as a destruction. `echo '' > file` was. CONSTITUTION-03 now tries
the double-quote form too: 8/8, the audit log held 5 ways (`20260928T230107Z`).

### 10.6 As built: one memory per pursuit (2026-09-28)

Approved to begin.

**Built.**
- **A pursuit's memory is formed when the work is taken on.** `intend` forms it for a root pursuit
  (`MemoryAgent.begin_pursuit`), a request or a pursuit of the substrate's own. A goal raised inside a pursuit forms
  none of its own.
  - A pursuit taken up again is the same pursuit: its memory opens again.
  - Its record (`schema: pursuit_v1`) holds the pursuit (intent, kind, aim, status), its tasks, and one experience.
- **Every task is added to it as it ends** (`add_to_pursuit`), found by walking the task's intent up to the root
  (`_root_intent_id`, `_pursuit_memory_for`).
  - No task has a memory of its own.
  - The task's record joins the pursuit's occurrences, and the latest is also kept on top, where one record is read.
  - The task's experience parts join the pursuit's, with repeats counted (`_summarize_parts`): the same call, the same
    error, however often it came, is one part saying how many times and holding the latest. Numbers do not make two
    parts different; words and names do.
  - The task's domain tag joins the memory's tags.
  - Work taken on with no intent is a pursuit of its own, closed with its one task.
- **It says the whole pursuit** (`pursuit_account`): each task with how often it went each way, then how the pursuit
  ended.
- **It is closed when the root pursuit concludes**, at `conclude_pursuit` or `_reconcile_intent`
  (`_close_pursuit_memory`). It is then queued in the pool as the one experience it was.
  - A task that ends after the close is added all the same, and the pursuit is decided again.
- **Writes to one pursuit memory are serialized across instances** by an advisory lock on its id. Pursuit memories
  are found through an index on the intent they are the memory of.
- **Readers** read a pursuit memory as they read a task memory: `event` stays `task_outcome`, the occurrences are its
  tasks, and domain expansion skips a pursuit with no task ended yet.

**Verified, each run once.**

| Run | Result |
|---|---|
| `tests/test_pursuit_memory.py` (new) | 4/4: repeats within a pursuit are counted, not listed; a pursuit says each task and how it ended; one pursuit is one memory, closed and queued once, re-queued when a task ends after the close, opened again when taken up again, and a second pursuit with the same aim is its own memory; through the coordinator, a root task and the task of a goal raised inside it land in one memory, and the conclusion closes it |
| the pool, task memory, domain expansion, memory writers and memory loop tests | 32/32 |
| CREDIT-01 | 26/26 (`20260928T231904Z`). Its tasks are made without an intent, so each drive is a pursuit of its own: 8 memories, each closed with how it ended, and 8 pool items pointing at them |

**Open.**
- **The substrate's own work does not yet plan** (step 2 of §10.5).
- **Look-ups and reasonings done within a pursuit** are not yet part of its memory (step 3).
- **A plan's step tasks are made with no actor** (`state_plan_to_tasks`), so a person's plan step is labelled the
  substrate's own in its experience parts. The pursuit memory's owner is the root's actor.
- **"I was asked to …" is said of the substrate's own work too**, as it always was.

**What started a pursuit is kept (2026-09-28):** the initial message, error or system notification that caused
it, whatever it is.
- `intend(..., trigger=)` takes what started the work as {what, source, content}. `begin_pursuit` keeps it whole: as
  the pursuit's `trigger` in the record, and as the first part of its experience, saying whose it is. A pursuit
  started again keeps each trigger (`last_trigger`, and a part counted like any repeat).
- **Each producer says what started its work:**
  - a person's request: their message, word for word, with where it came from and its session (theirs);
  - a repair: the error's type, message and source, and the whole traceback (the world's). The task's own metadata
    still cuts it at 500 characters;
  - a knowledge refresh: what fired it (the substrate's);
  - exploration: the drive's goal, its metadata and the task's (the substrate's);
  - an agent deployment: its job, parameters and granted tools.
- Work whose producer says nothing, and a pursuit given its memory late, keep the task as it was made
  (`_task_trigger`).
- Verified: `tests/test_pursuit_memory.py` 4/4, run once. The error trigger keeps all 401 lines of its traceback; a
  pursuit started again keeps both triggers; through the coordinator, a person's message is held word for word and
  is theirs.

### 10.7 Step 2 mapped: the substrate's own work always plans (2026-09-28, before building)

When the substrate works on itself, it always plans; it never just acts, and its work has the same shape. Step two
follows, with no workarounds, stubs or fallbacks unless absolutely necessary, keeping the authorities.

**Read in the code.** Planning is owned by the planning engine (`PlanningEngine.plan_for_goal`), which has two modes by
goal type.
- **STATE goals** (conditions to reach) are planned by search over learned operators. The proved route is recorded as
  the goal's intent (`_record_plan_intent`), and each step carries it.
- **DESCRIPTIVE goals** get template decomposition (`_generate_tasks_for_goal`).
  - The phases are found by word lists (`_WORK_PHASES`: research, analysis, creation).
  - A goal that names none gets a default breakdown: "Research requirements for X", "Analyze approach for X",
    "Execute: X". Its last step reaches the honest gap, because nothing can do "X". That is a plan in form only.
  - Template plans record no intent, so their steps cannot be found in a pursuit.

**How each of the substrate's own kinds of work runs today:**

| Work | Today | Planned? |
|---|---|---|
| Drive goal (competence, confidence) | `_run_exploration_cycle` creates a goal through the planning engine, then queues a task; `_execute_drive_goal` runs up to 8 experiments inline (the domain's proposer chooses them) and re-induces the operator | no: the experiments are chosen and run in one go, never laid out as a plan |
| Repair | one task, "Fix <error> in <source>: <message>" | no: it reaches the honest gap |
| Knowledge refresh | one task carrying a written brief | no: the knowledge loop reads the brief |
| Agent work | the deployment's declared tool plan | declared by whoever deployed the agent |
| A goal that names a state | `_drive_substrate_goal` asks the planning engine | yes |

**What "always plan" asks for.**
- Each of the substrate's own pursuits raises its work as a goal through the planning engine, under the pursuit's
  intent. The plan's steps carry that intent, so their outcomes land in the pursuit's memory.
- Nothing acts without a plan. When no plan can be made, the pursuit ends saying why, with the diagnosed deficit.
- The default breakdown goes: it is a fallback that makes a plan where there is none.
