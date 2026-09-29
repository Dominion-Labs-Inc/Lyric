#!/usr/bin/env python3
"""
Perception Manager - Simplified sensory input processing
Consolidates all perception functionality from the monolithic controller
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import deque

from .shared_types import PerceptionData, Task, TaskType, TaskStatus, Priority
from core.database import LyricUnifiedDatabase

logger = logging.getLogger(__name__)


#: The live perceptual-awareness hub, exposed as a singleton so any reader — the
#: memory agent stamping a forming memory's perceptual context — reaches the SAME
#: instance the coordinator feeds. The perceptual analogue of get_appraisal_system().
_PERCEPTION_MANAGER: Optional["PerceptionManager"] = None


def get_perception_manager() -> Optional["PerceptionManager"]:
    """The live PerceptionManager the coordinator created and feeds, or None before
    one exists (a reading, never invented)."""
    return _PERCEPTION_MANAGER


#: The perceptions table had NO definition anywhere in the codebase. Both the
#: writer and the reader named an unqualified `perceptions`, so every write
#: since this module was authored failed with `relation "perceptions" does not
#: exist`, was caught, logged, and counted as processed anyway. The substrate
#: has never retained a single perception.
#:
#: Schema-qualified, because the rest of the store is: an unqualified name
#: resolves through search_path, which differs between the pooled connection
#: and a psql session, so "the table exists" stops being a fact about the
#: database and becomes a fact about who is asking.
#:
#: WHOSE A PERCEPTION IS, on the row. A person's image is theirs: its row is
#: kept in their context (a per-owner table, `postgres_config.PER_OWNER_TABLES`)
#: and says so, so a release cut can keep the substrate's own and leave theirs.
PERCEPTIONS_DDL = """
CREATE TABLE IF NOT EXISTS unified.perceptions (
    id          VARCHAR PRIMARY KEY,
    source      VARCHAR NOT NULL,
    data_type   VARCHAR NOT NULL,
    content     JSONB   NOT NULL,
    confidence  DOUBLE PRECISION NOT NULL,
    timestamp   DOUBLE PRECISION NOT NULL,
    metadata    JSONB   NOT NULL DEFAULT '{}'::jsonb,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    owner       TEXT
);

ALTER TABLE unified.perceptions ADD COLUMN IF NOT EXISTS owner TEXT;

