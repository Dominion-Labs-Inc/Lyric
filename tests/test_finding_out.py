"""What a person asks decides the work (`Conversation.finding_out`): a request whose doing is a kind of finding out,
as held, asks what it is about, the question "What is ...?" reads as; its sentence is then understood as that
question (`Conversation.understand_as`). The held kinds are stood in for; nothing touches a store."""
import asyncio

from core.agents.autonomous import autonomous_coordinator as ac
from core.semantics.derived_reader import Meaning, MeaningFact

#: As `data/lessons/kinds_of_finding_out.json` teaches them.
KINDS = {"look up": ["research", "find out"], "research": ["find out"], "investigate": ["find out"]}


def _request(doing, *facts):
    return Meaning("request", (MeaningFact("instance_of", "?v0", doing), MeaningFact("done_by", "?v0", "?listener"))
                   + tuple(facts))


def _asked(monkeypatch, meaning):
    async def objects(self, subject, relation):
        return KINDS.get(subject, []) if relation == "isa" else []
    monkeypatch.setattr(ac._Held, "objects", objects)
    conversation = ac.Conversation.__new__(ac.Conversation)
    return asyncio.run(conversation.finding_out(meaning))


def test_a_request_to_find_something_out_asks_what_it_is_about(monkeypatch):
    rome = _request("look up", MeaningFact("done_to", "?v0", "?v1"), MeaningFact("instance_of", "?v1", "history",
                                                                                   given=True),
                    MeaningFact("word_of", "?v1", "rome"))
    assert _asked(monkeypatch, rome).canonical() == (
        "ask: equals(?v0, ?v1) & given instance_of(?v0, history) & word_of(?v0, rome) ? ?v1")
    about = _request("find out", MeaningFact("word_about", "?v0", "?v1"),
                     MeaningFact("instance_of", "?v1", "photosynthesis"))
    assert _asked(monkeypatch, about).canonical() == "ask: equals(?v0, ?v1) & instance_of(?v0, photosynthesis) ? ?v1"


def test_a_request_for_anything_else_asks_no_finding_out(monkeypatch):
    flight = _request("book", MeaningFact("done_to", "?v0", "?v1"), MeaningFact("instance_of", "?v1", "flight"))
    assert _asked(monkeypatch, flight) is None
    nothing_named = _request("research", MeaningFact("done_to", "?v0", "?speaker"))
    assert _asked(monkeypatch, nothing_named) is None
    told = Meaning("tell", (MeaningFact("isa", "research", "work"),))
    assert _asked(monkeypatch, told) is None


def test_a_sentence_understood_as_what_it_asks_means_that_while_it_is_understood():
    conversation = ac.Conversation.__new__(ac.Conversation)
    conversation._taken_as = {}
    question = Meaning("ask", (MeaningFact("instance_of", "?v0", "photosynthesis"),
                               MeaningFact("equals", "?v0", "?q")), ("?q",))
    seen = []

    async def understand(sentence):
        seen.append(conversation._meaning(sentence))
        return "understood"
    conversation.understand = understand
    assert asyncio.run(conversation.understand_as("Research photosynthesis.", question)) == "understood"
    assert seen == [question] and conversation._taken_as == {}
