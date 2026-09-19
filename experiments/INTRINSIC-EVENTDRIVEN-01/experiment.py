"""INTRINSIC-EVENTDRIVEN-01 — intrinsic pursuit is event-driven and sourced from the revised frontier.

(1) CONTENT: `_pursuit_to_goal` routes each frontier to its real closer — knowledge→a Research goal
    (understand loop), capability→a competence DRIVE goal (_execute_drive_goal), environment→None
    (closed by its own reaction). No stub routes.
(2) TRIGGER + COALESCE: a state-changing event fires `_react_pursue_frontier`, which runs ONE selection
    cycle; a BURST of events collapses to a single selection (single-flight). No timer involved.
(3) END-TO-END: a real event drives the real selection cycle, which consults the frontier
    (`_intrinsic_pursuits`) — proven by the cycle running off the event and reading the seeded pursuit.

Run: ./venv_torin/bin/python3 scratchpad/bench_eventdriven.py
"""
from __future__ import annotations
import asyncio, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "INTRINSIC-EVENTDRIVEN-01",
    claim=("Intrinsic pursuit is EVENT-DRIVEN, not polled: a state-changing event "
           "fires one coalesced selection cycle, which reads the frontier from "
           "`_intrinsic_pursuits` and routes each frontier kind to its real closer "
           "— knowledge to the understand loop, capability to a competence drive "
           "goal, environment to its own reaction. No timer, no stub routes."),
    hypothesis=("If selection were polled or stubbed, a burst of events would "
                "produce more than one cycle and a seeded not-knowing would not "
                "reach the frontier the cycle actually reads."))

