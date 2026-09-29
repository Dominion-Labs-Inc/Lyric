# MOTIVATION-CLOSEDLOOP-01 — does closing one pursuit change the next?

**What it tests.** Two competence beliefs are created in memory and appear as capability-frontier
pursuits. One of them is selected and given real positive competence evidence through `update_belief`.
The experiment then checks that:
- that belief's uncertainty falls;
- it leaves the unstable set and the pursuit ranking;
- the other belief becomes the next pursuit.

Nothing is written to the database.

**Scope.** This shows that the loop responds to a real competence update. It does not show the substrate
carrying out a task that produces that evidence; a direct evidence update stands in for that step.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/MOTIVATION-CLOSEDLOOP-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
**2026-09-28: 11/11.** Its stand-in self now carries the real constitution: choosing a pursuit asks it which way the substrate bears toward each subject, which the stand-in lacked since that was added.

