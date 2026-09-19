# The Unified Substrate — Systems Map

*Current-state map of the four systems and every method, grouped by pipeline.
It is all in the one coordinator: each faculty (reasoning, learning, memory,
execution, domain, intrinsic motivation, the self) has its own pipeline, and the
coordinator is the substrate. Line numbers are current as of this writing.
Pipelines marked **[live ✓]** were exercised end-to-end on the running system in
`experiments/systems/VERIFY-01` (model-free where a model is not the point).*

Files:
- coordinator/substrate — `core/agents/autonomous/autonomous_coordinator.py`
- reasoning — `core/reasoning/neural_bridge.py` (`NeuralSymbolicBridge`)
- learning — `core/learning/unified_learning_system.py` (`UnifiedLearningSystem`)
- memory — `core/agents/memory_agent.py` (`MemoryAgent`)

---

## 1. Reasoning pipeline  [live ✓]
`NeuralSymbolicBridge`, entered from the coordinator via `reason_about` → `neural_bridge.reason`. Substrate-first, no model fallback.

- **Entry / orchestration:** `reason` (1359), `_reason_impl` (1408), `_run_mode` (1916), `_reason_by_kind` (3187), `_finish` (1325), `initialize` (1232)
- **Formalization (question → logic):** `formalize` (the formalizer set: 332/462/712/764), `_get_deterministic_formalizer` (2346), `_build_reasoning_context` (3098), `_schemas_bearing_on` (3164), `_check_formalizability` (1733), `_check_formal_constraints` (1772), `_connectivity` (617), `_atom` (655)
- **Substrate solvers (model-free):** `_substrate_solvers` (2257), `_answer_over_sense_taxonomy` (1963), `_answer_over_concept_graph` (2011), `_answer_over_held_rules` (2123), `_held_rule_chain` (2237), `_symbolic_reasoning` (2360), `_solve_equation` (1825), `_extend_sequence` (1874), `_induce_from_demonstrations` (2632)
- **Modes:** `_neural_reasoning` (2542), `_hybrid_reasoning` (2711), `_neuro_symbolic_reasoning` (2845), `_cross_domain_reasoning` (3330), `_is_cross_domain_request` (3317)
- **Checks / quality:** `_check_argument_fallacies` (1690), `assess_uncertainty` (1080), `_unsettled` (1936), `_calculate_complexity_score` (3534), `reasoning_quality` (888), `reasoning_difficulty` (897), `_model_available` (1676)
- **Routing / telemetry:** `record_reasoning` (848), `record_reasoning_outcome` (869), `_update_stats` (3400), `_kind_key`/`_kind_cell` (834/837), `load_telemetry`/`flush_telemetry` (958/985), `get_statistics`/`flush_statistics`/`load_statistics` (3583/3610/3632)
- **Reflection / hypothesis / memory tie-in:** `reflect` (1041), `abstract_over_memories` (1028), `generate_hypothesis` (1141), `apply_reasoning_output` (1091), `observe_tool_result` (1170), `_extract_reasoning_steps` (1607), `_capture_reasoning_memory` (3428)

## 2. Learning pipeline  [live ✓ — beliefs]
`UnifiedLearningSystem` (`coord.learning`). The one learning authority; driven by acting/experience.

- **Lifecycle:** `__init__` (287), `start` (408), `initialize` (1040), `shutdown` (2860), `scoped` (227)
- **Ingestion fan-out (facts/rules/words → reasoning+beliefs+lexicon+domain+memory):** `learn_fact` (2111), `learn_facts` (2141), `learn_concept` (2192), `learn_rule` (2223), `learn_word`/`learn_words` (2254/2265), `learn_with_domain_context` (1839), `fan_out_ingested` (2375), `_fan_out_learning` (2407)
- **Experience learning:** `learn_from_experience` (1075), `learn_from_example` (566), `learn_from_data` (1049), `learn_from_event` (1268), `learn_from_feedback` (1079), `process_experience` (1325), `process_interaction` (1016), `query_experiences` (1381), `get_experience_count` (1435)
- **Operator induction (growth loop):** `induce` (2090), `record` (2094), `record_demonstration` (2486), `reinduce_operator` (2497), `drain_pending_induction` (2505), `_induce_signature` (2539), `_project_operator_to_concepts` (2605), `induce_causal_structure` (2648), `induce_sequence_rule` (2687), `derive_procedure` (2636), `inducer` (2076)
- **Beliefs (belief substrate interface):** `create_belief` (2297), `update_belief` (2324), `get_belief` (2333), `belief_for_claim` (2339), `beliefs_for_domain` (2345), `flush_belief` (2351), `observe_claim` (2358)
- **Transfer / cross-domain:** `transfer_learning` (1164), `_transfer_from_known_domains` (1468), `transfer_learning_across_domains` (1616), `get_domain_learning_stats` (2044)
- **Candidate/contribution model:** `contribute` (2743), `admit_projection` (2792), `admissions` (2843), `register_contributor` (2081), `contributors` (2087), `rules` (2847), `store` (2070)
- **Prediction / metrics / self-improvement:** `predict_outcome` (1455), `predict_optimal_retry_delay` (1314), `recommend_strategies` (1343), `update_strategy_effectiveness` (1330), `metrics` (2850), `get_learning_metrics` (1203), `get_learning_state` (1238), `get_system_status` (1027), `consolidate_learning` (1258), `drain_events` (1354), `run_self_improvement_cycle` (2465), `knowledge_base_size` (1176), `is_knowledge` (279)

