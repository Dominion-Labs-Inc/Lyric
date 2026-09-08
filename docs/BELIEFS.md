# Beliefs — the substrate's revisable model of the world

*Reference. Traced against code 2026-09-06. What a belief is, what moves it, what
it touches, and how it persists.*

A **belief** is a proposition the substrate holds with a probability, revisable as
evidence arrives. Beliefs are the substrate's model of the world and of itself:
what is true, how confident it is, and what it does not yet know. They are
**universal and revisable** — what it believes today, evidence can move tomorrow.

---

## What a belief is (`BayesianBelief`, `core/reasoning/bayesian_uncertainty.py:87`)

| Field | Meaning |
|-------|---------|
| `belief_id` | stable id |
| `claim` | the proposition (e.g. "a robin is a bird", "the goal of task T holds") |
| `domain` | the knowledge domain it belongs to |
| `prior_probability` | P(H) before evidence |
| `likelihood` | P(E\|H) |
| `posterior_probability` | P(H\|E) — the current confidence |
| `evidence_for` / `evidence_against` | the observations that moved it |
| `uncertainty_type` | epistemic (default) vs aleatoric |
| `entropy` | information-theoretic uncertainty |
| `decay_rate` | domain-adaptive λ for temporal decay |
| `update_count`, `last_updated` | provenance of change |

Related structures: `BeliefRelationship` (belief A ↔ B, for constraint
propagation), `KnownUnknown` (a registered ignorance — a belief *gap*),
`ConfidenceCalibration` (per-domain over/under-confidence correction),
`domain_volatility` (per-domain λ, learned by reflection).

## The one authority

The belief substrate is `BayesianUncertaintySystem` (`get_uncertainty_system()`).
Every write goes through **one authority**, `UnifiedLearningSystem` (`self.learning`
on the coordinator), which exposes `create_belief` / `update_belief` /
`observe_claim` / `get_belief` / `belief_for_claim` / `beliefs_for_domain` /
`flush_belief` and delegates to the substrate. A belief is a knowledge write like
any other — a reasoning conclusion, a taught fact, a perception, a tool outcome all
move the SAME store by one door, not each reaching the substrate directly.

- `create_belief(claim, domain, prior, evidence=None, source)` — mint. With no
  evidence the belief stands exactly at its prior (source is provenance, not an
  observation).
- `observe_claim(claim, domain, supports, quality, source)` — idempotent
  find-or-create-by-claim + one observation. The first telling mints it; each later
  telling moves the SAME posterior.
- `update_belief(id, evidence, evidence_supports)` — a Bayesian update on an
  existing belief.
- `get_belief(id)` / `belief_for_claim(claim)` / `beliefs_for_domain(domain)` —
  reads.
- `flush_belief(id)` — durable, awaited, committed persistence (for
  decision-critical beliefs).

## What CONTRIBUTES to beliefs (what moves them)

Every one of these is an *observation* that moves a posterior — the substrate
learning from experience.

| Source | Mechanism | Moves |
|--------|-----------|-------|
| **Teaching / learning** | `_fan_out_learning` → `observe_claim(claim, domain, supports, "taught")` (`unified_learning_system.py`) | a taught fact/rule/word moves its claim's posterior |
| **Task / tool outcomes** | post-tool seam `_observe_tool_belief` → `neural_bridge.observe_tool_result` → `epistemic_engine.observe_tool_result` (`autonomous_coordinator.py`, `neural_bridge.py:1170`) | capability beliefs — the substrate learns what its tools do, from success/failure |
| **Task completion** | `_observe_completion_evidence` → DID/SAW groundings → `update_belief` on the completion belief (`autonomous_coordinator.py`) | the belief "the goal of task T holds" |
| **Reasoning conclusions** | `epistemic_engine.apply_reasoning_output`, `hypothesis_testing`, `abstract_reasoning_engine`, `hierarchical_abstraction` — all route through the authority | beliefs concluded by inference |
| **Research / perception / evidence** | `evidence_producers` → `fan_out_ingested` → `_fan_out_learning` | beliefs from admitted research/perception |
| **Domain competence** | `universal_domain_master.record_competence_evidence` → `flush_belief` (durable, every update) | per-domain competence beliefs — decide what the substrate explores after restart |
| **Temporal decay** | `decay_belief` / decay applied inside `update_belief` | drifts an unreinforced belief toward 0.5 so stale confidence erodes and is re-verified |
| **Reflection** | domain volatility (adaptive λ), regime-shift detection | how fast a domain's beliefs decay; flags reversals |

