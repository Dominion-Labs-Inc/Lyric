# Learning — `UnifiedLearningSystem`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authority changes. Line numbers drift; the explanations must stay true.*

## `UnifiedLearningSystem` — the one learning authority

*File:* `core/learning/unified_learning_system.py` (class at line 284; `class UnifiedLearningSystem(ILearningAuthority, ILearningSystem)`)

### 1. Purpose

`UnifiedLearningSystem` is the substrate's single learning authority — the subsystem every faculty reaches as `coord.learning` (`autonomous_coordinator.py:355`) or through the module singletons `get_learning_authority()` / `get_unified_learning_system()` (lines 3173, 3181, which return the same object). It was once the *declared* authority while a separate `learning_authority.py` held the *real* model-free implementation; that file was deleted and its whole implementation folded in here, so this one class now owns both the strategy/experience machinery (meta-learning, memory routing, transfer) and the model-free authority core (rule store, inducer, and the propose→attest boundary). Its governing principle is **propose vs. attest**: a contributor may propose a hypothesis, situation, or formalization, but nothing it offers is evidence — everything admitted enters as `CANDIDATE` with zero evidence roots, and only world-supplied outcomes move it. It holds **no model handle**: a language model is the teacher's alone; nothing in this file generates.

### 2. State (instance attributes, set in `__init__`, lines 287–357)

- **`_store`** (291) — lazy handle to the induced-rule store (`get_rule_store()`). Accessed via the `store` property.
- **`_inducer`** (292) — lazy rule inducer (`get_rule_inducer()`), the hypothesis-search engine. Via the `inducer` property.
- **`_contributors`** (293) — `{name: role}` registry of recognised proposers. `contribute()`/`admit_projection()` admit only from a registered contributor; registration is provenance, not permission to attest.
- **`_admissions`** (294) — append-only ledger of every `Admission`, accepted and rejected alike.
- **`_clause_classifiers`** (299) — `{name: {"model": CTM, "labels", "encode"}}`. Parametric perceptual learners (Convolutional Tsetlin Machines) OWNED by the authority; a mechanism whose recognitions become knowledge only via `recognize` → `learn_fact`.
- **`config` / `domain_master` / `initialized`** (300–302) — config dict, optional injected domain master, started flag.
- **`memory_system`** (305) — the memory agent, injected by `main.py` or fetched lazily in `start()`.
- **`meta_learning`** (308) — the global `MetaLearner` singleton, the shared strategy-selection/credit engine.
- **`domain_registry`, `universal_ontology`, `cross_domain_reasoner`** (312–313) — domain-knowledge singletons for transfer.
- **`domain_learning_stats`** (315) — `cross_domain_transfers`, `domain_specific_learning`, `transfer_learning_successes`.
- **`log_db`** (322) — `LoggingDatabase` for compliance logging.
- **`active_learning_tasks`** (327) / **`_max_queued_events`** (328, =200) — bounded event queue.
- **`_event_tasks`** (332) — strong refs to in-flight event tasks (no GC mid-flight).
- **`system_metrics`** (341) — per-process counters, reset on restart (`knowledge_base_size` removed — measured from stores now).
- **`recent_strategy_usage` / `max_recent_strategies`** (348–349) — rolling window (100) feeding the exploration-quota hard gate.
- **`_max_nesting_depth`** (354, =3) — circular-dependency limit; the depth is the per-task `_learning_depth` ContextVar (module line 103).
- **`slack_notifier`** (357) / **`_pending_notifications`** (class attr 363) — milestone notifier + strong refs.
- **`_asi_self_improvement`** (used at 2777) — optional self-improvement engine, an internal collaborator.

*Module-level support:* `_LEARNING_TYPE_TO_TASK_FAMILY` (69, the lossy bridge); `_learning_depth` ContextVar (103); `_json_safe` (106); induction bounds `_BASIS_*` (141–143) + `_bounded_basis` (146) + `_relevant_frame` (197); `ContributionKind` (244), `Contribution` (256), `Admission` (268, `is_knowledge` at 279 — never true on admission).

