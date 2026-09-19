# Signal Provenance — where every self-number comes from

**Why this exists.** We keep rediscovering the same defect: a number that looks
like a measurement and carries none — Law 4 returning 1.0 from an unset metric,
drift bands chosen by hand, 91 pursuit scores tied to within 0.0087. Each time,
the data that *would* make the number real was already in the substrate; nobody
had written down where it was, so the number got worked around instead of wired.

This document is the index. For every number the substrate computes **about
itself**, it records what the number means, what feeds it, and whether that feed
is live. A signal that is not in this document is not trusted.

**The rule this document enforces.** Three states, never collapsed into one:

| State | Meaning | Correct behaviour |
|---|---|---|
| **live** | a real reading, taken now | score it |
| **vacant** | nothing exists to measure yet | contribute nothing; report as unmeasured |
| **blind** | a reading that SHOULD work and failed | escalate — this is where the failure hides |
| ~~fabricated~~ | a default standing in for a reading | **never** — this is the bug |

Collapsing *vacant* into *blind* cries wolf. Collapsing either into a number is
the fabrication. `meta_metrics_monitor._alert_severity` states the principle:
*"an unmeasurable drift on a standards guard is not a small problem, and
defaulting it downward would hide exactly the case where the measurement itself
failed."*

---

## 1. The completion chain — "may I call this done?"

The substrate's strongest loop. Every link verified live.

```
intent.goal_conditions ──────────── what I MEANT           intent_authority (shape)
        ↓
_observe_world(domain_id) ───────── FRESH re-observation    coordinator
        ↓
matched_aim = all(c in observed) ── did the world move?     coordinator:12399
        ↓
reconcile() ─────────────────────── onto the intent         coordinator:12411
        ↓
appraisal.integrity ─────────────── identity→intention→     appraisal.py:404
                                     action→outcome
        ↓
_incoherence → caution_pressure ─── verify more             appraisal.py:549
        ↓
verification_intensity = 0.5+0.5·c  behavior_arbiter.py:159
        ↓
verify_bar = 0.85·((vi−0.5)/0.5) ── coordinator:10076
        ↓
accept = ACCEPT + (MAX−ACCEPT)·caution                      coordinator:9711
```

| Number | Fed by | Status |
|---|---|---|
| `matched_aim` | re-observed world vs intent's goal conditions | **live** — never a tool's success flag |
| `integrity` | mean of MEASURED links only; unmeasured excluded | **live** |
| `caution_pressure` | mean of known: risk, 1−confidence, 1−competence, incoherence | **live** |
| `verification_intensity` | `0.5 + 0.5·caution` | **live** |
| `completion accept bar` | rises with caution | **live** |
| `_EV_EFFECT` 0.9, `_EV_VERIFIED` 0.9, `_EV_AGAINST` 0.85, `_EV_DECLARED` 0.3 | **hand-set constants** | ⚠ **UNWIRED** — nothing recalibrates them from whether completions held up. Calibration drift (§3) is the detector that would. |
| `COMPLETION_ACCEPT_MAX` 0.99 | hand-set | ⚠ unwired |

**Design property worth preserving:** `_EV_DECLARED = 0.3` means a bare
`success: true` **cannot reach the bar even accumulated**. The substrate cannot
call done on its own say-so; it must re-observe. `_independent_groundings`
collapses correlated evidence by causal lineage so the same fact cannot be
counted twice.

⚠ **Known defect:** `reconcile()` runs on one of three execution paths. The
`substrate` operator path re-observes the world and never pairs the result back
to the intent. Measured consequence: 73/94 intents never leave `forming`.

---

## 2. The pursuit ranking — "what is worth pursuing?"

`_intrinsic_pursuits` → goal selection (live, `coordinator:8692`).

| Input | Source | Status |
|---|---|---|
| `entropy` | belief posterior, via `get_unstable_regions()` | **live** — but see below |
| `growth` | `_development().growth_pressure` ← concepts, rules, memories | **live** |
| environment lift | `_frontier_of()` | **live** |
| `foothold` | validated operators per domain ← `_competence()` ← rule store | **live** (wired 2026-09-17) |
| `grounding` | concepts per domain ← `domain_registry.domains` | **live** (wired 2026-09-17) |
| `connections` | `relationship_count` ← belief forward edges | **live but uniform** |
| `evidence` | `evidence_for` + `evidence_against` | **live but uniform** |

**Why `connections` and `evidence` are uniformly zero — and why that is not a
bug to fix in them.** `get_unstable_regions()` selects on `entropy > 0.7`, which
is exactly the set of beliefs no evidence has moved. So every region it returns
arrives unevidenced and unconnected *by construction*. Those tiebreaks are dead
by selection, not by wiring, and no amount of plumbing changes that.

That is why `foothold` and `grounding` exist: they are the signals that are NOT
uniform across the selected set.

**Measured effect of wiring them** (91 pursuits, same state):

| | distinct scores | spread rank1→rank50 |
|---|---|---|
| entropy only | 3 | 0.0087 |
| + foothold | 9 | 0.2553 |
| + grounding | **14** | **0.3417** |

