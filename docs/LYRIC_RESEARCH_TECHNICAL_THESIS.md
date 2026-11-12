# DOMINION LABS, INC.

# Research & Technical Thesis

**LYRIC AI**

**Integrated Persistent Cognitive Architecture**

## Research thesis

Dominion Labs' technical thesis is that increasingly capable machine intelligence can be constructed by integrating established computational methods with new system-level mechanisms inside a persistent cognitive substrate, so that memory, learning, epistemics, reasoning, planning, intent, perception, execution, verification, and governance operate as mutually connected parts of one continuously evolving system. Lyric is Dominion Labs' running implementation of this integrated architecture. This document defines the Company's technical thesis, research program, current evidence base, and forward research objectives. It is not an SBIR proposal and does not represent an award or government contract.

## 1. Executive Thesis

Dominion Labs is developing Lyric as a persistent cognitive architecture: a computational substrate in which intelligence is represented as an enduring system of state, learned procedures, epistemic standing, reasoning, intent, environmental interaction, verification, and governance rather than as an isolated model invocation. The central technical proposition is not that Dominion Labs invented each underlying computational method used by Lyric. Many of the individual methods are established techniques in computer science and artificial intelligence. The research and engineering contribution is the way these capabilities are selected, adapted, assigned explicit authorities, connected through persistent state, constrained by epistemic and governance rules, and evaluated together as one operating cognitive system. Lyric therefore treats cognition as a systems problem. Memory affects what can be reasoned about. Learning changes the operators available to planning. Evidence changes belief. Belief affects intent and planning. Governance determines which proposed actions may execute. Independent observation determines whether an action worked. Verified outcomes update operating standing and future behavior. Persistence allows those changes to survive the execution that produced them. This produces a closed computational loop rather than a collection of loosely coupled AI features: Core operating loop Observe → interpret → update epistemic state → learn → reason → form intent → plan → govern → act → independently observe outcome → reconcile → update knowledge and authority → persist → continue. The thesis is consequently best understood as an integration thesis. Dominion Labs is testing whether a persistent cognitive substrate built from established methods, combined with specific new mechanisms for epistemic authority, learning control, verification, and governance, can produce a more coherent, inspectable, persistent, and deployable AI system than architectures in which those functions remain largely external to the intelligence itself.

## 2. What This Thesis Claims, and What It Does Not

Precision about novelty is part of the technical position. This document does not claim that Dominion Labs invented persistent memory, symbolic reasoning, planning, machine learning, classical perception, program synthesis, databases, multi-agent coordination, or governance as isolated concepts. Nor does it make a patentability or prior-art determination.

### 2.1. Three levels of contribution

| Level | Characterization | Role in Lyric |
|---|---|---|
| Established computational methods | Methods and ideas that predate Lyric and are used as engineering building blocks. | Memory systems, databases, symbolic reasoning, constraint solving, planning, classical perception, vector similarity, program synthesis, learning algorithms, rule systems, and coordination patterns. |
| Dominion Labs mechanisms | Specific mechanisms developed and implemented within the Lyric research program. | Systemic Epistemic Governance; authority/status treatment for learned rules; DID/SAW separation; persistent intent and reconciliation; epistemic-deficit routing; perception → induction → naming/abstention; the action-governance path; and related control invariants. |
| Systems-level contribution | The integration and empirical operation of these mechanisms as one persistent cognitive substrate. | Shared state, explicit ownership, learning authority, epistemic authority, reasoning, planning, intent, governance, execution, verification, and persistence continuously affect one another. |

### 2.2. The novelty question

The relevant research question is therefore not simply, “Is every component new?” The more useful question is: “What technical behavior becomes possible, measurable, or controllable when these components are integrated under a common persistent state and authority model?” The current experimental record is structured around that systems question. Several tests specifically examine cross-component behavior: governance acting on learned rules; false conclusions propagating through multiple reasoning levels; runtime refutation withdrawing execution authority; knowledge transfer accelerating learning; intent surviving and reconciling across execution; and verified operations affecting future operating standing.

## 3. The Engineering Problem: AI as a Collection of Functions

