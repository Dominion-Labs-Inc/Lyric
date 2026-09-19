# PER-USER-CONCURRENCY-01 — several tasks per user, shared fairly

**What it tests.** Each user may run up to `per_actor_max_tasks` tasks at once, under a global cap. The
substrate's own work is exempt from the per-user cap.
- A user at their cap is skipped and other users are served. The skipped jobs stay queued.
- Once that user is under their cap again, their jobs are served, in their original priority.
- The coordinator caps users, never the substrate.
- A finished task frees that user's slot.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/PER-USER-CONCURRENCY-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
