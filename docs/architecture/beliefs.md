# Beliefs — `BayesianUncertaintySystem`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

*Re-traced 2026-11-19.*

## `BayesianUncertaintySystem` — the belief authority (the circulatory system)

*`core/reasoning/bayesian_uncertainty.py` (about 2,900 lines). Class at 413.*

**Module level, before the class:** `log_odds_of` (47), `probability_of` (56), `evidence_step` (65),
`belief_entropy` (70); the enums `UncertaintyType` (78), `KnowledgeState` (86), `RelationType` (94); and
the dataclasses `BeliefRelationship`, `BayesianBelief`, `KnownUnknown`,
`ResolutionGrounds`, `ConfidenceCalibration`, with `_EvidenceIndex` and `_indexed`
between them. Singletons `get_uncertainty_system` and `get_bayesian_uncertainty`.

### 1. Purpose
The substrate's **single belief store** — every graded, revisable, provenance-aware proposition. Not a boolean fact table: each belief is a Bayesian posterior with prior, likelihood, evidence lists, entropy, credible interval, and a temporal-decay clock. **Revisable** (asserted today, moved/reversed tomorrow) and **provenance-aware** (evidence carries `quality`+`source`). Its defining door is **find-or-create-by-claim** (`observe_claim`, 298): normalise → O(1) index lookup → mint or move the *same* belief, so "I was told X" is idempotent. It is the **circulation hub**: learning/reasoning/hypothesis-testing/domain/epistemic pump evidence IN; completion/memory/motivation/health read posteriors OUT. Singleton `get_uncertainty_system` (2717; alias `get_bayesian_uncertainty` 1849).

### 2. State (`__init__`, 176)
`unified_db` (Postgres), `beliefs: Dict[id, BayesianBelief]`, **`_claim_ids: Dict[claim_key, List[id]]`** + **`_domain_ids: Dict[domain_key, Set[id]]`** (the indexes every read by claim or domain uses; kept exact by `_register_belief` / `_unregister_belief`, the only writers of `beliefs`. The LAST id for a claim is the belief `observe_claim` moves and `belief_for_claim` returns — 1,902 claims are held by more than one belief, and a scan returned the first while observation moved the last), `persistence_drops` (surfaced in stats), `_pending_writes` (DB-down buffer, upsert+replay), `_write_tasks` (tracked fire-and-forget writes for the shutdown drain), `known_unknowns`, `calibrations`, `domain_volatility` (per-domain λ default 0.01), `domain_belief_changes` (last-50 window), `domain_regime_shifts`, `relationships` (CONTRADICTS/SUPPORTS/IMPLIES/WEAKENS/REQUIRES/MUTUALLY_EXCLUSIVE graph), `forward_edges`/`backward_edges`, `propagation_queue`, `stats`.
*Dataclasses:* `BayesianBelief` (136; prior/likelihood/posterior, evidence_for/against, entropy, credible_interval, decay_rate, update_count, confidence_history), `BeliefRelationship` (`reverse_relation()` 69), `KnownUnknown`, `ConfidenceCalibration`. Enums `UncertaintyType` (78), `KnowledgeState` (86), `RelationType` (94).

### 3. Methods by area

#### Creation / observation
- **`create_belief(claim, domain, prior=0.5, evidence=None) -> BayesianBelief`** — mints `belief_<uuid>`, `posterior=prior`, registers through `_register_belief` *before* applying initial evidence (else `update_belief` raises). Mints a new id every call → not idempotent by claim.
- **`_claim_key(claim)`** — `" ".join(claim.strip().lower().split())`; every index op keys on this, so case/spacing never fork a belief.
- **`observe_claim(claim, domain="language", *, supports=True, quality=0.9, source="taught")`** — **the find-or-create-by-claim door.** Key → index; stale entry treated as new. Absent → `create_belief(prior = quality if supports else 1-quality)`. Present → `update_belief(existing, evidence, evidence_supports=supports)`. The idempotent "record I was told this" entry.
- **`update_belief(belief_id, evidence, evidence_supports=True)`** — the core update. **A belief is held in
  log-odds, and evidence adds to it with no cap.** One observation moves it by `evidence_step(quality,
  supports)` = `±_LR_STRENGTH × quality`, with `_LR_STRENGTH = 3.0` (a likelihood ratio of `e^±3q`, so
  quality 1.0 is about 20× or 0.05× and quality 0 moves nothing). The steps: (1) **temporal decay first**,
  so early conclusions are not gravity wells; (2) append evidence, read `evidence_weight`, adjust through
  `_adjust_evidence_with_domain_support` (cross-domain consensus ×1.15); (3) **add the step to the
  log-odds**; (4) **reversal detection** on crossing 0.5; (5) volatility update, recompute entropy and
  credible interval, persist; and if the posterior moved more than 0.05, `propagate_constraints(...)`.

  **Why it is log-odds and not a clamped posterior.** The posterior used to be the belief itself,
  clamped just short of certainty after every step. Past five or six agreeing sources every belief sat at the same value, so **a claim six hundred
  sources hold was as easy to overturn as one six hold**, and a few contrary words brought either to even.
  `TRUTH-01` measured that on 2026-10-07 and the representation changed the same day. In log-odds a claim
  many sources hold is held more firmly than one a few hold, and it takes as much contrary evidence to
  overturn. **Nothing becomes irrefutable:** however far the log-odds go, evidence the other way moves them
  back by the same steps. There is no cap and no clamp, and the earlier `[1e-6, 1-1e-6]` clamp is gone.

