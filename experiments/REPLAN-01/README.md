# REPLAN-01 — does a refuted rule's goal actually get a new route?

**What it tests.** The near half of this edge was already proven: a runtime contradiction refutes the rule,
and the refutation is written durably. The far half is the goal: a pursuit standing on a rule the world just
refuted must not stop at the failed step with its goal still reading `active`.

On a LIVE substrate, nothing here calls the repair. The refutation is caused by acting in a real world (a
room that refuses the move its rule predicts), and the question is whether the pursuit that was acting comes
out the other side having planned again over what is still validated.

```
act in a world that refuses the move
  -> rule loses VALIDATED                          (rule store)
  -> RuleAuthorityChanged written durably
  -> the walk stops                                (_pursue_proved_route)
  -> the same pursuit plans again over what is left (_drive_substrate_goal)
```

| Section | What it establishes |
|---|---|
| A | there is one pursuer of a goal: no repair path beside the drive, no route-withdrawn event |
| B | the pursuit proved a route and walked it; the world contradicted the rule; the rule lost VALIDATED |
| C | the same pursuit planned again, over what is still validated (nothing, here), ended saying so, closed the stopped route as not reached, and forced nothing |
| D | negative controls: a pursuit whose rules hold in an unchanged world is not planned again; a goal whose world cannot be observed is not planned at all, and a stopped walk there is not planned again on a world nobody read |

**Until 2026-10-22** the repair was a planning engine's (`replan_withdrawn_goals`, reached through a
route-withdrawn event when its dispatcher drained the refutation). It pursued goals outside the task that
owned them. The engine was dissolved; the repair is the drive's own, inside the one pursuit. That a repaired
route is carried out over an operator that survived is REPLAN-02's measurement.

**Run** (from the Lyric folder; boots the full system on `lyric_dev`):

```
./venv_lyric/bin/python3 experiments/REPLAN-01/experiment.py
```

Works in temporary sandboxes and removes its domains' rules afterwards. Each run writes
`results/<UTC timestamp>.json` with a `.md` beside it.

**2026-10-22: 12/12** on `lyric_dev` (`20261023T011934Z`).
