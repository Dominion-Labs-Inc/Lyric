# ENV-INVESTIGATE-01 — investigating the environment

**What it tests.** That scanning the environment:
- goes through folders recursively;
- reads file contents into knowledge, as observations;
- perceives images;
- records binaries by metadata only.

It uses the real `_scan_environment`, `_read_text_bounded` and `_ingest_environment_entry`, connected to
a stand-in learning faculty that records what would become knowledge. Nothing is written to the database.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/ENV-INVESTIGATE-01/experiment.py
```

The docstring's `scratchpad/bench_envscan.py` is an old path.

**Results.** Printed to the terminal only; no run is saved.
