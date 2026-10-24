"""A question's look-up is work (`AutonomousCoordinator._look_up_as_work`): queued as a RESEARCH task carrying the
person's question, answered through the knowledge loop by whichever instance takes it, and said to them when it ends;
the reply says it is being looked up."""
import asyncio
import types

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator, Conversation, Understanding
from core.agents.autonomous.shared_types import TaskSource, TaskType


def test_a_look_up_is_queued_as_the_persons_question():
    queued = []

    async def add_task(task, priority=None):
        queued.append(task)
        return True
    coordinator = types.SimpleNamespace(task_queue=types.SimpleNamespace(add_task=add_task))
    conv = types.SimpleNamespace(_actor="alice", _session="world:alice", _context="work", _organization="northwind")
    assert asyncio.run(AutonomousCoordinator._look_up_as_work(coordinator, conv, "What is photosynthesis?"))
    task = queued[0]
    assert task.type is TaskType.RESEARCH and task.description == "What is photosynthesis?"
    assert task.actor == "alice" and task.source is TaskSource.API and task.created_by == "look_up"
    assert task.metadata["conversation_id"] == "world:alice" and task.metadata["told_taken_on"] is True
    assert (task.metadata["context"], task.metadata["organization"]) == ("work", "northwind")


def test_the_reply_says_it_is_being_looked_up():
    said = Conversation.say(Understanding(sentence="What is photosynthesis?", asked=True, looking_up="photosynthesis"))
    assert said == "I don't hold photosynthesis yet; I'm looking it up."
