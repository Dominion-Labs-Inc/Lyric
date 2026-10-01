# Intrinsic Motivation Redesign — the substrate's developmental engine

Status: **PLAN (not yet built)**. Written for review before any code.

## Thesis
Intrinsic motivation is the substrate's **developmental engine**: from its *whole* state it feels
what to pursue in order to **grow** — learn, interact, use tools, explore its environment, and
advance past **what it currently knows** and **what it currently can and cannot do**. It lives in
the coordinator (the self), is **event-driven**, reads **all systems**, and never depends on a
human-maintained catalog.

Two examples that must fall out of it naturally:
- *"I don't know much yet, I have few memories"* → a broad, strong pull to learn, interact, and
  accumulate experience. As it develops, this narrows to targeted mastery.
- *"I just landed in an environment I've never seen"* → a pull to investigate it (the environment is
  an unknown domain), gated by whether now is the right moment.

## Current state (grounded — what exists today)
`core/agents/autonomous/intrinsic_motivation.py` — `IntrinsicMotivationSystem`, **3544 lines**:
- Dimensions (`curiosity/competence/novelty/mastery/autonomy/social/impact`) computed by
  `_calculate_*` from perception + system-state + goals ([:948‑1216](../core/agents/autonomous/intrinsic_motivation.py)).
- Affect it OWNS: `CoreAffect`/`AffectState`/`Mood`, `update_affect`, `_affect_from_appraisal`.
- `sense_fitness` → `Fitness(certainty/coherence/competence)`.
- Goal generators: `_competence_goals`, `_confidence_goals`, `generate_curiosity_driven_goals`
  (uncertainty-weighted, mood-modulated), and `get_top_exploration_targets` →
  `epistemic_engine.get_unstable_regions()`.
- Domain performance stats; profile persistence; goal embeddings/dedup.
- A SEED of the developmental idea: `_experience_pressure` ([:932](../core/agents/autonomous/intrinsic_motivation.py))
  nudges novelty up when experience is low.

Coordinator usage: `_run_exploration_cycle` (goals, arbiter-gated), `_react_competence_changed`
(refresh signals, coalesced) + a **%5 motivation poll backstop**, `state()` composes drives/affect.

**Gaps vs. the vision:** it is a separate object (not collapsed); motivation is almost entirely
**local** (per-belief/per-domain uncertainty), not **global/developmental**; the **environment**
(`SelfState.situation`) is not an input; **prior↔current belief trajectory** and **known/unknown
domain breadth** are not first-class; **tool-usage** and a **capability frontier** are not drives;
and it is not fully event-driven (the %5 poll remains).

## Target architecture

### A. One authority — collapse the *decision* into the coordinator (the self)
- The **decision** ("given all of me, what do I pursue") becomes a coordinator faculty, reasoning
  over the self's own composed `SelfState` (which already includes interoception, affect, competence,
  purpose, continuity, and now `situation`/environment) plus the belief/domain/memory stores.
- **Keep as the self's owned mechanics** (relocated, not deleted): affect (`update_affect`, Mood),
  `sense_fitness`, reward accounting, profile persistence, embeddings/dedup. These are machinery, not
  a second decider.
- **Retire the competing authority:** the idle-work playbook's role as a work-*selector* (demote to a
  learnable *seed* + the exploration-config *translator*, per the playbook analysis); the **%5 poll**
  (→ event-driven); the **`LLM_AUTONOMOUS`** consolidation preference (→ model-free).

### B. Whole-self synthesis — all systems in one read
Motivation weighs, together:
- **Developmental appraisal (GLOBAL, new):** knowledge held (belief/fact counts), experience
  (memory/episode counts, real interactions), **known vs. unknown domain breadth**, coherence →
  sets the *intensity and breadth* of the growth drive.
- **Beliefs — prior + current:** current uncertainty (unstable regions) **and** trajectory (is it
  learning? progress is itself a signal).
- **Known vs. unknown domains:** the explore↔exploit axis, from the domain registry + competence
  beliefs (an unknown domain = a max-uncertainty competence belief, e.g. the environment).
