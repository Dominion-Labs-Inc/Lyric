"""One queue for every running Lyric (`QueueAuthority.get_next_task`): while a worker is alive the Lyric it works for
draws no queued work, and leaves it to the workers; with none alive it draws its own; a worker always draws."""
import asyncio

from core.agents.autonomous.queue_authority import QueueAuthority
from core.agents.autonomous.shared_types import Priority, Task, TaskType


class _Store:
    """The durable queue, as far as drawing a job asks of it."""

    def __init__(self, workers):
        self.workers = workers

    async def workers_alive(self, lease_s):
        return self.workers

    async def claim_new(self, **written):
        return True

    async def claim_start(self, **written):
        return True

    async def claim_waiting(self, **asked):
        return None

    async def upsert(self, **written):
        return True


def _drawn(workers, monkeypatch, role=""):
    monkeypatch.setenv("LYRIC_ROLE", role)
    queue = QueueAuthority()
    queue._persistence = _Store(workers)

    async def run():
        await queue.add_task(Task(id="one_queue_job", type=TaskType.ANALYSIS, description="a job"), Priority.HIGH)
        return await queue.get_next_task(timeout=0)
    return asyncio.run(run())


def test_the_lyric_a_worker_works_for_leaves_it_the_work(monkeypatch):
    assert _drawn(1, monkeypatch) is None, "a worker is alive: its Lyric drew the job itself"


def test_with_no_worker_alive_the_lyric_runs_its_work(monkeypatch):
    drawn = _drawn(0, monkeypatch)
    assert drawn is not None and drawn.task.id == "one_queue_job"


def test_a_worker_draws_work_whatever_else_is_alive(monkeypatch):
    drawn = _drawn(2, monkeypatch, role="worker")
    assert drawn is not None and drawn.task.id == "one_queue_job"
