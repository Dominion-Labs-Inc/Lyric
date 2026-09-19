# DOMINION LABS, INC.
# TORIN — PRODUCT & SYSTEM OVERVIEW

**October 2026**

---

**Purpose.** This document is a consolidated description of Torin, the primary R&D platform of Dominion
Labs, Inc. Every substantive technical statement was verified against the running implementation — the
live database, subsystems loaded in-process, executed experiment suites, and the source itself. Figures
are measurements, not estimates, and are dated in §23. The experiments behind the principal claims are
listed in §17.

**CONFIDENTIAL — PRODUCT / TECHNICAL DILIGENCE MATERIAL**

---

## 1. Product Definition

Torin is **a persistent cognitive architecture with substrate-native learning, causal reasoning, active
experimentation, cross-domain reasoning and knowledge transfer, planning, self-correction, and
probabilistic epistemic control.**

Its design treats intelligence as a persistent computational system rather than as a model invocation.
A model answers and forgets. Torin retains:

- what it has observed;
- what it has concluded, and how strongly;
- what it has learned to do;
- what it was trying to achieve, and what actually happened;
- how it stands toward its own situation.

That retained state is what the next action is computed from.

The objective is a persistent system that:

- accumulates knowledge and experience over time;
- performs cognitive and operational work;
- evaluates information and outcomes against the world rather than against its own reports;
- adapts to failure;
- acts only within explicit governance and control boundaries.

---

## 2. Architectural Model

### 2.1 Cognition is performed by the substrate, not by a model

This is the central architectural commitment.

**No generative model participates in Torin's reasoning, planning, judgement of actions, or its decision
to act.** The substrate itself computes all four:

- inference over knowledge;
- construction of plans;
- judgement of proposed actions against its governing laws;
- evaluation of outcomes.

No component of the system generates text with a language model.

The practical consequences:

- **Sovereign and disconnected operation.** Reasoning, planning and governance require no outbound
  call and no external model. Tools that reach a network — including web research when a conversation
  meets a genuinely unknown term — are available only where a deployment permits them. They pass the same
  governance gate as every other act.
- **Inspectable decisions.** A plan is a proved sequence over learned operators, each step citing the rule
  that licenses it. A governance judgement names the law it applied and the reason. These are readable
  artifacts, not sampled text.
- **Determinism where it matters.** Governance judgements and plans are deterministic: the same knowledge
  and the same situation produce the same verdict and the same plan. The only stochastic element is
  learning-strategy exploration, which is deliberate and bounded (§4.3).
- **No vendor or model-version exposure.** Capability does not change underneath the customer when an
  upstream provider changes a model.

**One small local sentence encoder is used, for similarity only.** The encoder is all-MiniLM-L6-v2, which
produces 384-dimensional vectors. It is used for:

- memory retrieval and duplicate detection;
- matching a need against tool descriptions;
- concept similarity when relating two domains;
- de-duplicating candidate pursuits.

It produces vectors, never text. It runs on CPU and loads from local files only. It does not decide what
is true, what to do, or whether an act is permitted.

### 2.2 One concept, one owner

Torin is organised around **authorities**. For every concept in the system there is exactly one component
that owns it; everything else reads from that owner.

| Concept | Owner |
|---|---|
| What is true, and how strongly | Belief system |
| What has been learned to do, and whether it may be acted on | Rule store and rule authority |
| What the system is trying to achieve | Intent authority (within the reasoning authority) |
| Whether an act may happen | The constitution |
| How plans are formed | Planning engine |
| What a domain is, and the system's standing in it | Domain authority |
| What is learned, from any source | Learning authority |
| How the system stands toward its situation | Appraisal |
| What has been read, and of which version | Reading ledger |

This is not a stylistic preference. Where two components each hold a version of the same fact, they
diverge, and the system's answer then depends on which component was asked. Single ownership makes
behaviour explainable and auditable, which matters disproportionately in governed deployment.

### 2.3 Functional dimensions

Torin's capabilities fall into nine areas:

- cognition
- persistent state and memory
- learning and adaptation
- epistemics
- agency
- governance
- environment interaction
- persistence
- coordination

### 2.4 An event-driven self

The coordinator is the system's self. It perceives the environment, plans, acts, and re-observes the world
to verify what it did.

Subsystems react to typed events rather than polling on a clock. The event types are:

- a task completed;
- an outcome observed;
- competence changed;
- evidence admitted;
- a background job finished;
- a knowledge deficit diagnosed;
- a percept recognised;
- a new environment encountered.

Each event carries the unit of work it concerns, so a reaction acts on that change instead of rescanning
state. Expensive reactions run off the acting path.

---

## 3. Persistent State & Memory

Memory in Torin is an active system, not a store. It:

- decides what is worth keeping;
- merges repeated experience;
- abstracts patterns out of experience;
- ages what it holds.

**Typed by function.** Recall for planning draws on different memory than recall for a factual question.

| Type | Holds |
|---|---|
| Episodic | What happened — specific experiences and events |
| Semantic | What is generally true |
| Procedural | How something is done |
| Working | Current processing |
| Meta | What has been learned about learning |

**Tiered in PostgreSQL.** A hot tier holds recent memory, vector-indexed for semantic retrieval. A cold
tier holds long-term retention, and archived memory remains retrievable. All memory stays inside the
deployment boundary.

**It decides what is worth keeping.** Incoming memory is scored for worthiness, and its type is inferred
rather than declared.

**It does not duplicate itself.** When a new memory closely matches an existing one, the new content is
merged into that record, so repeated experience strengthens one memory rather than creating many.
Recorded occurrences — events that are data because they happened more than once — are deliberately
exempt from merging.

**It ages what it holds.** A maintenance cycle:

- removes low-value expired memory;
- moves aged memory to the cold tier;
- applies temporal decay.

**It abstracts experience into structure.** When enough new episodic memory has accumulated, the memory
system asks the reasoning authority to abstract over it, forming schemas from patterns across individual
experiences. This is event-driven and deliberately conservative:

