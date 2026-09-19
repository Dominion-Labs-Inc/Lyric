# SELF-PARTITION-01 — one shared mind, separate context per user

**What it tests.** The router that decides where learning goes.
- The substrate's own learning goes into the shared concept graph and the universal beliefs, and
  writes nothing scoped.
- What a user tells it touches neither; it stays in that user's scoped context.
- One user's scoped belief cannot be seen by another user.
- When a second, independent user says the same thing, the claim is promoted into the shared graph
  and the universal beliefs, once.
- Reads of the universal beliefs never return a claim that exists only in someone's scope.

Uses real Postgres, the real learning authority, and the real belief and concept graphs.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/SELF-PARTITION-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
