# The body — `AutonomousCoordinator`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

`core/agents/autonomous/autonomous_coordinator.py` is **27,378 lines across 59 classes and 707
definitions**. It holds four subsystems, and each has its own document:

| Subsystem | Lines, with its supporting types | Document |
|---|---|---|
| `AutonomousCoordinator` — the body and self | 14,206 (the class alone 13,891, 292 methods) | this one |
| `Constitution` — the law every act passes through | 6,993 (the class alone 3,608, 86 methods) | [constitution.md](constitution.md) |
| `Conversation` — reading a sentence and answering from what is held | 5,454 (the class alone 4,107, 90 methods) | [conversation.md](conversation.md) |
| `Drift` — the substrate perceiving its own change | 602 | [drift.md](drift.md) |

They are in one module because the self holds its own law and its own speech rather than submitting to an
outside judge or calling out to a service for either.

---

## 1. What the body is

The coordinator **is the substrate's body and self**: one process that holds every faculty-authority as a
handle and reaches each faculty *through* itself rather than constructing a rival. The state that used to
live in a separate `GeneralPurposeExecutor` was absorbed here — execution is the self's own faculty.

Every substrate path is **model-free** and reports an honest capability fault rather than falling back. The
coordinator holds no model handle, and `get_autonomous_coordinator(config)` — the async singleton accessor —
takes no model argument. `model_available()` is retained for compatibility and answers that there is none.

## 2. What it holds

Each authority is assigned in `__init__` (class at 7983, `__init__` at 8004) and is reached only through
the handle below. The belief store is reached via `self.learning`, not a separate handle.

| Handle | From | Line |
|---|---|---|
| `coordinator_config` | `CoordinatorConfig.from_dict` | 8016 |
| `circuit_breakers` | `get_circuit_breaker_registry()` | 8020 |
| `system_state` | `SystemState()` | 8050 |
| `vision` | `get_perception_faculty()` | 8059 |
| `learning` | `get_learning_authority()` — the one `UnifiedLearningSystem`; beliefs are reached through it | 8074 |
| `intrinsic_motivation` | `get_intrinsic_motivation_system()` | 8096 |
| `directive_system` | `DirectiveSystem()` | 8281 |
| `env_state`, `discovery`, `behavioral`, `topology` | environment state, active discovery, behavioural analysis, infrastructure topology | 8287–8297 |
| `constitution` | `get_constitution()` | 8315 |
| `capabilities` | `get_capabilities()` | 8322 |
| `threat` | `ThreatSense()` | 8336 |
| `arbiter` | `get_behavior_arbiter()` | 8349 |
| `reading` | the constitution's own reading ledger | 8350 |
| `drift` | `Drift()` | 8387 |
| `appraisal` | `get_appraisal_system()` | 8405 |
| `task_queue` | `get_queue_authority(...)` | 8430 |
| `outbox` | `get_outbox()` | 8440 |
| `db` | `LyricUnifiedDatabase()` | 8448 |
| `memory` | the memory agent, bound during start-up | 8517 |
| `abstract_reasoning`, `proof_engine` | abstract reasoning engine, proof engine | 8529–8531 |
| `neural_bridge` | bound during start-up (`get_neural_bridge()`) | 8545 |
| `intelligence` | `get_predictive_intelligence()` | 8557 |
| `causal_analyzer` | `CausalFeedbackAnalyzer()` | 8565 |
| `meta_learning` | `get_meta_learner(...)` | 8574 |
| `health_monitor` | `get_health_monitor()` | 8608 |
| `agent_coordinator` | the agent authority, bound later | 8627 |
| `tool_registry` | bound by `initialize_execution_faculty` | 8449 |

## 3. Bring-up and the cognitive cycle

`initialize(start_loop=False)` brings every subsystem up and binds memory, the neural bridge and the
meta-learner. `start_coordination()` starts the cognition loop; `start_background_tasks()` registers the
recurring jobs and starts the queue authority's scheduler. `shutdown()` stops the queue authority, which
releases this instance's lease so what it owes is claimed by the next instance at once.

**`_coordination_cycle()`** is the cognition loop, and what remains on its tick is only task dispatch and
reaping:

- **Reap first.** Finished tasks are collected before the pull, so the slots they free are filled in the
  same cycle and failures are observed rather than discarded. Reaping after the pull left a finished task's
  slot idle for a whole extra cycle — about 3 s at the default 2 s interval.
