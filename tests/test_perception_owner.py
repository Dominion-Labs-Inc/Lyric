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
    import core.agents.autonomous.perception_manager as hub_module
    from core.agents.autonomous.shared_types import PerceptionData
    from core.agents.memory_agent import MemoryAgent

    class Hub:
        async def get_recent_perceptions(self, limit=10):
            return [PerceptionData("theirs.png", "image", {"detections": ["alice's"]},
                                   origin=Origin.of("alice", "see")),
                    PerceptionData("other.png", "image", {"detections": ["bob's"]},
                                   origin=Origin.of("bob", "see")),
                    PerceptionData("room.png", "image", {"detections": ["its own"]}, origin=Origin.own("see")),
                    PerceptionData("unsaid.png", "image", {}, origin=None)]

    monkeypatch.setattr(hub_module, "get_perception_manager", lambda: Hub())
    agent = MemoryAgent()
    alice = asyncio.run(agent._perceptual_state("alice"))
    own = asyncio.run(agent._perceptual_state(None))
    assert [(p["source"], p["owner"]) for p in alice["perceptions"]] == [("theirs.png", "alice")]
    assert [(p["source"], p["owner"]) for p in own["perceptions"]] == [("room.png", None)]
    assert asyncio.run(agent._perceptual_state("carol")) is None


def test_what_a_persons_image_shows_goes_to_their_context_and_never_the_shared_graph(monkeypatch):
    import core.domain.concept_ingestion as ingestion_module
    import core.domain.evidence_producers as producers
    import core.learning.unified_learning_system as learning_module

    ingested, held = [], []

    class SharedGraph:
        async def _ready(self):
            pass

        async def ingest(self, envelope):
            ingested.append(envelope)
            return SimpleNamespace(admitted_relations=[])

    class Router:
        async def learn_fact(self, subject, relation, obj, **given):
            held.append((subject, relation, obj, given["actor"], given["provenance"].source_type))
            return SimpleNamespace(admitted=True)

        async def fan_out_ingested(self, result, **given):
            pass

    # The producers import the service where they use it, so it is replaced at its source.
    monkeypatch.setattr(ingestion_module, "get_concept_ingestion_service", lambda: SharedGraph())
    monkeypatch.setattr(learning_module, "get_unified_learning_system", lambda: Router())
    content = {"subject": "image_ab12", "detections": ["zqmarker"], "properties": {"has_format": "png"},
               "blobs": [{"name": "image_ab12_blob_1", "isa": ["circle", "vivid_red"]}]}

    asyncio.run(producers.submit_image("upload", content, memory_id="mem_1", origin=Origin.of("alice", "see")))
    assert not ingested, "a person's image reached the shared graph"
    assert {(actor, kind) for *_edge, actor, kind in held} == {("alice", "PERCEPTION")}
    assert ("image_ab12", "observed", "zqmarker", "alice", "PERCEPTION") in held
    assert ("image_ab12_blob_1", "isa", "circle", "alice", "PERCEPTION") in held

    held.clear()
    asyncio.run(producers.submit_image("environment", content, memory_id="mem_2", origin=Origin.own("see")))
    assert len(ingested) == 1 and not held, "the substrate's own seeing takes the one write path, as before"


def test_two_people_showing_the_same_picture_do_not_put_it_in_the_shared_mind():
    async def run():
        from core.database import get_database_manager
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import get_unified_learning_system
        from core.semantics.cognitive_ingress import Provenance
        db = get_database_manager()
        await db.initialize()
        where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        assert where["d"] == "lyric_dev", where
        token = "zpercept" + "".join(random.choice(string.ascii_lowercase) for _ in range(8))
        actors = [f"{token}-a", f"{token}-b"]
        seen = Provenance(producer="upload", source_id="upload:image", source_type="PERCEPTION")
        learning = get_unified_learning_system()
        try:
            admitted = [(await learning.learn_fact(f"{token}_image", "observed", f"{token}_mark", provenance=seen,
                                                   domain="vision", quality=0.9, actor=actor)).admitted
                        for actor in actors]
            shared = await db.execute_query(
                "SELECT count(*) AS n FROM unified.concepts WHERE name LIKE $1", (f"%{token}%",), fetch_one=True)
            promoted = await get_scoped_context_store().is_promoted(f"{token}_image observed {token}_mark")
            return admitted, int(shared["n"]), promoted
        finally:
            for table in ("scoped_concept_relations", "scoped_beliefs"):
                await db.execute_query(f"DELETE FROM unified.{table} WHERE scope_actor = ANY($1::text[])",
                                       (actors,), commit=True)

    admitted, shared, promoted = asyncio.run(run())
    assert admitted == [True, True], "each person holds what their picture showed"
    assert shared == 0 and not promoted, "a perception is not a telling that another person corroborates"
