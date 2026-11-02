#!/usr/bin/env python3
"""A verb's frames are a whole analysis of a happening, so one of them answers for all of its places.

`Lexicon.framed` was asked for one place per call and chose afresh among the frames that fit. Of `paint`'s VerbNet
frames the one naming "with" is the filling analysis -- {subject: done_by, object: moves_to, pp:with: done_to}, where
the paint is what is applied and the medal where it goes -- while the object's link came from another frame
({subject: done_by, object: done_to}). Asked a place at a time, "Roy painted the medal with paint." was read as a
painting DONE TO TWO THINGS, which no single frame says, and the paint stopped being what it was done with
(TRAIN-FORMAT-02, 2026-11-02).

These tests pin the property that failure violated: the links a happening's places are given must come from one
analysis. A frame may speak of a place only where it agrees with the links already given, and a place no agreeing
frame names is left to the grammar's own link rather than taken from a frame that contradicts the rest.
"""
from collections import Counter

import pytest

from core.semantics import grammar as gm


def _lexicon(frames):
    """A lexicon holding these frames of the verb "paint", of its sense `coat paint` and of the word; no word is
    held (`gm.Words` answers for a word nothing is held of), so the frames are all the evidence here."""
    lexicon = gm.Lexicon(gm.Words())
    lexicon.sense_used["paint"]["coat paint"] = 14
    lexicon.sense_used["paint"]["represent paint"] = 12
    for key, held in frames.items():
        lexicon.frames_said["paint"][key] = Counter({tuple(sorted(f.items())): n for f, n in held})
    return lexicon


#: VerbNet's frames of `paint`, as a word recorded whole holds them: its object what is painted, and, in the filling
#: analysis, the surface it goes onto with what is applied said after "with".
PAINTED = {"coat paint": [({"subject": "done_by", "object": "done_to"}, 1),
                          ({"subject": "done_by", "object": "done_to", "pp:to": "moves_to"}, 1)],
           "": [({"subject": "done_by", "object": "done_to"}, 8),
                ({"subject": "done_by", "object": "moves_to", "pp:with": "done_to"}, 1),
                ({"subject": "done_by", "object": "done_to", "pp:*": "moves_to"}, 1)]}


def test_a_happening_is_never_done_to_two_things_because_two_frames_answered_it():
    lexicon = _lexicon(PAINTED)
    places = lexicon.places_framed("paint", "coat paint", ["subject", "object", "pp:with"],
                                   {"subject": "done_by", "object": "done_to", "pp:with": "done_with"})
    assert places["object"] == "done_to"
    assert list(places.values()).count("done_to") == 1
    # Nothing of the word's frames names "with" that agrees with the object being what was painted, so the place is
    # left to the grammar's own link ("with paint" is what the painting was done with).
    assert "pp:with" not in places


def test_the_analysis_chosen_is_the_one_fitting_the_places_said():
    lexicon = _lexicon(PAINTED)
    # Said with a "to" and no "with", the filling frame of the sense fits and says where it moves to.
    places = lexicon.places_framed("paint", "coat paint", ["subject", "object", "pp:to"],
                                   {"subject": "done_by", "object": "done_to", "pp:to": "moves_to"})
    assert places == {"subject": "done_by", "object": "done_to", "pp:to": "moves_to"}


def test_a_preposition_a_frame_names_is_answered_by_it():
    # "The chicken is pecking at Tom." is a pecking done to Tom (`chew-39.2-1`: "NP V PP-Conative").
    lexicon = _lexicon({"coat paint": [({"subject": "done_by", "pp:at": "done_to"}, 1)]})
    places = lexicon.places_framed("paint", "coat paint", ["subject", "pp:at"],
                                   {"subject": "done_by", "pp:at": None})
    assert places["pp:at"] == "done_to"


def test_what_teaching_said_of_a_place_is_what_the_frames_must_agree_with():
    lexicon = _lexicon(PAINTED)
    # Taught that the object is what the painting moves to, the frames saying it is what was painted may no longer
    # speak of the places said with it; the filling frame may, and it is the one that names "with".
    places = lexicon.places_framed("paint", "coat paint", ["subject", "object", "pp:with"],
                                   {"subject": "done_by", "object": "done_to", "pp:with": "done_with"},
                                   {"object": "moves_to"})
    assert "object" not in places           # the caller keeps what teaching said
    assert places.get("pp:with") == "done_to"


def test_a_place_no_frame_gives_is_left_to_the_grammar():
    lexicon = _lexicon(PAINTED)
    places = lexicon.places_framed("paint", "coat paint", ["subject", "object", "pp:about"],
                                   {"subject": "done_by", "object": "done_to", "pp:about": "about"})
    assert "pp:about" not in places


def test_a_verb_with_no_frames_says_nothing():
    lexicon = _lexicon({})
    assert lexicon.places_framed("paint", "coat paint", ["subject", "object"], {}) == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
