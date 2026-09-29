"""ACTOR-IDENTITY-01 — a conversation scopes to the VERIFIED identity, not the session.

"Fix actor": the actor a told fact is scoped to is now a World Auth identity (resolved through
the one owner, `actor_for`), not the ephemeral session string. This proves:

  1. `Conversation._actor` returns the bound identity (via actor_for) when a person is
     authenticated, and falls back to the session when no identity is bound — NEVER the
     substrate. Talking is not teaching: the one shared mind is reachable only through the
     learning door, and a thread that IS the substrate's own work says so with its SOURCE.
  2. A user may not masquerade as the substrate: binding the substrate's actor id raises.
  3. END-TO-END: teaching through a conversation bound to a World Auth identity lands the fact
     in THAT identity's scoped context — and NOT under the session string. So the same person
     is one context across sessions/devices, and the session is no longer the scope key.

Real learning authority + real scoped store. No stubs.

Run: ./venv_lyric/bin/python3 experiments/ACTOR-IDENTITY-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.database import get_database_manager
    from core.agents.autonomous.autonomous_coordinator import Conversation, get_conversation
    from core.agents.autonomous.shared_types import (
        actor_for, TaskSource, SUBSTRATE_ACTOR, is_substrate_actor)
    from core.learning.unified_learning_system import get_unified_learning_system
    from core.learning.scoped_context_store import get_scoped_context_store, scoped_claim_key

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    store = get_scoped_context_store()
    await store.beliefs_for_actor("__warmup__")

    nonce = uuid.uuid4().hex[:8]
    user_id = f"wa-user-{nonce}"      # a World Auth user id
    session = f"sess-{nonce}"         # a thread of talk
    SUBJ = f"florble{nonce}"

    print("\n== 1. _actor resolves the bound identity, else the session ==")
    bound = Conversation(session=session, actor_identity=user_id)
    check("a bound conversation's actor IS the identity (via actor_for)",
          bound._actor == actor_for(TaskSource.MANUAL, user_id) == user_id,
          f"_actor={bound._actor}")
    anon = Conversation(session=session)
    check("an UNBOUND conversation scopes to its SESSION — never the substrate",
          anon._actor == session and anon._actor != SUBSTRATE_ACTOR,
          f"_actor={anon._actor}")
    check("NO conversation can be the substrate: every MANUAL thread is a user actor",
          not is_substrate_actor(anon._actor) and not is_substrate_actor(bound._actor))
    own = Conversation(session="knowledge:t1", source=TaskSource.AUTONOMOUS)
    check("the substrate's OWN work (AUTONOMOUS source) is the shared mind",
          own._actor == SUBSTRATE_ACTOR, f"_actor={own._actor}")

    print("\n== 2. a user may not masquerade as the substrate ==")
    raised = False
    try:
        Conversation(session=session, actor_identity=SUBSTRATE_ACTOR)._actor
    except ValueError:
        raised = True
    check("binding the substrate actor id raises (no user writes the shared mind)", raised)

    print("\n== 3. END-TO-END: teaching scopes to the IDENTITY, not the session ==")
    conv = get_conversation(session, actor_identity=user_id)
    conv._learning = get_unified_learning_system()

    async def cleanup():
        for a in (user_id, session, "__warmup__"):
            await db.execute_query("DELETE FROM unified.scoped_beliefs WHERE scope_actor = $1",
                                   (a,), commit=True)
            await db.execute_query("DELETE FROM unified.scoped_concept_relations WHERE scope_actor = $1",
                                   (a,), commit=True)
    await cleanup()
    try:
        acquired = await conv.teach(f"a {SUBJ} is a gadget")
        check("the sentence was taught", bool(acquired))
        id_beliefs = await store.beliefs_for_actor(user_id)
        about_subj = [b for b in id_beliefs if SUBJ in scoped_claim_key(b["claim"])]
        check("the fact is in the IDENTITY's scoped context",
              len(about_subj) == 1 and about_subj[0]["posterior"] > 0.5,
              f"identity beliefs={[b['claim'] for b in id_beliefs]}")
        sess_beliefs = await store.beliefs_for_actor(session)
        check("NOTHING is scoped under the bare session string (actor is the identity)",
              all(SUBJ not in scoped_claim_key(b["claim"]) for b in sess_beliefs),
              f"session beliefs={[b['claim'] for b in sess_beliefs]}")
    finally:
        await cleanup()

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
