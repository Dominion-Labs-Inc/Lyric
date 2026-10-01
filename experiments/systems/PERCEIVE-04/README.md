# PERCEIVE-04 — remembering a picture

**What it tests.** `coord.remember_met` takes a real image in by every sense that can and stores a memory that
describes it. It keeps what the picture is seen again from (its gist) and known again by (its sight trace), never
the photograph. The experiment checks that:
- the memory is stored;
- the seeing is linked to its memory (`recall_media` finds it by memory ID);
- no photograph is kept, only the sight trace;
- the dimensions ride in the gist, and the perceived structure (its properties and the things seen in it) rides
  with the trace;
- the picture is seen again from memory (`recollect`), at its proportions;
- the memory's text describes the picture.

**Run** (from the Lyric folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-04/experiment.py
```

**Changed 2026-09-30.** `remember_image`, `remember_sound` and `remember_seen` became one rememberer,
`remember_met`, for whatever the senses met at one moment. A picture remembered on its own used to be described by
a second describer (`dominant_colors`, `regions`), while a picture seen through `see` was kept under the senses'
own names. That was two spellings of one seeing. Now there is one, so the check for the perceived structure reads
the senses' names (`properties.dominant_color`, `blobs`).

**Results.** `manifest.json` (each run overwrites it). 2026-09-30: all eight checks pass.
