# CAPABILITY-BASELINE-01 — capability baselines and regression tracking

**What it tests.** The learning authority records a baseline for a component's capability once, compares
every later reading with it, and reports regressions.
- The first reading sets the baseline and invents no trend.
- A reading within ±5% is stable, a drop of more than 5% is degrading, and a rise of more than 5% is
  improving.
- `get_capability_regressions()` lists a degrading capability and drops it once it recovers.
- `establish=False` refuses to create a baseline from an unfit reading, but still updates an existing one.
- Decimal and float readings compare correctly.

Uses real Postgres and cleans up after itself.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/CAPABILITY-BASELINE-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
