#!/usr/bin/env python3
"""Nothing stands in for a sentence saying cannot say.

`Conversation.say` is the one path from what the substrate holds to what it says. Where saying had no sentence for a
fact, five stand-ins spoke instead, and each of them put the store in front of a person rather than words:

- "Noted - I'll hold that about coat_paint_890984b3." -- the name memory made for a happening it met. Across a run on
  published prose, 92 of 147 replies to a sentence carried such a name, 663 of them in all.
- "I remember: 2970x1770 png image, 1 region(s)." -- a stored record recited as the answer. "Is South Asia a
  sub-region of Asia?" was answered that, because a picture's caption named a region.
- "I hold things about south asia that I have not been taught to say yet." -- the largest single reply to a question
  on published prose, 44 of 144.
- "A wall: met in use 'Roy painted the wall.'" -- the store's own note on how a word was first met.
- "Which wall do you mean - the one in environment_dc1455ad4d39ee9c, or in reading?" -- the store's shelves.

All five fired exactly where saying failed, so each one hid the failure it was covering: of the twenty relations
reading prose produces, saying can say three, and `done_by`, `done_to`, `part_of`, `located_in` and `owned_by` have no
sentence at all (lyric_dev, 2026-11-02). These tests pin that the reply says what saying can say and nothing else, so
that hole shows as silence and is measured rather than papered over.

Nothing here needs a store: the case under test is the one where saying produces nothing.
"""
import re

import pytest

from core.agents.autonomous.autonomous_coordinator import Acquired, Conversation, Resolved, Understanding

#: A name the substrate made for something it met, which nobody wrote: a word with a hex tail or a numbered one.
MADE_UP = re.compile(r"\b[a-z][a-z'-]*[ _](?:[0-9a-f]{6,8}|\d{1,3})\b", re.I)

#: What used to be said where saying said nothing.
STAND_INS = ("I'll hold that about", "have not been taught to say", "but nothing said about it yet",
             "I remember: ", "still searching memory", "met in use")


def _said(understanding) -> str:
    return str(Conversation.say(understanding) or "")


def _clean(reply: str) -> None:
    assert not MADE_UP.search(reply), f"a name the store made for itself reached the reply: {reply!r}"
    for stood_in in STAND_INS:
        assert stood_in not in reply, f"{stood_in!r} stood in for a sentence: {reply!r}"


def test_a_telling_whose_facts_saying_cannot_say_does_not_name_the_happening():
    """"Roy painted the wall." holds a painting done by Roy to the wall. Saying has no sentence for either fact, and
    the happening's name is `coat_paint_c60b554a`, which is not a word of anything."""
    reply = _said(Understanding(
        sentence="Roy painted the wall.", asked=False,
        acquired=[Acquired(label="coat_paint_c60b554a", relations=(("instance_of", "coat paint"),
                                                                  ("done_by", "roy"), ("done_to", "wall_1")),
                           origin="you", stored=True)],
        named={"roy": "Roy", "paint": "painted", "wall": "wall"}, kinds={}))
    _clean(reply)


def test_a_rule_that_cannot_be_said_is_not_acknowledged_with_nothing():
    """A bare "Noted." says a rule was held while saying none of it."""
    reply = _said(Understanding(
        sentence="If a thing is a wall then it is a partition.", asked=False,
        acquired=[Acquired(label="a rule", description="a rule", relations=(),
                           origin="you", stored=True, rule=(("isa", "wall", "partition", True),))]))
    assert reply.strip() != "Noted."
    _clean(reply)


def test_a_question_nothing_matched_does_not_recite_a_stored_record(monkeypatch):
    """The records recall hands up are the store's own text. A picture's measurements are not an answer about Asia.

    A record was recited only where it read as a claim, so the reading is supplied here (`_claim_facts` wants the
    store): without it the recitation never ran and this test pinned nothing."""
    import core.agents.autonomous.autonomous_coordinator as coordinator

    class _Fact:
        def __init__(self, subject, obj):
            self.subject, self.obj, self.relation, self.positive = subject, obj, "isa", True
    monkeypatch.setattr(coordinator, "_claim_facts",
                        lambda text: (_Fact("south asia", "region"),), raising=True)
    reply = _said(Understanding(
        sentence="Is South Asia a sub-region of Asia?", asked=True,
        remembered=["2970x1770 png image, 1 region(s)", "environment_dc1455ad4d39ee9c user stefan",
                    "research_graph.png has_size_bytes 108671"],
        resolved=[Resolved(phrase="south asia", how="context", relations=(("located in", "asia"),))]))
    assert "2970x1770" not in reply, f"a picture's measurements were recited as an answer: {reply!r}"
    assert "has_size_bytes" not in reply, f"a file's size was recited as an answer: {reply!r}"
    _clean(reply)


def test_what_is_held_but_unsayable_is_not_announced_as_unsayable():
    """`located_in` has no sentence. The reply says what it can and stops; it does not report the gap in its place."""
    reply = _said(Understanding(
        sentence="What is south asia?", asked=True,
        resolved=[Resolved(phrase="south asia", how="context",
                           relations=(("located in", "asia"), ("part of", "asia")),
                           description="met in use: 'South Asia is the southern sub-region of Asia.'")]))
    _clean(reply)


def test_which_one_is_meant_is_not_asked_by_where_it_is_kept():
    """A domain is a shelf in the store. Asked which "wall" was meant, a person cannot answer "the one in
    environment_dc1455ad4d39ee9c"."""
    reply = _said(Understanding(
        sentence="Is the wall red?", asked=True,
        resolved=[Resolved(phrase="wall", how="context", domain="environment_dc1455ad4d39ee9c",
                           description="met in use: 'Roy painted the wall.'",
                           relations=(("isa", "partition"),),
                           alternatives=(("reading", ""), ("code_generation", "")))]))
    assert "environment_dc1455ad4d39ee9c" not in reply, f"a store shelf was offered as a choice: {reply!r}"
    assert "code_generation" not in reply, f"a store shelf was offered as a choice: {reply!r}"
    _clean(reply)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
