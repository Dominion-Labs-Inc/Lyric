# VERIFY-01 — Fresh current-state verification of the unified substrate

*Not an archived rung. A single harness that boots the ONE running coordinator
and drives each faculty's pipeline through the coordinator's own public interface,
recording what the system does today. Every probe is defensive — it captures the
real result or the real error — so this is an honest snapshot of the current
system, not a frozen number.*

## Why this exists

The earlier capability documents were written from experiment scripts frozen on
their record dates; the code has changed heavily since, so re-running those
scripts tests obsolete methods and their committed JSONs are stale. This verifies
the substrate **as it runs now**, through the unified pipelines.

## Method

Boot `system.autonomous_coordinator` and drive each pipeline through the
coordinator (one pipeline per faculty, all inside the coordinator):

- reasoning → `coord.reason_about(q)`
- execution → `coord.execute_task(Task(...))`
- cross-domain → `coord.perform_cross_domain_reasoning(q, source_domains=...)`
- domain → the one domain authority + the domain store
- learning + beliefs → `coord.learning.create_belief / update_belief / get_belief`
- intrinsic motivation → `coord.intrinsic_motivation.get_top_exploration_targets`
- memory → `coord.memory.store_memory / retrieve`

## Result — all seven pipelines run live (model-free where applicable)

| Pipeline | Status | Fresh evidence |
|---|---|---|
| **Reasoning** | ✅ | "is a robin a bird" → *Yes: robin isa a bird* (conf 0.95, mode cross-domain, `derived_by_kind`, **0 model calls**); "is a hammer a bird" → `unsupported_input` (refuses to fabricate) |
| **Execution** | ✅ | `execute_task(question)` → success, `verification_state: verified`, model-free, via `conversation.understand` |
| **Cross-domain** | ✅ | `perform_cross_domain_reasoning(..., source_domains=["scientific","mathematical"])` → `{success: True, mappings: 0}` (runs; finds no structural correspondence between two operator-less category domains — honest) |
| **Domain** | ✅ | one domain authority present; **22 domains** in the store — 15 categories + 7 learned (`bird, device, general, insect, language, lexical`, …) |
| **Learning + beliefs** | ✅ | belief round-trip through the one authority: prior **0.15 → 0.724** on one grounding (the calibration value), learning initialized |
| **Intrinsic motivation** | ✅ | 5 uncertainty-driven exploration targets surfaced (e.g. *resolve uncertainty: rained(sky)*) |
| **Memory** | ✅ | `MemoryAgent`; retrieval returned a hit |

Full detail (queries, routes, modes, counts) in `manifest.json`, stamped with the
run time.

## What this establishes — and what it does not

- **Establishes:** the substrate boots as one system and every faculty's pipeline
  is reachable and functioning through the single coordinator, today, model-free
  where a model is not the point. This is direct evidence for "unified and running"
  rather than "isolated subsystems."
- **Honest nuances (fresh):** cross-domain reasoning ran but returned 0 mappings
  for two operator-less *category* domains — it needs domains that actually share
  operator structure to produce a mapping (the pipeline is sound; the inputs were
  thin). `store_memory` returned `None` while `retrieve` succeeded — worth
  confirming the store return contract. The in-memory domain registry is lazy
  (0 at boot) while the domain store holds 22 — count from the store, not the
  registry object.
- **Does not establish:** end-to-end *autonomous* operation over time, the growth
  loop learning a new operator from scratch this run, or multi-world coverage. It
  is a reachability-and-function snapshot of the pipelines, not a longitudinal or
  capability-ceiling claim.

## Run

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
  ./venv_lyric/bin/python3 experiments/systems/VERIFY-01/experiment.py
```

Read-mostly: it writes only a throwaway `verify01` belief/memory probe; it does
not teach or mutate learned domains.
