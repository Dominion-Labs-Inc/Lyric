#!/usr/bin/env python3
"""INTENT-03 — the judgment is correct UNDER EXECUTION, not just wired.

Phases 1–3 proved the plumbing: intent is owned, formed where reasoning starts,
and the proved route is recorded. Porting every caller to `judge(..., intent_id=)`
proved the call sites work. NONE of that proves the resulting judgments are
CORRECT once acts actually run — which is the only thing that matters.

So this drives the whole chain on the real substrate and checks the world:

  A  the planner proves a route and the authority records it as intent
  B  ALLOW is correct     — the allowed act runs, and the world afterwards
                            really satisfies what the intent said it was for
  C  REFUSAL is correct   — a genuine intent does not license a different act,
                            and the refused act leaves the world untouched
  D  FORGERY is correct   — an intent that was never recorded is refused, and
                            that act leaves the world untouched
  E  RECONCILIATION       — what actually happened attaches to the intent, so
                            meant-vs-happened is readable afterwards

Success is the RE-OBSERVED world, never a tool's own report. Self-cleaning.
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402

os.environ.setdefault("TORIN_SHADOW_MODE", "1")

PASS = FAIL = 0
EV = RunRecord(
    "INTENT-03",
    claim="A judgement made from a recorded intent is correct when the act runs: "
          "what it allows achieves what the intent was for, what it refuses does "
          "not happen, and an intent that was never recorded licenses nothing.",
    hypothesis="If the constitution reads intent from the authority rather than "
               "accepting one, then the allowed act's effect is visible in the "
               "re-observed world, a genuine intent cannot be repurposed, a "
               "forged id changes nothing, and the outcome reconciles onto the "
               "intent.")


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


async def main():
    from core.agents.autonomous.autonomous_coordinator import (
        AutonomousCoordinator, Verdict)
    from core.agents.autonomous.shared_types import Priority
    from core.execution.operator_binding import get_binding_registry
    from core.execution.tool_domain import sensed_fact, take_up_workspace
    from core.learning.rule_induction import Fact
    from core.reasoning.intent_authority import get_intent_authority
    from core.reasoning.temporal_reasoning import PlanningStatus, TemporalReasoningSystem

    holds = TemporalReasoningSystem.condition_holds
    # THE PRECONDITION IS DECLARED, NOT ASSUMED. This plans over a MOVE_FILE
    # operator the substrate LEARNED from its own acts. That was ambient state:
    # when the store was wiped, this failed with a signature that reads like
    # broken code rather than a missing prerequisite. `ensure_taught` teaches it
    # from real executions if it is not there, and costs a store read if it is.
    from experiments.fs_move_teach import DOMAIN, ensure_taught
    if not await ensure_taught():
        print("  [precondition] FAILED: no executable MOVE_FILE operator in "
              f"{DOMAIN}; nothing below can plan", flush=True)
        return 1
    root = Path(tempfile.mkdtemp(prefix="intent-03-"))
    (root / "inbox").mkdir()
    (root / "archive").mkdir()
    report = root / "inbox" / "report.txt"
    report.write_text("the file the intent is about\n")
    bystander = root / "inbox" / "bystander.txt"
    bystander.write_text("nothing should happen to this\n")

    IA = get_intent_authority()
    intent_id = None

    print("\n== A. The planner proves a route; the authority records it ==")
    coord = AutonomousCoordinator()
    check("execution faculty up", await coord.initialize_execution_faculty())
    await coord.planning.initialize()
    # The workspace is handed over: the substrate looks at it with its own
    # perception, and what is there becomes the world it plans in.
    take_up_workspace(DOMAIN, str(root))
    binding = get_binding_registry().get(DOMAIN, "MOVE_FILE")
    world = get_binding_registry().observe_world(DOMAIN) or frozenset()
    # "Archive the report": the report is a file in archive, and is no longer
    # one in the inbox — which is what moving it means, in perception's words.
    goal_conditions = [
        sensed_fact("kind", "path", str(root / "archive" / "report.txt"), "file").to_formula(),
        "¬" + sensed_fact("kind", "path", str(report), "file").to_formula()]
    goal = await coord.planning.create_goal(
        "archive the report", Priority.MEDIUM, state_conditions=goal_conditions)
    outcome = await coord.planning.plan_for_goal(
        goal.id, {"world_state": [f.to_formula() for f in world],
                  "domain_id": DOMAIN})
    check("the planning authority proved a route",
          outcome.status is PlanningStatus.PLAN_FOUND, outcome.reason)
    if outcome.status is not PlanningStatus.PLAN_FOUND:
        shutil.rmtree(root, ignore_errors=True)
        return 1
    step = outcome.plan.tasks[0]
    intent_id = ((outcome.plan.metadata or {}).get("intent") or {}).get("intent_id")
    intent = await IA.get_by_id(intent_id)
    check("the authority holds the proved intent",
          bool(intent) and intent.stated(), intent.proof if intent else None)

    # The substrate must have read what it acts on (Law 2), the honest way.
    await coord._run_tool("read_file", {"file_path": str(report)}, step)
    coord.reading.record(str(report))
    args = binding.parameters(Fact.parse(intent.operator).args)

    print("\n== B. ALLOW is correct: the act runs and the world matches the intent ==")
    j_allow = await coord.constitution.judge("tool", binding.tool_name, args,
                                             intent_id=intent_id)
    check("the proved act is allowed", j_allow.verdict is Verdict.ALLOW,
          f"{j_allow.verdict.value}: {j_allow.reason}")
    ran = await coord._run_tool(binding.tool_name, args, step)
    check("the allowed act really ran", bool(ran and ran.get("success")),
          str((ran or {}).get("error"))[:90])
    # THE WORLD DECIDES. Re-observe and ask whether what the intent was FOR now holds.
    after = {str(f) for f in (get_binding_registry().observe_world(DOMAIN) or set())}
    reached = all(holds(c, after) for c in intent.goal_conditions)
    check("the re-observed world satisfies what the intent was FOR",
          reached, f"goal={intent.goal_conditions} present={reached}")
    check("the file really moved on disk",
          (root / "archive" / "report.txt").exists()
          and not report.exists(), "archive/report.txt exists, inbox/ is empty")

    print("\n== C. REFUSAL is correct: a real intent licenses only its own act ==")
    coord.reading.record(str(bystander))
    j_other = await coord.constitution.judge(
        "tool", "delete_file", {"file_path": str(bystander)}, intent_id=intent_id)
    check("a genuine intent does not license a different act",
          j_other.verdict is not Verdict.ALLOW,
          f"{j_other.verdict.value} L{j_other.law_number}: {j_other.reason[:70]}")
    check("the refused act left the world untouched — it was never run",
          bystander.exists() and bystander.read_text().startswith("nothing"),
          "bystander.txt still present and unchanged")

    print("\n== D. FORGERY is correct: an unrecorded intent licenses nothing ==")
    j_forged = await coord.constitution.judge(
        "tool", binding.tool_name,
        {"source_path": str(root / "archive" / "report.txt"),
         "destination_path": str(root / "inbox" / "report.txt")},
        intent_id="never-recorded-" + os.urandom(4).hex())
    check("an intent that was never recorded is refused",
          j_forged.verdict is not Verdict.ALLOW,
          f"{j_forged.verdict.value} L{j_forged.law_number}: {j_forged.reason[:70]}")
    check("the forged-intent act left the world untouched",
          (root / "archive" / "report.txt").exists() and not report.exists(),
          "the archive still holds it; nothing moved back")

    print("\n== E. Reconciliation: meant-vs-happened lands on the intent ==")
    await IA.reconcile(intent_id,
                       {"outcome_class": "success" if reached else "missed",
                        "matched_aim": bool(reached),
                        "goal_conditions_met": sorted(
                            c for c in intent.goal_conditions if holds(c, after))},
                       status="fulfilled" if reached else "abandoned")
    settled = await IA.get_by_id(intent_id)
    check("the outcome is readable on the intent afterwards",
          bool(settled and settled.outcome)
          and settled.outcome.get("matched_aim") is True
          and settled.status == "fulfilled",
          f"outcome={settled.outcome if settled else None} status={settled.status if settled else None}")
    check("the outcome is substrate-wide, carrying no actor content",
          bool(settled) and settled.content == {} and settled.actor == "",
          "shape view only")

    EV.metric("goal_conditions", intent.goal_conditions)
    EV.metric("world_reached_goal", reached)
    EV.metric("allowed_verdict", j_allow.verdict.value)
    EV.metric("other_act_verdict", j_other.verdict.value)
    EV.metric("forged_verdict", j_forged.verdict.value)

    # Self-cleaning: this run recorded a real intent for a throwaway goal.
    await IA.store._ready()
    await IA.store.db.execute_query(
        "DELETE FROM unified.scoped_intents WHERE intent_id = $1",
        (intent_id,), commit=True)
    await IA.store.db.execute_query(
        "DELETE FROM unified.intents WHERE intent_id = $1", (intent_id,), commit=True)

    await EV.verify_database()
    EV.write()
    shutil.rmtree(root, ignore_errors=True)
    print("\n" + "=" * 62)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
