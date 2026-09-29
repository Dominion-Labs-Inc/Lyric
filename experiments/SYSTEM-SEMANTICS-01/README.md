# SYSTEM-SEMANTICS-01 — the semantic write door, alone

**Finding (2026-09-26): behaviour 9/9, no findings.** One door for what the substrate is told
(`CognitiveIngress`). A relation is admitted once, a repeat is already present, a term that names nothing is
refused, and a conditional becomes a held rule the store returns. The door's shape test is now one function,
`shape_proposition`, used by the fact path, each clause of a conditional, and every user's scoped telling
(which used to skip it — see SYSTEM-CONVERSATION-01).

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site |
| **B** | a relation enters once; the repeat is `already_present` |
| **C** | what cannot be represented is refused, with the reason |
| **D** | a conditional is held as a rule, once |

**The trap in measuring it.** The run used to leave its evidence envelopes behind: concept rows were removed by name, but the envelopes
(and the evidence rows citing them on shared concepts) were not. Cleanup now removes every envelope stamped
with this experiment's provenance and every row that cites one.

## Run

```
./venv_torin/bin/python3 experiments/SYSTEM-SEMANTICS-01/experiment.py
```

Everything written is removed by id. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
