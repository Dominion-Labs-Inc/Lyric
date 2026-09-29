# Lyric — Architecture

*The canonical architecture document. Verified against the running system
(`experiments/systems/VERIFY-01`). This master holds the conceptual model, the subsystem
diagram, the authority map, and the belief circulation; the **exhaustive method-by-method
reference for every subsystem** lives in [`docs/architecture/`](architecture/) (linked per
faculty below). Living document — update it (and the diagram / belief I/O) whenever a
subsystem, method, or wiring changes. Supersedes `ARCHITECTURE_GRAPH.md` and
`AUTONOMOUS_COORDINATOR_MAP.md`; the terse name+line inventory is `SUBSTRATE_SYSTEMS_MAP.md`.*

---

## 1. What Lyric is

Lyric is a **persistent cognitive substrate**: a system that maintains and develops
structured knowledge, memory, beliefs, learned operators, competence, and goals over time,
and reasons over what it holds rather than regenerating an answer from scratch. Cognition is
**one body** — not a bus between independent services. Each faculty is an **subsystem that does
one thing**, owned by exactly one authority, and the **coordinator is the body** that holds
every authority. The output of one subsystem becomes structured input to another: a conclusion
revises a belief, an action produces an experience, an experience induces an operator, a
competence gap raises the motivation to explore.

> **Language models.** Lyric's cognition uses no language model. Reasoning, learning,
> planning, action, and verification consult none. The last component that could consult one
> — the teaching module `core/learning/teacher_policy.py` — has been deleted, along with
> `unified_llm` and `llm_teacher`. There is no longer any path from the substrate to a
> generative model. One local sentence encoder remains, for vector similarity only; it
> produces vectors, never text, and decides nothing.

---

## 2. The body — Module authorities, and the belief circulation

**One owner per subsystem; the coordinator holds them all.** A snapshot of the running
system is *one coherent entity with one state*, not a service mesh.

```mermaid
flowchart TB
    subgraph BODY["AutonomousCoordinator — the body / self (holds every authority)"]
      COORD["self-state: affect · disposition · appraisal · identity<br/>execution · event spine (on/emit/drain) · constitution · bearing · drift · idle tiers"]
    end

    subgraph Module ["Authorities — one owner per subsystem"]
      LEARN["**Learning**<br/>UnifiedLearningSystem<br/>get_learning_authority()"]
      REASON["**Reasoning**<br/>NeuralSymbolicBridge<br/>get_neural_bridge()"]
      MEM["**Memory**<br/>MemoryAgent<br/>get_memory_agent()"]
      DOM["**Domain**<br/>UniversalDomainMaster<br/>get_universal_domain_master()"]
      INGRESS["**Semantics-write**<br/>CognitiveIngress<br/>get_cognitive_ingress()"]
      BELIEF["**Beliefs — circulation hub**<br/>BayesianUncertaintySystem<br/>get_uncertainty_system()"]
    end

    subgraph SEC["Governance — the substrate's own law"]
      SAFETY["Constitution (in the coordinator)<br/>five laws · four verdicts · input screen<br/>the single gate on execute_tool"]
    end

    COORD --> LEARN & REASON & MEM & DOM & SAFETY

    LEARN -->|"learn_fact → admit"| INGRESS
    INGRESS -->|"concepts + recallable episode"| MEM
    LEARN -->|"_fan_out_learning"| BELIEF
    REASON -->|"conclusions / hypotheses"| BELIEF
    DOM -->|"competence beliefs"| BELIEF
    COORD -->|"completion beliefs (DID/SAW)"| BELIEF

    BELIEF -->|"posterior → answer/abstain (p≥0.9/≤0.1)"| REASON
    BELIEF -->|"posterior → act / re-verify"| COORD
    BELIEF -->|"beliefs_for_domain → stamp memory"| MEM
    BELIEF -->|"uncertainty → exploration"| DOM
```

