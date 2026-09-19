"""INTEGRITY-01 — integrity is an emergent chain-coherence dimension that drives re-alignment.

Integrity = coherence across identity → intention → action → outcome, computed as the MEAN of the
chain links that were actually measured (never a generic score, never zero-filled). It is DISTINCT
from success — a faithful attempt thwarted by an EXTERNAL cause keeps integrity intact, while acting
in a way that does not realize one's own intent dents it — and low integrity drives RE-ALIGNMENT
(verify more + re-examine the approach), high integrity backs confident engagement.

  1. A self-initiated success is maximally coherent (integrity ≈ 1.0).
  2. A STRATEGY failure (the substrate's own approach not bearing out its intent) dents integrity.
  3. ORTHOGONAL TO SUCCESS: an EXTERNAL/execution failure — a worse outcome — keeps integrity HIGHER
     than the self-incoherent strategy failure, because the break was not the substrate's.
  4. No measurable chain link → integrity is UNMEASURED (None), contributing nothing (not zero).
  5. Low integrity RAISES caution (verify) and replan (re-examine); high integrity BACKS approach.

Run: ./venv_torin/bin/python3 experiments/INTEGRITY-01/experiment.py
"""
from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.autonomous.appraisal import AppraisalState, build_appraisal, _derive_pressures  # noqa: E402
from core.learning.meta_learning import OutcomeClass  # noqa: E402
from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "INTEGRITY-01",
    claim=("Integrity is an EMERGENT coherence over the chain identity → intention → "
           "action → outcome — the mean of the links actually measured, never "
           "zero-filled — and it is orthogonal to success: a faithful attempt "
           "thwarted externally keeps integrity intact, while acting in a way that "
           "does not realize one's own intent dents it. Low integrity drives "
           "RE-ALIGNMENT (verify more, re-examine the approach); high integrity "
           "backs confident engagement."),
    hypothesis=("If integrity were a generic success score, the EXECUTION failure "
                "(a worse outcome) would score at or below the STRATEGY failure. If "
                "it is chain coherence, the execution failure scores HIGHER, because "
                "its break was not the substrate's own. And an unmeasured chain "
                "contributes nothing to caution rather than reading as zero."))

results = []
def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


print("\n== 1-3. Integrity emerges from the chain, orthogonal to success ==")
# A self-initiated success: identity↔intention (self-initiated) + intention↔action (ran) +
# action↔outcome (succeeded) all coherent.
succ = build_appraisal(self_initiated=True, action_success_rate=1.0, outcome_quality=1.0,
                       outcome_class=OutcomeClass.SUCCESS)
# A STRATEGY failure: it acted (ran) but its own approach did not realize the intent.
strat = build_appraisal(self_initiated=True, action_success_rate=1.0, outcome_quality=0.0,
                        outcome_class=OutcomeClass.STRATEGY_FAILURE)
# An EXECUTION failure: it could not act at all — faithful but externally thwarted.
execf = build_appraisal(self_initiated=True, action_success_rate=0.0, outcome_quality=0.0,
                        outcome_class=OutcomeClass.EXECUTION_FAILURE)

check("self-initiated success is maximally coherent", succ.integrity == 1.0, f"integrity={succ.integrity}")
check("a strategy failure dents integrity", strat.integrity is not None and strat.integrity < 1.0,
      f"integrity={strat.integrity}")
check("ORTHOGONAL: the external-failure outcome keeps integrity HIGHER than the self-incoherent one",
      execf.integrity is not None and execf.integrity > strat.integrity,
      f"execution_failure={execf.integrity} vs strategy_failure={strat.integrity}")

# THE MEASURED CHAIN, recorded — these are the numbers the claim rests on.
EV.metric("integrity_self_initiated_success", succ.integrity, "coherence [0,1]",
          "all three links measured and coherent")
EV.metric("integrity_strategy_failure", strat.integrity, "coherence [0,1]",
          "acted, but its own approach did not realize the intent")
