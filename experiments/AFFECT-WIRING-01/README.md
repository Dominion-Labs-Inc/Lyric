# AFFECT-WIRING-01 — two disposition pressures now change behaviour

**What it tests.** Appraisal computed two pressures that nothing used. Both now act through settings the
loop already reads (`should_explore`, `max_goals`, `mode`).
- **Approach** reaches the behavioural directive: a confident state takes on more self-initiated goals
  (a higher `max_goals`).
- **Avoidance** holds back self-initiated exploration. This is shown with escalation not firing, so
  avoidance is the cause.
- Escalation works as it did before.
- The directive's `to_dict()` shows both new signals.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/AFFECT-WIRING-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
