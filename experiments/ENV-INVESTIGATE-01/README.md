# ENV-INVESTIGATE-01 — investigating the environment

**What it tests.** That scanning the environment:
- goes through folders recursively;
- holds each thing's structure (what it is, its extension and size, that the environment contains it);
- hands what each file holds to the one act of perceiving (`take_in`), which takes it in by every sense that
  can: a picture seen, a recording heard, a text read;
- judges what a file can give by its bytes, so a text with no extension is read and a binary never is;
- records a binary, and a text past the read bound, by metadata only.

It uses the real `_scan_environment`, `_ingest_environment_entry` and the senses' own judgement
(`PerceptionFaculty.senses_of`). They are connected to a stand-in that records the structural facts learned and
what is handed to `take_in`. Nothing is written to the database. What the one act does with a text it reads is
READ-01's to show.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/ENV-INVESTIGATE-01/experiment.py
```

**Changed 2026-09-30.** The scan used to read text files itself: its own line loop, at quality 0.3, into a stand-in
learning faculty that accepted everything. The real learning door refuses anything below 0.5
(`MIN_ADMIT_QUALITY`). So this experiment passed while the substrate held nothing any of its files said. The scan
now takes files in through the one act, and what a document says is held at the door's floor (READ-01). The
stand-in no longer stands in for learning.

**Run 2026-09-30:** 10/10.