CREATE INDEX IF NOT EXISTS perceptions_source_idx    ON unified.perceptions (source);
CREATE INDEX IF NOT EXISTS perceptions_timestamp_idx ON unified.perceptions (timestamp DESC);
"""


class PerceptionManager:
    """Manages sensory input processing and environmental awareness"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False
        
        # Perception data storage
        self.perception_queue: deque = deque(maxlen=1000)
        self.processed_perceptions: Dict[str, PerceptionData] = {}
        
        # Use unified database instead of separate perception.db
        self.unified_db = LyricUnifiedDatabase()
        self.connection = None  # For backwards compatibility
        
        # Processing statistics
        self.stats = {
            "total_processed": 0,
            "total_retained": 0,
            "processing_time_avg": 0.0,
            "confidence_avg": 0.0,
            "queue_length": 0
        }

        # Expose this instance as the live hub so the memory agent can stamp a
        # forming memory's perceptual context from the same state we feed.
        global _PERCEPTION_MANAGER
        _PERCEPTION_MANAGER = self

    async def initialize(self) -> bool:
        """Initialize the perception system"""
        try:
            await self.unified_db.initialize()
            # LyricUnifiedDatabase uses connection pools, not direct connection
            self.connection = self.unified_db  # Store database instance for queries

            # The table this module writes to is created HERE, by the module
            # that owns it. Nothing else defined it, which is why every write
            # failed. It is created in every store its rows are kept in: the
            # substrate's own and people's contexts.
            for store in self.unified_db.schema_stores():
                for statement in [s for s in PERCEPTIONS_DDL.split(";") if s.strip()]:
                    await self.unified_db.execute_query(statement, commit=True, store=store)

            self.active = True
            logger.info("Perception manager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize perception manager: {e}")
            return False
    
    async def process_input(self, source: str, data_type: str,
                            content: Dict[str, Any],
                            memory_id: Optional[str] = None, *,
                            origin: "Origin") -> Optional[PerceptionData]:
        """Process new sensory input.

        `memory_id` is the memory of HAVING PERCEIVED this, formed by the caller
        that met it (`coord.see` remembers the image it looked at). It travels
        to the evidence producer so every claim admitted from this percept is a
        belief ABOUT that memory. Without it the belief store refuses the claims
        — correctly, since a belief names the memory it is about — which is what
        left seeing writing to the concept graph and believing nothing.

        `origin` is whose perception this is, and it has no default. A person's
        image is kept in their context, and what it shows goes where their words
        go, never into the substrate's own knowledge."""
        if not self.active:
            return None
        
        try:
            start_time = datetime.now().timestamp()
            
            # Create perception data
            perception = PerceptionData(
                source=source,
                data_type=data_type,
                content=content,
                confidence=self._calculate_confidence(content),
                timestamp=start_time,
                origin=origin,
            )
            
            # Process the perception
            processed_perception = await self._analyze_perception(perception)
            
            # Store in queue and database
            perception_id = f"perc_{start_time}_{source}"
            self.perception_queue.append(processed_perception)
            self.processed_perceptions[perception_id] = processed_perception
            
            # Retention is reported, never assumed. The write used to fail on
            # every call and be absorbed, so `total_processed` counted
            # perceptions that no longer existed a moment later.
            try:
                await self._store_perception(perception_id, processed_perception)
                processed_perception.metadata["retained"] = True
            except Exception as e:
                processed_perception.metadata["retained"] = False
                logger.error(
                    "perception %s from %s was analysed but NOT retained: %s",
                    perception_id, source, e)

            # THE PERCEPT'S IDENTITY TRAVELS ON THE PERCEPT, so a caller can
            # bind it as the scope its work is done under (`set_acting_percept`)
            # and a memory formed there links to it BY REFERENCE.
            #
            # BINDING IS NOT DONE HERE, deliberately. This function does not own
            # the scope — it returns, and whatever the caller does next may or
            # may not be about what was just perceived. Binding without owning
            # the reset leaves the percept standing over unrelated later work,
            # which is the recency defect the link exists to remove, arriving by
            # another route. Same contract as `set_acting_intent`: the acting
            # path binds and resets; the authority only supplies the id.
            processed_perception.metadata["perception_id"] = perception_id
            _digest = (content or {}).get("sha256") or (content or {}).get("digest")
            if _digest:
                processed_perception.metadata["digest"] = str(_digest)
            # WHAT THE SUBSTRATE REMEMBERS OF THIS PERCEPT, so a caller reading
            # the percept back can find the episode rather than re-deriving it.
            if memory_id:
                processed_perception.metadata["memory_id"] = str(memory_id)

            # A perception is an OBSERVATION of something the substrate can
            # name, and PerceptionManager was its only consumer -- perceptions
            # were stored, counted, and never became knowledge of anything.
            # Health monitoring, the live producer, supplies a component and a
            # condition in typed fields, so nothing has to read the message
            # text to know what was observed.
            # ADMITTED INSIDE THE SCOPE OF THE PERCEPT, so anything formed
            # while the evidence is being admitted links to what was perceived
            # BY REFERENCE rather than by having happened near it in time.
            token = set_acting_percept(perception_id, _digest)
            try:
                await self._observe_semantically(source, data_type, content,
                                                 memory_id=memory_id, origin=origin)
            finally:
                reset_acting_percept(token)

            # Update statistics
            processing_time = datetime.now().timestamp() - start_time
            self._update_stats(processing_time, processed_perception.confidence,
                               retained=processed_perception.metadata.get("retained", False))
            
            logger.debug(f"Processed perception from {source}: {data_type}")
            return processed_perception
            
        except Exception as e:
            logger.error(f"Error processing perception input: {e}")
            return None
    
    async def _observe_semantically(self, source, data_type, content, *,
                                    memory_id: Optional[str] = None,
                                    origin: "Origin") -> None:
        """Submit a perception as evidence. Never fails perception itself.

        Dispatched on modality: a sensor reading, an image, a video and a sound
        each carry structure a bare component/status envelope cannot (a typed
        value and unit, perceived individuals, recognised labels, temporal
        events), so each has its own producer. Anything else -- the original health-monitoring case, a named
        component in a named state -- takes the general `submit_perception` path.
        The producer decides what is nameable; an unrecognised modality is not
        coerced into one that loses its structure. Whose it is travels with it."""
        try:
            from core.domain import evidence_producers as ep

            modality = {
                "sensor": ep.submit_sensor_reading,
                "image": ep.submit_image,
                "video": ep.submit_video,
                "audio": ep.submit_audio,
            }.get(str(data_type or "").strip().lower())

            if modality is not None:
                await modality(source, content or {}, memory_id=memory_id, origin=origin)
            else:
                await ep.submit_perception(source, data_type, content or {},
                                           memory_id=memory_id, origin=origin)
        except Exception as e:
            logger.error(
                "perception from %s could not be recorded as evidence: %s: %s",
                source, type(e).__name__, e)

    def note_perception(self, source: str, data_type: str,
                        content: Dict[str, Any], *, origin: "Origin",
                        confidence: float = 1.0) -> PerceptionData:
        """Record what was just perceived into the overall perceptual awareness —
        WITHOUT re-admitting it as evidence. For a percept whose evidence was already
        admitted by its own owner (a recognition rides `learn_fact`; a sensed image
        rides `process_input`): this only updates the live perceptual state, so the
        substrate knows what it is currently perceiving and a memory forming now can
        stamp that context. Calling `process_input` here would double-admit.
        `origin` is whose perception it is, as for `process_input`."""
        perception = PerceptionData(source=source, data_type=data_type,
                                    content=dict(content or {}),
                                    confidence=float(confidence), origin=origin)
        self.perception_queue.append(perception)
        return perception

    async def get_recent_perceptions(self, limit: int = 10) -> List[PerceptionData]:
        """Get most recent perception data"""
        return list(self.perception_queue)[-limit:]
    
    async def search_perceptions(self, query: Dict[str, Any]) -> List[PerceptionData]:
        """Search retained perceptions.

        Rewritten because every part of the previous query was wrong for the
        database it runs against: `?` and `%s` placeholders (SQLite and
        psycopg2) against an asyncpg pool that takes `$1`, an unqualified table
        that does not exist, and positional row indexing against a manager that
        returns mapping rows. It could not have returned a result under any
        input, and the `except` around it reported that as "no perceptions
        found".
        """
        if not self.connection:
            raise RuntimeError(
                "perception manager has no database connection; initialize() "
                "must run before perceptions can be searched")

        # WHOSE: the substrate's own perceptions unless a person's are asked for
        # (`owner`), never everyone's at once.
        conditions, params = [], [query.get("owner")]
        conditions.append("owner IS NOT DISTINCT FROM $1")
        for key, column, operator in (("source", "source", "="),
                                      ("data_type", "data_type", "="),
                                      ("min_confidence", "confidence", ">=")):
            if key in query:
                params.append(query[key])
                conditions.append(f"{column} {operator} ${len(params)}")

        params.append(int(query.get("limit", 50)))
        where = " AND ".join(conditions)
        # A per-owner table is read where its owner's rows are kept: the
        # substrate's own in the model, a person's in their context.
        rows = await self.connection.execute_query(
            f"""SELECT id, source, data_type, content, confidence, timestamp, metadata, owner
                FROM unified.perceptions
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ${len(params)}""",
            tuple(params), fetch_all=True,
            store="user_context" if query.get("owner") else "model") or []

        import json
        from core.memory import Origin

        def _obj(value):
            return json.loads(value) if isinstance(value, str) else (value or {})

        return [PerceptionData(
            source=row["source"],
            data_type=row["data_type"],
            content=_obj(row["content"]),
            confidence=row["confidence"],
            timestamp=row["timestamp"],
            metadata=_obj(row["metadata"]),
            origin=Origin.of(row["owner"], "perception"),
        ) for row in rows]

    async def get_statistics(self) -> Dict[str, Any]:
        """Get perception processing statistics"""
        self.stats["queue_length"] = len(self.perception_queue)
        return self.stats.copy()
    
    async def _analyze_perception(self, perception: PerceptionData) -> PerceptionData:
        """Analyze and enhance perception data"""
        # Simple analysis - can be enhanced as needed
        analysis_metadata = {
            "processed_at": datetime.now().timestamp(),
            "analysis_version": "1.0"
        }
        
        # Add pattern recognition, feature extraction, etc. here
        if perception.data_type == "text":
            analysis_metadata["word_count"] = len(perception.content.get("text", "").split())
        elif perception.data_type == "image":
            analysis_metadata["image_size"] = perception.content.get("dimensions", "unknown")
        
        perception.metadata.update(analysis_metadata)
        return perception
    
    def _calculate_confidence(self, content: Dict[str, Any]) -> float:
        """Calculate confidence score for perception data"""
        # Simple confidence calculation - can be enhanced
        base_confidence = 0.8
        
        # Adjust based on data completeness
        if "text" in content and len(content["text"]) > 0:
            base_confidence += 0.1
        if "metadata" in content:
            base_confidence += 0.1
        
        return min(1.0, base_confidence)
    
    async def _store_perception(self, perception_id: str, perception: PerceptionData) -> bool:
        """Store perception in the database. Raises when the write fails."""
        if not self.connection:
            raise RuntimeError(
                "perception manager has no database connection; initialize() "
                "must run before a perception can be retained")

        try:
            import json
            from core.agents.memory_agent import memory_agent
            await memory_agent().hold_perception(
                perception_id=perception_id, source=perception.source,
                data_type=perception.data_type, content=json.dumps(perception.content),
                confidence=perception.confidence, timestamp=perception.timestamp,
                metadata=json.dumps(perception.metadata), origin=perception.origin)

            return True

        except Exception as e:
            # Raised to the caller rather than absorbed. A perception that was
            # analysed but not retained is not a processed perception, and
            # counting it as one is how this subsystem reported four years of
            # activity while persisting nothing.
            logger.error("Error storing perception %s: %s", perception_id, e)
            raise

    def _update_stats(self, processing_time: float, confidence: float,
                      retained: bool = True):
        """Update processing statistics.

        `total_retained` is tracked apart from `total_processed` so the gap
        between "analysed" and "still exists" is visible in the statistics
        rather than only in a log line.
        """
        self.stats["total_processed"] += 1
        if retained:
            self.stats["total_retained"] += 1
        
        # Update averages
        total = self.stats["total_processed"]
        self.stats["processing_time_avg"] = (
            (self.stats["processing_time_avg"] * (total - 1) + processing_time) / total
        )
        self.stats["confidence_avg"] = (
            (self.stats["confidence_avg"] * (total - 1) + confidence) / total
        )
    
    async def shutdown(self):
        """Shutdown the perception manager"""
        self.active = False
        # Database cleanup is handled by the unified database itself
        self.connection = None
        logger.info("Perception manager shutdown completed")

