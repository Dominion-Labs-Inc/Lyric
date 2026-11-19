# Releases of the Lyric World Model

How a version of the model is cut, checked, served, replaced and rolled back, and how what a served release
learned is brought back. The mechanism is `core/database/releases.py`; the interface is
`scripts/release.py`.

Written 19 November 2026. **No release has been cut yet**, so everything below describes a mechanism that is
built and unused. Section 9 says exactly where things stand.

---

## 1. What a release is

A release is a **numbered, frozen, read-only copy of the model** in a database of its own.

The model is taught in **development**, which is the only place it changes. Staging and production never
teach: they serve a release. An instance reads a release rather than the living World Model, for two reasons:

- **An instance's knowledge must not change underneath it while it is working.** A release is cut once and
  does not move.
- **A tenant must be able to say which version of Lyric they are running**, and have that mean something
  precise: a number, a checksum, and the code it was cut with.

A release carries the **model** store only — the knowledge: concepts, beliefs, the grammar, word senses, what
tools do. It does not carry anybody's context, and it does not carry what the substrate remembered while
serving. Those live in each environment's own databases, which outlive the release.

---

## 2. The names

Everything is named from the **development database**, which is what `POSTGRES_DATABASE` is set to. That is
how a sandbox line can never reach the main line's releases.

| | Name | Holds |
|---|---|---|
| The living model | `lyric_db` | Development. The World Model, where teaching happens. |
| A release | `lyric_db_model_v3` | Release 3 of the model. Read-only at the database level. |
| The registry | `lyric_db_model_registry` | Every release of this line, and every change of status. |
| An environment's own stores | `lyric_db_production_runtime`, `lyric_db_production_user_context`, `lyric_db_production_learning` | Operational state, people's context, and what it remembered while serving. |

The sandbox line is `lyric_dev`, and its releases would be `lyric_dev_model_v1` and so on, in a registry of
its own.

---

## 3. Version numbers are assigned, not chosen

**You do not set a version number.** `cut` reads the registry and takes the next integer:

```sql
SELECT coalesce(max(version), 0) + 1 FROM releases
```

So the first release is `v1`, the next `v2`, and a number is never reused or skipped. There is no way to cut
"v5" out of order, and no way to re-cut a number — a second cut is a new, higher number, even if nothing
changed in between.

What you **do** choose is **which release each environment serves**. That is what `stage`, `promote` and
`rollback` change, and it is recorded in the registry rather than in a file or a flag.

A serving process is told which release it serves by its environment:

```
LYRIC_ENVIRONMENT=production
LYRIC_RELEASE=3
POSTGRES_DATABASE=lyric_db
```

`LYRIC_RELEASE` is required for staging and production and **refused in development**, which serves no
release. Development is also the default, so a process with neither variable set is a development process.

Two rules the registry enforces with partial unique indexes, so they cannot be broken even by two people
working at once:

- **At most one release is in staging.**
- **At most one release is in production.**

---

## 4. The commands

All of them run **from development** and refuse from a frozen environment:

```
./venv_lyric/bin/python3 scripts/release.py list
./venv_lyric/bin/python3 scripts/release.py cut [--notes TEXT]
./venv_lyric/bin/python3 scripts/release.py verify N
./venv_lyric/bin/python3 scripts/release.py stage N
./venv_lyric/bin/python3 scripts/release.py promote N
./venv_lyric/bin/python3 scripts/release.py rollback [--to N]
./venv_lyric/bin/python3 scripts/release.py take {staging,production}
```

### The four statuses

A release moves through them in one direction, except for rollback:

```
candidate ──stage──> staging ──promote──> production ──replaced──> retired
     ^                   │                     │
     └──another staged───┘                     └──rollback──> (a release it served before)
```

- **candidate** — cut, checked, serving nothing.
- **staging** — what staging serves, exactly as production would.
- **production** — what production serves.
- **retired** — replaced or rolled back from. **Kept intact**, never deleted, which is what makes a rollback
  possible at all.

---

## 5. Cutting a release

```
./venv_lyric/bin/python3 scripts/release.py cut --notes "the grammar's crossing licence and the four new rows"
```

What it does, in order:

1. **Takes the code's identity** — a SHA-256 over every `core/**/*.py` (path and content), plus the git commit
   it sits on and how many files differ from it. The **hash** is what gets compared later, not the commit,
   because uncommitted changes are code too.
2. **Refuses if development's encoding is unfinished.** A concept with no `embedding_model` has no vectors, so
   it could never be found by meaning where the release is served. A release cannot encode what it lacks.
3. **Creates `<database>_model_v<N>`** from development's structure and keeps only the model store's tables.
4. **Copies the rows** — in binary, with triggers off, and for tables that also hold people's rows, only the
   substrate's own.
5. **Replays every sequence's position**, so a release does not hand out ids development has already used.
6. **Checks it holds together**, and refuses if any of these is true:
   - **dangling references** — a link to a row that was not carried;
   - **people's memories** — any memory whose owner is not the substrate;
   - **beliefs about people's memories** — a belief that would point into context the release does not hold.
   On a refusal the database is **left in place, unregistered**, for inspection. Nothing is cleaned up behind
   your back.
7. **Sets the database read-only** (`default_transaction_read_only = on`).
8. **Registers it as a candidate**, with both checksums, the code identity, and per-table row counts.

### What the registry records per release