### 3. Methods by functional area

#### Lifecycle & internal plumbing
- **`__init__(config=None, domain_master=None)`** — 287. Constructs all state; wires meta-learner, logging DB, notifier, bounded event queue.
- **`_notify(**kwargs)`** — 365. Fire-and-forget Slack notification off the learning path; failures logged and dropped (a blocking webhook once deadlocked every `reason()`).
- **`async start()`** — 413. Full async startup: logging DB, memory system (idempotent, *verified* not asserted), domain systems, meta-learner; registers `analogical_projection`; reloads persisted classifiers. Raises on critical failure.
- **`async initialize() -> bool`** — 1065. Interface shim: delegates to `start()`.
- **`get_system_status() -> dict`** — 1052. Snapshot of initialised/readiness/metrics/active tasks.
- **`async shutdown()`** — 3162. Honest no-op teardown (persistence delegated to the demo/rule stores).
- **`async _report_unmapped_learning_type(name)`** — 558. Records a `LearningType` with no `TaskFamily` on the failure record (a gap watchers can read).
- **`_calculate_exploration_quota() -> float`** — 1003. Fraction of recent uses that were exploratory (`trials<20`), feeding the meta-learner hard gate.
- **`_track_strategy_usage(strategy)`** — 1021. Appends to the rolling window, trims to 100.

#### Experience / procedural learning (the strategy-credit lane)
- **`async learn_from_example(example) -> dict`** — 581. **The primary entry the coordinator invokes.** (1) fires the declarative takeaway through the gate first; (2) resolves `LearningType`/`TaskFamily` (stated wins, else lossy map, else `unmapped_learning_type` — no default family); (3) selects a strategy via the meta-learner hard gate, capturing decision id — when every arm fails the gate (`gate_blocked` in the decision sink) the example is still stored and transferred but **no arm is credited** (`strategy_used=None`, `strategy_gate_blocked` reasons, `credit_applied=False`), and the empty decision still counts in the exploration budget so it can recover; (4) memory-stores; (5) records outcome with honest credit (`INSUFFICIENT_EVIDENCE` when unstated); (6) fires cross-domain transfer gated on the *domain*, not success. Guards recursion per-task.
- **`async process_interaction(user_input, system_response)`** — 1041. Wraps a chat turn as an example.
- **`async learn_from_data(data, learning_type) -> Any`** — 1074. Shim: injects `learning_type` into the example; wraps result with the example's stated confidence.
- **`async learn_from_experience(experience) -> Any`** — 1100. `learn_from_data(experience, CONTINUAL)`.
- **`async learn_from_feedback(feedback) -> dict`** — 1104. A verdict on a claim already made+remembered: FLAGS the existing memory (merge-only), credits a *strategy* only with a `decision_id` (credit invariant), and moves the *belief* through the gate (`_route_declarative_takeaway` / `observe_claim`).
- **`async process_experience(experience) -> dict`** — 1375. Wrapper over `learn_from_example`.
- **`learn_from_event(event) -> bool`** — 1318. Sync entry for autonomous events; hands to `learn_from_example` as a task; returns whether learning *began* (False → queued in the bounded list). (Old version returned True having learned nothing.)
- **`async drain_events(timeout=30.0) -> dict`** — 1404. Awaits in-flight event tasks before shutdown so decision rows close.
- **`async query_experiences(query) -> list`** — 1431. Searches `unified.operation_logs` by type/strategy/success/source/since/limit.
- **`async get_experience_count() -> int`** — 1485. Counts recorded rows (survives restart), not the queue length.

