#!/usr/bin/env python3
"""The domain system's statements reader: prose becomes typed edges, or is declined.

It reads through the one reader (`derived_reader`), so a sentence reads only through constructions the substrate was
taught; the tests hand it the view memory would warm, built from taught pairs. A meaning is already in the domain
system's link kinds, and a denial is polarity, never a link name. Pure: no database, no memory, nothing written
anywhere.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain.concept_ingestion import (ConceptExtractor, EvidenceEnvelope,
                                           EvidenceSourceType)
from core.domain.domain_types import ConceptType
from core.semantics import derived_reader as dr
from core.semantics.derived_reader import Meaning, MeaningFact as F, PatternInventory
from core.semantics.relation_types import SemanticRelation as R
from core.semantics.sentence_machine import form_of


def _tell(*facts):
    return Meaning("tell", tuple(F(*f) for f in facts))


@pytest.fixture(autouse=True)
def taught(monkeypatch):
    """What memory would hold after these pairs were taught, handed to the reader as memory would hand it over."""
    view = PatternInventory(score=lambda item: (0.9, 1))
    for sentence, meaning in [
            ("A robin is a bird.", _tell(("isa", "robin", "bird"))),
            ("A sparrow is a bird.", _tell(("isa", "sparrow", "bird"))),
            ("A robin is a songbird.", _tell(("isa", "robin", "songbird"))),
            ("A sparrow is a songbird.", _tell(("isa", "sparrow", "songbird"))),
            ("A robin is not a songbird.", _tell(("isa", "robin", "songbird", False))),
            ("The book is in the box.", _tell(("located_in", "book", "box"))),
            ("The pen is in the box.", _tell(("located_in", "pen", "box"))),
            ("If the tank is full then the valve is open.",
             Meaning("tell", (F("has_property", "tank", "full", True, True),
                              F("has_property", "valve", "open"))))]:
        form = form_of(sentence)
        if dr.readings_of(tuple(p.text for p in form), meaning, view):
            continue
        repair = next(r for r in (step(form, meaning, view) for step in dr.REPAIRS) if r is not None)
        for item in repair.constructions + repair.links:
            view.add(item)
    monkeypatch.setattr(dr, "_live_inventory", lambda: view)
    return view


def _envelope(domain="test_domain", content="statements under test"):
    return EvidenceEnvelope(evidence_id="ev_statements_test",
                            source_type=EvidenceSourceType.RESEARCH_FINDING,
                            source_id="test", content=content, producer="test",
                            structured_data={"domain": domain})


def _read(extractor, raw, envelope):
    """The statements reader waits for memory where a word names several things; none does here."""
    return asyncio.run(extractor._read_statements(raw, envelope))


def _edges(candidates):
    return {c.label: set(c.relationships) for c in candidates if c.relationships}


def test_statements_become_typed_edges_with_polarity():
    got = _read(ConceptExtractor(),
                ["A robin is a bird.", "A robin is not a mammal.", "The cup is in the box."],
                _envelope())
    edges = _edges(got)
    assert (R.ISA.value, "bird", "positive") in edges["robin"]
    assert (R.ISA.value, "mammal", "negative") in edges["robin"], \
        "a denial is polarity, never a link name"
    assert (R.LOCATED_IN.value, "box", "positive") in edges["cup"]
    kinds = {k for rels in edges.values() for k, _t, _p in rels}
    assert kinds <= {r.value for r in R}, f"every link is a kind: {kinds}"


def test_every_candidate_names_its_domain_and_evidence():
    got = _read(ConceptExtractor(), ["A robin is a bird."], _envelope("birds"))
    assert got and all(c.domain_candidates == ("birds",) for c in got)
    assert all(c.evidence_ids == ("ev_statements_test",) for c in got)
    assert {c.label: c.concept_kind for c in got}["robin"] is ConceptType.ENTITY


def test_a_conditional_is_declined_not_written_as_an_edge():
    extractor = ConceptExtractor()
    got = _read(extractor, ["If the tank is full then the valve is open."], _envelope())
    assert got == []
    assert extractor.last_failure and "none of 1 statement" in extractor.last_failure


def test_what_was_never_taught_is_declined():
    extractor = ConceptExtractor()
    assert _read(extractor, ["Quarks bind through gluons."], _envelope()) == []
    assert "none of 1 statement" in extractor.last_failure


def test_no_domain_is_refused():
    extractor = ConceptExtractor()
    assert _read(extractor, ["A robin is a bird."], _envelope("")) == []
    assert extractor.last_failure == "statements form carries no domain"