## 3. Memory pipeline  [live ✓ — retrieval]
`MemoryAgent` (`coord.memory`).

- **Lifecycle:** `__init__` (79), `initialize` (149), `start_memory_loops`/`stop_memory_loops` (3531/3551), `_maintenance_loop` (3564), `cleanup_cache` (3016)
- **Write:** `store_memory` (377), `enqueue_memory` (240), `_write_queue_worker` (280), `store_batch` (1022), `capture_task_outcome` (893), `note_episodic_stored` (3603), `bulk_import` (1811)
- **Worthiness / typing:** `_generate_worthiness_metadata` (1062), `_infer_memory_type` (1350), `_readable_claim` (319)
- **Read:** `retrieve` (2024), `retrieve_memory` (1899), `search_memories` (2280), `query_by_tags` (2344), `get_recent_memories` (1970), `get_memory_by_content` (2376), `retrieve_from_archive` (2869)
- **Consolidation / abstraction:** `consolidate_memories` (3648), `_find_similar_memories` (1440), `_merge_memory_content` (1497), `_cluster_by_similarity` (1618), `_consolidate_cluster` (1745), `consolidate_old_duplicates` (2910), `form_abstractions` (3728), `form_abstractions_if_due` (3741), `_run_abstraction_then_reflect` (3625), `reflect_on_beliefs` (3870)
- **Lifecycle / tiers / edits:** `update_memory` (2514), `update_importance` (2585), `update_tags` (2624), `update_metadata` (2690), `add_related_memory` (2660), `increment_access_count` (2555), `claim_tags` (2430), `find_open`/`close_open` (2446/2498), `supersede` (2454), `migrate_to_cold_tier` (2829), `delete_memory` (2730), `permanent_delete` (2777)
- **Governance (token-protected deletes):** `validate_governance_compliance`, `get_governance_status`, `_validate_capability_token`
- **Metrics:** `get_metrics` (3002)

## 4. The substrate — AutonomousCoordinator
All pipelines live here. Grouped by sub-pipeline.

- **Lifecycle:** `__init__` (284), `initialize` (916), `start_coordination` (1293), `start_background_tasks` (1330), `shutdown` (10355), `initialize_execution_faculty` (10903), `get_status` (11970), `get_intelligence_capabilities` (10418), `to_dict` (14117)
- **Event dispatch / reactive spine:** `on` (1620), `emit` (1646), `register_completion_callback` (1571), `_start_reactive_worker` (1674), `_reactive_drain_worker` (1680), `_execute_completion_callbacks` (8840); reactions: `_react_affect` (1702), `_react_integrity_reaudit` (1818), `_react_competence_changed` (1830), `_react_induce` (1859), `_react_expand_outcome` (1886), `_react_resolve_transfers` (1914), `_react_crystallize_taught` (1923), `_react_job_completed` (4302), `_react_close_deficit` (4331)
- **Reasoning (entry)  [live ✓]:** `reason_about` (3262), `perform_cross_domain_reasoning` (3423), `_predict_and_resolve_system_state` (7205), `_answer_from_what_is_held` (9010), `_model_calls_on` (3359)
  - *Vestigial (present but 0 callers, not registered — NOT live):* `predict_system_behavior` (3374), `make_enhanced_prediction` (3547), `get_domain_insights` (3615). Reachable only if called directly; nothing in the running substrate calls them.
