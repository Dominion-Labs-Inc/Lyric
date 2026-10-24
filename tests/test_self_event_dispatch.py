#!/usr/bin/env python3
"""Unit tests for the coordinator's self-event dispatch (Phase 0a).

Exercises the event core in isolation — a bare coordinator with only the
reaction state set — so the dispatch semantics are proven without booting the
whole system: sync ordering, reaction isolation, the reactive drain worker,
the one-owner guard, and the reentrancy depth demotion.
"""
import asyncio
from collections import deque

import pytest

from core.agents.autonomous.autonomous_coordinator import (
    AutonomousCoordinator, CompetenceChanged, SelfEvent, SelfEventType, TaskCompleted,
)


def _bare_coord() -> AutonomousCoordinator:
    """A coordinator with just the reaction state — no subsystem wiring."""
    c = AutonomousCoordinator.__new__(AutonomousCoordinator)
    c._reactions = {}
    c._reactive_queue = deque()
    c._work_ready = asyncio.Event()
    c._reactive_worker = None
    c._emit_depth = 0
    c._max_emit_depth = 8
    c.active = True
    c.worker = False
    return c


def _completed(task_id: str = "t") -> SelfEvent:
    """A TASK_COMPLETED event with the payload that event kind declares."""
    return SelfEvent(SelfEventType.TASK_COMPLETED, TaskCompleted(
        task=None, task_id=task_id, result=None, is_complete=True, confidence=1.0))


@pytest.mark.asyncio
async def test_sync_reactions_run_in_priority_order():
    c = _bare_coord()
    order = []

    async def hi(e):
        order.append("high")

    async def lo(e):
        order.append("low")

    # register low first, then high — priority (not registration order) decides
    c.on(SelfEventType.TASK_COMPLETED, lo, name="low", mode="sync", priority=1)
    c.on(SelfEventType.TASK_COMPLETED, hi, name="high", mode="sync", priority=90)
    await c.emit(_completed())
    assert order == ["high", "low"], order


@pytest.mark.asyncio
async def test_failing_reaction_is_isolated():
    c = _bare_coord()
    ran = []

    async def boom(e):
        raise RuntimeError("intended")

    async def ok(e):
        ran.append("ok")

    c.on(SelfEventType.TASK_COMPLETED, boom, name="boom", mode="sync", priority=90)
    c.on(SelfEventType.TASK_COMPLETED, ok, name="ok", mode="sync", priority=1)
    # emit must not raise; the good reaction must still run
    await c.emit(_completed())
    assert ran == ["ok"], ran


@pytest.mark.asyncio
async def test_deferred_reaction_drains_when_woken():
    c = _bare_coord()
    drained = []

    async def slow(e):
        drained.append(e.payload.task_id)

    c.on(SelfEventType.TASK_COMPLETED, slow, name="slow", mode="deferred")
    worker = asyncio.create_task(c._reactive_drain_worker())
    try:
        await c.emit(_completed("1"))
        await c.emit(_completed("2"))
        # give the worker a couple of loop turns to drain
        for _ in range(50):
            if drained == ["1", "2"]:
                break
            await asyncio.sleep(0.01)
        assert drained == ["1", "2"], drained
    finally:
        c.active = False
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_duplicate_owner_rejected():
    c = _bare_coord()

    async def h(e):
        pass

    c.on(SelfEventType.TASK_COMPLETED, h, name="dup", mode="sync")
    with pytest.raises(ValueError):
        c.on(SelfEventType.TASK_COMPLETED, h, name="dup", mode="sync")


@pytest.mark.asyncio
async def test_bad_mode_rejected():
    c = _bare_coord()

    async def h(e):
        pass

    with pytest.raises(ValueError):
        c.on(SelfEventType.TASK_COMPLETED, h, name="x", mode="nonsense")


@pytest.mark.asyncio
async def test_depth_guard_demotes_sync_to_deferred():
    c = _bare_coord()
    ran_inline = []

    async def h(e):
        ran_inline.append(True)

    c.on(SelfEventType.TASK_COMPLETED, h, name="h", mode="sync")
    # simulate being already at max emit depth: the sync reaction must be
    # enqueued (deferred) rather than run inline, and nothing dropped.
    c._emit_depth = c._max_emit_depth
    await c.emit(_completed())
    assert ran_inline == [], "sync reaction should have been demoted, not run inline"
    assert len(c._reactive_queue) == 1, "demoted reaction must be enqueued, not dropped"
    assert c._work_ready.is_set()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))


