# GOVERNANCE-ABSORPTION-01 — can the constitution replace the old gate?

> **RETIRED 2026-09-26.** Its final run (`results/20260926T122208Z`) was the licence to delete the old gate: 12/12, 0 regressions, the constitution catching 17/17 against the old gate's 11/17, 0/10 false refusals. `safety_framework` was then deleted in the governance consolidation, so the old gate this compares against no longer exists and the script cannot run. Results are kept as the record.

**What it tests.** The security modules are being folded into the coordinator's constitution, one
capability at a time, so that they can be deleted. This experiment runs the gate that is live today
(`safety_framework.evaluate_action`) and the constitution (`constitution.judge`) over the same acts.
A module may be deleted only when its capabilities are absorbed and **regressions are 0**.

- **Sections A–D:** 27 acts, 17 that must be stopped and 10 ordinary ones. For each gate it measures
  regressions (the old gate blocked, the new one did not), gains, catches, false refusals and latency.
- **Section E:** the absorbed input screen on its own:
  - one screening per judgement;
  - no per-caller rate limit (callers are World Auth's business);
  - the act is blocked when an argument cannot be read, when the screen breaks, and when judging breaks.

When the database is up, the old gate writes each evaluation to `unified.safety_assessments`.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/GOVERNANCE-ABSORPTION-01/experiment.py
```

**Results.** Every run is saved in `results/`. Latest: 2026-09-16, 12/12, 0 regressions, 17/17
caught against the old gate's 11/17, false refusals 0/10 (`results/20260916T155731Z.md`).
The record and the absorption ledger are in `docs/research/BENCHMARKS.md` §1.3.
