# The Lyric World Model and its instances

Decided 2026-11-19. This document records what the World Model is, what an instance is, and how knowledge
moves between them. It is a statement of the architecture, not a plan of work.

---

## 1. The name

The main store is the **Lyric World Model**.

It is not "the Lyric database", not "lyric_db", not "main". `lyric_db` is the name of a PostgreSQL database
on one machine; it is an implementation detail and will not be used to refer to the model in conversation,
in documents, in log lines or in code comments.

This matters because the confusion was not cosmetic. Treating the World Model as "a database" made it sound
interchangeable with any other database, and on 18 November 2026 that produced a real failure: 497 of
English's ways of reading were taught into a separate database while the World Model received none of them,
and nothing reported it. The World Model is the knowledge. A database is where a copy of some of it is kept.

---

## 2. What an instance is

An instance of Lyric is:

1. **A runtime process.** One process running the substrate.
2. **Its own stores.** Its own `learning`, `user_context` and `runtime` databases, holding everything it
   comes to know and everything that happens inside it.
3. **Read access to a cut release of the World Model.** Frozen, read-only, and complete.

An instance is therefore never blank. It begins knowing everything the World Model knew at the release it
was cut from: the concepts, the beliefs, the grammar, what words mean, what its tools do. It then goes on
to learn things of its own, and those stay in its own stores.

**An instance is not a sandbox.** A sandbox is a place to try something without consequence. An instance is
a full Lyric doing real work for a real tenant, and what it learns is real knowledge. The separation of
stores exists so that knowledge can be examined before it joins the World Model, not so that it can be
discarded.

---

## 3. The four stores

The substrate already divides a line of the model into four stores. The division is in
`core/database/postgres_config.py` and the routing is in `core/database/unified_database_postgres.py`.

| Store | Holds | In an instance |
|---|---|---|
| `model` | The knowledge: concepts, beliefs, the grammar, word senses, what tools do. 49 tables. | A **cut release**, shared, **read-only**. Writes against it are refused and counted. |
| `learning` | What the substrate comes to remember while serving: memories hot and cold, evidence, hypotheses, experiments, known unknowns, the experience pool. 14 tables. | **The instance's own.** This is where everything it learns lives. |
| `user_context` | Each person's context. | The instance's own. |
| `runtime` | Operational state while serving. | The instance's own. |

Sixteen tables are already marked per-owner (`PER_OWNER_TABLES`), so rows belonging to different owners are
already kept apart within a store.

---

## 4. The base is a cut release

An instance reads a **numbered, frozen release** of the World Model (`<database>_model_v<N>`), not the
living model.

The reason is stability. An instance's knowledge must not change underneath it while it is working, and a
tenant must be able to say which version of Lyric they are running. A release is cut deliberately, carries
a number, and does not move.

This also means a release has to exist before an instance can be created. None has been cut yet.

---

## 5. How knowledge comes back

Everything an instance learns is written to its own `learning` store and stays there until the World Model
takes it in.

The World Model takes it in through **self-reflection**.

### There are two reflections, not one

They are different acts with different subjects, and conflating them is the mistake the current LyricOS
documentation makes.

| | Who reflects | On what | What it is for |
|---|---|---|---|
| **The instance's own reflection** | The instance | Its own day: what it did, what it learned, what it now holds | To settle and strengthen its own knowledge. Everything stays in that instance. |
| **The World Model's reflection** | The World Model | Its own learning over a window, **and each instance's learning store** | To decide what joins the World Model and appears in the next release. |

An instance reflecting on its day is complete in itself and happens whether or not the organisation permits
training. The World Model reflecting over instances is the only route by which anything leaves an instance,
and it runs only for instances whose organisation permits it.

What survives the World Model's reflection joins the World Model and appears in the next release. What does
not survive stays in the instance's store, or is dropped.

One route already carries knowledge between stores, and it is not reflection. `releases.take()` pulls a
frozen environment's learning store into development through the memory agent, with the questions it met and
could not answer and how often it recalled each memory, and marks `taken_at` so taking twice takes once. It
takes **everything, unconditionally**: it weighs nothing, rejects nothing, and never consults an
organisation's training decision. It is a transfer, not a verdict, and it exists only for staging and
production. There is no equivalent for a tenant instance.

### When reflection runs

**Reflection runs in downtime and never blocks work.**