- **`BayesianBelief.hold(log_odds)`** — **the only way a belief's strength is set.** It assigns the
  log-odds; `posterior_probability` and `entropy` are then *read from* them, never kept instead of them. A
  reader who wants a probability calls `probability_of`.
- **`_EvidenceIndex`** — what reading a belief's evidence whole worked out, **kept rather than
  recounted**: each witness's latest word, how many witnesses stand each way, and how many uses the
  supporting observations witnessed. Each entry is read once, because entries are only ever added. It
  exists because the counts were previously re-derived by reading every entry on every observation: a
  frame taught by 16,000 sentences read 16,000 entries before accepting the next one, so **teaching slowed
  in proportion to everything already taught**. The index is rebuilt only when the lists it was made for
  are not the ones it holds, or are shorter than what it has read, which a merge or a load can cause.
- **A belief must name the memory it is about.** `BayesianBelief.memory_id` is defaulted so every existing
  construction site still builds, and persistence **refuses** to store a belief that names no memory. The
  refusal is at the point of storage, where it is visible, rather than as an import-time error.
- **`_calculate_entropy(probability)`** — Shannon binary entropy; 0 at p∈{0,1}.
- **`_apply_temporal_decay(belief)`** — drifts toward 0.5 with elapsed time (`λ`, `decay=1-exp(-λΔt)`); read-only (caller assigns).
- **`_update_domain_volatility(domain, belief_change, is_reversal=False)`** — adapts λ per domain: rolling window + regime penalty, clamp `[0.005, 0.1]`.
- **`_adjust_evidence_with_domain_support(belief, evidence, base_weight)`** — cross-domain consensus (scientific/mathematical/technical) boosts weight ×1.15.

#### Retrieval / interpretation
- **`get_belief(belief_id)`** — id lookup or None (completion reads its posterior).
- **`belief_for_claim(claim)`** — the belief `observe_claim` moves for that normalised claim, via `_claim_ids` (was a scan over all 198k beliefs, 40 ms per call, returning a different duplicate than observation moved; used by completion SAW).
- **`beliefs_for_domain(domain, limit=8)`** — `[{belief_id, claim, posterior, updated_at}]` most-recent first, from `_domain_ids` (was a 19 ms scan per memory store; stamps a memory with pertinent beliefs).
- **`get_belief_uncertainty(belief_id)`** — full uncertainty snapshot + human interpretation.
- **`_interpret_uncertainty(belief)`** — renders posterior+entropy to English.

#### Belief graph & constraint propagation
- **`add_relationship(source, target, relation_type, strength=1.0, confidence=1.0, discovered_by="system")`** — creates a `BeliefRelationship`, adds edges, and **immediately activates** (fires `propagate_constraints` if the source deviates >0.05 from 0.5).
- **`propagate_constraints(changed_belief_id, probability_delta, max_depth=5, visited=None)`** — recursive coherence: per forward edge, `effect = _compute_propagation_effect`, nudge the target posterior, recompute entropy, recurse. "When A changes, dependents update."
- **`_compute_propagation_effect(relation_type, delta, strength, confidence)`** — posterior-transfer math: IMPLIES +0.8·base, CONTRADICTS −0.9·base, SUPPORTS +0.4, WEAKENS −0.4, REQUIRES (only on large drop) 0.7, MUTUALLY_EXCLUSIVE −0.95.
- **`check_consistency()`** — read-only global audit: implication/contradiction/mutual-exclusivity violations. (Distinct from the async mutating `check_belief_consistency`.)