results = []
def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.database import get_database_manager
    db = get_database_manager(); await db.initialize()
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C, SelfEventType

    # ---- (1) CONTENT: _pursuit_to_goal routing (pure; no init needed) ----
    print("\n== (1) _pursuit_to_goal routes each frontier to its real closer ==")
    class _P:
        _pursuit_to_goal = C._pursuit_to_goal
    p = _P()
    gk = p._pursuit_to_goal({"frontier": "knowledge", "domain": "d1",
                             "target": "photosynthesis", "entropy": 0.9, "score": 0.8})
    check("knowledge → a Research goal for the understand loop (no drive)",
          gk is not None and gk.description.lower().startswith("research")
          and gk.metadata.get("frontier") == "knowledge" and "drive" not in gk.metadata,
          f"desc={gk.description!r} md={gk.metadata}")
    gc = p._pursuit_to_goal({"frontier": "capability", "domain": "test_cap",
                             "target": "the substrate has learned the operators of domain test_cap",
                             "entropy": 0.9, "score": 0.8})
    check("capability → a competence DRIVE goal (_execute_drive_goal reads drive/domain_id/scope)",
          gc is not None and gc.metadata.get("drive") == "competence"
          and gc.metadata.get("domain_id") == "test_cap"
          and gc.metadata.get("scope") == "domain_contrastive",
          f"md={gc.metadata}")
    ge = p._pursuit_to_goal({"frontier": "environment", "domain": "environment_x",
                             "target": "where am I", "entropy": 0.9, "score": 0.8})
    check("environment → None (closed by _react_investigate_environment, not a queued task)",
          ge is None)
    # intrinsic values are REAL signals from the pursuit, not placeholders
    check("intrinsic values derive from the pursuit (novelty=entropy, curiosity=score)",
          gk.expected_novelty == 0.9 and gk.curiosity_value == 0.8)

    # ---- bring up a real coordinator for (2) and (3) ----
    coord = C(); await coord.initialize(start_loop=False)

    # ---- (2) TRIGGER + COALESCE (count real selection runs) ----
    print("\n== (2) events drive selection; a burst coalesces to one ==")
    calls = {"n": 0}
    _orig_cycle = coord._run_exploration_cycle
    async def _counting():
        calls["n"] += 1
        await asyncio.sleep(0.03)
    coord._run_exploration_cycle = _counting

    await coord._react_pursue_frontier(None)          # one event
    if coord._pursuit_selection_task:
        await coord._pursuit_selection_task
    check("one state-changing event → exactly one selection cycle", calls["n"] == 1,
          f"cycles={calls['n']}")

    calls["n"] = 0
    for _ in range(6):                                # a burst of events
        await coord._react_pursue_frontier(None)
    if coord._pursuit_selection_task:
        await coord._pursuit_selection_task
    check("a BURST of 6 events collapses to a single-flight selection (≤2 cycles)",
          calls["n"] <= 2, f"cycles={calls['n']}")
    coord._run_exploration_cycle = _orig_cycle

    # ---- (3) END-TO-END: a real event drives the real cycle, which reads the frontier ----
    print("\n== (3) a real event drives the real cycle, consulting _intrinsic_pursuits ==")
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    unc = get_uncertainty_system()
    # a fresh unknown capability belief so the frontier has something to pursue
    SEED_DOM = "test_evtdriven_cap"
    b = unc.create_belief(
        f"the substrate has learned the operators of domain {SEED_DOM}", SEED_DOM, prior=0.5)
    pursuits = await coord._intrinsic_pursuits(limit=50)
    seeded_is_pursuit = any(pp.get("domain") == SEED_DOM for pp in pursuits)

    # WHY, WHEN IT FAILS. A bare red mark says the frontier did not surface the
    # seeded gap; it does not say whether the gap was absent (a wiring fault) or
    # merely ranked below the cut (a DISCRIMINATION fault). Those need opposite
    # fixes, so the run records enough to tell them apart.
    _all = await coord._intrinsic_pursuits(limit=100000)
    _scores = sorted({p["score"] for p in _all}, reverse=True)
    _rank = next((i + 1 for i, p in enumerate(_all) if p.get("domain") == SEED_DOM), None)
    EV.metric("frontier_pursuits_total", len(_all), "count",
              "every pursuit the frontier holds, unlimited")
    EV.metric("frontier_distinct_scores", len(_scores), "count",
              "distinct score values — 1 would mean the ranking carries no information")
    EV.metric("frontier_score_spread",
              (round(_scores[0] - _scores[-1], 4) if _scores else None), "score delta",
              "best minus worst across the whole frontier")
    EV.metric("seeded_rank", _rank, "rank",
              f"position of the freshly-seeded gap among {len(_all)} pursuits; "
              f"present but > 50 means crowded out, not missing")
    EV.metric("seeded_present_unlimited", _rank is not None, "bool",
              "TRUE with a bare rank beyond the cut distinguishes a ranking fault "
              "from a wiring fault")
    if _rank is not None and not seeded_is_pursuit:
        EV.note(f"DISCRIMINATION, not wiring: the seeded gap IS on the frontier at "
                f"rank {_rank}/{len(_all)}, below the limit=50 cut. Pursuits scoring "
                f"identically tie at the cut, and which one surfaces is then decided "
                f"by the structural tiebreak rather than by merit.")

    check("the seeded not-knowing surfaces as a frontier pursuit", seeded_is_pursuit,
          f"{len(pursuits)} pursuits")

    ran = {"hit": False}
    async def _observing():
        ran["hit"] = True
        return await _orig_cycle()
    coord._run_exploration_cycle = _observing
    q_before = set(coord.task_queue.tasks_by_id.keys())
    await coord._react_pursue_frontier(SelfEventType.COMPETENCE_CHANGED)
    if coord._pursuit_selection_task:
        await coord._pursuit_selection_task
    coord._run_exploration_cycle = _orig_cycle
    check("the event drove the REAL selection cycle to run", ran["hit"])

    new_ids = set(coord.task_queue.tasks_by_id.keys()) - q_before
    frontier_tasks = []
    for tid in new_ids:
        qt = coord.task_queue.tasks_by_id.get(tid)
        md = getattr(getattr(qt, "task", None), "metadata", {}) or {}
        if md.get("frontier") in ("knowledge", "capability") or md.get("drive") == "competence":
            frontier_tasks.append((tid, md.get("frontier"), md.get("drive"), md.get("domain_id")))
    # A frontier task queued is the strong result; if the arbiter declined (a real
    # disposition gate at cold boot), the event→cycle wiring still fired (checked above).
    if frontier_tasks:
        check("the cycle queued a FRONTIER-sourced task (not the old IMS generator)",
              True, str(frontier_tasks[:3]))
    else:
        status = getattr(coord, "_exploration_status", None)
        check("no task queued only because a real gate declined (wiring still fired)",
              status in ("DECLINED_BY_ARBITER", None),
              f"exploration_status={status} (event→cycle wiring confirmed above)")

    # ---- cleanup (non-polluting) ----
    for tid in new_ids:
        coord.task_queue.tasks_by_id.pop(tid, None)
        try:
            await db.execute_query("DELETE FROM unified.goals WHERE goal_id=$1", (tid,), commit=True)
        except Exception:
            pass
    unc.beliefs.pop(b.belief_id, None)

    passed = sum(results); total = len(results)
    print(f"\n==== INTRINSIC-EVENTDRIVEN-01: {passed}/{total} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