- **Fill every free slot.** The first pull may wait briefly; the rest take only what is ready now and stop
  at the first empty answer. One pull per cycle let a backlog start at most one task per cycle interval.
- **Its own backlog first**, then the next job another instance queued and has not started — one queue,
  many instances.
- **Per-user caps are recomputed before each pull**, so one user's backlog cannot monopolise the pool. The
  substrate's own actor is never capped. The acting cap is directive-driven when an active
  `resource_allocation` directive exists (`_effective_max_parallel`).
- **Launch, do not await** (`_launch_task`). Awaiting a task blocked the whole loop for that task's
  lifetime, which is what made the substrate single-threaded. Concurrency is bounded by the queue
  authority's semaphore.

`apply_throttle` applies a temporary throttle. Active-task counts everywhere come from
`task_queue.active_tasks()`.

**Intrinsic exploration is not polled here.** It reacts to state-changing events (§5), and each completed
pursuit emits the events that wake the next — a self-sustaining drive that is quiet when nothing changes.

## 4. Workers

More Lyric processes on the one store, each taking queued work in its own process and learning from it
(`LYRIC_ROLE=worker`, `./lyric worker [n]`; `is_worker`). A worker is not in the world: it opens no senses,
runs none of the self's scheduled work, and runs none of the self's own reactions (`SELF_REACTIONS`:
`pursue_frontier`, `motivation_refresh`).

Instead it **tells the self** what it must hear — `_tell_the_self` posts to `SELF_CHANNEL` (`lyric_self`).
The Lyric it works for hears it (`_hear_workers`, `_heard_from_a_worker`) and wakes the self's reactions
registered for that event. A message a worker owes a person is kept in the outbox and said by the self
(`_say_what_a_worker_owes`). Evidence: `INSTANCES-01`.

## 5. The event spine

An event names something that happened to the substrate and carries the specific unit of work it concerns —
never "go scan a table". `on(event, handler, *, name, mode, priority)` registers a reaction; `emit(event)`
dispatches it. Synchronous reactions run inline in priority order, isolated; deferred reactions queue to
`_reactive_drain_worker`, which is **woken by `emit` and never runs on an interval**. `_max_emit_depth`
guards recursion.

**Nine event types** (`SelfEventType`, 124):

| Event | Raised when | Carries |
|---|---|---|
| `TASK_COMPLETED` | A task finished and was judged complete, or not | the task and its verdict |
| `OUTCOME_OBSERVED` | A completed task's outcome became durable | domain, meta-memory id |
| `COMPETENCE_CHANGED` | Learning moved a domain's competence | the domain |
| `EVIDENCE_ADMITTED` | Something was admitted to the concept store | subject, relation, object, domain |
| `JOB_COMPLETED` | A submitted background job came back | job id, name, result, error |
| `DEFICIT_DIAGNOSED` | A planning attempt could not reach a goal | a typed `EpistemicDeficit` |
| `PERCEPT_RECOGNIZED` | A percept was recognised and compared to the acceptance band | claim, posterior, ACT/VERIFY/ABSTAIN, domain, classifier |
| `ENVIRONMENT_ENCOUNTERED` | A place was met for the first time | environment id, domain, facts |
| `EXPECTATION_UNMET` | The world did not do what the substrate expected | a `Departure` |

`EXPECTATION_UNMET` is the one event that starts from the substrate's own expectation rather than from
something that happened.

**Nineteen registrations** wire **twelve reactions** to those nine events. One runs inline; every other
is deferred to the drain worker, off the acting path.

| Reaction | On | Mode |
|---|---|---|
| `_react_affect` | `TASK_COMPLETED` | sync |
| `_react_induce` | `OUTCOME_OBSERVED` | deferred |
| `_react_expand_outcome` | `OUTCOME_OBSERVED`, `COMPETENCE_CHANGED`, `EVIDENCE_ADMITTED` | deferred |
| `_react_resolve_transfers` | `OUTCOME_OBSERVED` | deferred |
| `_react_crystallize_taught` | `EVIDENCE_ADMITTED`, `COMPETENCE_CHANGED` | deferred |
| `_react_job_completed` | `JOB_COMPLETED` | deferred |
| `_react_competence_changed` | `COMPETENCE_CHANGED` | deferred |
| `_react_close_deficit` | `DEFICIT_DIAGNOSED` | deferred |
| `_react_percept` | `PERCEPT_RECOGNIZED` | deferred |
| `_react_investigate_environment` | `ENVIRONMENT_ENCOUNTERED` | deferred |
| `_react_expectation_unmet` | `EXPECTATION_UNMET` | deferred |
| `_react_pursue_frontier` | all five state-changing events | deferred, priority 10 |

