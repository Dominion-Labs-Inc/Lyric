"""The queue authority's scheduler runs one run of a job at a time.

A job that comes due while its last run is still going is not started again on top of it: two runs of one job act
on the same state at once. The run not started is counted, on the job and in the authority's statistics, and the
job runs again once its run has ended. No store: the authority runs without persistence.
"""

import asyncio

from core.agents.autonomous.queue_authority import QueueAuthority


def test_a_job_still_running_is_not_started_again_and_what_was_not_started_is_counted():
    async def run():
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        release = asyncio.Event()
        started = []

        async def slow():
            started.append(asyncio.get_running_loop().time())
            await release.wait()

        authority.schedule_recurring("slow", slow, 0.02)
        authority.start()
        try:
            await asyncio.sleep(0.3)
            assert len(started) == 1, "a job due again while its run is going is not started on top of it"
            (status,) = [s for s in authority.scheduled_job_status() if s["name"] == "slow"]
            assert status["skipped"] >= 3, f"each time it came due, the run not started is counted: {status}"
            assert status["runs"] == 0, "the run in flight has not ended"
            assert (await authority.get_statistics())["scheduler_skipped"] == status["skipped"]
            release.set()
            await asyncio.sleep(0.2)
            assert len(started) >= 2, "once its run has ended, the job runs again"
            (status,) = [s for s in authority.scheduled_job_status() if s["name"] == "slow"]
            assert status["runs"] >= 1 and status["errors"] == 0
        finally:
            release.set()
            await authority.stop()

    asyncio.run(run())


def test_the_authority_says_whether_the_substrate_has_work_in_flight_and_for_how_long_it_has_not():
    """DOWNTIME WORK NEEDS ONE PLACE TO ASK. The authority already held two budgets -- an acting cap for work and
    a separate one for background -- so that background work can never take an acting slot, but `_pool_stats.active`
    counts both alike and so could not say whether anyone was being served: reflection running on the background
    budget read as the substrate being busy with itself.

    `busy` counts WORK ONLY, from the moment the job is handed over and before it waits for a slot, because a
    person waiting for a slot is a person waiting. `idle_for` is how long since the last one ended, monotonic, so
    setting the clock does not move it."""
    async def run():
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        assert not authority.busy(), "nothing has been asked of it"
        assert authority.idle_for() >= 0.0

        release = asyncio.Event()

        async def a_turn():
            await release.wait()
            return "answered"

        turn = asyncio.create_task(authority.execute("turn", a_turn))
        await asyncio.sleep(0.05)
        assert authority.busy(), "a person's turn is work in flight"
        assert authority.idle_for() == 0.0, "nothing is idle while work is in flight"

        # Background work is not someone being served, and must not read as it.
        async def upkeep():
            await asyncio.sleep(0.01)

        await authority.execute("upkeep", upkeep, background=True)
        assert authority.busy(), "the turn is still in flight"

        release.set()
        assert await turn == "answered"
        await asyncio.sleep(0.05)
        assert not authority.busy(), "the turn ended"
        assert authority.idle_for() > 0.0, "idle is counted from when the last work ended"

        # Background work alone leaves the substrate idle.
        await authority.execute("upkeep-again", upkeep, background=True)
        assert not authority.busy(), "background work is not someone being served"

    asyncio.run(run())


