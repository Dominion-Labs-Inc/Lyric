#!/usr/bin/env python3
"""Reading and speaking what the substrate was TAUGHT: a sentence with its meaning.

`derived_reader` holds what a pattern and a meaning are, and reads and speaks
through the view memory warms. What must hold, and each has a way to be wrong:

    PIECES     a sentence splits into its pieces with nothing lost or changed
    MEANING    one meaning is written one way, whatever its facts' order or its
               variables' names -- and two different meanings never collide
    PATTERN    identity is exact; the belief's claim is what the fan-out writes
    READ/SAY   a taught sentence reads to its meaning and its meaning says it
               back; an untaught one reads to nothing; one taught two ways is
               reported both ways, never resolved silently
    FORMALIZE  the reasoner gets atoms only for ground taught statements, in
               the same atom vocabulary as held graph facts
    TEACHING   a record's meaning is bound to its situation; what cannot be held
               is counted, not invented

Pure: no database, no memory, nothing written anywhere. Where the formalizer
reads memory's view, the test hands it the view.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics import derived_reader as dr
from core.semantics.derived_reader import (Meaning, MeaningFact as F, Pattern,
                                           PatternInventory, pattern_from, read, read_text, say)
from core.semantics.sentence_machine import form_of, surface_of

SHOE = Meaning("tell", (F("instance_of", "?shown", "shoe"),
                        F("owned_by", "?shown", "?speaker")))
COLOR_Q = Meaning("ask", (F("instance_of", "?x", "shoe"),
                          F("has_property", "?x", "?c"),
                          F("instance_of", "?c", "color")), asked=("?c",))
ROBIN = Meaning("tell", (F("isa", "robin", "bird"),))
ROBIN_Q = Meaning("ask", (F("isa", "robin", "bird"),))
NOT_MAMMAL = Meaning("tell", (F("isa", "robin", "mammal", positive=False),))


# ------------------------------------------------------------------ pieces

@pytest.mark.parametrize("text,pieces", [
    ("This is my shoe.", ["This", "is", "my", "shoe", "."]),
    ("It's black.", ["It", "'s", "black", "."]),
    ("The teacher's hat is red.", ["The", "teacher", "'s", "hat", "is", "red", "."]),
    ("The boys' hats are red.", ["The", "boys", "'", "hats", "are", "red", "."]),
    ("The door isn't open.", ["The", "door", "isn", "'t", "open", "."]),
    ("My appt is at 3pm.", ["My", "appt", "is", "at", "3pm", "."]),
    ("The U.S. is a country.", ["The", "U.S", ".", "is", "a", "country", "."]),
    ('"Hi," she said.', ['"', "Hi", ",", '"', "she", "said", "."]),
    ("Wait — is it red?", ["Wait", "—", "is", "it", "red", "?"]),
    ("the Klein four-group costs $3.50", ["the", "Klein", "four", "-", "group", "costs", "$", "3.50"]),
    ("There are twenty-one dogs.", ["There", "are", "twenty", "-", "one", "dogs", "."]),
    ("It rained on 2026-09-29.", ["It", "rained", "on", "2026-09-29", "."]),
    ("COVID-19 is a disease.", ["COVID-19", "is", "a", "disease", "."]),
])
def test_a_sentence_splits_into_its_pieces_with_nothing_lost(text, pieces):
    form = form_of(text)
    assert [p.text for p in form] == pieces
    assert surface_of(form) == text


# ------------------------------------------------------------------ meaning

def test_a_hyphen_joins_the_words_beside_it_into_one_word():
    """A hyphen between two letters is a piece of its own, glued to both words: what "twenty-one" builds is learned
    from "twenty" and "one". Looked up, and counted as a name's words, the words it joins are one word, as written."""
    pieces = form_of("An x-ray is a picture.")
    assert [(p.text, p.space_after) for p in pieces[1:4]] == [("x", False), ("-", False), ("ray", True)]
    assert dr._loose(["X", "-", "ray"]) == ("x-ray",) and dr._loose(["jack", "-", "in", "-", "the", "-", "box"]) \
        == ("jack-in-the-box",)
    assert not dr._parted(form_of("jack-in-the-box")) and dr._parted(form_of("Tom - the boy"))
    assert [len(word) for word in dr._written_words(form_of("a jack-in-the-box"))] == [1, 7]


def test_a_number_built_from_numbers_is_written_as_its_value():
    """"twenty-one" is the number whose addends are 20 and 1, "two hundred and six" one whose addends are 6 and the
    number whose factors are 2 and 100: each meaning is written with the value, as the digits would write it."""
    built = Meaning("tell", (F("instance_of", "?g", "cat"), F("has_count", "?g", "?n"), F("has_addend", "?n", "?m"),
                             F("has_factor", "?m", "2"), F("has_factor", "?m", "100"), F("has_addend", "?n", "6")))
    digits = Meaning("tell", (F("instance_of", "?g", "cat"), F("has_count", "?g", "206")))
    assert built.canonical() == digits.canonical()
    assert built.evaluated() == Meaning("tell", (F("instance_of", "?g", "cat"), F("has_count", "?g", "206")))
    alone = Meaning("tell", (F("isa", "?n", "number"), F("has_addend", "?n", "20")))
    assert alone.evaluated() == alone, "a sum of one number alone is not a number built"


def test_a_meaning_is_written_one_way_whatever_its_order_or_names():
    reordered = Meaning("tell", tuple(reversed(SHOE.facts)))
    renamed = Meaning("ask", (F("instance_of", "?s", "shoe"),
                              F("has_property", "?s", "?k"),
                              F("instance_of", "?k", "color")), asked=("?k",))
    assert reordered.canonical() == SHOE.canonical()
    assert renamed.canonical() == COLOR_Q.canonical()


def test_different_meanings_never_collide():
    assert ROBIN.canonical() != ROBIN_Q.canonical(), "telling is not asking"
    assert ROBIN.canonical() != NOT_MAMMAL.canonical()
    hat = Meaning("tell", (F("instance_of", "?shown", "hat"),
                           F("owned_by", "?shown", "?speaker")))
    theirs = Meaning("tell", (F("instance_of", "?shown", "shoe"),
                              F("owned_by", "?shown", "?listener")))
    assert len({SHOE.canonical(), hat.canonical(), theirs.canonical()}) == 3


@pytest.mark.parametrize("build", [
    lambda: Meaning("shout", (F("isa", "a", "b"),)),
    lambda: Meaning("tell", ()),
    lambda: Meaning("tell", (F("isa", "?x", "b"),), asked=("?x",)),
    lambda: Meaning("ask", (F("isa", "?x", "b"),), asked=("?y",)),
    lambda: Meaning("ask", (F("isa", "?speaker", "b"),), asked=("?speaker",)),
    lambda: Meaning("tell", (F("isa", "a", "b"), F("isa", "a", "b"))),
    lambda: F("related_to", "a", "b"),
    lambda: F("isa", "?Bad", "b"),
    lambda: F("isa", "", "b"),
])
def test_a_malformed_meaning_is_refused(build):
    with pytest.raises(ValueError):
        build()


def test_the_situation_binds_pointing_words_and_nothing_else():
    bound = SHOE.bound({"?shown": "teachers_shoe", "?speaker": "teacher"})
    assert {f.render() for f in bound} == {"instance_of(teachers_shoe, shoe)",
                                           "owned_by(teachers_shoe, teacher)"}
    with pytest.raises(ValueError):
        SHOE.bound({"?who": "teacher"})
    with pytest.raises(ValueError):
        SHOE.bound({"?shown": "?x"})


# ------------------------------------------------------------------ pattern

def test_a_pattern_is_identified_exactly_and_survives_memory():
    pattern = pattern_from("This is my shoe.", SHOE)
    again = pattern_from("This is my shoe.", Meaning("tell", tuple(reversed(SHOE.facts))))
    assert pattern.key == again.key
    assert pattern_from("This is my hat.", SHOE).key != pattern.key
    assert pattern_from("This is my shoe.", ROBIN).key != pattern.key
    restored = Pattern.from_dict(pattern.to_dict())
    assert restored == pattern and restored.key == pattern.key


def test_the_beliefs_claim_is_what_the_fan_out_writes():
    """The fan-out joins a clause's first three parts with spaces; the pattern's
    own claim must be that string, or the belief a re-teach looks up is not the
    belief the first teach wrote."""
    pattern = pattern_from("This is my shoe.", SHOE)
    clause = (*pattern.belief_clause(), "mem_x")
    assert " ".join(str(p) for p in clause[:3] if p) == pattern.claim()


# ------------------------------------------------------------------ read / say

def test_a_taught_sentence_reads_and_its_meaning_speaks():
    view = PatternInventory([pattern_from("This is my shoe.", SHOE),
                             pattern_from("What color is the shoe?", COLOR_Q)])
    assert [r.meaning for r in read("This is my shoe.", view)] == [SHOE]
    assert say(SHOE, view) == ("This is my shoe.",)
    assert say(COLOR_Q, view) == ("What color is the shoe?",)


def test_an_untaught_sentence_reads_to_nothing():
    view = PatternInventory([pattern_from("This is my shoe.", SHOE)])
    for sentence in ("This is my hat.", "This is my shoe. Really.", ""):
        assert read(sentence, view) == ()
    assert say(ROBIN, view) == ()


def test_case_and_marks_are_set_aside_only_when_nothing_reads_as_written():
    view = PatternInventory([pattern_from("This is my shoe.", SHOE)])
    (exact,) = read("This is my shoe.", view)
    assert not exact.loose
    for heard in ("this is my shoe.", "This is my shoe", "THIS IS MY SHOE"):
        (reading,) = read(heard, view)
        assert reading.meaning == SHOE and reading.loose, heard


def test_a_sentence_taught_two_ways_is_reported_both_ways():
    view = PatternInventory([pattern_from("A robin is a bird.", ROBIN),
                             pattern_from("A robin is a bird.", NOT_MAMMAL)])
    assert {r.meaning for r in read("A robin is a bird.", view)} == {ROBIN, NOT_MAMMAL}


def test_the_view_holds_a_pattern_once():
    view = PatternInventory()
    assert view.add(pattern_from("This is my shoe.", SHOE)) is True
    assert view.add(pattern_from("This is my shoe.", SHOE)) is False
    assert len(view) == 1


# ------------------------------------------------------------------ formalize

@pytest.fixture
def taught(monkeypatch):
    """Memory's view, handed to the reader as memory would hand it over."""
    view = PatternInventory([
        pattern_from("A robin is a bird.", ROBIN),
        pattern_from("Is a robin a bird?", ROBIN_Q),
        pattern_from("A robin is not a mammal.", NOT_MAMMAL),
        pattern_from("This is my shoe.", SHOE),
        pattern_from("What color is the shoe?", COLOR_Q),
        pattern_from("Tie your shoe.", Meaning("request", (
            F("instance_of", "?e", "tying"), F("done_by", "?e", "?listener"),
            F("done_to", "?e", "?s"), F("instance_of", "?s", "shoe")))),
    ])
    monkeypatch.setattr(dr, "_live_inventory", lambda: view)
    return view


def test_a_taught_ground_statement_formalizes_in_the_graphs_atom_vocabulary(taught):
    from core.reasoning.neural_bridge import DerivedReadingFormalizer, clause_atom
    atoms, source = asyncio.run(DerivedReadingFormalizer._atoms("A robin is a bird."))
    # The SAME atom a held graph edge `robin isa bird` becomes.
    assert atoms == [clause_atom("robin", "isa", "bird", True)] == ["robin_bird"]
    assert source.startswith("pattern:")
    denied, _ = asyncio.run(DerivedReadingFormalizer._atoms("A robin is not a mammal."))
    assert denied == ["~" + clause_atom("robin", "isa", "mammal", True)]


