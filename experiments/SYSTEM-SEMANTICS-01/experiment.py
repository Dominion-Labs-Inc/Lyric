#!/usr/bin/env python3
"""SYSTEM-SEMANTICS-01 — the semantic write door, alone, on the live substrate.

One authority for admitting what the substrate is told (`CognitiveIngress`,
reached through `get_cognitive_ingress`). A relation is admitted once, a repeat
is already present, an unrepresentable term is refused, a conditional becomes a
held rule that the store returns. Everything written is removed by id.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-SEMANTICS-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

DOMAIN = "isolation_probe_semantics"
EV = RunRecord(
    "SYSTEM-SEMANTICS-01",
    claim=("Admitting a proposition has one door: a relation enters the concept graph once, "
           "a repeat is reported already present, an unrepresentable term is refused, and a "
           "taught conditional is held as a rule the store gives back."),
    hypothesis=("A second ingress, a relation admitted twice, a guess admitted for a term it "
                "cannot represent, or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    memories = set()
    try:
        from core.semantics.cognitive_ingress import Provenance, get_cognitive_ingress
        ING = get_cognitive_ingress()
        prov = Provenance(producer="experiment", source_id="SYSTEM-SEMANTICS-01",
                          source_type="USER_SUPPLIED")

        print("\n== A. One authority, and it is called ==")
        # The coordinator reaches the ingress through the learning authority; the
        # module singleton is the only instance there is.
        authority_audit(EV, check, system="semantics", cls="CognitiveIngress",
                        path="core/semantics/cognitive_ingress.py",
                        held=get_cognitive_ingress(), reached=ING)

        print("\n== B. A relation enters once ==")
        a = await ING.admit_relation(subject="isoprobe_kestrel", relation="isa", obj="isoprobe_raptor",
                                     surface="an isoprobe kestrel is an isoprobe raptor",
                                     provenance=prov, domain=DOMAIN)
        if getattr(a, "memory_id", None):
            memories.add(a.memory_id)
        check("the relation is admitted", bool(a.admitted),
              f"created={a.concepts_created} reinforced={a.concepts_reinforced} refusals={a.refusals}")
        edge = await d.execute_query(
            "SELECT count(*) n FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON cr.source_concept_id = c.concept_id WHERE c.name = 'isoprobe_kestrel' AND cr.relation = 'isa'",
            (), fetch_one=True)
        check("one isa edge in the graph", edge is not None and int(edge["n"]) == 1, f"edges={edge and edge['n']}")
        b = await ING.admit_relation(subject="isoprobe_kestrel", relation="isa", obj="isoprobe_raptor",
                                     surface="an isoprobe kestrel is an isoprobe raptor",
                                     provenance=prov, domain=DOMAIN)
        if getattr(b, "memory_id", None):
            memories.add(b.memory_id)
        edge2 = await d.execute_query(
            "SELECT count(*) n FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON cr.source_concept_id = c.concept_id WHERE c.name = 'isoprobe_kestrel' AND cr.relation = 'isa'",
            (), fetch_one=True)
        check("a repeat is already present and adds no edge",
              (b.already_present or not b.concepts_created) and int(edge2["n"]) == 1,
              f"already_present={b.already_present} edges={edge2['n']}")

        print("\n== C. What cannot be represented is refused ==")
        try:
            c = await ING.admit_relation(subject="", relation="isa", obj="isoprobe_raptor",
                                         surface="is an isoprobe raptor", provenance=prov, domain=DOMAIN)
            refused, detail = not c.admitted, f"admitted={c.admitted} refusals={c.refusals}"
        except (ValueError, TypeError) as e:
            refused, detail = True, f"raised {type(e).__name__}"
        check("an empty subject is refused", refused, detail)

        print("\n== D. A conditional is held as a rule ==")
        before = len(await ING.held_conditionals(DOMAIN))
        r = await ING.admit_conditional(
            {"subject": "isoprobe_kestrel", "relation": "isa", "object": "isoprobe_raptor"},
            {"subject": "isoprobe_kestrel", "relation": "has", "object": "isoprobe_talons"},
            surface="if an isoprobe kestrel is an isoprobe raptor then it has isoprobe talons",
            provenance=prov, domain=DOMAIN)
        if getattr(r, "memory_id", None):
            memories.add(r.memory_id)
        held = await ING.held_conditionals(DOMAIN)
        check("the conditional is admitted and held", bool(r.admitted) and len(held) == before + 1,
              f"admitted={r.admitted} held={len(held)} (was {before})")
        r2 = await ING.admit_conditional(
            {"subject": "isoprobe_kestrel", "relation": "isa", "object": "isoprobe_raptor"},
            {"subject": "isoprobe_kestrel", "relation": "has", "object": "isoprobe_talons"},
            surface="if an isoprobe kestrel is an isoprobe raptor then it has isoprobe talons",
            provenance=prov, domain=DOMAIN)
        if getattr(r2, "memory_id", None):
            memories.add(r2.memory_id)
        check("telling it the same rule again holds it once",
              len(await ING.held_conditionals(DOMAIN)) == before + 1)
    finally:
        try:
            for mid in memories:
                await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,))
            await d.execute_query("DELETE FROM unified.held_conditionals WHERE domain = $1", (DOMAIN,))
            ids = [x["concept_id"] for x in await d.execute_query(
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
            for t, col in (("knowledge_updates", "domain"), ("beliefs", "domain")):
                try:
                    await d.execute_query(f"DELETE FROM unified.{t} WHERE {col} = $1", (DOMAIN,))
                except Exception:
                    pass
            # The evidence envelopes this run's provenance stamped, and every row
            # that cites one -- a reinforced SHARED concept keeps its evidence
            # row after the probe's own concepts are gone.
            envelopes = [r["evidence_id"] for r in await d.execute_query(
                "SELECT evidence_id FROM unified.evidence_envelopes "
                "WHERE producer = 'experiment' AND source_id = $1", ('SYSTEM-SEMANTICS-01',)) or []]
            if envelopes:
                for t in ("concept_relations", "concept_domains", "concept_evidence"):
                    await d.execute_query(
                        f"DELETE FROM unified.{t} WHERE evidence_id = ANY($1::text[])", (envelopes,))
                await d.execute_query(
                    "DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                    (envelopes,))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE 'isoprobe_%') + "
                "(SELECT count(*) FROM unified.held_conditionals WHERE domain = $1) + "
                "(SELECT count(*) FROM unified.evidence_envelopes WHERE producer = 'experiment' "
                "AND source_id = 'SYSTEM-SEMANTICS-01') n", (DOMAIN,), fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-SEMANTICS-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
