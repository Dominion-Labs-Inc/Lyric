# RECONCILE-01 — whoever owns a pursuit closes it, once, from the world

**What it tests.** Reconciliation (meant vs. happened) is a pipeline stage with one rule: the execution path
that **owns** a pursuit closes its intent, exactly once, from the re-observed world. Earlier experiments drove
`coord._run_tool`, which owns nothing, so the owner paths were never exercised. Here every case goes through
the real dispatcher, `execute_task`.

| Case | Path | What it establishes |
|---|---|---|
| A | plan owner (`_drive_substrate_goal`) | a two-step route closes **once**, after **both** files moved, as fulfilled |
| B | plan step (`plan_id` set) | the step runs and confirms, and leaves the plan's intent open for its owner |
| C | standalone operator | closes its own intent as fulfilled, and returns the verdict with its result |
| D | standalone operator, wrong destination | the rule is **confirmed** but the intent closes as **missed**: the world decides, not the step |
| E | standalone operator, refused (Law 2, never read) | the pursuit still closes, as missed, with the refusal as the reason; nothing on disk changes |
| F | declared-tool operation (`_execute_operation`) | closes its own intent as fulfilled |
| G | declared-tool operation that is a plan step | closes nothing |

Throughout, the `MOVE_FILE` rule stays validated. `_reconcile_intent` is wrapped only to count calls.
The experiment deletes every intent it forms.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/RECONCILE-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-17, **27/27**.

**What the first run found.** 25/27:
- **C (a real gap):** a standalone operator closed its intent but did not return the verdict with its
  result. The plan and tool paths did. Fixed.
- **D (an error in this experiment):** it compared against the wrong outcome string. Fixed.

A third defect was fixed before the run: a **refused** standalone operator returned before closing, so its
intent stayed in `forming`.

**Not covered.** Nothing in production dispatches queued plan steps (`PlanningEngine.get_next_tasks` has no
production caller), so a route run step by step from a queue has no owner that closes it. That path is not
live today; if it is wired, it needs an owner.