`_react_pursue_frontier` is **the developmental drive**. It is registered at low priority so the reactions
that *update* the state — induction to competence, domain expansion, environment investigation — run first
on the same event and the pursuit reads the post-update self. It is coalesced single-flight
(`_coalesced_pursue`), running one `_run_exploration_cycle`. A boot kick resumes it after a restart.
Evidence: `INTRINSIC-EVENTDRIVEN-01`.

**Expensive work is coalesced.** `_react` starts one single-flight reaction unless it is already running;
`_coalesced_induction_drain` drains to completion; `_coalesced_domain_expansion` is progress-bounded;
`_coalesced_domain_discovery` is a full sweep; `_coalesced_motivation_refresh` drains a dirty flag so a
burst of competence changes costs one refresh. `_stop_reactions` stops every one before anything they read
closes.

## 6. What the scheduler runs

Background work is not a tier system. It is **seven recurring jobs**, each sampling state that drifts
continuously and has no discrete event to react to. Everything that can be driven by an event is.

`_register_idle_subsystems()` hands each to `task_queue.schedule_recurring(name, method, interval,
priority)`. The scheduler fires them on the **background budget**, separate from the acting cap, so a job
can never take an acting slot, and records each one's runs and errors. The coordinator owns no cadence,
nothing here loops on its own interval, and nothing schedules outside the authority. A registration naming
a method that does not exist **raises** — a wiring defect is surfaced loudly, never skipped into a green
count.

| Job | Method | Priority | Interval |
|---|---|---|---|
| `idle_system_state_refresh` | `_update_system_state` | low | 60 s |
| `motivation_refresh` | `_refresh_motivation_signals` | high | 60 s |
| `epistemic_affect` | `integrate_epistemic_affect` | high | 60 s |
| `constitution_record` | `_drain_constitution_record` | high | 30 s |
| `constitution_integrity` | `_check_constitution_integrity` | high | 120 s |
| `affect_refresh` | `_refresh_affect` | high | 60 s |
| `system_awareness` | `_run_system_awareness_cycle` | medium | 60 s |

`idle_system_state_refresh` is the **sole writer** of `system_state.resource_usage`, its timestamp and its
performance metrics, which the constitution's standing assessment reads live. It had been dead, leaving the
constitution with values from initialisation.

`_check_constitution_integrity` both verifies the governing machinery and **takes up code that changed on
disk** — the adoption path in [constitution.md](constitution.md) §10.

Ten routines that were timed are reactions on the spine now, and are no longer defined:
`_idle_system_review_work`, `_idle_knowledge_refresh_work`, `_idle_self_improvement_work`,
`_idle_meta_learning_work`, `_learning_phase`, `_idle_analogy_discovery_work`,
`_idle_operator_exploration_work`, `_idle_operator_induction_work`, `_idle_self_optimization_work`,
`_idle_abstraction_work`. Self-improvement went with self-modification.

Still defined and used outside the scheduler: `_idle_domain_expansion_work`, `_idle_domain_discovery_work`,
`_check_constitutional_alignment`, and `_run_exploration_cycle` — the last driven by a pursuit rather than
a timer.

## 7. The self

Composed from the faculties, derived, and **honest about what is missing**: every accessor returns None
rather than a default when nothing has been measured.

| Accessor | What it reads |
|---|---|
| `state()` | Composes the whole self; `SelfState` is the snapshot |
| `render(audience)` | The self as language, from `state()`. No model |
| `identity_prompt(role)` | The stable identity statement |
| `_interoception` | The measured interoceptive variables, from appraisal's current state |
| `_attitude` | Derived emotions — eagerness, doubt, frustration, satisfaction, valence, attribution. None if unappraised |
| `_temperament` | The standing drives — what it is, before any situation |
| `_drives` | How strongly each drive is active now |
| `_values` | The laws it is bound by, read from the constitution, not restated |
| `_competence` | What it is actually good at — the operators it has **validated**, per domain |
| `_purpose` | What it is for — the **active** directives |
| `_continuity` | Who it has been, from durable state only |
| `_development` | How developed it is — a global read of how much it holds and has lived |
| `_situation` | Where it is, the outward half of the self |

`disposition(*, slots_available, queue_pressure)` turns the standing disposition into a
`BehavioralDirective`. `_refresh_directive_guidance` refreshes the directive-driven knobs from the active
directives.

