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
