# PLANNING-01 — one planning authority, every planning step verified honest

**What it tests.** The planning faculty is what gives the substrate the ability to make plans, and
`self.planning` is the only place a plan is formed or operated on. This checks that claim, and for each
planning path that what it reports is **true** — a plan it calls proved really is proved, and a failure is
reported as a failure rather than quietly becoming a plausible-looking plan.

Real coordinator, real rule store, real learned operators, real Postgres. Nothing mocked.

| Section | What it establishes |
|---|---|
| A · One authority | the planner **is** `self.planning`; goals made through it are the goals it plans |
| B · True positive | a state goal with a real operator route plans by search, and every step is grounded in a learned rule; a proved plan states confidence 1.0 because it is proved, not estimated |
| C · No false positive | a state goal with no route returns UNREACHABLE with a real reason and **no plan** |
| D · The guard | template decomposition produces no plan for a state goal, and that refusal is **distinguishable from a generic failure** |
| E · Honest label | a descriptive goal's plan is labelled `template` and claims no learned rule behind its steps |
| F · Provenance | a template plan **declares where its confidence and duration came from**, and never presents an unmeasured value as evidence |
| G · Hierarchical planning | the absorbed abstraction-and-memory method runs against the real pipeline, records what it found as real ids, and emits **no prose steps** |
| H · Declared inputs | each **kind** of plan declares the inputs it needs, each is obtained **through the authority that owns it**, and anything missing is reported with a reason |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/PLANNING-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-16, **20/20**
(`results/20260916T192850Z.md`).

**2026-09-28: 39/39.** The hand-written filesystem domain was deleted. This now plans over an operator the substrate learned from its own acts in `tools:path` (taught by `experiments/fs_move_teach.py` if the store has none), and states its goal in perception's words: `KIND(<path>, Ffile)`, and `¬KIND(...)` for "no longer there".

## What this experiment found, and what was fixed after it ran

The first run (`20260916T192420Z`, 14/16) was the gate doing its job. It found three real defects, fixed
afterwards:

1. **The state-goal guard was swallowed.** `generate_plan` raised a deliberate `ValueError` for a state
   goal, but its blanket `except Exception` caught it and returned `None`, logged as "Error generating
   plan". The refusal held, yet a caller could not tell refusal from breakage. The guard now sits
   *outside* the try and propagates.
2. **Template confidence was invented** — `0.7` adjusted by task *count* (+0.2 if ≤3 tasks). It now reads
   the substrate's measured tool success rate from `tool_usage_history` via
   `AdaptiveToolLearning.metrics_summary()`.
3. **Template durations were hardcoded constants** (30/20/60 minutes per templated task, summed). They now
   come from measured tool latency, or are reported as `unmeasured`.

Where nothing has been measured, the plan says `unmeasured` and carries the neutral 0.5 — the same
discipline `operating_reliability` already uses ("optimism withheld BOTH ways until earned"), rather than
a number pretending to be evidence. Every plan now records `confidence_source` / `duration_source` in its
metadata.

**Two false passes in this experiment itself** were caught and fixed, because a gate that can produce false
positives is worthless:
- `c1 in (0.9, ...)` never matched the heuristic's actual `0.8999999999999999`;
- "duration differs from the old constant" passed on `0.0`, which is the *unmeasured* sentinel, not a
  measurement.

Both checks now assert **provenance** rather than the value, which is the property that actually matters.

## HierarchicalPlanner, absorbed

`HierarchicalPlanner` had **zero callers**. Its method is now
`PlanningEngine._hierarchical_context`: principles → schemas beneath them → strategy constraints (above a
0.7 strength floor) → episodic memory queried *within* those constraints. That is what makes planning
hierarchical, and it is how a plan draws on past memories rather than on the goal's wording alone.

Its **final step was deliberately not absorbed.** That emitted prose steps — `"Apply strategy: {when} →
{prefer}"`, `"Based on past: {action}"` — output shaped like a plan that proves nothing. Steps come from
proved operators; the absorbed method supplies the *context* a plan is formed in, as real ids. The
experiment asserts no such prose reappears. The orphaned class and its factory are deleted. A latent bug
came with it and was fixed: `search_memories` can return either a list or a `(ok, list)` pair, and the
original assumed a list.

**Honest limit of the current result:** the context comes back `available: True` with **empty** principles,
schemas and memories — the hierarchy holds no Level-3 principles for the queried domain yet, and no schema
clears the strength floor. The capability is wired and reports truthfully; it has not yet been exercised
with real hierarchical content. The domain is now passed through from the planning context rather than
always defaulting to `"general"`.

## Not every plan is the same — declared inputs, from their owners

A plan kind now states what it needs (`PlanInput` / `PLAN_KIND_INPUTS`), and the engine assembles exactly
that through the authority that **owns** each input — never by importing a store behind its owner's back:

| Input | Owner it is obtained through |
|---|---|
| `observed_world` | the **coordinator**, which perceives — the planner is given what it saw |
| `learned_operators` | the rule store |
| `operating_reliability` | the **domain authority** |
| `tool_history` | the **learning authority** |
| `abstraction` | the **reasoning authority**, which owns the abstraction pipeline |
| `episodic_memory` | memory, queried within the abstraction's constraints |

A **state** plan declares `observed_world`, `learned_operators`, `operating_reliability`; a **template**
plan declares `tool_history`, `abstraction`, `episodic_memory`. Every declared input is either gathered or
listed in `missing` with a reason — a plan formed without an input it declared is a plan formed on less
than it said it needed.

`episodic_memory` is named as the memory authority names it (`MemoryType.EPISODIC`), and the query is now
actually scoped to that type — the planner this came from claimed "episodic" in its docstring while
querying every memory type.

**Scope.** Covers the state-goal path, the template path, the guard between them, one authority, the
absorbed hierarchical method, and declared inputs routed through their owners. The dead alternate plan
entries in `temporal_reasoning` were removed. `_derive_goal_spec` / `_observe_world` deliberately stay with
the coordinator: it is the coordinator that observes the environment, and re-observing is how the substrate
verifies it achieved a goal.
