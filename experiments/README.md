# Experiments

Each experiment has its own folder with a short `README.md`: what it tests, how to run it, and what its
saved results say. Run everything from the TorinAI folder with `./venv_torin/bin/python3`.

**Where results go.**
- **Newer experiments** save every run through `_evidence.py` to `<folder>/results/<UTC timestamp>.json`,
  with a short `.md` summary beside it built from the same data. A run never overwrites an earlier
  one: a second run in the same second gets a `_2` suffix.
- **Older experiments** either only print, or write one fixed file (`manifest.json`, `result.json`,
  `last_run.txt`) that each run replaces.

The standing record of measurements is `docs/research/BENCHMARKS.md`; session notes are in
`docs/research/LAB_NOTEBOOK.md`.

## Governance — the constitution

| Experiment | What it tests | Saved runs |
|---|---|---|
| [CONSTITUTION-01](CONSTITUTION-01/) | The constitution judging real acts, with intent taken from real reasoning | `results/` |
| [CONSTITUTION-02](CONSTITUTION-02/) | The same under noise, coercion, forged intent, evasion, laundering, TOCTOU | `results/` |
| [CONSTITUTION-03](CONSTITUTION-03/) | A determined adversary, in campaigns — 5/8 campaigns held, 3 gaps found | `results/` |
| [GOVERNANCE-ABSORPTION-01](GOVERNANCE-ABSORPTION-01/) | The old gate and the constitution on the same acts; regressions must be 0 before a module is deleted | `results/` |
| [GOVERNANCE-MONITOR-01](GOVERNANCE-MONITOR-01/) | `RuntimeGovernance.monitor()` as a live monitor | printed only |
| [INPUT-VALIDATION-01](INPUT-VALIDATION-01/) | The OLD gate's input validation (not the constitution's) | printed only |
| [systems/GOV-ABLATION-01](systems/GOV-ABLATION-01/) | Whether the promotion gate stops a false rule from gaining authority to act | see its README |
| [systems/GOV-CASCADE-01](systems/GOV-CASCADE-01/) | Whether one injected error contaminates authority as derivations get deeper | see its README |

## Identity, users and concurrency

| Experiment | What it tests | Saved runs |
|---|---|---|
| [ACTOR-IDENTITY-01](ACTOR-IDENTITY-01/) | What a person teaches is scoped to their verified identity, not the session | printed only |
| [FRONTDOOR-IDENTITY-01](FRONTDOOR-IDENTITY-01/) | The front door binds the verified identity to the conversation | printed only |
| [SELF-PARTITION-01](SELF-PARTITION-01/) | One shared mind plus separate per-user context, with promotion when users corroborate | printed only |
| [TASK-RESULT-01](TASK-RESULT-01/) | Fetching a job's result, visible only to the person who asked | printed only |
| [PER-USER-CONCURRENCY-01](PER-USER-CONCURRENCY-01/) | Several tasks per user, shared fairly under a global cap | printed only |
| [CHAT-CONCURRENCY-01](CHAT-CONCURRENCY-01/) | How many people can chat at once | printed only |
| [LOOKUP-SINGLEFLIGHT-01](LOOKUP-SINGLEFLIGHT-01/) | Many callers asking about the same unknown cause one lookup | printed only |

## Learning, motivation and affect

| Experiment | What it tests | Saved runs |
|---|---|---|
| [OPERATOR-REMOVAL-01](OPERATOR-REMOVAL-01/) | Learning a removal operator from real deletions | `results/` |
| [CAPABILITY-BENCHMARK-01](CAPABILITY-BENCHMARK-01/) | The capability benchmark: harness check (`experiment.py`) and measurement (`full_suite.py`) | `results/` (full suite) |
| [CAPABILITY-BASELINE-01](CAPABILITY-BASELINE-01/) | Capability baselines and regression tracking | printed only |
| [MOTIVATION-CLOSEDLOOP-01](MOTIVATION-CLOSEDLOOP-01/) | Closing one pursuit changes which pursuit comes next | printed only |
| [INTRINSIC-EVENTDRIVEN-01](INTRINSIC-EVENTDRIVEN-01/) | Intrinsic pursuit is triggered by events, not a timer | printed only |
| [INTEGRATION-LOOP-01](INTEGRATION-LOOP-01/) | The full know → do → frontier loop on a real task | printed only |
| [AFFECT-WIRING-01](AFFECT-WIRING-01/) | Approach and avoidance pressures now change behaviour | printed only |
| [INTEGRITY-01](INTEGRITY-01/) | Integrity measured as coherence, not success | printed only |
| [systems/EPISTEMIC-AFFECT-01](systems/EPISTEMIC-AFFECT-01/) | Changes in knowledge become feeling, in one direction only | `last_run.txt` |

## Planning

| Experiment | What it tests | Saved runs |
|---|---|---|
| [PLANNING-01](PLANNING-01/) | One planning authority, and every planning path verified honest — proved plans grounded, unreachable goals yield no plan, template plans declare where their numbers came from | `results/` |

Record: `docs/research/BENCHMARKS.md` §6.

## Intent — reasoning's own account of what it is doing

