# PERCEIVE-EVAL — perceive and name, measured

**What it tests.** Three categories: red circle, blue square and green triangle. For each one, the
substrate:
1. perceives real images;
2. sees a few labelled examples;
3. induces a naming rule;
4. is tested on held-out images, which it should either name or decline.

Measured: perception fidelity, naming recall, abstention, and model calls (which must be 0).

**Run** (from the TorinAI folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 experiments/systems/PERCEIVE-EVAL/experiment.py
```

**Results.** `manifest.json` (2026-09-17; each run overwrites it), 31 images:
- shape and colour were perceived correctly every time;
- **naming recall was 1.0**, with abstention at 100%, 0 hallucinations and 0 model calls;
- with the learned rules ablated, naming recall drops to 0 and abstention stays at 100%, so the naming comes
  from the induced rules.

The 2026-09-13 result (recall 0, no rules induced) was the label leakage described in
[PERCEIVE-03](../PERCEIVE-03/README.md), fixed in `induce_category`.
