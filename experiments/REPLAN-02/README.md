# REPLAN-02 — knocked off course, does the substrate get there anyway?

**Why.** A learned rule can stop being true of the world. When that happens mid-pursuit, the
substrate should notice from what the world does, stop trusting that rule, and still reach the goal
over what it knows that is still true. The route must start from where things actually are, not
from where the withdrawn plan assumed they were.

**Setup.** Rooms are directories, the agent is a file, and a move is the real `move_file` tool. The
substrate holds two validated operators:

```
rooms:   HALL --> LAB           (the direct way; POLLUTED)
         HALL --> ANNEX --> LAB (the long way; intact)
```

`SBMOVE` is the one it will plan over, and the world is changed so that anything sent toward LAB
lands in ANNEX. `SBHAUL` is still true of the world. The substrate gets one goal, `SBAT(z, LAB)`, and
nothing tells it what to do at any step. The one hand-driven call is the dispatch drain
(`get_next_tasks`), because that seam has no production caller.

**What it checks.**

| | |
|---|---|
| **Setup** | the live substrate is the registered one; both movers are validated |
| **Defeat** | it planned and acted on its own; the polluted world put z in ANNEX; it did not claim success |
| **Refutation** | `SBMOVE` is refuted by the world; `SBHAUL` is untouched |
| **Recovery** | z reaches LAB; the new route is over `SBHAUL`; it starts from ANNEX, where z is, not HALL |
| **Closure** | the replanned pursuit's intent carries a reconciled outcome |

## Run

```
./venv_lyric/bin/python3 experiments/REPLAN-02/experiment.py
```

Works in a temporary sandbox, and removes its domain's rules, plans and goals afterwards. Each run
writes `results/<timestamp>.json` with a `.md` beside it. Runs before 2026-09-26 wrote a JSON only.
