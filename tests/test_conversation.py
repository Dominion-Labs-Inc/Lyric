#!/usr/bin/env python3
"""Talking to the substrate: understanding, answering, asking, and telling a
question from a job.

Four claims, each with a way to be wrong:

    UNDERSTANDS   a sentence resolves to things the substrate holds, and a
                  phrase is read as a phrase -- `pressure loss` is one thing,
                  not `pressure` and `loss`
    COMMUNICATES  the reply is assembled out of stored descriptions and
                  relations, never generated, and it answers the QUESTION
                  rather than reciting the concept it was about
    ASKS          where it holds nothing and cannot find anything, it says so
                  and names what it does not know
    DISCRIMINATES a question is answered; a job is queued. This is the one that
                  was broken: everything was a job, so `What is a load
                  balancer?` got 84 tools, a 26-iteration budget and 4,680
                  seconds, and created a directory.

What must never happen is answering about something it does not hold. Every
claim below has a negative beside it for exactly that reason.

THE ENGLISH IS TAUGHT, NOT ASSUMED. The substrate reads only through the
constructions it was taught (`derived_reader`), so these tests speak only
English they taught it first: the two lessons in `data/lessons/`, and the few
sentences below that the tests themselves need. They are taught to a view of
their own, never to a store, so nothing here depends on what the sandbox holds.
"""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

from core.agents.autonomous.autonomous_coordinator import Conversation, phrases
from core.semantics import derived_reader as dr
from core.semantics.derived_reader import Meaning, PatternInventory
from core.semantics.sentence_machine import form_of

LESSONS = Path(__file__).resolve().parents[1] / "data" / "lessons"


def _ask(*facts, asked=()):
    return {"act": "ask", "facts": [list(f) for f in facts], "asked": list(asked)}


#: The English these tests speak beyond the lessons: a question about causes,
#: and questions about the exchange itself.
SPOKEN_HERE = [
    ("What causes pipe friction?", _ask(("caused_by", "pipe friction", "?x", True), asked=("?x",))),
    ("What causes water hammer?", _ask(("caused_by", "water hammer", "?x", True), asked=("?x",))),
    ("What did I just ask you about?", _ask(("instance_of", "?e", "ask", True), ("done_by", "?e", "?speaker", True),
                                            ("done_to", "?e", "?listener", True), asked=("?e",))),
    ("What were we talking about?", _ask(("instance_of", "?e", "tell", True), ("done_by", "?e", "?speaker", True),
                                         ("done_by", "?e", "?listener", True), asked=("?e",))),
    ("What did you say?", _ask(("instance_of", "?e", "tell", True), ("done_by", "?e", "?listener", True),
                               asked=("?e",))),
]

_VIEW = None


def _taught_view() -> PatternInventory:
    """The lessons and the sentences above, learned pair by pair by the
    learner's own repairs, into a view nothing else reads."""
    global _VIEW
    if _VIEW is None:
        view = PatternInventory(score=lambda item: (0.9, 1))
        pairs = [(r["sentence"], r["meaning"]) for name in ("english_01", "english_02")
                 for r in json.loads((LESSONS / f"{name}.json").read_text())["records"]] + SPOKEN_HERE
        for sentence, data in pairs:
            form, meaning = form_of(sentence), Meaning.from_dict(data)
            if dr.readings_of(tuple(p.text for p in form), meaning, view):
                continue
            repair = next(r for r in (step(form, meaning, view) for step in dr.REPAIRS) if r is not None)
            for item in repair.constructions + repair.links:
                view.add(item)
        _VIEW = view
    return _VIEW


@pytest.fixture(autouse=True)
def taught(monkeypatch):
    view = _taught_view()
    monkeypatch.setattr(dr, "_live_inventory", lambda: view)
    return view


@pytest.fixture
def talk():
    return Conversation()


async def _pressure_loss_is_held():
    """THE LESSON IS TAUGHT, NOT ASSUMED. `what causes pressure loss` is answered
    out of what the substrate was taught, and a store it was never taught that
    in -- the sandbox after a reset, a model wiped for teaching -- has nothing
    to answer from, so the failure reads as broken understanding when it is a
    missing lesson. Taught here through the one learning path, into the sandbox
    the suite runs in, and only when it is not already held. The store is opened
    first: a test process has no substrate running to open it."""
    from core.learning.unified_learning_system import get_learning_authority
    from core.memory import get_memory_agent

    await get_memory_agent()
    held = await Conversation().understand("what causes pressure loss", look_up=False)
    if any(r.phrase == "pressure loss" and any("caus" in relation for relation, _ in r.relations)
           for r in held.known):
        return
    admission = await get_learning_authority().learn_fact(
        "pressure loss", "caused_by", "pipe friction", domain="fluid_mechanics",
        description="the drop in pressure as a fluid flows through a pipe or a fitting")
    assert admission.admitted, admission.refusals


