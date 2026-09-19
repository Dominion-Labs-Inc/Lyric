"""SELF-PARTITION-01 — the self splits into one shared mind + isolated per-actor context.

Pass 1 (write isolation + promotion). Proves the learning-intake ROUTER:

  1. The substrate's OWN learning (substrate actor) enters the SHARED concept graph
     (the reasoner walks it for everyone) AND moves the UNIVERSAL belief — and writes
     NO scoped row. This is the one mind that ships in a snapshot.
  2. A USER's telling touches NEITHER the shared graph NOR the universal beliefs — it
     is held only in that user's scoped context layer (edge + belief). This is the
     leak being closed: a user cannot write the one mind, not even its graph.
  3. Context is isolated: actor A's scoped belief is invisible to actor B.
  4. The PROMOTION gate: when a SECOND, INDEPENDENT actor is told the same thing, the
     claim is corroborated and lifted into the shared graph + universal belief — once.
  5. The universal reads never surface a scoped-only claim.

Real Postgres, the real learning authority, the real belief graph, the real concept
graph. No stubs.

Run: ./venv_torin/bin/python3 experiments/SELF-PARTITION-01/experiment.py
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
    from core.learning.unified_learning_system import get_unified_learning_system
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.learning.scoped_context_store import (get_scoped_context_store,
                                                   scoped_claim_key)
    from core.reasoning.concept_graph_reasoning import (instance_predicates,
                                                       answer_over_graph)
    from core.semantics.relation_types import SemanticRelation
    from core.reasoning.relation_algebra import TRUE, UNKNOWN

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    learn = get_unified_learning_system()
    us = get_uncertainty_system()
    store = get_scoped_context_store()

    nonce = uuid.uuid4().hex[:8]
    domain = f"partition_probe_{nonce}"
    alice = f"user:alice:{nonce}"
    bob = f"user:bob:{nonce}"
    SUBJ_U = f"zorptl{nonce}"      # substrate learns this (shared mind)
    SUBJ_C = f"quibnar{nonce}"     # a user teaches this (context only)
    SUBJ_P = f"fendril{nonce}"     # two users teach this (promotes)
    MID = f"blitzn{nonce}"         # shared middle class (substrate-taught)
    SUP = f"vorq{nonce}"           # shared super class (substrate-taught)

    def claim(subj):
        return f"{subj} isa gadget"

    await store.beliefs_for_actor("__warmup__")  # force scoped schema to exist

    async def cleanup():
        for a in (alice, bob, "__warmup__"):
            await db.execute_query("DELETE FROM unified.scoped_beliefs WHERE scope_actor = $1",
                                   (a,), commit=True)
            await db.execute_query("DELETE FROM unified.scoped_concept_relations WHERE scope_actor = $1",
                                   (a,), commit=True)
        for c in (claim(SUBJ_U), claim(SUBJ_C), claim(SUBJ_P), f"{MID} isa {SUP}"):
            await db.execute_query("DELETE FROM unified.beliefs WHERE claim = $1",
                                   (c,), commit=True)
        # Shared concept graph: remove the synthetic subjects that reached it.
        names = [SUBJ_U, SUBJ_P, MID, SUP]
        await db.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id IN "
            "(SELECT concept_id FROM unified.concepts WHERE name = ANY($1))",
            (names,), commit=True)
        await db.execute_query("DELETE FROM unified.concepts WHERE name = ANY($1)",
                               (names,), commit=True)

    await cleanup()
    try:
        print("\n== 1. Substrate's own learning -> SHARED graph + UNIVERSAL belief, no scoped row ==")
        adm = await learn.learn_fact(SUBJ_U, "isa", "gadget", domain=domain, quality=0.9, actor=None)
        check("substrate fact admitted", getattr(adm, "admitted", False))
        u_bel = us.belief_for_claim(claim(SUBJ_U))
        check("UNIVERSAL belief moved", u_bel is not None and u_bel.posterior_probability > 0.5)
        preds = await instance_predicates(db, SUBJ_U)
        check("the SHARED concept graph has the edge (reasoner can walk it)", "gadget" in preds,
              f"instance_predicates={preds}")
        srow = await db.execute_query(
            "SELECT count(*) AS n FROM unified.scoped_beliefs WHERE claim_key = $1",
            (scoped_claim_key(claim(SUBJ_U)),), fetch_one=True)
        check("NO scoped row for substrate learning", srow["n"] == 0)

        print("\n== 2. A user's telling -> scoped context ONLY; shared graph + beliefs untouched ==")
        adm = await learn.learn_fact(SUBJ_C, "isa", "gadget", domain=domain, quality=0.9, actor=alice)
        check("user fact admitted (to the scoped layer)", getattr(adm, "admitted", False))
        check("NO universal belief created", us.belief_for_claim(claim(SUBJ_C)) is None)
        preds_c = await instance_predicates(db, SUBJ_C)
        check("NO edge in the SHARED concept graph (the leak is closed at the graph)",
              "gadget" not in preds_c, f"instance_predicates={preds_c}")
        a_held = [b for b in await store.beliefs_for_actor(alice) if b["claim"] == claim(SUBJ_C)]
        check("a SCOPED belief exists for the user", len(a_held) == 1 and a_held[0]["posterior"] > 0.5)
        a_edges = await store.edges_for_actor(alice, [SUBJ_C])
        check("a SCOPED edge exists for the user", len(a_edges) == 1 and a_edges[0]["obj"] == "gadget")

        print("\n== 3. Context is isolated: Alice's belief is invisible to Bob ==")
        b_beliefs = await store.beliefs_for_actor(bob)
        check("Bob's context does NOT contain Alice's belief",
              all(b["claim"] != claim(SUBJ_C) for b in b_beliefs))

        print("\n== 4. Promotion gate: an INDEPENDENT actor corroborates -> lifted to the one mind ==")
        await learn.learn_fact(SUBJ_P, "isa", "gadget", domain=domain, quality=0.9, actor=alice)
        check("after ONE actor: not in the universal belief", us.belief_for_claim(claim(SUBJ_P)) is None)
        check("after ONE actor: not in the shared graph", "gadget" not in await instance_predicates(db, SUBJ_P))
        await learn.learn_fact(SUBJ_P, "isa", "gadget", domain=domain, quality=0.9, actor=bob)
        promoted = us.belief_for_claim(claim(SUBJ_P))
        check("after a SECOND independent actor: promoted to the UNIVERSAL belief",
              promoted is not None and promoted.posterior_probability > 0.5)
        check("after promotion: now in the SHARED concept graph too",
              "gadget" in await instance_predicates(db, SUBJ_P))
        check("the claim is flagged promoted (lifted once, not per telling)",
              await store.is_promoted(claim(SUBJ_P)))

        print("\n== 5. Universal reasoning never sees scoped-only context ==")
        check("belief_for_claim does not return the scoped-only claim",
              us.belief_for_claim(claim(SUBJ_C)) is None)
        dom_claims = {b["claim"] for b in us.beliefs_for_domain(domain, limit=50)}
        check("beliefs_for_domain excludes the scoped-only claim", claim(SUBJ_C) not in dom_claims)
        check("beliefs_for_domain includes the substrate-learned + promoted claims",
              claim(SUBJ_U) in dom_claims and claim(SUBJ_P) in dom_claims, f"domain={sorted(dom_claims)}")

        print("\n== 6. OVERLAY READ: the substrate chains a user's context WITH the shared graph, for that user only ==")
        # Shared mind knows MID isa SUP. Alice (scoped) is told SUBJ_C isa MID.
        await learn.learn_fact(MID, "isa", SUP, domain=domain, quality=0.9, actor=None)
        await learn.learn_fact(SUBJ_C, "isa", MID, domain=domain, quality=0.9, actor=alice)
        # Acting FOR ALICE: chain her scoped (SUBJ_C->MID) onto shared (MID->SUP).
        a_ans = await answer_over_graph(db, SUBJ_C, SemanticRelation.ISA, SUP, actor=alice)
        check("for the OWNER, the scoped fact chains onto the shared graph -> TRUE",
              a_ans.verdict == TRUE, f"verdict={a_ans.verdict}")
        # Acting FOR BOB: Alice's scoped edge is invisible, so no chain exists.
        b_ans = await answer_over_graph(db, SUBJ_C, SemanticRelation.ISA, SUP, actor=bob)
        check("for ANOTHER user, the chain does NOT exist -> not TRUE",
              b_ans.verdict != TRUE, f"verdict={b_ans.verdict}")
        # With NO actor (shared-mind reasoning), it is also invisible.
        n_ans = await answer_over_graph(db, SUBJ_C, SemanticRelation.ISA, SUP)
        check("for the SHARED mind (no actor), the scoped fact is invisible -> not TRUE",
              n_ans.verdict != TRUE, f"verdict={n_ans.verdict}")
        # instance_predicates overlay is actor-scoped too.
        check("instance_predicates overlays the owner's scoped feature",
              MID in await instance_predicates(db, SUBJ_C, actor=alice))
        check("instance_predicates hides it from another user",
              MID not in await instance_predicates(db, SUBJ_C, actor=bob))
    finally:
        await cleanup()

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
