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

The World Model takes it in through **self-reflection**. On a schedule, the World Model reflects over a
window of time. It reflects over what it has learned itself, and over what each instance has learned in
that window. What survives that reflection joins the World Model and appears in the next release. What does
not survive stays in the instance's store, or is dropped.

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

---

## 8. What is not built

### ⚠️ Self-reflection is the open work

**The World Model does not yet reflect on what instances have learned.** Nothing reads an instance's
`learning` store, nothing weighs what is in it, and nothing carries anything from it into the World Model.
This is the piece with nothing behind it, and until it exists the architecture in this document does not
function: instances would accumulate knowledge that never reaches anyone else.

This is the next substantial piece of work on the substrate. It needs, at minimum: what a reflection window
is, what self-reflection establishes about a piece of knowledge before it may join, what happens to
knowledge that fails, and how a tenant's training decision is read.

### Also missing

- **Development does not route.** In development the substrate keeps everything in one database and does
  not divide it into stores. This is why every instance created so far was all or nothing: either the whole
  World Model, or an empty database. Work on the model happens in development, so this is the gap that is
  felt daily.
- **No release has been cut.** An instance needs one to read.
- **An organisation's training decision is not read by anything.** The setting exists in the platform; the
  substrate does not consult it.
- **Knowledge carries no mark of origin.** No memory records which instance wrote it, so there is nothing
  to reflect on selectively and nothing to attribute.

---

## 9. Until it is built

Teaching runs against the World Model directly, with the resident stopped, because `scripts/teach.py`
starts a full substrate of its own and there must be only one at a time.

**Once this is built, teaching fires up an instance**: a process attached to a release, learning into its
own store, with what it learned reaching the World Model through reflection. That is the point of the
design, and it is the reason the separation is worth having.
