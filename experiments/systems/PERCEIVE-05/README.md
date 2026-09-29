# PERCEIVE-05 — one perception pipeline, with perception kept in memories

**What it tests.** Three fixes, each checked on the booted substrate:
- Vision only senses. Every percept goes through the one pipeline (`PerceptionManager.process_input`) and
  is admitted once.
- `perceive` is the recognition primitive. A trained Tsetlin machine recognises an instance, and the
  decision (act, verify or abstain) goes out on the event spine.
- A memory records the perceptual state at the moment it forms, so recalling the memory returns what
  was perceived then.

**Run** (from the Lyric folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-05/experiment.py
```

**Results.** `last_run.txt` holds the output of a run on 2026-09-09: PASS. It is not a structured record.
