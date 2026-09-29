# Reasoning — `NeuralSymbolicBridge`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authority changes. Line numbers drift; the explanations must stay true.*

## `NeuralSymbolicBridge` — the reasoning authority

`core/reasoning/neural_bridge.py` (class at 791; singleton `get_neural_bridge()` at 3805)

### 1. Purpose
The **one reasoning authority**. Obtained process-wide via `get_neural_bridge()` (3805, lazily cached). Every request enters from the coordinator: `AutonomousCoordinator.reason_about` (autonomous_coordinator.py:3332) → `bridge.reason(...)` (3385) → `_reason_impl` (1408). Stance (docstrings 49-67):
- **Substrate-first and substrate-only** — `_substrate_solvers` runs for *every* request; the eleven kinds run next; a named mode is consulted only when neither settles it. No AUTO mode, no model fallback.
- **Model-free where a model is not the point** — despite the name, it never consults a language model to reason. `_neural_reasoning` (2689) is *learned inference over persisted beliefs*, not model inference. `_model_available` (1676) only *reports* whether escalating to a teacher is possible; it never calls one.
- **Owns every reasoning MODE** — the `ReasoningMode` routes, the substrate solvers, and (via the abstract engine) the eleven kinds. Also owns the belief graph, abstraction pipeline, and abstract-reasoning engine that used to be driven by the memory agent; single entry to the epistemic + hypothesis services.

Module-scope reason codes (155-212): `REASON_SUBSTRATE_VERIFIED/REFUTED/DERIVED_BY_KIND/UNDECIDED/UNSUPPORTED_INPUT/ENTAILMENT_ONLY/CAPABILITY_UNAVAILABLE/INVALID_INPUT/INTERNAL_FAULT/MODEL_COVERAGE/MODEL_FAILED`; metadata keys `KEY_SUBSTRATE_FORMALIZED/TEACHER_AVAILABLE/TEACHER_CONSULTED` (195-197); `model_required` a deprecated always-False alias.

### 2. State
`__init__` (1187), populated in `initialize` (1232): `config`/`initialized`; `memory_agent` (1192); owned subsystems (1201-1203) `beliefs` (`BayesianUncertaintySystem`), `abstraction` (`AbstractionPipeline`), `abstract_engine` (shared `AbstractReasoningEngine`); `statistics` mode-mix counters (1207-1216); telemetry `_reasoning_telemetry` per-kind `{runs,total_latency,attempts,successes}` (1218-1223) + dirty/db/schema flags. Class priors `_DECLARED_DIFFICULTY` + thresholds (820-831), quality thresholds (865-867), DDLs (930, 3749), `SYMBOLIC_PROOF_TIMEOUT=10.0` (1674), `_SUBCLASS_Q` regex (1961). Lazily builds: the deterministic formalizer chain (2493), and (inside methods) proof engine, constraint solver, learning authority, rule store/inducer, concept-graph reasoning, sense taxonomy, cognitive ingress, formal argumentation, epistemic engine, hypothesis system, domain master.

### 3. Methods by area

#### Entry / orchestration
- **`async reason(request) -> ReasoningResult`** (1359) — public entry; timing wrapper over `_reason_impl`; records per-kind latency, then annotates with a `fallacy_warning` (`_check_argument_fallacies`) and `epistemic_uncertainty` (`assess_uncertainty`) — honest annotations that never change the answer.
- **`async _reason_impl(request) -> ReasoningResult`** (1408) — the router: init (raises on failure), one-time memory injection (cached claims or a `memory_injector` search, 1427-1534); if `mode != ABSTRACT` runs the named mode via `_run_mode`; else the default pipeline `_substrate_solvers` → `_reason_by_kind` → (on explicit domain intent) `_cross_domain_reasoning` → `_unsettled`. A lossy propositional refutation is deferred past the kinds when the query names kinds/markers/a predicate rule (1559-1582). Any exception → confidence-0 error.
- **`async _run_mode(request) -> Optional[ReasoningResult]`** (1916) — runs the named substrate strategy (all model-free): `SYMBOLIC→_substrate_solvers`, `NEURAL→_neural_reasoning`, `HYBRID→_hybrid_reasoning`, `NEURO_SYMBOLIC→_neuro_symbolic_reasoning`, `CROSS_DOMAIN→_cross_domain_reasoning`; None otherwise.
- **`async _reason_by_kind(request) -> Optional[ReasoningResult]`** (3334) — runs the eleven kinds through the persistent `abstract_engine`; selects from `request.kinds` else `kinds_of_thinking_for(query)` else `CLASSICAL_REASONING_TYPES`; orders by measured `reasoning_quality`; keeps only on-topic conclusions; picks highest quality-then-confidence; records the QUALITY outcome; surfaces bearing schemas. None (≠ empty) when nothing applies.
- **`_unsettled(request, route) -> ReasoningResult`** (1936) — honest inability: empty answer, confidence 0, `reason=REASON_UNSUPPORTED_INPUT`; never handed to a model.
- **`_finish(request, result) -> ReasoningResult`** (1325) — single exit: `_update_stats`; for standalone non-empty answers schedules `_capture_reasoning_memory`.
- **`async initialize() -> bool`** (1232) — connects memory; takes ownership of belief graph/abstraction/abstract-engine; loads beliefs+schemas; restores telemetry+statistics; registers the periodic persistence flush on the queue authority.

