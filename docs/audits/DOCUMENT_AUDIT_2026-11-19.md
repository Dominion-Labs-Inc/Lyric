# Lyric Document Audit

**2026-11-19.** Every document in the Lyric repository and at the `Dominion Labs` repository root,
measured against the code, the experiment artifacts and the six Lyric documents the investor data room
is serving today. Nothing below is carried over from an earlier description: each finding names the file
and the measurement that produced it, and each one is reproducible by the command beside it.

**What this is for.** The data room was synced on 2026-11-18 and serves 91 documents. Six of them are the
Lyric technical set, and those six are rendered from markdown sources in `Lyric/docs/`. This audit asks one
question of those sources and of everything around them: would a technical reviewer reading them today be
reading the system that exists?

---

## 1. The census

| Where | Documents | Kind | State |
|---|---|---|---|
| `Lyric/experiments/*/results/` | 1,981 | machine run records | current, to 2026-11-11 |
| `Lyric/docs/teaching_sessions/` | 440 | machine teaching records | current, to 2026-11-17 |
| `Lyric/experiments/*/README.md` | 196 | per-experiment prose | mostly current, 36 gaps |
| `Lyric/docs/` top level | 17 | reference and canonical | 4 canonical, 13 mixed |
| `Lyric/docs/governance/` | 20 | phase plans and reports | retired system |
| `Lyric/docs/research/` | 19 | research and measurements | 2 current, rest topic notes |
| `Lyric/docs/design/` | 12 | design decisions | historical |
| `Lyric/docs/architecture/` | 9 | live subsystem maps | current |
| `Lyric/docs/security/` | 6 | security architecture | dismantled system |
| `Lyric/docs/archive/` | 5 | already archived | correct |
| `Lyric/docs/audits/` | 1 | point-in-time audit | this folder |
| `Lyric/archive/` | 29 | retired | correct |
| `Lyric/core/**` | 8 | stray, 3 substantive | see §3.10 |
| `Lyric/{data,projects,output,design,research}/` | 11 | Lyric's own work product | not documentation |
| `Lyric/LYRIC_REFERENCE.md` | 1 | self-declared authoritative | see §3.6 |
| `Dominion Labs/` root | 39 | TorinAI-era engineering notes | see §3.5 |

2,809 markdown files sit under `Lyric/`. 2,421 of them are machine records, and those are the healthy part
of the estate: they are written by the harness, never edited by hand, and they run to within two days of
today. The document problem is entirely in the roughly 110 hand written documents and the 39 at the
repository root.

## 2. The structure already exists, and it is the right one

`Lyric/docs/` is already organised the way it should be, and the data room already maps onto it one to one:

| In the room | Rendered from |
|---|---|
| Lyric Ai Product and System Overview | `docs/LYRIC_PRODUCT_AND_SYSTEM_OVERVIEW.md` |
| Lyric Ai Technical Overview 2026 | the same source |
| Lyric Ai Architecture Documentation | `docs/LYRIC_ARCHITECTURE_DOCUMENT.md` |
| Lyric Ai Validation and Experiment Results 2026 | `docs/LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md` |
| Research Technical Thesis | `docs/LYRIC_RESEARCH_TECHNICAL_THESIS.md` |
| Lyric Ai Product Overview 2026 | nothing; no markdown source exists |

Four canonical documents, each with one job, each feeding the room. That is a sound structure and it does
not need replacing. What it needs is for the four to be current, for the index to describe it, and for the
documents that belong to retired systems to stop sitting in folders that read as live.

## 3. Findings

### 3.1 The evidence document represents a quarter of the evidence

`docs/LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md`, line 21, states it was compiled from
**614 run artifacts plus 27 manifest artifacts across 84 experiment directories**, of which 33 carry
machine written run records.

Measured on disk today:

| | Document | On disk | |
|---|---|---|---|
| Experiment directories | 84 | **245** | |
| Carrying machine artifacts | 33 | **189** | |
| Run artifacts | 614 | **2,477** | |

**149 evidenced experiments, holding 1,552 artifacts, do not appear in the document at all.** The largest
of them are the language and reading series, which is the work of the last two months:

