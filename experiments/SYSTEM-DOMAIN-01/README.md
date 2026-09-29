# SYSTEM-DOMAIN-01 — the domain authority, alone

**Finding (2026-09-26): behaviour 14/14; one wiring finding.** One domain authority
(`UniversalDomainMaster`). A domain comes into existence once, competence evidence moves its progress, and a
gap is detected against what it holds. Wiring: `knowledge_sparsity_map` is called by nothing.

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site |
| **B** | a domain comes into existence once |
| **C** | competence evidence moves progress |
| **D** | it knows what it does not know: a gap is detected |

**The trap in measuring it.** Learning progress is a SIGNED rate of competence change, not a level: a fresh domain with too little
history reads `OPTIMISTIC_PROGRESS` (1.0) by design, so "progress = 1.0" on a new domain is not a bug.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-DOMAIN-01/experiment.py
```

The probe domain is removed afterwards. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
