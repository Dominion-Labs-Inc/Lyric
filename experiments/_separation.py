"""What the separation checks share (SPLIT-01, TRUTH-01; docs/research/SEPARATION_MAP.md §11.7): where a claim
landed -- the world, a person's context (personal, or work and the organization's), what they said of themselves,
nowhere -- read from the stores themselves, and the removal of everything a run named with its nonce."""
from __future__ import annotations

import json
import random
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]


def nonce(length: int = 6) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


def shaped(subject: str, relation: str, obj: Optional[str]):
    """The claim in the store's own terms (`shape_proposition`)."""
    from core.semantics.cognitive_ingress import shape_proposition
    s, r, o, refusal = shape_proposition(subject, relation, obj)
    if refusal:
        raise ValueError(f"{subject} {relation} {obj}: {refusal}")
    return s, r, o


async def in_world(d, subject: str, relation: str, obj: str, positive: bool = True) -> bool:
    s, r, o = shaped(subject, relation, obj)
    row = await d.execute_query(
        "SELECT 1 FROM unified.concept_relations cr JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
        "WHERE c.name = $1 AND cr.relation = $2 AND cr.target_surface = $3 "
        "AND COALESCE(cr.polarity, 'positive') = $4 LIMIT 1",
        (s, r, o, "positive" if positive else "negative"), fetch_one=True)
    return row is not None


async def world_names(d, subject: str) -> bool:
    s, _, _ = shaped(subject, "isa", "thing")
    row = await d.execute_query("SELECT 1 FROM unified.concepts WHERE name = $1 LIMIT 1", (s,), fetch_one=True)
    return row is not None


async def in_context(d, owner: str, subject: str, relation: str, obj: str) -> Optional[Dict[str, Any]]:
    """The claim's row in `owner`'s context -- a person's Personal Context, or an organization's Work Context
    (`org:<organization>`) -- with which context it records; None when it is not held there."""
    s, r, o = shaped(subject, relation, obj)
    row = await d.execute_query(
        "SELECT context, organization FROM unified.scoped_concept_relations "
        "WHERE scope_actor = $1 AND subj = $2 AND rel = $3 AND obj = $4", (owner, s, r, o), fetch_one=True)
    return dict(row) if row else None


async def about_speaker(d, speaker: str, subject: str, relation: str) -> Optional[Dict[str, Any]]:
    row = await d.execute_query(
        "SELECT object, context, organization FROM unified.user_beliefs "
        "WHERE speaker = $1 AND subject = $2 AND relation = $3", (speaker, subject, relation), fetch_one=True)
    return dict(row) if row else None


async def rule_in_world(d, word: str) -> bool:
    row = await d.execute_query(
        "SELECT 1 FROM unified.held_conditionals WHERE ant_subject ILIKE $1 OR cons_subject ILIKE $1 LIMIT 1",
        (f"%{word}%",), fetch_one=True)
    return row is not None


async def rule_in_context(d, actor: str, word: str) -> Optional[Dict[str, Any]]:
    row = await d.execute_query(
        "SELECT context, organization FROM unified.scoped_beliefs WHERE scope_actor = $1 AND claim LIKE 'if %' "
        "AND claim ILIKE $2", (actor, f"%{word}%"), fetch_one=True)
    return dict(row) if row else None


def posterior(claim: str) -> Optional[float]:
    from core.learning import get_learning_authority
    belief = get_learning_authority().belief_for_claim(claim)
    return None if belief is None else float(belief.posterior_probability)


#: (name, table, the column that carries the nonce)
BY_NONCE = (
    ("concepts", "unified.concepts", "name"),
    ("beliefs", "unified.beliefs", "claim"),
    ("knowledge_updates", "unified.knowledge_updates", "subject_id"),
    ("evidence_envelopes", "unified.evidence_envelopes", "content"),
    ("held_conditionals", "unified.held_conditionals", "surface"),
    ("memory_hot", "memory_hot.memory_hot", "content"),
    ("experience_pool", "unified.experience_pool", "parts::text"),
    ("user_beliefs", "unified.user_beliefs", "surface"),
)


async def clean(d, word: str, actors: Sequence[str], label: str) -> Dict[str, int]:
    """Snapshot, then delete, everything a run named with `word` or kept for `actors`. Returns rows removed per
    table. The snapshot is kept under data/snapshots."""
    snap: Dict[str, List[Dict[str, Any]]] = {}
    for name, table, column in BY_NONCE:
        snap[name] = [dict(r) for r in (await d.execute_query(
            f"SELECT * FROM {table} WHERE {column} ILIKE $1", (f"%{word}%",), fetch_all=True) or [])]
    for table in ("scoped_beliefs", "scoped_concept_relations"):
        snap[table] = [dict(r) for r in (await d.execute_query(
            f"SELECT * FROM unified.{table} WHERE scope_actor = ANY($1::text[]) OR claim_key ILIKE $2"
            if table == "scoped_beliefs" else
            f"SELECT * FROM unified.{table} WHERE scope_actor = ANY($1::text[]) OR subj ILIKE $2",
            (list(actors), f"%{word}%"), fetch_all=True) or [])]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (ROOT / "data" / "snapshots").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "snapshots" / f"{label}_{word}_{stamp}.json").write_text(json.dumps(snap, default=str))
    concepts = [r["concept_id"] for r in snap["concepts"]]
    envelopes = [r["evidence_id"] for r in snap["evidence_envelopes"]]
    if concepts or envelopes:
        await d.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
            "OR target_concept_id = ANY($1::text[]) OR evidence_id = ANY($2::text[])", (concepts, envelopes))
        for table in ("concept_domains", "concept_evidence"):
            await d.execute_query(f"DELETE FROM unified.{table} WHERE concept_id = ANY($1::text[]) "
                                  f"OR evidence_id = ANY($2::text[])", (concepts, envelopes))
        await d.execute_query("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])", (concepts,))
        await d.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])", (concepts,))
        await d.execute_query("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                              (envelopes,))
    updates = [r["update_id"] for r in snap["knowledge_updates"]]
    if updates:
        await d.execute_query("DELETE FROM unified.knowledge_consumption WHERE update_id = ANY($1::text[])",
                              (updates,))
        await d.execute_query("DELETE FROM unified.knowledge_updates WHERE update_id = ANY($1::text[])", (updates,))
    for name, table, key in (("beliefs", "unified.beliefs", "belief_id"),
                             ("held_conditionals", "unified.held_conditionals", "conditional_id"),
                             ("memory_hot", "memory_hot.memory_hot", "memory_id"),
                             ("experience_pool", "unified.experience_pool", "item_id")):
        ids = [r[key] for r in snap[name]]
        if ids:
            await d.execute_query(f"DELETE FROM {table} WHERE {key} = ANY($1::text[])", (ids,))
    await d.execute_query("DELETE FROM unified.user_beliefs WHERE surface ILIKE $1 OR speaker = ANY($2::text[])",
                          (f"%{word}%", list(actors)))
    await d.execute_query("DELETE FROM unified.scoped_beliefs WHERE scope_actor = ANY($1::text[]) "
                          "OR claim_key ILIKE $2", (list(actors), f"%{word}%"))
    await d.execute_query("DELETE FROM unified.scoped_concept_relations WHERE scope_actor = ANY($1::text[]) "
                          "OR subj ILIKE $2", (list(actors), f"%{word}%"))
    return {name: len(rows) for name, rows in snap.items()}
