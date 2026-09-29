# PURSUIT-01 — does work carry WHY it exists, and end with what actually ended it?

**Asked (2026-09-25):** queued tasks should carry intent *"so that way the substrate is not
confused later on about why work exists in the first place, and it also helps with drift"* —
and *"Constitutional should not record refusals as abandoned; it's replanned, refused,
redirected, etc."*

**Measured before:**
- **0 of 293 queued tasks named an intent.** No producer recorded why its work existed.
- **Every constitutional refusal was reconciled `abandoned`.** `refused` was declared in the
  intent lifecycle and never written. The substrate's own record said it had *quit* pursuits
  its law had only sent back.
- **The declared-tool path returned an error string only**, so whatever closed the pursuit
  could not tell a refusal from a failure.
- **Nothing closed a pursuit that named no world state** — a task carrying one would have left
  it `forming` forever.

## What changed

| | |
|---|---|
| `AutonomousCoordinator.intend` | the ONE place work gets its why: formed through the intent authority where the substrate takes the work on, keyed on the goal it serves (one goal = one intent) or on the task. Shape = kind of pursuit / task type / raising faculty (anonymous); content = the words of the aim (the actor's) |
| producers | user requests (session recorded), intrinsic pursuits (drive goals, research, exploration — keyed on the persisted goal), error repair, knowledge refresh, agent work. A queue that refuses the work closes the pursuit `abandoned`, saying so |
| lifecycle | `halted` ("not now"), `replanned` ("not by this route"), `redirected` ("not in this form") are LIVE; `refused` (a BLOCK — "this may not happen") joins `fulfilled` / `abandoned` as CONCLUDED |
| reconciliation | the constitution's judgement reaches it from all three acting paths; **the world decides first** (an aim that holds is fulfilled however its act ended), then the verdict, then a miss |
| `Judgment.halt` | the halt's own BLOCK says it is the halt — read from the record, never from whether a halt still stands when the pursuit is closed |
| `conclude_pursuit` | the task runner's four endings (and agent work) close the pursuit: completed → `fulfilled`; stopped by the law → its verdict; otherwise `abandoned`. A record the world or the law already wrote is never overwritten; a plan step is not the owner |
| task gate | a pursuit the law SENT BACK does not have its stopped work repeated; a `halted` one resumes once the halt is lifted; planning's return reopens it |
| planner | a route proved while working on a pursuit is its CHILD (`parent_intent_id`), not merged into it |

A carried-out REDIRECT (the permitted form ran, on the declared-tool path) is how the work
proceeded, recorded in the outcome — never the reason it ended.

## The five properties

| | |
|---|---|
| **A** | work carries its why — user request, repair, agent work, and a proved route as the child of its pursuit |
| **B** | the law's word is recorded on real acts at the real gate: REPLAN (Law 2) → `replanned`, BLOCK (Law 3) → `refused`, a halt → `halted`; the world decides first |
| **C** | the work's end closes it — `fulfilled`, `abandoned` with why, `halted` even when closed after the halt was lifted; the law's record stands; a plan step is not the owner |
| **D** | the gate reads it — sent back is not repeated (naming the law), refused does not start, halted resumes, a return reopens |
| **E** | standing check, read from the source — every Task the coordinator enqueues is intended first; every ending of the task runner closes its pursuit; agent work is intended before and closed after |

**REDIRECT** is checked on the verdict→status map with a constructed judgement, labelled as
such: a real redirect is reachable only by a PROVED removal of a declared-sensitive target
(`~/.ssh/id_rsa`), which OPERATOR-REMOVAL-01 judges and — rightly — never executes.

**E is the guard.** A producer added later that enqueues work without saying why fails it.

## Found, not decided

`_idle_health_work` calls `task_queue.add_task(description=…, task_type="HEALTH_RECOVERY", …)`.
`add_task` takes a `Task`, and `TaskType` has no `HEALTH_RECOVERY` — so every health escalation
raised a `TypeError` that was logged as an "escalation notification error", and **no escalation
has ever reached the queue.** What an escalation should be (the substrate cannot do "manual
intervention" work) is a decision, so it is reported and left.

## Run

```
./venv_torin/bin/python3 experiments/PURSUIT-01/experiment.py
```

Boots the coordinator without its cognition loop (queued work is inspected, not run), halts it
on purpose twice and resumes it, and removes everything it wrote — intents, queued tasks, the
goal and plan it proved, demonstrations, pending-induction entries — by id. Each run writes a
structured record to `results/<timestamp>.json` with a `.md` summary beside it.

**2026-09-28: 27/27.** The hand-written filesystem domain was deleted. This now plans over an operator the substrate learned from its own acts in `tools:path` (taught by `experiments/fs_move_teach.py` if the store has none), and states its goal in perception's words: `KIND(<path>, Ffile)`, and `¬KIND(...)` for "no longer there". It now declares the operator the route is proved over.
