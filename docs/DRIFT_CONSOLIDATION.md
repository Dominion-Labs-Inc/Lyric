# Drift Consolidation — capability inventory and absorption plan

**Purpose.** One first-class Drift faculty in the coordinator, beside the Constitution,
so the substrate PERCEIVES ITS OWN DRIFT and can correct itself. Today drift is
computed in eight places and reported to logs, a deleted Slack integration, and a
NATS broker nothing has used in six months. The substrate measures its own
degradation and cannot feel it.

**Method** (same as the security consolidation): inventory capabilities FIRST,
absorb or rewrite each one, prove the new authority holds every capability, and
only THEN delete. Nothing is deleted on the strength of a plan.

**Status** (2026-09-17): inventory complete; two consolidations scoped (§1 substrate
self-drift, §2 tool-system drift). **Step 0 DONE and evidenced** (RECONCILE-01 27/27).
**Step 1 IN PROGRESS** — the Drift faculty itself, carrying the eleven invariants,
with no detector absorbed yet. Absorption (step 2) begins only once the faculty
holds them.

Done so far, each verified against the live substrate:

| Change | Evidence |
|---|---|
| `_reconcile_intent(intent_id, domain_id, …)` — reconciliation is a PIPELINE STAGE, no longer plan-bound | PLANNING-01 39/39, INTENT-01/03, OPERATOR-REMOVAL-01 19/19 |
| Every owner path closes its pursuit once, from the world; steps close nothing | **RECONCILE-01 27/27** · CREDIT-01 25/25 · INTENT-04 15/15 · INTENT-03 13/13 |
| `IntentAuthority.standing()` — the substrate-wide goal set, actor-free | reads live `unified.intents` |
| Constitution standing assessment on real measurements; `Measurement.taken` separate from `compliant` | CONSTITUTION-01 39/39 |
| Law 4 measures whether goals CONCLUDE (was a fabricated 1.0) | reports 73/94 never leave `forming` |
| `SelfState` composed at startup onto `self.self_state` (was `state()` → `render()` → no caller) | 5/8 derived fields live at boot |
| Pursuit ranking wired to `foothold` + `grounding` | distinct scores 3 → 14; spread 0.0087 → 0.3417 |
| LLM-era media stack removed: `av`, `faster-whisper`, `qwen-vl-utils` + `tests/test_pipeline_diagnosis.py` | objc dylib clash gone; embeddings 384-dim, cv2 4.13.0 OK |

Signal-by-signal provenance: [SIGNAL_PROVENANCE.md](SIGNAL_PROVENANCE.md).

---

## 0. The distinction that governs the whole plan

Three things in this codebase are called "drift" and only the first consolidates:

| Kind | What it is | Disposition |
|---|---|---|
| **Detector** | measures observed against expected | **absorb into the one authority** |
| **Mechanism** | deliberate drift as a designed behaviour | **leave alone — it is what detectors watch** |
| **Invariant prose** | the word "drift" used to mean "two copies must not diverge" | not drift monitoring; ignore |

Mechanisms that must NOT be folded in — folding them would delete real faculties:

- `core/reasoning/bayesian_uncertainty.py:512` — unreinforced beliefs decay toward 0.5
  (maximum uncertainty). This is how the substrate forgets; it is an INPUT to drift.
- `core/agents/autonomous/intrinsic_motivation.py:2159` — `_BASELINE_DRIFT = 0.01`, the
  mood trait slowly following lived mood. This is temperament forming; also an INPUT.

Invariant prose (no monitoring, no action needed): `core/domain/domain_registry.py`
uses "cannot drift from its owner" to mean single-authority.

---

## 1. Capability inventory — substrate-side detectors

### 1.1 `core/execution/convergence_gate.py` — CALIBRATION drift · WIRED

The substrate's honesty about its own confidence. Buckets `(uncertainty, success)`
pairs and checks that stated uncertainty tracks actual correctness:
low uncertainty (<0.3) should mean high success (>0.8); high uncertainty (>0.7)
should mean low success (<0.5).

