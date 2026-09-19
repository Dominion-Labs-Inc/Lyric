# KNOW-50 — 50 questions about what it was taught

**What it tests.** The real substrate is asked 50 questions drawn from the English IsA taxonomy it was
taught, and it is given only the question. For each one the run shows:
- what it reasons (`coord.reason_about`);
- what it believes (its posterior);
- the derivation.

The expected answers are used only to score the run afterwards.

**Run** (from the TorinAI folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 experiments/systems/KNOW-50/experiment.py
```

**Results.** `manifest.json` (2026-09-13; each run overwrites it):
- 37 of 50 questions answered, all 37 correctly;
- 13 refused or unknown: all 10 questions whose answer is "no", and 3 of the 40 whose answer is "yes";
- 0 model calls.