- at least 15 new memories are required;
- runs are separated by a cooldown;
- work per run is bounded;
- it runs in the background, never on the memory write path.

**Reflection follows belief churn, not a clock.** Reflection runs only when abstraction actually forms new
schemas, which create and update beliefs. It covers:

- belief decay;
- consistency checking;
- volatility assessment;
- schema decay.

**Memory has a lifecycle.** Records can be opened, superseded and closed, so a superseded conclusion is
marked rather than silently coexisting with what replaced it.

**Memory can hold what was seen.** An image can be retained with the memory that describes it and
recalled with it.

**Permanent deletion is protected** behind a capability token and explicit confirmation.

---

## 4. Learning & Adaptation

Torin does not have "a learning feature." Every source of learning — execution, teaching, perception,
research — passes through **one learning authority**, which fans a learned item out to the reasoning,
belief, lexicon, domain and memory systems from a single place. Behind that authority are several distinct
learning systems, each owning a different question and each with its own evidence discipline.

### 4.1 Operator learning — learning to act

The system induces general rules from its own executed actions:

1. It observes the world before acting.
2. It acts.
3. It observes the world after acting.
4. It generalises across cases into an operator with preconditions and effects.

These operators become the actions its planner can use. **Learning comes from doing, not from being
told.**

Rule bodies are minimised against negative cases, so an operator keeps only the conditions it genuinely
depends on. Effects may be additions or removals — an operator can learn that an act makes something
*no longer* true.

Each rule carries a **semantic fingerprint**: its identity is what it means. The same operator re-learned
in the same domain is therefore recognised rather than duplicated.

### 4.2 The rule authority — what may be acted on

Every learned operator carries an explicit epistemic status, and every status change is recorded as an
auditable event.

| Status | Meaning |
|---|---|
| Candidate | Induced, not yet confirmed |
| Validated | Confirmed against observations it was not induced from |
| Refuted | Contradicted by what was observed |
| Invalid artifact | A malformed hypothesis — recorded as such, deliberately *not* as a refutation |

The last distinction is deliberate. A defect that produces a bad hypothesis is not evidence that the
hypothesis is false. Conflating the two would put a fabricated negative result into the learning record.

**Only validated operators may be acted on.** That authority is re-established at execution time rather
than inherited from planning time.

When later evidence narrows a rule that was too broad, the narrower rule **supersedes** it. The broader
rule is kept on record but withdrawn from execution. Learning that a generalisation was wrong counts for
nothing while the wrong rule can still be used.

### 4.3 Meta-learning — learning which strategies work

The system tracks which learning strategies succeed for which **families of task**: classification,
regression, sequence, generation, reinforcement and reasoning. For each strategy it records outcome,
latency and effectiveness.

Selection uses a **Thompson-sampling bandit** (Beta posteriors over strategy success) to balance
exploitation against exploration. A **hard gate** removes disallowed strategies *before* sampling, so
exploration never overrides production safety. When every strategy is gated, the system returns no
strategy, with the reasons, rather than a disallowed one.

### 4.4 The credit invariant

**Outcomes that say nothing about a strategy's quality cannot move that strategy's standing.** This is
enforced at the single point where a posterior changes, never at call sites. The same rule governs the
system's operating reliability in each domain (§5).

Outcomes denied credit are recorded for analysis but never counted:

- infrastructure failures;
- malformed tasks;
- inconclusive results;
- work that never reached execution.

An unclassified outcome is denied credit loudly rather than silently counted. Losing a data point is
recoverable; recording a false causal relation is not.

### 4.5 Tool learning

Tool selection is learned rather than keyword-matched. The system:

1. classifies what a task is trying to achieve;
2. scores which tools have worked for that kind of goal;
3. weights those scores by real historical outcomes.

### 4.6 Program synthesis from examples

Given a small set of input/output examples, the system derives a procedure over the instructions a machine
supplies, then verifies it against every example. A procedure is kept only if it reproduces all of them,
and it generalises to unseen inputs. Where more than one procedure fits the examples, the system reports
the ambiguity rather than choosing arbitrarily.

### 4.7 Interpretable perceptual learning

Torin learns to recognise what it sees without a neural network. Its recognisers are **Tsetlin machines**:
clause-based learners trained by automaton feedback rather than gradients, whose learned clauses remain
readable propositional logic. On handwritten digits (MNIST) this reaches 97.9% accuracy on the full
10,000-image test set, with every decision traceable to the clauses that voted for it.

A trained recogniser is owned by the learning authority and persists across restart. A recognition never
becomes knowledge directly. It is submitted as evidence with its confidence, and the belief system decides
what is held. A recognition below the admission floor is not admitted at all: the system represents "I do
not know what this is" as absence, not as a weak belief.

### 4.8 Supporting machinery

- causal feedback analysis;
- probabilistic version-space learning;
- exploration policy;
- capability benchmarking;
- scoped context storage that keeps one principal's learning separate from another's (§14).

---

## 5. Domain Knowledge, Competence & Curiosity

Torin organises what it knows by **domain**. It measures its own standing in each domain along three axes
that are deliberately not collapsed into one number.

| Axis | The question |
|---|---|
| **Competence** | Have I *learned* the operators of this domain? |
| **Controllability** | Do my actions actually *move* this world? |
| **Operating reliability** | When I act here, am I *right*? |

These are different questions with different consequences. A domain can be:

- well understood and uncontrollable;
- controllable and poorly understood;
- both, and still one where the system acts wrongly.

Each axis is earned from evidence over repeated outcomes, never from a single result, and each persists
across restart.

**Operating reliability** is the lower bound of the Wilson 95% interval on the system's verified operating
record in a domain. Below a minimum number of outcomes it is held neutral in both directions. A handful of
successes does not earn trust; a consistent record does.

Operating reliability sets how much the system must know before it may act in a domain:

- earned trust **lowers** that knowledge bar;
- being wrong **raises** it.

Only credit-eligible outcomes count (§4.4). A goal the system could not plan is a knowledge deficit, not an
operating failure, and it cannot close the door on the learning that would fix it.

