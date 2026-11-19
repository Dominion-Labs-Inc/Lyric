#!/usr/bin/env python3
"""A greeting is answered, counted as answered, and never turned into work.

Typed "hello" at 13:42 and "thank you" at 14:06 on 2026-11-19, the running substrate said this:

    Part of that is about something I have no name for yet (?v0, in what it says of done_by), so I did not hold it.
    I'm on it: "thank you".
    I couldn't do "thank you". Validation failed: no substrate handler for a ANALYSIS task yet; the substrate
    declined all model-free paths and the model is not a fallback, not met: the goal of the task is achieved:
    thank you (0.01), completion belief 0.01 < acceptance 0.98 - goal not yet grounded-confident

Four separate faults produced those three lines, and each has a test here. None of them was in reading: "thank you"
read correctly, as the exact three facts the lesson gives "Thank you.", and was classified a telling.

  1. AN ACT DONE BACK WAS COUNTED AS NOTHING. `_answered_in_kind` composed "You are welcome.", and then the work
     path's check -- `known or remembered or acquired or answers or looking_up` -- found every field empty, because
     such a turn holds nothing and answers nothing out of knowledge. The reply was discarded and the turn queued as
     a job. `Understanding.in_kind` records what the turn did, and both that check and `answered` read it.
  2. THE TEMPORAL RELATION WAS USED FOR WHAT IS SAID BACK. `follows` is acyclic and always transitive; adjacency is
     neither. So of three taught pairs, the two whose reply is the SAME kind of act -- a greeting, a farewell --
     were refused at the one admission and only "a welcome answers thanks" was ever held.
  3. A JOB'S OWN ERROR WAS SPOKEN. It names handlers, paths, beliefs and thresholds, and none of it is the
     person's to act on.
  4. THE READER'S TERMS WERE SPOKEN. "?v0" and "done_by" are how a meaning is written, not words for anybody.

Nothing here needs a store: each case is a decision made before anything is read or written.
"""
import json
from pathlib import Path

import pytest

from core.agents.autonomous.autonomous_coordinator import Acquired, Understanding
from core.semantics.relation_types import SPEC, SemanticRelation, Transitivity, classify

#: The work path's own check, quoted from `_answer_from_what_is_held`: what it asks before deciding a turn
#: managed nothing and should become a job.
def _managed_nothing(u: Understanding) -> bool:
    return not (u.known or u.remembered or u.acquired or u.answers or u.looking_up or u.in_kind)


# ---------------------------------------------------------------- 1. an act done back is an answer

def test_an_act_done_back_is_not_counted_as_nothing():
    """The exact turn that failed: a reply composed by `_answered_in_kind` and nothing else set."""
    turn = Understanding(sentence="thank you", asked=False)
    turn.reply = "You are welcome."
    turn.in_kind = ("thank", "welcome")
    assert not _managed_nothing(turn), (
        "a turn that did an act back was read as having managed nothing, so its reply would be "
        "thrown away and the turn queued as a job")


def test_an_act_done_back_counts_as_answered():
    turn = Understanding(sentence="hello", asked=False)
    turn.reply = "Hello."
    turn.in_kind = ("greet", "greet")
    assert turn.answered, "a greeting answered with a greeting is as answered as a turn can be"


def test_a_turn_that_did_nothing_still_falls_through():
    """The check still has to let a question nothing is held for reach the work path, or asking
    about something unheld would stop finding it out."""
    empty = Understanding(sentence="what is a trel", asked=True)
    assert _managed_nothing(empty)
    assert not empty.answered


def test_a_reply_alone_is_not_an_answer():
    """`in_kind` is what counts, not a non-empty reply: "I do not know." is a reply, and a question
    it was said to must still fall through and be found out."""
    unknown = Understanding(sentence="what is a trel", asked=True)
    unknown.reply = "I hold nothing for trel."
    assert _managed_nothing(unknown), "any non-empty reply counted as an answer would stop look-ups"


# ---------------------------------------------------------------- 2. what is said back is its own relation

def test_answers_is_cyclic_and_does_not_chain():
    spec = SPEC[SemanticRelation.ANSWERS]
    assert spec.acyclic is False, (
        "a greeting answers a greeting, so the relation must permit a thing standing in it to "
        "itself -- acyclic is what refused it at depth 0")
    assert spec.transitivity is Transitivity.NEVER, (
        "a welcome answers thanks and thanks may answer a gift; a welcome does not answer a gift")


