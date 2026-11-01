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
    compose to nothing: no chaining, no inheritance down ISA, no inverse.

    EXCEPT RENAMING WHO IT WAS: `same_as` is not a step THROUGH the participant
    link, it REPLACES one of its arguments. A tying done by Alice, where Alice is
    the mayor, was done by the mayor -- the event is untouched and no kind of the
    participant leaks into it (`test_an_event_participant_stays_a_fact_about_that_event`
    is what guards that). Substitution carries the participant relation through
    unchanged, so it licenses nothing the relation did not already license."""
    from core.semantics.relation_types import get_spec
    for kind in (R.DONE_BY, R.DONE_TO):
        spec = get_spec(kind)
        assert spec.surface_forms == frozenset()
        assert spec.inverse is None and not spec.inheritable and not spec.symmetric
        for other in R:
            if other is R.SAME_AS:
                assert is_licensed(kind, other) and is_licensed(other, kind), kind
                continue
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


def test_a_group_and_a_count_told_of_are_named_in_a_conversation():
    """`told_events(..., described=True)`: "Plants take in carbon dioxide and water." tells of the two taken in as a
    group, and a count compared ("more attacks than earlier methods") is a number told of; each is named (`group_`,
    `number_`), so what is said of them is held. Teaching names neither."""
    from core.learning.teaching import told_events
    from core.semantics.derived_reader import Meaning, MeaningFact
    taken = Meaning("tell", (MeaningFact("instance_of", "?e", "take in"), MeaningFact("done_by", "?e", "plant"),
                             MeaningFact("done_to", "?e", "?g"), MeaningFact("has_member", "?g", "?c"),
                             MeaningFact("has_member", "?g", "?w"), MeaningFact("instance_of", "?c", "carbon dioxide"),
                             MeaningFact("instance_of", "?w", "water"), MeaningFact("has_count", "?w", "?n")))
    named = told_events(taken, "Plants take in carbon dioxide and water.", described=True)
    assert named["?g"].startswith("group_") and named["?n"].startswith("number_")
    assert "?g" not in told_events(taken, "Plants take in carbon dioxide and water.")


def test_a_thing_told_of_by_a_description_is_named_in_a_conversation():
    """`told_events(..., described=True)`, as a conversation names what it is told: "The company hired three
    engineers." names the hiring and the engineers hired (three of them), each from the telling; the company, a known
    thing found, is no unknown; what a question asks stays unnamed, and what is not told as so is not named. Teaching
    names the happening alone, as decided 2026-10-04."""
    from core.learning.teaching import told_events
    from core.semantics.derived_reader import Meaning, MeaningFact
    hired = Meaning("tell", (MeaningFact("instance_of", "?v0", "hire"), MeaningFact("done_by", "?v0", "company_1"),
                             MeaningFact("done_to", "?v0", "?v2"), MeaningFact("instance_of", "?v2", "engineer"),
                             MeaningFact("has_count", "?v2", "3"), MeaningFact("precedes", "?v0", "?now")))
    named = told_events(hired, "The company hired three engineers.", described=True)
    assert set(named) == {"?v0", "?v2"} and named["?v2"].startswith("engineer_") and named["?v0"].startswith("hire_")
    assert told_events(hired, "The company hired three engineers.") == {"?v0": named["?v0"]}
    shoe = Meaning("tell", (MeaningFact("instance_of", "?x", "shoe"), MeaningFact("has_property", "?x", "black")))
    assert list(told_events(shoe, "Some shoe is black.", described=True)) == ["?x"]
    asked = Meaning("ask", (MeaningFact("instance_of", "?v0", "eat"), MeaningFact("done_by", "?v0", "wug"),
                            MeaningFact("done_to", "?v0", "?v1"), MeaningFact("instance_of", "?v1", "food")),
                    ("?v1",))
    assert set(told_events(asked, "What food did the wug eat?", described=True)) == {"?v0"}
    said = Meaning("tell", (MeaningFact("instance_of", "?v0", "say"), MeaningFact("done_by", "?v0", "tom"),
                            MeaningFact("done_to", "?v0", "?v1"),
                            MeaningFact("instance_of", "?v1", "dog", unasserted=True),
                            MeaningFact("has_property", "?v1", "loud", unasserted=True)))
    assert list(told_events(said, "Tom said a dog was loud.", described=True)) == ["?v0"]


def test_a_told_happening_is_named_as_one_event_and_nothing_else_is():
    """"The wug ate a fep.": one eating, done by the wug, named from its telling, the same name taught again and
    another for another telling. "Some shoe is black." names no shoe: only a happening, an unknown something was done
    by or done to, is named (decided 2026-10-04)."""
    from core.learning.teaching import told_events
    from core.semantics.derived_reader import Meaning, MeaningFact
    ate = Meaning("tell", (MeaningFact("instance_of", "?v0", "eat"), MeaningFact("done_by", "?v0", "wug"),
                           MeaningFact("done_to", "?v0", "fep"), MeaningFact("precedes", "?v0", "?now")))
    named = told_events(ate, "The wug ate a fep.")
    assert list(named) == ["?v0"] and named["?v0"].startswith("eat_")
    assert told_events(ate, "The wug ate a fep.") == named, "the same telling names the same event"
    assert told_events(ate, "A wug ate a fep.") != named, "another telling is another event"
    shoe = Meaning("tell", (MeaningFact("instance_of", "?x", "shoe"), MeaningFact("has_property", "?x", "black")))
    assert told_events(shoe, "Some shoe is black.") == {}
    asked = Meaning("ask", (MeaningFact("instance_of", "?v0", "eat"), MeaningFact("done_by", "?v0", "wug"),
                            MeaningFact("done_to", "?v0", "?v1")), ("?v1",))
    assert set(told_events(asked, "What did the wug eat?")) == {"?v0"}, "the event a question asks of is not asked"
    said = Meaning("tell", (MeaningFact("instance_of", "?v0", "say"), MeaningFact("done_by", "?v0", "tom"),
                            MeaningFact("done_to", "?v0", "?v1"), MeaningFact("precedes", "?v0", "?now"),
                            MeaningFact("instance_of", "?v1", "bark", unasserted=True),
                            MeaningFact("done_by", "?v1", "dog", unasserted=True),
                            MeaningFact("precedes", "?v1", "?now", unasserted=True)))
    assert list(told_events(said, "Tom said that the dog barked.")) == ["?v0"], \
        "the saying is held; what was said, not told as so, is not a happening held (decided 2026-10-05)"


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


def test_every_relation_a_chain_of_holds_chains_and_no_other():
    """A cause of a cause is a cause, what is before what is before a thing is before it, and so are above, more than,
    a need of a need and the stuff of a thing's stuff; a chain of nearness, membership, "on", owning or likeness holds
    nothing (2026-10-21). Nothing chaining stands in itself where a loop of it is a contradiction, so only those are
    guarded against cycles at admission: not equals, nor causes, whose loop is a feedback."""
    from core.reasoning.relation_algebra import answer, UNKNOWN, TRUE
    from core.semantics.relation_types import SemanticRelation as SR, get_spec
    for relation in (SR.CAUSES, SR.PRECEDES, SR.ABOVE, SR.EXCEEDS, SR.REQUIRES, SR.MADE_OF, SR.EQUALS):
        chain = [Edge("a", relation, "b"), Edge("b", relation, "c")]
        assert answer("a", relation, "c", chain).verdict == TRUE, relation
    for relation in (SR.NEAR, SR.MEMBER_OF, SR.LOCATED_AT, SR.OWNS, SR.SIMILAR_TO):
        chain = [Edge("a", relation, "b"), Edge("b", relation, "c")]
        assert answer("a", relation, "c", chain).verdict == UNKNOWN, relation
    assert get_spec(SR.PART_OF).acyclic and get_spec(SR.PRECEDES).acyclic
    assert not get_spec(SR.EQUALS).acyclic and not get_spec(SR.CAUSES).acyclic
    import asyncio
    from core.semantics.cognitive_ingress import CognitiveIngress

    class Unreachable:
        initialized = True

        async def execute_query(self, *a, **k):
            raise AssertionError("a loop of what is no contradiction is never looked for")
    guard = CognitiveIngress(db_manager=Unreachable())
    for relation, subject, obj in (("causes", "stress", "insomnia"), ("equals", "paris", "capital_1")):
        assert asyncio.run(guard._would_close_a_cycle(relation, subject, obj)) is None
    try:
        asyncio.run(guard._would_close_a_cycle("part of", "paris", "france"))
        raise AssertionError("a part's loop is looked for")
    except RuntimeError as looked:
        assert "could not run" in str(looked)


def test_a_part_of_a_part_is_a_part_and_what_is_in_a_thing_is_where_it_is():
    """PART_OF and LOCATED_IN chain, and through each other to where a thing is: in Paris, and Paris part of France, is
    in France; a finger part of a hand part of an arm is part of the arm. Not part of France for being in Paris, and
    membership never chains (UNDERSTANDS-PROSE-01, 2026-10-21)."""
    from core.reasoning.relation_algebra import answer, PLACE, UNKNOWN, TRUE
    from core.semantics.relation_types import SemanticRelation as SR
    hand = [Edge("finger", SR.PART_OF, "hand"), Edge("hand", SR.PART_OF, "arm")]
    assert answer("finger", SR.PART_OF, "arm", hand).verdict == TRUE
    paris = [Edge("eiffel tower", SR.LOCATED_IN, "paris"), Edge("paris", SR.PART_OF, "france")]
    found = answer("eiffel tower", SR.LOCATED_IN, "france", paris)
    assert found.verdict == TRUE and found.derivation.rules == (PLACE,)
    assert answer("eiffel tower", SR.PART_OF, "france", paris).verdict == UNKNOWN
    wheel = [Edge("wheel", SR.PART_OF, "car"), Edge("car", SR.LOCATED_IN, "garage")]
    assert answer("wheel", SR.LOCATED_IN, "garage", wheel).verdict == TRUE
    team = [Edge("finger", SR.PART_OF, "hand"), Edge("hand", SR.PART_OF, "player"),
            Edge("player", SR.MEMBER_OF, "team")]
    assert answer("finger", SR.PART_OF, "team", team).verdict == UNKNOWN
    assert answer("finger", SR.MEMBER_OF, "team", team).verdict == UNKNOWN


def test_a_symmetric_relation_holds_both_ways_round():
    """"incoming is the opposite of outgoing" answers "Is outgoing the opposite of incoming?": a symmetric relation is
    its own inverse, derived (not observed), and no other relation is."""
    from core.reasoning.relation_algebra import answer, inverse, TRUE, DERIVED, UNKNOWN
    from core.semantics.relation_types import SemanticRelation as SR
    assert inverse(SR.ANTONYM_OF) is SR.ANTONYM_OF and inverse(SR.ISA) is None
    held = [Edge("incoming", SR.ANTONYM_OF, "outgoing")]
    found = answer("outgoing", SR.ANTONYM_OF, "incoming", held)
    assert found.verdict == TRUE and found.basis == DERIVED
    assert answer("outgoing", SR.ISA, "incoming", [Edge("incoming", SR.ISA, "outgoing")]).verdict == UNKNOWN


def test_no_closed_world_on_what_the_asker_said_and_was_not_taken_in():
    """The strong disjointness assumption answers No only while memory holds all that was said of the two kinds.
    Told "Python is a high-level, general-purpose programming language." and unable to read it, asked "Is Python a
    programming language?": memory's python is a snake, and No would answer against what was just told. Declined
    before memory is asked anything (the store here is None), judged by the words said, case and number aside."""
    import asyncio
    from core.reasoning.concept_graph_reasoning import _kinds_exclude, _named_in_any
    from core.semantics.relation_types import SemanticRelation as SR
    told = ["Python is a high-level, general-purpose programming language."]
    held = [Edge("python", SR.ISA, "boa")]
    assert asyncio.run(_kinds_exclude(None, "python", SR.ISA, "programming_language", held,
                                      not_taken_in=told)) is None
    assert asyncio.run(_kinds_exclude(None, "key", SR.ISA, "function", [Edge("key", SR.ISA, "device")],
                                      not_taken_in=["The argument key is a function that is applied."])) is None
    assert _named_in_any("whale", ["Whales feed their young with milk."])
    assert _named_in_any("programming_language", told)
    assert not _named_in_any("grandfather_clock", ["The grandfather of Tom is old."]), "every word of the name"
    assert not _named_in_any("python", []) and not _named_in_any("python", ["The beer is cold."])


# ------------------------------------------------ identity (one thing, two descriptions)

def test_what_is_said_of_one_description_is_said_of_the_other():
    """"South Asia is the southern sub-region of Asia that is defined in ... terms." reads as an identity between
    the name and the described thing, and every other fact of the sentence hangs off the DESCRIBED one. Asked what
    South Asia is a sub-region of, the reasoner held `same_as(south_asia, sub_region_1)` and
    `part_of(sub_region_1, asia)` and could reach nothing: `equals` composes with nothing by design, because nothing
    chains through arithmetic, and the reader had one word for both (UNDERSTANDS-PROSE-02, 2026-11-01)."""
    held = [Edge("south_asia", R.SAME_AS, "sub_region_1"),
            Edge("sub_region_1", R.PART_OF, "asia"),
            Edge("sub_region_1", R.HAS_PROPERTY, "southern"),
            Edge("sub_region_1", R.INSTANCE_OF, "sub_region")]
    got = {(d.edge.relation, d.edge.obj) for d in derive_from("south_asia", held)}
    assert (R.PART_OF, "asia") in got, got            # where it is
    assert (R.HAS_PROPERTY, "southern") in got, got   # what it is like
    assert (R.INSTANCE_OF, "sub_region") in got, got  # what it is


def test_identity_substitutes_in_either_argument_position():
    """A fact reached THROUGH an identity and a fact whose OBJECT is renamed by one are both entailed: the mayor
    signed it, and Alice is the mayor, so Alice signed it."""
    assert compose(R.SAME_AS, R.PART_OF)[0] is R.PART_OF
    assert compose(R.PART_OF, R.SAME_AS)[0] is R.PART_OF
    for kind in (R.ISA, R.INSTANCE_OF, R.HAS_PROPERTY, R.LOCATED_IN, R.DONE_BY, R.CAUSES):
        assert compose(R.SAME_AS, kind)[0] is kind, kind
        assert compose(kind, R.SAME_AS)[0] is kind, kind
    # Renaming carries the relation through UNCHANGED, so it licenses no step that relation did not license: an
    # unlicensed pairing still stops the chain at its own hop.
    held = [Edge("a", R.SAME_AS, "b"), Edge("b", R.MADE_OF, "steel"), Edge("steel", R.ISA, "alloy")]
    got = {(d.edge.relation, d.edge.obj) for d in derive_from("a", held)}
    assert (R.MADE_OF, "steel") in got
    assert (R.ISA, "alloy") not in got, "made_of never becomes isa, through an identity or otherwise"


def test_arithmetic_equality_is_not_identity_and_substitutes_nothing():
    """`equals` is two values that are the SAME NUMBER: "the sum of two and three equals five". Nothing chains
    through arithmetic -- the symbolic faculty works it out -- so it must stay inert, and giving identity its own
    relation is what lets it stay inert while identity reasons."""
    from core.semantics.relation_types import get_spec
    assert get_spec(R.EQUALS).gloss != get_spec(R.SAME_AS).gloss
    for kind in R:
        if kind is R.EQUALS:
            continue
        assert compose(R.EQUALS, kind) is None, kind
        assert compose(kind, R.EQUALS) is None, kind
    held = [Edge("sum_1", R.EQUALS, "five"), Edge("five", R.INSTANCE_OF, "number")]
    assert not [d for d in derive_from("sum_1", held) if d.edge.obj == "number"]


def test_identity_does_not_inherit_down_a_kind_or_place_a_thing():
    """`same_as` is a fact about one PARTICULAR, so it neither rides ISA down to every member of a kind nor counts
    as a place. Were it inheritable, "a robin is a bird" and "that bird is the one I saw" would make every robin
    the one I saw; were it a place, it would answer where things are."""
    from core.semantics.relation_types import get_spec
    spec = get_spec(R.SAME_AS)
    assert not spec.inheritable, "identity holds of a particular, never of every member of a kind"
    assert spec.symmetric and spec.transitive, "one thing under two descriptions, either way round"
    assert not spec.generic_safe, "a bare indefinite is no universal law of identity"
    assert compose(R.ISA, R.SAME_AS)[1] == "one_thing_under_two_descriptions", "renaming, not inheritance"
    # The thing a robin is identical to is not WHERE a robin is.
    held = [Edge("robin", R.SAME_AS, "bird_7"), Edge("bird_7", R.LOCATED_IN, "nest")]
    got = {d.edge.relation for d in derive_from("robin", held)}
    assert R.LOCATED_IN in got and R.PART_OF not in got


def test_an_identity_cycle_terminates_and_says_only_what_it_knows():
    """Each told the other way ("A is B", "B is A") is a cycle; the walk must end, and must not invent a third
    thing. Nothing is acyclic about identity -- each stands in it to the other -- so termination is the walk's
    job, not the relation's."""
    held = [Edge("a", R.SAME_AS, "b"), Edge("b", R.SAME_AS, "a"), Edge("b", R.HAS_PROPERTY, "red")]
    got = {(d.edge.subject, d.edge.relation, d.edge.obj) for d in derive_from("a", held)}
    assert ("a", R.HAS_PROPERTY, "red") in got
    assert all(o in ("a", "b", "red") for _, _, o in got), got


def test_a_derived_identity_says_which_rule_licensed_it_and_what_it_rests_on():
    """An inference is never confused with an observation: the derivation names the rule and carries the evidence of
    EVERY edge it went through, so "what does this rest on" can be answered of a renamed fact too."""
    held = [Edge("south_asia", R.SAME_AS, "sub_region_1", ("ev_identity",)),
            Edge("sub_region_1", R.PART_OF, "asia", ("ev_part",))]
    found = [d for d in derive_from("south_asia", held) if d.edge.relation is R.PART_OF]
    assert len(found) == 1, found
    assert found[0].rules == ("one_thing_under_two_descriptions",), found[0].rules
    rests_on = {e for edge in found[0].path for e in edge.evidence}
    assert rests_on == {"ev_identity", "ev_part"}, rests_on