| Experiment | Artifacts | In the document |
|---|---|---|
| `GRAMMAR-01` | 181 | no |
| `TRAIN-FORMAT-02` | 111 | no |
| `TRAIN-FORMAT-01` | 68 | no |
| `RULE-AUTHORITY-02` | 46 | no |
| `UNDERSTANDS-PROSE-01` | 38 | no |
| `STRUCTURE-02` | 31 | no |
| `SYSTEM-CONVERSATION-01` | 24 | no |
| `PATHS-01` | 24 | no |
| `CANARY-01` | 22 | no |
| `RULE-AUTHORITY-01` | 22 | no |
| `ENGLISH-01` | 17 | no |
| `SENSE-01` | 15 | no |
| `UNDERSTANDS-PROSE-02` | 16 | no |
| `UNDERSTANDS-WORDNET-01` | present | no |

Nothing in the document is wrong. Everything in it is a real result that was really measured. The defect is
that it stops in September, and the strongest evidence the company holds was produced after it stopped.
This is the single item that most changes what a reviewer concludes.

Reproduce: compare `^\| \`NAME\` \|` registry rows in the document against
`glob('experiments/**/results/*.json')`.

### 3.2 The architecture document's component map is 37 percent low

`docs/LYRIC_ARCHITECTURE_DOCUMENT.md` carries a subsystem table of lines and module counts, measured
2026-09-19 at 20:49 UTC, and closes it with "Roughly 175,000 lines across the subsystems listed".
`core/` today holds **245,952 lines across 268 files**. The listed subsystems total 235,667 against the
171,796 in the table.

| Subsystem | Document | Today | Drift |
|---|---|---|---|
| `memory/` | 534 | 5,453 | +921% |
| `semantics/` | 4,828 | 29,207 | +505% |
| `perception/` | 1,899 | 8,915 | +369% |
| `monitoring/` | 234 | 596 | +155% |
| `chaos/` | 4,188 | 8,505 | +103% |
| `database/` | 2,056 | 3,609 | +76% |
| `learning/` | 17,326 | 29,749 | +72% |
| `intelligence/` | 1,506 | 2,218 | +47% |
| `observability/` | 916 | 1,329 | +45% |
| `agents/` | 40,713 | 52,410 | +29% |
| `integration/` | 5,485 | 6,356 | +16% |
| `reasoning/` | 21,713 | 24,342 | +12% |
| `domain/` | 7,527 | 8,144 | +8% |
| `tools/` | 48,524 | 40,891 | -16% |

`semantics/` growing fivefold is the reading and grammar work. `memory/` growing tenfold and `perception/`
nearly fourfold are the same story. The table understates the system in exactly the places where the recent
research went.

The table also lists **`execution/` at 4,804 lines and 9 modules, and `core/execution/` does not exist.**
The capability is live and was traced, not assumed: effect verification is
`core/intelligence/effect_verification.py`, procedure synthesis over learned operators is
`core/learning/procedure_synthesis.py` and `core/learning/rule_store.py`, and learned-operator plans run
through `core/agents/autonomous/execution_plan_adapter.py`. The subsystem was dissolved into three others.
Nothing was lost; the map is stale.

The cover reads **September 2026**.

### 3.3 The product overview's measurement table is two months old

`docs/LYRIC_PRODUCT_AND_SYSTEM_OVERVIEW.md` §23 states that measurements were taken
**2026-09-19 at 20:49 UTC** and lists 302,240 concepts, 516,110 relations, 514,132 beliefs, 482,491
evidence records, 146 registered domains, 356 tools and **"Named experiment suites (current series): 32"**
against the 189 evidenced directories that exist now. Its cover reads October 2026.

These are the numbers a reviewer quotes back. They need one re-measurement under the canonical runtime
against the live store. I could not take it: reading `Lyric/.env` was refused by the sandbox, so the
connection details were not available to me. This is a run for you to start.

Separately, **§13 Language and Knowledge Foundation is 25 lines.** It is accurate as far as it goes, and it
is the thinnest section in the document covering the subsystem that grew 505 percent and carries the
largest experiment series in the corpus. The reading and understanding work is the least represented part
of the best evidenced capability.

### 3.4 The standing benchmark record stops on 2026-09-28

`experiments/README.md` names `docs/research/BENCHMARKS.md` as "the standing record of measurements".
That file's rules are exact and good: every number came from a named re-runnable command, nothing is
estimated, a regression shows as a number that moved. Its **last dated row is 2026-09-28.**

