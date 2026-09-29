#!/usr/bin/env python3
"""The deterministic prose reader must not be defeated by an article.

`DeterministicExtractor` is the model-free path from English into logic. When
it returns None the sentence never reaches a solver at all, and the symbolic
result comes back at 0.0 confidence -- which reads as "the substrate cannot
reason about this" when the truth is "the substrate was never given it".

Measured before the fix: "robin is a bird" parsed correctly while "A robin is a
bird" returned None, because the subject group is deliberately a single token
and "A robin" is two.

READING MOVED OUT OF `neural_bridge` on 2026-08-24, into
`core.semantics.sentence_reader.SentenceReader`. These tests kept calling
`DeterministicExtractor._parse_statement` and so raised AttributeError on every
one of them from that day -- nine assertions about the model-free path that
stopped being checked without ever going red in a way anyone read. The fixture
now hands back the reader the reader itself delegates to, so the test still
pins the PRODUCTION path rather than a second instance of its own.
"""

import pytest

from core.reasoning.neural_bridge import DeterministicExtractor


@pytest.fixture
def reader():
    """The very reader `DeterministicExtractor` uses -- not a fresh one, so a
    change to what the reader delegates to shows up here."""
    return DeterministicExtractor()._reader


#: The claim under test is REPRESENTABILITY -- that an article does not make a
#: sentence vanish. Which reading it then receives is genericity's business and
#: is pinned in tests/test_genericity.py, so the subject is checked wherever
#: that reading puts it.
@pytest.mark.parametrize("sentence,subject,kind", [
    ("A robin is a bird", "robin", "universal"),
    ("An oak is a tree", "oak", "universal"),
    ("The vault is locked", "vault", "fact"),
    ("robin is a bird", "robin", "fact"),
    ("Socrates is human", "Socrates", "fact"),
])
def test_a_leading_article_does_not_make_a_sentence_unrepresentable(
        reader, sentence, subject, kind):
    parsed = reader._parse_statement(sentence)
    assert parsed is not None, f"{sentence!r} is unrepresentable"
    assert parsed["kind"] == kind
    assert parsed.get("subject", parsed.get("p")) == subject
    assert parsed["negated"] is False


def test_negation_survives_the_article(reader):
    parsed = reader._parse_statement("A whale is not a fish")
    assert parsed is not None and parsed["negated"] is True
    # A generic-kind reading puts the subject in `p`.
    assert parsed.get("subject", parsed.get("p")) == "whale"


def test_a_question_with_an_article_still_forms_a_goal(reader):
    goal = reader._parse_goal("Is a robin an animal?")
    assert goal is not None
    assert goal["subject"] == "robin"


def test_universals_are_not_captured_by_the_fact_pattern(reader):
    """Order matters: 'All humans are mortal' must stay a universal, or the
    syllogism that the symbolic path proves at 0.98 stops working."""
    parsed = reader._parse_statement("All humans are mortal")
    assert parsed["kind"] == "universal"
    assert parsed["p"] == "humans" and parsed["q"] == "mortal"
    negative = reader._parse_statement("No birds are mammals")
    assert negative["kind"] == "universal" and negative["negated"] is True


def test_articles_are_stripped_when_the_atom_is_built(reader):
    """The determiner is admitted by the pattern; the atom must not keep it."""
    assert reader._atom("robin", "a bird") == reader._atom("robin", "bird")
    assert "_a_" not in reader._atom("robin", "an animal")
