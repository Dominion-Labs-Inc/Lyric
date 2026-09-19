#!/usr/bin/env python3
"""Durable image data for memories.

A memory can be ABOUT an image, and to say the substrate "remembers" the image
rather than only a sentence about it, the pixels themselves must be retained and
retrievable. Storing raw bytes inside the memory row would bloat the vector table
every similarity search scans, so image data lives here, in its own table, keyed
by content hash and linked to the memory it belongs to. The memory keeps a short
PERCEIVED description in its recallable text (so it can be found by what is in the
picture); this keeps the bytes, so the picture can be produced again.

Identity is the image's SHA-256: the same image attached to two memories is one
stored blob, not two, the way one source observation is one epistemic root.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS unified.memory_media (
    media_id    TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL,
    mime        TEXT,
    bytes       BYTEA NOT NULL,
    sha256      TEXT NOT NULL,
    byte_size   INTEGER NOT NULL,
    width       INTEGER,
    height      INTEGER,
    perceived   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS memory_media_memory_idx ON unified.memory_media (memory_id);
CREATE INDEX IF NOT EXISTS memory_media_sha_idx    ON unified.memory_media (sha256);
"""


def _read_bytes(image: Union[str, bytes, "Path"]) -> bytes:
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    return Path(image).read_bytes()


class MediaStore:
    """The one home for image bytes attached to memories."""

    def __init__(self, db_manager=None):
        self._db = db_manager
        self._ready_done = False

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self):
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()
        if not self._ready_done:
            for statement in filter(None, (s.strip() for s in _DDL.split(";"))):
                await db.execute_query(statement, commit=True)
            self._ready_done = True

    async def store_image(
        self,
        memory_id: str,
        image: Union[str, bytes, "Path"],
        *,
        perceived: Optional[Dict[str, Any]] = None,
        mime: Optional[str] = None,
    ) -> str:
        """Retain one image for a memory, and return its media id (its content
        hash). Idempotent: the same bytes re-stored update the row rather than
        duplicating the blob. Raises on empty image data -- a memory that claims
        an image but carries no bytes is not honestly storing one."""
        await self._ready()
        data = _read_bytes(image)
        if not data:
            raise ValueError(f"image for memory {memory_id} has no bytes to store")
        perceived = perceived or {}
        sha = hashlib.sha256(data).hexdigest()
        media_id = f"media_{sha[:32]}"
        if not mime:
            fmt = str(perceived.get("format") or "").lower()
            mime = f"image/{fmt}" if fmt else "application/octet-stream"
        width = perceived.get("width")
        height = perceived.get("height")

        import json
        await self.db().execute_query(
            """INSERT INTO unified.memory_media
                   (media_id, memory_id, mime, bytes, sha256, byte_size,
                    width, height, perceived)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (media_id) DO UPDATE SET
                   memory_id = EXCLUDED.memory_id,
                   perceived = EXCLUDED.perceived""",
            (media_id, memory_id, mime, data, sha, len(data),
             int(width) if width else None, int(height) if height else None,
             json.dumps(perceived)),
            commit=True)
        logger.info("retained %d-byte image %s for memory %s",
                    len(data), media_id, memory_id)
        return media_id

    async def get_image(self, media_id: str) -> Optional[Dict[str, Any]]:
        """The stored image: its bytes, mime, dimensions and perceived structure,
        or None if no such media."""
        await self._ready()
        rows = await self.db().execute_query(
            "SELECT media_id, memory_id, mime, bytes, sha256, byte_size, "
            "width, height, perceived FROM unified.memory_media WHERE media_id=$1",
            (media_id,), fetch_all=True) or []
        return self._row(rows[0]) if rows else None

    async def media_for_memory(self, memory_id: str) -> List[Dict[str, Any]]:
        """Every image attached to a memory, bytes included, newest first."""
        await self._ready()
        rows = await self.db().execute_query(
            "SELECT media_id, memory_id, mime, bytes, sha256, byte_size, "
            "width, height, perceived FROM unified.memory_media "
            "WHERE memory_id=$1 ORDER BY created_at DESC",
            (memory_id,), fetch_all=True) or []
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> Dict[str, Any]:
        import json
        raw = r["bytes"]
        data = bytes(raw) if isinstance(raw, (memoryview, bytearray)) else raw
        perceived = r["perceived"]
        if isinstance(perceived, str):
            perceived = json.loads(perceived)
        return {"media_id": r["media_id"], "memory_id": r["memory_id"],
                "mime": r["mime"], "bytes": data, "sha256": r["sha256"],
                "byte_size": r["byte_size"], "width": r["width"],
                "height": r["height"], "perceived": perceived or {}}


_store: Optional[MediaStore] = None


def get_media_store() -> MediaStore:
    global _store
    if _store is None:
        _store = MediaStore()
    return _store