def test_premises_and_goal_formalize_together(taught):
    from core.reasoning.neural_bridge import DerivedReadingFormalizer
    result = asyncio.run(DerivedReadingFormalizer().formalize(
        "Is a robin a bird?", ["A robin is a bird."]))
    assert result.succeeded and not result.requires_model
    assert result.statement == "robin_bird" and result.premises == ["robin_bird"]


def test_a_taught_conditional_is_one_premise_its_condition_implying_the_rest(taught):
    from core.reasoning.neural_bridge import DerivedReadingFormalizer
    taught.add(pattern_from("If the valve is closed, the tank overflows.", Meaning("tell", (
        F("has_property", "valve", "closed", condition=True), F("has_property", "tank", "overflowing")))))
    atoms, _ = asyncio.run(DerivedReadingFormalizer._atoms("If the valve is closed, the tank overflows."))
    assert atoms == ["(valve_closed) -> (tank_overflowing)"]


@pytest.mark.parametrize("sentence", [
    "A sparrow is a bird.",        # never taught
    "This is my shoe.",            # names nothing without its situation
    "What color is the shoe?",     # asks for a value
    "Tie your shoe.",              # asks for something to be done
])
def test_what_is_not_a_ground_taught_statement_is_declined(taught, sentence):
    from core.reasoning.neural_bridge import DerivedReadingFormalizer
    assert asyncio.run(DerivedReadingFormalizer._atoms(sentence)) is None


def test_a_sentence_taught_two_ways_is_not_formalized(taught):
    from core.reasoning.neural_bridge import DerivedReadingFormalizer
    taught.add(pattern_from("A robin is a bird.",
                            Meaning("tell", (F("isa", "robin", "animal"),))))
    assert asyncio.run(DerivedReadingFormalizer._atoms("A robin is a bird.")) is None


# ------------------------------------------------------------------ teaching

def test_a_record_binds_its_meaning_and_counts_what_it_cannot_hold():
    """A fact about the situation belongs to the speaker's context; a fact naming none of it is the model's; a
    conditional states no fact outright and is held as a rule, one fact a side."""
    from core.learning.teaching import TaughtRecord, TeachingPass
    buckets, rules = {}, []
    counts = {"bound": 0, "speaker_context": 0, "no_speaker": 0, "open": 0, "not_told": 0,
              "rule": 0, "rule_not_held": 0, "alternative": 0}

    def bucket(record):
        TeachingPass._bucket_meaning(record, record.sentence, 0.9, buckets, counts, rules)

    bucket(TaughtRecord("", "", "", 0.9, sentence="This is my shoe.", meaning=SHOE,
                        situation=(("?shown", "teachers_shoe"), ("?speaker", "teacher"))))
    bucket(TaughtRecord("", "", "", 0.9, sentence="A robin is not a mammal.", meaning=NOT_MAMMAL))
    bucket(TaughtRecord("", "", "", 0.9, sentence="What color is the shoe?", meaning=COLOR_Q))
    bucket(TaughtRecord("", "", "", 0.9, sentence="This is my shoe.", meaning=SHOE))
    bucket(TaughtRecord("", "", "", 0.9, sentence="This is my shoe.", meaning=SHOE,
                        situation=(("?shown", "teachers_shoe"),)))
    closed = Meaning("tell", (F("has_property", "valve", "closed", condition=True),
                              F("has_property", "tank", "overflowing")))
    bucket(TaughtRecord("", "", "", 0.9, sentence="If the valve is closed, the tank overflows.", meaning=closed))
    both = Meaning("tell", (F("has_property", "valve", "closed", condition=True),
                            F("has_property", "tank", "overflowing"), F("has_property", "floor", "wet")))
    bucket(TaughtRecord("", "", "", 0.9, sentence="If the valve is closed, the tank overflows and the floor is wet.",
                        meaning=both))
    either = Meaning("tell", (F("has_property", "door", "open", alternative=True),
                              F("has_property", "door", "closed", alternative=True)))
    bucket(TaughtRecord("", "", "", 0.9, sentence="The door is open or closed.", meaning=either))
    assert set(buckets[(0.9, True, "teacher")]) == {
        ("teachers_shoe", "instance_of", "shoe", "This is my shoe."),
        ("teachers_shoe", "owned_by", "teacher", "This is my shoe.")}
    assert buckets[(0.9, False, None)] == [("robin", "isa", "mammal", "A robin is not a mammal.")]
    assert set(buckets) == {(0.9, True, "teacher"), (0.9, False, None)}, "a condition is never stated as a fact"
    assert [(q, c.render(), t.render(), whose) for q, c, t, _, whose in rules] == [
        (0.9, "if has_property(valve, closed)", "has_property(tank, overflowing)", None)]
    assert counts == {"bound": 1, "speaker_context": 2, "no_speaker": 1, "open": 3, "not_told": 3,
                      "rule": 1, "rule_not_held": 1, "alternative": 2}


def test_a_record_with_a_meaning_and_no_sentence_is_said_through_what_was_taught(monkeypatch):
    from core.learning.teaching import TaughtRecord, TeachingPass
    view = _lesson_view()
    monkeypatch.setattr(dr, "_live_inventory", lambda: view)
    sense = TaughtRecord("", "", "", 0.9, meaning=_tell(("isa", "flying thing robin", "bird")),
                         words=(("flying thing robin", "robin"),))
    assert TeachingPass._said(sense) == "A robin is a bird.", "the concept is written as the source writes it"
    new = TaughtRecord("", "", "", 0.9, meaning=_tell(("isa", "wren", "bird")))
    assert TeachingPass._said(new) == "A wren is a bird.", "a word never seen, said as its concept is named"
    assert TeachingPass._said(TaughtRecord("", "", "", 0.9, meaning=_tell(("used_for", "saw", "cutting")))) == "", \
        "nothing taught says it: no sentence"
    assert len(view) == len(_lesson_view()), "saying writes nothing"
    with pytest.raises(ValueError):
        TaughtRecord("a", "isa", "b", 0.9, situation=(("?speaker", "teacher"),))
    with pytest.raises(ValueError):
        TaughtRecord("a", "isa", "b", 0.9, words=(("a", "b"),))


def test_memory_exempts_the_pattern_tag_from_the_novelty_filter():
    from core.memory.utils.memory_filter import MemoryFilter
    assert dr.PATTERN_TAG in MemoryFilter.EXEMPT_EVENT_TAGS


# ------------------------------------------------------------------ step 2: constructions found between pairs

def _tell(*facts):
    return Meaning("tell", tuple(F(*f) for f in facts))


def _mine(thing):
    return _tell(("instance_of", "?shown", thing), ("owned_by", "?shown", "?speaker"))


def _it(colour):
    return _tell(("has_property", "?previous", colour))


def _the(thing, colour):
    return _tell(("instance_of", "?shown", thing), ("has_property", "?shown", colour))


_WAVE = (("instance_of", "?e", "waving"), ("done_by", "?e", "?listener"))


def _learn(view, pairs):
    """What the learner does with each pair, without memory or beliefs: read it, or run the first repair that
    applies and fold in what it creates. Returns the repair names, in order ('read' when nothing was needed)."""
    ran = []
    for sentence, meaning in pairs:
        form = form_of(sentence)
        words = tuple(p.text for p in form)
        if dr.readings_of(words, meaning, view):
            ran.append("read")
            continue
        repair = next(r for r in (step(form, meaning, view) for step in dr.REPAIRS) if r is not None)
        for item in repair.constructions + repair.links:
            view.add(item)
        assert dr.readings_of(words, meaning, view), f"{sentence!r} does not read after {repair.name}"
        ran.append(repair.name)
    return ran


def _believed():
    return PatternInventory(score=lambda item: (0.9, 1))


def test_constructions_and_links_are_identified_exactly_and_survive_memory():
    view = _believed()
    _learn(view, [("This is my shoe.", _mine("shoe")), ("This is my hat.", _mine("hat"))])
    for item in view.items():
        restored = dr.item_from(item.kind, item.to_dict())
        assert restored.key == item.key
    (frame,) = view.item_based()
    assert frame.surface == "This is my ?slot0." and frame.slots == ("?slot0",)
    swapped = Meaning("tell", (F("has_property", "?slot1", "?slot0"),))
    straight = Meaning("tell", (F("has_property", "?slot0", "?slot1"),))
    assert swapped.canonical() != straight.canonical(), "a slot is named by its place, never renamed away"


def test_the_repairs_run_in_the_papers_order_each_where_it_applies():
    view = _believed()
    ran = _learn(view, [
        ("This is my shoe.", _mine("shoe")),
        ("This is my hat.", _mine("hat")),
        ("This is my cup.", _mine("cup")),
        ("It is red.", _it("red")),
        ("It is blue.", _it("blue")),
        ("The shoe is red.", _the("shoe", "red")),
        ("The hat is blue.", _the("hat", "blue")),
        ("Wave bye bye.", Meaning("request", tuple(F(*f) for f in _WAVE))),
        ("Wave bye bye to grandma.", Meaning("request", tuple(F(*f) for f in _WAVE + (("done_to", "?e", "grandma"),)))),
        ("Sing the happy song.", Meaning("request", (F("instance_of", "?e", "singing"), F("done_to", "?e", "?s"),
                                                      F("has_property", "?s", "happy")))),
        ("Sing the song.", Meaning("request", (F("instance_of", "?e", "singing"), F("done_to", "?e", "?s")))),
        ("This is my hat.", _mine("hat")),
    ])
    assert ran == ["holophrase", "substitution", "item_based_lexical", "holophrase", "substitution",
                   "lexical_item_based", "add_links", "holophrase", "addition", "holophrase", "deletion", "read"]


def test_a_new_combination_reads_and_is_said_but_an_unseen_pairing_or_shape_is_not():
    view = _believed()
    _learn(view, [("This is my shoe.", _mine("shoe")), ("This is my hat.", _mine("hat")),
                  ("It is red.", _it("red")), ("It is blue.", _it("blue")),
                  ("The shoe is red.", _the("shoe", "red")), ("The hat is blue.", _the("hat", "blue"))])
    assert [r.meaning.canonical() for r in read("The shoe is blue.", view)] == [_the("shoe", "blue").canonical()]
    assert say(_the("hat", "red"), view) == ("The hat is red.",)
    assert read("This is my red.", view) == (), "red is not of the kind that fills that slot"
    assert read("Blue is the shoe.", view) == ()
    (unmarked,) = read("The shoe is blue", view)
    assert unmarked.meaning == _the("shoe", "blue") and unmarked.loose


def test_a_construction_no_longer_believed_takes_no_part_and_the_pair_revives_it():
    scores = {}
    view = PatternInventory(score=lambda item: scores.get(item.key, (0.9, 1)))
    _learn(view, [("This is my shoe.", _mine("shoe"))])
    (held,) = view.holophrases()
    scores[held.key] = (0.2, 3)
    assert read("This is my shoe.", view) == ()
    repair = dr.holophrase(form_of("This is my shoe."), _mine("shoe"), view)
    assert repair.revived == (held,) and repair.constructions == ()


def test_the_best_reading_is_the_most_believed_then_the_most_used():
    scores = {}
    view = PatternInventory(score=lambda item: scores.get(item.key, (0.9, 1)))
    _learn(view, [("This is my shoe.", _mine("shoe")), ("This is my hat.", _mine("hat"))])
    frame = view.item_based()[0]
    scores[frame.key] = (0.9, 5)
    readings = dr.readings_of(tuple(p.text for p in form_of("This is my shoe.")), _mine("shoe"), view)
    assert len(readings) == 2 and readings[0].pattern is frame, "equal belief: the more used reading wins"
    (holophrase,) = view.holophrases()
    scores[holophrase.key] = (0.99, 1)
    readings = dr.readings_of(tuple(p.text for p in form_of("This is my shoe.")), _mine("shoe"), view)
    assert readings[0].pattern is holophrase, "higher belief wins before use counts"