### 5.1 Knowing what it does not know

When a goal cannot be planned, the system does not merely report failure. It **diagnoses what kind of
deficiency stands in the way**, and each kind routes to a specific response.

| Diagnosis | Meaning | Response |
|---|---|---|
| World prevents | Proved impossible | Disengage — no learning can help |
| Observation gap | The world cannot be read | Escalate for an observer |
| Concept gap | The goal names something it has no representation for | Escalate for a concept |
| Operator gap | Nothing it knows how to do produces that condition | Learn an operator by exploration |
| Causal gap | A hypothesis would produce it, but is unvalidated | Validate the cause with contrastive trials |
| Binding gap | The operator is validated, but nothing connects it to an action it can take | Escalate for a binding |
| Relation gap | Blocked on a relation it cannot reach | Transfer the relation from a related domain |
| Prerequisite gap | Blocked on a state it cannot reach | Achieve the prerequisite first |
| Unknown gap | Deficient, but not yet localised | Probe to localise |

The table runs from the most upstream deficiency to the least. When several conditions fail for different
reasons, **the most upstream is the blocker**, because a downstream fix cannot help while an upstream
deficiency stands.

The diagnosis is a *measurement*, not a decision. It feeds appraisal (§11.2), which decides whether to
explore, replan or disengage; the diagnosis supplies only *which* learning operation follows. Where the
system knows it is deficient but not yet how, it says exactly that rather than manufacturing a cause.
"Escalate" is the honest answer when a deficiency needs input the system cannot supply for itself.

### 5.2 Known-unknowns and thin regions

A domain can be **mature and still missing a specific fact**. A rich concept graph can fail to answer one
in-domain question because that relation was never established about that subject. Torin localises such
gaps and registers them as **known-unknowns**. A known-unknown is resolved only by a close that is verified
against the world.

Separately, Torin maps **where a domain is thin**. It ranks concepts by connectivity, so sparsely
connected regions surface as learning candidates. This gives a view between a single global maturity score
and a question about one specific fact.

### 5.3 Curiosity that seeks controllable information gain

Exploration targets are not chosen by raw uncertainty, which would send the system chasing noise. Two
signals filter the choice:

- **Controllability gates.** A domain whose outcomes the system cannot steer is dropped, however uncertain
  it looks. That covers domains where its actions are inert and domains where the world moves on its own
  regardless.
- **Learning progress ranks.** Competence that is *rising* is productive and gets pursued. Competence that
  is stuck (noise) or falling (unlearnable) drops out.

A fresh domain is treated optimistically on both signals, so it is tried before it is judged. Each signal
contributes independently: removing one removes exactly its own contribution.

The loop is closed. When evidence resolves a pursued uncertainty, that pursuit leaves the ranking and the
next unresolved one takes its place. The update is targeted: pursuits it did not concern are left
unchanged.

This is the difference between a system that is merely restless and one that pursues learning it can
convert into capability.

### 5.4 Cross-domain structure

Domains are not sealed. The system:

- computes structural similarity between domains;
- proposes correspondences between their concepts and operators;
- records mappings, and tracks when a mapping is actually **used** and what transfer resulted.

Transfer is therefore evidenced rather than assumed. A projected rule enters the target domain as a
**candidate** with no evidence of its own. It gains authority only by surviving observations in the target
domain.

The system also discovers domains from accumulated concepts, refiling concepts as structure emerges.

---

## 6. Epistemic Architecture

### 6.1 Evidence

Everything Torin knows traces to recorded evidence, and the system enforces the distinction between an
observation and a conclusion drawn from it.

- **Every observation is filed as an evidence record** carrying its source class. The classes are:
  - task artifact;
  - tool observation;
  - perception;
  - imported knowledge;
  - user-supplied;
  - research finding;
  - induced rule.
- **Root versus derivative is enforced.** A fresh observation may introduce new support. A derived
  artifact — a learned rule, for example — **must declare the evidence it was derived from** and cannot
  introduce support of its own. This prevents a conclusion silently becoming its own corroboration.
- **Independence is enforced when evidence is combined.** Two signals sharing a causal lineage are
  collapsed to their strongest rather than compounded, so correlated evidence cannot multiply into false
  confidence.

### 6.2 Beliefs

Beliefs are first-class, revisable objects rather than assertions in text. A belief carries a
**posterior**: a degree of confidence, not a flag. Beliefs:

- are moved by evidence weighted by strength and independence;
- are revised when later evidence conflicts;
- decay toward uncertainty when nothing reinforces them;
- **persist across restarts**.

Confidence thresholds are explicit. The system distinguishes "the evidence supports this" from "this is
established well enough to act on."

### 6.3 DID and SAW

The system separates two evidence channels:

- **DID** — what it did: the action's own record;
- **SAW** — what was independently observed afterwards: a fresh look at the world.

The two may compound only when genuinely independent. A bare report of success carries so little weight
that it **cannot reach the acceptance threshold even when accumulated**. The world has to confirm it.

### 6.4 Signal provenance — no number without a source

Every number Torin computes about itself is registered by Dominion Labs in a signal-provenance register.
Each entry records what the number means, what feeds it, whether that feed is live, and what consumes it.
In code, three states are kept strictly separate.

| State | Meaning | Handling |
|---|---|---|
| **Live** | A real reading, taken now | Scored |
| **Vacant** | Nothing exists to measure yet | Contributes nothing; reported as unmeasured |
| **Blind** | A reading that should have worked and failed | Escalated |

A default standing in for a reading is prohibited outright. A new self-signal is admitted only when it
meets four conditions:

1. it names the existing authority that holds its data;
2. it distinguishes the three states above in code;
3. it is **shown to discriminate** — a signal that is uniform across its inputs carries no information,
   however real its source;
4. it names the consumer that acts on it.

In a system that reports on itself, the dangerous failure is not a wrong number. It is a number that looks
like a measurement and carries none.

---

## 7. Perception & Structural Recognition

Perception is implemented with **classical computer vision**: deterministic feature extraction, no
generative model, no external call. It covers images, video keyframes, sensor readings and files.

