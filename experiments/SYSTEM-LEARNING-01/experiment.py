#!/usr/bin/env python3
"""SYSTEM-LEARNING-01 — the learning faculty, alone, on the live substrate.

One authority (`UnifiedLearningSystem`, reached through `get_learning_authority`).
A told fact is admitted once, fans out to a belief, and is not admitted twice; a
malformed fact is refused; two demonstrations become a rule through the
induction the substrate drains itself. Everything written is removed by id.

Run: ./venv_torin/bin/python3 experiments/SYSTEM-LEARNING-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

DOMAIN = "isolation_probe_learning"
EV = RunRecord(
    "SYSTEM-LEARNING-01",
    claim=("The learning faculty is one authority: a told fact enters the concept graph "
           "once and moves a belief, a malformed one is refused, demonstrations become a "
           "rule through the substrate's own induction, and every public method is reached."),
    hypothesis=("A second learning system, a fact admitted twice, a belief that did not "
                "move, or a dead public method would each fail a check here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    written = {"memories": set(), "beliefs": set()}
    try:
        from core.learning import get_learning_authority
        from core.learning.unified_learning_system import get_unified_learning_system
        from core.semantics.cognitive_ingress import Provenance
        L = get_learning_authority()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="learning", cls="UnifiedLearningSystem",
                        path="core/learning/unified_learning_system.py",
                        held=coord.learning, reached=L)
        check("the two accessors name the same authority",
              get_unified_learning_system() is L)

        print("\n== B. A told fact enters once and moves a belief ==")
        prov = Provenance(producer="experiment", source_id="SYSTEM-LEARNING-01",
                          source_type="USER_SUPPLIED")
        adm = await L.learn_fact("isoprobe_finch", "isa", "isoprobe_bird", domain=DOMAIN,
                                 provenance=prov, surface="an isoprobe finch is an isoprobe bird")
        if getattr(adm, "memory_id", None):
            written["memories"].add(adm.memory_id)
        check("the fact is admitted", bool(getattr(adm, "admitted", False)),
              f"created={getattr(adm, 'concepts_created', None)} "
              f"reinforced={getattr(adm, 'concepts_reinforced', None)} memory={getattr(adm, 'memory_id', None)}")
        belief = L.belief_for_claim("isoprobe_finch isa isoprobe_bird")
        if belief is not None:
            written["beliefs"].add(belief.belief_id)
        check("the admission moved a belief through the one belief door",
              belief is not None and float(getattr(belief, "posterior_probability", 0)) > 0.5,
              f"belief={getattr(belief, 'belief_id', None)} "
              f"posterior={getattr(belief, 'posterior_probability', None)}")
        rel = await d.execute_query(
            "SELECT count(*) n FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON cr.source_concept_id = c.concept_id WHERE c.name = $1 AND cr.relation = 'isa'",
            ("isoprobe_finch",), fetch_one=True)
        check("the relation is in the concept graph the reasoner walks",
              rel is not None and int(rel["n"]) >= 1, f"isa edges from isoprobe_finch: {rel and rel['n']}")

        adm2 = await L.learn_fact("isoprobe_finch", "isa", "isoprobe_bird", domain=DOMAIN,
                                  provenance=prov, surface="an isoprobe finch is an isoprobe bird")
        if getattr(adm2, "memory_id", None):
            written["memories"].add(adm2.memory_id)
        check("telling it again does not admit it twice",
              bool(getattr(adm2, "already_present", False)) or not getattr(adm2, "concepts_created", None),
              f"already_present={getattr(adm2, 'already_present', None)} "
              f"created={getattr(adm2, 'concepts_created', None)}")

        print("\n== C. A malformed fact is refused, not repaired ==")
        try:
            bad = await L.learn_fact("", "isa", "isoprobe_bird", domain=DOMAIN, provenance=prov)
            refused = not getattr(bad, "admitted", True)
            detail = f"admitted={getattr(bad, 'admitted', None)} refusals={getattr(bad, 'refusals', None)}"
        except (ValueError, TypeError) as e:
            refused, detail = True, f"raised {type(e).__name__}: {e}"
        check("an empty subject is refused", refused, detail)

        print("\n== D. Demonstrations become a rule through the substrate's own induction ==")
        from core.learning.rule_induction import Fact, TrainingExample
        for i, (src, dst) in enumerate((("x", "y"), ("y", "z"), ("z", "w"))):
            ex = TrainingExample(
                before=(Fact("ISOAT", ("a", src)),), action=Fact("ISOMOVE", ("a", src, dst)),
                after=(Fact("ISOAT", ("a", dst)),), positive=True, evidence_id=f"sysl01_{i}")
            ok = await L.record_demonstration(ex, domain_id=DOMAIN)
        check("demonstrations are recorded", bool(ok))
        drained = await L.drain_pending_induction(limit=50)
        check("the pending induction drains", isinstance(drained, dict) and drained.get("drained", 0) >= 1,
              f"{drained}")
        rules = await L.rules(DOMAIN)
        kinds = {getattr(r.status, "value", str(r.status)) for r in rules}
        check("a rule was induced for the domain", bool(rules),
              f"{len(rules)} rule(s): {[str(r.rule)[:60] for r in rules][:2]} status={kinds}")
        EV.metric("rules_induced", len(rules), "count")

        print("\n== F. Strategy learning, prediction and retry waits are real learning ==")
        from core.learning.meta_learning import OutcomeClass, TaskFamily
        ARM = "isoprobe_arm:"
        before = await L.predict_outcome({"task_family": TaskFamily.CONTROL,
                                          "strategy_type": f"{ARM}steady"})
        check("with no outcome recorded, nothing is predicted",
              before["predicted_success"] is None and before["evidence"] == 0, f"{before}")
        for i in range(6):
            await L.update_strategy_effectiveness(
                TaskFamily.CONTROL, f"{ARM}steady", success=(i != 0), performance_score=1.0,
                time_ms=10.0, outcome_class=OutcomeClass.SUCCESS if i else OutcomeClass.STRATEGY_FAILURE,
                predicted_success=0.5)
            await L.update_strategy_effectiveness(
                TaskFamily.CONTROL, f"{ARM}flaky", success=(i == 0), performance_score=0.0,
                time_ms=10.0, outcome_class=OutcomeClass.STRATEGY_FAILURE if i else OutcomeClass.SUCCESS)
        after = await L.predict_outcome({"task_family": TaskFamily.CONTROL,
                                         "strategy_type": f"{ARM}steady"})
        check("recorded outcomes move the prediction: 5 of 6 -> (5+1)/(6+2)",
              after["evidence"] == 6 and abs(after["predicted_success"] - 0.75) < 1e-9, f"{after}")
        ranked = await L.recommend_strategies({"task_family": TaskFamily.CONTROL,
                                               "strategy_prefix": ARM})
        check("the evidence recommends the arm that wins over the one that loses",
              [r["strategy_type"] for r in ranked] == [f"{ARM}steady", f"{ARM}flaky"],
              f"{[(r['strategy_type'], r['successes'], r['trials'], r['lower']) for r in ranked]}")
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        cal = get_uncertainty_system().calibrations.get("strategy:control")
        check("a prediction made at decision time is checked against the outcome",
              cal is not None and cal.total_predictions >= 6,
              f"predictions checked={getattr(cal, 'total_predictions', 0)}")
        refused = None
        try:
            await L.predict_outcome({"task_family": "not_a_family"})
        except ValueError as error:
            refused = str(error)
        check("an unknown task family is refused", refused is not None, (refused or "")[:70])

        comp = "isoprobe_component"
        waits = {await L.predict_optimal_retry_delay({"component": comp}) for _ in range(20)}
        check("a retry wait is one the learner chooses among",
              waits <= set(L.RETRY_DELAYS_S), f"{sorted(waits)}")
        for _ in range(12):
            for short in (15.0, 30.0, 60.0):
                await L.record_retry_outcome({"component": comp}, short, recovered=False)
            await L.record_retry_outcome({"component": comp}, 120.0, recovered=True)
        # Thompson sampling on the EXPECTED TIME TO RECOVERY (delay / P(success)):
        # a 15 s wait that failed 12 times still has ~7% chance, i.e. ~211 s
        # expected against ~129 s for 120 s -- so it is still tried now and then,
        # and correctly. What the evidence settles is which wait is chosen MOST,
        # and that long waits nothing supports are not chosen at all.
        chosen = [await L.predict_optimal_retry_delay({"component": comp}) for _ in range(60)]
        most = max(set(chosen), key=chosen.count)
        check("after short waits keep failing and 120 s keeps recovering, 120 s is chosen most",
              most == 120.0 and chosen.count(120.0) > len(chosen) / 2,
              f"{ {w: chosen.count(w) for w in sorted(set(chosen))} }")
        check("and long waits no evidence supports are not chosen",
              not any(w >= 300.0 for w in chosen), f"{sorted(set(chosen))}")
        bad = None
        try:
            await L.record_retry_outcome({"component": comp}, 7.0, recovered=True)
        except ValueError as error:
            bad = str(error)
        check("a wait it does not choose among is refused as evidence", bad is not None)

        report = await L.consolidate_learning()
        check("consolidation settles unknowns, closes abandoned decisions, persists classifiers",
              set(report) == {"refreshed", "known_unknowns", "abandoned_decisions_closed",
                              "classifiers_saved"}
              and isinstance(report["known_unknowns"], dict),
              f"{report}")

        print("\n== E. It can account for itself ==")
        m = await L.metrics()
        check("metrics are a dict", isinstance(m, dict) and bool(m), f"keys={sorted(m)[:8]}")
    finally:
        # ── cleanup, by id and by the probe's own domain ─────────────────────
        try:
            # The probe's strategy and retry arms: in memory and persisted.
            ml = L.meta_learning
            for sid in [sid for sid, st in ml.strategies.items()
                        if str(st.strategy_type).startswith(("isoprobe_arm:", "retry:isoprobe_component:"))]:
                st = ml.strategies.pop(sid)
                ml.task_strategy_map.get(st.task_type, []).remove(sid) \
                    if sid in ml.task_strategy_map.get(st.task_type, []) else None
                await d.execute_query("DELETE FROM unified.meta_learning_strategies WHERE strategy_id = $1", (sid,))
            for mid in written["memories"]:
                await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,))
            for bid in written["beliefs"]:
                await d.execute_query("DELETE FROM unified.beliefs WHERE belief_id = $1", (bid,))
                try:
                    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                    get_uncertainty_system().beliefs.pop(bid, None)
                except Exception:
                    pass
            ids = [r["concept_id"] for r in await d.execute_query(
                "SELECT concept_id FROM unified.concepts WHERE name LIKE 'isoprobe_%'", ())]
            if ids:
                await d.execute_query(
                    "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
                    "OR target_concept_id = ANY($1::text[])", (ids,))
                for t in ("concept_aliases", "concept_domains", "concept_evidence"):
                    try:
                        await d.execute_query(f"DELETE FROM unified.{t} WHERE concept_id = ANY($1::text[])", (ids,))
                    except Exception:
                        pass
                await d.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])", (ids,))
            await d.execute_query(
                "DELETE FROM unified.rule_authority_events WHERE rule_id IN "
                "(SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
            for t, col in (("learned_rule_evidence", None), ("learned_rules", "domain_id"),
                           ("operator_demonstrations", "domain_id"), ("operator_induction_pending", "domain_id"),
                           ("knowledge_updates", "domain")):
                if col is None:
                    await d.execute_query(
                        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN "
                        "(SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
                else:
                    await d.execute_query(f"DELETE FROM unified.{t} WHERE {col} = $1", (DOMAIN,))
            await d.execute_query("DELETE FROM unified.beliefs WHERE domain = $1", (DOMAIN,))
            await d.execute_query("DELETE FROM unified.domains WHERE domain_id = $1", (DOMAIN,))
            # The evidence envelopes this run's provenance stamped, and every row
            # that cites one -- a reinforced SHARED concept keeps its evidence
            # row after the probe's own concepts are gone.
            envelopes = [r["evidence_id"] for r in await d.execute_query(
                "SELECT evidence_id FROM unified.evidence_envelopes "
                "WHERE producer = 'experiment' AND source_id = $1", ('SYSTEM-LEARNING-01',)) or []]
            if envelopes:
                for t in ("concept_relations", "concept_domains", "concept_evidence"):
                    await d.execute_query(
                        f"DELETE FROM unified.{t} WHERE evidence_id = ANY($1::text[])", (envelopes,))
                await d.execute_query(
                    "DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                    (envelopes,))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE 'isoprobe_%') "
                "+ (SELECT count(*) FROM unified.learned_rules WHERE domain_id = $1) "
                "+ (SELECT count(*) FROM unified.operator_demonstrations WHERE domain_id = $1) "
                "+ (SELECT count(*) FROM unified.evidence_envelopes WHERE producer = 'experiment' "
                "AND source_id = 'SYSTEM-LEARNING-01') AS n", (DOMAIN,),
                fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-LEARNING-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
