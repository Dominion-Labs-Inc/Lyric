# Lyric documentation

Lyric is **a persistent cognitive architecture with substrate-native learning, causal reasoning, active
experimentation, cross-domain reasoning and knowledge transfer, planning, self-correction, and
probabilistic epistemic control.** No generative model participates in its reasoning, planning, judgement
of actions, or its decision to act: the substrate performs all of it.

This folder is Dominion Labs' documentation of that system. It is a reference, not a manual: it describes
what Lyric is, how it is built, and what it has been shown to do. Lyric is not an open model and its
source is not distributed, so nothing here is written for someone intending to modify it.

**The source decides.** Where a document and the running system disagree, the system is right and the
document is corrected. Every figure in the four documents below is a measurement with a date and a method
beside it, never an estimate.

---

## The four documents

These are what Dominion Labs issues, and the only documents to quote outside the engineering work. Each
answers one question and they do not overlap.

| Document | Answers |
|---|---|
| [LYRIC_PRODUCT_AND_SYSTEM_OVERVIEW.md](LYRIC_PRODUCT_AND_SYSTEM_OVERVIEW.md) | What Lyric is and what it does. The diligence-grade account of the whole system: memory and persistence, learning, domains and competence, epistemics, perception, reasoning and planning, intent, governed autonomy, self-monitoring, tools, language, coordination, boundaries, markets |
| [LYRIC_ARCHITECTURE_DOCUMENT.md](LYRIC_ARCHITECTURE_DOCUMENT.md) | How it is built. The architectural commitments, the components and who owns what, the two gates every piece of work passes, each subsystem and what feeds it, what persists |
| [LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | What has been measured, and against what. The experiment registry, per-experiment results, ablations, adversarial campaigns, and the failures and negative results, which belong here by design |
| [LYRIC_RESEARCH_TECHNICAL_THESIS.md](LYRIC_RESEARCH_TECHNICAL_THESIS.md) | The research argument: what question the architecture answers and what the evidence bears on |

## The system

Measured 2026-11-19: the substrate from a source scan, the store through the system's own configuration
authority against `lyric_db`, whose identity the server confirmed when asked, and the corpus from the
artifacts themselves.

| | |
|---|---|
| Substrate | `core/`, **242,794 lines across 263 modules**, counting what runs: the five archived perimeter modules held in `security/_disabled/` and imported by nothing add 3,589 more. The largest faculties are the coordinator and memory agent (52,517), the tools (40,891), learning (29,767) and language (29,250) |
| Experiment corpus | **246 experiment directories, 188 carrying machine-written run records, 2,166 run records** with 311 side records beside them, 2,477 artifacts in all. 142 validated, 43 findings, 58 directories holding a harness and no artifact. Latest run 2026-11-10. Index: [`../experiments/README.md`](../experiments/README.md) |
| Knowledge held | **117,294 concepts**, 590,614 relations of which 97,639 are *is-a* or *instance of*, **1,022,193 beliefs**, 1,179,242 concept evidence records and 1,783,544 belief evidence records |
| Memory held | **1,441,708 records**: 1,441,519 semantic, 150 episodic, 39 meta |
| Language held | **443,072 learned ways English says things** — the constructions and links memory holds — 146,732 word records, 94,683 word-class records, 3,052 taught sentences, and **497 ways of reading English with 87 pairs beside them**, all of it in memory rather than in a file |
| Teaching record | **440 machine-written teaching sessions**, 2026-09-08 to 2026-11-17, in [`teaching_sessions/`](teaching_sessions/) |
| Held-out evaluation data | The Parallel Meaning Bank, PropBank, the Universal Dependencies English treebanks, STREUSLE, LibriSpeech and MSWC English audio, and a vision instruction set. Held off-repository; see [Evaluation data](#evaluation-data) |
| Canonical runtime | `./venv_lyric/bin/python3`, Python 3.11.14, real PostgreSQL, real tool registry, real rule store |

Evidence is machine-written, never typed: every run saves a `RunRecord` to
`experiments/<NAME>/results/<UTC>.json` carrying its claim, its hypothesis, every check with its verdict,
metrics with units, and an environment block recording the commit, the count of uncommitted changes, and
the database both as resolved and as the server reported it. A run never overwrites an earlier one.

**The store was emptied on 2026-09-26, by decision, and taught again from the first English lesson.**
Everything in the knowledge, memory and language rows above was learned since. Counts of *running* work,
learned rules and operator demonstrations, stand at zero: those accumulate from use rather than from
teaching, and the faculties that produce them are evidenced by their experiment series.

## The substrate reference

[ARCHITECTURE.md](ARCHITECTURE.md) is the engineering master: the conceptual model, the subsystem diagram,
the authority map and the belief circulation. Each faculty then has its own document.

| | |
|---|---|
| [architecture/SUBSTRATE_SYSTEMS_MAP.md](architecture/SUBSTRATE_SYSTEMS_MAP.md) | Every system by name and size |
| [architecture/world-model-and-instances.md](architecture/world-model-and-instances.md) | What the Lyric World Model is, what an instance is, and how what an instance learns reaches the World Model |
| [architecture/coordinator.md](architecture/coordinator.md) | The body: every authority it holds, the nineteen registrations on its event spine, the cognitive cycle, and what its scheduler runs |
| [architecture/constitution.md](architecture/constitution.md) | The law: the five laws, the three doors into them, what an act is judged on, and the eighteen measurements of standing state |
| [architecture/conversation.md](architecture/conversation.md) | A thread of talk: what it remembers, how a turn is understood, and the one path from what is held to what is said |
| [architecture/drift.md](architecture/drift.md) | The substrate perceiving its own change: eleven invariants and five detectors |
| [architecture/memory.md](architecture/memory.md) | What persists, in which tier, and how it is recalled |
| [architecture/beliefs.md](architecture/beliefs.md) | How a belief forms, moves and is retired |
| [architecture/learning.md](architecture/learning.md) | The learning authorities and what each may admit |
| [architecture/reasoning.md](architecture/reasoning.md) | The kinds of reasoning and how one is chosen |
| [architecture/semantics-ingress.md](architecture/semantics-ingress.md) | The reader, and the gate language passes through to become knowledge |
| [architecture/domain.md](architecture/domain.md) | Domains, competence and how a domain comes to exist |
| [architecture/security.md](architecture/security.md) | The substrate's own boundary |
| [architecture/reasoning-pipeline.md](architecture/reasoning-pipeline.md) | The reasoning pipeline, method by method: how a question becomes a derived, checkable conclusion or an honest refusal |
| [architecture/reasoning-paths-verified.md](architecture/reasoning-paths-verified.md) | Each of the eleven kinds of reasoning, what a correct test of it must show, and the recorded result of testing all eleven against the running system |

## Standing records

| | |
|---|---|
| [research/BENCHMARKS.md](research/BENCHMARKS.md) | The standing record of measurements. Each run appends a dated row rather than replacing the last, so a regression shows as a number that moved. Nine sections: governance, operator acquisition, intent, planning, credit, system isolation and the reading work |
| [research/LAB_NOTEBOOK.md](research/LAB_NOTEBOOK.md) | Every session, in order, with what was tried and what it showed |
| [TEACHING.md](TEACHING.md) | How the substrate is taught, what it has been taught, and from which sources |
| [HANDOFF.md](HANDOFF.md) | Where the reading and understanding work stands, for the engineer taking it up |

## Research

Topic documents, each written from the code and the artifacts: [research/](research/) holds the language
and reading work ([ONE_LANGUAGE_PLAN.md](research/ONE_LANGUAGE_PLAN.md),
[SENTENCE_AND_WORD_SHAPES.md](research/SENTENCE_AND_WORD_SHAPES.md),
[WORD_SENSES.md](research/WORD_SENSES.md),
[READING_PROSE_AT_SCALE.md](research/READING_PROSE_AT_SCALE.md),
[ENGLISH_CURRICULUM.md](research/ENGLISH_CURRICULUM.md),
[COMPREHENSION_SCOPE.md](research/COMPREHENSION_SCOPE.md),
[REPLYING_TO_WHAT_IS_MEANT.md](research/REPLYING_TO_WHAT_IS_MEANT.md),
[MEANING_COVERAGE.md](research/MEANING_COVERAGE.md)), hearing
([HEARING_BY_PHONES.md](research/HEARING_BY_PHONES.md)), generalisation
([GENERALIZING_BY_KIND.md](research/GENERALIZING_BY_KIND.md)), abstention
([RESEARCH_OOD_ABSTENTION.md](research/RESEARCH_OOD_ABSTENTION.md)), the memory and separation maps, and
the systemic epistemic governance paper. [research/REASONING_IN_A_COGNITIVE_SUBSTRATE.md](research/REASONING_IN_A_COGNITIVE_SUBSTRATE.md) is Paper I of the
Cognitive Substrate Series.

## Governance, safety and harm

| | |
|---|---|
| [architecture/constitution.md](architecture/constitution.md) | The constitution that judges every act: five laws, four verdicts, eleven gates in one order, and the halt |
| [architecture/drift.md](architecture/drift.md) | What a thousand permitted acts add up to, which judging one act at a time cannot see |
| [security/SAFETY_ARCHITECTURE.md](security/SAFETY_ARCHITECTURE.md) | What a control plane must decide, reasoned out in full. A dated inventory from 2026-08-11: its argument holds, its module map does not, and its own status note traces where each capability went |
| [HARM_DEFINITION.md](HARM_DEFINITION.md) | What harm means, as the basis for Law 3 |
| [SIGNAL_PROVENANCE.md](SIGNAL_PROVENANCE.md) | Where every number the system reports about itself comes from, so that nothing that looks like a measurement carries none |
| [PERMISSION_SURFACE.md](PERMISSION_SURFACE.md) | Every operation the substrate performs autonomously, by access class |
| [security/CAPABILITIES_CATALOG.md](security/CAPABILITIES_CATALOG.md) | The capabilities of the perimeter modules that were taken out of the substrate |
| [security/chaos_testing.md](security/chaos_testing.md) | The fault-injection framework and its safety controller |

## Design and product records

Reasoning records, written at the time a decision was taken and kept as the record of it:
[design/](design/) for the substrate's design decisions,
[GOVERNANCE_SECURITY_CONSOLIDATION.md](GOVERNANCE_SECURITY_CONSOLIDATION.md) and
[DRIFT_CONSOLIDATION.md](DRIFT_CONSOLIDATION.md) for two completed consolidations,
[INTRINSIC_MOTIVATION_REDESIGN.md](INTRINSIC_MOTIVATION_REDESIGN.md) for the developmental engine,
[OFFERINGS_RESEARCH.md](OFFERINGS_RESEARCH.md) for what the system can do per offering,
[AUTONOMOUS_CAPABILITIES.md](AUTONOMOUS_CAPABILITIES.md) for the lines of autonomy, and
[PUBLIC_BETA_ROLE_PROFILES.md](PUBLIC_BETA_ROLE_PROFILES.md) for capability reasoning by role.

## Evaluation data

The corpora Lyric's reading and hearing are evaluated against are held off-repository, on an external
volume, because of their size. They are not inputs the substrate was taught on: they are what it is
measured against.

| Archive | Holds |
|---|---|
| `test_data.tar.gz` | 871,253 entries. The Parallel Meaning Bank (840,698), PropBank release (21,105) and frames (7,627), the Universal Dependencies English treebanks EWT, GUM, ParTUT, LinES, Atis and PUD, STREUSLE, and the held-out grammar word and WordNet link sets |
| `data_speech.tar` | 59,054 entries. LibriSpeech forced alignments and per-word audio in test and dev splits, and MSWC English |
| `data_bulk.tar` | ConceptNet assertions 5.7.0, the UD English EWT CoNLL-U train, dev and test files |
| `data_vision_flan.tar.gz` | A 1,000-item vision instruction set with its images |
| `data_records.tar.gz` | The record sets runs are scored against: PMB gold, the 182-word 62-sentence gold subset, EWT words, and two small sets |
| `data_backups.tar.gz` | A taught-propositions export and two corruption-test fixtures |

## Audits and archive

[audits/](audits/) holds point-in-time audits, each dated and kept as found.
[archive/](archive/) holds superseded documents. **Nothing in the archive describes the running system,
and nothing in it should be quoted as current;** each note there says what replaced what it describes.