`integrate_epistemic_affect()` relays reasoning to emotion: it asks the neural bridge how knowledge **moved**
and hands that to appraisal. It interprets nothing and changes no belief and no decision — knowledge to
feeling to disposition only.

## 8. Where it is

`_observe_environment` reads the host live — platform, release, machine, hostname, user, root — with
nothing hardcoded, and the environment's identity is a hash of the facts that make the place the place.
`_situate` establishes it as a first-class **environment domain** and notices if it is new;
`_register_environment` is the one registration for every place, through the one domain authority, with a
maximum-uncertainty competence belief so the place surfaces to be investigated, and emits
`ENVIRONMENT_ENCOUNTERED` when new.

`situate_device(report, actor_identity)` does the same for a device a person operates Lyric through. The
device answers for itself: its kind (platform, release, model, form, maker), its surface (what exists on it
at all), and the person's settings. **The kind is the place**, keyed by what it is rather than whose it is,
so a second device of the same kind is not new. Evidence: `DEVICE-01` (20/20).

`_react_investigate_environment` holds every fact observed and each surface capability as `offers`, with
negative polarity for one that is not there. Only a place with a root gets its folder scanned.

## 9. Perceiving

**One act of perceiving.** `perceive_moment(things)` takes in everything met at one moment, by every sense
that can take something from it, at the same time, as one experience. Four named doors open onto it:

| Door | Sense | Opens |
|---|---|---|
| `see(path)` | sight | images, videos |
| `hear(path)` | hearing | recordings, and the sound track of a video |
| `read(path)` | reading | PDFs, Word, Excel, any file of text |
| `take_in(path)` | every sense that can | one real file |

A video is seen **and** heard on one percept. `_sense_and_recall` takes the file in by every sense that can
and asks memory, by what was sensed, what it already holds; `_heard_before`, `_seen_before` and
`_read_before` recall the earlier encounters of the same thing.

`remember_met` keeps what was met — a picture and its gist, a trace of sounds but never the recording.
`recall_media` returns what was stored; `recollect(memory_id)` **rebuilds** what a memory holds of what was
met, which is how the substrate remembers.

**Teaching by perceiving**: `learn_word`, `learn_voice`, `learn_phones`, `learn_song` and `learn_thing` are
the same act with a lesson attached (`_hear_lesson`) — the example is sensed, admitted, judged, remembered
and handed over as any perceiving is. What was said and whose voice said it are claims of the hearing like
any other (`_sensed_claims`).

**Recognition is one primitive.** `perceive(classifier, instance, ...)` recognises and lets the posterior
govern ACT / VERIFY / ABSTAIN against the same acceptance band the completion decision uses, then emits
`PERCEPT_RECOGNIZED` so the decision governs behaviour through the spine instead of each call site
re-deciding. `attach_recognizer(domain, classifier)` wires a route's sensation to its recognition, which is
what makes `see` chain sensation to recognition. `recognise_sensed` names what was seen **without being
asked**; `describe_kind` says what a kind looks like from what sight observed of its instances.

## 10. Taking work on

| | |
|---|---|
| `handle_user_request` | **The front door** — one turn from a person, typed or heard alike |
| `_take_turn` | Takes the turn: its kind, a turn about the substrate's own work, an answer from what is held, else work queued and "I'm on it" |
| `_about_my_work` | Answered from the queue authority: what it is doing, whether it finished, stop it, keep going |
| `stop_work` | Because they asked — the queue authority cancels, waiting or running |
| `_answer_from_what_is_held` | Answer out of the concept store and memory, and remember the exchange |
| `set_goal` | Set itself a goal and take it on: its intent formed, its work queued |
| `generate_curiosity_driven_goals` | Goals from curiosity and exploration targets |
| `execute_task` | The public entry, substrate-first |

A request **not** to act is answered and never made a job. `set_reply_debug` switches reply detail. Evidence:
`WORK-TALK-01`.

**Speaking first.** `speak_to(actor, text, why, about, at)` owes a person a message in the durable outbox,
due now or at a moment, and records it in their conversation. `on_message(actor, listener)` is a front end
listening for that person, pushed each message the moment it is due and anything already waiting; each is
delivered once. A later message is delivered by the queue authority's timed job, and `_rearm_messages` arms
what is still owed at boot. Work a person asked for that **ends** is said by the substrate itself:
the queue authority announces it and `_speak_of_ended_work` tells them how it ended and what it found.
Evidence: `MESSAGE-01`.

