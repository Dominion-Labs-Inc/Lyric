#!/usr/bin/env python3
"""Reflection takes a window of what was learned, reaches a verdict on each piece, and survives a restart.

Nothing reflected. `bridge.reflect()` is belief-graph hygiene over the graph as it stands -- no window, no
verdict, and it opens neither the evidence nor a single memory -- and `review_against_evidence`, which reads
1,783,544 observations back against the beliefs they bear on, had no caller at all.

These run against a store of their own, so no belief and no memory is written anywhere.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from core.agents.memory_agent import MemoryAgent  # noqa: E402
from core.utils.give_way import StandDown  # noqa: E402

BEGAN = datetime(2026, 11, 6, 21, 12, 40)


class Store:
    """The reflection's store: the reflections table, the window's memories and what came of each."""

    def __init__(self, memories, came_of_it=None, held=None):
        #: [(memory_id, created_at)], oldest first, as the walk reads them
        self.memories = list(memories)
        #: memory_id -> (beliefs, borne, against)
        self.came_of_it = dict(came_of_it or {})
        #: the unfinished reflection the store already holds, if any
        self.held = held
        self.rows = []
        self.positions = []
        self.saved = []
        self.ended = []
        self.pages = 0

    def maintained_stores(self):
        return ["main"]

    async def execute_query(self, query, params=None, **kw):
        q = " ".join(query.split())
        if q.startswith(("CREATE", "ALTER")):
            return None
        if "FROM unified.reflections WHERE whose" in q and "ended_at IS NULL" in q:
            return [self.held] if self.held else []
        if "max(window_to)" in q:
            return [{"upto": None}]
        if "min(created_at)" in q:
            return [{"first": self.memories[0][1] if self.memories else None}]
        if q.startswith("INSERT INTO unified.reflections"):
            self.rows.append(params)
            return [{"reflection": 7}]
        if "UNION ALL" in q:
            self.pages += 1
            _owners, window_from, window_to, since, last, many = params
            after = [(mid, at) for mid, at in self.memories
                     if window_from <= at < window_to and (at, mid) > (since, last)]
            return [{"memory_id": mid, "created_at": at} for mid, at in sorted(after, key=lambda p: (p[1], p[0]))][:many]
        if "FROM unified.beliefs" in q:
            out = []
            for mid in params[0]:
                if mid in self.came_of_it:
                    beliefs, borne, against = self.came_of_it[mid]
                    out.append({"memory_id": mid, "beliefs": beliefs, "borne": borne, "against": against})
            return out
        if q.startswith("UPDATE unified.reflections SET position"):
            self.positions.append(params[0])
            self.saved.append(params)
            return None
        if q.startswith("UPDATE unified.reflections SET ended_at"):
            self.ended.append(params)
            return None
        raise AssertionError(f"unexpected query: {q[:120]}")


def agent_over(store, *, reviewed=0, settled=None):
    """A memory agent whose store is `store` and nothing else: no initialise, no loops, no embeddings."""
    agent = MemoryAgent.__new__(MemoryAgent)
    agent._reflection_schema_ready = True
    agent._memory_db = lambda: store
    agent.written = []

    async def update_memory(memory_id, updates, tier=None):
        agent.written.append((memory_id, updates))
        return True

    async def review(resume_at=None, **kw):
        return {"reviewed": reviewed, "resume_at": None}

    async def reflect_on_beliefs():
        return settled if settled is not None else {"decayed": 0, "consistency": {}, "errors": []}

    agent.update_memory = update_memory
    agent.reflect_on_beliefs = reflect_on_beliefs
    agent._reasoning_authority = lambda: type("Bridge", (), {"beliefs": type("B", (), {
        "review_against_evidence": staticmethod(review)})()})()
    return agent


def memories(n, *, start=BEGAN):
    return [(f"mem_{i:04d}", start + timedelta(seconds=i)) for i in range(n)]


def test_a_verdict_is_reached_on_every_piece_of_knowledge():
    """Each of the four verdicts, and the lines between them.

    A withdrawal is already excluded from `opposed` by the review, so `against` is genuine contradiction:
    never contradicted bore out, contradicted but outweighed is questioned, contradiction at least equal did
    not hold, and nothing to weigh is not a failure -- a grammar row has no evidence because it is a rule."""
    store = Store(memories(4), came_of_it={
        "mem_0000": (1, 30, 0),      # borne out thirty times, never contradicted
        "mem_0001": (1, 30, 4),      # contradicted, and outweighed
        "mem_0002": (1, 12, 30),     # contradicted more often than borne out
    })                               # mem_0003: no belief came of it
    agent = agent_over(store)
    got = asyncio.run(agent.reflect_on_what_was_learned())
    assert got["examined"] == 4, got
    assert (got["bore_out"], got["questioned"], got["did_not_hold"], got["nothing_to_weigh"]) == (1, 1, 1, 1), got


def test_only_a_finding_is_written_back_onto_the_knowledge():
    """Marking every piece `fine` would rewrite the store to say what the reflection's own counts say. What
    goes on the knowledge is the verdict somebody has to look at -- and it is MERGED, because the column is
    the memory filter's record of what let it in and a reflection may not overwrite that."""
    store = Store(memories(3), came_of_it={
        "mem_0000": (1, 30, 0),
        "mem_0001": (2, 12, 30),
    })
    agent = agent_over(store)
    asyncio.run(agent.reflect_on_what_was_learned())
    written = {mid: updates for mid, updates in agent.written}
    assert set(written) == {"mem_0001"}, f"only what did not hold up is marked: {sorted(written)}"
    reflected = written["mem_0001"]["memory_admission"]["reflected"]
    assert reflected["verdict"] == MemoryAgent.DID_NOT_HOLD
    assert (reflected["borne_out"], reflected["contradicted"], reflected["beliefs"]) == (12, 30, 2)
    assert reflected["reflection"] == 7
    assert list(written["mem_0001"]) == ["memory_admission"], "nothing else about the memory is touched"


