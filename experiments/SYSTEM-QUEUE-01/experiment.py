#!/usr/bin/env python3
"""SYSTEM-QUEUE-01 — the queue authority, alone, on the live substrate.

One authority (`QueueAuthority`, reached through `get_queue_authority`) owning
work, the pool and the scheduler. Work is admitted, drawn and completed;
admission control defers discretionary work under pressure and never defers a
user's; a job's failure comes back as an error, never as a result; a one-shot
schedule fires. A separate, unpersisted queue is used for the work leg so
nothing reaches the durable queue the live substrate restores from.

Run: ./venv_torin/bin/python3 experiments/SYSTEM-QUEUE-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

EV = RunRecord(
    "SYSTEM-QUEUE-01",
    claim=("The queue is one authority: work is admitted, drawn and completed; discretionary "
           "work is deferred under pressure and user-directed work never is; a failed job is an "
           "error, not a result; a scheduled job fires; and the durable queue is untouched."),
    hypothesis=("A second queue, a deferred user task, a failure returned as a result, or a "
                "dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    pending_before = await d.execute_query(
        "SELECT count(*) n FROM unified.task_queue WHERE status = 'pending'", (), fetch_one=True)
    try:
        from core.agents.autonomous.queue_authority import QueueAuthority, get_queue_authority
        from core.agents.autonomous.shared_types import (Priority, SUBSTRATE_ACTOR, Task,
                                                         TaskSource, TaskType)
        Q = get_queue_authority()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="queue", cls="QueueAuthority",
                        path="core/agents/autonomous/queue_authority.py", held=coord.task_queue, reached=Q)

        def task(tid, source, desc):
            return Task(id=tid, type=TaskType.ANALYSIS, source=source, description=desc)

        print("\n== B. Work: admitted, drawn, completed (an unpersisted queue) ==")
        q = QueueAuthority({"persist": False, "soft_limit": 3, "hard_limit": 6})
        check("the probe queue never reaches the durable store", q._persistence_or_none() is None)
        empty = await q.get_next_task(timeout=0)
        ok = await q.add_task(task("isoq_1", TaskSource.AUTONOMOUS, "isoprobe work"))
        drawn = await q.get_next_task(timeout=0)
        check("work is admitted and drawn in order", ok and drawn is not None and drawn.task.id == "isoq_1")
        check("the non-blocking pull (timeout=0) returns nothing from an empty queue and "
              "the ready job from a non-empty one",
              empty is None and drawn is not None,
              f"empty={empty} drawn={getattr(getattr(drawn, 'task', None), 'id', None)}")
        active = [t.id for t in q.active_tasks()]
        check("drawn work is active until it finishes", active == ["isoq_1"], f"active={active}")
        await q.mark_completed("isoq_1", {"done": True})
        status = await q.result_for("isoq_1", actor=SUBSTRATE_ACTOR)
        check("completion is recorded with its result",
              status.get("status") == "completed" and status.get("result") == {"done": True},
              f"{status}")
        other = await q.result_for("isoq_1", actor="user:isoprobe")
        check("finished work is no longer active, and another actor cannot read it",
              not q.active_tasks() and other.get("status") == "not_found",
              f"active={[t.id for t in q.active_tasks()]} other={other}")

        print("\n== C. Admission control: capacity, not permission ==")
        for i in range(3):
            await q.add_task(task(f"isoq_a{i}", TaskSource.AUTONOMOUS, "fill"))
        check("the backlog reads soft pressure at the soft limit", q.pressure() == "soft", q.pressure())
        deferred = await q.add_task(task("isoq_disc", TaskSource.AUTONOMOUS, "discretionary"))
        user = await q.add_task(task("isoq_user", TaskSource.MANUAL, "a person asked"))
        urgent = await q.add_task(task("isoq_hi", TaskSource.AUTONOMOUS, "urgent"), Priority.HIGH)
        check("discretionary autonomous work is deferred, a user's and urgent work are not",
              deferred is False and user is True and urgent is True,
              f"deferred={deferred} user={user} urgent={urgent} metrics={q.get_metrics().get('tasks_deferred')}")

        print("\n== D. The pool is honest about failure ==")
        async def works():
            return 41 + 1

        async def fails():
            raise RuntimeError("isoprobe: this job fails")

        r_ok = await q.execute("isoq_job_ok", works)
        check("a job's value comes back", r_ok == 42, f"{r_ok!r}")
        jid = q.submit(fails, name="isoprobe failing job")
        res = await q.await_result(jid)
        check("a failed job is returned as an error, never as a result",
              isinstance(res, dict) and res.get("error") and res.get("result") is None, f"{res}")

        print("\n== E. The scheduler fires, retunes and cancels; a timed one-shot runs once ==")
        fired = asyncio.Event()

        async def tick():
            fired.set()

        q.start()
        q.schedule_recurring("isoprobe_every", tick, 0.2)
        try:
            await asyncio.wait_for(fired.wait(), timeout=10.0)
            check("a recurring job fires", True)
        except asyncio.TimeoutError:
            check("a recurring job fires", False, "not fired within 10 s")
        before = {j["name"]: j for j in q.scheduled_job_status()}.get("isoprobe_every", {})
        q.schedule_recurring("isoprobe_every", tick, 3600.0)
        after = {j["name"]: j for j in q.scheduled_job_status()}.get("isoprobe_every", {})
        check("registering the name again retunes its cadence and keeps its record",
              after.get("interval_s") == 3600.0 and after.get("runs") == before.get("runs"),
              f"before={before} after={after}")
        stopped = q.cancel("isoprobe_every")
        unknown = q.cancel("isoprobe_never_scheduled")
        check("cancel stops a scheduled job; an unknown id is reported, not faked",
              stopped is True and "isoprobe_every" not in q.scheduled_jobs() and unknown is False,
              f"stopped={stopped} unknown={unknown} jobs={q.scheduled_jobs()}")
        t0 = time.monotonic()
        once = q.submit(works, name="isoprobe timed one-shot", delay_s=0.3)
        await asyncio.sleep(0.1)
        waiting = once in q.await_pending()
        res = await q.await_result(once)
        waited = time.monotonic() - t0
        check("a timed one-shot waits out its delay, runs once, and its value comes back",
              waiting and res.get("result") == 42 and waited >= 0.3,
              f"waiting at 0.1 s={waiting} waited={waited:.2f}s result={res.get('result')!r}")
        await q.stop()
        stats = await q.get_statistics()
        check("statistics are flat scalars",
              isinstance(stats, dict) and all(isinstance(v, (int, float, bool, str, type(None))) for v in stats.values()),
              f"keys={sorted(stats)[:8]}")

        print("\n== F. One copy per id: here, and across instances ==")
        dq = QueueAuthority({"persist": False})
        first = await dq.add_task(task("isoq_dup", TaskSource.MANUAL, "dup"))
        again = await dq.add_task(task("isoq_dup", TaskSource.MANUAL, "dup"))
        check("a second add of a queued id reports it queued and adds no copy",
              first and again and dq.queue.qsize() == 1 and dq.metrics["tasks_already_queued"] == 1,
              f"heap={dq.queue.qsize()} already_queued={dq.metrics['tasks_already_queued']}")
        await dq.get_next_task(timeout=0)
        in_flight = await dq.add_task(task("isoq_dup", TaskSource.MANUAL, "dup"))
        await dq.mark_completed("isoq_dup", {"done": True})
        rerun = await dq.get_next_task(timeout=0)
        check("an add while it runs queues nothing, so it runs once and stays completed",
              in_flight and rerun is None and dq.tasks_by_id["isoq_dup"].status.value == "completed",
              f"drawn again={rerun} status={dq.tasks_by_id['isoq_dup'].status.value}")
        renewed = await dq.add_task(task("isoq_dup", TaskSource.MANUAL, "dup"))
        check("a finished id may be queued again as new work",
              renewed and dq.queue.qsize() == 1 and dq.tasks_by_id["isoq_dup"].status.value == "pending")
        race = await asyncio.gather(*[dq.add_task(task("isoq_race", TaskSource.MANUAL, "race"))
                                      for _ in range(5)])
        copies = sum(1 for _, _, x in dq.queue._queue if x.task.id == "isoq_race")
        check("five simultaneous adds of one id leave one copy", all(race) and copies == 1,
              f"copies={copies}")

        # Two instances on the ONE durable table. Their probe rows and heartbeats
        # are removed by id below; the pending count is checked after.
        qa, qb = QueueAuthority({"persist": True}), QueueAuthority({"persist": True})
        pa, pb = qa._persistence_or_none(), qb._persistence_or_none()
        probe_ids = [f"isoq_inst_{uuid.uuid4().hex[:8]}" for _ in range(2)]
        try:
            await pa.heartbeat()
            await pb.heartbeat()
            await qa.add_task(task(probe_ids[0], TaskSource.MANUAL, "instance probe"))
            held_by_b = await qb.add_task(task(probe_ids[0], TaskSource.MANUAL, "instance probe"))
            owner = (await d.execute_query("SELECT owner FROM unified.task_queue WHERE task_id = $1",
                                           (probe_ids[0],), fetch_one=True))["owner"]
            check("an id a living instance holds is not taken over or queued by another",
                  held_by_b and probe_ids[0] not in qb.tasks_by_id and owner == pa.instance_id,
                  f"b queued={probe_ids[0] in qb.tasks_by_id} owner is a={owner == pa.instance_id}")
            await pa.release()
            taken = await qb.add_task(task(probe_ids[0], TaskSource.MANUAL, "instance probe"))
            owner = (await d.execute_query("SELECT owner FROM unified.task_queue WHERE task_id = $1",
                                           (probe_ids[0],), fetch_one=True))["owner"]
            check("once that instance stops, another may take the id",
                  taken and probe_ids[0] in qb.tasks_by_id and owner == pb.instance_id,
                  f"owner is b={owner == pb.instance_id}")
        finally:
            await d.execute_query("DELETE FROM unified.task_queue WHERE task_id = ANY($1::text[])",
                                  (probe_ids,))
            await pa.release()
            await pb.release()
    finally:
        try:
            pending_after = await d.execute_query(
                "SELECT count(*) n FROM unified.task_queue WHERE status = 'pending'", (), fetch_one=True)
            check("the durable queue is untouched",
                  pending_before is not None and pending_after is not None
                  and int(pending_after["n"]) == int(pending_before["n"]),
                  f"pending {pending_before and pending_before['n']} -> {pending_after and pending_after['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-QUEUE-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
