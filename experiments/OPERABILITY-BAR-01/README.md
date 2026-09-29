# OPERABILITY-BAR-01 — the earned half of the operability bar

**What it tests.** The bridge from knowing to doing.
- **(A) Mechanism,** on a throwaway domain in the real store:
  - recorded operating outcomes move earned reliability;
  - the bar goes down after a proven-correct record and up after a poor one;
  - the gate flips.

  Satisfaction is held fixed, so only earned trust moves the bar, and the domain is deleted at the end.
- **(B) Live:** `_domain_operability` across the real domains, reporting whether the bar has moved.
  When this was written, the bar sat flat at the stakes base, because no domain had any operating
  history yet.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/OPERABILITY-BAR-01/experiment.py
```

The docstring's `scratchpad/bench_operability.py` is an old path.

**Results.** Printed to the terminal only; no run is saved.
