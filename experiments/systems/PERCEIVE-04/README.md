# PERCEIVE-04 — remembering a picture

**What it tests.** `coord.remember_image` perceives a real image and stores a memory that describes it,
keeping the image bytes with it. The experiment checks that:
- the memory is stored;
- the bytes come back exactly (same sha-256);
- the dimensions and perceived structure are kept;
- `recall_image` finds the image by memory ID;
- the memory's text describes the picture.

**Run** (from the TorinAI folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 experiments/systems/PERCEIVE-04/experiment.py
```

**Results.** `manifest.json` (2026-09-13; each run overwrites it): all six checks pass.
