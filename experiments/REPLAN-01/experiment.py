#!/usr/bin/env python3
"""REPLAN-01 — does a refuted rule's goal actually get a new route?

The near half of this edge was already proven: a runtime contradiction refutes
the rule, the refutation is written durably, and the plans standing on it are
withdrawn. The far half did not exist. `replan_withdrawn_goals` is now that
half, and a unit test calling it directly proves only that the METHOD works.

WHAT THIS MEASURES IS THE PATH, on a LIVE substrate with its reactive drain
worker running: nothing here calls the repair. The refutation is caused by
acting in a real world, and the question is whether the announcement reaches the
reaction and the goal comes out the other side with a route.

    act in a world that refuses the move
      -> rule loses VALIDATED                        (rule store)
      -> RuleAuthorityChanged written durably
      -> get_next_tasks drains it, plans withdrawn   (planning engine)
      -> ROUTE_WITHDRAWN announced                   (the new seam)
      -> deferred reaction replans over what is left (the far half)

The negative controls are where the value is: a goal that still has a live plan
must not be replanned, and a goal whose world cannot be observed must be
reported unobservable rather than planned against an invented empty world.
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

# THE STANDARD RECORD. This wrote a hand-rolled JSON with no `.md` beside it,
# so a run left nothing a person could read without opening the file.
EV = RunRecord(
    "REPLAN-01",
    claim=("A refuted rule's goal gets a new route without anything asking, and the "
           "substrate carries the repaired route out; a goal that still has a live "
           "plan is not replanned, and one whose world cannot be observed is "
           "reported unobservable."),
    hypothesis=("If ROUTE_WITHDRAWN reaches a deferred reaction that replans over what "
                "is still validated and pursues the new route, then a refutation "
                "caused by acting repairs the pursuit it stranded."))

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

    drain = bool(getattr(coordinator, "_reactive_worker", None))
    print(f"  reactive drain worker: {drain}", flush=True)
    if not drain:
        raise SystemExit(
            "the reactive drain worker is not running, so a deferred reaction "
            "would queue forever. Refusing to measure a path that cannot run.")

    from core.agents.autonomous.autonomous_coordinator import (
        AutonomousCoordinator, SelfEventType)
    from core.agents.autonomous.planning_engine import PlanningEngine
    from core.agents.autonomous.shared_types import (
        Plan, Priority, SystemState, Task, TaskStatus, TaskType)
    from core.execution.operator_binding import get_binding_registry
    from core.learning.rule_induction import Fact, get_rule_inducer
    from core.learning.rule_store import EpistemicStatus, RuleStore
    sys.path.insert(0, str(ROOT / "tests"))
    from tests.test_substrate_execution import (
        DOMAIN, HELD_OUT, LockedWorld, TEACHING, World, task_for)

    # ── the reaction is actually registered, and deferred ────────────────────
    print("\n== A. The seam exists on the live substrate ==")
    reactions = coordinator._reactions.get(SelfEventType.ROUTE_WITHDRAWN, [])
    named = {r["name"]: r for r in reactions}
    check("ROUTE_WITHDRAWN has a registered reaction",
          "replan_withdrawn_routes" in named,
          f"reactions: {sorted(named)}")
    check("it is DEFERRED, so it never runs on the dispatch path",
          named.get("replan_withdrawn_routes", {}).get("mode") == "deferred",
          f"mode={named.get('replan_withdrawn_routes', {}).get('mode')}")

    # THE ENGINE ANNOUNCES THROUGH THE REGISTRY, and `AutonomousCoordinator()`
    # REGISTERS ITSELF on construction — so a throwaway coordinator built
    # anywhere in this process silently becomes the one the announcement
    # reaches, and the work is handed to a self with no drain worker. That is
    # how this experiment first read 9/11 with every part working. Asserted, so
    # it can never quietly happen again.
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

    engine = PlanningEngine({"max_concurrent_tasks": 10_000})
    assert await engine.initialize() is True
    coordinator.planning = engine          # the live coordinator's own engine

    async def plan_on(rule_id, label):
        goal = await engine.create_goal(f"replan01 {label}", Priority.MEDIUM)
        def step(index, status):
            return Task(id=f"replan01_{goal.id}_{index}", type=TaskType.EXECUTION,
                        description=f"SBMOVE(z, R{index}, R{index+1})",
                        priority=Priority.MEDIUM, status=status,
                        created_at=datetime.now(),
                        dependencies=[f"replan01_{goal.id}_0"] if index else [],
                        provenance={"learned_rule_id": rule_id,
                                    "plan_id": goal.id,
                                    "grounded_operator": f"SBMOVE(z, R{index}, R{index+1})"})
        plan = Plan(id=f"plan_{uuid4().hex[:8]}", goal_id=goal.id,
                    tasks=[step(0, TaskStatus.COMPLETED), step(1, TaskStatus.PENDING)],
                    status="active")
        engine.active_plans[plan.id] = plan
        await engine._store_plan(plan)
        return goal, plan

    stranded_goal, stranded_plan = await plan_on(stored.rule_id, "stranded")
    safe_goal, safe_plan = await plan_on("rule_nobody_refuted", "untouched")

    print("\n== B. Acting in a world that refuses the move ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        result = await coordinator.execute_task(
            await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    check("the act ran and the world CONTRADICTED the rule",
          result.get("runtime_outcome") == "runtime_contradiction",
          f"outcome={result.get('runtime_outcome')} refused={result.get('refused')}")
    reloaded = [r for r in await store.load(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id][0]
    check("the rule lost VALIDATED",
          reloaded.status is EpistemicStatus.REFUTED, f"status={reloaded.status.value}")

    print("\n== C. Nothing calls the repair — dispatch drains, the seam fires ==")
    before_status = stranded_plan.status
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await engine.get_next_tasks(SystemState())
    check("the plan standing on it was withdrawn by DISPATCH",
          before_status == "active" and stranded_plan.status == "invalidated",
          f"{before_status} -> {stranded_plan.status}")
    check("a plan on an unrelated rule was NOT touched",
          safe_plan.status == "active", f"status={safe_plan.status}")

    # The reaction is deferred: give the drain worker its turn. Waited ON THE
    # EFFECT, not slept past — a fixed sleep would pass for a queue nothing was
    # ever put in.
    replanned = None
    for _ in range(100):
        await asyncio.sleep(0.1)
        live = [p for p in engine.active_plans.values()
                if p.goal_id == stranded_goal.id and p.status == "active"]
        if live:
            replanned = live[0]
            break

    print("\n== D. The goal came out the other side with a route ==")
    check("the stranded goal has a LIVE plan again, without anything asking",
          replanned is not None,
          f"plan={getattr(replanned, 'id', None)} "
          f"(goal status={engine.current_goals[stranded_goal.id].status})")
    check("the withdrawn plan is still recorded as withdrawn, not rewritten",
          stranded_plan.status == "invalidated",
          f"status={stranded_plan.status}")

    print("\n== E. The substrate CARRIES OUT the route it repaired ==")
    # A repaired pursuit nobody runs is repaired in name only: the goal reads
    # `active`, a plan sits under it, and the world is exactly where the
    # refutation left it. So this is measured on the WORLD.
    #
    # A STATE goal, in its own domain with a rule that is still validated —
    # a withdrawn route over knowledge that survived, which is the case the
    # repair exists for. The plan is marked withdrawn directly; what produced
    # the withdrawal is section C's business, and this is about what happens
    # after one.
    ALT = DOMAIN + "_alt"
    alt_root = Path(tempfile.mkdtemp(prefix="replan01_alt_"))
    alt_world = World(alt_root, ["HALL", "LAB"], [("HALL", "LAB")])
    alt_world.place("z", "HALL")
    get_binding_registry().register(ALT, alt_world.binding())
    alt_rule = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=ALT, rule_kind="move"))[0]
    await store.validate(alt_rule, HELD_OUT)

    alt_goal = await engine.create_goal(
        "replan01 state goal", Priority.MEDIUM,
        state_conditions=["SBAT(z, LAB)"])
    alt_plan = Plan(
        id=f"plan_{uuid4().hex[:8]}", goal_id=alt_goal.id, status="invalidated",
        tasks=[Task(id="replan01_alt_0", type=TaskType.EXECUTION,
                    description="SBMOVE(z, HALL, LAB)", priority=Priority.MEDIUM,
                    status=TaskStatus.BLOCKED, created_at=datetime.now(),
                    provenance={"learned_rule_id": alt_rule.rule_id,
                                "domain_id": ALT,
                                "grounded_operator": "SBMOVE(z, HALL, LAB)"})])
    engine.active_plans[alt_plan.id] = alt_plan

    before_world = alt_world.observe()
    check("before the repair, z is still where the withdrawal left it",
          Fact("SBAT", ("z", "HALL")) in before_world,
          f"{sorted(str(f) for f in before_world if f.predicate == 'SBAT')}")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await coordinator.announce_route_withdrawal(
            goal_ids=[alt_goal.id], plan_ids=[alt_plan.id],
            rule_ids=[alt_rule.rule_id], tasks_blocked=1)
        moved = False
        for _ in range(150):
            await asyncio.sleep(0.1)
            if (alt_root / "LAB" / "z").exists():
                moved = True
                break

    check("THE WORLD MOVED — the repaired route was carried out, not just formed",
          moved and (alt_root / "LAB" / "z").exists()
          and not (alt_root / "HALL" / "z").exists(),
          f"LAB/z={(alt_root / 'LAB' / 'z').exists()} "
          f"HALL/z={(alt_root / 'HALL' / 'z').exists()}")

    new_plan = next((p for p in engine.active_plans.values()
                     if p.goal_id == alt_goal.id and p.status == "active"), None)
    intent_id = ((getattr(new_plan, "metadata", None) or {}).get("intent")
                 or {}).get("intent_id") if new_plan else None
    from core.reasoning.intent_authority import get_intent_authority
    # THE RECONCILIATION IS WAITED ON, LIKE THE MOVE. The world moving is the
    # route's STEP; reconciling the pursuit comes after it — the step still
    # records its evidence, and the route re-observes the world before it
    # reconciles. This read used to follow the move by one poll tick, the run
    # then ended ~100 ms later, and `asyncio.run` cancelled the route mid-record
    # (profiled: the step FAILED after 111 ms with CancelledError), so the
    # pursuit was never reconciled at all. A harness race, failing identically
    # since 2026-09-20 — not a missing reconciliation. Waited on the effect being
    # checked, and bounded, exactly as the move above is.
    intent = None
    for _ in range(100):
        intent = await get_intent_authority().get_by_id(intent_id) if intent_id else None
        if intent is not None and intent.outcome is not None:
            break
        await asyncio.sleep(0.1)
    check("the pursuit was RECONCILED — meant vs happened is recorded on it",
          intent is not None and intent.outcome is not None,
          f"intent={intent_id} outcome={getattr(intent, 'outcome', None)}")

    get_binding_registry().clear(ALT)
    shutil.rmtree(alt_root, ignore_errors=True)

    print("\n== F. Negative controls ==")
    report = await engine.replan_withdrawn_goals()
    check("a goal that already has a live plan is NOT replanned again",
          report["stranded"] == 0 and report["replanned"] == 0,
          f"stranded={report['stranded']} replanned={report['replanned']}")

    # A withdrawn STATE goal whose domain has no observer must be reported
    # unobservable, never planned against an invented empty world.
    blind_goal = await engine.create_goal(
        "replan01 unobservable", Priority.MEDIUM,
        state_conditions=["SBAT(z, NOWHERE)"])
    blind_plan = Plan(
        id=f"plan_{uuid4().hex[:8]}", goal_id=blind_goal.id, status="invalidated",
        tasks=[Task(id=f"replan01_blind_0", type=TaskType.EXECUTION,
                    description="SBMOVE(z, A, B)", priority=Priority.MEDIUM,
                    status=TaskStatus.BLOCKED, created_at=datetime.now(),
                    provenance={"learned_rule_id": stored.rule_id,
                                "domain_id": "a_domain_with_no_bindings",
                                "grounded_operator": "SBMOVE(z, A, B)"})])
    engine.active_plans[blind_plan.id] = blind_plan
    blind = await engine.replan_withdrawn_goals()
    check("a state goal whose world cannot be observed is reported UNOBSERVABLE",
          blind["unobservable"] == 1 and blind["replanned"] == 0,
          f"{ {k: v for k, v in blind.items() if k != 'goals'} }")
    check("...and it was not abandoned on a world nobody read",
          engine.current_goals[blind_goal.id].status == "active",
          f"status={engine.current_goals[blind_goal.id].status}")

    # ── cleanup ──────────────────────────────────────────────────────────────
    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    db = store.db()
    for table in ("rule_authority_events", "learned_rule_evidence"):
        await db.execute_query(
            f"DELETE FROM unified.{table} WHERE rule_id IN"
            f" (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)",
            (DOMAIN,))
    await db.execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))
    for table in ("rule_authority_events", "learned_rule_evidence"):
        await db.execute_query(
            f"DELETE FROM unified.{table} WHERE rule_id IN"
            f" (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)",
            (DOMAIN + "_alt",))
    await db.execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1",
        (DOMAIN + "_alt",))
    for goal_id in (stranded_goal.id, safe_goal.id, blind_goal.id, alt_goal.id):
        await db.execute_query("DELETE FROM unified.goals WHERE id = $1", (goal_id,))
    for plan in list(engine.active_plans.values()):
        if plan.goal_id in (stranded_goal.id, safe_goal.id, blind_goal.id,
                            alt_goal.id):
            await db.execute_query(
                "DELETE FROM unified.plans WHERE id = $1", (plan.id,))

    passed = sum(1 for c in CHECKS if c["passed"])
    print("\n" + "=" * 62)
    print(f"RESULT: {passed}/{len(CHECKS)} checks passed")
    print("=" * 62)

    await EV.verify_database()
    written = EV.write()
    print(f"\nrun record: {written}")
    return 0 if passed == len(CHECKS) else 1


sys.exit(asyncio.run(main()))