| Column | Why it is there |
|---|---|
| `version`, `database`, `cut_from`, `cut_at` | Which release this is and where it came from. |
| `code_identity`, `code_files`, `code_commit`, `code_uncommitted` | The code it was cut with. A release and the code that reads it must match. |
| `content_checksum`, `schema_checksum` | That the release has not changed since it was cut. |
| `row_counts` | What it holds, per table. |
| `status`, `status_at`, `notes` | What it serves, since when, and why it was cut. |

`release_events` records every status change with its reason, which is what `rollback` reads to find out
where production has been.

---

## 6. Checking a release

```
./venv_lyric/bin/python3 scripts/release.py verify 3
```

Exits 0 if intact, 1 if not. It checks four things:

- the release is **registered**;
- its database **exists**;
- it is **read-only**;
- **both checksums match** what it was cut with.

It also reports `same_code` — whether the code now present is the code it was cut with. **That is not part of
`intact`**, deliberately: a release can be perfectly sound while you happen to be sitting on different code.

`verify_serving` is the stricter form, and it runs **inside a staging or production process before it serves
anything**. It requires everything `verify` requires, and three more:

- the release is registered **for this environment** (staging serves the staging release, production the
  production one);
- it **was cut with the code now running**;
- this environment's own `runtime`, `user_context` and `learning` databases **exist**.

If any check fails the process **does not start**, and the error names every failure. A frozen environment
never serves a release it cannot account for.

---

## 7. Staging, promoting, rolling back

```
./venv_lyric/bin/python3 scripts/release.py stage 3
./venv_lyric/bin/python3 scripts/release.py promote 3
./venv_lyric/bin/python3 scripts/release.py rollback
./venv_lyric/bin/python3 scripts/release.py rollback --to 2
```

Each one verifies the release first and refuses if it is not intact.

- **`stage N`** — only a **candidate** may be staged. Whatever was in staging goes back to being a candidate.
  Also creates staging's own three databases if they do not exist; an existing one is left exactly as it is,
  because what an environment holds outlives the release it serves.
- **`promote N`** — the release **must be the one in staging**. Nothing reaches production without having been
  staged, and there is no flag to skip it. The release production served before is retired and kept.
- **`rollback`** — puts production back on the release it served before. `--to N` names one instead, and it
  must be a release **production has actually served**: a release reaches production by promotion, never by
  rollback.

**Changing the registry does not move a running process.** A serving process read its release at start and
checked it there. After `promote` or `rollback`, restart the serving process so it comes up on the release now
registered for its environment — and it will refuse to start if that release is not sound.

---

## 8. Bringing back what a release learned

```
./venv_lyric/bin/python3 scripts/release.py take production
```

A serving environment writes everything it comes to know into its **own** `learning` database, never into the
release. `take` brings that into development:

- **what it remembered**, through the memory agent — the normal path, so development learns from it as it
  learns from anything, rather than having rows pushed into its tables;
- **the questions it met and could not answer**, joined to development's own open questions;
- **how often it recalled each memory of its release**, added to those memories' access counts here.

Each memory is marked `taken_at` in the environment's own store as it is taken, so **taking twice takes
once**. The mark is on the source side because a taken memory may merge into one development already holds,
which means development cannot be asked whether it has it.

**`take` is a transfer, not a judgement.** It weighs nothing, rejects nothing, and does not consult an
organisation's training decision. What decides whether knowledge is sound is reflection
([world-model-and-instances.md](world-model-and-instances.md) §8), and the two are not yet connected: there
is no equivalent of `take` for a tenant instance, and nothing reads a training decision. Until that exists,
`take` is for bringing a staging or production environment's own learning home.

---

## 9. Where this stands today

Measured 19 November 2026 against `lyric_db`:

| | |
|---|---|
| Releases cut | **none** |
| `lyric_db_model_registry` | **does not exist** — the first `cut` creates it |
| Databases on the line | `lyric_db` (10 GB), `lyric_dev` (32 MB) |
| Concepts not yet encoded | **0 of 117,294** — this gate would pass |
| People's memories in the model tables | **0** — this gate would pass |

So a first cut is not blocked by anything in the data. What it is waiting on is a decision that the model is
at a point worth numbering.

Two things that need saying plainly:

- **Development does not divide into stores.** In development everything lives in one database. The release
  machinery reads `tables_of("model")` to decide what to carry, so a cut is correct regardless — but the
  separation an instance depends on is only real in a frozen environment.
- **Nothing can be an instance until a release exists.** An instance reads a cut release, so the whole
  architecture in [world-model-and-instances.md](world-model-and-instances.md) waits on `cut` being run once.
  Reflection refuses to reflect on an instance for exactly this reason, and says so by name.

---

## 10. A first release, start to finish

```
# 1. Nothing exists yet.
./venv_lyric/bin/python3 scripts/release.py list

# 2. Stop teaching, let any encoding finish, then cut. Creates the registry and lyric_db_model_v1.
./lyric-stop
./venv_lyric/bin/python3 scripts/release.py cut --notes "first release"

# 3. Read what it holds, and check it against its own registration.
./venv_lyric/bin/python3 scripts/release.py verify 1

# 4. Serve it in staging. Creates staging's own three databases.
./venv_lyric/bin/python3 scripts/release.py stage 1

# 5. Start a process on it. It checks the release before it serves anything.
LYRIC_ENVIRONMENT=staging LYRIC_RELEASE=1 POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 -m core.main

# 6. Once it has been exercised, promote the same release to production.
./venv_lyric/bin/python3 scripts/release.py promote 1

# 7. Later, bring what it learned while serving back into development.
./venv_lyric/bin/python3 scripts/release.py take production
```

Teaching runs with the resident stopped, and a cut should be taken with nothing writing to development, so
the checksums describe a store that is not moving underneath them.