- It starts after the instance has been idle for a period. It is not scheduled for a fixed hour, and how
  long it runs depends on the organisation, the team and how much there is to reflect on.
- **It is interruptible.** If someone begins using Lyric while reflection is running, reflection pauses
  immediately and the person is served. Nothing waits on reflection and nothing is slowed by it.
- **It resumes where it left off.** A paused reflection is not restarted and not abandoned; it continues
  from the point it stopped when downtime returns. Work already reflected on is not reflected on again.

This is the same shape as the dedicated cycle already specified for the product: review, reconcile,
validate, optimise, plan, commit, outside working hours, interruptible.

Whether an instance's knowledge is reflected on at all is the tenant's decision:

- **An organisation that permits its data to train the model.** The World Model reflects on that instance's
  learning store and may take knowledge from it.
- **An organisation that does not.** Everything that happens inside that instance stays inside its own
  stores, permanently. The World Model never reads it and never reflects on it.

This choice is a property of the organisation and is read by the reflection pass, not by anything else. An
instance's knowledge is never copied out by any other route.

---

## 6. The rule this replaces

**No instance is taught something that is not brought back.**

Until now, instances were created empty and taught in isolation, and nothing carried what they learned to
the World Model. Two things made that invisible:

- The reader fell back to reading English's grammar from a file on disk whenever it was handed none, so a
  World Model holding no grammar read exactly as well as one that held it.
- Nothing compared the two stores, and nothing recorded which instance had written a piece of knowledge.

The fallback was removed on 19 November 2026 (`83ccfa46`). `Lexicon`, `GrammarView` and `closed_uses` now
require a grammar and refuse to read without one, so a World Model that has not been taught English fails
and says so rather than quietly reading from disk.

The second half is this document: if an instance is stood up and taught, the path back is part of the same
piece of work, not something to be done afterwards.

---

## 7. What is already built

- The four-store division, and the routing of each statement to the database its tables live in.
- Read-only enforcement against a frozen release: reads are answered, table creation is checked against
  what the release holds, and every other write is refused and counted (`frozen_refusals`).
- Per-owner tables, so rows belonging to different owners are already separated inside a store.
- Release cutting: `core/database/releases.py` creates a numbered release database from development's
  structure and loads the model tables into it.
- **The reflection pass itself** (19 November 2026). The substrate reflects on a window of what it learned,
  reaches a verdict on each piece, runs only in downtime, stands down the moment a person arrives, and takes
  up where it stopped across restarts. See section 8 for what it does, and section 9 for what it does not yet reach.

---

## 8. Reflection, as it now stands

**Built 19 November 2026.** `MemoryAgent.reflect_on_what_was_learned` takes a window of what was learned,
reaches a verdict on each piece, and records the ones that need recording. Registered on the queue authority
as a resumable job (`"reflection"`, offered every 10 minutes by default).

Three steps, in order:

1. **The evidence is weighed.** `review_against_evidence` reads all 1,783,544 observations back against the
   beliefs they bear on and records, per belief, how often it has been borne out and how often genuinely
   contradicted. Evidence carrying `withdraws` is excluded: a teaching taken back is not a claim that
   failed. This pass had been written and **nothing ever called it**; reflection is what calls it.
2. **The window's knowledge is examined**, oldest first, by `(created_at, memory_id)`. Each piece gets one
   of four verdicts from what came of it: **bore out** (never contradicted), **questioned** (contradicted,
   and outweighed), **did not hold** (contradiction at least equal to support), **nothing to weigh** (no
   belief came of it — which is not a failure; a grammar row has no evidence because it is a rule).
3. **The graph is settled** — `bridge.reflect()`: decay, consistency, volatility, schema decay. This was
   previously the whole of reflection; it is now its last step.

Three properties were requirements, not conveniences:

- **It runs in downtime and never blocks.** A firing that finds the substrate in use does nothing. A firing
  that finds it quiet carries on from where the last one stopped, giving the event loop back by time and
  asking at each give-way whether a person has arrived.
- **It stands down mid-pass**, within one give-way of someone arriving, and says where it had got to.
- **Its place survives a restart.** The position is in `unified.reflections`, not on the scheduled job: a job
  object lives inside one process and a reflection over everything learned does not finish inside one. A
  partial unique index allows one unfinished reflection per subject, so a process that starts continues the
  one in hand rather than opening a second over the same window.

Only a finding is written back, under `memory_admission.reflected`, **merged** so the memory filter's own
record of what admitted the knowledge is left intact. Marking every piece "fine" would rewrite the store to
say what the reflection's own counts already say.

