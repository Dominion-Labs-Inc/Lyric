"""FRONTDOOR-IDENTITY-01 — the substrate's front door binds the verified identity.

`handle_user_request` is the ONE door a user request enters by. The membrane authenticates the
crossing and the adapter puts the verified World Auth identity in `metadata["actor_identity"]`.
This proves the door threads that identity into the conversation it opens — so a fact learned from
this person is scoped to THEM, not the session — and falls back to the session when no verified
identity is present. (That a bound conversation then scopes teaching to the identity is
ACTOR-IDENTITY-01; this proves the front door does the binding.)

Run: ./venv_lyric/bin/python3 experiments/FRONTDOOR-IDENTITY-01/experiment.py
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
    from core.agents.autonomous.autonomous_coordinator import (
        create_autonomous_system, get_conversation)
    from core.agents.autonomous.shared_types import actor_for, TaskSource, SUBSTRATE_ACTOR
    from core.learning.unified_learning_system import get_unified_learning_system

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    # Build the coordinator WITHOUT booting its loops; wire the few things the
    # conversation faculty reads. learning = the real authority (so the actor
    # routing is the real path); emit/disposition absent is fine.
    coord = await create_autonomous_system({})
    coord.emit = None
    coord.learning = get_unified_learning_system()
    coord.disposition = None

    nonce = uuid.uuid4().hex[:8]
    user_id = f"wa-user-{nonce}"
    sess_auth = f"sess-auth-{nonce}"
    sess_anon = f"sess-anon-{nonce}"

    print("\n== 1. an AUTHENTICATED request binds the conversation to the identity ==")
    try:
        await coord.handle_user_request(
            f"a florble{nonce} is a gadget", source="api",
            metadata={"session_id": sess_auth, "actor_identity": user_id})
    except Exception as e:
        # The binding happens at the door, before any downstream work-path logic;
        # a later error there does not undo it. We assert the binding regardless.
        print(f"    (downstream work-path raised, ignored for this check: {e})")
    conv = get_conversation(sess_auth)
    check("the held conversation carries the verified identity",
          conv._actor_identity == user_id, f"_actor_identity={conv._actor_identity}")
    check("its actor resolves through actor_for to the identity (not the session)",
          conv._actor == actor_for(TaskSource.MANUAL, user_id) == user_id,
          f"_actor={conv._actor}")

    print("\n== 2. an UNAUTHENTICATED request is scoped to its session (never the shared mind) ==")
    try:
        await coord.handle_user_request(
            f"a wibble{nonce} is a gadget", source="api",
            metadata={"session_id": sess_anon})
    except Exception as e:
        print(f"    (downstream work-path raised, ignored for this check: {e})")
    conv2 = get_conversation(sess_anon)
    # the front door ALWAYS binds an actor: the session as a fail-safe scope, so an
    # unauthenticated external request is scoped (NOT the substrate/shared mind).
    check("the front door bound the session as the scope", conv2._actor_identity == sess_anon)
    check("its actor is the session scope, never the substrate",
          conv2._actor == sess_anon and conv2._actor != SUBSTRATE_ACTOR, f"_actor={conv2._actor}")

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
