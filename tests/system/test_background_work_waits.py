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
apparatus from the SAME kind of creator, and only the real one is said at the
installed level.

Run with: python3 -m pytest tests/system/test_background_work_waits.py -v
"""

import asyncio
import logging

import pytest

from core.observability.channels import running_now, watch_background_work


#: Both halves of the pair, to be compiled under a `core.` module name.
#:
#: `_level_for` keys the installed level off the CREATOR'S module name -- a
#: library's plumbing is logged at DEBUG whatever it does -- so a pair created
#: from a test module arrives at DEBUG on both sides and proves nothing about
#: the demotion under test. Compiling the probe under a core name is what puts
#: it on the path the resident actually takes.
_PROBE = """
import asyncio

async def poll_an_empty_queue(queue, timeout):
    return await asyncio.wait_for(queue.get(), timeout=timeout)

def start_work_nobody_lets_finish():
    async def work_nobody_lets_finish():
        await asyncio.sleep(30)
    return asyncio.get_running_loop().create_task(work_nobody_lets_finish())
"""


class _Caught(logging.Handler):
    """Every record the apparatus emits, with the level it chose."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def cancelled(self, naming):
        return [(lvl, msg) for lvl, msg in self.records
                if "background task cancelled" in msg and naming in msg]


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


@pytest.fixture
def probe():
    """The pair's two creators, under a core module name."""
    namespace = {"__name__": "core.observability._wait_probe"}
    exec(compile(_PROBE, "_wait_probe.py", "exec"), namespace)
    return namespace


@pytest.mark.asyncio
async def test_expired_wait_is_not_reported_as_a_cancelled_task(caught, probe):
    """The poll that found nothing: still a line, but not at the installed level."""
    assert watch_background_work(level=logging.INFO)

    with pytest.raises(asyncio.TimeoutError):
        await probe["poll_an_empty_queue"](asyncio.Queue(), 0.05)

    lines = caught.cancelled("Queue.get")
    assert lines, "the expired wait said nothing at all; it should still be at DEBUG"
    assert all(lvl == logging.DEBUG for lvl, _ in lines), (
        "an expired deadline was reported at the installed level: %r" % (lines,))


@pytest.mark.asyncio
async def test_a_real_cancellation_is_still_reported(caught, probe):
    """The capability this must not cost: work stopped is still said."""
    assert watch_background_work(level=logging.INFO)

    task = probe["start_work_nobody_lets_finish"]()
    await asyncio.sleep(0)          # let it reach the sleep
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    lines = caught.cancelled("work_nobody_lets_finish")
    assert lines, "a cancelled task said nothing"
    assert any(lvl == logging.INFO for lvl, _ in lines), (
        "a real cancellation was demoted with the waits: %r" % (lines,))


@pytest.mark.asyncio
async def test_a_standing_wait_is_still_on_the_roster(caught, probe):
    """What this must not cost: `running_now` answers "what is it doing".

    The mark that demotes an expired wait rides on the task object, so `_LIVE`
    keeps the shape every reader of it already expects -- and a wait long enough
    to matter is still something the roster can name.
    """
    assert watch_background_work(level=logging.INFO)
    waiting = asyncio.ensure_future(
        probe["poll_an_empty_queue"](asyncio.Queue(), 5))
    await asyncio.sleep(0.05)

    try:
        rows = running_now()
        assert [row for row in rows if row["what"] == "Queue.get"], (
            "a live wait was not on the roster at all")
        assert all({"what", "where", "channel", "logger", "running_for_s"}
                   <= set(row) for row in rows)
    finally:
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