### Authority accessors
| Module | Authority (accessor) | File | Reference |
|---|---|---|---|
| Learning | `UnifiedLearningSystem` — `get_learning_authority()` | `core/learning/unified_learning_system.py` | [learning.md](architecture/learning.md) |
| Reasoning | `NeuralSymbolicBridge` — `get_neural_bridge()` | `core/reasoning/neural_bridge.py` | [reasoning.md](architecture/reasoning.md) |
| Memory | `MemoryAgent` — `get_memory_agent()` (async) | `core/agents/memory_agent.py` | [memory.md](architecture/memory.md) |
| Beliefs | `BayesianUncertaintySystem` — `get_uncertainty_system()` | `core/reasoning/bayesian_uncertainty.py` | [beliefs.md](architecture/beliefs.md) |
| Domain | `UniversalDomainMaster` — `get_universal_domain_master()` | `core/integration/universal_domain_master.py` | [domain.md](architecture/domain.md) |
| Semantics-write | `CognitiveIngress` — `get_cognitive_ingress()` | `core/semantics/cognitive_ingress.py` | [semantics-ingress.md](architecture/semantics-ingress.md) |
| Governance (the act gate) | `Constitution` — `get_constitution()` / `judge_act()` | `core/agents/autonomous/autonomous_coordinator.py` | [security.md](architecture/security.md) |
| Body / control plane | `AutonomousCoordinator` — `get_autonomous_coordinator()` | `core/agents/autonomous/autonomous_coordinator.py` | [coordinator.md](architecture/coordinator.md) |

