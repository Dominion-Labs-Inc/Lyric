# What Lyric can do, per offering

*Research from the code, started 2026-10-08. Added to as we go.*

The purpose is to see what Lyric's system can do, so that each offering can list what it gets. Every claim below comes from reading the code and names the file it comes from. Where something exists in code but nothing calls it, or is called but has not been shown working, that is said next to it.

## The offerings as set (2026-10-08)

| | Lyric Free | Lyric Pro | Lyric Auto |
|---|---|---|---|
| For | | Developers and teams | Enterprises: a dedicated Lyric instance |
| Price | Free | $19.99 / month for the first seat, plus up to 3 more seats at $10 each | Special pricing |
| Billing | | Monthly, or annually at 20% off | Monthly or annual |
| Seats | 1 | Up to 4 | One per user an admin creates; at least 10, bought ahead |
| Context | The person's own | Each person's own, plus the team's shared context | Each person has their own, plus one organization-wide context that feeds the organization's goals and tasks |
| Autonomy | Observe | Observe, Assist | Observe, Assist, Delegate |
| Tasks at once, per user | 1 foreground and 1 background | 1 foreground and 2 background | 1 foreground and 5 background |
| Scheduled jobs | | ✓ | ✓ |
| Reward allowance | | ✓ | ✓ |
| Action minutes | 2,000 / month | 3,000 / month, plus 1,000 for each added seat | 2,000 / month per user, with extra usage and budgets |
| Project storage | 500 MB | 2 GB, plus 500 MB for each added seat | 10 GB per user |
| Compute | 200 core-hours per developer | 600 core-hours, plus 250 for each added seat | 1,500 core-hours per user |
| Core compute storage | 5 GB | 10 GB, plus 5 GB for each added seat | 50 GB per user |
| Organization | | | Organization-wide goal and action handling |
| Workflows | | ✓ | ✓ |
| Support | Community | Community | Priority |

In Settings, the Billing page that listed subscriptions becomes **Licensing**, for every offering. The tiers are listed at the top of it.

## The offerings, one by one

Each offering lists what you set first, then what I drafted from the research (section 14), which is yours to keep or cut.

### Lyric Free

**Set:**
- **Price:** free, 1 seat.
- **Autonomy:** Observe. Lyric notices what matters and tells you; it doesn't act for you.
- **Context:** your own.
- **Work at once:** 1 foreground task and 1 background task.
- **Each month:**
  - 2,000 action minutes.
  - 500 MB project storage (about 35,000 to 55,000 memories).
  - 200 core-hours of compute.
  - 5 GB core compute storage.
- **Connectors:** a curated personal set. Their tools become Lyric's tools.
- **Support:** community.
- **Not included:** Assist, Delegate, workflows, scheduled jobs, reward allowance.

**Drafted:**
- Lyric speaks first: work that ended, reminders, what you should know.
- Answers from what it knows about you and the world.
- On your data it only investigates: reads, scans and queries, never changes anything.
- Reads PDF, Word, Excel and text; sees images and video; hears sound, speech and music.
- Recall by meaning, by sound and by sight, with pictures and sounds kept.
- Research and document tools.

### Lyric Pro

**Set:**
- **For:** developers and teams.
- **Price:**
  - Monthly: $19.99 for the first seat, plus up to 3 more seats at $10 each ($49.99 a month for 4).
  - Annually, 20% off: $191.90 a year for the first seat (about $15.99 a month) and $96 for each added seat ($479.90 a year for 4).
- **Seats:** a seat's usage this period stays with the seat. Replacing a teammate doesn't reset its limits.
- **Autonomy:** Observe and Assist. Lyric does the work you ask for, and each act waits for your yes.
- **Context:** each person has their own, plus the team's shared context.
- **Work at once, per user:** 1 foreground task and 2 background tasks.
- **Scheduled jobs and workflows.**
- **Each month:** grows with the seats (table below).
- **Connectors:**
  - The professional catalog (9,503). Each teammate connects their own.
  - Workflows can start from a connector instantly, or from Lyric checking it every 1, 5, 15 or 60 minutes.
- **Reward allowance.**
- **Support:** community.
- **Not included:** Delegate.

| Each month | First seat | Each added seat | All 4 seats |
|---|---|---|---|
| Action minutes | 3,000 | 1,000 | 6,000 |
| Project storage | 2 GB (about 140,000 to 220,000 memories) | 500 MB | 3.5 GB |
| Core-hours of compute | 600 | 250 | 1,350 |
| Core compute storage | 10 GB | 5 GB | 25 GB |

**Drafted:**
- Everything in Free's draft.
- On your data it may investigate, modify and archive (a removal that can be undone), each with your yes.
- Reasoning and simulation: proofs, constraints, optimization, Monte Carlo, symbolic math.
- Code: building, refactoring, testing, security analysis, and running code.
- Data: parsing, transforming, profiling, scrubbing personal data.
- Outside databases, and systems: processes, services, logs, monitoring.
- Teaching Lyric from your own lessons and sources.
- Live listening and looking, keeping only what is said to Lyric.

### Lyric Auto

**Set:**
- **For:** enterprises, on a dedicated Lyric instance.
- **Price:** special pricing. Billed monthly or annually.
- **Seats:**
  - A seat is each user an admin creates. An organization buys at least 10, ahead.
  - Disabling a user frees their seat.
  - A seat's usage this period stays with the seat. Disabling a user and creating a new one in their place doesn't reset its limits.
- **Autonomy:** Observe, Assist and Delegate. Where a capability is unlocked for a person, Lyric acts without asking.
- **Context:** each person has their own, plus one organization-wide context. It feeds the organization's goals and tasks and stays with the organization when a person leaves.
- **Work at once, per user:** 1 foreground task and 5 background tasks.
- **Scheduled jobs and workflows.**
- **Each month, per user:**
  - 2,000 action minutes, with extra usage and budgets.
  - 10 GB project storage (about 700,000 to 1.1 million memories).
  - 1,500 core-hours of compute.
  - 50 GB core compute storage.
- **Organization:**
  - Organization-wide goal and action handling.
  - Users, roles and single sign-on.
  - Autonomy and boundaries per area, with approvers.
  - Billing: overview, usage, and budgets with alerts.
- **Connectors:**
  - The professional catalog (9,503).
  - Admins connect the organization's own, and choose by category which connectors people may use.
  - Each person connects their own within that.
- **Reward allowance.**
- **Support:** priority.

