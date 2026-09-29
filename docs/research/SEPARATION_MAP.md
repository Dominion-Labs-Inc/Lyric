# World knowledge, world model, user context: the change map

Requirements, 2026-09-27, in order:
1. World model and world knowledge are kept apart from self knowledge and user context.
2. That is established now, with separate databases, even where nothing uses them yet.
3. World knowledge is self knowledge from a world perspective: nothing learned is taken as fact until there is
   irrefutable evidence for it. So there are three parts: world knowledge, world model, and user context.
4. The world model is the model the world uses. The substrate is copied, one copy for development and one for world
   use, and that is where world knowledge comes in.
5. There is no knowledge graph; there is only memory.

His rule for any change of this size applies: map everywhere that has to change before building, and leave no
function half done. Nothing in this map is built, apart from the databases in §2.

## 1. What the words mean

Being replaced by the industry-standard terms (§8): development, staging, production, the model and its releases, runtime, user context.

| Term | Meaning |
|---|---|
| World model | the copy of the substrate that the world uses. There are two copies: one for development, one for world use. It is the same design the self partition was built for: "one model the whole world uses, tells users apart, stays air-gappable" |
| World knowledge | the world model's own knowledge. It is the substrate's self knowledge, seen from the world's side: what it has learned, held in memory. It does not take what it learns as fact until irrefutable evidence establishes it |
| User context | what each person tells it or asks of it, kept to that person and apart from world knowledge |
| Memory | the one store. The memories, the concepts and links between them, and the beliefs are all memory. There is no separate knowledge graph |

## 2. The databases

