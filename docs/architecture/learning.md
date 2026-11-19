# Learning — `UnifiedLearningSystem`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

*File:* `core/learning/unified_learning_system.py` — 7,236 lines. `UnifiedLearningSystem` at 835: 6,052
lines, **104 public and 44 private methods**. The singletons `get_unified_learning_system()` (6802) and
`get_learning_authority()` (6810) return the same object, and every faculty reaches it as `coord.learning`.

---

## 1. One authority, one door

`UnifiedLearningSystem` is the substrate's **single learning authority**. It was once the *declared*
authority while a separate learning-authority module held the real model-free implementation; that file is
gone and its implementation folded in here, so one class now owns both the strategy and experience
machinery — meta-learning, memory routing, transfer — and the model-free authority core: the rule store,
the inducer, and the propose-versus-attest boundary.

It holds **no model handle**. A language model is the teacher's alone; nothing in this file generates.

Its governing principle is **propose, then attest**. A contributor may propose a hypothesis, a situation or
a formalization, but nothing it offers is evidence: everything admitted enters as `CANDIDATE` with zero
evidence roots, and only world-supplied outcomes move it.

## 2. `consider` — the one door into world knowledge

Whatever says a claim about the world — a person, a page, Lyric's senses, the outcome of its own work, a
lesson — it is judged by **whether it is true**, and nothing else writes the world.
(`docs/research/SEPARATION_MAP.md` §11.4.)

`consider(subject, relation, obj, *, evidence, domain, positive, …)` takes a claim through four steps:

1. **Shape and evidence quality.** What the store cannot hold is refused (`shape_proposition`), and so is
   what is too weakly supported — below `MIN_ADMIT_QUALITY`, the ingress's own floor.
2. **A person's word has a rate.** Beyond `PERSON_CLAIMS_PER_HOUR` (120) in the hour, a `USER_SUPPLIED`
   claim waits.
3. **What is held against it** (`_held_against`): the same claim held the other way, or, for a kind, a
   denial it inherits. It is counted either way, and held only once its independent witnesses outweigh
   those on the other side (`witness_weight`, owned by the belief authority). Until then it is **refused**
   where that side is settled and **doubted** where it is not. Many sources take many to overturn; a flood
   of one source's word is one witness.
4. **Held.** Written to the world through the one admission (`_admit_to_world`), the belief moved by this
   evidence exactly once (keyed on `evidence.key`), and its standing read back from the belief.

**One claim is one belief however it was spelled.** The claim is named in the store's own terms before
anything else, so "Flippers" and "flipper", "fire truck" and "fire_truck", told by two sources, are two
witnesses of one claim rather than two claims.

The door has four shapes, and nothing else writes world knowledge:

| | |
|---|---|
| `consider` | One claim |
| `consider_many` | Many claims from one source — a lesson, a corpus — each judged as `consider` judges one |
| `consider_rule` | A rule about the world ("if the valve is closed then the tank overflows", of kinds) |
| `consider_envelope` | Structured evidence: what a sense, a tool, a page or a demonstration gives in one envelope — concepts and relations together |
| `learn_concept` | A concept node and its relationships, through `consider` |

`_fan_out_learning` is the shared post-admission fan-out, so a fact and a rule touch the **same** systems:
beliefs, metrics, and the domain (`ensure_domain`, then an `EVIDENCE_ADMITTED` announcement on the body's
event spine). Its arms are isolated, every belief write moves a posterior, and `quality` is required rather
than defaulted.

## 3. Learning from what it did

The strategy-and-credit lane, driven by the coordinator.

| | |
|---|---|
| `learn_from_example` | The primary entry. Resolves the learning type and task family — stated wins, else the lossy map, else `unmapped_learning_type`, never a default family — selects a strategy through the meta-learner's hard gate, stores to memory, records the outcome with honest credit, and fires cross-domain transfer gated on the **domain**, not on success |
| `learn_from_feedback` | A verdict on a claim the substrate already made and already remembers. Flags the existing memory, credits a strategy **only** with a decision id, and moves the belief through the door |
| `learn_from_event` | Sync entry for autonomous events; returns whether learning **began**. An earlier version returned true having learned nothing |
| `learn_from_data` / `learn_from_experience` / `process_experience` / `process_interaction` | Shims onto `learn_from_example` |
| `drain_events` | Awaits in-flight event tasks before shutdown, so decision rows close |
| `query_experiences` / `get_experience_count` | Recorded experiences, which survive a restart — not the queue length |

