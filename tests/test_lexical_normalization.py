"""One surface form, one canonical lexical interpretation, across all of Torin.

Concept identity normalised through a singularising path, so `men` and `man`
were one thing. The formalizer that turns prose into logic had its own private
normaliser that only lowercased and stripped articles, so to the solver they
were two things -- and "Socrates is a man. All men are mortal. Is Socrates
mortal?" could not be proved. A substrate whose concept store believes
`men == man` while its logic believes `men != man` does not have one vocabulary.

The second discipline these pin: canonicalisation resolves GRAMMAR, never
meaning. `men -> man` is morphology; `human -> person` would be a claim about
the world, and belongs to concept identity backed by alias evidence.
"""
import inspect

import pytest

from core.domain.concept_ingestion import ConceptResolver
# THE MODEL-FREE GUARD IS GONE, AND SO IS WHAT IT GUARDED AGAINST.
# These tests wrapped themselves in an autouse fixture that set
# `ModelPolicy.STRICT_MODEL_FREE` and asserted afterwards that no model had been
# called. `core.model_policy` was REMOVED when the substrate became model-free by
# CONSTRUCTION -- there is no longer a policy to set, because there is nothing to
# set it against. The guard's subject is gone; the subject of these tests is not,
# and they had been uncollectable ever since.
# MORPHOLOGY IS READING, AND READING IS SEMANTICS'. `_singular` and
# `_normalize` moved from `DeterministicExtractor` to
# `core.semantics.sentence_reader` on 2026-08-24, when 619 lines of English
# patterns left the reasoning module. The formalizer is imported still because
# these tests also exercise `formalize()`, which stayed with reasoning.
from core.reasoning.neural_bridge import DeterministicExtractor
from core.semantics.sentence_reader import SentenceReader
from core.reasoning.reasoning_interfaces import Connectivity
from core.semantics import lexical_normalization as lexical




# ------------------------------------------------------------------ one owner

def test_concept_identity_delegates_to_the_shared_layer():
    resolver = ConceptResolver()
    for word in ("men", "people", "physics", "batteries", "analyses",
                 "characteristics", "phosphoric_acid_fuel_cells_pafc"):
        assert resolver.canonical_label(word) == lexical.canonical_label(word)


def test_the_formalizer_no_longer_carries_its_own_morphology():
    """The duplicate that caused the defect. It may delegate; it may not
    reimplement."""
    source = inspect.getsource(SentenceReader._singular)
    assert "_lexical.singularise" in source
    assert "endswith" not in source, (
        "a second morphology implementation has reappeared in the logic path"
    )


def test_both_paths_agree_on_the_same_word():
    """The invariant, stated directly."""
    extractor = SentenceReader()
    resolver = ConceptResolver()
    for word in ("men", "humans", "people", "batteries"):
        assert extractor._singular(word) == lexical.singularise(word)
        assert resolver.canonical_label(word) == lexical.canonical_label(word)


# ----------------------------------------------------------------- morphology

@pytest.mark.parametrize("plural,singular", [
    ("men", "man"), ("women", "woman"), ("children", "child"),
    ("people", "person"), ("mice", "mouse"), ("feet", "foot"),
    ("teeth", "tooth"),
])
def test_irregular_plurals_reduce(plural, singular):
    assert lexical.singularise(plural) == singular


@pytest.mark.parametrize("word", [
    "man", "woman", "child", "person", "mouse", "foot", "tooth",
])
def test_singular_forms_are_left_alone(word):
    assert lexical.singularise(word) == word


@pytest.mark.parametrize("word,expected", [
    ("humans", "human"), ("batteries", "battery"), ("analyses", "analysis"),
    ("characteristics", "characteristic"),
])
def test_regular_morphology_still_works(word, expected):
    assert lexical.singularise(word) == expected


@pytest.mark.parametrize("word", ["physics", "mathematics", "synthesis", "series"])
def test_the_guards_earned_from_live_data_survive_the_move(word):
    """`physics` became `physic`, and physics concepts attached to a domain that
    did not exist. That guard must not be lost in the extraction."""
    assert lexical.singularise(word) == word


# ------------------------------------------------------- morphology != synonymy

def test_canonicalisation_does_not_invent_synonyms():
    """Distinct words stay distinct. Equivalence is identity's job, on evidence."""
    assert lexical.canonical_label("human") != lexical.canonical_label("man")
    assert lexical.canonical_label("human") != lexical.canonical_label("person")
    assert lexical.canonical_label("man") != lexical.canonical_label("person")


def test_the_logic_path_uses_morphology_only_not_identity_policy():
    """canonical_label can strip qualifier tails -- the claim that
    lithium_iron_phosphate_battery IS lithium_iron_phosphate. That is synonymy,
    and a logical predicate must not acquire it from a string function.

    The tail-stripping is now OPT-IN (`document_derived=True`): applied by
    default it renamed `nervous_system` to `nervous` across 691 of 83k facts, so
    it runs only for text pulled out of a document. This first asserted the old
    default -- i.e. the defect. The identity policy still exists when asked for,
    which is what this test needs to show the logic path does NOT use it."""
    assert lexical.canonical_label("solar_system", document_derived=True) != "solar_system"
    assert lexical.canonical_label("solar_system") == "solar_system"
    assert SentenceReader()._singular("solar_system") == "solar_system"


