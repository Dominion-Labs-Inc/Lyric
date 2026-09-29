#!/usr/bin/env python3
"""RULE-EVIDENCE-01 — can a rule say how sure it is, and is validation still strict?

TWO THINGS A RULE'S COUNTS HAVE TO GET RIGHT, and both were wrong.

  1  THEY MUST BE CURRENT. `_refresh_root_counts` had exactly ONE caller — the
     fingerprint-reuse branch of `record_induction`. Validation attached its
     evidence and did not recount; runtime confirmation and contradiction
     attached theirs and did not recount. Measured on the live store: the
     `warehouse` transfer rule held FIVE `validation_positive` roots, its own
     `detail` column read "confirmed by 5 independent observation(s)", and
     `positive_root_count` was 0. A `kite17` move rule had been confirmed by
     the world 133 times and its record said 2.

  2  THEY MUST MEAN ONE THING EACH. An INDUCTION counterexample was stored
     `supports=False`, identically to a runtime CONTRADICTION — and the two are
     opposites. A counterexample is part of the basis: the rule was induced to
     EXCLUDE it, and excluding four is what makes a rule discriminative rather
     than vacuous. A contradiction is the world disagreeing. Collapsed into one
     number, a well-induced rule was indistinguishable from a refuted one, and
     `IntrinsicMotivationSystem._operator_confidence` reads exactly this as
     `p / (p + n)` — so every executable operator reported 0.33–0.40 confidence
     with nothing having ever contradicted it.

  A  A NEW RULE'S COUNTS ARE ITS OWN            induction: positives, counterexamples, 0 contradicted
  B  VALIDATION IS STILL STRICT                 one contradiction ⇒ REFUTED, no exceptions
  C  VALIDATION UPDATES THE COUNTS              the defect that hid the warehouse rule
  D  A CONFIRMATION IS NOT A COUNTEREXAMPLE     the three counts stay separable
  E  CONFIDENCE READS TRUE                      p/(p+n) is about contradictions only
  F  NOTHING IS INVENTED                        no independent evidence ⇒ status unchanged

Run: ./venv_lyric/bin/python3 experiments/RULE-EVIDENCE-01/experiment.py
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

sys.path.insert(0, str(HERE.parent))
from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "RULE-EVIDENCE-01",
    claim=("A learned rule can say how well attested it is, that attestation is "
           "current, and it reaches the act's judgement."),
    hypothesis=("If evidence counts are recounted by role wherever evidence is "
                "attached, and bound to the acting context, then a judgement can "
                "report whether the act rests on a rule the world confirmed 133 "
                "times or one it confirmed twice — and validation stays strict."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


async def main() -> int:
    from core.database import get_database_manager
    from core.learning.rule_induction import (Fact, RuleInducer, TrainingExample)
    from core.learning.rule_store import (EpistemicStatus, EvidenceRole,
                                          get_rule_store)
    db = get_database_manager()
    await db.initialize()
    store = get_rule_store()
    await store.ensure_schema()

    tag = uuid.uuid4().hex[:6]
    DOMAIN = f"ruleev{tag}"

    # The canonical demonstration shape this store's own tests use: the action
    # is part of `before`, and a positive outcome ADDS to it.
    F = Fact.parse

    def positive(x, y, eid):
        before = (F(f"NAL{tag}({x})"), F(f"VEX{tag}({x},{y})"), F(f"TOR{tag}({y})"))
        return TrainingExample(before=before, action=F(f"KEM{tag}({x},{y})"),
                               after=before + (F(f"ZOR{tag}({x},{y})"),),
                               evidence_id=eid)

    def negative(before, action, eid):
        return TrainingExample(before=before, action=action, after=before,
                               positive=False, evidence_id=eid)

    def lesson(suffix):
        """Two demonstrations that worked and three counterexamples."""
        return [
            positive("a", "b", f"{tag}{suffix}_d1"),
            positive("c", "d", f"{tag}{suffix}_d2"),
            negative((F(f"VEX{tag}(e,f)"), F(f"TOR{tag}(f)")),
                     F(f"KEM{tag}(e,f)"), f"{tag}{suffix}_no_NAL"),
            negative((F(f"NAL{tag}(g)"), F(f"TOR{tag}(h)")),
                     F(f"KEM{tag}(g,h)"), f"{tag}{suffix}_no_VEX"),
            negative((F(f"NAL{tag}(i)"), F(f"VEX{tag}(i,j)")),
                     F(f"KEM{tag}(i,j)"), f"{tag}{suffix}_no_TOR"),
        ]

    print("\n== A. A new rule's counts are its own ==")
    teaching = lesson("A")
    result = RuleInducer().induce(teaching)
    stored = await store.record_induction(result, teaching, domain_id=DOMAIN,
                                          rule_kind="move_box")
    check("a rule was induced", bool(stored),
          f"{len(stored)} rule(s) — {result.status.value}: {result.detail}")
    rule = stored[0]
    check("its confirmations are the demonstrations that worked",
          rule.positive_root_count == 2, f"+{rule.positive_root_count}")
    check("its counterexamples are counted AS counterexamples",
          rule.counterexample_root_count == 3,
          f"{rule.counterexample_root_count} counterexample(s)")
    # THE CONFLATION. Before this, `negative_root_count` was 3 here — and a rule
    # nothing had contradicted read as 40% confident.
    check("and NOTHING has contradicted it, because nothing has tested it yet",
          rule.negative_root_count == 0, f"-{rule.negative_root_count}")

    print("\n== B. Validation is still strict — one contradiction refutes ==")
    # An independent observation where the box did NOT land. The rule says it does.
    contradicting = [negative(
        (F(f"NAL{tag}(z)"), F(f"VEX{tag}(z,y)"), F(f"TOR{tag}(y)")),
        F(f"KEM{tag}(z,y)"), f"{tag}_held_bad")]
    outcome = await store.validate(rule, contradicting)
    check("a single contradicting observation REFUTES the rule",
          outcome.status is EpistemicStatus.REFUTED,
          f"status={outcome.status.value}, detail={outcome.detail!r}")
    refuted = await store.get(rule.rule_id)
    check("and it is no longer executable", not refuted.is_executable,
          f"is_executable={refuted.is_executable}")
    check("the contradiction is counted as a contradiction",
          refuted.negative_root_count == 1, f"-{refuted.negative_root_count}")
    check("without disturbing the counterexamples it was induced from",
          refuted.counterexample_root_count == 3,
          f"{refuted.counterexample_root_count}")

    print("\n== C/D. Validation UPDATES the counts (the warehouse defect) ==")
    teaching2 = lesson("B")
    result2 = RuleInducer().induce(teaching2)
    stored2 = await store.record_induction(result2, teaching2,
                                           domain_id=f"{DOMAIN}b",
                                           rule_kind="move_box")
    good = stored2[0]
    held_out = [positive(f"m{i}", f"n{i}", f"{tag}_ok{i}") for i in range(5)]
    outcome2 = await store.validate(good, held_out)
    check("five confirming observations VALIDATE it",
          outcome2.status is EpistemicStatus.VALIDATED,
          f"{outcome2.detail!r}")
    fresh = await store.get(good.rule_id)
    attached = len(await store.evidence_roots(
        good.rule_id, {EvidenceRole.VALIDATION_POSITIVE}))
    check("the attached validation evidence and the stored count AGREE",
          fresh.positive_root_count == 2 + attached and attached == 5,
          f"count=+{fresh.positive_root_count} (2 induction + {attached} validation)")
    # This is the exact shape of the live defect: detail said five, count said zero.
    check("the row does not contradict its own detail column",
          "5 independent" in (fresh.detail or "") and fresh.positive_root_count > 0,
          f"detail={fresh.detail!r} count=+{fresh.positive_root_count}")
    check("and still nothing has contradicted it",
          fresh.negative_root_count == 0 and fresh.counterexample_root_count == 3,
          f"-{fresh.negative_root_count} / {fresh.counterexample_root_count} counterexample(s)")

    print("\n== E. Confidence now reads what it claims to read ==")
    p, n = fresh.positive_root_count, fresh.negative_root_count
    confidence = p / (p + n) if (p + n) else None
    old_style = p / (p + n + fresh.counterexample_root_count)
    check("p/(p+n) is about contradictions, not counterexamples",
          confidence == 1.0, f"{confidence:.2f} (conflated, it read {old_style:.2f})")

    print("\n== F. Nothing is invented from no evidence ==")
    outcome3 = await store.validate(fresh, [])
    check("no independent observations leaves the status UNCHANGED",
          outcome3.status is EpistemicStatus.VALIDATED
          and "no independent observations" in outcome3.detail,
          f"{outcome3.detail!r}")

    print("\n== G. The attestation reaches the act's judgement ==")
    from core.agents.autonomous.autonomous_coordinator import (
        Constitution, ReadingLedger)
    from core.learning.rule_store import (get_acting_rule, reset_acting_rule,
                                          set_acting_rule)
    con = Constitution(reading_ledger=ReadingLedger())
    con.set_rule_evidence(get_acting_rule)

    # UNBOUND FIRST. A raw tool call rests on no learned rule, and the honest
    # answer is silence rather than an invented attestation.
    bare = await con.judge("tool", "read_file", {"file_path": "/tmp/x.txt"})
    check("an act resting on no rule reports no attestation",
          bare.rests_on is None, f"rests_on={bare.rests_on}")

    token = set_acting_rule(fresh)
    try:
        judged = await con.judge("tool", "read_file", {"file_path": "/tmp/x.txt"})
    finally:
        reset_acting_rule(token)
    rests = judged.rests_on or {}
    check("the judgement names the rule the act rests on",
          rests.get("rule_id") == fresh.rule_id, f"{rests.get('rule_id')}")
    check("and how the world has tested it",
          rests.get("confirmed") == fresh.positive_root_count
          and rests.get("contradicted") == 0
          and rests.get("counterexamples") == 3,
          f"+{rests.get('confirmed')} / -{rests.get('contradicted')} / "
          f"{rests.get('counterexamples')} counterexample(s)")
    check("support is the share of observations that TESTED it",
          rests.get("support") == 1.0, f"support={rests.get('support')}")
    # The record the agent and the durable store both read.
    check("it travels in the judgement's own dict, so the record carries it",
          (judged.to_dict().get("rests_on") or {}).get("rule_id") == fresh.rule_id)
    check("the binding is released — it does not leak to the next act",
          get_acting_rule() is None)

    # UNTESTED IS NOT UNRELIABLE. A rule nothing has exercised reports None,
    # never 0.0, for the same reason `ThreatSense.level()` does.
    token = set_acting_rule(refuted)
    try:
        after_refute = await con.judge("tool", "read_file", {"file_path": "/tmp/x.txt"})
    finally:
        reset_acting_rule(token)
    r2 = after_refute.rests_on or {}
    check("a refuted rule's contradiction is visible in the judgement",
          r2.get("contradicted") == 1 and r2.get("status") == "refuted",
          f"status={r2.get('status')} -{r2.get('contradicted')} "
          f"support={r2.get('support')}")

    EV.metric("attested_confirmations", rests.get("confirmed"), "roots")
    EV.metric("attested_support", rests.get("support"), "fraction")

    # ── clean up everything this run created ─────────────────────────────
    removed = 0
    for d in (DOMAIN, f"{DOMAIN}b"):
        removed += await store.forget_domain(d)

    passed, total = sum(results), len(results)
    print(f"\n==== RULE-EVIDENCE-01: {passed}/{total} checks passed "
          f"({removed} probe rule(s) forgotten) ====\n")
    EV.write()
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
