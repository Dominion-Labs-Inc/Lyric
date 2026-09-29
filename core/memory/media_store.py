#!/usr/bin/env python3
"""Durable media for memories: the pictures and the sounds the substrate met.

A memory can be ABOUT an image or a sound, and to say the substrate "remembers"
it rather than only a sentence about it, the pixels or the samples themselves must
be retained and retrievable. Storing raw bytes inside the memory row would bloat
the vector table every similarity search scans, so media lives here, in its own
table, keyed by the memory and its content and linked to the memory it belongs to. The memory
keeps a short PERCEIVED description in its recallable text (so it can be found by
what is in the picture or the recording); this keeps the bytes, so the picture
can be shown and the sound played again.

Each memory keeps its own copy: the same recording heard twice is two memories,
and each can be heard again and recalled by what it holds. Its SHA-256 still
says WHAT was met, and is indexed, so the two are known to be of one thing.

WHAT WAS MET IS FOUND BY WHAT IT WAS. A hearing's distinct landmark hashes
(`hearing.landmark_hashes`) and a seeing's keypoint keys
(`vision.keypoint_hashes`) are kept beside its trace (`landmarks`), so memory
can be asked "have I heard this? seen this?" by what the sound or the picture
shares with one met before (`similar`, read by `MemoryAgent.retrieve`'s
`sound` and `sight` strategies). The two kinds of key never overlap.

WHAT THE BYTES ARE, THE BYTES SAY. The mime type is read off the file's own
first bytes, never off a name or a caller's guess, so a sound brought back from
another store is still a sound.
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
ALTER TABLE unified.memory_media ADD COLUMN IF NOT EXISTS landmarks INTEGER[];
CREATE INDEX IF NOT EXISTS memory_media_landmarks_idx ON unified.memory_media USING GIN (landmarks);
"""


def _read_bytes(media: Union[str, bytes, "Path"]) -> bytes:
    if isinstance(media, (bytes, bytearray)):
        return bytes(media)
    return Path(media).read_bytes()


def mime_of(data: bytes) -> Optional[str]:
    """What a file says it is, in its own first bytes, or None where they do
    not say."""
    head = bytes(data[:16])
    # A remembered TRACE (what is kept of a sound instead of the recording) is a
    # numpy archive: a zip whose first entry is an array.
    if head.startswith(b"PK\x03\x04") and b".npy" in bytes(data[30:96]):
        return "application/x-npz"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"FORM") and head[8:12] in (b"AIFF", b"AIFC"):
        return "audio/aiff"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"caff"):
        return "audio/x-caf"
    if head.startswith(b".snd"):
        return "audio/basic"
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"M4A ", b"M4B ", b"M4P "):
            return "audio/mp4"
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "image/heic"
        return "video/mp4"
    return None


def media_kind(media: Union[str, bytes, "Path"]) -> Optional[str]:
    """"image" or "audio" (or "video"), as the bytes say, or None."""
    mime = mime_of(_read_bytes(media)[:96])
    return mime.split("/", 1)[0] if mime else None