| Experiment | What it tests | Saved runs |
|---|---|---|
| [INTENT-01](INTENT-01/) | The intent authority + store: formed on engagement, refreshed not rebuilt, goal-in-thread tree, content/shape split, restart survival | `results/` |
| [INTENT-02](INTENT-02/) | The bridge forms intent on every real `reason()` — formation, refresh, goal parenting, concurrency, latency, restart | `results/` |
| [RECONCILE-01](RECONCILE-01/) | Whoever owns a pursuit closes its intent once, from the world — plan, standalone operator (including refused), declared-tool operation; plan steps close nothing | `results/` |

Design: `docs/design/INTENT_AUTHORITY.md`. Record: `docs/research/BENCHMARKS.md` §5.

## Knowledge and domains

| Experiment | What it tests | Saved runs |
|---|---|---|
| [DOM-KG-01](DOM-KG-01/) | A knowledge gap versus a missing operator | `result.json` |
| [BORROWED-KNOWLEDGE-01](BORROWED-KNOWLEDGE-01/) | Borrowing a prior from a related domain | printed only |
| [OPERABILITY-BAR-01](OPERABILITY-BAR-01/) | The earned half of the operability bar | printed only |
| [ENV-INVESTIGATE-01](ENV-INVESTIGATE-01/) | Scanning the environment into knowledge | printed only |
| [systems/KNOW-50](systems/KNOW-50/) | 50 questions about what it was taught | `manifest.json` |
| [systems/VERIFY-01](systems/VERIFY-01/) | A snapshot of every faculty's pipeline as it runs today | see its README |

## Perception (`systems/`)

| Experiment | What it tests | Last saved outcome |
|---|---|---|
| [PERCEIVE-01](systems/PERCEIVE-01/) | Sensor, image and video structure become knowledge | pass (2026-09-13) |
| [PERCEIVE-02](systems/PERCEIVE-02/) | Sight over real files | pass (2026-09-13) |
| [PERCEIVE-03](systems/PERCEIVE-03/) | Learning to name what it sees | pass, 5/5 (2026-09-17) |
| [PERCEIVE-04](systems/PERCEIVE-04/) | Remembering a picture | pass (2026-09-13) |
| [PERCEIVE-05](systems/PERCEIVE-05/) | One perception pipeline, with perception kept in memories | pass (2026-09-09) |
| [PERCEIVE-EVAL](systems/PERCEIVE-EVAL/) | Perceive and name, measured | naming recall 1.0, abstention 100%, 0 hallucinations (2026-09-17) |

## Education ladder (`edu/`)

See [edu/README.md](edu/README.md).

Several of these scripts import modules that have since been deleted: `core.model_policy`, and
`core.services.unified_llm` (the LLM teacher, retired on 2026-09-13). The affected scripts are
CSP-AGI-1, EDU-04, EDU-05, EDU-06, EDU-07, EDU-08, EDU-09, EDU-12, EDU-13, EDU-14, EDU-15, EDU-16 and
[systems/SESSION-01](systems/SESSION-01/). Their saved results stand as recorded, but the scripts do
not run as written.

## Shared worlds and tools

| File | What it is |
|---|---|
| `_evidence.py` | Run records: a new JSON file per run, plus its `.md` summary |
| `e2e_world.py`, `e2e_common.py` | A real filesystem world: rooms are directories |
| `archive_world.py`, `warehouse_world.py` | Further real worlds in other domains, with different predicates |
| `warehouse_stochastic.py`, `warehouse_latent.py`, `warehouse_complex.py` | The EDU warehouse with unreliable outcomes, a hidden cause, or twelve conditions |
| `computation_world.py` | A world where the values a plan needs do not exist until it runs |
| `data_world.py` | A data environment: values are held, operations compute, and `observe()` reads back what is there |
| `list_machine.py` | A machine that supplies instructions, not answers |
| `sentence_machine.py` | Moved to `core.semantics.sentence_machine` |
| `archive_teach.py` | Learns the ARCHIVE operator from real execution |
| `kite_teach.py`, `kite_evaluate.py`, `kite_ablation.py` | KITE-17: teach, evaluate, and test whether the capability lives in the learned rules |
| `substrate_baseline.py` | Freezes what the substrate held before an experiment taught it |
| `verify_wiring.py` | Evidence for the evidence-source wiring (writes `WIRING_EVIDENCE.json`) |
| `world/habitat.py` | A contained sandbox world (`world/sandbox/`) that exercises every faculty |

## Other folders

- `results/` — the KITE-17 ablation. `kite17_ablation.json` is the valid run.
  `kite17_ablation_INVALID_run1.json` is invalid because of a configuration isolation failure; its
  `.md` says why.
- `baselines/` — `pre_kite.json`, what the substrate held before KITE-17 was taught; and
  `kite_taught.json`, the rules that teaching produced.
- `cleanup/` — the rule-identity cleanup of 2026-08-19 and the script that quarantined a rule artefact.

**Still writing fixed filenames** (each run replaces the last): `kite_ablation.py`, `kite_teach.py`,
`substrate_baseline.py`, `verify_wiring.py`, the EDU manifests, and the `systems/` manifests.
