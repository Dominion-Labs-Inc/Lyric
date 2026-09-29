# SYSTEM-SELF-01 — the self's faculties, alone

**Finding (2026-09-26): behaviour 17/17; one wiring finding.** Appraisal (`AppraisalSystem`), the
behaviour arbiter (`BehaviorArbiter`) and intrinsic motivation (`IntrinsicMotivationSystem`) are each one
authority the coordinator holds. Appraisal turns measured signals into a disposition it can account for, the
arbiter decides from that disposition and real capacity, and motivation reports a mood, a valence and a
state. Wiring: motivation's `get_skill_recommendations` is called by nothing.

**What it checks.**

| | |
|---|---|
| **A** | one authority each; one construction site each |
| **B** | appraisal: measured signals become an accountable disposition |
| **C** | the arbiter decides from disposition and capacity |
| **D** | motivation reports itself |

**The trap in measuring it.** An appraisal's `risk_level` is a label (`low` … `critical`), not a number; and the arbiter's capacity
gates `should_explore` and `max_goals`, not the mode. Both were harness mistakes in the first version.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-SELF-01/experiment.py
```

Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
