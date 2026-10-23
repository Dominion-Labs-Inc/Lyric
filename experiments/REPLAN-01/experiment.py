#!/usr/bin/env python3
"""REPLAN-01 — does a refuted rule's goal actually get a new route?

The near half of this edge was already proven: a runtime contradiction refutes
the rule, and the refutation is written durably. The far half is the goal: a
pursuit standing on a rule the world just refuted must not stop at the failed
step with its goal still reading `active`.

WHAT THIS MEASURES IS THE PATH, on a LIVE substrate: nothing here calls the
repair. The refutation is caused by acting in a real world, and the question is
whether the pursuit that was acting comes out the other side having planned
again over what is still validated.

    act in a world that refuses the move
      -> rule loses VALIDATED                        (rule store)
      -> RuleAuthorityChanged written durably
      -> the walk stops                              (_pursue_proved_route)
      -> the same pursuit plans again over what is left (_drive_substrate_goal)

There is no second pursuer to reach: a planning engine used to replan withdrawn
goals on its own, outside the task that owned them. The drive is the only
pursuit of a goal now, so the repair is asked of it.

The negative controls are where the value is: a pursuit whose rules still hold
in an unchanged world must not be planned again, and a pursuit whose world
cannot be observed must not be planned against an invented empty world.
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "REPLAN-01",
    claim=("A pursuit whose rule the world refutes plans again inside itself, over "
           "what is still validated, without anything asking; one with nothing new "
           "is not planned again, and one whose world cannot be observed is never "
           "planned against an invented world."),
    hypothesis=("If the drive asks, whenever a walk stops, whether a rule its route "
                "stood on lost its authority, then a refutation caused by acting "
                "makes the same pursuit plan again rather than strand its goal."))

CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    EV.check(name, bool(passed), detail)
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    from core.agents.autonomous import autonomous_coordinator as coordinator_module
    from core.agents.autonomous.shared_types import Plan, Priority, Task, TaskType
    from core.tools.tool_registry import get_binding_registry
    from core.learning.rule_authority import AuthorityCause, authority_history
    from core.learning.rule_induction import get_rule_inducer
    from core.learning.rule_store import EpistemicStatus, RuleStore
    from core.reasoning.intent_authority import (
        SUBSTRATE_ACTOR, continuity_goal, get_intent_authority)
    sys.path.insert(0, str(ROOT / "tests"))
    from tests.test_substrate_execution import (
        DOMAIN, HELD_OUT, LockedWorld, TEACHING, World)

    # ── the one pursuer ──────────────────────────────────────────────────────
    print("\n== A. One pursuer: the drive, and no repair beside it ==")
    beside = [name for name in ("replan_withdrawn_goals", "announce_route_withdrawal",
                                "_react_route_withdrawn")
              if hasattr(coordinator, name)]
    check("no second pursuer of a goal exists on the live substrate",
          not beside and not hasattr(coordinator_module.SelfEventType, "ROUTE_WITHDRAWN"),
          f"found: {beside}")
    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    check("the registry still names the LIVE substrate",
          get_autonomous_coordinator() is coordinator,
          "a later AutonomousCoordinator() would have displaced it")

    # ── a world that refuses the move the rule predicts ──────────────────────
    root = Path(tempfile.mkdtemp(prefix="replan01_"))
    world = LockedWorld(root, ["HALL", "LAB"], [("HALL", "LAB")], locked={"LAB"})
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding())

    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    print("\n== B. A goal pursued in a world that refuses the move ==")
    goal = Task(id=f"replan01_{uuid4().hex[:8]}", type=TaskType.EXECUTION,
                description="put z in the lab", priority=Priority.MEDIUM,
                provenance={"goal_conditions": ["SBAT(z, LAB)"], "domain_id": DOMAIN})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        result = await coordinator.execute_task(goal)
    route = await get_intent_authority().get(
        SUBSTRATE_ACTOR, continuity_goal(f"{goal.id}:route"))
    check("the pursuit proved a route and walked it",
          route is not None and route.shape.get("operators") == ["SBMOVE(z, HALL, LAB)"],
          f"route={None if route is None else route.shape.get('operators')}")
    lost = [e for e in await authority_history(store.db(), stored.rule_id)
            if e.lost_authority]
    check("the act ran and the world CONTRADICTED the rule",
          [e.cause for e in lost] == [AuthorityCause.RUNTIME_CONTRADICTION],
          f"{[e.cause.value for e in lost]}")
    reloaded = [r for r in await store.load(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id][0]
    check("the rule lost VALIDATED",
          reloaded.status is EpistemicStatus.REFUTED, f"status={reloaded.status.value}")

    print("\n== C. Nothing calls the repair — the same pursuit planned again ==")
    check("it PLANNED AGAIN, over what is still validated, without anything asking",
          result.get("planning_status") in ("unreachable", "indeterminate")
          and result.get("operators_considered") == 0,
          f"planning_status={result.get('planning_status')} "
          f"operators={result.get('operators_considered')}")
    check("and ended saying so, not claiming the goal",
          result.get("success") is False and bool(result.get("reason")),
          f"{result.get('reason')}")
    check("the route that stopped was closed as NOT reached",
          route is not None and route.concluded
          and (route.outcome or {}).get("matched_aim") is False,
          f"route intent {None if route is None else route.status}")
    check("the world is where the refusal left it — nothing was forced",
          (root / "HALL" / "z").exists() and not (root / "LAB" / "z").exists())

    print("\n== D. Negative controls ==")
    ALT = DOMAIN + "_alt"
    alt_root = Path(tempfile.mkdtemp(prefix="replan01_alt_"))
    alt_world = World(alt_root, ["HALL", "LAB"], [("HALL", "LAB")])
    alt_world.place("z", "HALL")
    get_binding_registry().register(ALT, alt_world.binding())
    alt_rule = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=ALT, rule_kind="move"))[0]
    await store.validate(alt_rule, HELD_OUT)
    calm = Plan(id=f"route_{uuid4().hex[:8]}", goal_id="replan01_calm", tasks=[],
                metadata={"rule_ids": [alt_rule.rule_id],
                          "planned_world": coordinator._observe_world(ALT)})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        unchanged = await coordinator._worth_planning_again(
            calm, ALT, {"success": False, "steps": []})
    check("a pursuit whose rules hold in an unchanged world is NOT planned again",
          unchanged is None, f"{unchanged}")

    # A pursuit whose world has no observer must not be planned against an
    # invented empty world: the drive declines it, and a stopped walk there is
    # not planned again on a world nobody read.
    blind_domain = f"replan01_unobserved_{uuid4().hex[:6]}"
    blind = Task(id=f"replan01_blind_{uuid4().hex[:6]}", type=TaskType.EXECUTION,
                 description="put z nowhere", priority=Priority.MEDIUM,
                 provenance={"goal_conditions": ["SBAT(z, NOWHERE)"],
                             "domain_id": blind_domain})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        declined = await coordinator._drive_substrate_goal(blind)
        blind_again = await coordinator._worth_planning_again(
            Plan(id="route_blind", goal_id=blind.id, tasks=[],
                 metadata={"rule_ids": [], "planned_world": None}),
            blind_domain, {"success": False, "steps": []})
    check("a goal whose world cannot be observed is not planned at all",
          declined is None, f"{declined}")
    check("...and a stopped walk there is not planned again on a world nobody read",
          blind_again is None, f"{blind_again}")

    # ── cleanup ──────────────────────────────────────────────────────────────
    get_binding_registry().clear(DOMAIN)
    get_binding_registry().clear(ALT)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(alt_root, ignore_errors=True)
    if route is not None:
        for table in ("unified.scoped_intents", "unified.intents"):
            await get_intent_authority().store.db.execute_query(
                f"DELETE FROM {table} WHERE intent_id = $1", (route.intent_id,), commit=True)
    db = store.db()
    for domain in (DOMAIN, ALT):
        for table in ("rule_authority_events", "learned_rule_evidence"):
            await db.execute_query(
                f"DELETE FROM unified.{table} WHERE rule_id IN"
                f" (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)",
                (domain,))
        await db.execute_query(
            "DELETE FROM unified.learned_rules WHERE domain_id = $1", (domain,))

    passed = sum(1 for c in CHECKS if c["passed"])
    print("\n" + "=" * 62)
    print(f"RESULT: {passed}/{len(CHECKS)} checks passed")
    print("=" * 62)

    await EV.verify_database()
    written = EV.write()
    print(f"\nrun record: {written}")
    return 0 if passed == len(CHECKS) else 1


sys.exit(asyncio.run(main()))