### The belief circulation (feeders → hub → consumers)
Beliefs are the blood: one artery in (the fan-out door), a bounded set of tissues perfused.
- **Feeders (move a posterior — all via `observe_claim`/`create_belief`/`update_belief`):**
  teaching + perception (`_fan_out_learning`, `evidence_producers`→`fan_out_ingested`),
  reasoning conclusions (`epistemic_engine`, `hypothesis_testing`, `abstract_reasoning`,
  `hierarchical_abstraction`), competence (`UniversalDomainMaster`), task completion (the
  coordinator's DID/SAW belief).
- **Consumers (read a posterior to act):** task completion (`_decide_completion`) and
  perception act-vs-verify (`perceive`, which emits `PERCEPT_RECOGNIZED`) in the
  coordinator; reasoning answer/abstain (`neural_bridge`, p≥0.9/≤0.1); exploration
  (`intrinsic_motivation`); memory stamping — each memory records the live
  `belief_state`, the appraisal self-state, AND (recency-gated) the `perceptual_state`,
  so a recalled memory carries what was perceived + believed + felt at that moment.

### Knowledge → emotion (and the decision invariant)
Belief movement is also what the substrate *feels*. The **reasoning authority** owns the
interpretation: `NeuralSymbolicBridge.epistemic_affect_signal()` reads how the belief
graph moved since last asked — from **any** source (perception, teaching, reasoning),
via `EpistemicEngine.interpret_drift()`, a read-only diff — and summarizes it into the
emotional dials (`uncertainty_reduction` → confidence ↑; `uncertainty_increase`/
`contradiction` → doubt + curiosity ↑). The coordinator (the body) relays that signal to
the appraisal authority; it interprets nothing itself. No subsystem special-cases itself into
emotion — they all feed it by moving beliefs.

**The invariant:** emotion may shape **disposition** (how cautious, how much to verify,
what to attend to) and may color beliefs — but **in a core decision it has no vote.** A
decision is *evidence vs. a bar*; emotion can set the bar (disposition), never substitute
for the evidence. `perceive`/`_decide_completion` embody this: the accept bar is
disposition-derived (appraisal), the decision itself is `posterior ≥ bar`. The substrate
always takes the most logical path; feeling changes how hard it looks, not what it concludes.

### Resilience in a single-subsystem body
There are no spare hearts (redundancy is the duplicate-authority anti-pattern). Robustness
comes from three substitutes: **honest distress signalling** (`raise_if_structural` — a
broken subsystem re-raises instead of masking a "0 done"), **failure isolation** (one subsystem's
fault must not cascade), and **homeostasis** (the health/recovery event loop detects distress
and heals). The nervous path (the coordinator's hot loop) must never block.

---

## 3. Persistent cognitive state

The shared, durable state every subsystem reads and writes. Each element has a single authority.

| Element | What it is | Store |
|---|---|---|
| **Concepts** | typed nodes of what the system knows | `unified.concepts` |
| **Relations** | typed, polarity-bearing edges (is-a, part-of, denials) | `unified.concept_relations` |
| **Memory** | retained experiences, retrievable and consolidated | memory tiers (`MemoryAgent`) |
| **Beliefs** | propositions held with calibrated, revisable uncertainty | `unified.beliefs` |
| **Operators** | learned, variable-carrying transformations with add/remove effects | `unified.learned_rules` |
| **Competence** | per-subject estimate of what the system can *do* | competence beliefs (UDM) |
| **Domains** | subjects — clusters of concepts and operators, created automatically | `unified.domains` |
| **Experience** | before/action/after traces that feed learning | `unified.operator_demonstrations` |

The elements form a cycle: experience → memory → learning → (operators, concepts, beliefs) →
reasoning → planning → action → experience.

---

## 4. The faculties (one subsystem each, all held by the coordinator)

Each links to its exhaustive method reference.

- **Reasoning** — [`architecture/reasoning.md`](architecture/reasoning.md). `coord.reason_about(q)`
  → `NeuralSymbolicBridge.reason`. Substrate-first, no model fallback: substrate solvers
  (taxonomy, concept graph, held/induced rules, symbolic, equation, sequence), the eleven
  kinds, and the named modes. Returns `unsupported` rather than guessing; diagnoses gaps.
- **Learning** — [`architecture/learning.md`](architecture/learning.md). The one learning
  authority (`coord.learning`): instruction fan-out, operator induction (off the acting
  path), consolidation, and the belief door. Perception classifiers are owned here.
- **Memory** — [`architecture/memory.md`](architecture/memory.md). `MemoryAgent`
  (`coord.memory`): worthiness-gated write, type inference, recall, consolidation/abstraction,
  tiering, governed parameter changes.
- **Beliefs** — [`architecture/beliefs.md`](architecture/beliefs.md). The circulation hub;
  find-or-create-by-claim, graded/revisable posteriors, constraint propagation, decay.
- **Domain** — [`architecture/domain.md`](architecture/domain.md). `UniversalDomainMaster`:
  domain existence, competence/controllability, crystallization, cross-domain transfer.
- **Semantics-write** — [`architecture/semantics-ingress.md`](architecture/semantics-ingress.md).
  `CognitiveIngress`: the one door knowledge comes through (admit → concepts + aliases +
  evidence + memory), with the `MIN_ADMIT_QUALITY` floor.
- **Perception** — the one sensory pipeline. `coord.see(path)` and `coord.hear(path)` *sense*
  (classical CV and classical signal processing, no model) through ONE faculty
  (`PerceptionFaculty`, readers `vision` and `hearing`) and route the structure through
  `PerceptionManager.process_input`, the **sole admitter** — every modality (vision, hearing,
  sensors) admitted once, through one owner. Hearing states each sound as a perceived
  individual on sight's own contract (`isa` pitched/unpitched, register, onset; level, start
  and length as facts about the recording; `before`/`louder_than`/`higher_than` between
  neighbours), so the naming reflex, induction and `describe_kind` serve it unchanged, and it
  recognises known sounds by spectral-landmark agreement. REMEMBERING IS REBUILDING: a hearing
  is kept as a trace (each sound's envelope, pitch, periodicity, loudness, rise; a few percent
  of the recording, which is not kept) and a seeing as a gist (the scene small, the most
  prominent things in detail); `coord.recollect(memory_id)` rebuilds them, and the rebuilt
  sound or picture is perceived as the same (RECALL-01). SPEECH IS HEARD AS FAR AS IT WAS
  TAUGHT (`core.perception.speech`): words and voices are taught by HEARING an example, told
  what it is (`coord.learn_word`, `coord.learn_voice`) -- the lesson is a hearing like any
  other, remembered as one, its trace keeping the example measured for matching;
  a recording is divided into words in one pass (connected-word dynamic time warping, pauses
  where hearing hears no sound), each span named only when one taught word clearly wins
  (`said`, `heard_text`), each sound judged a voice by how near the taught voices it lies
  (`isa voice`), and whose voice named only when one clearly wins on a second of voiced
  speech (`spoken_by`) (SPEECH-01). MUSIC IS HEARD IN EVERY RECORDING (`core.perception.music`,
  no model): the key by the fit of its pitch-class profile to the Krumhansl-Kessler key profiles
  (`in_key`, claimed only when the fit is close), the tempo by the periodicity of its onsets
  (Ellis; `has_tempo`, with the half- or double-speed rival kept), and the notes of a melody
  where a single line holds its pitches at a singer's pace (`melody`, kept in the percept and
  its memory, told in words); each claim's support is set from how often such a reading
  matched people's annotations (GTZAN, GiantSteps, vocadito), and speech is heard as no music.
  A SONG is taught as a word is, by hearing it, told its title (`coord.learn_song`); its trace
  keeps the song's landmarks, and a recording playing it is known by the share of landmarks
  that agree (`plays`), through a room and a codec (SONGS-01). EACH SENSE MEASURES IN A PROCESS OF ITS OWN
  (`core.perception.senses`): sight and hearing are programs the faculty talks to over pipes,
  so the substrate hears, sees and reasons at the same time; a sense process found dead is
  started again and the perception given to it once (SENSES-TOGETHER-01). THE LIVE SENSES
  (`core.perception.live`) listen to a microphone and look at a camera for as long as the
  substrate runs (`core/main.py`'s `run`, never a bare `start`); the ear cuts the stream into
  utterances by hearing's own sounds and keeps one only when the substrate's taught NAME is in
  it, or taught words are firmly heard in it within attention of one that was -- everything
  else is dropped inside the ear's process. A kept utterance is heard through `hear`, the scene
  looked at through `see`, and a complete hearing goes to the front door
  (`handle_user_request`), the same conversation typed words go to (LIVE-01).
  `coord.perceive(classifier, instance, id)` recognizes and lets the recognition's
  posterior govern behaviour through the **same acceptance band as completion**, emitting
  `PERCEPT_RECOGNIZED` → `_react_percept` (ACT stands; VERIFY → known-unknown; ABSTAIN
  nothing). A percept is a belief **feeder**, and each memory stamps the contemporaneous
  `perceptual_state` so a recalled memory holds what was perceived *and* believed *and*
  felt. A percept also **feeds the emotional state** — not by a perception-specific hook,
  but because a percept moves beliefs, and belief movement is read by the epistemic
  channel (below) like movement from any other source.
- **Governance** — [`architecture/security.md`](architecture/security.md). The substrate's own law,
  held by the `Constitution` inside the coordinator and applied at the single gate every tool call
  passes (`tool_registry.execute_tool`); self-defense is the Constitution and `ThreatSense`
  together. World/DHCM security lives in the world's factory, outside Lyric.
- **The body / coordinator** — [`architecture/coordinator.md`](architecture/coordinator.md).
  Holds every authority; execution faculty (`execute_task`), the self (`state`/`render`/
  `disposition`), grounded completion (`_derive_completion_anchor`→`_decide_completion`, DID+SAW),
  the event spine + reactions, and the idle tiers. The substrate never modifies itself: it has no
  model weights and never rewrites its code or configuration — it improves only by learning.

---

## 5. Cross-faculty loops

- **Experience → learning:** action → outcome → experience → operators/knowledge → next plan.
- **Completion:** action → DID + independent SAW → completion belief → done / recovery.
- **Intrinsic learning:** competence gap → epistemic uncertainty → exploration target →
  experience → competence update → uncertainty falls.

Each loop crosses several subsystems; removing any one breaks it. That is what makes the substrate
one body rather than co-resident parts.

---

## 6. Coordination and standing operation

- **One coordinator, one shared state.** One authority per state kind.
- **Reactive event spine:** `on` / `emit` / `_reactive_drain_worker`; reactions (`_react_*`)
  let one subsystem's outcome wake another (a demonstration triggers induction, an admitted fact
  triggers domain crystallisation, a health event triggers recovery).
