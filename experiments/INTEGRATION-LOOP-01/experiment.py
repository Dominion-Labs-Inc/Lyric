"""INTEGRATION-LOOP-01 — the full KNOW→DO→frontier loop through the REAL coordinator.

Not a unit test: a real AutonomousCoordinator runs a real grounded-operator task against a real
FilesystemWorld, and we read the chain the user drew end-to-end WITHOUT hand-calling the internals:

  real task → execution → INDEPENDENTLY VERIFIED outcome (filesystem oracle, not the tool's return)
            → persisted operating outcome (producer fires inside _execute_and_validate_task)
            → earned reliability moves → operability BAR shifts
            → OUTCOME_OBSERVED on the event spine → competence/motivation frontier revised

Uses the kite17 experiment domain (a learned, executable MOVE operator). Non-polluting: kite17's
operating counters are snapshotted and restored at the end, so the benchmark is repeatable.

Run: ./venv_torin/bin/python3 scratchpad/bench_integration_loop.py
"""
from __future__ import annotations
import asyncio, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "INTEGRATION-LOOP-01",
    claim=("The full KNOW -> DO -> frontier loop runs through the REAL coordinator: a real grounded-operator task acts on a real FilesystemWorld, the outcome is verified by an INDEPENDENT filesystem oracle rather than the tool's own return, that outcome persists, earned reliability moves, and the operability bar shifts with it."),
    hypothesis=('If any link were stubbed, the chain would still report success while the filesystem oracle disagreed — so the oracle, not the tool, decides.'))

results = []
def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

DOMAIN = "kite17"
RULE = "rule_edbe5a8b4ad8"
RUNS = 5            # ≥ OPERATING_MIN_SAMPLE (4) so earned moves off neutral