def test_word_kinds_emerge_from_the_slots_they_fill():
    view = _believed()
    _learn(view, [("This is my shoe.", _mine("shoe")), ("This is my hat.", _mine("hat")),
                  ("It is red.", _it("red")), ("It is blue.", _it("blue")),
                  ("The shoe is red.", _the("shoe", "red")), ("The hat is blue.", _the("hat", "blue"))])
    kinds = {frozenset(x.surface for x in kind) for kind in view.word_kinds()}
    assert kinds == {frozenset({"shoe", "hat"}), frozenset({"red", "blue"})}


# ------------------------------------------------------------------ step 3: what reading may suppose

def _lesson_view():
    view = _believed()
    _learn(view, [("This is my shoe.", _mine("shoe")), ("This is my hat.", _mine("hat")),
                  ("This is my ball.", _mine("ball")),
                  ("It is red.", _it("red")), ("It is blue.", _it("blue")),
                  ("The shoe is red.", _the("shoe", "red")), ("The hat is blue.", _the("hat", "blue")),
                  ("A robin is a bird.", _tell(("isa", "robin", "bird"))),
                  ("A sparrow is a bird.", _tell(("isa", "sparrow", "bird")))])
    return view


def test_a_filler_of_the_slots_kind_stands_in_it_and_nothing_is_written():
    view = _lesson_view()
    before = len(view)
    (reading,) = read("The ball is red.", view)
    assert reading.meaning == _the("ball", "red")
    assert [(l.lexical_surface, l.slot) for l in reading.proposed] == [("ball", "?slot0")] and not reading.new
    assert len(view) == before, "a reading writes nothing"
    assert not dr.readings_of(tuple(p.text for p in form_of("The ball is red.")), _the("ball", "red"), view), \
        "the learner still reads strictly, so a taught pair creates the link"


def test_a_word_never_seen_stands_in_a_known_frame_as_a_new_concept():
    view = _lesson_view()
    (reading,) = read("A vex7 is a bird.", view)
    assert reading.meaning == _tell(("isa", "vex7", "bird"))
    assert [lx.value for lx in reading.new] == ["vex7"] and len(reading.proposed) == 1
    assert not read("A Klein four-group is a bird.", view), "the slot has only held one-word names"
    _learn(view, [("A blue jay is a bird.", _tell(("isa", "blue jay", "bird")))])
    (named,) = read("A Klein four-group is a bird.", view)
    assert [lx.value for lx in named.new] == ["Klein four-group"], "several unknown words can be one name"


def test_what_is_known_is_never_taken_for_a_new_name():
    view = _lesson_view()
    assert read("This is my red.", view) == (), "a known word of another kind is not new"
    assert view.is_structure("my") and not view.is_structure("hat")
    assert read("The my hat is red.", view) == (), "a run holding a structure word is not a name"
    _learn(view, [("A blue jay is a bird.", _tell(("isa", "blue jay", "bird")))])
    (named,) = read("A red robin is a bird.", view)
    assert [lx.value for lx in named.new] == ["red robin"], \
        "fillers alone make one new name: a phrase in a slot is the next step, not this one"


def test_new_words_are_anchored_by_the_words_of_the_construction_they_stand_in():
    view = _believed()
    ran = _learn(view, [("A robin is a bird.", _tell(("isa", "robin", "bird"))),
                        ("A sparrow is a bird.", _tell(("isa", "sparrow", "bird"))),
                        ("A robin is an animal.", _tell(("isa", "robin", "animal"))),
                        ("A sparrow is an animal.", _tell(("isa", "sparrow", "animal")))])
    assert ran[-1] == "substitution", "the held 'A robin is ?slot0.' with 'sparrow' where 'robin' stands"
    assert "A ?slot0 is ?slot1." in {p.surface for p in view.item_based()}
    (reading,) = read("A dax is an animal.", view)
    assert reading.meaning == _tell(("isa", "dax", "animal")) and [lx.value for lx in reading.new] == ["dax"]
    (two,) = read("A dax is wug.", view)
    assert {lx.value for lx in two.new} == {"dax", "wug"}, "two words of its own anchor two new ones"
    with pytest.raises(ValueError):
        Pattern((dr.Slot("?slot0", False), dr.Piece(".", False)),
                Meaning("tell", (F("has_property", "?previous", "?slot0"),)))
    two_words = PatternInventory(score=lambda item: (0.9, 1))
    ran = _learn(two_words, [("Birds fly.", _tell(("capable_of", "bird", "fly"))),
                             ("Birds swim.", _tell(("capable_of", "bird", "swim"))),
                             ("Fish fly.", _tell(("capable_of", "fish", "fly"))),
                             ("Fish swim.", _tell(("capable_of", "fish", "swim")))])
    assert "?slot0 ?slot1." not in {p.surface for p in two_words.item_based()}, \
        "a frame keeps a word of its own; a mark alone anchors nothing"
    assert read("Hello there.", two_words) == ()
    causes = _believed()
    _learn(causes, [("Fire causes smoke.", _tell(("causes", "fire", "smoke"))),
                    ("Heat causes smoke.", _tell(("causes", "heat", "smoke"))),
                    ("Fire causes heat.", _tell(("causes", "fire", "heat"))),
                    ("Heat causes fire.", _tell(("causes", "heat", "fire")))])
    assert "?slot0 causes ?slot1." in {p.surface for p in causes.item_based()}
    (rain,) = read("Rain causes floods.", causes)
    assert {lx.value for lx in rain.new} == {"Rain", "floods"}, \
        "one word of its own anchors any number of new words standing one to a slot"


def test_a_new_name_is_no_longer_than_the_slots_kind_has_held():
    view = _believed()
    _learn(view, [("He is kind.", _tell(("has_property", "?previous", "kind"))),
                  ("He is tall.", _tell(("has_property", "?previous", "tall")))])
    (one,) = read("He is brave.", view)
    assert [lx.value for lx in one.new] == ["brave"]
    assert read("He is be working.", view) == (), "the slot has only held one-word fillers"
    _learn(view, [("He is very kind.", _tell(("has_property", "?previous", "very kind")))])
    (two,) = read("He is quite brave.", view)
    assert [lx.value for lx in two.new] == ["quite brave"], "once the kind has held a two-word filler"


def test_the_same_word_in_another_case_is_one_word_of_one_kind():
    view = _believed()
    _learn(view, [("Birds fly.", _tell(("capable_of", "bird", "fly"))),
                  ("Ducks fly.", _tell(("capable_of", "duck", "fly"))),
                  ("Can birds fly?", Meaning("ask", (F("capable_of", "bird", "fly"),))),
                  ("Can cats fly?", Meaning("ask", (F("capable_of", "cat", "fly"),)))])
    (reading,) = read("can ducks fly", view)
    assert reading.meaning == Meaning("ask", (F("capable_of", "duck", "fly"),)) and reading.loose, \
        "Ducks opened a sentence and birds ended one: one word each, one kind"
    assert not reading.new


def test_a_text_is_read_as_the_utterances_that_cover_it():
    view = _lesson_view()
    said = read_text("This is my shoe. It is red. Blah blah. The hat is blue.", view)
    assert [u.text for u in said] == ["This is my shoe.", "It is red.", "Blah blah.", "The hat is blue."]
    assert [u.understood for u in said] == [True, True, False, True]
    assert said[1].readings[0].meaning == _it("red")
    assert read_text("", view) == ()
    (whole,) = read_text("nothing here is taught", PatternInventory(), parts=True)
    assert not whole.understood, "with nothing held, the whole text is one unread utterance"
    assert whole.partial == () and whole.unknown == ("nothing", "here", "is", "taught")


def test_or_is_one_of_its_alternatives_and_generalizes_like_anything_taught():
    def either(thing, a, b):
        return Meaning("ask", (F("has_property", thing, a, alternative=True),
                               F("has_property", thing, b, alternative=True)))
    with pytest.raises(ValueError):
        Meaning("ask", (F("has_property", "stove", "hot", alternative=True),))
    assert either("stove", "hot", "cold").canonical() == \
        "ask: either has_property(stove, cold) & either has_property(stove, hot)"
    assert Meaning.from_dict(either("stove", "hot", "cold").to_dict()) == either("stove", "hot", "cold")
    view = _lesson_view()
    _learn(view, [("Is the shoe red or blue?", either("shoe", "red", "blue"))])
    (reading,) = read("Is the hat blue or red?", view)
    assert reading.meaning == either("hat", "blue", "red")
    told = Meaning("tell", (F("has_property", "sky", "blue", alternative=True),
                            F("has_property", "sky", "grey", alternative=True)))
    _learn(view, [("The sky is blue or grey.", told)])
    assert read("The sky is blue or grey.", view)[0].meaning == told
    assert dr.stated("The sky is blue or grey.", view) == (), "of alternatives, none is stated outright"


def test_sentences_with_only_marks_between_them_are_read_as_sentences():
    view = _lesson_view()
    said = read_text("The shoe is red, the hat is blue.", view)
    assert [u.text for u in said] == ["The shoe is red,", "the hat is blue."]
    assert [u.readings[0].meaning for u in said] == [_the("shoe", "red"), _the("hat", "blue")]


def test_a_phrase_learned_in_one_slot_reads_in_every_slot_of_its_kind():
    view = _lesson_view()
    red_hat = _tell(("instance_of", "?shown", "hat"), ("owned_by", "?shown", "?speaker"), ("has_property", "?shown", "red"))
    assert _learn(view, [("This is my red hat.", red_hat)]) == ["phrase_in_slot"]
    (phrase,) = view.phrases()
    assert phrase.surface == "?slot0 ?slot1"
    assert phrase.canonical() == "?v0 : has_property(?v0, ?slot0) & instance_of(?v0, ?slot1)"
    assert dr.item_from("phrase", phrase.to_dict()) == phrase
    before = len(view)
    (mine,) = read("This is my blue ball.", view)
    assert mine.meaning.canonical() == _tell(("instance_of", "?shown", "ball"), ("owned_by", "?shown", "?speaker"),
                                             ("has_property", "?shown", "blue")).canonical()
    (the,) = read("The blue shoe is red.", view)
    assert the.meaning.canonical() == _tell(("instance_of", "?shown", "shoe"), ("has_property", "?shown", "blue"),
                                            ("has_property", "?shown", "red")).canonical(), \
        "a phrase of the slot's kind stands in another frame"
    assert the.proposed, "and the link it stands through there is proposed, never written"
    assert len(view) == before, "a reading writes nothing"
    (glorpy,) = read("This is my glorpy ball.", view)
    assert [lx.value for lx in glorpy.new] == ["glorpy"], "a phrase of slots alone takes a new word beside a held one"
    assert read("This is my glorpy blick.", view) == (), "and no new word beside nothing held"
    with pytest.raises(ValueError):
        dr.Phrase((dr.Slot("?slot0", False),), "?slot0")


def test_what_it_says_reads_back_to_what_it_meant():
    view = _lesson_view()
    before = len(view)
    for meaning in (_the("ball", "red"),                                   # a filler of the slot's kind
                    _tell(("isa", "vex7", "bird")),                         # a concept no filler names
                    _tell(("isa", "sparrow", "bird"))):                     # linked fillers
        said = dr.say(meaning, view)
        assert said, meaning.canonical()
        assert [r.meaning.canonical() for r in read(said[0], view)] == [meaning.canonical()], said[0]
    assert dr.say(_tell(("isa", "vex7", "bird")), view)[0] == "A vex7 is a bird."
    assert not dr.say(_tell(("used_for", "hammer", "building")), view), "what nothing taught says is not said"
    assert len(view) == before, "saying writes nothing"


