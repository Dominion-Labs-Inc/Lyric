"""What reasoning writes down is whoever's reasoning it was: a person's arguments, temporal knowledge, hypotheses
and failed work stay in their context; the substrate keeps and reads back only its own.

Runs against the database it is pointed at (the sandbox, `POSTGRES_DATABASE=torinai_dev`) and removes the rows it
writes.
"""
import asyncio
import random
import string
from types import SimpleNamespace


def _token(prefix):
    return prefix + "".join(random.choice(string.ascii_lowercase) for _ in range(8))


async def _db():
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    assert where["d"] == "torinai_dev", where
    return db


async def _owners(db, table, column, token):
    rows = await db.execute_query(
        f"SELECT owner FROM unified.{table} WHERE {column}::text LIKE $1", (f"%{token}%",), fetch_all=True) or []
    return sorted(str(r["owner"]) for r in rows)


def test_a_persons_argument_is_kept_as_theirs_and_let_go_by_the_shared_engine():
    async def run():
        from core.reasoning.formal_argumentation import ArgumentType, FormalArgumentationSystem
        db = await _db()
        theirs, own = _token("zargp"), _token("zargs")
        engine = FormalArgumentationSystem()
        try:
            for owner, token in (("alice", theirs), (None, own)):
                claim = engine.create_claim(statement=f"{token} is a pump", owner=owner)
                engine.create_argument(claim, premises=[f"{token} moves water"],
                                       argument_type=ArgumentType.DEDUCTIVE)
            await engine.persist()
            kept = (await _owners(db, "reasoning_arg_claims", "statement", theirs),
                    await _owners(db, "reasoning_arg_claims", "statement", own),
                    await _owners(db, "reasoning_arguments", "conclusion", theirs))
            in_working_set = sorted(c.statement for c in engine.claims.values()
                                    if theirs in c.statement or own in c.statement)
            fresh = FormalArgumentationSystem()
            await fresh.load()
            loaded = sorted(c.statement for c in fresh.claims.values()
                            if theirs in c.statement or own in c.statement)
            return kept, in_working_set, loaded
        finally:
            for table, column in (("reasoning_arg_claims", "statement"), ("reasoning_arguments", "conclusion")):
                await db.execute_query(f"DELETE FROM unified.{table} WHERE {column} LIKE ANY($1::text[])",
                                       ([f"%{theirs}%", f"%{own}%"],), commit=True, store="model")

    (claims_theirs, claims_own, arguments_theirs), in_working_set, loaded = asyncio.run(run())
    assert claims_theirs == ["alice"] and arguments_theirs == ["alice"], (claims_theirs, arguments_theirs)
    assert claims_own == ["None"], claims_own
    assert all("zargs" in s for s in in_working_set), "a person's claim stayed in the shared engine"
    assert loaded and all("zargs" in s for s in loaded), "the substrate read back someone else's claim"


def test_temporal_knowledge_is_whoever_s_reasoning_made_it():
    async def run():
        from core.reasoning.temporal_reasoning import TemporalReasoningSystem, TimePoint
        db = await _db()
        theirs, own = _token("ztmpp"), _token("ztmps")
        engine = TemporalReasoningSystem()
        try:
            for owner, token in (("alice", theirs), (None, own)):
                cause = engine.create_proposition(f"{token} leak", TimePoint.PAST, owner=owner)
                effect = engine.create_proposition(f"{token} pressure drop", TimePoint.PRESENT, owner=owner)
                engine.establish_causal_link(cause, effect, strength=0.9)
            await engine.persist()
            kept = (await _owners(db, "reasoning_temporal_propositions", "statement", theirs),
                    await _owners(db, "reasoning_temporal_propositions", "statement", own))
            links = sorted(str(link.owner) for link in engine.causal_links.values())
            left = sorted(p.statement for p in engine.propositions.values()
                          if theirs in p.statement or own in p.statement)
            return kept, links, left
        finally:
            ids = await db.execute_query(
                "SELECT prop_id FROM unified.reasoning_temporal_propositions WHERE statement LIKE ANY($1::text[])",
                ([f"%{theirs}%", f"%{own}%"],), fetch_all=True, store="model") or []
            ids = [r["prop_id"] for r in ids]
            await db.execute_query("DELETE FROM unified.reasoning_temporal_causal_links WHERE cause_id = ANY($1::text[])",
                                   (ids,), commit=True, store="model")
            await db.execute_query("DELETE FROM unified.reasoning_temporal_propositions WHERE prop_id = ANY($1::text[])",
                                   (ids,), commit=True, store="model")

    (props_theirs, props_own), links, left = asyncio.run(run())
    assert props_theirs == ["alice", "alice"] and props_own == ["None", "None"], (props_theirs, props_own)
    assert all("ztmps" in s for s in left), "a person's proposition stayed in the shared engine"
    assert "alice" not in links, "a person's causal link stayed in the shared engine"