**Asking before an act.** When a task's declared steps are an instance of a capability not unlocked for its
person, the act returns `awaiting_person` **before** it happens and the run is kept on the task.
`_wait_for_person` holds the job and asks once for that act; "Yes." resumes it (`go_on_with`) and "No."
stops it. Evidence: `CAPABILITY-EMERGE-01`.

## 11. Doing the work

`_execute_and_validate_task` is the real per-task path from `_launch_task`: it executes, then decides
completion from the task's own completion belief — there is no separate validator. It is also the producer
of the **earned operability** signal, recording the operating outcome for domain-tagged non-drive tasks.
Success there is the goal-holds posterior reaching 0.5 — operating *correctness* — not the cautious
done-acceptance band, so correct-but-not-yet-accepted work still earns operating trust.

`_execute_task_paths` runs the model-free paths in order, or returns the honest gap:

| Path | |
|---|---|
| `_execute_grounded_operator` | Deterministic execution of a **validated** operator, re-establishing authority and world against *current* state |
| `_drive_substrate_goal` | Plans a state goal over learned operators; the re-observed world decides success |
| `_execute_operation` | The one operation path for every task — no per-type handler switch: declared tools, or the knowledge loop |

`_task_gate` asks the constitution whether the task may begin at all. Each tool runs through `_run_tool`,
and every tool call reaches the constitution in the tool registry.

**Planning and routes.** `_plan_route` plans a state goal over what the substrate holds; `_route_of` records
a proved route as the steps that walk it; `_pursue_proved_route` runs it and closes it out;
`_perform_reading_step` reads a file the route is about to act on, **because the law requires it**;
`_worth_planning_again` decides whether a stopped walk has something new to plan over. `_premise_gone`
retires a goal whose premise no longer holds.

**Why work exists.** `intend` records why at the moment the work is taken on; `_reconcile_intent` and
`_reconcile_plan_intent` attach what actually happened; `conclude_pursuit` closes the pursuit with what
ended it. `_account_for_creation_steps` records why each step that must make something is happening.

**Learning from acting.** `_learn_what_the_act_did` closes the frame and files what the act did as a
demonstration; `_record_execution_demonstration` files one executed action for the learner;
`_record_calibration_outcome` records whether the confidence was earned — the pair that makes calibration
real; `_appraise_substrate_execution` and `_appraise_tool_outcome` report to appraisal in measured signals
only.

**Plain words to tools.** `_tools_for_request` decides which tools do what a person asked, from what they
asked as Lyric read it. Each tool's own description is **read** for what it says it does
(`_read_tools_by_doing`, `said_of`, `doing_said`), so a tool is selected by the doing it names rather than
by a keyword table. `ready_to_read` warms what that needs before anyone is read to.

## 12. Grounded completion — DID and SAW

A task is done when the substrate's own belief that the goal holds reaches the acceptance band. Nothing else
decides it.

| | |
|---|---|
| `_derive_completion_anchor` | The completion proposition `G` for the task |
| `_completion_domain` | The task-specific domain the belief and its outcome memories live in |
| `_open_completion` | Opens `G` at the **low** prior, on the task itself |
| `_expected_outcomes` / `_stated_outcomes` | Everything the task is expected to leave true |
| `_gather_did_evidence` | **DID** — the intervention's own report that it produced the effect |
| `_saw_reobserve` | **SAW** — a fresh, independent measurement of the resulting world state |
| `_rerun_check` | Runs a check again against a disposable copy of the end state it checked |
| `_saw_memory_holds` | Fresh independent retrieval: is the claim actually held now? |
| `_independent_groundings` | Reduces raw evidence to independent groundings — derived items dropped, the rest grouped |
| `_observe_completion_evidence` | Moves the belief on independent groundings, one belief per grounding |
| `_decide_completion` | Done from the posterior, against the band |
| `_acceptance_band` | `(verification_intensity, accept)` — the same band `perceive` uses |
| `_corroborated` | The most caution may ask: two independent strong groundings |

