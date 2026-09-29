#!/usr/bin/env python3
"""TASK-GATE-01 — does a refused route stay refused, and does a REPLAN replan?

TWO HOLES, ONE SHAPE. The constitution is upstream of task dispatch: it judges
the act and it decides the route. But nothing was asked at the TASK boundary at
all, and one of the constitution's four verdicts reached nobody.

  1  NOTHING CONSUMED `Verdict.REPLAN`. Its entire content is "this is not the
     route, plan again" — and it is produced in five places while no code in the
     tree branched on it. So a route the constitution had rejected stayed the
     ACTIVE route: every dispatch of it was refused again at the tool gate,
     forever, and the goal it served was never repaired. A livelock the laws
     themselves diagnosed on every pass.

  2  THE TASK BOUNDARY ASKED NOTHING. `execute_task` is the one door every task
     comes through, and it ran whatever arrived — including a step of a plan the
     substrate had already decided was no longer the route.

  A  A REPLAN VERDICT WITHDRAWS THE ROUTE   the near half, beside the refuted-rule one
  B  AND BLAMES NO RULE                     "not this act" is not "this operator is wrong"
  C  A WITHDRAWN ROUTE'S STEP DOES NOT RUN  the backstop the user asked for
  D  A HALTED SUBSTRATE STARTS NOTHING      asked of the law, not a flag read
  E  IT IS NOT A SECOND JUDGE               an ordinary task is NOT refused
  F  AN UNREADABLE PLAN DOES NOT STOP WORK  absence of evidence is not withdrawal
  G  THE GATE FAILS CLOSED ON THE HALT      an unanswerable boundary has permitted nothing

E and F are the experiment. A backstop that refuses ordinary work, or that
refuses because the planner hiccupped, is worse than no backstop: it would stop
the substrate working for a reason that is not about the substrate.

Run: ./venv_torin/bin/python3 experiments/TASK-GATE-01/experiment.py
"""
import asyncio
import contextlib
import io
import logging
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))
logging.disable(logging.CRITICAL)

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "TASK-GATE-01",
    claim=("A route the constitution replanned is withdrawn and its steps stop "
           "running, and the task boundary refuses nothing else."),
    hypothesis=("If a REPLAN verdict withdraws the route where the provenance is "
                "in scope, and the task boundary reads the plan's own status "
                "rather than re-judging the act, then a refused route stays "
                "refused without any ordinary task being refused."))

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
    from core.agents.autonomous.shared_types import (Task, TaskStatus, TaskType,
                                                     Priority)
    from core.agents.autonomous.autonomous_coordinator import Verdict

    tag = uuid.uuid4().hex[:6]
    engine = await coord._get_planning_engine()

    def a_task(plan_id=None, tid=None):
        t = Task(id=tid or f"tg{tag}_{uuid.uuid4().hex[:6]}", type=TaskType.RESEARCH,
                 description="find out what a pump is", priority=Priority.LOW)
        if plan_id:
            t.provenance = {"plan_id": plan_id, "goal_id": f"goal_{tag}"}
        return t

    # A REAL plan object, registered where the engine keeps them, with one step.
    step = a_task()
    plan = SimpleNamespace(id=f"plan_{tag}", goal_id=f"goal_{tag}", status="active",
                           metadata={}, tasks=[step])
    step.provenance = {"plan_id": plan.id, "goal_id": plan.goal_id}
    engine.active_plans[plan.id] = plan
    stored_calls = []
    original_store = engine._store_plan

    async def watched_store(p):
        stored_calls.append(p.id)
        return None                  # the probe plan is not a real Plan row
    engine._store_plan = watched_store

    withdrawn_events = []
    original_announce = coord.announce_route_withdrawal

    async def watched_announce(**kw):
        withdrawn_events.append(kw)
        return await original_announce(**kw)
    coord.announce_route_withdrawal = watched_announce

    print("\n== A/B. A REPLAN verdict withdraws the route, and blames no rule ==")
    judgment = {"verdict": Verdict.REPLAN.value, "law_number": 2,
                "reason": "would move a file with no current reading of it",
                "judgment_id": f"j_{tag}"}
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        did = await coord._withdraw_replanned_route(
            judgment, {"plan_id": plan.id, "goal_id": plan.goal_id})
    check("the route is withdrawn", did and plan.status == "invalidated",
          f"withdrawn={did} status={plan.status}")
    check("and says WHY, in the constitution's own words",
          plan.metadata.get("invalidated_by") == "constitutional_replan"
          and plan.metadata.get("law_number") == 2,
          f"{plan.metadata.get('invalidated_by')} / Law {plan.metadata.get('law_number')}")
    check("its pending step is blocked, with the judgement named",
          step.status is TaskStatus.BLOCKED
          and (step.result or {}).get("judgment_id") == f"j_{tag}",
          f"status={step.status} reason={(step.result or {}).get('blocked_reason')}")
    check("the withdrawal was durably recorded before being announced",
          stored_calls == [plan.id], f"{stored_calls}")
    check("the goal is announced as having lost its route",
          len(withdrawn_events) == 1
          and withdrawn_events[0]["plan_ids"] == [plan.id],
          f"{withdrawn_events[0] if withdrawn_events else None}")
    # THE ONE THAT MATTERS. A constitutional refusal is not evidence about a rule.
    check("NO rule is blamed for the constitution's own refusal",
          withdrawn_events and withdrawn_events[0]["rule_ids"] == [],
          f"rule_ids={withdrawn_events[0]['rule_ids'] if withdrawn_events else None}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        again = await coord._withdraw_replanned_route(
            judgment, {"plan_id": plan.id, "goal_id": plan.goal_id})
    check("withdrawing twice is one withdrawal, not two",
          again is False and len(withdrawn_events) == 1)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        allow_case = await coord._withdraw_replanned_route(
            {"verdict": Verdict.ALLOW.value}, {"plan_id": plan.id})
    check("an ALLOW withdraws nothing", allow_case is False)

    print("\n== C. A step of a withdrawn route does not run ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        blocked = await coord._task_gate(a_task(plan_id=plan.id))
    check("the task boundary refuses it", blocked is not None and blocked.get("refused"),
          (blocked or {}).get("error", "")[:110])
    check("and names the plan and why it went", (blocked or {}).get("plan_id") == plan.id
          and (blocked or {}).get("withdrawn_by") == "constitutional_replan",
          f"{(blocked or {}).get('withdrawn_by')}")

    print("\n== E. It is NOT a second judge — ordinary work is not refused ==")
    # An ordinary task, and a task on a LIVE plan. Neither may be stopped here:
    # the act it performs is judged where the act exists.
    live = SimpleNamespace(id=f"plan_live_{tag}", goal_id=f"goal_{tag}",
                           status="active", metadata={}, tasks=[])
    engine.active_plans[live.id] = live
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        plain = await coord._task_gate(a_task())
        on_live = await coord._task_gate(a_task(plan_id=live.id))
    check("a task belonging to no plan proceeds", plain is None, f"{plain}")
    check("a task on a LIVE plan proceeds", on_live is None, f"{on_live}")
    # The description is an imperative. Judging a task like an act would read it
    # as a directive found in content and refuse it.
    imperative = a_task()
    imperative.description = "Delete the stale exports and remove the old archive"
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        not_a_directive = await coord._task_gate(imperative)
    check("an imperative DESCRIPTION is not treated as a directive",
          not_a_directive is None, f"{not_a_directive}")

    print("\n== F. An unreadable plan does not stop work ==")
    orphan = a_task(plan_id=f"plan_gone_{tag}")     # never registered
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        missing = await coord._task_gate(orphan)
    check("a plan the engine no longer holds is not treated as withdrawn",
          missing is None, f"{missing}")

    print("\n== D/G. A halted substrate starts nothing ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await coord.constitution.halt("TASK-GATE-01 probe", by="constitution")
        halted = await coord._task_gate(a_task())
    check("the halt is asked of the LAW, and refuses the task",
          halted is not None and halted.get("refused")
          and (halted.get("judgment") or {}).get("law_number") == 5,
          f"Law {(halted.get('judgment') or {}).get('law_number')}: "
          f"{(halted or {}).get('error', '')[:70]}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await coord.constitution.resume(authorized_by="task_gate_01")
        after_resume = await coord._task_gate(a_task())
    check("and lifting the halt lets work begin again", after_resume is None,
          f"{after_resume}")
    # FAIL-CLOSED. A boundary that cannot be asked has established nothing.
    broken = SimpleNamespace(may_start=lambda kind: (_ for _ in ()).throw(
        RuntimeError("the law could not be reached")))
    real, coord.constitution = coord.constitution, broken
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            unanswerable = await coord._task_gate(a_task())
    finally:
        coord.constitution = real
    check("a boundary that could not be asked refuses, never permits",
          unanswerable is not None and unanswerable.get("refused"),
          (unanswerable or {}).get("error", "")[:90])

    # ── restore everything this run touched ──────────────────────────────
    engine._store_plan = original_store
    coord.announce_route_withdrawal = original_announce
    engine.active_plans.pop(plan.id, None)
    engine.active_plans.pop(live.id, None)

    passed, total = sum(results), len(results)
    EV.metric("routes_withdrawn_by_law",
              coord.stats.get("routes_withdrawn_by_law", 0), "routes")
    EV.metric("tasks_refused_at_gate",
              coord.stats.get("tasks_refused_at_gate", 0), "tasks")
    EV.note("E and F are the negative controls: the gate is a backstop made of "
            "state reads, and refuses no ordinary work.")
    EV.write()
    print(f"\n==== TASK-GATE-01: {passed}/{total} checks passed ====\n")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
