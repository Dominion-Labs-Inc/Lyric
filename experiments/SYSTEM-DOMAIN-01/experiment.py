#!/usr/bin/env python3
"""SYSTEM-DOMAIN-01 — the domain authority, alone, on the live substrate.

One authority (`UniversalDomainMaster`, reached through
`get_universal_domain_master`). A domain comes into existence once, competence
evidence moves its progress, a gap is detected against what it holds, and the
domain is removed afterwards.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-DOMAIN-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

DOMAIN = "isolation_probe_domain"
EV = RunRecord(
    "SYSTEM-DOMAIN-01",
    claim=("Domains have one authority: a domain comes into existence once and idempotently, "
           "competence evidence moves its learning progress, a knowledge gap is detected "
           "against what it holds, and every public method is reached."),
    hypothesis=("Two domain masters, a domain created twice, progress that did not move, "
                "or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    try:
        from core.integration.universal_domain_master import get_universal_domain_master
        UDM = get_universal_domain_master()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="domain", cls="UniversalDomainMaster",
                        path="core/integration/universal_domain_master.py",
                        held=coord.universal_domain_master, reached=UDM)

        print("\n== B. A domain comes into existence once ==")
        before = {getattr(x, "domain_id", None) for x in await UDM.learned_domains()}
        dom = await UDM.ensure_domain(DOMAIN, name="Isolation Probe", description="SYSTEM-DOMAIN-01 probe")
        check("ensure_domain returns the domain", getattr(dom, "domain_id", None) == DOMAIN,
              f"{type(dom).__name__} id={getattr(dom, 'domain_id', None)}")
        again = await UDM.ensure_domain(DOMAIN)
        check("a second call returns the same domain, not a second one", again is dom or
              getattr(again, "domain_id", None) == DOMAIN)
        row = await d.execute_query("SELECT count(*) n FROM unified.domains WHERE domain_id = $1", (DOMAIN,),
                                    fetch_one=True)
        check("exactly one durable row", row is not None and int(row["n"]) == 1, f"rows={row and row['n']}")
        after = {getattr(x, "domain_id", None) for x in await UDM.learned_domains()}
        check("it is a learned domain, and the others are untouched",
              DOMAIN in after and after - {DOMAIN} == before - {DOMAIN},
              f"learned={len(after)} (was {len(before)})")

        print("\n== C. Competence evidence moves progress ==")
        # Learning progress is a signed RATE (the derivative of competence over
        # a window), and a domain with too little history reads optimistic
        # (`OPTIMISTIC_PROGRESS`), so it is tried before it is judged.
        p0 = UDM.learning_progress(DOMAIN)
        check("a fresh domain reads optimistic, not zero", p0 == UDM.OPTIMISTIC_PROGRESS, f"{p0}")
        for _ in range(4):
            await UDM.record_competence_evidence(DOMAIN, learned=True)
        p1 = UDM.learning_progress(DOMAIN)
        check("learned outcomes make progress positive", 0 < p1 < UDM.OPTIMISTIC_PROGRESS, f"{p0} -> {p1}")
        for _ in range(4):
            await UDM.record_competence_evidence(DOMAIN, learned=False)
        p2 = UDM.learning_progress(DOMAIN)
        check("failed outcomes turn it negative", p2 < 0, f"{p1} -> {p2}")

        print("\n== D. It knows what it does not know ==")
        # A gap is LOCALIZED: a concept the domain holds, lacking a relation. A
        # subject the domain does not hold is a different question and is None.
        check("a subject the domain does not hold is not a gap in it",
              await UDM.detect_knowledge_gap(DOMAIN, "isoprobe_widget", "isa") is None)
        reg = await UDM._registry()
        rich = next(((did, c) for did, dom in reg.domains.items() for c in dom.concepts.values()
                     if getattr(c, "name", None)), None)
        if rich is None:
            check("a held concept lacking a relation is registered as a known unknown", False,
                  "no domain holds a concept to ask about")
        else:
            did, concept = rich
            gap = await UDM.detect_knowledge_gap(did, concept.name, "isoprobe_relation_qzx")
            check("a held concept lacking a relation is registered as a known unknown",
                  gap is not None and getattr(gap, "unknown_id", None),
                  f"domain={did} subject={concept.name} -> {getattr(gap, 'question', gap)}")
            if gap is not None:
                from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                get_uncertainty_system().known_unknowns.pop(gap.unknown_id, None)
                await d.execute_query("DELETE FROM unified.known_unknowns WHERE unknown_id = $1", (gap.unknown_id,))
        sim = await UDM.similar_domains(DOMAIN, threshold=0.5)
        check("nothing is strongly similar to an empty domain", isinstance(sim, list) and len(sim) == 0,
              f"{len(sim)} at >= 0.5")
        stats = await UDM.get_statistics()
        check("statistics are a dict", isinstance(stats, dict) and bool(stats), f"keys={sorted(stats)[:8]}")
    finally:
        try:
            reg = await UDM._registry()
            reg.domains.pop(DOMAIN, None)
            for t, col in (("domain_controllability", "domain_id"), ("concept_domains", "domain"),
                           ("knowledge_updates", "domain"), ("beliefs", "domain")):
                try:
                    await d.execute_query(f"DELETE FROM unified.{t} WHERE {col} = $1", (DOMAIN,))
                except Exception:
                    pass
            comp = [r["belief_id"] for r in await d.execute_query(
                "SELECT belief_id FROM unified.beliefs WHERE claim LIKE $1", (f"%{DOMAIN}%",))]
            if comp:
                await d.execute_query("DELETE FROM unified.beliefs WHERE belief_id = ANY($1::text[])", (comp,))
                try:
                    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
                    for bid in comp:
                        get_uncertainty_system().beliefs.pop(bid, None)
                except Exception:
                    pass
            await d.execute_query("DELETE FROM unified.domains WHERE domain_id = $1", (DOMAIN,))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.domains WHERE domain_id = $1) + "
                "(SELECT count(*) FROM unified.beliefs WHERE claim LIKE $2) n", (DOMAIN, f"%{DOMAIN}%"),
                fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-DOMAIN-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