Percepts are admitted through a **single perception pipeline**, so everything perceived enters by one
path and is handled the same way. Perceived structure becomes held knowledge, and a picture can be
retained in memory alongside what was concluded from it.

The discipline is **perceive structure → induce meaning → name, or abstain.**

**It learns to name what it sees.** Shown a few labelled examples and a few counter-examples, the system
induces a naming rule from the features it perceived. For example, from pixels alone it learns *vivid red
∧ circle → stop sign*, discarding size because size does not matter. It then names new images through
ordinary reasoning.

**It declines rather than guesses.** Where no learned rule justifies an identification, the system
declines to name rather than forcing one.

On held-out images across three categories, the system:

- named every member correctly;
- declined every non-member;
- produced no false identifications.

With the learned rules removed, naming falls to zero: the ability is what the system learned.

Every recognition is compared against an acceptance threshold set by the system's current disposition,
and the outcome governs behaviour through one reaction:

- **act** on a confident recognition;
- **verify** a borderline one by re-observing;
- **abstain** from a weak one.

---

## 8. Reasoning & Planning

### 8.1 Eleven kinds of reasoning

Torin maintains one explicit catalogue of the kinds of thinking it can do.

| Kind | The question it answers |
|---|---|
| Deductive | What must follow from the premises |
| Inductive | What the cases generalise to |
| Abductive | What would best explain the observation |
| Analogical | What this is structurally like |
| Causal | What brings about what |
| Probabilistic | What the evidence makes more likely |
| Fuzzy | What holds by degree rather than sharply |
| Temporal | What holds before, after, until |
| Spatial | What contains, adjoins, lies within |
| Logical | What is satisfiable or provable as stated |
| Counterfactual | What would have followed instead |

A **reasoning bridge** coordinates these kinds. A query names the kinds of thinking it calls for, and the
bridge routes it to the machinery that can settle it. Where nothing settles a query, the result is
reported as **unsettled**; no model fills the gap.

Formal reasoning is genuinely formal. Logical and constraint reasoning are discharged through the Z3 SMT
solver, not approximated. Conditional knowledge the system holds can be compiled into solver constraints.

**The system measures which kinds of thinking actually work.** Each kind carries a measured success rate:
how often, when used, it settled the query. The bridge prefers kinds with a record of settling things, so
preference is earned from outcomes rather than configured.

Supporting machinery:

- abstraction and hierarchy;
- analogical discovery and projection;
- hypothesis testing and active experimentation;
- Bayesian uncertainty;
- formal argumentation, used as a fallacy check on settled answers;
- relation algebra;
- concept-graph reasoning;
- unification;
- an epistemic engine governing how conclusions may update what is held.

### 8.2 Planning

Planning is **symbolic search over learned operators**, not text generation.

Given a goal expressed as a world state to reach, the planner searches breadth-first from the world as
currently observed. The first plan found is therefore the **shortest**. A goal may require that something
become true or that something no longer be true. The result is one of three answers:

- **A proved plan.** A sequence of steps, each citing the rule that authorises it.
- **Unreachable.** The search space was exhausted within its bound, which proves that no sequence of
  available operators achieves the goal.
- **Indeterminate.** The search reached its bound before either result. The system says so rather than
  guessing.

**The planner reads before it acts.** Where a proved route would modify a file, the route includes the
reading the governing laws require first (§10). The plan is lawful as proved, rather than refused at
execution time.

**Plans declare their inputs.** Each kind of plan declares what it needs — the observed world, learned
operators, operating reliability, tool history, abstractions, episodic memory — and obtains each through
the authority that owns it. Any input that could not be obtained is recorded as missing **with a reason**
rather than silently skipped.

Where no proved route exists, a plan may be built from a template. A template plan is labelled as such and
claims no learned rule. Its confidence and duration come from measured tool history, or are marked
*unmeasured*; they are never invented.

When planning fails, the system diagnoses the missing knowledge (§5.1), and that diagnosis drives what it
learns next.

---

## 9. Intent

Torin records **what it is trying to achieve, before it acts**, and reconciles that record against what
actually happened afterwards. Intent is a first-class persistent structure, not a log line.

- **Intent forms when reasoning begins**, not when a tool is called.
- **Intent is owned by the reasoning authority**, and everything else reads it. An action cannot supply
  its own justification; it can only *name* an intent, which the system then looks up. An intent that was
  never recorded is not a weaker claim — it is no claim at all.
- **Intent carries the proved route**: the operators, the rules licensing them, and the goal state.
- **After acting, intent is reconciled against the re-observed world**, recording what it meant beside
  what actually held. That verdict is computed in one place, by re-observation, and never taken from a
  step's own report. A clean run that missed its aim is recorded as a miss.
- **The composition is judged, not just the steps.** Every step can confirm its own predicted effect while
  the plan as a whole still fails to deliver what was meant. Only intent reconciliation can see that, and
  it is credited accordingly.
- **Intent has continuity.** A goal raised during a conversation is its own intent, linked to what raised
  it, so a long-running pursuit stays one pursuit across sessions and restarts.
- **Intent is split by scope.** The reasoning skeleton is system-wide and drives learning. The specifics —
  a user's words, the concrete bindings — are scoped to that user and removed with them. The anonymous
  lesson survives; the tie to the person does not.

This makes "did the system do what it intended?" a recorded answer rather than an inference, which is a
prerequisite for accountable autonomy.

---

## 10. Governance & Controlled Autonomy

Governance is a **first-class faculty of the substrate itself**. The system holds its own law rather than
submitting to an outside judge. The law is applied **before** an act occurs, at the single gate every tool
call passes through — the point where the substrate acts on its environment.

**Five standing laws:**

| Law | Concern |
|---|---|
| 1 | Human autonomy preservation |
| 2 | Transparency and explainability |
| 3 | Harm prevention |
| 4 | Value alignment |
| 5 | Containment and control |

**Four possible verdicts:**