def test_a_persons_hypothesis_is_theirs_and_not_the_substrates_own_work():
    async def run():
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.reasoning.hypothesis_testing import HypothesisTestingSystem
        db = await _db()
        token = _token("zhyp")
        system = HypothesisTestingSystem()
        assert await system.initialize()
        try:
            hypothesis = await system.generate_hypothesis(
                claim=f"the {token} valve is stuck", domain="plumbing", owner="alice")
            kept = await _owners(db, "hypotheses", "claim", token)
            believed = await get_scoped_context_store().belief("alice", f"the {token} valve is stuck")
            return hypothesis.owner, kept, believed
        finally:
            await db.execute_query("DELETE FROM unified.hypotheses WHERE claim LIKE $1", (f"%{token}%",),
                                   commit=True, store="model")
            await db.execute_query("DELETE FROM unified.scoped_beliefs WHERE scope_actor = 'alice' AND claim LIKE $1",
                                   (f"%{token}%",), commit=True)

    owner, kept, believed = asyncio.run(run())
    assert owner == "alice" and kept == ["alice"], (owner, kept)
    assert believed is not None, "a person's hypothesis is believed in their context"


def test_the_substrate_does_not_take_up_a_persons_stalled_hypothesis(monkeypatch):
    from datetime import datetime, timedelta
    from core.reasoning.epistemic_engine import EpistemicEngine
    from core.reasoning.hypothesis_testing import HypothesisStatus

    old = datetime.now() - timedelta(days=30)
    stalled = [SimpleNamespace(hypothesis_id=h, claim=c, domain="general", owner=o,
                               status=HypothesisStatus.PROPOSED, proposed_at=old,
                               supporting_evidence=[], contradicting_evidence=[], confidence=0.5)
               for h, c, o in (("h_theirs", "their claim", "alice"), ("h_own", "its own claim", None))]
    engine = EpistemicEngine.__new__(EpistemicEngine)
    monkeypatch.setattr(engine, "_hypothesis_sys", lambda: SimpleNamespace(
        hypotheses={h.hypothesis_id: h for h in stalled}), raising=False)
    monkeypatch.setattr(engine, "_hyp_entropy", lambda hyp: 0.9, raising=False)
    monkeypatch.setattr(engine, "_uncertainty", lambda: None, raising=False)
    targets = [t for t in engine.get_unstable_regions() if t.target_type == "hypothesis"]
    assert [t.target_id for t in targets] == ["h_own"], [t.target_id for t in targets]


def test_a_persons_failed_work_is_recorded_as_theirs_and_not_read_back():
    async def run():
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
        db = await _db()
        coord = AutonomousCoordinator.__new__(AutonomousCoordinator)
        theirs, own = _token("fpp"), _token("fps")
        try:
            await coord._record_failed_fingerprint(theirs, SimpleNamespace(
                id="t1", actor="alice", description="read my private note"))
            await coord._record_failed_fingerprint(own, SimpleNamespace(
                id="t2", actor=None, description="explore the workspace"))
            kept = {r["fingerprint"]: r["owner"] for r in await db.execute_query(
                "SELECT fingerprint, owner FROM unified.failed_task_fingerprints WHERE fingerprint = ANY($1::text[])",
                ([theirs, own],), fetch_all=True, store="runtime") or []}
            await coord._load_failed_fingerprints()
            return kept, theirs, own, set(coord._permanently_failed_fps)
        finally:
            await db.execute_query("DELETE FROM unified.failed_task_fingerprints WHERE fingerprint = ANY($1::text[])",
                                   ([theirs, own],), commit=True, store="runtime")

    kept, theirs, own, loaded = asyncio.run(run())
    assert kept == {theirs: "alice", own: None}, kept
    assert own in loaded and theirs not in loaded
