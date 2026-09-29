# SYSTEM-LEARNING-01 — the learning authority, alone, with no stubs

**Finding (2026-09-26): behaviour 23/23; three wiring findings, zero completeness findings.** One
learning authority (`UnifiedLearningSystem`): a told fact is admitted once and moves a belief, a malformed
fact is refused, and demonstrations become a rule through the induction the substrate drains itself.

**Every stub is real learning now.** Every learning stub must be real learning, connected to the real learning
authority; half-implemented code and stubs are never approved. Five methods raised
`NotImplementedError` (each had once returned a fabricated constant) and `shutdown` did nothing:

| method | what it does now | who calls it |
|---|---|---|
| `consolidate_learning` | puts every open known unknown through the resolution gate; closes meta-learning decisions whose outcome will never arrive (INDETERMINATE, credit-free); persists trained clause classifiers | the `idle_learning_consolidation` tier (900 s) |
| `shutdown` | drains in-flight event learning; persists classifiers | `main.py` shutdown (which used to save classifiers itself) |
| `update_strategy_effectiveness` | records a strategy's outcome with the meta-learner (credit gate, persisted posterior) and checks the prediction made at decision time (calibration) | the coordinator's adaptive task-type outcome |
| `recommend_strategies` | ranks a family's arms by the Wilson lower bound of their measured success | the coordinator's idle meta-learning evaluation |
| `predict_outcome` | the Beta(successes+1, failures+1) posterior mean the bandit samples from, with its interval and evidence; None with no evidence | made when the coordinator chooses a task type, carried to the outcome |
| `predict_optimal_retry_delay` | Thompson sampling over waits on expected time to recovery (delay / P(success)), each wait an arm of the meta-learner per component | the health tier's recovery retries (replacing a fixed table) |

It also owns **resolving known unknowns** (`resolve_known_unknown`, `resolve_open_unknowns`): resolved only when
the knowledge is held, the belief is settled and grounded, and the domain holds it — see SYSTEM-BELIEFS-01.

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site; the two accessors name it |
| **B** | a told fact enters once, moves a belief, is in the graph; a repeat is not admitted twice |
| **C** | a malformed fact (empty subject) is refused |
| **D** | demonstrations are recorded, the pending induction drains, a rule is induced |
| **F** | no evidence → no prediction; six outcomes move it to (5+1)/(6+2); the winning arm is recommended over the losing one; a decision-time prediction is checked against the outcome; an unknown family is refused; retry waits are from the learner's set, and after short waits keep failing and 120 s keeps recovering, 120 s is chosen most and unsupported long waits never; a wait outside the set is refused as evidence; consolidation reports all three steps |
| **E** | metrics readable |

**Wiring findings:** `process_interaction` is called by nothing; `train_clause_classifier` (the clause-population
recognizer) and `induce_causal_structure` are exercised only by experiments (FALSIFY-01, RECOGNISE-02, EDU-12) —
real capabilities not yet wired into the substrate.

**The trap in measuring it.** A retry learner that optimises expected time to recovery keeps trying a cheap
wait with a poor record now and then — a 15 s wait that failed 12 times still has ~7% chance, ~211 s expected
against ~129 s for a 120 s wait that recovered 12 of 12 — so "the learner always waits 120 s" is the wrong
expectation; "120 s is chosen most" is the right one. And consolidation is global: it sweeps every open known
unknown and reaps abandoned decisions on the live store (the first run closed 1,870 abandoned decision rows) —
a sweep checks without counting a resolution attempt.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-LEARNING-01/experiment.py
```

Its probe facts, demonstrations, rules, domain, and strategy/retry arms are removed by id. Each run writes
`results/<UTC timestamp>.json` with a `.md` beside it, reporting **behaviour** (pass/fail), **wiring** and
**completeness** findings apart (`experiments/_isolation.py`).
