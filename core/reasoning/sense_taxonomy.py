#!/usr/bin/env python3
"""Sense-EXACT subclass reasoning over the graduate math/CS taxonomy.

The concept graph is keyed by NAME, so a walk about the algebraic "group" can
cross into the collective "group" -- one node, two senses -- and conclude a
Turing machine is a group. This taxonomy is keyed by Wikidata QID, and a QID IS
a sense: Q83478 is the algebraic group and nothing else. Reasoning over the QID
edges therefore cannot bridge senses, and because the graph was pulled only under
graduate math/CS roots, a surface word here resolves to its TECHNICAL sense (the
collective "group" is simply absent).

`is_subclass` answers "is every <child> a <parent>?" by transitive closure over
the P279 edges, from the QIDs the child label names to the QIDs the parent names.
It answers TRUE only on a real chain, UNKNOWN otherwise -- never a cross-sense
guess.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class SubclassAnswer:
    verdict: str                       # "true" | "unknown"
    child: str
    parent: str
    recognized: bool = False           # both terms name a concept IN this taxonomy
    path: List[str] = field(default_factory=list)   # label chain when true


async def ensure_schema(db) -> None:
    await db.execute_query(
        """CREATE TABLE IF NOT EXISTS unified.sense_taxonomy (
               child_qid    text NOT NULL,
               child_label  text NOT NULL,
               parent_qid   text NOT NULL,
               parent_label text NOT NULL,
               field        text NOT NULL,
               PRIMARY KEY (child_qid, parent_qid)
           )""", commit=True)
    await db.execute_query(
        "CREATE INDEX IF NOT EXISTS ix_sense_child ON unified.sense_taxonomy (child_qid)",
        commit=True)
    await db.execute_query(
        "CREATE INDEX IF NOT EXISTS ix_sense_childlabel ON unified.sense_taxonomy (lower(child_label))",
        commit=True)
    await db.execute_query(
        "CREATE INDEX IF NOT EXISTS ix_sense_parentlabel ON unified.sense_taxonomy (lower(parent_label))",
        commit=True)


async def load_edges(db, edges: Sequence[Sequence[str]]) -> int:
    """Replace the taxonomy with `edges` = [(child_qid, child_label, parent_qid,
    parent_label, field), ...]. Idempotent on (child_qid, parent_qid)."""
    await ensure_schema(db)
    await db.execute_query("TRUNCATE unified.sense_taxonomy", commit=True)
    n = 0
    for i in range(0, len(edges), 4000):
        chunk = edges[i:i + 4000]
        cols = list(zip(*chunk))            # 5 columns of the chunk
        await db.execute_query(
            """INSERT INTO unified.sense_taxonomy
               (child_qid, child_label, parent_qid, parent_label, field)
               SELECT * FROM unnest($1::text[],$2::text[],$3::text[],$4::text[],$5::text[])
               ON CONFLICT DO NOTHING""",
            (list(cols[0]), list(cols[1]), list(cols[2]), list(cols[3]), list(cols[4])),
            commit=True)
        n += len(chunk)
    return n


async def _qids_for(db, label: str) -> List[str]:
    """Every QID the label names in the taxonomy -- as a child or as a parent."""
    low = str(label or "").strip().lower()
    if not low:
        return []
    rows = await db.execute_query(
        "SELECT child_qid AS q FROM unified.sense_taxonomy WHERE lower(child_label) = $1 "
        "UNION SELECT parent_qid AS q FROM unified.sense_taxonomy WHERE lower(parent_label) = $1",
        (low,), fetch_all=True) or []
    return [r["q"] for r in rows]


async def is_subclass(db, child: str, parent: str) -> SubclassAnswer:
    """TRUE iff every <child> is a <parent> by a real P279 chain; else UNKNOWN."""
    child_qids = await _qids_for(db, child)
    parent_qids = await _qids_for(db, parent)
    recognized = bool(child_qids) and bool(parent_qids)
    if not recognized:
        return SubclassAnswer("unknown", child, parent, recognized=False)

    # A child that IS one of the parent senses is trivially a subclass.
    if set(child_qids) & set(parent_qids):
        return SubclassAnswer("true", child, parent, recognized=True, path=[child, parent])

    reachable = await db.execute_query(
        """WITH RECURSIVE reach(qid) AS (
               SELECT unnest($1::text[])
               UNION
               SELECT st.parent_qid FROM unified.sense_taxonomy st
               JOIN reach r ON st.child_qid = r.qid
           )
           SELECT EXISTS(SELECT 1 FROM reach WHERE qid = ANY($2::text[])) AS hit""",
        (child_qids, parent_qids), fetch_all=True)
    hit = bool(reachable and reachable[0]["hit"])
    return SubclassAnswer("true" if hit else "unknown", child, parent, recognized=True)
