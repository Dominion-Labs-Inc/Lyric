# DOM-KG-01 — a knowledge gap versus a competence gap

**What it tests.** Whether the domain system tells "I know little about X" (a declarative gap) apart from
"I cannot produce X" (a missing operator), inside a mature domain, and keeps the two separate.
- **H1:** a concept gap and an operator gap are told apart by structure.
- **H2:** a concept gap escalates (acquire the concept); an operator gap goes to operator learning.
- **H3:** teaching raises knowledge coverage but not operator competence.
- **H4:** an unanswerable question inside the domain registers as a known unknown, without touching
  competence and without false gaps.
- **H5** (in the result file): the gap becomes an exploration target and then an acquisition goal.

Paper: `docs/design/TR-2026-09_domain_knowledge_gaps.md`.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/DOM-KG-01/experiment.py
```

**Results.** `result.json`, which each run overwrites. Latest: 2026-09-13, all 16 checks pass
(H1 to H5).
