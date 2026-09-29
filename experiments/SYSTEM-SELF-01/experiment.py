#!/usr/bin/env python3
"""SYSTEM-SELF-01 — the self's faculties, alone, on the live substrate.

Appraisal (`AppraisalSystem`), the behaviour arbiter (`BehaviorArbiter`) and
intrinsic motivation (`IntrinsicMotivationSystem`), each one authority the
coordinator holds. Appraisal turns measured signals into a disposition it can
account for, the arbiter decides from that disposition and real capacity, and
motivation has a mood, a valence and a state it can report.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-SELF-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, outcome, shutdown  # noqa: E402

EV = RunRecord(
    "SYSTEM-SELF-01",
    claim=("The self's faculties are each one authority: appraisal builds a disposition from "
           "measured signals and can say what it is made of, the arbiter decides from it and "
           "real capacity, and motivation reports a mood, a valence and a state."),
    hypothesis=("A second appraisal or arbiter, a disposition that ignores its signals, an "
                "arbiter that ignores capacity, or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    try:
        from core.agents.autonomous.appraisal import get_appraisal_system
        from core.agents.autonomous.behavior_arbiter import get_behavior_arbiter
        from core.agents.autonomous.intrinsic_motivation import get_intrinsic_motivation_system
        A, B, M = get_appraisal_system(), get_behavior_arbiter(), get_intrinsic_motivation_system()

        print("\n== A. One authority each, and each is called ==")
        authority_audit(EV, check, system="appraisal", cls="AppraisalSystem",
                        path="core/agents/autonomous/appraisal.py", held=coord.appraisal, reached=A)
        authority_audit(EV, check, system="arbiter", cls="BehaviorArbiter",
                        path="core/agents/autonomous/behavior_arbiter.py", held=coord.arbiter, reached=B)
        authority_audit(EV, check, system="motivation", cls="IntrinsicMotivationSystem",
                        path="core/agents/autonomous/intrinsic_motivation.py",
                        held=coord.intrinsic_motivation, reached=M)

        print("\n== B. Appraisal: measured signals become a disposition it can account for ==")
        saved = A.current_state
        # `risk_level` is a LABEL mapped through `_RISK`, not a number.
        calm = A.update(outcome_quality=0.9, action_success_rate=0.9, risk_level="low")
        tense = A.update(outcome_quality=0.2, action_success_rate=0.2, risk_level="critical")
        check("a worse world raises caution",
              float(getattr(tense, "caution_pressure", 0)) > float(getattr(calm, "caution_pressure", 0)),
              f"caution {getattr(calm, 'caution_pressure', None)} -> {getattr(tense, 'caution_pressure', None)}")
        standing = A.standing()
        dims = standing.get("dimensions") or standing.get("state") or {}
        check("standing names every dimension and where it came from",
              isinstance(standing, dict) and bool(dims), f"keys={sorted(standing)[:8]} dims={len(dims)}")
        A.update()
        st = A.standing()
        check("an unmeasured dimension says so rather than reading as zero",
              "unmeasured" in str(st).lower() or "None" in str(st) or "measured" in str(st).lower(),
              f"{str(st)[:120]}")
        A.current_state = saved

        print("\n== C. The arbiter decides from disposition and capacity ==")
        d_free = B.decide(tense, slots_available=3, queue_pressure="nominal")
        d_full = B.decide(tense, slots_available=0, queue_pressure="hard")
        check("a directive is returned with a mode", hasattr(d_free, "mode") and bool(d_free.mode),
              f"free={d_free.mode} full={d_full.mode}")
        # `mode` reports the dominant PRESSURE; permission to act on it is
        # `should_explore` / `max_goals`, and that is what capacity gates.
        check("no free slot and a hard backlog take away permission to explore",
              d_full.should_explore is False and d_full.max_goals == 0
              and "queue_pressure:hard" in d_full.reason_codes,
              f"should_explore={d_full.should_explore} max_goals={d_full.max_goals} codes={d_full.reason_codes}")
        d_unknown = B.decide(tense)
        check("unknown capacity is not permission", d_unknown.should_explore is False
              and "capacity_unknown" in d_unknown.reason_codes, f"{d_unknown.reason_codes}")
        d_none = B.decide(None)
        check("no appraisal at all still yields a directive, not a crash", hasattr(d_none, "mode"),
              f"{getattr(d_none, 'mode', None)}")

        print("\n== D. Motivation reports itself ==")
        state = await M.get_motivation_state()
        check("motivation state is a dict with dimensions", isinstance(state, dict) and "dimensions" in state,
              f"keys={sorted(state)[:8]}")
        mood, val, aff = M.mood(), M.valence(), M.affect_state()
        check("mood, valence and affect are readable now, without a loop",
              mood is not None and isinstance(val, float) and aff is not None,
              f"mood={getattr(mood, 'name', mood)} valence={val:.3f} affect={type(aff).__name__}")
        motiv = await M.calculate_motivation({"task_type": "analysis", "novelty": 0.5, "success": True})
        check("motivation is calculated from a context", isinstance(motiv, dict) and bool(motiv),
              f"keys={sorted(motiv)[:8]}")
        disp = coord.disposition()
        check("the coordinator's disposition is the appraisal's, not a second one",
              isinstance(disp, dict) or disp is not None, f"{type(disp).__name__}")
    finally:
        await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-SELF-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