Created 2026-09-27. Each was built from a schema-only dump of `torinai_db` and verified against it:
- the same 336 tables and 1,243 indexes;
- identical columns (one checksum over every table's columns);
- `vector` 0.8.1;
- 0 rows.

Nothing writes to them yet.

| | Main | Sandbox |
|---|---|---|
| World knowledge | `torinai_db_world_knowledge` | `torinai_dev_world_knowledge` |
| World model | `torinai_db_world_model` | `torinai_dev_world_model` |
| User context | `torinai_db_user_context` | `torinai_dev_user_context` |

A self-knowledge pair created earlier the same day was dropped on correction. It was empty, had no
connections, and only the reset script named it. `scripts/reset_dev_store.py` empties the four sandbox databases,
each by fixed name.

**What each database holds (confirmed 2026-09-27, following the research)**

| Database | Holds |
|---|---|
| `torinai_db` | the development copy, whole |
| `torinai_dev` | its sandbox |
| `torinai_db_world_model` | the running store of the copy the world uses: its tasks, queue and own records |
| `torinai_db_world_knowledge` | that copy's memory: what it knows, stored as the research found (patterns and memories in memory, scores in beliefs, meanings as linked facts) |
| `torinai_db_user_context` | each person's context |

The `torinai_dev_*` databases are the same three for the world copy's sandbox.

**Each world database holds only its own tables.** Every database was created with the full schema, so a statement
sent to the wrong one would succeed silently against its copy of the table. Trimming each to its own tables makes
a wrong route fail loudly instead ("relation does not exist"). No foreign key crosses stores: the directive,
component, chaos, goal/plan and test tables stay within the world model; the rule and ledger tables stay within
world knowledge. The enum types are kept in all three.

## 3. Within one copy: its own knowledge, kept apart from a person's context

Memory today holds both, in one set of tables. A person's told facts and rules already go to the per-person
tables (`scoped_concept_relations`, `scoped_beliefs`, `scoped_intents`) through the learning authority's router,
which SELF-PARTITION-01 proves. Everything below that belongs to a person but is not routed there is still open:

| What | Where it is written | State |
|---|---|---|
| The memory of a task done for a person | `autonomous_coordinator.py:8907` (`store_memory`) | stored with no owner, holding the person's request and the result: the leak found 09-26, still open |
| A person's question it could not answer | `known_unknowns` (`bayesian_uncertainty.py`) | stored verbatim; the table has no owner column (09-26, still open) |
| Facts about the speaker in a taught sentence ("This is my shoe.") | `teaching.py` → `learn_facts` | stored as the substrate's own knowledge. The meaning taught with the sentence marks who each fact is about (`?speaker`, `?listener`, `?shown`, `?previous`, or none), so the substrate can judge where it belongs without a word list |
| Exchange records (what a person asked, what it answered) | the conversation | owned by the asker (fixed 09-26) |

Everything else the substrate learns is its own knowledge: lessons, English, web findings, the host scan, what it
sees, its tools and what they did, learned rules. Measured in the sandbox after SHAPES-LEARN-01, memory held 1,672
concepts:

| Source | Concepts |
|---|---|
| The lesson | 7 |
| Tool declarations, under 16 generic field names (`security`, `network`, …) | 949 |
| The host scan | 706 |
| Percepts | 10 |

They are told apart only by field name and first producer. A lesson named `security` shares one domain with the
tools' `security` concepts.

## 4. How a copy reaches its databases

**Today.** `TorinUnifiedDatabasePostgres` (`core/database/unified_database_postgres.py`) is one object per process
with one connection pool. A running copy can reach exactly one database. The code runs 518 SQL call sites, and
obtains the database in 170 places.

**Change: the table decides.** The manager stays the one object every component holds, and routes each statement
to the database its tables live in. Only these callers name the database:

| Case | Why the table cannot decide |
|---|---|
| Rows of `memory_hot`, `memory_cold`, `memory_media`, `archive_log`, `known_unknowns` | the substrate's own rows are world knowledge, and a person's rows are that person's context. The table exists in both |
| A statement that touches no table (`SELECT 1`, advisory locks) | there is nothing to route by |
| A raw connection (`get_connection`) in the substrate's own code (directives, the database layer) | its statements are not known in advance |

**Tools are not the substrate's stores (2026-09-27).** Tools serve the substrate itself, users and other
systems. A tool acts on whatever target its use names; it is not routed into the substrate's databases, and its
tables are not classified into them.
- The database tools (`database_tools.py`, 15) and the monitoring tools (`monitoring_tools.py`, 15) are not adapted:
  once the substrate is taught to code, it will not need tools that tell it exactly what to do in database and
  health operations. What happens to them is still to be decided.
- In the world copy, the database tools as written would reach that copy's own databases directly. Through them, a
  person's request could run SQL on its memory or on other people's context. The world copy does not carry them.

**The authority.** One list in `postgres_config.py` gives the store of every table the code uses: 101 tables, plus
ones the code creates when needed. The router resolves a table named without its schema the way Postgres does,
through the search path the manager sets itself; 116 such references were found.

**Refused, never guessed:**
- a statement touching two stores. Two exist, in `intent_authority.py` (a person's intents joined with the
  substrate's), and they are split;
- a table that is not classified;
- a statement with nothing to route by and no store named.

The development copy runs by the same rules, with all three stores in one database, so a wrong route is caught in
development before the world copy runs.

**The copy.** A setting, `TORINAI_COPY` (`development` or `world`), resolved like every other connection setting.
The world copy's databases are `<POSTGRES_DATABASE>_<store>`.

## 5. What reads must never cross

- **Research sends topics out.** Research topics come from `_thinnest_knowledge_topics`, wired this session. They
  must never carry a person's context. As built, they would also send the host's details out (`0 arm64`, file
  names); it has never run.
- **Answering a person** reads the world model's knowledge and that person's context, never another person's. The
  actor overlay already does this for told facts.
- **A copy of the development model given to the world** carries its knowledge, never any person's context.

## 6. After this work: check the belief system

The system is designed not to take everything it learns as fact automatically. We keep going around in
circles on it, so it is checked once this work is finished, as its own job, not raised during it.

## 7. Build order

Nothing is switched halfway: each step ends with every caller it touches switched and verified.

| Step | Built | Verified by |
|---|---|---|
| S1 | **done 2026-09-27.** The copy is a setting (`TORINAI_COPY`). The one list of which store every table is in (`postgres_config.STORE_TABLES`, `PER_OWNER_TABLES`, `TOOL_TABLES`). The manager holds one pool per database of its copy and places each world-copy statement by its tables, refusing what it cannot place. `scripts/separation_map.py` reads every statement in `core/` and reports how the world copy would place it. `scripts/world_copy_databases.py` builds the world databases, each holding only its store's tables (partitions kept with their table) | manager checks: development 8/8 (unchanged behaviour), world 16/16; a statement forced onto the wrong database fails ("relation does not exist") |
| S2 | **done 2026-09-27.** Every call site the tables cannot place names its store. Memory storage follows its owner rule across two databases: a person's rows in user context, the substrate's in world knowledge; each search reads the stores its actor may see, merged in the query's own order. Images follow their memory. Intent content follows its owner, and shape-and-content stay "both or neither" across two databases. Directives, the Constitution's ledger check, the health probe and the domain checks name their stores. The world copy leaves out the 12 registered tools that reach its own databases | scanner: 484 substrate call sites, none refused, 2 needing a store (both in code that already cannot run: the chaos memory adapter and the Slack handler). 300 of the tests touching these modules pass in the development copy; the 21 failures are all unrelated. **SEPARATION-01 28/28** (`20260927T144018Z`): 0 refusals raised in the whole run, counted inside the manager. Its hardened check found three more, now fixed: the ledger's schema (an index name places nothing; the ledger was failing silently on every write), the health monitor's pool, and the monthly partitions the first trim dropped |
| S3 | **done 2026-09-27** (§9.6). A person's context routed in full: the memory of a task done for a person is theirs; unanswered questions carry their owner; facts a taught meaning binds from its situation go to the speaker's context | SHAPES-LEARN-01 re-run; SEPARATION-01 as staging |
| S4 | **done 2026-09-27** (§9.7). The readers in §5, and development's own readers of the per-owner tables | SEPARATION-01 as staging |
| S5 | **done 2026-09-27**, as releases (§9.3): a release is cut from development's model and carries no person's context | RELEASE-01; SEPARATION-01 A |

## 8. The industry-standard layout: development, staging, production, and a frozen versioned model

Decided 2026-09-27: the world-model terms are fixed to match the industry standard, as long as that still gives a
separate, frozen, version-controlled model. It does. This section is the plan. Its
terms replace "world copy", "world model" and "world knowledge" once built.

**The terms.**

| Was | Industry term | Meaning here |
|---|---|---|
| development copy | **development** | where the model is taught and learns: `torinai_db` (sandbox `torinai_dev`) |
| world copy | **production** | serves people from a released version of the model |
| (none) | **staging** | runs a release candidate exactly as production would, before it is promoted |
| world knowledge | **the model** | what the substrate knows (its memory, beliefs and the facts linked in it). In production it is a **release**: a numbered snapshot of development's model, frozen, never edited, replaced only by a newer release |
| world model (the running store) | **runtime** | production's operational records: tasks, queue, its own records, usage |
| user context | **user context** | unchanged: each person's own, kept apart |
| `TORINAI_COPY` | `TORINAI_ENVIRONMENT` plus `TORINAI_RELEASE` | which environment a process is, and which release it serves |

**The databases.**

| Now | Becomes |
|---|---|
| `torinai_db`, `torinai_dev` | unchanged (development, and its sandbox) |
| `torinai_db_world_knowledge` (empty) | replaced by releases: `torinai_model_v1`, `torinai_model_v2`, … Each is read-only at the database level, with its content checksum in the registry |
| `torinai_db_world_model` | `torinai_prod_runtime` |
| `torinai_db_user_context` | `torinai_prod_user_context` |
| `torinai_dev_world_model`, `torinai_dev_user_context` | `torinai_staging_runtime`, `torinai_staging_user_context` |
| `torinai_dev_world_knowledge` | the staging copy of a release candidate |
| (new) | `torinai_model_registry`: every release with its version, when it was cut, from which database, the code commit it was cut with, its content checksum, and its status (candidate, staging, production, retired) |

**The release lifecycle.**
1. Cut a release from development's model. The tables of the model store (§4) are copied into
   `torinai_model_v<N>`, which is set read-only, and the registry records it.
2. Stage it: staging serves the candidate on sandbox databases, and SEPARATION-01 becomes the staging check.
3. Promote it: production is pointed at `v<N>`. At start it checks that the release's checksum matches the
   registry and that the release was cut with the code production is running.
4. Roll back by pointing production at the previous version, which is still intact.

**What production does with each write a frozen model refuses** (measured 2026-09-27: the production layout
served a person against a read-only release of 241 memories, 1,072 concepts and 243 beliefs).

| Write | Where it came from | In production |
|---|---|---|
| Creating tables at start-up | 5 places: `rule_store`, the classifier store, unanswered questions, perceptions, volatility | a release is cut complete, so creation is only checked: the table, index or column must be there, and if it is not, the release and the code do not match and start-up stops |
| Model maintenance: refreshing concept embeddings (347 retries), memory decay, low-importance cleanup | `universal_domain_master`, `postgres_storage` | development's job; a frozen model is not maintained |
| Access counts on the release's memories when recalled | `postgres_storage.get_memory` | recorded as usage in runtime, not on the release's rows |
| The substrate's own learning while serving: research findings, exploration, beliefs moved by outcomes, domain judgments | none in a 20-minute frozen run of serving and idling: the same 9 write sites as the one-minute run, nothing more. It does not yet learn from its own work (LEARNED-WORK-01, 09-26) | written exactly as every lesson already is (memory, beliefs, linked facts, the ledger, each with its evidence), into production's own **learning store**: the model's tables, beside the frozen release, never into it. Development takes those lessons, with their evidence, into the next release. No separate proposal format: lessons already go into memory with their evidence. **Decided (2026-09-27): strictly frozen.** Production answers only from its release; its own lessons wait in the learning store for the next release |

A person's facts, memories and questions keep going to user context. Serving a person already works against a
frozen release: telling, remembering, recall by search and by id, and answering all passed.

**Status (2026-09-27).** Parked, then resumed the same day. The model freeze work is finished first, then
step two. §9 maps what is left, down to the code.

## 9. Finishing it: S3, S4 and the frozen releases (mapped 2026-09-27, before building)

### 9.1 Environments and their databases

Every database of a model's line is named from its development database, `POSTGRES_DATABASE` (the root). §8's names
gain that root as a prefix: `torinai_model_v1` becomes `torinai_db_model_v1`. The reason is the sandbox. An
experiment sets `POSTGRES_DATABASE=torinai_dev`, so everything it cuts, stages or serves is `torinai_dev_…`, and it
cannot touch the main line's releases or registry. Test runs writing into the main store (09-27) is the failure this
guards against.

| Environment | Database | Holds |
|---|---|---|
| development | `<root>` | everything, as now: the model is taught and learns here |
| releases | `<root>_model_v<N>` | the model's tables, copied at the cut, read-only |
| registry | `<root>_model_registry` | every release: version, database, cut from, when, code identity, commit, checksums, row counts, status, and the history of status changes |
| staging, production | `<root>_<environment>_runtime` | runtime: tasks, queue, the running records |
| | `<root>_<environment>_user_context` | each person's context |
| | `<root>_<environment>_learning` | what the substrate remembers of its own while serving, kept for development |

The six empty world-copy databases are renamed, not dropped:
- `_world_model` becomes `_production_runtime`;
- `_user_context` becomes `_production_user_context`;
- `_world_knowledge` becomes `_production_learning`, trimmed to the tables the learning store holds.

The staging databases are new.

**Settings.**
- `TORINAI_ENVIRONMENT` is development, staging or production. It replaces `TORINAI_COPY`.
- `TORINAI_RELEASE` is the release a staging or production process serves. It is required there and refused in
  development.

### 9.2 Stores, and where each statement goes

The stores become runtime, model and user context: the world model's running store becomes runtime, and world
knowledge becomes the model. Staging and production add a fourth, the learning store. The table still decides:
- the runtime and user-context tables are writable in every environment;
- the model's tables differ by environment.

| Statement on the model's tables | Development | Staging and production |
|---|---|---|
| a read | the one database | the release |
| creating a table, index or column | runs | checked against the release. The object must be there; if it is not, the release and the code do not match, and the statement is refused |
| any other write | runs | refused (`ModelFrozenError`, raised before it reaches the database; the release is also read-only in PostgreSQL) |
| the substrate's own rows of memory, images, the archive log, unanswered questions | the one database | read from the release; written to the learning store |

Where rows go is written at each site; nothing is quietly redirected:
- The places that write the substrate's own rows name the store they write to (`db.write_store(owner)`): the model in
  development, the learning store when frozen.
- Maintenance names the stores it keeps (`db.maintained_stores()`): not the release and not the learning store.
- Table creation names every store a table must exist in (`db.schema_stores()`).

### 9.3 Releases

The release tool, `scripts/release.py`, is backed by `core/database/releases.py`. It has these commands:
- **cut**, from development:
  - it copies the model's tables, and only the substrate's own rows of the per-owner tables. No person's row is
    copied, and the cut is refused if a model row points at one;
  - it sets the new release read-only;
  - it computes a content checksum (every row, with fixed session settings so the text form cannot drift) and a
    schema checksum;
  - it records the code identity: a hash of every `core/**/*.py`, plus the git commit;
  - it registers the release as a candidate.
- **stage N**, **promote N** and **rollback**. At most one release is in staging and one in production. Promoting
  retires the release it replaces, which is kept intact. Rolling back puts the previous one back.
- **verify N**, and **list**.
- **take**: covered in §9.5.

Before serving, a staging or production process checks, and refuses to start if any check fails:
- the release is registered, with the status its environment serves;
- it is read-only;
- its content and schema match their checksums;
- it was cut with the code now running.

### 9.4 Frozen: what production does with each write

Measured writes, from §8:

| Write | Change |
|---|---|
| table creation at start (5 sites) | checked against the release (§9.2) |
| embedding refresh, memory decay, low-importance cleanup, moving memories to the cold tier | run only in `maintained_stores()`. A person's memory is still maintained; the release and the learning store are not |
| access counts when a release memory is recalled | recorded in runtime (`release_memory_usage`), never on the release's rows |
| the substrate's own learning while serving | see below |

**Production does not learn on its own. This refines §8.** "Written into its learning store the normal way" cannot hold
together with "answers only from its release":
- The normal way changes state held inside the running process, not only rows: beliefs held in memory, the
  word-class view, the domain registry.
- Production would then answer from lessons that are not in its release until it restarts.

What production does instead:
- **Refuses at the doors.** In staging and production, the substrate's own learning is refused where it enters, with
  the reason stated:
  - the learning authority, for facts, patterns and word classes;
  - the belief store, for every belief change;
  - the manager, for any write to the model.
  
  A person's context flows to user context as before.
- **Does not start the loops whose only work is learning.** Which loops is found by running production and counting
  the refusals.
- **Keeps what it remembers of its own.** Those memories go to the learning store, with their evidence. Development
  learns from them the normal way (§9.5).

This is the industry pattern:
- production serves a fixed model;
- what it experiences is logged;
- learning happens in development.

### 9.5 Development takes production's memories and usage

`release.py take --from production` runs in development.
- **Memories.** Each memory in the learning store is stored in development through the memory agent, the normal
  path. It carries where it came from, so taking it twice stores it once.
- **Usage.** Recorded usage of release memories is added to those memories' access counts in development, and marked
  as taken.

The next cut then carries them.

### 9.6 S3: a person's context, routed in full

| What | Change |
|---|---|
| the memory of a task done for a person (`_store_task_outcome_meta_memory`, and a failed task's account in `_execute_and_validate_task`) | owned by `task.actor` |
| unanswered questions (`known_unknowns`) | gain an `owner` column. A question raised by a person's words (`_register_domain_gap` → `detect_knowledge_gap`) is theirs, kept in their context. The substrate's research and resolution set holds only its own questions. Loading reads only its own |
| facts a taught meaning binds from the situation (`?speaker`, `?listener`, `?shown`, `?previous`) | the speaker's context. Facts with no situation term ("a robin is a bird") are the model's. The meaning decides this, with no word list |

### 9.7 S4: the readers

| Reader | Change |
|---|---|
| research topics (`_thinnest_knowledge_topics`) | read only the model. A person's facts are in the scoped tables, never in `concepts`. Checked in staging. Production does no research (it cannot learn what it finds). In development, topics can still name the host's details; that is left open |
| task outcomes grouped by field (`_task_outcomes_by_field`), the knowledge-base size, loading unanswered questions | read only the substrate's own rows in development too. After S3, a person's task outcomes and questions carry their owner |
| answering a person | the model plus their own context (verified, SEPARATION-01 F) |
| the release | carries no person's context (§9.3) |

### 9.8 Build order and checks

The build order:
1. The settings and names, the routing and the frozen rules, `releases.py`, `release.py`, and the database renames.
2. The four frozen changes, and the refusals at the doors.
3. S3 and S4.
4. Callers renamed (`world_model`/`world_knowledge` become `runtime`/`model`): directives, intents, the ledger,
   health, the domain master, the coordinator, tools, tests.

The checks:
- **SEPARATION-01**, re-run as staging. The lesson is taught in the development sandbox, cut, staged, and then served
  to two people.
- **RELEASE-01**, new. It covers:
  - the whole release lifecycle, with checksum and code tampering both refused;
  - the frozen behaviours;
  - a production run of serving and idling in which nothing is refused;
  - taking production's memories and usage into development.
- **SHAPES-LEARN-01** re-run, and the test suites touching these modules.

### 9.9 As built (2026-09-27)

Everything in §9.1–§9.7 is built. The build found four more things, each changed:

| Found | Changed |
|---|---|
| Every boot wrote each tool's projection into the model: 344 writes a frozen release refused | A frozen start does not project. The release already holds the projection, cut with the same code |
| The boot's background encoding tried to write vectors for concepts cut before they were encoded | A cut is refused while any concept is unencoded, and a frozen release is never encoded. The development phase of an experiment finishes its encoding before it stops |
| A look-up for a person, and the idle research, would send words out and then have every finding refused | Neither is made where the model is frozen |
| `take` could take a memory twice once development had merged it into a memory it already held (the memory agent's normal duplicate handling) | Each memory and recall count is marked taken in the environment's own store |

**Measured.**

| Run | Result |
|---|---|
| `tests/test_release_environments.py` (settings, names, statement kinds, creation checks, learning-store writes) | 29/29 |
| SHAPES-LEARN-01, development | 35/35 (`20260927T172201Z`, on the final code). The teacher's shoe is in the teacher's context; the model holds only the robin facts |
| RELEASE-01 | 29/29 (`20260927T171154Z`) |
| SEPARATION-01, staging | 33/33 (`20260927T171536Z`) |
| Tests touching the changed modules (48 files, sandbox) | 571 pass. One failure came from this change and is fixed: `test_derived_reading` pinned the old rule that put facts about the teacher's shoe in the model. 33 failures and 3 errors are not from it: 15 failed before this build too (same tests, previous run); the rest name code since removed (`SubstrateLearning`, `core.services.unified_llm`, a `teacher_model` argument, `AnalogyDiscovery._persist_concept`), read beliefs from a store that no longer receives them, send event payloads of the wrong type, pin a frozen code baseline, need a taught store (the sandbox is empty), or are Law 2 replans |

In RELEASE-01, production served release 1 through boot, one person, a memory of its own, a recall, memory
maintenance and 60 s idle:
- nothing was refused, and nothing tried to change the release;
- 56 table-creation statements were checked against the release instead of run;
- afterwards the release was byte-for-byte what was cut.

**Open decisions.**
1. **Production does not learn on its own.** This refines §8's "written the normal way into its learning store". The
   normal way changes what the running process answers from (its beliefs and views, not only rows), so it cannot
   also answer only from its release. What it remembers of its own does wait in the learning store. A separate
   production learner process could learn the normal way without touching what serving answers from. It is not
   built.
2. **Production cannot look a word up for a person.** What it would find could instead go into that person's
   context.
3. **The release holds the projection of the 12 database and monitoring tools a serving environment does not carry.**
   Running one there gives TOOL_NOT_FOUND.
4. **A fact about the situation, from a situation that names no speaker, is not held.** An example is "It is black."
   with only `?previous` bound. A lesson can name `?speaker` in every situation.
5. **In development, research topics can still name the host's details.** They carry no person's context.
6. **Competence from task outcomes now counts only the substrate's own tasks.** Whether it may learn a skill from a
   task done for a person, without their content, belongs to the belief check.
7. **Found, not fixed: every memory-delete path is broken.** `memory_agent.delete_memory`, `permanent_delete` and
   consolidation's clean-up after a merge pass `soft_delete` and `reason` to a storage `delete_memory` that takes
   neither. The memory tables have no soft delete (statuses: raw, processed, archived). What a deleted memory is
   needs deciding first.

## 10. What production learns, and what stays a person's (reasoning, not built)

The frozen build stopped staging and production from learning at all, which cut out one of the substrate's biggest
capabilities: learning from experience. Before production learns again (2026-09-27):
- Learning has to be solid first. In production, beliefs and memories accumulate, but what the substrate takes in as
  learned needs a hard filter.
- "User context is not learned" is too simple, and false:
  - a person's projects and their design are that person's own;
  - the steps the substrate takes to design the project are learned;
  - so are the challenges it met while coding and running experiments;
  - when a person's question needs research, the facts the research finds are learned world knowledge.
- What is built is much simpler than that. Reason out a proper way to separate these things.

### 10.1 What happens today (read in the code)

| Part of an experience | Today |
|---|---|
| A task done for a person: the request, the result, the method used (`tool_plan`), the fix that turned a failure into a success (`causal_rules`) | one memory, all the person's (`_store_task_outcome_meta_memory`). The substrate keeps none of the method or the fix |
| The same task, as what it found and the tools it used (`memory_agent.capture_task_outcome`) | written with no owner, holding the person's request, summary, findings and file names, so it would reach the model. **It never fires.** It reads `summary`, `key_findings` and `tool_results` from a task's result, and no task result in `core/` carries them: a declared-tools job returns `tools_run`. So it stores nothing. The leak is latent, and the substrate keeps no record of what a task found or which tools worked (corrected 09-27, measured by CANARY-01) |
| Each action's before, action and after (`operator_demonstrations`) | the model, in full, with the person's paths and names and no owner. Rules are induced from these |
| Competence in a field from task outcomes | counts only the substrate's own tasks |
| Which strategy works for which kind of task (`meta_learning_strategies`) | runtime. It holds no content, but it is never carried into a release |
| Tasks that failed before (`failed_task_fingerprints`) | runtime, holding the person's request text |
| A person's question it could not answer | theirs, and not researched. Production makes no look-ups at all |
| Research findings (`_research_phrase`) | the model: the first page whose title names the phrase, and its first "X is a Y" sentence, through the learning authority's quality floor. One page, one sentence |
| A fact a person tells it (`_learn_scoped_fact`) | theirs, but promoted into the model when another person holds the same claim, or the substrate already does. That rule was rejected on 09-26 (several people telling the same fact is not how it learns), and is still in the code |
| How far one piece of evidence moves a belief | one lesson from one source took a belief from nothing to 0.997 (LEARNED-WORK-01 A) |

Today one owner takes a whole experience. A person's task goes to them whole, method and fix included. What is not
wired to an owner goes to the model whole, the person's paths included. Nothing is split.

Learning from work also barely happens. LEARNED-WORK-01 (09-26) found that after the work:
- competence stayed at 0.5 and no rule was induced;
- nothing was learned from 9 searches and 18 pages;
- a second attempt was the same as the first.

### 10.2 The way to separate: split each experience, then gate what is learned

An experience is not given to one owner. It is split into parts, and each part is decided by two questions.

**1. Whose is it?** This is decided by where the part came from, not by who was there.
- **The person's:** whatever came from them or is about them. That covers their words, files, data, project,
  designs and methods, facts about them, and the fact that they asked or did something.
- **The substrate's experience:** what it did and what the world answered.
  - What it did: its steps, the errors it met and how it got past them.
  - What the world answered: the sources it read, and what running things returned.

**2. Is it learned yet?** This is decided by evidence, at a gate. The substrate's experience becomes learned
knowledge only when both of these hold.
- **Nothing of the person is left in it.**
  - A lesson is written only in terms the substrate already held or found in the world. Any term whose only source
    is the person's material makes the lesson theirs.
  - The method is lifted out of the project the way rule induction lifts a rule from its examples: the person's
    particulars become variables, and only what the outcome depended on stays.
  - Two different instances are what show which parts are general. It is the same comparison that found a frame and
    its slots between two sentences in SHAPES-LEARN-02.
- **It has the evidence its kind needs.**
  - *A fact about the world:* sources independent of the person that agree, with nothing contradicting them. Never
    the person's word, and never several people's.
  - *A method, or a fix:* an outcome checked by something other than the substrate's own report, such as tests or a
    validated result. The same method must also work again on a different task. One success makes a candidate.
  - *A challenge:* the error it met and what made it go away, lifted the same way.

Below the gate, experience accumulates: memories, candidate lessons and their beliefs, each with its evidence. The
substrate may try a candidate method, carrying its uncertainty. It does not state a candidate as known, and a
candidate is not released.

**The cases, through it:**

| Experience | The person's | Learned, once through the gate |
|---|---|---|
| Designing a person's project | the project, its design, their requirements | the steps taken to design it, lifted from the project |
| Coding and experiments for them | their code, data and results | the errors met and what fixed them; which approach worked |
| A question that needed research | the question, and that they asked it | the facts the research found, once the sources pass |
| A fact they tell it | the fact, as their claim | nothing, until the substrate finds it in the world itself |

### 10.3 What it rests on

- **Explanation-based generalization** (Mitchell, Keller & Kedar-Cabelli, *Machine Learning* 1, 1986) and **Soar's
  chunking** (Laird, Rosenbloom & Newell, *Machine Learning* 1, 1986). A lesson from a solved problem keeps only what
  the solution depended on, and the problem's particulars drop away. This is how the steps come apart from the
  project.
- **Complementary learning systems** (McClelland, McNaughton & O'Reilly, *Psychological Review* 102, 1995).
  Experiences are stored quickly and whole, and general knowledge is drawn from them slowly. This is the
  accumulate-then-gate split.
- **Contextual integrity** (Nissenbaum, *Washington Law Review* 79, 2004). Information keeps to the norms of the
  context it was shared in. The person's material never leaves their context; only what is no longer theirs does.
- **Agent Workflow Memory** (Wang, Mao, Fried & Neubig, 2024). Agents build reusable workflows from past tasks by
  replacing each task's specific values with variables. Current agent research separates the steps from the task
  the same way.
- **Extracting training data from large language models** (Carlini et al., USENIX Security 2021). A model trained
  on people's data can give it back word for word. This is why the "nothing of the person left" test is strict.

### 10.4 What it changes (to be mapped to the code before building)

- **A task's memory splits.** The episode stays the person's. Candidate lessons (the method, the fixes, the
  challenges) are lifted into the substrate's experience with their evidence.
- **Demonstrations.** The ground records are the person's. Only the induced rules, already in lifted form, are the
  substrate's.
- **Competence from outcomes.** Every checked task counts, without its content.
- **Strategy counts.** They are learned knowledge, so they belong to the model and travel with a release.
- **A person's question.** The question is theirs. The gap it shows in the substrate's knowledge of the world is the
  substrate's, and is researched.
- **Research.** The gate for world facts replaces one page, one sentence.
- **Told facts.** Promotion because another person agrees is removed.
- **Beliefs.** The gate is belief admission: how far each kind of evidence moves a belief. This is where §6's belief
  check lands.
- **Production learning** (a working copy of the release that production learns into) is built after this, on top
  of it.

Checks to build with it:
- LEARNED-WORK-01 re-run. After the work, competence moves, a rule is induced, the research is learned, and a second
  attempt goes differently.
- SEPARATION-01 extended. No term of a person's material appears in anything the substrate learned from their
  tasks.

### 10.5 Open decisions

1. **The bar for a fact about the world.** Proposed: at least two independent sources that agree and none that
   contradicts. How reliable a source is gets learned too.
2. **When a method or fix is learned.** Proposed: after it works again on a different task. One checked success is a
   candidate.
3. **Whether production may try a candidate method before it passes.** Proposed: yes, without stating it as known.
   That is how the evidence is gathered.
4. **A method the person brought** (their design, their algorithm) stays theirs, even when the substrate carried it
   out. Proposed: yes.
5. **Deleting a person's material.** Lessons lose the evidence their tasks gave, and may fall back below the gate.
   Proposed: yes.
6. **A person confirming their task was done** is evidence about that outcome, never about a fact of the world.
   Proposed: yes.
7. **Research for a person sends their words out.**
   - Proposed: send only terms that pass the same "nothing of the person" test, and nothing at all from an
     air-gapped deployment.
   - A term the substrate cannot place (a public word, or a private project name) is looked up only with the
     person's consent.
   - §5's rule "research topics never carry a person's context" still stands.

### 10.6 The pool and the memory agent

Everything goes to memory (2026-09-27). So the memory agent is made substantially more intelligent, and a pool is
added that it pulls from and filters, to meet the standards it holds, plus this logic.

**Why it fits.** Everything the substrate learns ends in memory. Today six writers each decide on their own whose a
part is and whether the substrate keeps it:
- the coordinator (a person's task outcome);
- the memory agent (`capture_task_outcome`);
- the demonstration store;
- the learning authority (told facts and their promotion);
- research;
- the meta-learner.

That is the duplicate-authority pattern, applied to the question "whose is this, and does the substrate take it in".
One pool that every experience enters, judged by one agent, puts the decision in one place.

**What the memory agent does today (read 09-27).**
- **Worth keeping** is judged by counting keywords and words in the content and reading its tags
  (`_generate_worthiness_metadata`, `memory_filter`). Novelty is never checked: `is_novel=False`, "would require
  memory lookup". With no metadata, or on a filter error, it stores anyway.
- **Whose a memory is** is whatever the caller passes.
- **A finished task is already split in two** (`capture_task_outcome`): what it found and the tools it used. Both are
  written with no owner, with the person's content in them (§10.1). It reads fields no task result carries, so
  today it stores nothing.
- **Duplicates** are merged by similarity. Maintenance decays, cleans up and moves memories to the cold tier.

**The design.**
1. **Every experience enters the pool whole, with the origin of each part.**
   - A task brings the request, each step, each tool run and its output, errors, fixes, the result and the checks.
   - A research episode brings the question, what was searched, and each source with what it said.
   - Each part is labelled with where it came from: the person (their words, files and data), the world (a source,
     or a tool's output) or the substrate (its own steps).
2. **The person's episode is theirs at once.** It is stored in their context when it happens, so serving them never
   waits on the pool.
3. **The memory agent pulls each item and decides what the substrate may take from it.**
   - *Its standards:* worth keeping, already held (merged with what is held), and new against what memory holds.
   - *The split:* the person's parts stay theirs.
   - *The lift:* the person's particulars become variables. They are found by their origin, and by comparing with
     earlier experiences of the same shape (`rule_induction.anti_unify`).
   - *The residue test:* nothing of the person is left.
   - *A recorded decision on the item:* what went where, and why.
4. **What survives goes to the learning authority, the one learning path, as a candidate with its evidence.** The
   belief system judges whether the evidence is enough. The memory agent asks it and keeps no second judge, so the
   rule of 09-01 stands: the memory agent owns no reasoning layer. Below the gate an item stays a candidate; above
   it, it is learned.
5. **The pool is durable and shared by instances.**
   - It lives in the database, per owner like memory: a person's items in their context, the substrate's in its own
     store.
   - Each item is claimed with a lease, as the task queue does, so two instances never split one experience twice.
   - An added item wakes the memory agent.

**What "more intelligent" needs.**
- **Structured experiences.** The executor, research, conversation and perception must hand experiences over as
  structure, with each part's origin. Today they hand over prose and loose dictionaries.
- **Judgment from memory.** Novelty and relatedness come from memory itself, not from keyword counts.
- **Lifting and the residue test,** from provenance and anti-unification.
- **Reading.** Turning a research page or an error message into a lesson is reading, so this grows with the language
  plan.
- **No storing without a decision.** The paths that store when the filter fails are removed.

**Checks.**
- **Canary test.** This is the method of Carlini et al., *The Secret Sharer* (USENIX Security 2019). Plant unique
  marker strings in a person's requests and files, run their tasks, and search every table outside their context
  for them. None may appear.
- **Transfer.** A method learned from person A's task helps a different task for person B, and B can recall nothing
  of A's.
- **LEARNED-WORK-01.** The substrate is measurably different after doing the work.

**The one writer.** The memory agent is the only one that writes memories. How every
writer is routed to it, and the build order, are in `MEMORY_AGENT_MAP.md`.

**Added decision.**
8. **Turning off learning from tasks.** Can a deployment, or a person, turn it off? Classified work may need to.
   Proposed: yes, per deployment. The person's episode is still kept as theirs.
