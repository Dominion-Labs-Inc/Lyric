# Reasoning — `NeuralSymbolicBridge`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

## `NeuralSymbolicBridge` — the reasoning authority

`core/reasoning/neural_bridge.py` — 4,452 lines. `NeuralSymbolicBridge` at 1052; the singleton `get_neural_bridge()` at 4415.

### 1. Purpose
The **one reasoning authority**. Obtained process-wide via `get_neural_bridge()`, lazily cached. Every request enters from the coordinator: `AutonomousCoordinator.reason_about`  → `bridge.reason(...)` → `_reason_impl`. Stance:
- **Substrate-first and substrate-only** — `_substrate_solvers` runs for *every* request; the eleven kinds run next; a named mode is consulted only when neither settles it. No AUTO mode, no model fallback.
- **Model-free where a model is not the point** — despite the name, it never consults a language model to reason. `_neural_reasoning` is *learned inference over persisted beliefs*, not model inference. `_model_available` is permanently False: the teacher subsystem is retired, and nothing here can reach a model at all.
- **Owns every reasoning MODE** — the `ReasoningMode` routes, the substrate solvers, and (via the abstract engine) the eleven kinds. Also owns the belief graph, abstraction pipeline, and abstract-reasoning engine that used to be driven by the memory agent; single entry to the epistemic + hypothesis services.

Module-scope reason codes: `REASON_SUBSTRATE_VERIFIED/REFUTED/DERIVED_BY_KIND/UNDECIDED/UNSUPPORTED_INPUT/ENTAILMENT_ONLY/CAPABILITY_UNAVAILABLE/INVALID_INPUT/INTERNAL_FAULT/MODEL_COVERAGE/MODEL_FAILED`; metadata keys `KEY_SUBSTRATE_FORMALIZED/TEACHER_AVAILABLE/TEACHER_CONSULTED`; `model_required` a deprecated always-False alias.

### 2. State
`__init__`, populated in `initialize`: `config`/`initialized`; `memory_agent`; owned subsystems `beliefs` (`BayesianUncertaintySystem`), `abstraction` (`AbstractionPipeline`), `abstract_engine` (shared `AbstractReasoningEngine`); `statistics` mode-mix counters; telemetry `_reasoning_telemetry` per-kind `{runs,total_latency,attempts,successes}` + dirty/db/schema flags. Class priors `_DECLARED_DIFFICULTY` + thresholds, quality thresholds, DDLs, `SYMBOLIC_PROOF_TIMEOUT=10.0`, `_SUBCLASS_Q` regex. Lazily builds: the deterministic formalizer chain, and (inside methods) proof engine, constraint solver, learning authority, rule store/inducer, concept-graph reasoning, sense taxonomy, cognitive ingress, formal argumentation, epistemic engine, hypothesis system, domain master.

### 3. Methods by area