#### Formalization
- **`_get_deterministic_formalizer() -> IFormalizer`** (2493) — the model-free `FormalizerChain([Passthrough, DeterministicExtractor, DerivedReading])` the router probes with. `DerivedReadingFormalizer` reads sentences TAUGHT with their meaning (`derived_reader`, since 2026-09-27): a taught ground statement or yes/no question becomes atoms through `clause_atom`, the same vocabulary as held graph facts.
- **`_build_reasoning_context(request, kinds)`** (3245) — turns a `ReasoningRequest` into an engine `ReasoningContext`: non-implications → premises+facts, implications → rules, query → target_conclusions (never a fact); `confidence_threshold=0.05`.
- **`async _check_formalizability(answer, request) -> Optional[str]`** (1733) — pressures an answer toward the extractor's grammar; returns a restatement request when unformalizable.
- *(Formalizer classes are module-level: `PassthroughFormalizer` 323, `DeterministicExtractor` 371, `DerivedReadingFormalizer` 638, `FormalizerChain` 751.)*

#### Substrate solvers (model-free)
- **`async _substrate_solvers(request) -> Optional[ReasoningResult]`** (2395) — fixed order (order, not privilege): (1) arithmetic `read_equation→_solve_equation`; (2) sequence `read_sequence→_extend_sequence`; (3) `_answer_over_sense_taxonomy`; (4) `_answer_over_concept_graph`; (5) `_answer_over_held_rules`; (6) `_answer_over_induced_rules`; (7) deterministic formalization → `_symbolic_reasoning`. None when nothing formalizes.
- **`async _answer_over_sense_taxonomy(request)`** (1963) — sense-exact subclass answer from the QID-keyed graduate taxonomy (`is_subclass`), before the name-keyed concept graph can cross a homonym.
- **`async _answer_over_concept_graph(request)`** (2011) — reads the query to a typed (s,r,o) triple (`SentenceReader`) and answers via the typed relation algebra (`answer_over_graph`, hop-bounded to 4). ISA consults the sense taxonomy first; on UNKNOWN ISA consults the belief store (p≥0.9/≤0.1 gate) before abstaining.
- **`async _answer_over_held_rules(request)`** (2165) — chains TAUGHT rules: `held_conditionals()` + held facts rendered to one atom vocab (`SentenceReader.clause_atom`), proved with Z3 via `_symbolic_reasoning`. Helper **`_held_rule_chain`** (static, 2278) renders the fired chain.
- **`async _answer_over_induced_rules(request)`** (2299) — names an instance via a rule the substrate INDUCED (`red & circular -> stop_sign`): loads feature facts, applies non-refuted rules concluding the category (VALIDATED>SUPPORTED>CANDIDATE).
- **`_solve_equation(equation)`** (1825) — linear equation via Z3; missing solver → `CAPABILITY_UNAVAILABLE`, unsat → `REFUTED`, solved → `VERIFIED` @1.0.
- **`_extend_sequence(sequence)`** (1874) — extends by the induced rule; MULTIPLE_HYPOTHESES/NO_RULE → unsupported; single rule → next term verified @1.0.
- **`async _symbolic_reasoning(request, formalization=None)`** (2507) — the solver decides and sets confidence: build a propositional `Theorem`, call the proof engine; proved w/ trusted premises → `VERIFIED`, w/ model-written premises → `ENTAILMENT_ONLY`, not entailed → try the negation (modus tollens) for `Disproved` else `REFUTED`, solver error → `UNDECIDED`. Emits the credit-assignment metadata contract.
- **`async _induce_from_demonstrations(demonstrations, target_predicate)`** (2779) — induces a rule from before/action/after demos via the inducer (from the NEURAL route). Helpers `_fact`/`_facts` coerce to `Fact`.

