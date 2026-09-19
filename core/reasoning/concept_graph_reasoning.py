#!/usr/bin/env python3
"""Reason over the REAL concept graph with the typed relation algebra.

`unified.concept_relations` stores the relation as the canonical name of a
`SemanticRelation` (written by the ingress now that reading is typed). This loads
the relevant subgraph, maps those names back to types, and answers a query
through `relation_algebra` -- so inference over stored knowledge is
type-licensed, never naive reachability.

A relation string that is NOT a known type is skipped, not coerced: a legacy or
unrecognised edge licenses no inference rather than a wrong one.
"""

from __future__ import annotations

import logging
from typing import FrozenSet, List, Sequence, Tuple

from core.reasoning.relation_algebra import Answer, Edge, answer, derive_from
from core.semantics.relation_types import SemanticRelation

logger = logging.getLogger(__name__)

_BY_VALUE = {r.value: r for r in SemanticRelation}

_SUBGRAPH_SQL = (
    "SELECT c1.name AS subj, cr.relation AS rel, c2.name AS obj, cr.polarity AS pol "
    "FROM unified.concept_relations cr "
    "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
    "JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
    "WHERE c1.name = ANY($1)")


def _typed_edge(row) -> "Tuple[Optional[Edge], bool]":
    """A row -> (typed Edge, is_denied), or (None, _) for an untyped/legacy
    relation. The ingress stores the relation with spaces ("has part") and the
    polarity as "positive"/"negative"; both are decoded here so the one
    vocabulary lives in one place."""
    rel = _BY_VALUE.get(str(row["rel"]).strip().replace(" ", "_"))
    if rel is None:
        return None, False                     # untyped/legacy edge: no inference
    denied = str(row.get("pol") or "positive") == "negative"
    return Edge(row["subj"], rel, row["obj"]), denied


async def _scoped_rows(actor, frontier):
    """This actor's scoped edges whose subject is in `frontier`, in the SAME row
    shape as `_SUBGRAPH_SQL` (subj/rel/obj/pol). Empty when there is no actor, so
    the shared walk is unchanged for substrate/universal reasoning. This is the
    OVERLAY: a user's own context is unioned into a walk done ON THEIR BEHALF, and
    never on anyone else's — the reasoning counterpart of the write-side router."""
    if not actor:
        return []
    from core.learning.scoped_context_store import get_scoped_context_store
    return await get_scoped_context_store().edges_for_actor(actor, frontier)


async def load_subgraph(db, roots: Sequence[str], *, max_hops: int = 6,
                        actor=None) -> List[Edge]:
    """Typed POSITIVE edges reachable from `roots`, breadth-first to `max_hops`.
    Only edges whose relation names a known type are returned; untyped edges are
    skipped so they cannot be walked to a conclusion. A DENIED edge ("X is not a
    Y") is not a positive fact and is excluded here — `load_denials` returns those
    for `answer` to turn into an explicit FALSE.

    When `actor` is given, that actor's scoped edges are unioned into the walk
    (the overlay), so the substrate can chain a user's own context together with
    the shared graph — e.g. a taught "my pump isa broken" chains onto the shared
    "broken isa faulty" — while a walk for anyone else sees only the shared graph."""
    edges: List[Edge] = []
    seen_nodes: set = set()
    frontier = [str(r) for r in roots]
    for _ in range(max_hops):
        frontier = [n for n in frontier if n not in seen_nodes]
        if not frontier:
            break
        rows = await db.execute_query(_SUBGRAPH_SQL, (frontier,), fetch_all=True) or []
        rows = list(rows) + await _scoped_rows(actor, frontier)
        seen_nodes.update(frontier)
        nxt: List[str] = []
        for row in rows:
            edge, denied = _typed_edge(row)
            if edge is None or denied:
                continue
            edges.append(edge)
            if edge.obj not in seen_nodes:
                nxt.append(edge.obj)
        frontier = nxt
    return edges


async def load_denials(db, roots: Sequence[str], *, actor=None) -> List[Edge]:
    """The DENIED typed edges asserted directly about `roots` — "X is NOT a Y".

    These are what let `answer` distinguish FALSE (an explicit denial) from
    UNKNOWN (never told). Not traversed: a denial is a fact about its own
    subject, not a link to walk onward. An `actor`'s scoped denials are included
    too, so a user's own "my X is not a Y" refutes for that user."""
    rows = await db.execute_query(
        _SUBGRAPH_SQL, ([str(r) for r in roots],), fetch_all=True) or []
    rows = list(rows) + await _scoped_rows(actor, [str(r) for r in roots])
    out: List[Edge] = []
    for row in rows:
        edge, denied = _typed_edge(row)
        if edge is not None and denied:
            out.append(edge)
    return out


#: Relations that assert a property/type OF a subject, so `blob7 isa red`
#: reads as the unary feature red(blob7) an induced rule can match.
_COPULAR = ("is", "isa", "is_a", "are", "was", "were",
            "has_property", "instance_of")


