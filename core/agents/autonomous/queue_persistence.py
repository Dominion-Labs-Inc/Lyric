#!/usr/bin/env python3
"""
Queue persistence — the durable backing for the queue authority.

The queue authority is the substrate's ONE owner of work jobs. Work that has
been accepted but not yet finished must survive a restart, or a crash silently
drops the substrate's backlog and the loss is invisible. This store is that
durability: every not-yet-terminal work job has a row in `unified.task_queue`,
written when it is queued and updated as it moves through its lifecycle, and on
boot the authority rehydrates them.

Design commitments (matching the queue authority's discipline):
  * No fake success. A persist failure is logged with the task id and counted
    (the authority exposes the counter to the health monitor); it never returns
    a value that reads as "durably saved" when it was not.
  * No silent default on load. A row whose enum values are unrecognised RAISES
    rather than loading as some default task — a corrupted row must be visible,
    not quietly mutated into ordinary work.
  * Persistence never blocks acting. A write that fails leaves the in-memory
    queue intact and the substrate working; the durability gap is surfaced,
    not hidden, and not fatal.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .shared_types import (
    Task, TaskType, TaskStatus, Priority, TaskSource,
)
from .queue_authority import ACTIVE_STATUSES

logger = logging.getLogger(__name__)


DDL = """
CREATE TABLE IF NOT EXISTS unified.task_queue (
    task_id     VARCHAR PRIMARY KEY,
    status      VARCHAR NOT NULL,
    priority    INTEGER NOT NULL,
    payload     JSONB   NOT NULL,
    result      JSONB,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS task_queue_status_priority
    ON unified.task_queue (status, priority DESC, updated_at);
ALTER TABLE unified.task_queue ADD COLUMN IF NOT EXISTS owner TEXT;
CREATE TABLE IF NOT EXISTS unified.queue_instances (
    instance_id  TEXT PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


# ── Task <-> JSON ───────────────────────────────────────────────────────────
# Explicit, field-by-field. The Task dataclass carries enums, datetimes, and
# one field that CANNOT persist: `completion_callbacks` holds live function
# objects (runtime closure hooks). Those are dropped on save and restored empty
# — a rehydrated task re-registers its hooks through the normal path, it does
# not carry stale ones across a restart. This is stated, not silent.

_DATETIME_FIELDS = ("created_at", "completed_at", "deadline", "verified_at")
_ENUM_FIELDS = {
    "type": TaskType,
    "priority": Priority,
    "status": TaskStatus,
    "source": TaskSource,
}
# Everything else copies straight through as JSON-native values.
_PLAIN_FIELDS = (
    "id", "description", "estimated_duration", "dependencies", "result",
    "provenance", "actor", "created_by", "governance_approved",
    "governance_action_id", "success_criteria", "acceptance_criteria",
    "required_artifacts", "validation_strategy", "completion_score",
    "remaining_risks", "open_questions", "assumptions", "max_time_seconds",
    "max_tokens", "max_iterations", "parent_task_id", "child_task_ids",
    "verification_attempts", "last_verification_result", "verified_at",
    "retry_count", "max_retries", "metadata", "allowed_tools",
)


def task_to_jsonable(task: Task) -> Dict[str, Any]:
    """A JSON-native dict for one Task. Enums -> value, datetimes -> isoformat,
    completion_callbacks dropped (they are live functions)."""
    out: Dict[str, Any] = {}
    for name, _enum in _ENUM_FIELDS.items():
        val = getattr(task, name, None)
        out[name] = val.value if val is not None else None
    for name in _DATETIME_FIELDS:
        val = getattr(task, name, None)
        out[name] = val.isoformat() if isinstance(val, datetime) else None
    for name in _PLAIN_FIELDS:
        if name in _DATETIME_FIELDS:
            continue
        out[name] = getattr(task, name, None)
    # completion_callbacks intentionally omitted — not serialisable.
    return out


def task_from_jsonable(d: Dict[str, Any]) -> Task:
    """Reconstruct a Task. Unknown enum values RAISE (a corrupted row must not
    load as a silent default)."""
    kwargs: Dict[str, Any] = {}
    for name, enum_cls in _ENUM_FIELDS.items():
        raw = d.get(name)
        if raw is None:
            continue
        try:
            kwargs[name] = enum_cls(raw)
        except ValueError as e:
            raise ValueError(
                f"task row has unrecognised {name}={raw!r} for {enum_cls.__name__}; "
                f"refusing to load it as a default") from e
    for name in _DATETIME_FIELDS:
        raw = d.get(name)
        if raw:
            kwargs[name] = datetime.fromisoformat(raw)
    for name in _PLAIN_FIELDS:
        if name in _DATETIME_FIELDS:
            continue
        if name in d and d[name] is not None:
            kwargs[name] = d[name]
    return Task(**kwargs)


class QueuePersistence:
    """Durable backing for the queue authority's work jobs."""

    def __init__(self, db_manager=None, instance_id: Optional[str] = None):
        self._db = db_manager
        self._schema_ready = False
        #: WHICH INSTANCE OF THE MODEL holds the jobs this store writes. Many
        #: instances share one queue table; a job is owned by the instance that
        #: holds it, and only a job whose owner has stopped may be taken over.
        import uuid as _uuid
        self.instance_id = instance_id or f"queue_{_uuid.uuid4().hex[:12]}"

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self):
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()

    async def ensure_schema(self):
        if self._schema_ready:
            return
        await self._ready()
        for statement in filter(None, (s.strip() for s in DDL.split(";"))):
            await self.db().execute_query(statement)
        self._schema_ready = True

    async def upsert(self, *, task: Task, status: str, priority: int,
                     result: Optional[Dict[str, Any]] = None,
                     error: Optional[str] = None,
                     queued_meta: Optional[Dict[str, Any]] = None) -> None:
        """Write/replace one work job's durable row. Raises on failure — the
        caller (the authority) wraps this so a DB error is logged with the task
        id, counted, and non-fatal to the live queue."""
        await self.ensure_schema()
        payload = {"task": task_to_jsonable(task), "queued": queued_meta or {}}
        await self.db().execute_query(
            "INSERT INTO unified.task_queue"
            " (task_id, status, priority, payload, result, error, owner, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())"
            " ON CONFLICT (task_id) DO UPDATE SET"
            "   status = EXCLUDED.status, priority = EXCLUDED.priority,"
            "   payload = EXCLUDED.payload, result = EXCLUDED.result,"
            "   error = EXCLUDED.error, owner = EXCLUDED.owner, updated_at = NOW()",
            (task.id, status, int(priority),
             json.dumps(payload, default=str),
             json.dumps(result, default=str) if result is not None else None,
             error, self.instance_id),
            commit=True,
        )

    async def claim_new(self, *, task: Task, status: str, priority: int,
                        result: Optional[Dict[str, Any]] = None,
                        error: Optional[str] = None,
                        queued_meta: Optional[Dict[str, Any]] = None,
                        lease_s: float) -> bool:
        """Write a NEW job's row for this instance, unless the same id is already
        owed work held by another LIVING instance. Returns True when written,
        False when another instance holds it (nothing is changed).

        One statement, so two instances adding the same id cannot both win. An
        existing row is overwritten only when it is finished history, has no
        owner, is this instance's own, or belongs to an instance whose heartbeat
        is older than `lease_s` — the same rule `claim_restorable` uses for
        taking over a stopped instance's work."""
        await self.ensure_schema()
        payload = {"task": task_to_jsonable(task), "queued": queued_meta or {}}
        owed = self.RESTORABLE_STATUSES
        owed_ph = ", ".join(f"${i + 8}" for i in range(len(owed)))
        lease = f"${len(owed) + 8}"
        rows = await self.db().execute_query(
            "INSERT INTO unified.task_queue AS t"
            " (task_id, status, priority, payload, result, error, owner, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())"
            " ON CONFLICT (task_id) DO UPDATE SET"
            "   status = EXCLUDED.status, priority = EXCLUDED.priority,"
            "   payload = EXCLUDED.payload, result = EXCLUDED.result,"
            "   error = EXCLUDED.error, owner = EXCLUDED.owner, updated_at = NOW()"
            f" WHERE t.status NOT IN ({owed_ph})"
            "    OR t.owner IS NULL OR t.owner = EXCLUDED.owner"
            "    OR NOT EXISTS (SELECT 1 FROM unified.queue_instances i"
            "                   WHERE i.instance_id = t.owner"
            f"                    AND i.heartbeat_at >= NOW() - make_interval(secs => {lease}))"
            " RETURNING task_id",
            (task.id, status, int(priority),
             json.dumps(payload, default=str),
             json.dumps(result, default=str) if result is not None else None,
             error, self.instance_id, *owed, float(lease_s)),
            fetch_all=True,
        )
        return bool(rows)

    async def update_status(self, task_id: str, status: str, *,
                            result: Optional[Dict[str, Any]] = None,
                            error: Optional[str] = None) -> bool:
        """Move a persisted job to a new lifecycle status. Returns whether a row
        was actually updated (False = no such row — never faked)."""
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "UPDATE unified.task_queue SET status = $2,"
            "   result = COALESCE($3, result), error = COALESCE($4, error),"
            "   updated_at = NOW()"
            " WHERE task_id = $1 RETURNING task_id",
            (task_id, status,
             json.dumps(result, default=str) if result is not None else None,
             error),
            fetch_all=True,
        )
        return bool(rows)

    #: The lifecycle states that are NOT terminal — work still owed. These are
    #: what boot rehydrates; every other status is a history row. Taken from
    #: the authority's ACTIVE_STATUSES, not declared again here.
    RESTORABLE_STATUSES: Tuple[str, ...] = tuple(sorted(
        s.value for s in ACTIVE_STATUSES))

    async def heartbeat(self) -> None:
        """Say this instance is alive, so the jobs it owns are not taken over."""
        await self.ensure_schema()
        await self.db().execute_query(
            "INSERT INTO unified.queue_instances (instance_id) VALUES ($1)"
            " ON CONFLICT (instance_id) DO UPDATE SET heartbeat_at = NOW()",
            (self.instance_id,), commit=True)

    async def release(self) -> None:
        """This instance is stopping: remove its heartbeat, so the work it still
        owes can be claimed by another instance at once rather than after the
        lease runs out."""
        await self.ensure_schema()
        await self.db().execute_query(
            "DELETE FROM unified.queue_instances WHERE instance_id = $1",
            (self.instance_id,), commit=True)

    @staticmethod
    def _decode(row) -> Dict[str, Any]:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return {
            "task": task_from_jsonable(payload["task"]),
            "status": row["status"],
            "priority": int(row["priority"]),
            "queued": payload.get("queued", {}),
        }

    async def claim_restorable(self, lease_s: float) -> List[Dict[str, Any]]:
        """CLAIM the owed work no living instance holds, atomically, and return
        it, highest priority first. A job is claimable when it has no owner or
        its owner's heartbeat is older than `lease_s`; `FOR UPDATE SKIP LOCKED`
        means two instances booting together never claim the same job. This
        replaces reading every owed row: with several instances each boot
        re-queued the others' work and reset their running jobs, so a task could
        run twice. A row that cannot be decoded RAISES -- a corrupt backlog row
        must be seen, not skipped."""
        await self.ensure_schema()
        statuses = tuple(self.RESTORABLE_STATUSES)
        placeholders = ", ".join(f"${i+1}" for i in range(len(statuses)))
        me, lease = f"${len(statuses) + 1}", f"${len(statuses) + 2}"
        rows = await self.db().execute_query(
            f"UPDATE unified.task_queue t SET owner = {me}, updated_at = NOW()"
            f" WHERE t.task_id IN ("
            f"   SELECT q.task_id FROM unified.task_queue q"
            f"   LEFT JOIN unified.queue_instances i ON i.instance_id = q.owner"
            f"   WHERE q.status IN ({placeholders})"
            f"     AND (q.owner IS NULL OR i.instance_id IS NULL"
            f"          OR i.heartbeat_at < NOW() - make_interval(secs => {lease}))"
            f"   FOR UPDATE OF q SKIP LOCKED)"
            f" RETURNING t.task_id, t.status, t.priority, t.payload",
            (*statuses, self.instance_id, float(lease_s)),
            fetch_all=True,
        ) or []
        claimed = [self._decode(row) for row in rows]
        claimed.sort(key=lambda r: -r["priority"])
        return claimed

    async def load_one(self, task_id: str) -> Optional[Dict[str, Any]]:
        """One job's stored state (any status), or None -- for reading a job
        this instance does not hold."""
        await self.ensure_schema()
        row = await self.db().execute_query(
            "SELECT task_id, status, priority, payload, result, error FROM unified.task_queue"
            " WHERE task_id = $1", (task_id,), fetch_one=True)
        if row is None:
            return None
        out = self._decode(row)
        result = row["result"]
        out["result"] = json.loads(result) if isinstance(result, str) else result
        out["error"] = row["error"]
        return out

    async def prune_terminal(self, keep_last: int = 500) -> int:
        """Bound the history: keep the most recent `keep_last` terminal rows,
        delete older ones. Returns how many were deleted. Prevents the table from
        growing without limit while keeping recent history for diagnostics.
        Terminal = any status that is not restorable, so a row is always one or
        the other: owed work is never pruned, and no status is left in neither."""
        await self.ensure_schema()
        owed = self.RESTORABLE_STATUSES
        placeholders = ", ".join(f"${i+1}" for i in range(len(owed)))
        status = await self.db().execute_query(
            f"DELETE FROM unified.task_queue WHERE task_id IN ("
            f"  SELECT task_id FROM unified.task_queue"
            f"  WHERE status NOT IN ({placeholders})"
            f"  ORDER BY updated_at DESC OFFSET {int(keep_last)}"
            f")",
            tuple(owed),
        )
        # asyncpg returns e.g. "DELETE 12"
        try:
            return int(str(status).split()[-1])
        except (ValueError, IndexError, AttributeError):
            return 0
