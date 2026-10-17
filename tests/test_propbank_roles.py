"""PropBank's roles in Lyric's meaning language (`core/semantics/propbank_roles.py`): each to a link kind the
meaning language has, a rule its words settle, nothing, or a named gap; nothing guessed."""
from core.semantics import propbank_roles as pr
from core.semantics.derived_reader import _KINDS


def test_every_kind_the_mapping_names_is_one_the_meaning_language_has():
    assert all(kind in _KINDS for kind in pr.kinds_used()), sorted(set(pr.kinds_used()) - set(_KINDS))


def test_numbered_arguments_are_said_by_their_verbnet_role_then_their_function_tag_then_their_number():
    assert pr.said("ARG2", roleset="give.01", function_tag="GOL", verbnet=("recipient",)) == pr.fact("received_by")
    assert pr.said("ARG2", roleset="cut.01", function_tag="MNR", verbnet=("instrument",)) == pr.fact("done_with")
    assert pr.said("ARG1", roleset="kick.01", function_tag="PPT", verbnet=("nm",)) == pr.fact("done_to")
    assert pr.said("ARG1", roleset="unheld.01") == pr.fact("done_to"), "a sense the frame files lack: ARG1 by number"
    assert pr.said("ARG2", roleset="unheld.01", words=("for", "errors")) == pr.fact("done_for"), "by its preposition"
    assert pr.said("ARG2", roleset="unheld.01", words=("nothing",)) is None, "nothing guessed"
    assert pr.said("ARG2", roleset="do.04", words=("nothing",)) == pr.NEGATES, "has nothing to do with"


def test_a_predicate_the_lessons_say_in_a_kind_of_its_own_is_said_so():
    owns = pr.said("ARG0", roleset="have.03", function_tag="PAG", verbnet=("pivot",))
    assert (owns.kind, owns.of, owns.to) == ("owns", "argument", "ARG1"), "Rex has a bike."
    assert pr.said("ARG1", roleset="have.03", function_tag="PPT") == pr.OTHER_SIDE
    assert pr.said("ARG2", roleset="be.01", function_tag="PRD").rule == "predicated", "Whales are mammals."
    assert pr.predicate("be.03") == pr.NOTHING and pr.predicate("have.LV") == pr.NOTHING
    assert pr.predicate("big.01", "JJ").rule == "quality" and pr.predicate("kick.01", "VBD") is None


def test_modifiers_are_said_by_the_word_that_begins_them_as_the_lessons_say_them():
    assert pr.said("ARGM-MOD", words=("can",)) == pr.fact("capable_of", of="doer", to="event"), "Rex can swim."
    assert pr.said("ARGM-MOD", words=("would",)) == pr.fact("has_property", to="=hypothetical")
    assert pr.said("ARGM-MOD", words=("might",)) == pr.needs("possible")
    assert pr.said("ARGM-LOC", words=("on", "the")) == pr.fact("located_at"), "on the table"
    assert pr.said("ARGM-LOC", words=("in", "front")) == pr.fact("in_front_of")
    assert pr.said("ARGM-TMP", words=("before", "noon")) == pr.fact("precedes")
    assert pr.said("ARGM-ADV", words=("if", "it")) == pr.Said("condition")
    assert pr.said("ARGM-ADV", words=("although", "it")) == pr.fact("has_property", to="=unexpected")
    assert pr.said("ARGM-NEG", words=("not",)) == pr.NEGATES


def test_a_discourse_marker_is_an_act_who_is_addressed_nothing_or_a_named_gap():
    assert pr.said("ARGM-DIS", words=("please",)) == pr.Said("act", "request")
    assert pr.said("ARGM-DIS", words=("Richard",), first_class="NAME").rule == "addressed"
    assert pr.said("ARGM-DIS", words=("hello",)).kind == "greet"
    assert pr.said("ARGM-DIS", words=("also",)) == pr.NOTHING
    assert pr.said("ARGM-DIS", words=("however",)) == pr.needs("between sentences")
    assert pr.said("ARGM-DIS", words=("wow",)) == pr.needs("felt")


def test_a_relative_pronoun_or_a_continuation_takes_the_role_it_stands_for_and_an_unknown_label_is_none():
    assert pr.said("R-ARG0") == pr.SAME and pr.said("C-ARG1") == pr.SAME
    assert pr.said("ARG1-DSP") == pr.fact("done_to", unasserted=True)
    assert pr.said("ARGM-XYZ") is None
