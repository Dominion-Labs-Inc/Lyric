"""AFFECT-WIRING-01 — the previously-dangling disposition pressures are now connected.

Two pressures the appraisal authority computes were not reaching behaviour:
  • approach_pressure — never delivered to the BehavioralDirective at all (dangling).
  • avoidance — on the directive but with no flag and no consumer (half-wired).
This proves both now have real teeth, routed through knobs the loop already consumes
(should_explore / max_goals / mode), without changing the emotion authority or its feeders.

  1. APPROACH is delivered to the directive and flagged; a confident state leans in — it widens
     self-initiated breadth (max_goals) beyond what epistemic pull alone would give.
  2. AVOIDANCE is flagged and SUPPRESSES self-initiated exploration — proven in isolation, with
     escalation NOT firing, so it is avoidance (not escalation) doing the suppression.
  3. Regression: the already-wired loops (escalation) are unchanged.
  4. The directive surfaces the new signals (to_dict).

Run: ./venv_lyric/bin/python3 experiments/AFFECT-WIRING-01/experiment.py
"""
from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.autonomous.appraisal import AppraisalState, _derive_pressures   # noqa: E402
from core.agents.autonomous.behavior_arbiter import BehaviorArbiter, ACT_THRESHOLD  # noqa: E402

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def decide(**core):
    s = AppraisalState(**core)
    _derive_pressures(s)
    return s, BehaviorArbiter().decide(s, slots_available=3, queue_pressure="nominal")


print("\n== 1. APPROACH is delivered and leans in (was fully dangling) ==")
s, d = decide(valence=0.8, activation=0.8, confidence=0.9, epistemic_opportunity=0.6,
              progress=0.7, controllability=0.9, competence=0.9, goal_congruence=0.9,
              agency=0.8, risk=0.1)
check("approach_pressure reaches the directive", abs(d.approach - s.approach_pressure) < 1e-9
      and d.approach > 0, f"approach={d.approach:.3f}")
check("should_approach set on a confident state", d.should_approach, f"approach={d.approach:.3f}")
explore_only = round(s.exploration_pressure * 3)
check("approach WIDENS breadth beyond epistemic pull alone",
      d.should_explore and d.max_goals > explore_only,
      f"max_goals={d.max_goals} vs explore-only={explore_only}")

print("\n== 2. AVOIDANCE suppresses self-initiated exploration (was half-wired) ==")
s, d = decide(valence=-0.8, activation=0.5, confidence=0.5, epistemic_opportunity=0.7,
              progress=0.1, controllability=0.9, competence=0.1, goal_congruence=0.3, risk=0.2)
check("exploration pressure WOULD otherwise admit", s.exploration_pressure >= ACT_THRESHOLD,
      f"explore={s.exploration_pressure:.3f}")
check("escalation is NOT firing (isolates avoidance)", not d.should_escalate,
      f"escalation={d.escalation:.3f}")
check("should_avoid set", d.should_avoid, f"avoidance={d.avoidance:.3f}")
check("self-initiated exploration SUPPRESSED by avoidance",
      (not d.should_explore) and "exploration_suppressed_by_avoidance" in d.reason_codes)

print("\n== 3. Regression: escalation path unchanged ==")
s, d = decide(valence=-0.7, controllability=0.1, competence=0.3, progress=0.2,
              attribution="infrastructure_failure")
check("escalation still fires on an external, uncontrollable failure", d.should_escalate,
      f"escalation={d.escalation:.3f}")

print("\n== 4. The directive surfaces the new signals ==")
dd = d.to_dict()
check("to_dict exposes should_avoid + should_approach",
      "should_avoid" in dd and "should_approach" in dd)

print("\n" + "=" * 60)
passed = sum(1 for r in results if r)
print(f"RESULT: {passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