async def main() -> int:
    from core.database import get_database_manager
    db = get_database_manager(); await db.initialize()

    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.shared_types import Task, TaskType, TaskSource
    from core.integration.universal_domain_master import get_universal_domain_master
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from experiments.e2e_world import FilesystemWorld, ITEM

    OPERATOR = f"MOVE({ITEM},HALL,LAB)"
    udm = get_universal_domain_master(); await udm.initialize()

    # snapshot kite17 operating counters so the run is non-polluting + repeatable
    snap = await db.execute_query(
        "SELECT operating_attempts, operating_wins FROM unified.domain_controllability "
        "WHERE domain_id=$1", (DOMAIN,), fetch_all=True)
    snap_att = snap[0]["operating_attempts"] if snap else 0
    snap_win = snap[0]["operating_wins"] if snap else 0

    world = FilesystemWorld().register(DOMAIN)
    created_intents = []

    coord = AutonomousCoordinator()
    await coord.initialize(start_loop=False)

    # Capture the completion DECISION directly: mark_completed is called iff
    # is_complete is True, mark_failed iff not. (Reading task.status doesn't work
    # here — the task isn't enqueued, so the queue can't find it to update it.)
    completed_ids, failed_ids = [], []
    _orig_mc, _orig_mf = coord.task_queue.mark_completed, coord.task_queue.mark_failed
    async def _mc(tid, res, *a, **k): completed_ids.append(tid); return True
    async def _mf(tid, err, *a, **k): failed_ids.append(tid); return True
    coord.task_queue.mark_completed = _mc
    coord.task_queue.mark_failed = _mf
    # clear any stale permanent-fail block on this operator (a buggy earlier run
    # could have recorded one — a verified-successful op must not stay blocked).
    try:
        from core.agents.autonomous.idle_work_playbook import IdleWorkPlaybook as _IWP
        _opfp = _IWP.description_fingerprint(OPERATOR)
        coord._permanently_failed_fps.discard(_opfp)
        coord._save_permanently_failed_fps()
    except Exception:
        pass
    try:
        # ---- BASELINE (before operating) ----
        rel0 = await udm.operating_reliability(DOMAIN)
        op0 = await coord._domain_operability(DOMAIN)
        bel = get_uncertainty_system()
        def _competence_conf():
            claim = f"the substrate has learned the operators of domain {DOMAIN}"
            b = next((b for b in bel.beliefs.values() if getattr(b, "claim", None) == claim), None)
            return None if b is None else round(float(getattr(b, "confidence", 0.0)), 4)
        comp0 = _competence_conf()
        refr0 = coord.stats.get("motivation_refreshes_reactive", 0)
        print(f"\nBASELINE: earned={rel0['earned']} bar={op0['bar']} "
              f"op_attempts={rel0['attempts']} competence_conf={comp0} refreshes={refr0}")

        # ---- RUN the real loop N times ----
        print(f"\n== running {RUNS} real grounded-operator tasks through _execute_and_validate_task ==")
        verified_world_changes = 0
        is_complete_agreements = 0
        # THE LAWS APPLY TO A BARE OPERATOR TASK TOO, and there is no planner in
        # this path to satisfy them, so the caller does what a plan would have:
        #
        #   * Law 2 refuses an act on a file with no current reading — so the item
        #     is READ first, through the real tool, which records the account.
        #   * Law 2 also refuses an act nothing explains — so the move runs under a
        #     recorded INTENT naming MOVE in this domain. The read is left unbound:
        #     it is investigate-class, and claiming the move's intent for it would
        #     have Law 4 replan it for not being the proved act.
        from core.reasoning.intent_authority import (
            get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
        from uuid import uuid4 as _uuid4
        acting = await get_intent_authority().form(
            "goal", SUBSTRATE_ACTOR, continuity_goal(f"intloop_{_uuid4().hex[:8]}"),
            shape={"proved": True, "operator": OPERATOR, "operators": [OPERATOR],
                   "goal_conditions": [f"AT({ITEM}, LAB)"], "rule_ids": [RULE],
                   "domain": DOMAIN, "steps": 1, "grounding_complete": True},
            content={"aim": "move the item to the lab", "bindings": [{}]})
        created_intents.append(acting.intent_id)

        for i in range(RUNS):
            world.clear(ITEM); world.place(ITEM, "HALL")
            await coord.tool_registry.execute_tool(
                "read_file", {"file_path": str(world.root / "HALL" / ITEM)})
            task = Task(
                id=f"intloop_{i}_{int(asyncio.get_running_loop().time()*1000)}",
                type=TaskType.EXECUTION,
                description=OPERATOR,
                source=TaskSource.AUTONOMOUS,
                provenance={"learned_rule_id": RULE, "grounded_operator": OPERATOR,
                            "domain_id": DOMAIN, "plan_id": None, "goal_id": None,
                            "intent_id": acting.intent_id},
            )
            await coord._execute_and_validate_task(task)
            # INDEPENDENT oracle: the filesystem, not the task result
            after = sorted(str(f) for f in world.observe())
            moved = f"AT({ITEM}, LAB)" in after and f"AT({ITEM}, HALL)" not in after
            verified_world_changes += int(moved)
            accepted = task.id in completed_ids     # mark_completed ⇒ is_complete True
            is_complete_agreements += int(accepted)
            print(f"    run {i}: world_moved={moved} completion_accepted={accepted}")

        check("every run actually changed the world (independent filesystem oracle)",
              verified_world_changes == RUNS, f"{verified_world_changes}/{RUNS}")
        # HONEST expectation: a verified world change IS a successful operation.
        check("the substrate ACCEPTED the verified-successful operation as complete",
              is_complete_agreements == RUNS,
              f"{is_complete_agreements}/{RUNS} accepted — if 0, completion rejected a real success "
              f"(false negative); EARNED then records wins as losses")

        # ---- PERSISTED operating outcome (producer fired automatically) ----
        rows = await db.execute_query(
            "SELECT operating_attempts, operating_wins FROM unified.domain_controllability "
            "WHERE domain_id=$1", (DOMAIN,), fetch_all=True)
        att = rows[0]["operating_attempts"] if rows else 0
        win = rows[0]["operating_wins"] if rows else 0
        check("operating outcomes PERSISTED by the producer (no hand-call) — attempts += RUNS",
              att - snap_att == RUNS, f"attempts {snap_att}→{att} (Δ{att-snap_att}), wins {snap_win}→{win}")

        # ---- earned moved → BAR shifted ----
        rel1 = await udm.operating_reliability(DOMAIN)
        op1 = await coord._domain_operability(DOMAIN)
        check("earned reliability moved OFF neutral after ≥4 verified operations",
              rel1["earned"] != 0.5 and rel1["enough_history"],
              f"earned {rel0['earned']}→{rel1['earned']} (win_rate={rel1['win_rate']})")
        # HONEST expectation: verified successes → earned UP → bar DOWN.
        check("operability BAR shifted DOWN (verified successes earned trust)",
              op1["bar"] < op0["bar"],
              f"bar {op0['bar']}→{op1['bar']} (wins {win-snap_win}/{RUNS}) — UP means real "
              f"successes were recorded as losses")

        # ---- the motivation frontier reads a REVISED threshold ----
        # The persisted operating outcomes changed the operability bar the
        # motivation frontier gates on — a fresh read reflects the new earned
        # basis live, not a stale snapshot. (Competence-belief-driven frontier
        # change is a DIFFERENT signal, proven in MOTIVATION-CLOSEDLOOP-01; it is
        # NOT expected here — re-running an already-validated operator earns no NEW
        # competence, so a flat competence belief is the honest outcome.)
        await asyncio.sleep(0.2)      # let deferred reactions drain
        comp1 = _competence_conf()
        op_fresh = await coord._domain_operability(DOMAIN)
        check("the motivation frontier now reads the REVISED threshold (live earned basis)",
              op_fresh["earned_basis"]["attempts"] >= RUNS and op_fresh["bar"] < op0["bar"],
              f"fresh bar={op_fresh['bar']} earned_attempts={op_fresh['earned_basis']['attempts']}")

        print(f"\nSUMMARY: bar {op0['bar']}→{op1['bar']}, earned {rel0['earned']}→{rel1['earned']}, "
              f"completion_accepted={is_complete_agreements}/{RUNS}, "
              f"competence {comp0}→{comp1} (flat = no NEW competence, honest), "
              f"verified {verified_world_changes}/{RUNS}")
    finally:
        coord.task_queue.mark_completed = _orig_mc
        coord.task_queue.mark_failed = _orig_mf
        # restore kite17 operating counters (non-polluting, repeatable)
        await db.execute_query(
            "UPDATE unified.domain_controllability SET operating_attempts=$2, operating_wins=$3 "
            "WHERE domain_id=$1", (DOMAIN, snap_att, snap_win), commit=True)
        try:
            world.clear(ITEM)
        except Exception:
            pass

    passed = sum(results); total = len(results)
    print(f"\n==== INTEGRATION-LOOP-01: {passed}/{total} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
