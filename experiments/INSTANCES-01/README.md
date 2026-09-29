# INSTANCES-01 — many instances of the model, one store: no instance undoes another

**Finding (2026-09-26): 11/11.** Once the main model is taught, it runs as many instances. Every
instance holds its own in-memory copies — beliefs, strategy arms, known unknowns, queued work — and they all
write the one store. Four of those writes were **last-writer-wins**, measured in the code before this fix:

| state | what an instance did | what was lost |
|---|---|---|
| beliefs (`_write_belief_row`) | upserted its own posterior | the other instance's evidence |
| strategy arms (`MetaLearner.save_strategy`) | upserted ABSOLUTE trials/successes | the other instance's outcomes |
| known unknowns (`_write_known_unknown`) | upserted its whole row | a resolution — a stale instance reopened it |
| the durable queue (`restore_pending`) | re-queued EVERY owed row at boot, reset running ones | exclusivity — a job could run twice |

**Now:**
- a **belief** row is replaced only if it is still at the version (`update_count`) this instance last saw;
  on a conflict the instance re-applies its OWN new evidence on top of the stored belief with the same
  kernel, and writes that;
- a **strategy outcome** is one atomic increment, and the instance takes the store's totals back — one
  posterior, however many instances feed it;
- a **known unknown** that is resolved is final (the upsert never touches a resolved row), attempts are an
  atomic increment, and the first target stands; consolidation refreshes each instance's open set;
- **queued work** is owned: each instance heartbeats (`unified.queue_instances`, every 30 s); at boot it
  CLAIMS only work whose owner has no live heartbeat (120 s lease), in one statement with
  `FOR UPDATE SKIP LOCKED`; a clean stop releases its lease. A job's result is read from the store when the
  instance polled does not hold it.

**What it checks.**

| | |
|---|---|
| **A** | two instances update one belief → both pieces of evidence are in it, and the posterior is A's update with B's evidence applied on top |
| **B** | 3 outcomes from one instance, 2 from another → the stored arm has 5, and the second instance's copy reads 5 |
| **C** | one instance resolves an unknown, a stale one then writes → it stays resolved and the stale instance's refresh drops it; attempts from both count |
| **D** | a living instance's running job is not claimed; once it stops it is; two instances racing for one job → exactly one gets it |

**Still per instance, by design — stale READS, not lost writes:** the memory agent's cache, the ingress's
in-process dedup set, and the domain registry's snapshot (whose content is derived from `unified.concepts`,
so an overwritten domain document is regenerated) catch up on refresh or restart.

**The trap in measuring it.** Two objects against one store reproduce the conflict exactly — the store is
where it lives — but the second instance must hold a COPY taken before the first one's write, or there is
no stale state to conflict with. And the queue claim acts on every unowned owed row in the live table, so it
was run only when the live table owed nothing.

## Run

```
./venv_lyric/bin/python3 experiments/INSTANCES-01/experiment.py
```

Needs only the database (no full boot). Everything written is removed by id. Each run writes
`results/<UTC timestamp>.json` with a `.md` beside it.