**When every arm fails the gate**, the example is still stored and transferred but no arm is credited:
`strategy_used` is None, the reasons are carried, credit is not applied, and the empty decision still counts
toward the exploration budget so the system can recover.

The event queue is **bounded** at 200. It used to grow for the life of the process because nothing removed
from it. In-flight event tasks are held by strong reference: without that, asyncio keeps only a weak one and
a task can be collected mid-flight, losing the learning silently. Recursion is guarded per task by a
`ContextVar` depth against `_max_nesting_depth` (3).

## 4. Prediction and credit, measured

Four capabilities on this interface were once `NotImplementedError` because what stood there was fabricated.
Each is now measured from recorded outcomes.

| | |
|---|---|
| `predict_outcome` | The probability that a strategy succeeds on a task family: the mean of the same Beta(successes+1, failures+1) posterior the bandit samples from, with its Wilson interval and how many outcomes it rests on. **With no outcome recorded the prediction is None** — there is nothing to predict from. It returned 0.85/0.8 for every context |
| `update_strategy_effectiveness` | Records how a strategy actually performed, through the meta-learner, which persists the posterior and applies the credit gate so an infrastructure failure never charges a strategy. Where the decision carried a prediction, it is checked against what happened — a prediction never checked could not be wrong |
| `recommend_strategies` | Ranked by the **lower bound** of each arm's measured success rate (Wilson, 95%), so an arm that has won once is not ranked above one that has won ninety times in a hundred. Untried arms come last with no rate: untried is not a number. It returned a fixed list of four subsystem names that were not strategies |
| `consolidate_learning` | Settles what learning left open, on the authority's own schedule: known unknowns whose answer has since been learned, decisions whose outcome will never arrive (closed as indeterminate and credit-ineligible, never as failures), and trained classifiers persisted so a recognizer survives a crash rather than only a clean shutdown |

`tool_usage` reports each tool's success rate over the runs that have a verdict and its mean time over the
timed runs, and reports `available: False` with the reason when none is held. `knowledge_base_size` measures
what the substrate actually holds, by store, and is None if unreadable — it used to be a counter nothing
assigned, reported as 0 forever. `get_learning_metrics` reports this process's counters **and** the recorded
totals, labelled separately.

## 5. Transfer across domains

| | |
|---|---|
| `_transfer_from_known_domains` | On new learning in a domain: rank candidate sources by `similar_domains` (cheap), then re-rank by `suggest_mappings` strength (the real signal), and transfer from the best. A failed mapping probe is logged and returned as a probe failure, never folded into "none share a mapping" |
| `transfer_learning_across_domains` | The full worker: candidates from `suggest_mappings`, each validated, each persisted **with its verdict** through the domain master, which is the one writer. Candidate and validated counts are kept apart, and negatives are typed |
| `learn_with_domain_context` | Domain-scoped learning that reports **learned** and **earned credit** separately, so recorded-without-credit is representable |
| `transfer_learning` / `get_domain_learning_stats` | A shim onto the worker; the transfer counters and a success rate that is None when there have been no attempts |

## 6. Inducing an operator

The world is the only teacher here.

| | |
|---|---|
| `record_demonstration` | The cheap hot-path half: keep one executed demonstration, induce nothing |
| `drain_pending_induction` | Induce every signature that gathered demonstrations since it was last induced |
| `reinduce_operator` | Re-induce one operator off the hot path; promote to executable when **held-out** experience confirms |
| `induce` / `induce_on_thread` / `induce_bounded` | Learn a rule from demonstrations; on a worker thread for coroutines that learn; from a bounded basis that leaves out no miss |
| `induce_category` | Learn a rule that **names** a category, by anti-unifying labelled instances' feature facts. Refuses with fewer than two positives or no feature facts |
| `record` | Persist what induction produced, keyed against the demonstrations that produced it |
| `executable_producers` | The executable rules in a domain whose effects produce a predicate |
| `rules` / `store` / `inducer` | The stored rules, the rule store, the hypothesis-search engine |

