"""PER-USER-CONCURRENCY-01 — the substrate runs multiple tasks PER USER, fairly, under a global cap.

Concurrency used to be one global cap (default 3) shared by everyone + the substrate's own work, with
no per-user notion. Now: each USER may hold up to `per_actor_max_tasks` concurrently (so a user runs
several tasks at once), a user at their cap is SKIPPED so they can't monopolise the pool (others still
run), and the SUBSTRATE's own work is exempt from the per-user cap (bounded only by the global ceiling).

  1. Selection skips a capped user's jobs and serves the other users' — capped jobs stay queued (not lost).
  2. With the capped user unskipped, their jobs are served again (nothing was dropped; priority kept).
  3. The coordinator caps USERS at per_actor_max but never the substrate (its autonomous work is exempt).
  4. Reap releases a user's slots, so a finished task frees capacity for that user's next one.

Run: ./venv_torin/bin/python3 experiments/PER-USER-CONCURRENCY-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.agents.autonomous.queue_authority import QueueAuthority
    from core.agents.autonomous.autonomous_coordinator import create_autonomous_system
    from core.agents.autonomous.shared_types import (Task, TaskType, Priority,
                                                    TaskSource, SUBSTRATE_ACTOR,
                                                    is_substrate_actor)

    A, B = "user:A", "user:B"
    def mk(actor, n):
        return Task(id=f"{actor}:{n}:{uuid.uuid4().hex[:6]}", type=TaskType.ANALYSIS,
                    description="x", priority=Priority.HIGH, source=TaskSource.API, actor=actor)

    print("\n== 1. a capped user is skipped; other users are served; capped jobs stay queued ==")
    q = QueueAuthority(config={"max_parallel": 6})
    a_tasks = [mk(A, i) for i in range(4)]
    b_tasks = [mk(B, i) for i in range(2)]
    for t in a_tasks + b_tasks:
        await q.add_task(t, priority=Priority.HIGH)
    # A is at its per-user cap -> skip A. Pull until no eligible job remains.
    served = []
    while True:
        nxt = await q.get_next_task(timeout=0.1, skip_actors=frozenset({A}))
        if nxt is None:
            break
        served.append(nxt.task)
    check("only the non-capped user's jobs were served",
          {t.actor for t in served} == {B} and len(served) == 2,
          f"served actors={[t.actor for t in served]}")
    check("the capped user's jobs are NOT lost (still queued)",
          all(q.tasks_by_id[t.id].status.value != "completed" for t in a_tasks)
          and q.queue.qsize() == 4, f"qsize={q.queue.qsize()}")

    print("\n== 2. with the user unskipped, their jobs are served again (priority preserved) ==")
    nxt = await q.get_next_task(timeout=0.1)     # no skip
    check("the previously-capped user is now served", nxt is not None and nxt.task.actor == A,
          f"actor={getattr(getattr(nxt,'task',None),'actor',None)}")

    print("\n== 3. the coordinator caps USERS but exempts the substrate ==")
    coord = await create_autonomous_system({})
    coord._per_actor_max = 3
    coord._inflight_by_actor = {A: 3, B: 1, SUBSTRATE_ACTOR: 5}
    capped = frozenset(a for a, n in coord._inflight_by_actor.items()
                       if not is_substrate_actor(a) and n >= coord._per_actor_max)
    check("a user at the cap is capped", A in capped)
    check("a user under the cap is not", B not in capped)
    check("the substrate is NEVER capped (exempt even at 5 in-flight)", SUBSTRATE_ACTOR not in capped,
          f"capped={capped}")

    print("\n== 4. reap releases a user's slots ==")
    # two finished tasks for user A in flight -> reap -> A's count drops to 0 (uncapped again)
    coord._inflight_tasks.clear(); coord._inflight_by_actor.clear(); coord._inflight_actor.clear()
    for i in range(2):
        tid = f"{A}:done:{i}"
        fut = asyncio.get_event_loop().create_future(); fut.set_result({"ok": True})
        coord._inflight_tasks[tid] = fut
        coord._inflight_actor[tid] = A
        coord._inflight_by_actor[A] = coord._inflight_by_actor.get(A, 0) + 1
    check("user A is at cap before reap", coord._inflight_by_actor.get(A) == 2)
    coord._reap_finished_tasks()
    check("reap released A's slots (count cleared, uncapped again)",
          coord._inflight_by_actor.get(A, 0) == 0 and not coord._inflight_tasks,
          f"by_actor={coord._inflight_by_actor}")

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
