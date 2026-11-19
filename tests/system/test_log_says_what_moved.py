#!/usr/bin/env python3
"""
What the log says: the fact that moved, and the reason behind a verdict
======================================================================
Measured over 8m28s of one resident run (2026-11-18, PID 11474), 2,846 of
2,976 lines -- 95.6% -- were a handful of facts restated:

  2,278  🧭 Behaviour / 🧘 Exploration declined, the same stance twice a line,
         eight times a second for 147 seconds
    255  the 30s roster: four threads on the same four lines, eleven tasks
         still standing, fifteen identical lines a tick
    238  fourteen components restating an unchanged verdict every 30s
     75  [IDLE:DOMAIN] the same "none unexpanded" finding

and the one line that carried a real finding -- `learning = degraded` -- named
no reason, though the reasons were computed in that very method and persisted
to component_health a line later.

Four properties, each the real code path:
  1. the pursuit drain settles between passes and is bounded (the 2,278)
  2. a disposition is said at the installed level when it CHANGES
  3. a health verdict carries its reasons, and is said when it is news
  4. a roster tick that repeats the last one is DEBUG, plus ONE liveness line

Run with: python3 -m pytest tests/system/test_log_says_what_moved.py -v
"""

import asyncio
import logging
import time
import types

import pytest


class _Caught(logging.Handler):
    """Every record, with the level the apparatus chose for it."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append((record.levelno, record.getMessage()))

    def saying(self, fragment):
        return [(lvl, msg) for lvl, msg in self.records if fragment in msg]


@pytest.fixture
def caught():
    """Capture at DEBUG, so a line MOVED to DEBUG is seen, not just absent."""
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


# ── 1. The drain that was neither settled nor bounded ────────────────────────

@pytest.mark.asyncio
async def test_a_burst_of_wakes_costs_one_more_selection_not_one_each():
    """147 seconds of mutual re-waking cost 1,139 appraisals; it should cost 2.

    The drain re-ran per event with no pause, so the pursuit drain and the two
    domain drains answering the same events kept each other awake at 8 Hz. The
    settle is what makes a burst of any size one more pass.
    """
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    passes = []
    coordinator = types.SimpleNamespace(
        _pursuit_dirty=True,
        _COALESCE_MAX_PASSES=100,
        _COALESCE_SETTLE_S=0.05,
    )

    async def one_selection():
        passes.append(time.monotonic())
        # A burst arriving while one selection runs: the drains answering the
        # same events emit fifty times over before this pass returns.
        if len(passes) == 1:
            for _ in range(50):
                coordinator._pursuit_dirty = True

    coordinator._run_exploration_cycle = one_selection
    await AutonomousCoordinator._coalesced_pursue(coordinator)

    assert len(passes) == 2, (
        "fifty wakes arriving during one selection should collapse into one "
        "more selection, not fifty; got %d passes" % len(passes))
    assert passes[1] - passes[0] >= 0.05, (
        "the second pass started without letting events settle")


@pytest.mark.asyncio
async def test_a_drain_that_keeps_being_woken_is_bounded_and_says_so(caught):
    """Re-woken forever, it stops at the bound and leaves the flag for the next
    wake -- the backstop its three sibling drains already had."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    passes = []
    coordinator = types.SimpleNamespace(
        _pursuit_dirty=True, _COALESCE_MAX_PASSES=4, _COALESCE_SETTLE_S=0.0)

    async def one_selection():
        passes.append(1)
        coordinator._pursuit_dirty = True

    coordinator._run_exploration_cycle = one_selection
    await AutonomousCoordinator._coalesced_pursue(coordinator)

    assert len(passes) == 4, "the drain ran past its bound: %d" % len(passes)
    assert coordinator._pursuit_dirty, "work left at the bound was dropped"
    assert caught.saying("pursuit selection ran 4 passes"), (
        "a drain stopping at its bound said nothing about it")


# ── 2. A disposition is news when it changes ─────────────────────────────────