#### Modes (`ReasoningMode` execution routes)
- **`async _neural_reasoning(request)`** (2689) — learned inference, model-free: if demos present, induce; else answer from the most relevant Bayesian belief (content-word overlap, ranked by relevance then low entropy), confidence = `1 - entropy`.
- **`async _hybrid_reasoning(request)`** (2858) — propose→constrain→revise: derive ranked candidates once, cross-check each with formal constraints, fallacies, and entropy; first clearing all constraints wins, else the least-violating unverified.
- **`async _neuro_symbolic_reasoning(request)`** (2992) — ensemble of deductive/inductive/abductive derivations arbitrated formally: derive one per kind → Dung-semantics arbitration (grounded>credulous>defeated) → constraint-solver consistency → combine argument strength (0.4)+consistency (0.3)+base (0.3).
- **`async _cross_domain_reasoning(request)`** (3477) — maps structure between named domains via `UniversalDomainMaster` (ANALOGICAL, min_similarity 0.5). Gated by **`_is_cross_domain_request`** (3464) — true only when `task_metadata` names source/target domains.

**Routes/kinds owned:** `ReasoningMode` (6, 49-75): SYMBOLIC, NEURAL, HYBRID, NEURO_SYMBOLIC, ABSTRACT (default = the kinds), CROSS_DOMAIN. Substrate solvers (7): arithmetic, sequence, sense-taxonomy, concept-graph, held-rules, induced-rules, symbolic-proof. The eleven kinds (`ReasoningType`): DEDUCTIVE, INDUCTIVE, ABDUCTIVE, ANALOGICAL, CAUSAL, PROBABILISTIC, FUZZY, TEMPORAL, SPATIAL, LOGICAL, COUNTERFACTUAL.

#### Checks / quality
- **`async _check_argument_fallacies(answer, request=None)`** (1690) — argumentation-engine fallacy detection over an answer; context supplies premises so correct answers don't trip `begging_question`.
- **`async _check_formal_constraints(answer, request)`** (1772) — proves the *negated* goal from context when both formalize; a proof = formal contradiction. Unrepresentable ≠ violation.
- **`_extract_reasoning_steps(response)`** (1607) — extracts steps (THINKING sections, numbered lists, "Step N:", decimal-safe sentence split); `[]` never fabricated.
- **`_calculate_complexity_score(request, result)`** (3681) — 0-1 from steps, context, inverted confidence, vision success.
- **`_model_available()`** (1676) — reports (via `teacher_reachable()`) whether a teacher could serve; the reasoner never calls it.

#### Difficulty / quality telemetry
- **`_kind_key`** (static, 833) · **`_kind_cell`** (837) — normalize a kind; its `{runs,total_latency,attempts,successes}` cell.
- **`record_reasoning(kinds, latency_s)`** (848) — grounds difficulty in behaviour (latency per exercised kind, every real call).
- **`record_reasoning_outcome(attempted, winning)`** (869) — which kinds were considered vs settled it (the quality signal).
- **`reasoning_quality(type) -> float`** (888) — measured success rate (`_QUALITY_PRIOR` until `_QUALITY_MIN_ATTEMPTS`).
- **`reasoning_difficulty(type) -> float`** (897) — avg latency normalized to the fastest kind, else the declared prior; read by the coordinator's agent allowance + queue timeout.

