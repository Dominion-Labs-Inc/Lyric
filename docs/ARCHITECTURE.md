# TorinAI — Architecture

*The canonical architecture document. Current as of 2026-09-07, verified against
the running system (`experiments/systems/VERIFY-01`). Supersedes the older
`ARCHITECTURE_GRAPH.md` and `AUTONOMOUS_COORDINATOR_MAP.md`. For the method-level
inventory (every method of every faculty, grouped by pipeline), see
[`SUBSTRATE_SYSTEMS_MAP.md`](SUBSTRATE_SYSTEMS_MAP.md).*

---

## 1. What TorinAI is

TorinAI is a **persistent cognitive substrate**: a system that maintains and
develops structured knowledge, memory, beliefs, learned operators, competence,
and goals over time, and reasons over what it holds rather than regenerating an
answer from scratch each time. Cognition is organised as a set of interacting
faculties operating over **one shared persistent state**. The output of one
faculty becomes structured input to another — a conclusion revises a belief, an
action produces an experience, an experience induces an operator, a competence
gap raises the motivation to explore.

It is **one running process**: a single coordinator in which each faculty is a
pipeline. It is not a bus between independent services.

> **Language models.** TorinAI's cognition uses no language model. Reasoning,
> learning, planning, action, and verification consult none. The only component
> that can consult a model at all is a single teaching module
> (`core/learning/teacher_policy.py`), and in practice it is essentially unused —
> remove it and the substrate is unchanged.

---

## 2. Persistent cognitive state

The shared, durable state every faculty reads and writes. Each element has a
single authority.

| Element | What it is | Store |
|---|---|---|
| **Concepts** | typed nodes of what the system knows | `unified.concepts` |
| **Relations** | typed, polarity-bearing edges (is-a, part-of, denials) | `unified.concept_relations` |
| **Memory** | retained experiences, retrievable and consolidated | memory tiers (`MemoryAgent`) |
| **Beliefs** | propositions held with calibrated, revisable uncertainty | `unified.beliefs` |
| **Operators** | learned, variable-carrying transformations with add/remove effects | `unified.learned_rules` |
| **Competence** | per-subject estimate of what the system can *do* | competence beliefs (UDM) |
| **Domains** | subjects — clusters of concepts and operators, created automatically | `unified.domains` |
| **Experience** | before/action/after traces that feed learning | `unified.operator_demonstrations` |

The elements form a cycle: experience → memory → learning → (operators, concepts,
beliefs) → reasoning → planning → action → experience.

---

## 3. The faculties (one pipeline each, all in the coordinator)

The coordinator is `core/agents/autonomous/autonomous_coordinator.py`
(`AutonomousCoordinator`). Each faculty is a pipeline within it. Full method
inventory in [`SUBSTRATE_SYSTEMS_MAP.md`](SUBSTRATE_SYSTEMS_MAP.md).

### 3.1 Reasoning — `core/reasoning/neural_bridge.py`
Entered via `coord.reason_about(q)` → `NeuralSymbolicBridge.reason`. Formalises a
question into a logical query, selects a mode, and answers from the substrate's
own knowledge (no model fallback):
- **Substrate solvers:** taxonomy (`_answer_over_sense_taxonomy`), concept graph
  (`_answer_over_concept_graph`), held rules (`_answer_over_held_rules` / chaining),
  symbolic deduction, equation, sequence.
- **Modes:** symbolic, hybrid, neuro-symbolic, cross-domain.
- Returns **`unsupported`** when it cannot ground an answer, rather than guessing;
  performs **gap diagnosis** (missing fact vs missing operation).

### 3.2 Learning — `core/learning/unified_learning_system.py`
The one learning authority (`coord.learning`). Four modes, one shared state:
- **Instruction:** `learn_fact` / `learn_rule` / `learn_concept` / `learn_word`,
  admitted with provenance; fans out to reasoning, beliefs, lexicon, domain, memory.
- **Operator induction (growth loop):** `record_demonstration` (hot path) →
  `drain_pending_induction` / `_induce_signature` (off-band) → validate on
  independent held-out → executable. Induction never runs on the acting path.
- **Consolidation:** clustering, domain crystallisation, merges.
- **Belief revision:** `create_belief` / `update_belief` / `observe_claim` over
  the Bayesian belief substrate (`core/reasoning/bayesian_uncertainty.py`).

### 3.3 Memory — `core/agents/memory_agent.py`
`MemoryAgent` (`coord.memory`): worthiness-gated write, retrieval by content and
relation, consolidation and abstraction (`form_abstractions`, `reflect_on_beliefs`),
tiering, and governed parameter changes.

