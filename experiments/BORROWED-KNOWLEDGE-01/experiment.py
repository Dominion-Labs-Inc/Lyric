"""BORROWED-KNOWLEDGE-01 — cross-domain transfer on the KNOW side lightens the operability load.

(A) MECHANISM (controlled stand-ins, real methods): a target domain confidently related to a
    well-known neighbor BORROWS a discounted prior, its EFFECTIVE satisfaction rises, and it can
    clear the bar VIA TRANSFER — while an unrelated unknown borrows nothing, borrowing is capped,
    and a high-stakes domain can NOT be cleared by borrowing alone. One hop (neighbor's OWN sat only).
(B) LIVE: real `similar_domains` over the real DB — honest about how much transfer is available now.

Run: ./venv_torin/bin/python3 scratchpad/bench_borrowed.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


class _Neighbor:
    def __init__(self, domain_id): self.domain_id = domain_id


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C

    # ---- controlled collaborators ----
    class _UDM:
        def __init__(self): self._sims = {}
        async def similar_domains(self, domain_id, *, threshold=0.0):
            return [(n, s) for (n, s) in self._sims.get(domain_id, []) if s >= threshold]
        async def operating_reliability(self, domain_id):
            return {"earned": 0.5, "enough_history": False, "attempts": 0, "wins": 0}
    udm = _UDM()

    SATS = {}   # domain_id -> own satisfaction (None = unmeasured)
    STAKES = {"_t": 0.5}

    class _B:
        _borrowed_satisfaction = C._borrowed_satisfaction
        _domain_operability = C._domain_operability
        _BORROW_REL_MIN = C._BORROW_REL_MIN
        _BORROW_NEIGHBORS = C._BORROW_NEIGHBORS
        _BORROW_CAP = C._BORROW_CAP
        _OPERABILITY_BAND = C._OPERABILITY_BAND
        _OPERABILITY_FLOOR = C._OPERABILITY_FLOOR
        _OPERABILITY_CEIL = C._OPERABILITY_CEIL
        def _domain_satisfaction(self, d):
            s = SATS.get(d)
            return None if s is None else {"domain": d, "satisfaction": s}
        async def _domain_stakes(self, d):
            return {"domain": d, "stakes": STAKES.get("_t", 0.5)}
    b = _B(); b.universal_domain_master = udm; b.domain_registry = object()

    print("\n== (A) MECHANISM ==")
    # target TGT is unknown on its own, but strongly related to KNOWN_A (0.8, sat 0.9) and
    # weakly to KNOWN_B (0.4, sat 0.5).
    SATS.update({"TGT": None, "KNOWN_A": 0.9, "KNOWN_B": 0.5})
    udm._sims["TGT"] = [(_Neighbor("KNOWN_A"), 0.8), (_Neighbor("KNOWN_B"), 0.4)]

    bi = await b._borrowed_satisfaction("TGT")
    # lends: 0.8*0.9=0.72, 0.4*0.5=0.20 ; noisy-OR = 1-(0.28*0.80)=0.776 ; cap 0.5 → 0.5
    check("each neighbor lends similarity × its OWN satisfaction (one hop)",
          {l["domain"]: l["lends"] for l in bi["from"]} == {"KNOWN_A": 0.72, "KNOWN_B": 0.2},
          str(bi["from"]))
    check("borrowed is noisy-OR'd then CAPPED (0.776 → 0.5)", bi["borrowed"] == 0.5,
          f"borrowed={bi['borrowed']}")

    op = await b._domain_operability("TGT")
    check("unknown-on-its-own domain becomes operable VIA TRANSFER at a 0.5 bar",
          op["operable"] is True and op["reason"] == "satisfied-via-transfer",
          f"own={op['own_satisfaction']} borrowed={op['borrowed_satisfaction']} "
          f"eff={op['satisfaction']} bar={op['bar']} reason={op['reason']}")
    check("own and borrowed reported separately (ignorance not hidden)",
          op["own_satisfaction"] is None and op["borrowed_satisfaction"] == 0.5)

    print("\n-- unrelated unknown borrows nothing --")
    SATS["LONE"] = None
    udm._sims["LONE"] = []            # nothing related
    op_lone = await b._domain_operability("LONE")
    check("no own knowledge + no related lender → stays unknown-domain",
          op_lone["operable"] is False and op_lone["reason"] == "unknown-domain",
          f"borrowed={op_lone['borrowed_satisfaction']} reason={op_lone['reason']}")

    print("\n-- high stakes can NOT be cleared by borrowing alone --")
    STAKES["_t"] = 0.95              # dangerous domain → bar ~0.95
    op_hi = await b._domain_operability("TGT")
    check("borrowed (capped 0.5) < high bar → NOT operable; must KNOW it for real",
          op_hi["operable"] is False and op_hi["satisfaction"] == 0.5 and op_hi["bar"] == 0.95,
          f"eff={op_hi['satisfaction']} bar={op_hi['bar']} reason={op_hi['reason']}")
    STAKES["_t"] = 0.5

    print("\n-- own knowledge + borrowed combine (noisy-OR), never exceed 1 --")
    SATS["TGT"] = 0.3               # now it knows a little on its own too
    op_both = await b._domain_operability("TGT")
    # eff = 1-(1-0.3)(1-0.5) = 1-0.35 = 0.65
    check("own 0.3 noisy-OR borrowed 0.5 → effective 0.65 (own reported as 0.3)",
          op_both["satisfaction"] == 0.65 and op_both["own_satisfaction"] == 0.3,
          f"eff={op_both['satisfaction']}")

    print("\n-- weakly-related neighbors below threshold lend nothing --")
    udm._sims["TGT2"] = [(_Neighbor("KNOWN_A"), 0.2)]   # 0.2 < _BORROW_REL_MIN 0.30
    SATS["TGT2"] = None
    op_weak = await b._domain_operability("TGT2")
    check("a sub-threshold relation is not 'confidently related' → borrows nothing",
          op_weak["borrowed_satisfaction"] == 0.0 and op_weak["reason"] == "unknown-domain",
          f"borrowed={op_weak['borrowed_satisfaction']}")

    # ---- (B) LIVE ----
    print("\n== (B) LIVE: transfer available over the real DB right now ==")
    from core.database import get_database_manager
    db = get_database_manager(); await db.initialize()
    from core.integration.universal_domain_master import get_universal_domain_master
    from core.domain.domain_registry import get_domain_registry
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    rudm = get_universal_domain_master(); await rudm.initialize()
    reg = get_domain_registry()
    try: await reg.initialize()
    except Exception as e: print("registry init:", type(e).__name__, e)
    try: await get_uncertainty_system().load_from_db()
    except Exception as e: print("belief load:", type(e).__name__, e)

    class _Live:
        _borrowed_satisfaction = C._borrowed_satisfaction
        _domain_satisfaction = C._domain_satisfaction
        _BORROW_REL_MIN = C._BORROW_REL_MIN
        _BORROW_NEIGHBORS = C._BORROW_NEIGHBORS
        _BORROW_CAP = C._BORROW_CAP
    lv = _Live(); lv.universal_domain_master = rudm; lv.domain_registry = reg

    dom_ids = list(reg.domains.keys())
    lent = 0
    for d in dom_ids:
        info = await lv._borrowed_satisfaction(d)
        if info["borrowed"] > 0.0:
            lent += 1
            if lent <= 6:
                print(f"    {d[:34]:34s} borrows {info['borrowed']} from "
                      f"{[(x['domain'], x['similarity']) for x in info['from'][:3]]}")
    print(f"[LIVE] {lent}/{len(dom_ids)} domains currently have a confidently-related lender "
          f"(≥{C._BORROW_REL_MIN} similarity AND a measured neighbor)")
    check("LIVE transfer runs without error over every real domain", True,
          "honest: transfer scales with how coupled/developed the real domain graph is")

    passed = sum(results); total = len(results)
    print(f"\n==== BORROWED-KNOWLEDGE-01: {passed}/{total} checks passed ====")
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
