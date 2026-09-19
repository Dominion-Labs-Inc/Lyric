# OPERATOR-REMOVAL-01 — learning to remove a file

**What it tests.** Whether the substrate can learn a removal operator from real deletions:
- each demonstration runs the real `delete_file` tool on a real directory and reads the
  filesystem before and after;
- the substrate's own inducer learns the rule, which goes into the real rule store;
- the rule is then validated against observations it was not learned from.

It matters for governance: until this operator existed, the constitution had no real irreversible
act to judge, and judging those acts is what REDIRECT is for.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/OPERATOR-REMOVAL-01/experiment.py
```

**Results.** Every run is saved in `results/`. Latest: 2026-09-16, 18/18, with rule
`rule_b053f38a9158` validated. The constitution redirects the proved removal to `move_file`
(`results/20260916T155819Z.md`). Record: `docs/research/BENCHMARKS.md` §2.1. The run writes to the
real rule store.
