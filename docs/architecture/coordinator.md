# The body / control plane — `AutonomousCoordinator`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the body changes. Line numbers drift; the explanations must stay true.*

## `AutonomousCoordinator` — the body and self

*`core/agents/autonomous/autonomous_coordinator.py` (~14,220 lines; class L267–L12094).
Module helpers: `_subsystem_readiness` (100), `SelfEventType` (122), `SelfEvent` (181), `Evidence` (194), `_tool_resource` (257). The conversation/language faculty (`Conversation`, `SelfState`, `say`) lives below the class (L12216+), reached via `conversation()`.*

### 1. Purpose
The coordinator **is the substrate's body and self**: one process that *holds* every faculty-authority as a handle and reaches each faculty *through* itself rather than constructing a rival. "The coordinator is the BODY"; "EXECUTION is the self's own faculty" — the state that used to live in a separate `GeneralPurposeExecutor` was absorbed here (580-595). It holds the language model only as an optional teacher, never its brain (291-304); every substrate path is model-free and reports an honest capability fault rather than falling back.
Authorities held: `self.learning` (355, the one `UnifiedLearningSystem`), `self.memory` (672/946), `self.neural_bridge` (707/1048), `self.universal_domain_master` (773/1049), `self.security_controller` (836). The belief store is reached via `self.learning`, not a separate handle.
Accessor: `get_autonomous_coordinator(config, teacher_model)` (L12095, async singleton; returns a coordinator with OR without a model — the "LLM is mandatory" rule was removed).

### 2. State
**Held authorities/subsystems** (`self.X = get_Y()`): `coordinator_config` (307), `circuit_breakers` (311), `perception` (340), `vision` (345), `planning` (346), **`learning` (355)**, `intrinsic_motivation` (377), `directive_system` (534), awareness layers (540-550), `runtime_governance` (553), `constitution` (557), `safety_prompts` (562), **`task_queue` = `get_queue_authority()` (576, the shared QueueAuthority — backlog, concurrency pool, await-jobs, idle scheduling)**, `db` (584), reasoning toolkit (691-700), `neural_bridge` (707→1048), `intelligence`/`watchdog` (721-722), cognitive toolkit (730-765), `domain_registry` (772), `universal_domain_master` (773→1049), `health_monitor` (782), `recovery_manager` (800), `log_db` (817), `security_controller` (836), `monitoring_coordinator` (840, wires `singleton_callback=self._receive_health_event` at 846), `slack_notifier` (852); injected by main.py: `memory_injector` (681), `asi_self_improvement` (713), `governance` (718→2775), `agent_coordinator` (858); `tool_registry` (585→11012), `memory` (672/675→946).
**Own self-state:** `system_state` (336), `stats` (865-895, honest counters incl. reactive), `reply_debug` (359), `_started_at_ts` (289), `teacher_model` (304). The self is **derived, not stored** — assembled on demand by `state()`.
**Event registries:** `_completion_callbacks` (410), `_reactions`/`_reactive_queue`/`_work_ready`/`_reactive_worker`/`_emit_depth`+`_max_emit_depth=8` (418-423), coalescing (`_motivation_dirty`/`_motivation_refresh_task` 430-431), integrity watcher (438).
**Task/execution state:** `_inflight_tasks`, `_max_parallel_tasks`=3, directive caps (628-637); exploration state (588-622); `_idle_subsystems_registered` (623); per-tier timestamps/snapshots (646-919); `_step_execution_log` (641); `_component_recovery_state` (667).
**Registered at construction:** one completion callback (`RESEARCH/AUTONOMOUS→_on_knowledge_refresh_complete`) and **seven reactions** via `on(...)`: `TASK_COMPLETED→_react_affect` (460), `OUTCOME_OBSERVED→_react_induce/_react_expand_outcome/_react_resolve_transfers` (469-478), `EVIDENCE_ADMITTED→_react_crystallize_taught` (486), `JOB_COMPLETED→_react_job_completed` (494), `COMPETENCE_CHANGED→_react_competence_changed` (503), `INTEGRITY_REAUDIT→_react_integrity_reaudit` (511), `DEFICIT_DIAGNOSED→_react_close_deficit` (530).

