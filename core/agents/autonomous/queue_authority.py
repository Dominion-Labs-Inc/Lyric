#!/usr/bin/env python3
"""Queue Authority — the one owner of the substrate's queued, awaited, and
scheduled work.

The self (the autonomous coordinator — the sheriff, Lyric, the substrate) is a
WORKER: it pulls work and does it. It does NOT own the queue, the execution
pool, or the scheduler. Those are this authority's, so there is one place that
knows what work exists, what is running, and what is due.

Three kinds of job, one authority:
  1. WORK jobs   — ad-hoc tasks pushed on, pulled off by priority, run under a
                   concurrency limit. Admission control (backpressure) is the
                   queue's own metabolism: it refuses discretionary work when the
                   backlog grows so the substrate cannot invent work faster than
                   it can metabolise it.
  2. AWAIT jobs  — submit a coroutine and await THIS result (a future), or come
                   back and collect it later. What the agent factory needs. A
                   one-shot TIMED job is an await job with a delay.
  3. SCHEDULED   — recurring interval jobs (e.g. periodic maintenance/learning).
     jobs           Nothing schedules timed work on its own; it registers here.

THE CONSTITUTION IS NOT HERE. It is a blanket authority over the whole self —
internal affairs over the sheriff's office — not a call reached up into from
inside a sub-component. What is here is admission control, which is about
the QUEUE'S capacity, not about whether an action is permitted — a different
question, owned above.
"""

import asyncio
import inspect
import logging
import time
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple, Callable, Awaitable
from datetime import datetime, timedelta
from asyncio import PriorityQueue
from dataclasses import dataclass, field

from .shared_types import (Task, TaskStatus, Priority, TaskSource, TaskType,
                           SUBSTRATE_ACTOR)

logger = logging.getLogger(__name__)


# A job's time budget, owned by the queue authority (see `timeout_for`). The
# formula and two of its three factors live here:
#   * TASK TYPE base — how long that kind of work reasonably takes (below);
#   * SEVERITY — important/urgent work gets more room (below).
# The third factor, REASONING difficulty, is NOT declared here: it is the
# reasoning authority's MEASURED signal (NeuralSymbolicBridge.reasoning_difficulty),
# which the queue reads. The queue owns the algorithm; the reasoning authority
# owns how hard the thinking is. Keyed by TaskType/Priority value; unknown ->
# default.
_TASK_TYPE_BASE_S: Dict[str, float] = {
    "communication": 60.0,
    "research": 120.0, "validation": 180.0, "analysis": 180.0, "synthesis": 180.0,
    "planning": 300.0,
    "execution": 600.0, "learning": 600.0, "optimization": 600.0,
    "self_improvement": 1800.0,
}
_DEFAULT_TASK_BASE_S = 300.0

_SEVERITY_FACTOR: Dict[str, float] = {
    "critical": 1.5, "high": 1.25, "medium": 1.0, "low": 0.75,
}
_DEFAULT_SEVERITY_FACTOR = 1.0

#: Work still owed — queued, in flight, or waiting on something. The ONE
#: definition of "active": `active_tasks()` reads it, and the durable store
#: derives from it which rows boot restores (these) and which are history it
#: may prune (everything else).
ACTIVE_STATUSES = frozenset({
    TaskStatus.PLANNED, TaskStatus.PENDING, TaskStatus.IN_PROGRESS,
    TaskStatus.AWAITING_VERIFICATION, TaskStatus.BLOCKED,
})


class TaskPriority(Enum):
    """Heap-key priority (int-valued)."""
    CRITICAL = 4
    HIGH = 3
    MEDIUM = 2
    LOW = 1


@dataclass
class QueuedTask:
    """A work job on the queue, with its lifecycle and timing."""
    task: Task
    priority: TaskPriority
    added_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration: float = 0.0
    times_requeued: int = 0
    status: TaskStatus = TaskStatus.PENDING
    error_message: Optional[str] = None
    wait_time: float = 0.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task.id,
            'task_type': self.task.type.value,
            'task_description': self.task.description,
            'priority': self.priority.value,
            'status': self.status.value,
            'added_at': self.added_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'wait_time': self.wait_time,
            'times_requeued': self.times_requeued,
            'retry_count': self.retry_count,
            'error_message': self.error_message,
        }


@dataclass
class _PoolStats:
    total_submitted: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    active: int = 0
    peak_active: int = 0
    total_wait_time_sec: float = 0.0
    total_execution_time_sec: float = 0.0


@dataclass
class _ScheduledJob:
    """A recurring job the authority owns the cadence of."""
    name: str
    call: Callable[[], Awaitable[Any]]
    #: Seconds between runs.
    interval_s: float
    #: Next monotonic time this is due.
    next_due: float
    priority: str = "medium"
    last_run: Optional[float] = None
    runs: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    #: The run in flight, so the job is never started again on top of itself.
    running: Optional["asyncio.Future"] = None
    #: Times it came due while its last run was still going, and so did not start.
    skipped: int = 0


