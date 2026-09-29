"""The memory agent is the only writer of the substrate's memory.

`scripts/separation_map.py` finds every string in `core/` that holds a statement writing a memory table,
whatever runs it -- the database manager, a raw connection -- and none may sit outside the memory agent.
"""
import importlib.util
import os
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "separation_map", os.path.join(ROOT, "scripts", "separation_map.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_the_memory_agent_writes_memory():
    outside, _scripts = _scanner().memory_written_outside_the_agent()
    assert outside == [], "memory written outside the memory agent:\n" + "\n".join(
        f"  {f}:{line} {table}" for f, line, table in outside)


def test_a_write_of_memory_is_found_whatever_runs_it(tmp_path):
    module = tmp_path / "writer.py"
    module.write_text(textwrap.dedent('''
        async def write(db, conn, table):
            await db.execute_query("INSERT INTO unified.beliefs (belief_id) VALUES ($1)", ("b",))
            await conn.execute(f"DELETE FROM {table} WHERE rule_id = $1", "r")
            await db.execute_query(
                "UPDATE memory_hot SET access_count = 1 WHERE memory_id = $1", ("m",))
            await db.execute_query("INSERT INTO unified.task_queue (id) VALUES ($1)", ("q",))
            await db.execute_query("SELECT * FROM unified.beliefs")
    '''))
    found = _scanner().memory_writes(str(module), "writer.py")
    assert {table for _file, _line, table in found} == {
        "unified.beliefs", "{table}", "memory_hot.memory_hot"}, found


def test_every_hand_off_says_where_it_came_from():
    unsaid = _scanner().hand_offs_that_say_no_origin()
    assert unsaid == [], "memory handed over without an origin, or naming its owner:\n" + "\n".join(
        f"  {f}:{line} {call} {what}" for f, line, call, what in unsaid)


def test_a_hand_off_that_says_nothing_is_found(tmp_path):
    module = tmp_path / "handoff.py"
    module.write_text(textwrap.dedent('''
        async def hand_over(agent, person):
            await agent.store_memory(content="a")
            await agent.store_memory(content="b", user_id=person)
            agent.enqueue_memory("c", origin=None)
    '''))
    found = _scanner().hand_offs_without_origin(str(module), "handoff.py")
    assert [(line, what) for _f, line, _call, what in found] == [
        (3, "says no origin"), (4, "names an owner (user_id)"), (4, "says no origin")], found


def test_a_perception_that_does_not_say_whose_it_is_is_found(tmp_path):
    module = tmp_path / "perceiving.py"
    module.write_text(textwrap.dedent('''
        async def perceive(coord, hub, origin):
            await coord.see("/a.png", source="upload")
            await coord.see("/b.png", actor_identity=None, source="environment")
            await hub.process_input("s", "image", {})
            await hub.process_input("s", "image", {}, origin=origin)
            hub.note_perception("s", "recognition", {})
    '''))
    found = _scanner().hand_offs_without_origin(str(module), "perceiving.py")
    assert sorted((line, call) for _f, line, call, _what in found) == [
        (3, "see"), (5, "process_input"), (7, "note_perception")], found


def test_whose_memory_follows_where_it_came_from():
    from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
    from core.agents.memory_agent import MemoryAgent
    from core.memory import Origin
    assert MemoryAgent._owner_from(Origin.of("alice", "conversation")) == "alice"
    assert MemoryAgent._owner_from(Origin.of(SUBSTRATE_ACTOR, "task")) is None
    assert MemoryAgent._owner_from(Origin.own("teaching")) is None


def test_a_hand_off_with_no_origin_is_refused():
    import asyncio

    import pytest
    from core.agents.memory_agent import MemoryAgent
    agent = MemoryAgent()
    with pytest.raises(TypeError):
        asyncio.run(agent.store_memory(content="nobody said where this came from"))
    with pytest.raises(TypeError):
        asyncio.run(agent.store_memory(content="an owner is not an origin", origin="alice"))
    with pytest.raises(TypeError):
        agent.enqueue_memory("an owner named in a queued write", origin=None, user_id="alice")


def test_an_origin_names_what_it_came_through():
    import pytest
    from core.memory import Origin
    with pytest.raises(ValueError):
        Origin(through=" ", person=None)
