# CAPABILITY-BENCHMARK-01 — the capability benchmark

Two scripts that make two different claims:
- **`experiment.py` tests the harness, not capability.** It samples 6 cases and checks that the harness
  grades, counts and tracks honestly:
  - scores are in [0, 1];
  - only graded cases are counted;
  - the Wilson interval is valid;
  - scores are tracked as baselines;
  - the `benchmarkcapability` tool takes the same path.
- **`full_suite.py` is the capability measurement.** It runs every frozen case, with no sampling. The
  substrate answers through the neural bridge (not a model), and a frozen grader scores the answers.

```
./venv_torin/bin/python3 experiments/CAPABILITY-BENCHMARK-01/experiment.py
./venv_torin/bin/python3 experiments/CAPABILITY-BENCHMARK-01/full_suite.py
```

**Results.** `full_suite.py` saves every run in `results/` (JSON plus a `.md` summary). Latest:
2026-09-16, overall 0.243, 12 passed and 26 failed (`results/20260916T150327Z_full_suite.md`).
`experiment.py` only prints. Record: `docs/research/BENCHMARKS.md` §3.1.
