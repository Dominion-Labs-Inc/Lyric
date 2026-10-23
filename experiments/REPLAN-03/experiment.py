#!/usr/bin/env python3
"""REPLAN-03 — the substrate's OWN domain, its OWN operator, and a world that
keeps changing under it.

REPLAN-02 proved the repair machinery inside a world this experiment's author
built: invented predicates, bound to tools by hand, taught from hand-written
demonstrations. That shows the mechanism and not the substrate. This one uses
what the substrate actually has:

    learning/exploration.derive_domain    a real sandbox directory as a domain it
                                          may practise in: the place and the act
                                          are declared, the world is the self's
                                          own perception of what is there (the
                                          KIND and SIZE of each path)
    core/learning/exploration.py          the substrate ACTING IN ORDER TO LEARN
                                          -- it tries the domain's own candidate
                                          actions and induces the operator from
                                          what happens

Nothing here writes a demonstration or names a precondition. The operator is
whatever the substrate induced from acting.

One thing IS declared rather than learned: WHICH ACT may be practised here.
The sandbox names `move_file`; the operator's arguments are the tool's own
declared parameters. What the substrate learns by acting is the RULE -- what
the operator requires and what it does.

THE TWO POLLUTIONS, both real changes to the world and neither a change to the
substrate's wiring:

  P1  something else moves the file while a route to it is being carried out.
      No rule is refuted -- MOVE_FILE is still perfectly true. The plan is just
      a route from a state that has moved on.
  P2  the destination directory is taken away and a plain file put in its
      place, so the tool genuinely fails and the world does not move as the
      operator predicted. (Only removing the directory no longer does it:
      `move_file` recreates a missing destination directory by default.)

P1 is the case that had no repair at all until now: replanning fired only on
refutation, so a pursuit knocked off course by an ordinary change in the world
stopped at the diverged step and stayed there with the goal still reading
`active`. That was ours to fix, not a fact about the world.

The repair is the pursuit's own (`_drive_substrate_goal`): when a walk stops it
plans again, inside the same pursuit, when something is new since the route was
proved. Each route is recorded on the pursuit's route intent, so the routes it
tried are read there (`earlier_attempts`).
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DOMAIN = "replan03_workspace"
CHECKS = []
EV = None


def _record():
    """This run's record, made once the repository is importable."""
    global EV
    if EV is None:
        from experiments._evidence import RunRecord
        EV = RunRecord('REPLAN-03',
                       claim='The substrate learns its own operator by practice in a directory it was given, and pursues a goal over it while the world changes under it: it replans when the route goes stale and never claims a goal the world refused.',
                       hypothesis='If practice teaches the operator and repair is driven by the world, then a moved file is re-routed without refuting the rule, a destination the tool cannot use stops the pursuit honestly, and an unchanged world spawns no endless replans.')
    return EV


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    _record().check(name, bool(passed), str(detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def forget_the_domain():
    """Remove everything this experiment's own domain holds: its bindings, its
    rules and their evidence, the demonstrations it practised, and what waits to
    be induced. The domain id is this experiment's alone, so nothing else is
    touched. Run at the start too, so the operator the checks read is the one
    THIS run induced from acting, not one an earlier run left behind."""
    from experiments._domains import forget_domain
    await forget_domain(DOMAIN)


#: This run's own: a pursuit's route intent is keyed by its task, so a task id
#: an earlier run used would return to that run's intent and its attempts.
RUN = uuid.uuid4().hex[:8]
ROUTE_INTENTS = []


async def routes_tried(task_id):
    """The routes a pursuit proved, read from its route intent: the one it holds
    now, and every earlier attempt it planned again from."""
    from core.reasoning.intent_authority import (
        SUBSTRATE_ACTOR, continuity_goal, get_intent_authority)
    held = await get_intent_authority().get(
        SUBSTRATE_ACTOR, continuity_goal(f"{task_id}:route"))
    if held is None:
        return None, 0
    ROUTE_INTENTS.append(held.intent_id)
    return held, 1 + len(held.shape.get("earlier_attempts") or [])


async def forget_the_routes():
    """The route intents this run's pursuits formed."""
    from core.reasoning.intent_authority import get_intent_authority
    db = get_intent_authority().store.db
    for table in ("unified.scoped_intents", "unified.intents"):
        await db.execute_query(f"DELETE FROM {table} WHERE intent_id = ANY($1::text[])",
                               (sorted(set(ROUTE_INTENTS)),), commit=True)


async def main():
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    if not getattr(coordinator, "_reactive_worker", None):
        raise SystemExit("the reactive drain worker is not running.")

    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    from core.learning.exploration import derive_domain, take_up_workspace
    from core.perception.perception_faculty import sensed_fact, world_of
    from core.tools.tool_registry import get_binding_registry
    from core.learning.exploration import SubstrateExplorer, get_proposer
    from core.learning.rule_store import EpistemicStatus, get_rule_store

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator, "")

    # ── a real directory, handed over as a workspace ─────────────────────────
    root = Path(tempfile.mkdtemp(prefix="replan03_"))
    for d in ("inbox", "review", "archive"):
        (root / d).mkdir()
    (root / "inbox" / "report.txt").write_text("the quarterly numbers\n")

    def report_in(d):
        return sensed_fact("kind", "path", str(root / d / "report.txt"), "file")

    await forget_the_domain()

    # The sandbox a person hands over: this directory, and the act it may be
    # practised with. Everything else is the substrate's own doing.
    declared = derive_domain(
        DOMAIN, observations=[("list_directory", {"directory_path": str(root)})],
        actions=["move_file"])
    take_up_workspace(DOMAIN, str(root))
    world = world_of(DOMAIN)
    print("\n== A. A sandbox it may practise in, perceived by the self ==")
    check("the domain is bound — observable and actable",
          declared.get("actable") and get_proposer(DOMAIN) is not None,
          f"operators: {[b.predicate for b in get_binding_registry().bindings_for(DOMAIN)]}")
    check("it reads the real directory as its world",
          report_in("inbox") in (world.observe() or ()),
          f"{len(world.observe() or ())} fact(s)")

    # ── the substrate acts in order to learn the operator ────────────────────
    print("\n== B. It ACTS IN ORDER TO LEARN — no demonstration is written here ==")
    store = get_rule_store()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        cycles = []
        for _ in range(6):
            cycles.append(await SubstrateExplorer().explore(
                DOMAIN, get_proposer(DOMAIN), max_actions=8, reinduce=True))
            learned = [r for r in await store.executable_rules(domain_id=DOMAIN)]
            if learned:
                break
    acted = sum(c.get("acted", 0) or 0 for c in cycles)
    check("it tried real actions in the real world to find out what they do",
          acted > 0, f"{acted} action(s) over {len(cycles)} cycle(s)")
    rules = {r.rule_id: r for r in await store.load(domain_id=DOMAIN)}
    executable = await store.executable_rules(domain_id=DOMAIN)
    check("it INDUCED an executable MOVE_FILE operator from what happened",
          bool(executable),
          f"{[(r.rule_id[:14], getattr(r, 'status', None) and r.status.value) for r in rules.values()]}")
    if not executable:
        print("\n  exploration did not yield an operator; the rest of this "
              "experiment has nothing to plan over.")
        for c in cycles:
            print(f"    cycle: { {k: v for k, v in c.items() if k != 'demonstrations'} }")
        shutil.rmtree(root, ignore_errors=True)
        await forget_the_domain()
        await _record().verify_database()
        print(f"run record: {_record().write()}")
        return 1

    def where():
        seen = world.observe() or ()
        return next((d for d in ("inbox", "review", "archive") if report_in(d) in seen), None)

    # exploration's round trips leave the file back where it started
    for d in ("review", "archive"):
        stray = root / d / "report.txt"
        if stray.exists():
            shutil.move(str(stray), str(root / "inbox" / "report.txt"))

    def goal_task(label):
        return Task(id=f"replan03_{label}_{RUN}", type=TaskType.EXECUTION,
                    description="file the report",
                    priority=Priority.MEDIUM,
                    provenance={"domain_id": DOMAIN,
                                "workspace_root": str(root),
                                "goal_conditions": [
                                    report_in("archive").to_formula(),
                                    "¬" + report_in("inbox").to_formula()]})

    # ── P1: something else moves the file mid-pursuit ────────────────────────
    print("\n== C. POLLUTION 1 — something else moves the file under it ==")
    print("   (no rule is refuted; the route is simply from a state that moved on)")

    # What stood before this pollution, so the check below asks what IT did:
    # practice may already have refuted a first, incomplete rule on its way to
    # the one it keeps, and that is learning, not this scenario.
    standing = {r.rule_id for r in await store.load(domain_id=DOMAIN)
                if r.status is not EpistemicStatus.REFUTED}
    moved_once = {"done": False}
    registry = get_binding_registry()
    original = registry.get(DOMAIN, "MOVE_FILE")

    from core.tools.tool_registry import OperatorBinding

    def meddle(args):
        # THE WORLD CHANGES, NOT THE SUBSTRATE. Before the first move is
        # carried out, something else in the world relocates the file. The
        # parameters the substrate computed are left exactly as they are --
        # they now name a source that is no longer there, which is precisely
        # what a stale route is.
        params = original.parameters(args)
        if not moved_once["done"]:
            moved_once["done"] = True
            src = root / "inbox" / "report.txt"
            if src.exists():
                shutil.move(str(src), str(root / "review" / "report.txt"))
        return params

    registry.register(DOMAIN, OperatorBinding(
        predicate="MOVE_FILE", tool_name=original.tool_name,
        parameters=meddle, observe=original.observe))

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        first = await coordinator.execute_task(goal_task("p1"))

    registry.register(DOMAIN, original)
    route_p1, tried_p1 = await routes_tried(f"replan03_p1_{RUN}")
    check("the first route was knocked off course, and the SAME pursuit planned again",
          moved_once["done"] and tried_p1 >= 2,
          f"{tried_p1} route(s) recorded on the pursuit's route intent")
    moved = {r.rule_id: r.status for r in await store.load(domain_id=DOMAIN)}
    check("nothing was refuted — MOVE_FILE is still true of this world",
          standing and all(moved.get(rule_id) is not EpistemicStatus.REFUTED
                           for rule_id in standing),
          f"{ {k[:14]: v.value for k, v in moved.items()} }; standing before: "
          f"{sorted(r[:14] for r in standing)}")
    check("IT REPLANNED FROM WHERE THE FILE ACTUALLY WENT AND FINISHED THE JOB",
          first is not None and first.get("success") is True and where() == "archive",
          f"success={None if first is None else first.get('success')}; "
          f"report.txt is in {where()} (expected archive)")

    # ── P2: the destination is taken away ────────────────────────────────────
    print("\n== D. POLLUTION 2 — the destination directory is taken away ==")
    print("   (the tool genuinely fails; the world does not move as predicted)")
    if where() == "archive":
        shutil.move(str(root / "archive" / "report.txt"),
                    str(root / "inbox" / "report.txt"))
    shutil.rmtree(root / "archive")
    (root / "archive").write_text("not a directory any more\n")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        second = await coordinator.execute_task(goal_task("p2"))
        await asyncio.sleep(3)

    check("it did not claim to have filed a report into a place that is gone",
          second is not None and second.get("success") is False,
          f"success={None if second is None else second.get('success')} "
          f"status={None if second is None else second.get('planning_status')}")
    check("the file is still somewhere real — nothing was destroyed chasing it",
          (root / "inbox" / "report.txt").exists()
          or (root / "review" / "report.txt").exists(),
          f"report.txt is in {where()}")
    route_p2, _ = await routes_tried(f"replan03_p2_{RUN}")
    check("the route that stopped was closed as NOT reached, not left standing",
          route_p2 is not None and route_p2.concluded and route_p2.status != "fulfilled"
          and (route_p2.outcome or {}).get("matched_aim") is False,
          f"route intent {None if route_p2 is None else route_p2.status}; "
          f"planning_status={second.get('planning_status')}")

    # ── the loop guard ───────────────────────────────────────────────────────
    print("\n== E. Repair is driven by the world, not by a retry count ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        third = await coordinator.execute_task(goal_task("p3"))
    _, tried_p3 = await routes_tried(f"replan03_p3_{RUN}")
    check("an unchanged world does not spawn endless replans",
          third is not None and third.get("success") is False and tried_p3 <= 2,
          f"{tried_p3} route(s) tried before the pursuit ended")

    # ── cleanup ──────────────────────────────────────────────────────────────
    shutil.rmtree(root, ignore_errors=True)
    await forget_the_domain()
    await forget_the_routes()

    passed = sum(1 for c in CHECKS if c["passed"])
    print("\n" + "=" * 64)
    print(f"RESULT: {passed}/{len(CHECKS)} checks passed")
    print("=" * 64)
    await _record().verify_database()
    print(f"\nrun record: {_record().write()}")
    return 0 if passed == len(CHECKS) else 1


sys.exit(asyncio.run(main()))
