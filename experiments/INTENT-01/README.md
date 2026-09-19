# INTENT-01 — the intent authority

**What it tests.** The foundation of the intent model (`docs/design/INTENT_AUTHORITY.md`,
`core/reasoning/intent_authority.py`), against real Postgres, nothing mocked:

- forming an intent when reasoning engages creates it (a substrate-wide shape row and an
  actor-scoped content row);
- returning to it **refreshes the same intent** — same id, version up, history grown — rather than
  rebuilding it;
- a **goal raised inside a thread is its own intent**, parented to the thread and resolved by its own
  key, so it cannot collapse into the conversation's intent (the flat-key trap);
- the **content/shape split** holds: the substrate-wide view carries no actor and no content;
- the **outcome reconciles** onto the intent (meant-vs-happened, for learning);
- it **survives a restart** — a separate `./venv_torin/bin/python3` process reads it all back;
- **forgetting the actor** removes content and continuity while the anonymous shape (the lesson)
  survives.

The restart check spawns a fresh interpreter, so persistence is proven across a real process boundary,
not asserted. The experiment uses a unique actor per run and deletes its own rows at the end, so it is
repeatable and leaves the tables as it found them.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/INTENT-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON plus a `.md` summary). Latest: 2026-09-16, **14/14**
(`results/20260916T175834Z.md`). Record: `docs/research/BENCHMARKS.md` §5.1.

**Scope.** This proves phase 1 — the authority, its store, and its lifecycle. It does **not** yet prove
that live reasoning forms intent (phase 2), that the planner records through it (phase 3), or that the
constitution and learning read from it (phases 5–6). Those are separate experiments as they land.
