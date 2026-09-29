#!/usr/bin/env python3
"""TASK-GATE-02 — does the task gate ask INTENT whether the pursuit is still live?

The task gate asked two things: is the substrate halted, and has this task's plan
been withdrawn. It never asked the faculty that owns the answer to "is this work
still anyone's to do". INTENT is the substrate's own account of what it is trying
to do and why — owned by reasoning, durable, with a lifecycle (forming → active →
fulfilled / abandoned / refused) — and the constitution, planning, exploration,
memory and reconciliation all read or write it. The gate did not. A task names its
pursuit by id; whether that pursuit is still being pursued is the intent
authority's to say, never the task's.

Measured before this, on the live store and the live code:
  * the gate read the PLAN's status only;
  * a RETURN to a concluded pursuit did not reopen it: a goal whose first route
    stopped (`abandoned`) and was then replanned kept `abandoned`, and the FIRST
    route's outcome, while the second route was written onto it (version 3). Any
    step of the second route reaching the gate would have been refused for the
    first route's end;
  * drive goals went around the gate entirely — `_execute_and_validate_task`
    routed them to their executor instead of through `execute_task`.

  A  THE GATE ASKS INTENT                concluded or unrecorded → refused; live → proceeds
  B  ABSENCE IS REPORTED, NOT FILLED IN  no intent named → proceeds, counted, nothing formed
  C  A RETURN REOPENS A CONCLUDED PURSUIT  and the ended attempt's lesson survives
  D  ONE DOOR                            a drive goal meets the same gate

The live-pursuit checks in A and C, and all of B, are the negative controls: the
gate must refuse no work whose pursuit is live, and must not manufacture an intent
for work that has none.

Run: ./venv_lyric/bin/python3 experiments/TASK-GATE-02/experiment.py
"""
import asyncio
import contextlib
import contextvars
import io
import logging
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))
logging.disable(logging.CRITICAL)

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "TASK-GATE-02",
    claim=("The task gate asks the intent authority whether the pursuit a task "
           "serves is still live, refuses the steps of concluded or unrecorded "
           "pursuits, and refuses nothing whose pursuit is live."),
    hypothesis=("If the gate reads the task's intent by id from the authority that "
                "owns it, and a return to a concluded pursuit reopens it, then work "
                "on an ended pursuit stops at the door while a replanned pursuit's "
                "work and intent-less work both pass."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


async def main() -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coord = system.autonomous_coordinator
    from core.agents.autonomous.shared_types import Task, TaskType, Priority
    from core.reasoning.intent_authority import (
        CONCLUDED, continuity_goal, get_intent_authority)

    authority = get_intent_authority()
    tag = uuid.uuid4().hex[:6]
    # A probe ACTOR, so every content row this run writes is removable by it, and
    # the shape rows by the ids collected here. Nothing else is written: the gate
    # itself writes nothing.
    actor = f"task_gate_02_{tag}"
    made = []

    async def pursuit(name, status=None, detail=None):
        """A real pursuit, formed through the authority and concluded as asked."""
        held = await authority.form(
            "goal", actor, continuity_goal(f"tg02_{tag}_{name}"),
            shape={"proved": True, "operator": "MOVE(z, HALL, LAB)",
                   "goal_conditions": ["AT(z, LAB)"]},
            content={"aim": f"TASK-GATE-02 probe: {name}"})
        made.append(held.intent_id)
        if status == "active":
            await authority.refresh(held.intent_id, actor, shape={"engaged": True})
        elif status in CONCLUDED:
            await authority.reconcile(
                held.intent_id,
                {"outcome_class": "success" if status == "fulfilled" else "missed",
                 "matched_aim": status == "fulfilled",
                 "detail": detail or f"{name} concluded"},
                status=status)
        return held.intent_id

    def a_task(intent_id=None, **claims):
        task = Task(id=f"tg02_{tag}_{uuid.uuid4().hex[:6]}", type=TaskType.RESEARCH,
                    description="find out what a pump is", priority=Priority.LOW)
        if intent_id:
            task.provenance = {"intent_id": intent_id, **claims}
        return task

    async def gate(task):
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            return await coord._task_gate(task)

    try:
        print("\n== A. The gate asks INTENT whether the pursuit is still live ==")
        forming = await pursuit("forming")
        active = await pursuit("active", "active")
        fulfilled = await pursuit("fulfilled", "fulfilled", "the file is in the archive")
        abandoned = await pursuit("abandoned", "abandoned", "stopped at MOVE(z, HALL, LAB)")
        refused = await pursuit("refused", "refused", "the constitution refused the act")

        r = await gate(a_task(forming))
        check("a step of a FORMING pursuit proceeds", r is None, f"{r}")
        r = await gate(a_task(active))
        check("a step of an ACTIVE pursuit proceeds", r is None, f"{r}")
        r = await gate(a_task(fulfilled)) or {}
        check("a step of a FULFILLED pursuit is refused — the pursuit is over",
              r.get("refused") and r.get("intent_status") == "fulfilled",
              r.get("error", "")[:110])
        r = await gate(a_task(abandoned)) or {}
        check("a step of an ABANDONED pursuit is refused, and says what ended it",
              r.get("refused") and r.get("intent_status") == "abandoned"
              and "stopped at MOVE(z, HALL, LAB)" in r.get("error", ""),
              r.get("error", "")[:110])
        r = await gate(a_task(refused)) or {}
        check("a step of a REFUSED pursuit is refused",
              r.get("refused") and r.get("intent_status") == "refused",
              r.get("error", "")[:110])
        ghost = uuid.uuid4().hex
        r = await gate(a_task(ghost)) or {}
        check("a task naming a pursuit the authority does NOT hold is refused",
              r.get("refused") and r.get("intent_id") == ghost
              and r.get("intent_status") is None,
              r.get("error", "")[:110])
        # THE TASK'S WORDS CARRY NO AUTHORITY ABOUT THE PURSUIT. Only the id travels;
        # a claim riding beside it that the pursuit is live changes nothing.
        r = await gate(a_task(abandoned, intent_status="active", status="active")) or {}
        check("a task CLAIMING its ended pursuit is live is still refused — the "
              "status comes from the record", r.get("refused")
              and r.get("intent_status") == "abandoned", r.get("error", "")[:90])

        print("\n== B. Absence is reported as absence, never filled in ==")
        # Watched only inside this context, so the live substrate's own reasoning
        # running concurrently cannot be mistaken for the gate forming an intent.
        in_gate = contextvars.ContextVar("tg02_in_gate", default=False)
        formed = []
        original_form = authority.form

        async def watched_form(*args, **kwargs):
            if in_gate.get():
                formed.append(args[:3])
            return await original_form(*args, **kwargs)

        bare = a_task()
        counted_before = coord.stats.get("tasks_without_intent", 0)
        authority.form = watched_form
        token = in_gate.set(True)
        try:
            r = await gate(bare)
        finally:
            in_gate.reset(token)
            del authority.form           # the class's own method again
        counted = coord.stats.get("tasks_without_intent", 0) - counted_before
        check("a task naming no pursuit proceeds — its acts meet Law 2 at the tool gate",
              r is None, f"{r}")
        check("and the absence is COUNTED", counted >= 1, f"+{counted}")
        check("and no intent was formed for it at the door",
              not formed and not (bare.provenance or {}).get("intent_id"),
              f"formed={formed} provenance={bare.provenance}")

        print("\n== C. A return to a concluded pursuit reopens it ==")
        key = continuity_goal(f"tg02_{tag}_replanned")
        route = {"proved": True, "operator": "MOVE(z, HALL, LAB)",
                 "goal_conditions": ["AT(z, LAB)"]}
        first = await authority.form(
            "goal", actor, key, shape={**route, "rule_ids": ["rule_first_route"]},
            content={"aim": "TASK-GATE-02 probe: replanned"})
        made.append(first.intent_id)
        await authority.reconcile(
            first.intent_id,
            {"outcome_class": "missed", "matched_aim": False,
             "detail": "stopped at MOVE(z, HALL, LAB)"}, status="abandoned")
        ended = await authority.get_by_id(first.intent_id)
        # Reasoning SETTLING a pass over it is not a return to it.
        settled = await authority.refresh(first.intent_id, actor,
                                          shape={"engaged": False})
        check("reasoning SETTLING a pass over an ended pursuit does not reopen it",
              ended.status == "abandoned" and settled.status == "abandoned",
              f"{ended.status} -> {settled.status}")
        # The planner proves a second route and records it the way it always does.
        second = await authority.form(
            "goal", actor, key, shape={**route, "rule_ids": ["rule_second_route"]},
            content={"aim": "TASK-GATE-02 probe: replanned"})
        check("the planner's RETURN reopens it — the pursuit is live again",
              second.status == "active", f"status={second.status}")
        check("the same pursuit, not a second account of it",
              second.intent_id == first.intent_id and second.version > ended.version,
              f"v{ended.version} -> v{second.version}")
        shape_view = await authority.get_by_id(first.intent_id)
        earlier = shape_view.shape.get("earlier_attempts") or []
        check("the ended attempt's lesson survives on the actor-free SHAPE",
              len(earlier) == 1 and earlier[0].get("status") == "abandoned"
              and (earlier[0].get("outcome") or {}).get("detail")
              == "stopped at MOVE(z, HALL, LAB)",
              f"{earlier}")
        check("the current outcome is the new attempt's — none yet",
              shape_view.outcome is None, f"{shape_view.outcome}")
        full = await authority.get_by_id(first.intent_id, actor)
        check("the history records the full previous state, status and outcome",
              any(h.get("status") == "abandoned" and (h.get("outcome") or {}).get(
                  "detail") for h in full.history),
              f"{[(h.get('version'), h.get('status')) for h in full.history]}")
        r = await gate(a_task(first.intent_id))
        check("a step of the REOPENED pursuit passes the gate — not refused for the "
              "first route's end", r is None, f"{r}")
        await authority.reconcile(
            first.intent_id,
            {"outcome_class": "success", "matched_aim": True,
             "detail": "the second route reached it"}, status="fulfilled")
        closed = await authority.get_by_id(first.intent_id)
        check("and it concludes again on its own outcome, the earlier attempt kept",
              closed.status == "fulfilled"
              and (closed.outcome or {}).get("detail") == "the second route reached it"
              and len(closed.shape.get("earlier_attempts") or []) == 1,
              f"{closed.status} / {len(closed.shape.get('earlier_attempts') or [])}")

        print("\n== D. One door — a drive goal meets the same gate ==")
        # No domain named: the drive executor answers with its own honest failure
        # and touches nothing, which is all this needs to see whether it was reached.
        def drive_task(intent_id=None):
            task = Task(id=f"tg02_{tag}_drive_{uuid.uuid4().hex[:4]}",
                        type=TaskType.SELF_IMPROVEMENT,
                        description="Strengthen my operators in domain tg02",
                        priority=Priority.LOW, metadata={"drive": "competence"})
            if intent_id:
                task.provenance = {"intent_id": intent_id}
            return task

        reached = []
        original_drive = coord._execute_drive_goal

        async def watched_drive(task):
            reached.append(task.id)
            return await original_drive(task)

        coord._execute_drive_goal = watched_drive
        halted_task, open_task = drive_task(), drive_task()
        ended_task = drive_task(abandoned)
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                await coord.constitution.halt("TASK-GATE-02 probe", by="constitution")
                try:
                    while_halted = await coord.execute_task(halted_task)
                finally:
                    await coord.constitution.resume(authorized_by="task_gate_02")
                once_open = await coord.execute_task(open_task)
                on_ended = await coord.execute_task(ended_task)
        finally:
            del coord._execute_drive_goal    # the class's own method again
        check("while HALTED a drive goal is refused at the gate — its executor never ran",
              while_halted.get("method") == "task_gate"
              and halted_task.id not in reached,
              (while_halted.get("error") or "")[:90])
        check("once the halt is lifted it reaches its executor — the gate let it through",
              open_task.id in reached
              and "drive goal missing" in (once_open.get("error") or ""),
              (once_open.get("error") or "")[:90])
        check("a drive goal on an ENDED pursuit is refused like any other work",
              on_ended.get("intent_status") == "abandoned"
              and ended_task.id not in reached,
              (on_ended.get("error") or "")[:90])
    finally:
        # ── remove everything this run wrote ─────────────────────────────────
        db = authority.store.db
        await db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE scope_actor = $1", (actor,),
            commit=True)
        if made:
            await db.execute_query(
                "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
                (made,), commit=True)

    passed, total = sum(results), len(results)
    EV.metric("tasks_refused_at_gate",
              coord.stats.get("tasks_refused_at_gate", 0), "tasks")
    EV.metric("tasks_without_intent",
              coord.stats.get("tasks_without_intent", 0), "tasks")
    EV.note("A-live, B and C's gate check are the negative controls: live and "
            "intent-less work passes, and the gate forms no intent.")
    EV.note("Nothing in the live path writes status 'refused' yet; A reaches it by "
            "reconciling the probe pursuit through the authority directly.")
    EV.write()
    print(f"\n==== TASK-GATE-02: {passed}/{total} checks passed ====\n")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