def test_the_place_is_written_to_the_store_so_a_restart_takes_it_up():
    """A resumable job keeps its place on the job object, and a job object lives inside one process. A
    reflection of everything learned does not finish inside one, so the place is in the store: a second
    process finds the reflection in hand and continues it instead of opening another over the same window."""
    store = Store(memories(60), came_of_it={}, held=None)
    agent = agent_over(store)

    async def run():
        asyncio.get_running_loop().slow_callback_duration = 0.0      # ask at every give-way
        asked = {"n": 0}

        def busy_after_ten():
            asked["n"] += 1
            return asked["n"] > 10

        try:
            await agent.reflect_on_what_was_learned(stand_down=busy_after_ten)
            raise AssertionError("it did not stand down")
        except StandDown as stood:
            return stood.at

    where = asyncio.run(run())
    step, _, place = where.partition(":")
    assert step == "knowledge", where
    assert store.positions[-1] == where, "the place reached the store before it was raised"
    assert place.startswith("main|"), where

    # A NEW PROCESS: a new agent, a store that holds the unfinished reflection, and the place read back from
    # it rather than handed in. It takes up the walk and opens no second reflection.
    # CARRIED FORWARD EXACTLY AS SAVED, not as the test guesses: the counts the first sitting wrote are what
    # the next one adds to, and an off-by-one here would hide one in the pass.
    _where, weighed, examined, bore, questioned, failed, nothing, _flag, _which = store.saved[-1]
    carried = {"reflection": 7, "whose": "own", "window_from": BEGAN,
               "window_to": BEGAN + timedelta(days=1), "position": where, "weighed": weighed,
               "examined": examined, "bore_out": bore, "questioned": questioned, "did_not_hold": failed,
               "nothing_to_weigh": nothing, "stood_down": 1}
    after = Store(memories(60), came_of_it={}, held=carried)
    got = asyncio.run(agent_over(after).reflect_on_what_was_learned())
    assert after.rows == [], "no second reflection was opened"
    assert got["examined"] == 60, f"it finished the window: {got}"
    assert got["nothing_to_weigh"] == 60


def test_the_window_runs_from_where_the_last_one_ended_and_is_open_at_the_top():
    """A memory written while the pass runs belongs to the next window, or a reflection never reaches its own
    end. `window_to` is fixed when the reflection opens for the same reason."""
    store = Store(memories(5))
    agent = agent_over(store)
    asyncio.run(agent.reflect_on_what_was_learned())
    _whose, window_from, window_to = store.rows[0]
    assert window_from == BEGAN, "the first window starts at the oldest memory held"
    assert window_to > store.memories[-1][1], window_to
    # Everything in the window was examined, and the walk asked for more than once.
    assert store.pages >= 2, "the walk pages until the window is exhausted"


def test_the_evidence_is_weighed_before_a_verdict_is_reached():
    """`review_against_evidence` is what makes `supported`/`opposed` true as of now, and nothing called it.
    Reflection calls it first, so a verdict is reached on what the evidence says rather than on whatever it
    said when something last asked."""
    store = Store(memories(2))
    agent = agent_over(store, reviewed=1022193)
    got = asyncio.run(agent.reflect_on_what_was_learned())
    assert got["weighed"] == 1022193, got
    assert store.positions[0] == "knowledge:", "the evidence step is recorded as done before the walk"


def test_the_settling_step_is_the_last_one_and_is_kept():
    """Belief-graph hygiene still runs -- decay, consistency, volatility, schema decay -- as reflection's last
    step rather than as the whole of it, and its report is kept on the reflection."""
    store = Store(memories(1))
    agent = agent_over(store, settled={"decayed": 3, "consistency": {"contradictions": 1}, "errors": []})
    got = asyncio.run(agent.reflect_on_what_was_learned())
    assert got["settled"]["consistency"] == {"contradictions": 1}
    assert store.positions[-1] == "settling:", store.positions
    assert json.loads(store.ended[0][6])["decayed"] == 3, "the settling is kept with the reflection"