`docs/research/LAB_NOTEBOOK.md` by contrast was written to yesterday, 2026-11-18, and is the only standing
record that is current. The benchmark file is where the notebook's results were supposed to settle.

### 3.5 Thirty-nine documents at the repository root contradict the investment thesis

The `Dominion Labs` repository root holds 39 markdown files, all committed on 2026-10-16 in a single
import, with content written between December 2025 and March 2026. Across them:

- **442 mentions of Torin or TorinAI**, in 28 files
- **86 mentions of an LLM layer**, in 17 files
- **45 mentions of AGI or ASI**, in 11 files

What they say, verbatim:

| File | Opening line |
|---|---|
| `AGENT_BASED_MEMORY_ARCHITECTURE.md` | "TorinAI now uses specialized **Memory Query Agents** orchestrated by the **AutonomousCoordinator** to intelligently retrieve and summarize memory context for LLM injection." |
| `MEMORY_ARCHITECTURE_REALITY.md` | "TorinAI Memory Architecture, THE TRUTH. Status: CRITICAL, Fragmented architecture with disconnected systems" |
| `AGI_TEST_CRITICAL_ANALYSIS.md` | "Status: TESTS INVALID, MAJOR FLAWS IDENTIFIED. Recommendation: Do not use current results to support AGI claims" |
| `SINGLETON_EXECUTION_FLOW.md` | "What Happens When Torin (The Singleton Brain) Starts" |
| `lyricsched.md` | "TorinAI operates as a fully autonomous AI system with 12 background workers" |
| `README.md` | "**TorinAI**, Advanced AI assistant and natural language processing" and "**AI**: TorinAI cognitive substrate" |

Every one of these describes a system that no longer exists, in a vocabulary the company retired, and three
of them read as an indictment of it. `AGI_TEST_CRITICAL_ANALYSIS.md` is the worst case: a document in the
repository whose stated conclusion is that the validation tests were invalid. It was about a test design
from December 2025 that has since been replaced by the 2,477-artifact corpus, but nothing in the file says
so, and nobody reading it would know.

Only **two** of the 39 are current: `HANDOFF.md` (2026-11-09, the LyricOS platform handoff) and
`HIDDEN.md` (2026-11-14). The company `README.md` still names TorinAI as the product.

### 3.6 The one document that calls itself authoritative describes an LLM brain

`Lyric/LYRIC_REFERENCE.md`, 104 KB, header:

> **Version:** Current as of 2026-03-06
> **Classification:** Internal Technical Reference
> **Purpose:** Authoritative, scientifically thorough documentation of all Lyric systems, subsystems,
> algorithms, equations, data structures, and control flows.

Its table of contents includes **"3. The Brain, LLM Layer"**, and inside it "3.1 Unified LLM Service",
"3.2 Lightweight LLM Service", `lyric_brain` as an LLM service instance, and control flow that reads
"Call LLM via neural bridge (ReasoningMode.NEURAL)". 27 mentions of a model layer in total.

