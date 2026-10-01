# RULE-AUTHORITY-01 — 1,000 hidden worlds: does a learned rule get authority only when it should?

**What it tests.** Whether a learned operator gains the authority to act only when independent
evidence has seen it work and nothing it applies to contradicts it, at a scale no hand-written
suite reaches.

Each world hides one true rule: an act `ZIM(x, y)` produces `RAN(x, y)` iff a hidden subset
(1 to 4) of six candidate conditions holds, sometimes consuming one of them. The world decides
every outcome; the generator only chooses which situations to show (2 to 5 successes; near-miss
failures covering none, about half, or all hidden conditions; 0 to 2 failures the right rule says
nothing about; one still world; in a quarter of worlds a late near-miss for an uncovered
condition; shuffled arrival). After **every** arrival the learner's real authority step
(`UnifiedLearningSystem._judge_signature`: re-judge, hold out, induce, record, validate) runs.
Every rule left executable is scored against the world's truth over all 64 situations.

An independent oracle classifies each world by what the learner's own basis determines: it
enumerates every well-formed conjunction of the six conditions and the act consistent with the
shown evidence and keeps the minimal ones (`determined`, `ambiguous`, `pins_other_rule`).

**Run** (sandbox only; every world's domain is removed after it runs):

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/RULE-AUTHORITY-01/experiment.py --worlds 1000 --seed 20260930
```

**Checks, declared before the run.**

| | check |
|---|---|
| C1 | no executable rule is contradicted by any demonstration of its act |
| C2 | every executable rule was validated on a held-out success |
| C3 | no executable rule in a world shown only 2 successes |
| C4 | determined worlds: no executable rule authorizes an act the world refuses |
| C5 | determined worlds: no executable rule predicts the wrong effect |
| C6 | at least 95% of determined worlds end with an executable rule |
| C7 | ambiguous worlds: no executable rule |

**Results.**

- 2026-10-01 (`results/20261001T005243Z.json`, per-world records `..._worlds.json`): **7/7** over
  1,000 worlds in 27 s. 5,805 demonstrations, 5,805 authority judgements, 418 executable rules.
  Determined 250/250 ended with the correct operator; ambiguous 0/469 ended with any operator; 257
  two-success worlds, 0 executable rules; 269 rules lost authority to evidence that arrived after
  they were validated. 168 worlds ended with an over-broad operator the evidence licensed (62 of
  them shown no failure at all): measured, not a failure; a rule is as general as what it was
  shown, and runtime re-observation is what catches the rest.
- Earlier runs on 2026-10-01, kept because they changed the instrument or the code:
  - 20 worlds, 5/6 (C6 1/9): the generator's notion of "determined" ignored incidental features
    shared by every success; the learner's "multiple hypotheses" was right. The oracle was added.
  - 40 worlds: holding back the latest FAILURE as well as the latest success removed the
    counterexample that forced a precondition, so determined worlds ended with no operator. The
    learner now holds back only the latest success (failures arriving later are answered by
    `RuleStore.rejudge`).
  - 40 worlds: two "determined" worlds the learner called ambiguous: its rival "the effect follows
    without the act" was real. The oracle now treats the act as a literal.
  - 1,000 worlds, 6/7 (C7 3/469): the oracle counted rivals such as `SUN(y) → RAN(x, y)`, which
    leave `x` unbound and are not rules the language can express. Amended to well-formed
    hypotheses only. No check or threshold was changed.
