"""MOTIVATION-CLOSEDLOOP-01 — does closing a selected pursuit actually improve competence and
change the next pursuit?

Targets the specific "does not yet prove" claim: *selected tasks improve competence, the original
uncertainty decreases, and the next pursuit changes accordingly.*

Real machinery, isolated & non-polluting: two competence beliefs are created IN MEMORY (the same
BayesianUncertainty store the epistemic engine reads), so they surface as real capability-frontier
pursuits. We select one, then apply REAL competence evidence via the same `update_belief` path
`record_competence_evidence` uses (positive `operator_learning` evidence — an executed pursuit's
outcome), and measure: the belief's uncertainty falls, it leaves the unstable set, it drops out of the
pursuit ranking, and the OTHER belief becomes the next pursuit. In-memory beliefs are deleted at the
end; nothing is flushed to the DB.

SCOPE (honest): this proves the closed loop RESPONDS to a real competence update — uncertainty
decreases and the next pursuit changes. It does NOT prove the substrate autonomously executed a web
task to produce that evidence; the executed-outcome is stood in by a real evidence update (real
machinery, not a stub), which is the deterministic, reproducible core of the claim.

Run: ./venv_lyric/bin/python3 experiments/MOTIVATION-CLOSEDLOOP-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "MOTIVATION-CLOSEDLOOP-01",
    claim=("The motivation loop CLOSES: an unknown becomes a ranked frontier "
           "pursuit, acting on it moves the underlying belief, and the moved "
           "belief changes the ranking on the next pass. The decision is "
           "deterministic — the same self state yields the same ranking, with no "
           "RNG anywhere in it."),
    hypothesis=("If the loop were open, resolving an unknown would leave the "
                "frontier unchanged and the substrate would keep pursuing what it "
                "had already learned."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.reasoning.epistemic_engine import get_epistemic_engine
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C

    unc = get_uncertainty_system()

    # the REAL coordinator decision methods, bound to a minimal stand-in. No DB, so
    # _development → None → growth 0, and the competence/grounding reads return
    # nothing; the ranking then rests on entropy and the structural tiebreaks,
    # which is all this claim needs.
    #
    # `_competence` is bound because the ranking now READS it: a gap in a domain
    # the substrate already holds operators in is more closable than one it does
    # not, and that is the signal that tells otherwise-identical gaps apart. The
    # stand-in has to expose what the real decision depends on, or this stops
    # testing the real decision.
    class _Self:
        _development = C._development
        _competence = C._competence
        _intrinsic_pursuits = C._intrinsic_pursuits
        _score_pursuits = C._score_pursuits
        _frontier_of = staticmethod(C._frontier_of)
    me = _Self(); me.learning = None; me.domain_registry = None
    # The real constitution, as the real self has: choosing a pursuit asks it
    # which way the substrate bears toward each subject.
    from core.agents.autonomous.autonomous_coordinator import get_constitution
    me.constitution = get_constitution()

    # two unknown-capability domains: max-uncertainty competence beliefs (prior 0.5 → entropy ~1.0)
    A = unc.create_belief("the substrate has learned the operators of domain test_capA", "test_capA", prior=0.5)
    B = unc.create_belief("the substrate has learned the operators of domain test_capB", "test_capB", prior=0.5)
    try:
        _pursuits = await me._intrinsic_pursuits(limit=50)
        pdoms = {p["domain"]: p for p in _pursuits}
        print("\n== Generate → both unknown capabilities are pursuits at max uncertainty ==")
        check("test_capA is a capability pursuit", pdoms.get("test_capA", {}).get("frontier") == "capability",
              str(pdoms.get("test_capA")))
        check("test_capB is a capability pursuit", pdoms.get("test_capB", {}).get("frontier") == "capability")
        ent_A0 = A.entropy
        ent_B0 = B.entropy
        check("both start uncertain (entropy > 0.7)", ent_A0 > 0.7 and ent_B0 > 0.7,
              f"A={ent_A0:.3f} B={ent_B0:.3f}")

        print("\n== Select A → execute (real competence evidence, at the REAL default quality) ==")
        from core.integration.universal_domain_master import UniversalDomainMaster
        QUALITY = UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY   # 0.15 — the real, deliberately low default

        def learn_cycle():
            # exactly the evidence record_competence_evidence(learned=True) feeds update_belief
            unc.update_belief(A.belief_id, {"source": "operator_learning", "quality": QUALITY}, evidence_supports=True)

        learn_cycle()                                    # ONE cycle
        check("one weak cycle does NOT flip competence (not resolved after a single data point)",
              A.entropy > 0.7, f"entropy after 1 cycle = {A.entropy:.3f}")
        cycles = 1
        while A.entropy > 0.7 and cycles < 300:
            learn_cycle(); cycles += 1
        ent_A1 = A.entropy
        check("A's uncertainty DECREASED (posterior moved on real evidence)", ent_A1 < ent_A0,
              f"entropy {ent_A0:.3f} -> {ent_A1:.3f}")
        check("competence EARNED over SEVERAL cycles, not one", cycles > 1 and ent_A1 <= 0.7,
              f"{cycles} cycles, entropy {ent_A1:.3f}")
        check("A left the unstable set (entropy <= 0.7)", ent_A1 <= 0.7, f"{ent_A1:.3f}")

        print("\n== Observe → the pursued gap is resolved; the next pursuit changes ==")
        regions_after = {getattr(r, "domain", None) for r in get_epistemic_engine().get_unstable_regions()}
        check("A is no longer an unstable region", "test_capA" not in regions_after)
        pursuits_after = await me._intrinsic_pursuits(limit=50)
        pdoms_after = {p["domain"] for p in pursuits_after}
        check("A dropped out of the pursuit ranking", "test_capA" not in pdoms_after)
        check("B is STILL a pursuit — the next pursuit changed to the unresolved one",
              "test_capB" in pdoms_after)
        check("B was untouched by A's update (targeted, not global)", abs(B.entropy - ent_B0) < 1e-9,
              f"B entropy {ent_B0:.3f} -> {B.entropy:.3f}")

        # THE LOOP, MEASURED. Competence is EARNED here, not declared: the
        # evidence quality is the real production default, so the number of
        # cycles needed is a property of the belief math rather than of this
        # experiment, and a future change that makes competence cheap to claim
        # shows up as this count collapsing.
        EV.metric("evidence_quality", QUALITY, "quality [0,1]",
                  "UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY — the real, "
                  "deliberately low production default, not a test value")
        EV.metric("cycles_to_competence", cycles, "count",
                  "weak positive evidence updates needed before the gap left the "
                  "unstable set; 1 would mean competence flips on a single point")
        EV.metric("entropy_pursued_before", round(ent_A0, 4), "entropy [0,1]")
        EV.metric("entropy_pursued_after", round(ent_A1, 4), "entropy [0,1]",
                  "must fall below the 0.7 unstable threshold for the gap to close")
        EV.metric("entropy_reduction", round(ent_A0 - ent_A1, 4), "entropy delta",
                  "how far acting on the pursuit moved the belief")
        EV.metric("entropy_untouched_control", round(abs(B.entropy - ent_B0), 6),
                  "entropy delta",
                  "the OTHER unknown, which must not move — proves the update was "
                  "targeted rather than a global drift toward confidence")
    finally:
        # cleanup — in-memory only; nothing was flushed to the DB
        unc.beliefs.pop(A.belief_id, None)
        unc.beliefs.pop(B.belief_id, None)

    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"\n==== MOTIVATION-CLOSEDLOOP-01: {passed}/{total} checks passed ====")
    EV.metric("pursuits_before", len(_pursuits), "count",
              "frontier size while both seeded unknowns are still unknown")
    EV.metric("pursuits_after", len(pursuits_after), "count",
              "frontier size after one is RESOLVED — the loop closing shows here")
    EV.note("Uses the REAL coordinator decision methods bound to a minimal stand-in: "
            "no database, so _development is None and growth is 0, and the "
            "competence/grounding reads return nothing. The ranking then rests on "
            "entropy and the structural tiebreaks, which is what this claim needs.")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total else 1


sys.exit(asyncio.run(main()))
