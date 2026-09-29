# REPLAN-03 — its own operator, learned by practice, in a world that keeps changing

**What it tests.** A person hands over a directory and names the act it may practise there
(`move_file`). Everything else is the substrate's own:
- it perceives the directory;
- it practises;
- it induces `MOVE_FILE` from what happened;
- it pursues a goal over that operator while the world changes under it.

The world changes in two ways:

| | what changes | what must happen |
|---|---|---|
| P1 | something else moves the file while the route is being carried out | nothing is refuted; it replans from where the file went and finishes |
| P2 | the destination directory is taken away and a plain file put in its place | the tool genuinely fails; it does not claim the goal, the file is still somewhere real, and the stopped route is withdrawn |

It also checks that an unchanged world does not spawn endless replans.

**P2 changed on 2026-09-28.** Removing the directory is no longer a failure, because `move_file`
recreates a missing destination directory by default, and the derived binding uses the tool's own
defaults. A plain file where the directory was is a destination the tool genuinely cannot use.

**Run** (sandbox store, boots the full system):

```
POSTGRES_DATABASE=torinai_dev ./venv_torin/bin/python3 experiments/REPLAN-03/experiment.py
```

The domain id `replan03_workspace` is this experiment's alone. Everything it holds is removed at the start,
on an early exit and at the end, so the operator checked is the one this run induced.

**Results.** Each run writes `results/<UTC timestamp>.json`.
- 2026-09-28: **12/12**. `MOVE_FILE` was learned from scratch by practice in the first cycle, validated,
  and nothing was refuted.
- The run before it failed on a refuted rule left by an earlier failed run, which had exited before its
  cleanup. That is why the cleanup now also runs at the start and on an early exit.
