"""Teaching mode: the recurring tiers a teaching session does not need are STOPPED, not slowed.

`LYRIC_TEACHING=1` is read once, in `core/main.py`, right after `start_coordination` registers the substrate's
seven recurring tiers. What it stops and what it keeps is `TEACHING_KEEPS`, and these check the three things that
would make the mode a lie: that a stopped tier is removed from the scheduler rather than retuned to fire rarely,
that the constitution and what makes teaching felt are kept, and that nothing is reported stopped that was never
scheduled.

No substrate and no store: the tiers are scheduled on a real `QueueAuthority` by the names the coordinator uses.
"""
import asyncio

import pytest

from core.agents.autonomous.queue_authority import QueueAuthority
from core.main import TEACHING_KEEPS, quiet_for_teaching


class _Coordinator:
    """What `quiet_for_teaching` needs of a coordinator: the one queue authority its tiers are scheduled on."""

    def __init__(self, queue):
        self.task_queue = queue


async def _nothing():
    return None


def _substrate(tiers=None):
    """A queue authority with the substrate's recurring tiers scheduled on it, by the coordinator's own names."""
    queue = QueueAuthority()
    for tier in (tiers if tiers is not None else TEACHING_KEEPS):
        queue.schedule_recurring(tier, _nothing, 60.0, "high")
    return _Coordinator(queue)


def test_the_tiers_a_teaching_session_does_not_need_are_gone_from_the_scheduler():
    """Stopped means removed: a tier left scheduled at a longer interval is the same substrate doing the same thing
    less often, which is not what the mode says it does."""
    coordinator = _substrate()
    stopped = quiet_for_teaching(coordinator)
    left = set(coordinator.task_queue.scheduled_jobs())
    assert stopped and all(stopped.values()), stopped
    for tier, keep in TEACHING_KEEPS.items():
        assert (tier in left) == keep, tier


def test_the_constitution_is_kept():
    """It judges acts, never language and never a taught fact; its record is a drain of judgements already made, and
    dropping one is a substrate that cannot answer for itself."""
    coordinator = _substrate()
    quiet_for_teaching(coordinator)
    left = set(coordinator.task_queue.scheduled_jobs())
    assert "constitution_record" in left
    assert "constitution_integrity" in left


def test_what_makes_teaching_felt_is_kept():
    """Both were made periodic so a teaching run is felt at all; stopped, teaching would be felt by nothing."""
    coordinator = _substrate()
    quiet_for_teaching(coordinator)
    left = set(coordinator.task_queue.scheduled_jobs())
    assert "epistemic_affect" in left
    assert "affect_refresh" in left


def test_a_tier_that_was_never_scheduled_is_not_reported_stopped():
    """Never faked either way: the mode says what it actually stopped."""
    coordinator = _substrate(["system_awareness"])
    stopped = quiet_for_teaching(coordinator)
    assert set(stopped) == {"system_awareness"}


def test_a_tier_nobody_named_is_left_running():
    """A tier added to the coordinator and not to `TEACHING_KEEPS` keeps running: the mode stops what it was told
    to stop and never guesses at a name it does not hold."""
    coordinator = _substrate(list(TEACHING_KEEPS) + ["something_new"])
    quiet_for_teaching(coordinator)
    assert "something_new" in set(coordinator.task_queue.scheduled_jobs())


def test_nothing_is_stopped_where_there_is_no_queue_to_stop_it_on():
    """It says so rather than claiming a quiet substrate it did not make."""
    class _Bare:
        task_queue = None

    assert quiet_for_teaching(_Bare()) == {}


@pytest.mark.parametrize("tier", sorted(TEACHING_KEEPS))
def test_every_tier_named_here_is_one_the_coordinator_schedules(tier):
    """The table names the substrate's own tiers: a name that drifts from `_register_idle_subsystems` would stop
    nothing and report nothing, and the mode would quietly do less than it says."""
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]
              / "core/agents/autonomous/autonomous_coordinator.py").read_text()
    assert f'("{tier}"' in source, tier


#: THE METHODS THE BOOT CALLS ON `LyricSystem`. Adding `quiet_for_teaching` and its table at column 0 inside the
#: class body ENDED THE CLASS: ten methods after that point became module-level functions, `core.main` still
#: parsed, and every check above still passed, because they import two names and never build the system. The
#: substrate then died eleven seconds into its boot on `'LyricSystem' object has no attribute
#: '_initialize_autonomous_coordinator'`, and died again in its own `finally` on `shutdown` for the same reason,
#: which hid the first (2026-11-02). A thing defined at module level has to BE at module level.
BOOT_CALLS = ("initialize", "start", "run", "shutdown", "_initialize_autonomous_coordinator",
              "_system_control_loop", "get_system_status", "open_senses", "close_senses")


@pytest.mark.parametrize("name", BOOT_CALLS)
def test_the_system_still_holds_the_methods_its_boot_calls(name):
    """`getattr` on the class, not on the module: a method that slipped out of the class body is still importable
    from `core.main` and would pass a test that only asked whether the name exists somewhere."""
    from core.main import LyricSystem
    held = getattr(LyricSystem, name, None)
    assert callable(held), f"LyricSystem.{name} is not a method of the class"


def test_quiet_for_teaching_is_module_level_and_not_a_method():
    """It is called from inside the class and must not be one of its attributes."""
    import core.main as m
    assert callable(m.quiet_for_teaching)
    assert not hasattr(m.LyricSystem, "quiet_for_teaching")
