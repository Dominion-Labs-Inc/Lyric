# INTENT-04 — the loop closes: meant-vs-happened, recorded and felt

**What it tests.** Intent is only worth holding if the substrate can later ask *"did I do what I meant?"*
and have the answer change something. This is **intent-governed execution with automatic post-action
reconciliation and downstream appraisal**, checked end to end on the real substrate.

| Section | What it establishes |
|---|---|
| A · reached | driving a real state goal reconciles the intent **automatically** — this experiment never calls `reconcile()`, so if the outcome is on the intent, the execution path put it there — as `fulfilled`, with what it counts as met read from the **re-observed world**, and the file really moved on disk |
| A · felt | appraisal's integrity reads its **action↔outcome** link *from the reconciled intent* (`read_from: reconciled intent`), the link it used to fake with `attribution == "success"` |
| B · missed | a route proved for a goal the world does not satisfy reconciles as **missed**, recording what it *meant* beside what actually held, landing on the intent as `abandoned` |
| B · felt | the miss is felt: the same link reads `matched_aim: false`, and an unrealized intent is measurably less coherent than a realized one (0.7 vs 1.0) |

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/INTENT-04/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-16, **15/15**
(`results/20260917T004439Z.md`).

**2026-09-28: 15/15.** The hand-written filesystem domain was deleted. This now plans over an operator the substrate learned from its own acts in `tools:path` (taught by `experiments/fs_move_teach.py` if the store has none), and states its goal in perception's words: `KIND(<path>, Ffile)`, and `¬KIND(...)` for "no longer there". The drive takes up the named workspace itself.

## Why the miss is produced the way it is

An earlier version of section B forced a real failure by making a directory unwritable. `move_file`
copied the file but could not unlink the source; the substrate observed its predicted delete-effect fail
and **correctly refuted a validated `MOVE_FILE` rule** that four experiments depend on.

The substrate behaved properly. The test was wrong: it taught the substrate something **false** about an
operator that works. Recovering took re-teaching the operator from real executions
(`experiments/fs_move_teach.py`).

So the miss is now produced without making any operator fail: a route is proved for a goal the world does
not satisfy, and reconciliation is asked what happened. The verdict must come from the world, which is the
property under test anyway.

**A test must not teach the substrate a lie.** An experiment that writes to shared learned state can
corrupt it as easily as any other writer.

## What each section does and does not cover

- Section A exercises the **real drive path** (`_drive_substrate_goal`), so "automatic" is proven there.
- Section B exercises the **same reconciliation helper the drive path calls**, with nothing executed. It
  proves the missed-vs-fulfilled verdict is decided by the re-observed world; it does not re-prove
  automatic invocation, which A already covers.