# ------------------------------------------------------------- the syllogism

@pytest.mark.asyncio
@pytest.mark.parametrize("premises,label", [
    (["Socrates is a man", "All men are mortal"], "man/men"),
    (["Socrates is a human", "All humans are mortal"], "human/humans"),
    (["Socrates is a person", "All people are mortal"], "person/people"),
])
async def test_the_canonical_syllogism_is_proved_model_free(premises, label):
    from core.reasoning.advanced_proof_engine import (
        LogicType, Theorem, get_proof_engine,
    )

    formalization = await DeterministicExtractor().formalize(
        "Is Socrates mortal?", premises)
    assert formalization.succeeded, label
    assert formalization.connectivity is Connectivity.CONNECTED

    proof = await get_proof_engine().prove_theorem(
        Theorem(theorem_id="syllogism", statement=formalization.statement,
                premises=list(formalization.premises),
                logic_type=LogicType.PROPOSITIONAL), timeout=10)
    assert proof.confidence > 0.9, f"{label}: {formalization.premises}"


@pytest.mark.asyncio
async def test_distinct_terms_do_not_entail():
    """`human` and `man` are different words; nothing may bridge them silently."""
    from core.reasoning.advanced_proof_engine import (
        LogicType, Theorem, get_proof_engine,
    )

    formalization = await DeterministicExtractor().formalize(
        "Is Socrates mortal?", ["Socrates is a human", "All men are mortal"])
    proof = await get_proof_engine().prove_theorem(
        Theorem(theorem_id="unbridged", statement=formalization.statement,
                premises=list(formalization.premises),
                logic_type=LogicType.PROPOSITIONAL), timeout=10)
    assert proof.confidence == 0.0


# ----------------------------------------------------------------- honesty

@pytest.mark.asyncio
@pytest.mark.parametrize("goal,premises,succeeded,connectivity", [
    ("Is Socrates mortal?", ["Socrates is a man", "All men are mortal"],
     True, Connectivity.CONNECTED),
    ("Is Socrates mortal?", ["Socrates is a human", "All men are mortal"],
     True, Connectivity.CONNECTED),
    ("Is Socrates mortal?", ["Socrates is a man", "All dogs are mammals"],
     True, Connectivity.DISCONNECTED),
    ("Why did Rome fall?", ["Caesar is a general"],
     False, Connectivity.UNSUPPORTED),
])
async def test_translation_failure_is_distinguishable_from_non_entailment(
    goal, premises, succeeded, connectivity
):
    """A goal the premises never mention returns 0.0 from the solver, and a
    caller reading that as 'not entailed' is reading a translation gap as a
    reasoning result."""
    formalization = await DeterministicExtractor().formalize(goal, premises)
    assert formalization.succeeded is succeeded
    assert formalization.connectivity is connectivity


def test_a_failed_formalization_is_never_reported_connected():
    from core.reasoning.reasoning_interfaces import Formalization

    assert Formalization(succeeded=False).connectivity is Connectivity.UNSUPPORTED
    assert Formalization(succeeded=True).connectivity is Connectivity.CONNECTED


# ── names keep their words ──────────────────────────────────────────────────

@pytest.mark.parametrize("label,as_name,as_phrase", [
    ("A major", "a_major", "major"),
    ("A Day in the Life", "a_day_in_the_life", "day_in_the_life"),
    ("The Beatles", "the_beatles", "beatle"),
    ("F-sharp minor", "f_sharp_minor", "f_sharp_minor"),
])
def test_a_name_keeps_its_words_and_a_phrase_is_read_as_before(label, as_name, as_phrase):
    """A determiner and a plural are grammar in a noun phrase and part of a
    title. The key "A major" became the word `major` until a producer could
    say a label is a name."""
    assert lexical.canonical_label(label, name=True) == as_name
    assert ConceptResolver().canonical_label(label, name=True) == as_name
    assert lexical.canonical_label(label) == as_phrase


def test_a_producer_says_which_concept_is_a_name():
    from core.domain.concept_ingestion import ConceptIngestionService, EvidenceEnvelope
    from core.domain.concept_ingestion import EvidenceSourceType
    from core.domain.concept_ingestion import ConceptExtractor
    envelope = EvidenceEnvelope(
        evidence_id="ev_names", source_type=EvidenceSourceType.PERCEPTION,
        source_id="probe:audio", producer="probe", content="a recording in A major",
        structured_data={"concepts": []})
    read = ConceptExtractor()._read_concepts([
        {"label": "a_major", "kind": "entity", "domains": ["hearing"], "is_name": True},
        {"label": "the_ladders", "kind": "entity", "domains": ["hearing"]}], envelope)
    named, phrase = read
    resolver = ConceptIngestionService().resolver
    assert named.is_name and named.attributes.get("is_name") is True
    assert resolver.resolve(named).name == "a_major"
    assert not phrase.is_name and resolver.resolve(phrase).name == "ladder"