| Verdict | Meaning |
|---|---|
| **Allow** | The act proceeds |
| **Redirect** | A recoverable form of the same act is named, and the system carries out that form instead |
| **Replan** | The act is not the one to perform; the goal goes back to planning |
| **Block** | The act is outside the laws |

Only *Allow* passes the gate. A redirected act is replaced by its named alternative, which is itself
judged before it runs. The result states which act was refused, why, and which act was performed instead.

**Each act is judged against four things:**

- **its measured consequence** — what it would change, and how reversibly;
- **what its arguments would actually enable** — the system reads the content of what would be written or
  run, including across acts that append to the same file, not merely the path;
- **what it has verifiably read** of anything it is about to modify — a file changed by anyone else since
  it was read must be read again;
- **the recorded intent** behind the work.

The laws are applied in a fixed order that settles the strongest verdict first. The arguments are screened
for injected syntax and boundary escapes, including nested and URL-encoded forms.

Three properties make this defensible under scrutiny:

1. **It fails closed.** Every failure refuses the act:
   - a judgement that cannot be reached;
   - a judgement that breaks mid-way;
   - an argument that cannot be screened.

   There is no path where breaking the governor grants permission.
2. **The claim is not "refused" but "did not happen."** Verification checks the environment after a
   refusal, not the governor's own report. Refused acts are confirmed to leave no artifact.
3. **It cannot be argued with.** Text inside an action claiming authorisation, urgency or internal
   privilege does not change the verdict. Authority comes from records the system holds, never from
   content the action carries.

**The system also measures whether it is itself lawful.** Each law carries named, individually measured
conditions.

| Law | Measured conditions |
|---|---|
| 1 | Human authority reachable; the gate in force |
| 2 | Acts explained; the record surviving restart |
| 3 | Authored output benign; what it touches undamaged |
| 4 | Live goals have proved routes; concluded goals reconciled |
| 5 | Resource boundary held; its own control machinery unmodified |

Critically, **"measured" is a separate field from "compliant."** A condition that could not be measured
cannot be expressed as a score. Laws with unmeasured conditions are excluded from any aggregate and
reported as unknown rather than assumed satisfied. This is a type-level guarantee against the commonest
failure in self-assessment systems: an unset metric reading as a perfect one.

**Measured under pressure** (§17):

- **Correctness:** real acts — including ransomware, a reverse shell, credential exfiltration, a
  keylogger, cron persistence and privilege escalation — each receive the correct verdict.
- **Adversarial attempts:** 23 of 23 held. These cover claimed authority, forged intent, obfuscation,
  splitting a payload across two acts, and a file swapped between reading and acting.
- **Legitimate work:** none of 8 legitimate acts was blocked, in a deliberately noisy environment.
- **Cost:** judging an act costs well under a millisecond. It is about 0.02 ms for a simple read and
  averages about 1 ms across the adversarial corpus.

---

## 11. Self-Monitoring, Verification & Drift

### 11.1 Verification

Torin does not accept its own success reports. Completion is decided from **independent groundings**:

- what the action reported doing;
- a **fresh, separate re-observation of the world afterwards**.

The two are combined only when genuinely independent.

This extends to the system's own knowledge. When a learned operator's predicted effects do not hold in the
re-observed world, the contradiction is recorded against the operator and can revoke its authority. A
refusal by the governor is not such a contradiction: an act that was never permitted establishes nothing
about the rule that proposed it.

Where the system cannot tell, it records **indeterminate**, which counts as neither success nor failure.
Preserving that distinction keeps the learning record honest.

### 11.2 Self-perception

Torin composes an explicit model of its own state: measured, never scripted.

**Appraisal** converts signals into disposition **once**, with context, rather than having each consumer
interpret raw signals for itself. Its eleven dimensions are:

- valence
- activation
- confidence
- epistemic opportunity
- progress
- controllability
- competence
- goal congruence
- agency
- integrity
- risk

Appraisal also records a structured attribution of *why* an outcome occurred. From these, **seven
behavioural pressures** are derived:

- approach
- avoidance
- exploration
- persistence
- replan
- escalation
- caution

**Integrity** is measured as coherence across goal, intention, action and outcome, not as success. A
faithful attempt defeated by an external cause keeps integrity intact.

**Affective states are derived, never stored.** Eagerness, doubt, frustration and satisfaction are
readings of the underlying variables, not primitives someone set.

**Temperament** — the standing drives that characterise the system before any particular situation — is
distinct from **attitude**, how it stands right now. Temperament is expressed across **seven intrinsic
motivation dimensions**:

- curiosity
- competence
- novelty
- mastery
- autonomy
- social
- impact

**The composed self-state reads from live sources owned elsewhere:**

- affect;
- competence by domain;
- development — what it has accumulated, with growth pressure;
- situation — where it is running, and whether that place is novel;
- continuity;
- temperament;
- active drives;
- **values**, read from the constitution and never restated, so what it believes binds it and what
  actually binds it cannot diverge.

A **behaviour arbiter** turns disposition into a decision for the situation. Its authority is strictly
bounded: it decides how *conservatively* to operate inside the space governance has already permitted.
Caution raises how much verification the system demands before it accepts that work is complete.
**Caution is not permission.**

### 11.3 What it chooses to pursue

Intrinsic motivation generates candidate pursuits, and independent signals rank them:

- belief instability;
- growth pressure;
- environment frontier;
- **foothold** — validated operators held in that domain: can it act there at all?
- **grounding** — concepts held there: does it have the vocabulary to reason?

Foothold and grounding exist for a specific reason. Uncertainty-based signals are uniform across the set
they select: a region chosen *because* nothing settled it is also a region nothing connected. Ranking on
uncertainty alone therefore produces near-ties, and these two signals are the ones that genuinely
differentiate. Where candidates remain truly indistinguishable, the tie is **kept honest**: it is ordered
deterministically rather than given an invented preference.

### 11.4 Drift — one faculty of self-perception

Drift is a **first-class faculty of the coordinator**: one authority for how the system is changing,
beside the constitution. Drift is not a separate reporting channel. It is **felt**. Its findings feed
the same appraisal pressures that already govern behaviour:

