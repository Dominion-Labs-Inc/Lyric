# REPLAN-02 — knocked off course, does the substrate get there anyway?

**Why.** A learned rule can stop being true of the world. When that happens mid-pursuit, the
substrate should notice from what the world does, stop trusting that rule, and still reach the goal
over what it knows that is still true. The route must start from where things actually are, not
from where the stopped route assumed they were.

**Setup.** Rooms are directories, the agent is a file, and a move is the real `move_file` tool. The
substrate holds two validated operators:

```
rooms:   HALL --> LAB           (the direct way; POLLUTED)
         HALL --> ANNEX --> LAB (the long way; intact)
```

`SBMOVE` is the one it will plan over, and the world is changed so that anything sent toward LAB
lands in ANNEX. `SBHAUL` is still true of the world. The substrate gets one goal, `SBAT(z, LAB)`, and
nothing tells it what to do at any step. Nothing is driven by hand: the repair is the pursuit's own
(`_drive_substrate_goal` plans again inside itself when a rule its route stood on loses its authority).
Until 2026-10-22 the repair was a planning engine's, reached through a dispatch drain this experiment had
to call by hand; the engine is gone. The routes the pursuit tried are read from its route intent.

**What it checks.**

| | |
|---|---|
| **Setup** | the live substrate is the registered one; both movers are validated |
| **Defeat** | it planned and acted on its own; the polluted world defeated the first route (its outcome is on the route intent, not reached) |
| **Refutation** | `SBMOVE` is refuted by the world; `SBHAUL` is untouched |
| **Recovery** | z reaches LAB; the new route is over `SBHAUL`; it starts from ANNEX, where z is, not HALL |
| **Closure** | the route intent is closed `fulfilled`, matching what it meant |

## Run

```
./venv_lyric/bin/python3 experiments/REPLAN-02/experiment.py
```

Works in a temporary sandbox, and removes its domain's rules afterwards. Each run
writes `results/<timestamp>.json` with a `.md` beside it. Runs before 2026-09-26 wrote a JSON only.

**2026-10-22: 10/10** on `lyric_dev` (`20261023T011818Z`): refuted, planned again inside the pursuit from ANNEX,
over `SBHAUL`, and the route intent closed `fulfilled`.
