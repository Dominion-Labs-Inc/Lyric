# SELF-PARTITION-01 — one shared mind, separate context per user

> **SUPERSEDED 2026-10-07; the script is deleted.** The rule it tested is gone. What a person tells is no
> longer kept out of the world because a person said it, nor put in when a second person agrees: memory
> splits it by what it is about, a person's own things held in their context and a claim about the world
> judged at the one door by whether it is true (`UnifiedLearningSystem.consider`;
> docs/research/SEPARATION_MAP.md §11). Promotion by a second holder (`independent_holders`,
> `mark_promoted`) was removed with it. That one person's context is unseen by another is checked by
> SPLIT-01. The record below is kept as it was.

**What it tests.** The router that decides where learning goes.
- The substrate's own learning goes into the shared concept graph and the universal beliefs, and
  writes nothing scoped.
- What a user tells it touches neither; it stays in that user's scoped context.
- One user's scoped belief cannot be seen by another user.
- When a second, independent user says the same thing, the claim is promoted into the shared graph
  and the universal beliefs, once.
- Reads of the universal beliefs never return a claim that exists only in someone's scope.

Uses real Postgres, the real learning authority, and the real belief and concept graphs.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/SELF-PARTITION-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
