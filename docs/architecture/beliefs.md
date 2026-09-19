# Beliefs — `BayesianUncertaintySystem`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authority changes. Line numbers drift; the explanations must stay true.*

## `BayesianUncertaintySystem` — the belief authority (the circulatory system)

*`core/reasoning/bayesian_uncertainty.py` (~1851 lines). Class at 165.*

### 1. Purpose
The substrate's **single belief store** — every graded, revisable, provenance-aware proposition. Not a boolean fact table: each belief is a Bayesian posterior with prior, likelihood, evidence lists, entropy, credible interval, and a temporal-decay clock. **Revisable** (asserted today, moved/reversed tomorrow) and **provenance-aware** (evidence carries `quality`+`source`). Its defining door is **find-or-create-by-claim** (`observe_claim`, 298): normalise → O(1) index lookup → mint or move the *same* belief, so "I was told X" is idempotent. It is the **circulation hub**: learning/reasoning/hypothesis-testing/domain/epistemic pump evidence IN; completion/memory/motivation/health read posteriors OUT. Singleton `get_uncertainty_system` (1838; alias `get_bayesian_uncertainty` 1849).

### 2. State (`__init__`, 176)
`unified_db` (Postgres), `beliefs: Dict[id, BayesianBelief]` (181), **`_claim_ids: Dict[claim_key, List[id]]`** + **`_domain_ids: Dict[domain_key, Set[id]]`** (the indexes every read by claim or domain uses; kept exact by `_register_belief` / `_unregister_belief`, the only writers of `beliefs`. The LAST id for a claim is the belief `observe_claim` moves and `belief_for_claim` returns — 1,902 claims are held by more than one belief, and a scan returned the first while observation moved the last), `persistence_drops` (190, surfaced in stats), `_pending_writes` (197, DB-down buffer, upsert+replay), `_write_tasks` (203, tracked fire-and-forget writes for the shutdown drain), `known_unknowns` (206), `calibrations` (209), `domain_volatility` (212, per-domain λ default 0.01), `domain_belief_changes` (213, last-50 window), `domain_regime_shifts` (214), `relationships` (217, CONTRADICTS/SUPPORTS/IMPLIES/WEAKENS/REQUIRES/MUTUALLY_EXCLUSIVE graph), `forward_edges`/`backward_edges` (218-219), `propagation_queue` (220), `stats` (223).
*Dataclasses:* `BayesianBelief` (86; prior/likelihood/posterior, evidence_for/against, entropy, credible_interval, decay_rate, update_count, confidence_history), `BeliefRelationship` (55, `reverse_relation()` 69), `KnownUnknown` (119), `ConfidenceCalibration` (145). Enums `UncertaintyType` (29), `KnowledgeState` (37), `RelationType` (45).

### 3. Methods by area

