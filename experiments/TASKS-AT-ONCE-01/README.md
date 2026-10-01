# TASKS-AT-ONCE-01: sixty tasks at once, three per person at most

The substrate drew at most six tasks at a time (`max_parallel_tasks`, default 6). Several other ceilings sat
behind that:
- the acting cap was clamped to 16;
- the substrate's own tuning of its cap stopped raising it at 8;
- the queue authority's own budget defaulted to 5.

The queue authority is one per process, made by whoever reaches it first. A faculty that registers a recurring
job, or submits a background job, reaches it with no settings. After that, the substrate's own setting was never
put in force.

**What changed (2026-09-30):**
- **The budget is sixty.** The substrate's cap (`max_parallel_tasks`) and the queue authority's own default are
  both 60. Each person may hold three of those slots at once (`per_actor_max_tasks`). Both are set once, in the
  coordinator.
- **No lower ceiling.** A resource directive can hold the cap lower when failures are measured, never above the
  configured budget. The substrate's own tuning can raise it back only as far as that budget.
- **Put in force whoever came first.** `get_queue_authority(config)` applies settings given after the authority
  exists (`QueueAuthority.configure`). The acting budget changes only while no work job runs.
- **Deleted.** `CoordinatorConfig.max_parallel_tasks = 1` ("one task at a time") was read by nothing and said the
  opposite of what runs.

**Found by its first run, and changed with it:**
- **A lock sat on the pool it needed (the root cause).** The memory agent locks a task's memory while adding to it
  (`_pursuit_lock`), across every instance of the model. The lock lived on a connection taken from the query pool
  and held for the whole write, and the write needs that same pool. Sixty jobs added their reading at the same
  moment: all twenty connections were held by locks waiting for a second one, and nothing moved until each job timed
  out. A lock now holds a connection of its own, opened for it and closed with it
  (`DatabaseManager.advisory_lock`), so no number of locks at once can starve the pool.
- **More connections, none kept idle.** Each process's pool opens a connection when a statement needs one and closes it
  after 60 s idle (`POSTGRES_POOL_IDLE_SECONDS`). It holds none at rest, and at most 100 at once (was 5 to 20, kept
  open). The server allows 250 (was 100): two processes at full load, with room for scripts and checks.
- **A job that times out is recorded as failed.** The queue authority ended it and left its record saying "in
  progress". No one was told, and the next boot ran it again. It is now marked failed with the time it ran out at,
  and its person is told.

**What it checks**, on the running substrate in the sandbox:

| | |
|---|---|
| A | The queue authority runs sixty work jobs at once, and the substrate draws up to sixty, three per person. A size given after the authority exists is put in force, and is never changed under running work. |
| B | Twenty people ask for four jobs each, and one more person for two, through the one front door. All 82 are taken on. |
| C | Sixty jobs run at the same moment, inside the queue authority's budget, and never more are in flight. Every person holds three at once and never a fourth. A person's fourth job starts only once one of theirs has ended. The one more person's jobs wait for a slot to free. Every job ends done, with its note read, under that load. Each person is told how each of their jobs ended. |
| D | The main model's store is untouched. |

**The one stand-in:** each job first holds its slot for 10 s, as work waiting on the world does (a page to load,
a mail server to answer). Then it does its real job: reading its note through the job's tool. Without the wait,
the jobs end too fast to overlap. The substrate's own exploration is turned off for the run with its own setting
(`LYRIC_INTRINSIC_EXPLORATION_CAP=0`), so every slot counted is a person's.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/TASKS-AT-ONCE-01/experiment.py
```

It removes the messages owed to the people, by person, and the pursuit memories their turns form, by id. What it
leaves in the sandbox, named by the run's nonce:
- the people's job records in the queue's history;
- their turns' and readings' experiences in the memory agent's pool.

**What sixty at once is, and is not.** One process runs its tasks on one event loop. Sixty tasks at once means
sixty in progress together. Their waiting on the world overlaps: pages, tools, mail, the database. Their
heavy thinking takes turns on one core. More cores serve more tasks as more instances of the model. Past a
process's 100 database connections, a task waits its turn for one and is never refused.

**Runs:**
- `20260930T164812Z`, 11/14. Sixty ran at once, never a fourth per person, and the one more person waited. Then the
  first sixty deadlocked on the pool: each read its note within a second and then waited until the queue's time
  limit (225 s) ended it. The 22 after them, started a few seconds apart, finished in 13 s each. The sixty stayed
  "in progress" and their people were not told. Both causes are changed above.
- `20260930T175144Z`, **14/14**, after the changes above and the server's restart at 250 connections. Sixty ran at
  once and no person held a fourth. All 82 completed with their notes read, none timed out, and every person was told
  how each job ended. From the substrate's log: the first job began at 13:52:35.8 EDT, the first ended 13.4 s later,
  and the last ended at 13:53:37.9. That is 62 s for 82 jobs that each hold their slot 10 s; at five at once the
  holding alone takes at least 170 s. The run's own detail said "all 60 done in 22s". It measured before the last 22
  jobs had finished the work after their records said completed. The harness now waits for every job and measures
  from the first start.
