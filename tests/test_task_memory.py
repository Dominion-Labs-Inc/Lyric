"""What a task's memory says, and that no memory is ever merged into another.

The store test runs against the database it is pointed at (the sandbox, `POSTGRES_DATABASE=torinai_dev`) and removes
every row it writes by id.
"""
import asyncio
from datetime import datetime
from uuid import uuid4

from core.agents.autonomous.governance_block_schema import (
    task_occurrences, task_outcome_account, task_outcomes_from_memory)


def _record(description, outcome, reason=None):
    return {"event": "task_outcome", "schema": "task_outcome_v1", "task_id": f"t_{uuid4().hex[:6]}",
            "task_type": "execution", "task_description": description, "outcome": outcome, "confidence": 0.9,
            "domain": "tools:path", "task_source": "internal", "timestamp": datetime.now().isoformat(),
            "failure_reason": reason}


def test_once_it_is_said_as_it_always_was():
    assert task_outcome_account("put report.txt in archive", [_record("x", "success")]) == \
        "I was asked to put report.txt in archive. I did it."
    assert task_outcome_account("put report.txt in archive", [_record("x", "failure", "the file was gone.")]) == \
        "I was asked to put report.txt in archive. I could not, because the file was gone."


def test_what_repeats_is_counted_not_listed():
    description = "put report.txt in archive"
    said = task_outcome_account(description, [
        _record(description, "success"), _record(description, "success"),
        _record(description, "failure", "completion belief 0.00 < acceptance 0.95"),
        _record(description, "failure", "completion belief 0.00 < acceptance 0.98"),
        _record(description, "failure", "the aim was not reached")])
    assert said == ("I was asked to put report.txt in archive. I did it 2 times. I could not 2 times, because "
                    "completion belief 0.00 < acceptance 0.98. I could not, because the aim was not reached."), said


def test_a_record_reads_back_as_its_occurrences():
    record = _record("put report.txt in archive", "success")
    assert task_occurrences(record) == [record]
    held = {**record, "occurrences": [record, _record("put report.txt in archive", "failure", "gone")]}
    assert [r.outcome for r in task_outcomes_from_memory({"thinking_state": {"raw_event": held}})] == \
        ["success", "failure"]


def test_the_same_thing_on_two_days_is_two_memories(monkeypatch):
    """The memory agent merges nothing: two memories that read alike are two memories."""
    monkeypatch.setenv("TORIN_SHADOW_MODE", "1")
    nonce = uuid4().hex[:8]

    async def run():
        from core.agents.memory_agent import MemoryAgent
        from core.database import get_database_manager
        from core.memory.utils.interfaces import MemoryType, Origin
        db = get_database_manager()
        await db.initialize()
        agent = MemoryAgent()
        ids = []
        try:
            for said in (f"The backup of the {nonce} volume finished and the checksums matched.",
                         f"The backup of the {nonce} volume finished and the checksums matched.",
                         f"A {nonce} kidney is an organ.", f"A {nonce} liver is an organ."):
                stored, memory_id = await agent.store_memory(
                    said, memory_type=MemoryType.EPISODIC, importance_score=0.8,
                    tags=["merge_check"], origin=Origin.own("task"))
                assert stored
                ids.append(memory_id)
            return ids
        finally:
            for memory_id in set(ids):
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)

    ids = asyncio.run(run())
    assert len(set(ids)) == 4, ids