EV.metric("integrity_execution_failure", execf.integrity, "coherence [0,1]",
          "could not act at all — faithful but externally thwarted")
EV.metric("orthogonality_margin", (None if execf.integrity is None or strat.integrity is None
                                   else round(execf.integrity - strat.integrity, 4)),
          "coherence delta",
          "execution_failure MINUS strategy_failure; > 0 is the orthogonality claim — "
          "a generic success score would put this at or below zero")

print("\n== 4. No measurable link → unmeasured (not zero) ==")
none_state = build_appraisal(outcome_quality=0.5)  # no self_initiated, no outcome_class, no goal align
check("integrity unmeasured with no chain signal", none_state.integrity is None, f"integrity={none_state.integrity}")
check("and it is named in `unmeasured`", "integrity" in none_state.unmeasured)

print("\n== 5. Low integrity drives re-alignment; high integrity backs approach ==")
# Hold everything else equal; vary only integrity, then derive pressures.
def pressures(integrity):
    s = AppraisalState(valence=-0.2, controllability=0.8, confidence=0.7, competence=0.7,
                       goal_congruence=0.6, activation=0.5, integrity=integrity)
    _derive_pressures(s)
    return s

lo = pressures(0.1)
hi = pressures(0.9)
check("low integrity raises caution (verify more)", lo.caution_pressure > hi.caution_pressure,
      f"low={lo.caution_pressure:.3f} hi={hi.caution_pressure:.3f}")
check("low integrity raises replan (re-examine the approach)", lo.replan_pressure > hi.replan_pressure,
      f"low={lo.replan_pressure:.3f} hi={hi.replan_pressure:.3f}")
check("high integrity backs approach", hi.approach_pressure > lo.approach_pressure,
      f"hi={hi.approach_pressure:.3f} lo={lo.approach_pressure:.3f}")

# Unmeasured integrity contributes nothing: caution matches the same state with no integrity at all.
none_p = pressures(None)
check("unmeasured integrity leaves caution between the low and high extremes (contributes nothing)",
      hi.caution_pressure <= none_p.caution_pressure <= lo.caution_pressure
      and none_p.integrity is None,
      f"none={none_p.caution_pressure:.3f} (hi={hi.caution_pressure:.3f}, lo={lo.caution_pressure:.3f})")

# WHAT INTEGRITY DOES TO BEHAVIOUR, with everything else held equal. These feed
# the live chain: caution → verification_intensity → verify_bar → the bar the
# substrate must clear before it may call a task done.
EV.metric("caution_low_integrity", round(lo.caution_pressure, 4), "pressure [0,1]",
          "integrity=0.1, all other dimensions held equal")
EV.metric("caution_high_integrity", round(hi.caution_pressure, 4), "pressure [0,1]",
          "integrity=0.9, same state otherwise")
EV.metric("caution_unmeasured_integrity", round(none_p.caution_pressure, 4), "pressure [0,1]",
          "integrity=None — must sit BETWEEN the extremes, proving it contributes "
          "nothing rather than reading as zero")
EV.metric("replan_low_integrity", round(lo.replan_pressure, 4), "pressure [0,1]",
          "incoherence drives re-examination of the approach")
EV.metric("replan_high_integrity", round(hi.replan_pressure, 4), "pressure [0,1]")
EV.metric("approach_high_integrity", round(hi.approach_pressure, 4), "pressure [0,1]",
          "coherence backs confident engagement")
EV.metric("approach_low_integrity", round(lo.approach_pressure, 4), "pressure [0,1]")

EV.note("Pure appraisal computation: no database is touched, so the run record "
        "reports no verified database rather than claiming one.")
EV.note("Integrity's action↔outcome link is read from a RECONCILED INTENT in the "
        "live substrate (matched_aim, from a fresh re-observation of the world) — "
        "this experiment exercises the derivation those readings feed.")

print("\n" + "=" * 60)
passed = sum(1 for x in results if x)
print(f"RESULT: {passed}/{len(results)} checks passed")
EV.write()
sys.exit(0 if passed == len(results) else 1)
