#!/usr/bin/env python3
"""A name of several words costs what a word costs, and a word English builds sentences from is known by its class.

TWO QUESTIONS ASKED OF A WORD AND NOT OF A RUN OF WORDS.

`_share_among_senses` prices the one choice a reading still has to make where the sentence hands it the word:
"of all the things THIS WORD names, why this one?". It was asked only where the filler was written as ONE word
(`len(stood.split()) == 1`), so every taught name of several words fell to `_share_of` instead -- "of all the
things of this kind, why this one?", asked over a 155,767-word vocabulary, about eleven nats. The composed side
had the same restriction and charged nothing at all for a multi-word name. So a reading that took "Old Testament"
as the one taught name it is paid the vocabulary's price, while a reading that split it into "Old" and
"Testament" paid the cheap per-word price twice -- the opposite of what the reader supposes of the two
(`Reading.supposed`: 2 against 3). Measured against the store on 2026-11-19:

    'Are Psalms part of Old Testament?'
      part_of(Psalms, old testament)             derivation -10.21 -> -1.39   (the taught `part of` frame)
      has_property(?v0, old) & instance_of(?v0, legal document will) & part_of(psalms, ?v0)      -4.38

    'Is writer roberts a The writer?'
      instance_of(writer roberts, writer)        derivation -27.61 -> -6.48, and is now the reading taken

`is_structure` is the other. It asks whether a word is held ONLY inside forms and never as a filler, so one
sighting as a filler disqualifies it for ever -- and WordNet gave a sense to most of the words English builds
its sentences from. Of the twenty-five most structural words in the store, thirteen were held to name things:
"is" (1,337 shapes of sentence against one filler), "to" (728/2), "a" (591/9), "are" (242/1), "on", "with",
"for", "not", "no", "all", "some", "every", "or". Every word that passed -- "the", "of", "in", "and", "was",
"at", "by" -- had no filler at all. A slot's openings are read through `names_nothing` (`filler_openings`), so
"A dog" and "dog" were one opening and the rule they are for could not see English's article.

`holds_a_building_class` answers from the class memory holds the word as, which is evidence from outside that
circle -- the other side of the cut `holds_a_naming_class` makes, off the same counts. Asked as evidence FOR and
never as the absence of it: a view built from a handful of lessons holds no class of any word, and asked the
other way round ("not a naming class") every word written in two frames of a thirteen-lesson view became a word
that names nothing, "cut" among them, and "Tom cut himself." stopped reading at all.

Nothing here needs a store.
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics import derived_reader as dr


# ------------------------------------------------- a run of words is a word to look up

def test_the_fillers_held_for_a_run_are_asked_for_as_a_word_s_are():
    signature = inspect.signature(dr.PatternInventory.holding)
    assert "word" in signature.parameters
    source = inspect.getsource(dr.PatternInventory.holding)
    # Built from the whole run, which is how the loose index is keyed (`_lexical_loose`).
    assert '_loose((word,) if isinstance(word, str) else tuple(word))' in source
    assert "lexicals_with_words(run, loose=True)" in source


def test_how_many_senses_a_run_has_is_a_question_it_can_be_asked():
    source = inspect.getsource(dr._share_among_senses)
    assert "view.holding(words)" in source, "asked of the run it was given, not of one word of it"


def test_a_frame_prices_a_filler_of_several_words_as_it_prices_one():
    source = inspect.getsource(dr._derivation_of)
    assert "_share_among_senses(view, stood.split())" in source
    assert "len(stood.split()) == 1" not in source, (
        "a name of several words fell to the vocabulary's price again")
    # `_share_of` stays for a link with no written surface: there is no run to ask about.
    assert "else _share_of(view, filler," in source


def test_a_composed_reading_pays_for_every_word_it_names_a_thing_with():
    source = inspect.getsource(dr._derivation)
    assert "_share_among_senses(view, construction.words)" in source
    assert "len(construction.words) != 1" not in source, "a multi-word name was free on this side"
    # A packed word is charged here as any other is: left out, "The rock was heavy." took a packed reading
    # saying the rock IS heavy over the one taught for "was".
    assert "_stand_in(construction)" not in source.split('"""')[-1]


# ------------------------------------------------- a word English builds sentences from

def test_the_two_sides_of_the_cut_are_read_off_the_same_counts():
    naming = inspect.getsource(dr.PatternInventory.holds_a_naming_class)
    building = inspect.getsource(dr.PatternInventory.holds_a_building_class)
    for both in ("self.word_classes.get(word)", "max(classes, key=lambda c: (classes[c], c))"):
        assert both in naming and both in building, both
    assert "in self.NAMING_CLASSES" in naming
    assert "not in self.NAMING_CLASSES" in building


def test_a_word_memory_holds_no_class_of_says_nothing_either_way():
    """EVIDENCE FOR, NOT THE ABSENCE OF IT. `bool(classes)` is the guard that keeps a lesson-sized view, which
    holds no class of any word, answering exactly as it did before."""
    building = inspect.getsource(dr.PatternInventory.holds_a_building_class)
    assert "return bool(classes) and" in building
    view = dr.PatternInventory()
    assert view.holds_a_building_class("a") is False, "nothing taught, nothing to say"
    assert view.holds_a_naming_class("a") is False


def test_what_builds_sentences_and_what_names_things_are_told_apart_by_class():
    view = dr.PatternInventory()
    view.word_classes.update({"a": {"DETERMINER": 158, "NOUN": 7}, "is": {"AUXILIARY": 900, "VERB": 3},
                              "to": {"PARTICLE": 700, "NOUN": 1}, "and": {"CONJUNCTION": 150},
                              "cut": {"VERB": 40, "NOUN": 9}, "rock": {"NOUN": 30},
                              "heavy": {"ADJECTIVE": 22}, "west": {"NAME": 12, "PREPOSITION": 2}})
    for word in ("a", "is", "to", "and"):
        assert view.holds_a_building_class(word) is True, word
        assert view.holds_a_naming_class(word) is False, word
    for word in ("cut", "rock", "heavy", "west"):
        assert view.holds_a_building_class(word) is False, word
        assert view.holds_a_naming_class(word) is True, word


def test_a_word_that_names_a_concept_is_still_no_structure_word_on_the_old_test():
    """The guard the strict test carries is kept where it is asked: "color", held only inside "What color is the
    ?slot0?", names the concept `color`. Only the class may say otherwise, and only when memory holds one."""
    source = inspect.getsource(dr.PatternInventory.names_nothing)
    assert "self.is_structure(word) and word not in self._named" in source
    assert "or self.holds_a_building_class(word)" in source
    assert "self._shapes.get(word, 0) <= 1" in source, "one shape is one sighting, not evidence"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