def test_a_phrase_is_read_as_a_phrase():
    """`pressure loss` is one concept and `pressure` is another; reading the
    shorter out of the longer changes the subject."""
    found = [text for _, _, text in phrases(["what", "causes", "pressure", "loss"])]
    assert "pressure_loss" in found
    assert found.index("causes_pressure_loss") < found.index("pressure_loss"), \
        "longest first, so the longest match wins the words"


@pytest.mark.asyncio
async def test_it_understands_a_sentence_as_things_it_holds(talk):
    await _pressure_loss_is_held()
    understanding = await talk.understand("what causes pressure loss")

    assert any(r.phrase == "pressure loss" for r in understanding.known), \
        [r.phrase for r in understanding.resolved]
    held = next(r for r in understanding.known if r.phrase == "pressure loss")
    assert held.description, "a name with nothing behind it is not understanding"
    assert held.domain


@pytest.mark.asyncio
async def test_it_answers_the_question_rather_than_reciting_the_concept(talk):
    await _pressure_loss_is_held()
    understanding = await talk.understand("what causes pressure loss")

    assert understanding.answers, "the question named a relation it holds"
    answer = understanding.answers[0]
    assert answer.about == "pressure loss"
    assert "cause" in answer.relation
    # Every word of the answer came out of the store -- the stored atom, said
    # the way the reply says it (`pipe_friction` is "pipe friction").
    for other in answer.others:
        assert Conversation._render_atom(other).lower() in understanding.reply.lower()


@pytest.mark.asyncio
async def test_it_reports_the_gap_when_it_holds_nothing_and_can_find_nothing(talk):
    """It SAYS it does not hold the thing, names it, and invents nothing.

    An unknown phrase is reported honestly and never filled in. Both words are
    invented, which is what the test needs to be about: nothing the substrate
    was taught names either, so the reply says which words it does not know."""
    understanding = await talk.understand("what is a zorblatt florpnax")

    assert not understanding.known, [r.phrase for r in understanding.known]
    assert not understanding.answered, "reporting a gap is not answering"
    assert "don't hold" in understanding.reply.lower(), understanding.reply
    assert any(w in understanding.reply for w in ("zorblatt", "florpnax")), \
        understanding.reply
    # And it must not have invented one.
    assert not any(a.stored for a in understanding.acquired)


@pytest.mark.asyncio
async def test_a_name_with_nothing_behind_it_is_not_an_answer(talk):
    """The store holds 240 bare fragments with no description. Matching one is
    not knowing, and saying `held, with no description` stopped it ever going
    to find out."""
    understanding = await talk.understand("what is a load balancer")

    assert "no description" not in understanding.reply
    assert not any(r.phrase in ("load", "balancer") for r in understanding.known)


@pytest.mark.asyncio
async def test_telling_it_something_is_not_asking_it_something(talk):
    """What the speaker wants is part of what the sentence means, taught with
    it: a question asks, a telling tells, a request asks for something done.
    What does not read is none of them."""
    assert talk.is_question("What is a robin?") is True
    assert talk.is_question("is a whale a fish or a mammal") is True
    assert talk.is_question("A robin is a bird.") is False
    assert talk.is_question("Close the door.") is False
    assert await talk.classify("What is a robin?") == "question"
    assert await talk.classify("The door is open and the window is closed.") == "telling"
    assert await talk.classify("please open the window") == "job"
    assert await talk.classify("a firewall blocks network traffic") == "not_understood"


@pytest.mark.asyncio
async def test_it_remembers_what_happened_not_only_what_things_are():
    """The concept store holds what things ARE; memory holds what HAPPENED.
    Answering out of one and not the other is why it could describe a concept
    and not that you had just discussed it."""
    talk = Conversation()
    remembered = await talk.recall("load balancer")
    assert isinstance(remembered, list)
    # Recall must return text, never raw objects a caller has to unpick.
    assert all(isinstance(item, str) for item in remembered)


# ------------------------------------------------------------------ polarity