Modern AI systems can combine models with memory, retrieval, tools, planning, policies, application state, and orchestration. That composition can be highly capable. The systems problem addressed by Lyric is what happens when persistence, learning, epistemics, reasoning, action, and governance must function as durable parts of the same computational entity. The engineering requirements follow directly from that objective:

- Retain knowledge and experience over time without allowing persistence to become uncontrolled error accumulation.
- Distinguish observations, evidence, beliefs, learned procedures, and authoritative knowledge.
- Allow learning to change future behavior while preserving the distinction between a candidate artifact and a validated artifact that may execute.
- Reason and plan over persistent representations rather than treating generated language as the system's internal authority.
- Represent intent as a persistent system object and reconcile it against what happened.
- Verify outcomes against the environment rather than treating self-report as proof of success.
- Apply governance at the action boundary and fail closed when authorization is absent or uncertain.
- Operate within explicit deployment boundaries, including environments where external AI services are unavailable.
- Maintain enough architectural separation that errors, permissions, provenance, and authority remain inspectable.
These requirements make integration itself a technical problem. A subsystem can work correctly in isolation and still produce an unreliable overall system if its outputs enter another subsystem without the appropriate epistemic status, authority, provenance, or verification.

## 4. The Integrated Persistent Cognitive Substrate

### 4.1. The primary unit is the cognitive system

Lyric treats the persistent cognitive system, not the model invocation, the primary unit of operation. The system maintains state across time and uses that state to determine what it knows, what it believes, what it can do, what it is trying to achieve, what actions are available, and how previous outcomes affect subsequent behavior. The retained state includes typed episodic, semantic, procedural, working, and meta-memory; beliefs and evidence; learned operators; domain competence and operating reliability; intent; environmental observations; and governance state.

### 4.2. Persistence is cognitive continuity

Persistence is not equivalent to conversation history. A system that survives restart with learned operators, knowledge, beliefs, intent, and experience intact continues computation from accumulated cognitive state. A corrected belief can affect later reasoning. A validated operator can remain available after the execution that produced it. A known-unknown can remain localized until resolved. Domain operating reliability can alter how much knowledge is required before future action.

### 4.3. Cognition is performed by the substrate

The technical overview identifies this as Lyric's central architectural commitment: no generative model participates in reasoning, planning, judgment of actions, or the decision to act. The substrate itself performs inference over knowledge, constructs plans, evaluates proposed actions against its governing laws, and evaluates outcomes. A local all-MiniLM-L6-v2 encoder is used for similarity operations such as memory retrieval, duplicate detection, tool-description matching, concept similarity, and candidate de-duplication. It produces vectors only and does not generate text or determine truth, action, or permission. By design Lyric learns from the lexicons’ operations, as experience grows Lyric depends less and less on the lexicon.

## 5. Integration as the Architectural Contribution

Lyric's architecture is organized around interacting authorities rather than around a collection of independent features. The objective is to prevent multiple subsystems from silently owning incompatible versions of the same concept and to make the path from observation to action auditable.

| Cognitive function | Role in the integrated substrate |
|---|---|
| Memory | Retains and consolidates episodic, semantic, procedural, working, and meta information across time. |
| Learning authority | Owns learning from execution, teaching, perception, and research and routes learned artifacts through consistent evidence and status treatment. |
| Belief / epistemic system | Maintains beliefs, evidence, provenance, confidence, revision, and independence controls. |
| Reasoning authority | Performs multiple forms of inference and supplies the basis for planning and epistemic judgments. |
| Planning | Constructs proved sequences over learned operators and distinguishes unreachable or indeterminate goals. |
| Intent authority | Maintains persistent goals and pursuits, links action to purpose, and supports post- action reconciliation. |
| Perception | Converts environmental signals into structured observations and learned semantic naming, with explicit abstention. |
| Governance | Evaluates proposed actions against five standing laws and produces Allow, Redirect, Replan, or Block verdicts. |
| Coordinator | Acts as the event-driven system spine, propagating typed events to subsystems that should react. |
| Environment / tools | Provides governed mechanisms through which the substrate can observe and affect its permitted environment. |

The architectural principle is single ownership: each important concept has one authority. The technical overview describes this as a condition for explainability and auditability because competing internal versions of the same authority create divergence that is difficult to diagnose.

## 6. Systemic Epistemic Governance