#### Entry / orchestration
- **`async reason(request) -> ReasoningResult`** — public entry; timing wrapper over `_reason_impl`; records per-kind latency, then annotates with a `fallacy_warning` (`_check_argument_fallacies`) and `epistemic_uncertainty` (`assess_uncertainty`) — honest annotations that never change the answer.
- **`async _reason_impl(request) -> ReasoningResult`** — the router: init (raises on failure), one-time memory injection (cached claims, or what the memory agent hands over, `MemoryAgent.recall_for`, told the request's complexity as it arrived, `complexity_of`); if `mode != ABSTRACT` runs the named mode via `_run_mode`; else the default pipeline `_substrate_solvers` → `_reason_by_kind` → (on explicit domain intent) `_cross_domain_reasoning` → `_unsettled`. A lossy propositional refutation is deferred past the kinds when the query names kinds/markers/a predicate rule. Any exception → confidence-0 error.
- **`async _run_mode(request) -> Optional[ReasoningResult]`** — runs the named substrate strategy (all model-free): `SYMBOLIC→_substrate_solvers`, `NEURAL→_neural_reasoning`, `HYBRID→_hybrid_reasoning`, `NEURO_SYMBOLIC→_neuro_symbolic_reasoning`, `CROSS_DOMAIN→_cross_domain_reasoning`; None otherwise.
- **`async _reason_by_kind(request) -> Optional[ReasoningResult]`** — runs the eleven kinds through the persistent `abstract_engine`; selects from `request.kinds` else `kinds_of_thinking_for(query)` else `CLASSICAL_REASONING_TYPES`; orders by measured `reasoning_quality`; keeps only on-topic conclusions; picks highest quality-then-confidence; records the QUALITY outcome; surfaces bearing schemas. None (≠ empty) when nothing applies.
- **`_unsettled(request, route) -> ReasoningResult`** — honest inability: empty answer, confidence 0, `reason=REASON_UNSUPPORTED_INPUT`; never handed to a model.
- **`_finish(request, result) -> ReasoningResult`** — single exit: `_update_stats`; for standalone non-empty answers schedules `_capture_reasoning_memory`.
- **`async initialize() -> bool`** — connects memory; takes ownership of belief graph/abstraction/abstract-engine; loads beliefs+schemas; restores telemetry+statistics; registers the periodic persistence flush on the queue authority.

#### Formalization
- **`_get_deterministic_formalizer() -> IFormalizer`** — the model-free `FormalizerChain([Passthrough, DeterministicExtractor, DerivedReading])` the router probes with. `DerivedReadingFormalizer` reads sentences TAUGHT with their meaning (`derived_reader`, since 2026-09-27): a taught ground statement or yes/no question becomes atoms through `clause_atom`, the same vocabulary as held graph facts.
- **`_build_reasoning_context(request, kinds)`** — turns a `ReasoningRequest` into an engine `ReasoningContext`: non-implications → premises+facts, implications → rules, query → target_conclusions (never a fact); `confidence_threshold=0.05`.
- **`async _check_formalizability(answer, request) -> Optional[str]`** — pressures an answer toward the extractor's grammar; returns a restatement request when unformalizable.
- *(Formalizer classes are module-level: `PassthroughFormalizer`, `DeterministicExtractor`, `DerivedReadingFormalizer`, `FormalizerChain`.)*

#### Substrate solvers (model-free)
- **`async _substrate_solvers(request) -> Optional[ReasoningResult]`** — fixed order (order, not privilege): (1) arithmetic `read_equation→_solve_equation`; (2) sequence `read_sequence→_extend_sequence`; (3) `_answer_over_sense_taxonomy`; (4) `_answer_over_concept_graph`; (5) `_answer_over_held_rules`; (6) `_answer_over_induced_rules`; (7) deterministic formalization → `_symbolic_reasoning`. None when nothing formalizes.
- **`async _answer_over_sense_taxonomy(request)`** — sense-exact subclass answer from the QID-keyed graduate taxonomy (`is_subclass`), before the name-keyed concept graph can cross a homonym.
- **`async _answer_over_concept_graph(request)`** — reads the query to a typed (s,r,o) triple (`SentenceReader`) and answers via the typed relation algebra (`answer_over_graph`, hop-bounded to 4). ISA consults the sense taxonomy first; on UNKNOWN ISA consults the belief store (p≥0.9/≤0.1 gate) before abstaining.
- **`async _answer_over_held_rules(request)`** — chains TAUGHT rules: `held_conditionals()` + held facts rendered to one atom vocab (`SentenceReader.clause_atom`), proved with Z3 via `_symbolic_reasoning`. Helper **`_held_rule_chain`** renders the fired chain.
- **`async _answer_over_induced_rules(request)`** — names an instance via a rule the substrate INDUCED (`red & circular -> stop_sign`): loads feature facts, applies non-refuted rules concluding the category (VALIDATED>SUPPORTED>CANDIDATE).
- **`_solve_equation(equation)`** — linear equation via Z3; missing solver → `CAPABILITY_UNAVAILABLE`, unsat → `REFUTED`, solved → `VERIFIED` @1.0.
- **`_extend_sequence(sequence)`** — extends by the induced rule; MULTIPLE_HYPOTHESES/NO_RULE → unsupported; single rule → next term verified @1.0.
- **`async _symbolic_reasoning(request, formalization=None)`** — the solver decides and sets confidence: build a propositional `Theorem`, call the proof engine; proved w/ trusted premises → `VERIFIED`, w/ model-written premises → `ENTAILMENT_ONLY`, not entailed → try the negation (modus tollens) for `Disproved` else `REFUTED`, solver error → `UNDECIDED`. Emits the credit-assignment metadata contract.
- **`async _induce_from_demonstrations(demonstrations, target_predicate)`** — induces a rule from before/action/after demos via the inducer (from the NEURAL route). Helpers `_fact`/`_facts` coerce to `Fact`.

#### Modes (`ReasoningMode` execution routes)
- **`async _neural_reasoning(request)`** — learned inference, model-free: if demos present, induce; else answer from the most relevant Bayesian belief (content-word overlap, ranked by relevance then low entropy), confidence = `1 - entropy`.
- **`async _hybrid_reasoning(request)`** — propose→constrain→revise: derive ranked candidates once, cross-check each with formal constraints, fallacies, and entropy; first clearing all constraints wins, else the least-violating unverified.
- **`async _neuro_symbolic_reasoning(request)`** — ensemble of deductive/inductive/abductive derivations arbitrated formally: derive one per kind → Dung-semantics arbitration (grounded>credulous>defeated) → constraint-solver consistency → combine argument strength (0.4)+consistency (0.3)+base (0.3).
- **`async _cross_domain_reasoning(request)`** — maps structure between named domains via `UniversalDomainMaster` (ANALOGICAL, min_similarity 0.5). Gated by **`_is_cross_domain_request`** — true only when `task_metadata` names source/target domains.

**Routes/kinds owned:** `ReasoningMode` (6, 49-75): SYMBOLIC, NEURAL, HYBRID, NEURO_SYMBOLIC, ABSTRACT (default = the kinds), CROSS_DOMAIN. Substrate solvers (7): arithmetic, sequence, sense-taxonomy, concept-graph, held-rules, induced-rules, symbolic-proof. The eleven kinds (`ReasoningType`): DEDUCTIVE, INDUCTIVE, ABDUCTIVE, ANALOGICAL, CAUSAL, PROBABILISTIC, FUZZY, TEMPORAL, SPATIAL, LOGICAL, COUNTERFACTUAL.

#### Checks / quality
- **`async _check_argument_fallacies(answer, request=None)`** — argumentation-engine fallacy detection over an answer; context supplies premises so correct answers don't trip `begging_question`.
- **`async _check_formal_constraints(answer, request)`** — proves the *negated* goal from context when both formalize; a proof = formal contradiction. Unrepresentable ≠ violation.
- **`_extract_reasoning_steps(response)`** — extracts steps (THINKING sections, numbered lists, "Step N:", decimal-safe sentence split); `[]` never fabricated.
- **`_model_available()`** — **permanently False.** The unified-LLM and teacher subsystem is retired, so no teacher can serve a request. The substrate reasoner is deterministic and never consults a model; this reports only, for a higher layer, that escalating is not possible. `_verify_candidate`, which verified a model-proposed answer, was removed on 2026-09-01: the bridge is model-free by construction, so there are no model proposals to verify.
- How complex a request is, is measured by **`complexity_of`** below, from what the request MEANS, scored once as it arrives. There is no after-the-fact score over steps, context and confidence.

#### Difficulty / quality telemetry
- **`_kind_key`** · **`_kind_cell`** — normalize a kind; its `{runs,total_latency,attempts,successes}` cell.
- **`record_reasoning(kinds, latency_s)`** — grounds difficulty in behaviour (latency per exercised kind, every real call).
- **`record_reasoning_outcome(attempted, winning)`** — which kinds were considered vs settled it (the quality signal).
- **`reasoning_quality(type) -> float`** — measured success rate (`_QUALITY_PRIOR` until `_QUALITY_MIN_ATTEMPTS`).
- **`reasoning_difficulty(type) -> float`** — avg latency normalized to the fastest kind, else the declared prior; read by the coordinator's agent allowance + queue timeout.
- **`complexity_of(text, reading=None, inventory=None, utterances=None) -> float`** — how complex a message, task or request is, measured: the larger of the thinking it asks for (the kinds `kinds_of_thinking_for` reads in its meaning, at their `reasoning_difficulty`, between the easiest kind and the hardest) and what of it is unknown (the share of its words `PatternInventory.knows` does not hold, or of its sentences nothing reads). Scored in `reason` from the question as heard, read once (`_question_heard` returns the utterances too); read by the curiosity a target arouses; not by recall, which what memory holds of a request decides (`MemoryAgent.recall_for`). Replaced the word count the memory injection policy had kept (2026-10-23).

#### Persistence
- **`_telemetry_db_handle`** / **`async _ensure_telemetry_schema`** — lazy handle + DDL.
- **`async load_telemetry`** / **`async flush_telemetry`** — restore/persist measured per-kind behaviour; flush no-ops when unchanged.
- **`async _flush_reasoning_persistence`** — the one scheduled job (queue authority owns cadence): telemetry + statistics.
- **`async get_statistics`** — flat scalar stats for health (quality-loop summary).
- **`async flush_statistics`** / **`async load_statistics`** — mode-mix + avg-confidence counters.
- **`_update_stats(request, result)`** — increments the used-mode counter and running average confidence.

#### Reflection / hypothesis / memory / epistemic tie-in
- **`async abstract_over_memories(memory_dicts) -> Dict[str,int]`** — forms schemas→beliefs from a memory batch via the owned abstraction pipeline (the memory agent *asks*).
- **`async reflect() -> Dict`** — belief-graph hygiene: temporal decay, consistency, domain volatility, schema decay; steps isolated.
- **`async assess_uncertainty(request) -> Dict`** — belief-graph entropy about this query, via the epistemic engine.
- **`async apply_reasoning_output(outputs) -> int`** — folds hypotheses/belief_updates into the belief graph (epistemic engine); returns real mutations.
- **`async epistemic_affect_signal() -> Dict`** — the authority's reading of how the belief graph MOVED since last asked, from **any** source (perception, teaching, reasoning), summarized into the emotional dials (`information_gain`, `uncertainty_reduction`→confidence, `uncertainty_increase`/`contradiction`→doubt+curiosity). Delegates to `EpistemicEngine.interpret_drift()` — a **read-only** entropy diff over the whole graph (primed on first call). This is the knowledge→emotion producer; it interprets what changed, it never writes a belief. The coordinator relays the signal to appraisal; emotion shapes disposition, never a core decision.
- **`_coerce_predictions(value, *, field)`** — normalize predictions/alternatives to non-empty strings.
- **`async generate_hypothesis(*, claim, domain, predictions, alternatives) -> Optional[str]`** — generates+persists a falsifiable hypothesis (single entry, e.g. intrinsic motivation).
- **`async observe_tool_result(tool_name, parameters, output, success) -> int`** — folds a tool observation into the belief graph (executor post-tool seam).
- **`async _capture_reasoning_memory(request, result)`** — background, never-raising hand-over to the memory agent: the reasoning as an experience, and what was reasoned (`MemoryAgent.take_in_reasoning`: steps, answer, confidence, kind, verified, its reason), which decides whether its trace is kept, how important it is and what kind of memory it is.
- **`_schemas_bearing_on(query)`** — learned schemas whose terms overlap the query.
- *(Module helpers: `_is_implication`, `_content_terms`, `_query_topic`, `_relevant_to_topic` 279.)*

### 4. Feeds / feeds-into
**Called by:** coordinator (`reason_about` 3332 → `bridge.reason` 3385; holds `self.neural_bridge` 1048; routes `observe_tool_result` 11857; `agent_allowance` reads `reasoning_difficulty`); executor (post-tool seam); memory agent (memory_agent.py:3767 asks `abstract_over_memories`/`reflect`); queue authority (queue_authority.py:548 drives `_flush_reasoning_persistence`); `reasoning_tools`, `health_monitor` (probes `get_statistics`), `intrinsic_motivation` (`generate_hypothesis`), `abstract_reasoning_engine`, `causal_feedback_analyzer`, `capability_benchmark_suite`, `enhanced_asi_self_improvement`.
**Reads:** belief graph (`get_uncertainty_system`, owned + re-fetched 2720/2880); concept graph, sense taxonomy, held conditionals (ingress), rule store, proof engine, constraint solver, learning authority, argumentation engine, epistemic engine, hypothesis system, domain master.
**The posterior gate (p≥0.9 / p≤0.1):** in `_answer_over_concept_graph`, when the bounded closure returns UNKNOWN for an ISA question, it reads the taught claim's `posterior_probability` and answers only when decisive — **`if p >= 0.9 or p <= 0.1`**: `p≥0.9`→Yes @ `p`; `p≤0.1`→No @ `1-p`; the uncertain middle band (or an untaught claim) → **abstain** (None,). The same decisiveness recurs in `_neuro_symbolic`'s `_strength` and `_hybrid`'s entropy check; `_neural_reasoning` sets `confidence = 1 - entropy`.