def _declining_coordinator():
    """A coordinator whose arbiter says "proceed, do not explore" -- the stance
    that was logged 1,139 times. Only what the cycle reads before it returns."""
    directive = types.SimpleNamespace(
        mode="proceed", should_explore=False, max_goals=0,
        verification_intensity=0.5,
        reason_codes=["dominant:escalate:0.00", "mood_explore:+0.00"])

    async def context():
        return {}

    async def unexpected(error, where):
        raise AssertionError("the cycle faulted at %s: %r" % (where, error))

    return types.SimpleNamespace(
        _recent_exploration_fp_list=[],
        _intrinsic_exploration_cap=1,
        _exploration_status=None,
        # "nominal" is the pressure the resident ran at: anything else suspends
        # exploration before the arbiter is ever consulted.
        task_queue=types.SimpleNamespace(active_tasks=lambda: [],
                                         pressure=lambda: "nominal",
                                         get_queue_length=lambda: 0),
        _collect_system_context_for_goals=context,
        disposition=lambda **kw: directive,
        _handle_error=unexpected,
    )


@pytest.mark.asyncio
async def test_the_same_stance_reached_again_is_not_announced_again(caught):
    """First time at the installed level; unchanged, at DEBUG -- still recorded."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = _declining_coordinator()
    cycle = AutonomousCoordinator._run_exploration_cycle

    await cycle(coordinator)
    first = caught.saying("🧭 Behaviour")
    assert first and first[-1][0] == logging.INFO, (
        "a disposition the substrate had not taken before was not announced: %r"
        % (first,))
    assert [lvl for lvl, _ in caught.saying("Exploration declined by arbiter")] \
        == [logging.INFO]

    await cycle(coordinator)
    await cycle(coordinator)
    again = caught.saying("🧭 Behaviour")[1:]
    assert len(again) == 2, "the stance stopped being recorded at all"
    assert all(lvl == logging.DEBUG for lvl, _ in again), (
        "the same stance was announced again at the installed level: %r" % (again,))
    assert [lvl for lvl, _ in caught.saying("Exploration declined by arbiter")] \
        == [logging.INFO, logging.DEBUG, logging.DEBUG]


@pytest.mark.asyncio
async def test_a_stance_that_moves_is_announced(caught):
    """What this must not cost: a disposition that changed is still news."""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    coordinator = _declining_coordinator()
    cycle = AutonomousCoordinator._run_exploration_cycle
    await cycle(coordinator)
    await cycle(coordinator)

    moved = types.SimpleNamespace(
        mode="escalate", should_explore=False, max_goals=0,
        verification_intensity=0.9, reason_codes=["dominant:escalate:0.70"])
    coordinator.disposition = lambda **kw: moved
    await cycle(coordinator)

    said = caught.saying("🧭 Behaviour")
    assert said[-1][0] == logging.INFO, (
        "a disposition that moved was buried at DEBUG: %r" % (said[-1],))
    assert "mode=escalate" in said[-1][1]


# ── 3. A verdict says why ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_verdict_carries_the_reasons_it_rests_on(caught):
    """`learning = degraded` named no reason, though its findings were right there.

    The real `check_component_health`, with the component's own check standing in
    for the learning authority and nothing written to the store.
    """
    from core.health.health_monitor import HealthMonitor, HealthStatus

    monitor = HealthMonitor()
    regression = ("Capability regression: memory.health_score fell from a "
                  "baseline of 100.0 to 90.0 over 7581 cycle(s)")

    async def learning_check():
        return {"learning_available": True, "capability_regressions": 1}, [regression]

    async def no_probes(component):
        return {}, []

    async def not_persisted(record):
        return None

    monitor._check_learning_health = learning_check
    monitor._probe_subcomponents = no_probes
    monitor._record_subcomponent_health = lambda component, metrics: {}
    monitor._persist_assessment = not_persisted

    health = await monitor.check_component_health("learning")
    said = caught.saying("Component health check: learning")
    assert said, "the check said nothing at all"
    level, line = said[-1]

    assert regression in line, (
        "the verdict named a status and no reason, so nothing reading the log "
        "can tell which part is unwell or what to work on: %r" % (line,))
    if health.status == HealthStatus.HEALTHY:
        assert level == logging.INFO
    else:
        assert level == logging.WARNING, (
            "a component reporting itself unwell was said at %s" % level)


@pytest.mark.asyncio
async def test_an_unchanged_verdict_is_recorded_but_not_announced(caught):
    """Fourteen components every 30s: the second identical verdict is DEBUG."""
    from core.health.health_monitor import HealthMonitor

    monitor = HealthMonitor()

    async def safety_check():
        return {"safety_available": True}, []

    async def no_probes(component):
        return {}, []

    async def not_persisted(record):
        return None

    monitor._check_safety_health = safety_check
    monitor._probe_subcomponents = no_probes
    monitor._record_subcomponent_health = lambda component, metrics: {}
    monitor._persist_assessment = not_persisted

    for _ in range(3):
        await monitor.check_component_health("safety")

    levels = [lvl for lvl, _ in caught.saying("Component health check: safety")]
    assert len(levels) == 3, "a check stopped being recorded: %r" % (levels,)
    assert levels[0] in (logging.INFO, logging.WARNING), (
        "the first verdict for a component was not announced")
    assert levels[1:] == [logging.DEBUG, logging.DEBUG], (
        "an unchanged verdict was announced again: %r" % (levels,))


# ── 4. A roster tick that repeats the last one ───────────────────────────────

def test_an_unchanged_tick_is_debug_plus_one_line_that_it_is_alive(caught):
    """The roster's job is "what is it doing right now", and silence would read
    as idle -- so an unchanged tick keeps one line, not fifteen."""
    from core.observability import channels

    watcher = __import__("threading").Thread(
        target=channels._heartbeat, args=(0.1, 0.0, logging.INFO), daemon=True)
    watcher.start()
    time.sleep(0.45)

    roster = caught.saying(" is on ")
    assert roster, "the roster said nothing at all"
    announced = [lvl for lvl, _ in roster if lvl == logging.INFO]
    quiet = [lvl for lvl, _ in roster if lvl == logging.DEBUG]
    assert announced, "the first tick was not announced"
    assert quiet, (
        "every tick was announced at the installed level, which is the 255 "
        "identical lines this changes")

    alive = caught.saying("nothing moved for")
    assert alive and all(lvl == logging.INFO for lvl, _ in alive), (
        "a tick with no news went silent; a thread sitting on one line for 400s "
        "is the event this apparatus exists for")
    assert "thread(s) where they were" in alive[-1][1]


def test_a_moved_thread_is_announced(caught):
    """What this must not cost: the tick where something moved is still news."""
    from core.observability import channels

    rosters = [
        [{"thread": "MainThread", "daemon": False, "on": "selectors.py:566 select"}],
        [{"thread": "MainThread", "daemon": False, "on": "selectors.py:566 select"}],
        [{"thread": "MainThread", "daemon": False, "on": "memory_agent.py:9355 _consolidate"}],
    ]
    ticks = iter(rosters)
    stock_threads, stock_running, stock_sleep = (
        channels.threads_now, channels.running_now, time.sleep)
    channels.threads_now = lambda: next(ticks)
    channels.running_now = lambda: []

    def one_tick_at_a_time(_):
        return None

    try:
        channels.time.sleep = one_tick_at_a_time
        try:
            channels._heartbeat(0.0, 0.0, logging.INFO)
        except StopIteration:
            pass
    finally:
        channels.time.sleep = stock_sleep
        channels.threads_now, channels.running_now = stock_threads, stock_running

    said = caught.saying(" is on ")
    assert [lvl for lvl, _ in said] == [logging.INFO, logging.DEBUG, logging.INFO], (
        "a thread that moved was not announced, or an unchanged tick was: %r"
        % (said,))
    assert "_consolidate" in said[-1][1]
