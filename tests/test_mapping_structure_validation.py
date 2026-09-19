#!/usr/bin/env python3
"""A mapping is accepted only when structure is actually shared.

An edge of the source is preserved at the target when the target has the SAME
relation to the SAME concept. A shared relation label is not structure: `isa`
is 98% of stored relations, and matching labels alone stored sparrow <-> vessel
as an accepted analogy.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain.universal_ontology import UniversalOntology  # noqa: E402


class _Relations:
    """unified.concept_relations for the concepts under test."""

    initialized = True

    def __init__(self, edges):
        self.edges = edges

    async def execute_query(self, query, params=None, fetch_all=False, **_):
        assert "DISTINCT" in query, "edges must be read once per (relation, concept)"
        rows = {(r, t) for r, t in self.edges.get(params[0], [])}
        return [{"relation": r, "target_concept_id": t} for r, t in rows]


def _verdict(monkeypatch, edges, source, target):
    import core.database
    monkeypatch.setattr(core.database, "get_database_manager", lambda: _Relations(edges))
    return asyncio.run(UniversalOntology().validate_cross_domain_mapping(
        {"source_concept_id": source, "target_concept_id": target}))


def test_shared_labels_to_different_concepts_are_not_structure(monkeypatch):
    # The stored edges of the accepted sparrow <-> vessel mapping.
    edges = {
        "conversation:sparrow": [("isa", "language:passerine"), ("isa", "language:passerine"),
                                 ("isa", "conversation:fish")],
        "biology:vessel": [("carries", "biology:blood"), ("isa", "lexical:container"),
                           ("isa", "lexical:craft"), ("isa", "lexical:tube")],
    }
    result = _verdict(monkeypatch, edges, "conversation:sparrow", "biology:vessel")
    assert result["verdict"] == "REJECTED"
    assert result["measurements"]["source_edges"] == 2, "a repeated edge was counted twice"
    assert result["measurements"]["preserved_edges"] == []


def test_the_same_relation_to_the_same_concept_is_preserved(monkeypatch):
    edges = {
        "engineering:pump": [("moves", "engineering:fluid"), ("isa", "lexical:device"),
                             ("connects_to", "engineering:pipe")],
        "biology:heart": [("moves", "engineering:fluid"), ("isa", "lexical:device"),
                          ("isa", "lexical:organ")],
    }
    result = _verdict(monkeypatch, edges, "engineering:pump", "biology:heart")
    assert result["verdict"] == "ACCEPTED"
    assert result["measurements"]["preserved_edges"] == [
        ["isa", "lexical:device"], ["moves", "engineering:fluid"]]
    assert result["confidence"] > 0


def test_an_edge_to_the_other_side_of_the_mapping_is_not_shared_structure(monkeypatch):
    edges = {
        "a:x": [("related_to", "b:y"), ("isa", "c:thing")],
        "b:y": [("related_to", "a:x"), ("isa", "c:other")],
    }
    result = _verdict(monkeypatch, edges, "a:x", "b:y")
    # Each side has one remaining edge: too few to judge, not accepted.
    assert result["verdict"] == "INDETERMINATE"


def test_too_little_structure_is_indeterminate_not_refuted(monkeypatch):
    edges = {"a:x": [("isa", "c:thing")], "b:y": [("isa", "c:thing"), ("has", "c:part")]}
    assert _verdict(monkeypatch, edges, "a:x", "b:y")["verdict"] == "INDETERMINATE"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
