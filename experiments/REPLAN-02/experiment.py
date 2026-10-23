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
  3. SBMOVE loses execution authority, and the route standing on it stops
  4. the SAME pursuit plans again OVER WHAT IS STILL VALIDATED, from where z
     ACTUALLY IS -- not from where the stopped route assumed it was
  5. the substrate carries the new route out and the file reaches LAB

Step 4 is the one worth watching. Replanning from the remembered world would
produce SBHAUL(z, HALL, ANNEX) -- a route from a room z left. Only re-observing
gives SBHAUL(z, ANNEX, LAB).

NOTHING IS DRIVEN BY HAND. The goal is handed over once (`execute_task`), and
the repair is the pursuit's own (`_drive_substrate_goal`): when its walk stops
over a rule that lost its authority, it plans again inside itself. Each route is
recorded on the pursuit's route intent, so the routes it tried are read there.
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

from experiments._evidence import RunRecord  # noqa: E402

# THE STANDARD RECORD. This wrote a hand-rolled JSON with no `.md` beside it,
# so a run left nothing a person could read without opening the file.
EV = RunRecord(
    "REPLAN-02",
    claim=("Knocked off course by a world that no longer behaves as its learned rule "
           "says, the substrate refutes that rule, replans from where the file "
           "actually is over what is still validated, and gets it there anyway."),
    hypothesis=("If a contradicted operator loses execution authority and the route "
                "standing on it is planned again from a fresh observation, "
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
        from core.tools.tool_registry import OperatorBinding

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

    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    from core.tools.tool_registry import get_binding_registry
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
    # This run's own: a pursuit's route intent is keyed by its task, so an id an
    # earlier run used would return to that run's intent and its attempts.
    task = Task(id=f"replan02_pursuit_{uuid.uuid4().hex[:8]}",
                type=TaskType.EXECUTION,
                description="get z to LAB",
                priority=Priority.MEDIUM,
                provenance={"domain_id": DOMAIN,
                            "goal_conditions": ["SBAT(z, LAB)"]})
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        first = await coordinator.execute_task(task)

    where = lambda: next((f.args[1] for f in world.observe()
                          if f.predicate == "SBAT" and f.args[0] == "z"), None)
    from core.reasoning.intent_authority import (
        SUBSTRATE_ACTOR, continuity_goal, get_intent_authority)
    route = await get_intent_authority().get(
        SUBSTRATE_ACTOR, continuity_goal(f"{task.id}:route"))
    earlier = list((route.shape.get("earlier_attempts") or []) if route else [])
    check("it planned a route on its own and acted",
          first is not None and first.get("execution_path") == "substrate_plan",
          f"path={None if first is None else first.get('execution_path')} "
          f"steps={None if first is None else first.get('steps_executed')}")
    check("the polluted world defeated the FIRST route — it did not reach LAB by it",
          bool(earlier) and (earlier[0].get("outcome") or {}).get("matched_aim") is False,
          f"{len(earlier)} earlier route(s); first ended "
          f"{earlier[0].get('status') if earlier else None}")

    print("\n== D. The knowledge that stopped being true lost its authority ==")
    reloaded = {r.rule_id: r for r in await store.load(domain_id=DOMAIN)}
    check("SBMOVE was REFUTED by the world",
          reloaded[rules["SBMOVE"].rule_id].status is EpistemicStatus.REFUTED,
          f"status={reloaded[rules['SBMOVE'].rule_id].status.value}")
    check("SBHAUL was NOT touched — one bad operator is not all of them",
          reloaded[rules["SBHAUL"].rule_id].status is EpistemicStatus.VALIDATED,
          f"status={reloaded[rules['SBHAUL'].rule_id].status.value}")

    print("\n== E. The same pursuit planned again, on its own ==")
    check("THE SUBSTRATE GOT z TO LAB — it planned again and carried it out",
          first is not None and first.get("success") is True and where() == "LAB",
          f"success={None if first is None else first.get('success')}; z is in {where()}")
    routes = list(route.shape.get("operators") or []) if route else []
    check("the new route is over SBHAUL, not the refuted operator",
          routes and all("SBMOVE" not in r for r in routes),
          f"route={routes}")
    check("it replanned FROM WHERE z ACTUALLY WAS, not from the remembered world",
          any("ANNEX" in r for r in routes) and not any("HALL" in r for r in routes),
          f"route={routes} — a remembered world would start from HALL")

    print("\n== F. The pursuit was closed out, not just executed ==")
    check("the replanned pursuit carries a reconciled outcome",
          route is not None and route.status == "fulfilled"
          and (route.outcome or {}).get("matched_aim") is True,
          f"route intent {None if route is None else route.status}: "
          f"{None if route is None else route.outcome}")

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
    if route is not None:
        for table in ("unified.scoped_intents", "unified.intents"):
            await get_intent_authority().store.db.execute_query(
                f"DELETE FROM {table} WHERE intent_id = $1", (route.intent_id,), commit=True)

    passed = sum(1 for c in CHECKS if c["passed"])
    print("\n" + "=" * 64)
    print(f"RESULT: {passed}/{len(CHECKS)} checks passed")
    print("=" * 64)

    await EV.verify_database()
    written = EV.write()
    print(f"\nrun record: {written}")
    return 0 if passed == len(CHECKS) else 1


sys.exit(asyncio.run(main()))