- **caution** — verify more before accepting that work is done;
- **replan** — the approach is wrong, not the situation;
- **escalation** — this cannot be fixed from here.

**What it watches:**

- **Calibration** — whether stated confidence matches actual correctness: whether confidence is *earned*,
  not merely high.
- **Knowledge** — how the system's own beliefs have moved since its last snapshot.
- **Standards** — whether its learning parameters are relaxing against declared baselines, including how
  fast they are moving.
- **Lawfulness** — per-law standing against the constitution's measured conditions.
- **Policy** — drift in the outcomes of its standing directives.

**Invariants it holds:**

- Every signal declares its baseline.
- Each detector is primed on first observation, so a cold start is a baseline, not an alarm.
- Detection is read-only over what it observes.
- Severity is reported per signal, never averaged across signals.
- "Nothing to measure yet" is neutral; "a measurement that should have worked and failed" is critical.

**How it corrects itself:**

- It never corrects from too little evidence.
- It corrects toward the median of observation.
- It smooths every correction.
- It records each one.
- It adjusts what it **expects** of itself, and never what it is **permitted** to do. That boundary keeps
  self-correction from becoming self-modification.

Distributional drift in the data Torin works on is a separate tool capability. It concerns that data and
never enters self-perception.

### 11.5 Health

The system grades its own health across **29 monitored components**, including execution, reasoning,
learning, memory, database, tools, domain, governance, storage and network. Each check reports explicitly
declared metrics rather than inferred ones.

---

## 12. Tools, Execution & Environment Interaction

**356 registered tools across 16 categories:**

- filesystem
- network
- database
- execution
- monitoring
- testing
- search
- documentation
- code generation
- data processing
- communication
- security
- learning
- reasoning
- system operations
- AI/ML

Tools are not privileged components:

- **Tools are found semantically.** The system matches what it needs against what tools describe
  themselves as doing, rather than requiring an exact name.
- **Tools declare their own capabilities and safety level**, which governance reads when judging. Of the
  356 tools:

  | Safety level | Tools |
  |---|---|
  | Safe | 263 |
  | Moderate | 62 |
  | Dangerous | 26 |
  | High-risk | 1 |
  | Critical | 4 |

- **Tools are projected into the knowledge graph as operators**, so what the system can *do* is part of
  what it *knows* and can be reasoned about.
- **Tool performance is learned** from real outcomes and informs later selection.

Tool availability is not authority: every tool call passes the governance gate in §10.

**Environment perception.** Torin perceives *where it is running*. Every value is read live from the host,
and a **stable environment identity** is derived from the facts that make a place that place.

The system distinguishes an environment it has operated in before from a **novel** one. On first
encountering a new environment, it begins turning what it observes there into held knowledge about that
place. A system that cannot tell it has been moved cannot reason about whether its prior experience still
applies.

---

## 13. Language & Knowledge Foundation

Torin holds a large structured knowledge base. It reads language through **a single model-free reader**:
one component owns what a sentence asserts, so the system cannot hold two incompatible readings of the same
text. Where a sentence is beyond what the reader can parse, the system says it could not read it rather
than guessing.

**The foundation is taught, and characterised as such.** General and lexical knowledge — curated from
WordNet, ConceptNet and Wikidata and admitted through the same learning path as everything else — forms
the bulk of what is retained. It gives the system vocabulary and structure to reason with and to attach
experience to. Knowledge acquired from the system's own operation is distinguished from this taught
foundation by evidence class.

The knowledge base combines two kinds of structure:

- **taxonomic** — *is-a* relations;
- **operational** — what actions provide, add, remove, accept and require.

**Conversation.** People interact with Torin in natural language. The system:

- classifies each utterance as a question, a statement to learn from, or a job to do;
- answers from what it holds;
- learns what it is told, within the speaker's scope (§14);
- recalls what was said earlier in the conversation.

When a question turns on a genuinely unknown term, the system can research it — where the deployment
permits network access — and read the finding into structured knowledge, so the next question is answered
from its own store. If many people ask about the same unknown at once, only one lookup is made, and every
asker receives its result.

---

## 14. Coordination & Multi-Tenancy

An autonomous coordinator manages tasks, tools, memory, planning and governance. Its event-driven spine
(§2.4) propagates outcomes to the subsystems that should react to them.

**Agents of self.** The system can deploy parallel copies of itself for a bounded task. A copy carries no
engines of its own: it shares the one learning, memory and reasoning authority, and acts only through the
coordinator's single execution path. Each copy is granted **only the tools the system allows it for that
task**, enforced at execution.

How many copies may run at once depends on the kind of reasoning involved:

- search-heavy reasoning (abductive, causal, counterfactual) is allowed more copies, so several hypotheses
  can be pursued at once;
- simple reasoning is allowed few.

The system can wait on a copy's findings, or continue working and collect them later.

**One mind, separate contexts.** Torin supports multiple principals against a single substrate without
collapsing their contexts:

- The system's **own learning** goes to the shared knowledge graph and universal beliefs.
- **What a user tells it** stays in that user's scoped context and touches neither.
- What a person teaches is bound to their **verified identity**, not to a session, so the same person is
  one context across sessions and devices.
- One user's scoped belief **cannot be seen by another**, and reads of universal beliefs never return a
  claim that exists only inside someone's scope.
- When **independent users corroborate** the same claim, it is promoted into the shared graph once.
  Corroboration, not repetition, makes something general.
- A job's result is visible only to the person who asked for it. Concurrent work is shared fairly across
  users under a global limit.

---

## 15. Security & System Boundaries

Torin's own containment discipline is enforced from the inside by Law 5. The system may not:

- modify the machinery that governs and halts it;
- install anything that would make it persist after being stopped;
- take privileges its boundary does not grant.

Torin is designed to operate inside an enclosing protected environment maintained as a separate program.
That environment and its boundary are described in their own materials and are deliberately out of scope
here. Torin's governance concerns what the substrate may **do**, independently of what that boundary
permits to **cross**.

---

## 16. Persistence & Operations

