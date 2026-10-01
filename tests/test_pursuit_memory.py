"""One pursuit is one memory: formed as the work is taken on, every task within it added as it ends, repeats counted
rather than listed, closed with how the pursuit ended. Separate pursuits are never merged.

The store tests run against the database they are pointed at (the sandbox, `POSTGRES_DATABASE=lyric_dev`), with the
memory agent's background loops kept off (shadow mode), and remove every row they write by id.
"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from core.memory.utils.interfaces import pursuit_account
from core.memory import Experience, Origin, Part


def _task_record(description, outcome, reason=None):
    return {"event": "task_outcome", "schema": "task_outcome_v1", "task_id": f"t_{uuid4().hex[:6]}",
            "task_type": "execution", "task_description": description, "outcome": outcome, "confidence": 0.9,
            "domain": "tools:path", "task_source": "internal", "timestamp": datetime.now().isoformat(),
            "failure_reason": reason}


def _experience(*parts):
    return Experience("task", Origin.own("task"), tuple(parts), {"outcome": "success"})



def test_what_was_heard_and_seen_in_a_pursuit_is_said_with_it():
    """A perception within a pursuit is a part of its memory, and the memory's
    account says it, so the pursuit is found by what was met in it."""
    from core.agents.memory_agent import MemoryAgent
    heard = {"role": "heard", "source": "person",
             "content": {"caption": "3.1s wav recording, 2 sound(s); said \"are cats animals\"",
                         "subject": "livexab"}}
    seen = {"role": "seen", "source": "world",
            "content": {"caption": "640x360 jpeg image, 8 region(s)", "subject": "livexcd"}}
    record = {"pursuit": {"aim": "are cats animals", "status": "active"}, "occurrences": [],
              "experience": {"parts": MemoryAgent._summarize_parts([], [heard, seen])}}
    said = pursuit_account(record)
    assert said.startswith("I was asked to are cats animals.")
    assert 'I heard 3.1s wav recording, 2 sound(s); said "are cats animals".' in said
    assert "I saw 640x360 jpeg image, 8 region(s)." in said

def test_what_repeats_within_a_pursuit_is_counted_not_listed():
    from core.agents.memory_agent import MemoryAgent
    failed_read = {"role": "tool_run", "source": "substrate", "content": {"tool": "read_file", "success": False}}
    parts = MemoryAgent._summarize_parts([], [failed_read])
    parts = MemoryAgent._summarize_parts(parts, [
        failed_read,
        {"role": "error", "source": "world", "content": {"attempt": 1, "error": "No such file: /a/b.txt"}}])
    parts = MemoryAgent._summarize_parts(parts, [
        {"role": "error", "source": "world", "content": {"attempt": 2, "error": "No such file: /a/b.txt"}},
        {"role": "tool_run", "source": "substrate", "content": {"tool": "read_file", "success": True}}])
    assert [(p["role"], p["count"]) for p in parts] == [("tool_run", 2), ("error", 2), ("tool_run", 1)]
    assert parts[1]["content"]["attempt"] == 2, "the latest of a repeat is the one kept"


def test_a_pursuit_says_each_task_and_how_it_ended():
    record = {"pursuit": {"aim": "archive the report", "status": "active"}, "occurrences": [
        _task_record("read report.txt", "failure", "no such file"),
        _task_record("read report.txt", "failure", "no such file"),
        _task_record("read report.txt", "success"),
        _task_record("move report.txt to archive", "success")]}
    assert pursuit_account(record) == (
        "I was asked to read report.txt. I did it. I could not 2 times, because no such file. "
        "I was asked to move report.txt to archive. I did it.")
    record["pursuit"]["status"] = "fulfilled"
    assert pursuit_account(record).endswith("The pursuit ended: fulfilled.")
    assert pursuit_account({"pursuit": {"aim": "archive the report", "status": "active"}, "occurrences": []}) == \
        "I was asked to archive the report."


def test_one_pursuit_is_one_memory_and_two_are_two(monkeypatch):
    monkeypatch.setenv("LYRIC_SHADOW_MODE", "1")
    nonce = uuid4().hex[:8]

    async def run():
        from core.agents.memory_agent import MemoryAgent
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        agent = MemoryAgent()
        memories = []
        try:
            first = await agent.begin_pursuit(
                intent_id=f"pursuit-test-{nonce}-a", kind="test", aim=f"archive report {nonce}",
                origin=Origin.own("task"),
                trigger={"what": "error", "source": "world",
                         "content": {"error_type": "OSError", "message": "disk full",
                                     "traceback": "Traceback (most recent call last):\n" + "  x\n" * 400}})
            memories.append(first)
            failed = Part("tool_run", {"tool": "read_file", "success": False}, "substrate")
            for record, experience in (
                    (_task_record(f"read report {nonce}", "failure", "no such file"), _experience(failed)),
                    (_task_record(f"read report {nonce}", "failure", "no such file"), _experience(failed)),
                    (_task_record(f"move report {nonce}", "success"),
                     _experience(Part("tool_run", {"tool": "move_file", "success": True}, "substrate")))):
                await agent.add_to_pursuit(first, record, experience)
            await agent.close_pursuit(first, status="fulfilled", outcome={"matched_aim": True})
            closed = await agent._pursuit_record(first)
            pool = await db.execute_query(
                "SELECT item_id, parts, memory_id, status FROM unified.experience_pool WHERE memory_id = $1",
                (first,), fetch_all=True, store=None)
            # A task that ends after its pursuit closed is added, and the pursuit is decided again.
            await db.execute_query("UPDATE unified.experience_pool SET status = 'decided' WHERE memory_id = $1",
                                   (first,), commit=True, store=None)
            await agent.add_to_pursuit(first, _task_record(f"note report {nonce}", "success"),
                                       _experience(Part("step", {"tool": "write_file"}, "substrate")))
            requeued = await db.execute_query(
                "SELECT status FROM unified.experience_pool WHERE memory_id = $1", (first,),
                fetch_one=True, store=None)
            # Taken up again, it is the same pursuit and the same memory.
            again = await agent.begin_pursuit(
                intent_id=f"pursuit-test-{nonce}-a", kind="test", aim=f"archive report {nonce}",
                origin=Origin.own("task"),
                trigger={"what": "notification", "source": "substrate", "content": {"disk": "full again"}})
            reopened = await agent._pursuit_record(first)
            # A second pursuit with the same aim is its own memory.
            second = await agent.begin_pursuit(intent_id=f"pursuit-test-{nonce}-b", kind="test",
                                               aim=f"archive report {nonce}", origin=Origin.own("task"))
            memories.append(second)
            content = await db.execute_query("SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
                                             (first,), fetch_one=True, store=None)
            return first, second, again, closed, reopened, pool, requeued, content
        finally:
            for memory_id in [m for m in memories if m]:
                await db.execute_query("DELETE FROM unified.experience_pool WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)

    first, second, again, closed, reopened, pool, requeued, content = asyncio.run(run())
    record, _ = closed
    assert len(record["occurrences"]) == 3 and record["counts"] == {"success": 1, "failure": 2}
    trigger, *runs = record["experience"]["parts"]
    assert trigger["role"] == "trigger" and trigger["source"] == "world", trigger
    assert trigger["content"]["what"] == "error"
    assert trigger["content"]["content"]["traceback"].count("\n") == 401, "the traceback is kept whole"
    assert record["pursuit"]["trigger"]["content"]["message"] == "disk full"
    assert [(p["content"]["tool"], p["count"]) for p in runs] == [("read_file", 2), ("move_file", 1)]
    assert record["pursuit"]["status"] == "fulfilled"
    assert len(pool) == 1 and pool[0]["parts"] is None and pool[0]["memory_id"] == first, pool
    assert requeued["status"] == "waiting", requeued
    assert again == first and reopened[0]["pursuit"]["status"] == "active"
    assert reopened[0]["pursuit"]["last_trigger"]["content"] == {"disk": "full again"}
    assert [p["content"]["what"] for p in reopened[0]["experience"]["parts"] if p["role"] == "trigger"] == \
        ["error", "notification"], "a pursuit started again keeps each trigger that started it"
    assert second != first
    said = json.loads(content["content"]) if content["content"].startswith('"') else content["content"]
    assert "I could not 2 times, because no such file." in said, said


def test_the_coordinator_keeps_a_pursuit_in_one_memory(monkeypatch):
    """Taken on through `intend`, a root task and the task of a goal raised inside the pursuit land in one memory,
    and the pursuit's conclusion closes it."""
    monkeypatch.setenv("LYRIC_SHADOW_MODE", "1")
    nonce = uuid4().hex[:8]

    async def run():
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
        from core.agents.autonomous.shared_types import Priority, Task, TaskSource, TaskType
        from core.agents.memory_agent import MemoryAgent
        from core.database import get_database_manager
        from core.reasoning.intent_authority import continuity_goal, get_intent_authority
        db = get_database_manager()
        await db.initialize()
        coord = AutonomousCoordinator()
        coord.memory = MemoryAgent()
        intents, memory_id = [], None
        try:
            root_task = Task(id=f"pursuit-test-root-{nonce}", type=TaskType.EXECUTION,
                             description=f"tidy the {nonce} folder", priority=Priority.MEDIUM,
                             source=TaskSource.AUTONOMOUS, created_by="pursuit-test")
            root = await coord.intend(root_task, pursuit="test", trigger={
                "what": "message", "source": "person",
                "content": {"message": f"Could you tidy the {nonce} folder? It's a mess.", "source": "api"}})
            intents.append(root)
            memory_id = root_task.provenance.get("pursuit_memory_id")
            child = await get_intent_authority().form(
                "self_goal", "__substrate__", continuity_goal(f"pursuit-test-goal-{nonce}"),
                shape={"pursuit": "test"}, content={"aim": "read the folder"}, parent_intent_id=root)
            intents.append(child.intent_id)
            step = Task(id=f"pursuit-test-step-{nonce}", type=TaskType.EXECUTION,
                        description=f"read the {nonce} folder", priority=Priority.MEDIUM,
                        source=TaskSource.AUTONOMOUS, created_by="pursuit-test",
                        provenance={"intent_id": child.intent_id})
            from_step = await coord._store_task_outcome_meta_memory(step, "success", result={"success": True})
            from_root = await coord._store_task_outcome_meta_memory(root_task, "success",
                                                                    result={"success": True})
            await coord.conclude_pursuit(root_task, {"success": True}, completed=True)
            record, _ = await coord.memory._pursuit_record(memory_id)
            return memory_id, from_step, from_root, record
        finally:
            if memory_id:
                await db.execute_query("DELETE FROM unified.experience_pool WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)
            for intent_id in intents:
                for table in ("unified.intents", "unified.scoped_intents"):
                    await db.execute_query(f"DELETE FROM {table} WHERE intent_id = $1",
                                           (intent_id,), commit=True, store=None)

    memory_id, from_step, from_root, record = asyncio.run(run())
    assert memory_id and from_step == memory_id and from_root == memory_id
    assert [o["task_description"] for o in record["occurrences"]] == \
        [f"read the {nonce} folder", f"tidy the {nonce} folder"]
    assert record["pursuit"]["status"] == "fulfilled", record["pursuit"]
    assert record["pursuit"]["trigger"]["content"]["message"] == f"Could you tidy the {nonce} folder? It's a mess."
    first = record["experience"]["parts"][0]
    assert first["role"] == "trigger" and first["source"] == "person", first
