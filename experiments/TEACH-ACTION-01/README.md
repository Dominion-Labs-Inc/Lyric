# TEACH-ACTION-01 — a curriculum of acts, and whether experience makes a distinction

**What it tests.** An operator cannot be told as a fact, since a triple has no room for preconditions, an
action and effects. So this teaches the way a curriculum does: it gives the substrate a sandbox it may
practise in, with `copy_file` and `move_file`, and every before/action/after is the substrate's own
reading.

The question is whether experience produces a **distinction**. Copy and move take the same two
arguments and differ only in whether the source survives.

**Run** (sandbox store, boots the full system):

```
POSTGRES_DATABASE=torinai_dev ./venv_torin/bin/python3 experiments/TEACH-ACTION-01/experiment.py
```

**Results.**
- No run was recorded before 2026-09-28.
- 2026-09-28: **10/10**. From its own practice it learned both operators, and the difference:
  - `COPY_FILE(?S, ?D) ∧ KIND(?S, ?k) ∧ SIZE(?S, ?z) → KIND(?D, ?k) ∧ SIZE(?D, ?z)`: the source stays;
  - `MOVE_FILE(?S, ?D) ∧ KIND(?S, ?k) ∧ SIZE(?S, ?z) → KIND(?D, ?k) ∧ SIZE(?D, ?z) ⊖ KIND(?S, ?k) ∧
    SIZE(?S, ?z)`: the source is taken away.

  The run also found an experiment bug. It read `rendered_formula`, which a stored rule does not have,
  and that code had never been reached before. It now reads the rule itself.