| Capability | Keep? |
|---|---|
| paired (uncertainty, outcome) sample collection | **absorb** |
| bucketed success-rate by uncertainty band | **absorb** |
| correlation check → `drift_detected` | **absorb** |
| `insufficient_data` below 10 samples — refuses to score what it cannot measure | **absorb — this is the vacant-vs-blind rule done right** |
| periodic re-check every 50 samples | **absorb** |
| reports to `logger.error` and nothing else | **rewrite — this is the whole problem** |

**This is the highest-value signal in the inventory.** It is literally the substrate
detecting its own overconfidence, and it currently dies in a log line.

### 1.2 `core/reasoning/epistemic_engine.py::interpret_drift` — EPISTEMIC drift · WIRED

Diffs the whole belief graph's entropy against the last snapshot. The **only**
detector that already reports to the self: `neural_bridge` routes it to affect as
"the knowledge→emotion producer".

| Capability | Keep? |
|---|---|
| snapshot → diff → typed mutations → advance snapshot | **absorb as the AUTHORITY'S CORE PATTERN** |
| priming: first call sets the baseline instead of emitting a flood of false "new" | **absorb — every detector needs this** |
| typed vocabulary: `new_belief` / `entropy_reduction` / `entropy_increase` | **absorb** |
| READ-ONLY over what it observes | **absorb as an invariant for all detectors** |
| already feeds affect | **preserve the wire; make it the template** |

### 1.3 `core/learning/meta_metrics_monitor.py` — STANDARDS drift · WIRED

Watches whether the meta-learner is relaxing its own standards. The best-engineered
detector in the codebase and the richest source of capabilities.

| Capability | Keep? |
|---|---|
| `APPROVED_DEFAULTS` — a DECLARED baseline to measure against | **absorb — the model for all baselines** |
| `capture_snapshot` — durable point-in-time snapshots | **absorb** |
| `_snapshot_series` — time series per measured column | **absorb — gives drift real history** |
| `_describe_trend` — rising / falling / stable | **absorb** |
| `_parameter_rate_of_change` — speed of movement, not just distance | **absorb** |
| `_measured_exploration_rate` — configured vs ACTUALLY measured | **absorb** |
| `detect_standards_degradation` | **absorb** |
| `_alert_severity` with `_ALERT_BANDS` — bands justified by information content | **absorb** |
| **unmeasurable on a guard ⇒ CRITICAL, never defaulted downward** | **absorb as a LAW of the authority** |
| `_adoption_velocity`, `_confidence_trend` | **absorb** |
| escalates CRITICAL to `slack_notifier` — deleted six months ago | **delete that path; route to self-perception** |

### 1.4 `core/execution/iteration_controller.py` — GAIN-MODEL drift · **DELETE — PHASE OUT COMPLETELY**

**Verified: it has NO consumer in the execution path.** `health_monitor` reads
`get_stats()` for reporting; `shared_types.py:202` mentions it in a comment; the
only things that exercise it are `tests/test_phase2_iteration_controller.py` and
`tests/test_phase3_self_optimization.py`. Its `_recalibrate_all()` loop corrects
parameters **nothing reads**. It self-corrects into a vacuum.

Its capabilities are also strictly WEAKER than the live mechanism (§1.7): it answers
*"when should I stop trying?"* from a curve fitted to its own past, never
re-observing anything. The live loop answers *"is it actually true?"* from a fresh
observation of the world.

Nothing to absorb. Delete the module, its two test files, the `shared_types`
comment, and the `health_monitor` stats read.

### 1.7 THE LIVE MEANT-vs-HAPPENED LOOP — already complete, WIRED, and the model

This is the mechanism iteration_controller was a weaker imitation of. It already
exists end to end and already reads intent:

```
intent.goal_conditions (what was meant)
  → _observe_world(domain_id)            ← FRESH re-observation, not a success flag
  → matched_aim = all(c in observed)     autonomous_coordinator.py:12399
  → reconcile() onto the intent          :12411
  → appraisal.integrity  (identity→intention→action→outcome)   appraisal.py:404
  → _incoherence → caution_pressure + replan_pressure          appraisal.py:549
  → behavior_arbiter.verification_intensity = 0.5 + 0.5·caution  behavior_arbiter.py:159
  → verify_bar = 0.85·((vi − 0.5)/0.5)                         coordinator:10076
  → completion acceptance bar rises                            coordinator:9711
```

