# PERCEIVE-01 — sensor, image and video structure become knowledge

**What it tests.** The substrate is model-free and does not read raw pixels or waveforms here. It takes
the structure an upstream detector or sensor supplies, such as a value with a unit, recognised labels,
a duration or a capture date. That structure goes through `PerceptionManager.process_input`, and the
experiment then checks the store:
- the perception is retained;
- its edges are in the concept graph;
- a number is held as a typed quantity;
- the substrate believes the observations;
- each observation carries perception provenance.

**Run** (from the TorinAI folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 experiments/systems/PERCEIVE-01/experiment.py
```

**Results.** `manifest.json` (2026-09-13; each run overwrites it): all five checks pass.
