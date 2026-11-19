# The substrate — every system by name and size

*Part of the [substrate architecture reference](../ARCHITECTURE.md).*

*Re-traced 2026-11-19.*

`core/` is **242,794 lines across 263 modules**, counting what runs. The five archived perimeter modules
held in `security/_disabled/` and imported by nothing add 3,589 more. Tests, experiments and tooling are
excluded.

Each faculty has one authority, reached through one accessor, and one document. **Where a second thing
would decide the same question, it is a defect** — `scripts/separation_map.py` fails the build when one
appears.

---

## The authorities

| Faculty | Authority | Accessor | Document |
|---|---|---|---|
| The body | `AutonomousCoordinator` | `get_autonomous_coordinator()` | [coordinator.md](coordinator.md) |
| The law | `Constitution` | `get_constitution()` / `judge_act()` | [constitution.md](constitution.md) |
| Self-perception over time | `Drift` | `coordinator.drift` | [drift.md](drift.md) |
| Conversation | `Conversation` | `get_conversation(session)` | [conversation.md](conversation.md) |
| Memory | `MemoryAgent` | `get_memory_agent()` | [memory.md](memory.md) |
| Learning | `UnifiedLearningSystem` | `get_learning_authority()` | [learning.md](learning.md) |
| Beliefs | `BayesianUncertaintySystem` | `get_uncertainty_system()` | [beliefs.md](beliefs.md) |
| Reasoning | `NeuralSymbolicBridge` | `get_neural_bridge()` | [reasoning.md](reasoning.md) |
| Domains | `UniversalDomainMaster` | `get_universal_domain_master()` | [domain.md](domain.md) |
| Admission | `CognitiveIngress` | `get_cognitive_ingress()` | [semantics-ingress.md](semantics-ingress.md) |
| Perception | `PerceptionFaculty` | `get_perception_faculty()` | — |
| Work | `QueueAuthority` | `get_queue_authority()` | — |
| Intent | `IntentAuthority` | `get_intent_authority()` | — |

## By subsystem

| Subsystem | Lines | Modules | Largest modules |
|---|---|---|---|
| `agents/` | 52,517 | 27 | `autonomous/autonomous_coordinator.py` 27,378 · `memory_agent.py` 9,974 · `autonomous/intrinsic_motivation.py` 3,712 · `autonomous/queue_authority.py` 1,668 · `autonomous/appraisal.py` 1,319 |
| `tools/` | 40,891 | 30 | `security_tools.py` 3,890 · `code_generation_tools.py` 3,661 · `testing_validation_tools.py` 2,702 · `tool_registry.py` 2,607 · `search_tools.py` 2,587 · `filesystem_tools.py` 2,325 |
| `learning/` | 29,767 | 29 | `unified_learning_system.py` 7,236 · `teaching_sources.py` 6,204 · `rule_induction.py` 1,633 · `meta_learning.py` 1,556 · `teaching.py` 1,356 · `rule_store.py` 1,194 |
| `semantics/` | 29,250 | 23 | `derived_reader.py` 9,833 · `grammar.py` 7,720 · `sentence_reader.py` 1,483 · `cognitive_ingress.py` 1,043 · `structure.py` 1,025 · `composition.py` 933 |
| `reasoning/` | 24,567 | 23 | `neural_bridge.py` 4,452 · `bayesian_uncertainty.py` 2,884 · `abstract_reasoning_engine.py` 2,727 · `hierarchical_abstraction.py` 2,308 · `temporal_reasoning.py` 1,535 · `hypothesis_testing.py` 1,241 |
| `perception/` | 8,915 | 10 | `perception_faculty.py` 2,365 · `vision.py` 1,497 · `speech.py` 1,167 · `hearing.py` 1,148 · `live.py` 919 · `music.py` 907 |
| `chaos/` | 8,505 | 23 | The fault-injection framework and its safety controller |
| `domain/` | 8,144 | 10 | `concept_ingestion.py` 1,724 · `domain_registry.py` 1,603 · `evidence_producers.py` 1,471 · `cross_domain_reasoner.py` 1,015 · `universal_ontology.py` 888 |
| `integration/` | 6,364 | 6 | `universal_domain_master.py` 4,201 · `slack_notifier.py` 1,097 |
| `memory/` | 5,453 | 13 | `storage/postgres_storage.py` 1,782 · `utils/interfaces.py` 945 |
| `quantum/` | 5,264 | 11 | Deactivated; retained, and not in the cognitive path |
| `health/` | 4,788 | 5 | `health_monitor.py` 3,295 · `recovery_manager.py` 967 |
| `database/` | 3,609 | 5 | `unified_database_postgres.py` 1,422 · `logging_database.py` 870 |
| `intelligence/` | 2,218 | 3 | `predictive_intelligence_system.py` 1,429 |
| `system/` | 1,920 | 6 | Environment state, service location, active discovery, topology |
| `utils/` | 1,590 | 8 | Environment loading, notification, chunking, port management |
| `observability/` | 1,329 | 5 | The one failure record, the regression record, capture, channels |
| `security/` | 1,276 | 3 | `security_training_pipeline.py` 892, and secret handling |
| `connectors/` | 906 | 4 | Speaking the Model Context Protocol as a client |
| `services/` | 822 | 2 | The backup scheduler |
| `monitoring/` | 596 | 4 | Prometheus metrics export |
| `api/` | 590 | 2 | The companion channel |
| `simulation/` | 411 | 2 | Numerical and system-dynamics simulation |
| `guardian/` | 269 | 2 | The supervising daemon, outside the substrate's process |
| `optimization/` | 226 | 1 | Optimisation utilities |
| `core/*.py` | 2,607 | 6 | `main.py`, `capabilities.py`, `database.py`, `service_configuration.py`, `structural_defects.py`, and the package initialiser |

Two subsystems are not in the cognitive path. **`quantum/`** is deactivated and retained.
**`security/_disabled/`** holds the five perimeter modules — the host and network boundary that once ran
inside the substrate — imported by nothing; containment is Tet's, outside the substrate
([security.md](security.md)).

**`execution/` no longer exists.** It held effect verification, domains derived from the tools, and
procedures over learned operators; each went to the subsystem that owns it —
`intelligence/effect_verification.py`, `learning/procedure_synthesis.py` with `learning/rule_store.py`,
and the coordinator.

## The four pipelines

Each is one authority's, and each is exercised end to end on the running system in
`experiments/systems/VERIFY-01`.

| Pipeline | Runs | Entered from |
|---|---|---|
| **Reasoning** | `_substrate_solvers` for every request, then the eleven kinds, then a named mode only if neither settled it. No model fallback | `AutonomousCoordinator.reason_about` |
| **Learning** | `consider` as the one door into world knowledge; demonstrations accumulate, induction drains off the acting path, and a rule becomes executable only when held-out experience confirms it | Acting and experience, through the coordinator |
| **Memory** | `store_memory` decides worthiness and type itself; everything else the substrate holds enters through the write methods, and nothing else writes a memory table | Every authority that decides what to hold |
| **The body** | The cognition loop dispatches and reaps; nineteen reaction registrations on the event spine carry the rest; seven recurring jobs sample what no event can | `core/main.py` |

## Where a faculty's work is evidenced

| | |
|---|---|
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | The experiment registry and every result, including the negative ones |
| [../research/BENCHMARKS.md](../research/BENCHMARKS.md) | The standing record: each run appends a dated row, so a regression shows as a number that moved |
| [../SIGNAL_PROVENANCE.md](../SIGNAL_PROVENANCE.md) | Where every number the system reports about itself comes from |
