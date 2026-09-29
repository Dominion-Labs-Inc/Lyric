#!/usr/bin/env python3
"""The coordinator's single-flight reactions start in one place and stop with it.

A domain sweep that was running when the substrate shut down went on after the
store's pool closed, and died with "pool is closing", an exception no one was
left to retrieve. A bare coordinator (only the reactions' state) proves the
lifecycle without booting anything or touching a store.
"""
import asyncio
import logging

import pytest

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator


def _bare_coord() -> AutonomousCoordinator:
    c = AutonomousCoordinator.__new__(AutonomousCoordinator)
    for attr in AutonomousCoordinator._REACTIONS:
        setattr(c, attr, None)
    return c


@pytest.mark.asyncio
async def test_a_reaction_runs_once_at_a_time():
    c = _bare_coord()
    runs = []
    release = asyncio.Event()

    async def sweep():
        runs.append(1)
        await release.wait()

    c._react("_domain_discovery_drain_task", sweep)
    c._react("_domain_discovery_drain_task", sweep)
    await asyncio.sleep(0)
    assert runs == [1]
    release.set()
    await c._domain_discovery_drain_task


@pytest.mark.asyncio
async def test_stopping_cancels_a_reaction_in_flight_and_starts_no_more():
    c = _bare_coord()
    started = asyncio.Event()

    async def sweep():
        started.set()
        await asyncio.sleep(3600)

    c._react("_domain_discovery_drain_task", sweep)
    await started.wait()
    running = c._domain_discovery_drain_task
    await c._stop_reactions()
    assert running.cancelled()

    later = []

    async def after():
        later.append(1)

    c._react("_domain_expansion_drain_task", after)
    await asyncio.sleep(0)
    assert c._domain_expansion_drain_task is None and later == []


@pytest.mark.asyncio
async def test_a_reaction_that_failed_is_reported_at_stopping(caplog):
    c = _bare_coord()

    async def broken():
        raise RuntimeError("pool is closing")

    c._react("_induction_drain_task", broken)
    await asyncio.sleep(0)
    assert c._induction_drain_task.done()
    with caplog.at_level(logging.ERROR):
        await c._stop_reactions()
    assert any("_induction_drain_task had failed before shutdown" in r.getMessage()
               for r in caplog.records)