### 3. Methods by region

#### A — Lifecycle & the coordination loop
- **`__init__(config, teacher_model)`** (284) — wires every authority, registers callbacks+reactions, sets up the queue authority. Model-optional.
- **`initialize(start_loop=False)`** (921) — async bring-up; binds memory (946), neural_bridge/domain_master (1048-1049); no model connected.
- **`start_coordination()`** (1298) / **`start_background_tasks()`** (1335, calls `_register_idle_subsystems` + starts the queue scheduler).
- **`_coordination_cycle()`** (4080) — the cognition loop: dequeue an extrinsic task only when a slot is free (`_effective_max_parallel`), **launch not await** (`_launch_task`), run idle exploration when idle, reap tasks, collect jobs. All 15+ timed tiers moved OFF this loop onto the queue scheduler (Phase-5 poll retirement).
- **`_launch_task`** (4302) · **`_reap_finished_tasks`** (4331) · **`_collect_finished_jobs`** (4349, surfaces `JOB_COMPLETED`) · **`apply_throttle`** (4196) · **`_handle_error`** (7214) · **`shutdown()`** (10461).

#### B — The self / identity (derived, None-honest)
- **`state()`** (3916) — compose the current self from the faculties; honest about missing pieces.
- **`render(audience="human")`** (3947) — the self as language, from `state()`, no model.
- **`identity_prompt(role=None)`** (3996) — a stable model-facing identity seed.
- **`disposition(*, slots_available, queue_pressure)`** (3880) — standing disposition → a `BehavioralDirective`.
- Accessors: `_appraisal`/`_arbiter`/`_constitution` (3749/3754/3759), `_temperament` (3807), `_competence` (3827, VALIDATED operators per domain), `_purpose` (3847, ACTIVE directives), `_attitude` (3796, None if unappraised), `_interoception` (3785), `_drives`/`_values`/`_continuity`/`motivation` (3812/3822/3863/3763), `_affect_snapshot` (3933), `_describe_attitude` (4008), `_refresh_directive_guidance` (3899), `_effective_max_parallel` (3891).
- **`_update_system_state()`** (10401) — the **sole writer** of `system_state.resource_usage`/metrics the constitution reads; idle tier `idle_system_state_refresh`.
- `get_system_status` (4022) · `get_status` (12071) · `get_intelligence_capabilities` (10524).

#### B2 — KNOW→DO operability (the hybrid, domain-dependent bar)
*Can the self OPERATE in a domain yet? A pure MEASUREMENT (`operable=False` ⇒ abstain + keep researching); the authority-side signals live in [domain.md](domain.md). Benchmarks: `experiments/OPERABILITY-BAR-01`, `experiments/BORROWED-KNOWLEDGE-01`. Full design: `docs/INTRINSIC_MOTIVATION_REDESIGN.md`.*
- **`_domain_satisfaction(domain_id)`** — the KNOW side: knowledge COVERAGE (`structural_complexity`) **noisy-OR** belief CONFIDENCE (`1 − mean entropy`), `None` if unknown.
- **`_domain_stakes(domain_id)`** + `_ACTION_STAKES` (investigate .2 → execute .95) — the bar's base from the domain's operators' `ActionClass` (`action_consequence._declared_consequence`); neutral 0.5 where no operator resolves (**inert on current data — 0/94 domains have executable operators**).
- **`_borrowed_satisfaction(domain_id)`** + `_BORROW_REL_MIN=0.30`/`_BORROW_NEIGHBORS=5`/`_BORROW_CAP=0.5` — cross-domain transfer on the KNOW side: confidently-related KNOWN domains (`udm.similar_domains`) each lend `similarity × neighbor's OWN satisfaction` (ONE hop), noisy-OR'd, capped. **LIVE on 83/94 domains** (unlike stakes). Distinct from operator transfer (`transfer_relation`).
- **`async _domain_operability(domain_id)`** + `_OPERABILITY_BAND=0.3`/`_FLOOR=0.2`/`_CEIL=0.99` — composes it: `bar = clamp(stakes − BAND·(earned−0.5), FLOOR, CEIL)` (earned = `udm.operating_reliability`, Wilson lower bound); `effective = noisy-OR(own, borrowed)`; `operable = effective ≥ bar`. Reports own/borrowed/effective separately; reasons `unknown-domain` / `satisfied` / `satisfied-via-transfer` / `below-bar-researching|earning`.