#### Prediction / metrics / self-improvement (several deliberate `NotImplementedError`)
- **`async knowledge_base_size() -> dict|None`** — 1226. Measures actual holdings (concepts + learned_rules + memories), or None.
- **`async get_learning_metrics() -> dict`** — 1253. Process counters + recorded total + KB sizes + tool-usage (labelled separately).
- **`async _tool_usage_metrics() -> dict|None`** — 1278. Reads tool metrics through the one owner (`get_adaptive_tool_learning`).
- **`async get_learning_state() -> dict`** — 1288. State for self-improvement; genuinely-checked component activity (None = absent).
- **`get_domain_learning_stats() -> dict`** — 2094. Transfer counters + `transfer_success_rate` (None when no attempts).
- **`async consolidate_learning()`** — 1308. **Raises NotImplementedError** (owned by memory tiering).
- **`async predict_optimal_retry_delay(context)`** — 1364. **Raises** (used to return constant 3.0).
- **`async update_strategy_effectiveness(strategy, effectiveness)`** — 1380. **Raises** (owned by `MetaLearner`).
- **`async recommend_strategies(context)`** — 1393. **Raises** (use `MetaLearner.select_strategy`).
- **`async predict_outcome(context)`** — 1505. **Raises** (used to return 0.85/0.8; `PredictiveIntelligenceSystem` owns it).
- **`async run_self_improvement_cycle(scope=None, target_components=None, context=None)`** — 2767. Runs one self-improvement cycle through the injected `_asi_self_improvement` engine — self-repair as a *kind of learning* reached here.

#### Transfer / cross-domain
- **`async transfer_learning(source, target) -> bool`** — 1214. Shim → `transfer_learning_across_domains` (replaced a bare `True`).
- **`async _transfer_from_known_domains(target, max_sources=3, task_id=None) -> dict|None`** — 1518. On new learning in a domain: resolve reference → rank candidate sources by `UniversalDomainMaster.similar_domains` (cheap) then re-rank by `suggest_mappings` strength (real signal) → transfer from the best. A failed mapping probe is logged at ERROR and returned in `probe_failures`, never folded into "none share a mapping". Fired from `learn_from_example`.
- **`async transfer_learning_across_domains(source, target, knowledge) -> dict`** — 1666. Full worker: candidates from `UniversalDomainMaster.suggest_mappings`; validates each and persists it WITH its verdict through the Master (`record_mapping`, `record_knowledge_transfer`, `record_mapping_usage`) — the Master is the one writer, the registry stores; content-addressed `KnowledgeTransfer` row; candidate vs validated counts kept apart. Typed negatives (`no_candidate`/`no_validated_mapping`/`unknown_domain`/`operational`).
- **`async learn_with_domain_context(example: LearningExample, domain) -> LearningResult`** — 1889. Domain-scoped: resolve to a populated field; state `type=CONTINUAL` + true `task_family`; lift the producer's stated outcome; report **learned** and **earned-credit** separately (so `(recorded=True, credit=False)` is representable).

#### Perception / clause classifiers (gated mechanisms)
- **`register_clause_classifier(name, model, labels, *, encode=None)`** — 2140. Registers a trained CTM + a `clause_classifier:<name>` contributor; knowledge only via `recognize`.
- **`_classifier_dir() -> str`** — 2153. Durable on-disk home (`data/classifiers`).
- **`save_classifiers(directory=None) -> int`** — 2160. `torch.save`s each mechanism (TA/weights/polarity/shape) so it survives restart; `encode` not persisted.
- **`load_classifiers(directory=None) -> int`** — 2179. Restores on startup, re-homing tensors to device; `encode` = None.
- **`async recognize(name, instance, instance_id, *, domain="perception", threshold=0.0) -> Admission|None`** — 2207. Runs the classifier, margin-based confidence, and TEACHES the finding through the gate via `learn_fact` (`instance_id isa <category>`, PERCEPTION provenance, confidence as quality). None below threshold/unregistered.