- **Standing background tiers** (13, one scheduler, `_register_idle_subsystems`): security,
  health & recovery, system review, knowledge refresh, self-improvement, meta-learning, memory
  consolidation, self-optimisation, domain expansion/discovery, operator exploration/induction,
  analogy discovery — plus a constitutional self-check.

---

## 7. Running it

Canonical runtime: `./venv_lyric/bin/python3` (Python 3.11). Postgres at `127.0.0.1:5433`,
database `lyric_db`.

```python
from core.main import get_system
system = get_system(); await system.initialize()
coord = system.autonomous_coordinator
```

Environment: `PYTHONPATH="$PWD"`, `POSTGRES_PORT=5433`, `LYRIC_NO_WATCHDOG=1`.

---

## 8. Repository layout & verification

- `core/` — the substrate: `agents/autonomous` (the coordinator), `reasoning`, `learning`,
  `memory`, `execution`, `domain`, `integration`, `semantics`, `governance`, `security`,
  `health`, `tools`.
- `docs/` — root holds only this file + `README.md`; everything else is categorized in
  subfolders: `architecture/` (per-subsystem method references + `SUBSTRATE_SYSTEMS_MAP.md`,
  the terse inventory + seam/honesty audit), `design/` (internal design notes), `research/`
  (`LAB_NOTEBOOK.md` the scientific record, `RESEARCH_OOD_ABSTENTION.md`, theses, papers),
  `security/`, `audits/`, `governance/`, `teaching_sessions/`, `archive/`.
- `experiments/` — reproducible studies (`experiment.py` + `manifest.json` + `README.md`);
  `systems/VERIFY-01` exercises reasoning, execution, cross-domain, domain, learning+beliefs,
  intrinsic motivation, and memory live, model-free where a model is not the point.
- `tests/` — by subsystem.