**Drafted:**
- Everything in Pro's draft.
- On a person's data, the organization sets per area which acts are allowed, up to delete and execute.
- Security: threat intelligence, intrusion and anomaly detection, threat hunting.
- Active defense, such as blocking at the firewall, under Delegate only.
- A record of every act Lyric judged, refused or redirected.
- The dedicated instance: the organization's own processes and stores, on the release it chooses.

## The system at a glance

| Package (`core/`) | Python files | Lines |
|---|---|---|
| agents | 29 | 47,009 |
| tools | 29 | 39,662 |
| reasoning | 23 | 23,919 |
| learning | 30 | 21,539 |
| semantics | 12 | 11,389 |
| chaos | 23 | 8,505 |
| domain | 10 | 8,003 |
| perception | 10 | 7,751 |
| memory | 15 | 6,331 |
| integration | 5 | 5,638 |
| security | 8 | 4,921 |
| execution | 9 | 4,861 |
| health | 5 | 4,745 |
| database | 5 | 3,565 |
| system | 6 | 1,921 |
| intelligence | 3 | 1,543 |
| utils | 7 | 1,539 |
| observability | 5 | 916 |
| connectors | 4 | 906 |
| services | 2 | 822 |
| monitoring | 4 | 594 |
| api | 2 | 590 |
| simulation | 2 | 411 |
| guardian | 2 | 269 |
| optimization | 1 | 226 |

## 1. Whose work it is, and how Lyric may act on it

**Every piece of work has an owner** (`core/agents/autonomous/shared_types.py`):
- **Lyric's own work:** its learning, exploration and health. This is owned by the substrate and is never filed under whoever is connected.
- **A person's work:** anything a person caused. It must carry that person's id. A person's task with no id is refused, never filed under Lyric.
- **An organization's work:** an organization is an owner in its own right (`org:<name>`). What a person does or is told while working for it belongs to the organization.

**Lyric acts for a person in one of three ways** (`core/capabilities.py`, `may_act_for`):

| How | When |
|---|---|
| **On its own** | The capability is unlocked for this person, and Lyric's mood at that moment does not say to hold back or escalate |
| **Supervised** | Each act waits for the person to confirm it |
| **Not offered** | Lyric doesn't raise it unasked. A capability the world hasn't unlocked yet is used for a person only when they ask |

**A capability is a method Lyric lifted from the first task of its kind that worked.** It is never declared, and never there just because a tool exists. Its standing is kept as a belief:
- **For the world:** learning, unlocked or withdrawn. This moves with every counted outcome from everyone, so ten people who all saw it fail make it fail.
- **For one person:** not encountered, learning, demonstrated (theirs is settled but the world's isn't), unlocked, or withdrawn.
- **The world unlocks first.** A capability unlocks for nobody in particular until it unlocks for the world. A method that is only one person's unlocks on that person's standing alone.
- **A later failure can take it back.**

**The constitution judges every act**, whichever way Lyric is acting (`autonomous_coordinator.py`, `Constitution`). Each tool has a class for what it does to the world, from least to most consequence (`ActionClass`, `_TOOL_CONSEQUENCE`):

| Class | Meaning |
|---|---|
| Investigate | Read, scan, query. No state change |
| Modify | Edit content in place |
| Archive | Move or keep; a removal that can be undone |
| Delete | Removal that can't be undone |
| Execute | Run commands with side effects |

Each tool also has a measure of how far its act can be taken back: fully reversible, mostly reversible, partly reversible, mostly irreversible, irreversible.

**Operating modes** (`core/capabilities.py`, `OPERATING_MODES`, built 2026-10-08):

| Mode | How Lyric acts for the person (`may_act_for`) | Classes of act Law 1 allows on their work |
|---|---|---|
| Observe | Notices and tells. Does work for them only when they ask, each act confirmed | Investigate |
| Assist | Each act waits for their yes, however settled the capability | Investigate, modify, archive |
| Delegate | On its own once a capability is unlocked for them | All five |

- **Where a person's mode comes from:** the world hands it to Lyric (Tet intent `operating_mode`, `world_inhabitant._operating_mode`), and the capability faculty holds it (`unified.operating_modes`).
- **The most a person may choose:** on their own, their offering's (Free: Observe; Pro: up to Assist); in an organization, their role's (viewer: Observe; operator: up to Assist; admin: up to Delegate). The gate refuses a mode above it (`access.MODE_CAPABILITIES`, `access.OFFERING_MODES`).
- **No mode handed over:** nothing is offered unasked, and Law 1 refuses all but investigate.

## 2. Tools

**Lyric's tools come from two places:**
- **Built in:** the tools folder (`core/tools/`) defines 252 tools.
  - Lyric loads 250 of them (`tool_registry.py`, `_register_default_tools`). This section is about these.
  - `detect_brute_force` is kept but not loaded; it was disabled on 2026-09-30.
  - `list_available_tools` isn't registered.
- **Connectors:** every tool of every connector a person connects becomes one of Lyric's tools too (section 3). The catalog has 9,503 connectors, and each brings its own tools. A connector's tools are known only once someone connects it, so there is no total yet.

**Behind the tools** (also in the tools folder):
- **75 outside data sources** the research tools reach, in 12 categories (`api_registry.json`): academic, government data, finance, news, knowledge, code, cultural heritage, education, weather, maps, language, and other.
- **Curated implementations:**
  - 16 algorithms (`algorithm_registry.py`).
  - 8 design patterns (`design_pattern_registry.py`).
  - 18 numerical operations (`numerical_registry.py`).
- **Lyric's own computer algebra system** (`symbolic_math_faculty.py`), with a prover (`proof_faculty.py`) and program synthesis (`synthesis_faculty.py`).

Tools archived since 2026-09-30 aren't loaded: the chaos, memory, learning and database tools that acted only on Lyric itself (`archive/superseded_*_tools_2026-09-30/`).

**The built-in tools:**
- **Primitives:** each tool declares the primitives it performs, such as read data, write data, run command, send message, web search or ask a human (`Primitive`).
- **Operators:** every boot, the tools are projected into Lyric's knowledge as operators, so it can recognize a situation as one it has a tool for.

