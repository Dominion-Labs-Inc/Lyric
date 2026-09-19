# BORROWED-KNOWLEDGE-01 — borrowing knowledge from a related domain

**What it tests.** Whether a domain confidently related to a well-known neighbour can borrow a
discounted prior from it, and so clear the operability bar through transfer.
- **(A) Mechanism** (controlled stand-ins, real methods):
  - a related domain's effective satisfaction rises;
  - an unrelated domain borrows nothing;
  - borrowing is capped;
  - a high-stakes domain cannot clear the bar by borrowing alone;
  - borrowing reaches one hop only.
- **(B) Live:** `similar_domains` runs over the real database and reports how much transfer is available
  now.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/BORROWED-KNOWLEDGE-01/experiment.py
```

The docstring's `scratchpad/bench_borrowed.py` is an old path.

**Results.** Printed to the terminal only; no run is saved.