It is the only document in the estate that claims to be authoritative, it is eight months old, and it says
the opposite of §1.1 of the architecture document ("No generative model participates in Lyric's reasoning,
planning, judgement of actions, or its decision to act"). Of the two, the architecture document is the one
that matches the code.

### 3.7 The documentation index is from a different era

`docs/README.md` is what an engineer or a technical reviewer opens first. It says:

> Lyric is an AGI system with reasoning, memory, learning, security, and autonomous capabilities.

The validation document, line 1263, states the opposite and states it deliberately: "That Lyric is
generally intelligent, AGI, or human-level, **no experiment bears on this**". The index contradicts the
evidence document on the one claim the evidence document is most careful about.

It then presents memory filtering, chaos testing and a three-tier governance approval system as the three
core systems, links to `docs/memory_filtering.md` and `docs/chaos_testing.md` which moved to
`docs/design/` and `docs/security/` (six broken links), and points at
`core/governance/unified_governance_trigger_system.py`, which no longer exists. It does not mention the
four canonical documents, the semantics subsystem, the reading work, the teaching record or the experiment
corpus.

### 3.8 Retired systems are documented in folders that read as live

**`docs/governance/`, 20 documents.** Nine phase completion reports and their plans, describing the
governance trigger system. `core/governance/` does not exist, and the only trace of it in `core/` is an orphaned
`governance_block_schema.cpython-311.pyc` with no source beside it. `config/governance_triggers.json` does
not exist. `tests/governance/` still holds three of the phase tests and a tenth governance document,
`phase1_test_plan.md`, outside `docs/` entirely; `test_phase1_core.py`, which four of the reports cite, is
gone. The system was absorbed, which is recorded in
`docs/governance/GOVERNANCE_SESSION_RETIRED.md` and evidenced by the
`experiments/GOVERNANCE-ABSORPTION-01` series. The one note saying so sits in a folder of twenty saying
otherwise.

**`docs/security/`, 6 documents.** `docs/security/SAFETY_ARCHITECTURE.md`, dated 2026-08-11, tells the
reader that host and perimeter security "is covered by" `SECURITY_GUARDIAN_ARCHITECTURE.md`,
`SECURITY_FOLDER_AUDIT.md` and `SECURITY_INTEGRATION_ANALYSIS.md`. Those three describe
`content_security.py`, `malware_sandbox.py`, `threat_intelligence.py`, `firewall_manager.py`,
`cloudflare_waf.py`, `threat_blocking.py` and `asi_safety.py`. `core/security/` now holds `secrets.py`,
`security_training_pipeline.py` and a `_disabled/` folder, whose own README states the perimeter was
"superseded by the Tet membrane, which lives outside the substrate".

The investor-facing account of this is **correct**: §15 of the Product and System Overview already says
Lyric runs inside an enclosing protected environment maintained as a separate program and puts that
boundary out of scope. Only the internal set is wrong, and it is wrong in a way that invites a reviewer to
ask about modules that were deliberately retired.

### 3.9 Smaller items

| Item | Measurement |
|---|---|
| Broken relative links in `Lyric/docs` | **66.** About a third are path-depth errors (`../core/` where `../../core/` was meant) and fix mechanically. The rest point at deleted modules and need the prose changed, not the link. |
| Experiments without a README | **36 of 189** evidenced directories, including `BEARING-01`, `DRIFT-01`, `FALSIFY-01`, `FRAME-01`, `HARM-02`, `RECOGNISE-01/02`, `SEE-LOOP-01`, the 14 `ENCODER-*` and the 13 under `experiments/nlu/`. |
| Experiments index coverage | `experiments/README.md` names 179 identifiers; **47 evidenced experiments are not named in it.** |
| `docs/TEACHING.md` | Edited 2026-11-15, still states "Every number here was measured against the live store on 2026-09-20". |
| Duplicate authority | `docs/architecture/beliefs.md` and `docs/design/BELIEFS.md` both describe beliefs. `docs/design/memory_filtering.md` (January) sits beside the live `docs/architecture/memory.md` (October). |
| Source-less room documents | "Lyric Ai Product Overview 2026" has no markdown source, as does the one-pager already on record. Every other room document is regenerable. |
| `PUBLIC_BETA_ROLE_PROFILES.md:367` | Last live reference to `torinai-chat` on port 9080. |
| `core/security/_disabled/README.md` | Points at `../CAPABILITIES_CATALOG.md`; the file is at `docs/security/CAPABILITIES_CATALOG.md`. |

### 3.10 Substantive documents are hiding in the code tree

Eight markdown files sit under `Lyric/core/`, outside the documentation structure, and three of them are
real documents that a reviewer would want and cannot find:

| File | Size | Modified |
|---|---|---|
| `core/reasoning/REASONING_PIPELINE.md` | 58 KB | 2026-10-07 |
| `core/reasoning/REASONING.md` | 18 KB | 2026-08-24 |
| `core/reasoning/REASONING_PATHS_VERIFIED.md` | 14 KB | 2026-09-29 |

`REASONING_PATHS_VERIFIED.md` is titled "The Eleven Reasoning Paths, Verified Against the Code". The
product overview's §23 table asserts "Kinds of reasoning: 11". The document that substantiates that number
is in the code tree, is not linked from `docs/`, and is not named by either canonical document. These three
belong in `docs/architecture/` beside `reasoning.md`, or linked from it.

The rest of that set is noise worth clearing: `core/neural_bridge/` holds a `README.md` and no Python at
all, and that README describes "a decentralized, federated learning architecture for distributed training
across edge devices", which is not what a neural bridge is and not what the real module
(`core/reasoning/neural_bridge.py`) does. `core/health/health_monitor.py:483` already records that
`core/neural_bridge` holds no modules. `core/agents/agent_capability_test.md` contains the text
"## Test ##". `core/health/README.md` is an empty heading.

Separately, 11 markdown files under `data/`, `projects/`, `output/`, `design/` and `research/` are
**Lyric's own work product**, not company documentation: a decentralized logging system README, an IPFS
storage architecture, Kafka task design notes, a dependency security audit the system ran on itself. They
are evidence of the system working and should not be mistaken for documents about it, in either direction.

---

## 4. What the repairs are

In the order that changes what a reviewer concludes, largest first.

**1. Regenerate the validation document's registry from the full corpus.** The generator parses
`experiments/**/results/*.json` and the document's own structure does not change: the same registry table,
the same per-experiment sections, the same artifact index, over 2,477 artifacts and 189 experiments instead
of 614 and 33. This is the highest-value single piece of work in the estate, because the material already
exists and is already machine-verified. Needs: a run on your word.

**2. Re-measure the two tables.** The architecture document's subsystem table from a source scan, and the
product overview's §23 from the live store under `./venv_lyric/bin/python3`. Both documents already declare
their method, so this is re-running what they describe. Needs: the live database, which I could not reach.

**3. Fix the architecture document's component map.** Replace the `execution/` row with where those three
capabilities now live, and move the cover from September to November.

**4. Expand §13 of the product overview.** The reading and grammar work, the sentence reader, the admission
gate, sense selection, the taught grammar, and the teaching record of 440 sessions. The section is thin on
the capability with the most evidence behind it.

**5. Bring `docs/research/BENCHMARKS.md` forward from 2026-09-28,** from the artifacts and the lab notebook
entries that already record the runs.

**6. Rewrite `docs/README.md` as the index to the structure in §2.** Name the four canonical documents and
what each one answers, the live subsystem maps, the two standing records, the experiment corpus and the
teaching record. Drop the AGI sentence, which the evidence document explicitly disclaims.

**7. Move the retired sets into `archive/`, dated, with one note each saying what replaced them.**
`docs/governance/` (20 files) and the three perimeter documents in `docs/security/`, leaving
`SAFETY_ARCHITECTURE.md` and `CAPABILITIES_CATALOG.md` in place and correcting
`SAFETY_ARCHITECTURE.md`'s pointer. Nothing is deleted and no capability is removed: the governance
absorption and the Tet supersession are both real, recorded decisions, and the archived documents are the
record of how the system got here.

**8. Clear the repository root.** 37 of the 39 files belong in an archive folder, not at the root of the
repository a technical reviewer is shown. `HANDOFF.md` and `HIDDEN.md` stay. The company `README.md` needs
TorinAI replaced with Lyric Ai in its product list and its stack section.

**9. Retire or rewrite `LYRIC_REFERENCE.md`.** It cannot stay as it is while calling itself authoritative:
either it is archived with a date, or its model-layer sections are rewritten against the substrate. The
material it covers that is still true is already covered by `docs/architecture/`, which is current.

**10. Lift the three reasoning documents into `docs/architecture/`** (§3.10), and delete the three stray
files that contain nothing: `core/neural_bridge/README.md`, `core/agents/agent_capability_test.md` and the
empty `core/health/README.md`.

**11. The mechanical set.** 66 broken links, 36 missing experiment READMEs, 47 index gaps, the
`TEACHING.md` measurement date, the `torinai-chat` reference, the duplicate belief documents.

## 5. What needs your word before it happens

- **Runs.** Items 1, 2 and 5 are runs against the store, and runs start when you say so. Item 2 also needs
  the live database connection, which the sandbox would not let me read from `.env`.
- **Moves and archiving.** Items 7, 8 and 9 move files. None of them deletes anything and none removes a
  capability, but they change what is in the repository root and in two folders, so they are yours to
  approve.
- **Re-renders.** Once the sources are current, the four documents re-render to Word and PDF through the
  Word pipeline and the data room picks them up on its next `sync`.

Everything in §3 is reported as found and re-verified against the code and the artifacts. No capability was
marked missing on the evidence of an old file: where a document named something that is gone, the capability
was traced to where it lives now and that is what §3.2 and §3.8 record.