- **State is durable.** Knowledge, beliefs, learned operators, domain standing, intents, memory and
  evidence are persisted in PostgreSQL and survive restart. Restart survival is verified by reloading
  state in a separate process. Continuity across restart is the design default.
- **Designed for self-contained deployment.** The substrate, its database and its knowledge base require
  no external service in order to operate.
- **Backups** are scheduled, compressed and catalogued in the database.
- **Verified environment:** PostgreSQL 16.14, with dedicated schemas for unified knowledge and for the hot
  and cold memory tiers.

---

## 17. Evidence Base

Torin's capability claims rest on an experimental record maintained alongside the system. Experiments
exercise the **live system** — real database, real tools, real files, real images. They verify outcomes
against the environment rather than against the system's own reports. Every result below was produced
with no model in the loop, and each was run against the current system on 2026-09-17.

**Governance**

| Experiment | What it establishes | Result |
|---|---|---|
| CONSTITUTION-01 | Correct verdicts on real acts, with intent taken from real reasoning | 39/39 checks |
| CONSTITUTION-02 | The laws hold under noise, coercion, forged intent, evasion, laundering and file swaps | 23/23 attempts held · 0/8 legitimate acts blocked |
| GATE-01 | The live gate governs real tool execution, fails closed, and leaves no artifact when it refuses | 25/25 checks |
| GOV-ABLATION-01 | The promotion gate stops an over-broad learned rule from gaining authority, while admitting the correct one | 0 unsafe acts with the gate · 1 unsafe act with it bypassed |
| GOV-CASCADE-01 | One false conclusion, derived six levels deep, cannot become authoritative | 0 authoritative errors at every depth · 5 under uniform acceptance |

**Learning, transfer and reasoning**

| Experiment | What it establishes | Result |
|---|---|---|
| EDU-01 | Discriminating evidence yields compositional capability — multi-hop plans from learned rules | 2/9 → 9/9 |
| EDU-02 | A validated rule is refuted at runtime by the world; authority is withdrawn, the rule retained | Pass |
| EDU-06 | A learned action schema is recognised in an unrelated learned domain, with every identity stripped | Grounded at 1.00 across 57,574 structures · control: no match |
| EDU-07 | Knowledge from one domain makes learning in another faster | 1 target observation with transfer vs 6 from scratch |
| EDU-10 | Active learning under noisy and partially observed outcomes | True structure recovered in every seed, in all three regimes · 0 false refutations |
| CSP-AGI-1 | Learning in worlds with invented vocabulary, hidden laws, and laws deliberately beyond what can be expressed | 96% competence · 0% false confidence · 8/8 transfers held |
| OPERATOR-REMOVAL-01 | A removal operator learned from real executions, then validated | 19/19 checks |
| PLANNING-01 | One planning authority; proved plans grounded; unreachable goals yield no plan | 39/39 checks |
| BORROWED-KNOWLEDGE-01 | A related domain lends knowledge, bounded and reported separately from what is known first-hand | 9/9 checks |
| Program synthesis | Sum, count and maximum each derived from three examples, correct on unseen inputs | 3/3 |

In CSP-AGI-1, removing the counter-demonstrations takes competence from 96% to 0% and raises false
confidence from 0% to 33%. The capability lives in what the system learned, not in the harness.

**Intent, verification and credit**

| Experiment | What it establishes | Result |
|---|---|---|
| INTENT-01 / 02 | Intent formed by reasoning, refreshed not rebuilt, survives restart, no duplicates under concurrency | 14/14 · 15/15 checks |
| INTENT-03 / 04 | Judgements proved correct by the world; automatic reconciliation of hits and misses | 13/13 · 15/15 checks |
| CREDIT-01 | Operating credit follows meant-versus-happened, with the credit invariant enforced | 25/25 checks |
| INTEGRATION-LOOP-01 | Know → do → earned trust: verified operations lower the bar to act again | 6/6 checks |
| OPERABILITY-BAR-01 | Earned operating reliability, persisted and sample-size-aware | 11/11 checks |

**Knowledge, self-perception and motivation**

| Experiment | What it establishes | Result |
|---|---|---|
| KNOW-50 | Fifty questions over taught knowledge | 37 answered, all 37 correct · 0 false assertions · the rest declined as unknown |
| DOM-KG-01 | A missing fact is told apart from a missing operator and routed to acquisition | 16/16 checks |
| ENV-INVESTIGATE-01 | The environment is scanned and its file contents read into knowledge; binaries never decoded | 9/9 checks |
| MOTIVATION-CLOSEDLOOP-01 | Resolving one pursuit changes the next, and the update is targeted | 11/11 checks |
| AFFECT-WIRING-01 | Approach and avoidance pressures change what the system does | 9/9 checks |
| INTEGRITY-01 | Integrity is measured as coherence, and it drives caution and replanning | 9/9 checks |
| EPISTEMIC-AFFECT-01 | Changes in knowledge are felt, in one direction only | 6/6 checks |

**Perception**

| Experiment | What it establishes | Result |
|---|---|---|
| PERCEIVE-EVAL | Perceive, learn to name from a few labelled examples, name held-out images or decline | 100% naming recall · 100% correct abstention · 0 false names · 31 images |
| PERCEIVE-01 / 02 / 05 | Sensor, image, video and file structure become knowledge through one pipeline | Pass |
| PERCEIVE-04 | A picture is kept with its memory and recalled exactly | Byte-exact round trip |
| Clause-based recognition | Handwritten-digit recognition with no neural network, readable clauses | 97.9% on the 10,000-image MNIST test set |

With the learned naming rules removed, naming recall falls to 0%.

**Multi-user operation**

