"""The pool: experiences handed to the memory agent whole, waiting as candidates in their owner's store.

Runs against the database it is pointed at (the sandbox, `POSTGRES_DATABASE=torinai_dev`); every row it writes is
removed by id.
"""
import asyncio
from types import SimpleNamespace

import pytest

from core.memory import Experience, Origin, Part


def test_an_experience_says_whose_work_it_was_and_where_each_part_came_from():
    with pytest.raises(TypeError):
        Experience(kind="task", origin="alice", parts=(), evidence={})
    with pytest.raises(ValueError):
        Part("step", "read the note", "somewhere")
    with pytest.raises(ValueError):
        Part(" ", "read the note", "substrate")


def test_whose_work_it_is_says_where_its_ends_and_its_material_came_from():
    theirs, own = Origin.of("alice", "task"), Origin.own("task")
    assert (theirs.theirs, theirs.material) == ("person", "person")
    assert (own.theirs, own.material) == ("substrate", "world")


def test_the_same_experience_has_one_fingerprint_whoever_it_was_for():
    steps = (Part("step", {"tool": "read_file"}, "substrate"), Part("error", "not found", "world"))
    alice = Experience("task", Origin.of("alice", "task"),
                       steps + (Part("request", "read my note", "person"),), {"outcome": "failure"})
    bob = Experience("task", Origin.of("bob", "task"),
                     steps + (Part("request", "read the report", "person"),), {"outcome": "failure"})
    other = Experience("task", Origin.of("bob", "task"),
                       (Part("step", {"tool": "write_file"}, "substrate"),), {"outcome": "success"})
    assert alice.fingerprint() == bob.fingerprint()
    assert alice.fingerprint() != other.fingerprint()


def test_a_finished_task_is_an_experience_with_each_part_where_it_came_from():
    from core.agents.memory_agent import MemoryAgent
    agent = MemoryAgent()
    verdict = {"success": True, "outcome_class": "success", "read_from": "completion belief"}
    task = SimpleNamespace(
        id="t1", actor="alice", description="Read my note about the pump.",
        type=SimpleNamespace(value="analysis"),
        metadata={"parameters": {"tool_plan": [{"tool": "read_file", "args": {"file_path": "/a/note.txt"}}]},
                  "failure_history": [{"attempt": 0, "error": "no such file"}],
                  "retry_method_structured": {"file_path": "/a/notes.txt"},
                  "completion_evidence": [{"channel": "file_read", "strength": 0.8}],
                  "operating_verdict": verdict})
    result = {"success": True, "verification_state": "verified",
              "tools_run": [{"tool": "read_file", "success": True, "output": {"content": "the pump leaks"}}]}
    experience = agent.task_experience(task, result=result, success=True)
    assert experience.origin == Origin.of("alice", "task") and experience.about == "t1"
    sources = [(p.role, p.source) for p in experience.parts]
    assert sources == [("request", "person"), ("step", "substrate"), ("tool_run", "substrate"),
                       ("tool_output", "person"), ("error", "world"), ("fix", "substrate"),
                       ("check", "world"), ("result", "person")], sources
    assert experience.evidence["outcome"] == "success" and experience.evidence["checks"] == 1
    assert experience.evidence["verdict"] == verdict
    assert experience.to_dict()["parts"][2] == {"role": "tool_run", "source": "substrate",
                                                "content": {"tool": "read_file", "success": True}}


class _Handed:
    """Stands in for the memory agent, keeping what it is handed."""

    def __init__(self):
        self.experiences, self.memories = [], []

    async def remember_experience(self, experience):
        self.experiences.append(experience)
        return "exp_test"

    def enqueue_memory(self, *args, **kwargs):
        self.memories.append(kwargs)


def _conversation(handed):
    """A person's conversation whose hand-overs are kept here, not sent."""
    from core.agents.autonomous.autonomous_coordinator import Conversation
    conversation = Conversation(session="pool-test", actor_identity="alice")

    async def hand_over(origin, kind, parts, evidence):
        handed.append((origin, kind, list(parts), evidence))
    conversation._hand_over = hand_over
    return conversation


def test_a_turn_is_handed_over_with_each_part_where_it_came_from():
    from core.agents.autonomous.autonomous_coordinator import Acquired, Answer, Understanding
    handed = []
    conversation = _conversation(handed)
    told = Understanding(sentence="A zq is a robin.", asked=False, reply="Noted.",
                         acquired=[Acquired("zq", relations=(("isa", "robin"),), stored=True)])
    asked = Understanding(sentence="Is a zq an animal?", asked=True, reply="Yes.",
                          answers=[Answer(about="zq", relation="is", others=("animal",), verdict=True,
                                          support=("zq → robin → animal",), conclusion="zq is animal")])
    asyncio.run(conversation._hand_over_turn(told, {"placed": [["zq", "context"]]}, "held"))
    asyncio.run(conversation._hand_over_turn(asked, {"answered_by": ["reasoned"]}, "answered"))
    (origin, kind, parts, evidence), (_, _, asked_parts, _) = handed
    assert kind == "conversation" and origin == Origin.of("alice", "conversation")
    assert [(p.role, p.source) for p in parts] == [
        ("said", "person"), ("told", "person"), ("route", "substrate"), ("reply", "person")]
    assert [(p.role, p.source) for p in asked_parts] == [
        ("said", "person"), ("route", "substrate"), ("answer", "person"), ("reply", "person")]
    assert evidence == {"outcome": "held", "asked": False}


