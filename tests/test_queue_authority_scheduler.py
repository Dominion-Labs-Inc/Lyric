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