The coordinator's own comment at :12576 reads **"THE LOOP CLOSES HERE."**

Properties that make it the template — each one better than iteration_controller's:

| Property | Where |
|---|---|
| "expected" is what the substrate SAID it would achieve, not a fitted parameter | `goal_conditions` |
| "observed" is a fresh re-observation of the world | `_observe_world` |
| a bare `success: true` is worth 0.3 and **cannot reach the bar even accumulated** | `_EV_DECLARED` |
| correlated evidence collapses by causal lineage — cannot multiply into false confidence | `_independent_groundings` |
| unmeasured links are EXCLUDED, never zero-filled | `_known()`, `_integrity_terms` |
| a faithful attempt thwarted externally leaves the link unmeasured — integrity stays intact | `appraisal.py:380` |
| correction adjusts the completion BAR, never the law | `_decide_completion` |

**Disposition: preserve and extend.** Drift becomes a second source feeding the same
`caution_pressure` input this loop already consumes — not a parallel mechanism.

#### ⚠ DEFECT — the loop closes on ONE of three execution paths

`reconcile()` has exactly **one call site** (`:12411`), inside `_drive_substrate_goal`
— the `substrate_plan` path. The other two paths never reconcile:

| Path | Re-observes? | Reconciles intent? |
|---|---|---|
| `substrate_plan` | yes | **yes** |
| `substrate` (single learned operator, `:12931`) | **yes** — `RuntimeOutcome.CONFIRMATION` | **NO** |
| `substrate_reading` (`:12646`) | n/a | **NO** |

The `substrate` path is the serious one: it **already re-observes the world** and
carries a runtime outcome, then never pairs it back to the intent. So for every
single-operator act, `matched_aim` is never written, integrity's action↔outcome link
falls back to the attribution label, and the question the intent authority exists to
answer — *"did I do what I meant"* — goes unanswered.

**This is visible in the live data.** Of 86 intents: 19 fulfilled, 1 abandoned,
**66 stuck in `forming`** — formed by `planning_engine`/`neural_bridge` and never
reconciled, because the path that executed them does not reconcile.

Fix: reconcile on every path that observes an outcome. This is a prerequisite for
drift — a drift authority reading meant-vs-happened would be reading 23% of the work.

### 1.5 Constitutional standing assessment — `autonomous_coordinator.py` · PARTIAL

Scores the five laws against measured standing state.

| Capability | Keep? |
|---|---|
| per-law standing measurements, `taken` separate from `compliant` | **keep — becomes a drift SOURCE** |
| unknown laws excluded from the average rather than scored 1.0 | **keep** |
| its own private drift bands (`0.95/0.85/0.75/0.65`) | **delete — unjustified; the authority owns severity** |
| `average_compliance` across five laws | **delete — averaging implies the laws are tradeable** |
| runs only on the idle loop, every 30 min, priority `low` | **rewrite — event-driven, like the constitution** |
| `assess_quick_alignment` | **DEAD — zero callers; delete** |

### 1.6 `core/agents/autonomous/directive_evolution_engine.py` — DIRECTIVE drift · WIRED (1 importer)

Mostly an evolution LEDGER, not a detector: `log_evolution`, `get_evolution_history`,
`get_evolution_chain`, `get_version_lineage`, `get_evolution_summary`. The drift part
is a 30% threshold over that history.

| Capability | Keep? |
|---|---|
| `drift_threshold` detection over directive outcomes | **absorb into drift** |
| evolution lineage / version chain / provenance of policy change | **stays with directives — this is policy history, not drift** |
| `AB_TEST_STARTED` / `AB_TEST_WINNER` evolution types | **delete — the learning authority owns arm ranking** |

---

## 2. TOOL-SYSTEM drift — ONE capability, not one per tool

**Two consolidations, and they must never be merged into each other.**

* §1 is the substrate perceiving ITSELF → the first-class Drift faculty, feeding
  interoception.
* THIS section is drift as a CAPABILITY the tool system offers, applied to
  external data the substrate is working on. It says nothing about the substrate
  and must never reach interoception.