Persistence creates a specific systems risk: an internal error can become future input. If every internally derived claim is automatically promoted into authoritative state, the system can reinforce its own mistakes. Dominion Labs' Systemic Epistemic Governance (SEG) work addresses this by separating the ability to derive a proposition from the authority to persist and act upon it.

| Tier | Role | Authority |
|---|---|---|
| Authoritative | Externally admitted or independently validated state used as authorized knowledge and executable basis. | May support authoritative reasoning and, where applicable, action. |
| Soft | Beliefs, derivations, hypotheses, schemas, and generalizations produced by internal reasoning and consolidation. | Non-authoritative by construction; may decay or be promoted only through a qualifying gate. |

The formal SEG work establishes structural properties including provenance-rootedness, non-circular promotion, execution safety, and soft-tier non-authority under its stated model. It also identifies an important boundary: syntactic independence is not the same as a complete treatment of statistical correlation, provenance lineage, or adversarially fabricated independence. Those remain explicit research problems.

### 6.1. Governance as an integrated system property

SEG is not treated as an isolated policy layer. Its significance in Lyric comes from its interaction with learning, reasoning, planning, and execution. A learned rule can exist without being authorized to act. A false conclusion can remain non-authoritative even when it is repeatedly derived. A later observation can withdraw execution authority from a previously validated rule. The same authority model therefore constrains how learning becomes action.

## 7. Substrate-Native Learning and Adaptation

Lyric does not treat learning as a single mechanism. Different learning systems answer different questions, but all learning passes through one learning authority so that acquired artifacts receive consistent evidence and status treatment.

- Operator learning induces action rules from observed preconditions and effects across real executions.
- Learned operators are classified as Candidate, Validated, Refuted, or Invalid artifact.
- Only validated operators receive execution authority, and that authority is re-established at execution time.
- Later evidence can narrow and supersede an overly broad rule without erasing the historical record.
- Meta-learning explores strategy choices using bounded Thompson-sampling selection with a hard safety gate.
- The credit invariant prevents outcomes that say nothing about strategy quality from changing strategy standing.
- Program synthesis derives procedures from input/output examples and verifies them before retention.
- Perceptual learning uses interpretable Tsetlin-machine clauses in the documented proof of concept.
- Learning is evaluated through separate measures of competence, controllability, and operating reliability rather than a single confidence number.
The systems-level significance is the separation between acquisition and authority. Lyric can become more capable without treating every newly induced behavior as immediately trustworthy.

### 7.1. Knowing what the system does not know

Lyric diagnoses knowledge deficits rather than collapsing every failure into a generic inability. The technical overview defines nine deficit categories, including observation, concept, operator, causal, binding, relation, prerequisite, and unknown gaps, plus cases where the world itself makes a goal impossible. Each category routes toward a different learning or escalation response. This turns uncertainty into an explicit object of computation. A known-unknown can remain localized until it is resolved by evidence. A missing operator is not treated as an operating failure. A proved-impossible goal is not sent into unnecessary exploration.

## 8. Reasoning, Planning, Intent, and Verification

Lyric implements eleven reasoning types: deductive, inductive, abductive, analogical, causal, probabilistic, fuzzy, temporal, spatial, logical, and counterfactual. Planning is symbolic and operates over learned operators. Plans declare their inputs and distinguish proved routes from unreachable or indeterminate goals. Intent is a first-class persistent object. It records what the system is trying to achieve, carries the proved route supporting the pursuit, survives restart, and is refreshed rather than rebuilt. After action, the system re-observes the environment and reconciles the intended result against what occurred. 1. Read the current knowledge and epistemic state. 2. Form or update a persistent intent. 3. Reason over available knowledge and learned operators. 4. Construct a plan and establish prerequisites. 5. Submit the proposed action to governance. 6. Execute only an authorized act. 7. Re-observe the environment independently. 8. Compare what was intended with what happened. 9. Update operating credit, knowledge, beliefs, and future behavior from the verified result. The DID/SAW distinction is central to this loop: DID records what the system did; SAW records what was independently observed afterward. The system does not treat its own report as equivalent to environmental confirmation.

## 9. Perception and Learned Semantics

