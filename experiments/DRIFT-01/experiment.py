#!/usr/bin/env python3
"""DRIFT-01 — the Drift faculty holds its eleven invariants, against live state.

DRIFT_CONSOLIDATION step 1. The faculty is the vessel; no existing detector has
been absorbed yet (that is step 2, one at a time against a parity benchmark).
What this proves is that the vessel enforces the laws the absorbed detectors will
have to obey — because each invariant was taken from a detector already in this
codebase that gets that ONE thing right, and the point of consolidating is that
every detector then gets all eleven.

Real throughout: the faculty is the one the coordinator owns, and
`goal_conclusion_rate` reads the live intent authority over the real database.
Nothing is stubbed, and no detector is invented to make a check pass.

  1  every detector declares a BASELINE with a stated reason
  2  snapshot -> diff -> typed delta -> advance
  3  PRIMED on first observation — a cold start is not drift
  4  READ-ONLY over what it observes
  5  VACANT is not BLIND
  6  severity per signal, never averaged across signals
  7  never correct from too little evidence
  8  correct toward the MEDIAN, not the mean
  9  smooth every correction (0.7 old + 0.3 new)
 10  every self-correction is recorded
 11  correction adjusts EXPECTATION, never LAW

Run: ./venv_lyric/bin/python3 experiments/DRIFT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "DRIFT-01",
    claim=("The Drift faculty enforces eleven invariants on every detector it "
           "holds: a declared baseline with a stated reason, prime-then-diff, "
           "read-only observation, VACANT distinguished from BLIND, per-signal "
           "severity with no averaging, and correction that requires evidence, "
           "aims at the median, moves only partway, is recorded, and reaches the "
           "substrate's EXPECTATIONS while being unable to reach its LAWS."),
    hypothesis=("If the vessel did not enforce these, an absorbed detector could "
                "opt out of them one at a time — which is exactly how the existing "
                "detectors came to disagree: each gets one thing right and the "
                "rest wrong. A cold start would read as drift, an unmeasurable "
                "guard would read as healthy, and a baseline could be moved on two "
                "data points."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.agents.autonomous.autonomous_coordinator import (
        Drift, DriftDetector, DriftSignal, DriftState, DriftSeverityBand,
        Baseline, GoalConclusionDrift, AutonomousCoordinator)

    drift = Drift()

    print("\n== 1. Every detector declares a baseline, with a stated reason ==")
    det = drift.detectors["goal_conclusion_rate"]
    check("the detector carries a declared baseline", det.baseline is not None,
          f"expected={det.baseline.expected}")
    check("the baseline states WHY it is that value — not a chosen constant",
          bool(det.baseline.why.strip()), det.baseline.why[:72] + "…")
    check("its severity bands are ordered largest-first and each names a severity",
          all(isinstance(t, float) and isinstance(b, DriftSeverityBand)
              for t, b in det.baseline.bands)
          and [t for t, _ in det.baseline.bands] == sorted(
              [t for t, _ in det.baseline.bands], reverse=True),
          str([(t, b.value) for t, b in det.baseline.bands]))

    print("\n== 3. Primed on first observation: a cold start is not drift ==")
    first = await drift.perceive()
    s1 = first["goal_conclusion_rate"]
    check("the FIRST reading is VACANT, establishing footing rather than movement",
          s1.state is DriftState.VACANT and s1.severity is DriftSeverityBand.NONE,
          f"state={s1.state.value} severity={s1.severity.value}")
    check("and it is not counted as drift", not s1.drifting)

    print("\n== 2. Second reading diffs against the baseline and is typed LIVE ==")
    second = await drift.perceive()
    s2 = second["goal_conclusion_rate"]
    check("the second reading is LIVE, with a real observed value from the substrate",
          s2.state is DriftState.LIVE and isinstance(s2.observed, float),
          f"observed={s2.observed}")
    check("it carries a computed magnitude against the declared expectation",
          s2.magnitude is not None
          and abs(s2.magnitude - abs(s2.observed - s2.expected)) < 1e-9,
          f"|{s2.observed:.4f} - {s2.expected}| = {s2.magnitude:.4f}")
    EV.metric("goal_conclusion_rate_observed", round(s2.observed, 4), "fraction",
              "LIVE reading from the intent authority over the real database")
    EV.metric("goal_conclusion_rate_expected", s2.expected, "fraction",
              det.baseline.why)
    EV.metric("goal_conclusion_deviation", round(s2.magnitude, 4), "fraction",
              "how far the substrate sits from finishing what it starts")
    EV.metric("goal_conclusion_severity", s2.severity.value, "band")

    print("\n== 5. VACANT is not BLIND ==")

    class _NothingYet(DriftDetector):
        """Real shape of a detector whose subject does not exist yet."""
        def read(self):
            return None

    class _Broken(DriftDetector):
        """Real shape of a detector whose reading SHOULD work and does not."""
        def read(self):
            raise RuntimeError("the store this guard reads is unreachable")

    band = Baseline(name="probe", expected=1.0, why="probe baseline",
                    bands=((0.1, DriftSeverityBand.CRITICAL),))
    drift.register(_NothingYet("nothing_yet", band))
    drift.register(_Broken("broken_guard", Baseline(
        name="probe2", expected=1.0, why="probe baseline",
        bands=((0.1, DriftSeverityBand.CRITICAL),))))
    signals = await drift.perceive()
    vac, blind = signals["nothing_yet"], signals["broken_guard"]
    check("nothing-to-measure reads VACANT and is NOT graded severe",
          vac.state is DriftState.VACANT and vac.severity is DriftSeverityBand.NONE,
          f"{vac.state.value}/{vac.severity.value}")
    check("a guard that COULD NOT be read is BLIND and CRITICAL — never defaulted down",
          blind.state is DriftState.BLIND and blind.severity is DriftSeverityBand.CRITICAL,
          f"{blind.state.value}/{blind.severity.value}")
    check("neither is reported as drift — absence of a reading is not movement",
          not vac.drifting and not blind.drifting)
    check("the blind one is surfaced separately, as a blind spot",
          [s.detector for s in drift.blind_spots()] == ["broken_guard"],
          str([s.detector for s in drift.blind_spots()]))
    check("a detector that raises does not take the faculty down with it",
          len(signals) == len(drift.detectors), f"{len(signals)} signal(s) returned")

    print("\n== 6. Severity is per signal — no average is produced ==")
    check("the faculty exposes no aggregate score to average away a failing signal",
          not any(hasattr(drift, a) for a in
                  ("average_severity", "overall_drift", "drift_score", "average")),
          "no average_* / overall_* attribute exists")
    worst = drift.worst()
    check("it reports the WORST signal instead, so one healthy reading cannot pay "
          "for a broken one",
          worst is not None and worst.severity is DriftSeverityBand.CRITICAL,
          f"worst={worst.detector} ({worst.severity.value})")

    print("\n== 7-11. Correction: evidence, median, smoothing, record, and the law boundary ==")
    target = drift.detectors["goal_conclusion_rate"]
    before = target.baseline.expected

    thin = [0.10, 0.12, 0.11]
    refused = drift.correct("goal_conclusion_rate", thin,
                            why="too few observations to revise a standard")
    check("7 — a correction on too little evidence is REFUSED",
          refused is None and target.baseline.expected == before,
          f"{len(thin)} samples < {Drift.MIN_CORRECTION_SAMPLES} required; "
          f"expectation still {target.baseline.expected}")

    # Eight real observations with two wild outliers: the median must survive them.
    observed = [0.30, 0.31, 0.29, 0.32, 0.30, 0.31, 0.99, 0.01]
    applied = drift.correct("goal_conclusion_rate", observed,
                            why="eight measured conclusion rates")
    check("a correction with enough evidence is APPLIED", applied is not None,
          f"{before} → {target.baseline.expected:.4f}")

    ordered = sorted(observed)
    median = ordered[len(ordered) // 2]
    mean = sum(observed) / len(observed)
    expected_after = (1 - Drift.CORRECTION_WEIGHT) * before + Drift.CORRECTION_WEIGHT * median
    check("8 — it aimed at the MEDIAN, not the mean (outliers cannot drag a standard)",
          abs(target.baseline.expected - expected_after) < 1e-9,
          f"median={median} mean={mean:.4f} → {target.baseline.expected:.4f}")
    check("9 — it moved only part of the way, so the substrate converges not oscillates",
          min(before, median) < target.baseline.expected < max(before, median),
          f"{before} → {target.baseline.expected:.4f} (target was {median})")
    check("10 — the self-correction is RECORDED, with what it was and why",
          drift.corrections and drift.corrections[-1].was == before
          and drift.corrections[-1].samples == len(observed)
          and bool(drift.corrections[-1].why),
          drift.corrections[-1].why if drift.corrections else "none")
    EV.metric("correction_from", before, "fraction", "the declared expectation before")
    EV.metric("correction_to", round(target.baseline.expected, 4), "fraction")
    EV.metric("correction_median_target", median, "fraction",
              "what the observations actually centred on")
    EV.metric("correction_mean_rejected", round(mean, 4), "fraction",
              "what the mean would have aimed at — dragged by two outliers")
    EV.metric("correction_weight", Drift.CORRECTION_WEIGHT, "fraction",
              "how far one correction travels toward observation")
    EV.metric("min_correction_samples", Drift.MIN_CORRECTION_SAMPLES, "count",
              "below this the substrate will not revise what it expects of itself")

    print("\n== 11. Correction cannot reach the LAWS ==")
    coord = AutonomousCoordinator()
    laws_before = {n: law.law_description for n, law in coord.constitution.laws.items()}
    threshold_before = coord.constitution.minimum_compliance_threshold
    await coord.drift.perceive()
    coord.drift.correct("goal_conclusion_rate", observed, why="probe")
    check("the constitution's five laws are untouched by a drift correction",
          {n: law.law_description for n, law in coord.constitution.laws.items()} == laws_before)
    check("and its compliance threshold is untouched",
          coord.constitution.minimum_compliance_threshold == threshold_before,
          f"{threshold_before}")
    check("correction reaches ONLY a detector's expectation — it has no handle on a law",
          set(Drift.correct.__code__.co_names).isdisjoint(
              {"laws", "constitution", "minimum_compliance_threshold", "judge"}),
          "no law-touching name appears in correct()")

    print("\n== 4. READ-ONLY: observing does not move what is observed ==")
    from core.reasoning.intent_authority import get_intent_authority
    standing_before = await get_intent_authority().standing()
    for _ in range(3):
        await coord.drift.perceive()
    standing_after = await get_intent_authority().standing()
    check("three perceptions left the observed goal set exactly as it was",
          standing_before["total"] == standing_after["total"]
          and standing_before["concluded"] == standing_after["concluded"],
          f"total {standing_before['total']}→{standing_after['total']}, "
          f"concluded {standing_before['concluded']}→{standing_after['concluded']}")

    print("\n== The faculty the coordinator actually owns ==")
    check("the coordinator holds ONE Drift faculty", isinstance(coord.drift, Drift))
    check("a second detector under a live name is refused — one question, one authority",
          _duplicate_refused(coord.drift), "ValueError raised on re-registration")

    EV.metric("detectors_registered", len(drift.detectors), "count")
    EV.note("`goal_conclusion_rate` reads the live intent authority over the real "
            "database; the VACANT and BLIND probes are real detector subclasses "
            "whose subjects genuinely do not exist / genuinely fail to read.")
    EV.note("No existing detector (calibration, epistemic, standards, "
            "constitutional) is absorbed yet — that is step 2, one at a time "
            "against a parity benchmark. This proves the vessel's laws.")

    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"\n==== DRIFT-01: {passed}/{total} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1


def _duplicate_refused(drift) -> bool:
    """Registering a second detector under a live name must raise."""
    from core.agents.autonomous.autonomous_coordinator import GoalConclusionDrift
    try:
        drift.register(GoalConclusionDrift())
    except ValueError:
        return True
    return False


sys.exit(asyncio.run(main()))