def test_a_look_up_is_handed_over_with_each_part_where_it_came_from(monkeypatch):
    import core.tools
    from core.agents.autonomous.autonomous_coordinator import Acquired
    from core.semantics.sentence_reader import SentenceReader

    answers = {
        "web_search": SimpleNamespace(success=True, output={"results": [
            {"title": "Pumps of the world", "url": "https://a.example", "content": "Pumps move fluids."},
            {"title": "Peristaltic pump", "url": "https://b.example", "snippet": "2024 — tube pumps"}]}),
        "web_fetch": SimpleNamespace(success=True, output={
            "text": "A peristaltic pump is a positive displacement pump."})}

    class World:
        async def execute_tool(self, name, params):
            return answers[name]

    def read_all(self, text):
        if text.startswith("A peristaltic pump is"):
            return [{"subject": "peristaltic pump", "relation": "is", "obj": "a positive displacement pump"}]
        return []

    monkeypatch.setattr(core.tools, "get_tool_registry", lambda: World())
    monkeypatch.setattr(SentenceReader, "read_all", read_all)
    handed = []
    conversation = _conversation(handed)

    async def ingest(**given):
        return Acquired(given["label"], stored=True)
    conversation._ingest = ingest

    assert asyncio.run(conversation._research_phrase("peristaltic pump")).stored
    origin, kind, parts, evidence = handed[0]
    assert kind == "research" and origin == Origin.of("alice", "research")
    assert [(p.role, p.source) for p in parts] == [
        ("asked", "person"), ("query", "substrate"), ("source", "world"), ("read", "substrate"),
        ("source", "world"), ("finding", "world")]
    assert parts[-1].content["object"] == "positive displacement pump"
    assert evidence == {"outcome": "found", "sources": 2, "pages_read": 1, "admitted": True}

    class Unreachable:
        async def execute_tool(self, name, params):
            raise ConnectionError("no route to the web")

    monkeypatch.setattr(core.tools, "get_tool_registry", lambda: Unreachable())
    asyncio.run(conversation._research_phrase("peristaltic pump"))
    _origin, _kind, parts, evidence = handed[1]
    assert [(p.role, p.source) for p in parts] == [("asked", "person"), ("query", "substrate"), ("error", "world")]
    assert evidence["outcome"] == "failed"


def test_a_reasoning_is_handed_over_with_each_premise_where_it_came_from():
    from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
    from core.reasoning.abstract_reasoning_engine import ReasoningPremise
    from core.reasoning.neural_bridge import NeuralSymbolicBridge, ReasoningRequest, ReasoningResult
    bridge = NeuralSymbolicBridge()
    bridge.memory_agent = handed = _Handed()
    premises = [ReasoningPremise("p0", "zq isa robin", provenance_kind="context"),
                ReasoningPremise("p1", "robin isa bird", provenance="c1", provenance_kind="concept"),
                ReasoningPremise("p2", "an earlier claim", provenance="m1", provenance_kind="memory"),
                "a caller's own sentence"]
    theirs = ReasoningRequest(query="zq is animal", context=premises, task_metadata={"actor": "alice"})
    proved = ReasoningResult(answer="Yes: zq is an animal", confidence=0.9,
                             reasoning_steps=["zq isa robin", "robin isa bird", "bird isa animal"],
                             metadata={"verified": True, "reason": "substrate_verified"})
    asyncio.run(bridge._capture_reasoning_memory(theirs, proved))
    experience = handed.experiences[0]
    assert experience.kind == "reasoning" and experience.origin == Origin.of("alice", "reasoning")
    assert [(p.role, p.source) for p in experience.parts] == [
        ("question", "person"), ("premise", "person"), ("premise", "substrate"), ("premise", "person"),
        ("premise", "person"), ("step", "substrate"), ("step", "substrate"), ("step", "substrate"),
        ("answer", "person")]
    assert experience.evidence["outcome"] == "substrate_verified"

    refused = ReasoningResult(answer="", confidence=0.0, metadata={"reason": "not_formalizable"})
    asyncio.run(bridge._capture_reasoning_memory(theirs, refused))
    assert handed.experiences[1].evidence["outcome"] == "not_formalizable"
    assert not any(p.role == "answer" for p in handed.experiences[1].parts)
    assert len(handed.memories) == 1, "a refusal is an experience, never a memory"

    own = ReasoningRequest(query="robin is animal", context=["robin isa bird"],
                           task_metadata={"actor": SUBSTRATE_ACTOR})
    asyncio.run(bridge._capture_reasoning_memory(own, proved))
    assert handed.experiences[2].origin == Origin.own("reasoning")
    assert all(p.source == "substrate" for p in handed.experiences[2].parts)