class QueueAuthority:
    """One authority for the substrate's queued, awaited, and scheduled work."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = {
            'max_queue_size': 1000,
            'max_retries': 1,
            # Sixty work jobs at once: the people the substrate works for (three
            # each at most -- the per-user cap is the substrate's, when it draws)
            # and its own work, under this one budget.
            'max_parallel': 60,
            'job_timeout_seconds': 300.0,
            **(config or {}),
        }

        # ── WORK QUEUE ──────────────────────────────────────────────────────
        self.queue: PriorityQueue = PriorityQueue()
        self.tasks_by_id: Dict[str, QueuedTask] = {}
        self.total_tasks_added = 0
        self._sequence = 0
        self.lock = asyncio.Lock()
        self.metrics: Dict[str, int] = {
            'tasks_completed': 0, 'tasks_failed': 0,
            'tasks_requeued': 0, 'tasks_deferred': 0,
            'tasks_already_queued': 0, 'tasks_cancelled': 0,
        }
        #: The work jobs running now, by id, while they run: what `cancel` stops.
        self._running_jobs: Dict[str, asyncio.Task] = {}
        #: Writes of a cancelled job's record, held until they finish.
        self._persisting: set = set()
        #: Who is told when a work job ENDS (completed, failed, partly done):
        #: handed the job, as a job is shown to its owner (`_job_view`), and the
        #: task. How a result is passed back without polling, as `submit`'s
        #: `on_complete` is for an await-job. A job cancelled is not announced:
        #: whoever cancelled it already knows.
        self._ended_handlers: List[Callable[[Dict[str, Any], Task], Any]] = []

        # Admission control (the queue's own metabolism — NOT the Constitution's).
        self.soft_limit = int(self.config.get('soft_limit', 25))
        self.hard_limit = int(self.config.get('hard_limit', 60))
        # Work that must never be refused, whatever the backlog. API/MANUAL are
        # user-directed; SYSTEM covers error-handler fixes.
        self.NON_DISCRETIONARY_SOURCES = {
            TaskSource.API, TaskSource.MANUAL, TaskSource.SYSTEM,
        }

        # ── EXECUTION POOL (folded in) ──────────────────────────────────────
        # TWO budgets, deliberately separate. WORK jobs (the substrate's acting
        # tasks) run under `max_parallel` — the acting cap. AWAIT/SCHEDULED jobs
        # (spawned agents, periodic maintenance/learning) run under a SEPARATE
        # background budget, so background work can never steal an acting slot
        # (the starvation the one-tier-per-cycle rule used to guard against).
        self.max_parallel = int(self.config['max_parallel'])
        self.bg_max_parallel = int(self.config.get('bg_max_parallel', 8))
        self._semaphore = asyncio.Semaphore(self.max_parallel)
        self._bg_semaphore = asyncio.Semaphore(self.bg_max_parallel)
        self._pool_stats = _PoolStats()
        self._pool_lock = asyncio.Lock()
        #: The reasoning authority, consulted (lazily) for the MEASURED
        #: reasoning-difficulty factor in `timeout_for`. The queue owns the
        #: timeout formula; the reasoning authority owns how hard the thinking is.
        self._reasoning: Any = None

        # PER-JOB TIMEOUT is the AUTHORITY'S to decide, and it depends on the job
        # — not a single flat number. How long a job may run is a scheduling
        # question (this authority's), computed from the task's base budget, how
        # hard the reasoning is, and a per-job difficulty. `timeout_for` combines
        # them; `_TIMEOUT_MIN/MAX` bound the result so no computation runs away.
        self._TIMEOUT_MIN = float(self.config.get('timeout_min_s', 30.0))
        self._TIMEOUT_MAX = float(self.config.get('timeout_max_s', 7200.0))

        # ── AWAIT JOBS ──────────────────────────────────────────────────────
        #: job_id -> the running asyncio task, until awaited/collected.
        self._await_jobs: Dict[str, asyncio.Task] = {}
        self._await_meta: Dict[str, Dict[str, Any]] = {}
        #: Metrics the health monitor reads (see get_statistics). Every count is
        #: real: submitted on submit, completed/failed when the job actually ends,
        #: delivered/delivery_failed for push handlers. No optimistic increments.
        self._await_metrics: Dict[str, int] = {
            "submitted": 0, "completed": 0, "failed": 0,
            "delivered": 0, "delivery_failed": 0, "cancelled": 0,
        }

        # ── SCHEDULER ───────────────────────────────────────────────────────
        self._scheduled: Dict[str, _ScheduledJob] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_tick_s = float(self.config.get('scheduler_tick_s', 1.0))
        self._running = False
        #: Real counters — a fire is counted when the loop actually dispatches a
        #: due job; an error is counted when that job's coroutine raised. Never
        #: incremented optimistically, so the health monitor reads the truth.
        self._scheduler_metrics = {"fired": 0, "errors": 0, "cancelled": 0, "skipped": 0}

        # ── PERSISTENCE ─────────────────────────────────────────────────────
        # Accepted-but-unfinished work must survive a restart. Every lifecycle
        # mutation mirrors to `unified.task_queue`; boot rehydrates what was
        # owed. A write failure is logged + counted, never fatal to the live
        # queue (durability degrades VISIBLY, it does not fake success).
        self._persist_enabled = bool(self.config.get('persist', True))
        self._persistence: Any = None
        self._restoring = False
        self._persist_metrics = {"writes": 0, "errors": 0,
                                 "restored": 0, "restarted": 0}

    # ══════════════════════════════════════════════════════════════════════
    # WORK QUEUE — admission, add, pull, lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def pressure(self) -> str:
        """Backlog pressure: 'nominal' | 'soft' | 'hard'."""
        depth = self.queue.qsize()
        if depth >= self.hard_limit:
            return "hard"
        if depth >= self.soft_limit:
            return "soft"
        return "nominal"

    def _is_discretionary(self, task: Task, priority: Priority) -> bool:
        if getattr(task, "source", None) in self.NON_DISCRETIONARY_SOURCES:
            return False
        return priority not in (Priority.CRITICAL, Priority.HIGH)

    def admits(self, task: Task, priority: Priority = Priority.MEDIUM) -> Tuple[bool, str]:
        """Whether the queue can take this now, given the backlog. Capacity, not
        permission: permission is the Constitution's, decided above the queue."""
        level = self.pressure()
        if level == "nominal":
            return True, "nominal"
        discretionary = self._is_discretionary(task, priority)
        if level == "soft":
            if discretionary:
                return False, (f"soft limit ({self.queue.qsize()}/{self.soft_limit}): "
                               "discretionary work deferred")
            return True, "soft: obligation admitted"
        # hard
        if discretionary or priority not in (Priority.CRITICAL, Priority.HIGH):
            if getattr(task, "source", None) not in self.NON_DISCRETIONARY_SOURCES:
                return False, (f"hard limit ({self.queue.qsize()}/{self.hard_limit}): "
                               "only safety, remediation, user-directed and critical admitted")
        return True, "hard: obligation admitted"

    async def add_task(self, task: Task, priority: Priority = Priority.MEDIUM) -> bool:
        """Push a work job. Returns True when the job is queued, False if
        admission (backpressure) refused it or the queue is at capacity. The
        Constitution is not here — it is a blanket authority applied where the
        substrate DECIDES to create work.

        ONE COPY PER ID. A job whose id is already owed — queued or in flight
        here, or held by another living instance of the model — is not queued
        again: that returns True (the work IS queued, once) and counts
        `tasks_already_queued`. It is not a refusal, so a caller does not end
        the pursuit the first copy is serving. A FINISHED id may be queued again
        as new work. Before this, a second add put a second copy on the heap:
        the job ran twice, and its completed record flipped back to in_progress."""
        async with self.lock:
            held = self.tasks_by_id.get(task.id)
            if held is not None and held.status in ACTIVE_STATUSES:
                return self._already_queued(task.id, f"{held.status.value} here")
            admitted, why = self.admits(task, priority)
            if not admitted:
                self.metrics['tasks_deferred'] += 1
                logger.info("[BACKPRESSURE] refused %s (%s/%s): %s", task.id,
                            getattr(task.type, 'value', '?'),
                            getattr(task.source, 'value', '?'), why)
                return False
            if self.queue.qsize() >= self.config['max_queue_size']:
                logger.warning("queue at capacity; refusing %s", task.id)
                return False
            tp = self._priority_to_task_priority(priority)
            queued = QueuedTask(task=task, priority=tp, added_at=datetime.now())
            # Held here from this moment, so a second add of the same id while
            # the durable write below is in flight finds it.
            self.tasks_by_id[task.id] = queued

        if not await self._persist_new(queued):
            async with self.lock:
                if self.tasks_by_id.get(task.id) is queued:
                    if held is not None:
                        self.tasks_by_id[task.id] = held      # its finished record
                    else:
                        del self.tasks_by_id[task.id]
            return self._already_queued(task.id, "held by another instance")

        async with self.lock:
            self._sequence += 1
            await self.queue.put((-tp.value, self._sequence, queued))
            self.total_tasks_added += 1
        logger.info("queued %s (priority=%s, depth=%d)", task.id, tp.value, self.queue.qsize())
        return True

    def _already_queued(self, task_id: str, where: str) -> bool:
        self.metrics['tasks_already_queued'] += 1
        logger.info("%s is already queued (%s); not queued twice", task_id, where)
        return True

    async def _take_first(self, timeout: Optional[float]):
        """The first ready heap entry that is still owed, or None. A job
        cancelled while it waited is let go of here, never drawn."""
        while True:
            first = await self._take_one(timeout)
            if first is None or first[2].status != TaskStatus.CANCELLED:
                return first

    async def _take_one(self, timeout: Optional[float]):
        """The first ready heap entry, or None. `timeout=None` waits for work, a
        positive timeout waits that long, `timeout <= 0` does not wait at all.

        Zero is handled by `get_nowait`, not `wait_for(get(), 0)`: wait_for with
        a zero timeout cancels the get before it ever runs, so a queue holding
        work read as empty."""
        if timeout is None:
            return await self.queue.get()
        if timeout <= 0:
            try:
                return self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return None
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def get_next_task(self, timeout: float = None,
                            skip_actors: "Optional[frozenset]" = None
                            ) -> Optional[QueuedTask]:
        """Pull the highest-priority work job; None on timeout/empty. This is how
        the WORKER (the coordinator) draws from the authority — the ONE pull.
        `timeout=0` is the non-blocking form: take what is ready now, never wait.

        `skip_actors` are actors already at their per-user concurrency cap: the
        highest-priority job whose actor is NOT one of them is returned, so one
        user's backlog cannot monopolise the pool and several users each run up to
        their cap concurrently. The substrate's own actor is never in this set (its
        autonomous work is bounded only by the global ceiling, not the per-user cap).
        When every ready job belongs to a capped actor, returns None — those jobs
        stay queued, in priority order, for a later cycle."""
        first = await self._take_first(timeout)
        if first is None:
            return None
        if not skip_actors:
            # fast path: the one job popped is the one returned
            queued = first[2]
            self._mark_started(queued)
            await self._persist_queued(queued)
            return queued

        # actor-aware: take what is ready (priority order), pick the first job whose
        # actor is not capped, and put the rest back unchanged (priority preserved).
        items = [first]
        while True:
            try:
                item = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item[2].status != TaskStatus.CANCELLED:
                items.append(item)
        chosen_idx = None
        for idx, (_, _, q) in enumerate(items):
            if getattr(q.task, "actor", SUBSTRATE_ACTOR) not in skip_actors:
                chosen_idx = idx
                break
        for i, it in enumerate(items):
            if i != chosen_idx:
                await self.queue.put(it)                 # same tuple -> priority kept
        if chosen_idx is None:
            return None
        queued = items[chosen_idx][2]
        self._mark_started(queued)
        await self._persist_queued(queued)
        return queued

    @staticmethod
    def _mark_started(queued: QueuedTask) -> None:
        queued.status = TaskStatus.IN_PROGRESS
        queued.started_at = datetime.now()
        queued.wait_time = ((queued.started_at - queued.added_at).total_seconds()
                            if queued.added_at else 0.0)

    def on_work_ended(self, handler: Callable[[Dict[str, Any], Task], Any]) -> None:
        """Be told when a work job ends: `handler(job, task)`, sync or async, once
        it is recorded as ended. A handler that raises is logged and never
        changes how the job ended."""
        self._ended_handlers.append(handler)

    async def _announce_ended(self, queued: "QueuedTask") -> None:
        job = self._job_view(queued)
        for handler in list(self._ended_handlers):
            try:
                outcome = handler(job, queued.task)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception as error:
                logger.error("a handler of %s's ending raised: %s", queued.task.id, error)

    async def mark_completed(self, task_id: str, result: Dict[str, Any]) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            logger.warning("mark_completed: %s not found", task_id)
            return False
        if queued.status == TaskStatus.CANCELLED:
            logger.info("mark_completed: %s was cancelled; its record stays so", task_id)
            return False
        async with self.lock:
            queued.status = TaskStatus.COMPLETED
            queued.completed_at = datetime.now()
            queued.task.result = result
            self.metrics['tasks_completed'] += 1
        await self._persist_queued(queued)
        await self._announce_ended(queued)
        return True

    async def mark_failed(self, task_id: str, error: str) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            logger.warning("mark_failed: %s not found", task_id)
            return False
        if queued.status == TaskStatus.CANCELLED:
            logger.info("mark_failed: %s was cancelled; its record stays so", task_id)
            return False
        async with self.lock:
            queued.status = TaskStatus.FAILED
            queued.completed_at = datetime.now()
            queued.error_message = error
            self.metrics['tasks_failed'] += 1
        await self._persist_queued(queued)
        logger.warning("task %s failed: %s", task_id, error)
        await self._announce_ended(queued)
        return True

    async def requeue_task(self, task_id: str) -> bool:
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            return False
        if queued.retry_count >= self.config['max_retries']:
            logger.warning("task %s exceeded max retries", task_id)
            return False
        async with self.lock:
            queued.retry_count += 1
            queued.times_requeued += 1
            queued.status = TaskStatus.PENDING
            queued.started_at = None
            self._sequence += 1
            await self.queue.put((-queued.priority.value, self._sequence, queued))
            self.metrics['tasks_requeued'] += 1
        await self._persist_queued(queued)
        return True

    def active_tasks(self) -> List[Task]:
        """The work still owed: every job queued, in flight, or waiting
        (ACTIVE_STATUSES). The one answer to "what is active?" — whether a given
        task is still owed, how many are, which explorations are running — so no
        caller keeps its own list or its own idea of which statuses count. A
        FAILED/COMPLETED job is history, not active."""
        return [q.task for q in self.tasks_by_id.values()
                if q.task is not None and q.status in ACTIVE_STATUSES]

    def get_queue_length(self) -> int:
        return self.queue.qsize()

    async def result_for(self, task_id: str, *, actor: str) -> Dict[str, Any]:
        """The status and outcome of `task_id` — the ONE read of a job's status,
        and ONLY for the actor it belongs to (the substrate reads its own work
        with SUBSTRATE_ACTOR).

        A user may read the result of THEIR OWN job, never another's. A task owned
        by a different actor (or absent) reads as `not_found` — identical to a real
        miss, so result-polling cannot enumerate other actors' work. Returns
        status, plus `result` when COMPLETED or `error` when FAILED."""
        queued = self.tasks_by_id.get(task_id)
        if queued is None:
            # Not held here: with several instances of the model the job may be
            # held -- or have been finished -- by another. The stored row is
            # the one record of it, scoped by the same actor rule.
            p = self._persistence_or_none()
            stored = await p.load_one(task_id) if p is not None else None
            if stored is None or getattr(stored["task"], "actor", None) != actor:
                return {"task_id": task_id, "status": "not_found"}
            out = {"task_id": task_id, "status": stored["status"]}
            if stored["status"] == TaskStatus.COMPLETED.value:
                out["result"] = stored["result"]
            elif stored["status"] == TaskStatus.FAILED.value:
                out["error"] = stored["error"]
            return out
        if queued.task is None or getattr(queued.task, "actor", None) != actor:
            return {"task_id": task_id, "status": "not_found"}
        out = {"task_id": task_id, "status": queued.status.value}
        if queued.status == TaskStatus.COMPLETED:
            out["result"] = queued.task.result
        elif queued.status == TaskStatus.FAILED:
            out["error"] = queued.error_message
        return out

    @staticmethod
    def _job_view(queued: "QueuedTask") -> Dict[str, Any]:
        """One work job as its owner may see it: what was asked, where it stands,
        how it ended, and when they were told how it ended."""
        return {"task_id": queued.task.id, "asked": queued.task.description,
                "status": queued.status.value,
                "added_at": queued.added_at.isoformat() if queued.added_at else None,
                "completed_at": queued.completed_at.isoformat() if queued.completed_at else None,
                "result": queued.task.result, "error": queued.error_message,
                "read": (queued.task.metadata or {}).get("read"),
                "told_at": (queued.metadata or {}).get("told_at")}

    async def work_of(self, actor: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        """The work `actor` asked for, newest first: each job's id, what was
        asked, where it stands, how it ended, and when they were told how it
        ended (`told_at`). ONLY the actor's own, as `result_for` reads. This
        instance's jobs from what it holds; any other from the stored record,
        since another instance of the model may hold or have finished it."""
        out: Dict[str, Dict[str, Any]] = {
            q.task.id: self._job_view(q) for q in self.tasks_by_id.values()
            if q.task is not None and getattr(q.task, "actor", None) == actor}
        p = self._persistence_or_none()
        if p is not None:
            for row in await p.jobs_of(actor, limit=limit):
                out.setdefault(row["task_id"], row)
        return sorted(out.values(), key=lambda j: j.get("added_at") or "", reverse=True)[:limit]

    async def mark_told(self, task_id: str) -> None:
        """Its owner has been told how this job ended: kept with the job's own
        record, so they are told once, whichever instance tells them."""
        at = datetime.now().isoformat()
        queued = self.tasks_by_id.get(task_id)
        if queued is not None:
            queued.metadata = {**(queued.metadata or {}), "told_at": at}
            await self._persist_queued(queued)
            return
        p = self._persistence_or_none()
        if p is not None:
            await p.mark_told(task_id, at)

    async def get_failed_tasks(self, limit: int = 10) -> List[Task]:
        """Recently failed work jobs, most recent first — context for the
        substrate's intrinsic goal formation (what went wrong lately)."""
        failed = [q.task for q in self.tasks_by_id.values()
                  if q.status == TaskStatus.FAILED and q.task is not None]
        failed.sort(key=lambda t: getattr(t, 'completed_at', None) or datetime.min,
                    reverse=True)
        return failed[:limit]

    def get_metrics(self) -> Dict[str, Any]:
        return {
            'total_tasks_added': self.total_tasks_added,
            'current_queue_size': self.queue.qsize(),
            **self.metrics,
        }

    async def recent_outcomes(self, limit: int) -> Optional[Tuple[int, int]]:
        """How the newest `limit` finished work jobs ended, as (finished, failed), read from the durable history so
        a restart does not forget them. None with no durable store: there is no recent history to read, and this
        process's own counts are not it. A store error raises."""
        p = self._persistence_or_none()
        if p is None:
            return None
        statuses = await p.recent_finished(limit)
        return len(statuses), sum(1 for status in statuses if status == TaskStatus.FAILED.value)

    def _priority_to_task_priority(self, priority: Priority) -> TaskPriority:
        mapping = {
            Priority.CRITICAL: TaskPriority.CRITICAL, Priority.HIGH: TaskPriority.HIGH,
            Priority.MEDIUM: TaskPriority.MEDIUM, Priority.LOW: TaskPriority.LOW,
        }
        if priority in mapping:
            return mapping[priority]
        name = getattr(priority, "name", None)
        if name and name in TaskPriority.__members__:
            return TaskPriority[name]
        logger.warning("unmappable priority %r; defaulting MEDIUM", priority)
        return TaskPriority.MEDIUM

    # ══════════════════════════════════════════════════════════════════════
    # PERSISTENCE — the durable backing (unified.task_queue)
    # ══════════════════════════════════════════════════════════════════════

    def _persistence_or_none(self):
        """The lazy persistence store, or None when persistence is disabled.
        Lazy because the authority singleton is built before the DB is up."""
        if not self._persist_enabled:
            return None
        if self._persistence is None:
            from .queue_persistence import QueuePersistence
            self._persistence = QueuePersistence()
        return self._persistence

    #: How long an instance may go without a heartbeat before the work it owns
    #: may be claimed by another (config `instance_lease_s`).
    INSTANCE_LEASE_S = 120.0
    #: How often this instance says it is alive (config `heartbeat_interval_s`).
    HEARTBEAT_INTERVAL_S = 30.0

    async def heartbeat(self) -> None:
        """Scheduled: renew this instance's lease on the work it owns."""
        p = self._persistence_or_none()
        if p is not None:
            await p.heartbeat()

    @staticmethod
    def _queued_meta(queued: "QueuedTask") -> Dict[str, Any]:
        """The QueuedTask timing/lifecycle fields, as a JSON-native dict, so a
        rehydrated job keeps its wait/retry history rather than resetting."""
        return {
            "added_at": queued.added_at.isoformat() if queued.added_at else None,
            "started_at": queued.started_at.isoformat() if queued.started_at else None,
            "completed_at": queued.completed_at.isoformat() if queued.completed_at else None,
            "retry_count": queued.retry_count,
            "times_requeued": queued.times_requeued,
            "error_message": queued.error_message,
            "wait_time": queued.wait_time,
            "metadata": queued.metadata,
        }

    async def _persist_queued(self, queued: "QueuedTask") -> None:
        """Mirror one work job's CURRENT full state to the durable row. Non-fatal
        by contract: a DB error is logged with the task id and counted, and the
        in-memory queue is untouched — the substrate keeps working, and the
        durability gap is visible in `persist_errors`, not hidden."""
        p = self._persistence_or_none()
        if p is None or self._restoring:
            return
        try:
            await p.upsert(
                task=queued.task,
                status=queued.status.value,
                priority=queued.priority.value,
                result=queued.task.result,
                error=queued.error_message,
                queued_meta=self._queued_meta(queued),
            )
            self._persist_metrics["writes"] += 1
        except Exception as e:
            self._persist_metrics["errors"] += 1
            logger.error("queue persist failed for %s (%s): %s",
                         queued.task.id, queued.status.value, e)

    async def _persist_new(self, queued: "QueuedTask") -> bool:
        """Write a NEW job's durable row and take it for this instance — unless
        another living instance already owes the same id, in which case nothing
        is written and False is returned (the job is queued there). A plain
        upsert here took the row over and both instances ran the job.

        A store error keeps the non-fatal contract: logged with the task id,
        counted in `persist_errors`, and the job is queued here anyway — whether
        another instance holds it could not be read, and that is visible in the
        counter, not hidden."""
        p = self._persistence_or_none()
        if p is None or self._restoring:
            return True
        try:
            written = await p.claim_new(
                task=queued.task,
                status=queued.status.value,
                priority=queued.priority.value,
                result=queued.task.result,
                error=queued.error_message,
                queued_meta=self._queued_meta(queued),
                lease_s=float(self.config.get('instance_lease_s', self.INSTANCE_LEASE_S)),
            )
        except Exception as e:
            self._persist_metrics["errors"] += 1
            logger.error("queue persist failed for new job %s: %s", queued.task.id, e)
            return True
        if written:
            self._persist_metrics["writes"] += 1
        return written

    async def restore_pending(self) -> Dict[str, int]:
        """Rehydrate accepted-but-unfinished work from the durable store on boot.

        PENDING/PLANNED/BLOCKED/AWAITING_VERIFICATION jobs re-enter the queue as
        they were. IN_PROGRESS jobs were interrupted mid-run by the restart —
        they are reset to PENDING and re-queued (restart the interrupted work),
        and their durable row is corrected to PENDING so a second crash can't
        double-count them. Terminal jobs stay as history and are not restored.
        Idempotent: re-running finds nothing new because restored rows are no
        longer IN_PROGRESS.

        MANY INSTANCES, ONE QUEUE TABLE. Only work no living instance holds is
        restored, and it is CLAIMED atomically (`claim_restorable`): this read
        every owed row, so each instance that booted re-queued the others' work
        and reset their running jobs to PENDING -- a task could run twice. An
        IN_PROGRESS job is restarted only when its owner has stopped."""
        p = self._persistence_or_none()
        if p is None:
            return {"restored": 0, "restarted": 0}
        self._restoring = True
        restored = restarted = 0
        try:
            await p.heartbeat()     # alive before claiming, so no one claims ours
            rows = await p.claim_restorable(
                float(self.config.get('instance_lease_s', self.INSTANCE_LEASE_S)))
            for r in rows:
                task = r["task"]
                held = self.tasks_by_id.get(task.id)
                if held is not None and held.status in ACTIVE_STATUSES:
                    continue    # already owed here; not restored a second time
                interrupted = (r["status"] == TaskStatus.IN_PROGRESS.value)
                if interrupted:
                    task.status = TaskStatus.PENDING
                # add_task skips its own persist while _restoring is set (the row
                # already exists); admission still applies.
                accepted = await self.add_task(task, priority=task.priority)
                if not accepted:
                    logger.warning("restore: %s not re-admitted (backpressure)", task.id)
                    continue
                restored += 1
                if interrupted:
                    restarted += 1
                    # Correct the durable row so it reflects the re-queue.
                    await p.update_status(task.id, TaskStatus.PENDING.value)
            self._persist_metrics["restored"] = restored
            self._persist_metrics["restarted"] = restarted
            logger.info("queue restore: %d rehydrated (%d interrupted -> restarted)",
                        restored, restarted)
        except Exception as e:
            logger.error("queue restore failed: %s", e)
        finally:
            self._restoring = False
        return {"restored": restored, "restarted": restarted}

    async def prune_history(self, keep_last: Optional[int] = None) -> int:
        """Bound the durable history: keep the newest `keep_last` finished rows
        (config `history_keep_last`, default 500), delete the rest. Returns how
        many were deleted; 0 when there is no durable store. Scheduled by
        `start()` as the recurring `queue_history_prune` job. A store error
        raises, so the scheduler records it against the job by name — it is not
        reported as "nothing to prune"."""
        p = self._persistence_or_none()
        if p is None:
            return 0
        keep = int(keep_last if keep_last is not None
                   else self.config.get('history_keep_last', 500))
        deleted = await p.prune_terminal(keep_last=keep)
        if deleted:
            logger.info("queue history pruned: %d finished row(s) beyond the newest %d",
                        deleted, keep)
        return deleted

    # ══════════════════════════════════════════════════════════════════════
    # EXECUTION POOL (folded in) — concurrency-limited running
    # ══════════════════════════════════════════════════════════════════════

    def _reasoning_difficulty(self, reasoning_type: Any) -> float:
        """The reasoning-difficulty factor — the reasoning authority's MEASURED
        signal (B), not a queue-local table. Sourced lazily; if the reasoning
        authority is unavailable, a neutral 1.0 (never a fabricated number)."""
        if reasoning_type is None:
            return 1.0
        try:
            if self._reasoning is None:
                from core.reasoning.neural_bridge import get_neural_bridge
                self._reasoning = get_neural_bridge()
            return float(self._reasoning.reasoning_difficulty(reasoning_type))
        except Exception:
            return 1.0

    def timeout_for(self, *, reasoning_type: Any = None, task_type: Any = None,
                    severity: Any = None, difficulty: float = 1.0) -> float:
        """This job's time budget, in seconds — the AUTHORITY'S formula:

            base(task_type) × reasoning_difficulty(reasoning_type)
                            × severity(priority) × difficulty        (clamped)

        base and severity are the queue's; reasoning_difficulty is the reasoning
        authority's MEASURED signal (the queue asks for it). A research task with
        simple reasoning finishes fast; a critical self-improvement (learning)
        task doing hard causal reasoning gets far longer. No flat number lives here.
        """
        base = _TASK_TYPE_BASE_S.get(
            str(getattr(task_type, "value", task_type) or "").strip().lower(),
            _DEFAULT_TASK_BASE_S)
        reasoning = self._reasoning_difficulty(reasoning_type)
        sev = _SEVERITY_FACTOR.get(
            str(getattr(severity, "value", severity) or "").strip().lower(),
            _DEFAULT_SEVERITY_FACTOR)
        budget = base * reasoning * sev * max(0.1, float(difficulty or 1.0))
        return max(self._TIMEOUT_MIN, min(self._TIMEOUT_MAX, budget))

    async def execute(self, job_id: str, func: Callable[..., Awaitable[Any]],
                      *args, background: bool = False,
                      timeout: Optional[float] = None,
                      reasoning_type: Any = None, task_type: Any = None,
                      severity: Any = None, difficulty: float = 1.0, **kwargs) -> Any:
        """Run `func` under a concurrency limit + a per-job timeout the AUTHORITY
        decides. `background=False` (work jobs) uses the acting-cap budget;
        `background=True` (await/scheduled) uses the separate background budget so
        it can't steal an acting slot. `timeout` may be passed explicitly, else it
        is computed from reasoning/task/severity/difficulty via `timeout_for`. The
        one place concurrent execution is bounded — no private pools."""
        semaphore = self._bg_semaphore if background else self._semaphore
        job_timeout = timeout if timeout is not None else self.timeout_for(
            reasoning_type=reasoning_type, task_type=task_type,
            severity=severity, difficulty=difficulty)
        # A WORK JOB IS HELD BY WHAT RUNS IT, from the moment it waits for a
        # slot, so `cancel` can stop it wherever it is.
        if not background and asyncio.current_task() is not None:
            self._running_jobs[job_id] = asyncio.current_task()
        try:
            return await self._execute_held(job_id, func, args, kwargs, semaphore, job_timeout)
        except asyncio.TimeoutError:
            # The authority set the time and ended the job, so its record says it
            # failed and why, and whoever waits on it is told. Left alone, the
            # record said "in progress" for good: no one was told, and the next
            # boot ran it again.
            if not background:
                await self.mark_failed(job_id, f"timed out after {job_timeout:.0f}s")
            raise
        finally:
            if not background:
                self._running_jobs.pop(job_id, None)

    async def _execute_held(self, job_id: str, func: Callable[..., Awaitable[Any]],
                            args: tuple, kwargs: Dict[str, Any], semaphore: asyncio.Semaphore,
                            job_timeout: float) -> Any:
        """`execute`'s run: under the semaphore, within the job's timeout."""
        wait_start = time.time()
        async with semaphore:
            wait = time.time() - wait_start
            async with self._pool_lock:
                self._pool_stats.total_submitted += 1
                self._pool_stats.active += 1
                self._pool_stats.peak_active = max(self._pool_stats.peak_active,
                                                   self._pool_stats.active)
                self._pool_stats.total_wait_time_sec += wait
            exec_start = time.time()
            try:
                # Accept both coroutine functions and plain callables — a
                # scheduled tier or job may be sync (e.g. a cheap prune). Only an
                # awaitable goes through wait_for (the timeout applies to async
                # work); a sync callable has already run by the time it returns.
                call_result = func(*args, **kwargs)
                if inspect.isawaitable(call_result):
                    result = await asyncio.wait_for(call_result, timeout=job_timeout)
                else:
                    result = call_result
                async with self._pool_lock:
                    self._pool_stats.total_completed += 1
                    self._pool_stats.active -= 1
                    self._pool_stats.total_execution_time_sec += time.time() - exec_start
                return result
            except asyncio.TimeoutError:
                async with self._pool_lock:
                    self._pool_stats.total_timeout += 1
                    self._pool_stats.active -= 1
                logger.error("job %s timed out after %.0fs", job_id, job_timeout)
                raise
            except asyncio.CancelledError:
                # STOPPED, not failed: the slot is given back and the stop goes on.
                self._pool_stats.active -= 1
                raise
            except Exception:
                async with self._pool_lock:
                    self._pool_stats.total_failed += 1
                    self._pool_stats.active -= 1
                raise

    def configure(self, config: Dict[str, Any]) -> None:
        """Settings given after the authority exists, put in force.

        The one authority is made by whoever reaches it first, and at boot that
        can be a faculty registering its recurring job, with no settings. The
        substrate's own settings, given after, must still be the ones in force,
        or its acting budget is silently the default. The acting budget changes
        only while no work job runs: a running job holds the budget it started
        under."""
        self.config.update(config)
        size = int(self.config['max_parallel'])
        if size != self.max_parallel:
            if self._running_jobs:
                raise RuntimeError(f"the acting budget changes only while no work runs; "
                                   f"{len(self._running_jobs)} work job(s) running")
            self.max_parallel = size
            self._semaphore = asyncio.Semaphore(size)

    def pool_stats(self) -> Dict[str, Any]:
        s = self._pool_stats
        return {
            "max_parallel": self.max_parallel, "active": s.active,
            "peak_active": s.peak_active, "total_submitted": s.total_submitted,
            "total_completed": s.total_completed, "total_failed": s.total_failed,
            "total_timeout": s.total_timeout,
            "avg_wait_time_sec": (s.total_wait_time_sec / s.total_submitted
                                  if s.total_submitted else 0.0),
            "avg_execution_time_sec": (s.total_execution_time_sec / s.total_completed
                                       if s.total_completed else 0.0),
        }

    # ══════════════════════════════════════════════════════════════════════
    # AWAIT JOBS — submit and await THIS result (or collect later)
    # ══════════════════════════════════════════════════════════════════════

    def submit(self, coro_factory: Callable[[], Awaitable[Any]], *,
               name: str = "", job_id: Optional[str] = None,
               on_complete: Optional[Callable[[Dict[str, Any]], Any]] = None,
               delay_s: float = 0.0) -> str:
        """Submit a coroutine to run once (through the pool, on the BACKGROUND
        budget) and return a job_id.

        `delay_s` makes it a one-shot TIMED job: it runs once after that many
        seconds. The wait holds no pool slot, and `cancel(job_id)` before it
        runs means it never does. Its result comes back like any other.

        TWO ways the result gets back to whoever wanted it — pick one:
          * PULL — no `on_complete`: the owner `await_result(id)`s it, or
            `collect_ready()`s it later. The result stays until taken.
          * PUSH — `on_complete(outcome)`: when the job ends, the authority
            hands the outcome to that handler and RETIRES the job. This is how a
            result is passed back to the substrate without it polling. The
            handler may be sync or async; if it raises, that is logged and
            counted (delivery_failed) — never swallowed into a false success.
        `outcome` is always {job_id, name, result, error}: `error` set means the
        job failed (honest — never reported as a result).
        """
        import uuid
        jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
        self._await_metrics["submitted"] += 1

        async def _run():
            if delay_s > 0:
                await asyncio.sleep(delay_s)   # outside the pool: no slot held
            return await self.execute(jid, coro_factory, background=True)

        if on_complete is None:
            task = asyncio.ensure_future(_run())
        else:
            async def _deliver():
                outcome = {"job_id": jid, "name": name, "result": None, "error": None}
                try:
                    outcome["result"] = await _run()
                    self._await_metrics["completed"] += 1
                except Exception as e:
                    outcome["error"] = str(e)
                    self._await_metrics["failed"] += 1
                    logger.error("await-job %s (%s) failed: %s", jid, name, e)
                try:
                    r = on_complete(outcome)
                    if asyncio.iscoroutine(r):
                        await r
                    self._await_metrics["delivered"] += 1
                except Exception as e:
                    self._await_metrics["delivery_failed"] += 1
                    logger.error("await-job %s completion handler raised: %s", jid, e)
                finally:
                    self._await_jobs.pop(jid, None)
                    self._await_meta.pop(jid, None)
                return outcome
            task = asyncio.ensure_future(_deliver())

        self._await_jobs[jid] = task
        self._await_meta[jid] = {"name": name, "submitted_at": datetime.now(),
                                 "push": on_complete is not None,
                                 "delay_s": delay_s}
        return jid

    async def await_result(self, job_id: str) -> Dict[str, Any]:
        """Block until this PULL job returns; hand back {result} or {error}
        (honest — a failure is never returned as a result). Removes it. An
        unknown id is reported as such, not faked."""
        task = self._await_jobs.get(job_id)
        if task is None:
            return {"job_id": job_id, "name": None, "result": None,
                    "error": "unknown job id (never submitted, already taken, "
                             "or push-delivered)"}
        meta = self._await_meta.get(job_id, {})
        try:
            result = await task
            self._await_metrics["completed"] += 1
            out = {"job_id": job_id, "name": meta.get("name"),
                   "result": result, "error": None}
        except Exception as e:
            self._await_metrics["failed"] += 1
            out = {"job_id": job_id, "name": meta.get("name"),
                   "result": None, "error": str(e)}
        self._await_jobs.pop(job_id, None)
        self._await_meta.pop(job_id, None)
        return out

    def collect_ready(self) -> List[Dict[str, Any]]:
        """Take every PULL job that has returned since the last collect, without
        blocking — so the worker can keep going and reconcile later. Push jobs
        (on_complete) never appear here; they were delivered + retired already."""
        ready: List[Dict[str, Any]] = []
        for jid in [j for j, t in self._await_jobs.items() if t.done()]:
            task = self._await_jobs.pop(jid)
            meta = self._await_meta.pop(jid, {})
            try:
                ready.append({"job_id": jid, "name": meta.get("name"),
                              "result": task.result(), "error": None})
                self._await_metrics["completed"] += 1
            except Exception as e:
                ready.append({"job_id": jid, "name": meta.get("name"),
                              "result": None, "error": str(e)})
                self._await_metrics["failed"] += 1
        return ready

    def await_pending(self) -> List[str]:
        return [j for j, t in self._await_jobs.items() if not t.done()]

    def cancel(self, job_id: str) -> bool:
        """Stop a job by its id — the ONE way to stop any job. A WORK job still
        owed is cancelled: one waiting is never drawn, one running is stopped
        where it is, and its record says `cancelled`. An await-job is retired
        (cancelled if still running or still waiting out its delay; a finished
        one is retired without a cancel). A recurring scheduled job is removed
        and never fires again. False for an id that names none of them (never
        faked)."""
        found = False
        queued = self.tasks_by_id.get(job_id)
        if queued is not None and queued.status in ACTIVE_STATUSES:
            queued.status = TaskStatus.CANCELLED
            queued.completed_at = datetime.now()
            self.metrics['tasks_cancelled'] += 1
            running = self._running_jobs.get(job_id)
            if running is not None and not running.done():
                running.cancel()
            write = asyncio.ensure_future(self._persist_queued(queued))
            self._persisting.add(write)
            write.add_done_callback(self._persisting.discard)
            logger.info("work job %s cancelled%s", job_id,
                        " while it ran" if running is not None else " before it ran")
            found = True
        task = self._await_jobs.pop(job_id, None)
        self._await_meta.pop(job_id, None)
        if task is not None:
            if not task.done():
                task.cancel()
            self._await_metrics["cancelled"] += 1
            logger.info("await-job %s cancelled", job_id)
            found = True
        if self._scheduled.pop(job_id, None) is not None:
            self._scheduler_metrics["cancelled"] += 1
            logger.info("scheduled job %s cancelled", job_id)
            found = True
        return found

    # ══════════════════════════════════════════════════════════════════════
    # SCHEDULER — recurring interval jobs (a one-shot timed job is
    # `submit(..., delay_s=)`; stopping any job is `cancel`)
    # ══════════════════════════════════════════════════════════════════════

    def schedule_recurring(self, name: str, call: Callable[[], Awaitable[Any]],
                           interval_s: float, priority: str = "medium") -> None:
        """Register a recurring job the authority fires every `interval_s`. This
        is where the substrate's periodic work lives — nothing runs its own
        interval loop.

        Registering a name that is already scheduled RETUNES it — new call,
        cadence and priority, next run one new interval from now — and keeps
        the job's run/error record. This is how a cadence is changed."""
        interval_s = float(interval_s)
        next_due = time.monotonic() + interval_s
        job = self._scheduled.get(name)
        if job is not None:
            job.call, job.interval_s = call, interval_s
            job.priority, job.next_due = priority, next_due
            logger.info("retuned recurring job %s to every %.0fs", name, interval_s)
            return
        self._scheduled[name] = _ScheduledJob(
            name=name, call=call, interval_s=interval_s,
            next_due=next_due, priority=priority)
        logger.info("scheduled recurring job %s every %.0fs", name, interval_s)

    def run_now(self, name: str) -> bool:
        """Make a scheduled job due on the NEXT tick — the substrate pulling its
        own periodic work forward (e.g. reflect BECAUSE something just failed,
        rather than waiting out the interval). This is the authority-owned form
        of the coordinator's old `_mark_reflection_due`. False if unknown."""
        job = self._scheduled.get(name)
        if job is None:
            return False
        job.next_due = time.monotonic()
        logger.info("scheduled job %s made due now", name)
        return True

    def scheduled_jobs(self) -> List[str]:
        return list(self._scheduled)

    def start(self) -> None:
        """Start the scheduler loop (idempotent). The authority now fires due
        jobs itself; no other component ticks a schedule.

        The authority's own maintenance is registered here: with a durable
        store, `queue_history_prune` bounds its finished rows (every
        `history_prune_interval_s`, default 3600)."""
        if self._persist_enabled and "queue_history_prune" not in self._scheduled:
            self.schedule_recurring(
                "queue_history_prune", self.prune_history,
                float(self.config.get('history_prune_interval_s', 3600.0)),
                priority="low")
        if self._persist_enabled and "queue_heartbeat" not in self._scheduled:
            # This instance's lease on the work it owns; lapsing means stopped.
            self.schedule_recurring(
                "queue_heartbeat", self.heartbeat,
                float(self.config.get('heartbeat_interval_s', self.HEARTBEAT_INTERVAL_S)),
                priority="high")
        self._running = True
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.ensure_future(self._scheduler_loop())
            logger.info("queue authority scheduler started")

    async def _fire_scheduled(self, job: _ScheduledJob) -> None:
        """Run one due scheduled job on the background budget and record its real
        outcome on the job itself. Wrapping the dispatch means a tier that raises
        is logged BY NAME and counted (no orphaned-task warning, no silent loss);
        a tier that succeeds bumps its run count. `execute` still owns the timeout
        and the pool counters — this only adds the per-tier truth."""
        try:
            await self.execute(f"scheduled:{job.name}", job.call, background=True)
            job.runs += 1
        except Exception as e:  # includes asyncio.TimeoutError from execute
            job.errors += 1
            job.last_error = f"{type(e).__name__}: {e}"
            self._scheduler_metrics["errors"] += 1
            logger.error("scheduled job %s failed: %s", job.name, job.last_error)

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._scheduler_tick_s)
                now = time.monotonic()
                for job in list(self._scheduled.values()):
                    if now < job.next_due:
                        continue
                    # ONE RUN OF A JOB AT A TIME. A run still going when the job
                    # comes due again is not started twice: two runs of one job
                    # act on the same state at once (two resolved the same
                    # prediction, and the second had nothing left to resolve).
                    # The skipped run is counted, and the next falls due one
                    # interval on.
                    if job.running is not None and not job.running.done():
                        job.skipped += 1
                        self._scheduler_metrics["skipped"] += 1
                        job.next_due = now + job.interval_s
                        logger.info("scheduled job %s is still running from its last run; "
                                    "this run not started (%d so far)", job.name, job.skipped)
                        continue
                    # Fire on the BACKGROUND budget: a scheduled job is maintenance
                    # nobody awaits, so it must NOT enter the await-job map (which
                    # only holds results a caller will collect). Bounded by the bg
                    # semaphore; a slow one cannot stall the loop. Dispatched via
                    # the wrapper so its outcome is recorded, not orphaned.
                    job.running = asyncio.ensure_future(self._fire_scheduled(job))
                    self._scheduler_metrics["fired"] += 1
                    job.last_run = now
                    job.next_due = now + job.interval_s
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("scheduler loop error: %s", e)

    async def stop(self) -> None:
        self._running = False
        # Stopping: drop this instance's lease so the work it still owes can be
        # claimed at once by an instance that is running.
        p = self._persistence if self._persist_enabled else None
        if p is not None:
            try:
                await p.release()
            except Exception as e:
                logger.error("queue: could not release this instance's lease: %s", e)
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(self._await_jobs.values()):
            if not task.done():
                task.cancel()
        self._await_jobs.clear()

    async def get_statistics(self) -> Dict[str, Any]:
        """FLAT scalar metrics for the health monitor.

        The probe records only int/float/bool/str values (nested dicts are
        dropped, health_monitor.py:1758), so everything here is a scalar and
        every counter is real — incremented when the thing actually happened,
        never optimistically. `pressure` is a string the probe keeps as-is.
        """
        p = self._pool_stats
        return {
            # work queue
            "queue_depth": self.queue.qsize(),
            "pressure": self.pressure(),
            "total_tasks_added": self.total_tasks_added,
            "tasks_completed": self.metrics["tasks_completed"],
            "tasks_failed": self.metrics["tasks_failed"],
            "tasks_requeued": self.metrics["tasks_requeued"],
            "tasks_deferred": self.metrics["tasks_deferred"],
            "tasks_already_queued": self.metrics["tasks_already_queued"],
            # execution pool (two budgets)
            "work_max_parallel": self.max_parallel,
            "bg_max_parallel": self.bg_max_parallel,
            "pool_active": p.active,
            "pool_peak_active": p.peak_active,
            "pool_total_submitted": p.total_submitted,
            "pool_total_completed": p.total_completed,
            "pool_total_failed": p.total_failed,
            "pool_total_timeout": p.total_timeout,
            # await jobs
            "await_submitted": self._await_metrics["submitted"],
            "await_completed": self._await_metrics["completed"],
            "await_failed": self._await_metrics["failed"],
            "await_delivered": self._await_metrics["delivered"],
            "await_delivery_failed": self._await_metrics["delivery_failed"],
            "await_cancelled": self._await_metrics["cancelled"],
            "await_pending": len(self.await_pending()),
            # scheduler
            "scheduled_jobs": len(self._scheduled),
            "scheduler_running": self._running,
            "scheduler_fired": self._scheduler_metrics["fired"],
            "scheduler_errors": self._scheduler_metrics["errors"],
            "scheduler_cancelled": self._scheduler_metrics["cancelled"],
            "scheduler_skipped": self._scheduler_metrics["skipped"],
            # persistence (durability of the backlog)
            "persist_enabled": self._persist_enabled,
            "persist_writes": self._persist_metrics["writes"],
            "persist_errors": self._persist_metrics["errors"],
            "persist_restored": self._persist_metrics["restored"],
            "persist_restarted": self._persist_metrics["restarted"],
        }

    def scheduled_job_status(self) -> List[Dict[str, Any]]:
        """Per-job diagnostics (name, cadence, runs, errors, last_error) — the
        substrate's window on what its periodic work is actually doing. Not a
        health scalar (the probe drops nested/list values); read on demand."""
        out: List[Dict[str, Any]] = []
        for job in self._scheduled.values():
            out.append({
                "name": job.name,
                "interval_s": job.interval_s,
                "runs": job.runs,
                "errors": job.errors,
                "skipped": job.skipped,
                "last_error": job.last_error,
            })
        return out


# Back-compat alias during migration: existing imports of `TaskQueue` keep
# working while call sites move to QueueAuthority.
TaskQueue = QueueAuthority


# ── singleton ─────────────────────────────────────────────────────────────
_queue_authority: Optional[QueueAuthority] = None


def get_queue_authority(config: Optional[Dict[str, Any]] = None) -> QueueAuthority:
    """The one queue authority for the process. Settings given once it exists
    are put in force (`configure`), whoever reached it first."""
    global _queue_authority
    if _queue_authority is None:
        _queue_authority = QueueAuthority(config)
    elif config:
        _queue_authority.configure(config)
    return _queue_authority
