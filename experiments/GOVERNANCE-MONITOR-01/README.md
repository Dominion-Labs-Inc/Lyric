# GOVERNANCE-MONITOR-01 — runtime governance as a live monitor

**What it tests.** `RuntimeGovernance.monitor()` watches actions from the live stream and checks them
against the five laws, instead of gating them beforehand.
- A compliant action is allowed and leaves no snapshot.
- A teachable breach (Law 1) is redirected and snapshotted, and execution is not halted.
- A prime-directive breach (Law 3) is blocked, halted and snapshotted.
- The snapshot is a real forensic record and is saved to the database.
- A user-context provider (the World Auth seam) stamps who was acting on the snapshot.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/GOVERNANCE-MONITOR-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.

**Note.** The plan is for the constitution to become the only governance authority. See the
2026-09-16 (night) entry in `docs/research/LAB_NOTEBOOK.md`.
