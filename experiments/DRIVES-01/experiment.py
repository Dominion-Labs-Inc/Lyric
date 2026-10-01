"""DRIVES-01 — the drives are measured from many authorities, and every one is consumed.

Three defects, measured in the live tree before this, and closed here.

  1. NO DRIVE WAS A MEASUREMENT. Each of the seven was a constant (0.5, 0.7, 0.4)
     adjusted by KEYWORD MATCHES on goal text — `"explore" in description` moved
     curiosity, `"master"` moved mastery, `"help"` moved social — and each
     swallowed its exceptions into the same middling default. A drive could be
     changed by how a goal was PHRASED, and an unmeasured one was indistinguishable
     from a genuine mid-level pull.

  2. MOTIVATION COMPUTED ITS OWN PRESSURE. `_experience_pressure` derived an
     exploration pressure from the sign of accumulated reward and fed curiosity.
     `appraisal.py`'s module docstring names that exact function as the coupling
     `AppraisalState` was built to replace — "interpretation happens ONCE, with
     context, rather than N times in N consumers". It never was replaced.

  3. THREE DRIVES HAD NO CONSUMER, AND THE OTHER FOUR NEVER REACHED APPRAISAL.
     mastery / autonomy / social were read by nothing anywhere. And the documented
     link `activation <- IntrinsicMotivationSystem total_reward` (appraisal.py)
     was never made by any caller: no `appraisal.update()` in the tree passed
     `motivation_state`, so `activation` was unmeasured on every appraisal and
     everything downstream of it — `eagerness`, `approach_pressure`, and through
     that the arbiter's breadth — was computed without the substrate's drive.

Real measurement sources, real appraisal, real store. No stubs.

Run: ./venv_lyric/bin/python3 experiments/DRIVES-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "DRIVES-01",
    claim=("Every drive is the mean of terms READ from the authorities that own "
           "them — several authorities per drive, never one axis — with unreadable "
           "terms named and excluded rather than defaulted. A drive nothing can be "
           "measured for is absent, not 0.5. Motivation computes no pressure of its "
           "own: it reads appraisal's. And every drive is consumed — through the "
           "drive level into appraisal's activation, and through the situation "
           "features the substrate conditions its own performance claims on."),
    hypothesis=("If the drives were still keyword-scored, changing the WORDING of "
                "the goals in context would move them. If they were still "
                "baseline-filled, a drive with no readable source would come back "
                "0.5 instead of absent. If the drive level still went nowhere, "
                "feeding it to appraisal would leave `activation` unmeasured."))

results = []


def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


DRIVES = ("curiosity", "competence", "novelty", "mastery",
          "autonomy", "social", "impact")


async def main() -> int:
    from core.database import get_database_manager
    from core.agents.autonomous.intrinsic_motivation import (
        get_intrinsic_motivation_system, IntrinsicMotivationSystem, DriveReading)
    from core.agents.autonomous.appraisal import get_appraisal_system, AppraisalState
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.learning.meta_learning import OutcomeClass

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    ims = get_intrinsic_motivation_system()
    await ims.initialize()
    appraisal = get_appraisal_system()

    # ── 1. Every drive is MEASURED, from SEVERAL authorities ──────────────────
    print("\n== 1. Each drive is the mean of terms read from several authorities ==")
    state = await ims.calculate_motivation({})
    readings = state["drive_readings"]

    check("all seven drives were attempted", set(readings) == set(DRIVES),
          f"{sorted(readings)}")
    check("no drive rests on a single axis (every one declares >= 2 terms)",
          all(len(r["terms"]) + len(r["unmeasured"]) >= 2 for r in readings.values()),
          "; ".join(f"{k}={len(v['terms']) + len(v['unmeasured'])}"
                    for k, v in readings.items()))
    check("each level IS the mean of the terms actually measured — nothing added",
          all(r["level"] is None or
              abs(r["level"] - sum(r["terms"].values()) / len(r["terms"])) < 1e-9
              for r in readings.values() if r["terms"]))
    check("an unreadable term is NAMED, never counted as zero",
          all(k not in r["terms"] for r in readings.values() for k in r["unmeasured"]))
    check("every measured level carries the raw counts it was derived from",
          all(r["sources"] for r in readings.values() if r["terms"]),
          "; ".join(f"{k}:{list(v['sources'])[:2]}"
                    for k, v in readings.items() if v["terms"]))

    measured_now = [k for k, r in readings.items() if r["level"] is not None]
    EV.metric("drives_measured", len(measured_now), "count", "of seven, this run")
    for name in DRIVES:
        lvl = readings[name]["level"]
        if lvl is not None:
            EV.metric(f"drive_{name}", round(lvl, 4), "level [0,1]",
                      f"terms: {', '.join(readings[name]['terms'])}")

    # ── 2. Wording cannot move a drive ────────────────────────────────────────
    print("\n== 2. A drive cannot be moved by how a goal is WORDED ==")
    worded = SimpleNamespace(description=(
        "explore and discover and investigate and learn and master a deep "
        "comprehensive understanding, help collaborate communicate share, "
        "improve optimize enhance upgrade impact"))
    loaded = await ims.calculate_motivation({
        "active_goals": [worded, worded, worded],
        "perception": SimpleNamespace(confidence=0.1,
                                      content={"novel_elements": True,
                                               "unknown_patterns": True}),
        "context": {"user_interactions": True, "collaboration_tasks": True},
    })
    plain = await ims.calculate_motivation({})
    moved = [d for d in DRIVES
             if (loaded["dimensions"].get(d) is None) != (plain["dimensions"].get(d) is None)
             or (loaded["dimensions"].get(d) is not None
                 and abs(loaded["dimensions"][d] - plain["dimensions"][d]) > 1e-9)]
    check("goal wording, 'novel_elements' and 'collaboration_tasks' move NOTHING",
          not moved, f"moved={moved or 'none'}")
    EV.metric("drives_moved_by_wording", len(moved), "count",
              "every keyword the old scorers matched on, in one goal")

    # ── 3. Absence is absence ─────────────────────────────────────────────────
    print("\n== 3. A drive nothing can be measured for is ABSENT, not 0.5 ==")
    reading = DriveReading(name="probe", level=None)
    level, terms, unmeasured = IntrinsicMotivationSystem._drive_level(
        {"a": None, "b": None})
    check("no measurable term -> level is None", level is None and terms == {})
    check("and both terms are named unmeasured", sorted(unmeasured) == ["a", "b"])
    level2, terms2, _ = IntrinsicMotivationSystem._drive_level({"a": 0.8, "b": None})
    check("one measurable term -> the mean is over THAT term, not over two",
          abs(level2 - 0.8) < 1e-9, f"level={level2}")
    check("a None level never enters `dimensions`",
          all(v is not None for v in state["dimensions"].values())
          and set(state["dimensions"]) | set(state["drives_unmeasured"]) == set(DRIVES))
    check("the reading dataclass admits an unmeasured drive at all",
          reading.level is None and reading.to_dict()["level"] is None)

    # total reward over measured only
    ims.weights.curiosity = ims.weights.competence = 1.0
    total_one = ims._calculate_total_reward({"curiosity": 0.8})
    total_two = ims._calculate_total_reward({"curiosity": 0.8, "competence": 0.2})
    check("total drive level is the weighted mean of the MEASURED drives only",
          abs(total_one - 0.8) < 1e-9 and abs(total_two - 0.5) < 1e-9,
          f"one={total_one} two={total_two}")
    check("nothing measured -> no drive level at all (was 0.5)",
          ims._calculate_total_reward({}) is None)

    # ── 4. Motivation computes no pressure of its own ─────────────────────────
    print("\n== 4. The pressure comes from the ONE appraisal authority ==")
    check("`_experience_pressure` is gone from the motivation system",
          not hasattr(ims, "_experience_pressure"))
    check("curiosity declares exploration_pressure as one of its terms",
          "exploration_pressure" in (set(readings["curiosity"]["terms"])
                                     | set(readings["curiosity"]["unmeasured"])))

    appraisal.current_state = None
    quiet = await ims._measure_curiosity()
    check("with NO appraisal, the pressure term is unmeasured — not invented",
          "exploration_pressure" in quiet.unmeasured)

    eager = AppraisalState(epistemic_opportunity=0.9, controllability=0.9, risk=0.0)
    from core.agents.autonomous.appraisal import _derive_pressures
    _derive_pressures(eager)
    appraisal.current_state = eager
    keen = await ims._measure_curiosity()
    check("with a state that WANTS to explore, curiosity reads that pressure",
          keen.terms.get("exploration_pressure", 0) >= 0.35
          and keen.level > (quiet.level or 0.0),
          f"pressure={keen.terms.get('exploration_pressure')} "
          f"curiosity {quiet.level} -> {keen.level}")

    # ── 5. The drives REACH appraisal ─────────────────────────────────────────
    print("\n== 5. The drive level reaches appraisal, and attribution survives ==")
    appraisal.current_state = None
    appraisal.update(outcome_quality=0.2, action_success_rate=0.3,
                     outcome_class=OutcomeClass.STRATEGY_FAILURE,
                     self_initiated=True, goal_alignment_score=0.9)
    before = appraisal.current_state
    check("an outcome alone leaves activation UNMEASURED (the old steady state)",
          before.activation is None and "activation" in before.unmeasured)
    check("and it records the attribution of that outcome",
          before.attribution == "strategy_failure")

    fed = await ims.calculate_motivation({})
    appraisal.update(motivation_state=fed)
    after = appraisal.current_state
    check("feeding the drive level MEASURES activation",
          after.activation is not None
          and abs(after.activation - fed["total_reward"]) < 1e-6,
          f"activation={after.activation} total_reward={fed['total_reward']}")
    check("the attribution of the last outcome SURVIVES the partial update",
          after.attribution == "strategy_failure",
          "it was overwritten with None before this")
    check("approach pressure — which the arbiter reads — now includes the drive",
          after.approach_pressure > 0.0, f"approach={after.approach_pressure:.3f}")
    check("so does eagerness, the named emotion built on activation",
          after.eagerness is not None, f"eagerness={after.eagerness}")

    # ── 6. Every drive is consumed ────────────────────────────────────────────
    print("\n== 6. No drive is left unread ==")
    shell = SimpleNamespace(
        _current_motivation=fed, health_monitor=SimpleNamespace(component_health={}),
        system_state=None, task_queue=None, _idle_count=0,
        _permanently_failed_fps=set(), _started_at_ts=0)
    shell._health_counts = lambda: AutonomousCoordinator._health_counts(shell)
    features = await AutonomousCoordinator._decision_context(shell, "a task")
    check("all seven drives condition what the substrate concludes about itself",
          all(d in features for d in DRIVES),
          f"missing={[d for d in DRIVES if d not in features]}")
    check("and they carry the MEASURED values, not placeholders",
          all(features[d] == fed["dimensions"].get(d) for d in DRIVES))

    EV.metric("drives_with_no_consumer_before", 3, "count",
              "mastery, autonomy, social — read by nothing in the tree")
    EV.metric("appraisals_with_unmeasured_activation_before", 1.0, "fraction",
              "no appraisal.update() call in the tree passed motivation_state")

    EV.note("Drive levels depend on the live store, so absolute values differ "
            "between runs. Every check here is about the SHAPE of the reading — "
            "what it was derived from, what is excluded, and what consumes it.")
    EV.note("`_drive_level` and `_calculate_total_reward` are exercised directly "
            "for the absence cases, because a store that happens to have data for "
            "every drive cannot demonstrate what happens when one has none.")

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
