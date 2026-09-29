"""TASK-RESULT-01 — the task loop is fully wired, and scoped to who asked.

A user request that is a JOB (not a question) enters the one front door, is queued as a Task scoped
to the requester, and returns a task_id ACK immediately (the work runs async on the cognition loop).
This proves the OTHER half — retrieving the result — is wired and isolated:

  1. Submitting a job returns a task_id ack + the handle to poll it, and the Task is scoped to the
     requester (actor = the verified identity), NOT the substrate.
  2. Polling before completion reports it still working (no result yet).
  3. After the work completes, polling returns the result — both via the direct method and through
     the one front door (metadata={"task_result": id}).
  4. A FAILED job reports failed + its error.
  5. ISOLATION: another actor polling the same task id gets not_found (no cross-actor enumeration).

Real coordinator, real queue authority. No stubs.

Run: ./venv_lyric/bin/python3 experiments/TASK-RESULT-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "TASK-RESULT-01",
    claim=('The task loop is fully wired AND scoped to who asked: a job entering the one front door is queued as a Task owned by the verified requester, returns a task_id acknowledgement immediately, and its result is retrievable only by that requester.'),
    hypothesis=('If scoping were cosmetic, another identity could poll the handle and read the result, or the Task would be attributed to the substrate itself.'))

results = []
def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.database import get_database_manager
    from core.agents.autonomous.autonomous_coordinator import create_autonomous_system
    from core.agents.autonomous.shared_types import actor_for, TaskSource, SUBSTRATE_ACTOR

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    coord = await create_autonomous_system({})

    nonce = uuid.uuid4().hex[:8]
    user_id = f"wa-user-{nonce}"
    other_id = f"wa-other-{nonce}"
    session = f"sess-{nonce}"
    user_actor = actor_for(TaskSource.MANUAL, user_id)

    print("\n== 1. a JOB is accepted (ack + poll handle) and scoped to the requester ==")
    ack = await coord.handle_user_request(
        "analyze the quarterly numbers and summarize",  # a job, not a question
        source="api",
        metadata={"session_id": session, "actor_identity": user_id})
    task_id = ack.get("task_id")
    check("ack carries a task_id", bool(task_id), f"ack={ack}")
    check("ack carries the poll handle", ack.get("poll_with") == {"task_result": task_id})
    queued = coord.task_queue.tasks_by_id.get(task_id)
    check("the Task is scoped to the requester (not the substrate)",
          queued is not None and queued.task.actor == user_actor,
          f"actor={getattr(getattr(queued,'task',None),'actor',None)}")

    print("\n== 2. polling before completion: still working, no result ==")
    early = await coord.get_task_result(task_id, actor=user_actor)
    check("status is a working state, no result yet",
          early.get("status") not in ("completed", "failed", "not_found") and "result" not in early,
          f"early={early}")

    print("\n== 3. after the work completes, the result comes back ==")
    await coord.task_queue.mark_completed(task_id, {"summary": "revenue up 12%", "quality_score": 0.9})
    done = await coord.get_task_result(task_id, actor=user_actor)
    check("status completed + result returned (direct method)",
          done.get("status") == "completed" and done.get("result", {}).get("summary") == "revenue up 12%",
          f"done={done}")
    via_door = await coord.handle_user_request(
        "", source="api", metadata={"actor_identity": user_id, "task_result": task_id})
    check("same result through the one front door (task_result poll)",
          via_door.get("status") == "completed" and via_door.get("result", {}).get("summary") == "revenue up 12%",
          f"via_door={via_door}")

    print("\n== 4. a FAILED job reports failed + its error ==")
    # Queue the fail-case task directly (scoped to the user), so the failed-result
    # RETRIEVAL is tested deterministically, independent of how a sentence classifies.
    from core.agents.autonomous.shared_types import Task, TaskType, Priority
    tid2 = f"user_{uuid.uuid4().hex[:12]}"
    await coord.task_queue.add_task(
        Task(id=tid2, type=TaskType.ANALYSIS, description="a job that will fail",
             priority=Priority.HIGH, source=TaskSource.API, actor=user_actor,
             created_by="user"),
        priority=Priority.HIGH)
    await coord.task_queue.mark_failed(tid2, "no tool could do it")
    failed = await coord.get_task_result(tid2, actor=user_actor)
    check("status failed + error", failed.get("status") == "failed" and failed.get("error") == "no tool could do it",
          f"failed={failed}")

    print("\n== 5. ISOLATION: another actor cannot read this task's result ==")
    other_actor = actor_for(TaskSource.MANUAL, other_id)
    sneak = await coord.get_task_result(task_id, actor=other_actor)
    check("another actor gets not_found (no result leak, no enumeration)",
          sneak.get("status") == "not_found" and "result" not in sneak, f"sneak={sneak}")
    sneak_door = await coord.handle_user_request(
        "", source="api", metadata={"actor_identity": other_id, "task_result": task_id})
    check("and not through the front door either", sneak_door.get("status") == "not_found")

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