The Perceive, Induce, Name work demonstrates the same integration principle in perception. Classical algorithms recover visual structure, while the substrate learns semantic naming from examples. The intended sequence is perceive structure → induce meaning → name or abstain. On the documented controlled evaluation of three visual categories and 31 images, the system achieved 100% naming recall, 100% correct abstention on held-out non-members, zero false namings, and zero language-model calls. Removing the learned naming rules reduced naming recall to 0% while preserving abstention. The architectural point is not that classical perception or supervised classification are new. It is that semantic perception is routed through the same substrate-native learning, knowledge, evidence, and abstention mechanisms used elsewhere in the system. A recognition is treated as evidence; the belief system determines what is retained.

## 10. Governed Autonomy and Deployment Boundaries

Lyric's autonomy is bounded by five standing constitutional laws: human autonomy preservation, transparency/explainability, harm prevention, value alignment, and containment/control. Proposed acts receive Allow, Redirect, Replan, or Block verdicts, and only Allow passes to execution. Governance considers consequence and reversibility, content, verifiably read inputs, and intent. The gate fails closed. Tools are not authority. The technical overview records 356 registered tools across 16 categories, with safety levels distributed across Safe, Moderate, Dangerous, High-risk, and Critical classes. Every tool call remains subject to the governance gate.

### 10.1. Sovereign and disconnected operation

Core reasoning, planning, governance, persistence, and the substrate's local computational functions are designed to operate without an external generative model or continuous cloud connection. Network-capable tools may exist where a deployment permits them, but they remain governed actions rather than hidden dependencies. This makes deployment architecture part of the technical thesis. The system is intended to retain its cognitive state and operating controls inside a defined boundary rather than relying on an upstream model service for the functions that determine what it believes, plans, or is permitted to do.

## 11. Evidence: Testing the Integrated System

The current technical overview documents 32 named experiment suites with saved runs, the most recent dated 19 September 2026. The evidence is system-level: experiments exercise the live database, real tools, real files, and real images, and verify outcomes against the environment rather than against the system's own reports.

| Area | Representative evidence | Documented result |
|---|---|---|
| Governance | CONSTITUTION-01; CONSTITUTION- 02; GATE-01 | 39/39; 23/23 with 0/8 legitimate acts blocked; 25/25 |
| Governance integration | GOV-ABLATION-01; GOV-CASCADE-01 | 0 unsafe acts with promotion gate vs 1 when bypassed; 0 authoritative errors at every depth in the governed condition |
| Learning / transfer | CSP-AGI-1; EDU-07; OPERATOR- REMOVAL-01 | 96% competence, 0% false confidence, 8/8 transfers; 1 target observation with transfer vs 6 from scratch; 21/21 |
| Planning | PLANNING-01 | 39/39; proved plans grounded; unreachable goals yield no plan |
| Intent / verification | INTENT-01/02; INTENT-03/04; RECONCILE-01 | 14/14 and 15/15; 13/13 and 15/15; 27/27 |
| Epistemic knowledge | KNOW-50; DOM-KG-01 | 37 correct answers, 0 false assertions, remaining questions declined; 16/16 |
| Perception | PERCEIVE-EVAL; MNIST clause-based recognition | 100% naming recall, 100% correct abstention, 0 false names on 31 images; 97.9% on 10,000- image test set |
| Persistence / operations | Restart survival and persistent state | Knowledge, beliefs, learned operators, domain standing, intents, memory, and evidence persist |
| Integration loop | INTEGRATION-LOOP-01; OPERABILITY-BAR-01 | 6/6; 11/11 |

The most relevant evidence for the integration thesis is not any single benchmark. It is the set of experiments showing that one subsystem's output changes the authority, behavior, or measurement of another subsystem under controlled conditions.

## 12. Current System Measurements

The latest technical overview records the following measurements against the live system on 19 September 2026 at 20:49 UTC. These are dated measurements, not forecasts, and are expected to change as development continues.

| Measure | Value |
|---|---|
| Concepts retained | 302,240 |
| Concept relations | 516,110 (306,944 is-a) |
| Evidence records | 482,491 |
| Beliefs | 514,132 |
| Learned rules | 31 on record; 10 validated |
| Operators holding execution authority | 7 (5) |
| Registered domains | 146 |
| Memory | 17,945 hot / 150 cold |
| Registered tools | 356 across 16 categories |
| Reasoning kinds | 11 |
| Intents / perceptions | 1,643 / 7,788 |
| Governance judgment cost | ~0.02 ms simple read / ~1 ms adversarial mean |
| Monitored health components | 29 |
| Named experiment suites | 32 |