#### C — Execution faculty (substrate-first, model-free)
- **`execute_task(task)`** (12009) — public entry (agent factory `agents.py:303`, experiments): `_execute_grounded_operator` → `_drive_substrate_goal` → `_execute_operation`; else an **honest gap** (`success:False, model_free:True`).
- **`_execute_and_validate_task(task)`** (8128, ~820 lines, largest) — the real per-task path (from `_launch_task`); executes then decides completion from the task's completion belief `G` (no separate validator); binds the per-task `ActionContract`. **Producer of the EARNED operability signal:** records `udm.record_operating_outcome(domain, success)` for domain-tagged NON-drive tasks (domain from `provenance` OR `metadata`; drive goals feed competence — see B2). `success` = the goal-holds posterior ≥ 0.5 (operating-CORRECTNESS), not the cautious ~0.95 done-acceptance — so correct-but-not-yet-accepted work still earns operating trust. Full loop proven end-to-end in `experiments/INTEGRATION-LOOP-01` (6/6, real coordinator + world).
- **`_execute_grounded_operator(task)`** (11320) — deterministic execution of a VALIDATED operator; re-establishes authority + world vs *current* state.
- **`_drive_substrate_goal(task)`** (11194) — plans a STATE goal over learned operators; the re-observed world decides success.
- **`_execute_operation(task)`** (11861) — the ONE operation path (no per-TaskType switch): declared tools or the knowledge loop.
- `_execute_declared_tools` (11889) · `_answer_via_knowledge_loop` (11953, via the single `understand` loop) · `_run_tool` (11708) · `_appraise_tool_outcome` (11779) · `_observe_tool_belief` (11845) · `_record_tool_metrics` (11822) · `_record_execution_demonstration` (11556) · `_appraise_substrate_execution` (11656) · `_execute_drive_goal` (6116, an intrinsic DRIVE goal as real learning).
- Bring-up: `initialize_execution_faculty` (11004, binds `tool_registry`), `_ensure_dotenv_loaded` (11027), `_config_value` (11069), `_observe_world` (11085), `_derive_goal_spec` (11101), `_get_planning_engine` (11175).
- Adaptive type/experience: `_task_family_for`, `_record_adaptive_type_outcome`, `_record_experience_outcome`, **`_select_adaptive_task_type`** (the MetaLearner's CONTROL `tasktype:` arms; **None when no arm passes the production gate** — the exploration cycle then queues no task for that goal this cycle, and the decision still counts toward the exploration budget; the keyword match on the description that used to answer is deleted), `_recall_similar_task_experience` (8005), `_select_retry_method` (8060), `_extract_task_outcome` (7977).

#### D — Grounded completion (DID / SAW belief pipeline)
- **`knowledge_domain_of(task_type, declared_domain)`** / **`_task_domain(task)`** — the knowledge domain a task acts in, from what the task IS: a declared `domain_id`, else None. Replaced a keyword classifier over the description, which filed every remediation (its contract text says "investigate") under `scientific` → biology. Task outcome records carry it as `knowledge_domain`; `_expand_one_outcome` and `_task_outcomes_by_field` derive it the same way for old records and mark an outcome with no domain `no_knowledge_domain`. · `_completion_domain` (operation bucket: `op:<tools>`, else the task's domain, else `task:<type>`) · **`_derive_completion_anchor`** (7685, the proposition `G`) · **`_mint_completion_belief`** (7712, LOW prior in the task's domain) · **`_observe_completion_evidence`** (7753, moves on INDEPENDENT groundings only) · **`_gather_did_evidence`** (7793, DID = the intervention's own report) · `_did_intent_achieved` (7837) · **`_saw_reobserve`** (7849, SAW = a fresh independent measurement — re-observes filesystem tools by `intervention_target`, learned facts by re-retrieval, AND a grounded operator's world effects via a FRESH `get_binding_registry().observe_world(domain)`: without that last path a grounded op had only DID≈0.72 and could never reach the 0.95 band, so verified successes were marked failed — see INTEGRATION-LOOP-01) · `_saw_memory_holds` (7889) · **`_independent_groundings`** (7901, drop derived/group) · **`_decide_completion`** (7915, DONE iff `G`'s posterior reaches the acceptance band).
- **`perceive(classifier, instance, instance_id, ...)`** (7967) — the one recognition primitive: recognize AND let confidence govern ACT / VERIFY / ABSTAIN against the completion acceptance band, then **emit `PERCEPT_RECOGNIZED`** so the decision governs behaviour via the spine (no caller re-decides). WIRED: called by `see` when a recognizer is attached (`attach_recognizer`), and reachable directly. Records the recognition into the perceptual awareness hub (awareness-only).
- **`attach_recognizer(domain, classifier)`** (8031) — wire a route's sensation to its recognition; a classifier attached to a domain makes `see` chain sensation→`perceive`.
- **`integrate_epistemic_affect()`** (1753) — the body relays reasoning→emotion: asks `neural_bridge.epistemic_affect_signal()` (how knowledge MOVED, any source) and hands it to appraisal. Interprets nothing; changes no belief and no decision (knowledge→feeling→disposition only). Called by `_react_affect`.

#### E — Event spine + reactions
- `register_completion_callback` (1576) · `_execute_completion_callbacks` (8946, from `_execute_and_validate_task`) · **`on(event_type, handler, *, name, mode, priority)`** (1625) · **`emit(event)`** (1651, sync reactions inline in priority order/isolated, deferred queued to the worker; `_max_emit_depth` guard) · `_start_reactive_worker` (1679) · **`_reactive_drain_worker`** (1685, woken by `emit`, never on an interval).
- Reactions: `_react_affect` (1707, the reference reaction), `_react_induce` (1864), `_react_expand_outcome` (1891), `_react_resolve_transfers` (1919), `_react_crystallize_taught` (1928), `_react_job_completed` (4372), `_react_competence_changed` (1835), `_react_integrity_reaudit` (1823), `_react_close_deficit` (4401).
- **`_react_pursue_frontier`** — THE developmental drive, event-driven: registered on COMPETENCE_CHANGED / OUTCOME_OBSERVED / EVIDENCE_ADMITTED / ENVIRONMENT_ENCOUNTERED / DEFICIT_DIAGNOSED (LOW priority, so state-updating reactions run first); coalesced single-flight (`_coalesced_pursue`) runs ONE `_run_exploration_cycle`. A completed pursuit emits the events that wake the next → self-sustaining, quiet when nothing changes. A boot kick in `start_background_tasks` resumes it after a restart. REPLACES the retired idle-timer exploration poll (INTRINSIC-EVENTDRIVEN-01).
- Support: `_coalesced_motivation_refresh` (1849), `_register_deficit_unknown` (4522), `_deficit_is_closed` (4554), `_mark_reflection_due` (4577); integrity watcher `_integrity_watched_paths` (1715), `_start_integrity_watcher` (1738).

#### F — Idle tiers (on the QueueAuthority scheduler)
- **`_register_idle_subsystems()`** (4624) — registers each tier as a recurring job via `task_queue.schedule_recurring(name, method, interval, priority)` on the background budget (never steals an acting slot); a missing tier method raises loudly. The table:

| Tier | Method | Priority / interval | Line |
|---|---|---|---|
| `idle_health_check` | `_idle_health_work` | high/30s | 4891 |
| `idle_system_review` | `_idle_system_review_work` | high/180s | 5118 |
| `idle_knowledge_refresh` | `_idle_knowledge_refresh_work` | medium/6h | 5253 |
| `idle_self_improvement` | `_idle_self_improvement_work` | medium/900s | 5602 |
| `idle_meta_learning` | `_idle_meta_learning_work` | medium/300s | 6401 |
| `idle_memory_consolidation` | `_idle_memory_work` | low/600s | 6594 |
| `idle_learning` | `_learning_phase` | medium/600s | 9731 |
| `idle_domain_expansion` | `_idle_domain_expansion_work` | medium/900s | 5723 |
| `idle_domain_discovery` | `_idle_domain_discovery_work` | medium/900s | 5897 |
| `idle_analogy_discovery` | `_idle_analogy_discovery_work` | medium/1200s | 6028 |
| `idle_operator_exploration` | `_idle_operator_exploration_work` | medium/300s | 5929 |
| `idle_operator_induction` | `_idle_operator_induction_work` | medium/300s | 5998 |
| `idle_self_optimization` | `_idle_self_optimization_work` | low/120s | 6963 |
| `idle_step_log_prune` | `_prune_step_execution_log` | low/600s | 4589 |
| `idle_system_state_refresh` | `_update_system_state` | low/60s | 10401 |
| `motivation_refresh` | `_refresh_motivation_signals` | high/10s | 4212 |
| `system_awareness` | `_run_system_awareness_cycle` | medium/60s | 4256 |
| `idle_constitution_check` | `_check_constitutional_alignment` | low/1800s | 9516 |

- `_run_exploration_cycle` (the selection — now sources `_intrinsic_pursuits` via `_pursuit_to_goal`, not the old IMS generator; driven by `_react_pursue_frontier`, no longer by an idle timer — `_run_idle_exploration` is retired) · support: `_expand_one_outcome` (5827), `_resolve_transfer_outcomes` (6255), `_task_outcomes_by_field` (6360), `_idle_abstraction_work` (6560, **not scheduled** — abstraction is event-driven now), `_rule_root_count` (6104), `_should_trigger_curiosity_optimization` (7031), `_curiosity_driven_optimization` (7057), `_propose_directive_improvements` (7138), knowledge-cutoff persistence (5389-5545), `_observe_system_performance` (7258), `_predict_and_resolve_system_state` (7275), `_persist_prediction_result` (7328), `_decision_context` (7380).

#### G — Reasoning / prediction APIs
- **`reason_about(question, context, ...)`** (3332) — answer with the substrate; returns a `ReasoningResult`, never None (`model_available` 3307, `agent_allowance` 3313, `_model_calls_on` 3429).
- **`perform_cross_domain_reasoning(query_text, ...)`** (3493).
- **`predict_system_behavior`** (3444) · **`make_enhanced_prediction`** (3617) · **`get_domain_insights`** (3685) — **all VESTIGIAL: 0 callers.**
- No self-modification API: the substrate improves only by learning (the learning authority). The governed `change_*` / `allocate_resources` / `_apply_self_modification` path and the `SELF_MODIFIED` event were removed 2026-09-15.
- `set_goal` (2073, STATE goal via `extract_state_conditions` 2042) · `generate_curiosity_driven_goals` (2118, from `_run_exploration_cycle` + tests).
- Memory helpers: `store_memory` (2388), `search_memories` (2726), `get_intelligent_memory_context` (3203), `_build_memory_narrative` (2214), `_store_governance_block_meta_memory` (2484), `_store_task_outcome_meta_memory` (2545), `_infer_domain_from_task` (2643).

#### H — Health integration
- **`_receive_health_event(health_event)`** (10549) — the callback wired into `MonitoringCoordinator.singleton_callback` (846): analyze (startup grace) → diagnose → recover. Support: `_diagnose_health` (10765), `_health_action_risk` (10823), `_execute_recovery` (10836), `_verify_recovery` (10973), `_create_recovery_goal_from_health_event` (9666), `_report_failure` (1277).
- `_idle_health_work` is the periodic health backstop. (The security audit worker, its 120s tier, `handle_security_finding`, the remediation callback and the integrity watcher were REMOVED 2026-09-14; world security is the DHCM world factory's security-audit agent.)
- Constitution: `_check_constitutional_alignment` (9516, idle tier) · `_check_constitutional_alignment_quick` (9653, **VESTIGIAL: 0 callers** — the every-cycle quick check left dead when the poll loop was retired).

#### I — Conversation / teach
- **`conversation(session="default", *, db=None)`** (3767) — a `Conversation` bound to this substrate (understands a sentence + answers through the brain that owns reasoning/memory/language).
- `handle_user_request(...)` (8997, `_request_kind` 9101, `_answer_from_what_is_held` 9116, `set_reply_debug` 9093) — **referenced only in docs; no code caller (unwired ingress).**
- `teach(sentence)` (13395) + `_ingest(...)` (13280) live on the **`Conversation`** class, via `conversation()`; `understand` (13717), `say` (13931); `get_conversation`/`end_conversation`/`held_conversations` (14115/14136/14141).
- **`look_up(phrase)`** (Conversation) — research a genuine gap via the `web_search` tool, with a **process-wide single-flight** (`_LOOKUPS_INFLIGHT`, module-level, keyed by `normalize_term(phrase)`): one self behind up to 64 sessions, so a crowd asking the same unknown at once collapses to ONE real research + ONE shared-store write, the rest piggyback on the same Future (`_research_phrase` holds the old body). NOT a cross-time cache (entry lives only while in flight → a later ask re-verifies). Benchmark: `experiments/LOOKUP-SINGLEFLIGHT-01`.
- Vision: `see(path, ...)` (1951), `remember_image` (1961), `recall_image` (1991), `_image_caption` (1999).

#### J — Capability plug-in system (dormant)
`register_capability` (1476), `unregister_capability` (1560), `_execute_registered_capabilities` (9885), `_check_capability_conditions` (10048). **Vestigial:** `_execute_registered_capabilities` + `_check_task_completions` (10141, "legacy scanner") have 0 callers; `_handle_idle_state` (9511) is legacy/0-callers; `process_input` (2016) + `_analyze_for_goal_creation` (10262) have no live callers. `_learning_phase` (9731) + `_apply_learning_recommendation` (10282) are alive via `idle_learning`.

#### Agent-of-self deployment
`deploy_agent` (1390) · `await_agent` (1414) · `collect_agent_findings` (1422) · `pending_agents` (1431) — via the bound `agent_coordinator`. `deploy_agent` has **0 in-repo callers** (bound, not yet invoked).

### 4. Feeds / holds
**Holds & drives (down):** learning/belief authority, memory + injector, neural_bridge, domain master + registry, intrinsic_motivation, planning, perception + vision, intelligence/watchdog, health monitor + recovery, monitoring coordinator, constitution + governance, directive system, meta_learning/causal/improvement, agent_coordinator, and the QueueAuthority. Each is one pipeline within the one process.
**Driven by (up):** `main.py` (constructs, injects, initializes/starts); the cognition loop (pulls its own next task from the shared QueueAuthority); the event spine (`emit`/`on` reactions + drain worker); the QueueAuthority scheduler (owns the cadence of all idle tiers); health/security callbacks (`_receive_health_event`, `handle_security_finding`, remediation-complete); the agent factory (`execute_task`) and experiments/tests.

### Vestigial (present but 0 wired callers — the code-flip punch-list)
`perceive`, `predict_system_behavior`, `make_enhanced_prediction`, `get_domain_insights`, `_check_task_completions`, `_execute_registered_capabilities` (+ `register_capability`/`_check_capability_conditions`), `_handle_idle_state`, `_check_constitutional_alignment_quick`, `process_input`/`_analyze_for_goal_creation`, `deploy_agent` (bound, not invoked), `handle_user_request` (docs-only). (`_idle_abstraction_work` exists but is intentionally not scheduled — abstraction is event-driven.)
