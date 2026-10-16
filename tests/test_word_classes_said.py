"""A word's class is learned from how English uses it: from what was said. A fact taught with no sentence is
remembered as its claim, the triple the door writes ("giraffe defined with tall"), and implies nothing of its words:
read as English, every term of WordNet's adjective facts was a thing, and "tall" was a NOUN 279 times against the one
ADJECTIVE WordNet states (2026-10-12)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics.genericity import classes_implied_by  # noqa: E402


def test_a_claim_no_one_said_implies_no_word_class():
    assert classes_implied_by("giraffe defined with tall", "giraffe", "defined_with", "tall") == {}
    assert classes_implied_by("leaning_tower defined with tall", "leaning tower", "defined_with", "tall") == {}
    assert classes_implied_by("tall similar to high", "tall", "similar_to", "high") == {}


def test_what_was_said_still_teaches_its_words_classes():
    said = classes_implied_by("The giraffe is tall.", "giraffe", "has_property", "tall")
    assert said.get("tall") == "ADJECTIVE" and said.get("giraffe") == "NOUN"
    kind = classes_implied_by("A robin is a thrush.", "robin", "isa", "thrush")
    assert kind.get("robin") == "NOUN" and kind.get("thrush") == "NOUN"
