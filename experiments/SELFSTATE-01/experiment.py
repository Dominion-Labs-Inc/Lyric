#!/usr/bin/env python3
"""SELFSTATE-01 — does KNOWING feed self-state, or only DOING?

The substrate's appraisal was fed exclusively by task outcomes. Teaching it 15
facts on a live substrate moved **0 of 13** core variables, and neither the
directive nor the acceptance band changed. `integrate_epistemic_affect()` --
the one thing that folds knowledge movement into feeling -- had a single caller,
`_react_affect`, registered for TASK_COMPLETED alone, while its own docstring
says the signal is read "from any source: perception, teaching, reasoning".

AFFECT-WIRING-01 cannot catch this. It builds an `AppraisalState` by hand and
checks that pressures reach the directive, which they do. The break was upstream
of anything a constructed state can show: nothing was ASKING.

So this runs a LIVE substrate and teaches it, and every check below is about
what the substrate does to itself.

  A  THE BASELINE IS PRIMED AT BOOT       not by whoever asks first
  B  THE CADENCE IS REGISTERED            `epistemic_affect` on the authority
  C  KNOWING MOVES SELF-STATE             taught facts -> core variables
  D  SELF-STATE MOVES BEHAVIOUR           -> the directive the loop consumes
  E  WHAT NEEDS A TASK STAYS UNMEASURED   no fabricated competence/progress

Run: ./venv_lyric/bin/python3 experiments/SELFSTATE-01/experiment.py
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
logging.disable(logging.CRITICAL)

#: Fed by KNOWING. The substrate learns without running a task, so these are the
#: ones a teaching workload can move.
FROM_KNOWING = ["confidence", "epistemic_opportunity", "stakes"]

#: Fed by DOING, and deliberately NOT fed here. Appraisal's `competence` is task
#: SUCCESS RATE -- DO-competence -- while teaching moves maturity, which is KNOW.
#: The credit invariant forbids crossing them, so these staying None through a
#: teaching run is CORRECT. Check E exists to stop anyone "fixing" that by
#: inventing a number.
NEEDS_A_TASK = ["progress", "competence", "goal_congruence", "agency",
                "integrity", "controllability"]

#: The cadence is retuned for the run through the queue authority's own API --
#: the substrate can retune its periodic work, so this is a supported call and
#: not a test hook. Without it the experiment waits out two 60s windows.
FAST_CADENCE_S = 5.0

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


async def main() -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coord = system.autonomous_coordinator
        from core.semantics.cognitive_ingress import Provenance
        from core.reasoning.epistemic_engine import get_epistemic_engine
        engine = get_epistemic_engine()

    print("\n== A. The drift baseline is primed AT BOOT ==")
    # `interpret_drift` reports what moved since last asked and primes on its
    # first call. Priming LAZILY meant everything learned between boot and that
    # first ask was swallowed, and the size of the window depended on who
    # happened to call and when. Measured before the fix: 20 facts taught at
    # boot were absorbed as baseline by the first scheduled drain a minute
    # later, and the substrate never felt having learned them.
    primed = bool(getattr(engine, "_drift_primed", False))
    check("the baseline is already primed before anything asks", primed,
          f"_drift_primed={primed}")
    beliefs = len(getattr(engine._uncertainty(), "beliefs", {}) or {})
    check("and it was primed against a HYDRATED graph, not an empty one",
          beliefs > 0,
          f"{beliefs:,} belief(s) held — priming an empty graph would report "
          f"every hydrated belief as newly learned")

    print("\n== B. Knowledge movement is on the substrate's own cadence ==")
    jobs = coord.task_queue.scheduled_jobs()
    check("`epistemic_affect` is registered on the queue authority",
          "epistemic_affect" in jobs, f"{len(jobs)} scheduled job(s)")
    # PERIODIC IS THE RIGHT SHAPE, not a compromise. `interpret_drift` is a
    # DRAIN over the whole belief graph -- measured at 380 ms for 128,647
    # beliefs -- so hanging it on EVIDENCE_ADMITTED would walk the graph once
    # per taught fact.
    # Registering a scheduled name again retunes its cadence (the job's record kept).
    coord.task_queue.schedule_recurring(
        "epistemic_affect", coord.integrate_epistemic_affect, FAST_CADENCE_S, "high")
    coord.task_queue.schedule_recurring(
        "motivation_refresh", coord._refresh_motivation_signals, FAST_CADENCE_S, "high")

    print("\n== C. What the substrate COMES TO KNOW moves its self-state ==")
    before = coord.appraisal.current_state
    fed_before = [f for f in FROM_KNOWING
                  if before is not None and getattr(before, f, None) is not None]
    check("nothing is fabricated before any work is done", not fed_before,
          f"fed at boot: {fed_before or 'none'}")

    tag = uuid.uuid4().hex[:6]
    provenance = Provenance(producer="selfstate01", source_id=f"ss01_{tag}",
                            source_type="USER_SUPPLIED")
    # Taught ACROSS cadence windows, because one drain establishes and the next
    # measures. A single burst before the first drain is absorbed as baseline --
    # correct behaviour, and invisible to a test that does not wait.
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        for batch in range(4):
            for i in range(8):
                name = f"ss01{tag}b{batch}i{i}"
                await coord.learning.learn_fact(
                    name, "isa", f"ss01kind{tag}",
                    surface=f"a {name} is a ss01kind{tag}",
                    domain=f"selfstate01{tag}", provenance=provenance,
                    quality=0.95)
            await asyncio.sleep(FAST_CADENCE_S * 1.6)

    after = coord.appraisal.current_state
    fed_after = [f for f in FROM_KNOWING
                 if after is not None and getattr(after, f, None) is not None]
    check("teaching alone moves the variables knowing can move",
          len(fed_after) >= 2,
          ", ".join(f"{f}={getattr(after, f):.4f}" for f in fed_after) or "none")

    print("\n== D. Self-state reaches the behaviour the loop consumes ==")
    directive = coord.disposition()
    exploration = getattr(after, "exploration_pressure", None)
    check("a pressure was derived from it", exploration is not None,
          f"exploration_pressure={exploration}")
    # The pressures reach a directive the acting loop already reads. Which flag
    # moves depends on what was learned, so this asserts that the directive is
    # DERIVED from the moved state rather than pinning one outcome.
    from core.agents.autonomous.behavior_arbiter import BehaviorArbiter
    recomputed = BehaviorArbiter().decide(after, slots_available=3,
                                          queue_pressure="nominal")
    check("the directive the loop reads is the one this state implies",
          bool(getattr(directive, "should_explore", None)
               == getattr(recomputed, "should_explore", None)),
          f"should_explore={getattr(directive, 'should_explore', None)}")
    vi, accept = coord._acceptance_band()
    check("and the acceptance band is derived from the same state, not fixed",
          abs(vi - float(getattr(directive, "verification_intensity", 0))) < 1e-9,
          f"verification_intensity={vi:.4f} accept={accept:.4f}")

    print("\n== E. What needs a task stays UNMEASURED, never invented ==")
    # Appraisal's `competence` is task success rate. Teaching moves maturity.
    # The credit invariant says one never stands in for the other, so every one
    # of these must still be None after a pure teaching workload.
    invented = [f for f in NEEDS_A_TASK
                if after is not None and getattr(after, f, None) is not None]
    check("no DO-variable was fabricated from KNOW-work", not invented,
          f"still unmeasured: {[f for f in NEEDS_A_TASK if f not in invented]}"
          if not invented else f"FABRICATED: {invented}")

    passed, total = sum(results), len(results)
    print(f"\n==== SELFSTATE-01: {passed}/{total} checks passed ====\n")
    (HERE / "results").mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (HERE / "results" / f"{stamp}.json").write_text(json.dumps({
        "experiment": "SELFSTATE-01",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed, "total": total,
        "beliefs_at_prime": beliefs,
        "fed_by_knowing": {f: getattr(after, f, None) for f in FROM_KNOWING},
        "unmeasured_without_a_task": {f: getattr(after, f, None)
                                      for f in NEEDS_A_TASK},
    }, indent=2, default=str))
    print(f"  run record: experiments/SELFSTATE-01/results/{stamp}.json")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.database import get_database_manager
        db = get_database_manager()
        for sql in ("DELETE FROM unified.beliefs WHERE domain=$1",
                    "DELETE FROM unified.domains WHERE domain_id=$1"):
            await db.execute_query(sql, (f"selfstate01{tag}",), commit=True)
        await db.execute_query(
            "DELETE FROM unified.concepts WHERE name LIKE $1",
            (f"%{tag}%",), commit=True)
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
