# SYSTEM-INTENT-01 — the intent authority, alone

**Finding (2026-09-26): behaviour 13/13, no findings.** One intent authority (`IntentAuthority`). A pursuit
is formed once per (actor, continuity key), a return refreshes rather than duplicates, reconciliation records
its outcome, an unknown id is None, and an actor can be forgotten.

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site |
| **B** | formed once; a return refreshes it |
| **C** | reconciled from the world |
| **D** | what it does not have, it says it does not have |
| **E** | an actor can be forgotten |

**The trap in measuring it.** `reconcile` returns None — its outcome is read back from the pursuit, not from the return value — and a
pursuit's `standing` is a dict, not a label. Both were harness mistakes in the first version.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-INTENT-01/experiment.py
```

Everything written is removed by id. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
