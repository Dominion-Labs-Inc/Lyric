# Memory — `MemoryAgent`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authority changes. Line numbers drift; the explanations must stay true.*

## `MemoryAgent` — the memory authority

*`core/agents/memory_agent.py` (~3,999 lines). Utilities live in `core/memory/`; the class lives in `core/agents/`.*

### 1. Purpose
The **single memory authority**: owns storage, the worthiness filter (what is kept), type inference (what KIND each record is), all query/recall, and consolidation. Coordinates a hot tier (Postgres `memory_hot`, 0–60d), a cold tier (`memory_cold`, 60+d), and a pgvector index (`all-MiniLM-L6-v2`, 384-dim). Abstraction and beliefs are NOT owned here — that's *reasoning*, delegated to `NeuralSymbolicBridge` (197-207, 3762-3767).
- **One entry:** `get_memory_agent()` (3945) — async, returns a *ready* singleton (raises if backends won't connect); callers must `await` it, never construct `MemoryAgent()` directly. `initialize_memory_agent()` (3986) is a legacy alias.
- **Aliases:** `MemoryManager = CentralizedMemoryManager = UnifiedMemorySystem = MemoryAgent` (memory/__init__.py). Same class, legacy names.
- **Principle:** callers pass raw content; the agent decides **worthiness** and **TYPE** itself. Pre-generating worthiness (408-410) or pre-deciding type is deprecated/discouraged.

### 2. State (`__init__`, 79-147)
`postgres_storage` (one backend, both tiers), `embedding_service` (384-dim; absent degrades search, never fails a store), `memory_cache`/`cache_enabled`, `initialized`, loop flags (`maintenance`/`abstraction`/`reflection`_loop_active — only maintenance is a timer), `abstraction_pipeline`/`bayesian_beliefs` left None (owned by reasoning), `abstraction_state` (watermark bookkeeping), `_abstraction_running`/`_new_episodic_since_abstraction`/`_abstraction_trigger_scheduled` (event-trigger state), `metrics` counters, `_write_queue` + `_pending_memories` + `_queue_worker_task` (non-blocking writes visible to the injector), `filter_metrics`.

### 3. Methods by area

#### Lifecycle
- **`async initialize() -> bool`** (149) — idempotent; connects Postgres (hard-fails if absent), loads embeddings, leaves belief/abstraction None; under `TORIN_SHADOW_MODE` suppresses loops+queue worker (storage still live); else starts `start_memory_loops()` + `_write_queue_worker`.
- **`async get_memory_agent()`** (module, 3945) — the accessor; returns the ready singleton under a lock (old contract returned an uninitialised agent).
- **`async initialize_memory_agent()`** (module, 3986) — alias.
- **`__del__`** (3918, the winning def) — clears cache, guards interpreter teardown.

#### Store path
- **`enqueue_memory(content, memory_type=None, importance_score=0.5, confidence_score=1.0, tags=None, source_context=None, **kw) -> str`** (240) — **non-blocking** store; queues + records in `_pending_memories`; returns a provisional `pending_<hex>` id immediately.
- **`async _write_queue_worker()`** (280) — drains `_write_queue` via `store_memory`; removes from `_pending_memories` on completion; survives per-item errors.
- **`_readable_claim(content, source_context)`** (319) — extracts the substrate-readable CLAIM a memory asserts (from `conclusion` else `content`), strips reasoning-status prefixes, keeps only if `SentenceReader` parses it; returns claim + `ClaimShape` (polarity+tense).
- **`@profile_performance async store_memory(content, memory_type=None, importance_score=0.5, confidence_score=1.0, tags=None, source_context=None, embedding_metadata=None, related_memories=None, decay_rate=None, access_count=0, session_id=None, user_id=None, reasoning_trace=None, thinking_state=None, system_state=None, decision_factors=None, emotional_context=None, image=None, image_meta=None) -> Tuple[bool, Optional[str]]`** (376-911) — **the primary write authority.** (0) auto-init; (1) generate `MemoryWorthinessMetadata` itself; (2) worthiness filter (`get_memory_filter().evaluate`) with an event-class **exemption** (`exemption_for`) for records-that-matter-because-they-happened; (3) reject → `(False, None)`; (4) accept → write a `memory_admission` record, stamp a `belief_state` snapshot (per-domain `relevant_beliefs` via `beliefs_for_domain`, an index read) + an appraisal snapshot (from the live `AppraisalSystem`); (5) **dedup** — merge near-duplicate KNOWLEDGE (≥0.75) but NEVER observations/events; (6) mint `mem_<hex>`, **infer type** if absent, stamp readable claim + shape tags, embed (absent embedding still stores), persist to hot, retain image, `note_episodic_stored()`. Returns `(success, memory_id)`.
- **`async _retain_image(memory_id, image, image_meta)`** (913) — attaches image bytes via the media store; isolated; called on new-store and merge paths.
- **`async get_memory_images(memory_id) -> List[Dict]`** (927) — bytes/mime/dimensions/perceived structure of attached images.
- **`async capture_task_outcome(task, *, result=None, success=True, confidence=1.0) -> Optional[str]`** (934) — composes up to TWO durable artifacts from a completed task: a SEMANTIC record (what was learned) + a PROCEDURAL record (the tool sequence). Model-free; each skipped honestly if empty.
- **`async store_batch(memories: List[MemoryItem]) -> Tuple[bool, int]`** (1063) — batch store of built items with batch embeddings; bypasses per-item worthiness/dedup.
- **`async _generate_worthiness_metadata(content, confidence_score, tags, source_context, reasoning_trace, importance_score=0.5) -> MemoryWorthinessMetadata`** (1103) — **decides worthiness from raw data**: cognition/novelty/criticality/query/outcome/temporal/justification from content heuristics + signals — never from trace *length*. `from_principal` forces HIGH consequence + SYNTHESIS; `importance_score` → `consequence_level`.
- **`_infer_memory_type(worthiness_metadata, source_context) -> MemoryType`** (1391) — **decides TYPE**: error→EPISODIC; procedural/meta tags→PROCEDURAL/META; successful lookup or reusable new knowledge→SEMANTIC; source-system patterns (`neural_bridge`/`autonomous_coordinator`/`hypothesis_testing`→EPISODIC, `continuous_learning`→PROCEDURAL); default EPISODIC.
- **`async bulk_import(memories, memory_type=None, generate_embeddings=True, tier="hot", batch_size=100) -> Tuple[bool, int]`** (1852) — migration path; bypasses worthiness/dedup.
- **Dedup/consolidation helpers:** `async _find_similar_memories(content, similarity_threshold=0.85, tags=None, memory_type=None, limit=5)` (1481); `async _merge_memory_content(existing, new_content, new_metadata)` (1538, **deterministic no-LLM** sentence-level merge — appends novel sentences, max importance, avg confidence, union tags, `access_count=1` increment, re-embed); `async _cluster_by_similarity(memories, similarity_threshold=0.85)` (1659, greedy cosine clustering); `async _consolidate_cluster(cluster)` (1786, merge into most-important base, soft-delete rest).

#### Retrieve / query
- **`async retrieve_memory(memory_id, update_access=True, tier_hint=None)`** (1940) — cache→hot→cold; increments access; caches hot.
- **`async get_recent_memories(limit=10, memory_types=None, min_importance=None, tags=None)`** (2011) — recent hot within 7-day window.
- **`RETRIEVAL_STRATEGIES = ("semantic","keyword","tags")`** (2063).
- **`async retrieve(query=None, *, tags=None, memory_types=None, strategies=None, limit=10, min_similarity=0.5, min_importance=None, deduplicate=True, include_events=True, relative_to_best=None, require_named_match=False)`** (2065) — **the single recall authority.** Runs applicable strategies concurrently, merges by id, ranks relevance-first (similarity→corroboration→importance); a failing strategy is skipped, not emptying. `include_events=False` withholds events; `require_named_match` drops off-entity memories; `relative_to_best` self-calibrates the cutoff.
- **`@profile_performance async search_memories(...)`** (2320) — compatibility shim over `retrieve()`; legacy `(query=/limit=)` returns `(bool, list)`, new returns a bare list (a known deliberately-unmerged return-type fork).
- **`async query_by_tags(tags, memory_types=None, limit=100) -> Tuple[bool, List]`** (2385) — structural tag query, no time filter (the exact-count path for events).
- **`async get_memory_by_content(content, exact_match=False, limit=10)`** (2417) — fuzzy or exact content lookup.
- **`@staticmethod claim_tags(content)`** (2470) — polarity/tense as exact-comparable tags (what the embedding cannot carry).
- **`async find_open(about, limit=5)`** (2487) — still-open episodes (tagged `open`) semantically related to `about`.

#### Update / supersede / close / delete
- **`async supersede(memory_id, content, add_tags=None, drop_tags=None, because="")`** (2495) — REPLACES what a memory says (preserving prior under `metadata.superseded`).
- **`async close_open(about, content, because="resolved")`** (2539) — finds an open episode about `about` and supersedes it (adds `resolved`, drops `open`).
- **`async update_memory(memory_id, updates, capability_token="", tier=None)`** (2555) — generic update; protected fields (importance/confidence/type) need a token.
- **`async increment_access_count(memory_id, tier, increment=1)`** (2596).
- **`async update_importance(memory_id, new_importance, capability_token, tier, reason, tier_hint=None)`** (2626) — token-gated + audit note.
- **`async update_tags(memory_id, tags, capability_token="", tier="hot", operation="replace")`** (2665).
- **`async add_related_memory(memory_id, related_id, tier, relationship_type)`** (2701).
- **`async update_metadata(memory_id, metadata_updates, capability_token="", merge=True, tier="hot", tier_hint=None)`** (2731).
- **`async delete_memory(memory_id, capability_token, reason="", tier_hint=None)`** (2771) — governance-protected soft delete.
- **`async permanent_delete(memory_id, capability_token, confirmation=False)`** (2818) — irreversible; token AND `confirmation=True`.

#### Tiering
- **`async migrate_to_cold_tier(memory_id, force=False, tier_hint=None)`** (2870) · **`async retrieve_from_archive(memory_id, restore_to_hot=False)`** (2910) · **`async consolidate_old_duplicates(days_back=30, batch_size=100, similarity_threshold=0.85)`** (2951).

#### Maintenance / consolidation / abstraction
- **`async start_memory_loops`** (3572) / **`async stop_memory_loops`** (3592) — only maintenance is a timer; abstraction/reflection are event-triggered.
- **`async _maintenance_loop`** (3605) — hourly `consolidate_memories()`.
- **`async consolidate_memories`** (3689) — clean low-importance expired rows (imp<0.2, age>180d) BEFORE migrating 60+d survivors hot→cold, then temporal decay.
- **`note_episodic_stored(n=1)`** (3644) — write-path hook; past `ABSTRACTION_MIN_NEW_MEMORIES` (15) schedules (never runs inline) `_run_abstraction_then_reflect`.
- **`async _run_abstraction_then_reflect`** (3666) — resets counter, `form_abstractions_if_due()`, and only if schemas formed → `reflect_on_beliefs()`.
- **`_reasoning_authority`** (3762) — lazy `NeuralSymbolicBridge` (owner of abstraction+belief).
- **`async form_abstractions`** (3769) — shim → `form_abstractions_if_due(force=True)`.
- **`async form_abstractions_if_due(force=False)`** (3782) — admission gate for abstraction: checks authority, not-running, cooldown, watermark, ≥threshold new memories, then ASKS `bridge.abstract_over_memories(batch)`; advances watermark; report names *why* it declined. Deliberately off the write path.
- **`async reflect_on_beliefs`** (3911) — asks `bridge.reflect()` (belief-graph hygiene).

#### Governance (capability-token-protected deletes)
- **`async _validate_capability_token(token)`** — validates `gov_`/`cap_`/`admin_` tokens vs `capability_tokens` (active/unexpired; honours `emergency_override`).
- **`async validate_governance_compliance(operation, parameters=None)`** (routes to `safety_framework.evaluate_action`; honest "not evaluated" if unavailable) · **`async get_governance_status`**.
- No parameter self-modification: the `modify_importance_threshold` / `modify_decay_rates` / `modify_tier_thresholds` / `modify_embedding_config` setters were removed 2026-09-15 (no callers; the substrate improves only by learning).

#### Metrics / cache
- **`get_metrics`** (3043) · **`async cleanup_cache(max_age_hours=24)`** (3057).

### 4. Feeds / feeds-into
**Called by:** cognitive ingress `_remember` (cognitive_ingress.py:417-453, `store_memory(..., SEMANTIC, 0.75)`, NOT an event); learning; coordinator + intrinsic_motivation (rich writes + `capture_task_outcome`); reasoning (`neural_bridge`, `hypothesis_testing`), cross-domain reasoner; recall surfaces (`live_recall`, `memory_injector` reads `_pending_memories`); health/tools/chaos/security.
**Reads/delegates to:** beliefs (`beliefs_for_domain` to stamp `belief_state`); appraisal (`get_appraisal_system().current_state`); reasoning authority (`abstract_over_memories`/`reflect`); worthiness filter (`memory_filter`); storage/embeddings/media/queue; semantics (`claim_shape`, `sentence_reader`); governance/safety (`capability_tokens`, `safety_framework`).