# ══════════════════════════════════════════════════════════════════════════
# WHAT THE SUBSTRATE IS PERCEIVING RIGHT NOW — bound to the acting context
# ══════════════════════════════════════════════════════════════════════════
#
# The perceptual counterpart of `set_acting_intent`, and it exists for the same
# reason that one does: a memory forming while the substrate is perceiving has
# to be able to say WHICH percept it is of, by reference.
#
# WHAT THIS REPLACES. A memory already carried a `perceptual_state` snapshot,
# attached by RECENCY — a 120-second window over whatever had been perceived
# lately. That is a correlation: it says something was in view around then, and
# it degrades exactly where it matters most, when several things were seen close
# together. "I saw that employee send that email" then rests on the substrate's
# word plus a nearby timestamp, which is testimony, not a record.
#
# A reference is defensible where a recollection is not: the percept holds what
# was actually sensed, and its digest identifies the very bytes.
#
# MODALITY-AGNOSTIC. `percept`, not `image` — hearing and voice arrive through
# the same door and bind here the same way.

import contextvars as _contextvars

_acting_percept: "_contextvars.ContextVar[Optional[Dict[str, Any]]]" = \
    _contextvars.ContextVar("lyric_acting_percept", default=None)


def set_acting_percept(percept_id: Optional[str],
                       digest: Optional[str] = None):
    """Bind the percept the current work is being done under. Returns the token.

    `digest` is the content identity of the thing perceived (an image's sha256),
    carried beside the id so the OBJECT stays identifiable even if the percept
    row is later pruned.
    """
    if not percept_id:
        return _acting_percept.set(None)
    return _acting_percept.set({"percept_id": str(percept_id),
                                "percept_digest": str(digest) if digest else None})


def get_acting_percept() -> Optional[Dict[str, Any]]:
    """The percept bound to the current async context, or None. None is honest:
    work that is not being done under a percept must not borrow one."""
    return _acting_percept.get()


def reset_acting_percept(token) -> None:
    try:
        _acting_percept.reset(token)
    except (ValueError, LookupError):
        # A token from another context is not this context's to reset; losing the
        # reset is harmless (the context ends), silently ignoring a real error is
        # not, so only these two are caught.
        pass