def test_a_long_pass_stands_down_for_work_and_says_where_it_had_got_to():
    """`GiveWay` gives the loop back so a long pass blocks nothing; that is politeness, not pausing, and the pass
    still runs to its end. Work that may only happen in downtime has to stop outright when a person arrives, and
    stop somewhere it can be taken up from.

    ASKED WHEN IT GIVES WAY, which is once per slice of work (`slow_callback_duration`) and not once per item. A
    person arriving is therefore noticed within one slice of the pass rather than at its end, and a pass whose
    items are too cheap to fill a slice is never interrupted at all -- it was already over. The slice is set small
    here so the test does not have to burn a tenth of a second to reach one."""
    async def run():
        from core.utils.give_way import GiveWay, StandDown
        asyncio.get_running_loop().slow_callback_duration = 0.001
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        release = asyncio.Event()

        async def a_turn():
            await release.wait()

        done, stopped_at, asked = [], None, False
        give_way = GiveWay(stand_down=authority.busy)
        try:
            for item in range(1000000):
                await give_way(at=item)
                done.append(item)
                if len(done) == 2000 and not asked:
                    # A person arrives in the middle of the pass.
                    asked = True
                    asyncio.create_task(authority.execute("turn", a_turn))
        except StandDown as stood:
            stopped_at = stood.at
        release.set()
        await asyncio.sleep(0.05)

        assert asked, "the turn was never asked for"
        assert stopped_at is not None, "the pass did not stand down for the turn"
        assert stopped_at == len(done), f"it said where it had got to: stopped at {stopped_at}, did {len(done)}"
        assert len(done) < 1000000, "it stopped before the end"

    asyncio.run(run())


def test_a_pass_given_no_stand_down_runs_as_it_always_has():
    """Every pass in the substrate but downtime work is given no `stand_down`, calls give-way with nothing, and
    cannot be stopped there. All 27 of them are unchanged by this."""
    async def run():
        from core.utils.give_way import GiveWay
        asyncio.get_running_loop().slow_callback_duration = 0.001
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        release = asyncio.Event()

        async def a_turn():
            await release.wait()

        asyncio.create_task(authority.execute("turn", a_turn))
        await asyncio.sleep(0.02)
        assert authority.busy(), "work is in flight"

        give_way = GiveWay()                       # no stand_down: the pass every other caller has
        done = 0
        for item in range(200000):
            await give_way()                       # called with nothing, as every caller calls it
            done += 1
        release.set()
        assert done == 200000, "a pass with no stand_down runs to its end though the substrate is busy"

    asyncio.run(run())


def test_a_resumable_job_is_taken_up_where_it_stopped_and_never_begun_again():
    """A stopped pass that starts from the beginning next time never reaches its end: it redoes the part it had
    already done, is stopped again, and holds a substrate that is used at all to the first seconds of its work for
    ever. A resumable job is called with where it last stood down, and standing down is not an error."""
    async def run():
        from core.utils.give_way import StandDown
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        seen = []

        async def reflect(resume_at=None):
            start = resume_at or 0
            seen.append(start)
            if start < 20:
                raise StandDown(start + 10)
            return "reflected"

        authority.schedule_recurring("reflect", reflect, 0.02, resumable=True)
        authority.start()
        try:
            await asyncio.sleep(0.3)
        finally:
            await authority.stop()

        assert seen[:3] == [0, 10, 20], f"each run takes up where the last stood down: {seen[:5]}"
        # Having run to its end it holds no place, so the run after it begins again from the start.
        assert seen[3] == 0, f"a job that ran to its end holds no place: {seen[:6]}"
        (status,) = [s for s in authority.scheduled_job_status() if s["name"] == "reflect"]
        assert status["errors"] == 0, f"standing down is not failing: {status}"
        assert status["stood_down"] >= 2, f"standing down is counted on the job: {status}"

    asyncio.run(run())


def test_downtime_work_stands_down_for_another_substrate_on_the_same_store():
    """`busy()` is answered inside one process and cannot see a second substrate on the same store.

    `scripts/teach.py` starts a full substrate of its own against the same World Model. While one teaches,
    this process is idle by every measure it has -- no turn, no task, nothing in flight -- so a pass that may
    run only in downtime would begin a long walk over the database being written. The heartbeat reads how many
    other instances are alive, and downtime work stands down for them as it does for a person."""
    async def run():
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})
        should = authority.stand_down_after(0.0)
        assert not authority.busy() and not authority.elsewhere_working()
        assert not should(), "nothing is working this store"

        # A teaching run comes up: another instance, beating.
        authority._others_alive = 1
        assert authority.elsewhere_working()
        assert should(), "a pass must stand down while something else works the store"
        assert not authority.busy(), "and it is not this process that is busy"

        # It finishes.
        authority._others_alive = 0
        assert not should()

    asyncio.run(run())


