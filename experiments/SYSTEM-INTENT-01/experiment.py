#!/usr/bin/env python3
"""SYSTEM-INTENT-01 — the intent authority, alone, on the live substrate.

One authority (`IntentAuthority`, reached through `get_intent_authority`). A
pursuit is formed once per (actor, continuity key), a return refreshes rather
than duplicates, reconciliation records its outcome, an unknown id is None, and
an actor can be forgotten. Everything written is removed by id.

Run: ./venv_torin/bin/python3 experiments/SYSTEM-INTENT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

ACTOR = "isoprobe_intent_actor"
EV = RunRecord(
    "SYSTEM-INTENT-01",
    claim=("Intent has one authority: a pursuit is formed once per actor and key, a return "
           "refreshes it, reconciliation records the outcome, an unknown id is None, and "
           "forgetting an actor removes that actor's pursuits."),
    hypothesis=("A second authority, a duplicate intent for one key, a fabricated intent "
                "for an unknown id, or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    ids = []
    try:
        from core.reasoning.intent_authority import get_intent_authority
        IA = get_intent_authority()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="intent", cls="IntentAuthority",
                        path="core/reasoning/intent_authority.py", held=get_intent_authority(), reached=IA)

        print("\n== B. Formed once, refreshed on return ==")
        i1 = await IA.form("question", ACTOR, "question:isoprobe-1", shape={"question": "isoprobe?"})
        ids.append(i1.intent_id)
        check("a pursuit is formed", i1.status in ("forming", "active") and i1.version == 1,
              f"id={i1.intent_id} status={i1.status} v{i1.version}")
        i2 = await IA.form("question", ACTOR, "question:isoprobe-1", shape={"question": "isoprobe?"})
        check("a return on the same key refreshes the same pursuit",
              i2.intent_id == i1.intent_id and i2.version >= i1.version,
              f"same_id={i2.intent_id == i1.intent_id} v{i1.version}->v{i2.version}")
        got = await IA.get(ACTOR, "question:isoprobe-1")
        check("it is found by actor and key", got is not None and got.intent_id == i1.intent_id)
        by_id = await IA.get_by_id(i1.intent_id, ACTOR)
        check("and by id", by_id is not None and by_id.intent_id == i1.intent_id)

        print("\n== C. Reconciled from the world ==")
        # `reconcile` returns None by contract; what it did is read back.
        await IA.reconcile(i1.intent_id, {"matched_aim": True, "success": True, "source": "SYSTEM-INTENT-01"})
        rec = await IA.get_by_id(i1.intent_id, ACTOR)
        check("reconciliation records the outcome and concludes the pursuit",
              rec is not None and rec.outcome is not None and rec.status not in ("forming", "active"),
              f"status={getattr(rec, 'status', None)} outcome={getattr(rec, 'outcome', None)}")
        row = await d.execute_query("SELECT status, outcome FROM unified.intents WHERE intent_id = $1",
                                    (i1.intent_id,), fetch_one=True)
        check("the outcome is durable", row is not None and row["outcome"] is not None,
              f"row={dict(row) if row else None}")

        print("\n== D. What it does not have, it says it does not have ==")
        check("an unknown id is None", await IA.get_by_id("intent_does_not_exist_qzx", ACTOR) is None)
        check("an unknown key is None", await IA.get(ACTOR, "question:never-asked") is None)

        print("\n== E. An actor can be forgotten ==")
        i3 = await IA.form("thread", ACTOR, "thread:isoprobe-2")
        ids.append(i3.intent_id)
        n = await IA.forget_actor(ACTOR)
        after = await IA.get(ACTOR, "thread:isoprobe-2")
        check("forgetting the actor removes that actor's pursuits", after is None, f"forgotten={n}")
        standing = await IA.standing(24)
        check("standing is the substrate-wide account (a dict)", isinstance(standing, dict) and bool(standing),
              f"keys={sorted(standing)[:8]}")
    finally:
        try:
            await d.execute_query("DELETE FROM unified.scoped_intents WHERE scope_actor = $1", (ACTOR,))
            if ids:
                await d.execute_query("DELETE FROM unified.scoped_intents WHERE intent_id = ANY($1::text[])", (ids,))
                await d.execute_query("DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])", (ids,))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.intents WHERE intent_id = ANY($1::text[])) + "
                "(SELECT count(*) FROM unified.scoped_intents WHERE scope_actor = $2) n", (ids, ACTOR), fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-INTENT-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
