"""How complex what arrives is, scored once by the reasoning authority as it arrives, and read where it is needed.

A task is scored as the queue takes it in (`QueueAuthority.add_task`, on its provenance), by the reasoning authority
(`NeuralSymbolicBridge.complexity_of`); a task that comes with its score keeps it. Whether a request calls for what
is remembered is the memory agent's, from that score (`MemoryAgent.calls_for_recall`): it never scores a request
itself. No store: the queue runs without persistence.
"""

import asyncio

from core.agents.autonomous.queue_authority import QueueAuthority
from core.agents.autonomous.shared_types import Priority, Task, TaskType
from core.agents.memory_agent import MemoryAgent
from core.reasoning.neural_bridge import get_neural_bridge


def test_a_task_is_scored_by_the_reasoning_authority_as_the_queue_takes_it_in():
    async def run():
        authority = QueueAuthority({"persist": False})
        said = "Why does the backup fail on Fridays, and how should the retention policy change?"
        task = Task(id="arrives_scored", type=TaskType.ANALYSIS, priority=Priority.MEDIUM, description=said)
        assert await authority.add_task(task, Priority.MEDIUM)
        assert task.provenance["complexity"] == get_neural_bridge().complexity_of(said)

        kept = Task(id="arrives_with_its_score", type=TaskType.ANALYSIS, priority=Priority.MEDIUM,
                    description=said, provenance={"complexity": 0.1})
        assert await authority.add_task(kept, Priority.MEDIUM)
        assert kept.provenance["complexity"] == 0.1, "scored once: a task that came with its score keeps it"

    asyncio.run(run())


def test_the_memory_agent_recalls_by_the_reasoning_authoritys_score():
    bridge = get_neural_bridge()
    complex_request = "Why does the backup fail on Fridays, and how should the retention policy change?"
    assert MemoryAgent.calls_for_recall(complex_request, bridge.complexity_of(complex_request))
    assert not MemoryAgent.calls_for_recall("list files", bridge.complexity_of("list files"))
    assert MemoryAgent.calls_for_recall("what did we discuss last time", 0.0), "a request asking for memory is recalled for"
    assert not MemoryAgent.calls_for_recall("list files", None), "with no score, only a request asking for memory"
    assert not MemoryAgent.calls_for_recall("   ", 1.0)
