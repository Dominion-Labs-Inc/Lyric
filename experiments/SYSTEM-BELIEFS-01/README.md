# SYSTEM-BELIEFS-01 — the belief store and what it knows it does not know

**Finding (2026-09-26): behaviour 22/22; two wiring findings.** One belief door (`BayesianUncertaintySystem`):
the learning authority's belief calls and the store's own return the same object. Evidence moves a belief both
ways; a belief grounded in no memory is not stored, and one grounded in a memory is durable with the posterior
it holds. Wiring: `get_belief_uncertainty` and `should_defer_to_expert` are called by nothing
(`record_prediction` was a third — it is now how a strategy prediction is checked against its outcome).

**Known unknowns did not survive a restart, and a resolution was never written.** They were saved by an
untracked fire-and-forget task, and nothing in `core/` read `unified.known_unknowns` back: every restart began
with none, and curiosity and the epistemic engine — which read that set — lost every open question. Resolving
one removed it from memory only, so its row stayed open forever, and minted a belief at 0.7 grounded in
nothing. Now:

- the belief store owns the table's shape, including what the unknown's **target** is (what would satisfy it:
  an operator, a relation, or a settled doubt), what blocks it, and how it was resolved;
- registration requires a target; writes are tracked (awaited at shutdown) and replayed if the database was
  not up; `load_from_db` restores every open unknown;
- **an unknown is resolved only by the learning authority's gate** (`UnifiedLearningSystem.
  resolve_known_unknown`): the knowledge it asks for is held, the belief in it is settled (at or below
  `UNSTABLE_ENTROPY`, the same boundary the epistemic engine explores above) and grounded in something met, and
  the domain holds it. The store refuses a resolution on anything less, and writes the one it records.

**What it checks.**

| | |
|---|---|
| **A** | one door, one construction site |
| **B** | evidence raises and lowers a belief; an ungrounded belief is not stored; a grounded one is durable |
| **C** | an unknown id, claim or domain is None / empty — never invented |
| **D** | an unknown with no target is refused; a restart reloads an open unknown with its target; with nothing learned the gate leaves it open and counts the attempt; the store refuses unsatisfied grounds; once a grounded belief has settled in a held domain the gate resolves it, the answer is that belief, the resolution is written, a restart does not reopen it, and a second resolution is refused |

**The trap in measuring it.** `update_belief` moves the belief in place and returns the same object, so a
posterior must be read as a number when it is reached — two references compared afterwards are always equal.
And the cleanup must `drain_writes()` first: a known-unknown write still in flight lands after its row is
deleted (measured: the first run left exactly that row behind).

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-BELIEFS-01/experiment.py
```

Everything written — beliefs, the known unknowns, the grounding memories, the probe domain — is removed by id.
Each run writes `results/<UTC timestamp>.json` with a `.md` beside it, reporting **behaviour** (pass/fail),
**wiring** and **completeness** findings apart (`experiments/_isolation.py`).