def test_the_heartbeat_reads_who_else_is_alive_and_a_store_error_leaves_the_last_answer():
    """Read on the heartbeat's cadence, not per give-way: downtime work asks at every give-way, and a store
    read each time would cost more than the pass it guards.

    A failed read leaves the last answer standing. Reading "nothing else is working" from a failure would
    start a long pass on a guess; reading "something is" would stop downtime work for ever on a store that
    stays unwell."""
    async def run():
        authority = QueueAuthority({"persist": False, "scheduler_tick_s": 0.01})

        class Persistence:
            def __init__(self):
                self.alive, self.fail, self.beats = 2, False, 0

            async def heartbeat(self):
                self.beats += 1

            async def others_alive(self, lease_s):
                assert lease_s > 0, "asked with the lease the work it guards is held under"
                if self.fail:
                    raise RuntimeError("the store is unwell")
                return self.alive

        persistence = Persistence()
        authority._persistence_or_none = lambda: persistence

        await authority.heartbeat()
        assert persistence.beats == 1, "its own lease is still renewed"
        assert authority._others_alive == 2 and authority.elsewhere_working()

        persistence.fail = True
        await authority.heartbeat()
        assert authority._others_alive == 2, "a failed read leaves the last answer standing"
        assert persistence.beats == 2, "and does not stop the heartbeat"

        persistence.fail, persistence.alive = False, 0
        await authority.heartbeat()
        assert not authority.elsewhere_working()

    asyncio.run(run())


def test_the_store_is_asked_for_other_instances_and_never_counts_this_one():
    """The statement excludes this instance by id and bounds freshness by the lease. Counting itself, every
    substrate would read as having company and no downtime work would ever run."""
    from core.agents.autonomous.queue_persistence import QueuePersistence

    asked = {}

    class Db:
        async def execute_query(self, query, params=None, **kw):
            asked["query"] = " ".join(query.split())
            asked["params"] = params
            return {"n": 3}

    persistence = QueuePersistence.__new__(QueuePersistence)
    persistence.instance_id = "queue_me"
    persistence._db = Db()
    persistence._schema_ready = True

    assert asyncio.run(persistence.others_alive(120.0)) == 3
    assert "instance_id <> $1" in asked["query"], asked["query"]
    assert "heartbeat_at >= NOW() - make_interval(secs => $2)" in asked["query"], asked["query"]
    assert asked["params"] == ("queue_me", 120.0), asked["params"]

    # No row at all is no company, not an error.
    class Empty(Db):
        async def execute_query(self, query, params=None, **kw):
            return None

    persistence._db = Empty()
    assert asyncio.run(persistence.others_alive(120.0)) == 0


def test_the_downtime_question_is_answered_by_an_authority_that_predates_it():
    """THIS SUBSTRATE ADOPTS CODE INTO A RUNNING PROCESS, so a new attribute set only in `__init__` does not
    exist on the authority already built.

    Measured live: `elsewhere_working` was adopted into a resident whose authority was constructed before the
    attribute, and the reflection job failed every ten minutes with
    `AttributeError: 'QueueAuthority' object has no attribute '_others_alive'` (2026-11-19 12:21:36). A
    default on the class is what such an authority reads; the first heartbeat replaces it with the store's
    answer. Nothing here runs `__init__`, which is the point."""
    bare = QueueAuthority.__new__(QueueAuthority)
    assert bare.busy() is False
    assert bare.elsewhere_working() is False
    assert bare.idle_for() >= 0.0
    assert QueueAuthority.stand_down_after(bare, 0.0)() is False, "it answers rather than raising"