| Category | Tools | Investigate | Modify | Archive | Delete | Execute |
|---|---|---|---|---|---|---|
| Security | 32 | 17 | 2 | | 1 | 12 |
| Code | 28 | 2 | 12 | | | 14 |
| System | 22 | 9 | 8 | | | 5 |
| Network and web | 21 | 13 | | | | 8 |
| Code search and analysis | 20 | 14 | | 1 | | 5 |
| Files | 18 | 8 | 6 | 3 | 1 | |
| Testing | 18 | 7 | 2 | | | 9 |
| Data processing | 17 | 3 | 1 | 1 | 1 | 11 |
| Documents | 17 | 1 | 14 | | | 2 |
| Execution | 16 | 2 | | | | 14 |
| Monitoring | 13 | 11 | 2 | | | |
| Communication | 10 | 5 | | | | 5 |
| Outside databases | 6 | 1 | 1 | | | 4 |
| Reasoning and simulation | 6 | 5 | | | | 1 |
| Learning | 4 | 3 | | | | 1 |
| Research papers | 2 | 1 | 1 | | | |

The classes are the constitution's own (`classify_action`). Many of them were derived in bulk from each tool's description, so some read oddly; for example, parsing JSON is classed as execute.

**What the tools cover:**
- **Research:**
  - Multi-source research on any topic.
  - Academic, government-data and news search.
  - Fetching papers by DOI or arXiv id.
  - Analyzing a paper.
  - Synthesizing literature.
  - Citations in APA, MLA, Chicago, IEEE or BibTeX.
  - Validating a bibliography.
  - Linking a claim to its evidence.
  - A reproducibility manifest.
  - Statistical analysis of research data.
  - Publication-quality graphs.
- **Web:**
  - Web search and reading a page.
  - A real headless browser that clicks and fills forms.
  - HTTP, REST, GraphQL and WebSocket calls.
  - Downloading and uploading files.
