# SYSTEM-HEALTH-01 — health and recovery, alone

**Finding (2026-09-26): behaviour 18/18; six wiring findings.** One health authority (`HealthMonitor`) and one
recovery authority (`RecoveryManager`), each the instance its accessor returns. Health grades only from
evidence (no signals: no score, UNKNOWN), grades the Constitution through its own surfaces (`safety`,
`governance`), and REFUSES a name it does not know. Recovery records a failure and its history. The wait
before each recovery retry is learned.

**Fixed on the way:**
- **Two monitors.** The coordinator built its own `HealthMonitor()` / `RecoveryManager()` whenever it was not
  handed one, while main.py, the recovery manager, the guardian and the coordinator's own health read used the
  accessor's — the coordinator's copy unscoped and never initialised until main.py overwrote it. It now holds
  the accessor's instances; main.py's injection is gone.
- **Any name was HEALTHY.** A component outside `COMPONENT_MANIFEST` fell to a "generic" check that measured
  nothing and reported no issue, so it graded HEALTHY and was registered from then on — and the recovery
  manager, verifying a repair, read that as the component having recovered. It is refused now; the generic
  check is deleted (every manifest component has a real check).
- **Retry waits were a fixed table** (0/60/120/300/900/3600 s). The learning authority now chooses each wait
  (`predict_optimal_retry_delay`, Thompson sampling on expected time to recovery) and is credited with each
  retry's outcome. The reset of a recovered component also sat AFTER the all-nominal early return, so the
  last component to recover was never reset — and an `unknown` reading counted as recovered.
- **An undefined rate hid a failed reading.** The evaluator skipped every None `*_rate`; it now honours the
  check's `_record_rate` declaration (undefined = not applicable, unread = missing evidence).

**What it checks.**

| | |
|---|---|
| **A** | one health and one recovery authority, each the accessor's instance, constructed once |
| **B** | no signals → no score, UNKNOWN; the Constitution graded through `safety`; an unknown name refused and not registered; system health readable |
| **C** | a failure is handled and in the history; the tool throttle is a number; statistics readable |
| **D** | the real health tier, fed one probe component: first attempt immediate with a learned next wait; no retry before it; a retry after it; an `unknown` reading credits nothing; seen healthy, the wait before the recovering retry is credited |

**Wiring findings (called by nothing in `core/`):** health `get_component_health`, `get_health_history`,
`clear_component_health`, `reset_statistics`; recovery `register_snapshot_handler`, `clear_failure_history`.

**The trap in measuring it.** Section D feeds the tier a probe READING only; everything after it — plans, the
recovery manager, the learner — is the real path, so the probe component's retry arms are removed from the
meta-learner (memory and table) afterwards. And "the Constitution" is not a health component name: health
grades it as `safety` and `governance`.

**Open:** an escalation after five failed recoveries reaches no one — Slack is deleted, and the
queue call it makes (`add_task(description=…)`) raises TypeError, swallowed. Which channel should carry it is
undecided.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-HEALTH-01/experiment.py
```

Each run writes `results/<UTC timestamp>.json` with a `.md` beside it, reporting **behaviour** (pass/fail),
**wiring** and **completeness** findings apart (`experiments/_isolation.py`).
