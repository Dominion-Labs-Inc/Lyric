# SEPARATION-01: staging serves a frozen release, and keeps runtime, the model and each person's context apart

**Finding (2026-09-27, run `20260927T171536Z`, 33/33).** Release 1 (10,894 rows) was cut from the sandbox and staged,
and staging served it:
- **What each person told it** landed in user context and nowhere else.
- **The substrate's own memory** went to the learning store. It was never read back: the substrate's search found
  only the release's memory.
- **Recall and answers** stayed with each owner. Research topics carried no person's context.
- **Runtime** held its running records and no memory.
- **Nothing was refused** in the whole run, and nothing tried to change the release. Afterwards the release matched
  its checksum.
- **Untouched:** development received nothing from staging, and the main line had no new rows and no release.

The model is taught in development: the sandbox, `torinai_dev`, runs the development phase in `experiments/_develop.py`.
It is then cut into release 1 and staged. The experiment process itself is staging, serving release 1. Where each row
landed is read over a separate connection to each database, never through the database manager being tested.

| Database | What it holds after the run |
|---|---|
| `torinai_dev_model_v1` (the release, read-only) | the lesson's pattern memories, the model's facts, beliefs and ledger, and the memory development made |
| `torinai_dev_staging_user_context` | each person's told fact and their memory |
| `torinai_dev_staging_learning` | the substrate's own memory made while serving, never read back while serving |
| `torinai_dev_staging_runtime` | the running records, and no memory at all |

## What it checks

| Part | Check |
|---|---|
| A. Release | release 1 is cut from the sandbox's model and staged. It is read-only and intact, and holds no person's memory and no person's context table |
| B. Staging | the process is staging serving release 1, and checked its release before serving. It holds one pool per store, each reaching its own database. The tools that reach its own databases are not carried |
| C. Boot | the substrate starts. No statement is refused or reaches a database without its table, and nothing tries to change the release |
| D. Model | the lesson is in the release: 9 patterns, the model's facts, beliefs, ledger. None of it is in user context or the learning store |
| E. People | two people each tell a fact and leave a memory: both land in user context, in neither the release nor the learning store. The substrate's own new memory goes to the learning store |
| F. Recall | each person finds their own memory and the release's, never the other's. The substrate's own search finds the release's memory, and neither a person's nor the memory it made while serving |
| G. Reason | a person's context answers their question. The other person's context and the substrate's do not |
| H. Research | topics come from the release and carry no person's context |
| I. Runtime | it holds running records and no memory |
| J. Untouched | nothing is refused and nothing tries to change the release in the whole run (both counted where they are raised). The release matches its checksum. Development received nothing from staging, and the main line is untouched |

## Traps in measuring it

**A harness that flatters.** The first version of this experiment read only warning logs and passed 26/26, while
260 refusals were raised and swallowed. Refusals are counted where the manager raises them, and so are frozen
refusals (`db.frozen_refusals`).

**What the audit found in a frozen environment.** Each was a write a serving process tried to make to its release:
- the boot writing every tool's projection into the model (344 writes; the release already holds it);
- the boot's encoding of concepts cut without vectors. A release is now cut with every concept encoded, and a
  frozen release is not encoded.

## Run

```
./venv_torin/bin/python3 experiments/SEPARATION-01/experiment.py
```

It empties the sandbox line first (`scripts/reset_dev_store.py`). The version that ran the world copy (28/28, run
`20260927T144018Z`) is backed up in `archive/superseded_separation_2026-09-27/`.
