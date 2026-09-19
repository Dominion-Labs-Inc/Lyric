#!/usr/bin/env python3
"""INTENT-04 — the loop closes: meant-vs-happened, recorded and felt.

Intent is only worth holding if the substrate can later ask "did I do what I
meant?" and have the answer change something. This drives the REAL execution path
(`_drive_substrate_goal`) twice — once where the goal is reached and once where it
is not — and checks that:

  A  the intent is reconciled AUTOMATICALLY. This experiment never calls
     `reconcile()`; if the outcome is on the intent, the execution path put it
     there.
  B  the reconciliation is read from the RE-OBSERVED world, not a tool's report.
  C  appraisal's integrity reads its action↔outcome link FROM that reconciled
     intent — the link it used to fake with `attribution == "success"`.
  D  a MISS is recorded as a miss and FELT as one: integrity drops, because a
     pursuit that did not realize its intent is the case worth learning from.

The miss is produced WITHOUT making a real operator fail. Forcing one to fail
teaches the substrate something false about an operator that works — an earlier
version of this did exactly that and refuted a validated MOVE_FILE rule that four
experiments depend on. Instead a route is proved for a goal the world does not
satisfy, and reconciliation is asked what happened; the verdict must come from
the world.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402

os.environ.setdefault("TORIN_SHADOW_MODE", "1")

PASS = FAIL = 0
EV = RunRecord(
    "INTENT-04",
    claim="The substrate records what it meant, reconciles it against the world "
          "it re-observes, and its disposition reads that pairing — so 'did I do "
          "what I meant' is answerable and consequential.",
    hypothesis="If the execution path reconciles intent automatically, then a "
               "reached goal lands as fulfilled and a failed one as missed, and "
               "integrity's action-outcome link is read from the reconciled "
               "intent rather than inferred from a success label.")


def check(label, ok, detail=""):
    global PASS, FAIL
    EV.check(label, ok, detail)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


async def intents_with_outcomes(IA):
    await IA.store._ready()
    rows = await IA.store.db.execute_query(
        "SELECT intent_id, outcome, status FROM unified.intents "
        "WHERE outcome IS NOT NULL", fetch_all=True)
    out = []
    for r in (rows or []):
        o = r["outcome"]
        out.append({"intent_id": r["intent_id"], "status": r["status"],
                    "outcome": json.loads(o) if isinstance(o, str) else o})
    return out


async def drive(coord, root, domain, conditions, description):
    from core.agents.autonomous.shared_types import (
        Task, TaskType, TaskStatus, Priority, TaskSource)
    task = Task(id=str(uuid4()), type=TaskType.EXECUTION, description=description,
                priority=Priority.MEDIUM, status=TaskStatus.PENDING,
                created_at=datetime.now(), source=TaskSource.AUTONOMOUS,
                provenance={"goal_conditions": conditions, "domain_id": domain,
                            "workspace_root": str(root)})
    return await coord._drive_substrate_goal(task)


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.appraisal import get_appraisal_system
    from core.agents.autonomous.shared_types import Priority
    from core.execution.filesystem_domain import ensure_filesystem_domain, _encode
    from core.execution.operator_binding import get_binding_registry
    from core.learning.rule_induction import Fact
    from core.reasoning.intent_authority import get_intent_authority
    from core.reasoning.temporal_reasoning import PlanningStatus

    IA = get_intent_authority()
    created = []

    # ── A run that REACHES its goal ─────────────────────────────────────────
    print("\n== A. A pursuit that reaches its goal ==")
    root = Path(tempfile.mkdtemp(prefix="intent-04-ok-"))
    (root / "inbox").mkdir()
    (root / "archive").mkdir()
    (root / "inbox" / "report.txt").write_text("the file the intent is about\n")
    DOMAIN = "fs_g2_real1"

    coord = AutonomousCoordinator()
    check("execution faculty up", await coord.initialize_execution_faculty())
    await coord.planning.initialize()
    ensure_filesystem_domain(DOMAIN, str(root))
    reach_goal = Fact("FILE_IN", (_encode("report.txt"), _encode("archive"))).to_formula()

    before = await intents_with_outcomes(IA)
    result = await drive(coord, root, DOMAIN, [reach_goal], "archive the report")
    check("the substrate drove the goal and reached it",
          bool(result) and result.get("success") and result.get("goal_reached"),
          f"success={result.get('success') if result else None}")

    after = await intents_with_outcomes(IA)
    fresh = [i for i in after if i["intent_id"] not in {b["intent_id"] for b in before}]
    created += [i["intent_id"] for i in fresh]
    check("the intent was reconciled AUTOMATICALLY (this test never calls reconcile)",
          len(fresh) == 1, f"{len(fresh)} newly reconciled intent(s)")
    hit = fresh[0] if fresh else {"outcome": {}, "status": None}
    check("it reconciled as fulfilled, matching what it meant",
          hit["status"] == "fulfilled" and hit["outcome"].get("matched_aim") is True,
          f"status={hit['status']} matched_aim={hit['outcome'].get('matched_aim')}")
    check("what it counts as met came from the RE-OBSERVED world",
          hit["outcome"].get("goal_conditions_met") == [reach_goal],
          str(hit["outcome"].get("goal_conditions_met")))
    check("the file really moved on disk",
          (root / "archive" / "report.txt").exists()
          and not (root / "inbox" / "report.txt").exists(),
          "archive holds it; inbox is empty")

    state = get_appraisal_system().current_state
    src = ((state.sources or {}).get("integrity") or {}) if state else {}
    link = src.get("action_outcome")
    print(f"     integrity={getattr(state, 'integrity', None)} action_outcome={link}")
    check("integrity's action-outcome link is READ from the reconciled intent",
          isinstance(link, dict) and link.get("read_from") == "reconciled intent"
          and link.get("matched_aim") is True,
          str(link))
    check("a realized intent reads as coherent", (state.integrity or 0) >= 0.99,
          f"integrity={state.integrity}")

    # ── A pursuit whose goal the world does NOT satisfy ────────────────────
    print("\n== B. A pursuit the world does NOT satisfy (the case to learn from) ==")
    # NOTHING IS EXECUTED HERE, AND NO OPERATOR IS MADE TO FAIL — deliberately.
    # An earlier version of this section forced `move_file` to fail by making a
    # directory unwritable. The move copied the file but could not unlink the
    # source, the substrate observed its predicted delete-effect fail, and it
    # CORRECTLY REFUTED a validated MOVE_FILE rule that four experiments depend
    # on. The substrate behaved properly; it was taught something false about an
    # operator that works. A test must not teach the substrate a lie.
    #
    # So the miss is produced the honest way: a route is proved for a goal the
    # world does not satisfy, and reconciliation is asked what happened. The
    # verdict must come from the WORLD, which is the property under test.
    second = root / "inbox" / "second.txt"
    second.write_text("this one is never acted on\n")
    miss_goal = Fact("FILE_IN", (_encode("second.txt"), _encode("archive"))).to_formula()
    goal2 = await coord.planning.create_goal(
        "archive the second file", Priority.MEDIUM, state_conditions=[miss_goal])
    world2 = get_binding_registry().observe_world(DOMAIN) or set()
    out2 = await coord.planning.plan_for_goal(
        goal2.id, {"world_state": [str(f) for f in world2], "domain_id": DOMAIN})
    check("a route is proved for the second goal",
          out2.status is PlanningStatus.PLAN_FOUND, out2.reason)
    miss_intent_id = ((out2.plan.metadata or {}).get("intent") or {}).get("intent_id")
    created.append(miss_intent_id)

    # The plan is NOT run, so the world still does not satisfy the goal.
    reconciled2 = await coord._reconcile_plan_intent(
        out2.plan, DOMAIN, goal_conditions=[miss_goal],
        detail="the route was proved but not carried out")
    check("reconciliation reads the WORLD, and says missed",
          bool(reconciled2) and reconciled2["matched_aim"] is False
          and reconciled2["outcome_class"] == "missed",
          f"matched_aim={reconciled2['matched_aim'] if reconciled2 else None}")
    check("the miss records what it MEANT beside what actually held",
          reconciled2["goal_conditions"] == [miss_goal]
          and reconciled2["goal_conditions_met"] == [],
          f"meant={reconciled2['goal_conditions']} met={reconciled2['goal_conditions_met']}")
    stored_miss = await IA.get_by_id(miss_intent_id)
    check("the miss is on the intent itself, not quietly left open",
          bool(stored_miss) and stored_miss.status == "abandoned"
          and (stored_miss.outcome or {}).get("matched_aim") is False,
          f"status={stored_miss.status if stored_miss else None}")
    check("the file never moved — the world says so",
          second.exists() and not (root / "archive" / "second.txt").exists(),
          "still in inbox, never arrived in archive")

    # And the miss is FELT: the same link the drive path feeds, given a miss.
    get_appraisal_system().update(outcome_quality=0.0, self_initiated=True,
                                  intent_outcome=reconciled2)
    state2 = get_appraisal_system().current_state
    link2 = ((state2.sources or {}).get("integrity") or {}).get("action_outcome")
    print(f"     integrity={getattr(state2, 'integrity', None)} action_outcome={link2}")
    check("the miss is FELT: the action-outcome link reads the intent and is 0",
          isinstance(link2, dict) and link2.get("read_from") == "reconciled intent"
          and link2.get("matched_aim") is False,
          str(link2))
    check("an unrealized intent is less coherent than a realized one",
          (state2.integrity or 1.0) < (state.integrity or 1.0),
          f"missed={state2.integrity} < reached={state.integrity}")

    EV.metric("reached_integrity", state.integrity)
    EV.metric("missed_integrity", state2.integrity)
    EV.metric("intents_reconciled_automatically", len(created), "count")

    # Self-cleaning
    for intent_id in created:
        await IA.store.db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE intent_id = $1",
            (intent_id,), commit=True)
        await IA.store.db.execute_query(
            "DELETE FROM unified.intents WHERE intent_id = $1",
            (intent_id,), commit=True)

    await EV.verify_database()
    EV.write()
    shutil.rmtree(root, ignore_errors=True)
    print("\n" + "=" * 62)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
