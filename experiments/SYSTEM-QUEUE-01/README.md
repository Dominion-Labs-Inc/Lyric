# SYSTEM-QUEUE-01 — the queue authority, alone, on the live substrate

**Finding (2026-09-26).** The first runs passed every behaviour check and listed **8 public methods of
`QueueAuthority` that nothing in `core/` called**. Each one turned out to be a second copy of something
the queue already did under another name. After collapsing them, the authority has 29 public methods
(it had 35), with **0 wiring findings**:

| was | the one method now | what the copy got wrong |
|---|---|---|
| `try_get_task` | `get_next_task(timeout=0)` | skipped the durable write and the per-user skip. And `get_next_task(timeout=0)` returned None **with work queued**: `wait_for(get(), 0)` cancels the get before it runs |
| `get_task_status` | `result_for(task_id, actor=)` | read any actor's task; never reported a failure's error; `include_details` did nothing |
| `has_active_task` | `active_tasks()` | a third copy of "active" sat in the coordinator's exploration scan (PENDING/IN_PROGRESS only), a fourth in `QueuePersistence.RESTORABLE_STATUSES` |
| `execute_batch` | `execute` | `execute` inside `gather`, left over from the old batch dispatch |
| `schedule_after` | `submit(..., delay_s=)` | its outcome was dropped: the job was removed from the scheduler before it ran |
| `unschedule` | `cancel(job_id)` | one way to stop an await job, another to stop a scheduled one |
| `reschedule` | `schedule_recurring` (same name) | re-registering already retuned the cadence, but discarded the job's run/error record |
| `prune_history` | *(no twin: wired)* | nothing bounded `unified.task_queue`; `start()` now schedules `queue_history_prune` |

**Properties checked** (behaviour; wiring and completeness are reported separately, never as failures):

| # | property |
|---|---|
| A | one authority: the coordinator holds the instance the accessor returns, constructed in one place |
| B | work is admitted and drawn in order; the non-blocking pull returns nothing from an empty queue and the ready job from a non-empty one; drawn work is active until it finishes; its result is readable by its owner and `not_found` to anyone else |
| C | admission control defers discretionary work at the soft limit and never defers a user's or urgent work |
| D | a job's value comes back; a failed job comes back as an error, never as a result |
| E | a recurring job fires; registering its name again retunes it and keeps its record; `cancel` stops it and reports an unknown id as unknown; a timed one-shot waits out its delay, runs once, and returns its value |
| F | one copy per id: a second add of a queued or running id adds no copy and reports it queued; a finished id may be queued again; five simultaneous adds leave one copy; across two instances on the one table, an id a living instance holds is not taken over, and is taken once that instance stops |
| — | statistics are flat scalars; the durable queue's pending count is unchanged |

**The trap in measuring it.** A zero-timeout pull that says "nothing ready" looks exactly like an empty
queue. Section B puts a job on the queue first, so an empty answer is a failure rather than a pass.
Every probe queue is built with `persist: False` except section F's two instances, whose rows and
heartbeats are removed by id; the run compares the durable queue's pending count before and after.

**Run** (from the TorinAI folder; boots the full system, so check that
`pgrep -fl "experiments/.*/experiment.py"` is empty first):

```
./venv_torin/bin/python3 experiments/SYSTEM-QUEUE-01/experiment.py
```

**Results.** Each run writes `results/<UTC timestamp>.json` and a `.md` summary beside it.
`20260926T175940Z`: behaviour 18/18 · wiring findings 0 · completeness findings 0 · pending 0 → 0.
`20260928T130915Z` (section F added): behaviour 24/24 · wiring 0 · completeness 0 · pending 0 → 0. Section F's
two-instance leg writes probe rows to `unified.task_queue` and deletes them by id in a `finally`.