#### Operator induction (model-free)
- **`induce(examples, target_predicate=None)`** — 2245. Learn a rule from demonstrations (delegates to the inducer).
- **`async record(result, examples, *, domain_id, rule_kind="state_transition")`** — 2249. Persists induction keyed on the producing demonstrations.
- **`async induce_category(category, positives, negatives=(), *, domain="perception")`** — 2256. Anti-unifies labelled instances' feature facts into a naming rule (`CANDIDATE`); fans per-instance naming through `learn_fact`. Refuses with <2 positives / no feature facts.
- **`async record_demonstration(example, *, domain_id) -> bool`** — 2788. Cheap hot-path half: keep one demo; no induction here.
- **`async reinduce_operator(*, domain_id, predicate, arity) -> dict`** — 2799. Online half: re-induce one operator off the hot path; promote to executable when held-out experience confirms.
- **`async drain_pending_induction(*, limit=50) -> dict`** — 2807. Induce every signature that gathered demos since last induced.
- **`async _induce_signature(*, domain_id, predicate, arity) -> dict`** — 2841. Expensive core: load demos + contrastives, reserve held-out, bound the basis, induce, record, validate on the full world, project to concepts on promotion.
- **`async _project_operator_to_concepts(record, basis, *, domain_id) -> bool`** — 2907. Records induction roots as concept-graph demonstrations, submits the rule as their derivative (operator↔concept learning meet). Never fatal.
- **`derive_procedure(operators, guards, examples, terminal="RESULT", max_rules=None)`** — 2938. Second acquisition MODE: composes learned operators into a length-general procedure from I/O (widens *sequence*, not the learner).
- **`induce_causal_structure(observations)`** — 2950. Learns which conditions gate an outcome (owns `ProbabilisticVersionSpace`); None if trials unusable.
- **`induce_sequence_rule(terms)`** — 2989. Learns a numeric sequence's rule and predicts the next value; None when undetermined.

#### The contribution boundary (propose → attest)
- **`register_contributor(name, role)`** — 2131. Records a named proposer (provenance).
- **`async contribute(contribution: Contribution) -> Admission`** — 3045. The one proposal door: rejects unregistered; non-hypothesis kinds accepted as proposals not stored; a hypothesis (`CandidateRule`) enters as `CANDIDATE` with zero evidence roots. Never above `CANDIDATE`.
- **`async admit_projection(projection, *, contributor, rule_kind="projected") -> Admission`** — 3094. Admits an analogically-projected operator via `record_projection` (element-level provenance kept); `CANDIDATE`.

#### Beliefs door (delegates to `bayesian_uncertainty`, one owner)
- **`create_belief(claim, domain, prior=0.5, evidence=None, *, source="derived")`** — 2577. Records a belief; `source` = provenance (evidence applied only if a real evidence dict is given).
- **`update_belief(belief_id, evidence, evidence_supports=True)`** — 2604. Bayesian update on the single store.
- **`get_belief(belief_id)`** — 2613 · **`belief_for_claim(claim)`** — 2619 · **`beliefs_for_domain(domain, limit=8)`** — 2625. Reads.
- **`async flush_belief(belief_id) -> bool`** — 2631. Durably persists a decision-critical belief; replays buffered writes.
- **`observe_claim(claim, domain="language", *, supports=True, quality=0.9, source="observed")`** — 2638. Find-or-create-by-claim: first mints, later moves the same posterior (the completion-belief door).

