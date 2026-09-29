# SELFSTATE-01 — does KNOWING feed self-state, or only DOING?

**What it found.** The substrate's appraisal was fed exclusively by task outcomes.
Teaching it 15 facts on a live substrate moved **0 of 13** core variables; neither the
directive nor the acceptance band changed. `integrate_epistemic_affect()` — the one thing
that folds knowledge movement into feeling — had a single caller, `_react_affect`,
registered for `TASK_COMPLETED` alone, while its own docstring says the signal is read
*"from any source: perception, teaching, reasoning"*.

The authority underneath worked the whole time. Teaching produces
`information_gain 1.0 · uncertainty_reduction 1.0 · mutation_count 15`. Nothing asked.

**Why AFFECT-WIRING-01 could not catch it.** That experiment builds an `AppraisalState`
by hand and checks that pressures reach the directive — which they do. The break was
upstream of anything a constructed state can show. So this one runs a LIVE substrate and
teaches it, and every check is about what the substrate does to itself.

## The five properties

| | |
|---|---|
| **A** | the drift baseline is primed AT BOOT, not by whoever asks first |
| **B** | `epistemic_affect` is on the queue authority's cadence |
| **C** | what the substrate comes to KNOW moves its self-state |
| **D** | self-state reaches the behaviour the acting loop consumes |
| **E** | what needs a task stays UNMEASURED — no fabricated competence |

**Check E is the one to read carefully.** Appraisal's `competence` is task SUCCESS RATE —
DO-competence — while teaching moves maturity, which is KNOW. The credit invariant forbids
crossing them, so `competence`, `progress`, `agency`, `integrity`, `goal_congruence` and
`controllability` staying `None` through a teaching run is **correct**. E exists to stop
anyone "fixing" that by inventing a number. Self-state during teaching is four variables,
and that is the right number.

## Measuring this is a trap

`interpret_drift` is a stateful **drain**: it reports what moved since it was last asked
and advances its snapshot. Three ways to get a confident wrong answer, all of which
happened while this was being investigated:

1. Its **first call primes** and returns `[]` — read as "nothing moved".
2. Calling `bridge.epistemic_affect_signal()` to inspect the signal **consumes** it, so
   the integrator that runs next sees nothing and looks broken.
3. Teaching everything **before the first drain** gets absorbed as baseline.

Measure through the door the substrate itself uses, and never twice.

## Cadence

The run retunes `epistemic_affect` and `motivation_refresh` to 5s through
`QueueAuthority.reschedule` — the substrate's own API for retiming its periodic work, not
a test hook. At the production 60s cadence the same run takes ~4 minutes.

Periodic is the right *shape*, not a compromise: `interpret_drift` walks the whole belief
graph — measured at **380 ms for 128,647 beliefs, 0.63% of a core at 60s** — so hanging it
on `EVIDENCE_ADMITTED` would walk the graph once per taught fact. `TASK_COMPLETED` still
fires it immediately, so a task outcome is still felt at once.

## Run

```
./venv_lyric/bin/python3 experiments/SELFSTATE-01/experiment.py
```

Each run writes a structured record to `results/<timestamp>.json`.
