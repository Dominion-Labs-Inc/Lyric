#!/usr/bin/env python3
"""
Phase 5A: Task Creation Governance Tests
Using TestBase for MySQL logging
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add project root and tests directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tests"))

from test_base import TestBase
from core.agents.autonomous.task_queue import TaskQueue
from core.agents.autonomous.shared_types import Task, TaskType, TaskSource, Priority


class TestPhase5ATaskGovernance(TestBase):
    """Phase 5A: who bounds the creation of work, now that the queue holds no governance.

    These tests used to count a sliding window of autonomous tasks and "trigger
    governance" at the 20th. That mechanism was removed from the queue on
    2026-09-01: governance is a blanket authority applied where the substrate
    DECIDES to act (the Constitution), never reached up into from inside the
    queue. What bounds a flood of self-created work now is the queue's own
    admission control -- capacity, not permission -- and that is what is tested:
    discretionary autonomous work is deferred under backlog pressure, work a
    user directed never is, and pressure clears as work drains.

    EVERY QUEUE HERE IS BUILT WITHOUT PERSISTENCE. The old tests wrote each task
    into the durable queue, and 184 fixtures from a 2026-09-20 run were sitting
    there PENDING -- restored and run at the next boot. Removed 2026-09-26
    (snapshot `data/snapshots/phase5a_queue_residue_20260926T151108Z.json`).
    """

    def __init__(self):
        super().__init__(
            test_category="governance_phase5a",
            test_type="integration"
        )
        self.queue = None

    @staticmethod
    def _queue(**config):
        queue = TaskQueue({"persist": False, **config})
        assert queue._persistence_or_none() is None, "a test queue must never reach the durable queue"
        return queue

    @staticmethod
    def _task(task_id, source, description):
        return Task(id=task_id, type=TaskType.ANALYSIS, source=source,
                    description=description)

    @pytest.mark.asyncio
    async def test_1_normal_task_creation(self):
        """A single autonomous task on a quiet queue is admitted."""
        self.queue = self._queue()

        result = await self.queue.add_task(
            self._task("task_1", TaskSource.AUTONOMOUS, "Analyze system metrics"))

        assert result is True, "Task should be added"
        assert self.queue.get_queue_length() == 1, "Queue should have 1 task"
        assert self.queue.pressure() == "nominal"
        assert self.queue.metrics["tasks_deferred"] == 0

    @pytest.mark.asyncio
    async def test_2_user_defined_tasks_exempt(self):
        """Work a user directed is never deferred, even past the hard limit."""
        self.queue = self._queue(soft_limit=5, hard_limit=10)

        for i in range(30):
            source = [TaskSource.API, TaskSource.MANUAL, TaskSource.API][i % 3]
            result = await self.queue.add_task(
                self._task(f"user_task_{i}", source, f"User task {i}"))
            assert result is True, f"User task {i} should be added"

        assert self.queue.get_queue_length() == 30, "Should have 30 tasks"
        assert self.queue.pressure() == "hard", "the backlog is past the hard limit"
        assert self.queue.metrics["tasks_deferred"] == 0, "user-directed work is never deferred"

    @pytest.mark.asyncio
    async def test_3_bulk_autonomous_triggers_governance(self):
        """A burst of discretionary autonomous work is deferred once the backlog is under pressure."""
        self.queue = self._queue(soft_limit=5, hard_limit=10)

        admitted = 0
        for i in range(20):
            admitted += await self.queue.add_task(
                self._task(f"auto_{i}", TaskSource.AUTONOMOUS, f"Auto task {i}"))

        assert admitted == 5, f"only the work below the soft limit is admitted, got {admitted}"
        assert self.queue.get_queue_length() == 5
        assert self.queue.metrics["tasks_deferred"] == 15, "the rest is deferred, and counted"
        assert self.queue.pressure() == "soft"

        # An obligation is not discretionary: high-priority autonomous work still enters.
        urgent = await self.queue.add_task(
            self._task("auto_19", TaskSource.AUTONOMOUS, "20th task"), Priority.HIGH)
        assert urgent is True, "high-priority autonomous work is admitted under soft pressure"

    @pytest.mark.asyncio
    async def test_4_mixed_source_only_counts_autonomous(self):
        """Under pressure, only the discretionary autonomous work is deferred."""
        self.queue = self._queue(soft_limit=5, hard_limit=10)

        for i in range(8):
            await self.queue.add_task(self._task(f"user_{i}", TaskSource.MANUAL, f"User {i}"))
        autonomous = [await self.queue.add_task(
                          self._task(f"auto_{i}", TaskSource.AUTONOMOUS, f"Auto {i}"))
                      for i in range(5)]
        users_after = [await self.queue.add_task(
                           self._task(f"api_{i}", TaskSource.API, f"API {i}"))
                       for i in range(3)]

        assert not any(autonomous), "discretionary autonomous work is deferred under pressure"
        assert all(users_after), "user-directed work still enters"
        assert self.queue.get_queue_length() == 11, "8 + 3 user tasks, no autonomous"
        assert self.queue.metrics["tasks_deferred"] == 5

    @pytest.mark.asyncio
    async def test_5_window_cleanup(self):
        """Pressure clears as work drains, and autonomous work is admitted again."""
        self.queue = self._queue(soft_limit=3, hard_limit=10)

        for i in range(3):
            await self.queue.add_task(self._task(f"task_{i}", TaskSource.AUTONOMOUS, f"Task {i}"))
        assert self.queue.pressure() == "soft"
        deferred = await self.queue.add_task(
            self._task("task_3", TaskSource.AUTONOMOUS, "Task 3"))
        assert deferred is False, "deferred while the backlog is at the soft limit"

        assert await self.queue.get_next_task(timeout=0) is not None, "a worker draws one job"
        assert self.queue.pressure() == "nominal"
        admitted = await self.queue.add_task(
            self._task("new_task", TaskSource.AUTONOMOUS, "New task"))
        assert admitted is True, "admitted again once the backlog drained"

    async def run_all_tests(self):
        """Run all Phase 5A tests"""
        await self.start_session()

        await self.run_test(
            "test_1_normal_task_creation",
            self.test_1_normal_task_creation,
            metadata={
                "description": "A single autonomous task on a quiet queue is admitted",
                "expected_behavior": "Admitted at nominal pressure, nothing deferred",
                "tasks_added": 1
            }
        )

        await self.run_test(
            "test_2_user_defined_tasks_exempt",
            self.test_2_user_defined_tasks_exempt,
            metadata={
                "description": "User-directed work is never deferred, even past the hard limit",
                "expected_behavior": "All 30 admitted at hard pressure",
                "soft_limit": 5, "hard_limit": 10,
                "tasks_added": 30,
                "task_sources": ["API", "MANUAL"]
            }
        )

        await self.run_test(
            "test_3_bulk_autonomous_triggers_governance",
            self.test_3_bulk_autonomous_triggers_governance,
            metadata={
                "description": "A burst of discretionary autonomous work is deferred under pressure",
                "expected_behavior": "5 admitted, 15 deferred; high priority still admitted",
                "soft_limit": 5, "hard_limit": 10,
                "tasks_added": 21,
                "task_source": "AUTONOMOUS"
            }
        )

        await self.run_test(
            "test_4_mixed_source_only_counts_autonomous",
            self.test_4_mixed_source_only_counts_autonomous,
            metadata={
                "description": "Under pressure only discretionary autonomous work is deferred",
                "expected_behavior": "11 user tasks admitted, 5 autonomous deferred",
                "user_tasks": 11,
                "autonomous_tasks": 5
            }
        )

        await self.run_test(
            "test_5_window_cleanup",
            self.test_5_window_cleanup,
            metadata={
                "description": "Pressure clears as work drains",
                "expected_behavior": "Deferred at the soft limit, admitted again after a job is drawn",
                "tasks_added": 5
            }
        )

        await self.end_session()
        self.print_summary()


async def main():
    """Run Phase 5A tests"""
    tests = TestPhase5ATaskGovernance()
    await tests.run_all_tests()

    # Return exit code
    return 0 if tests.failed_tests == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