def test_follows_keeps_being_temporal():
    """The fix must not loosen the guard that exists because 17 real cycles were measured."""
    spec = SPEC[SemanticRelation.FOLLOWS]
    assert spec.acyclic is True and spec.transitivity is Transitivity.ALWAYS
    assert spec.inverse is SemanticRelation.PRECEDES


def test_answers_reads_from_its_surface():
    assert classify("answers").relation is SemanticRelation.ANSWERS


def test_a_self_answering_pair_is_admissible():
    """The shape test at the one door, which is what `follows(greet, greet)` never got past."""
    from core.semantics.cognitive_ingress import shape_proposition
    _s, _r, _o, refusal = shape_proposition("greet", "answers", "greet")
    assert refusal is None, f"the one door refused a greeting answering a greeting: {refusal}"


def test_the_cycle_guard_leaves_answers_alone():
    """`_would_close_a_cycle` returns before it reads anything for a relation that does not chain,
    so a self-answering pair is never matched at depth 0."""
    import asyncio
    from core.semantics.cognitive_ingress import get_cognitive_ingress
    why = asyncio.run(get_cognitive_ingress()._would_close_a_cycle("answers", "greet", "greet"))
    assert why is None


def test_the_lessons_teach_the_pairs_with_answers():
    """The taught sentence and the taught relation have to move together: left saying "follows"
    while meaning `answers`, the lesson would teach that the word "follows" means this."""
    lesson = json.loads(Path("data/lessons/english_30.json").read_text(encoding="utf-8"))
    pairs = [(r["sentence"], f) for r in lesson["records"]
             for f in (r.get("meaning", {}).get("facts") or ())
             if f and f[0] in ("answers", "follows")]
    assert len(pairs) == 3, f"expected the three adjacency pairs, found {len(pairs)}"
    for sentence, fact in pairs:
        assert fact[0] == "answers", f"{sentence!r} still states the temporal relation: {fact}"
        assert " answers " in sentence, f"{sentence!r} does not say the relation it states"
    held = {(f[1], f[2]) for _s, f in pairs}
    assert ("greet", "greet") in held and ("farewell", "farewell") in held, (
        "the two self-answering pairs are the ones that were being refused")


def test_the_acts_are_taught_as_a_person_types_them():
    """WHY THIS IS TAUGHT AND NOT CODED. The act lives in a construction whose literal words are the
    taught ones -- Phrase(['Hello', '.']) -- so "hello" matched neither the capital nor the stop. The
    strict pass cannot fold case or drop a mark (that is what `loose` is for, and `loose` runs only
    where the strict pass found NOTHING, while here it found two: "hello" the noun, and a sound being
    played, done to a thing called "hello").

    Measured, which is what decides it: 'Hello.' reads with supposed=(False, 0, 0, 0, 0) and is the
    ONLY reading, while both readings of 'hello' suppose (False, 0, 1, 0, 0). A construction matching
    the bare words exactly supposes 0, so it cuts both of them -- no reader change needed, and none
    made. A speaker learns "hello" as a greeting however it is written; teaching both is the faithful
    thing, and it is how the lesson already teaches "Hi." beside "Hello.".
    """
    lesson = json.loads(Path("data/lessons/english_16.json").read_text(encoding="utf-8"))
    said = {r["sentence"]: r["meaning"] for r in lesson["records"]}
    for bare, kind in [("hello", "greet"), ("hi", "greet"), ("hey", "greet"),
                       ("good morning", "greet"), ("thanks", "thank"), ("thank you", "thank"),
                       ("goodbye", "farewell"), ("bye", "farewell")]:
        assert bare in said, f"{bare!r} is not taught, so typing it is not a {kind}"
        facts = {tuple(f) for f in said[bare]["facts"]}
        assert facts == {("instance_of", "?v0", kind, True),
                         ("done_by", "?v0", "?speaker", True),
                         ("done_to", "?v0", "?listener", True)}, bare
        assert said[bare]["act"] == "tell", bare


def test_a_bare_act_means_what_its_written_form_means():
    """The bare form and the written form are the same act, or typing one gets a different answer."""
    lesson = json.loads(Path("data/lessons/english_16.json").read_text(encoding="utf-8"))
    said = {r["sentence"]: r["meaning"] for r in lesson["records"]}
    for bare, written in [("hello", "Hello."), ("hi", "Hi."), ("thanks", "Thanks."),
                          ("thank you", "Thank you."), ("goodbye", "Goodbye."), ("bye", "Bye."),
                          ("good morning", "Good morning.")]:
        assert said[bare] == said[written], f"{bare!r} and {written!r} are not the same act"


# ---------------------------------------------------------------- 3. a job's own error is not spoken

