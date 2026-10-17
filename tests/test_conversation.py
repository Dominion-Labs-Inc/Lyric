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
#: a name of two words asked what it is, and questions about the exchange itself.
#:
#: A NAME OF TWO WORDS IS TAUGHT WHERE THE TESTS ASK ONE. The reader takes words
#: it never met as a new name no longer than the longest name the slot's kind
#: has held (`derived_reader._may_be_new`). The two lessons put only one-word
#: names where "What is a ...?" asks, so "what is a zorblatt florpnax" read as
#: "what is a zorblatt" with a word left over, where the substrate, taught every
#: lesson, reads one name of two words.
SPOKEN_HERE = [
    ("What causes pipe friction?", _ask(("caused_by", "pipe friction", "?x", True), asked=("?x",))),
    ("What causes water hammer?", _ask(("caused_by", "water hammer", "?x", True), asked=("?x",))),
    ("What is a water hammer?", _ask(("isa", "water hammer", "?x", True), asked=("?x",))),
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
        view = PatternInventory(score=lambda item: (0.9, 1, True))
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
    from core.learning.unified_learning_system import Evidence, get_learning_authority
    from core.memory import get_memory_agent

    await get_memory_agent()
    held = await Conversation().understand("what causes pressure loss", look_up=False)
    if any(r.phrase == "pressure loss" and any("caus" in relation for relation, _ in r.relations)
           for r in held.known):
        return
    decision = await get_learning_authority().consider(
        "pressure loss", "caused_by", "pipe friction", domain="fluid_mechanics",
        description="the drop in pressure as a fluid flows through a pipe or a fitting",
        evidence=Evidence(source="test:conversation", key="test:conversation", source_type="IMPORTED_KNOWLEDGE",
                          quality=0.9, producer="test"))
    assert decision.admitted, decision.reasons


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


def test_what_is_said_is_written_with_one_dash():
    """Nothing said to a person is written with a long dash or a doubled hyphen: one rule where words leave
    (`said_plainly`), so it holds for a reply, a remembered sentence quoted back and a tool's words alike. What is
    no dash is kept: an option written with two hyphens, a markdown rule and a table's row of dashes."""
    from core.agents.autonomous.autonomous_coordinator import said_plainly
    assert said_plainly("Noted — The dog is in the kennel.") == "Noted - The dog is in the kennel."
    assert said_plainly("It reads lessons 1–26 -- then WordNet.") == "It reads lessons 1-26 - then WordNet."
    assert said_plainly("word--word and a—b") == "word - word and a - b"
    assert said_plainly("— a line that starts with a dash") == "- a line that starts with a dash"
    for kept in ("Run it with --fresh and --k-only.", "| a | b |\n| --- | --- |\n| 1 | 2 |", "Title\n\n---\n\nBody",
                 "nothing to change - here"):
        assert said_plainly(kept) == kept, kept


@pytest.mark.asyncio
async def test_a_reply_is_written_with_one_dash(talk):
    """The speech path applies it: a telling noted is said with a hyphen."""
    understanding = await talk.understand("The door is open.", look_up=False)
    reply = Conversation.say(understanding)
    assert "—" not in reply and "–" not in reply and " -- " not in reply, reply


@pytest.mark.asyncio
async def test_a_question_about_a_known_thing_asks_the_reasoner_the_one_fact_asked(talk, monkeypatch):
    """"Is the tank full?" reads as the tank both know (given instance_of(?t0, tank)) and what is asked of it
    (has_property(?t0, full)). Once the tank is found (`tank_1`), what it is only named it: the reasoner is asked the
    one fact, tank_1 has_property full, and its proof answers yes. Counted as two facts, no yes/no question about a
    known thing reached the reasoner, so a rule told about the tank never answered one."""
    from core.reasoning import neural_bridge
    from core.reasoning.neural_bridge import ReasoningResult
    from core.semantics.derived_reader import MeaningFact
    asked = []

    class Reasoner:
        async def reason(self, request):
            asked.append(request.reading.facts)
            return ReasoningResult(answer="Proved: tank_1_full", confidence=1.0, metadata={
                "verified": True, "route": ["substrate", "held_rules", "proved"],
                "chain": ["valve_1 has property closed", "tank_1 has property full"]})

    async def found(meaning, *, telling=False):
        return {"?t0": "tank_1"}

    async def held_premises(*_):
        return []

    meaning = Meaning("ask", (MeaningFact("instance_of", "?t0", "tank", given=True),
                              MeaningFact("has_property", "?t0", "full")))
    monkeypatch.setattr(neural_bridge, "get_neural_bridge", lambda: Reasoner())
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_of", found)
    monkeypatch.setattr(talk, "_held_premises", held_premises)
    answers = await talk._reasoned_answers("Is the tank full?", [], None)
    assert asked == [(MeaningFact("has_property", "tank_1", "full"),)], asked
    assert [(a.about, a.relation, a.others, a.verdict) for a in answers] == [
        ("tank_1", "has_property", ("full",), True)], answers


@pytest.mark.asyncio
async def test_a_question_that_only_names_what_was_found_is_not_answered(talk, monkeypatch):
    """"Is the valve closed?" composed as the valve alone (given instance_of(?t0, valve)): once the valve is found,
    nothing is left to ask. No answer is derived and the reasoner is not asked; taken as a question, it stopped the
    conversation."""
    from core.reasoning import neural_bridge
    from core.semantics.derived_reader import MeaningFact
    asked = []

    class Reasoner:
        async def reason(self, request):
            asked.append(request)

    async def found(meaning, *, telling=False):
        return {"?t0": "valve_1"}

    async def held_premises(*_):
        return []

    meaning = Meaning("ask", (MeaningFact("instance_of", "?t0", "valve", given=True),))
    monkeypatch.setattr(neural_bridge, "get_neural_bridge", lambda: Reasoner())
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_of", found)
    monkeypatch.setattr(talk, "_held_premises", held_premises)
    assert await talk._reasoned_answers("Is the valve closed?", [], None) == [] and not asked


@pytest.mark.asyncio
async def test_a_telling_read_by_composing_is_not_taken_in_whole(talk, monkeypatch):
    """A telling no taught frame read, read by composing its meaning, is held but not taken in whole
    (`_not_taken_in`), so no answer closes the world on what it names; one a frame read is taken in whole."""
    import core.memory
    from core.semantics.derived_reader import MeaningFact, Reading, Utterance
    meaning = Meaning("tell", (MeaningFact("has_property", "chlorophyll", "green"),))

    async def nothing(*_, **__):
        return None

    async def agent():
        return None

    async def telling(*_, **__):
        return None, []

    monkeypatch.setattr(talk, "_listen", nothing)
    monkeypatch.setattr(talk, "_telling", telling)
    monkeypatch.setattr(core.memory, "get_memory_agent", agent)
    for composed, sentence in ((False, "Chlorophyll is green."), (True, "Chlorophyll is the green pigment.")):
        utterance = Utterance(form_of(sentence), (Reading((), (), meaning, composed=composed),))
        monkeypatch.setattr(talk, "_read", lambda text, u=utterance: (u,))
        await talk.teach(sentence)
    assert list(talk._not_taken_in) == ["Chlorophyll is the green pigment."], talk._not_taken_in


@pytest.mark.asyncio
async def test_a_happening_told_is_held_as_one_event_of_the_tellers(talk, monkeypatch):
    """"Tom kicked the ball." tells of one kicking, done by Tom, done to the ball: named as teaching names a happening
    (`told_events`), from the telling with its known things found, and the teller's. Unnamed, every fact of it was
    "about something I have no name for yet", and no telling of a happening was ever held. The same telling names the
    same kicking; a kick of another ball is another."""
    import re
    from core.semantics.derived_reader import MeaningFact
    from types import SimpleNamespace
    meaning = Meaning("tell", (MeaningFact("instance_of", "?t0", "ball", given=True),
                               MeaningFact("instance_of", "?e", "kick"), MeaningFact("done_by", "?e", "tom"),
                               MeaningFact("done_to", "?e", "?t0"), MeaningFact("precedes", "?e", "?now")))
    balls = iter(["ball_1", "ball_1", "ball_2"])

    async def found(meaning, *, telling=False):
        return {"?t0": next(balls)}

    monkeypatch.setattr(talk, "_known_of", found)
    told = []
    for _ in range(3):
        telling, notes = await talk._telling("Tom kicked the ball.", SimpleNamespace(meaning=meaning, constructions=()),
                                             dict(talk._situation()))
        assert not notes, [n.detail for n in notes]
        told.append(telling)
    kicking = next(f.subject for f in told[0].facts if f.relation == "instance_of" and f.obj == "kick")
    assert re.fullmatch(r"kick_[0-9a-f]{8}", kicking), kicking
    assert {(f.relation, f.subject, f.obj) for f in told[0].facts if f.relation != "precedes"} == {
        ("instance_of", "ball_1", "ball"), ("instance_of", kicking, "kick"), ("done_by", kicking, "tom"),
        ("done_to", kicking, "ball_1")}
    assert any(f.relation == "precedes" and f.subject == kicking for f in told[0].facts)
    assert kicking in told[0].theirs
    again = next(f.subject for f in told[1].facts if f.relation == "instance_of" and f.obj == "kick")
    other = next(f.subject for f in told[2].facts if f.relation == "instance_of" and f.obj == "kick")
    assert again == kicking and other != kicking, (kicking, again, other)


@pytest.mark.asyncio
async def test_what_a_speaker_told_points_at_a_thing_from_their_own_context():
    """"What did Tom kick?" is answered by what points at Tom (`_incoming_relations`). A kicking a speaker told of is
    held in their context, and is found there for them, and for no one else. Held in working memory here: nothing is
    written."""
    import random
    import string
    from core.memory import get_memory_agent
    from core.memory.remembering import not_remembered
    token = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    teller = Conversation(session=f"zteller{token}", remembers=False)
    other = Conversation(session=f"zother{token}", remembers=False)
    kicking, kicker = f"kick_{token}", f"ztom{token}"
    agent = await get_memory_agent()
    with not_remembered():
        decision = await agent.hold_for_person(teller._actor, kicking, "done_by", kicker, positive=True, quality=0.9,
                                               domain="conversation", surface="Tom kicked the ball.", source="told")
        told = await teller._incoming_relations(kicker)
        not_told = await other._incoming_relations(kicker)
    assert decision.standing == "theirs", decision
    assert (kicking, "done by", kicker, True) in told, told
    assert not any(subject == kicking for subject, *_ in not_told), not_told