def test_what_does_not_read_whole_is_read_in_parts_and_nothing_is_lost():
    view = _lesson_view()
    before = len(view)
    (joined,) = read_text("The shoe is red and the hat is blue.", view, parts=True)
    assert not joined.understood
    assert [part.text for part in joined.partial] == ["The shoe is red", "the hat is blue."]
    assert [part.readings[0].meaning for part in joined.partial] == [_the("shoe", "red"), _the("hat", "blue")]
    assert joined.unknown == ("and",) and [surface_of(run) for run in joined.unread] == ["and"]
    (owned,) = read_text("The teacher's shoe is red.", view, parts=True)
    assert not owned.understood
    assert {part.text: part.fillers[0].value for part in owned.partial if part.fillers} == {"shoe": "shoe",
                                                                                            "red": "red"}
    assert owned.unknown and all("teacher" in word or "'" in word for word in owned.unknown), \
        "only the words nothing held has are unknown: 'The' and 'is' are held as parts of forms"
    assert len(view) == before, "a reading in parts writes nothing"


def test_a_conditional_is_a_meaning_whose_condition_is_not_stated_as_fact():
    closed = Meaning("tell", (F("has_property", "valve", "closed", condition=True),
                              F("has_property", "tank", "overflowing")))
    assert closed.condition == (F("has_property", "valve", "closed", condition=True),)
    assert closed.asserted == (F("has_property", "tank", "overflowing"),)
    assert closed.canonical() == "tell: has_property(tank, overflowing) & if has_property(valve, closed)"
    assert Meaning.from_dict(closed.to_dict()) == closed
    with pytest.raises(ValueError):
        Meaning("tell", (F("has_property", "valve", "closed", condition=True),))
    plain = Meaning.from_dict({"act": "tell", "facts": [["isa", "robin", "bird", True]], "asked": []})
    assert plain == ROBIN and plain.to_dict()["facts"] == [["isa", "robin", "bird", True]], \
        "a meaning stored before conditions existed is read and written exactly as it was"


def test_conditionals_generalize_condition_with_condition():
    def rule(state, outcome):
        return Meaning("tell", (F("has_property", "valve", state, condition=True),
                                F("has_property", "tank", outcome)))
    view = _believed()
    ran = _learn(view, [("If the valve is closed, the tank overflows.", rule("closed", "overflowing")),
                        ("If the valve is open, the tank overflows.", rule("open", "overflowing"))])
    assert ran == ["holophrase", "substitution"]
    (frame,) = view.item_based()
    assert frame.surface == "If the valve is ?slot0, the tank overflows."
    assert frame.meaning.condition == (F("has_property", "valve", "?slot0", condition=True),)
    (reading,) = read("If the valve is closed, the tank overflows.", view)
    assert reading.meaning.condition and not reading.proposed
    (heard,) = read("if the valve is closed the tank overflows", view)
    assert heard.meaning == reading.meaning and heard.loose, "heard without its comma or final mark"


# ------------------------------------------------------------------ step 4: word shapes

def _animal(thing):
    return _tell(("isa", thing, "animal"))


def _plurals_view():
    view = _believed()
    _learn(view, [("Dogs are animals.", _animal("dog")), ("Cats are animals.", _animal("cat")),
                  ("Birds are animals.", _animal("bird")), ("Foxes are animals.", _animal("fox")),
                  ("Lynxes are animals.", _animal("lynx")), ("Flies are animals.", _animal("fly")),
                  ("Ponies are animals.", _animal("pony")), ("Geese are animals.", _animal("goose")),
                  ("A dog is an animal.", _animal("dog")), ("A horse is an animal.", _animal("horse")),
                  ("A puppy is an animal.", _animal("puppy")),
                  ("A car is a vehicle.", _tell(("isa", "car", "vehicle"))),
                  ("A bus is a vehicle.", _tell(("isa", "bus", "vehicle")))])
    return view


def test_word_shapes_are_found_from_the_fillers_each_in_its_context():
    view = _plurals_view()
    assert dr.PatternInventory.changes_between("Foxes", "fox") == (("es", ""), ("xes", "x"), ("oxes", "ox"))
    assert dr.PatternInventory.changes_between("Geese", "goose") == (), "an irregular form is a word of its own"
    shapes = view.word_shapes()
    productive = {change for change in shapes if view.productive(change)}
    assert productive == {("s", ""), ("es", ""), ("xes", "x"), ("ies", "y")}
    assert shapes[("s", "")] == (3, 4), \
        "'bus' is a word `s` would misread; 'flies' and 'foxes' belong to the more particular changes that read them"
    assert not view.productive(("nies", "ny")), "one word is a list, not a shape"


def test_a_word_in_a_learned_shape_reads_as_the_word_it_is_and_is_said_in_the_slots_shape():
    view = _plurals_view()
    before = len(view)
    for sentence, meaning in (("Horses are animals.", _animal("horse")),
                              ("Puppies are animals.", _animal("puppy")),
                              ("A fox is an animal.", _animal("fox"))):   # a concept's own name, held only as "Foxes"
        (reading,) = read(sentence, view)
        assert reading.meaning == meaning and not reading.new, sentence
    for thing, plural in (("horse", "Horses"), ("puppy", "Puppies"), ("lynx", "Lynxes")):
        said = dr.say(_animal(thing), view)
        assert f"{plural} are animals." in said and f"A {thing} is an animal." in said, said
        for sentence in said:
            assert [r.meaning for r in read(sentence, view)] == [_animal(thing)], sentence
    assert len(view) == before, "reading and saying write nothing"


def _from_scratch(view):
    """What the view keeps as items arrive, computed again from everything it holds, as it once was every time."""
    fillers = {}
    for lexical in view.lexicals():
        words = dr._loose(lexical.words)
        if len(words) == 1:
            fillers.setdefault(words[0], set()).add(dr._fold(lexical.value))
    rights = {w: set().union(*(dr.PatternInventory.changes_between(w, n) for n in names))
              for w, names in fillers.items()}
    shapes, productive = {}, set()
    for change in sorted(set().union(*rights.values()), key=lambda c: (-len(c[0]), c)):
        right = covered = 0
        for word in fillers:
            if not (word.endswith(change[0]) and len(word) > len(change[0])):
                continue
            if change not in rights[word] and any(len(o[0]) > len(change[0]) and o in productive
                                                  for o in rights[word]):
                continue
            covered += 1
            right += change in rights[word]
        shapes[change] = (right, covered)
        if dr._tolerated(right, covered):
            productive.add(change)
    parent = {}

    def root(key):
        while parent.setdefault(key, key) != key:
            key = parent[key]
        return key

    for (pattern, slot), keys in view._linked.items():
        for key in keys:
            parent[root(key)] = root(keys[0])
    same = {}
    for key in list(parent):
        lexical = view.get(key)
        if isinstance(lexical, dr.Lexical):
            words = dr._loose(lexical.words)
            if len(words) == 1 and dr.PatternInventory.shape_between(words[0], lexical.value) is not None:
                words = (dr._fold(lexical.value),)
            parent[root(key)] = root(same.setdefault((words, lexical.value), key))
    kinds = {}
    for key in parent:
        kinds.setdefault(root(key), set()).add(key)
    after = {}
    for item in view.items():
        if isinstance(item, (Pattern, dr.Phrase)):
            for here, there in zip(item.form, item.form[1:]):
                if not isinstance(here, dr.Piece) or dr._is_mark(here.text):
                    continue
                if isinstance(there, dr.Piece):
                    if there.text[:1].isalpha():
                        after.setdefault(dr._fold(here.text), set()).add(dr._fold(there.text[:1]))
                else:
                    for filler in view.fillers(item.key, there.name):
                        if isinstance(filler, dr.Lexical) and filler.words and filler.words[0][:1].isalpha():
                            after.setdefault(dr._fold(here.text), set()).add(dr._fold(filler.words[0][:1]))
    return shapes, productive, {frozenset(k) for k in kinds.values()}, after


def _said_from_scratch(view):
    """The changes productive in saying, found again: scored over the concepts a word written in a shape is held
    for, the longer name side first."""
    made = {}
    for lexical in view.lexicals():
        words = dr._loose(lexical.words)
        if len(words) == 1 and words[0] != dr._fold(lexical.value):
            made.setdefault(dr._fold(lexical.value), set()).update(
                dr.PatternInventory.changes_between(words[0], lexical.value))
    productive = set()
    for change in sorted(set().union(*made.values()) if made else (), key=lambda c: (-len(c[1]), -len(c[0]), c)):
        applies = [n for n in made if n.endswith(change[1]) and len(n) > len(change[1])]
        right = sum(1 for n in applies if change in made[n])
        covered = sum(1 for n in applies if change in made[n]
                      or not any(len(o[1]) > len(change[1]) and o in productive for o in made[n]))
        if dr._tolerated(right, covered):
            productive.add(change)
    return productive


def test_what_the_view_derives_is_kept_as_items_arrive_in_any_order():
    import random
    source = _plurals_view()
    frame = next(p for p in source.item_based() if p.surface == "?slot0 are animals.")
    # Words ending as `xes` that no shape makes: enough of them and `xes` → `x` stops being productive.
    extra = [dr.Lexical((dr.Piece(word, False),), word) for word in ("wexes", "zaxes", "quixes", "vaxes", "bus")]
    items = list(source.items()) + extra + [dr.link(frame, "?slot0", lexical) for lexical in extra]
    for seed in range(12):
        order = items[:]
        random.Random(seed).shuffle(order)
        view = _believed()
        for item in order:
            view.add(item)
        shapes, productive, kinds, after = _from_scratch(view)
        assert view.word_shapes() == shapes, seed
        assert {c for c in shapes if view.productive(c)} == productive, seed
        assert {frozenset(x.key for x in kind) for kind in view.word_kinds()} == \
            {frozenset(k for k in kind if k in view) for kind in kinds} - {frozenset()}, seed
        assert {w: view.letters_after(w) for w in after} == {w: frozenset(v) for w, v in after.items()}, seed
        for (pattern, slot), keys in view._linked.items():
            present = [view.get(k) for k in keys if isinstance(view.get(k), dr.Lexical)]
            one = [x for x in present if len(dr._loose(x.words)) == 1]
            otherwise = sum(1 for x in one if dr._loose(x.words)[0] != dr._fold(x.value))
            kind = next(k for k in kinds if keys[0] in k)
            written = {dr.PatternInventory.shape_between(dr._loose(view.get(k).words)[0], view.get(k).value)
                       for k in kind if isinstance(view.get(k), dr.Lexical) and len(dr._loose(view.get(k).words)) == 1}
            family = {c for c in _said_from_scratch(view) if dr.PatternInventory._least(c) in written} \
                if otherwise * 2 > len(one) else set()
            assert set(view.shape_of_slot(pattern, slot)) == family, seed
            assert view.filler_openings(pattern, slot) == frozenset(
                dr._begins_with_structure(view, x) for x in present), seed
            assert view.longest_filler(pattern, slot) == max(
                (len(dr._loose(view.get(k).words)) for kind in kinds if keys[0] in kind for k in kind
                 if isinstance(view.get(k), dr.Lexical)), default=0), seed
    assert not view.productive(("xes", "x")), "four words that are no shape of anything outweigh two that are"


