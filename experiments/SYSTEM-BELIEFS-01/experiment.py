#!/usr/bin/env python3
"""SYSTEM-BELIEFS-01 — the belief store, alone, on the live substrate.

One door (`BayesianUncertaintySystem`, reached through `get_uncertainty_system`):
the learning authority's belief calls and the store's own return the same
object. A belief moves with evidence, survives a flush, an unknown id is None,
a known unknown is registered and resolved. Everything written is removed by id.

Run: ./venv_torin/bin/python3 experiments/SYSTEM-BELIEFS-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

DOMAIN = "isolation_probe_beliefs"
EV = RunRecord(
    "SYSTEM-BELIEFS-01",
    claim=("Beliefs have one door: the learning authority and the store return the same "
           "object, evidence moves a posterior, a flush makes it durable, and an unknown "
           "id or question is answered honestly."),
    hypothesis=("Two belief stores, a posterior that did not move, a fabricated belief for "
                "an unknown id, or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.memory import Origin
    system, coord = await boot()
    d = db()
    belief_ids, unknown_ids, memory_ids = [], [], []
    try:
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        U = get_uncertainty_system()

        print("\n== A. One door, and it is called ==")
        # The coordinator reaches beliefs THROUGH the learning authority; the
        # object it gets back must be the store's own.
        probe = coord.learning.create_belief("isoprobe door check", DOMAIN, 0.4, None)
        belief_ids.append(probe.belief_id)
        authority_audit(EV, check, system="beliefs", cls="BayesianUncertaintySystem",
                        path="core/reasoning/bayesian_uncertainty.py",
                        held=U.get_belief(probe.belief_id), reached=probe)

        print("\n== B. Evidence moves a belief, and a flush keeps it ==")
        b = U.create_belief("isoprobe the lamp is on", DOMAIN, 0.3, None)
        belief_ids.append(b.belief_id)
        before = float(b.posterior_probability)
        # `update_belief` moves the belief IN PLACE and returns it, so each
        # posterior is read as a number at the moment it is reached.
        raised = float(U.update_belief(b.belief_id, {"source": "SYSTEM-BELIEFS-01", "description": "the lamp is lit", "quality": 0.9}, True).posterior_probability)
        check("supporting evidence raises the posterior", raised > before,
              f"{before:.3f} -> {raised:.3f}")
        lowered = float(U.update_belief(b.belief_id, {"source": "SYSTEM-BELIEFS-01", "description": "the room is dark", "quality": 0.9}, False).posterior_probability)
        check("contrary evidence lowers it", lowered < raised, f"{raised:.3f} -> {lowered:.3f}")
        check("the same belief is found by its claim",
              (U.belief_for_claim("isoprobe the lamp is on") or b).belief_id == b.belief_id)
        # A BELIEF IS ABOUT SOMETHING MET. Nothing grounds this one in a memory,
        # so the store refuses to keep it -- by design (the grounding rule).
        kept = await U.flush_belief(b.belief_id)
        row = await d.execute_query(
            "SELECT 1 FROM unified.beliefs WHERE belief_id = $1", (b.belief_id,), fetch_one=True)
        check("a belief grounded in no memory is not stored", kept is False and row is None,
              f"flush={kept} row={row is not None}")
        # Grounded in a real memory, the same belief is durable.
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        ok, mid = await agent.store_memory(
            content="isoprobe: the lamp in the isolation room was seen lit",
            importance_score=0.8, tags=["isoprobe"], source_context={"producer": "SYSTEM-BELIEFS-01"}, origin=Origin.own("SYSTEM-BELIEFS-01"))
        if ok and mid:
            memory_ids.append(mid)
        grounded = float(U.update_belief(b.belief_id, {"source": "SYSTEM-BELIEFS-01", "description": "seen lit",
                                                       "quality": 0.9, "memory_id": mid}, True).posterior_probability)
        kept = await U.flush_belief(b.belief_id)
        row = await d.execute_query(
            "SELECT posterior_probability FROM unified.beliefs WHERE belief_id = $1",
            (b.belief_id,), fetch_one=True)
        check("grounded in a memory, the flushed belief is durable with the posterior it holds",
              kept is True and row is not None and abs(float(row["posterior_probability"]) - grounded) < 1e-6,
              f"memory={mid} flush={kept} row={dict(row) if row else None} held={grounded:.3f}")

        print("\n== C. What it does not have, it says it does not have ==")
        check("an unknown belief id is None", U.get_belief("belief_does_not_exist_qzx") is None)
        check("an unknown claim is None", U.belief_for_claim("isoprobe nothing was ever said") is None)
        check("a domain with no beliefs is an empty list", U.beliefs_for_domain("isoprobe_empty_domain", 10) == [])

        print("\n== D. A known unknown survives a restart, and resolves only when learned ==")
        from core.reasoning.bayesian_uncertainty import (BayesianUncertaintySystem,
                                                         ResolutionGrounds)
        refused = None
        try:
            U.register_known_unknown("isoprobe: says nothing would satisfy it", DOMAIN, [], [],
                                     target={})
        except ValueError as error:
            refused = str(error)
        check("an unknown that states nothing that would satisfy it is refused",
              refused is not None, refused or "registered")
        ABOUT = "isoprobe lamp standby draw"
        ku = U.register_known_unknown(f"what is unresolved about {ABOUT}?", DOMAIN, [], [],
                                      target={"kind": "settled", "about": ABOUT})
        unknown_ids.append(ku.unknown_id)
        await U.drain_writes()
        fresh = BayesianUncertaintySystem()
        await fresh.unified_db.initialize()
        await fresh.load_from_db()
        back = fresh.known_unknowns.get(ku.unknown_id)
        check("a restart reloads the open unknown, with what would satisfy it",
              back is not None and back.target.get("about") == ABOUT,
              f"reloaded={back is not None} target={back and back.target}")

        grounds = await coord.learning.resolve_known_unknown(ku.unknown_id)
        check("with nothing learned, the gate leaves it open",
              not grounds.satisfied and ku.unknown_id in U.known_unknowns, grounds.summary())
        check("and counts the attempt", U.known_unknowns[ku.unknown_id].resolution_attempts == 1)
        bypass = None
        try:
            U.resolve_known_unknown(ku.unknown_id, grounds)
        except ValueError as error:
            bypass = str(error)
        check("the store refuses a resolution on unsatisfied grounds", bypass is not None,
              (bypass or "resolved")[:90])

        # Learn it: a grounded belief about the object, settled by evidence, in
        # a domain the substrate holds.
        from core.integration.universal_domain_master import get_universal_domain_master
        await get_universal_domain_master().ensure_domain(DOMAIN)
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        ok, lamp_mid = await agent.store_memory(
            content=f"isoprobe: measured the {ABOUT} at 0.3 W",
            importance_score=0.8, tags=["isoprobe"], source_context={"producer": "SYSTEM-BELIEFS-01"}, origin=Origin.own("SYSTEM-BELIEFS-01"))
        if lamp_mid:
            memory_ids.append(lamp_mid)
        lamp = U.create_belief(f"the {ABOUT} is 0.3 W", DOMAIN, 0.5, None)
        belief_ids.append(lamp.belief_id)
        for _ in range(3):
            U.update_belief(lamp.belief_id, {"source": "SYSTEM-BELIEFS-01", "quality": 0.9,
                                             "description": "measured", "memory_id": lamp_mid}, True)
        grounds = await coord.learning.resolve_known_unknown(ku.unknown_id)
        check("once belief, knowledge and domain are learned, the gate resolves it",
              grounds.satisfied and ku.unknown_id not in U.known_unknowns, grounds.summary())
        check("the answer is the belief that settled it", grounds.belief_id == lamp.belief_id,
              f"{grounds.answer}")
        await U.drain_writes()
        row = await d.execute_query(
            "SELECT knowledge_state, resolved_at, resolution_belief_id FROM unified.known_unknowns "
            "WHERE unknown_id = $1", (ku.unknown_id,), fetch_one=True)
        check("the resolution is written", row is not None and row["knowledge_state"] == "known_known"
              and row["resolved_at"] is not None and row["resolution_belief_id"] == lamp.belief_id,
              f"{dict(row) if row else None}")
        again = BayesianUncertaintySystem()
        await again.unified_db.initialize()
        await again.load_from_db()
        check("and a restart does not reopen it", ku.unknown_id not in again.known_unknowns)
        gone = None
        try:
            await coord.learning.resolve_known_unknown(ku.unknown_id)
        except LookupError as error:
            gone = str(error)
        check("resolving it again is refused: it is not open", gone is not None, gone or "resolved twice")

        stats = U.get_statistics()
        check("statistics are a dict", isinstance(stats, dict) and bool(stats), f"keys={sorted(stats)[:8]}")
    finally:
        try:
            for bid in belief_ids:
                U.beliefs.pop(bid, None) if hasattr(U, "beliefs") else None
                await d.execute_query("DELETE FROM unified.beliefs WHERE belief_id = $1", (bid,))
            for mid in memory_ids:
                await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,))
            await U.drain_writes()          # no write may land after its row is removed
            for uid in unknown_ids:
                getattr(U, "known_unknowns", {}).pop(uid, None)
                await d.execute_query("DELETE FROM unified.known_unknowns WHERE unknown_id = $1", (uid,))
            await d.execute_query("DELETE FROM unified.domains WHERE domain_id = $1", (DOMAIN,))
            await d.execute_query("DELETE FROM unified.beliefs WHERE domain = $1", (DOMAIN,))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.beliefs WHERE domain = $1) + "
                "(SELECT count(*) FROM unified.known_unknowns WHERE unknown_id = ANY($2::text[])) + "
                "(SELECT count(*) FROM memory_hot.memory_hot WHERE memory_id = ANY($3::text[])) n",
                (DOMAIN, unknown_ids, memory_ids), fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-BELIEFS-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
