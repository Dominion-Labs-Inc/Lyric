#!/usr/bin/env python3
"""REPLAN-02 — knock the substrate off course and see whether it gets there anyway.

Nothing here tells the substrate what to do at any step. It is given ONE state
goal and a world it has learned two ways to move in, and then the world is
POLLUTED: the corridor it trusts has been rerouted, so the operator it proved
its route over now delivers the file somewhere else entirely.

    rooms:   HALL --> LAB          (the direct way; POLLUTED)
             HALL --> ANNEX --> LAB (the long way; intact)

    SBMOVE   the operator it will plan over. Anything it moves toward LAB now
             lands in ANNEX instead -- the environment changed, and the rule the
             substrate learned is no longer true of it.
    SBHAUL   a second learned operator, still true of this world.

What must happen, with nothing driving it:

  1. it plans a route to SBAT(z, LAB) and runs it
  2. the world CONTRADICTS the rule -- z is in ANNEX, not LAB
  3. SBMOVE loses execution authority, and the plan standing on it is withdrawn
  4. the goal is replanned OVER WHAT IS STILL VALIDATED, from where z ACTUALLY
     IS -- not from where the withdrawn plan assumed it was
  5. the substrate carries the new route out and the file reaches LAB

Step 4 is the one worth watching. Replanning from the remembered world would
produce SBHAUL(z, HALL, ANNEX) -- a route from a room z left. Only re-observing
gives SBHAUL(z, ANNEX, LAB).

THE ONE THING THIS EXPERIMENT DRIVES BY HAND is the dispatch drain
(`get_next_tasks`), because that seam has no production caller -- a gap
RECONCILE-01 and DRIFT_CONSOLIDATION already record. It is called once, and
labelled where it happens, so nothing here reads as more wired than it is.
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

# THE STANDARD RECORD. This wrote a hand-rolled JSON with no `.md` beside it,
# so a run left nothing a person could read without opening the file.
EV = RunRecord(
    "REPLAN-02",
    claim=("Knocked off course by a world that no longer behaves as its learned rule "
           "says, the substrate refutes that rule, replans from where the file "
           "actually is over what is still validated, and gets it there anyway."),
    hypothesis=("If a contradicted operator loses execution authority and the route "
                "standing on it is withdrawn and replanned from a fresh observation, "
                "then one polluted operator does not strand the goal."))

DOMAIN = "replan02_world"
CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    EV.check(name, bool(passed), detail)
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class PollutedWorld:
    """Rooms are directories, the agent is a file, a move is the move_file tool.

    The pollution is a property of the WORLD, not of the substrate: `reroute`
    names a destination that no longer receives what is sent to it. The observer
    is honest throughout -- it reads the filesystem and reports what is there.
    """

    def __init__(self, root, rooms, paths):
        self.root, self.rooms, self.paths = root, list(rooms), list(paths)
        self.reroute = {}
        for r in self.rooms:
            (self.root / r).mkdir(parents=True, exist_ok=True)

    def place(self, agent, room):
        (self.root / room / agent).write_text("")

    def observe(self):
        from core.learning.rule_induction import Fact
        facts = set()
        for room in self.rooms:
            d = self.root / room
            if not d.is_dir():
                continue
            facts.add(Fact("SBOPEN", (room,)))
            for entry in d.iterdir():
                if entry.is_file():
                    facts.add(Fact("SBAT", (entry.name, room)))
        for a, b in self.paths:
            facts.add(Fact("SBPATH", (a, b)))
        return frozenset(facts)

    def binding(self, predicate, *, polluted):
        from core.execution.operator_binding import OperatorBinding

        def parameters(args):
            agent, origin, destination = args
            actual = self.reroute.get(destination, destination) if polluted \
                else destination
            return {"source_path": str(self.root / origin / agent),
                    "destination_path": str(self.root / actual / agent),
                    "create_dirs": False}

        return OperatorBinding(predicate=predicate, tool_name="move_file",
                               parameters=parameters, observe=self.observe)


def teaching_for(predicate):
    """Demonstrations of one mover, taught the same way for both operators."""
    from core.learning.rule_induction import Fact, TrainingExample
    F = Fact.parse

    def demo(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
        before = []
        if at:
            before.append(F(f"SBAT({who},{a})"))
        if path:
            before.append(F(f"SBPATH({a},{b})"))
        if opened:
            before.append(F(f"SBOPEN({b})"))
        before = tuple(before)
        ok = opened and path and acted and at
        after = (tuple(f for f in before if f != F(f"SBAT({who},{a})"))
                 + (F(f"SBAT({who},{b})"),)) if ok else before
        return TrainingExample(
            before=before, action=F(f"{predicate}({who},{a},{b})") if acted else None,
            after=after, positive=ok, evidence_id=f"{predicate}_{evidence_id}")

    teaching = [
        demo("a", "R1", "R2", "t1"), demo("b", "R3", "R4", "t2"),
        demo("c", "R5", "R6", "n1", opened=False),
        demo("d", "R7", "R8", "n2", path=False),
        demo("e", "R9", "R10", "n3", acted=False),
        demo("h", "R15", "R16", "n4", at=False),
    ]
    held_out = [demo("f", "R11", "R12", "h1"), demo("g", "R13", "R14", "h2")]
    return teaching, held_out


async def main():
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    if not getattr(coordinator, "_reactive_worker", None):
        raise SystemExit("the reactive drain worker is not running; refusing to "
                         "measure a path that cannot run.")

    from core.agents.autonomous.planning_engine import PlanningEngine
    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.agents.autonomous.shared_types import (
        Priority, SystemState, Task, TaskType)
    from core.execution.operator_binding import get_binding_registry
    from core.learning.rule_induction import Fact, get_rule_inducer
    from core.learning.rule_store import EpistemicStatus, RuleStore

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator,
          "constructing an AutonomousCoordinator anywhere would displace it")

    # ── the world, and the two ways it has been learned ──────────────────────
    root = Path(tempfile.mkdtemp(prefix="replan02_"))
    world = PollutedWorld(root, ["HALL", "LAB", "ANNEX"],
                          [("HALL", "LAB"), ("HALL", "ANNEX"), ("ANNEX", "LAB")])
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding("SBMOVE", polluted=True))
    get_binding_registry().register(DOMAIN, world.binding("SBHAUL", polluted=False))

    store = RuleStore()
    await store.ensure_schema()
    rules = {}
    for predicate in ("SBMOVE", "SBHAUL"):
        teaching, held_out = teaching_for(predicate)
        stored = (await store.record_induction(
            get_rule_inducer().induce(teaching), teaching,
            domain_id=DOMAIN, rule_kind=predicate.lower()))[0]
        await store.validate(stored, held_out)
        rules[predicate] = stored

    engine = PlanningEngine({"max_concurrent_tasks": 10_000})
    assert await engine.initialize() is True
    coordinator.planning = engine

    print("\n== A. Two operators, both earned ==")
    executable = {r.rule_id for r in await store.executable_rules(domain_id=DOMAIN)}
    check("the substrate holds BOTH movers as executable knowledge",
          all(rules[p].rule_id in executable for p in ("SBMOVE", "SBHAUL")),
          f"{ {p: rules[p].status.value for p in rules} }")

    # ── the pollution: the corridor into LAB has been rerouted ───────────────
    world.reroute["LAB"] = "ANNEX"
    print(f"\n== B. The world is polluted — anything SBMOVEd toward LAB now "
          f"lands in ANNEX ==")

    # ── ONE goal, handed over, and nothing else ──────────────────────────────
    print("\n== C. Given one goal: get z to LAB. Nothing is told what to do ==")
    task = Task(id="replan02_pursuit", type=TaskType.EXECUTION,
                description="get z to LAB",
                priority=Priority.MEDIUM,
                provenance={"domain_id": DOMAIN,
                            "goal_conditions": ["SBAT(z, LAB)"]})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        first = await coordinator.execute_task(task)

    where = lambda: next((f.args[1] for f in world.observe()
                          if f.predicate == "SBAT" and f.args[0] == "z"), None)
    check("it planned a route on its own and acted",
          first is not None and first.get("execution_path") == "substrate_plan",
          f"path={None if first is None else first.get('execution_path')} "
          f"steps={None if first is None else first.get('steps_executed')}")
    check("the polluted world defeated the attempt — z did NOT reach LAB",
          where() == "ANNEX", f"z is in {where()}")
    check("...and the substrate did not claim success",
          first is not None and first.get("success") is False,
          f"success={None if first is None else first.get('success')}")

    print("\n== D. The knowledge that stopped being true lost its authority ==")
    reloaded = {r.rule_id: r for r in await store.load(domain_id=DOMAIN)}
    check("SBMOVE was REFUTED by the world",
          reloaded[rules["SBMOVE"].rule_id].status is EpistemicStatus.REFUTED,
          f"status={reloaded[rules['SBMOVE'].rule_id].status.value}")
    check("SBHAUL was NOT touched — one bad operator is not all of them",
          reloaded[rules["SBHAUL"].rule_id].status is EpistemicStatus.VALIDATED,
          f"status={reloaded[rules['SBHAUL'].rule_id].status.value}")

    print("\n== E. The withdrawal, and then the substrate on its own ==")
    print("   (the ONE hand-driven call: the dispatch seam has no production caller)")
    import logging
    _caught = []
    class _Grab(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                _caught.append(record.getMessage()[:240])
    _h = _Grab()
    _pursued = []
    _orig_pursue = coordinator._pursue_proved_route
    async def _spy_pursue(plan, **kw):
        r = await _orig_pursue(plan, **kw)
        _pursued.append({"plan": plan.id, "kw": {k: v for k, v in kw.items()},
                         "success": r.get("success"),
                         "intent_outcome": r.get("intent_outcome"),
                         "error": r.get("error")})
        return r
    coordinator._pursue_proved_route = _spy_pursue
    import traceback as _tb
    from core.tools import get_tool_registry as _gtr
    _reg = _gtr()
    _moves = []
    _orig_exec = _reg.execute_tool
    async def _spy_exec(name, params=None, *a, **kw):
        if name == "move_file":
            _moves.append((str((params or {}).get("destination_path", ""))[-24:],
                           [l.strip()[:90] for l in _tb.format_stack()[-7:-1]]))
        return await _orig_exec(name, params, *a, **kw)
    _reg.execute_tool = _spy_exec
    _reacted = []
    _orig_react = coordinator._react_route_withdrawn
    async def _spy_react(event):
        _reacted.append(("entered", event.payload.goal_ids))
        try:
            r = await _orig_react(event)
            _reacted.append(("returned", None))
            return r
        except Exception as e:
            _reacted.append(("raised", f"{type(e).__name__}: {e}"))
            raise
    for bucket in coordinator._reactions.values():
        for reaction in bucket:
            if reaction["name"] == "replan_withdrawn_routes":
                reaction["handler"] = _spy_react
    logging.getLogger("core.agents.autonomous.autonomous_coordinator").addHandler(_h)
    logging.getLogger("core.reasoning.intent_authority").addHandler(_h)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await engine.get_next_tasks(SystemState())
        reached = False
        for _ in range(200):
            await asyncio.sleep(0.1)
            if where() == "LAB":
                reached = True
                break

    for dest, stack in _moves:
        print(f"   [move] -> {dest}")
        for line in stack:
            print(f"          {line}")
    print(f"   [react] {_reacted}")
    print(f"   [pursue] n={len(_pursued)}")
    for r in _pursued:
        print(f"   [pursue] {r}")
    for m in _caught:
        print(f"   [log] {m}")
    check("THE SUBSTRATE GOT z TO LAB — it replanned and carried it out",
          reached and where() == "LAB", f"z is in {where()}")

    new_plans = [p for p in engine.active_plans.values() if p.status == "active"
                 and any((t.provenance or {}).get("domain_id") == DOMAIN
                         for t in p.tasks)]
    routes = [t.description for p in new_plans for t in p.tasks]
    check("the new route is over SBHAUL, not the refuted operator",
          routes and all("SBMOVE" not in r for r in routes),
          f"route={routes}")
    check("it replanned FROM WHERE z ACTUALLY WAS, not from the remembered world",
          any("ANNEX" in r for r in routes) and not any("HALL" in r for r in routes),
          f"route={routes} — a remembered world would start from HALL")

    print("\n== F. The pursuit was closed out, not just executed ==")
    from core.reasoning.intent_authority import get_intent_authority
    intent_ids = [((plan.metadata or {}).get("intent") or {}).get("intent_id")
                  for plan in new_plans]
    intent_ids = [i for i in intent_ids if i]
    # THE RECONCILIATION IS WAITED ON, LIKE THE MOVE — the race REPLAN-01 had
    # (fixed there 2026-09-25). z reaching LAB is the route's STEP; the pursuit
    # is reconciled after it, once the step's evidence is recorded and the world
    # re-observed. This read followed the move by one poll tick, while the
    # pursuit was still running (`[pursue] n=0`: it had not returned), and
    # failed 10/11 on 2026-09-26. Waited on the effect being checked, and
    # bounded, exactly as the move above is.
    intents = []
    for _ in range(100):
        intents = [await get_intent_authority().get_by_id(i) for i in intent_ids]
        if intents and all(i is not None and i.outcome is not None for i in intents):
            break
        await asyncio.sleep(0.1)
    closed = [i for i in intents if i is not None and i.outcome is not None]
    for i in intents:
        if i is not None:
            print(f"   [diag] status={i.status} outcome={i.outcome}")
            print(f"   [diag] shape.goal_conditions={i.goal_conditions}")
    print(f"   [diag] world now = {sorted(str(f) for f in world.observe())}")
    check("the replanned pursuit carries a reconciled outcome",
          bool(closed),
          f"{len(intents)} intent(s), {len(closed)} reconciled: "
          f"{[ (i.status, (i.outcome or {}).get('matched_aim')) for i in intents ]}")

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
    for plan in list(engine.active_plans.values()):
        if any((t.provenance or {}).get("domain_id") == DOMAIN for t in plan.tasks):
            await db.execute_query("DELETE FROM unified.plans WHERE id = $1",
                                   (plan.id,))
            await db.execute_query("DELETE FROM unified.goals WHERE id = $1",
                                   (plan.goal_id,))

    passed = sum(1 for c in CHECKS if c["passed"])
    print("\n" + "=" * 64)
    print(f"RESULT: {passed}/{len(CHECKS)} checks passed")
    print("=" * 64)

    await EV.verify_database()
    written = EV.write()
    print(f"\nrun record: {written}")
    return 0 if passed == len(CHECKS) else 1


sys.exit(asyncio.run(main()))