#### Persistence (Postgres)
- **`_init_database`** — no-op (Postgres).
- **`async _write_belief_row(belief, *, commit=True) -> bool`** — the single canonical writer; DB-not-ready → buffer + `persistence_drops`; else upsert into `unified.beliefs` writing both current epistemic columns AND the legacy NOT-NULL `belief_text`/`confidence`.
- **`_save_belief(belief)`** — fire-and-forget for sync callers: buffers to `_pending_writes` AND schedules a tracked `_write_tasks` task (done-callback clears the buffer only on success); no loop → buffer only.
- **`async drain_writes() -> int`** — shutdown barrier: `gather` `_write_tasks` then `flush_pending_writes()`; called before the pool closes.
- **`async flush_pending_writes() -> int`** — replays the DB-down backlog once the DB is up.
- **`async flush_belief(belief_id) -> bool`** — synchronous committed durable write for decision-critical beliefs (competence, completion).
- **`async _delete_belief_row(belief_id) -> bool`** — deletes a row (so a decayed-out belief isn't resurrected by load).
- **`_VOLATILITY_DDL` / `async _ensure_volatility_table`** (2011/1349) · **`async save_domain_volatility() -> int`** (persists per-domain λ) · **`async _load_domain_volatility() -> int`**.
- **`async decay_belief(belief_id)`** — decays ONE belief without new evidence (escape from ossification); clock = `last_updated` so repeated calls apply only the increment; durably flushes on a real move.
- **`_save_known_unknown`** · **`_save_calibration_data`** — fire-and-forget upserts.
- **`async load_from_db()`** — startup hydration: rebuild `beliefs` and both indexes, then `_load_domain_volatility` + `flush_pending_writes`.
- **`get_statistics()`** — `stats` + `active_beliefs`, `persistence_drops`, `persistence_healthy`, known-unknowns, calibrated domains, overconfidence rate.

#### Maintenance (reflection-loop, async — each guarded by `raise_if_structural`)
- **`async apply_temporal_decay_to_all_beliefs() -> Dict`** — decays idle (>1h) beliefs; drops a belief in `[0.45,0.55]` with `<3` evidence (deletes row); else durably writes. Returns `beliefs_decayed`, `avg_decay_amount`, `beliefs_removed` (the *actual* delete count).
- **`async check_belief_consistency() -> Dict`** — mutating repair: CONTRADICTS both >0.7 → weaken the weaker ×0.9; IMPLIES A>0.7 & B<0.3 → boost B. Returns violations/propagated/checked.
- **`async update_domain_volatility_metrics() -> Dict`** — recomputes λ per domain + persists; `avg_volatility` is `None` on failure (never a fabricated 0.01).

#### Known-unknowns / calibration / deferral
- **`register_known_unknown(question, domain, blocking_factors=None, required_info=None)`** · **`_estimate_information_value`** · **`_suggest_resolution_strategy`** · **`get_high_value_unknowns(min_value=0.7)`** · **`resolve_known_unknown(unknown_id, resolution)`** (flips to KNOWN + mints a belief) · **`record_prediction(domain, predicted_confidence, actual_outcome)`** · **`_update_calibration_metrics`** (Brier + calibration error) · **`get_calibrated_confidence(domain, raw_confidence)`** · **`should_defer_to_expert(domain, confidence, entropy)`**.
- **Module:** `get_uncertainty_system()` · `get_bayesian_uncertainty()`.

### 4. Feeds / feeds-into — the circulation hub

Everything reaches the belief store through `get_uncertainty_system()`, **46 call sites across the
substrate**, and the single largest caller is the learning authority with 27 of them.

**FEEDERS, evidence in:**

| Caller | How it feeds | Sites |
|---|---|---|
| `unified_learning_system.py` | The façade every taught claim passes through: `observe_claim` (13), `create_belief` (2), `update_belief` (2), `flush_belief` (4) | the primary feeder |
| `epistemic_engine.py` | `create_belief` (5), `update_belief` (1), `add_relationship` (2) | the main structured writer |
| `universal_domain_master.py` | `create_belief`, `update_belief`, `flush_belief` (3), `decay_belief`, `register_known_unknown` | competence beliefs |
| `hierarchical_abstraction.py` | `create_belief`, `add_relationship` | abstraction |
| `hypothesis_testing.py` | `observe_claim` | tested hypotheses |
| `memory_agent.py` | `observe_claim` | what a memory asserts |
| `scoped_context_store.py` | `observe_claim` | a person's own scope |
| `autonomous_coordinator.py` | `register_known_unknown` | what it found it did not know |
| `intrinsic_motivation.py` | `register_known_unknown` | what it is curious about |

**The coordinator does not write beliefs.** Completion is a belief held on the task
(`completion_log_odds`), and the coordinator reaches the store only to **read**: `belief_for_claim`, four
sites.

**CONSUMERS, posteriors out:**

| Caller | How it reads | Sites |
|---|---|---|
| `unified_learning_system.py` | `belief_for_claim` (13), `beliefs_for_domain` (2), `get_belief` (2) | every learning decision |
| `autonomous_coordinator.py` | `belief_for_claim` (4) | completion and the self's own state |
| `derived_reader.py` | `belief_for_claim` (2) | what a reading may rely on |
| `capabilities.py` | `belief_for_claim` | whether a capability is held |
| `memory_agent.py` | `beliefs_for_domain` | stamps a memory with the beliefs pertinent to it |
| `neural_bridge.py` | reads posteriors; drives the three maintenance passes from the reflection loop | reasoning |
| `main.py` | `load_from_db` at boot, `drain_writes` at shutdown | lifecycle |

The reader is a consumer: what a reading may rely on is a question asked of the belief store rather than
of the reader itself.

Because feeders and consumers touch the *same* posteriors through the *same* singleton, a fact taught once
is instantly visible to every completion check, memory and reasoning pass. That is the circulatory system,
and it is why the representation in §3 matters: a clamped posterior flattened every well-witnessed claim to
the same value everywhere at once.