#### Persistence
- **`_telemetry_db_handle`** (943) / **`async _ensure_telemetry_schema`** (949) — lazy handle + DDL.
- **`async load_telemetry`** (958) / **`async flush_telemetry`** (985) — restore/persist measured per-kind behaviour; flush no-ops when unchanged.
- **`async _flush_reasoning_persistence`** (1018) — the one scheduled job (queue authority owns cadence): telemetry + statistics.
- **`async get_statistics`** (3730) — flat scalar stats for health (quality-loop summary).
- **`async flush_statistics`** (3757) / **`async load_statistics`** (3779) — mode-mix + avg-confidence counters.
- **`_update_stats(request, result)`** (3547) — increments the used-mode counter and running average confidence.

#### Reflection / hypothesis / memory / epistemic tie-in
- **`async abstract_over_memories(memory_dicts) -> Dict[str,int]`** (1028) — forms schemas→beliefs from a memory batch via the owned abstraction pipeline (the memory agent *asks*).
- **`async reflect() -> Dict`** (1041) — belief-graph hygiene: temporal decay, consistency, domain volatility, schema decay; steps isolated.
- **`async assess_uncertainty(request) -> Dict`** (1080) — belief-graph entropy about this query, via the epistemic engine.
- **`async apply_reasoning_output(outputs) -> int`** (1091) — folds hypotheses/belief_updates into the belief graph (epistemic engine); returns real mutations.
- **`async epistemic_affect_signal() -> Dict`** (1106) — the authority's reading of how the belief graph MOVED since last asked, from **any** source (perception, teaching, reasoning), summarized into the emotional dials (`information_gain`, `uncertainty_reduction`→confidence, `uncertainty_increase`/`contradiction`→doubt+curiosity). Delegates to `EpistemicEngine.interpret_drift()` — a **read-only** entropy diff over the whole graph (primed on first call). This is the knowledge→emotion producer; it interprets what changed, it never writes a belief. The coordinator relays the signal to appraisal; emotion shapes disposition, never a core decision.
- **`_coerce_predictions(value, *, field)`** (static, 1106) — normalize predictions/alternatives to non-empty strings.
- **`async generate_hypothesis(*, claim, domain, predictions, alternatives) -> Optional[str]`** (1141) — generates+persists a falsifiable hypothesis (single entry, e.g. intrinsic motivation).
- **`async observe_tool_result(tool_name, parameters, output, success) -> int`** (1170) — folds a tool observation into the belief graph (executor post-tool seam).
- **`async _capture_reasoning_memory(request, result)`** (3575) — background, never-raising trace persistence to memory (skips trivial low-confidence; tags the kind).
- **`_schemas_bearing_on(query)`** (3311) — learned schemas whose terms overlap the query.
- *(Module helpers: `_is_implication` 221, `_content_terms` 241, `_query_topic` 257, `_relevant_to_topic` 279.)*

### 4. Feeds / feeds-into
**Called by:** coordinator (`reason_about` 3332 → `bridge.reason` 3385; holds `self.neural_bridge` 1048; routes `observe_tool_result` 11857; `agent_allowance` reads `reasoning_difficulty`); executor (post-tool seam); memory agent (memory_agent.py:3767 asks `abstract_over_memories`/`reflect`); queue authority (queue_authority.py:548 drives `_flush_reasoning_persistence`); `reasoning_tools`, `health_monitor` (probes `get_statistics`), `intrinsic_motivation` (`generate_hypothesis`), `abstract_reasoning_engine`, `causal_feedback_analyzer`, `capability_benchmark_suite`, `enhanced_asi_self_improvement`.
**Reads:** belief graph (`get_uncertainty_system`, owned + re-fetched 2720/2880); concept graph, sense taxonomy, held conditionals (ingress), rule store, proof engine, constraint solver, learning authority, argumentation engine, epistemic engine, hypothesis system, domain master.
**The posterior gate (p≥0.9 / p≤0.1):** in `_answer_over_concept_graph`, when the bounded closure returns UNKNOWN for an ISA question (2095), it reads the taught claim's `posterior_probability` (2107-2110) and answers only when decisive — **`if p >= 0.9 or p <= 0.1`** (2113): `p≥0.9`→Yes @ `p`; `p≤0.1`→No @ `1-p`; the uncertain middle band (or an untaught claim) → **abstain** (None, 2127). The same decisiveness recurs in `_neuro_symbolic`'s `_strength` and `_hybrid`'s entropy check; `_neural_reasoning` sets `confidence = 1 - entropy` (2752).