**Contributor call-site density** (traced): `epistemic_engine` (8),
`unified_learning_system` (5), `universal_domain_master` (5), `bayesian_uncertainty`
(4, internal), `autonomous_coordinator` (4), `hypothesis_testing` (2),
`abstract_reasoning_engine` (2), `neural_bridge` (1), `hierarchical_abstraction` (1).

## What beliefs TOUCH (what reads them)

| Consumer | Uses beliefs for |
|----------|------------------|
| **Reasoning** (`neural_bridge`, 9 sites) | reasons over held beliefs; consults them in inference |
| **Completion** (`autonomous_coordinator`) | reads the completion belief's posterior to decide DONE (≥ 0.95) |
| **Memory** (`memory_agent`, 7 sites) | stamps every memory with `belief_state` — the aggregate AND the domain's specific `relevant_beliefs` (claim + posterior) at the time |
| **Motivation / curiosity** (`intrinsic_motivation`, 3 sites) | known-unknowns and unstable beliefs drive what the substrate explores |
| **Epistemic exploration** (`epistemic_engine`, 3 sites) | belief changes surface/resolve unstable regions, driving the exploration loop |
| **Domain competence** (`universal_domain_master`, 5 sites) | competence beliefs decide explorable domains |
| **Execution control** (`iteration_controller`, `convergence_gate`) | belief state informs when to stop iterating |
| **Health** (`health_monitor`, 2 sites) | belief-graph stats as a liveness/coverage signal |

**Consumer call-site density** (traced): `neural_bridge` (9),
`unified_learning_system` (8), `memory_agent` (7), `autonomous_coordinator` (6),
`universal_domain_master` (5), `epistemic_engine` (3), `abstract_reasoning_engine`
(3), `intrinsic_motivation` (3), `hypothesis_testing` (2), `health_monitor` (2),
`hierarchical_abstraction` (1), `iteration_controller` (1), `convergence_gate` (1).

## Update dynamics (why beliefs don't ossify or over-multiply)

- **Bayesian update** — `posterior ∝ P(E|H)·P(H)`, evidence weighted by `quality`.
- **Temporal decay** — applied before each update (and by `decay_belief`): an
  unreinforced belief drifts toward 0.5, so stale/false confidence erodes,
  re-enters the unstable set, and is re-verified against the world.
- **Regime-shift detection** — a posterior crossing 0.5 is logged as a belief
  reversal; repeated reversals raise the domain's volatility.
- **Domain volatility** — per-domain λ, learned by reflection and persisted, so a
  fast-changing domain decays faster than a stable one.
- **Confidence calibration** — per-domain over/under-confidence correction.
- **Evidence independence (completion beliefs)** — correlated evidence collapses;
  only independent causal pathways (DID vs SAW) compound, so confidence cannot be
  faked by re-counting one observation. (See `TASK_COMPLETION_THESIS.md`.)

## Persistence and durability

- Stored in `unified.beliefs` (PostgreSQL). The DB is boot **Phase 2**, up before
  any belief update.
- **`load_from_db`** restores the whole belief graph on startup (`main.py:644`), so
  epistemic state survives restart; `_load_domain_volatility` restores adaptive λ.
- **`_save_belief`** — fire-and-forget for high-frequency updates; **`flush_belief`**
  — durable, awaited (competence beliefs, and a task's completion belief once its
  evidence is in).
- **Buffer-and-replay** — a write that cannot reach the DB is buffered in
  `_pending_writes` (latest state per belief) and replayed by `flush_pending_writes`
  (on `load_from_db` and every `flush_belief`), so no epistemic update — including a
  correct reversal — is ever silently dropped. `persistence_drops` stays observable.

## The completion belief as a worked example

A task's completion belief ("the goal of task T holds") is a first-class belief:
minted low (0.15 = not yet done), moved only by grounded, independence-checked
DID/SAW evidence, judged done at posterior ≥ 0.95 (raised by caution), flushed
durably, and re-locatable by its claim after restart. It is the model of "the
substrate knows it is done" expressed entirely in the belief substrate — no
separate completion machinery. Full design in `TASK_COMPLETION_THESIS.md`.

## Changelog

- **2026-09-06** — Authored. Traced contributors/consumers against code; documented
  structure, the one authority, update dynamics, and durability (buffer-and-replay).
  Added `beliefs_for_domain` and per-memory `relevant_beliefs` capture.
