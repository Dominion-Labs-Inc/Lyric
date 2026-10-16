#!/usr/bin/env python3
"""SYSTEM-CONVERSATION-01 — the conversation faculty, alone, on the live substrate.

The substrate holding a conversation (`Conversation`, reached through
`coord.conversation(session)`), as a SPEAKER meets it: everything is said to
it through `understand`, the one turn. A session is a user actor. What it is
told of names the world does not hold (this run's nonce words) is about that
speaker's own things, so it lands in their context, never the world
(docs/research/SEPARATION_MAP.md §11.3):

  * told, it is held in the speaker's context in the door's canonical terms,
    and nothing reaches the shared graph or beliefs;
  * asked back by the speaker it is answered from that context -- a two-word
    name, and a chain from a told fact onto the shared graph -- and the reply
    does not call the thing it just answered about unknown;
  * another speaker holds none of it;
  * a told conditional asserts neither of its sides;
  * a speaker's context refuses what the world's door refuses;
  * what was reasoned for the speaker is remembered as theirs, recallable by
    them and by no one else, by meaning or by wording.

Every run uses fresh nonce words and removes everything it wrote, so no run can
corroborate or answer from an earlier one.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-CONVERSATION-01/experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import string
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import ROOT, boot, callable_surface, db, outcome, shutdown  # noqa: E402

N = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
V = f"vex{N}"             # a kind word, for the conditional
G = f"glint{N}"
NAME = f"Vex{N}"          # a one-word name the world does not hold, told to be a mammal
TWO = f"Glint{N} Heron"   # a two-word name: `heron` is a shared word. Asked as written ("Is ... ?"): unpunctuated,
                          # "is Glint... Heron a glint... bird" also reads as Glint... having done a "Heron"
                          # (2026-10-07), and the listener does not yet choose by what the speaker told.
SESSION = f"SYSTEM-CONVERSATION-01-{N}"
EV = RunRecord(
    "SYSTEM-CONVERSATION-01",
    claim=("A conversation is a speaker's: what they tell is held in their context in the "
           "door's terms, answered back to them from it and to no one else, a conditional "
           "asserts neither side, and what is reasoned for them is remembered as theirs."),
    hypothesis=("A told name the speaker cannot ask back, a reply calling it unknown, another "
                "speaker answered from it, a conditional's clause held as fact, a "
                "refused telling held for the speaker, or an unowned memory of it would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def said(conversation, understanding) -> str:
    return type(conversation).say(understanding)


async def edges(d, actor):
    rows = await d.execute_query(
        "SELECT subj, rel, obj, polarity FROM unified.scoped_concept_relations "
        "WHERE scope_actor = $1", (actor,), fetch_all=True)
    return [(r["subj"], r["rel"], r["obj"], r["polarity"]) for r in (rows or [])]


async def world_knowledge(coord, d) -> bool:
    """THE PRECONDITION IS DECLARED, NOT ASSUMED. "Is a vex… an animal" is
    answered by chaining the speaker's "a vex… is a mammal" through what the
    substrate itself was taught: that a mammal is an animal. On an emptied store
    that was missing and the check failed as if the chain were broken. Taught
    here, to the shared mind, when it is not held."""
    held = await d.execute_query(
        "SELECT count(*) AS n FROM unified.concept_relations cr "
        "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
        "WHERE c.name = 'mammal' AND cr.relation = 'isa' "
        "AND cr.target_surface = 'animal' AND cr.polarity = 'positive'", (), fetch_one=True)
    if int(held["n"]):
        return True
    from core.learning.unified_learning_system import Evidence
    decision = await coord.learning.consider("mammal", "isa", "animal", domain="general", evidence=Evidence(
        source="experiment:SYSTEM-CONVERSATION-01", key="SYSTEM-CONVERSATION-01",
        source_type="IMPORTED_KNOWLEDGE", quality=0.9))
    return decision.admitted


async def main() -> int:
    system, coord = await boot()
    d = db()
    EV.metric("nonce", N)
    actors = []
    try:
        check("the substrate knows a mammal is an animal (held, or taught now)",
              await world_knowledge(coord, d))
        print("\n== A. One conversation per session, held by the substrate ==")
        A = coord.conversation(SESSION + "-a")
        check("the same session is the same held conversation",
              coord.conversation(SESSION + "-a") is A, type(A).__name__)
        B = coord.conversation(SESSION + "-b")
        check("a different session is a different one", B is not A)
        actors = [A._actor, B._actor]
        from core.agents.autonomous.shared_types import is_substrate_actor
        check("a session is a user actor, not the substrate",
              not is_substrate_actor(A._actor) and A._actor != B._actor, f"{actors}")
        callable_surface(EV, system="conversation", cls="Conversation",
                         path="core/agents/autonomous/autonomous_coordinator.py")

        print("\n== B. Told: held in the speaker's context, in the door's terms ==")
        for sentence in (f"{NAME} is a mammal.", f"{TWO} is a {G} bird."):
            u = await A.understand(sentence, look_up=False)
            print(f"    told {sentence!r} -> {said(A, u)[:90]!r}")
        held = await edges(d, A._actor)
        # IN THE DOOR'S TERMS: `normalize_term` singularises, so a nonce that
        # happens to end in "s" ("vexzzups") is held as "vexzzup".
        from core.semantics.cognitive_ingress import normalize_term
        check("the one-word telling is a scoped edge in canonical terms",
              (normalize_term(V), "isa", "mammal", "positive") in held, f"{held}")
        check("the two-word telling is a scoped edge in canonical terms",
              (f"{G}_heron", "isa", f"{G}_bird", "positive") in held, f"{held}")
        shared = await d.execute_query(
            "SELECT (SELECT count(*) FROM unified.concepts WHERE name ILIKE $1) + "
            "(SELECT count(*) FROM unified.beliefs WHERE claim ILIKE $1) AS n",
            (f"%{N}%",), fetch_one=True)
        check("nothing told reached the shared graph or beliefs", int(shared["n"]) == 0,
              f"shared rows={shared['n']}")

        print("\n== C. Asked back by the speaker, answered from their context ==")
        for question in (f"is {NAME} a mammal", f"is {NAME} an animal",
                         f"Is {TWO} a {G} bird?"):
            u = await A.understand(question, look_up=False)
            reply = said(A, u)
            check(f"{question!r} is affirmed", reply.lower().startswith("yes"), reply[:100])
            check(f"{question!r}: the reply does not call what it answered unknown",
                  "hold nothing for" not in reply.lower(), reply[:140])
        resolved = await A.resolve(f"Is {TWO} a {G} bird?")
        check("the two-word told name resolves whole, from the speaker's context",
              any(r.phrase.lower() == TWO.lower() and r.told for r in resolved),
              f"{[(r.phrase, r.known, bool(r.told)) for r in resolved]}")

        print("\n== D. Another speaker holds none of it ==")
        u = await B.understand(f"is {NAME} a mammal", look_up=False)
        reply = said(B, u)
        check("another speaker is not answered from the first one's context",
              not reply.lower().startswith("yes"), reply[:100])
        resolved = await B.resolve(f"Is {TWO} a {G} bird?")
        check("another speaker resolves nothing the first one told",
              not any(r.told for r in resolved),
              f"{[(r.phrase, r.known, bool(r.told)) for r in resolved]}")

        print("\n== E. A told conditional asserts neither side ==")
        u = await A.understand(f"if the {V} is hot then the valve is hot", look_up=False)
        rule_held = any(getattr(a, "stored", False) for a in u.acquired)
        check("the conditional is held", rule_held,
              f"{[(a.label, a.stored, a.detail) for a in u.acquired][:2]}")
        clause_edges = [e for e in await edges(d, A._actor) if e[2] == "hot"]
        check("neither clause is a scoped edge", not clause_edges, f"{clause_edges}")
        belief = await d.execute_query(
            "SELECT claim FROM unified.scoped_beliefs WHERE scope_actor = $1 AND claim LIKE 'if %'",
            (A._actor,), fetch_all=True)
        check("the implication is the speaker's one belief about it", len(belief or []) == 1,
              f"{[r['claim'] for r in belief or []]}")
        u = await A.understand(f"is the {V} hot", look_up=False)
        reply = said(A, u)
        check("asked whether the antecedent holds, it is not affirmed",
              not reply.lower().startswith("yes"), reply[:100])

        print("\n== F. A speaker's context refuses what the world's door refuses ==")
        from core.memory import get_memory_agent
        held_for = (await get_memory_agent()).hold_for_person
        for subject, obj, quality, why in (("you", "mammal", 0.9, "a subject that names nothing"),
                                           ("", f"{N}thing", 0.9, "an empty subject"),
                                           (f"{N}weak", "mammal", 0.2, "a telling below the support floor")):
            decision = await held_for(A._actor, subject, "isa", obj, positive=True, quality=quality,
                                      domain="conversation", surface=f"{subject} isa {obj}", source="told")
            check(f"{why} is refused for the speaker", not decision.admitted and bool(decision.reasons),
                  f"{decision.standing}: {decision.reasons}")
        stray = [e for e in await edges(d, A._actor) if e[0] in ("you", f"{N}weak") or e[2] == f"{N}thing"]
        check("nothing refused was written to the speaker's context", not stray, f"{stray}")

        print("\n== H. Nothing held, nothing invented ==")
        u = await A.understand(f"Is {TWO} a {G} fish?", look_up=False)
        reply = said(A, u)
        check("a relation never told is not affirmed", not reply.lower().startswith("yes"), reply[:100])
        u = await A.understand(f"is a {N}florp a {N}blip", look_up=False)
        reply = said(A, u)
        check("a question about nothing held is not answered yes",
              not reply.lower().startswith("yes"), reply[:100])

        print("\n== I. It can say what it just heard ==")
        u = await A.understand("what did I just tell you")
        reply = said(A, u)
        check("the record of this exchange answers a question about it",
              N in reply.lower() or N in str(u.remembered).lower(), reply[:100])

        print("\n== J. What was reasoned for the speaker is remembered as theirs ==")
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        await agent.drain_writes()          # every queued write has landed
        rows = await d.execute_query(
            "SELECT memory_id, user_id, left(content, 80) AS c FROM memory_hot.memory_hot "
            "WHERE content ILIKE $1", (f"%{N}%",), fetch_all=True) or []
        EV.metric("memories_written_about_the_nonce", len(rows), "count")
        check("the conversation remembered something about what it was told",
              len(rows) > 0, f"{len(rows)} rows")
        # Everything here came from the two speakers.
        unowned = [r["c"] for r in rows if (r["user_id"] or "") not in actors]
        check("every such memory belongs to a speaker, none to the shared mind",
              not unowned, f"{len(unowned)} unowned: {unowned[:3]}")
        # B asked about V too, so B holds its own trace of asking; what B must
        # not hold is an answer drawn from A's context.
        foreign = [r["c"] for r in rows if (r["user_id"] or "") == B._actor
                   and V in (r["c"] or "") and "answer: yes" in (r["c"] or "").lower()]
        check("nothing the second speaker holds affirms the first one's telling", not foreign,
              f"{foreign[:2]}")
        mine = await agent.retrieve(f"is {NAME} a mammal", actor=A._actor,
                                    min_similarity=0.3, limit=10)
        theirs = await agent.retrieve(f"is {NAME} a mammal", actor=B._actor,
                                      min_similarity=0.3, limit=10)
        shared_view = await agent.retrieve(f"is {NAME} a mammal", actor=None,
                                           min_similarity=0.3, limit=10)
        owned_by_a = [m for m in mine if (m.user_id or "") == A._actor]
        check("the speaker recalls their own", bool(owned_by_a), f"{len(owned_by_a)} of {len(mine)}")
        check("another speaker's recall does not reach it, by meaning or by wording",
              not any((m.user_id or "") == A._actor for m in theirs),
              f"{[(m.user_id, m.content[:40]) for m in theirs if V in m.content][:2]}")
        check("the substrate's own recall does not reach it",
              not any((m.user_id or "") == A._actor for m in shared_view),
              f"{[(m.user_id, m.content[:40]) for m in shared_view if V in m.content][:2]}")
    finally:
        try:
            removed = await clean(d, actors)
            EV.metric("rows_removed", sum(removed.values()), "count", json.dumps(removed))
            left = await residue(d, actors)
            check("everything this run wrote is removed", sum(left.values()) == 0, f"{left}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-CONVERSATION-01")
    EV.write()
    return code


# ── cleanup: everything named by this run's nonce or scoped to its speakers ──

#: (name, table, the column that carries the nonce)
_BY_NONCE = (
    ("concepts", "unified.concepts", "name"),
    ("beliefs", "unified.beliefs", "claim"),
    ("knowledge_updates", "unified.knowledge_updates", "subject_id"),
    ("evidence_envelopes", "unified.evidence_envelopes", "content"),
    ("held_conditionals", "unified.held_conditionals", "surface"),
    ("memory_hot", "memory_hot.memory_hot", "content"),
    ("experience_pool", "unified.experience_pool", "parts::text"),
)


async def residue(d, actors):
    out = {}
    for name, table, column in _BY_NONCE:
        row = await d.execute_query(
            f"SELECT count(*) AS n FROM {table} WHERE {column} ILIKE $1",
            (f"%{N}%",), fetch_one=True)
        out[name] = int(row["n"])
    for table in ("scoped_beliefs", "scoped_concept_relations"):
        row = await d.execute_query(
            f"SELECT count(*) AS n FROM unified.{table} WHERE scope_actor = ANY($1::text[])",
            (actors,), fetch_one=True)
        out[table] = int(row["n"])
    return out


async def clean(d, actors):
    """Snapshot, then delete by id, everything this run wrote."""
    snap = {}
    for name, table, column in _BY_NONCE:
        snap[name] = [dict(r) for r in (await d.execute_query(
            f"SELECT * FROM {table} WHERE {column} ILIKE $1", (f"%{N}%",), fetch_all=True) or [])]
    for table in ("scoped_beliefs", "scoped_concept_relations"):
        snap[table] = [dict(r) for r in (await d.execute_query(
            f"SELECT * FROM unified.{table} WHERE scope_actor = ANY($1::text[])",
            (actors,), fetch_all=True) or [])]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "data" / "snapshots" / f"system_conversation_01_{N}_{stamp}.json"
    path.write_text(json.dumps(snap, default=str, indent=1))
    EV.note(f"residue snapshot: {path.relative_to(ROOT)}")

    concepts = [r["concept_id"] for r in snap["concepts"]]
    envelopes = [r["evidence_id"] for r in snap["evidence_envelopes"]]
    updates = [r["update_id"] for r in snap["knowledge_updates"]]
    if concepts or envelopes:
        await d.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
            "OR target_concept_id = ANY($1::text[]) OR evidence_id = ANY($2::text[])",
            (concepts, envelopes))
        for table in ("concept_domains", "concept_evidence"):
            await d.execute_query(
                f"DELETE FROM unified.{table} WHERE concept_id = ANY($1::text[]) "
                f"OR evidence_id = ANY($2::text[])", (concepts, envelopes))
        await d.execute_query("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])",
                              (concepts,))
        await d.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])",
                              (concepts,))
        await d.execute_query("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                              (envelopes,))
    if updates:
        await d.execute_query("DELETE FROM unified.knowledge_consumption WHERE update_id = ANY($1::text[])",
                              (updates,))
        await d.execute_query("DELETE FROM unified.knowledge_updates WHERE update_id = ANY($1::text[])",
                              (updates,))
    ids = {
        "beliefs": ("unified.beliefs", "belief_id", [r["belief_id"] for r in snap["beliefs"]]),
        "held_conditionals": ("unified.held_conditionals", "conditional_id",
                              [r["conditional_id"] for r in snap["held_conditionals"]]),
        "memory_hot": ("memory_hot.memory_hot", "memory_id", [r["memory_id"] for r in snap["memory_hot"]]),
        "experience_pool": ("unified.experience_pool", "item_id",
                            [r["item_id"] for r in snap["experience_pool"]]),
    }
    for table, key, values in ids.values():
        if values:
            await d.execute_query(f"DELETE FROM {table} WHERE {key} = ANY($1::text[])", (values,))
    for table in ("scoped_beliefs", "scoped_concept_relations"):
        await d.execute_query(f"DELETE FROM unified.{table} WHERE scope_actor = ANY($1::text[])",
                              (actors,))
    return {k: len(v) for k, v in snap.items()}


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
