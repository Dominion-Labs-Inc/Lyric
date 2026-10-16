"""A perception is whoever's it is: a person's image stays in their context, the substrate's own seeing is its own.

The last test runs against the database it is pointed at (the sandbox, `POSTGRES_DATABASE=lyric_dev`) and
removes the rows it writes.
"""
import asyncio
import random
import string
from types import SimpleNamespace

from core.memory import Origin


def test_a_memory_is_stamped_only_with_what_its_own_owner_was_perceiving(monkeypatch):
    import core.perception.perception_faculty as faculty_module
    from core.agents.autonomous.shared_types import PerceptionData
    from core.agents.memory_agent import MemoryAgent

    class Faculty:
        def recent_percepts(self, limit=10):
            return [PerceptionData("theirs.png", "image", {"detections": ["alice's"]},
                                   origin=Origin.of("alice", "see")),
                    PerceptionData("other.png", "image", {"detections": ["bob's"]},
                                   origin=Origin.of("bob", "see")),
                    PerceptionData("room.png", "image", {"detections": ["its own"]}, origin=Origin.own("see")),
                    PerceptionData("unsaid.png", "image", {}, origin=None)]

    monkeypatch.setattr(faculty_module, "get_perception_faculty", lambda: Faculty())
    agent = MemoryAgent()
    alice = asyncio.run(agent._perceptual_state("alice"))
    own = asyncio.run(agent._perceptual_state(None))
    assert [(p["source"], p["owner"]) for p in alice["perceptions"]] == [("theirs.png", "alice")]
    assert [(p["source"], p["owner"]) for p in own["perceptions"]] == [("room.png", None)]
    assert asyncio.run(agent._perceptual_state("carol")) is None


def test_a_perception_a_memory_holds_is_pointed_to_never_copied(monkeypatch):
    """A document read is remembered once, by the memory of reading it; a memory forming near it names that memory
    and the digest. Every memory in the window used to carry the whole text again."""
    import core.perception.perception_faculty as faculty_module
    from core.agents.autonomous.shared_types import PerceptionData
    from core.agents.memory_agent import MemoryAgent

    read = PerceptionData("config_status", "document", {"text": ["x" * 100_000]}, origin=Origin.own("see"))
    read.metadata.update(memory_id="mem_read", digest="sha_of_the_bytes")
    recognised = PerceptionData("front_door", "recognition", {"claim": "front_door isa door"},
                                origin=Origin.own("see"))

    class Faculty:
        def recent_percepts(self, limit=10):
            return [read, recognised]

    monkeypatch.setattr(faculty_module, "get_perception_faculty", lambda: Faculty())
    seen = asyncio.run(MemoryAgent()._perceptual_state(None))["perceptions"]
    assert seen[0]["memory_id"] == "mem_read" and seen[0]["digest"] == "sha_of_the_bytes"
    assert "content" not in seen[0], "the text is the memory of reading it's, not every nearby memory's"
    assert seen[1]["content"] == {"claim": "front_door isa door"} and "memory_id" not in seen[1]


def test_what_a_persons_image_shows_goes_to_their_context_and_never_the_shared_graph(monkeypatch):
    import core.domain.concept_ingestion as ingestion_module
    import core.learning.unified_learning_system as learning_module
    import core.memory as memory_module
    import core.domain.evidence_producers as producers

    ingested, held = [], []

    class SharedGraph:
        async def _ready(self):
            pass

        async def ingest(self, envelope):
            ingested.append(envelope)
            return SimpleNamespace(admitted_relations=[])

    class Door:
        async def consider_envelope(self, service, envelope, **given):
            return await service.ingest(envelope)

    class Memory:
        async def hold_for_person(self, actor, subject, relation, obj, **given):
            held.append((subject, relation, obj, actor))
            return SimpleNamespace(admitted=True)

        async def store_memory(self, **given):
            return True, "mem"

    async def memory():
        return Memory()

    # The producers import the service, the door and memory where they use them, so each is replaced at its source.
    monkeypatch.setattr(ingestion_module, "get_concept_ingestion_service", lambda: SharedGraph())
    monkeypatch.setattr(learning_module, "get_unified_learning_system", lambda: Door())
    monkeypatch.setattr(memory_module, "get_memory_agent", memory)
    content = {"subject": "image_ab12", "detections": ["zqmarker"], "properties": {"has_format": "png"},
               "blobs": [{"name": "image_ab12_blob_1", "isa": ["circle", "vivid_red"]}]}

    asyncio.run(producers.submit_image("upload", content, memory_id="mem_1", origin=Origin.of("alice", "see")))
    assert not ingested, "a person's image reached the shared graph"
    assert {actor for *_edge, actor in held} == {"alice"}
    assert ("image_ab12", "observed", "zqmarker", "alice") in held
    assert ("image_ab12_blob_1", "isa", "circle", "alice") in held

    held.clear()
    asyncio.run(producers.submit_image("environment", content, memory_id="mem_2", origin=Origin.own("see")))
    assert len(ingested) == 1 and not held, "the substrate's own seeing takes the one door, as before"


def test_two_people_showing_the_same_picture_do_not_put_it_in_the_shared_mind():
    """What each person's picture showed is theirs (`MemoryAgent.hold_for_person`): two people showing the same one
    each hold it, and the world holds nothing of it -- a perception is not a telling, and a count of people is no
    evidence that it is true (docs/research/SEPARATION_MAP.md §11.4)."""
    async def run():
        from core.agents.memory_agent import memory_agent
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        assert where["d"] == "lyric_dev", where
        token = "zpercept" + "".join(random.choice(string.ascii_lowercase) for _ in range(8))
        actors = [f"{token}-a", f"{token}-b"]
        try:
            admitted = [(await memory_agent().hold_for_person(
                actor, f"{token}_image", "observed", f"{token}_mark", positive=True, quality=0.9,
                domain="vision", surface=f"{token}_image observed {token}_mark", source="upload")).admitted
                for actor in actors]
            shared = await db.execute_query(
                "SELECT count(*) AS n FROM unified.concepts WHERE name LIKE $1", (f"%{token}%",), fetch_one=True)
            return admitted, int(shared["n"])
        finally:
            for table in ("scoped_concept_relations", "scoped_beliefs"):
                await db.execute_query(f"DELETE FROM unified.{table} WHERE scope_actor = ANY($1::text[])",
                                       (actors,), commit=True)

    admitted, shared = asyncio.run(run())
    assert admitted == [True, True], "each person holds what their picture showed"
    assert shared == 0, "the world holds nothing of it"