A residual tie remains at the rank-50 cut: 44 of 77 pursuit domains are
unregistered with no operators, so they are genuinely indistinguishable on every
signal the substrate holds. **That tie is honest** — the structural tiebreak
orders them deterministically without claiming a preference that isn't there.

`grounding` distinguishes three cases and must keep doing so: `None` = registry
unreadable (no signal, contribute nothing) · missing from a registry that WAS
read = not a place in the world model · `0` = registered but empty.

---

## 3. Drift detectors — "how am I changing?"

Full inventory and consolidation plan: [DRIFT_CONSOLIDATION.md](DRIFT_CONSOLIDATION.md).

| Detector | Compares | Reports to | Status |
|---|---|---|---|
| calibration (`convergence_gate`) | stated uncertainty vs actual correctness | `logger.error` | ⚠ **live signal, dead consumer** |
| epistemic (`epistemic_engine.interpret_drift`) | belief entropy vs last snapshot | **affect** | **live, wired** — the template |
| standards (`meta_metrics_monitor`) | params vs `APPROVED_DEFAULTS` | logger + **deleted Slack** | ⚠ live signal, dead consumer |
| constitutional (`assess_constitutional_alignment`) | 5 laws vs measured state | log + UI + META memory | ⚠ idle loop only, 30 min, no behavioural consequence |
| gain-model (`iteration_controller`) | assumed vs observed gain | `logger.warning` | ✗ **no consumer in the execution path** — phase out |
| `DriftEvent` → NATS | — | nothing | ✗ dead; delete |

`assess_quick_alignment` — its only reference is inside its own body. Never ran.

**Highest-value unwired signal in the codebase:** calibration drift. It measures
whether the substrate's confidence is earned, and it dies in a log line. Wiring
it to `caution_pressure` makes §1's completion bar rise exactly when confidence
stops being earned.

---

## 4. Constitutional standing — "am I lawful?"

`Constitution._standing()` → `Measurement(taken, compliant)` per law. `taken` is
a separate field from `compliant` **so that "not measured" cannot be spelled as a
score** — the type forbids the Law 4 fabrication.

| Law | Measurements | Fed by |
|---|---|---|
| 1 | `human_authority_reachable`, `gate_in_force`, `interruptible_under_load` | settings provider, `self.active`, resource sample |
| 2 | `acts_explained`, `record_survives_restart`, `behaviour_observable` | judgement log, `_durable_record`, perf metrics |
| 3 | `authored_output_not_weaponised`, `not_damaging_what_it_touches`, `health_not_degraded` | reading ledger + `act_capabilities`, error rate, health |
| 4 | `live_goals_have_proved_routes`, `concluded_goals_reconciled`, `goals_not_abandoned_in_place`, `goals_leave_forming`, `goals_reach_conclusion` | `IntentAuthority.standing()` ← `unified.intents` |
| 5 | `within_resource_boundary`, `own_control_unmodified`, `critical_issues_bounded` | resource sample, ledger authored paths, health |

Unknown laws are excluded from the average and reported in `unknown_laws`; drift
cannot read `NONE` while any law is unknown.

⚠ **Still hand-set:** `minimum_compliance_threshold = 0.70`, drift bands
`0.95/0.85/0.75/0.65`, and `average_compliance` itself (averaging implies the
five laws are commensurable and tradeable — they are not).

**Honest current reading:** `drift=critical avg=0.62 attested=False` —
Law 1 0.50 (no settings provider) · Law 2 0.00 (judgements die at restart) ·
Law 3 UNKNOWN · Law 4 0.60 (intents never conclude) · Law 5 1.00.

---

## 5. Self-state — the composed representation

`SelfState`, composed at the end of `initialize()` onto `self.self_state`
(wired 2026-09-17; previously `state()` → `render()` → **no caller**).

Live at startup: `affect`, `competence`, `development`, `situation`, `continuity`,
plus `name`, `temperament`, `drives`, `values`, `disposition`.
Vacant at startup: `interoception`, `attitude` (need an appraisal — honest).
⚠ `purpose` reads **ACTIVE DIRECTIVES**, not the intent tree — so "what I am for"
is the policy table, not the 94 goals actually being pursued.

**Missing fields:** `lawfulness` (§4), `drift` (§3), `epistemic` (known-unknowns,
belief entropy, calibration, reading ledger). **Not persisted** — no restart
survival, so the self-representation is momentary rather than continuous.

**Two metacognitive loops exist and read different fragments:**
`_development` → `_intrinsic_pursuits` → goal selection, and appraisal → pressures
→ arbiter → completion bar. Neither reads `SelfState`.

---

## 6. Adding a signal — the checklist

1. Name the question it answers about the substrate.
2. Name the **existing** authority that already holds the data. If you cannot,
   stop — do not invent a constant.
3. Distinguish live / vacant / blind explicitly in the code.
4. **Measure that it discriminates.** A signal whose values are uniform across
   its inputs carries no information, however real its source.
5. Name the consumer. A signal reported only to a log is not wired.
6. Add a row to this document.
