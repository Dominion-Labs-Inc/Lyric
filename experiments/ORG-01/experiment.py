#!/usr/bin/env python3
"""ORG-01 — a person's Shared World Context is composed; work belongs to the organization.

The rule (docs/research/SEPARATION_MAP.md §11.13): what Lyric may reason over for one person is World Knowledge,
their Personal Context, and the Work Context of each organization they are authorized for, each kept where its
owner keeps it and composed when Lyric works for them -- never copied or merged. Ownership follows identity,
authorization and organizational context, never the device. Coworkers share their organization's Work Context and
never each other's Personal Context. A person who leaves takes the Work Context out of their composition; it stays
the organization's.

  A  AUTHORIZED     a verified person's request through their work context authorizes that organization's Work
                    Context for them; their other instances (another session, no context) resolve to the same
                    composition; Lyric's own work composes only its own
  B  OWNED          what they tell at work is held under the organization, what they tell personally under them
  C  COMPOSED       a coworker authorized for the organization is answered from its Work Context and not from the
                    person's Personal Context; an outsider from neither
  D  MEMORIES       a memory made at work is the organization's: found by the person and the coworker, not by the
                    outsider; a personal memory by the person alone
  E  UNLINKED       unlinked, the person is no longer answered from the Work Context nor finds its memories, still
                    has their Personal Context, and the organization keeps everything: the coworker is still answered
  F  REFUSED        a work context, or an unlink, without a verified identity is refused

Run on the sandbox; every word carries the run's nonce, and everything is removed after.

Run: ./venv_lyric/bin/python3 experiments/ORG-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

from experiments import _separation as sep  # noqa: E402
from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

N = sep.nonce()
ORG = f"org01-northwind-{N}"
ANA, BEN, CAL = (f"org01-{name}-{N}" for name in ("ana", "ben", "cal"))
WORK = f"org:{ORG}"

EV = RunRecord(
    "ORG-01",
    claim=("A person's Shared World Context is composed of World Knowledge, their Personal Context and the Work "
           "Context of each organization they are authorized for; work belongs to the organization, coworkers share "
           "it and never each other's personal context, and unlinking removes it from the person while the "
           "organization keeps it."),
    hypothesis=("Work held under the person, a coworker not answered from it, an outsider answered from it, a "
                "personal fact reaching a coworker, an unlinked person still answered from it, the organization "
                "losing it on unlink, or an unverified work context accepted would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
    from core.agents.memory_agent import memory_agent
    from core.memory import Origin
    from core.memory.utils.interfaces import MemoryType, Telling
    from core.reasoning.concept_graph_reasoning import answer_over_graph
    from core.reasoning.relation_algebra import TRUE
    from core.semantics.derived_reader import MeaningFact
    from core.semantics.relation_types import SemanticRelation

    system, coord = await boot()
    d = db()
    memory = memory_agent()

    def front(person, session, **more):
        return {"actor_identity": person, "session_id": session, **more}

    async def answered(subject, obj, actor):
        return (await answer_over_graph(d, subject, SemanticRelation.ISA, obj, actor=actor)).verdict == TRUE

    async def found(marker, actor):
        return [m.memory_id for m in await memory.postgres_storage.search_by_content(marker, actor=actor, limit=20)]

    try:
        where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        check("the run is in the sandbox", where["d"] == "lyric_dev", where["d"])

        print("\n== A. Authorized ==")
        await coord.handle_user_request("Hello.", source="api",
                                        metadata=front(ANA, f"{ANA}-phone", context="work", organization=ORG))
        composed = await memory.shared_world_context(ANA)
        check("a verified request through her work context authorizes the organization's Work Context",
              composed == (SUBSTRATE_ACTOR, ANA, WORK), f"{composed}")
        await coord.handle_user_request("Hello.", source="api", metadata=front(ANA, f"{ANA}-web"))
        check("another instance of hers, with no context said, resolves to the same composition",
              await memory.shared_world_context(ANA) == composed)
        await memory.authorize_work(BEN, ORG)
        check("an outsider composes no Work Context, and Lyric's own work only its own",
              await memory.shared_world_context(CAL) == (SUBSTRATE_ACTOR, CAL)
              and await memory.shared_world_context(None) == (SUBSTRATE_ACTOR,))

        print("\n== B. Owned ==")
        at_work = Origin.of(ANA, "conversation", context="work", organization=ORG)
        personal = Origin.of(ANA, "conversation")
        await memory.take_in_telling(Telling(
            sentence=f"Vpn{N} is a network.", origin=at_work, facts=(MeaningFact("isa", f"Vpn{N}", "network"),),
            speaker=ANA, names=frozenset({f"Vpn{N}"})))
        await memory.take_in_telling(Telling(
            sentence=f"Rex{N} is a dog.", origin=personal, facts=(MeaningFact("isa", f"Rex{N}", "dog"),),
            speaker=ANA, names=frozenset({f"Rex{N}"})))
        held_work = await sep.in_context(d, WORK, f"Vpn{N}", "isa", "network")
        check("what she tells at work is held under the organization, not her",
              held_work == {"context": "work", "organization": ORG}
              and await sep.in_context(d, ANA, f"Vpn{N}", "isa", "network") is None, f"{held_work}")
        check("what she tells personally is held under her",
              await sep.in_context(d, ANA, f"Rex{N}", "isa", "dog") == {"context": "personal", "organization": None})

        print("\n== C. Composed ==")
        check("she is answered from both", await answered(f"Vpn{N}", "network", ANA)
              and await answered(f"Rex{N}", "dog", ANA))
        check("her coworker is answered from the Work Context", await answered(f"Vpn{N}", "network", BEN))
        check("and never from her Personal Context", not await answered(f"Rex{N}", "dog", BEN))
        check("an outsider is answered from neither", not await answered(f"Vpn{N}", "network", CAL)
              and not await answered(f"Rex{N}", "dog", CAL))

        print("\n== D. Memories ==")
        _, work_memory = await memory.store_memory(
            content=f"Wm{N}: the badge reader on floor two is replaced on Friday.", origin=at_work,
            memory_type=MemoryType.EPISODIC, importance_score=0.9, tags=["org01"])
        _, own_memory = await memory.store_memory(
            content=f"Pm{N}: dentist on Thursday.", origin=personal,
            memory_type=MemoryType.EPISODIC, importance_score=0.9, tags=["org01"])
        await memory.drain_writes()
        owner = await d.execute_query("SELECT user_id FROM memory_hot.memory_hot WHERE memory_id = $1",
                                      (work_memory,), fetch_one=True)
        check("a memory made at work is the organization's", owner and owner["user_id"] == WORK, f"{owner}")
        check("found by her and her coworker, not by the outsider",
              work_memory in await found(f"Wm{N}", ANA) and work_memory in await found(f"Wm{N}", BEN)
              and work_memory not in await found(f"Wm{N}", CAL))
        check("her personal memory is found by her alone",
              own_memory in await found(f"Pm{N}", ANA) and own_memory not in await found(f"Pm{N}", BEN)
              and own_memory not in await found(f"Pm{N}", CAL))

        print("\n== E. Unlinked ==")
        left = await coord.handle_user_request("", source="api",
                                               metadata=front(ANA, f"{ANA}-web", unlink_work=ORG))
        check("unlinking through the front door", left.get("kind") == "unlinked" and left.get("was_authorized"),
              f"{left}")
        check("the Work Context is out of her composition",
              await memory.shared_world_context(ANA) == (SUBSTRATE_ACTOR, ANA))
        check("she is no longer answered from it, nor finds its memories",
              not await answered(f"Vpn{N}", "network", ANA) and work_memory not in await found(f"Wm{N}", ANA))
        check("she keeps her Personal Context", await answered(f"Rex{N}", "dog", ANA)
              and own_memory in await found(f"Pm{N}", ANA))
        check("the organization keeps everything: held under it, and her coworker still answered and finding it",
              await sep.in_context(d, WORK, f"Vpn{N}", "isa", "network") is not None
              and await answered(f"Vpn{N}", "network", BEN) and work_memory in await found(f"Wm{N}", BEN))

        print("\n== F. Refused ==")
        anonymous = await coord.handle_user_request(
            "Hello.", source="api", metadata={"session_id": f"org01-anon-{N}", "context": "work",
                                              "organization": ORG})
        check("a work context without a verified identity is refused", anonymous.get("kind") == "refused",
              f"{anonymous}")
        unverified = await coord.handle_user_request(
            "", source="api", metadata={"session_id": f"org01-anon-{N}", "unlink_work": ORG})
        check("an unlink without a verified identity is refused", unverified.get("kind") == "refused",
              f"{unverified}")
    finally:
        owners = [ANA, BEN, CAL, WORK]
        removed = await sep.clean(d, N, owners, "org01")
        await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE user_id = ANY($1::text[])", (owners,))
        await d.execute_query("DELETE FROM unified.experience_pool WHERE owner = ANY($1::text[])", (owners,))
        await d.execute_query("DELETE FROM unified.work_authorizations WHERE organization = $1", (ORG,))
        # The front door's requests are jobs on the queue too ("Hello." is work it was asked for).
        await d.execute_query("DELETE FROM unified.task_queue WHERE payload::text LIKE $1", (f"%org01-%-{N}%",))
        EV.metric("rows_removed", sum(removed.values()), "count", f"{removed}")
        await shutdown(system)

    passed = sum(results)
    print(f"\n==== ORG-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
