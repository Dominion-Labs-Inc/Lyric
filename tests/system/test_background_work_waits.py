#!/usr/bin/env python3
"""
Background-work reporting: a wait is not work somebody stopped
==============================================================
`asyncio.wait_for(x, t)` wraps `x` in a task of its own and cancels it when `t`
passes, so the loop's task factory saw every expired deadline as a cancelled
task and said so at the installed level. One 16h47m run of the resident wrote
27,746 such lines; 27,740 were `Queue.get` from the cognition loop polling an
empty queue, which is 29% of the log saying only that there was no work.

The minimal pair: an expired wait and a real cancellation go through the SAME
apparatus, and only the real one is said at the installed level.

Run with: python3 -m pytest tests/system/test_background_work_waits.py -v
"""

import asyncio
import logging

import pytest

from core.observability.channels import running_now, watch_background_work


class _Caught(logging.Handler):
    """Every record the apparatus emits, with the level it chose."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def cancelled_lines(self):
        return [(lvl, msg) for lvl, msg in self.records
                if "background task cancelled" in msg]


@pytest.fixture
def caught():
    """Capture at DEBUG, so a line moved to DEBUG is still seen, not just gone."""
    handler = _Caught()
    root = logging.getLogger()
    before = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(before)


@pytest.mark.asyncio
async def test_expired_wait_is_not_reported_as_a_cancelled_task(caught):
    """The poll that found nothing: a line, but not at the installed level."""
    assert watch_background_work(level=logging.INFO)
    queue = asyncio.Queue()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.05)

    lines = [(lvl, msg) for lvl, msg in caught.cancelled_lines()
             if "Queue.get" in msg]
    assert lines, "the expired wait said nothing at all; it should still be at DEBUG"
    assert all(lvl == logging.DEBUG for lvl, _ in lines), (
        "an expired deadline was reported at the installed level: %r" % (lines,))


@pytest.mark.asyncio
async def test_a_real_cancellation_is_still_reported(caught):
    """The capability this must not cost: work stopped is still said."""
    assert watch_background_work(level=logging.INFO)

    async def work_nobody_lets_finish():
        await asyncio.sleep(30)

    task = asyncio.get_running_loop().create_task(work_nobody_lets_finish())
    await asyncio.sleep(0)          # let it reach the sleep
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    lines = [(lvl, msg) for lvl, msg in caught.cancelled_lines()
             if "work_nobody_lets_finish" in msg]
    assert lines, "a cancelled task said nothing"
    assert any(lvl == logging.INFO for lvl, _ in lines), (
        "a real cancellation was demoted with the waits: %r" % (lines,))


@pytest.mark.asyncio
async def test_a_standing_wait_says_it_is_a_wait(caught):
    """`running_now` answers "what is it doing" -- a wait is named as one."""
    assert watch_background_work(level=logging.INFO)
    queue = asyncio.Queue()
    waiting = asyncio.ensure_future(asyncio.wait_for(queue.get(), timeout=5))
    await asyncio.sleep(0.05)

    try:
        waits = [row for row in running_now() if row["what"] == "Queue.get"]
        assert waits, "a live wait was not on the roster at all"
        assert all(row["is_a_wait"] for row in waits)
        assert not any(row["is_a_wait"] for row in running_now()
                       if row["what"] == "Queue.get" and False), "sanity"
    finally:
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