The basis is bounded — `_BASIS_POSITIVES` and `_BASIS_NEGATIVES` at 8, `_BASIS_CONTRASTIVE` at 6 — through
`_bounded_basis` and `_relevant_frame`.

**A second acquisition mode** sits beside induction: `derive_procedure` composes learned operators into a
length-general procedure from input/output evidence alone, which widens the *sequence* rather than the
learner. `induce_causal_structure` learns which conditions gate an outcome from trials, and
`induce_sequence_rule` learns a numeric sequence's rule and what comes next — each None when the evidence
cannot decide.

## 7. Regularities — what a world does on its own

A change the substrate did not cause is still something to learn from.

| | |
|---|---|
| `record_world_change` | Keep one change the world made on its own |
| `separates` | Whether something observed tells an unmet expectation apart from the times it was met |
| `regularity_claim` / `regularity_belief` / `regularity_record` | The claim that a kind of change can be relied on, how far it can be relied on now, and how that kind has fared in its world |
| `observe_regularity` | One settled expectation as one witness of whether a regularity holds |
| `regularity_relied_on` | Whether a person's habit is relied on |

## 8. Learning English

Language is taught into **memory** as knowledge, not written to a file. The lexicon file is gone, and so is
`save_lexicon`.

| | |
|---|---|
| `learn_word_classes` | What class a word has — one memory per `(word, class)`. `WORD_CLASSES` declares the **nineteen** the substrate can hold: four open (NOUN, VERB, ADJECTIVE, ADVERB), fourteen closed (PRONOUN, DETERMINER, PREPOSITION, CONJUNCTION, SUBORDINATOR, AUXILIARY, MODAL, NEGATOR, COPULA, RELATIVE, QUANTIFIER, NUMERAL, INTERJECTION, PARTICLE), and PUNCTUATION. Before this only three existed, because a class could only be derived from a proposition's subject, relation or object slot — so every word that never stands in one was unlearnable |
| `learn_grammar_rules` / `learn_grammar_pairs` | The ways English is read, and the pairs its grammar holds — each word's categories and what each place of a doing links |
| `learn_patterns` | How English says things, from sentences taught **with** their meaning |
| `learn_structure` / `learn_arguments` / `learn_derived` | How a sentence's words go together, from a treebank; which phrases are a happening's arguments; what each word takes beside the words around it, from a categorial grammar |
| `learn_word_records` / `learn_records` | Words and sentences recorded whole — every form, every sense, how a verb is used; every layer of each sentence |
| `learn_taught_sentences` | How a sentence's meaning is composed from how its words go together |
| `learn_pronunciations` / `learn_said` / `learn_usage` | How words are said; what words are said of, counted in real use; how often each word names each thing |
| `learn_word_groups` / `learn_word_forms` | Which words keep the same company; the forms words are written in |
| `learn_listening` | What the listener's evidence is worth, counted on sentences whose meaning it was taught |
| `withdraw_pairs` / `withdraw_links` | The teacher withdrew these: what they vouched for no longer rests on them, and the beliefs and memories go with them |
| `review_learned` | Ask itself about what it was taught in a domain, and let how it does move its standing |

Punctuation is part of written language, not scenery: a full stop is where one claim ends and the next
begins. The reader acts on these marks in a dozen places and the substrate could not say what any of them
were.

## 9. Perceptual classifiers as gated mechanisms

Convolutional Tsetlin Machines are **owned** by the authority as mechanisms. Their recognitions become
knowledge only by passing the one door.

| | |
|---|---|
| `train_clause_classifier` | Grow a clause population for a set of categories from labelled examples |
| `register_clause_classifier` | Own a trained classifier, and register a `clause_classifier:<name>` contributor |
| `name_instance` | What the classifier calls an instance, **and the evidence for it** — a reading, which then goes through `consider` |
| `save_classifiers` / `load_classifiers` | Persist the mechanism so it survives a restart, and restore it on startup |
| `has_clause_classifier` / `clause_classifier_vocabulary` | Whether one is registered, and the feature order it reads |

## 10. The contribution boundary

