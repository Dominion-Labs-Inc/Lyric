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
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from core.reasoning.relation_algebra import Answer, Edge, answer, derive_from
from core.semantics.relation_types import SemanticRelation

logger = logging.getLogger(__name__)

_BY_VALUE = {r.value: r for r in SemanticRelation}

#: ONE ROW PER TYPED TRIPLE, WITH EVERY ENVELOPE THAT ASSERTED IT. This used to
#: select names only, so the graph walk -- the route that answers most
#: questions -- produced a chain it could show and never trace: `zorb -> glomph
#: -> fizzly` with no way back to the facts that licensed each hop. The same
#: triple asserted by several sources is several rows (evidence_id is part of the
#: relation's key); aggregated here it is one edge carrying all of its support,
#: which is what "what does this rest on" has to answer.
_SUBGRAPH_SQL = (
    "SELECT c1.name AS subj, cr.relation AS rel, c2.name AS obj, cr.polarity AS pol, "
    "       array_remove(array_agg(DISTINCT cr.evidence_id), NULL) AS ev "
    "FROM unified.concept_relations cr "
    "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
    "JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
    "WHERE c1.name = ANY($1) "
    "GROUP BY c1.name, cr.relation, c2.name, cr.polarity")


def _typed_edge(row) -> "Tuple[Optional[Edge], bool]":
    """A row -> (typed Edge, is_denied), or (None, _) for an untyped/legacy
    relation. The ingress stores the relation with spaces ("has part") and the
    polarity as "positive"/"negative"; both are decoded here so the one
    vocabulary lives in one place."""
    rel = _BY_VALUE.get(str(row["rel"]).strip().replace(" ", "_"))
    if rel is None:
        return None, False                     # untyped/legacy edge: no inference
    denied = str(row.get("pol") or "positive") == "negative"
    # A scoped (per-user) row carries no envelope ids, so its evidence is empty
    # -- "no stored assertion to point at", not a missing lookup.
    evidence = tuple(sorted(str(e) for e in (row.get("ev") or ()) if e))
    return Edge(row["subj"], rel, row["obj"], evidence), denied


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


#: Relations that say where a thing was IN THIS PICTURE, not what it looks like.
#:
#: The substrate already drew this line and measured it. `extent` is "the
#: property D3 removed from `isa` for being about the framing", and over
#: geometric transforms of two-object scenes the frame-INVARIANT relations
#: survived where the frame-relative ones did not: `larger_than` 48/48 and
#: invented nothing, `left_of` 94%, `above` 88% -- against 73% for the size band
#: and 52% for the position word. Generalising `sits center` to a KIND would
#: describe the photography and call it the object.
#:
#: Hearing has the same line. How loud a sound came out (`level`) depends on the
#: gain and on how near the microphone was, as extent depends on how near the
#: camera was. When it began (`starts_at`) depends on where the recording
#: started, as `sits` depends on where the frame was put. How long it stayed
#: above this recording's ground (`lasts`) shortens as the noise rises: under
#: 20 dB of noise a struck glass measured half its length. Each is true of that
#: recording and none is what the sound is.
_FRAMING = frozenset({"occupies", "sits", "extent", "level", "starts_at", "lasts"})

#: Facts about the PHOTOGRAPH rather than the thing in it. These sit on the
#: percept, not on the blob, so reading an instance does not reach them -- listed
#: because a describer must never state them of a kind even if it did.
_OF_THE_PICTURE = frozenset({
    "has_format", "has_width", "has_height", "has_orientation",
    "focus", "view_is",
})

#: The same for a RECORDING: its container, codec, rate and channels, how good
#: the hearing was, what it rests on between sounds, and how much of it was heard.
_OF_THE_RECORDING = frozenset({
    "has_format", "has_codec", "has_sample_rate", "has_channels", "has_sound_codec",
    "hearing_is", "background_is", "heard_for",
})


