# RELEASE-01: the model is released, served frozen, and replaced only by a newer release

**Finding (2026-09-27, run `20260927T171154Z`, 29/29).**
- **The cut.** Release 1 was cut from the sandbox after the SHAPES-LEARN-01 lesson was taught there: 10,909 rows,
  with the code it was cut with recorded (263 files). PostgreSQL itself refuses a write to it.
- **Refused as it should be.** Nothing reached production without staging. A tampered release (one row added) and a
  release registered with other code were each refused at start-up.
- **Serving.** Production served it through boot, one person, a memory of its own, a recall, memory maintenance and
  60 s idle, with nothing refused: no misrouted statement, and no attempt to change the release. 56 table-creation
  statements were checked against the release instead of run.
- **Where things landed.** The person's fact and memory went to user context, and her context answered her. The
  substrate's own memory went to the learning store. The recall was counted in runtime.
- **Its own learning.** Its own fact, a new belief and a moved belief were each refused with the reason, and none
  of its 267 beliefs moved.
- **Afterwards.** The release was byte-for-byte what was cut.
- **Development took what production kept.** It took the memory through the memory agent, which merged it into a
  memory it already held, and the recall as an access count. Taking again took nothing.
- **The next release.** Release 2 carried the memory, was promoted, and retired release 1. Rolling back put release
  1 back in production, and both stayed intact.
- **The main line** was untouched.

**What the first runs found and what changed.** The frozen release refused, and so exposed, two writes the substrate
made at every start:
- **The tool projection.** Boot wrote every tool's projection into the model: 344 writes. The release already holds
  it (it was cut with the same code), so a frozen start no longer projects.
- **Concept encoding.** The boot's background encoding tried to write vectors for concepts cut before they were
  encoded. A cut is now refused while any concept is unencoded; the development phase finishes its encoding before
  it stops; a frozen release is never encoded.

The run is on the sandbox line (`lyric_dev`). The experiment process is development. Each staging or production
process runs separately (`serve.py`), because a process is one environment for its whole life.

## What it checks

| Part | Check |
|---|---|
| A. Cut | release 1 is cut from development's model and registered as a candidate. It is read-only in PostgreSQL itself (a direct write is refused there), its content, schema and code are recorded, and it holds no person's memory |
| B. Staged | a candidate cannot be promoted, and staging will not serve one. Once staged, it serves |
| C. Tamper | one row added to the release is found by its checksum, and staging will not serve it. With the row taken out again, the release is intact and served |
| D. Code | a release registered as cut with other code is not served |
| E. Served | promoted, production serves release 1 through boot, one person, a memory of its own, a recall of a release memory, memory maintenance, and 60 s idle. Nothing is refused: no misrouted statement, and no attempt to change the release. The person's fact and memory are in user context, and her context answers her. Its own memory goes to the learning store. The recall is counted in runtime. Then, on purpose, it tries to learn a fact of its own and to form and move a belief: each is refused with the reason, and no belief moves |
| F. Frozen | after serving, release 1 matches its checksum exactly |
| G. Take | development takes every memory production kept (through the memory agent, which may merge one into a memory it already holds) and its recalls as access counts. Taking again takes nothing |
| H. Next | release 2 carries what production kept. Staged and promoted, it retires release 1. Production serves 2 and will not serve 1 |
| I. Rollback | production goes back to release 1 and serves it. Both releases are intact |
| J. Main | the main line (`lyric_db`) is untouched, and no main-line release was made |

## Run

```
./venv_lyric/bin/python3 experiments/RELEASE-01/experiment.py
```

It empties the sandbox line first (`scripts/reset_dev_store.py`). The development phase is `experiments/_develop.py`:
it starts the substrate in development, teaches the SHAPES-LEARN-01 lesson, and stores one memory of its own. Do not
change `core/` while it runs: a release records the code it was cut with, and a process running other code will not
serve it.
