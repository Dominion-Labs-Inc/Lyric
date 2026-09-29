# TASK-GATE-01 — does a refused route stay refused?

**What it found.** Two holes with one shape: the constitution is upstream of task
dispatch, and one of its four verdicts reached nobody.

**`Verdict.REPLAN` was a label.** Its entire content is *"this is not the route, plan
again"*. It is produced in five places, and **no code in the tree branched on it.** So a
route the constitution had rejected stayed the ACTIVE route: every dispatch of it was
refused again at the tool gate, forever, and the goal it served was never repaired — a
livelock the laws themselves diagnosed on every pass.

**`execute_task` asked nothing.** It is the one door every task comes through, and it ran
whatever arrived, including a step of a plan the substrate had already decided was no
longer the route. The only gate was the tool gate, one layer in.

## The seven properties

| | |
|---|---|
| **A** | a REPLAN verdict withdraws the route — the near half, beside the refuted-rule one |
| **B** | and blames no rule — "not this act" is not "this operator is wrong" |
| **C** | a withdrawn route's step does not run |
| **D** | a halted substrate starts nothing — asked of the law, not a flag read |
| **E** | it is NOT a second judge — an ordinary task is not refused |
| **F** | an unreadable plan does not stop work — absence of evidence is not withdrawal |
| **G** | the gate fails closed on the halt — an unanswerable boundary has permitted nothing |

**B is the one that matters.** `rule_ids=[]` on the withdrawal, for exactly the reason the
refusal seam records no runtime evidence: the constitution said "not this act", never "this
operator is wrong". Withdrawing a route while blaming the rule would punish the substrate's
knowledge for the substrate's own law — the same false negative the executor already guards
against, one layer up.

**E and F are the experiment.** A backstop that refuses ordinary work, or that refuses
because the planner hiccupped, is worse than no backstop: it would stop the substrate
working for a reason that is not about the substrate. So the checks are negative controls —
a task on no plan, a task on a live plan, a task whose plan the engine no longer holds, and
a task whose DESCRIPTION is an imperative ("Delete the stale exports and remove the old
archive") must all proceed.

## Why the gate is not the full law chain

A task has a type and a description; it has no measured consequence, no arguments whose
capabilities can be read, no paths. Running the five laws against it would have them
answering a question nobody asked, and two of them would refuse nearly everything:

- **Law 2 transparency** REPLANs any act with no account, and a task is dispatched long
  before an account exists.
- **Law 3** reads params as content, so an ordinary imperative description would be judged
  as a directive found in content.

So the gate asks the one question answerable before an act exists and about the substrate
rather than the act — *is it halted* — through `Constitution.may_start`, which runs only
the halt law. Everything else it stops is a STATE READ: a plan marked `invalidated` is one
the substrate itself has already decided is no longer the route. The act is judged where
the act exists.

## Asymmetric failure, deliberately

The halt check **fails closed**: a boundary that could not be asked whether work may begin
has not established that it may. The plan-status read **does not**: being unable to read a
plan is not evidence that the plan was withdrawn, and the act still faces the tool gate.

## Run

```
./venv_torin/bin/python3 experiments/TASK-GATE-01/experiment.py
```

Runs a LIVE substrate, halts it on purpose and resumes it, and removes the probe plans it
registered. Each run writes a structured record to `results/<timestamp>.json` with a `.md`
summary beside it.
