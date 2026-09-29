# RULE-EVIDENCE-01 — can a rule say how sure it is, and does the act carry it?

**What it found.** Two defects, both in `core/learning/rule_store.py`, and one of them
made the other invisible.

**The counts were stale.** `_refresh_root_counts` had exactly **one** caller — the
fingerprint-reuse branch of `record_induction`. Validation attached its evidence and did
not recount. Runtime confirmation and contradiction attached theirs and did not recount.
Measured on the live store:

| rule | its own `detail` said | its count said |
|---|---|---|
| `warehouse transfer` | *"confirmed by 5 independent observation(s)"* | `positive_root_count = 0` |
| `kite17 move` | confirmed by the world **133** times | `2` |

**The counts meant two opposite things.** An INDUCTION counterexample — a case the rule
was built to EXCLUDE, which is what makes it discriminative rather than vacuous — was
stored `supports=False`, identically to a runtime CONTRADICTION, which means the rule is
wrong. One number, both meanings. Anyone reading it misread it, including the author of
this experiment, who reported that every executable rule had "more evidence against than
for". None of them did.

**Why it mattered.** `IntrinsicMotivationSystem._operator_confidence` is `p / (p + n)`
over executable rules, and `_competence_goals` targets the "weak" ones by positive count.
So the substrate read its own operators as **0.33–0.40 reliable with nothing having ever
contradicted them**, and generated goals to shore up the most-confirmed things it had.
After the repair: **1.00** across every executable rule — the same arithmetic over numbers
that are now true.

## The seven properties

| | |
|---|---|
| **A** | a new rule's counts are its own — confirmations, counterexamples, zero contradictions |
| **B** | **validation is still strict** — one contradiction refutes, no threshold, no exceptions |
| **C** | validation UPDATES the counts — the defect that hid the `warehouse` rule |
| **D** | a confirmation, a contradiction and a counterexample stay three separate things |
| **E** | `p/(p+n)` is about contradictions only, so confidence reads true |
| **F** | no independent evidence leaves the status unchanged — nothing is invented |
| **G** | the attestation reaches the act's judgement, and does not leak to the next act |

**B is the one to read carefully.** Strictness was the requirement, not a side effect:
this is an autonomous system with a lot of capabilities, and a rule promoted on partial
evidence is worse than no rule. `validate()` was not touched. The check exists so that a
later change cannot quietly relax it while the other six still pass.

**G is what the counts are FOR.** A rule carries its evidence, and the acting path loads
it — `stored` is right there, and `stored.is_executable` is read one line before the act
runs. But that is a BOOLEAN, and everything else went out of scope with it. The substrate
could say WHY it was acting (`Account`) and WHOSE things it was touching (`actor`), and
not HOW SURE it was of the thing it was acting on. `set_acting_rule` binds it to the async
context beside the intent and the actor; the constitution is given a reader for it the
same way it is given self-perception.

**Recorded, not yet deciding.** No law reads `rests_on` and no verdict moves because of
it. That is the absorb → benchmark → then wire discipline the constitution is being built
under. What changes now is that the judgement, the result handed back to the agent, and
`unified.safety_assessments` all SAY what the act rested on.

## Untested is not unreliable

`ActingRule.support` returns `None`, never `0.0`, when nothing has tested the rule — the
same distinction `ThreatSense.level()` makes. A rule the world has not exercised is
untested, and reporting zero would hand the constitution a measured doubt nobody measured.

## Run

```
./venv_lyric/bin/python3 experiments/RULE-EVIDENCE-01/experiment.py
```

Needs Postgres, not a full substrate boot. Every probe rule it creates is forgotten
through `RuleStore.forget_domain` before it exits. Each run writes a structured record to
`results/<timestamp>.json` with a `.md` summary beside it.
