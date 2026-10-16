"""What a conversation held not to remember is told is held in working memory, never in the store.

A conversation not remembered (`Conversation(remembers=False)`) still hears what it is told: memory holds it for that
person in working memory, as the premises of what they ask next, and writes none of it. Told nothing, it could
reason over nothing: a paragraph read to it, then asked about, was answered out of what it held before
(UNDERSTANDS-PROSE-01, 2026-10-14). On the sandbox, "Rex is a dog." then "Is Rex a dog?" is answered yes, with no
table written to."""
import pytest

from core.agents.memory_agent import MemoryAgent
from core.memory.remembering import not_remembered


@pytest.mark.asyncio
async def test_what_a_conversation_not_remembered_is_told_is_held_in_working_memory_each_persons_apart():
    agent = MemoryAgent()
    with not_remembered():
        await agent.hold_scoped_relation(actor="anon:a", subject="rex", relation="isa", obj="dog",
                                         polarity="positive", surface="Rex is a dog.", domain="conversation",
                                         source="told")
        await agent.hold_scoped_belief(actor="anon:a", claim_key="rex isa dog", claim="rex isa dog",
                                       domain="conversation", prior=0.5, posterior=0.7, log_odds=0.85, supports=True,
                                       update_count=1, surface="Rex is a dog.", source="told")
    assert agent.working_relations(["anon:a"]) == [
        {"subj": "rex", "rel": "isa", "obj": "dog", "pol": "positive", "surface": "Rex is a dog.",
         "scope_actor": "anon:a"}]
    assert [belief["claim"] for belief in agent.working_beliefs(["anon:a"])] == ["rex isa dog"]
    assert agent.working_relations(["anon:b"]) == [] and agent.working_beliefs(["anon:b"]) == [], \
        "what one person told is theirs"