The defect here has the same shape as everywhere else: drift was implemented
**per tool** rather than once for the tool system, so two tools answer the same
question by different methods and one of them answers it badly.

| Module | What | Disposition |
|---|---|---|
| `core/learning/drift_monitoring/` (Evidently 0.7.20) | PSI over reference vs current dataframes | **KEEP — this IS the one tool-system drift capability.** Statistically grounded; already exposed as `MonitorDataDriftTool` |
| `core/tools/data_processing_tools.py:1636` `_analyze_drift` | hand-rolled: *">20% change in mean"* for numerics, ad-hoc categorical compare | **DELETE and re-route.** Reachable through the profiling tool's `compare_with` (`:1773`). The 20% threshold is a chosen constant with nothing behind it — the same defect as the constitution's drift bands. Route that tool to the PSI capability |
| `core/tools/database_tools.py:1178` | schema hash vs expected | **KEEP SEPARATE** — structural identity, not a distribution. A different question correctly answered by a different method |
| `core/monitoring/publishers/event_publisher.py` | `DriftEvent` → NATS | **DELETE** — verified: only reference is a re-export in `publishers/__init__.py`; nothing calls it. NATS unused ≥6 months |
| `core/security/_disabled/firewall_manager.py` | config drift | already archived. **Correction: the `health_monitor:2985` read is guarded** — `firewall is None or isinstance(firewall, str)` sets `firewall_available = False` and returns. It degrades honestly rather than fabricating. **Leave it.** |

**The rule this establishes:** a tool that needs drift CALLS the tool-system
drift capability. It does not implement its own. A second implementation of a
question the system already answers is a duplicate authority, free to disagree
with the first the next time either one moves.

---

## 3. Dead modules found during this inventory

Verified by full-repo reference search, not importer count alone:

| Module | Lines | References outside itself | Note |
|---|---|---|---|
| `directive_ab_testing.py` | 499 | 0 | `directive_system.py` already documents it as unwired — learning authority owns arm ranking |
| `directive_safety_monitor.py` | 520 | 0 | |
| `perception_idea_monitor.py` | — | **0 — zero references anywhere in the repo** | **NOT a drift system.** It is a creative goal-seed generator (novelty + emergent pattern → goal seeds) built on the deactivated quantum engine. Needs its OWN triage against `intrinsic_motivation`'s curiosity/novelty drives before deletion — the capability may be worth preserving |
| `assess_quick_alignment` / `_check_constitutional_alignment_quick` | — | its only occurrence is inside its own body | never ran |

---

## 4. The one authority — shape

**Drift is self-perception**, not a separate reporting system. It reports to the organ
that already exists:

```
detectors → Drift (first-class faculty) → _interoception() → appraisal pressures
                                                                    ↓
                                                            behavior_arbiter
                                                    (escalate/replan/avoid/caution…)
```

That path is already live and already drives behaviour. Drift does not need its own
enforcement arm — it needs to be **felt**. The consequence mechanism exists:

- `caution_pressure` — "proceed, but verify more"
- `replan_pressure` — "the approach is wrong, not the situation"
- `escalation_pressure` — "we cannot fix this from here"

Invariants the authority holds, each taken from a detector that already gets it right:

1. **Every detector declares a baseline** (from `APPROVED_DEFAULTS`).
2. **Snapshot → diff → typed delta → advance snapshot** (from `interpret_drift`).
3. **Primed on first observation** so a cold start is a baseline, not a flood
   (from `interpret_drift`).
4. **READ-ONLY over what it observes** (from `interpret_drift`).
5. **Vacant ≠ blind.** Nothing-to-measure-yet is neutral (`insufficient_data`);
   a measurement that SHOULD work and failed is CRITICAL (from `_alert_severity`).
   These are two different states and must never collapse into one.
6. **Severity is per-signal, never an average across signals.**

And the correction laws, taken from the only loop that already closes
(`_recalibrate_all`) — because detecting drift is half the goal:

7. **Never correct from too little evidence** (`min_calibration_samples`).
8. **Correct toward the MEDIAN of observation**, not the mean — a few bad runs
   must not swing the baseline.