#: Fragments of the real error string a person was shown.
INTERNALS = ("substrate handler", "model-free paths", "completion belief", "acceptance",
            "grounded-confident", "ANALYSIS", "Validation failed")


def test_a_failed_job_does_not_say_its_own_error():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C
    said = C._outcome_said(object.__new__(C), {
        "asked": "thank you", "status": "failed", "id": "t1",
        "error": ("Validation failed: no substrate handler for a ANALYSIS task yet; the substrate "
                  "declined all model-free paths and the model is not a fallback, not met: the goal "
                  "of the task is achieved: thank you (0.01), completion belief 0.01 < acceptance "
                  "0.98 - goal not yet grounded-confident (needs corroboration)")})
    for leak in INTERNALS:
        assert leak not in said, f"{leak!r} was said to the person: {said!r}"
    assert "thank you" in said, "it still has to say WHICH thing could not be done"
    assert said.endswith("."), f"not one finished sentence: {said!r}"


def test_a_failed_job_with_no_error_still_says_so():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as C
    said = C._outcome_said(object.__new__(C), {"asked": "run the thing", "status": "failed"})
    assert "run the thing" in said and said.endswith(".")


# ---------------------------------------------------------------- 4. the reader's terms are not spoken

def test_a_note_says_why_in_words_and_keeps_the_terms_apart():
    note = Acquired("hello", detail="part of that is about something I have no name for yet, "
                                    "so I did not hold it",
                    account="?v0, in what it says of done_by")
    assert "?v" not in note.detail and "done_by" not in note.detail, (
        f"the reader's own terms are in the sentence said: {note.detail!r}")
    assert "?v0" in note.account and "done_by" in note.account, (
        "which term had no name is what tells a pronoun pointing at nothing from a description "
        "that found no referent; it is kept, not dropped")


def test_a_note_with_nothing_to_account_for_is_unchanged():
    assert Acquired("A zq is a robin.", detail="Noted.").account == ""


# ---------------------------------------------------------------- the whole chain, once the edge is held

def test_a_greeting_is_answered_and_the_turn_says_what_it_did(monkeypatch):
    """`_answered_in_kind` end to end with the edge in place: the gate passes on the lesson's own
    three facts, the act back is found through `answers`, and the turn records BOTH the reply and
    what it did. This is the chain that produced "You are welcome." and then threw it away."""
    import asyncio

    import core.reasoning.concept_graph_reasoning as cgr
    import core.semantics.derived_reader as dr
    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.agents.autonomous.shared_types import TaskSource
    from core.semantics.derived_reader import Meaning, MeaningFact as F

    class _Edge:
        def __init__(self, subject):
            self.subject, self.relation = subject, SemanticRelation.ANSWERS

    async def _edges_into(db, names, *, actor=None):
        assert names == ["greet"], names
        return [_Edge("greet")]

    monkeypatch.setattr(cgr, "edges_into", _edges_into)
    monkeypatch.setattr(dr, "say", lambda meaning, **kw: ("Hello.",))

    talk = object.__new__(Conversation)
    talk._framed, talk._turns, talk._last_subject, talk._last_reply = frozenset(), [], None, ""
    # `_actor` is resolved from the thread's source and identity (`actor_for`), never set.
    talk._source, talk._actor_identity, talk._session = TaskSource.MANUAL, None, "test"

    async def _services():
        return (None, None)

    async def _hand_over_turn(understanding, route, outcome):
        assert route == {"answered": "greet", "with": "greet"} and outcome == "answered"

    talk._services, talk._hand_over_turn = _services, _hand_over_turn

    #: Exactly what the lessons give "Hello.", and what the reader now gives "hello".
    greeting = Meaning("tell", (F("instance_of", "?v0", "greet"),
                                F("done_by", "?v0", "?speaker"),
                                F("done_to", "?v0", "?listener")))
    got = asyncio.run(talk._answered_in_kind("hello", greeting))
    assert got is not None, "the greeting gate refused the lesson's own meaning"
    assert got.reply == "Hello.", got.reply
    assert got.in_kind == ("greet", "greet"), got.in_kind
    assert got.answered and not _managed_nothing(got), (
        "the turn did an act back, so it must not be read as having managed nothing")


def test_a_telling_is_not_answered_in_kind(monkeypatch):
    """The gate still refuses anything that is not an act done to the substrate, so a real telling
    reaches the telling path."""
    import asyncio

    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.semantics.derived_reader import Meaning, MeaningFact as F

    talk = object.__new__(Conversation)
    told = Meaning("tell", (F("isa", "robin", "bird"),))
    assert asyncio.run(Conversation._answered_in_kind(talk, "A robin is a bird.", told)) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
