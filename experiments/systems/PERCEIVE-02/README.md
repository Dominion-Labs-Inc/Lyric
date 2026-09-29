# PERCEIVE-02 — sight over real files

**What it tests.** The vision faculty opens real image and video files, perceives their structure with
classical algorithms, and admits what it perceived through the perception ingress. The experiment checks
that:
- what the substrate holds matches what the code read from the bytes: size, colours, shapes, codec,
  frames, duration and motion;
- model-free instance recognition fires on a learned reference and nowhere else.

**Run** (from the Lyric folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-02/experiment.py
```

**Results.** `manifest.json` (2026-09-13; each run overwrites it): all 12 checks pass.