**The band is earned, not set.** A completion belief opens at a prior of 0.15 (`COMPLETION_PRIOR`). The
acceptance bar starts at 0.95 (`COMPLETION_ACCEPT`) and rises with the domain's own caution toward 0.99
(`COMPLETION_ACCEPT_MAX`) — but never past what two independent strong confirmations actually give from
that prior, which is 0.975 (`_corroborated`: 0.15 → 0.724 → 0.975). **Done demands corroboration, and
caution cannot demand what no evidence gives.** Raised toward 0.99 the bar asked for a third confirmation
a goal in the world cannot have — what the act reported and a fresh look at the world are its two — so in
a world whose own failures raised its caution, a goal the world reached and Lyric saw was never done
(`RULE-AUTHORITY-02`, worlds 1044 and 1725: 0.975 against 0.98).

This is also why DID alone cannot finish anything. A grounded operator carrying only its own report sits
at that one-confirmation 0.724, so verified successes were marked failed until `_saw_reobserve` learned to
re-observe a grounded operator's world effects through a fresh `observe_world`. Evidence:
`INTEGRATION-LOOP-01` (6/6, real coordinator and world).

## 13. Closing an epistemic deficit

When planning cannot reach a goal, the domain authority diagnoses **why** and `DEFICIT_DIAGNOSED` carries
the typed deficit. `_react_close_deficit` acts on it — reactively, model-free, and only when the disposition
and the deficit's kind both allow. Exploration runs off the acting path.

Closing moves the belief authority too: `_register_deficit_unknown` registers the ignorance as a
known-unknown, and `_deficit_is_closed` resolves it **only** on a close verified against the world. A goal
given up for want of something learnable waits (`_await_knowledge`) and is drawn again once it is there
(`_revisit_awaiting`).

## 14. Reasoning and prediction

`reason_about(question, context)` answers with the substrate and returns a `ReasoningResult`, never None.
It keeps no memory of its own — the one memory of the reasoning is the memory agent's, recorded with the
reason and whether it was verified. `agent_allowance` says how many agents-of-self a reasoning kind warrants
in parallel. `perform_cross_domain_reasoning` reasons across domains through the universal domain master.

`_attend_to_expectations` wires the predictive intelligence system's world expectations to this body, and
`_predict_and_resolve_system_state` closes the world-model loop: predict, wait, observe, score.
`_observe_system_performance` is the observable a system-performance prediction is scored against.

**There is no self-modification API.** The substrate improves only by learning. The governed `change_*` and
`allocate_resources` path, `_apply_self_modification` and the `SELF_MODIFIED` event were removed on
2026-09-15. What the development team changes on disk enters through the constitution's adoption path.

## 15. Agents of self

`deploy_agent(description, allowed_tools)` deploys an agent of self through the bound agent authority;
`await_agent` blocks until one returns; `collect_agent_findings` takes every agent that has come back since
the last collect without blocking; `pending_agents` names those still running. Findings come back as
`JOB_COMPLETED`.

## 16. Health

**The coordinator holds no health region.** Health is the health monitor's alone (`self.health_monitor`),
which checks every component on its own cadence, and it is supervised from outside the process by
`core/guardian/supervisor.py`, so a watchdog whose job is to survive a crash does not die in it.

What reaches cognition is a **count**: `_health_counts` reads how many components are graded, how many were
last graded below healthy, and when. `DEFICIT_DIAGNOSED` fires on task failure. A health verdict does not
otherwise reach the cognitive loop.

`_check_constitutional_alignment` asks the constitution for its standing assessment.

## 17. Feeds and holds

**Holds and drives:** the learning and belief authority, memory, the neural bridge, the domain master and
registry, intrinsic motivation, perception, the constitution with its reading ledger and durable record,
the behaviour arbiter, drift, appraisal, threat sense, the directive system, predictive intelligence,
meta-learning, the causal analyzer, the health monitor, the capability register, the outbox and the queue
authority. Each is one pipeline within the one process.

**Driven by:** `core/main.py` (constructs, injects, initializes, starts); the cognition loop pulling its own
next task from the shared queue authority; the event spine; the queue authority's scheduler, which owns the
cadence of every recurring job; the agent factory through `execute_task`; and the experiments.

## 18. Evidence

| | |
|---|---|
| `experiments/INTEGRATION-LOOP-01` | The whole loop end to end on a real coordinator and world, 6/6 |
| `experiments/INTRINSIC-EVENTDRIVEN-01` | The developmental drive as reactions rather than a timer |
| `experiments/INSTANCES-01` | Workers on one store |
| `experiments/systems/DEVICE-01` | Learning a device as a place, 20/20 |
| `experiments/MESSAGE-01` · `WORK-TALK-01` · `CAPABILITY-EMERGE-01` | Speaking first, talking about its own work, asking before an act |
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | Results, with the negative ones |