async def instance_predicates(db, subject: str, *, actor=None) -> List[str]:
    """The properties/types asserted POSITIVELY of `subject` via a copular
    relation, as bare object names -- `blob7 isa red` -> `red`. These are the
    atomic features an induced classification rule (red(?X) & circular(?X) ->
    stop_sign(?X)) is applied against. Reads the concept graph directly; a target
    that never became its own concept is still read from the edge's surface.

    When `actor` is given, that actor's scoped copular edges are included, so the
    features of a user's own `my_pump isa broken` are visible when reasoning for
    that user — and for no one else."""
    rows = await db.execute_query(
        "SELECT cr.relation AS rel, "
        "COALESCE(c2.name, cr.target_surface) AS obj "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
        "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
        "WHERE c1.name = $1 AND COALESCE(cr.polarity, 'positive') = 'positive'",
        (str(subject),), fetch_all=True) or []
    rows = list(rows) + [r for r in await _scoped_rows(actor, [str(subject)])
                         if str(r.get("pol") or "positive") != "negative"]
    out: List[str] = []
    for row in rows:
        rel = str(row["rel"] or "").strip().lower().replace(" ", "_")
        obj = str(row["obj"] or "").strip()
        if rel in _COPULAR and obj and obj not in out:
            out.append(obj)
    return out


async def observed_instance_features(db, subject: str) -> Tuple[List[str], List[str]]:
    """What was OBSERVED of `subject`, and the evidence that observed it.

    `instance_predicates` returns every copular edge, which is right for
    answering a question and wrong for RECOGNISING: once naming is a reflex, a
    name the substrate concluded becomes an edge like any other, and reading it
    back as a feature lets the next naming rest on the last one. Measured, once
    the reflex was live: a red circle named `stopsign` was then carrying
    `stopsign` as a feature the next rule could match on, and induction could
    generalise over a premise nothing ever saw.

    So recognition reads only edges whose evidence is a ROOT source — a fresh
    observation. A conclusion (INDUCED_RULE, a memory restating earlier
    evidence) is excluded by the same set the ingress uses to decide what may
    introduce root evidence at all, imported rather than re-listed so the two
    cannot drift.

    Returns (features, evidence_ids). The evidence ids are the lineage a derived
    name must declare: the name then resolves to the same roots the features
    resolve to, so recognising a hundred red circles adds support to nothing —
    which is the point. The rule's own induction roots are NOT usable for that:
    they live in the rule store's id space (`cat_<head>_<subject>`, from a
    TrainingExample) and were never recorded as evidence envelopes, so declaring
    them is a dangling lineage and the ingestion is refused."""
    from core.domain.concept_ingestion import ROOT_SOURCE_VALUES
    rows = await db.execute_query(
        "SELECT cr.relation AS rel, "
        "COALESCE(c2.name, cr.target_surface) AS obj, cr.evidence_id AS ev "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
        "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
        "JOIN unified.evidence_envelopes ee ON ee.evidence_id = cr.evidence_id "
        "WHERE c1.name = $1 AND COALESCE(cr.polarity, 'positive') = 'positive' "
        "AND ee.source_type = ANY($2::text[])",
        (str(subject), list(ROOT_SOURCE_VALUES)), fetch_all=True) or []
    feats: List[str] = []
    evidence: List[str] = []
    for row in rows:
        rel = str(row["rel"] or "").strip().lower().replace(" ", "_")
        if rel not in _COPULAR:
            continue
        obj = str(row["obj"] or "").strip()
        ev = str(row["ev"] or "").strip()
        if obj and obj not in feats:
            feats.append(obj)
        if ev and ev not in evidence:
            evidence.append(ev)
    return feats, evidence


async def answer_over_graph(db, subject: str, relation: SemanticRelation, obj: str,
                            *, context_licenses: FrozenSet[SemanticRelation] = frozenset(),
                            max_hops: int = 6, actor=None) -> Answer:
    """Answer `subject relation obj` against the live concept graph, open-world.

    Query terms are normalised the SAME way the ingress normalised them on the
    way in (plural->singular, etc.), so "flippers" matches the stored "flipper".
    Without this a query would miss its own taught fact on a surface variation.

    An explicit DENIAL ("a kestrel is not a fish") makes the query FALSE, not
    UNKNOWN — the denied edges are loaded and handed to `answer` alongside the
    positive ones. Without this, a taught denial was silently read as its own
    affirmation (a false positive).

    `actor` selects WHOSE context is in scope: None answers over the shared mind
    alone (the default); a user's id overlays that user's scoped edges, so the
    substrate can answer from what THAT user told it — never from another's."""
    from core.semantics.cognitive_ingress import normalize_term
    subject, obj = normalize_term(subject), normalize_term(obj)
    edges = await load_subgraph(db, [subject], max_hops=max_hops, actor=actor)
    # Denials on the subject AND on every class it belongs to, so an inherited
    # disjointness refutes an instance: "no mammal is a bird" is a denial on
    # `mammal`, and `rex isa mammal`, so "is rex a bird?" is FALSE. The ISA
    # closure is exactly the subject plus the objects the positive edges reach.
    denial_roots = {subject} | {e.obj for e in edges}
    negatives = await load_denials(db, sorted(denial_roots), actor=actor)
    return answer(subject, relation, obj, edges,
                  context_licenses=context_licenses, negatives=negatives)


__all__ = ["load_subgraph", "load_denials", "answer_over_graph", "instance_predicates"]
