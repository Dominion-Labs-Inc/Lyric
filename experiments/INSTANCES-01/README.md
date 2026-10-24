# INSTANCES-01 — many instances of the model, one store: no instance undoes another

**Finding (2026-10-23): 20/20 — one queue.** An instance ran only the work it had queued itself; another took it
over only once it had stopped, so every job ran in the event loop of the process that queued it, and a page being
read there held up all of them. Now (`QueueAuthority.get_next_task`):
- starting a job claims it (`QueuePersistence.claim_start`): it starts only if it is this instance's own, or still
  waiting and held by no other living instance; a copy another instance took is let go of, and its status is read
  from the store;
- with nothing of its own ready, an instance with room takes the highest-priority waiting job in the table,
  whichever instance queued it, in one statement (`claim_waiting`, `FOR UPDATE SKIP LOCKED`), skipping a person at
  their cap;
- a copy that is no longer this instance's writes nothing (`upsert` has `claim_new`'s owner rule).

**F (2026-10-23): 22/22 — workers.** A worker's word reaches the Lyric it works for through the store
(`SELF_CHANNEL`), and a message a worker owes a person is said by the Lyric their front end listens to, kept in
their conversation (`20261024T004818Z`). Its first run failed on a race the run found: a front end that starts
listening takes what already waits for its person (`on_message`), took the worker's message first, and the
message was then not kept in the conversation; it is kept now whoever delivered it, and F lets that first delivery
finish before the worker speaks. 0 of 30 early deliveries in a probe of F as run.

**E** checks each, and two real queue authorities: the one with nothing of its own draws the job the other
queued, the other lets it go, and the result is read where it was queued (`20261024T001439Z`, lyric_dev). E runs
only when the live table holds no waiting work but its own: `claim_waiting` takes the highest-priority waiting job
in the whole table. D's first claim, as before, re-owns the live table's restorable rows (three BLOCKED jobs of
stopped instances on lyric_dev, owned again by a stopped probe instance: restorable as before).


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