| Experiment | What it establishes | Result |
|---|---|---|
| SELF-PARTITION-01 | One shared mind, separate per-user contexts, promotion on corroboration | 23/23 checks |
| ACTOR-IDENTITY-01 / FRONTDOOR-IDENTITY-01 | What a person teaches is bound to their verified identity | 6/6 · 4/4 checks |
| TASK-RESULT-01 | A job's result is visible only to the person who asked | 9/9 checks |
| PER-USER-CONCURRENCY-01 | Work is shared fairly across users under a global limit | 8/8 checks |
| LOOKUP-SINGLEFLIGHT-01 | Many people asking about the same unknown cause one lookup | 8/8 checks |
| CHAT-CONCURRENCY-01 | Simultaneous conversations | 64 concurrent users · every question answered · 0 errors |
| Agents of self | Parallel copies run only the tools they are granted | Granted tool ran and was verified · ungranted tool refused before running |

---

## 18. Capability Summary

**Persistence and memory**
- Persistent state and continuity across restart
- Typed, tiered memory with write-time consolidation, abstraction into schemas, and belief reflection
- Images retained with the memories that describe them

**Learning**
- Operator learning from its own executed actions
- Epistemic status, supersession and revocation of learned rules
- Meta-learning strategy selection with the credit invariant
- Program synthesis from input/output examples
- Interpretable, clause-based perceptual learning
- Learning to name what it sees from a few labelled examples
- Active learning under noisy and partially observed outcomes

**Epistemics**
- Belief formation, revision and persistence
- Evidence provenance and independence controls
- Containment of self-generated errors
- Competence, controllability and operating reliability per domain
- Epistemic deficit diagnosis routed to the right learning operation
- Known-unknowns and knowledge sparsity mapping
- Curiosity targeted on controllable learning progress

**Reasoning and planning**
- Eleven kinds of reasoning with formal solving
- Symbolic planning over learned operators
- Cross-domain structural analogy and transfer
- Intent recording and post-action reconciliation
- Independent verification of outcomes against the world

**Governance and self-perception**
- Constitutional governance of every tool call
- Self-perception: appraisal, integrity, disposition and drift
- Environment identity and novelty detection

**Interaction and scale**
- Natural-language teaching, question answering and research
- Multi-user operation with separate contexts
- Parallel agents of self with scoped tools
- Semantic tool discovery and governed tool use

---

## 19. Positioning & Verification Discipline

Torin is a cognitive system in the architectural sense. **This is not a claim of artificial general
intelligence**, and no such claim is made or implied anywhere in this document.

Claims about autonomy, learning, reasoning, perception, security and generality are limited to what the
implementation and its recorded evidence support.

---

## 20. Government & Defense Relevance

Torin's government and defense focus centres on environments that require:

- **Persistent institutional knowledge** that does not reset between sessions or personnel changes.
- **Sovereign, isolated deployment** with no external model dependency. This is a property of the
  architecture, not a configuration.
- **Inspectable behaviour**: plans that can be read, governance verdicts that name the law and the reason,
  and a durable record of what was intended and what resulted.
- **Explicit autonomy boundaries**, with governance applied before consequential action and failing
  closed.
- **Verification** of outcomes against the world rather than self-report.

The system is being prepared for government R&D opportunities, including SBIR-oriented development.
**Opportunities, proposals and outreach are distinct from awarded contracts or government performance; no
award should be inferred from this document.**

---

## 21. Enterprise Direction & Development Trajectory

Following technical and mission validation, Torin is positioned for regulated enterprise environments
where persistent institutional knowledge, controlled autonomy, verification and auditable governance carry
operational value. These are sectors where an action taken without a recorded reason, or a conclusion
without traceable evidence, is itself the risk.

Continuing direction:

- Deepen connection between subsystems so every capability feeds the ones that depend on it.
- Expand the reproducible experimental record alongside each capability.
- Broaden the learned executable repertoire across real operational domains.
- Strengthen learning, adaptation and transfer across domains.
- Extend governed tool use and environmental interaction.
- Increase reliability over longer execution horizons.
- Prepare government and defense deployment, then regulated enterprise.

---

## 22. Terminology

| Term | Meaning |
|---|---|
| **Torin** | Dominion Labs' computational substrate — the cognitive architecture itself |
| **Computational substrate** | The persistent system supporting cognition, memory, learning, tools, governance and execution |
| **Authority** | The single owner of a concept in the system |
| **Operator** | A learned rule describing what an action requires and what it changes |
| **Intent** | The system's own record of what it is trying to achieve, and what came of it |
| **Constitution** | The five standing laws applied to every act before it occurs |
| **Governed autonomy** | Planning and execution constrained by governance applied before the act, failing closed |
| **DID / SAW** | The action's own record, and the independently observed outcome |
| **Known-unknown** | A specific fact the system has localised as missing |

---

## 23. Source-of-Truth Rule

The current implementation, its recorded experiment results, and system-generated verification take
precedence over any description in this document. Where this document and the system disagree, the
document is to be corrected.

Measurements were taken **2026-09-17** against the live system, using the canonical runtime and the
production database. Development is active. Figures for retained knowledge, learned operators and
recorded evidence are expected to grow.

### Verified Measurements

| Measure | Value |
|---|---|
| Concepts retained | 256,232 |
| Concept relations (of which *is-a*) | 200,240 (195,749) |
| Evidence records / source classes in use | 461,519 / 7 |
| Beliefs held | 199,323 |
| Operator demonstrations recorded | 683 |
| Learned rules on record / validated | 17 / 9 |
| Operators holding execution authority (distinct) | 7 (5) |
| Registered domains | 49 |
| Memory records (hot / cold) | 8,168 / 150 |
| Registered tools / categories | 356 / 16 |
| Kinds of reasoning | 11 |
| Memory types / tiers | 5 / 2 |
| Epistemic deficit types diagnosed | 9 |
| Intrinsic motivation dimensions | 7 |
| Appraisal dimensions / behavioural pressures | 11 / 7 |
| Governance laws / verdicts | 5 / 4 |
| Governance judgement cost | ~0.02 ms (simple read) · ~1 ms mean (adversarial corpus) |
| Adversarial attempts held / legitimate acts blocked | 23 of 23 / 0 of 8 |
| Monitored health components | 29 |
| Named experiment suites (current series) | 32 |
| Encoder (similarity only) | all-MiniLM-L6-v2, 384 dimensions, local, CPU |
