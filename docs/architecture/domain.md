# Domain — `UniversalDomainMaster`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

## `UniversalDomainMaster` — the domain authority

*`core/integration/universal_domain_master.py` · `get_universal_domain_master()`; alias `get_domain_master`.*

### 1. Purpose
The single authority for the domain system. Owns three things nothing else may: (1) **domain existence** — a *domain* is something the substrate has learned or can act in, distinct from a `DomainType` that merely *classifies*; (2) **per-domain competence, controllability, learning progress**, tracked as epistemic beliefs so the same intrinsic-motivation machinery that picks every exploration target also picks which domain to learn operators in; (3) **cross-domain reasoning, transfer, crystallization** — when a provisional bucket of operators (or a taught concept cluster) becomes a first-class domain. A *tool*, not an orchestrator: it measures and registers; decisions belong to the `AppraisalSystem` downstream (342-363, 532-543).

### 2. State
Singleton via `__new__`. `self.db` (`LyricUnifiedDatabase`), `domain_cache` (`DomainType`→dict), `mapping_cache` (the latest query's answer per reference pair; read by `intrinsic_motivation`), `stats`. Derived state, each entry keyed by the registry content version it was computed from (`DomainRegistry.concept_version`): `_vectors` (`_ConceptVectorStore`, stored concept vectors held in memory), `_sides` (per-domain scoring rows), `_signatures` (per-domain `DomainSignature`), `_correspondences` + `_correspondence_runs` (scored pairs; concurrent callers share one run), `_pair_mappings` (per field pair + strategy), `_embedding_backfill` (task). Constants: `MAX_RESOLVED_FIELDS=4`, `COMPETENCE_EVIDENCE_QUALITY=0.15`, `LEARNING_PROGRESS_WINDOW=4`/`MIN_LEARNING_PROGRESS=0.01`/`OPTIMISTIC_PROGRESS=1.0`, `CONTROLLABILITY_FLOOR=0.05`, `OPERATING_MIN_SAMPLE=4` (earned operability — min operating outcomes before reliability moves the bar). Vocabularies (`DomainType`, `ReasoningStrategy`, `ConceptType`) imported not redeclared (33-78). Types: `CrossDomainQuery`, `DomainMapping` (tri-state `verified: Optional[bool]`), `DomainIntegrationResult` (81-145); deficit model `DeficitType` (9, upstream-first)/`LearningOperation`/`EpistemicDeficit` + `_DEFICIT_PRIORITY`/`_SIGNALS`/`_OPERATION`.

### 3. Methods by area

#### Lifecycle
- **`__init__`** · **`async initialize`** · **`async _database`** (db initialized + concept vector schema ensured once) · **`async ensure_concept_schema`** (for writers of `unified.concepts`) · **`async _ensure_concept_vector_schema`** (adds `name_embedding` and `description_embedding` as 384-dimension vector columns + `embedding_model` + partial index `idx_concepts_embedding_pending` only when missing; clears vectors written by any other model) · **`async _load_domain_registry`** (counts+loads `unified.domains`) · **`async _initialize_default_domains`** (**RETIRED no-op** — seeding all 15 categories made classifications indistinguishable from learned domains) · **`async _initialize_default_domains_RETIRED`** (dead original) · **`async _registry`** (the `DomainRegistry` — one store).

#### Domain creation & discovery
- **`is_learned_domain(domain) -> bool`** — True iff `boundaries.origin=="learned"` (real capability, not a seeded category).
- **`async ensure_domain(domain_id, *, name=None, description="", domain_type=None)`** — **THE single authority for a domain coming into existence.** Idempotently registers an operational `Domain` (`origin="learned"`, `maturity_score=0.1`), classifies to ABSTRACT if untold, records an initial competence belief so it surfaces for exploration.
- **`async _ensure_domain_for_capability(domain_id)`** — registers a just-shown-capability domain; degrades a transient failure via `raise_if_structural` so competence/controllability evidence isn't lost.

#### Domain competence (epistemic belief)
- **`_competence_claim(domain_id)`** — the canonical claim `"the substrate has learned the operators of domain <id>"`.
- **`@staticmethod _uncertainty()`** — the belief store handle.
- **`async ensure_competence_belief(domain_id)`** — returns/creates the competence belief at `prior=0.5` (max entropy → surfaces), durably flushes.
- **`async record_competence_evidence(domain_id, *, learned, quality=None)`** — moves competence toward learned/not (default weak 0.15), ensures first-class first, durably flushes.
- **`async refresh_competence_beliefs() -> int`** — decays every competence belief toward uncertainty by elapsed time so unearned mastery re-enters the explorable set; called each exploration cycle.
- **`_competence_belief_of(domain_id)`** · **`learning_progress(domain_id) -> float`** (signed derivative of competence over the window = expected information gain; optimistic with little history; resets optimistic after restart while level persists).

#### Controllability
- **`async _ensure_controllability_table`** (creates `unified.domain_controllability` + `ADD COLUMN IF NOT EXISTS operating_attempts/operating_wins`) · **`async record_controllability(domain_id, *, action_attempts, action_effects, still_observations, ambient_changes)`** (acting-vs-observation evidence) · **`async controllability(domain_id) -> float`** (`action_effect_rate·(1-ambient_rate)`; optimistic 1.0 with no evidence).

#### Operating outcomes — the EARNED half of operability
*Same owner/table as controllability (one owner for all per-domain action accounting), but a DISTINCT measurement: controllability = "do my acts MOVE the domain"; operating = "when I acted to DO a task here, was the outcome RIGHT". Neither is competence ("did I LEARN the operators").*
- **`async record_operating_outcome(domain_id, *, success)`** — records one verified operating-correctness outcome (`operating_attempts`/`operating_wins`); ensures the domain first-class; persisted so earned trust survives restart. Producer: coordinator `_execute_and_validate_task` (verified `is_complete`), guarded to domain-tagged NON-drive tasks only (drive/learning goals feed competence — recording them here would conflate KNOW with OPERATE).
- **`async operating_reliability(domain_id) -> Dict`** — the **Wilson lower bound** (`meta_learning.wilson_interval`, the interval meta-learning and its adaptation gate use) on the operating win-rate: the `earned` shift signal for the operability bar. **NEUTRAL 0.5 below `OPERATING_MIN_SAMPLE=4`** (a handful of outcomes neither lowers nor raises the bar — "earned over several, never one"). Returns `{attempts, wins, win_rate, wilson_lower, wilson_upper, earned, enough_history}`. Consumed by the coordinator's `_domain_operability` gate.

#### Deficit diagnosis & remedy
- **`async diagnose_deficit(domain_id, goal_conditions, world, outcome) -> EpistemicDeficit`** — model-free measurement of *what kind* of knowledge is missing behind a goal that won't plan; returns exactly one (most upstream), defaulting `UNKNOWN_GAP`, upgrading to `WORLD_PREVENTS` only on a genuine unreachability proof.
- **`@staticmethod _classify_deficit(...)`** — diagnoses one unmet predicate down the chain: represented? produced? validated? bound? preconditions reachable? else undiagnosed.
- **`@staticmethod _parse_facts(conditions, Fact)`** — parses facts, dropping unparseable (a malformed condition isn't evidence of a deficit).
- **`async address_deficit(deficit, *, _depth=0) -> Dict`** — runs the operation the deficit already fixed: LEARN_OPERATOR/VALIDATE_CAUSE/PROBE explore (record controllability), ACHIEVE_PREREQUISITE recurses one level, TRANSFER_RELATION → `transfer_relation`, ESCALATE/DISENGAGE return honest non-action. No model; no decision to run.

#### Cross-domain transfer
- **`async transfer_relation(target_domain, relation_predicate) -> Dict`** — acquires a relation the target can't produce by projecting a source operator across the predicate correspondence their shared operators fix; lands it as a zero-evidence CANDIDATE via `admit_projection` (converts a RELATION_GAP into a CAUSAL_GAP, not a finished capability).

#### Exploration target selection
- **`async select_exploration_target(explorable_domains, targets) -> Optional[str]`** — the controllable operator-domain with the highest learning progress (controllability gates, progress ranks).
- **`is_competence_belief(target) -> Optional[str]`** — if a target is a competence belief, the domain it's about.
- **`async learned_domains()`** — registered domains with `origin="learned"`.

#### Concept vectors & concept-level correspondence
*A concept's name and description are encoded ONCE, when the concept is written, and stored on its `unified.concepts` row (unit float32 vectors; `embedding_model IS NULL` = not encoded yet; the ingestion upsert clears it when a description changes). Nothing encodes concept text per comparison. Correspondence between two domains is scored from stored vectors in a worker thread and reused until either domain's content version moves.*
- **`async concepts_written(concept_ids)`** — called by `ConceptIngestionService.ingest` after it writes: `registry.refresh_concepts` re-reads exactly those rows (moves re-filed concepts, bumps both domains' versions), then `embed_pending_concepts` stores their vectors.
- **`async embed_pending_concepts(concept_ids=None) -> int`** — encodes pending rows (`EMBED_BATCH=256`) off the loop via `EmbeddingService.encode_normalized` (raises when the model is unavailable; no lexical fallback) and writes them with one `UPDATE … FROM unnest(vector[])` guarded on the description it read, so a row edited meanwhile is re-read, never stored stale.
- **`start_concept_embedding()`** — `main.start()` launches the background completion of every pending row; failure logs ERROR and re-raises in the task; `shutdown` cancels it. First run over 256,231 concepts: 216 s.
- **`async similar_domains(domain_id, *, threshold=0.0)`** — `[(Domain, score)]` from cached `domain_signature`s (computed off the loop per version) and `domain_similarity`. Cold over `domain_general` (173k concepts): 1.4 s off-loop; previously 96 s synchronous in the registry.
- **`async suggest_mappings(source_id, target_id)`** — the ground truth transfer consumes: strongest pairs above `SUGGESTION_THRESHOLD=0.6`, at most `SUGGESTION_LIMIT=10`, as `validated=None` `CrossDomainMapping`s with derived ids; `UnknownDomain` for an unregistered domain. `general`×`lexical` (11.4B pairs): ~70 s off-loop once per version, then reused.
- **`async structural_similarities(source_id, target_id, *, threshold, keep)`** — every pair above `threshold`: `pairs`, `total`, `keep` strongest (the analogical strategy's input). `mathematics`×`lexical` (151.7M passing pairs): 15 s off-loop.
- **`async concept_similarity(src_domain, src_concept, tgt_domain, tgt_concept)`** — one pair, same exact scorer; `LookupError` for a concept its domain does not hold.
- **Incremental.** A result keeps `CORRESPONDENCE_DEPTH_FACTOR` (4) × `keep` strongest pairs (with a `complete` flag) and, counting all pairs, per-concept `(pairs, total)`. When a domain's version moves, `DomainRegistry.concept_changes` names the concepts that joined, left or changed, and `_update_correspondence` scores only pairs touching them and merges — exact, because pairs between unchanged concepts keep their scores and relative order. It declines (full rescore) when the change log does not reach back, more than 10% / 1000 concepts changed, both sides changed while counting all pairs, or too few exact pairs remain. Measured: general×lexical after a change that removed the top match 0.2 s vs 41.8 s full; mathematics×lexical all-pairs 0.1 s vs 11.6 s; identical results.
- **`async _concept_correspondence`** / **`_compute_correspondence`** / **`_concept_side`** / **`_vectors_for`** (loads stored vectors in 5k-row reads, encodes pending ones first, encodes universal-ontology projections in memory, raises for any other concept the table lacks).
- Module-level: **`_ConceptVectorStore`** (append-only rows; arrays replaced not resized, so worker threads never see a row change) · **`_score_correspondence`** — exact. The formula lives once in `domain_types.concept_similarity_scores`; a pair is only skipped when `semantic_floor` proves it cannot pass. Top-k: float32 blocks bound the semantic term against the rising k-th best, candidates rescored in float64 by `_exact_pair_scores`. Count-all: float64 blocks, scores read from them. Ties: source-then-target order. Verified against the retired per-pair implementation on 7 real domain pairs (identical top-10 order and pass counts; the only differences are pairs within 1e-8 of a 4th-decimal rounding boundary) and by `tests/test_concept_correspondence.py`.
- **`async record_mapping(mapping)`** · **`record_knowledge_transfer`** · **`record_mapping_usage`** — the one writer of mappings, transfers and usage; `DomainRegistry` stores them. The store writes nothing when a mapping or transfer is re-derived exactly as stored (every learning example used to re-upsert the same rows), adopts the id of a relationship already stored under another id, never lets a re-derivation that judged nothing erase a verdict, and never lets a re-derived transfer erase a recorded outcome or its evidence (`success = COALESCE(new, stored)`).
- **Validation** (`UniversalOntology.validate_cross_domain_mapping`, called by learning's transfer): an edge of the source concept is preserved only if the target has the SAME relation to the SAME concept (distinct edges; edges to either side of the mapping excluded); ACCEPTED at ≥ 0.5 preserved, REJECTED below, INDETERMINATE under 2 edges a side. Matching relation LABELS was the old test — `isa` is 98% of relations, so sparrow↔vessel scored 1.0 — and argument similarity was measured and rejected as a test (sound and unsound analogies overlap, 0.37–0.55). Re-validated read-only: all 26 stored ACCEPTED verdicts fail the structural test; none were rewritten.

#### Crystallization (operator-structure discovery)
- **`@staticmethod _operator_skeleton(rule)`** — predicate-agnostic structural signature (variables canonicalized, names dropped).
- **`async _domain_operators(domain_id)`** · **`_operators_coherent(rules)`** (one connected component) · **`_correspondence(source, target)`** (sound full-merge predicate bijection) · **`_partial_correspondence(source, target)`** (the renaming induced by *shared* operators — the basis of relation transfer).
- **`async provisional_domains()`** — operational domains with validated operators not yet first-class (crystallization candidates).
- **`async discover_domains(*, limit=8) -> Dict`** — the operator-structure discovery idle step: crystallize or merge each provisional domain.
- **`async discover_concept_domains(*, from_field="conversation", min_size=3, limit=8) -> Dict`** — **declarative twin**: mints/grows domains from coherent connected clusters of taught concepts, names each for its hub, re-files concepts (`_refile_concepts`, one UPDATE per cluster, stamps `updated_at`), refreshes exactly those concepts in the registry (no full reload), sets knowledge coverage — so taught subjects separate out of the `conversation` channel.
- **`async crystallize(provisional_domain_id) -> Dict`** — decides one: `merged` (identity correspondence = same vocab re-learned), `crystallized` (new domain, recording renaming as transfer bridges), or incoherent/empty/already_registered. Conservative.
- **`async _record_domain_correspondence(source, target, mapping)`** — persists a merge's transfer bridge into `unified.domain_mappings`.

#### Declarative knowledge coverage / gap / sparsity
- **`async update_knowledge_coverage(domain_id) -> float`** — sets `maturity_score` from concept-graph `structural_complexity` — the declarative-coverage signal, kept separate from operator competence (credit invariant).
- **`async detect_knowledge_gap(domain_id, subject, relation)`** — declarative twin of a CONCEPT_GAP: registers a domain-scoped `KNOWN_UNKNOWN` without touching competence.
- **`async knowledge_sparsity_map(domain_id) -> Dict`** — ranks concepts by connectivity so the thinnest regions surface (where to ask next).

#### Cross-domain query execution
- **`async execute_cross_domain_query(query: CrossDomainQuery) -> DomainIntegrationResult`** — finds mappings, generates insights/explanations, records the query, updates stats.
- **`_resolve_references(registry, refs, *, rank_against=None)`** — references → fields holding concepts, capped at `MAX_RESOLVED_FIELDS`. One resolution per field pair serves both generation and reading.
- **`async _find_cross_domain_mappings(...)`** — per reference pair, per resolved field pair: **`_pair_mappings_for`** generates once per content version of the two fields, then reads everything stored for that pair AND strategy (`verified IS NULL or TRUE`). Rows of another strategy (e.g. `similarity`) are not returned under this one.
- **`async _generate_mappings(registry, source, target, strategy, min_similarity) -> int`** — runs `CrossDomainReasoner`, stores each candidate through `record_mapping` with a derived id (`_mapping_key(..., strategy)`); a failure raises instead of reading as "no mappings".
- **`async _generate_insights`** · **`async _generate_explanations`** (top 5) · **`async _store_query_record`**.

#### Stats & lifecycle
- **`async get_statistics`** · **`async shutdown`** (cancels the embedding backfill; shared DB not closed here).

### 4. Feeds / feeds-into
**Consumes:** `DomainRegistry` (`get_domain_registry`; store of domains, concepts, mappings, transfers, usage events); `EmbeddingService.encode_normalized` (concept text vectors); belief store + `UnifiedLearningSystem` (competence beliefs, `register_known_unknown`); `rule_store` (operators); `operator_binding` (bindings, world observation); `SubstrateExplorer`/`get_proposer` (exploration); `analogical_projection.project` + `get_learning_authority().admit_projection` (transfer); `CrossDomainReasoner` (mapping generation); the `unified.*` tables.
**Called by:** `main.py` (initialize; `start()` → `start_concept_embedding`; `shutdown`); `ConceptIngestionService` (`ensure_concept_schema`, `concepts_written`); `CrossDomainReasoner` (`structural_similarities`, `concept_similarity`); `UnifiedLearningSystem` transfer (`similar_domains`, `suggest_mappings`, `record_*`); `unified_learning_system.py:2761-2762`; coordinator (1046-1049, `execute_cross_domain_query` at 2281 & 3512, 4442-4469, 11238-11240); `intrinsic_motivation`; `neural_bridge`; `hierarchical_abstraction`; `epistemic_engine`. `EpistemicDeficit.appraisal_signals()` → the `AppraisalSystem`; competence beliefs → the intrinsic-motivation loop; mappings/insights → cross-domain consumers.
**The KNOW→DO operability bar (coordinator, see [coordinator.md](coordinator.md)) reads three of this authority's signals:** `operating_reliability` (the EARNED half), `similar_domains` (borrowed-knowledge / declarative transfer on the KNOW side), and `_domain_stakes` reads `rule_store.executable_rules` + `action_consequence`. The authority measures; the coordinator composes them into `_domain_operability`.