async def observed_kind_description(db, category: str, *, min_instances: int = 2
                                    ) -> Tuple[List[Tuple[str, str]], List[str]]:
    """What EVERY observed instance of `category` was SEEN to be like, as
    (relation, value) pairs, and the evidence that saw it.

    SIGHT COULD ONLY EVER SPEAK OF PARTICULARS. Reading "a hammer is a tool"
    makes a claim about the KIND on the first telling; seeing a hammer made
    claims about THIS BLOB, and the category concept held zero relations. So the
    substrate could pick a hammer out of a lineup and had nothing to say about
    what a hammer looks like.

    THE RELATION IS PART OF THE DESCRIPTION, AND DROPPING IT WAS THE FIRST
    MISTAKE. This began by reusing `observed_instance_features`, which filters to
    COPULAR edges because that is what RECOGNITION needs -- bare feature names to
    match a rule against. Sight measures far more than that, and all of it was
    discarded: a kind came out describable only as "a circle" and "a red". What
    something LOOKS LIKE is mostly not copular.

    FRAMING IS NOT APPEARANCE. `occupies 0.269` and `sits center` are true of
    that photograph, not of the kind, and `_FRAMING` says so with the
    measurements behind it. What survives a change of viewpoint is what belongs
    to the thing: its own properties, and how its PARTS stand to one another.

    THE INTERSECTION, NOT A VOTE. A pair is the kind's only when every observed
    instance has it; one counterexample ends it. Two instances minimum, because
    one instance's features are its own. An instance with nothing observed ends
    it, rather than letting the claim rest on fewer sightings than it appears to.

    Reads ONLY root-sourced observations, so a name the substrate CONCLUDED can
    never become part of how it describes the kind it concluded.
    """
    rows = await db.execute_query(
        "SELECT c1.name AS instance FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
        "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
        "WHERE COALESCE(c2.name, cr.target_surface) = $1 "
        "AND cr.relation = 'isa' "
        "AND COALESCE(cr.polarity, 'positive') = 'positive'",
        (str(category),), fetch_all=True) or []

    instances: List[str] = []
    for row in rows:
        name = str(row["instance"] or "").strip()
        if name and name != str(category) and name not in instances:
            instances.append(name)
    if len(instances) < int(min_instances):
        return [], []

    shared: Optional[Set[Tuple[str, str]]] = None
    evidence: List[str] = []
    for instance in instances:
        pairs, ev = await observed_instance_description(db, instance)
        if not pairs:
            return [], []
        shared = set(pairs) if shared is None else (shared & set(pairs))
        for e in ev:
            if e not in evidence:
                evidence.append(e)
        if not shared:
            return [], []
    return sorted(shared or set()), evidence


async def observed_instance_description(db, subject: str
                                        ) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Everything OBSERVED of `subject` that describes it, as (relation, value).

    The describing counterpart of `observed_instance_features`, which returns
    bare names for rule matching. Here the relation is kept, because `looked
    vivid` and `larger_than handle` are not the same kind of fact as `isa red`
    and a description that flattened them would say neither.

    Same evidence discipline: root sources only, positive edges only. Framing and
    picture facts are excluded by name -- they are measured, they are true, and
    they are not what the thing looks like.
    """
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

    # A PART IS DESCRIBED BY WHAT IT IS, NEVER BY WHAT THIS PICTURE CALLED IT.
    #
    # Sight measures the structure of a thing as relations between the blobs it
    # segmented -- `head above handle`, `head larger_than handle` -- and those
    # are the claims that survive a change of viewpoint (`left_of` and `above`
    # "survive a translation 100% of the time"). But the object of such a
    # relation is a blob NAME minted for that one photograph
    # (`probex379bd0ec08_orangerectangle`), so the next sighting of the same kind
    # of thing produces a different name and the two have nothing in common. The
    # structure was measured, generalised over nothing, and lost.
    #
    # A part is recognised by what it is part of: another individual the SAME
    # PERCEPT contains, since both were perceived in it and `contains` is what
    # records that. Such a target is replaced by what was OBSERVED of it, so
    # "above <that orange rectangle>" becomes "above an orange rectangle", which
    # the next hammer can agree with.
    #
    # NOT BY SHARING A DOMAIN with the thing described. That stands in for this
    # only while every feature word lives in the taught graph. A feature never
    # taught is created where it is first stated, and `describe_kind` states
    # `<kind> has_property <feature>` in the perception domain, so a domain test
    # reads every such feature as a co-perceived part with nothing observed of
    # it, and drops it. Measured on hearing: once one kind had been described in
    # a domain, no later kind in that domain could be described at all.
    held_by = await db.execute_query(
        "SELECT DISTINCT COALESCE(p.name, part.target_surface) AS part "
        "FROM unified.concept_relations holds "
        "LEFT JOIN unified.concepts s ON holds.target_concept_id = s.concept_id "
        "JOIN unified.concept_relations part "
        "ON part.source_concept_id = holds.source_concept_id "
        "AND part.relation = 'contains' "
        "LEFT JOIN unified.concepts p ON part.target_concept_id = p.concept_id "
        "WHERE holds.relation = 'contains' "
        "AND COALESCE(s.name, holds.target_surface) = $1",
        (str(subject),), fetch_all=True) or []
    siblings = {str(r["part"]).strip() for r in held_by} - {str(subject)}
    co_seen = {str(r["obj"]).strip() for r in rows
               if r["obj"] and str(r["obj"]).strip() in siblings}
    described_as: Dict[str, str] = {}
    for blob in co_seen:
        labels, _ev = await observed_instance_features(db, blob)
        if labels:
            described_as[blob] = " ".join(sorted(labels))

    pairs: List[Tuple[str, str]] = []
    evidence: List[str] = []
    for row in rows:
        rel = str(row["rel"] or "").strip().lower().replace(" ", "_")
        obj = str(row["obj"] or "").strip()
        if not rel or not obj:
            continue
        if rel in _FRAMING or rel in _OF_THE_PICTURE or rel in _OF_THE_RECORDING:
            continue
        if obj in co_seen:
            # A part whose own description is unknown cannot stand in a claim
            # about the kind: naming it by its per-picture id would state a
            # structure no second sighting could ever match.
            if obj not in described_as:
                continue
            obj = described_as[obj]
        pair = (rel, obj)
        if pair not in pairs:
            pairs.append(pair)
        ev = str(row["ev"] or "").strip()
        if ev and ev not in evidence:
            evidence.append(ev)
    return pairs, evidence


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