- **Execution faculty  [live ✓]:** `execute_task` (11908), `_execute_grounded_operator` (11219), `_drive_substrate_goal` (11093), `_execute_operation` (11760), `_execute_declared_tools` (11788), `_answer_via_knowledge_loop` (11852), `_run_tool` (11607), `_execute_and_validate_task` (8022), `_observe_world` (10984), `_derive_goal_spec` (11000), `_get_planning_engine` (11074), `_execute_drive_goal` (6046), `_record_execution_demonstration` (11455), `_appraise_substrate_execution` (11555), `_appraise_tool_outcome` (11678), `_record_tool_metrics` (11721), `_observe_tool_belief` (11744)
- **Completion as grounded belief:** `_derive_completion_anchor` (7615), `_mint_completion_belief` (7642), `_observe_completion_evidence` (7683), `_gather_did_evidence` (7723), `_did_intent_achieved` (7767), `_saw_reobserve` (7779), `_saw_memory_holds` (7819), `_independent_groundings` (7831), `_decide_completion` (7845), `_completion_domain` (7599), `_extract_task_outcome` (7871), `_recall_similar_task_experience` (7899), `_select_retry_method` (7954)
- **Learning (coordinator side):** `_learning_phase` (9625), `_apply_learning_recommendation` (10176), `_idle_operator_induction_work` (5928), `_idle_operator_exploration_work` (5859), `_idle_analogy_discovery_work` (5958), `_run_exploration_cycle` (6600), `_rule_root_count` (6034)
- **Domain (one authority; automatic creation):** `_idle_domain_expansion_work` (5653), `_expand_one_outcome` (5757), `_idle_domain_discovery_work` (5827), `_resolve_transfer_outcomes` (6185), `_task_outcomes_by_field` (6290), `_infer_domain_from_task` (2573), `_react_crystallize_taught` (1923)
- **Intrinsic motivation / goals  [live ✓]:** `generate_curiosity_driven_goals` (2048), `set_goal` (2003), `extract_state_conditions` (1972), `motivation` (3693), `_refresh_motivation_signals` (4142), `_coalesced_motivation_refresh` (1844), `_run_idle_exploration` (4536), `_should_trigger_curiosity_optimization` (6961), `_curiosity_driven_optimization` (6987), `_analyze_for_goal_creation` (10156), `_collect_system_context_for_goals` (9237), `_register_deficit_unknown` (4452), `_deficit_is_closed` (4484)
- **Memory (coordinator side):** `store_memory` (2318), `search_memories` (2656), `_build_memory_narrative` (2144), `get_intelligent_memory_context` (3133), `_store_task_outcome_meta_memory` (2475), `_store_governance_block_meta_memory` (2414), `_idle_memory_work` (6524), `_idle_abstraction_work` (6490)
- **The Self / identity / affect:** `_appraisal` (3679), `_arbiter` (3684), `_constitution` (3689), `_interoception` (3715), `_attitude` (3726), `_temperament` (3737), `_drives` (3742), `_values` (3752), `_competence` (3757), `_purpose` (3777), `_continuity` (3793), `disposition` (3810), `state` (3846), `_affect_snapshot` (3863), `render` (3877), `identity_prompt` (3926), `_describe_attitude` (3938)
- **Life loop / scheduling / idle tiers:** `_coordination_cycle` (4010), `apply_throttle` (4126), `_run_system_awareness_cycle` (4186), `_launch_task` (4232), `_reap_finished_tasks` (4261), `_collect_finished_jobs` (4279), `_register_idle_subsystems` (4554), `_handle_idle_state` (9405), `_mark_reflection_due` (4507), `_prune_step_execution_log` (4519); tiers: `_idle_security_work` (4681), `_idle_health_work` (4821), `_idle_system_review_work` (5048), `_idle_knowledge_refresh_work` (5183), `_idle_self_improvement_work` (5532), `_idle_meta_learning_work` (6331), `_idle_memory_work` (6524), `_idle_self_optimization_work` (6893)
- **Meta-learning / adaptive:** `_record_adaptive_type_outcome` (7373), `_record_experience_outcome` (7458), `_select_adaptive_task_type` (7489), `_task_family_for` (7348), `_decision_context` (7310), `_get_recent_task_outcomes` (9584), `_observe_system_performance` (7188)
- **Governance / constitution / directives:** `_check_constitutional_alignment` (9410), `_check_constitutional_alignment_quick` (9547), `_refresh_directive_guidance` (3829), `_propose_directive_improvements` (7068), `handle_security_finding` (9079), `_on_security_remediation_complete` (10792)
- **Health / recovery (event-driven):** `_receive_health_event` (10443), `_diagnose_health` (10664), `_health_action_risk` (10722), `_execute_recovery` (10735), `_verify_recovery` (10872), `_create_recovery_goal_from_health_event` (9560)
- **Knowledge refresh (research cadence):** `_idle_knowledge_refresh_work` (5183), `_load_knowledge_cutoff_state` (5326), `_save_knowledge_cutoff_state` (5358), `_get_declared_model_cutoff_date` (5425), `_get_knowledge_cutoff_snapshot` (5449), `_on_knowledge_refresh_complete` (5475)
- **Capability registry / agents-of-self:** `register_capability` (1471), `unregister_capability` (1555), `_execute_registered_capabilities` (9779), `_check_capability_conditions` (9942), `deploy_agent` (1385), `await_agent` (1409), `collect_agent_findings` (1417), `pending_agents` (1426), `_calculate_exploration_quota` (1457), `_record_exploration_decision` (1441)
- **Handlers / status:** `handle_user_request` (8891), `process_input` (1946), `_request_kind` (8995), `_handle_error` (7144), `get_system_status` (3952), `_update_system_state` (10295), `model_available` (3237), `agent_allowance` (3243), `_check_task_completions` (10035)

