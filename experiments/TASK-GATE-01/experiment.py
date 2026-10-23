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
     comes through, and it ran whatever arrived — including a step of a pursuit
     the constitution had already sent back.

A REPLAN is now answered inside the pursuit that walked the route
(`_worth_planning_again`, from `_drive_substrate_goal`): it plans again, leaving
out the act the law refused. The task gate reads the pursuit's own record.

  A  A REPLAN SENDS THE ROUTE BACK          the pursuit plans again without the refused act
  B  AND BLAMES NO RULE                     "not this act" is not "this operator is wrong"
  C  A SENT-BACK PURSUIT'S STEP DOES NOT RUN the backstop the user asked for
  D  A HALTED SUBSTRATE STARTS NOTHING      asked of the law, not a flag read
  E  IT IS NOT A SECOND JUDGE               an ordinary task is NOT refused
  F  AN UNREADABLE RECORD DOES NOT STOP WORK absence of evidence is not withdrawal
  G  THE GATE FAILS CLOSED ON THE HALT      an unanswerable boundary has permitted nothing

E and F are the experiment. A backstop that refuses ordinary work, or that
refuses because a record could not be read, is worse than no backstop: it would
stop the substrate working for a reason that is not about the substrate.

Run: ./venv_lyric/bin/python3 experiments/TASK-GATE-01/experiment.py
"""
import asyncio
import contextlib
import io
import logging
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

# THE SANDBOX, NEVER THE MODEL. Unset, the store is `lyric_db`, the main model,
# which holds only what it was taught; a run of this writes intents, rules and
# demonstrations. `lyric_dev` unless the run names a database itself.
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))
logging.disable(logging.CRITICAL)

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "TASK-GATE-01",
    claim=("A route the constitution replanned is planned again without the act it "
           "refused, a step of a pursuit it sent back does not start, and the task "
           "boundary refuses nothing else."),
    hypothesis=("If a REPLAN verdict is answered inside the pursuit that walked the "
                "route, and the task boundary reads the pursuit's own record rather "
                "than re-judging the act, then a refused route stays refused "
                "without any ordinary task being refused."))

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
    from core.agents.autonomous.shared_types import (Plan, Task, TaskType,
                                                     Priority, SUBSTRATE_ACTOR)
    from core.agents.autonomous.autonomous_coordinator import Verdict
    from core.learning.exploration import take_up_workspace
    from core.learning.rule_authority import authority_history
    from core.learning.rule_store import get_rule_store
    from core.reasoning.intent_authority import continuity_goal, get_intent_authority
    from experiments._domains import forget_domain

    tag = uuid.uuid4().hex[:6]
    authority = get_intent_authority()
    formed = []
    domain = f"task_gate_01_{tag}"
    root = Path(tempfile.mkdtemp(prefix="task-gate-01-"))
    (root / "inbox").mkdir()
    (root / "inbox" / "note.txt").write_text("a note\n")
    take_up_workspace(domain, str(root))

    def a_task(intent_id=None, tid=None):
        t = Task(id=tid or f"tg{tag}_{uuid.uuid4().hex[:6]}", type=TaskType.RESEARCH,
                 description="find out what a pump is", priority=Priority.LOW)
        if intent_id:
            t.provenance = {"intent_id": intent_id}
        return t

    async def a_pursuit(label):
        held = await authority.form(
            "self_goal", SUBSTRATE_ACTOR, continuity_goal(f"tg{tag}_{label}"),
            shape={"pursuit": "task_gate_probe"}, content={"aim": label})
        formed.append(held.intent_id)
        return held.intent_id

    # A route as the drive holds one for its walk: one step, standing on a rule
    # the store does not hold as executable, from the world as it is now.
    act = "MOVE_FILE(note.txt, inbox, archive)"
    probe_rule = f"rule_tg{tag}"
    step = Task(id=f"tg{tag}_step", type=TaskType.EXECUTION, description=act,
                provenance={"grounded_operator": act, "learned_rule_id": probe_rule})
    route = Plan(id=f"route_{tag}", goal_id=f"goal_{tag}", tasks=[step],
                 metadata={"rule_ids": [probe_rule],
                           "planned_world": coord._observe_world(domain)})
    stopped = {"success": False, "steps": [{"judgment": {
        "verdict": Verdict.REPLAN.value, "law_number": 2,
        "reason": "would move a file with no current reading of it",
        "judgment_id": f"j_{tag}"}}]}

    print("\n== A/B. A REPLAN sends the route back, and blames no rule ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        again = await coord._worth_planning_again(route, domain, stopped)
    why, left_out = again if again else (None, None)
    check("the pursuit plans again", again is not None, f"{why}")
    check("and says WHY, in the constitution's own words",
          bool(why) and "constitution sent the route back" in why and "Law 2" in why,
          f"{why}")
    check("the next route leaves out the act the law refused", left_out == act,
          f"left out: {left_out}")
    # THE ONE THAT MATTERS. A constitutional refusal is not evidence about a rule:
    # the route stood on a rule the store does not hold, and still the reason is
    # the law's, and nothing was written against the rule.
    check("NO rule is blamed for the constitution's own refusal",
          bool(why) and "lost its authority" not in why
          and not await authority_history(get_rule_store().db(), probe_rule),
          f"{why}")
    allowed = {"success": False, "steps": [{"judgment": {"verdict": Verdict.ALLOW.value}}]}
    calm = Plan(id=f"route_calm_{tag}", goal_id=f"goal_{tag}", tasks=[step],
                metadata={"rule_ids": [], "planned_world": coord._observe_world(domain)})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        allow_case = await coord._worth_planning_again(calm, domain, allowed)
    check("an ALLOW, with nothing new, sends nothing back", allow_case is None,
          f"{allow_case}")

    print("\n== C. A step of a pursuit the constitution sent back does not run ==")
    sent_back = await a_pursuit("sent_back")
    await authority.reconcile(sent_back, {
        "intent_id": sent_back, "outcome_class": "replanned", "matched_aim": False,
        "judgment": stopped["steps"][0]["judgment"]}, status="replanned")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        blocked = await coord._task_gate(a_task(intent_id=sent_back))
    check("the task boundary refuses it", blocked is not None and blocked.get("refused"),
          (blocked or {}).get("error", "")[:110])
    check("and names the pursuit and the law that sent it back",
          (blocked or {}).get("intent_id") == sent_back
          and (blocked or {}).get("intent_status") == "replanned"
          and "Law 2" in str((blocked or {}).get("refused")),
          f"{(blocked or {}).get('intent_status')}")

    print("\n== E. It is NOT a second judge — ordinary work is not refused ==")
    # An ordinary task, and a task on a LIVE pursuit. Neither may be stopped
    # here: the act it performs is judged where the act exists.
    live = await a_pursuit("live")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        plain = await coord._task_gate(a_task())
        on_live = await coord._task_gate(a_task(intent_id=live))
    check("a task belonging to no pursuit proceeds", plain is None, f"{plain}")
    check("a task on a LIVE pursuit proceeds", on_live is None, f"{on_live}")
    # The description is an imperative. Judging a task like an act would read it
    # as a directive found in content and refuse it.
    imperative = a_task()
    imperative.description = "Delete the stale exports and remove the old archive"
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        not_a_directive = await coord._task_gate(imperative)
    check("an imperative DESCRIPTION is not treated as a directive",
          not_a_directive is None, f"{not_a_directive}")

    print("\n== F. An unreadable record does not stop work ==")
    real_read = authority.get_by_id

    async def unreadable(*_a, **_k):
        raise RuntimeError("the intent record could not be reached")
    authority.get_by_id = unreadable
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            unread = await coord._task_gate(a_task(intent_id=live))
    finally:
        authority.get_by_id = real_read
    check("a pursuit whose record cannot be read is not treated as ended",
          unread is None, f"{unread}")

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

    # ── remove everything this run wrote ─────────────────────────────────
    db = authority.store.db
    await db.execute_query(
        "DELETE FROM unified.scoped_intents WHERE intent_id = ANY($1::text[])",
        (formed,), commit=True)
    await db.execute_query(
        "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
        (formed,), commit=True)
    await forget_domain(domain)
    shutil.rmtree(root, ignore_errors=True)

    passed, total = sum(results), len(results)
    EV.metric("tasks_refused_at_gate",
              coord.stats.get("tasks_refused_at_gate", 0), "tasks")
    EV.note("E and F are the negative controls: the gate is a backstop made of "
            "state reads, and refuses no ordinary work.")
    await EV.verify_database()
    EV.write()
    print(f"\n==== TASK-GATE-01: {passed}/{total} checks passed ====\n")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