#### Declarative teaching / fan-out (the one door for TOLD knowledge)
- **`async learn_fact(subject, relation, obj, *, positive=True, surface=None, provenance=None, domain="conversation", description="", word_class_of=None, emit=None, quality=0.9)`** — 2347. Admits one fact through the ingress then runs `_fan_out_learning`. Returns the `Admission`.
- **`async learn_facts(facts, *, provenance=None, domain="conversation", fan_out=True, remember=True, progress=None) -> dict`** — 2377. Many facts, admitted each but fanned out ONCE over the batch. `{admitted, already, refused, total}`.
- **`async learn_concept(name, *, domain="conversation", description="", relationships=None, provenance=None, emit=None) -> list`** — 2428. Concept node + edges through the one path (the method a discoverer calls instead of writing `unified.concepts`).
- **`async learn_rule(antecedent, consequent, *, surface, provenance=None, domain="conversation", emit=None)`** — 2459. Told conditional as a held rule via `admit_conditional`, fanning out like a fact.
- **`async _route_declarative_takeaway(payload, *, domain)`** — 2490. Routes a payload's declarative takeaway (s/r/o or `fact`/`claim`) through `learn_fact`; nothing when no claim (credit invariant). Called first inside `learn_from_example` and by `learn_from_feedback`.
- **`learn_word(word, word_class, *, source="taught")`** — 2534. One door for a word's part of speech.
- **`learn_words(words, *, source="taught", authoritative=False) -> dict`** — 2545. Batch POS teaching, saves lexicon ONCE; `authoritative` corrects an unconfirmed guess.
- **`async fan_out_ingested(result, *, domain="researched", surface="") -> int`** — 2655. Fan-out over relations an ingestion already admitted (closes the lexicon/belief gap for direct-ingest producers).
- **`async _fan_out_learning(*, surface, claim, clauses, positive, domain, emit, emit_payload, save_lexicon=True, quality=0.9)`** — 2687. **The shared post-admission fan-out** every `learn_*` runs so a fact and a rule touch the SAME systems: LEXICON, BELIEFS, METRICS, DOMAIN (via emit / `ensure_domain`). Isolated arms; every belief write moves a posterior.

#### Properties & module singletons
- **`store`** (2119) · **`inducer`** (2125) · **`contributors`** (2136) · **`admissions`** (3144) — lazy accessors / copies.
- **`async rules(domain_id=None)`** — 3149. Loads stored rules for a domain.
- **`async metrics() -> dict`** — 3152. Authority-boundary metrics (contributors; contributions seen/accepted/promoted).
- **`get_unified_learning_system()`** — 3173 · **`get_learning_authority()`** — 3181. Both return the one singleton.

### 4. Feeds / feeds-into

**Feeders (what calls this authority):** `core/main.py` (815–843, 1963, boot wiring + shutdown `save_classifiers`); `autonomous_coordinator.py` (heaviest — `self.learning` at 355; `reinduce_operator` 6167/6198/6230, `recognize` 7954, `record_demonstration` 11617, `learn_fact` 13305, `learn_rule` 13425); reasoning faculties (`abstract_reasoning_engine`, `epistemic_engine`, `hypothesis_testing`, `analogy_discovery`, `hierarchical_abstraction`, `neural_bridge:1886`); `execution/list_synthesis:85`, `semantics/derived_reader:330`, `domain/evidence_producers`, `health/monitoring_coordinator`, `learning/exploration`, plus EDU experiments/tests.

**Feeds-into (dependencies):** `cognitive_ingress` (`admit_relation`/`admit_conditional`, `Provenance`); `bayesian_uncertainty` (`get_uncertainty_system` — the belief store); `universal_domain_master` (similarity, mapping, `ensure_domain`); `semantics.lexicon` (`observe_proposition`); `meta_learning` (`select_strategy` — the production gate filters arms BEFORE Thompson sampling, so recorded propensities are those of the policy that chose, and an all-blocked selection returns None with per-arm reasons instead of the blocked arm; `track_learning_outcome`); rule/demo substrate (`rule_store`, `rule_induction`, `demonstration_store`, `procedure_synthesis`, `probabilistic_version_space`, `tsetlin_gpu`, `adaptive_tool_owner`); domain layer (`domain_registry`, `universal_ontology`, `cross_domain_reasoner`, `concept_ingestion`); infra (`database`, `LoggingDatabase`, `observability.failure_record`, `slack_notifier`).
