# INTENT-02 — reasoning forms intent, on the real bridge

**What it tests.** Phase 2: the wiring that makes the reasoning authority actually own intent. A real
reasoning pass through `NeuralSymbolicBridge.reason` opens the substrate's intent where reasoning starts,
refreshes it as it firms up, stamps its id onto the result, and holds the content/shape split — against
the real bridge and real Postgres, nothing mocked (`core/reasoning/neural_bridge.py` `_intent_engage` /
`_intent_settle`; `docs/design/INTENT_AUTHORITY.md` phase 2).

Not a minimum test. It covers:

- a thread-anchored reasoning forms a thread intent; the result carries its `intent_id`;
- a second turn on the thread **refreshes the same intent** (version up, history grown), not a new one;
- a goal-anchored reasoning is its **own** intent, parented to the thread;
- an anchorless reasoning keys on the query — the **same** query refreshes one intent, a **different**
  query is a different intent;
- the **content/shape split**: content refreshes to the latest turn while the first turn survives in
  history, and the query is never in the substrate-wide shape;
- **concurrency**: six reasoning passes on one thread at once collapse to exactly one intent (the
  unique-key race is handled — no duplicates);
- **latency**: the cost is measured, not guessed;
- **restart**: a fresh `./venv_lyric/bin/python3` reloads the thread intent (settled) and the parented goal.

Self-cleaning: unique actors per run, and it deletes its own rows (scoped + shape) at the end.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/INTENT-02/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-16, **15/15**
(`results/20260916T185632Z.md`); reason()-call latency mean ~36 ms. Record: `docs/research/BENCHMARKS.md`
§5.2. (An earlier run, `20260916T185503Z`, is kept at 12/14 — it caught two wrong assertions in this
experiment, since corrected; the code was right. Evidence is not overwritten.)

**Scope.** Proves that live reasoning forms and refreshes intent. It does not yet prove the planner
records through the authority (phase 3), the old `Intent` is gone (phase 4), or the constitution and
learning read from it (phases 5–6).