| | |
|---|---|
| `register_contributor` | Named, so provenance survives. An anonymous proposal is untraceable, and registration is provenance rather than permission to attest |
| `contribute` | The one proposal door. An unregistered contributor is rejected; a hypothesis enters as `CANDIDATE` with zero evidence roots; nothing enters above `CANDIDATE` |
| `admit_projection` | An analogically-projected operator through the same boundary, element-level provenance kept |
| `admissions` | The full record — accepted and rejected alike |
| `metrics` | Contributors, and contributions seen, accepted and promoted |

`Admission.is_knowledge` is never true on admission.

## 11. The belief door

Every belief call delegates to the one belief authority (`bayesian_uncertainty`); see
[beliefs.md](beliefs.md).

`create_belief`, `update_belief`, `get_belief`, `belief_for_claim`, `beliefs_for_domain`, `flush_belief`,
`observe_claim` — the last being find-or-create-by-claim: it mints on the first observation and moves the
same posterior afterwards, which is the completion-belief door.

`resolve_known_unknown`, `resolve_open_unknowns` and `resolution_grounds` put open known-unknowns through
the gate: resolved **if and only if** the answer is actually held, and `resolution_grounds` gives the
verdict without acting on it.

## 12. Capability tracking

`track_capability_baseline` tracks a capability metric against its long-term baseline;
`get_capability_regressions` names every capability whose baseline is currently degrading; `record_metric`
upserts a metric's definition with its latest value; `benchmark_capability` measures the substrate against
the frozen benchmark suite and tracks the result.

## 13. Shared learning

`shared_learning` reports where each of an owner's switches stands — whether that kind of their work goes
into shared learning, and who decided. `set_shared_learning` sets one, or every one when no category is
named. `shares_learning` answers whether what Lyric learns from this kind of an owner's work may go into
shared learning; **Lyric's own work always does.** See
[world-model-and-instances.md](world-model-and-instances.md).

## 14. Who reaches it

**Callers:** `core/main.py` (boot wiring, and `save_classifiers` on shutdown); the coordinator, the
heaviest, as `coord.learning`; the reasoning faculties (`abstract_reasoning_engine`, `epistemic_engine`,
`hypothesis_testing`, `analogy_discovery`, `hierarchical_abstraction`, `neural_bridge`); the memory agent;
the domain master; `domain/evidence_producers`; `learning/exploration`; `capabilities`;
`intelligence/predictive_intelligence_system`; `integration/world_inhabitant`; `health/health_monitor`;
`quantum/quantum_learning_bridge`; and the experiments.

**Depends on:** `cognitive_ingress` (`MIN_ADMIT_QUALITY`, `shape_proposition`, `admit_conditional`,
`Provenance`); `bayesian_uncertainty` (the belief store, and `witness_weight`); `universal_domain_master`
(similarity, mappings, `ensure_domain`); `agents.memory_agent` (memories for taught word classes);
`meta_learning` (`select_strategy`, where the production gate filters arms **before** Thompson sampling so
recorded propensities are those of the policy that chose, and an all-blocked selection returns None with
per-arm reasons rather than the blocked arm; `track_learning_outcome`); the rule and demonstration
substrate (`rule_store`, `rule_induction`, `demonstration_store`, `procedure_synthesis`,
`probabilistic_version_space`, `tsetlin_gpu`); the domain layer (`domain_registry`, `universal_ontology`,
`cross_domain_reasoner`, `concept_ingestion`); and the infrastructure (`database`, `LoggingDatabase`,
`observability.failure_record`).

## 15. `ActFrame` — the world an act touches

`ActFrame` (6887) reads the world one act is about to touch, and reads it again after: `open` takes the
before-reading or declines to watch, and `close` re-reads and returns `(before, after)` over the readings
that were taken. This is what turns an executed act into a demonstration the learner can use.

## 16. Evidence

| | |
|---|---|
| `experiments/RULE-AUTHORITY-02` | The propose-versus-attest boundary, 9/9 |
| `experiments/OPERABILITY-BAR-01` · `BORROWED-KNOWLEDGE-01` | What competence in a domain is worth, and what a related domain lends it |
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | Results, with the negative ones |
| [../TEACHING.md](../TEACHING.md) | How the substrate is taught, and from which sources |
| [beliefs.md](beliefs.md) · [domain.md](domain.md) · [semantics-ingress.md](semantics-ingress.md) | The belief authority, the domain authority, and the admission gate |
