# PERCEIVE-03 — learning to name what it sees

**What it tests.** The full loop, with no model:
1. perceive real images;
2. teach each blob's features as facts;
3. label a few of them;
4. induce a naming rule (for example, red and circular means stop sign);
5. save the rule;
6. name a held-out blob through ordinary reasoning, and abstain on a category it never learned.

**Run** (from the Lyric folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-03/experiment.py
```

**Results.** `manifest.json` (2026-09-17; each run overwrites it): **PASS, 5/5**, on two runs in a row.
- From two labelled examples it learned `circle ∧ vivid_red → stopsign`. It dropped size, and the red-square
  and blue-circle negatives refuted the over-general alternatives.
- It named the held-out red circle through ordinary reasoning, using the learned rule.
- It abstained on the unlearned blue square and hallucinated nothing.

**The earlier FAIL (2026-09-13 to 2026-09-17) was label leakage from earlier runs.**
- **The mechanism:** a successful run writes `reda isa stopsign` and `redb isa stopsign`. The next run read
  `stopsign` back as one of their features, so labelling them "added" nothing, and induction found no effect
  to explain.
- **The fix:** `induce_category` now treats the category being learned as the label, never as a feature. The
  same defect would have broken any real re-teach of a category.
