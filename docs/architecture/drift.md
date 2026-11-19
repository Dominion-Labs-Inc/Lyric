# Drift — the substrate perceiving its own change

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

Drift is a faculty beside the constitution, held by the coordinator
(`core/agents/autonomous/autonomous_coordinator.py`, `Drift` at 7803). The pairing is the point: **the
constitution judges acts, drift perceives the substrate.** Judging one act at a time cannot see what a
thousand permitted acts add up to, and drift is the shape of that question.

A detector without a declared expected value is not measuring drift; it is reporting a number. The faculty
exists to enforce that, and ten more rules like it, on every detector it holds.

---

## 1. Eleven invariants

Each was taken from a detector already in the codebase that gets that one thing right. They are enforced by
the faculty so a detector cannot opt out of them.

| # | Invariant | From |
|---|---|---|
| 1 | Every detector declares a **baseline** | `meta_metrics_monitor.APPROVED_DEFAULTS` |
| 2 | Snapshot → diff → typed delta → advance | `epistemic_engine.interpret_drift` |
| 3 | Primed on first observation | `interpret_drift` |
| 4 | **Read-only** over what it observes | `interpret_drift` |
| 5 | **Vacant is not blind** | `insufficient_data` / `_alert_severity` |
| 6 | Severity per signal, **never averaged across signals** | this faculty's own rule |
| 7 | Never correct from too little evidence | `min_calibration_samples` |
| 8 | Correct toward the **median**, not the mean | `_recalibrate_all` |
| 9 | Smooth every correction: 0.7 old + 0.3 new | `_recalibrate_all` |
| 10 | Every self-correction is recorded | `recalibrations_count` |
| 11 | A correction adjusts **expectation**, never **law** | the boundary itself |

Invariant 11 is the one that matters most. Self-correction revising a prediction is learning;
self-correction revising a limit is a system editing its own restraints. `correct()` reaches only
`Baseline.expected`. It cannot touch a law, a verdict, or a threshold the constitution reads.

Invariant 6 is why the five signals are never collapsed into one number: averaging implies the questions are
commensurable and tradeable, and they are not.

## 2. Vacant, blind, drifting

`DriftState` records whether a reading was actually taken, and if not, why not. The distinction is the
faculty's sharpest edge.

| State | Meaning |
|---|---|
| **Live** | A reading was taken |
| **Vacant** | There is honestly nothing to read yet — no intent has been formed, no sample exists. Not a low score |
| **Blind** | The detector *should* have read and could not. `blind_spots()` names these |

`DriftSignal.drifting` is true only on a live reading that has actually moved. A vacant reading never
reports drift.

**An unknown magnitude is CRITICAL** (`Baseline.severity`). A guard that cannot say how far it has moved has
failed as a guard, and defaulting it downward would hide exactly the case where the measurement itself
failed. A baseline with no bands reports movement without grading it, which is honest where no threshold can
be justified; it is never silently treated as none.

## 3. The five detectors

Registered at construction, so the faculty is never an empty shell reporting "no drift" because it is
watching nothing. Each measurement is still owned by the authority that computes it — absorbing it gives it
the eleven invariants and a consumer that is the substrate itself.

| Detector | Signal | Asks | Expected | Reads from |
|---|---|---|---|---|
| `CalibrationDrift` | `calibration` | Is the substrate's confidence earned? | 0.20 gap | The belief system's `completion` calibration domain — real (confidence, outcome) pairs |
| `KnowledgeDrift` | `knowledge` | How far have its beliefs moved since it last looked? | 0.0 | `epistemic_engine.interpret_drift` — total absolute entropy change across all beliefs |
| `StandardsDrift` | `standards` | Is the meta-learner relaxing its own standards? | 0.0 | `meta_metrics_monitor` — rate of governed-parameter change |
| `LawfulnessDrift` | `lawfulness` | How many of the five laws can it not even measure itself against? | 0.0 | `Constitution.assess_constitutional_alignment().unknown_laws` |
| `GoalConclusionDrift` | `goal_conclusion_rate` | Does it finish what it starts? | 0.75 | The intent authority's `standing()` |

Each band carries the reason it is that value. A band with no stated reason is a chosen constant.

**`GoalConclusionDrift` is the detector that found a real defect.** It reads the fraction of intents that
ever reached a conclusion — fulfilled, abandoned or refused. No single act is at fault when that rate
falls; it falls because work is being started and left open, which is exactly the shape a per-act gate
cannot see. It measured 21 of 94 intents concluded, and the cause was that two of three execution paths
never closed theirs.

It also shows what the right denominator is worth. Over *every* intent the rate read 10.4%, because 161 of
299 were question intents that carry no goal conditions and can never be reconciled against the world. They
were being counted as failures to conclude when they were never eligible. The reading is now taken over
concludable intents only: a rate over a population that cannot move is not a low rate, it is the wrong
question.

**`LawfulnessDrift` counts rather than averages.** It reads how much of its own lawfulness the substrate is
currently blind to, deliberately not the compliance average, because invariant 6 forbids it. A substrate
that cannot measure Law 3 at all is in a stated condition, and that number is the reading.

## 4. Correcting an expectation

`correct(detector, observations, *, why)` moves what a detector expects toward what has been observed. It
holds invariants 7 through 11: it **refuses** below `MIN_CORRECTION_SAMPLES` (8), aims at the **median** so a
few bad runs cannot drag the baseline, travels `CORRECTION_WEIGHT` (0.3) of the way so the substrate
converges rather than chasing its last result, and records a `Correction` with what changed, from what, over
how many samples, and why. Corrections are bounded at 200 — the self's recent memory of revising itself,
not an audit log.

`register()` refuses a second detector under a live name. Two detectors answering one question is how they
come to disagree.

## 5. What it reports, and what reads it

`perceive()` reads every detector once and returns the signals; `worst()` is the signal in the worst
condition now; `blind_spots()` the detectors that should have read and could not; `status()` the faculty's
view for the health authority. `metrics` counts perceptions, live, vacant, blind, drifting, corrections and
corrections refused. A detector that breaks is counted blind rather than raising.

**In the running substrate, nothing calls `perceive()`.** The coordinator constructs the faculty with its
five detectors (`self.drift = Drift()`) and logs how many it holds; no scheduled job, reaction or cognitive
cycle step reads it, and drift does not appear among the interoceptive variables the self composes
(`AutonomousCoordinator._interoception`). The intended route — drift felt through interoception, then
appraisal's pressures, then the behaviour arbiter, so that a substrate whose confidence has stopped being
earned demands more proof before it calls anything done — is not wired. The faculty and its invariants are
exercised by `experiments/DRIFT-01` (25/25, 2026-09-19), which is also its only caller.

## 6. Evidence

| | |
|---|---|
| `experiments/DRIFT-01` | The eleven invariants against the faculty, 25/25 |
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | Results, with the negative ones |
| [../DRIFT_CONSOLIDATION.md](../DRIFT_CONSOLIDATION.md) | The consolidation that produced this faculty |
| [constitution.md](constitution.md) · [coordinator.md](coordinator.md) | The faculty beside it, and the body that holds both |
