"""OPERABILITY-BAR-01 — the EARNED half + the operability gate (KNOW→DO bridge).

Two parts, both on REAL machinery, no stubs:

  (A) MECHANISM on a synthetic throwaway domain in the REAL store: record operating
      outcomes and watch the earned reliability move, the bar move (DOWN on a proven-
      correct record, UP on a poor one), and the gate FLIP. The synthetic row is
      DELETED at the end; a fixed satisfaction is injected so we isolate the bar's
      response to earned trust alone. Proves the mechanism FUNCTIONS.

  (B) LIVE honesty over the real substrate DB: _domain_operability across real
      domains, reporting that the bar currently sits flat at the stakes base because
      no domain has operating history yet -- earned differentiation is earned from
      runtime, not asserted from a cold snapshot.

Run: ./venv_lyric/bin/python3 scratchpad/bench_operability.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()

    from core.integration.universal_domain_master import get_universal_domain_master
    from core.domain.domain_registry import get_domain_registry
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C

    udm = get_universal_domain_master()
    await udm.initialize()
    reg = get_domain_registry()
    try:
        await reg.initialize()
    except Exception as e:
        print("domain registry init:", type(e).__name__, e)

    # the REAL coordinator gate methods bound to the real subsystems, with a fixed
    # satisfaction so part (A) isolates the bar's response to EARNED trust.
    FIXED_SAT = 0.55
    class _B:
        _domain_stakes = C._domain_stakes
        _domain_operability = C._domain_operability
        _OPERABILITY_BAND = C._OPERABILITY_BAND
        _OPERABILITY_FLOOR = C._OPERABILITY_FLOOR
        _OPERABILITY_CEIL = C._OPERABILITY_CEIL
        _ACTION_STAKES = C._ACTION_STAKES
        # `_domain_operability` folds in cross-domain BORROWED trust. Part (A)
        # ISOLATES earned trust, so borrowing is neutralised here (it is covered
        # end-to-end by BORROWED-KNOWLEDGE-01) — without this, a synthetic domain
        # borrows from incidental neighbours and the bar reads "satisfied-via-transfer".
        async def _borrowed_satisfaction(self, d):
            return {"borrowed": 0.0, "from": []}
        def _domain_satisfaction(self, d):
            return {"domain": d, "satisfaction": FIXED_SAT, "coverage": 0.0,
                    "confidence": None, "beliefs": 0}
    b = _B(); b.universal_domain_master = udm; b.domain_registry = reg

    SYN = "test_operability_synthetic_domain"
    # clean any leftover from a prior run
    await db.execute_query("DELETE FROM unified.domain_controllability WHERE domain_id=$1",
                           (SYN,), commit=True)
    try:
        print("\n== (A) MECHANISM: earned trust moves the bar, the gate flips ==")
        op0 = await b._domain_operability(SYN)
        base_stakes = op0["stakes"]
        check("no history → earned is NEUTRAL (0.5), bar sits at the stakes base",
              op0["earned"] == 0.5 and abs(op0["bar"] - base_stakes) < 1e-9,
              f"earned={op0['earned']} bar={op0['bar']} stakes={base_stakes}")
        check(f"at fixed satisfaction {FIXED_SAT}, neutral bar {op0['bar']} → operable={op0['operable']}",
              op0["operable"] == (FIXED_SAT >= op0["bar"]),
              f"reason={op0['reason']}")

        # a few RIGHT operations, but below the min sample → still neutral (no swing on a handful)
        from core.integration.universal_domain_master import UniversalDomainMaster
        from core.learning.meta_learning import OutcomeClass
        MIN = UniversalDomainMaster.OPERATING_MIN_SAMPLE
        for _ in range(MIN - 1):
            await udm.record_operating_outcome(SYN, success=True,
                                             outcome_class=OutcomeClass.SUCCESS)
        op_few = await b._domain_operability(SYN)
        check("below min sample → earned still neutral (a handful of wins does not swing trust)",
              op_few["earned"] == 0.5 and op_few["reason"] != "below-bar-earning",
              f"attempts={op_few['earned_basis']['attempts']} earned={op_few['earned']}")

        # now a PROVEN-correct record (many wins) → earned rises, bar DROPS below stakes
        for _ in range(40):
            await udm.record_operating_outcome(SYN, success=True,
                                             outcome_class=OutcomeClass.SUCCESS)
        op_good = await b._domain_operability(SYN)
        check("proven-correct operation → earned > 0.5 (Wilson lower bound climbed)",
              op_good["earned"] > 0.5, f"earned={op_good['earned']} "
              f"win_rate={op_good['earned_basis']['win_rate']}")
        check("bar DROPPED below the stakes base (earned trust eases the KNOW requirement)",
              op_good["bar"] < base_stakes, f"bar {base_stakes} → {op_good['bar']}")
        check("gate is operable now that the bar eased under fixed satisfaction",
              op_good["operable"] is True and FIXED_SAT >= op_good["bar"],
              f"sat={FIXED_SAT} bar={op_good['bar']} reason={op_good['reason']}")

        # reset and prove the OTHER direction: a poor record RAISES the bar
        for _t in ("unified.domain_controllability", "unified.domains"):
            await db.execute_query(f"DELETE FROM {_t} WHERE domain_id=$1", (SYN,), commit=True)
        for _ in range(40):
            await udm.record_operating_outcome(SYN, success=False,
                                             outcome_class=OutcomeClass.EXECUTION_FAILURE)
        op_bad = await b._domain_operability(SYN)
        check("consistently WRONG operation → earned < 0.5", op_bad["earned"] < 0.5,
              f"earned={op_bad['earned']} win_rate={op_bad['earned_basis']['win_rate']}")
        check("bar ROSE above the stakes base (being wrong demands MORE knowledge)",
              op_bad["bar"] > base_stakes, f"bar {base_stakes} → {op_bad['bar']}")
        check("gate now abstains — the poor record pushed the bar past fixed satisfaction",
              op_bad["operable"] is False and op_bad["reason"] == "below-bar-earning",
              f"sat={FIXED_SAT} bar={op_bad['bar']} reason={op_bad['reason']}")

        # persistence: earned trust survives re-reading from the store (not in-memory)
        rel = await udm.operating_reliability(SYN)
        check("earned record is persisted (read straight from the store)",
              rel["attempts"] == 40 and rel["wins"] == 0, str(rel))
    finally:
        for _t in ("unified.domain_controllability", "unified.domains"):
            await db.execute_query(f"DELETE FROM {_t} WHERE domain_id=$1", (SYN,), commit=True)

    print("\n== (B) LIVE honesty: the bar over real domains sits flat until earned ==")
    # use the REAL satisfaction now (full gate), over a sample of real domains
    class _Full(_B):
        def _domain_satisfaction(self, d):
            return C._domain_satisfaction(self, d)
    fb = _Full(); fb.universal_domain_master = udm; fb.domain_registry = reg
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    try:
        await get_uncertainty_system().load_from_db()
    except Exception as e:
        print("belief load:", type(e).__name__, e)
    dom_ids = list(reg.domains.keys())
    print(f"[LIVE] {len(dom_ids)} real domains")
    sample = dom_ids[:12]
    any_earned = False
    operable_ct = 0
    for d in sample:
        op = await fb._domain_operability(d)
        if op["earned"] != 0.5:
            any_earned = True
        if op["operable"]:
            operable_ct += 1
        print(f"    sat={str(op['satisfaction']):>6} stakes={op['stakes']} "
              f"earned={op['earned']} bar={op['bar']} operable={str(op['operable']):>5} "
              f"{op['reason']:<20} {d[:40]}")
    check("LIVE earned is flat-neutral everywhere (no operating history yet — honest)",
          not any_earned, "earned differentiation is earned from runtime, not a cold snapshot")
    print(f"[LIVE] operable now: {operable_ct}/{len(sample)} sampled "
          f"(bar == stakes base everywhere; differentiation will come from earned + environment)")

    passed = sum(results); total = len(results)
    print(f"\n==== OPERABILITY-BAR-01: {passed}/{total} checks passed ====")
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