9. **Smooth every correction** (`0.7·old + 0.3·new`) so the substrate converges
   instead of oscillating.
10. **Every self-correction is recorded** (`recalibrations_count`) — a substrate
    that changed its own expectations must be able to say when and by how much.
11. **Correction adjusts EXPECTATION, never LAW.** The authority may recalibrate
    what it predicts of itself; it may never recalibrate what it is permitted to do.
    That boundary is what keeps self-correction from becoming self-modification.

Consumers: interoception/appraisal (primary — this is the point), the Constitution
(reads drift as standing evidence, never owns it), directives (drift tells policy to
evolve; drift never revises law).

---

## 5. Order of work

0. **Close the meant-vs-happened loop on every execution path** (§1.7 defect).
   **DONE — EVIDENCED by RECONCILE-01, 27/27 (2026-09-17).**

   `_reconcile_intent(intent_id, domain_id, …)` is now a pipeline stage, and the
   rule is uniform: **whoever owns the pursuit closes it, once.**

   | Owner | Closes | Guard |
   |---|---|---|
   | `_drive_substrate_goal` (plan) | yes, at the end of the route | — |
   | `_execute_grounded_operator` (one operator) | yes — **including when refused** | skips when `plan_id` present |
   | `_execute_operation` (tools / knowledge) | yes | skips when `plan_id` present |
   | `_run_tool` | **no — owns nothing** | its one production caller loops it per step with the SAME task |

   The `plan_id` guard matters: `state_plan_to_tasks` stamps the plan's intent_id
   onto EVERY step, so an unguarded close concludes a multi-step route on step one,
   recording "missed" against a world still being walked. A first version of this
   did exactly that and **every suite still passed** — no experiment exercises
   `_execute_grounded_operator`.

   **`RECONCILE-01` drives the OWNER paths through `execute_task`**, never `_run_tool`.
   It checks:
   - a two-step plan closes once, after both steps;
   - plan steps (operator and declared-tool) close nothing;
   - a standalone operator closes its intent, including when refused;
   - a confirmed step that left the world short of the aim closes as **missed**;
   - a declared-tool operation closes its intent.

   **Defects it found, all fixed:**
   - a **refused** standalone operator returned before closing, so its intent stayed in `forming`. Closing now
     happens in `_execute_grounded_operator`, which wraps the act (`_act_on_grounded_operator`);
   - the operator path closed its intent but did not return the verdict with its result (`intent_outcome`).

   **Not live, so not covered:** `PlanningEngine.get_next_tasks` has no production caller, so nothing runs a
   route step by step from the queue. If that is wired, the queued route needs an owner, because every one of
   its steps carries `plan_id`.

   **Why intents still sit in `forming`.** All 107 stuck goal intents measured on 2026-09-17 are proved
   one-step routes formed by experiment harnesses, which proved a route and then acted through `_run_tool`
   or not at all. They are harness residue, not a live execution path that fails to close.
1. Build the Drift faculty with the invariants above. No detectors moved yet.
2. Absorb detectors one at a time, each with a parity benchmark: same input, same
   finding as the original, 0 regressions.
   Order: calibration (1.1) → epistemic (1.2) → standards (1.3) →
   constitutional (1.5) → directive threshold (1.6).
3. Wire Drift into the `caution_pressure` input the live loop ALREADY consumes —
   not a parallel path. Prove end-to-end: a real calibration failure raises caution,
   `verification_intensity` rises, and the completion bar rises with it.
4. Prove self-correction: the substrate detects its own drift and demands more
   grounding before calling done than it would have.
5. **Only then** delete: `iteration_controller.py` + its two test files + the
   `health_monitor` stats read + the `shared_types` comment; `event_publisher.py`;
   `directive_ab_testing.py`; `directive_safety_monitor.py`;
   `assess_quick_alignment`; the constitution's private drift bands and
   `average_compliance`; the `AB_TEST_*` evolution types.
   **Not** the guarded `firewall_drift_detected` read.
6. Separately triage `perception_idea_monitor.py` against intrinsic motivation.

Evidence: one experiment per absorption step with a `RunRecord`, plus a
`DRIFT-CONSOLIDATION-01` end-to-end run proving step 4.