def test_a_and_an_are_one_word_in_two_shapes_found_from_what_was_taught():
    view = _believed()

    def kind(thing, of):
        return _tell(("isa", thing, of))

    def what(thing):
        return Meaning("ask", (F("isa", thing, "?x"),), ("?x",))

    def bird(thing):
        return Meaning("ask", (F("isa", thing, "bird"),))
    _learn(view, [("Robins fly.", _tell(("capable_of", "robin", "fly"))),
                  ("Sparrows fly.", _tell(("capable_of", "sparrow", "fly"))),
                  ("Eagles fly.", _tell(("capable_of", "eagle", "fly"))),
                  ("Owls fly.", _tell(("capable_of", "owl", "fly"))),
                  ("What is a robin?", what("robin")), ("What is a sparrow?", what("sparrow")),
                  ("What is an eagle?", what("eagle")), ("What is an owl?", what("owl")),
                  ("Is a robin a bird?", bird("robin")), ("Is a sparrow a bird?", bird("sparrow")),
                  ("Is an eagle a bird?", bird("eagle")), ("Is an owl a bird?", bird("owl")),
                  ("A robin is a songbird.", kind("robin", "songbird")),
                  ("A sparrow is a songbird.", kind("sparrow", "songbird"))])
    assert view.variants_of("a") == {"an"} and view.variants_of("an") == {"a"}
    assert not view.variants_of("is"), "a word alternating with nothing in one place of the same frame"
    before = len(view)
    (owl,) = read("An owl is a songbird.", view)
    assert owl.meaning == kind("owl", "songbird"), "a frame taught only with 'a' reads 'an' before a vowel letter"
    assert dr.say(kind("eagle", "songbird"), view)[0] == "An eagle is a songbird."
    assert dr.say(kind("jay", "songbird"), view)[0] == "A jay is a songbird.", \
        "before a letter neither shape was written before, the shape written before the most letters"
    assert len(view) == before, "reading and saying write nothing"
    assert _learn(view, [("An emu is a songbird.", kind("emu", "songbird"))]) == ["item_based_lexical"], \
        "a new word learned through the frame's other shape"
    assert "An ?slot0 is a songbird." in {p.surface for p in view.item_based()}, \
        "and the frame is held as the sentence wrote it"
    assert view.letters_after("a") & {"e", "o"} == set(), "so the letters after each shape stay as written"


def test_a_new_name_is_never_a_held_name_of_its_concept_with_other_words():
    view = _believed()

    def flies(thing):
        return _tell(("capable_of", thing, "fly"))
    _learn(view, [("Birds can fly.", flies("bird")), ("Ducks can fly.", flies("duck")),
                  ("Geese can fly.", flies("goose")),
                  ("All birds can fly.", flies("bird")), ("All ducks can fly.", flies("duck"))])
    assert not [lx.surface for lx in view.lexicals() if dr._loose(lx.words)[:1] == ("all",)], \
        "'All birds' is no name of `bird`: 'birds' already names it, and 'all' belongs to the frame"
    assert "All ?slot0 can fly." in {p.surface for p in view.item_based()}
    (reading,) = read("All geese can fly.", view)
    assert reading.meaning == flies("goose")


