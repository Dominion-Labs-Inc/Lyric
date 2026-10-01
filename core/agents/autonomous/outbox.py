#!/usr/bin/env python3
"""The outbox: what the substrate has to say to a person, kept until it is said.

A reply answers a turn. The outbox is how the substrate speaks FIRST: work a person asked for has ended, a moment
they were to be reminded of has come, something they should know about has happened. The substrate
(`AutonomousCoordinator.speak_to`) puts the message here, due now or at a set moment, and it is delivered:
  * PUSHED to every front end listening for that person (`AutonomousCoordinator.on_message`), the moment it is
    due; or
  * HELD until the person next speaks (it comes with that reply) or a front end asks for what waits.
Each message is delivered once. Its row records when, and how (`push`, `reply`, `asked`), and marking it delivered
is one statement, so two instances of the model never deliver it twice.

DURABLE, like the queue's backlog (`queue_persistence`): a message due tomorrow survives tonight's restart, and
the substrate arms it again at boot. Not memory: what was said is remembered through the conversation it was said
in; this is only what is owed to be said, and when.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS unified.outbox (
    message_id    TEXT PRIMARY KEY,
    actor         TEXT NOT NULL,
    text          TEXT NOT NULL,
    why           TEXT NOT NULL,
    about         TEXT,
    session       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    due_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at  TIMESTAMPTZ,
    delivered_by  TEXT
);
CREATE INDEX IF NOT EXISTS outbox_waiting ON unified.outbox (actor, due_at) WHERE delivered_at IS NULL
"""

_COLUMNS = "message_id, actor, text, why, about, session, created_at, due_at, delivered_at, delivered_by"


class Outbox:
    """What the substrate owes to be said, to whom, from when."""

    def __init__(self, db_manager=None):
        self._db = db_manager
        self._schema_ready = False

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self) -> None:
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()
        if not self._schema_ready:
            for statement in filter(None, (s.strip() for s in DDL.split(";"))):
                await db.execute_query(statement, commit=True)
            self._schema_ready = True

    @staticmethod
    def _row(row) -> Dict[str, Any]:
        out = dict(row)
        for key in ("created_at", "due_at", "delivered_at"):
            if isinstance(out.get(key), datetime):
                out[key] = out[key].isoformat()
        return out

    async def put(self, actor: str, text: str, *, why: str, about: Optional[str] = None,
                  session: Optional[str] = None, due_at: Optional[datetime] = None) -> Dict[str, Any]:
        """Owe `actor` this message, due at `due_at` (now when None). Returns its row."""
        await self._ready()
        if not str(text or "").strip():
            raise ValueError("a message says something; this one is empty")
        due = due_at or datetime.now(timezone.utc)
        if due.tzinfo is None:
            due = due.astimezone(timezone.utc)
        row = await self.db().execute_query(
            f"INSERT INTO unified.outbox (message_id, actor, text, why, about, session, due_at)"
            f" VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING {_COLUMNS}",
            (f"msg_{uuid.uuid4().hex[:16]}", str(actor), str(text).strip(), str(why), about, session, due),
            fetch_one=True, commit=True)
        return self._row(row)

    async def waiting(self, actor: Optional[str] = None) -> List[Dict[str, Any]]:
        """Messages due now and not yet delivered, oldest first: to `actor`, or to anyone."""
        await self._ready()
        rows = await self.db().execute_query(
            f"SELECT {_COLUMNS} FROM unified.outbox WHERE delivered_at IS NULL AND due_at <= NOW()"
            + (" AND actor = $1" if actor is not None else "") + " ORDER BY due_at, created_at",
            (str(actor),) if actor is not None else (), fetch_all=True) or []
        return [self._row(r) for r in rows]

    async def upcoming(self) -> List[Dict[str, Any]]:
        """Messages not yet due, soonest first -- what the substrate arms at boot."""
        await self._ready()
        rows = await self.db().execute_query(
            f"SELECT {_COLUMNS} FROM unified.outbox WHERE delivered_at IS NULL AND due_at > NOW()"
            " ORDER BY due_at", (), fetch_all=True) or []
        return [self._row(r) for r in rows]

    async def get(self, message_id: str) -> Optional[Dict[str, Any]]:
        await self._ready()
        row = await self.db().execute_query(
            f"SELECT {_COLUMNS} FROM unified.outbox WHERE message_id = $1", (message_id,), fetch_one=True)
        return self._row(row) if row else None

    async def mark_delivered(self, message_id: str, by: str) -> bool:
        """Claim one message as delivered, `by` how. False when it was already delivered (by another instance, or
        another front end first) -- the caller then does not deliver it again."""
        await self._ready()
        rows = await self.db().execute_query(
            "UPDATE unified.outbox SET delivered_at = NOW(), delivered_by = $2"
            " WHERE message_id = $1 AND delivered_at IS NULL RETURNING message_id",
            (message_id, by), fetch_all=True, commit=True)
        return bool(rows)

    async def unmark(self, message_id: str) -> None:
        """A claimed message that reached no one is owed again."""
        await self._ready()
        await self.db().execute_query(
            "UPDATE unified.outbox SET delivered_at = NULL, delivered_by = NULL WHERE message_id = $1",
            (message_id,), commit=True)

    async def settle(self, actor: str, about: str, by: str) -> int:
        """Messages to `actor` about `about` that were said some other way (a reply that already said it), marked
        delivered so they are not said again. Returns how many."""
        await self._ready()
        rows = await self.db().execute_query(
            "UPDATE unified.outbox SET delivered_at = NOW(), delivered_by = $3"
            " WHERE actor = $1 AND about = $2 AND delivered_at IS NULL RETURNING message_id",
            (str(actor), str(about), by), fetch_all=True, commit=True) or []
        return len(rows)

    async def forget(self, actor: str) -> int:
        """Every message owed or said to `actor`, removed. Returns how many."""
        await self._ready()
        rows = await self.db().execute_query(
            "DELETE FROM unified.outbox WHERE actor = $1 RETURNING message_id", (str(actor),),
            fetch_all=True, commit=True) or []
        return len(rows)


_outbox: Optional[Outbox] = None


def get_outbox() -> Outbox:
    global _outbox
    if _outbox is None:
        _outbox = Outbox()
    return _outbox