#### Creation / observation
- **`create_belief(claim, domain, prior=0.5, evidence=None) -> BayesianBelief`** (248) — mints `belief_<uuid>`, `posterior=prior`, registers through `_register_belief` *before* applying initial evidence (else `update_belief` raises). Mints a new id every call → not idempotent by claim.
- **`_claim_key(claim)`** (static, 293) — `" ".join(claim.strip().lower().split())`; every index op keys on this, so case/spacing never fork a belief.
- **`observe_claim(claim, domain="language", *, supports=True, quality=0.9, source="taught")`** (298) — **the find-or-create-by-claim door.** Key → index; stale entry treated as new. Absent → `create_belief(prior = quality if supports else 1-quality)`. Present → `update_belief(existing, evidence, evidence_supports=supports)`. The idempotent "record I was told this" entry.
- **`update_belief(belief_id, evidence, evidence_supports=True)`** (321) — the core Bayesian update in 5 steps: (1) **temporal decay first** (346, so early conclusions aren't gravity wells); (2) append evidence + read `evidence_weight`, adjust via `_adjust_evidence_with_domain_support`; (3) **odds-form update** (369, `_LR_STRENGTH=3.0`): support `lr=exp(+3w)`, contradict `lr=exp(-3w)`, `posterior = prior_odds·lr / (1+prior_odds·lr)` — weight 0→no move, 1.0→≈20× or 0.05×, symmetric/bounded; (4) **reversal detection** (395, crossing 0.5); (5) volatility update, clamp to `[1e-6, 1-1e-6]`, recompute entropy/credible-interval, persist; if `|Δposterior|>0.05` → `propagate_constraints(...)`.
- **`_calculate_entropy(probability)`** (452) — Shannon binary entropy; 0 at p∈{0,1}.
- **`_apply_temporal_decay(belief)`** (459) — drifts toward 0.5 with elapsed time (`λ`, `decay=1-exp(-λΔt)`); read-only (caller assigns).
- **`_update_domain_volatility(domain, belief_change, is_reversal=False)`** (494) — adapts λ per domain: rolling window + regime penalty, clamp `[0.005, 0.1]`.
- **`_adjust_evidence_with_domain_support(belief, evidence, base_weight)`** (1803) — cross-domain consensus (scientific/mathematical/technical) boosts weight ×1.15.

#### Retrieval / interpretation
- **`get_belief(belief_id)`** (804) — id lookup or None (completion reads its posterior).
- **`belief_for_claim(claim)`** — the belief `observe_claim` moves for that normalised claim, via `_claim_ids` (was a scan over all 198k beliefs, 40 ms per call, returning a different duplicate than observation moved; used by completion SAW).
- **`beliefs_for_domain(domain, limit=8)`** — `[{belief_id, claim, posterior, updated_at}]` most-recent first, from `_domain_ids` (was a 19 ms scan per memory store; stamps a memory with pertinent beliefs).
- **`get_belief_uncertainty(belief_id)`** (838) — full uncertainty snapshot + human interpretation.
- **`_interpret_uncertainty(belief)`** (857) — renders posterior+entropy to English.

#### Belief graph & constraint propagation
- **`add_relationship(source, target, relation_type, strength=1.0, confidence=1.0, discovered_by="system")`** (535) — creates a `BeliefRelationship`, adds edges, and **immediately activates** (fires `propagate_constraints` if the source deviates >0.05 from 0.5).
- **`propagate_constraints(changed_belief_id, probability_delta, max_depth=5, visited=None)`** (600) — recursive coherence: per forward edge, `effect = _compute_propagation_effect`, nudge the target posterior, recompute entropy, recurse. "When A changes, dependents update."
- **`_compute_propagation_effect(relation_type, delta, strength, confidence)`** (681) — posterior-transfer math: IMPLIES +0.8·base, CONTRADICTS −0.9·base, SUPPORTS +0.4, WEAKENS −0.4, REQUIRES (only on large drop) 0.7, MUTUALLY_EXCLUSIVE −0.95.
- **`check_consistency()`** (723) — read-only global audit: implication/contradiction/mutual-exclusivity violations. (Distinct from the async mutating `check_belief_consistency`.)

#### Persistence (Postgres)
- **`_init_database`** (240) — no-op (Postgres).
- **`async _write_belief_row(belief, *, commit=True) -> bool`** (1178) — the single canonical writer; DB-not-ready → buffer + `persistence_drops`; else upsert into `unified.beliefs` writing both current epistemic columns AND the legacy NOT-NULL `belief_text`/`confidence`.
- **`_save_belief(belief)`** (1251) — fire-and-forget for sync callers: buffers to `_pending_writes` AND schedules a tracked `_write_tasks` task (done-callback clears the buffer only on success); no loop → buffer only.
- **`async drain_writes() -> int`** (1279) — shutdown barrier: `gather` `_write_tasks` then `flush_pending_writes()`; called before the pool closes.
- **`async flush_pending_writes() -> int`** (1291) — replays the DB-down backlog once the DB is up.
- **`async flush_belief(belief_id) -> bool`** (1310) — synchronous committed durable write for decision-critical beliefs (competence, completion).
- **`async _delete_belief_row(belief_id) -> bool`** (1324) — deletes a row (so a decayed-out belief isn't resurrected by load).
- **`_VOLATILITY_DDL` / `async _ensure_volatility_table`** (1341/1349) · **`async save_domain_volatility() -> int`** (1357, persists per-domain λ) · **`async _load_domain_volatility() -> int`** (1378).
- **`async decay_belief(belief_id)`** (1393) — decays ONE belief without new evidence (escape from ossification); clock = `last_updated` so repeated calls apply only the increment; durably flushes on a real move.
- **`_save_known_unknown`** (1431) · **`_save_calibration_data`** (1484) — fire-and-forget upserts.
- **`async load_from_db()`** (1524) — startup hydration: rebuild `beliefs` and both indexes, then `_load_domain_volatility` + `flush_pending_writes`.
- **`get_statistics()`** (1573) — `stats` + `active_beliefs`, `persistence_drops`, `persistence_healthy`, known-unknowns, calibrated domains, overconfidence rate.

#### Maintenance (reflection-loop, async — each guarded by `raise_if_structural`)
- **`async apply_temporal_decay_to_all_beliefs() -> Dict`** (1589) — decays idle (>1h) beliefs; drops a belief in `[0.45,0.55]` with `<3` evidence (deletes row); else durably writes. Returns `beliefs_decayed`, `avg_decay_amount`, `beliefs_removed` (the *actual* delete count).
- **`async check_belief_consistency() -> Dict`** (1668) — mutating repair: CONTRADICTS both >0.7 → weaken the weaker ×0.9; IMPLIES A>0.7 & B<0.3 → boost B. Returns violations/propagated/checked.
- **`async update_domain_volatility_metrics() -> Dict`** (1752) — recomputes λ per domain + persists; `avg_volatility` is `None` on failure (never a fabricated 0.01).

#### Known-unknowns / calibration / deferral
- **`register_known_unknown(question, domain, blocking_factors=None, required_info=None)`** (890) · **`_estimate_information_value`** (928) · **`_suggest_resolution_strategy`** (946) · **`get_high_value_unknowns(min_value=0.7)`** (970) · **`resolve_known_unknown(unknown_id, resolution)`** (977, flips to KNOWN + mints a belief) · **`record_prediction(domain, predicted_confidence, actual_outcome)`** (1016) · **`_update_calibration_metrics`** (1055, Brier + calibration error) · **`get_calibrated_confidence(domain, raw_confidence)`** (1090) · **`should_defer_to_expert(domain, confidence, entropy)`** (1114).
- **Module:** `get_uncertainty_system()` (1838) · `get_bayesian_uncertainty()` (1849).

### 4. Feeds / feeds-into — the circulation hub
**FEEDERS (evidence IN)** — via the learning façade (`unified_learning_system.py:2577-2652`, which forwards create/update/observe to `get_uncertainty_system()`): learning/teaching (`observe_claim`, the primary feeder; `unified_learning_system.py:1198,2739`; teach scripts); **epistemic engine** (`epistemic_engine.py:246/250/300/306/346` create, 323 update, 351 add_relationship — the main structured writer); domain master (666 create, 705 update, 670/711 flush, 728 decay, 1791 known-unknown — competence beliefs); coordinator (7721 create, 7774 update, 7788 flush, 4542 known-unknown — completion beliefs); hypothesis testing (294/764); abstract reasoning (1869/1878); hierarchical abstraction (1197 create, 1528 add_relationship).
**CONSUMERS (posteriors OUT):** completion/SAW (coordinator 7894/7960 `belief_for_claim`, 7922 `get_belief`); memory formation (memory_agent.py:669 `beliefs_for_domain`); intrinsic motivation; reasoning engines (`abstract_reasoning`, `hierarchical_abstraction`, `neural_bridge`, `epistemic_engine` read `posterior_probability`); health monitor (`get_statistics`); iteration controller; lifecycle (`main.py` `load_from_db` at boot, `drain_writes`+`save_domain_volatility` at shutdown; `neural_bridge` reflection loop drives the three maintenance passes). Because feeders and consumers touch the *same* posteriors through the *same* singleton, a fact taught once is instantly visible to every completion check, memory, and reasoning pass — the circulatory system.
