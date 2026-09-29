# SYSTEM-EXECUTION-01 — the acting faculties, alone

**Finding (2026-09-26): behaviour 18/18; one wiring finding.** The rule store (`RuleStore`), the operator
bindings (`BindingRegistry`) and the tool registry. A rule is found by id and by status and an unknown id is
None; a binding is registered, found and cleared; a tool call passes the one gate, carries its judgement and
really does what it says; a tool that does not exist is refused, not invented. Wiring: the rule store's
`forget_domain` is exercised only by RECOGNISE-01/02.

**What it checks.**

| | |
|---|---|
| **A** | one authority each |
| **B** | rules: by id and status, honest about unknowns |
| **C** | bindings: registered, found, cleared |
| **D** | tools: judged, then done |

**The trap in measuring it.** The learning authority's `store` is a property returning the rule store, not a method.

## Run

```
./venv_lyric/bin/python3 experiments/SYSTEM-EXECUTION-01/experiment.py
```

Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