- **System state:** health, queue pressure, resources, competence-by-domain.
- **Emotions / affect:** valence/arousal/mood → *which* drive wins; stress → conserve, ease → explore.
- **Environment:** `SelfState.situation` — novel? what's around? ambient pressure (a harsh climate
  tilts toward upkeep over exploration).
- **Fitness:** certainty / coherence / competence / confidence.

### C. Two layers
- **Global developmental drive** → overall intensity + breadth (young/underdeveloped = broad hunger
  to learn/interact/experience; mature = targeted deepening and gap-filling).
- **Local target selection** → *which* specific gap / unknown / domain / tool to pursue now.

### D. Broadened pursuits (output space)
Not only "curiosity goals." The drive spawns pursuits to:
- **Learn** — acquire knowledge (research/understand/taught).
- **Use tools** — exercise and *expand* tool competence (advance what it CAN do).
- **Explore the environment** — investigate its world (the environment domain).
- **Interact / accumulate experience** — engage the world, build memories.
- **Advance the capability frontier** — push past current can/can't: validate/learn new operators.

The felt *"want to advance past what I know and what I can do"* = a **frontier drive over two
frontiers**: the **knowledge frontier** (unknown beliefs/domains) and the **capability frontier**
(operators it lacks or hasn't validated). It is affect-linked, so it is *felt*, not just computed.

### E. Event-triggered, NOT a loop
Motivation re-synthesizes **only on an event that could change it** — never on a timer or cycle:
- `COMPETENCE_CHANGED` (a domain moved, incl. a new unknown), `EVIDENCE_ADMITTED` (beliefs changed),
  `ENVIRONMENT_ENCOUNTERED` (somewhere new), `OUTCOME_OBSERVED` (a pursuit finished), `DEFICIT_DIAGNOSED`
  (a gap surfaced), belief/memory added (developmental appraisal shifts), affect changed (which drive
  wins changes).
- **The loop-replacement is a `CAPACITY_FREED` / became-idle event.** When a pursuit completes it emits
  `OUTCOME_OBSERVED` *and* frees a slot → that triggers **one** synthesis → if a pursuit is warranted,
  **disposition permits, and there is capacity**, it adopts **at most one**. That pursuit runs,
  completes, frees the slot → triggers the next. A **self-sustaining event chain**, not a poll: each
  outcome wakes the next. Boot emits the first trigger (init-complete / `ENVIRONMENT_ENCOUNTERED`) to
  start it.
- Goal → falsifiable hypothesis → task → outcome → belief/competence update → next trigger. Reactions
  all the way down. **It goes quiet when nothing warrants pursuit** (no timer runs to rediscover that),
  and any later event re-triggers it.
- **Retire** `_run_exploration_cycle`-on-a-coordination-timer and the `%5` motivation poll backstop.

### F. Disposition-gated
The arbiter/disposition already gates expression (queue-aware; declines under escalation). Kept.

### G. Non-blocking + concurrent (parallelism)
Motivation runs **alongside** primary work, never blocking it. While the substrate serves a
conversation or a research task, it can — from the whole-state synthesis — *feel it lacks knowledge
and want to learn*, and act on that **in parallel**. This **relaxes the current singleton**
(`_run_exploration_cycle`: "Only one task runs at a time") to **bounded concurrency**: user-facing
work and self-directed learning coexist, up to real capacity, still guarded by disposition + queue
pressure so it never generates debt. The substrate does multiple things at once.

Each pursuit also carries an **execution mode**, chosen from *urgency × scope*:
- **awaited / fast** — a need-it-now answer returns within the turn (a single quick lookup);
- **background / parallel** — a long or multi-source compilation runs off the turn via
  `queue_authority.submit`, reconciled through `JOB_COMPLETED`, folded in as results land;
- and the range between. The mode is a first-class part of adopting a pursuit, not a fixed policy.

### H. Conversation: curiosity in dialogue, decoupled from teaching
- **Curiosity fires during conversation, not only when idle.** When the substrate is reasoning over
  what a user says and hits a genuine gap ("I don't actually know what they mean"), that not-knowing
  triggers the same motivation → it starts research in the **task-appropriate mode** (awaited if the
  user needs it now; background/parallel if it's a compile-many-sources ask) and **keeps the
  conversation going** — folding the finding in when it lands (`JOB_COMPLETED`), never blocking.
- **Conversation is NOT teaching.** Today `understand()` auto-stores any non-question — *"TOLD, not
  asked. Store it"* → `await self.teach(sentence)` — which makes dialogue write beliefs. That is the
  conflation to remove: in conversation the substrate **reasons over** what is said and gets curious
  about what it lacks; it does **not** ingest statements as facts. Teaching stays a **deliberate,
  gated** act (`teach`/`learn_fact`), never automatic from the declarative mood of a sentence.

## What moves / stays / retires (concrete)
- **MOVE → coordinator:** the pursuit-decision synthesis (new faculty method over `SelfState` + stores).
- **KEEP (self mechanics):** affect, fitness, reward accounting, persistence, embeddings.
- **ADD:** developmental appraisal; environment input; known/unknown-domain axis; capability-frontier
  (tool/operator) drive; belief-trajectory signal.
- **RETIRE:** `LLM_AUTONOMOUS` consolidation preference; playbook-as-work-selector; the %5 poll.

## Build phases (each proven by a real experiment — no stubs, no LLM)
- **Phase 0 — Developmental appraisal. ✅ DONE.** `AutonomousCoordinator._development()` reads REAL
  counts — `self.learning.knowledge_base_size()` (concepts/rules/memories, a real DB query) + domain
  registry (`domains`, `unpopulated_domain_ids` → known/unknown breadth); `None` where unreadable,
  never fabricated. Exposes saturating per-axis `knowledge_pressure`/`experience_pressure` + overall
  `growth_pressure = max(axes)` (hungry if underdeveloped on ANY axis, so knowledge-rich + memory-poor
  still reads hungry). Composed into `SelfState.development` via `state()`. *Verified:* compiles;
  wiring introspected; curve real + monotonic (0 memories→1.0, half at the half-point, →0 as it grows).
  Not yet booted against the live DB (wiring + source + curve verified).
- **Phase 1 — Unify the synthesis in the coordinator. ◑ SYNTHESIS BUILT + VERIFIED; rewire pending.**
  `_intrinsic_pursuits()` reads the whole state — `_development()` (global hunger) + the epistemic
  engine's `get_unstable_regions()` (local not-knowing) — and returns a DETERMINISTIC ranked list of
  pursuits, each tagged by frontier via `_frontier_of` (environment / capability / knowledge) so it
  dispatches to the right closer. `_score_pursuits` lifts local entropy by global growth and boosts an
  unknown environment. IM mechanics untouched. *Verified:* compiles; frontier routing correct;
  deterministic; hunger raises scores; environment boosted. *Still to do (next step):* rewire
  `_run_exploration_cycle` to source pursuits from `_intrinsic_pursuits()` and make the refresh
  event-triggered — the behavior-changing part, to be done carefully (ideally with a boot test), not
  big-bang.
- **Phase 2 — Broaden pursuits + execution mode.** Add tool-usage, capability-frontier
  (missing/unvalidated operators), environment exploration, and interaction as first-class pursuits;
  each pursuit carries an **execution mode** (awaited/fast vs background/parallel) chosen from
  urgency × scope. *Verify:* a missing operator → a capability-advance pursuit; a novel environment →
  an investigate pursuit; low experience → an interaction pursuit; an urgent ask → awaited, a
  compile-many-sources ask → a background job.
- **Phase 3 — Concurrency (relax the singleton).** Let self-directed pursuits run **in parallel with
  primary user-facing work**, bounded by real capacity + disposition + queue pressure (no debt).
  Replace `_run_exploration_cycle`'s one-at-a-time rule with bounded concurrency. *Verify:* the
  substrate serves a task AND pursues a learning goal at the same time; pressure/disposition still cap
  and suspend it.
- **Phase 4 — Conversation: curiosity in dialogue, decoupled from teaching.** In `understand()`:
  (a) a genuine conversational gap triggers curiosity → research in the task-appropriate mode
  (awaited vs background), conversation continues, finding folded in on `JOB_COMPLETED`; (b) **remove
  the auto-teach** of non-questions — dialogue reasons + gets curious, never ingests statements as
  facts; teaching stays a deliberate, gated act. *Verify:* stating something in conversation writes no
  belief; a gap spawns non-blocking research; an urgent gap returns within the turn.
- **Phase 5 — Retire duplicates.** Remove the %5 poll (fully event-driven), demote the playbook
  selector to a seed, retire the LLM consolidation preference. *Verify:* motivation still fires on
  events with the poll gone; playbook seeds are adapted from outcomes, not fixed.

## Calibration & optimality are EARNED, not asserted
A benchmark that the machinery *functions* (reads real state → produces a real ranking) does **not**
establish that the pressure values are well-**calibrated** or that the ranking is operationally
**optimal**. Those are separate claims a snapshot cannot support:
- The half-points (`5000`/`500`) and score-weights are **provisional seeds, not validated values** —
  never treat them as "right."
- **Calibration** requires reference states (fresh substrate → high hunger, mature → low) and,
  properly, correlation of pressure with *actual learning benefit*.
- **Optimality** requires **closed-loop outcomes over many cycles**: did pursuing this pursuit, at
  this rank/pressure, actually reduce uncertainty / grow competence / raise fitness — vs. alternatives?
- **Mechanism (required):** every pursuit's closed-loop success criterion (uncertainty-delta) is the
  evidence; feed those outcomes into the `StrategyAdaptationGate` (Wilson CI, already in-repo) so the
  **pressures and weights adapt toward what demonstrably yields growth**. Calibration becomes a
  *learned, measured* property; the ranking's quality is judged by outcomes, not declared. Seeds +
  adapt — the same stance as the playbook.

## Evidence to date
- **Phase 0 developmental appraisal** — verified on the live DB (256,195 concepts / 7,549 memories →
  `growth_pressure 0.062`: a *mature* substrate reads low-hunger, correctly).
- **Phase 1 synthesis** — `_intrinsic_pursuits` proven deterministic, frontier-routed, dedup'd, and
  structurally tie-broken over 159 real beliefs (surfaces both `knowledge` and `capability` pursuits).
- **Closed loop (`experiments/MOTIVATION-CLOSEDLOOP-01`, 11/11)** — a selected capability pursuit,
  given REAL competence evidence (at the real `COMPETENCE_EVIDENCE_QUALITY`), has its uncertainty fall
  over several cycles (never flipped by one), leaves the unstable set, drops from the ranking, and the
  next pursuit changes. *Proves:* selected tasks improve competence; original uncertainty decreases;
  next pursuit changes. *Does NOT prove:* autonomous web-task execution produced the evidence (stood
  in by a real update), nor that the pressures are calibrated / the ranking operationally optimal —
  those stay earned from runtime outcomes.

## Knowledge → operability (the KNOW→DO bridge)
The substrate already keeps *what it KNOWS* about a domain (`maturity_score`/`structural_complexity`,
grown by research/teaching) SEPARATE from *what it can DO* (operator competence, earned by acting) —
by design (credit invariant). The gap: for domains where operating **is** applying knowledge (advise,
troubleshoot), sufficient knowledge should **confer operability** without a learned operator — gated
by a **domain-dependent** bar (trivial domains need little; hard/high-stakes need a lot).

Design (user chose **hybrid: stakes + earned**):
- **Satisfaction** (the KNOW side) — `_domain_satisfaction(domain)`: knowledge COVERAGE
  (`structural_complexity`, [0,1]) **noisy-OR** belief CONFIDENCE (`1 − mean entropy` of the domain's
  beliefs). Two partly-independent stores, so noisy-OR (not product, which wrongly zeros a domain rich
  in one, empty in the other). **BUILT + benchmarked on 94 live domains** (physics 1.0, conversation
  0.90, empty placeholders 0.0); benchmarking caught & fixed the product-formula flaw.
- **Bar** = **stakes base × earned adjustment**. Stakes base from the domain's actions' consequence
  classes (`ActionClass`/`_declared_consequence` → `_RISK` scale), neutral 0.5 where unknown; earned
  adjustment shifts it per-domain from real operating outcomes (Wilson-CI / `StrategyAdaptationGate`).
  - **`_domain_stakes` BUILT + benchmarked** — and the benchmark shows it is **inert on current data**:
    0/94 domains have executable operators, so every domain falls back to the 0.5 neutral prior. Real
    code, but no per-domain signal yet. **Implication:** bar differentiation must come from the EARNED
    half and/or the ENVIRONMENT axes — with operator-stakes empty, environment state (pressure +
    verified outcomes) is likely the *primary* bar signal, not secondary.
  - **EARNED half BUILT + benchmarked (OPERABILITY-BAR-01, 11/11).** One owner for per-domain action
    accounting (`UniversalDomainMaster` / `domain_controllability`, +`operating_attempts`/`operating_wins`
    columns) — `record_operating_outcome(domain, success)` + `operating_reliability(domain)` returning the
    **Wilson lower bound** (reuses `StrategyAdaptationGate._wilson_ci`). Distinct measurement from
    competence (did I LEARN the operators) and controllability (do my acts MOVE the world): correctness
    of operation. **Neutral (0.5) below `OPERATING_MIN_SAMPLE=4`** — a handful of wins can't swing trust
    (same "earned over several, never one" discipline as competence).
  - **Bar math:** `bar = clamp(stakes − BAND·(earned − 0.5), FLOOR=0.2, CEIL=0.99)`, `BAND=0.3`. Earned
    neutral → bar = stakes; proven-correct record → bar drops (0.918 earned pulled a 0.5 stakes bar to
    **0.3746**); poor record → bar rises (0.0 earned pushed it to **0.65**). No bootstrap deadlock:
    neutral-until-earned means a fresh high-stakes domain sits at full stakes → must KNOW first, then
    eases as correct operation is proven.
  - **Borrowed knowledge (cross-domain transfer on the KNOW side) BUILT + benchmarked
    (BORROWED-KNOWLEDGE-01, 9/9).** Confidently-related KNOWN domains lend a discounted prior so a new
    domain coupled to one the substrate knows cold is not starting from zero — the load-lightening the
    user called for (esp. long-horizon). `_borrowed_satisfaction`: top-5 neighbors from `similar_domains`
    with similarity ≥ `_BORROW_REL_MIN=0.30`, each lends `similarity × neighbor's OWN satisfaction`
    (**one hop**, never transitive), noisy-OR'd, **capped `_BORROW_CAP=0.5`** (accelerant, not a bypass).
    Gate uses `effective = noisy-OR(own, borrowed)`, reports own/borrowed/effective separately, reason
    `satisfied-via-transfer`. Similarity (`calculate_domain_similarity`) is REAL & discriminating
    (conceptual coupling + shared relation-vocabulary), so unlike operator-stakes this is **NOT inert**:
    **LIVE, 83/94 real domains already have a confidently-related lender.** High-stakes bars still can't
    be cleared by borrowing alone — a dangerous unknown still demands real own knowledge. Distinct from
    operator transfer (`transfer_relation`, which needs target operators): this transfers CONFIDENCE TO
    KNOW, not capability.
- **Operability gate BUILT (`_domain_operability`).** `operable = effective satisfaction ≥ bar`; below → abstain
  + keep researching (`reason` = `below-bar-researching` before any history, `below-bar-earning` once
  outcomes exist), `unknown-domain` when unlearned. A pure MEASUREMENT (decides nothing), like
  `diagnose_deficit`. **Producer wired** at the authoritative verified-outcome point
  (`_execute_and_validate_task`, after `is_complete`): records an operating outcome **only** for a task
  that resolves to a domain AND is **not** an intrinsic drive/learning goal (those feed competence —
  recording them here would re-conflate KNOW with OPERATE). Honestly QUIET today: the only domain-tagged
  tasks currently flowing ARE drive goals, so no operating outcome records until the KNOW→DO operating
  loop runs domain-scoped operations under the gate — the honest empty state, not a stub.
- **LIVE honesty (OPERABILITY-BAR-01 part B):** across all 95 real domains the bar sits **flat at the
  stakes base (0.5)** and earned is neutral everywhere — 0/12 sampled operable. The mechanism is correct;
  per-domain differentiation is *earned from runtime*, not asserted from a cold snapshot. Confirms the
  stakes-inert finding: differentiation will come from EARNED (runtime) + ENVIRONMENT, not operator-stakes.
- Routing: a `knowledge`-frontier pursuit for a domain-to-operate is done at `satisfaction ≥ bar`, not
  at one fact. DONE: satisfaction, stakes base, earned adjustment, gate, producer. TODO: CONDITIONS +
  VERIFY environment axes (world-integration).

## Selection sourced from the frontier + EVENT-DRIVEN (BUILT, INTRINSIC-EVENTDRIVEN-01, 9/9)
The unattended SELECTION now uses `_intrinsic_pursuits` (the whole-self frontier), not the old
`IntrinsicMotivationSystem.generate_curiosity_driven_goals`. `_pursuit_to_goal` routes each frontier to
its REAL closer — knowledge→a "Research …" goal the `understand` loop answers; capability→a competence
DRIVE goal `_execute_drive_goal` runs; environment→None (closed by `_react_investigate_environment`). IMS
keeps affect/reward/fitness (the DECISION moved to the coordinator, the mechanics stayed).
**Event-driven, not polled:** `_react_pursue_frontier` (coalesced single-flight) is registered on
COMPETENCE_CHANGED / OUTCOME_OBSERVED / EVIDENCE_ADMITTED / ENVIRONMENT_ENCOUNTERED / DEFICIT_DIAGNOSED
(LOW priority, after the state-updating reactions). A completed pursuit emits the events that wake the
next selection — self-sustaining through events, quiet when nothing changes. A single BOOT KICK on going
live resumes the drive after a restart. The idle-timer exploration poll is RETIRED. Still gated by the
arbiter (disposition) + queue pressure + cap — at cold boot the arbiter declines (real gate); queuing from
an event needs a warmed/disposed appraisal, which the autonomy/scale tests exercise next.

### Environment as the CONDITIONS + VERIFY axes (long-horizon)
Operability is really THREE axes, and environment state lives in two of them (distinct from *domain
knowledge* — knowledge is stable, environment state is not):
- **KNOW** — domain satisfaction ≥ stakes+earned bar (*may I operate here?*).
- **CONDITIONS** — the environment's pressure/climate (Tet `sense()`), **felt** (sense → interoception
  → affect) and modulating **disposition**: under a storm / high pressure, be more cautious (raise the
  bar, defer, verify harder). Plugs into the same disposition gate that governs exploration.
- **VERIFY** — the substrate cannot *know* it satisfied an environment requirement from internal
  confidence; it must **observe the environment state after acting** and confirm the effect matched.
  Crucially, **this grounds the "earned" half of the bar**: earned outcomes come from the *world
  confirming* success, not self-report — which keeps long-horizon operating honest (no drift on a
  stale internal model).
Status: Tet `sense()` + the environment-investigation exist; wiring **pressure → affect → operate-gate**
(CONDITIONS) and **environment-observed outcome → earned** (VERIFY) is the long-horizon layer, not yet
built — but it slots in without rethinking the hybrid (VERIFY = the source of "earned"; CONDITIONS = a
disposition modulator).

## Constraints
100% offline, **no LLM**, **no stubs / no placeholders**, model-free by construction, **one
authority**, **event-driven**, every phase verified by a reproducible experiment. Reported claims stay
scoped to what the evidence supports — "the machinery computes/acts on real signals" is not "the
signals are calibrated" or "the ranking is optimal"; those are earned from runtime outcomes.

## Risks / to-verify before editing
- Enumerate **all** coordinator call sites of `IntrinsicMotivationSystem` before moving the decision,
  so the many existing calls don't break (the mechanics stay callable).
- Confirm cheap, real sources for the developmental counts (belief-store count, memory-agent count,
  domain-registry known/unknown) — no expensive scans on the hot path.
- Preserve affect/fitness ownership used elsewhere (e.g. `state()`, disposition).