def test_the_worker_decides_what_waits_and_says_why():
    async def run():
        from core.agents.memory_agent import MemoryAgent
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        agent = MemoryAgent()
        shared = (Part("step", {"tool": "pool_test_tool"}, "substrate"), Part("check", "seen", "world"))
        ids = []
        try:
            ids.append(await agent.remember_experience(Experience(
                "task", Origin.of("pool-test-person", "task"),
                shared + (Part("request", "a person's request", "person"),), {"outcome": "success"})))
            await agent._decide_waiting()
            ids.append(await agent.remember_experience(Experience(
                "task", Origin.of("pool-test-person", "task"),
                shared + (Part("request", "the same, again", "person"),), {"outcome": "success"})))
            ids.append(await agent.remember_experience(Experience(
                "conversation", Origin.of("pool-test-person", "conversation"),
                (Part("said", "only their words", "person"),), {"outcome": "answered"})))
            ids.append(await agent.remember_experience(Experience(
                "task", Origin.own("task"), (Part("step", {"tool": "pool_test_other"}, "substrate"),),
                {"outcome": "success"})))
            await agent._decide_waiting()
            rows = await db.execute_query(
                "SELECT item_id, owner, status, seen, decision FROM unified.experience_pool"
                " WHERE item_id = ANY($1::text[])", (ids,), fetch_all=True, store=None)
            import json
            got = {r["item_id"]: (r["owner"], r["status"], r["seen"],
                                  (r["decision"] if isinstance(r["decision"], dict)
                                   else json.loads(r["decision"])).get("standing")) for r in rows}
            return ids, got
        finally:
            await db.execute_query("DELETE FROM unified.experience_pool WHERE item_id = ANY($1::text[])",
                                   (ids,), commit=True, store=None)

    ids, got = asyncio.run(run())
    first, again, words, own = ids
    assert got[first] == ("pool-test-person", "decided", 2, "candidate"), got[first]
    assert got[again] == ("pool-test-person", "decided", 1, "already held"), got[again]
    assert got[words][3] == "nothing to learn", got[words]
    assert got[own][0] is None and got[own][3] == "candidate", got[own]


def test_a_memory_waits_in_the_pool_as_itself_and_is_decided_from_its_record(monkeypatch):
    """A task's memory keeps the whole experience in its record, and the pool queues that memory: it holds no
    second copy of the parts, and decides the item from the memory's record. A queued memory that is gone
    leaves nothing to learn."""
    from uuid import uuid4
    nonce = uuid4().hex[:8]
    # Storing a memory starts the memory agent, and with it the pool's own worker, which would claim these
    # items before this test decides them. Shadow mode keeps the background loops off.
    monkeypatch.setenv("TORIN_SHADOW_MODE", "1")

    async def run():
        from core.agents.memory_agent import MemoryAgent
        from core.database import get_database_manager
        from core.memory.utils.interfaces import MemoryType
        db = get_database_manager()
        await db.initialize()
        agent = MemoryAgent()
        experience = Experience(
            "task", Origin.own("task"),
            (Part("step", {"tool": f"pool_memory_test_{nonce}"}, "substrate"), Part("check", "seen", "world")),
            {"outcome": "success"}, about=f"pool-memory-test-{nonce}")
        ids, memory_id = [], None
        try:
            stored, memory_id = await agent.store_memory(
                f"I was asked to test the pool ({nonce}). I did it.", memory_type=MemoryType.META,
                tags=["task_outcome", "pool_memory_test"],
                thinking_state={"raw_event": {"event": "task_outcome", "experience": experience.to_dict()}},
                origin=Origin.own("task"))
            assert stored and memory_id
            ids.append(await agent.remember_experience(experience, memory_id=memory_id))
            ids.append(await agent.remember_experience(experience, memory_id=f"mem_never_stored_{nonce}"))
            await agent._decide_waiting()
            rows = await db.execute_query(
                "SELECT item_id, parts, memory_id, decision FROM unified.experience_pool"
                " WHERE item_id = ANY($1::text[])", (ids,), fetch_all=True, store=None)
            return ids, memory_id, {r["item_id"]: dict(r) for r in rows}
        finally:
            await db.execute_query("DELETE FROM unified.experience_pool WHERE item_id = ANY($1::text[])",
                                   (ids,), commit=True, store=None)
            if memory_id:
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (memory_id,), commit=True, store=None)

    import json
    ids, memory_id, got = asyncio.run(run())
    kept, gone = got[ids[0]], got[ids[1]]

    def decision(row):
        return row["decision"] if isinstance(row["decision"], dict) else json.loads(row["decision"])

    assert kept["parts"] is None and kept["memory_id"] == memory_id, kept
    assert decision(kept)["standing"] == "candidate", decision(kept)
    assert decision(kept)["parts"] == {"substrate": 1, "world": 1, "person": 0}, decision(kept)
    assert decision(gone)["standing"] == "nothing to learn" and "gone" in decision(gone)["why"], decision(gone)
