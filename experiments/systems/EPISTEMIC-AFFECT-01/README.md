# EPISTEMIC-AFFECT-01 — changes in knowledge become feeling

**What it tests.** When a belief moves, from any source, the change reaches appraisal through the
reasoning authority:
1. `EpistemicEngine.interpret_drift()`
2. `NeuralSymbolicBridge.epistemic_affect_signal()`
3. `coord.integrate_epistemic_affect()`
4. appraisal: confidence rises when uncertainty falls; doubt and curiosity rise when it grows.

The channel runs one way only: the feeling never rewrites the evidence it read.

**Run** (from the TorinAI folder):

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 experiments/systems/EPISTEMIC-AFFECT-01/experiment.py
```

**Results.** `last_run.txt` holds the output of a run on 2026-09-09: PASS. It is not a structured record.

**2026-09-28: run again, 5/5 PASS** (sandbox). Two premises had gone stale since 09-09:
- `perceive` returns a `PerceptJudged`, not a dict, so the claim is read from its one claim (`d.claims[0].claim`);
- the boot now primes the drift baseline (`core/main.py`), so the first drain in a process reports what moved since
  boot. Step 0 checks that the boot primed it, then drains to move the baseline to now, before this run's teaching.

The perception here is the substrate's own (`origin=Origin.own(...)`), as `perceive` now requires whose it is.
