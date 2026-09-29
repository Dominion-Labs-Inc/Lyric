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
- **`@profile_performance async store_memory(content, memory_type=None, importance_score=0.5, confidence_score=1.0, tags=None, source_context=None, embedding_metadata=None, related_memories=None, decay_rate=None, access_count=0, session_id=None, user_id=None, reasoning_trace=None, thinking_state=None, system_state=None, decision_factors=None, emotional_context=None, media=None, media_meta=None) -> Tuple[bool, Optional[str]]`** (376-911) — **the primary write authority.** (0) auto-init; (1) generate `MemoryWorthinessMetadata` itself; (2) worthiness filter (`get_memory_filter().evaluate`) with an event-class **exemption** (`exemption_for`) for records-that-matter-because-they-happened; (3) reject → `(False, None)`; (4) accept → write a `memory_admission` record, stamp a `belief_state` snapshot (per-domain `relevant_beliefs` via `beliefs_for_domain`, an index read) + an appraisal snapshot (from the live `AppraisalSystem`); (5) **no merge** — a memory is never folded into another, however alike they read (the merge by likeness was removed 2026-09-28: the substrate doing the same thing on two days is two memories, and merging wiped one; what repeats within one pursuit is summarized inside that pursuit's memory, and what overlaps between memories is recall's to bring together); (6) mint `mem_<hex>`, **infer type** if absent, stamp readable claim + shape tags, embed (absent embedding still stores), persist to hot, retain media, `note_episodic_stored()`. Returns `(success, memory_id)`. Attached `media` (a picture or a sound) marks the memory `has_image`/`has_video`/`has_sound` by what its bytes are, and stamps `met` = the sha256 of those bytes: the identity of the thing met.
- **`async _retain_media(memory_id, media, media_meta, owner)`** — attaches a picture's or a sound's bytes via the media store (`MediaStore.store_media`, mime read off the bytes); isolated; called on new-store and merge paths. A sound trace's landmarks go with it (`landmarks=`), stored as their distinct hashes, so the sound can be found by the sound.
- **Media is kept per memory.** A media row's id is the memory's and the content's together. Keyed by content alone, the same recording heard twice MOVED its row to the second memory, and the first could no longer be heard again (fixed 2026-09-29, MEMORY-SOUND-01).
- **`async add_perception_to_pursuit(memory_id, part, *, media=None, media_meta=None, tags=None) -> str`** — a seeing or a hearing within a pursuit is a PART of that pursuit's memory: added to its experience (repeats counted), its trace or picture kept as that memory's media, its tags (a lesson's) added. Returns the pursuit memory's id, which the perception's claims then name. `pursuit_account` says it: "I heard …", "I saw …".
- **`async get_memory_media(memory_id) -> List[Dict]`** — bytes/mime/dimensions/perceived structure of what the memory kept.
- What a percept memory keeps: a picture's bytes and its gist; a sound's TRACE (`application/x-npz`, recognised from its bytes by `media_store.mime_of`), never the recording. The coordinator's `recollect` rebuilds either from what was kept.
- **A lesson taught by hearing is a hearing memory like any other.** A word, a voice or a song is taught by hearing an example (`coord.learn_word` / `learn_voice` / `learn_song`); the hearing is remembered as every hearing is (EPISODIC, trace kept, never the recording), tagged `SPOKEN_WORD_TAG`/`VOICE_TAG`/`SONG_TAG` with the word, person or song in its record, and its trace archive keeps the example measured for matching (`example`: a word's measurements, a voice's voiced frames, a song's landmarks). **`async taught_by_hearing(tag, key)`** is the view the perception faculty reads lessons back through (word, person or song -> the archives), capped by the named `TAUGHT_BY_HEARING_LIMIT`; there is no store beside memory.
- **`async capture_task_outcome(task, *, result=None, success=True, confidence=1.0) -> Optional[str]`** (934) — composes up to TWO durable artifacts from a completed task: a SEMANTIC record (what was learned) + a PROCEDURAL record (the tool sequence). Model-free; each skipped honestly if empty.
- **`async store_batch(memories: List[MemoryItem]) -> Tuple[bool, int]`** (1063) — batch store of built items with batch embeddings; bypasses per-item worthiness.
- **`async _generate_worthiness_metadata(content, confidence_score, tags, source_context, reasoning_trace, importance_score=0.5) -> MemoryWorthinessMetadata`** (1103) — **decides worthiness from raw data**: cognition/novelty/criticality/query/outcome/temporal/justification from content heuristics + signals — never from trace *length*. `from_principal` forces HIGH consequence + SYNTHESIS; `importance_score` → `consequence_level`.
- **`_infer_memory_type(worthiness_metadata, source_context) -> MemoryType`** (1391) — **decides TYPE**: error→EPISODIC; procedural/meta tags→PROCEDURAL/META; successful lookup or reusable new knowledge→SEMANTIC; source-system patterns (`neural_bridge`/`autonomous_coordinator`/`hypothesis_testing`→EPISODIC, `continuous_learning`→PROCEDURAL); default EPISODIC.
- **`async bulk_import(memories, memory_type=None, generate_embeddings=True, tier="hot", batch_size=100) -> Tuple[bool, int]`** (1852) — migration path; bypasses worthiness.
- **Merging, removed 2026-09-28.** `_find_similar_memories`, `_could_be_the_same_claim`, `_merge_memory_content`, `_cluster_by_similarity`, `_consolidate_cluster` and `consolidate_old_duplicates` are gone. Nothing merges memories.

#### Word classes — memory IS the vocabulary

There is no lexicon. What class a word has is knowledge the substrate holds like
any other, so it is a memory, and a wipe takes the vocabulary with it.

- **`WORD_CLASS_TAG = "word_class"`** (2588) — a memory that STATES a word's
  class, with `{word, word_class}` in metadata. `TAUGHT_PROPOSITION_TAG`
  (`admitted_proposition`) and `UNREAD_TELLING_TAG` (`told_but_unread`) are the
  other two kinds of evidence.
- **`async stated_word_classes() -> List[Tuple[str, str]]`** — every `(word,
  CLASS)` pair already told, read exactly from metadata so a teaching pass can
  tell what it has already said without asking a vector index whether two
  sentences about grammar resemble each other.
- **`async warm_word_classes() -> int`** (2707) — rebuilds the view from the
  substrate's OWN memories, folding **three** kinds of evidence: classes
  **stated** outright (every closed class, and every adverb); classes
  **implied** by the surface of a taught proposition (`classes_implied_by`); and
  classes **refuted** by a reading that failed because of them (`blamed`, which
  counts *against*). Called at the events that change what could be in it, never
  on a timer.
- **`word_classes(word) -> Dict[str, int]`** (2593) — every class the word has
  been observed to have, with net evidence. **Membership, not identity:** a word
  is not one part of speech, and asking "what class IS this" either picks one
  and is wrong half the time or, on even evidence, answers nothing.
- **`WORD_CLASS_WARM_LIMIT = 400000`** (2617) — raised from 20,000, which was
  sized for a store holding 199 words. With a reference vocabulary the old cap
  cut it off mid-alphabet and every word past the cut read as unknown, which is
  exactly what its own comment warned about.

**What the merge once destroyed.** The merge compared only a reading's subject, so
`'he' is used as a pronoun.` absorbed `'she'`, and a merge kept only the existing row's
metadata: the incoming word was destroyed (247 taught → 170 stored). A stated class's
identity is the `(word, class)` **pair**, checked by the caller before it writes, because
`that` is a determiner AND a relative AND a subordinator. Nothing merges now.

**A thing met is what it was (2026-09-28).** Every memory that keeps media carries
`met`, the sha256 of what was met: the identity of the thing, whatever its account says.
Memories are never merged. Percept accounts are short and shaped alike, and the
similarity merge this replaced folded three different sounds ("1.5s aiff recording,
1 sound(s): an abrupt mid-pitched sound") into one memory, so every belief about any of
them named that one memory. Each seeing or hearing is now its own memory, the same
thing met twice included. Checked by HEAR-01 (seven different sounds → seven memories,
seven digests).

#### Retrieve / query
- **`async retrieve_memory(memory_id, update_access=True, tier_hint=None)`** (1940) — cache→hot→cold; increments access; caches hot.
- **`async get_recent_memories(limit=10, memory_types=None, min_importance=None, tags=None)`** (2011) — recent hot within 7-day window.
- **`RETRIEVAL_STRATEGIES = ("semantic","keyword","tags")`** (2063).
- **`async retrieve(query=None, *, tags=None, memory_types=None, strategies=None, limit=10, min_similarity=0.5, min_importance=None, deduplicate=True, include_events=True, relative_to_best=None, require_named_match=False, actor=None, heard=None)`** (2065) — **the single recall authority.** Runs applicable strategies concurrently (`semantic`, `keyword`, `tags`, `sound`), merges by id, ranks relevance-first (similarity→corroboration→importance); a failing strategy is skipped, not emptying. `include_events=False` withholds events; `require_named_match` drops off-entity memories; `relative_to_best` self-calibrates the cutoff.
- **Recall BY THE SOUND (`heard=`, strategy `sound`, `_recall_by_sound`).** Given a sound's landmarks, it recalls the hearings of the same sound: a recording heard again, through a room, a codec, or over other sound. Candidates come from the media store's hash index (`MediaStore.by_sound`). Each is decided by agreement on one offset, the cut measured for songs: at least 10 agreeing landmarks, and at least 0.1 of those heard while the remembered sound was sounding. The item carries `similarity_score` (that share) and `heard_match`, and the same visibility rule applies as every strategy. The coordinator asks it before each hearing is remembered (`heard_before`: in words, in the graph as `same_sound_as`, as a belief). A song taught later names the hearings of it that came before (`plays`). `MemoryInjector.inject_memories(heard=...)` injects the same sound's memories first (MEMORY-SOUND-01).
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
- **`async migrate_to_cold_tier(memory_id, force=False, tier_hint=None)`** (2870) · **`async retrieve_from_archive(memory_id, restore_to_hot=False)`** (2910).

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
- No parameter self-modification: the `modify_importance_threshold` / `modify_decay_rates` / `modify_tier_thresholds` / `modify_embedding_config` setters were removed 2026-09-15 (no callers; the substrate improves only by learning).

#### Metrics / cache
- **`get_metrics`** (3043) · **`async cleanup_cache(max_age_hours=24)`** (3057).

### 4. Feeds / feeds-into
**Called by:** cognitive ingress `_remember` (cognitive_ingress.py:417-453, `store_memory(..., SEMANTIC, 0.75)`, NOT an event); learning; coordinator + intrinsic_motivation (rich writes + `capture_task_outcome`); reasoning (`neural_bridge`, `hypothesis_testing`), cross-domain reasoner; recall surfaces (`live_recall`, `memory_injector` reads `_pending_memories`); health/tools/chaos/security.
**Reads/delegates to:** beliefs (`beliefs_for_domain` to stamp `belief_state`); appraisal (`get_appraisal_system().current_state`); reasoning authority (`abstract_over_memories`/`reflect`); worthiness filter (`memory_filter`); storage/embeddings/media/queue; semantics (`claim_shape`, `sentence_reader`); governance/safety (`capability_tokens`).
