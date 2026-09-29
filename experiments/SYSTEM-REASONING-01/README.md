# SYSTEM-REASONING-01 — the reasoning faculty, alone

**Finding (2026-09-26): behaviour 8/8, no wiring or completeness findings.** One reasoning authority
(`NeuralSymbolicBridge`): the coordinator holds the instance `get_neural_bridge()` returns and it is
constructed in one place. A held `isa` question is answered from the substrate with no model call; a false
relation and a question about nothing held are refused (`substrate_refuted`), not invented. Every public
method is reached from `core/` (6 only inside their own file).

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site; every public method reached |
| **B** | a held question is affirmed from the substrate, with zero model calls |
| **C** | a false relation and a question about nothing held are refused |
| **D** | it accounts for itself: statistics, and a difficulty per reasoning kind |

**The trap in measuring it.** A refusal is read from the answer and its `reason` (`Not entailed by the premises`, `substrate_refuted`),
not from a low confidence: a low-confidence *yes* is still a yes.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-REASONING-01/experiment.py
```

Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