def _competence() -> SelfEvent:
    return SelfEvent(SelfEventType.COMPETENCE_CHANGED, CompetenceChanged(
        domain_id="d", learned=True, cause="test"))


@pytest.mark.asyncio
async def test_a_worker_leaves_the_selfs_reactions_to_the_lyric_it_works_for():
    """A worker learns from what it does, and tells the self of a change to what is worth pursuing; the self
    reacts to it (`SELF_REACTIONS`), never the worker."""
    async def handler(e):
        pass

    for worker, queued, told in ((True, ["operator_induction"], ["event:competence_changed"]),
                                 (False, ["operator_induction", "pursue_frontier"], [])):
        c = _bare_coord()
        c.worker = worker
        heard = []

        async def tell(said, heard=heard):
            heard.append(said)
        c._tell_the_self = tell
        c.on(SelfEventType.COMPETENCE_CHANGED, handler, name="operator_induction", mode="deferred", priority=50)
        c.on(SelfEventType.COMPETENCE_CHANGED, handler, name="pursue_frontier", mode="deferred", priority=10)
        await c.emit(_competence())
        assert [r["name"] for r, _ in c._reactive_queue] == queued, (worker, list(c._reactive_queue))
        assert heard == told, (worker, heard)


def test_the_self_wakes_its_reactions_on_what_a_worker_tells_it():
    """Each self reaction registered for the event a worker names is woken, from the same registrations
    `emit` uses; an event the self does not know wakes nothing."""
    async def handler(e):
        pass

    c = _bare_coord()
    woke = []
    c._pursuit_due = lambda: woke.append("pursuit")
    c._motivation_due = lambda: woke.append("motivation")
    c.on(SelfEventType.COMPETENCE_CHANGED, handler, name="motivation_refresh", mode="deferred", priority=20)
    c.on(SelfEventType.COMPETENCE_CHANGED, handler, name="pursue_frontier", mode="deferred", priority=10)
    c.on(SelfEventType.OUTCOME_OBSERVED, handler, name="pursue_frontier", mode="deferred", priority=10)
    c.on(SelfEventType.OUTCOME_OBSERVED, handler, name="operator_induction", mode="deferred", priority=50)
    c._heard_from_a_worker("event:competence_changed")
    assert woke == ["motivation", "pursuit"], woke
    c._heard_from_a_worker("event:outcome_observed")
    assert woke == ["motivation", "pursuit", "pursuit"], woke
    c._heard_from_a_worker("event:no_such_event")
    c._heard_from_a_worker("nonsense")
    assert woke == ["motivation", "pursuit", "pursuit"], woke


@pytest.mark.asyncio
async def test_what_a_worker_owes_a_person_is_said_by_the_lyric_it_works_for():
    """No front end listens to a worker: the message is owed in the outbox, and the self is told to say it."""
    class Outbox:
        async def put(self, actor, text, **kept):
            return {"message_id": "m1", "actor": actor, "text": text, "session": None, **kept}

    c = _bare_coord()
    c.worker = True
    c.outbox = Outbox()
    c._last_session_of = {}
    heard = []

    async def tell(said):
        heard.append(said)
    c._tell_the_self = tell
    c._arm = lambda message: heard.append("armed here")
    message = await AutonomousCoordinator.speak_to(c, "alice", "It is done.", why="work ended", about="t1")
    assert message["message_id"] == "m1"
    assert heard == ["said:m1"], heard


@pytest.mark.asyncio
async def test_a_workers_message_a_front_end_took_first_is_kept_and_not_said_again():
    """A front end that starts listening takes what waits for its person (`on_message`), and may take a worker's
    message before the self is told of it: the message is still kept in the person's conversation, and not said
    a second time."""
    for delivered, armed in ((None, ["m1"]), ("2026-10-23T00:00:00+00:00", [])):
        class Outbox:
            async def get(self, message_id):
                return {"message_id": message_id, "actor": "alice", "text": "It is done.", "why": "work ended",
                        "about": "t1", "session": None, "delivered_at": delivered}

        noted, said = [], []

        class Conversation:
            async def note_said(self, text, **kept):
                noted.append(text)
        c = _bare_coord()
        c.outbox = Outbox()
        c.conversation = lambda session, actor_identity=None: Conversation()
        c._arm = lambda message: said.append(message["message_id"])
        await c._say_what_a_worker_owes("m1")
        assert noted == ["It is done."], (delivered, noted)
        assert said == armed, (delivered, said)