def test_reflecting_on_an_instance_refuses_by_name_until_a_release_is_cut():
    """The World Model reflecting over an instance is the same walk over another store, and there is no
    instance: no release has been cut for one to read. Refusing and saying why is the answer; reading nothing
    and reporting a reflection is not."""
    agent = agent_over(Store(memories(1)))
    try:
        asyncio.run(agent.reflect_on_what_was_learned(whose="acme"))
        raise AssertionError("it did not refuse")
    except ValueError as refused:
        assert "no release has been cut" in str(refused), refused
        assert "acme" in str(refused), refused


def test_nothing_learned_yet_is_not_a_reflection():
    """A substrate holding no memory of its own has nothing to reflect on, and says so rather than opening a
    reflection over an empty window."""
    store = Store([])
    got = asyncio.run(agent_over(store).reflect_on_what_was_learned())
    assert got == {"reflected": False, "because": "nothing has been learned yet"}, got
    assert store.rows == [], "no reflection was opened"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_reflection_declines_while_anything_else_is_working_the_store():
    """Two gates, both asked before a window is opened: how long THIS process has been quiet, and whether
    another substrate is working the same store. The second cannot be read from the first -- a teaching run is
    a full substrate of its own against the same World Model, and while one teaches this process is idle by
    every measure it has."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    class Queue:
        def __init__(self, idle, elsewhere):
            self.idle, self.elsewhere, self.floors = idle, elsewhere, []

        def idle_for(self):
            return self.idle

        def elsewhere_working(self):
            return self.elsewhere

        def stand_down_after(self, floor):
            self.floors.append(floor)
            return lambda: False

    def coordinator(idle, elsewhere, memory="the agent"):
        coord = AutonomousCoordinator.__new__(AutonomousCoordinator)
        coord.config, coord.memory = {}, memory
        coord.task_queue = Queue(idle, elsewhere)
        return coord

    # In use a moment ago: nothing is begun, and it is not a stand-down -- there is no new place to record.
    busy = coordinator(idle=4.0, elsewhere=False)
    assert asyncio.run(busy._reflect_on_what_was_learned()) == {
        "reflected": False, "because": "in use within the last 120s"}

    # Quiet here, but something else is working the store.
    taught = coordinator(idle=9999.0, elsewhere=True)
    assert asyncio.run(taught._reflect_on_what_was_learned()) == {
        "reflected": False, "because": "another substrate is working this store"}
    assert taught.task_queue.floors == [], "the pass was never begun, so no floor was handed down"

    # Quiet, and nothing else about: the pass is begun, with the same floor handed down as its stand-down.
    class Memory:
        def __init__(self):
            self.asked = None

        async def reflect_on_what_was_learned(self, resume_at=None, *, stand_down=None):
            self.asked = (resume_at, stand_down)
            return {"reflected": True}

    memory = Memory()
    quiet = coordinator(idle=9999.0, elsewhere=False, memory=memory)
    assert asyncio.run(quiet._reflect_on_what_was_learned("knowledge:main|x|y")) == {"reflected": True}
    assert memory.asked[0] == "knowledge:main|x|y", "it is taken up where it stopped"
    assert quiet.task_queue.floors == [120.0], "one number answers both questions"


def test_reflection_without_a_memory_agent_is_a_wiring_defect_and_says_so():
    """Not caught and not skipped into a green count: reflection reads and writes the substrate's memory, so
    without the memory agent there is nothing to reflect on and nowhere to record it."""
    import pytest
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coord = AutonomousCoordinator.__new__(AutonomousCoordinator)
    coord.config, coord.memory, coord.task_queue = {}, None, None
    with pytest.raises(RuntimeError, match="without a memory agent"):
        asyncio.run(coord._reflect_on_what_was_learned())


def test_the_place_is_written_during_the_evidence_step_too():
    """The evidence step is the long one -- 1,022,193 beliefs, around thirteen minutes while giving the loop
    back by time -- and it used to record nothing until it ended or stood down. A restart carries no
    `StandDown`, so a reflection interrupted inside that step began the whole step again.

    Now the review says where it has got to after every batch and reflection writes it down, so the place is
    in the store whether the pass stops politely or the process disappears."""
    store = Store(memories(1))
    agent = agent_over(store)

    class Beliefs:
        @staticmethod
        async def review_against_evidence(resume_at=None, *, stand_down=None, reached=None):
            assert reached is not None, "reflection asks to be told where the review has got to"
            for n, belief in enumerate(("b_0100", "b_0200", "b_0300"), start=1):
                await reached(belief, n * 2000)
            return {"reviewed": 6000, "resume_at": None}

    agent._reasoning_authority = lambda: type("Bridge", (), {"beliefs": Beliefs()})()
    got = asyncio.run(agent.reflect_on_what_was_learned())
    assert got["weighed"] == 6000, got

    # Every batch's place reached the store, under the step it belongs to.
    during = [where for where in store.positions if where.startswith("evidence:")]
    assert during == ["evidence:b_0100", "evidence:b_0200", "evidence:b_0300"], store.positions
    # And the count written with each place is the count reached by then, not the count at the end.
    weighed = [params[1] for params in store.saved if params[0].startswith("evidence:")]
    assert weighed == [2000, 4000, 6000], weighed
