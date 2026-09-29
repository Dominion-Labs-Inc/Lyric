#!/usr/bin/env python3
"""Typed relations + licensed inference, with the isolation negative-controls.

The negative controls are the point: a typed graph must REFUSE the chains that
naive reachability would accept (made-of never becomes isa, part-of never
becomes isa, located-in never becomes isa).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics.relation_types import (
    classify, SemanticRelation as R, NOUN, ADJECTIVE)
from core.reasoning.relation_algebra import (
    Edge, compose, derive_from, entails, is_licensed)


# ---------------------------------------------------------------- typing

def test_predicate_spans_get_distinct_types_not_all_isa():
    cases = {
        "is a": R.ISA,
        "has": R.HAS_PART,
        "eats": R.EATS,
        "makes": R.CREATES,
        "lives in": R.LOCATED_IN,
        "is part of": R.PART_OF,
        "is made of": R.MADE_OF,
        "is used for": R.USED_FOR,
        "causes": R.CAUSES,
    }
    for span, expected in cases.items():
        got = classify(span)
        assert got.relation is expected, f"{span!r} -> {got.relation} != {expected}"
    # everything the machine reads carries its provenance
    assert classify("is a").source == "curated_lexical_map"


def test_unknown_predicate_is_inert_not_taxonomic():
    got = classify("flurbles")
    assert got.relation is R.RELATED_TO
    assert got.matched == "" and got.surface == "flurbles"
    # RELATED_TO must license no inference
    assert compose(R.RELATED_TO, R.ISA) is None
    assert compose(R.ISA, R.RELATED_TO) is None


def test_bare_copula_disambiguates_on_object_class():
    assert classify("is", object_word_class=ADJECTIVE).relation is R.HAS_PROPERTY
    assert classify("is", object_word_class=NOUN).relation is R.ISA
    assert classify("is").relation is R.ISA  # default, never invents a property


def test_generic_safety_is_typed():
    assert classify("is a").generic is True          # a kind law
    assert classify("lives in").generic is False     # contextual, not universal
    assert classify("owns").generic is False


# ---------------------------------------------------------- transitivity

def test_isa_chain_derives_animal():
    edges = [Edge("robin", R.ISA, "bird"), Edge("bird", R.ISA, "vertebrate"),
             Edge("vertebrate", R.ISA, "animal")]
    d = entails("robin", R.ISA, "animal", edges)
    assert d is not None and d.hops == 3          # derived, 3 observed hops
    assert d.edge == Edge("robin", R.ISA, "animal")


def test_instance_of_rides_up_isa():
    edges = [Edge("fido", R.INSTANCE_OF, "dog"), Edge("dog", R.ISA, "mammal")]
    assert entails("fido", R.INSTANCE_OF, "mammal", edges) is not None
    # but fido is NOT a subKIND of mammal
    assert entails("fido", R.ISA, "mammal", edges) is None


# ----------------------------------------------------------- inheritance

def test_generic_property_inherits_down_isa():
    edges = [Edge("robin", R.ISA, "bird"), Edge("bird", R.HAS_PART, "wings")]
    assert entails("robin", R.HAS_PART, "wings", edges) is not None
    edges2 = [Edge("robin", R.ISA, "bird"), Edge("bird", R.EATS, "insects")]
    assert entails("robin", R.EATS, "insects", edges2) is not None


def test_membership_does_not_transit():
    # robin member_of flock, flock member_of ecosystem  ⊬  robin member_of ecosystem
    edges = [Edge("robin", R.MEMBER_OF, "flock"),
             Edge("flock", R.MEMBER_OF, "ecosystem")]
    assert entails("robin", R.MEMBER_OF, "ecosystem", edges) is None


# ---------------------------------------------- ISOLATION (negative controls)

def test_made_of_never_becomes_isa():
    # "A widget is made of brass." + "Brass is a material."
    edges = [Edge("widget", R.MADE_OF, "brass"), Edge("brass", R.ISA, "material")]
    assert entails("widget", R.ISA, "brass", edges) is None
    assert entails("widget", R.ISA, "material", edges) is None
    # and nothing derived from widget is an ISA edge at all
    assert all(d.edge.relation is not R.ISA for d in derive_from("widget", edges))


def test_part_of_never_becomes_isa():
    # "A zorble is part of a colony." + "A colony is a group."
    edges = [Edge("zorble", R.PART_OF, "colony"), Edge("colony", R.ISA, "group")]
    assert entails("zorble", R.ISA, "colony", edges) is None
    assert entails("zorble", R.ISA, "group", edges) is None


def test_located_in_never_becomes_isa():
    # "A zorble lives in a burrow." + "A burrow is a shelter."
    edges = [Edge("zorble", R.LOCATED_IN, "burrow"), Edge("burrow", R.ISA, "shelter")]
    assert entails("zorble", R.ISA, "burrow", edges) is None
    assert entails("zorble", R.ISA, "shelter", edges) is None


def test_creates_composes_with_nothing_taxonomic():
    # "A carpenter makes a cabinet." + "A cabinet is furniture."
    edges = [Edge("carpenter", R.CREATES, "cabinet"),
             Edge("cabinet", R.ISA, "furniture")]
    assert entails("carpenter", R.ISA, "cabinet", edges) is None
    assert entails("carpenter", R.CREATES, "furniture", edges) is None  # CREATES not inheritable-object


def test_isolation_is_the_default_across_all_pairs():
    # A composition is licensed ONLY by an explicit rule; assert the vast
    # majority of pairs compose to nothing (isolation is the default).
    rels = list(R)
    licensed = sum(1 for a in rels for b in rels if is_licensed(a, b))
    total = len(rels) * len(rels)
    assert licensed < total * 0.10, f"too many licensed pairs ({licensed}/{total})"


# ------------------------------------------------ a kind by its own name

def test_every_kind_resolves_to_itself_by_name():
    """A relation read back from the store arrives as its kind's name, and every
    kind must resolve to itself that way, whether or not any English phrase is
    written for it. Measured before: `synonym_of` resolved to RELATED_TO."""
    for kind in R:
        assert classify(kind.value).relation is kind, kind
        assert classify(kind.value.replace("_", " ")).relation is kind, kind


# ------------------------------------------------ event participants

def test_event_participants_carry_no_english_and_license_nothing():
    """`done_by` / `done_to` say who did an event and what it was done to. No
    English is written for them -- which words say them is learned -- and they
    compose to nothing: no chaining, no inheritance down ISA, no inverse."""
    from core.semantics.relation_types import get_spec
    for kind in (R.DONE_BY, R.DONE_TO):
        spec = get_spec(kind)
        assert spec.surface_forms == frozenset()
        assert spec.inverse is None and not spec.inheritable and not spec.symmetric
        for other in R:
            assert not is_licensed(kind, other), (kind, other)
            assert not is_licensed(other, kind), (other, kind)


def test_an_event_participant_stays_a_fact_about_that_event():
    """"Tie your shoe.": a tying, done by the listener, done to the shoe. What
    the listener or the shoe is a kind of does not leak into the event."""
    from core.reasoning.relation_algebra import answer, TRUE, UNKNOWN, OBSERVED
    edges = [Edge("tying_1", R.INSTANCE_OF, "tying"),
             Edge("tying_1", R.DONE_BY, "listener"),
             Edge("tying_1", R.DONE_TO, "shoe_1"),
             Edge("listener", R.ISA, "person"),
             Edge("shoe_1", R.INSTANCE_OF, "shoe")]
    done_by = answer("tying_1", R.DONE_BY, "listener", edges)
    assert done_by.verdict == TRUE and done_by.basis == OBSERVED
    assert answer("tying_1", R.DONE_BY, "person", edges).verdict == UNKNOWN
    assert answer("tying_1", R.DONE_TO, "shoe", edges).verdict == UNKNOWN
    assert answer("listener", R.DONE_BY, "tying_1", edges).verdict == UNKNOWN


def test_the_graph_types_an_event_participant_row():
    """The graph decodes a stored row by the kind's name, so a participant link
    written to the store is walked as that kind, not skipped as untyped."""
    from core.reasoning.concept_graph_reasoning import _typed_edge
    for stored, kind in (("done by", R.DONE_BY), ("done_to", R.DONE_TO)):
        edge, denied = _typed_edge({"subj": "tying_1", "rel": stored, "obj": "x",
                                    "pol": "positive", "ev": []})
        assert edge is not None and edge.relation is kind and not denied


# --------------------------------------------- typed edges through the algebra
#
# These three were reader-integration tests over `derived_reader.read_typed`,
# which was removed on 2026-09-04, so they had not run since. What they state
# about the ALGEBRA is kept here with the typed edges given directly. Reading
# the seven constructions ("A zorble is a fintch.", "… has flippers.", "… eats
# krill.", "A tinker makes a widget.", "… lives in a burrow.", "… is part of a
# colony.", "A widget is made of brass.") is an acceptance case for the pattern
# reader once it has been taught them (docs/research/SHAPES_CHANGE_MAP.md, step 3).

def test_made_of_never_licenses_isa_through_the_material_kind():
    """A made-of edge, with the material itself a kind: no ISA is derivable."""
    edges = [Edge("cabinet", R.MADE_OF, "oak"),
             Edge("oak", R.ISA, "wood"), Edge("wood", R.ISA, "material")]
    assert entails("cabinet", R.ISA, "oak", edges) is None
    assert entails("cabinet", R.ISA, "material", edges) is None


# ===================== ACQUISITION + GENERALIZATION (open-world) =============

def test_open_world_acquisition_and_generalization():
    from core.reasoning.relation_algebra import answer, TRUE, UNKNOWN, OBSERVED, DERIVED

    # Phase 1 — only these five facts are held.
    edges = [Edge("zorble", R.ISA, "fintch"),
             Edge("fintch", R.ISA, "animal"),
             Edge("zorble", R.HAS_PART, "flippers"),
             Edge("zorble", R.EATS, "krill"),
             Edge("zorble", R.LOCATED_IN, "burrow")]

    # Phase 2 — ask what it was NOT directly told.

    # generalization by ISA transitivity (never taught directly)
    a = answer("zorble", R.ISA, "animal", edges)
    assert a.verdict == TRUE and a.basis == DERIVED
    assert a.derivation.hops == 2                      # zorble->fintch->animal
    assert [e.obj for e in a.derivation.path] == ["fintch", "animal"]

    # taught facts are TRUE and OBSERVED (not derived)
    assert answer("zorble", R.HAS_PART, "flippers", edges).basis == OBSERVED
    assert answer("zorble", R.EATS, "krill", edges).basis == OBSERVED

    # THE NEGATIVE CONTROL: never told, cannot derive -> UNKNOWN, not FALSE.
    wings = answer("zorble", R.HAS_PART, "wings", edges)
    assert wings.verdict == UNKNOWN
    assert wings.verdict != "false"


def test_inverse_is_derived_with_provenance_not_observed():
    from core.reasoning.relation_algebra import (
        answer, derive_from, TRUE, DERIVED, INVERSE)
    # zorble HAS_PART flippers  =>  flippers PART_OF zorble  (DERIVED, not seen)
    edges = [Edge("zorble", R.HAS_PART, "flippers")]
    inv = answer("flippers", R.PART_OF, "zorble", edges)
    assert inv.verdict == TRUE and inv.basis == DERIVED
    assert inv.derivation.rules == (INVERSE,)
    # the observed direction stays observed
    assert answer("zorble", R.HAS_PART, "flippers", edges).basis == "observed"


def test_ontology_defined_relations_do_not_chain_by_default():
    from core.reasoning.relation_algebra import answer, UNKNOWN, TRUE
    from core.semantics.relation_types import SemanticRelation as SR
    # finger PART_OF hand, hand PART_OF arm  -- PART_OF is ONTOLOGY_DEFINED,
    # so it must NOT chain on its own.
    edges = [Edge("finger", SR.PART_OF, "hand"), Edge("hand", SR.PART_OF, "arm")]
    assert answer("finger", SR.PART_OF, "arm", edges).verdict == UNKNOWN
    # ...but a context that licenses PART_OF transitivity DOES chain it.
    licensed = answer("finger", SR.PART_OF, "arm", edges,
                      context_licenses=frozenset({SR.PART_OF}))
    assert licensed.verdict == TRUE