### 3.4 Execution — the coordinator's execution faculty
`coord.execute_task(task)` is substrate-first: run a proven grounded operator
(`_execute_grounded_operator`) → plan a state goal over learned operators and drive
it (`_drive_substrate_goal`) → run declared tools or answer via the knowledge loop
(`_execute_operation` / `_answer_via_knowledge_loop`) → honest gap. No model path.
Acting records demonstrations that feed learning.

### 3.5 Domain modelling — `core/integration/universal_domain_master.py`
`UniversalDomainMaster` (`coord.universal_domain_master`): the one authority that
`ensure_domain`, `crystallize`s subjects automatically from taught/learned concepts,
consolidates same-vocabulary subjects, and answers cross-domain queries
(`coord.perform_cross_domain_reasoning`).

### 3.6 Intrinsic motivation — `core/agents/autonomous/intrinsic_motivation.py`
`coord.intrinsic_motivation`: surfaces exploration targets from measured epistemic
uncertainty (`get_top_exploration_targets`, over `epistemic_engine.get_unstable_regions`).
Attention follows what is uncertain and learnable, not a fixed agenda.

### 3.7 The self — in the coordinator
A first-class model of the system's disposition, competence, and continuity
(`state`, `render`, `identity_prompt`, `disposition`, `_appraisal`, `_temperament`,
`_competence`, `_purpose`). The coordinator reads it to describe and govern itself.

### 3.8 Grounded task completion — in the coordinator
Completion is a belief, formed on the execution path
(`_derive_completion_anchor` → `_mint_completion_belief` →
`_observe_completion_evidence` → `_decide_completion`). It combines **DID**
(execution-side evidence: the action reported the effect) with **SAW** (a fresh,
independent re-observation, `_saw_reobserve`), collapses correlated evidence to
independent groundings (`_independent_groundings`), and accepts only past the
substrate's own doubt.

### 3.9 Epistemic governance
A derived proposition may be held in soft cognition but is prohibited from becoming
authoritative or acting until it passes **independent, non-circular validation**
(the operator promotion gate in `rule_store.validate`; the belief independence
collapse). Separates the ability to derive from the authority to persist and act.

---

## 4. Cross-faculty loops

- **Experience → learning:** action → outcome → experience → operators/knowledge → next plan.
- **Completion:** action → DID + independent SAW → completion belief → done / recovery.
- **Intrinsic learning:** competence gap → epistemic uncertainty → exploration target
  → experience → competence update → uncertainty falls.

Each loop crosses several faculties; removing any one breaks it. This is what makes
the substrate one system rather than co-resident parts.

---

## 5. Coordination and standing operation

- **One coordinator, one shared state.** One authority per state kind
  (learning, domain, beliefs, concept graph).
- **Reactive event spine:** `on` / `emit` / `_reactive_drain_worker`; reactions
  (`_react_*`) let one faculty's outcome wake another (a demonstration triggers
  induction, an admitted fact triggers domain crystallisation, a health event
  triggers recovery).
- **Standing background tiers** (13, on one scheduler, `_register_idle_subsystems`):
  security, health & recovery, system review, knowledge refresh, self-improvement,
  meta-learning, memory consolidation, self-optimisation, domain expansion/discovery,
  operator exploration/induction, analogy discovery. Plus a constitutional self-check.

---

## 6. Running it

Canonical runtime: `./venv_torin/bin/python3` (Python 3.11). Postgres at
`127.0.0.1:5433`, database `torinai_db`. Bring the substrate up:

```python
from core.main import get_system
system = get_system(); await system.initialize()
coord = system.autonomous_coordinator
```

Environment: `PYTHONPATH="$PWD"`, `POSTGRES_PORT=5433`, `TORIN_NO_WATCHDOG=1`.

---

## 7. Repository layout

- `core/` — the substrate. Key subsystems: `agents/autonomous` (the coordinator),
  `reasoning`, `learning`, `memory`, `execution`, `domain`, `integration`,
  `semantics`, `governance`, `security`, `health`, `tools`.
- `experiments/` — reproducible, self-contained studies (each a folder with
  `experiment.py` + `manifest.json` + `README.md`); worlds and machines the
  experiments run in; `systems/` for in-situ system studies.
- `tests/` — the test suite, organised by subsystem.
- `docs/` — architecture and design docs. This file is the entry point; the
  method-level map is `SUBSTRATE_SYSTEMS_MAP.md`.
- `scripts/` — operational scripts.

---

## 8. Verification

The faculties above are exercised in situ on the running system, model-free where a
model is not the point, in `experiments/systems/VERIFY-01` (reasoning, execution,
cross-domain, domain, learning + beliefs, intrinsic motivation, memory — all live).
Individual mechanisms are studied in depth under `experiments/` (operator induction
and its causal ablation; derived reading; knowledge vs. competence; grounded
completion; the governance boundary).
