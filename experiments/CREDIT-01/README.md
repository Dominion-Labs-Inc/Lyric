# CREDIT-01 — meant-vs-happened becomes the substrate's operating credit

**What it tests.** The substrate already collects evidence: every executed step is verified against the
re-observed world, filed as a demonstration, and allowed to revise the rule it came from. So the credit
signal worth building is **not a new number** — it is the one credit that already governs behaviour,
answered by what the substrate now owns.

That signal is `operating_reliability`. Its own code says it asks *"did the operation achieve its
intent?"*, and it is consumed twice: by the **KNOW→DO operability bar** (`_domain_operability`), which
decides whether the substrate may act in a domain at all, and by **`PlanInput.OPERATING_RELIABILITY`**,
which every state plan declares as an input.

## What was measured before any code changed

| Probe | Result |
|---|---|
| a goal the substrate could not **plan** — nothing executed, no tool invoked | `operating_attempts 0→1, wins 0→0` — an operating **loss** for work never operated |
| a goal that **was** reached (file on disk, intent `matched_aim: true`) | win recorded, while the same task's completion decision said **not accepted** |

The first matters most: a falling `earned` **raises** the bar, so not knowing how to act in a domain made
the substrate less free to act there. The remedy for a knowledge deficit was closing the door on itself.

## Sections

| Section | What it establishes |
|---|---|
| A · the invariant | the credit invariant is enforced at the **authority**, not at call sites: outcomes that establish nothing about operating cannot move the posterior, do not enter the **denominator**, and an unclassified call is denied |
| B1 · never operated | a goal that would not plan credits nothing; the deficit is still diagnosed and still reaches appraisal |
| B2 · aim realized | 5 real drives moved the file; 5 wins, read from the **belief** the reconciled intent grounded — and the substrate now *believes* it, **5/5** accepted where **0/5** were before |
| B3 · aim missed | every step's runtime evidence CONFIRMED and the aim was still unrealized — the case per-step evidence cannot see. Credited a loss, believed as a miss, **no operator taught anything** |
| D · conflict | belief and world disagreeing is **denied**, not resolved in favour of either — and the guard is checked not to be swallowing the real runs |
| C · consumed | earned reliability, the KNOW→DO bar, and the planner's declared input all carry the corrected number |

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/CREDIT-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-17, **25/25**
(`results/20260917T033841Z.md`).

## Why B3 is built the way it is

The miss is produced **without making any operator fail**. An external actor (the experiment) moves the
file back *after* the step was verified. Nothing false is taught: the move really happened and the step's
own evidence is a genuine CONFIRMATION. What the substrate must notice is that its **aim** was still not
realized — which no per-step verification can hold, because `verify_effects` only ever checks a rule's own
predicted effects against the world.

This is the discipline INTENT-04 paid for: an experiment that writes to shared learned state can corrupt
it as easily as any other writer. B3 asserts the rule statuses are identical before and after.

## What is real here, and what is not

Real: the domain authority (`record_operating_outcome`, `operating_reliability`), the planning authority
(`create_goal`, `plan_for_goal`, `assemble_inputs`), the intent authority through the coordinator's own
reconciler, the rule store, the binding registry, the real `tool_registry.execute_tool` moving a real
file, `_domain_operability`, and real Postgres. The oracle is the filesystem.

Four substitutions, all observational:

- `task_queue.mark_completed` / `mark_failed` — recorders. The task is not enqueued, so the queue cannot
  update it; this captures the completion **decision** only.
- `coord.execute_task` — a pass-through that calls the real method and records its return, because
  `_execute_and_validate_task` returns `None`.
- `coord._execute_grounded_operator` (section B only) — calls the **real** method, then changes the world
  on disk afterwards. The experiment acting as an external actor, not replacing substrate logic.
- `coord._permanently_failed_fps` — restored at the end, because a task whose completion belief misses the
  acceptance band is fingerprinted and persisted for the session.

Section C's `_operating_verdict(...)` assertions call that method directly to check the verdict's
**provenance**. The *live* invocation is proven by the counter deltas, not by those calls.

Non-polluting: the domain's operating counters are snapshotted and restored, the synthetic domain of
section A is deleted, and every intent the run creates is removed.

## The belief is in the loop, not bypassed

An earlier version of this work read the credit straight off the reconciled intent, routing *around* the
belief system. That was wrong: the substrate still has to **believe** its intention was realized, and
going around the epistemic authority would leave two accounts of the same act.

What was actually broken was the belief's blindness. `_saw_reobserve` had one world-re-observation branch,
gated on `execution_path == "substrate"` and a single rule's `effects`. A driven plan is
`execution_path == "substrate_plan"` carrying **goal conditions**, so it matched nothing, got no SAW
grounding, and sat on DID alone (~0.72) against a 0.95 acceptance band — five verifiably-successful drives
accepted **0/5**.

Now a fresh `observe_world` checks the plan's goal conditions, which is what it *meant*. The belief moves
on its own independent look, and the credit follows the belief:

- eligibility first — work that operated nothing establishes nothing, and is denied;
- the verdict is the belief, with `read_from` naming what grounded it;
- **belief and world disagreeing is denied**, `INDETERMINATE`, logged. Neither is overruled.

The reconciled intent's verdict is deliberately **not** fed in as belief evidence. It came from the
reconciliation's own observation; feeding it in too would let one look at the world count twice —
correlated evidence wearing the shape of corroboration.