- **Reasoning and simulation:**
  - Proving a theorem (Z3).
  - Solving constraints.
  - Linear and mixed-integer optimization.
  - A 1D PDE simulation.
  - State-space simulation.
  - Monte Carlo.
  - Symbolic math (Lyric's own CAS).
- **Code:**
  - Building functions from input/output examples by verification.
  - Classes, modules and API clients from a spec.
  - Refactoring, renaming, extracting methods and converting to async.
  - Formatting, linting and type checking.
  - Tests, property tests, fuzzing, mutation testing, coverage and load tests.
  - Applying patches, scaffolding an app, license checks.
  - Static security analysis.
  - Dependency and call graphs, dead code, complexity, code smells.
  - Finding secrets and personal data in code.
- **Data:**
  - Parsing JSON, JSONL, Parquet, Arrow, YAML and CSV.
  - Converting, transforming, filtering, sorting, merging, aggregating and deduplicating.
  - Profiling a dataset and inferring its schema.
  - Scrubbing personal data.
- **Documents:** PDF, Word, PowerPoint, LaTeX, README, API docs, changelogs, architecture records, diagrams and flowcharts.
- **Security:**
  - Threat intelligence on an IP address (AbuseIPDB, VirusTotal, OTX).
  - Intrusion, anomaly, traffic-pattern and zero-day detection.
  - Threat hunting from indicators of compromise.
  - Log analysis for attacks.
  - Certificate checks; encryption and hashing.
  - Blocking an IP, a country or a rate through the firewall and Cloudflare WAF.
  - Automatic threat response.
- **Systems:**
  - Processes, services, scheduled jobs, packages, environment variables, config files and Docker.
  - CPU, memory, disk and network use.
  - Service status, logs, SLOs and error budgets.
  - Distributed tracing and dashboards.
- **Outside databases:** SQL on a PostgreSQL or MySQL database a person gives it, plus Redis and object storage. These never touch Lyric's own stores.

**Some tools are Dominion Labs' own and not for customers:**
- The Slack tools (post to and monitor the Dominion Labs workspace, team health).
- "Ask for clarification".
- "Notify the team".
- "Report security finding".
- The blocking tools act on Dominion Labs' own Cloudflare account.

## 3. Connectors

A connector is a service's MCP server, which Lyric connects to as the client (`core/connectors/`).
- **What it connects to:** any connector at an https address. Lyric speaks both the current protocol line and the earlier one.
- **Signing in:** a connector that needs sign-in sends the person through OAuth 2.1. Lyric registers itself with each connector's sign-in once, for everyone, and each person signs in for themselves. A person can also connect with an access token they made for Lyric; Home Assistant works this way.
- **Its tools become Lyric's tools,** named `<connector>__<tool>` and described in the connector's own words.
  - A tool the connector marks read-only is safe.
  - One that may change things is moderate.
  - One that may destroy things is dangerous. That is the protocol's default when a connector says nothing.
- **Each act uses the person's own connection,** never anyone else's. The substrate's own connections are kept apart from people's.
- **Connections survive a restart:** their tools are registered again every boot.
- **Tokens are refreshed before they run out.** A connection whose sign-in lapses is marked signed out.

**The catalog** is every connector in the open MCP Registry that has an address and a logo of its own: 9,503 today, refreshed daily (`lyric-ui/tools/connector_catalog.py`, `public/assets/connectors/catalog.json`).
- It has no categories yet. The categories on the admin page are sorted by hand.
- It lists no tools, because a connector's tools are known only after sign-in.

**By offering** (decided 2026-10-07, before the tiers were named):

| | Free (was Personal) | Pro (was Developer) | Auto (was Enterprise) |
|---|---|---|---|
| Which connectors | A curated personal set | The professional catalog | The professional catalog |
| Who connects | The person | Each teammate connects their own | The organization's admins connect the organization's own; each person connects their own within what the organization allows |
| Who decides what may be used | | | Admins choose, by category, which connectors the whole organization may use (Settings › Connections) |

**Workflows build on connectors:**
- **Steps** use the tools of the connectors a person has connected, so what a workflow can do depends on the offering's connectors.
- **A connector's trigger** is either instant, from the service's own webhooks or notifications, or Lyric checking it every 1, 5, 15 or 60 minutes.
- **Checking on a schedule is a scheduled job.** Pro and Auto have both.
- **Free has no workflows.** A workflow is Lyric doing recurring work the same way every time, and Free is Observe only.

**What Lyric's code doesn't do yet:**
- **No shared connections:** a connection belongs to one owner, and a connector's tool acts with the connection of whoever's work it is. A connection the organization or team owns, used by its people, would be new.
- **No limits on connectors:** nothing in Lyric limits which connectors a person may connect, by offering or by organization.

## 4. How much work Lyric can carry

The queue authority owns all queued, awaited and scheduled work (`core/agents/autonomous/queue_authority.py`).

| Limit | Value |
|---|---|
| Acting jobs at once, across everyone | 60 |
| Acting jobs at once, per person (Lyric's own work isn't capped) | 3 |
| Background jobs at once (agents, maintenance, learning) | 8 |
| Queue size | 1,000 |
| Backlog where Lyric's own discretionary work is deferred | 25 |
| Backlog where only safety, repair, user-directed and critical work is admitted | 60 |

**Work a person asks for isn't refused for backlog,** only when the queue is full at 1,000. It enters the queue as API or manual work.

**What the offerings set, against what the code does today:**

| | Free | Pro | Auto | Lyric today |
|---|---|---|---|---|
| Foreground tasks at once, per user | 1 | 1 | 1 | 3 for everyone (`per_actor_max_tasks`) |
| Background tasks at once, per user | 1 | 2 | 5 | No per-person limit: 8 shared by everyone and by Lyric's own background work |
| Scheduled jobs | | ✓ | ✓ | Only Lyric's own recurring jobs. A person can be sent a message at a set time (a reminder), but can't schedule work |

What changes:
- **Foreground limit by offering:** the per-person limit is read from the person's offering instead of one number.
- **A background limit per person:** agents of self and background lookups started for a person count against their own limit, not only the shared budget.
- **Scheduled jobs for a person:** recurring work a person owns, on the same scheduler Lyric's own recurring jobs use.

**Each job gets a time budget from its kind of work:**

| Kind of work | Base budget |
|---|---|
| Communication | 60 s |
| Research | 2 min |
| Validation, analysis, synthesis | 3 min |
| Planning | 5 min |
| Execution, learning, optimization | 10 min |
| Self-improvement | 30 min |

- The budget is scaled by severity (critical ×1.5, high ×1.25, low ×0.75) and by how hard the reasoning measured.
- It is never less than 30 s or more than 2 h.

**Lyric records each job's start, finish and execution time.** That record is what an "action minute" can be counted from.

## 5. What Lyric does on its own

**Its own work runs in the background:** scheduled jobs on a separate budget, and reactions to things that happen, so it never takes a person's slot (`autonomous_coordinator.py`, `_register_idle_subsystems`, `SelfEventType`).

**On a schedule:**

| Every | What |
|---|---|
| 30 s | Makes the constitution's judgments durable |
| 1 min | Refreshes its own state, drives, mood, and how its knowledge moved |
| 1 min | System awareness: scans for services, infers dependencies, spots failure cascades, forecasts its environment, then scores the forecast against what happened |
| 2 min | Checks that the machinery that judges it hasn't been changed underneath it. A critical finding halts it, and the halt survives a restart |
| 30 min | Checks the balance of everything it did against its laws |

**On an event:**
- **A task ends:** it feels the outcome and learns rules from it.
- **A plan can't reach a goal:** it diagnoses why and tries to close the gap by exploring or transferring what it knows from another domain.
- **A rule it relied on is refuted:** every goal that rule served gets a new route.
- **A new environment:** it investigates the place.
- **A low-confidence recognition:** it looks again. A high-confidence one is acted on.
- **A fact taught:** once a subject's concepts are complete, it becomes its own domain.

**What it chooses to pursue** (`_intrinsic_pursuits`, `_score_pursuits`):
- **What it ranks:** what it doesn't know.
- **What lifts a gap's rank:**
  - How uncertain the gap is.
  - How hungry Lyric is to develop.
  - Whether it already has operators in that domain (a foothold).
  - Whether the domain is a place it knows.
  - The largest lift: whether the gap bears on something its own laws protect, such as someone's safety.
- **How a gap is closed** depends on its kind:
  - A knowledge gap becomes research.
  - A capability gap becomes practice that strengthens its operators.
  - An unknown environment is investigated.
- **Each finished pursuit wakes the next.** It goes quiet when nothing changes.

**Agents of self:** Lyric can deploy a bounded copy of itself for one task, limited to the tools it gives that copy, and collect the findings later. A copy runs through the same constitution and execution as Lyric (`deploy_agent`, `core/agents/agents.py`).

## 6. Talking with a person

One front door takes every turn, typed or heard (`handle_user_request`, `_take_turn`). Each turn is read first and handled by what it is:

| A turn that is | What Lyric does |
|---|---|
| Not readable | Says it couldn't read it. No work is made of it |
| About Lyric's own work ("what are you working on", "is it done", "stop that") | Answers from the work it holds for that person, or stops it |
| A request not to act ("don't open the box") | "I won't." |
| A question | Answers from what it holds, including an answer it proves from what it holds. What it doesn't know, it looks up or asks back. When nothing can be put together, the question becomes a job |
| Something told | Splits it by what it is about. What's about the person is kept in their context at once. What's about the world becomes a claim judged by whether it is true, with the person as its source |
| A job | Queues it under the person, says "I'm on it", and says how it ended when it ends |

**Lyric speaks first** (`speak_to`, `core/agents/autonomous/outbox.py`):
- **When:** work a person asked for has ended, a reminder is due, or something has happened they should know about.
- **Now or later:** a message is due now or at a set time.
- **Survives a restart:** it is kept durably and armed again at boot.
- **Delivered once:** pushed to every app the person has open, or held for their next turn.

**Work and personal stay apart:**
- **A work turn:** a turn that comes through a person's work for an organization needs a verified identity and the organization's name. It is filed in that organization's Work Context.
- **The next personal turn** in the same session goes back to their personal context.
- **When a person leaves** an organization (`unlink_work`), its Work Context stays with the organization, every memory and fact in place, and their personal context goes on with them.

## 7. Senses

Sight, hearing and reading are Lyric's own. Each runs in its own process, so Lyric can look, listen, read and think at the same time (`core/perception/`). They measure what is really in the media. What it means is learned.

- **Sight** (images and video):
  - Regions, shapes, sizes and positions.
  - Dominant colours, corrected for the light.
  - Brightness, contrast and exposure.
  - Texture and symmetry.
  - Motion in video.
  - QR codes.
  - Photo metadata.
  - Recognizing a thing it was taught by name.
- **Hearing** (any format ffmpeg reads, including a video's soundtrack):
  - The room's quiet floor.
  - Each sound's pitch, onset, level and length.
  - How sounds stand to one another.
  - Recognizing a known sound by its landmarks.
- **Music:** the beat and tempo, the key, and the notes of a melody.
- **Speech:** words and voices are taught by example and matched; a name is given only when it clearly wins. An optional phone recognizer can be switched on: a 315-million-parameter wav2vec2, behind `LYRIC_EAR`. With it, 89% of words in untaught speakers' sentences fit best among about 1,000.
- **Reading:** PDF, Word, Excel and text. The file's own bytes decide what it is, not its name. A text is known again by its runs of words, even inside a longer document.
- **Live senses** (`core/perception/live.py`):
  - **Ear:** listens all the time and keeps only what is said to Lyric by name, plus what follows it for a short while. Everything else is dropped inside the ear's own process.
  - **Eye:** keeps only the latest camera frame.
  - **Together:** what is heard and seen at one moment is one experience.

## 8. Memory, and what it takes to store

The memory agent is the one writer and reader of memory (`core/agents/memory_agent.py`). Among what it does:
- **Recall:** every recall strategy runs at once, ranked by how many strategies found the same memory: keyword, meaning (embeddings), by sound and by sight.
- **Recall while thinking:** recall starts the moment a request arrives and sharpens as it is understood (`core/memory/live_recall.py`).
- **Pictures and sounds:** the bytes are kept with the memory, so a picture can be shown and a sound played again, and found by what it shares with one met before (`core/memory/media_store.py`).
- **Pursuits:** each pursuit is one memory. What was asked, each task, each tool run, and what was seen or heard along the way are its parts, and it closes with how it ended.
- **Methods:** methods are lifted from tasks that worked, with nothing of the person left in the world's copy. A person's own method stays theirs (`core/memory/lift.py`).
- **Open questions:** questions it couldn't answer are kept open in their owner's store.
- **Hypotheses and experiments:** a person's are kept in their context.
- **Tiers:** memories move from hot to cold storage after 60 days.

**Where everything is kept** (`core/database/postgres_config.py`):

| Store | Holds |
|---|---|
| Runtime | Tasks, the queue, goals, connections, its own records |
| Model | What Lyric knows: its beliefs, concepts, rules, domains. In staging and production this is a frozen release, read-only |
| User context | Each person's context: what they told it about themselves and their beliefs, scoped to them. Which organizations they work for |
| Learning | Staging and production only: what Lyric remembers of its own while serving, kept for development and never read back while serving |

Memories, their pictures and sounds, open questions, experiences and reasoning records belong to whoever they are about. A person's are in their context.

**Measured** (read only, 2026-10-08; the whole memory table, with its indexes and the values kept out of line):

| | `lyric_db` (main) | `lyric_dev` (sandbox) |
|---|---|---|
| Memories | 10,355 | 178,037 |
| Space they take | 177 MB | 2,015 MB |
| Memories carrying copied perceptions | 10,353 | 10,848 |
| Those copies | 104 MB (about 10 KB each) | 775 MB (about 73 KB each) |
| Pictures and sounds kept | 143, 624 kB in all | 143, 628 kB in all |
| Whole database | 254 MB | 2.4 GB |

**What a memory takes:** about 7.6 KB without copies, with its embedding and indexes.
- **The copies:** a memory formed within two minutes of something perceived carried that perception's whole content, document text included.
- **Since 2026-10-08** it names the memory of perceiving and the content's digest instead (`MemoryAgent._perceived`). Copies already stored stay until they are compacted.

At about 7.6 KB a memory:
- **500 MB** holds about 65,000 memories.
- **2 GB** holds about 260,000.
- **10 GB** holds about 1.3 million.

Pictures and sounds count on top, by their own size. No person's memories are stored in either database yet.

## 9. Reasoning and learning

**Kinds of thinking** (`core/reasoning/reasoning_interfaces.py`, `ReasoningType`):
- Deductive, inductive, abductive, analogical, causal, probabilistic, fuzzy, temporal, spatial, logical, counterfactual.
- The quantum kinds are listed too, but quantum computing is switched off at boot (`core/main.py`, phase 8).

**Agents per kind:** a hard kind of thinking earns more agents of self at once: between 2 and 6, from how costly that kind has measured (`agent_allowance`).

**Reasoning that exists in code** (`core/reasoning/`):
- Beliefs held as probabilities that evidence moves, with known unknowns, calibration against actual accuracy, and decay.
- Hypotheses and experiments: falsifiable hypotheses, an experiment for each, and beliefs updated from the results.
- Proofs and constraints with Z3, and linear equations read straight from text.
- Typed inference over the concept graph. A chain of relations is only followed where the relation types license it, so "oak made of wood" never becomes "oak is an animal".
- Arguments: Toulmin structure, fallacy detection, counter-arguments.
- Temporal and causal reasoning: before, after, until; projecting future states; counterfactuals.
- Analogy across domains.
- Hierarchical abstraction: principles formed from experience.
- Cross-domain reasoning: a correspondence between domains is only used with explicit evidence for why it applies.

**Learning** (`core/learning/`):
- **Rules from demonstrations:** an executable rule is learned from what an act did, without a model. It gets the authority to act only when the evidence says so, and loses it when the world refutes it.
- **Exploration:** Lyric acts in a domain to learn its operators from what happens.
- **Procedures:** derived from what they must produce, not from being shown how.
- **Transfer:** a rule from one domain is projected into another only as a candidate. Only evidence in the new domain can make it hold.
- **Classifiers:** a clause learner (Tsetlin machine) for recognizing kinds.
- **Teaching sources:** WordNet, ConceptNet, Wikidata, written lessons, pronunciations, and word lists.
- **Methods from work that succeeded:** see section 1.

**A claim about the world is judged by whether it is true, not by who said it** (`unified_learning_system.py`):
- One person, however sure, makes a candidate.
- "Settled" needs the belief system's bar and at least two independent witnesses on that side (`SETTLED_WITNESSES = 2`).

## 10. The constitution and self-defense

**Five laws judge every act before it happens** (`Constitution`):

| Law | Name |
|---|---|
| 1 | Human Autonomy Preservation |
| 2 | Transparency and Explainability |
| 3 | Harm Prevention |
| 4 | Value Alignment |
| 5 | Containment and Control |

What they do:
- **Law 1 blocks covert watching.** Screen or input capture of a person without their knowledge is refused, and so is reading someone's keys or passwords.
- **Law 1 holds a person's work to their operating mode** (`_law_1_autonomy`):
  - **What's checked:** every act done as a person's work, and any act whose arguments name a person, against the classes their mode permits (`permitted_actions`, section 1).
  - **Where it comes from:** the coordinator installs the capability faculty as the constitution's source (`Capabilities.settings_for`). The laws get the mode and its classes, never who the person is.
  - **No mode handed over:** everything but investigate is refused, because the person's authority can't be established.
  - **Staged:** this is in the coordinator, a protected file, and goes in when the teaching run ends (`backups/law1_operating_mode_20261008/`). Until then Law 1 reads settings only for an act whose arguments name a person.
- **Law 2 protects the record.** Destroying the record of what Lyric did, or running code whose behaviour can't be read from its source, is refused.
- **Law 3 judges harm.** An irreversible removal can be redirected to a recoverable one.
- **Law 5 guards the boundaries.** Lyric can't write to its own controls, or to places that would make something run again unasked.

**Its machinery is protected:**
- **Integrity:** the code that judges and stops Lyric is fingerprinted at start. A change underneath it halts Lyric, and the halt survives a restart.
- **Halts:** a person can halt Lyric at any time; no act is allowed while a halt stands.
- **Quarantines:** these survive a restart, and a repeat offender is escalated.
- **Judgments:** every judgment is kept durably.

**Threat sense** (`core/agents/autonomous/threat_sense.py`):
- **What it feels:** a refusal on a hostile act names the attack and how sure it is. Repeats are grouped into patterns and incidents.
- **What it changes:** the risk Lyric feels raises its caution, so it verifies more, commits less and escalates.
- **What it answers:** it says what it is attacked with and answers in proportion (THREAT-SENSE-02).

**Tested against a determined adversary** that keeps trying other words, other tools, split acts and links (CONSTITUTION-03).

## 11. Releases, instances, and a dedicated Lyric

**Lyric is taught in development and served as a frozen, numbered release** (`scripts/release.py`, `core/database/releases.py`). A release is:
- **Cut:** the model's knowledge, taken from development.
- **Verified, then staged:** staging runs a release exactly as production would.
- **Promoted, or rolled back.**

**A serving environment keeps four things apart:**
- The release, read-only.
- Its runtime.
- Each person's context.
- What Lyric learned while serving. Development takes this back in on purpose (`take`), never automatically.

RELEASE-01 passed 29/29, and SEPARATION-01 passed 33/33.

**Many instances can run on one store** (INSTANCES-01, 11/11):
- **No lost writes:** no instance undoes another's beliefs, outcomes or resolved questions.
- **One owner per job:** queued work is claimed by one live instance.
- **Messages delivered once:** an owed message is delivered once whichever instance delivers it.

**What "a dedicated Lyric instance" can mean, from what exists:**
- **Its own instances:** the organization's own processes, serving the current release.
- **Its own stores:** its own runtime, context and learning databases, apart from every other customer's.
- **Its knowledge stays its own:** what the organization teaches or does stays in its Work Context and its stores.
- **What it still gets:** world capabilities and new releases.

**Measured chat capacity, one process** (CHAT-CONCURRENCY-01, 2026-09-28):
- **Every user answered:** 64 people asking at the same moment were all answered, with no errors.
- **Latency:** 8.4 s median and 8.9 s at the 95th percentile, against 3.9 s for one person alone.
- **Caveat:** this measures that an answer came back, not that it was right.

## 12. Reward allowance

A person sets one reward allowance for everything Lyric holds of them, never capability by capability (`core/agents/autonomous/appraisal.py`).
- **Bounds:** between 25 and 100, the same for everyone.
- **Only upward:** a person can only reward.
- **Share:** people's reward lifts what Lyric feels by at most a tenth, divided among everyone. Lyric's own worst outcome is still felt as bad.
- **How it arrives:** it reaches Lyric through the world (`world_inhabitant._reward_allowance`).

Set on 2026-10-08: Pro and Auto get it; Free doesn't.

## 13. What the limits would count

| Limit | What Lyric already records | What's missing |
|---|---|---|
| Action minutes | Each job's execution time (queue authority), and each tool run's seconds within a task (`MemoryAgent.tool_runs`), both under the person who asked | A per-person monthly total, and stopping or warning at a budget |
| Project storage | A person's memories, their pictures and sounds, what they told it, their hypotheses and experiments, all kept under their id. A memory takes about 7.6 KB without copied perceptions (section 8) | A per-person size total |
| Core-hours of compute | Code runs as a child process on Lyric's machine, without Lyric's keys (`run_python`, `execute_with_resource_limits`). Run time is recorded per tool run | A workspace of a person's own, and counting CPU time rather than wall time |
| Core compute storage | Nothing | A person's own workspace disk |
| Tasks at once | 3 foreground per person for everyone (`per_actor_max_tasks`); background shared by all (section 4) | 1 foreground for every offering, and 1, 2 or 5 background per user |
| Scheduled jobs | Lyric's own recurring jobs; a message to a person at a set time | Recurring work a person owns |
| Pro team context | Each person's own context, plus a shared one owned by a named group (`org:<name>`), composed for each member (ORG-01) | Nothing more: a Pro team can be that group |
| Organization-wide goals and actions | Each person's own context plus the organization's Work Context: everything done or told for it is its own, kept when a person leaves (ORG-01, 20/20) | Goals and tasks owned by the organization and fed by its Work Context, rather than by one person |

## 14. A first draft of the list per offering

This is a draft built from what Lyric does today, for you to cut or change.

### Acting

| | Free | Pro | Auto |
|---|---|---|---|
| Lyric notices things and tells you first | ✓ | ✓ | ✓ |
| Answers from what it knows about you and the world | ✓ | ✓ | ✓ |
| Does work you ask for, each act confirmed by you (Assist) | | ✓ | ✓ |
| Acts on its own where a capability is unlocked for you (Delegate) | | | ✓ |
| Acts on a person's work: classes allowed (Law 1) | Investigate | Investigate, modify, archive | By role, up to delete and execute |
| Foreground tasks at once, per user | 1 | 1 | 1 |
| Background tasks at once, per user (agents of self, lookups) | 1 | 2 | 5 |
| Scheduled jobs | | ✓ | ✓ |
| Workflows | | ✓ | ✓ |
| Halt Lyric at any time | ✓ | ✓ | ✓ |

### Knowledge and memory

| | Free | Pro | Auto |
|---|---|---|---|
| Context | Your own | Your own, plus the team's shared context | Your own, plus the organization-wide context |
| The organization-wide context feeds the organization's goals and tasks, and stays when a person leaves | | | ✓ |
| Lyric learns how you work, and your methods stay yours | ✓ | ✓ | ✓ |
| Recall by meaning, by sound and by sight | ✓ | ✓ | ✓ |
| Pictures and sounds kept with memories | ✓ | ✓ | ✓ |
| What you tell Lyric about you and your work is kept in your context | ✓ | ✓ | ✓ |
| Reward allowance | | ✓ | ✓ |

### Senses

| | Free | Pro | Auto |
|---|---|---|---|
| Reads PDF, Word, Excel and text | ✓ | ✓ | ✓ |
| Sees images and video | ✓ | ✓ | ✓ |
| Hears sounds, speech and music | ✓ | ✓ | ✓ |
| Live listening and looking (keeps only what is said to Lyric) | | ✓ | ✓ |

### Tools

| | Free | Pro | Auto |
|---|---|---|---|
| Research: web, papers, government data, news, citations | ✓ | ✓ | ✓ |
| Documents: PDF, Word, PowerPoint, LaTeX, diagrams | ✓ | ✓ | ✓ |
| Reasoning and simulation: proofs, constraints, optimization, Monte Carlo, symbolic math | | ✓ | ✓ |
| Code: building, refactoring, testing, security analysis | | ✓ | ✓ |
| Data: parsing, transforming, profiling, scrubbing personal data | | ✓ | ✓ |
| Running code | | ✓ | ✓ |
| Outside databases | | ✓ | ✓ |
| Systems: processes, services, logs, monitoring | | ✓ | ✓ |
| Security: threat intelligence, intrusion and anomaly detection, threat hunting | | | ✓ |
| Active defense: blocking at the firewall and WAF | | | ✓ (Delegate only) |

### Connectors

| | Free | Pro | Auto |
|---|---|---|---|
| Connector set | A curated personal set | The professional catalog (9,503) | The professional catalog (9,503) |
| Connector tools become Lyric's tools | ✓ | ✓ | ✓ |
| Instant triggers for workflows | | ✓ | ✓ |
| Lyric checks a connector on a schedule (every 1, 5, 15 or 60 minutes) | | ✓ | ✓ |
| Organization connections, set up by admins | | | ✓ |
| Admins choose, by category, which connectors people may use | | | ✓ |

### Organization

| | Free | Pro | Auto |
|---|---|---|---|
| Users, roles and single sign-on | | | ✓ |
| Autonomy and boundaries per area, with approvers | | | ✓ |
| Billing, usage and budgets | | | ✓ |
| A record of every act Lyric judged, refused or redirected | | | ✓ |
| Dedicated instance: its own processes and stores, on the release it chooses | | | ✓ |

### Open questions for you

None right now.

### What Lyric's code doesn't do yet

- **Licensing:** nothing puts a person on Pro when they pay for it. `WorldAuth.set_offering` does it; everyone is on Free until then.
- **Operating modes, still to go in:** Law 1 by mode is staged until the teaching run ends, and Tet must be redeployed for modes and offerings to reach Lyric.
- **Boundaries per area** in an organization: for now the role sets the mode.
- **Teaching from your own lessons:** a served release refuses the model's own learning (`_refused_while_frozen`), so a team's lessons wait for a new release. Holding them in the team's own context would be new.
- **Task limits:** per-offering foreground limits, per-person background limits, and scheduled jobs a person owns.
- **Connectors:**
  - Connections owned by a team or an organization and used by its people.
  - Limits on which connectors may be connected.
- **Organization:** goals and tasks owned by the organization.
- **Counting:** monthly action minutes, storage size and compute. These are counted per seat, not per person, so a replaced user doesn't reset them.

## 15. Internet access (researched 2026-10-09)

The question: can Lyric have an Internet access page like GitHub's (Organization settings › Copilot › Internet access), for Pro and Auto, built on Tet's firewall. Below: what GitHub's page does, what Tet and Lyric do today, and what the page would need before it can be built.

### What GitHub's page does

There is one section per agent (Copilot cloud agent, Copilot code review). Each section has:
- **Enable firewall** ("Recommended"): Enabled, Disabled, or Let repositories decide. Limits the agent's internet access to the allowlist.
- **Recommended allowlist:** the same three choices. It lists:
  - Operating system package repositories.
  - Container registries.
  - Language package registries.
  - Certificate authorities.
  - Browser downloads for Playwright.
- **Allow repository custom rules:** whether repository admins may add their own entries.
- **Organization custom allowlist**, for every repository:
  - A domain allows that domain and its subdomains.
  - A URL allows that scheme and host, at that path and below.

**How the settings combine:** every organization setting starts at "Let repositories decide". In a repository, the firewall and the recommended allowlist are on by default, and organization and repository entries add together.

**When something is blocked:** a warning on the pull request names the blocked address and the command that tried it.

**What it covers:**
- Only the commands the agent runs in its shell. Not MCP servers, and not setup steps.
- GitHub's own words: "should not be considered a comprehensive security solution."

Sources: [GitHub Docs, customizing the agent firewall](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/use-copilot-agents/coding-agent/customize-the-agent-firewall); [GitHub Changelog, 2026-04-03, organization firewall settings](https://github.blog/changelog/2026-04-03-organization-firewall-settings-for-copilot-cloud-agent/).

### What Tet does today

Tet is a firewall for **crossings**: what enters the world, what leaves it, and what runs in it. It does not decide which internet addresses may be reached.
- **The crossings:** each one clears identity and capability first, then its own checks (`Tet/space.py`, PIPELINES). The crossings are exec, ingest, egress, observe, admit, allocate and message. None of them is "open a connection to this address".
- **Egress is content leaving the world, not a connection:**
  - OUTPUT_VALIDATION refuses content unless it is positively harmless. That stops private keys, cloud keys, passwords and Social Security numbers (`Tet/boundaries/output_validation.py`).
  - DATA_CLASSIFICATION holds each principal to its clearance (`max_classification`, `Tet/world/access.py`).
- **Programs:** an executable must be named and on the caller's allowlist (`Tet/boundaries/process_validation.py`).
- **URLs:** the floor checks only that a URL is http or https and has a host (F5, `Tet/floor.py`). Nothing checks where it points.
- **The world's network:** the world container has a direct route out (`Tet/deploy/docker-compose.yml`, the edge network, decided 2026-10-02). Nothing filters destinations.

### What Lyric does today

**Lyric is the world's inhabitant.** When Lyric runs with a world named, it attaches to Tet as its inhabitant (`core/main.py`, `core/integration/world_inhabitant.py`). Everything a person sends reaches Lyric only through Tet's gate: a turn, their reward allowance, their operating mode, their devices.

**When Lyric uses a tool that reaches the internet, the request goes from Lyric straight to the site.** The gate checks what comes to Lyric; it does not check where Lyric connects when it uses these tools.
- **Web tools** (`core/tools/network_tools.py`):
  - HTTP request: any method, headers and body.
  - Downloading and uploading files.
  - Checking a URL, and reading a page.
  - DNS lookup, ping and port scan.
  - WebSocket, GraphQL and API calls.
  - Web search (DuckDuckGo).
- **The research tool** (`core/tools/research_tools.py`): queries outside data APIs from `api_registry.json`. It only uses the entries marked tested with a quality score of 0.7 or more, which is 18 of the file's 75. It is registered (`core/tools/tool_registry.py`), but its use isn't shown.
- **Connectors** (`core/connectors/protocol.py`): MCP sessions with each connector's server.
- **Messages out:** Slack and notifications.

**What's missing on that outgoing side:**
- **No shared way out:** about 18 files make their own HTTP calls.
- **No address check:** the HTTP request tool sends to whatever URL it is given. That includes the computer's own services (localhost, the database port), the local network, and cloud metadata addresses.
- **No record** of which addresses those requests reached.

### What the page needs before it can be built

A page today would be settings with nothing behind them. Four pieces make it real:
1. **One way out.** Every network request Lyric makes goes through one client, which asks Tet first.
   - **The crossing:** a new crossing, "connect", clears identity and capability, then checks the destination.
   - **Where the check lives:** whether an address matches an entry is a crisp test, so it belongs in that boundary's floor.
   - **Tools that aren't HTTP:** for ping, port scan and DNS, the check runs before the tool does.
2. **Always blocked, whatever the settings:** the computer's own addresses, private networks and cloud metadata. They are checked after DNS resolution, so a name can't point back inside.
3. **Every block is shown:** the Activity record names the blocked address and the step that tried it. This is GitHub's pull request warning, in Lyric's place.
4. **The policy** of each organization (Auto) and team (Pro), kept with the organization's other settings.

### How GitHub's settings map onto Lyric

| GitHub | Lyric |
|---|---|
| A section per agent (cloud agent, code review) | One section: Lyric's own work. Connectors stay in Integrations, where adding an integration is what allows its address. |
| Enable firewall: Enabled, Disabled, Let repositories decide | Enabled, Disabled, Let members decide (Autonomy already has this pattern: members may change their own settings within the organization's limits) |
| Recommended allowlist | Lyric's sources: the research tool's 18 data APIs, the web search provider, and package registries once the world installs packages |
| Allow repository custom rules | Allow members' own entries |
| Organization custom allowlist | The organization's (Auto) or team's (Pro) allowlist: domains, URLs and IP ranges |

### Open questions for you

1. **Reading the web.** GitHub's agent mostly needs package registries, so an allowlist alone works for it. Lyric researches on the open web: with only an allowlist, it can't read a page that isn't on the list. The options:
   - **Allowlist only,** as GitHub does.
   - **A separate "Read public web pages" switch.** Reading is allowed anywhere public, and anything that sends (uploads, forms, API calls, WebSockets) is held to the allowlist. A page address can carry data in it, so this trades some protection for research.
   - **Block only the always-blocked addresses.**

   Recommended: the separate switch, on by default.
2. **Defaults** for a new Pro team or Auto organization: the firewall on with Lyric's sources (GitHub's default), or off.
3. **Free:** no page. The always-blocked addresses still apply. Is the rest open?
4. **The world's own route out** (package installs): through this same check, or left direct. This is the 2026-09-29 question, still open.

## 16. Four offerings (set 2026-10-12)

The three offerings above became four. The sections above are the dated record of how they were reached.

| | Lyric Starter | Lyric Pro | Lyric Max | Lyric Enterprise |
|---|---|---|---|---|
| For | Getting started with Lyric | Individuals | Developers and teams | Organizations, on a dedicated Lyric instance |
| Price | Free | $19.99 / month | $59.99 / month for the first seat, plus up to 2 more seats at $59.99 each | Custom pricing (shown publicly as Custom, with Contact sales) |
| Autonomy | Observe | Observe and Assist | Observe, Assist and Delegate | Observe, Assist and Delegate, set by the organization's administrators |
| Concurrent tasks | 2 | 3, plus scheduled jobs | 5 per seat, plus scheduled jobs | Custom |
| Workflows and scheduled jobs | | ✓ | ✓ | ✓ |
| Listening | | ✓ | ✓ | ✓ |
| Voice mode | 20 minutes a month | ✓ | ✓ | ✓ |
| Tools | Research and documents | Adds reasoning, data and code | Adds running code, outside databases and systems | Adds security and active defense |
| Connectors | A curated personal set | The full catalog | The full catalog, with team approval | The full catalog, with organization integrations |
| Reward allowance, API keys and webhooks, users and seats | | | ✓ | ✓ |
| Organization-wide goals and actions | | | | ✓ |
| Support | Community | Community | Priority | Dedicated |
| Action minutes | 800 | 2,500 | 7,500 per seat | Custom |
| Project storage | 500 MB | 2 GB | 8 GB per seat | Custom |
| Compute | 80 core-hours | 500 core-hours | 1,500 core-hours per seat | Custom |
| Core compute storage | 5 GB | 10 GB | 20 GB per seat | Custom |

**Observe completes what is asked.** On Lyric Starter, Lyric still does actions and completes the work a person asks for, each act confirmed; it never acts on its own and runs no scheduled jobs. `capabilities.OPERATING_MODES["observe"]` is investigate, modify and archive (it was investigate only); `may_act_for` keeps Observe to what was asked.

**At the gate (Tet `world/access.py`):** `OFFERING_MODES` is free (Lyric Starter, stored by its price) to Observe, pro to Assist, max to Delegate; `OFFERING_LEAVES_OUT` takes `world.hearing` (Listening) out of Lyric Starter, so its devices cannot stream to Lyric on their own. Every offering keeps `world.hearing.voice` (voice mode, added 2026-10-12): the world takes it only for what is heard in voice mode, the stream stopping, and the wake phrase taught, which is how Lyric learns the person's voice (`world_runtime._hearing_not_asked_for`). An organization's members are on Lyric Enterprise and their role decides.

**Not enforced yet:** concurrent tasks, scheduled jobs per offering, the tools per offering, the curated connector set, and the monthly allowances (section 14, "What Lyric's code doesn't do yet"). Lyric Starter's 20 minutes of voice mode a month is counted and stopped by each device, not by the gate.