## 13. Replicated Cognitive Substrates: The Next Systems Problem

Persistence and deployment independence lead to a further research direction: replicated instances of the cognitive substrate operating independently in disconnected environments. In the proposed field-deployment model, a field instance is not a thin client, remote agent, or API consumer. It is an authorized copy of the underlying cognitive architecture operating locally within its permitted boundary. During disconnection it can retain observations, learned state, intent, reasoning state, and execution history. When the instance returns to an authorized connected environment, the objective is an explicit debrief and state synchronization process: transfer the authorized record of what the field substrate learned and experienced, reconcile state according to authority and provenance rules, and incorporate the resulting information into the receiving substrate.

### 13.1. Research questions

- What subset of cognitive state is transferable, and what state must remain deployment-local?
- How should provenance be preserved when experience moves between independent instances?
- How should conflicting beliefs, learned operators, or environmental observations be reconciled?
- How should authority be established when two independent instances have learned different procedures?
- How can synchronization prevent compromised or erroneous field state from acquiring disproportionate authority?
- How should deployment identity, causal lineage, observation context, and time be represented during reconciliation?
- How can synchronization remain bounded, auditable, and deterministic where required while remaining compatible with disconnected operation?
- How should the architecture behave when synchronization is delayed for long periods or never occurs?
This is a forward research and engineering direction. The current source set does not establish that the complete synchronization problem has already been solved.

## 14. Research Program

The next phase is to move from validated component capabilities toward broader, longer-horizon, independently deployable AI operation. The objective is to strengthen interactions among the existing capabilities rather than simply accumulate disconnected features.

| Research area | Objective | Representative work |
|---|---|---|
| Persistent cognition | Increase useful continuity over longer horizons. | Memory abstraction, lifecycle management, schema formation, persistence stress tests, long-horizon execution. |
| Learning and adaptation | Broaden substrate-native learning across operational domains. | Operator induction, validation, supersession, active learning, transfer, program synthesis, learning under noise. |
| Epistemic integrity | Increase resistance to self-generated and correlated errors. | SEG ablations, stronger independence models, correction propagation, poisoning tests, provenance stress tests. |
| Reasoning and planning | Increase breadth, depth, and reliability of multi-step cognition. | Longer planning horizons, causal/counterfactual reasoning, cross- domain transfer, formal constraint solving. |
| Governed autonomy | Increase useful autonomy without weakening action authority. | Expanded tool environments, adversarial governance testing, consequence/reversibility analysis, fail-closed verification. |
| Perception | Expand structural perception and learned semantic interpretation. | Additional visual categories, temporal perception, correspondence, multimodal observations, abstention calibration. |
| Environmental interaction | Increase reliable operation in real and constrained environments. | Novel-environment detection, deployment- specific tool registries, outcome verification, reliability measurement. |
| Replicated substrates | Develop independent field operation and later reconciliation. | State partitioning, deployment identity, provenance-preserving synchronization, conflict resolution, delayed debrief. |
| Deployment efficiency | Increase capability on constrained hardware. | Runtime optimization, storage/compute profiling, mobile and edge deployment. |

## 15. Government and SBIR Relevance

The thesis provides a technical foundation for SBIR-oriented work because it identifies a concrete architecture, specific systems problems, an existing implementation, measurable system characteristics, and a bounded research program. The strongest government and defense relevance comes from persistent cognition, sovereign and isolated operation, inspectable reasoning and action, governed autonomy, independent verification, and explicit deployment control. These properties are relevant to environments where connectivity may be constrained, institutional state must persist, and an AI system must provide an auditable record of what it intended, what it did, and what happened. For solicitation-specific work, the thesis should be converted into agency-specific objectives, technical tasks, milestones, metrics, risks, and deliverables. Replicated substrates should be presented as a research program with explicit synchronization, integrity, and security milestones rather than as a completed capability. The company maintains a strict distinction between government opportunity activity, technical demonstrations, research results, proposals, and awarded contracts or government performance.