## 5. Conversation pipeline  [live ✓ via execution knowledge-loop]
`Conversation` (same file, 12330+): the language-facing pipeline into the substrate.
- **Speak / understand:** `teach` (13294), `understand` (13616), `look_up` (13386), `say` (13830), `natural_reply` (13799), `classify` (13589), `is_question` (13488), `read` (12781), `asked` (12799)
- **Recall / resolve:** `recall` (12771), `recalling` (12764), `resolve` (12574), `subject_of` (12676), `_incoming_relations` (12534), `_concept` (12527), `about_this_conversation` (12690), `_from_the_record` (12721)
- **Ingest / gaps / reasoning:** `_ingest` (13179), `_register_domain_gap` (13227), `_held_premises` (12990), `_reasoned_answers` (13056), `_grounded` (12953), `_affirmed` (12972), `_support_used` (12928), `_render_atom` (12917)
- **User model + feedback (the third channel):** `beliefs_about_user` (12460), `_learn_about_user` (12434), `_ensure_user_beliefs` (12412), `_about_speaker` (12405), `_admissible_world_fact` (12472), `feedback_of` (13530), `_take_feedback` (13547), `_feedback_referent` (13518), `_read_disposition` (13501)

---

---

## Wiredness review (verified against current callers, not the stale plan file)

The map was checked against actual call sites in today's code — the honest
unified-running vs. present-but-dead split the architecture paper turns on:

**Wired into the running substrate (live):**
- Reactive event spine — `emit` has 15 call sites; the drain worker is started at boot.
- **Completion as grounded belief** — `_mint`/`_observe`/`_decide` are called inside `_execute_and_validate_task` (8173/8190/8191), i.e. on every executed task.
- **The Self / identity** — `render` has 10 call sites; `disposition` 5.
- **Constitution** — `_check_constitutional_alignment` runs as the `idle_constitution_check` tier (4656). *(This corrects the earlier internal note that it was dead — against current code it is wired.)*
- **Health / recovery** — `_receive_health_event` wired via the monitoring callback.
- **All 13 idle tiers registered** in `_register_idle_subsystems`: security, health, system_review, knowledge_refresh, self_improvement, meta_learning, memory, self_optimization, domain_expansion, domain_discovery, operator_exploration, operator_induction, analogy_discovery.
- The 7 pipeline entries exercised end-to-end in VERIFY-01 (reasoning, execution, cross-domain, domain, learning+beliefs, intrinsic motivation, memory), model-free where a model is not the point.

**Present but NOT wired (vestigial — 0 callers, not registered):**
- `predict_system_behavior`, `make_enhanced_prediction`, `get_domain_insights` — prediction APIs nothing calls.

**Method that caveats the caller-count tool:** callback-registered methods (the `_idle_*` tiers) show 0 direct callers because they are passed by reference to the capability registry, not called with `()` — they are live via the scheduler. Counter-signal used: presence in `_register_idle_subsystems`.

*Verified live end-to-end on the current system (VERIFY-01): reasoning, execution,
cross-domain, domain, learning+beliefs, intrinsic motivation, memory. This map is
the method inventory behind that, with the wiredness of every region checked
against current call sites.*

---

## Authorities — one owner per subsystem (audit 2026-09-09)

A snapshot of the substrate expressed as authorities: the single class that owns each
subsystem, its singleton accessor, and whether it owns all routes for its subsystem.

