# INTEGRATION-LOOP-01 — the full know → do → frontier loop

**What it tests.** A real coordinator runs a real grounded-operator task (kite17's learned MOVE) in a
real filesystem world. The whole chain is then read back, without calling any internals by hand:
1. the task is executed;
2. the outcome is checked against the filesystem, not against the tool's own report;
3. the operating outcome is saved;
4. earned reliability moves;
5. the operability bar shifts;
6. `OUTCOME_OBSERVED` is emitted on the event spine;
7. the competence and motivation frontier is revised.

kite17's operating counters are restored at the end, so the run can be repeated.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/INTEGRATION-LOOP-01/experiment.py
```

The docstring's `scratchpad/bench_integration_loop.py` is an old path.

**Results.** Printed to the terminal only; no run is saved.