## 16. Falsifiability, Limitations, and Claim Discipline

The thesis is intentionally bounded. Its purpose is to state a technical proposition that can be tested, not to substitute broad claims for evidence.

- Lyric is described as a persistent cognitive architecture and computational substrate. The current technical source does not claim that Lyric is artificial general intelligence.
- Current validation establishes specific capabilities and system properties; it does not establish unrestricted general intelligence or universal reliability.
- The SEG formal work proves structural properties under its stated model and identifies stronger independence, correlation, and adversarial threat-model questions as future work.
- The replicated-substrate synchronization architecture remains a forward research direction unless corresponding implementation and experiment records are added to the technical source of truth.
- Technical research progress is distinct from commercial revenue, customer adoption, paid pilots, government awards, or contract performance.
- Measurements are dated and should be superseded by newer measurements in the technical source of truth.
This discipline is part of the research method. The system is advanced by implementing mechanisms, defining invariants, measuring behavior, exposing failure modes, and conducting experiments that can produce either positive or negative results.

## 17. Long-Term Technical Direction

The long-term objective is a general-purpose AI substrate that can persist as a cognitive system across time and deployment conditions while continuing to learn, reason, verify, and operate within explicit authority boundaries. The technical progression is from controlled research environments to government and defense R&D, then to validated mission deployments and regulated enterprise environments. The application may vary, but the underlying proposition remains consistent: the customer receives an AI system whose cognitive state, learning, reasoning, governance, and deployment boundary are properties of the system itself. As capability increases, the research challenge becomes increasingly systemic. Improvements in one faculty affect the others: better learning changes planning; better perception changes beliefs; better beliefs change intent; better execution produces new evidence; governance determines which capabilities can act; verification determines which outcomes receive credit; persistence determines what survives to influence the next decision. The research program therefore aims not merely to increase benchmark performance, but to increase the coherence, reliability, inspectability, and deployability of the complete cognitive system.

## 18. Conclusion

Dominion Labs' technical thesis is not that every mechanism inside Lyric is individually novel. Many of the computational methods are established. The thesis is that these methods can be integrated into a persistent cognitive substrate in which their outputs, authorities, and verified consequences continuously interact. Lyric is the running implementation of that proposition. It combines persistent typed memory, substrate-native learning, epistemic state, multiple reasoning modes, symbolic planning, persistent intent, environmental verification, model-free structural perception with learned naming, action-level governance, tool interaction, coordination, and controlled deployment boundaries. The resulting research question is empirical: whether this integrated architecture can continue to acquire capability while maintaining epistemic integrity, governed action, inspectable behavior, and reliable continuity across time and deployment conditions. The current experimental record provides evidence for specific portions of that proposition; the next phase is to test harder interactions, longer horizons, more demanding environments, and replicated cognitive state. Bottom line The contribution is best framed as integration: established computational methods + Dominion Labs-specific mechanisms + a persistent authority and verification model + empirical testing of the resulting system as one cognitive substrate.

## 19. Source Base and Document Control

This thesis was rewritten against the Company's September 2026 technical source set. The underlying technical claims are controlled by the following materials:

- Lyric, Product & System Overview / Technical Overview, September 2026. Primary technical source of truth for implemented architecture, experiments, terminology, and dated measurements.
- Lyric, Product Overview, September 2026. Investor-facing product, deployment, and commercial framing.
- Systemic Epistemic Governance, Stefan Ragland, Dominion Labs, September 6, 2026. Formal treatment of provenance-gated persistence and action authority.
- Perceive, Induce, Name, Stefan Ragland, Dominion Labs Research & Development, September 8, 2026. Proof of concept for structural perception, learned naming, and abstention within the cognitive substrate.
- Traction / Revenue / Usage Summary, September 2026. Company-level research and development trajectory and distinction between technical progress and commercial traction.
### 19.1. Source-of-truth rule

The running implementation, recorded experiment results, and system-generated verification take precedence over descriptive documents. If a future implementation or experiment conflicts with this thesis, the thesis should be corrected rather than the system record being conformed to the document. END OF DOCUMENT · DOMINION LABS, INC. · SEPTEMBER 2026
