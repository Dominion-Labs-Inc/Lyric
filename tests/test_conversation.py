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
from core.semantics.derived_reader import Meaning, MeaningFact as MeaningFact_, PatternInventory
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
    What does not read is none of them. (A sentence no frame reads is composed
    since 2026-10-18, so whether "a firewall blocks network traffic" reads
    depends on the sentences the store holds with their meanings: what never
    reads is an utterance of marks alone.) The store is opened first, as a
    test process has no substrate running to open it: run alone, this test
    found it closed."""
    from core.memory import get_memory_agent
    await get_memory_agent()
    assert talk.is_question("What is a robin?") is True
    assert talk.is_question("is a whale a fish or a mammal") is True
    assert talk.is_question("A robin is a bird.") is False
    assert talk.is_question("Close the door.") is False
    assert await talk.classify("What is a robin?") == "question"
    assert await talk.classify("The door is open and the window is closed.") == "telling"
    assert await talk.classify("please open the window") == "job"
    assert await talk.classify("...") == "not_understood"


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


def test_it_and_they_point_back_to_what_was_spoken_of_as_many_as_they_say():
    """A later "it" or "they" points back to the thing last spoken of that is as many as it says, the one the telling
    was about first. Taken as the first concept a meaning named, it was the doing's kind ("They release oxygen." done
    by taking in) or the company that hired the engineers ("Two of them work in Berlin.")."""
    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.semantics.derived_reader import MeaningFact as F

    talk = Conversation()
    talk._spoke_of([F("instance_of", "hire_1", "hire"), F("instance_of", "company_1", "company"),
                    F("instance_of", "engineer_1", "engineer"), F("done_by", "hire_1", "company_1"),
                    F("done_to", "hire_1", "engineer_1"), F("has_count", "engineer_1", "3")], {})
    assert talk._previous_for("Two of them work in Berlin.") == "engineer_1"
    assert talk._previous_for("It is in Berlin.") == "company_1"
    talk._spoke_of([F("instance_of", "take_1", "take_in"), F("done_by", "take_1", "plant"),
                    F("done_to", "take_1", "water_1"), F("instance_of", "water_1", "water")], {})
    assert talk._previous_for("They release oxygen.") == "plant"
    talk._spoke_of([F("instance_of", "build_1", "build"), F("done_to", "build_1", "eiffel_tower"),
                    F("during", "build_1", "1889")], {})
    assert talk._previous_for("It is in Paris.") == "eiffel_tower"
    talk._spoke_of([], {})
    assert talk._previous_for("It is in Paris.") == "eiffel_tower", "what names nothing leaves it as it was"


def test_a_pronoun_agrees_in_person_and_reaches_past_the_last_utterance():
    """"It" never points back to one memory holds a person, "he" never to one it holds is none, and of what one
    utterance spoke of, one held to be what the pronoun says comes before one held nothing of (memory stands in here:
    who it holds a person). What an utterance names before its pronoun is nearest, and what was spoken of before the
    last utterance is still there to point back to. After "Tom had a small dog.", "It chased a red ball." was Tom
    chasing, and "he" after it could point only to the ball (lyric_dev, 2026-10-24)."""
    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.semantics.derived_reader import Meaning
    from core.semantics.derived_reader import MeaningFact as F

    talk = Conversation()
    held = {"dog_1": False, "ball_1": False}
    talk._is_person = held.get
    talk._spoke_of([F("owns", "tom", "dog_1"), F("instance_of", "dog_1", "dog")], {})
    assert talk._previous_for("It chased a red ball.") == "dog_1", "Tom spoken of first, nothing held of him"
    assert talk._previous_for("He laughed.") == "tom", "the dog is held no person"
    talk._spoke_of([F("instance_of", "chase_1", "chase"), F("done_by", "chase_1", "dog_1"),
                    F("done_to", "chase_1", "ball_1"), F("instance_of", "ball_1", "ball")], {})
    assert talk._previous_for("He found the ball.") == "tom", "Tom, spoken of before the last utterance"
    followed = Meaning("tell", (F("instance_of", "?v0", "follow"), F("done_by", "?v0", "bill"),
                                F("done_to", "?v0", "dog_1")))
    said = "Bill followed the dog and he found it."
    assert talk._previous_for(said, talk._named_before_its_pronoun(said, followed)) == "bill", \
        "named before the pronoun in its own utterance"


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
async def test_a_happening_found_answers_its_question_though_nothing_taught_says_it(talk, monkeypatch):
    """Told "They live in the ocean." (a living, done by the whale, in `ocean_1`), "Do whales live in the ocean?" finds
    the living, and nothing taught says "Whales live in the ocean.": the answer is still yes. "Where do whales live?"
    is answered by what fills it, the ocean by its kind. Dropped unsaid, both went unanswered with the living found."""
    from types import SimpleNamespace
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import MeaningFact
    living = "live_a2cf4070"
    incoming = {"whale": [(living, "done by", "whale", True)], "live": [(living, "instance of", "live", True)],
                "ocean_1": [(living, "located in", "ocean_1", True)]}
    asked = {
        "Do whales live in the ocean?": Meaning("ask", (
            MeaningFact("done_by", "?e", "whale"), MeaningFact("instance_of", "?e", "live"),
            MeaningFact("located_in", "?e", "ocean_1"))),
        "Where do whales live?": Meaning("ask", (
            MeaningFact("done_by", "?e", "whale"), MeaningFact("instance_of", "?e", "live"),
            MeaningFact("located_in", "?e", "?x")), ("?x",))}

    async def found(meaning, *, telling=False):
        return {}

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=[("instance of", "live"), ("done by", "whale"),
                                                      ("located in", "ocean_1")])

    async def kind_of(name):
        return "ocean" if name == "ocean_1" else None

    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked[sentence])
    monkeypatch.setattr(talk, "_known_of", found)
    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    monkeypatch.setattr(talk, "_kind_of", kind_of)
    monkeypatch.setattr(dr, "say", lambda *a, **k: ())
    yes, = await talk._asked_of_events("Do whales live in the ocean?", incoming)
    assert (yes.about, yes.others, yes.verdict) == (living, (), True), yes
    where, = await talk._asked_of_events("Where do whales live?", incoming)
    assert (where.about, where.others, where.verdict) == (living, ("ocean",), None), where


@pytest.mark.asyncio
async def test_a_thing_with_a_name_of_its_own_is_said_by_its_name_not_its_kind(talk, monkeypatch):
    """A particular is named for its kind, with a mark (`kelt_1`; a happening told, `provide_f11f8919`), and is said
    by its kind. A thing held as one of a kind under a name of its own is said by its name: West Africa, held an
    instance of a geographical area, answered "Where did the Tichitt Tradition flourish?" as "Geographical area."
    (UNDERSTANDS-PROSE-02, 2026-10-22)."""
    from types import SimpleNamespace
    held = {"west_africa": [("instance of", "geographical_area")], "kelt_1": [("instance of", "kelt")],
            "provide_f11f8919": [("instance of", "provide")], "base_class_1": [("instance of", "base class")]}

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=held.get(name, []))

    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    assert await talk._kind_of("west_africa") is None
    assert await talk._kind_of("kelt_1") == "kelt"
    assert await talk._kind_of("provide_f11f8919") == "provide"
    assert await talk._kind_of("base_class_1") == "base class"


@pytest.mark.asyncio
async def test_an_answer_that_only_says_what_the_question_says_is_none(talk, monkeypatch):
    """Told unittest provides a base class (`base_class_1`, named for nothing else), "Which base class does unittest
    provide?" found it and said it by its kind, "Base class.": the question's own words (UNDERSTANDS-PROSE-02,
    2026-10-22). It is no answer. "What does unittest provide?", naming no kind, is answered by it."""
    from types import SimpleNamespace
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import MeaningFact
    providing = "provide_f11f8919"
    incoming = {"unittest": [(providing, "done by", "unittest", True)],
                "provide": [(providing, "instance of", "provide", True)]}
    held = {providing: [("instance of", "provide"), ("done by", "unittest"), ("done to", "base_class_1")],
            "base_class_1": [("instance of", "base class")]}

    def asked(*kind):
        return Meaning("ask", (MeaningFact("done_by", "?e", "unittest"), MeaningFact("instance_of", "?e", "provide"),
                               MeaningFact("done_to", "?e", "?x"))
                       + tuple(MeaningFact("instance_of", "?x", k) for k in kind), ("?x",))

    async def found(meaning, *, telling=False):
        return {}

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=held.get(name, []))

    async def kind_of(name):
        return "base class" if name == "base_class_1" else None

    monkeypatch.setattr(talk, "_known_of", found)
    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    monkeypatch.setattr(talk, "_kind_of", kind_of)
    monkeypatch.setattr(dr, "say", lambda *a, **k: ())
    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked("base class"))
    assert await talk._asked_of_events("Which base class does unittest provide?", incoming) == []
    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked())
    what, = await talk._asked_of_events("What does unittest provide?", incoming)
    assert (what.about, what.others) == (providing, ("base class",)), what


@pytest.mark.asyncio
async def test_what_a_question_asks_of_those_a_happening_was_done_by_is_asked_of_them(talk, monkeypatch):
    """Told "The account was locked after five failed attempts." (a failing done by `attempt_1`, five of them), "How
    many failed attempts were there?" finds the failing and asks the count of the attempts it was done by: the attempts
    hold it, and the answer is five. Read only of the failing, the count was never filled (2026-10-20). Asked of a
    kind the attempts are not, the failing is no answer."""
    from types import SimpleNamespace
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import MeaningFact
    failing = "fail_a8ea4f09"
    incoming = {"fail": [(failing, "instance of", "fail", True)]}
    held = {failing: [("instance of", "fail"), ("done by", "attempt_1")],
            "attempt_1": [("instance of", "attempt"), ("has count", "5")]}

    def asked(kind):
        return Meaning("ask", (MeaningFact("instance_of", "?x2", "fail"), MeaningFact("instance_of", "?x3", kind),
                               MeaningFact("has_count", "?x3", "?x0"), MeaningFact("done_by", "?x2", "?x3")), ("?x0",))

    async def found(meaning, *, telling=False):
        return {}

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=held.get(name, []))

    async def kind_of(name):
        return "attempt" if name == "attempt_1" else None

    monkeypatch.setattr(talk, "_known_of", found)
    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    monkeypatch.setattr(talk, "_kind_of", kind_of)
    monkeypatch.setattr(talk, "_particulars", {"attempt_1": ("attempt", "person")})
    monkeypatch.setattr(dr, "say", lambda *a, **k: ())
    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked("attempt"))
    count, = await talk._asked_of_events("How many failed attempts were there?", incoming)
    assert (count.about, count.others, count.verdict) == (failing, ("5",), None), count
    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked("password"))
    assert await talk._asked_of_events("How many failed passwords were there?", incoming) == []


@pytest.mark.asyncio
async def test_a_question_is_asked_of_what_is_held_as_a_whole(talk, monkeypatch):
    """`_asked_of_events` binds every unknown a question names against what is held, read as its relations say
    (`_Held`). Told chlorophyll is the green pigment that absorbs the light, "What absorbs the light?" is chlorophyll,
    not "Pigment.", and "Is chlorophyll green?" is yes: a thing is what it equals. Told plants take in carbon dioxide
    and water (a group), "Do plants take in carbon dioxide?" is yes. "Did the server log a failed login?" names two
    happenings, both found. "What is the largest animal?", told the blue whale is, is the blue whale (equals held the
    other way round), not the animal asked of. Told two of the engineers work in Berlin, "Do two of the engineers work
    in Berlin?" is yes: the two are found from the engineers, never from the number. Told the Eiffel Tower is in Paris,
    and Paris part of France, it is in France, and not for that part of France. (UNDERSTANDS-PROSE-01 on main,
    2026-10-21.)"""
    from types import SimpleNamespace
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import MeaningFact as F
    held = {"chlorophyll": [("equals", "pigment_1")],
            "pigment_1": [("instance of", "pigment"), ("has property", "green")],
            "absorb_1": [("instance of", "absorb"), ("done by", "pigment_1"), ("done to", "light_1")],
            "light_1": [("instance of", "light")],
            "take_in_1": [("instance of", "take in"), ("done by", "plant"), ("done to", "group_1")],
            "group_1": [("has member", "co2_1"), ("has member", "water_1")],
            "co2_1": [("instance of", "carbon dioxide")], "water_1": [("instance of", "water")],
            "log_1": [("instance of", "log"), ("done by", "server_1"), ("done to", "login_1")],
            "fail_1": [("instance of", "fail"), ("done by", "login_1")],
            "login_1": [("instance of", "login")], "server_1": [("instance of", "server")],
            "blue_whale_1": [("instance of", "blue whale"), ("equals", "animal_1")],
            "animal_1": [("instance of", "animal"), ("has degree", "large_1")],
            "large_1": [("instance of", "large"), ("greatest of", "animal")],
            "engineer_1": [("instance of", "engineer"), ("has count", "3")],
            "group_2": [("has count", "2"), ("part of", "engineer_1")],
            "work_1": [("instance of", "work"), ("done by", "group_2"), ("located in", "berlin")],
            "eiffel tower": [("located in", "paris")], "paris": [("part of", "france")]}
    pointing = {}
    for subject, relations in held.items():
        for relation, obj in relations:
            pointing.setdefault(obj, []).append((subject, relation, obj, True))
    kinds = {name: obj for name, relations in held.items() for relation, obj in relations if relation == "instance of"}
    asked = {
        "What absorbs the light?": (Meaning("ask", (
            F("instance_of", "?e", "absorb"), F("done_by", "?e", "?x"), F("done_to", "?e", "?l"),
            F("instance_of", "?l", "light", given=True)), ("?x",)), {"?l": "light_1"}),
        "Is chlorophyll green?": (Meaning("ask", (F("has_property", "chlorophyll", "green"),)), {}),
        "Do plants take in carbon dioxide?": (Meaning("ask", (
            F("instance_of", "?e", "take in"), F("done_by", "?e", "plant"), F("done_to", "?e", "?c"),
            F("instance_of", "?c", "carbon dioxide"))), {}),
        "Did the server log a failed login?": (Meaning("ask", (
            F("instance_of", "?e", "log"), F("done_by", "?e", "?s"), F("done_to", "?e", "?l"),
            F("instance_of", "?l", "login"), F("instance_of", "?f", "fail"), F("done_by", "?f", "?l"),
            F("instance_of", "?s", "server", given=True))), {"?s": "server_1"}),
        "What is the largest animal?": (Meaning("ask", (
            F("equals", "?a", "?w"), F("instance_of", "?a", "animal", given=True), F("has_degree", "?a", "?d"),
            F("instance_of", "?d", "large"), F("greatest_of", "?d", "animal")), ("?w",)), {"?a": "animal_1"}),
        "Do two of the engineers work in Berlin?": (Meaning("ask", (
            F("has_count", "?g", "2"), F("instance_of", "?e", "work"), F("done_by", "?e", "?g"),
            F("located_in", "?e", "berlin"), F("part_of", "?g", "?n"), F("instance_of", "?n", "engineer", given=True))),
            {"?n": "engineer_1"}),
        "Is the Eiffel Tower in France?": (Meaning("ask", (F("located_in", "eiffel tower", "france"),)), {}),
        "Is the Eiffel Tower part of France?": (Meaning("ask", (F("part_of", "eiffel tower", "france"),)), {})}

    async def known(meaning, *, telling=False):
        return next(found for m, found in asked.values() if m == meaning)

    async def incoming(name):
        return pointing.get(name, [])

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=held.get(name, []))

    async def kind_of(name):
        return kinds.get(name)
    monkeypatch.setattr(talk, "_meaning", lambda sentence: asked[sentence][0])
    monkeypatch.setattr(talk, "_known_of", known)
    monkeypatch.setattr(talk, "_incoming_relations", incoming)
    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    monkeypatch.setattr(talk, "_kind_of", kind_of)
    monkeypatch.setattr(talk, "_particulars", {name: (kind, "person") for name, kind in kinds.items()})
    monkeypatch.setattr(dr, "say", lambda *a, **k: ())
    what, = await talk._asked_of_events("What absorbs the light?", {})
    assert (what.about, what.others) == ("absorb_1", ("chlorophyll",)), what
    green, = await talk._asked_of_events("Is chlorophyll green?", {})
    assert green.verdict is True, green
    taken, = await talk._asked_of_events("Do plants take in carbon dioxide?", {})
    assert (taken.about, taken.verdict) == ("take_in_1", True), taken
    logged, = await talk._asked_of_events("Did the server log a failed login?", {})
    assert (logged.about, logged.verdict) == ("log_1", True), logged
    largest, = await talk._asked_of_events("What is the largest animal?", {})
    assert largest.others == ("blue whale",), largest
    two, = await talk._asked_of_events("Do two of the engineers work in Berlin?", {})
    assert (two.about, two.verdict) == ("work_1", True), two
    in_france, = await talk._asked_of_events("Is the Eiffel Tower in France?", {})
    assert in_france.verdict is True, in_france
    assert await talk._asked_of_events("Is the Eiffel Tower part of France?", {}) == []
    held["fail_1"] = [("instance of", "fail"), ("done by", "attempt_1")]
    pointing["login_1"] = [row for row in pointing["login_1"] if row[0] != "fail_1"]
    assert await talk._asked_of_events("Did the server log a failed login?", {}) == []


def test_a_known_thing_talked_of_here_is_the_one_meant(talk, monkeypatch):
    """Told of an account (`account_1`), "Was the account locked?" takes the account as the account, not a record of
    history, the sense met most: a word marked known names the kind of a particular told of here where it can
    (`_known_here`), packed among its senses or read apart. Where nothing of that kind was told of, every sense is
    offered."""
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import Lexical, Link, MeaningFact, Reading, Sense, Utterance

    def sense(value):
        return Sense(Lexical((dr.Piece("account", False),), value), Link("p", "?slot1", value), True), (0, 0, 0)
    packed = Reading((), (), Meaning("ask", (MeaningFact("instance_of", "?a", "⟨1⟨account", given=True),
                                             MeaningFact("done_to", "?e", "?a"))),
                     senses=(("⟨1⟨account", (sense("record history"), sense("account")), 0, 0),))
    apart = [Reading((), (), Meaning("ask", (MeaningFact("instance_of", "?a", kind, given=True),
                                             MeaningFact("done_to", "?e", "?a")))) for kind in ("record history",
                                                                                               "account")]
    monkeypatch.setattr(dr, "read_text", lambda text, view, parts=True: (
        Utterance(form_of(text), (packed,) if "packed" in text else tuple(apart)),))
    assert [o[0].lexical.value for o in talk._read("packed")[0].readings[0].senses[0][1]] == \
        ["record history", "account"]
    talk._particulars["account_1"] = ("account", "person")
    assert [o[0].lexical.value for o in talk._read("packed")[0].readings[0].senses[0][1]] == ["account"]
    reading, = talk._read("Was the account locked?")[0].readings
    assert MeaningFact("instance_of", "?a", "account", given=True) in reading.meaning.facts


@pytest.mark.asyncio
async def test_the_x_is_the_x_talked_of_most(talk, monkeypatch):
    """"What does the method detect?" after a paper's abstract proposed a method, went on about it, and compared it once
    with earlier methods: the method is the one talked of most, not the earlier methods told of last."""
    talk._particulars.update({"method_new": ("method", "person"), "method_earlier": ("method", "person")})
    talk._mentioned.update({"method_new": 2, "method_earlier": 1})
    asked = Meaning("ask", (MeaningFact_("instance_of", "?m", "method", given=True), MeaningFact_("done_by", "?e", "?m")))
    assert await talk._known_of(asked) == {"?m": "method_new"}


@pytest.mark.asyncio
async def test_a_question_is_also_asked_as_the_grammar_reads_it(talk, monkeypatch):
    """Told a locking done to the account (`lock_1`, read by the grammar), "Was the account locked?" read by a frame as
    the account doing an embracing finds nothing told; asked as memory's grammar reads it, a locking done to the
    account, it finds the locking: yes. Where the grammar reads it as the frame did, nothing more is asked."""
    from types import SimpleNamespace
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import MeaningFact
    framed = Meaning("ask", (MeaningFact("instance_of", "?e", "embrace interlock"), MeaningFact("done_by", "?e", "?a"),
                             MeaningFact("instance_of", "?a", "account", given=True)))
    composed = Meaning("ask", (MeaningFact("instance_of", "?e", "lock"), MeaningFact("done_to", "?e", "?a"),
                               MeaningFact("instance_of", "?a", "account", given=True)))
    held = {"lock_1": [("instance of", "lock"), ("done to", "account_1")]}
    pointing = {"lock": [("lock_1", "instance of", "lock", True)],
                "account_1": [("lock_1", "done to", "account_1", True)]}

    class View:
        def compose_sentence(self, sentence):
            return composed

    class Agent:
        # Memory holding no word recorded whole: nothing is a kind of anything by what a word means.
        def grammar_view(self):
            return View()

        def word_kinds(self, name):
            return []

        def word_senses_alike(self, name):
            return []

        def word_senses_written_so(self, name):
            return []

        def word_senses_any_class(self, name):
            return []

    async def known(meaning, *, telling=False):
        return {"?a": "account_1"}

    async def incoming(name):
        return pointing.get(name, [])

    async def resolve_name(name):
        return SimpleNamespace(known=True, relations=held.get(name, []))

    async def kind_of(name):
        return None
    monkeypatch.setattr(memory, "_memory_agent", Agent())
    monkeypatch.setattr(talk, "_meaning", lambda sentence: framed)
    monkeypatch.setattr(talk, "_known_of", known)
    monkeypatch.setattr(talk, "_incoming_relations", incoming)
    monkeypatch.setattr(talk, "resolve_name", resolve_name)
    monkeypatch.setattr(talk, "_kind_of", kind_of)
    monkeypatch.setattr(dr, "say", lambda *a, **k: ())
    yes, = await talk._asked_of_events_composed("Was the account locked?")
    assert (yes.about, yes.verdict) == ("lock_1", True), yes
    monkeypatch.setattr(talk, "_meaning", lambda sentence: composed)
    assert await talk._asked_of_events_composed("Was the account locked?") == []


def test_what_is_not_known_of_a_question_naming_only_a_known_thing_is_not_said():
    """A question of one fact that only names a known thing (given instance_of(?t0, light)) holds or not of nothing:
    what is not known of it is not said, and saying the reply goes on (the reply stopped there, 2026-10-17)."""
    from core.agents.autonomous.autonomous_coordinator import _not_known
    from core.semantics.derived_reader import MeaningFact
    assert _not_known(Meaning("ask", (MeaningFact("instance_of", "?t0", "light", given=True),))) is None


def _held(phrase, *relations):
    from core.agents.autonomous.autonomous_coordinator import Resolved
    return Resolved(phrase=phrase, concept_id=phrase, how="exact", relations=tuple(relations))


def test_what_a_question_asks_for_and_describes_twice_is_not_answered_by_one_of_them(talk, monkeypatch):
    """"In which journal did the engineers publish?" asks for a journal the publishing was done in. Any journal held
    answered it by the one fact `instance_of(?v2, journal)`, said "Journal." (UNDERSTANDS-PROSE-02, 2026-10-22): a
    question is all it asks at once, so what is asked for, described by more than one fact, is left to what is held
    as a whole (`_asked_of_events`)."""
    from core.semantics.derived_reader import MeaningFact
    meaning = Meaning("ask", (MeaningFact("done_by", "?v0", "?v1"),
                              MeaningFact("instance_of", "?v1", "engineer", given=True),
                              MeaningFact("instance_of", "?v0", "publish"),
                              MeaningFact("instance_of", "?v2", "journal"),
                              MeaningFact("received_by", "?v0", "?v2")), asked=("?v2",))
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_found", lambda meaning: {"?v1": "engineer_1"})
    incoming = {"journal": [("journal_1", "instance_of", "journal", True)]}
    assert talk.asked("In which journal did the engineers publish?", [], incoming) == []
    # Described once, it is answered by the one fact: "Which journal is prestigious?"
    meaning = Meaning("ask", (MeaningFact("has_property", "?v2", "prestigious"),), asked=("?v2",))
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_found", lambda meaning: {})
    incoming = {"prestigious": [("journal_1", "has_property", "prestigious", True)]}
    found = talk.asked("What is prestigious?", [], incoming)
    assert [(a.about, a.relation, a.others) for a in found] == [("journal_1", "has_property", ("prestigious",))]


def test_a_question_asking_for_something_is_not_answered_yes_by_what_names_nothing_it_asks(talk, monkeypatch):
    """"How many times can a person be elected to the office of the President?" was "Yes. A The office is part of a
    president.": the office's description, held, answered as if asked (UNDERSTANDS-PROSE-02, 2026-10-22). A question
    asking for something is answered only by facts that name what it asks."""
    from core.semantics.derived_reader import MeaningFact
    meaning = Meaning("ask", (MeaningFact("instance_of", "?v1", "office", given=True),
                              MeaningFact("part_of", "?v1", "president"),
                              MeaningFact("instance_of", "?v0", "elect"),
                              MeaningFact("moves_to", "?v0", "?v1"),
                              MeaningFact("has_count", "?v0", "?v2")), asked=("?v2",))
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_found", lambda meaning: {"?v1": "office_1"})
    office = _held("office_1", ("part of", "president"))
    assert talk.asked("How many times can a person be elected to the office of the President?", [office], {}) == []


def test_a_yes_or_no_is_of_all_a_question_says(talk, monkeypatch):
    """"Can a person be elected to the office of the President three times?" was "Yes." by the office's description
    alone, nothing held of the electing (UNDERSTANDS-PROSE-02, 2026-10-22). Yes is every part held; one part denied
    is no; a part not known leaves it unanswered."""
    from core.semantics.derived_reader import MeaningFact
    meaning = Meaning("ask", (MeaningFact("instance_of", "?v0", "office", given=True),
                              MeaningFact("part_of", "?v0", "president"),
                              MeaningFact("has_property", "person", "elected")))
    monkeypatch.setattr(talk, "_meaning", lambda sentence: meaning)
    monkeypatch.setattr(talk, "_known_found", lambda meaning: {"?v0": "office_1"})
    office = _held("office_1", ("part of", "president"))
    asked = "Can a person be elected to the office of the President?"
    assert talk.asked(asked, [office, _held("person")], {}) == []
    found = talk.asked(asked, [office, _held("person", ("has property", "elected"))], {})
    assert sorted((a.about, a.verdict) for a in found) == [("office_1", True), ("person", True)], found
    found = talk.asked(asked, [office, _held("person", ("not has property", "elected"))], {})
    assert [(a.about, a.verdict) for a in found] == [("person", False)], found


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

    async def told(*_, **__):
        return None, []

    monkeypatch.setattr(talk, "_listen", nothing)
    monkeypatch.setattr(talk, "_told", told)
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


@pytest.mark.asyncio
async def test_a_fact_a_telling_binds_twice_is_held_once(talk, monkeypatch):
    """Two things told of that are one once bound ("it", and the thing it stands for found known) say one fact twice;
    the telling holds it once, and what it holds is a meaning (`Conversation._told`). Held twice, the meaning made of
    it refused it and stopped the conversation (UNDERSTANDS-PROSE-02, 2026-10-26)."""
    from types import SimpleNamespace
    meaning = Meaning("tell", (MeaningFact_("located_in", "?previous", "asia"),
                               MeaningFact_("located_in", "?v1", "asia"),
                               MeaningFact_("instance_of", "?v1", "region", given=True)))

    async def known(meaning, telling=False):
        return {"?v1": "south_asia"}
    monkeypatch.setattr(talk, "_known_of", known)
    told, _ = await talk._told("It lies in Asia.", SimpleNamespace(meaning=meaning, constructions=()),
                               {"?previous": "south_asia"})
    assert [f for f in told[0] if f.relation == "located_in"] == [MeaningFact_("located_in", "south_asia", "asia")]
    assert Meaning("tell", told[0]).facts == told[0]