Measured on the World Model, 19 November 2026: of 1,441,710 memories, **1,021,531 (70.9%)** have a belief
that came of them and so can be weighed; **420,179 (29.1%)** have nothing to weigh. Of 1,022,193 beliefs,
**112** have ever been genuinely contradicted and **80** of those are contradicted at least as often as they
are borne out. So the first full reflection should find roughly 80 pieces that did not hold and 32 in
question — a small number, and the first time anything has looked.

---

## 9. What is not built

### ⚠️ What reflection still does not do

**1. The World Model does not reflect on an *instance's* learning.** `whose='own'` works. An instance's name
refuses, by name, because no release has been cut and there is no instance store to read. That refusal is
deliberate: reading nothing and reporting a reflection would be worse. Until this exists, the route by which
knowledge leaves an instance does not exist.

**2. Nothing joins anything.** The verdict today says whether a piece of knowledge held up. It does not admit
it into the World Model, because for `whose='own'` the knowledge is already there. Admission — taking a piece
from an instance's store into the World Model's, with the crossing stamped as `releases.take()` stamps its
own — is the second half and is not built.

**3. An organisation's training decision is still not read by anything.** The setting exists in the platform.
Reflection must consult it before it ever reads an instance's store, and it has nothing to consult.

**4. The instrument reaches 70.9% of knowledge.** Evidence can only speak about knowledge that produced a
belief. The other 420,179 pieces — grammar rows, word records, the shape of the language — get "nothing to
weigh", which is honest but says nothing. For taught language knowledge the real test is different and
already possible: **can the reader still read back what it was taught?** That is the next instrument, and it
is the one that matters for the case this architecture was built for, because a teaching instance's
knowledge is exactly the kind reflection currently cannot speak about.

**5. Knowledge carries no mark of which instance wrote it.** It carries a date stamp (`created_at`, on all
1,441,710) and a return address (`metadata.origin` on all of them; `producer` on 1,130,017; `source_id` on
1,130,102). What it does not say is which Lyric wrote it — which does not matter while an instance's
knowledge is a separate database, and matters the moment knowledge crosses between them. So the mark belongs
at the crossing, with the admission, not on rows that never moved.

### ⚠️ The LyricOS documentation describes this wrongly

The LyricOS documentation currently describes **an organisation's instance** as the thing that performs
self-reflection, and stops there. That is half of it. The World Model is also a reflector, and it is the
one whose reflection decides what knowledge becomes shared. The instance reflects on its own day to settle
what it learned; the World Model reflects over instances to take knowledge in.

Those pages need rewriting once the mechanism exists, and the rewrite needs to go deeper than the current
text: what each reflection examines, what each one may conclude, and what an organisation's training
decision changes about the second one.

### Also missing

- **Development does not route.** In development the substrate keeps everything in one database and does
  not divide it into stores. This is why every instance created so far was all or nothing: either the whole
  World Model, or an empty database. Work on the model happens in development, so this is the gap that is
  felt daily.
- **No release has been cut.** An instance needs one to read.
- **An organisation's training decision is not read by anything.** The setting exists in the platform; the
  substrate does not consult it.
- **Knowledge carries no mark of which instance wrote it** — see point 5 above, which says where that mark
  belongs and why it is not on every row.

---

## 10. Teaching

`scripts/teach.py` starts a full substrate of its own. **That is correct and stays.** Teaching is an
instance: a process that learns, with its own life and its own end.

Two things have to be true about it, and only the first is true today.

1. **It must be attached to a real store, not an empty one.** A bare teaching run resolves to the World
   Model's own database from `.env.postgres`, so it teaches the World Model directly. It only became a
   problem when a run was given a different database by its environment, which is how one store came to
   hold 497 ways of reading and the World Model none.
2. **The World Model must know an instance was taught, and must reflect on what it learned.** Nothing
   records that a teaching instance existed, and nothing reflects on what it produced. Until that is built,
   a teaching run is only safe because it happens to write into the World Model directly.

Until self-reflection exists, teaching runs with the resident stopped, because two substrates must not
serve one store at once and neither one can see the other.

**Once self-reflection exists, teaching fires up an instance**: a process attached to a release, learning
into its own store, announced to the World Model, with what it learned reaching the World Model through
reflection. That is the point of the design and the reason the separation is worth having.