class MediaStore:
    """The one home for the media bytes attached to memories."""

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
            # In every store that keeps memories: media lives with its memory.
            for store in db.schema_stores():
                for statement in filter(None, (s.strip() for s in _DDL.split(";"))):
                    await db.execute_query(statement, commit=True, store=store)
            self._ready_done = True

    async def store_media(
        self,
        memory_id: str,
        media: Union[str, bytes, "Path"],
        *,
        perceived: Optional[Dict[str, Any]] = None,
        owner: Optional[str] = None,
        keys: Optional[Any] = None,
    ) -> str:
        """Retain one picture or sound for a memory, and return its media id.
        Its `keys` -- a sound's landmark hashes, a picture's keypoint keys --
        are kept beside it, so it can be found by what it is (`similar`).
        Idempotent for that memory: the same bytes re-stored for it update its
        row rather than duplicating it. Raises on empty data -- a memory that
        claims media but carries no bytes is not honestly storing any.

        THE ID IS THE MEMORY'S AND THE CONTENT'S TOGETHER. Keyed by the content
        alone, the same recording heard twice MOVED its row to the second
        memory, and the first could no longer be heard again or recalled by
        what it held. Two memories of one thing each keep their own.

        The mime type is the bytes' own (`mime_of`); a file whose bytes do not
        say is stored as `application/octet-stream`, which is the truth about it.

        `owner` is the memory's owner (its user_id): the media is kept in the
        same store as the memory (the manager's `write_store`)."""
        await self._ready()
        data = _read_bytes(media)
        if not data:
            raise ValueError(f"media for memory {memory_id} has no bytes to store")
        perceived = perceived or {}
        sha = hashlib.sha256(data).hexdigest()
        media_id = f"media_{hashlib.sha256(f'{memory_id}:{sha}'.encode()).hexdigest()[:32]}"
        mime = mime_of(data) or "application/octet-stream"
        width = perceived.get("width")
        height = perceived.get("height")
        hashes = ([int(k) for k in keys] if keys is not None and len(keys) else None)

        import json
        await self.db().execute_query(
            """INSERT INTO unified.memory_media
                   (media_id, memory_id, mime, bytes, sha256, byte_size,
                    width, height, perceived, landmarks)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::int[])
               ON CONFLICT (media_id) DO UPDATE SET
                   memory_id = EXCLUDED.memory_id,
                   perceived = EXCLUDED.perceived,
                   landmarks = EXCLUDED.landmarks""",
            (media_id, memory_id, mime, data, sha, len(data),
             int(width) if width else None, int(height) if height else None,
             json.dumps(perceived), hashes),
            commit=True, store=self.db().write_store(owner))
        logger.info("retained %d-byte %s %s for memory %s",
                    len(data), mime, media_id, memory_id)
        return media_id

    async def similar(self, keys: Any, *, kind: str, limit: int = 20) -> List[Dict[str, Any]]:
        """The media of `kind` ("sound_trace", "sight_trace") kept that share
        the most keys with what was met, most first, each with how many it
        shares: CANDIDATES for being the same thing, found through the index.
        Whether one IS the same is decided by the sense's own agreement -- on
        one offset for a sound, on one geometry for a picture -- which only the
        kept features can tell."""
        await self._ready()
        hashes = [int(k) for k in (keys if keys is not None else [])]
        if not hashes:
            return []
        found: List[Dict[str, Any]] = []
        for store in self.db().owner_stores():
            rows = await self.db().execute_query(
                """SELECT media_id, memory_id, mime, bytes, sha256, byte_size,
                          width, height, perceived,
                          cardinality(ARRAY(SELECT unnest(landmarks)
                                            INTERSECT SELECT unnest($1::int[]))) AS shared
                     FROM unified.memory_media
                    WHERE landmarks && $1::int[] AND perceived->>'kind' = $3
                    ORDER BY shared DESC
                    LIMIT $2""",
                (hashes, int(limit), str(kind)), fetch_all=True, store=store) or []
            found += [{**self._row(r), "shared": int(r["shared"])} for r in rows]
        found.sort(key=lambda m: -m["shared"])
        return found[:limit]

    async def get_media(self, media_id: str) -> Optional[Dict[str, Any]]:
        """The stored media: its bytes, mime, dimensions (for a picture) and
        perceived structure, or None if no such media."""
        await self._ready()
        for store in self.db().owner_stores():
            rows = await self.db().execute_query(
                "SELECT media_id, memory_id, mime, bytes, sha256, byte_size, "
                "width, height, perceived FROM unified.memory_media WHERE media_id=$1",
                (media_id,), fetch_all=True, store=store) or []
            if rows:
                return self._row(rows[0])
        return None

    async def media_for_memory(self, memory_id: str) -> List[Dict[str, Any]]:
        """Every picture or sound attached to a memory, bytes included, newest
        first."""
        await self._ready()
        # A memory is in exactly one store, and its media with it.
        rows = []
        for store in self.db().owner_stores():
            rows += await self.db().execute_query(
                "SELECT media_id, memory_id, mime, bytes, sha256, byte_size, "
                "width, height, perceived, created_at FROM unified.memory_media "
                "WHERE memory_id=$1 ORDER BY created_at DESC",
                (memory_id,), fetch_all=True, store=store) or []
        rows.sort(key=lambda r: r["created_at"], reverse=True)
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