def test_a_statement_and_its_negation_are_not_the_same_claim():
    """The measurement this exists for: on this system's own embedding model,
    `the vault is locked` and `the vault is not locked` score 0.948, while two
    ways of saying the same thing score 0.484. No threshold separates them, so
    the distinction is read when the memory is written and compared exactly."""
    from core.semantics.claim_shape import read_claim

    locked = read_claim("the vault is locked")
    unlocked = read_claim("the vault is not locked")

    assert locked.polarity == "affirms" and unlocked.polarity == "denies"
    assert locked.agrees_with(unlocked) is False
    assert locked.agrees_with(read_claim("the safe is secured")) is True


def test_tense_is_part_of_the_claim():
    from core.semantics.claim_shape import read_claim

    assert read_claim("the vault was locked").tense == "past"
    assert read_claim("the vault is locked").tense == "present"
    assert read_claim("the vault wasn't locked").polarity == "denies"


def test_a_question_makes_no_claim():
    """`what is a load balancer` read as an affirmative claim about load
    balancers, so every question filed in memory carried a polarity nothing
    asserted."""
    from core.semantics.claim_shape import read_claim

    assert not read_claim("what is a load balancer").known
    assert not read_claim("is the vault locked?").known
    # And an unreadable claim agrees with nothing rather than agreeing weakly.
    assert read_claim("the vault is locked").agrees_with(
        read_claim("what is a load balancer")) is None


def test_a_change_over_time_is_not_placed_in_one_tense():
    from core.semantics.claim_shape import read_claim

    both = read_claim("it was locked and is now open")
    assert both.tense is None, "a described change belongs to neither tense"


def test_a_question_about_the_conversation_is_answered_from_the_conversation():
    """`What did I just ask you about?` was parsed as a question about a thing
    called `just ask`, researched on Wikipedia, and answered with an article on
    the rhetorical tactic of asking questions -- because nothing owned
    questions about the exchange itself, so they fell through to the owner of
    unrecognised phrases."""
    import asyncio

    from core.agents.autonomous.autonomous_coordinator import Conversation, Turn

    talk = Conversation()
    assert talk.about_this_conversation("What did I just ask you about?") == ("them", "asked")
    assert talk.about_this_conversation("what did I just ask you") == ("them", "asked")
    assert talk.about_this_conversation("What were we talking about?") == ("both", "discussed")
    assert talk.about_this_conversation("What did you say?") == ("me", "said")
    # A question about the world is not one of these, however many people it
    # mentions: there is no speech verb with a participant in front of it.
    assert talk.about_this_conversation("What is a load balancer?") is None
    assert talk.about_this_conversation("Who asked the first question in history?") is None

    # Answered from the record, with no lookup and no store access at all.
    talk._turns = [Turn(said="What causes pressure loss?", asked=True,
                        subject="pressure loss", reply="minor losses")]
    reply = asyncio.run(talk.understand("What did I just ask you about?")).reply
    assert "pressure loss" in reply and "What causes pressure loss?" in reply


def test_nothing_said_yet_is_reported_rather_than_invented():
    import asyncio

    from core.agents.autonomous.autonomous_coordinator import Conversation

    reply = asyncio.run(Conversation().understand("What did I just ask you about?")).reply
    assert "Nothing yet" in reply


def test_asking_about_the_conversation_does_not_become_the_subject():
    """Asking what we were talking about is a question ABOUT the subject, not
    a new one -- letting it replace the subject strands everything recall has
    accumulated under the topic still being discussed."""
    import asyncio

    from core.agents.autonomous.autonomous_coordinator import Conversation, Turn

    talk = Conversation()
    talk._last_subject = "pressure loss"
    talk._turns = [Turn(said="What causes pressure loss?", asked=True,
                        subject="pressure loss", reply="minor losses")]
    asyncio.run(talk.understand("What were we talking about?"))
    assert talk._last_subject == "pressure loss"


def test_research_that_does_not_name_the_phrase_is_refused():
    """A search engine always returns its best row. Taking it unchecked stored
    an article on animal sexual behaviour as the meaning of `spots unusual
    behaviour`, and a wrong fact written into the store is indistinguishable
    afterwards from one that was learned."""
    from core.agents.autonomous.autonomous_coordinator import _titles

    assert _titles("load_balancer", "Load balancing (computing)")
    assert _titles("anomaly_detection", "Anomaly detection")
    assert not _titles("spots_unusual_behaviour", "Animal sexual behaviour"), (
        "sharing one word with the title is not being about the phrase"
    )
    assert not _titles("", "Anything")