| Subsystem | Authority (accessor) | File |
|---|---|---|
| learning | `UnifiedLearningSystem` — `get_learning_authority()` / `get_unified_learning_system()` | `core/learning/unified_learning_system.py` |
| reasoning | `NeuralSymbolicBridge` — `get_neural_bridge()` (owns every reasoning mode) | `core/reasoning/neural_bridge.py` |
| memory | **`MemoryAgent`** — `get_memory_agent()` (async; owns store + worthiness-filter + type-inference + query) | `core/agents/memory_agent.py` |
| beliefs | `BayesianUncertaintySystem` — `get_uncertainty_system()` (the one-door belief store) | `core/reasoning/bayesian_uncertainty.py` |
| domain | `UniversalDomainMaster` — `get_universal_domain_master()` | `core/integration/universal_domain_master.py` |
| semantics (write) | `CognitiveIngress` — `get_cognitive_ingress()` (admit/relation/conditional) | `core/semantics/cognitive_ingress.py` |
| internal safety | `SafetyFramework` — `get_safety_framework()` (the gate: input validation, ASI assessment, RuntimeGovernance) | `core/security/safety_framework.py` |
| control plane / self | `AutonomousCoordinator` — `get_autonomous_coordinator()` (holds every authority; task queue → `QueueAuthority`) | `core/agents/autonomous/autonomous_coordinator.py` |

Belief ops on the learning authority delegate to the single `BayesianUncertaintySystem`, so
reasoning conclusions, taught facts, and perceptions all move ONE belief store through ONE door.
The coordinator is the *main* learning entry ("the pipeline starts at the coordinator, except
health metrics") but not the *sole* one (seam 4).

### Seams — where "one substrate expressed as authorities" breaks in code (ranked)
1. **`core/domain/` has no authority in its own folder.** Owner `UniversalDomainMaster` lives in
   `core/integration/`; `core/domain/` is a bag of unowned services (registry, concept_ingestion,
   grounding, ontology, evidence_producers) with no authority getter.
2. **`core/security/` is mid-rework.** The live internal gate is `SafetyFramework`; the old perimeter is
   archived in `_disabled/`; `threat_intelligence` + `active_defense_types` wait to be consolidated
   into the coordinator; `get_integrated_security_system()` is a None-returning stub.
3. **Direct concept-graph writes bypass the learning fan-out** — producers call
   `concept_ingestion.ingest` directly; `fan_out_ingested` exists only to retro-repair this.
4. **Coordinator is not the SOLE learning entry** — `analogy_discovery`, `hypothesis_testing`,
   `evidence_producers`, `derived_reader`, `list_synthesis` reach `get_learning_authority()`
   directly (they honor the authority, but not coordinator-as-sole-entry).
5. **Semantics split** — write-side owned (`CognitiveIngress`); read-side fragmented (no reading
   authority; sentence_reader/machine/registry/lexicon loose).
6. **Memory class misfiled** — `MemoryAgent` lives in `core/agents/`, not `core/memory/` (which
   holds a dead `AsyncMemoryAgent` stub); legacy aliases (`MemoryManager`/`CentralizedMemoryManager`/
   `UnifiedMemorySystem`) blur the one-name ideal.

### Honesty of failure — audit
Design intent ("each system is honest about failures; no masking; honest metrics") is
**substantially upheld and actively engineered.** The anti-masking primitive
`raise_if_structural` (`core/capability.py`) re-raises wiring bugs
(`AttributeError/NameError/ImportError/TypeError`) so a broken thing can't be logged as an
ordinary "no" — used 14× in learning, 14× in the coordinator, 7× in the domain master. Confirmed
honest: verdict-carrying transfer-learning; ingress declines surfaced as refusals; three-state
subsystem-readiness (attached vs initialized vs "doesn't say"); health path refuses to assume
health; bridge honest `None` fall-through; tool execution honors the tool's real `success`. **No
masked `success:True` found in any audited authority.**

**One concrete gap — the belief authority itself.** `bayesian_uncertainty.py` is the architectural
model of the ideal (one-door funnel) yet the single file that violates the honesty doctrine: it
uses `raise_if_structural` **zero times** and its broad handlers return zeroed-stat dicts on failure
(`apply_belief_decay`, `check_belief_consistency`, `update_domain_volatility` — `0 = crashed` reads
as `0 = nothing to do`). Two metric bugs: `beliefs_removed` counts neutral beliefs that were *kept*
(inverse of its name); `avg_volatility: 0.01` is a fabricated healthy-looking default on failure
rather than `None`. **Bounded fix:** adopt the guard + correct the two metrics. Matters because
everything leans on beliefs.