def test_positions_counts_groups_and_contrast_read_as_english_says_them():
    """english_08, never-taught sentences: where things are against each other (as sight finds it too), how many
    there are, a group the speaker is in, and "but" and "although", which say both."""
    view = _lessons_view(8)

    def ask(*facts, asked=()):
        return Meaning("ask", tuple(F(*f) for f in facts), tuple(asked))
    for sentence, meaning in (
            ("The cup is above the bed.", _tell(("above", "cup", "bed"))),
            ("The pen is under the book.", _tell(("below", "pen", "book"))),
            ("The bike is in front of the car.", _tell(("in_front_of", "bike", "car"))),
            ("What is to the right of the book?", ask(("right_of", "?v0", "book"), asked=["?v0"])),
            ("The cat is between the box and the bed.",
             _tell(("between", "cat", "?v0"), ("has_member", "?v0", "box"), ("has_member", "?v0", "bed"))),
            ("Tom owns seven cups.", _tell(("owns", "tom", "?v0"), ("instance_of", "?v0", "cup"), ("has_count", "?v0", "7"))),
            ("There are 9 cats.", _tell(("instance_of", "?v0", "cat"), ("has_count", "?v0", "9"))),
            ("How many bikes does Rex own?", ask(("owns", "rex", "?v0"), ("instance_of", "?v0", "bike"),
                                                 ("has_count", "?v0", "?v1"), asked=["?v1"])),
            ("Our ball is red.", _tell(("has_member", "?v0", "?speaker"), ("owned_by", "?v1", "?v0"),
                                       ("instance_of", "?v1", "ball"), ("has_property", "?v1", "red"))),
            ("Although the dog is small, the cat is big.",
             _tell(("has_property", "dog", "small"), ("has_property", "cat", "big")))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [meaning.canonical()], sentence


def test_events_their_time_and_what_a_shape_adds_read_as_english_says_them():
    """english_09, never-taught sentences: an event of its kind, done by, to and with things; its time against
    when it is said (`?now`), from the verb's shape; a state with a time; what "must" and "might" say of it. A verb
    never taught is read in the shape its slot's fillers are written in ("jumps"), and in a shape that says more of
    it ("jumped": a jumping, before now), as the phrases written so ("barked", "walked") show."""
    view = _lessons_view(9)
    e = "?v0"

    def meaning(act, *facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()
    for sentence, wanted in (
            ("The cat barked.", meaning("tell", ("instance_of", e, "bark"), ("done_by", e, "cat"),
                                        ("precedes", e, "?now"))),
            ("The bird will swim.", meaning("tell", ("instance_of", e, "swim"), ("done_by", e, "bird"),
                                            ("follows", e, "?now"))),
            ("The duck is walking.", meaning("tell", ("instance_of", e, "walk"), ("done_by", e, "duck"),
                                             ("during", e, "?now"))),
            ("Who closed the door?", meaning("ask", ("instance_of", e, "close"), ("done_by", e, "?v1"),
                                             ("done_to", e, "door"), ("precedes", e, "?now"), asked=["?v1"])),
            ("Rex opened the box with a key.", meaning("tell", ("instance_of", e, "opening"), ("done_by", e, "rex"),
                                                       ("done_to", e, "box"), ("done_with", e, "key"),
                                                       ("precedes", e, "?now"))),
            ("The box will be empty.", meaning("tell", ("instance_of", e, "empty"), ("state_of", e, "box"),
                                               ("follows", e, "?now"))),
            ("The cat might climb.", meaning("tell", ("instance_of", e, "climb"), ("done_by", e, "cat"),
                                             ("has_property", e, "possible"))),
            ("It hails.", meaning("tell", ("instance_of", e, "hailing"))),
            ("The dog jumps.", meaning("tell", ("instance_of", e, "jump"), ("done_by", e, "dog"))),
            ("The dog jumped.", meaning("tell", ("instance_of", e, "jump"), ("done_by", e, "dog"),
                                        ("precedes", e, "?now")))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence
    assert view.variants_of("it") == frozenset(), "'it' and 'she' are both written before the 'i' of 'is'"


def test_clauses_are_things_said_of_each_other():
    """english_10, never-taught sentences: "because", "before", "after" and "when" join two situations, each an
    event or a state of its own, and "why" and "when" ask for the cause, or the time."""
    view = _lessons_view(10)

    def meaning(act, *facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()
    climbed = (("instance_of", "?v0", "climb"), ("done_by", "?v0", "cat"), ("precedes", "?v0", "?now"))
    for sentence, wanted in (
            ("The cat climbed because the dog ran.", meaning("tell", *climbed, ("instance_of", "?v1", "run"),
                                                             ("done_by", "?v1", "dog"), ("precedes", "?v1", "?now"),
                                                             ("causes", "?v1", "?v0"))),
            ("The cat climbed after it rained.", meaning("tell", *climbed, ("instance_of", "?v1", "raining"),
                                                         ("precedes", "?v1", "?now"), ("follows", "?v0", "?v1"))),
            ("Why did the cat climb?", meaning("ask", *climbed, ("causes", "?v1", "?v0"), asked=["?v1"])),
            ("When did the cat climb?", meaning("ask", *climbed, ("during", "?v0", "?v1"), asked=["?v1"]))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_the_rest_of_the_verb_reads_as_english_says_it():
    """english_12, never-taught sentences: perfect and progressive times, "going to", the passive, "not", "does",
    how and how often and when an event is, "very", requests asked kindly, "has to". "would" is read where "could"
    was taught, as the two are said in each other's place with the same meaning (`synonyms_of`)."""
    view = _lessons_view(12)
    e, t = "?v0", "?v1"

    def meaning(act, *facts):
        return Meaning(act, tuple(F(*f) for f in facts)).canonical()
    for sentence, wanted in (
            ("Rex had opened the box.", meaning("tell", ("instance_of", e, "opening"), ("done_by", e, "rex"),
                                                ("done_to", e, "box"), ("precedes", e, t), ("precedes", t, "?now"))),
            ("The fish was swimming.", meaning("tell", ("instance_of", e, "swim"), ("done_by", e, "fish"),
                                               ("during", e, t), ("precedes", t, "?now"))),
            ("The dog was chased by the cat.", meaning("tell", ("instance_of", e, "chase"), ("done_by", e, "cat"),
                                                       ("done_to", e, "dog"), ("precedes", e, "?now"))),
            ("The fish did not swim.", meaning("tell", ("instance_of", e, "swim"), ("done_by", e, "fish"),
                                               ("precedes", e, "?now"), ("has_property", e, "false"))),
            ("The cat walked carefully.", meaning("tell", ("instance_of", e, "walk"), ("done_by", e, "cat"),
                                                  ("precedes", e, "?now"), ("has_property", e, "careful"))),
            ("The book is very old.", meaning("tell", ("has_degree", "book", e), ("instance_of", e, "old"),
                                              ("has_property", e, "high"))),
            ("Would you help me?", meaning("request", ("instance_of", e, "help"), ("done_by", e, "?listener"),
                                           ("done_to", e, "?speaker"))),
            ("Don't kick the ball.", meaning("request", ("instance_of", e, "kick"), ("done_by", e, "?listener"),
                                             ("done_to", e, "ball"), ("has_property", e, "false")))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence
    assert "would" in view.synonyms_of("could") and "a" not in view.synonyms_of("an")


def test_the_rest_of_the_noun_phrase_reads_as_english_says_it():
    """english_13, never-taught sentences: the speaker and listener, whose a thing is, one doing a thing to oneself,
    someone and something, every one and none, how many of a kind, numbers past ten met as words, a part of a thing,
    whose, either and neither."""
    view = _lessons_view(13)
    e = "?v0"

    def meaning(act, *facts, asked=()):
        return Meaning(act, tuple(F(f[0], f[1], f[2], f[3] if len(f) > 3 else True, False, f[4] if len(f) > 4 else False)
                                  for f in facts), tuple(asked)).canonical()
    for sentence, wanted in (
            ("The bike is mine.", meaning("tell", ("owned_by", "bike", "?speaker"))),
            ("Tom cut himself.", meaning("tell", ("instance_of", e, "cut"), ("done_by", e, "tom"), ("done_to", e, "tom"),
                                         ("precedes", e, "?now"))),
            ("Someone closed the door.", meaning("tell", ("instance_of", e, "close"), ("done_by", e, "?v1"),
                                                 ("instance_of", "?v1", "person"), ("done_to", e, "door"),
                                                 ("precedes", e, "?now"))),
            ("Nothing is in the cup.", meaning("tell", ("located_in", e, "cup", False))),
            ("Most cats can climb.", meaning("tell", ("instance_of", e, "cat"), ("has_count", e, "most"),
                                             ("capable_of", e, "climb"))),
            ("There are fifteen cats.", meaning("tell", ("instance_of", e, "cat"), ("has_count", e, "15"))),
            ("The window of the house is open.", meaning("tell", ("instance_of", e, "window"), ("part_of", e, "house"),
                                                         ("has_property", e, "open"))),
            ("Whose cat is this?", meaning("ask", ("instance_of", "?shown", "cat"), ("owned_by", "?shown", e),
                                           asked=[e])),
            ("Either the cup or the box is blue.", meaning("tell", ("has_property", "cup", "blue", True, True),
                                                           ("has_property", "box", "blue", True, True)))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_where_events_go_and_how_clauses_join_read_as_english_says_them():
    """english_14 and english_15, never-taught sentences: where an event goes, when and how long it lasts, whom it
    is for; what is known, wanted and tried; a thing a clause is about; while, if, unless, so, to; how; a tag; a
    cleft."""
    view = _lessons_view(15)

    def ev(e, v, who=None, what=None, past=False, cond=False):
        out = [("instance_of", e, v, True, cond)]
        out += [("done_by", e, who, True, cond)] if who else []
        out += [("done_to", e, what, True, cond)] if what else []
        return out + ([("precedes", e, "?now", True, cond)] if past else [])

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(f[0], f[1], f[2], f[3] if len(f) > 3 else True, f[4] if len(f) > 4 else False)
                                  for f in facts), tuple(asked)).canonical()
    for sentence, wanted in (
            ("The bird flew into the box.", meaning("tell", ev("?v0", "fly", "bird", past=True)
                                                    + [("moves_into", "?v0", "box")])),
            ("The dog swam for three days.", meaning("tell", ev("?v0", "swim", "dog", past=True)
                                                     + [("lasts_for", "?v0", "?v1"), ("instance_of", "?v1", "day"),
                                                        ("has_count", "?v1", "3")])),
            ("Rex kicked the ball for Tom.", meaning("tell", ev("?v0", "kick", "rex", "ball", past=True)
                                                     + [("done_for", "?v0", "tom")])),
            ("Rex knows that the dog barked.", meaning("tell", ev("?v0", "know", "rex", "?v1")
                                                       + ev("?v1", "bark", "dog", past=True))),
            ("Rex likes swimming.", meaning("tell", ev("?v0", "like", "rex", "?v1") + ev("?v1", "swim", "rex"))),
            ("The box that Tom closed is red.", meaning("tell", [("has_property", "?v1", "red"),
                                                                 ("instance_of", "?v1", "box")]
                                                        + ev("?v0", "close", "tom", "?v1", past=True))),
            ("If it rains, the cat runs.", meaning("tell", ev("?v1", "raining", cond=True) + ev("?v0", "run", "cat"))),
            ("Rex opened the door to help Tom.", meaning("tell", ev("?v0", "opening", "rex", "door", past=True)
                                                         + ev("?v1", "help", "rex", "tom")
                                                         + [("has_purpose", "?v0", "?v1")])),
            ("How big is the cat?", meaning("ask", [("has_degree", "cat", "?v0"), ("instance_of", "?v0", "big")],
                                            ["?v0"])),
            ("It was Tom who kicked the ball.", meaning("tell", ev("?v0", "kick", "tom", "ball", past=True)))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence
    (reading,) = read("The dog jumped.", view)[:1]
    assert reading.meaning.canonical() == meaning("tell", ev("?v0", "jump", "dog", past=True)), \
        "'jumped', held only inside frames, is `jump` written in a shape, not a word that builds sentences"


def test_answers_exclamations_and_what_would_be_read_as_english_says_them():
    """english_16, never-taught sentences: an answer is a verdict on what was just said, whatever pronoun it is
    said with ("she" read where "he" was taught, as each is said in the other's place); an exclamation, a degree;
    "let's", a request of speaker and listener; one clause said for two; what would be; one event's degree against
    another's."""
    view = _lessons_view(16)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(f[0], f[1], f[2], f[3] if len(f) > 3 else True, f[4] if len(f) > 4 else False)
                                  for f in facts), tuple(asked)).canonical()
    for sentence, wanted in (
            ("Yes, she did.", meaning("tell", [("has_property", "?previous", "true")])),
            ("What a cold room!", meaning("tell", [("has_degree", "room", "?v0"), ("instance_of", "?v0", "cold"),
                                                   ("has_property", "?v0", "high")])),
            ("Let's climb.", meaning("request", [("instance_of", "?v0", "climb"), ("done_by", "?v0", "?v1"),
                                                 ("has_member", "?v1", "?speaker"),
                                                 ("has_member", "?v1", "?listener")])),
            ("Rex can swim, but Tom cannot.", meaning("tell", [("capable_of", "rex", "swim"),
                                                               ("capable_of", "tom", "swim", False)])),
            ("If it had rained, the cat would have run.", meaning("tell", [
                ("instance_of", "?v1", "raining", True, True), ("precedes", "?v1", "?now", True, True),
                ("instance_of", "?v0", "run"), ("done_by", "?v0", "cat"), ("precedes", "?v0", "?now"),
                ("has_property", "?v0", "hypothetical")])),
            ("The cat runs faster than the dog.", meaning("tell", [
                ("instance_of", "?v0", "run"), ("done_by", "?v0", "cat"), ("instance_of", "?v1", "run"),
                ("done_by", "?v1", "dog"), ("has_degree", "?v0", "?v2"), ("instance_of", "?v2", "fast"),
                ("has_degree", "?v1", "?v3"), ("instance_of", "?v3", "fast"), ("exceeds", "?v2", "?v3")]))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence
    assert view.variants_of("it") == frozenset() and "he" in view.synonyms_of("it"), \
        "'it' and 'he' are said in each other's place; the letter after them does not decide which"


def test_numbers_order_measures_and_times_read_as_english_says_them():
    """english_17, never-taught sentences: a number built of number words is its value, and "five hundred and three"
    is five hundred, and three; a place in an order; how much a degree measures; a span from an event until now;
    words said of an event (soon, again, still, yet), a verb's own word where it is also a thing's ("snow"); "only"
    as nothing else; "else" and "other" as other than what was spoken of; a count of events; "there"."""
    view = _lessons_view(17)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(f[0], f[1], f[2], f[3] if len(f) > 3 else True) for f in facts),
                       tuple(asked)).canonical()

    def event(verb, who=None, *rest):
        return [("instance_of", "?v0", verb)] + ([("done_by", "?v0", who)] if who else []) + list(rest)
    past = ("precedes", "?v0", "?now")
    for sentence, wanted in (
            ("There are sixty-seven dogs.", meaning("tell", [("instance_of", "?v0", "dog"), ("has_count", "?v0", "67")])),
            ("There are five hundred and three cups.", meaning("tell", [("instance_of", "?v0", "cup"),
                                                                        ("has_count", "?v0", "503")])),
            ("The seventh dog is big.", meaning("tell", [("instance_of", "?v0", "dog"), ("has_rank", "?v0", "7"),
                                                         ("has_property", "?v0", "big")])),
            ("The tree is eight meters tall.", meaning("tell", [
                ("has_degree", "tree", "?v0"), ("instance_of", "?v0", "tall"), ("has_measure", "?v0", "?v1"),
                ("instance_of", "?v1", "meter"), ("has_count", "?v1", "8")])),
            ("The fish swam three days ago.", meaning("tell", event("swim", "fish", past) + [
                ("lasts_since", "?v1", "?v0"), ("lasts_until", "?v1", "?now"), ("instance_of", "?v1", "day"),
                ("has_count", "?v1", "3")])),
            ("It will snow soon.", meaning("tell", event("snowing", None, ("follows", "?v0", "?now"),
                                                           ("has_property", "?v0", "soon")))),
            ("The bird has just flown.", meaning("tell", event("fly", "bird", past, ("has_property", "?v0", "recent")))),
            ("The bird has not flown yet.", meaning("tell", event("fly", "bird", past, ("has_property", "?v0", "false"),
                                                                  ("has_property", "?v0", "yet")))),
            ("Only the cat can climb.", meaning("tell", [("capable_of", "cat", "climb"),
                                                         ("capable_of", "?v0", "climb", False),
                                                         ("other_than", "?v0", "cat")])),
            ("Only Rex walked.", meaning("tell", event("walk", "rex", past) + [
                ("instance_of", "?v1", "walk"), ("done_by", "?v1", "?v2"), ("other_than", "?v2", "rex"),
                ("precedes", "?v1", "?now"), ("has_property", "?v1", "false")])),
            ("The other fish swam.", meaning("tell", event("swim", "?v1", past) + [
                ("instance_of", "?v1", "fish"), ("other_than", "?v1", "?previous")])),
            ("The cat ran three times.", meaning("tell", event("run", "cat", past, ("has_count", "?v0", "3")))),
            ("The bird flew there.", meaning("tell", event("fly", "bird", past, ("moves_to", "?v0", "?there"))))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_giving_saying_and_asking_read_as_english_says_them():
    """english_18, never-taught sentences: who receives what an event passes, either way English says it; what was
    said, and when what was said was so, from the time it was said; a question or a request said inside another;
    each other; "one" as the kind said before; "used to"; a verb of two words, apart or together; making and letting
    an event happen; who is spoken to."""
    view = _lessons_view(18)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()

    def event(at, verb, who=None, what=None, to=None, past=True):
        return ([("instance_of", at, verb)] + ([("done_by", at, who)] if who else []) + ([("done_to", at, what)]
                if what else []) + ([("received_by", at, to)] if to else []) + ([("precedes", at, "?now")] if past else []))
    for sentence, wanted in (
            ("Rex sent Tom the cup.", meaning("tell", event("?v0", "send", "rex", "cup", "tom"))),
            ("Tom showed the book to Rex.", meaning("tell", event("?v0", "show", "tom", "book", "rex"))),
            ("Tom said that the cat had run.", meaning("tell", event("?v0", "say", "tom", "?v1") + event(
                "?v1", "run", "cat", past=False) + [("precedes", "?v1", "?v0")])),
            ("Tom said that the bird would fly.", meaning("tell", event("?v0", "say", "tom", "?v1") + event(
                "?v1", "fly", "bird", past=False) + [("follows", "?v1", "?v0")])),
            ("Rex asked where the dog ran.", meaning("tell", event("?v0", "ask", "rex", "?v2") + event(
                "?v1", "run", "dog") + [("moves_to", "?v1", "?v2")])),
            ("Tom asked Rex to close the door.", meaning("tell", event("?v0", "ask", "tom", "?v1", "rex") + event(
                "?v1", "close", "rex", "door", past=False))),
            ("Rex and Tom helped each other.", meaning("tell", event("?v0", "help", "rex", "tom")
                                                       + event("?v1", "help", "tom", "rex"))),
            ("Rex owns a red ball and Tom owns a blue one.", meaning("tell", [
                ("owns", "rex", "?v0"), ("instance_of", "?v0", "ball"), ("has_property", "?v0", "red"),
                ("owns", "tom", "?v1"), ("instance_of", "?v1", "ball"), ("has_property", "?v1", "blue")])),
            ("Rex used to swim.", meaning("tell", event("?v0", "swim", "rex") + [("has_property", "?v0", "usually")])),
            ("Rex put the cup down.", meaning("tell", event("?v0", "put down", "rex", "cup"))),
            ("Rex let the bird fly.", meaning("tell", event("?v0", "fly", "bird") + [("enables", "rex", "?v0")])),
            ("Rex, open the door.", meaning("request", event("?v0", "opening", "rex", "door", past=False)))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_words_ending_as_uncounted_words_do_are_said_without_a():
    """english_19: words that go without "a", taught by the endings that mostly say so ("-ity", "-ics", "-ence"),
    beside counted words ending so ("a city", "a fence"). A word never held ending so is used as they are; an
    ending the lessons leave mixed ("-dom": "freedom", "a kingdom") decides nothing."""
    view = _lessons_view(19)
    for word in ("serendipity", "credulity", "bionics", "aerodynamics", "insolence", "radiance"):
        assert view.use_of(word) == "mass", word
    for word in ("city", "community", "fence", "kingdom", "ocelot"):
        assert view.use_of(word) == "count", word


def test_concession_places_and_what_might_have_been_read_as_english_says_them():
    """english_20, never-taught sentences: "although" (the event held though the other was against it); where a
    thing is (near, inside, outside, under); "without", "except", "because of", "during"; too much or enough for
    something to happen; what might have been; one of a group; a month or a year."""
    view = _lessons_view(20)

    def meaning(act, facts):
        return Meaning(act, tuple(F(f[0], f[1], f[2], f[3] if len(f) > 3 else True) for f in facts)).canonical()

    def event(at, verb, who=None, *rest):
        return [("instance_of", at, verb)] + ([("done_by", at, who)] if who else []) + [("precedes", at, "?now")] \
            + list(rest)
    for sentence, wanted in (
            ("Although it snowed, the bird flew.", meaning("tell", event("?v1", "snowing") + event(
                "?v0", "fly", "bird", ("has_property", "?v0", "unexpected")))),
            ("The ball is near the box.", meaning("tell", [("near", "ball", "box")])),
            ("The bird is outside the house.", meaning("tell", [("located_in", "bird", "house", False)])),
            ("The cat ran without the dog.", meaning("tell", event("?v0", "run", "cat", ("done_by", "?v0", "dog", False)))),
            ("Everyone except Rex can swim.", meaning("tell", [("capable_of", "person", "swim"),
                                                               ("capable_of", "rex", "swim", False)])),
            ("Rex is old enough to drive.", meaning("tell", [
                ("has_degree", "rex", "?v0"), ("instance_of", "?v0", "old"), ("has_property", "?v0", "enough"),
                ("enables", "?v0", "?v1"), ("instance_of", "?v1", "drive"), ("done_by", "?v1", "rex")])),
            ("Rex might have gone.", meaning("tell", event("?v0", "go", "rex", ("has_property", "?v0", "possible")))),
            ("The cat ran in 1999.", meaning("tell", event("?v0", "run", "cat", ("during", "?v0", "1999"))))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_having_needing_leave_and_what_was_done_to_whom_read_as_english_says_them():
    """english_21 and english_22, never-taught sentences: "have" as owning, beside "has" of a part; things there
    before now; starting and stopping an event; what is needed; asking leave; asking what an event was done to; a
    thing said with "a" doing an event, and a kind doing what it does; "her", "me" and "you" done to; "than me";
    how someone is; "which" and "whose" in a description."""
    view = _lessons_view(22)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()

    def event(at, verb, who=None, what=None, past=True):
        return ([("instance_of", at, verb)] + ([("done_by", at, who)] if who else [])
                + ([("done_to", at, what)] if what else []) + ([("precedes", at, "?now")] if past else []))
    for sentence, wanted in (
            ("Rex has a bike.", meaning("tell", [("owns", "rex", "bike")])),
            ("A spider has legs.", meaning("tell", [("has_part", "spider", "leg")])),
            ("There were three dogs.", meaning("tell", [("instance_of", "?v0", "dog"), ("has_count", "?v0", "3"),
                                                         ("precedes", "?v0", "?now")])),
            ("The bird stopped flying.", meaning("tell", event("?v0", "stop", "bird", "?v1")
                                                 + event("?v1", "fly", "bird", past=False))),
            ("Rex needs a cup.", meaning("tell", [("requires", "rex", "cup")])),
            ("May I open the box?", meaning("ask", event("?v0", "opening", "?speaker", "box", past=False)
                                            + [("has_property", "?v0", "allowed")])),
            ("Who did the cat chase?", meaning("ask", event("?v0", "chase", "cat", "?v1"), ["?v1"])),
            ("A girl opened the box.", meaning("tell", event("?v0", "opening", "?v1", "box")
                                               + [("instance_of", "?v1", "girl")])),
            ("Birds swim.", meaning("tell", event("?v0", "swim", "bird", past=False))),
            ("Rex saw her.", meaning("tell", event("?v0", "see", "rex", "?previous"))),
            ("Rex is taller than me.", meaning("tell", [
                ("has_degree", "rex", "?v0"), ("instance_of", "?v0", "tall"), ("has_degree", "?speaker", "?v1"),
                ("instance_of", "?v1", "tall"), ("exceeds", "?v0", "?v1")])),
            ("How is the dog?", meaning("ask", [("has_property", "dog", "?v0")], ["?v0"])),
            ("The boy whose cat ran is sad.", meaning("tell", [
                ("instance_of", "?v1", "boy"), ("has_property", "?v1", "sad"), ("instance_of", "?v2", "cat"),
                ("owned_by", "?v2", "?v1")] + event("?v0", "run", "?v2")))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_names_origins_and_how_events_follow_read_as_english_says_them():
    """english_23, never-taught sentences: a name (`named`) and where someone is from (`comes_from`), said and
    asked; "so tired that"; "as soon as"; "whenever"; "instead of"; "where" in a description."""
    view = _lessons_view(23)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()

    def event(at, verb, who=None, past=True):
        return [("instance_of", at, verb)] + ([("done_by", at, who)] if who else []) + (
            [("precedes", at, "?now")] if past else [])
    for sentence, wanted in (
            ("My name is Rex.", meaning("tell", [("named", "?speaker", "rex")])),
            ("What is the bird's name?", meaning("ask", [("named", "bird", "?v0")], ["?v0"])),
            ("Where is Anna from?", meaning("ask", [("comes_from", "anna", "?v0")], ["?v0"])),
            ("The cat was so tired that it slept.", meaning("tell", [
                ("has_degree", "cat", "?v0"), ("instance_of", "?v0", "tired"), ("has_property", "?v0", "high"),
                ("causes", "?v0", "?v1")] + event("?v1", "sleep", "cat"))),
            ("The bird flew as soon as the dog barked.", meaning("tell", event("?v0", "fly", "bird") + event(
                "?v1", "bark", "dog") + [("follows", "?v0", "?v1"), ("has_property", "?v0", "immediate")])),
            ("Tom swam instead of walking.", meaning("tell", event("?v0", "swim", "tom") + event(
                "?v1", "walk", "tom", past=False) + [("has_property", "?v1", "false")])),
            ("The room where the cat slept is warm.", meaning("tell", [
                ("instance_of", "?v1", "room"), ("has_property", "?v1", "warm")] + event("?v0", "sleep", "cat")
                + [("located_in", "?v0", "?v1")]))):
        assert [r.meaning.canonical() for r in read(sentence, view)][:1] == [wanted], sentence


def test_numbers_to_the_trillions_read_as_english_builds_them():
    """english_24, never-taught numbers: any size, read to its value; parts of one, below zero, and groups of three
    digits. A scale word multiplies a group under a thousand, and a larger group before a smaller one adds. And "a"
    stays a word that builds sentences: set once where a number stands ("two and three quarters" beside "three and a
    half"), it named the number 1, and WordNet's nouns were then learned with their "a" as part of their names."""
    view = _lessons_view(24)
    assert view.is_structure("a") and view.is_structure("an"), "no lesson makes 'a' a word that names something"

    def number(value):
        return Meaning("tell", (F("isa", str(value), "number"),)).canonical()

    def count(value, kind):
        return Meaning("tell", (F("instance_of", "?v0", kind), F("has_count", "?v0", str(value)))).canonical()
    for sentence, wanted in (
            ("Seven trillion three hundred and twelve billion five million and one is a number.",
             number(7312005000001)),
            ("One hundred and twenty-three trillion four hundred and fifty-six billion seven hundred and eighty-nine "
             "million is a number.", number(123456789000000)),
            ("There are twelve thousand three hundred and forty-five cats.", count(12345, "cat")),
            ("There are eighteen thousand dogs.", count(18000, "dog")),
            ("There are 5,000,000 dogs.", count(5000000, "dog")),
            ("Two thirds is a number.", Meaning("tell", (F("instance_of", "?v0", "number"), F("has_dividend", "?v0", "2"),
                                                         F("has_divisor", "?v0", "3"))).canonical()),
            ("Negative nine is a number.", Meaning("tell", (F("instance_of", "?v0", "number"),
                                                            F("has_minuend", "?v0", "0"),
                                                            F("has_subtrahend", "?v0", "9"))).canonical())):
        assert {r.meaning.canonical() for r in read(sentence, view)} == {wanted}, sentence


def test_arithmetic_said_in_words_reads_to_its_operations():
    """english_25, never-taught sentences: each operation's numbers in their places, "times" inside "plus", more
    and less, what kind of number, and what an unknown is, given what it makes."""
    view = _lessons_view(25)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()
    value = [("equals", "?v0", "?v1")]
    for sentence, wanted in (
            ("What is eleven times twelve?", meaning("ask", value + [("has_multiplicand", "?v0", "11"),
                                                                     ("has_factor", "?v0", "12")], ["?v1"])),
            ("What is twenty minus seven?", meaning("ask", value + [("has_minuend", "?v0", "20"),
                                                                    ("has_subtrahend", "?v0", "7")], ["?v1"])),
            ("What is four plus five times six?", meaning("ask", [
                ("equals", "?v0", "?v2"), ("has_augend", "?v0", "4"), ("has_addend", "?v0", "?v1"),
                ("has_multiplicand", "?v1", "5"), ("has_factor", "?v1", "6")], ["?v2"])),
            ("What is two million times three?", meaning("ask", value + [("has_multiplicand", "?v0", "2000000"),
                                                                         ("has_factor", "?v0", "3")], ["?v1"])),
            ("Is three less than eight?", meaning("ask", [("exceeds", "8", "3")])),
            ("Is thirteen prime?", meaning("ask", [("has_property", "13", "prime")])),
            ("If x plus five is nine, what is x?", meaning("ask", [
                ("equals", "?v0", "9", True, True), ("has_augend", "?v0", "x", True, True),
                ("has_addend", "?v0", "5", True, True), ("equals", "x", "?v1")], ["?v1"]))):
        assert {r.meaning.canonical() for r in read(sentence, view)} == {wanted}, sentence


def test_a_written_formula_reads_as_one_term():
    """english_26, never-taught sentences: a formula is one term, however long, and "=", "<", ">" are words; what is
    asked of it, told of it, or asked to be done to it."""
    view = _lessons_view(26)

    def meaning(act, facts, asked=()):
        return Meaning(act, tuple(F(*f) for f in facts), tuple(asked)).canonical()
    solving = [("instance_of", "?v0", "solve"), ("done_by", "?v0", "?listener")]
    for sentence, wanted in (
            ("What is 17 × 23?", meaning("ask", [("equals", "17 × 23", "?v0")], ["?v0"])),
            ("Is 12 > 20?", meaning("ask", [("exceeds", "12", "20")])),
            ("5 × 5 is 26.", meaning("tell", [("equals", "5 × 5", "26")])),
            ("Solve x^2 + 2x - 15 = 0.", meaning("request", solving + [("equals", "x^2 + 2x - 15", "0", True, True)])),
            ("Solve 3x + 2y = 12 and x - y = -1.", meaning("request", solving + [
                ("equals", "3x + 2y", "12", True, True), ("equals", "x - y", "-1", True, True)])),
            ("If 4x = 28, what is x?", meaning("ask", [("equals", "4x", "28", True, True), ("equals", "x", "?v0")],
                                               ["?v0"])),
            ("Factor x^2 - 16.", meaning("request", [("instance_of", "?v0", "factor"), ("done_by", "?v0", "?listener"),
                                                     ("done_to", "?v0", "x^2 - 16")]))):
        assert {r.meaning.canonical() for r in read(sentence, view)} == {wanted}, sentence


def test_there_is_the_last_place_named_and_now_a_moment():
    """What "there" points back to is the last place a meaning names outright; "now", in a conversation, is the
    moment it is, a literal the store holds."""
    from core.semantics.literals import classify_literal, MOMENT
    went = Meaning("tell", (F("instance_of", "?e", "go"), F("done_by", "?e", "tom"), F("moves_to", "?e", "house")))
    assert dr.place_spoken_of(went) == "house"
    assert dr.place_spoken_of(_tell(("isa", "robin", "bird"))) is None
    assert dr.place_spoken_of(Meaning("tell", (F("located_at", "cat", "?there"),))) is None, "no place named outright"
    moment = classify_literal("2026-09-29T21:45:00Z")
    assert moment is not None and moment.kind == MOMENT and moment.concept_type == "temporal"
    assert classify_literal("2026-09-29T21:45:00") is None, "a time without its zone names no one moment"


def test_a_kind_is_said_of_a_kind_and_a_new_word_takes_the_plural_most_concepts_show():
    view = _lessons_view(7)
    kinds = _tell(("isa", "glintbsrtp heron", "glintbsrtp bird"))
    assert [r.meaning for r in read("a glintbsrtp heron is a glintbsrtp bird", view)][:1] == [kinds], \
        "a kind statement names a kind in each place: 'a glintbsrtp bird' is no bird that is glintbsrtp"
    assert [r.meaning.act for r in read("is a glintbsrtp heron a glintbsrtp bird", view)][:1] == ["ask"]
    assert [r.meaning.canonical() for r in read("The red ball is big.", view)][:1] == [_tell(
        ("instance_of", "?v0", "ball"), ("has_property", "?v0", "red"), ("has_property", "?v0", "big")).canonical()], \
        "a phrase still describes a thing where a thing is said"
    counts, productive = view.said_shapes()
    assert ("s", "") in productive and ("es", "") not in productive, (counts[("s", "")], counts[("es", "")])
    assert view.word_shapes()[("s", "")][1] > counts[("s", "")][1], \
        "'kindness', 'grass', 'scissors' end as plurals do, and are no concept said in a shape"
    said = dr.say(_tell(("isa", "vexbsrtp", "animal")), view)
    assert "Vexbsrtps are animals." in said and not any("Vexbsrtpes" in s for s in said), said
    assert "Vexduwhjxes are animals." in dr.say(_tell(("isa", "vexduwhjx", "animal")), view)


def test_a_word_never_held_is_written_as_the_slot_s_fillers_are():
    # "Every robin is a bird." learned as "Every ?slot0 is ?slot1." holding "a bird", as a learner that read
    # "a bird" as one filler once did: every filler of that slot begins with "a", a word that names nothing.
    view = _lessons_view(7)
    every = Pattern((dr.Piece("Every", True), dr.Slot("?slot0", True), dr.Piece("is", True), dr.Slot("?slot1", False),
                     dr.Piece(".", False)), Meaning("tell", (F("isa", "?slot0", "?slot1"),)))
    robin, a_bird = dr.Lexical((dr.Piece("robin", True),), "robin"), dr.Lexical(form_of("a bird"), "bird")
    for item in (every, robin, a_bird, dr.link(every, "?slot0", robin), dr.link(every, "?slot1", a_bird)):
        view.add(item)
    assert view.filler_openings(every.key, "?slot1") == {True}
    said = dr.say(_tell(("isa", "flowering quince", "shrub")), view)
    assert "A flowering quince is a shrub." in said
    assert not [s for s in said if s.endswith(" is shrub.")], \
        "a new word goes there no more bare than a held one does"


def _uses_from_scratch(view):
    """How the held words are used, found again from everything the view holds, as it once was every time a use was
    asked for: (slots, endings, words), as `_use_model` gives them."""
    import math
    counted, bare, plural, taken = set(), set(), set(), {}
    for pattern, slot, key in view._links:
        filler = view.get(key)
        if not isinstance(filler, dr.Lexical) or len(dr._loose(filler.words)) != 1:
            continue
        if view.counted_slot(pattern, slot):
            counted.add(filler.value)
        if (pattern, slot) not in taken:
            taken[(pattern, slot)] = bool(view.shape_of_slot(pattern, slot))
        if taken[(pattern, slot)]:
            plural.add(key)
            continue
        frame = view.get(pattern)
        if isinstance(frame, Pattern) and isinstance(frame.form[0], dr.Slot) and frame.form[0].name == slot \
                and dr._loose(filler.words)[0] == dr._fold(filler.value):
            bare.add(filler.value)
    nouns = {view._find(k) for k in view._parent
             if isinstance(view.get(k), dr.Lexical) and view.get(k).value in counted}
    use = {}
    for key in view._parent:
        filler = view.get(key)
        if not isinstance(filler, dr.Lexical) or len(dr._loose(filler.words)) != 1:
            continue
        word = dr._loose(filler.words)[0]
        if view.is_proper(word) and filler.value not in counted:
            use[key] = "name"
        elif key in plural:
            use[key] = "plural"
        elif filler.value in counted:
            use[key] = "count"
        elif filler.value in bare and view._find(key) in nouns:
            use[key] = "mass"
    slots = {where: frozenset(use[k] for k in keys if k in use) for where, keys in view._linked.items()}
    words = {}
    for key, how in use.items():
        counts = words.setdefault(dr._loose(view.get(key).words)[0], {})
        counts[how] = counts.get(how, 0) + 1
    by_ending, kept = {False: {}, True: {}}, {False: {}, True: {}}
    for word, counts in words.items():
        how = max(counts.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0]
        if how == "plural":
            continue
        proper = view.is_proper(word)
        kept[proper][how] = kept[proper].get(how, 0) + 1
        for size in range(1, min(4, len(word) - 1) + 1):
            by_ending[proper].setdefault(word[len(word) - size:], []).append((word, how))
    endings = {False: {}, True: {}}
    for proper, default in ((False, "count"), (True, "name")):
        trusted = dr._confidence(kept[proper].get(default, 0), sum(kept[proper].values()))
        decided = endings[proper]
        for ending in sorted(by_ending[proper], key=lambda e: (-len(e), e)):
            tally = {}
            for word, how in by_ending[proper][ending]:
                if any(word[len(word) - size:] in decided for size in range(len(ending) + 1, len(word))):
                    continue
                tally[how] = tally.get(how, 0) + 1
            total = sum(tally.values())
            if total < 2:
                continue
            how, most = max(tally.items(), key=lambda kv: (kv[1], kv[0] == default, kv[0]))
            if most * 2 > total and total - most <= total / math.log(total) \
                    and (how == default or dr._confidence(most, total) > trusted):
                decided[ending] = how
    return slots, endings, words


def test_the_uses_of_words_are_kept_as_items_arrive():
    """What the view keeps of how words are used, asked for between any two items, is what it would find again from
    everything it holds: in the order the lessons were learned, as teaching adds them, and in any order, as a view
    warmed from memory meets them."""
    import random
    items = list(_lessons_view(7).items())
    for seed, every in ((None, 1), (0, 1), (1, 37), (2, 37)):
        order = items[:]
        if seed is not None:
            random.Random(seed).shuffle(order)
        view = _believed()
        for at, item in enumerate(order):
            view.add(item)
            if at % every == 0 or at == len(order) - 1:
                assert view._use_model() == _uses_from_scratch(view), (seed, at, item)
    assert view.use_of("paleoanthropology") == "mass" and view.use_of("Bostonian") == "count"


def test_a_view_warmed_in_any_order_knows_the_same_names_and_uses():
    """A view warmed from memory meets constructions and links in the store's order, not the order they were
    learned in: a link can come before its filler or its frame."""
    import random
    taught = _lessons_view(7)
    items = list(taught.items())
    words = {w for lx in taught.lexicals() for w in dr._loose(lx.words)}
    names = {w for w in words if taught.is_proper(w)}
    assert {"tom", "paris", "italy", "american"} <= names
    for seed in range(4):
        order = items[:]
        random.Random(seed).shuffle(order)
        view = _believed()
        for item in order:
            view.add(item)
        assert {w for w in words if view.is_proper(w)} == names, seed
        assert view._use_model()[1:] == taught._use_model()[1:], seed
        assert view.use_of("Thiosulfil") == "name" and view.use_of("Bostonian") == "count", seed


def test_a_new_name_is_one_reading_could_take_and_a_word_s_shapes_share_out_the_letters():
    view = _lessons_view(7)
    assert [lx.surface for lx in view.lexicals_with_value("american")] == ["American"], \
        "'An American is a person.' teaches the word 'American': 'An' builds sentences and names nothing"
    assert not [lx.surface for lx in view.lexicals() if dr._loose(lx.words)[0] in ("a", "an")
                and dr._loose(lx.words)[1:] in {("american",), ("canadian",), ("german",), ("eel",)}]
    assert view.variants_of("an") == {"a"} and view.variants_of("a") == {"an"}
    assert view.variants_of("every") == frozenset(), \
        "'every' alternates with 'an' before other letters, but with 'a' before the same ones: no shape of theirs"
    said = dr.say(_tell(("isa", "peludo", "armadillo")), view)
    assert "A peludo is an armadillo." in said and not any(s.startswith("An peludo") for s in said), said


def _lessons_view(last):
    """The lessons english_01 to english_0<last>, learned in memory as the teaching path learns them."""
    import json
    view = _believed()
    for n in range(1, last + 1):
        path = Path(__file__).resolve().parents[1] / "data" / "lessons" / f"english_{n:02d}.json"
        _learn(view, [(r["sentence"], Meaning.from_dict(r["meaning"]))
                      for r in json.loads(path.read_text())["records"]])
    return view


def test_a_word_never_held_is_said_as_the_words_used_like_it_are():
    view = _lessons_view(7)
    assert view.use_of("Thiosulfil") == "name", "written with a capital by its source"
    for word in ("Cyanocitta", "Pakistan"):
        assert view.use_of(word) == "name", f"{word}: no word written with a capital and ending so is counted"
    assert view.use_of("Bostonian") == "count", "ending as 'Canadian', 'Italian' and 'Indian', counted, do"
    assert view.use_of("Latin American") == "count", "an American, described"
    assert view.use_of("Roman arch") == "count", "an arch, described: the word the rest describe decides"
    assert view.use_of("paleoanthropology") == "mass", "ending as 'biology', 'geology' and 'zoology' do"
    assert view.use_of("fire tongs") == "plural", "its last word is held as a plural only"
    for word in ("ocelot", "lens", "bus", "abacus"):
        assert view.use_of(word) == "count", f"{word}: a plural or 'no a' is never guessed from a final 's'"
    before = len(view)
    for fact, sentence in ((("isa", "Thiosulfil", "sulfa drug"), "Thiosulfil is a sulfa drug."),
                           (("isa", "paleoanthropology", "vertebrate paleontology"),
                            "Paleoanthropology is a kind of vertebrate paleontology."),
                           (("isa", "fire tongs", "tongs"), "Fire tongs are tongs."),
                           (("isa", "lens", "optical device"), "A lens is an optical device."),
                           (("isa", "Asian", "person"), "An Asian is a person."),
                           (("isa", "Bostonian", "person"), "A Bostonian is a person."),
                           (("isa", "german", "person"), "All Germans are persons.")):
        said = dr.say(_tell(fact), view)
        assert sentence in said, (fact, said)
        assert not any(s.startswith(("A Thiosulfil", "A paleoanthropology", "A fire tongs", "Asian is",
                                     "Bostonian is", "An Bostonian", "All germans")) for s in said), said
    for fact, sentence in ((("isa", "Thiosulfil", "sulfa drug"), "Thiosulfil is a sulfa drug."),
                           (("isa", "paleoanthropology", "vertebrate paleontology"),
                            "Paleoanthropology is a kind of vertebrate paleontology.")):
        # Names of words none of which is held read back as the names said. A word never held keeps its writing
        # when read ("Paleoanthropology" opening the sentence): the meaning is the same, case aside.
        assert [r.meaning.canonical().lower() for r in read(sentence, view)] == [_tell(fact).canonical().lower()], \
            sentence
    assert len(view) == before, "saying and reading write nothing"
    lens = _tell(("isa", "lens", "optical device"))
    assert [r.meaning for r in read("A lens is an optical device.", view)][:1] == [lens], \
        "a kind is said of a kind: 'optical device' is a kind of its own, never some device that is optical"
    _learn(view, [("A lens is an optical device.", lens)])
    assert [r.meaning for r in read("A lens is an optical device.", view)] == [lens], "and so it stays once taught"
