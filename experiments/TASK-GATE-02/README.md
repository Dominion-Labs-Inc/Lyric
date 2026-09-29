# TASK-GATE-02 — does the task gate ask INTENT whether the pursuit is still live?

**What it found.** The task gate asked two things — *is the substrate halted* and *has
this task's plan been withdrawn* — and never asked the faculty that owns the answer to
*is this work still anyone's to do*. Intent is the substrate's own account of what it is
trying to do and why: owned by reasoning, durable, with a lifecycle (`forming → active →
fulfilled / abandoned / refused`). The constitution, the planner, exploration, memory and
reconciliation all read or write it. The gate did not.

Three defects, measured before the change:

- **The gate read the plan, not the pursuit.** A step of a pursuit that had already
  concluded would start if its plan still read `active`.
- **A return to a concluded pursuit did not reopen it.** A goal whose first route stopped
  was reconciled `abandoned`; the planner then proved a second route and recorded it
  through `form` — same intent, version 3, the new rule on its shape — and the status
  stayed `abandoned`, carrying the *first* route's outcome. The substrate was pursuing a
  goal its own record said it had given up.
- **Drive goals went around the gate.** `_execute_and_validate_task` routed them straight
  to `_execute_drive_goal`, around `execute_task` — so the one boundary that claims
  everything comes through it did not see them, and a halted substrate would start one.

## What changed

| | |
|---|---|
| `_task_gate` | a third question, asked of the intent authority by id, shape view: **concluded → refused, not held → refused, live → proceeds, none named → proceeds and is counted** |
| `IntentAuthority.form` | a RETURN to a concluded pursuit reopens it (`active`); the ended attempt is kept on the actor-free shape (`earlier_attempts`) and in history |
| `refresh` history | records the full previous state — status and outcome included, not only shape and content |
| `execute_task` | drive goals are routed here, after the gate |
| `intent_authority.LIVE / CONCLUDED` | the lifecycle sets, named once by their owner (`standing` spelled them inline) |

## The four properties

| | |
|---|---|
| **A** | the gate asks intent — concluded or unrecorded → refused, live → proceeds; a task's own claim about its pursuit's status changes nothing |
| **B** | absence is reported, not filled in — no intent named → proceeds, is counted, and no intent is formed at the door |
| **C** | a return reopens a concluded pursuit — same identity, the ended attempt's lesson kept; reasoning *settling* a pass does not reopen it |
| **D** | one door — a drive goal meets the same gate (halted → never starts; ended pursuit → refused; open → reaches its executor) |

**B is the design line.** Intent is reasoning's to form. An account manufactured at the
door would be exactly the second, weaker account of why the substrate acts that the
intent authority exists to prevent — so a task with no intent passes the gate, is
counted, and meets Law 2 at the tool gate carrying no intent.

## Asymmetric failure, as in TASK-GATE-01

The halt check fails closed. The intent read, like the plan read, does not: being unable
to read the record is not evidence that the pursuit ended, and the act still meets the
tool gate, where the constitution reads the intent again and judges an unreadable one
as none stated. A wiring defect in the read (`raise_if_structural`) is raised, never
treated as "unreadable".

## What this did NOT show when it was written — both closed the same day

- **No queued task named a pursuit** (0 of 293). Every producer now forms the pursuit where
  it takes the work on, and the task's ending closes it — PURSUIT-01.
- **Nothing in the live path wrote `refused`.** Every constitutional verdict is now recorded
  on the pursuit it stopped — `replanned`, `redirected`, `refused`, or `halted` for the halt's
  own BLOCK — and the gate does not repeat work the law sent back — PURSUIT-01. This
  experiment still reaches `refused` by reconciling its probe directly, which is what it tests:
  the gate's READ of the status.

## Run

```
./venv_lyric/bin/python3 experiments/TASK-GATE-02/experiment.py
```

Runs a LIVE substrate, halts it on purpose and resumes it, and removes every intent it
wrote (content rows by its probe actor, shape rows by id). Each run writes a structured
record to `results/<timestamp>.json` with a `.md` summary beside it.
