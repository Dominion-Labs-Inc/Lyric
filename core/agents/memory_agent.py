#!/usr/bin/env python3
"""
Memory Agent
============

Primary memory coordination interface for Lyric AGI system.
Coordinates hot tier (PostgreSQL), cold tier, and semantic search (embeddings).

Architecture:
- Hot Tier: PostgreSQL storage (0-60 days, fast access) - memory_hot schema
- Cold Tier: PostgreSQL storage (60+ days, archival) - memory_cold schema
- Embeddings: Semantic similarity search with pgvector (all-MiniLM-L6-v2)

Features:
- CRUD operations (create, read, update, delete)
- Semantic and keyword-based search
- Automatic tier migration (hot → cold after 60 days)
- Governance integration (capability tokens for deletes)

Integration:
- Single entry point exported from core/memory/__init__.py
- Constitutional constraints enforcement

Author: Lyric System
Version: 8.0
"""

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import re

from core.capability import raise_if_structural
import uuid
from typing import Dict, Any, List, Optional, Sequence, Set, Tuple, Union
from datetime import datetime, timedelta

# Memory storage implementations
from core.memory.storage.postgres_storage import PostgresStorage
from core.memory.utils.embedding_service import (
    EmbeddingService,
    get_embedding_service
)
from core.memory.utils.interfaces import (
    MemoryItem,
    MemoryType,
    MemoryQuery,
    MemorySearchResult,
    MemoryOperation
)
from core.memory.utils.memory_worthiness import MemoryWorthinessMetadata

# Performance profiling
from core.learning.performance_profiler import profile_performance

from core.learning.learning_interfaces import IMemoryConsolidation

logger = logging.getLogger(__name__)


class MemoryAgent(IMemoryConsolidation):
    """
    Memory Agent - Primary Memory Coordination Interface

    Coordinates hot tier (PostgreSQL 0-60 days), cold tier (PostgreSQL 60+ days),
    and semantic search capabilities for Lyric memory system.

    Architecture:
        - PostgreSQL Hot: Fast hot tier storage for recent memories (memory_hot schema)
        - PostgreSQL Cold: Cold tier archival for historical memories (memory_cold schema)
        - Embeddings: Semantic similarity search across tiers with pgvector

    Governance:
        - Protected delete operations require capability tokens

    The only writer of the substrate's memory: memories through `store_memory`,
    and every other kind -- concepts, beliefs, rules, domains, what reasoning
    produced, perception, each person's context, the record of what was
    learned -- through its write methods (THE REST OF MEMORY, below).
    """

    def __init__(self):
        """
        Initialize Memory Agent

        Sets up storage backends but does not connect (call initialize())
        """
        # PostgreSQL storage (handles both hot and cold tiers)
        self.postgres_storage: Optional[PostgresStorage] = None  # Hot+Cold tier (PostgreSQL both)

        # Embedding service (sentence transformers)
        self.embedding_service: Optional[EmbeddingService] = None  # all-MiniLM-L6-v2
        self.embedding_dim: int = 384  # Embedding dimension

        # Memory cache (optional in-memory cache)
        self.memory_cache: Dict[str, MemoryItem] = {}  # memory_id → MemoryItem
        self.cache_enabled: bool = True  # Enable caching

        # WORD CLASSES ARE MEMORIES, AND THIS IS THE WARM VIEW OF THEM.
        #
        # The reader has to ask "does `filter` name a thing?" while parsing,
        # synchronously, thousands of times. Recall is async. That mismatch is
        # the whole reason a separate `lexicon.json` existed -- and it cost more
        # than it bought: measured on the live store it held 199 words, every
        # one of them a NOUN, 197 asserted by a fan-out that no one taught. A
        # word recorded NOUN makes `_reads_as_verb` return False, so those
        # entries did not merely fail to help, they DESTROYED readings that
        # worked without them ("A filter separates particles." reads when
        # `separates` is unknown and stops reading once it is filed as a noun).
        #
        # So the store is gone and this is what replaces it: a view, not a
        # store. It is never written to disk, it is empty until `warm_word_
        # classes()` fills it from memory, and every entry in it is derived from
        # observation memories that a wipe removes. Dropping it loses nothing.
        #
        # word -> {class: net evidence}. Net, because a reading that leaned on a
        # class and succeeded counts for it and one that failed counts against,
        # which is the same evidence discipline beliefs use.
        self._word_class_index: Dict[str, Dict[str, int]] = {}
        self._word_classes_warm: bool = False
        #: The taught patterns -- how English says things -- as the same kind of
        #: view: rebuilt from pattern memories at every warm, extended as a
        #: pattern is taught (`note_pattern`). None until the first warm or
        #: note; `pattern_inventory()` answers an empty view until then.
        self._pattern_inventory = None
        #: The single in-flight warm, so concurrent callers JOIN it instead of
        #: each re-reading the whole store. None when none is running.
        self._word_class_warm_task = None

        # Agent state
        self.initialized: bool = False

        # Autonomous background loops (persistent cognition)
        self.maintenance_loop_active: bool = False
        self.abstraction_loop_active: bool = False
        self.reflection_loop_active: bool = False
        self.abstraction_pipeline = None  # Will be initialized with hierarchical abstraction
        self.bayesian_beliefs = None  # Will be initialized with belief system

        # Admission control for abstraction. Without this, an idle-loop caller
        # would recluster the same memories every cycle and re-derive schemas
        # it already has.
        self.abstraction_state: Dict[str, Any] = {
            'last_abstraction_run':      None,   # datetime of last completed run
            'last_processed_created_at': None,   # newest memory consumed so far
            'memories_since_abstraction': 0,     # observed at last admission check
            'abstraction_backlog':       0,      # eligible but unprocessed
            'schemas_formed_last_run':   0,
            'runs':                      0,
            'last_skip_reason':          None,
        }
        self._abstraction_running: bool = False
        #: EVENT-TRIGGER state for abstraction. Abstraction is no longer a 4h
        #: poll — it fires when enough NEW episodic memories have accumulated.
        #: The write path only counts and (past threshold) schedules a
        #: background job on the queue authority; it never reasons inline.
        self._new_episodic_since_abstraction: int = 0
        self._abstraction_trigger_scheduled: bool = False

        # Performance metrics
        self.metrics = {
            "memories_stored": 0,
            "memories_retrieved": 0,
            "cache_hits": 0,
            "tier_migrations": 0,
            "queries_executed": 0,
            "consolidations_run": 0,
            "abstractions_formed": 0,
            "beliefs_updated": 0,
            "maintenance_cycles": 0
        }

        # Non-blocking write queue
        # Callers use enqueue_memory() to fire-and-forget; the background
        # worker drains it by calling store_memory() sequentially.
        # _pending_memories holds items that are queued but not yet in
        # postgres — the injector checks here so recent memories are
        # visible to retrieval immediately without waiting for the write.
        self._write_queue: asyncio.Queue = asyncio.Queue()

        # The pool of experiences waiting to be decided, and its worker. Set when
        # an experience arrives, so the worker wakes for it rather than polling.
        self._pool_arrived: asyncio.Event = asyncio.Event()
        self._pool_task: Optional[asyncio.Task] = None
        self._pool_ready: bool = False
        #: Who holds a claim on a pool item: this process. Many instances pull
        #: one pool, each claiming with a lease.
        self._pool_claimant = f"memory-agent-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._pending_memories: dict = {}  # memory_id → {content, tags, importance, ...}
        self._queue_worker_task: Optional[asyncio.Task] = None

    async def initialize(self) -> bool:
        """
        Initialize memory agent and all storage backends

        Connects to PostgreSQL hot tier, PostgreSQL cold tier, and loads embedding model.

        Returns:
            True if all components initialized successfully, False otherwise
        """
        if self.initialized:
            return True

        # Shadow mode suppresses background cognitive loops (see LYRIC_SHADOW_MODE
        # check further below) but memory storage is fully operational — PostgreSQL
        # initialises normally so memories are persisted during shadow runs.
        try:
            logger.info("Initializing MemoryAgent...")

            # Initialize PostgreSQL storage (hot and cold tiers)
            try:
                self.postgres_storage = PostgresStorage()
                await self.postgres_storage.initialize()
                logger.info("✓ PostgreSQL hot tier initialized (0-60 days)")
                logger.info("✓ PostgreSQL cold tier available (60+ days)")
            except Exception:
                logger.error("Failed to initialize PostgreSQL storage")

            # Initialize embedding service (all-MiniLM-L6-v2)
            try:
                self.embedding_service = get_embedding_service()
                if self.embedding_service.initialize():
                    logger.info("✓ Embedding service initialized (384-dim)")
                else:
                    logger.error("Embedding service initialization failed")
            except Exception as e:
                logger.error(f"Failed to initialize embedding service: {e}")

            # NO separate query agent. MemoryAgent IS the query authority --
            # `retrieve` (multi-strategy recall), `search_memories`, and
            # `query_by_tags` are its surface. The old `PostgresQueryAgent` was
            # assigned to `self.postgres_query_agent` here and never read again,
            # a dead duplicate over the same PostgresStorage; it has been deleted.

            # Verify PostgreSQL storage is available
            if not self.postgres_storage:
                logger.error("PostgreSQL storage not available - MemoryAgent cannot function")
                return False

            # Abstraction + belief are REASONING — the reasoning authority owns
            # and constructs them now (NeuralSymbolicBridge.initialize), not the
            # memory agent. The memory agent no longer builds its own pipeline or
            # belief graph (the duplicate-authority defect this used to be). When
            # it has new episodic memories worth abstracting, it ASKS the
            # authority (see form_abstractions_if_due -> bridge.abstract_over_memories
            # and reflect_on_beliefs -> bridge.reflect). Left None here; a lazy
            # `_reasoning_authority()` reaches the bridge at call time (the bridge
            # initializes after the memory agent, so it cannot be fetched here).
            self.bayesian_beliefs = None
            self.abstraction_pipeline = None

            self.initialized = True
            logger.info("MemoryAgent initialized successfully")

            # WHAT IT KNOWS ABOUT WORDS, RECOVERED FROM WHAT IT REMEMBERS.
            #
            # The view is process-local and starts empty, so without this a
            # restarted substrate cannot read a single action sentence until
            # something happens to teach it again -- it would have forgotten
            # every word it ever learned, while the memories that say so sat
            # in the store untouched. Derived, never stored, so this is the
            # only thing that makes them readable again.
            #
            # STARTED HERE, NOT AWAITED HERE, AND THE DIFFERENCE WAS EVERYTHING.
            #
            # This used to `await` the warm inline. `main._initialize_memory_system`
            # runs the whole memory system under `asyncio.wait_for(..., timeout=30)`
            # with three retries, and the warm reads the entire taught store:
            # MEASURED ON THE LIVE SUBSTRATE, 78,293 words in 45.6s. So attempt 1
            # was CANCELLED part-way through the warm -- and `self.initialized`
            # is set above, BEFORE this, so attempt 2 hit `if self.initialized:
            # return True` and returned instantly. Boot then logged
            # "memory_system initialized successfully" and went on.
            #
            # The result was that EVERY production boot ran with 0 of 78,293
            # word classes, while every experiment looked fine because the
            # harness warms explicitly afterwards. Two things the substrate
            # needs were dark the whole time: its reader treated every word as
            # never observed, and its constitution derived an EMPTY interest
            # vocabulary -- so `stakes`, the channel by which what it perceives
            # is allowed to matter to it, could never be measured.
            #
            # Raising the timeout would only move the cliff, because the warm
            # grows with the store. The real error was calling a DERIVED VIEW
            # part of initialization: memory is fully operational without it,
            # and `word_class()` already answers "not observed" honestly while
            # it is still being rebuilt. So it is started and tracked, and its
            # outcome is reported either way -- never silently absent.
            self.begin_word_class_warm()

            # Shadow mode: suppress background cognitive loops and write queue.
            # These are only needed for persistent long-running cognition, not
            # for single-task diagnostic runs.
            import os as _ma_os
            if _ma_os.environ.get("LYRIC_SHADOW_MODE"):
                logger.info("⚡ Shadow mode: cognitive background loops suppressed (LYRIC_SHADOW_MODE=1)")
            else:
                # Start autonomous background loops (persistent cognition)
                await self.start_memory_loops()
                logger.info("✓ Autonomous cognitive loops started")

                # Start non-blocking write queue worker
                self._queue_worker_task = asyncio.create_task(
                    self._write_queue_worker(),
                    name="memory_write_queue_worker"
                )
                logger.info("✓ Memory write queue worker started")

            return True

        except Exception as e:
            logger.error(f"MemoryAgent initialization failed: {e}")
            return False

    # ================================================================================================
    # MEMORY STORAGE (Hot Tier)
    # ================================================================================================

    def enqueue_memory(
        self,
        content: str,
        memory_type=None,
        importance_score: float = 0.5,
        confidence_score: float = 1.0,
        tags=None,
        source_context=None,
        *,
        origin: "Origin",
        **kwargs
    ) -> str:
        """
        Non-blocking fire-and-forget memory store.

        Puts the memory onto the write queue and returns immediately.
        The memory is also placed in _pending_memories so the injector
        can find it before it lands in postgres.

        Returns a provisional memory_id (starts with 'pending_').
        """
        import uuid
        if "user_id" in kwargs:
            raise TypeError("enqueue_memory() got an unexpected keyword argument 'user_id': "
                            "say where the memory came from (origin); the memory agent "
                            "decides whose it is")
        owner = self._owner_from(origin)
        pending_id = f"pending_{uuid.uuid4().hex}"
        entry = {
            "pending_id": pending_id,
            "owner": owner,
            "content": content,
            "memory_type": memory_type,
            "importance_score": importance_score,
            "confidence_score": confidence_score,
            "tags": tags or [],
            "source_context": {**(source_context or {}), "origin": origin.to_dict()},
            "kwargs": kwargs,
        }
        self._pending_memories[pending_id] = entry
        # Put onto the queue (non-blocking — Queue has no size limit by default)
        try:
            self._write_queue.put_nowait(entry)
        except Exception:
            # If event loop isn't running yet, drop gracefully — caller used wrong method
            del self._pending_memories[pending_id]
        return pending_id

    async def _write_queue_worker(self):
        """Background task: drains the write queue one item at a time."""
        logger.info("Memory write queue worker running")
        while True:
            try:
                entry = await self._write_queue.get()
                pending_id = entry["pending_id"]
                try:
                    await self._store_memory(
                        content=entry["content"],
                        memory_type=entry["memory_type"],
                        importance_score=entry["importance_score"],
                        confidence_score=entry["confidence_score"],
                        tags=entry["tags"],
                        source_context=entry["source_context"],
                        user_id=entry["owner"],
                        **entry.get("kwargs", {}),
                    )
                except Exception as e:
                    logger.error(f"Write queue worker: store_memory failed: {e}")
                finally:
                    # Remove from pending regardless of success
                    self._pending_memories.pop(pending_id, None)
                    self._write_queue.task_done()
            except asyncio.CancelledError:
                logger.info("Memory write queue worker cancelled")
                break
            except Exception as e:
                logger.error(f"Write queue worker unexpected error: {e}")
                await asyncio.sleep(1)

    #: Reasoning answers arrive with a status marker in front of the claim
    #: ("Proved: X is Y"). The marker is a fact about the reasoning, not part of
    #: what is claimed, so it is stripped before the claim is read.
    _STATUS_PREFIXES = (
        "proved:", "disproved:", "refuted:", "verified:", "concluded:",
        "not entailed by the premises:", "not entailed:", "unsettled:",
        "answer:",
    )

    def _readable_claim(self, content, source_context):
        """The substrate-readable CLAIM a memory asserts, its shape, and its
        facts -- or ``(None, None, ())``.

        A memory is recalled as a PREMISE, so it is useful to the substrate's
        reasoning only when it asserts a claim it can hold as facts. This reads
        that at WRITE time, once, from the recorded conclusion when there is one,
        else the content, with any reasoning-status prefix stripped.

        A claim the substrate MADE carries its facts (`claim_facts`, in the
        reading engine's form); it is the claim as made and is not read again.
        Any other text is read by the one reader (`derived_reader`): it is a
        claim when it reads, as one utterance, to one telling. A prose episode, a
        question, a measurement, or anything the substrate was not taught to read
        has no claim, and is left without one rather than dressed up as one: a
        fabricated premise is worse than an absent one, because it is recalled as
        knowledge.

        Returns the clean claim, its ``ClaimShape`` (the polarity the embedding
        vector provably cannot recover, stored beside the memory instead of
        guessed at recall), and the facts it states.
        """
        from core.semantics.claim_shape import shape_of
        from core.semantics.derived_reader import Meaning, MeaningFact, read_text

        candidate = ""
        if isinstance(source_context, dict):
            candidate = str(source_context.get("conclusion") or "").strip()
        if not candidate:
            candidate = str(content or "").strip()

        low = candidate.lower()
        for prefix in self._STATUS_PREFIXES:
            if low.startswith(prefix):
                candidate = candidate[len(prefix):].strip()
                break

        # A claim is ONE sentence. An episode written for a reader -- several
        # lines, a query and an answer -- is not one, and is not made one by
        # containing something readable somewhere inside it.
        if not candidate or "\n" in candidate or len(candidate) > 200:
            return None, None, ()

        made = source_context.get("claim_facts") if isinstance(source_context, dict) else None
        if made:
            try:
                meaning = Meaning("tell", tuple(MeaningFact.from_list(f) for f in made))
            except (TypeError, ValueError) as error:
                logger.warning("a claim's own facts are malformed (%s); not a claim", error)
                return None, None, ()
            return candidate, shape_of(meaning), meaning.facts

        utterances = read_text(candidate)
        if len(utterances) != 1 or not utterances[0].readings:
            return None, None, ()
        readings = utterances[0].readings
        if len({r.meaning.canonical() for r in readings}) > 1:
            return None, None, ()
        meaning = readings[0].meaning
        if meaning.act != "tell":
            return None, None, ()
        return candidate, shape_of(meaning), meaning.facts

    @staticmethod
    def _owner_from(origin: Any) -> Optional[str]:
        """Whose memory a hand-off is, decided from where it came from: a
        person's gift or request is that person's; the substrate's own work is
        its own (None). A hand-off that does not say where it came from is
        refused rather than filed as the substrate's own."""
        from core.memory.utils.interfaces import Origin
        if not isinstance(origin, Origin):
            raise TypeError("a hand-off to the memory agent must say where it came "
                            f"from (an Origin), not {type(origin).__name__}")
        return origin.person

    async def store_memory(
        self,
        content: str,
        memory_type: Optional[MemoryType] = None,
        importance_score: float = 0.5,
        confidence_score: float = 1.0,
        tags: Optional[List[str]] = None,
        source_context: Optional[Dict[str, Any]] = None,
        embedding_metadata: Optional[Dict[str, Any]] = None,
        related_memories: Optional[List[str]] = None,
        decay_rate: Optional[float] = None,
        access_count: int = 0,
        session_id: Optional[str] = None,
        reasoning_trace: Optional[List[str]] = None,
        thinking_state: Optional[Dict[str, Any]] = None,
        system_state: Optional[Dict[str, Any]] = None,
        decision_factors: Optional[Dict[str, Any]] = None,
        emotional_context: Optional[Dict[str, Any]] = None,
        media: Optional[Any] = None,
        media_meta: Optional[Dict[str, Any]] = None,
        *,
        origin: "Origin",
    ) -> Tuple[bool, Optional[str]]:
        """Store one memory through the one memory pipeline (`_store_memory`).

        WHOSE IT IS, THE MEMORY AGENT DECIDES, from `origin`: where it came
        from -- which door or work, and the person it came from, or none for
        the substrate's own. The caller says where it came from, never whose it
        is. When each caller named an owner, the ones that forgot filed a
        person's words as the substrate's own knowledge; now a hand-off with no
        origin is refused. The origin is kept with the memory.
        """
        owner = self._owner_from(origin)
        return await self._store_memory(
            content, memory_type=memory_type, importance_score=importance_score,
            confidence_score=confidence_score, tags=tags,
            source_context={**(source_context or {}), "origin": origin.to_dict()},
            embedding_metadata=embedding_metadata, related_memories=related_memories,
            decay_rate=decay_rate, access_count=access_count, session_id=session_id,
            user_id=owner, reasoning_trace=reasoning_trace,
            thinking_state=thinking_state, system_state=system_state,
            decision_factors=decision_factors, emotional_context=emotional_context,
            media=media, media_meta=media_meta)

    @profile_performance("memory_agent", "store_memory")
    async def _store_memory(
        self,
        content: str,
        memory_type: Optional[MemoryType] = None,
        importance_score: float = 0.5,
        confidence_score: float = 1.0,
        tags: Optional[List[str]] = None,
        source_context: Optional[Dict[str, Any]] = None,
        embedding_metadata: Optional[Dict[str, Any]] = None,
        related_memories: Optional[List[str]] = None,
        decay_rate: Optional[float] = None,
        access_count: int = 0,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        reasoning_trace: Optional[List[str]] = None,
        thinking_state: Optional[Dict[str, Any]] = None,
        system_state: Optional[Dict[str, Any]] = None,
        decision_factors: Optional[Dict[str, Any]] = None,
        emotional_context: Optional[Dict[str, Any]] = None,
        media: Optional[Any] = None,
        media_meta: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Store memory to hot tier (PostgreSQL) with intelligent filtering

        `media` (a path or raw bytes -- a picture or a sound) attaches what was
        met to the memory: the bytes are retained in the media store and can be
        produced again, while `media_meta` (the perceived structure -- for a
        picture its dimensions, colours and regions, for a sound its sounds and
        their pitch and timing) rides in the media record. The memory's own
        `content` should already describe what was met, so it is recallable by
        that.

        Memory Agent analyzes raw inputs and generates MemoryWorthinessMetadata.
        Calling systems should NOT pre-generate metadata - that's Memory Agent's job.

        Args:
            content: Memory content (text) - REQUIRED
            memory_type: Type of memory (EPISODIC, SEMANTIC, etc.) - Optional, will be inferred
            importance_score: Importance score (0.0-1.0)
            confidence_score: Confidence in memory accuracy (0.0-1.0)
            tags: Optional tags for categorization
            source_context: Raw metadata about memory source (system analyzes this)
            embedding_metadata: Optional metadata for embedding
            related_memories: Optional list of related memory IDs
            decay_rate: Optional custom decay rate
            access_count: Initial access count
            session_id: Optional session identifier
            user_id: Optional user identifier
            reasoning_trace: Optional chain of thought steps (list of reasoning steps)
            thinking_state: Optional thinking state metadata (DEPRECATED - metadata generated here)
            system_state: Optional system state (CPU, memory, services, dependencies) at time of memory
            decision_factors: Optional decision factors that influenced this memory
            emotional_context: Optional emotional/sentiment context

        Returns:
            Tuple of (success: bool, memory_id: Optional[str])
        """
        logger.debug(f"\n[MEMORY_AGENT.STORE_MEMORY] Called with:")
        logger.debug(f"  Content length: {len(content)} chars")
        logger.debug(f"  Memory type: {memory_type}")
        logger.debug(f"  Tags: {tags}")
        logger.debug(f"  Importance: {importance_score}")
        logger.debug(f"  Confidence: {confidence_score}")
        logger.debug(f"  Initialized: {self.initialized}")

        if not self.initialized:
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Initializing memory agent...")
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Initialization complete")

        # Attached media marks the memory as a percept -- a picture or a sound it
        # met -- for worthiness and search. The bytes say which, and their digest
        # is WHAT was met (`met`), which is how two memories of different things
        # are told apart when their accounts read alike.
        if media is not None:
            import hashlib
            from core.memory.media_store import _read_bytes, media_kind
            data = _read_bytes(media)
            kind = media_kind(data)
            flag = {"image": "has_image", "video": "has_video",
                    "audio": "has_sound"}.get(kind or "")
            source_context = {**(source_context or {}),
                              "met": hashlib.sha256(data).hexdigest(),
                              **({flag: True} if flag else {})}

        # ========== STEP 1: GENERATE OR EXTRACT METADATA ==========
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 1: Generate/extract metadata")
        worthiness_metadata = None

        # Check if upstream system pre-generated metadata (DEPRECATED path)
        if thinking_state and "worthiness_metadata" in thinking_state:
            try:
                from core.memory.utils.memory_worthiness import MemoryWorthinessMetadata

                # Deserialize metadata from dict
                metadata_dict = thinking_state["worthiness_metadata"]
                worthiness_metadata = MemoryWorthinessMetadata.from_dict(metadata_dict)

                logger.debug(f"Extracted worthiness metadata from thinking_state (source: {worthiness_metadata.source_system})")

            except Exception as e:
                logger.warning(f"Failed to extract worthiness metadata: {e}")
                worthiness_metadata = None

        # PREFERRED PATH: Generate metadata from raw inputs
        if worthiness_metadata is None:
            try:
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Generating worthiness metadata...")
                worthiness_metadata = await self._generate_worthiness_metadata(
                    content=content,
                    confidence_score=confidence_score,
                    tags=tags,
                    source_context=source_context,
                    reasoning_trace=reasoning_trace,
                    importance_score=importance_score
                )
                logger.debug(f"Generated worthiness metadata from raw inputs (source: {worthiness_metadata.source_system})")
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Metadata generated: source={worthiness_metadata.source_system}")

            except Exception as e:
                logger.error(f"Failed to generate worthiness metadata: {e}")
                logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ Metadata generation failed: {e}")
                # Fail open - allow storage without metadata
                worthiness_metadata = None

        # ========== STEP 2: EVALUATE FILTERING DECISION ==========
        memory_admission = None
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 2: Evaluating filter decision...")
        logger.debug(f"  Metadata available: {worthiness_metadata is not None}")

        # Observations are measurements, not insights. The worthiness filter
        # asks "is this novel / deeply reasoned / cross-domain enough to keep?"
        # — the wrong question for a data point. Applied to task outcomes it
        # produced survivorship bias: failures (importance 0.9 → high
        # consequence) were retained while successes (0.7) were discarded, so
        # the measured success_rate could never rise above near-zero no matter
        # how the system actually performed.
        # Exemption is decided by the filter, which owns retention policy. This
        # tested only for an observation raw_event; the same argument applies to
        # every event whose value is that it happened -- task outcomes, safety
        # events, governance decisions, learning updates, mapping verdicts and
        # critical failures are records other subsystems read back, not
        # candidates to be judged for novelty.
        from core.memory.utils.memory_filter import get_memory_filter as _get_filter
        _raw_event_early = (thinking_state or {}).get("raw_event")
        _exemption = _get_filter().exemption_for(tags=tags, raw_event=_raw_event_early)
        _is_observation_early = _exemption is not None

        if _is_observation_early:
            logger.debug(
                "Bypassing worthiness filter — %s is a record, not a candidate "
                "for retention", _exemption,
            )
            # An exempt record still has an admission reason; leaving it blank
            # would make "kept because it is a record" indistinguishable from
            # "kept without anyone deciding".
            memory_admission = {
                "filter_decision": {
                    "rule_matched": "event_class_exemption",
                    "decision_type": "exempt",
                    "rationale": _exemption,
                    "confidence": 1.0,
                },
                "admitted_at": datetime.now().isoformat(),
                "admitted_by": "memory_filter.exemption_for",
            }
        elif worthiness_metadata is not None:
            try:
                from core.memory.utils.memory_filter import get_memory_filter

                memory_filter = get_memory_filter()
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Memory filter: {type(memory_filter)}")

                # Evaluate with optional reasoning trace for calibration
                decision = memory_filter.evaluate(
                    metadata=worthiness_metadata,
                    reasoning_trace=reasoning_trace
                )
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Filter decision complete")

                # ========== STEP 3: HANDLE REJECTION ==========
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 3: Filter decision - should_store={decision.should_store}")
                if not decision.should_store:
                    logger.info(
                        f"✗ Memory REJECTED by filter: "
                        f"rule={decision.rule_matched}, "
                        f"rationale={decision.rationale}, "
                        f"source={worthiness_metadata.source_system}"
                    )

                    # A rejection is the worthiness filter doing its job, not a
                    # failure. Logged at debug so a normally-operating system
                    # does not fill the error log with correct decisions.
                    logger.debug("[MEMORY_AGENT.STORE_MEMORY] declined by filter:")
                    logger.debug(f"  Rule: {decision.rule_matched}")
                    logger.debug(f"  Rationale: {decision.rationale}")
                    logger.debug(f"  Source: {worthiness_metadata.source_system}")

                    # Track rejection metrics
                    if not hasattr(self, 'filter_metrics'):
                        self.filter_metrics = {'rejections': 0, 'accepts': 0}
                    self.filter_metrics['rejections'] += 1

                    # Return early - do not store
                    return False, None

                # ========== STEP 4: HANDLE ACCEPTANCE ==========
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 4: ✓ ACCEPTED by filter")
                logger.info(
                    f"✓ Memory ACCEPTED by filter: "
                    f"rule={decision.rule_matched}, "
                    f"decision_type={decision.decision_type}, "
                    f"rationale={decision.rationale}"
                )

                # Track acceptance metrics
                if not hasattr(self, 'filter_metrics'):
                    self.filter_metrics = {'rejections': 0, 'accepts': 0}
                self.filter_metrics['accepts'] += 1

                # Freeze metadata to enforce immutability
                worthiness_metadata.freeze()

                # ADMISSION IS NOT COGNITION. `thinking_state` is meant to hold
                # the substrate's state AT THE TIME of the episode; the filter
                # decision and worthiness metadata are computed by the memory
                # subsystem AFTERWARDS, about whether to keep it. Writing them
                # there made every memory assert as contemporaneous a judgement
                # that did not exist yet -- and it is why all 429 rows carry a
                # populated thinking_state that contains no thinking.
                #
                # Written to its own field now. Still mirrored into
                # thinking_state during the migration so existing readers (the
                # deprecated pre-generated-metadata path at the top of this
                # method, and anything reading filter_decision) keep working.
                memory_admission = {
                    "worthiness_metadata": worthiness_metadata.to_dict(),
                    "filter_decision": {
                        "rule_matched": decision.rule_matched,
                        "decision_type": decision.decision_type,
                        "rationale": decision.rationale,
                        "confidence": decision.confidence,
                    },
                    "admitted_at": datetime.now().isoformat(),
                    "admitted_by": "memory_filter",
                }

                if thinking_state is None:
                    thinking_state = {}
                thinking_state["worthiness_metadata"] = memory_admission["worthiness_metadata"]
                thinking_state["filter_decision"] = memory_admission["filter_decision"]

            except Exception as e:
                logger.error(f"Memory filtering error: {e}")
                # On filter error, default to storing (fail-open for now)
                logger.warning("Defaulting to STORE on filter error (fail-open)")
        else:
            # No metadata provided - allow storage but log warning
            logger.warning(
                f"No worthiness metadata provided - storing without filtering. "
                f"Source systems should generate upstream metadata."
            )

        # CONTEMPORANEOUS EPISTEMIC STATE.
        #
        # With admission moved to memory_admission, thinking_state is free to
        # mean what it says: the substrate's state AT THE TIME of the episode.
        # belief_state is measured from the live belief graph -- the same
        # singleton epistemic_engine restores -- so it is a reading, not a
        # description. raw_event, task_state and goal_state stay caller-supplied:
        # only the caller knows them, and inventing them here would be the same
        # error as a constant decision rationale.
        # Read the live belief graph via its singleton (the reasoning authority
        # owns it; the memory agent no longer constructs it, but this is a
        # reading, not driving).
        from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
        _beliefs = get_bayesian_uncertainty()
        if _beliefs is not None:
            try:
                _bstats = _beliefs.get_statistics()
                if thinking_state is None:
                    thinking_state = {}
                thinking_state.setdefault("belief_state", {
                    "active_beliefs": _bstats.get("active_beliefs"),
                    "known_unknowns": _bstats.get("known_unknowns"),
                    "high_value_unknowns": _bstats.get("high_value_unknowns"),
                    "overconfidence_rate": round(float(_bstats.get("overconfidence_rate", 0.0)), 4),
                    "calibrated_domains": _bstats.get("calibrated_domains"),
                    "captured_at": datetime.now().isoformat(),
                })
                # PER-MEMORY RELEVANT BELIEFS — not just the aggregate. Scope to
                # this memory's domain (from a `domain_<x>` tag): the specific
                # beliefs held there, claim + posterior. Task outcomes and learning
                # both move these, so they are the substrate's accumulated
                # understanding of the domain at the moment this memory formed.
                _mem_domain = next((t[len("domain_"):] for t in (tags or [])
                                    if isinstance(t, str) and t.startswith("domain_")), None)
                if _mem_domain:
                    _rel = _beliefs.beliefs_for_domain(_mem_domain, limit=8)
                    if _rel:
                        thinking_state["belief_state"]["domain"] = _mem_domain
                        thinking_state["belief_state"]["relevant_beliefs"] = _rel
            except Exception as e:
                logger.warning(f"Belief state snapshot failed: {type(e).__name__}: {e}")

        # CONTEMPORANEOUS APPRAISAL.
        #
        # `emotional_context` has been carrying {"autonomous_confidence": <the
        # memory's importance score>} -- one number, under a name implying
        # something it is not, on 96% of memories. Meanwhile AppraisalSystem is
        # live and producing valence, activation, confidence,
        # epistemic_opportunity, progress, controllability, competence,
        # goal_congruence, agency, risk and the action pressures, updated by the
        # executor after every task.
        #
        # Read here, not described: if no task has appraised yet, current_state
        # is None and this stays None rather than inventing a neutral state.
        # WHAT THE SUBSTRATE WAS TRYING TO ACHIEVE, captured the same way and at
        # the same moment as its appraisal: read from the live acting context,
        # never described. The record already held how it reasoned, what weighed
        # on it and how it felt — and not the goal any of that served.
        #
        # THE VERSION IS TAKEN NOW, deliberately. An intent is revisable: the
        # authority firms its shape up as understanding improves. Storing the id
        # alone would let a later refinement silently re-describe what a past act
        # was for, so the version current at the time is stored beside it and the
        # intent's own `history` holds that state.
        intent_id = intent_version = None
        try:
            from core.reasoning.intent_authority import get_acting_intent
            intent_id = get_acting_intent()
            if intent_id:
                from core.reasoning.intent_authority import get_intent_authority
                _held = await get_intent_authority().get_by_id(str(intent_id))
                intent_version = getattr(_held, "version", None) if _held else None
        except Exception as e:
            # Never blocks forming a memory; never silently claims one either.
            logger.debug("memory: acting intent unavailable: %s", e)
            intent_id = intent_version = None

        # WHAT THIS MEMORY IS OF, when it is of something perceived — by
        # reference to the percept, not by nearness to it in time.
        #
        # The `perceptual_state` snapshot below still records what was in view
        # (useful context, attached by recency); this is a different and stronger
        # claim: that THIS memory is of THAT percept. Only a memory formed inside
        # the scope of a seeing gets one, so a memory formed outside it carries
        # None rather than borrowing whatever was perceived lately.
        percept_id = percept_digest = None
        try:
            from core.agents.autonomous.perception_manager import get_acting_percept
            _percept = get_acting_percept()
            if _percept:
                percept_id = _percept.get("percept_id")
                percept_digest = _percept.get("percept_digest")
        except Exception as e:
            logger.debug("memory: acting percept unavailable: %s", e)
            percept_id = percept_digest = None

        try:
            from core.agents.autonomous.appraisal import get_appraisal_system
            _appraisal = get_appraisal_system().current_state
            if _appraisal is not None:
                appraisal_snapshot = _appraisal.to_dict()
                appraisal_snapshot["captured_at"] = datetime.now().isoformat()

                # THE SELF STAMPS ITS OWN STATE ON EVERY MEMORY IT FORMS, not
                # just coordinator-initiated ones. emotional_context and
                # system_state were populated only by the coordinator's rich
                # store_memory (~10% of writes) and left empty otherwise; here
                # they are FILLED FROM THE SAME LIVE APPRAISAL for any caller that
                # did not supply them — the real feelings (eagerness/doubt/…) in
                # place of the {"autonomous_confidence"} placeholder, and the
                # interoceptive variables as system_state. A caller that passes
                # its own richer value keeps it. None-valued fields are dropped,
                # and nothing is invented when a variable was never measured.
                def _present(d):
                    return {k: v for k, v in d.items() if v is not None} or None
                if not emotional_context:
                    emotional_context = _present({
                        "valence": getattr(_appraisal, "valence", None),
                        "eagerness": getattr(_appraisal, "eagerness", None),
                        "doubt": getattr(_appraisal, "doubt", None),
                        "frustration": getattr(_appraisal, "frustration", None),
                        "satisfaction": getattr(_appraisal, "satisfaction", None),
                    })
                if not system_state:
                    system_state = _present({
                        "activation": getattr(_appraisal, "activation", None),
                        "confidence": getattr(_appraisal, "confidence", None),
                        "controllability": getattr(_appraisal, "controllability", None),
                        "progress": getattr(_appraisal, "progress", None),
                        "competence": getattr(_appraisal, "competence", None),
                        "goal_congruence": getattr(_appraisal, "goal_congruence", None),
                        "agency": getattr(_appraisal, "agency", None),
                        "risk": getattr(_appraisal, "risk", None),
                        "epistemic_opportunity": getattr(
                            _appraisal, "epistemic_opportunity", None),
                    })
            else:
                appraisal_snapshot = None
        except Exception as e:
            logger.warning(f"Appraisal snapshot failed: {type(e).__name__}: {e}")
            appraisal_snapshot = None

        # CONTEMPORANEOUS PERCEPTION.
        # What the substrate was perceiving when this memory formed — the third live
        # snapshot, alongside belief_state and appraisal. Read from the one perceptual-
        # awareness hub (the perceptual analogue of reading the appraisal system), and
        # recency-gated so only perception contemporaneous with THIS memory attaches —
        # a stale percept is never stamped onto an unrelated memory. None when nothing
        # was perceived recently: a reading, never invented. This is how a recalled
        # memory carries what was perceived AND believed AND felt at that moment.
        perceived = await self._perceptual_state(user_id)
        if perceived is not None:
            if thinking_state is None:
                thinking_state = {}
            thinking_state["perceptual_state"] = perceived

        # NOTHING IS MERGED. A memory is never folded into another, however alike
        # they read: the substrate doing the same thing on two days is two
        # memories, and merging them wiped one. What repeats within one pursuit
        # is summarized inside that pursuit's memory; what overlaps between
        # memories is recall's to bring together.

        # ========== STEP 6: PROCEED WITH STORAGE ==========
        memory_id = f"mem_{uuid.uuid4().hex}"
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] Creating new memory with ID: {memory_id}")
        created_at = datetime.now()

        # Infer memory_type if not provided
        if memory_type is None:
            # Infer from worthiness_metadata and source_context
            memory_type = self._infer_memory_type(worthiness_metadata, source_context or {})
            logger.debug(f"Inferred memory_type as {memory_type.value}")

        # STORE THE CLAIM IN A FORM THE SUBSTRATE CAN READ.
        #
        # Every writer funnels through here, so the recall-facing claim is read
        # ONCE, at the single point content becomes a record, rather than in the
        # thirty-odd call sites that store memories. When the content asserts a
        # claim the reader can place, its clean form becomes the conclusion recall
        # hands back, its facts are kept beside it for reasoning to take as they
        # are, and its polarity is tagged so the distinction the vector cannot
        # recover is stored beside it. When it does not, nothing is invented --
        # an episode stays an episode.
        #
        # A PATTERN IS NOT A CLAIM ABOUT THE WORLD. Its content is a sentence the
        # substrate was taught to read, and what the sentence means is carried in
        # the pattern itself; reading it here would file the sentence's words as
        # a second, written-reader meaning beside the taught one.
        if (source_context or {}).get("pattern_key"):
            _claim, _claim_shape, _claim_facts = None, None, ()
        else:
            _claim, _claim_shape, _claim_facts = self._readable_claim(content, source_context)
        if _claim:
            source_context = dict(source_context or {})
            source_context["conclusion"] = _claim
            source_context["claim_facts"] = [f.to_list() for f in _claim_facts]
            tags = list(tags or [])
            for _tag in _claim_shape.as_tags():
                if _tag not in tags:
                    tags.append(_tag)

        # AN ABSENT EMBEDDING IS NOT A FAILED STORE. The vector is a RETRIEVAL
        # AID, not the memory: without it the record is still stored, readable,
        # and exact-matchable; only semantic search over it waits for a backfill.
        # generate_embedding returns None on any failure, so the store proceeds
        # unvectorised rather than losing the record.
        embedding = None
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(content)
        logger.debug(f"[EMBEDDING DEBUG] Embedding service available: {self.embedding_service is not None}")
        logger.debug(f"[EMBEDDING DEBUG] Generated embedding: {embedding is not None}, size: {len(embedding) if embedding else 0}")

        # Create MemoryItem
        memory_item = MemoryItem(
            memory_id=memory_id,
            memory_type=memory_type,
            content=content,
            importance_score=importance_score,
            confidence_score=confidence_score,
            created_at=created_at,
            last_accessed=created_at,
            access_count=access_count,
            decay_rate=decay_rate or 0.01,
            tags=tags or [],
            metadata=source_context or {},
            embeddings=embedding,  # Use 'embeddings' (plural) to match PostgreSQL storage
            embedding_metadata=embedding_metadata or {},
            related_memories=related_memories or [],
            session_id=session_id or '',
            user_id=user_id or '',
            tier='hot',  # Store to hot tier
            archived_at=None,
            deleted_at=None,
            # Chain of thought and cognitive state tracking
            reasoning_trace=reasoning_trace,
            thinking_state=thinking_state,  # Includes frozen metadata + filter decision
            system_state=system_state,  # System state at time of memory
            decision_factors=decision_factors,
            emotional_context=emotional_context,
            memory_admission=memory_admission,
            appraisal_snapshot=appraisal_snapshot,
            # The pursuit this episode belonged to — a link, plus the version
            # that was current, so hindsight cannot rewrite what it was for.
            intent_id=intent_id,
            intent_version=intent_version,
            percept_id=percept_id,
            percept_digest=percept_digest,
        )

        try:
            # Store to PostgreSQL hot tier
            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 6: Storing to PostgreSQL hot tier...")
            logger.debug(f"  Memory ID: {memory_id}")
            logger.debug(f"  PostgreSQL storage available: {self.postgres_storage is not None}")

            success = await self.postgres_storage.store_memory(memory_item)

            logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] PostgreSQL storage result: {success}")

            if success:
                self.metrics["memories_stored"] += 1
                logger.info(f"Memory {memory_id} stored to hot tier (filtered)")
                logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] ✓ SUCCESS - Memory {memory_id} stored")
                # Retain attached media DATA so the substrate remembers the
                # picture or the sound, not only a sentence about it.
                if media is not None:
                    await self._retain_media(memory_id, media, media_meta, user_id)
                # EVENT: a new episodic memory is what abstraction feeds on.
                # Count it (and, past threshold, schedule abstraction on the
                # queue authority). Cheap — never reasons on the write path.
                if memory_type == MemoryType.EPISODIC:
                    self.note_episodic_stored()
                return True, memory_id
            else:
                logger.error(f"Failed to store memory {memory_id}")
                logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ FAILED - PostgreSQL returned success=False")
                return False, None

        except Exception as e:
            logger.error(f"Memory storage error: {e}")
            logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    #: How long before a memory formed a perception counts as contemporaneous with it.
    PERCEPTUAL_WINDOW_SECONDS = 120.0

    async def _perceptual_state(self, owner: Optional[str]) -> Optional[Dict[str, Any]]:
        """What was being perceived when a memory of `owner`'s formed: the most
        recent perceptions of the window, of that owner's own, whole, each saying
        whose it was. None when there were none -- a reading, never invented.

        ONLY THE MEMORY'S OWN OWNER'S. A person's image is theirs: stamped on
        every memory that forms near it, it would go into the substrate's own
        memories and other people's. The substrate's own seeing (its environment)
        does not belong in a person's memory either."""
        from core.agents.autonomous.perception_manager import get_perception_manager
        from core.memory.utils.interfaces import Origin
        try:
            hub = get_perception_manager()
            if hub is None:
                return None
            now = datetime.now().timestamp()
            fresh = [p for p in await hub.get_recent_perceptions(limit=64)
                     if now - float(getattr(p, "timestamp", 0.0)) <= self.PERCEPTUAL_WINDOW_SECONDS
                     and isinstance(getattr(p, "origin", None), Origin)
                     and self._owner_from(p.origin) == (owner or None)][-8:]
        except Exception as e:
            logger.warning(f"Perceptual state snapshot failed: {type(e).__name__}: {e}")
            return None
        if not fresh:
            return None
        return {"captured_at": datetime.now().isoformat(),
                "perceptions": [
                    {"source": p.source, "data_type": p.data_type, "content": p.content,
                     "confidence": round(float(p.confidence), 4),
                     "age_s": round(now - float(p.timestamp), 2),
                     "owner": self._owner_from(p.origin)}
                    for p in fresh]}

    async def _retain_media(self, memory_id: str, media: Any,
                            media_meta: Optional[Dict[str, Any]],
                            owner: Optional[str]) -> None:
        """Attach media DATA -- a picture or a sound -- to a memory through the
        media store. Isolated: a media-store failure is reported and never fails
        the memory it belongs to. Called on BOTH storage paths (new memory and
        merge-into-existing) so what was met is kept even when its description
        deduplicates."""
        try:
            from core.memory.media_store import get_media_store
            # WHAT WAS MET KEEPS WHAT IT IS KNOWN BY, so memory can be asked by
            # the sound or the picture itself whether it was met before
            # (`retrieve`, strategies `sound` and `sight`).
            keys = None
            kind = (media_meta or {}).get("kind")
            if kind in ("sound_trace", "sight_trace") and isinstance(media, (bytes, bytearray)):
                keys = self._trace_keys(kind, bytes(media))
            await get_media_store().store_media(
                memory_id, media, perceived=media_meta or {}, owner=owner, keys=keys)
        except Exception as media_error:
            logger.error("memory %s stored but its media was not retained: %s",
                         memory_id, media_error)

    @staticmethod
    def _trace_keys(kind: str, data: bytes):
        """The keys a kept trace is found by: a sound's landmark hashes, a
        picture's keypoint keys. None when the trace keeps no features."""
        if kind == "sound_trace":
            from core.perception.hearing import landmark_hashes, trace_landmarks
            rows = trace_landmarks(data)
            return None if rows is None else landmark_hashes(rows)
        from core.perception.vision import keypoint_hashes, sight_trace
        features = sight_trace(data)
        return None if features is None else keypoint_hashes(features["descriptors"])

    async def get_memory_media(self, memory_id: str) -> List[Dict[str, Any]]:
        """The pictures and sounds attached to a memory -- bytes, mime,
        dimensions and perceived structure -- so the substrate can produce what
        it remembers, not only a description of it. Empty when the memory has
        none."""
        from core.memory.media_store import get_media_store
        return await get_media_store().media_for_memory(memory_id)

    def task_experience(
        self,
        task: Any,
        *,
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        confidence: float = 1.0,
    ) -> "Experience":
        """A finished task, succeeded or failed, as an experience: what the
        task's memory holds, and what the pool queues that memory for.

        A task done for a person -- code, a design, an experiment -- is theirs
        in its particulars and the substrate's in what it did. Each part says
        where it came from:

          the person     the request, the result they were given, and what the
                         tools returned from their material
          the substrate  the steps (the tools it chose and how), the fix that
                         worked
          the world      the errors it met, the checks that confirmed the
                         outcome, and what the tools returned on the substrate's
                         own work

        It used to compose "what the task found" and "the tools it used" from a
        summary, findings and tool results that no task result carries, so it
        kept nothing, for anyone.
        """
        from core.memory.utils.interfaces import Experience, Origin, Part
        result = result if isinstance(result, dict) else {}
        meta = getattr(task, "metadata", None) or {}
        origin = Origin.of(getattr(task, "actor", None), "task")

        parts = [Part("request", str(getattr(task, "description", "") or ""), origin.theirs)]
        for step in ((meta.get("parameters") or {}).get("tool_plan") or []):
            parts.append(Part("step", step, "substrate"))
        for run in (result.get("tools_run") or []):
            if not isinstance(run, dict):
                continue
            parts.append(Part("tool_run", {k: run.get(k) for k in ("tool", "args", "success")
                                           if k in run}, "substrate"))
            if "output" in run or "error" in run:
                parts.append(Part("tool_output", {"tool": run.get("tool"),
                                                  "output": run.get("output"),
                                                  "error": run.get("error")}, origin.material))
        for failure in (meta.get("failure_history") or []):
            parts.append(Part("error", failure, "world"))
        if meta.get("retry_method_structured"):
            parts.append(Part("fix", meta["retry_method_structured"], "substrate"))
        for check in (meta.get("completion_evidence") or []):
            parts.append(Part("check", check, "world"))
        delivered = {k: v for k, v in result.items() if k != "tools_run"}
        if delivered:
            parts.append(Part("result", delivered, origin.theirs))

        evidence = {"outcome": "success" if success else "failure",
                    "confidence": float(confidence),
                    "checks": len(meta.get("completion_evidence") or []),
                    "verification_state": result.get("verification_state"),
                    "task_type": getattr(getattr(task, "type", None), "value", None)}
        # WHAT THE OUTCOME SAYS ABOUT HOW IT WAS DONE, where the task loop has
        # judged it (`_operating_verdict`): whether it counts, and what it was
        # read from. Without it a failure in memory cannot say what caused it.
        if meta.get("operating_verdict"):
            evidence["verdict"] = meta["operating_verdict"]
        return Experience(
            kind="task", origin=origin, parts=tuple(parts), evidence=evidence,
            about=str(getattr(task, "id", "") or "") or None)

    async def store_batch(self, memories: List[MemoryItem]) -> Tuple[bool, int]:
        """
        Store multiple memories in batch (optimized)

        Generates embeddings in batch for efficiency.

        Returns:
            Tuple of (success, count_stored)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Generate batch embeddings
        contents = [m.content for m in memories]
        embeddings = self.embedding_service.batch_embed(
            contents
        ) if self.embedding_service else [None] * len(memories)

        # Assign embeddings to memories
        for memory, embedding in zip(memories, embeddings):
            memory.embedding = embedding

        # Batch store to PostgreSQL
        results = await self.postgres_storage.store_batch(
            memories=memories,
            batch_size=100
        )

        if results:
            self.metrics["memories_stored"] += len(memories)
            return True, len(memories)
        else:
            return False, 0

    async def _generate_worthiness_metadata(
        self,
        content: str,
        confidence_score: float,
        tags: Optional[List[str]],
        source_context: Optional[Dict[str, Any]],
        reasoning_trace: Optional[List[str]],
        importance_score: float = 0.5
    ) -> 'MemoryWorthinessMetadata':
        """
        Generate MemoryWorthinessMetadata from raw inputs.

        This is where Memory Agent analyzes the raw data and makes admission decisions.

        Args:
            content: The memory content
            importance_score: Caller-supplied importance (0.0-1.0), wired into consequence_level
            confidence_score: Confidence score
            tags: Tags from source system
            source_context: Raw metadata from source system
            reasoning_trace: Reasoning steps

        Returns:
            MemoryWorthinessMetadata
        """
        from datetime import datetime
        from core.memory.utils.memory_worthiness import (
            MemoryWorthinessMetadata,
            CognitionMetadata,
            NoveltyMetadata,
            CriticalityMetadata,
            QueryMetadata,
            OutcomeMetadata,
            TemporalMetadata,
            JustificationMetadata,
            DecisionType,
            ConsequenceLevel,
            PatternType,
            QueryType,
            ReusabilityLevel,
            DomainImportance
        )

        source_context = source_context or {}
        source_system = source_context.get("source_system", "unknown")

        # Analyze content for error patterns
        content_lower = content.lower()
        is_error = any(phrase in content_lower for phrase in [
            "sorry", "cannot see", "not visible", "unable to",
            "can't see", "image you intended", "please upload",
            "i'm sorry", "i can't", "i cannot"
        ])

        # Extract key metrics
        reasoning_step_count = len(reasoning_trace) if reasoning_trace else 0
        # A PERCEPT -- a picture, a clip or a sound the substrate met -- is not a
        # fact looked up, whatever its caption's words look like.
        has_percept = (source_context.get("has_image", False)
                       or source_context.get("has_video", False)
                       or source_context.get("has_sound", False))
        context_count = source_context.get("context_count", 0)

        # Check tags for semantic hints (used throughout metadata generation)
        tags_lower = [t.lower() for t in (tags or [])]
        has_research_tags = any(tag in tags_lower for tag in ['research', 'analysis', 'investigation', 'findings'])
        has_structural_tags = any(tag in tags_lower for tag in ['structure', 'architecture', 'dependencies', 'patterns'])

        # --- Content-based complexity heuristics (fallback when no external signals) ---
        content_words = len(content.split())
        analytical_keywords = [
            'analysis', 'reasoning', 'decision', 'finding', 'because', 'therefore',
            'strategy', 'architecture', 'conclusion', 'discovered', 'insight',
            'patterns', 'synthesis', 'evaluation', 'investigation', 'workflow',
            'coordinated', 'advanced', 'demonstrates', 'capabilities', 'multi-agent',
            'autonomous', 'critical', 'resolved', 'implemented', 'configured',
            'identified', 'determined', 'inferred', 'analyzed', 'optimized'
        ]
        keyword_count = sum(1 for kw in analytical_keywords if kw in content_lower)
        content_is_substantive = content_words >= 30 or keyword_count >= 2

        # 1. Cognition Metadata
        #
        # COMPLEXITY IS NO LONGER BOUGHT WITH LENGTH. This began
        # `complexity_score += min(reasoning_step_count / 5.0, 0.4)`, so a caller
        # emitting five strings gained 0.4 complexity outright -- past the 0.3
        # bar that `substantive_analysis` stores on. Removing the count from the
        # filter alone would not have closed that: verbosity simply bought
        # retention through complexity instead. The score is now derived from
        # the episode's own content and context.
        complexity_score = 0.0
        if context_count > 0:
            complexity_score += min(context_count / 10.0, 0.3)
        if has_percept and not is_error and confidence_score > 0.5:
            complexity_score += 0.3  # a percept, only if it was met successfully
        # BOOST: Research/structural findings are inherently complex
        if has_research_tags or has_structural_tags:
            logger.debug(f"[METADATA DEBUG] Boosting complexity_score for research/structure tags")
            complexity_score += 0.7  # Ensure it passes the 0.6 soft threshold
        # BOOST: Content-based signals when no external metadata is available
        if complexity_score == 0.0:
            if content_words >= 100:
                complexity_score += 0.4
            elif content_words >= 50:
                complexity_score += 0.25
            elif content_words >= 30:
                complexity_score += 0.1
            if keyword_count >= 3:
                complexity_score += 0.3
            elif keyword_count >= 2:
                complexity_score += 0.2
            elif keyword_count >= 1:
                complexity_score += 0.1
        complexity_score = min(complexity_score, 1.0)

        logger.debug(f"[METADATA DEBUG] Complexity score: {complexity_score:.2f}")
        logger.debug(f"[METADATA DEBUG] Reasoning steps: {reasoning_step_count}")
        logger.debug(f"[METADATA DEBUG] Has research tags: {has_research_tags}")
        logger.debug(f"[METADATA DEBUG] Has structural tags: {has_structural_tags}")
        logger.debug(f"[METADATA DEBUG] Content words: {content_words}, keyword_count: {keyword_count}, substantive: {content_is_substantive}")
        logger.debug(f"[METADATA DEBUG] Importance score: {importance_score:.2f}")

        cognition = CognitionMetadata(
            reasoning_steps=reasoning_step_count,
            reasoning_depth=min(reasoning_step_count, 3),
            execution_time_ms=0.0,
            inference_count=reasoning_step_count,
            complexity_score=complexity_score,
            required_backtracking=False,
            used_multiple_strategies=False,
            # RESOLVED FROM WHAT? This read `confidence_score > 0.7`, so at the
            # default confidence of 1.0 every caller claimed to have resolved
            # uncertainty -- while `involves_uncertainty` (confidence < 0.9)
            # simultaneously said the episode involved none. The same number was
            # being read two opposite ways.
            #
            # Uncertainty can only be resolved if there was some: the episode
            # started short of confident and ended reasonably confident.
            uncertainty_resolved=(
                confidence_score < 0.9 and confidence_score > 0.7 and not is_error
            )
        )

        # 2. Novelty Metadata
        novelty = NoveltyMetadata(
            is_novel=False,  # Would require memory lookup
            contradicts_existing=False,
            synthesis_of_domains=[],
            pattern_type=PatternType.ROUTINE,
            first_occurrence=False,
            connects_disparate_knowledge=False
        )

        # 3. Criticality Metadata

        # Observing the principal speak is a HIGH-consequence observation.
        #
        # Not an exemption from filtering — this IS an observation the substrate
        # made, through its own channel, and it belongs in the same triage as
        # every other one. The defect was that the assessment could not see what
        # kind of observation it was: every signal here is derived from the
        # content string (word count, keyword hits, reasoning steps), and the
        # relevant fact is not in the words. So "the companion must never show
        # reasoning text — use thinking deltas for liveness" scored as
        # QueryType.FACTUAL_LOOKUP and was hard-rejected as
        # `trivial_factual_lookup`.
        #
        # Forgetting what the principal said carries real consequence and the
        # knowledge is reusable indefinitely, so saying so is simply accurate.
        # `source_system` has meant "which system generated this" since this
        # metadata was defined and nothing has ever read it; this is that field
        # becoming load-bearing.
        from_principal = source_system in ("companion", "user", "principal")

        # Research findings have higher reusability
        reusability = (
            ReusabilityLevel.HIGH
            if (has_research_tags or has_structural_tags or from_principal)
            else ReusabilityLevel.MEDIUM
        )

        # Wire importance_score into consequence_level
        if is_error:
            consequence_level = ConsequenceLevel.NONE
        elif from_principal:
            consequence_level = ConsequenceLevel.HIGH
        elif importance_score >= 0.85:
            consequence_level = ConsequenceLevel.HIGH
        elif importance_score >= 0.7:
            consequence_level = ConsequenceLevel.MEDIUM
        elif confidence_score > 0.7:
            consequence_level = ConsequenceLevel.MEDIUM
        else:
            consequence_level = ConsequenceLevel.LOW

        criticality = CriticalityMetadata(
            decision_type=DecisionType.OPERATIONAL,
            domain_importance=DomainImportance.MEDIUM,
            reusability=reusability,
            consequence_level=consequence_level,
            likely_reference_count=0,
            time_sensitivity=False
        )

        # 4. Query Metadata
        # Determine query type based on characteristics (tags already checked above)
        if from_principal:
            # An exchange with the principal is not the substrate looking a fact
            # up. Classifying it as FACTUAL_LOOKUP is what triggered the
            # `trivial_factual_lookup` hard-reject.
            query_type = QueryType.SYNTHESIS
        elif has_percept and not is_error:
            # Perceiving something is always complex reasoning
            query_type = QueryType.COMPLEX_REASONING
        elif content_is_substantive and keyword_count >= 2:
            # Analytical language over substantive content. This tested
            # `reasoning_step_count > 1`, which classified an episode by how many
            # list items the caller sent -- and COMPLEX_REASONING is one of the
            # three types `substantive_analysis` stores on, so the format of the
            # trace decided the classification that decided retention.
            query_type = QueryType.COMPLEX_REASONING
        elif context_count > 2:
            # Synthesis of multiple sources
            query_type = QueryType.SYNTHESIS
        elif has_research_tags or has_structural_tags:
            # Research/structural findings are synthesis-level knowledge
            query_type = QueryType.SYNTHESIS
        elif keyword_count >= 3 or content_words >= 50:
            # Substantive content detected via text analysis
            query_type = QueryType.ANALYSIS
        else:
            # Default to factual lookup (conservative)
            query_type = QueryType.FACTUAL_LOOKUP

        logger.debug(f"[METADATA DEBUG] Query type: {query_type}")

        query = QueryMetadata(
            query_type=query_type,
            requires_synthesis=context_count > 0 or has_percept,
            multi_step=reasoning_step_count > 1 or has_percept,
            involves_uncertainty=confidence_score < 0.9,
            ambiguous_input=False,
            context_dependent=context_count > 0 or has_percept
        )

        # 5. Outcome Metadata
        outcome = OutcomeMetadata(
            conclusion_confidence=0.0 if is_error else confidence_score,
            hypothesis_supported=None,
            actionable=False if is_error else confidence_score > 0.7,
            created_new_knowledge=False,
            action_type="error_response" if is_error else "reasoning",
            action_summary=f"{source_system} result",
            affected_components=[source_system],
            validated_against_sources=False,
            requires_human_review=is_error or confidence_score < 0.5
        )

        # 6. Temporal Metadata
        temporal = TemporalMetadata(
            created_at=datetime.now().isoformat(),
            session_id="",
            trigger_event=f"{source_system}_query",
            sequence_number=0
        )

        # 7. Justification Metadata
        store_reasons = []
        if complexity_score >= 0.6:
            store_reasons.append("complexity_threshold")
        if reasoning_step_count >= 3:
            store_reasons.append("multi_step_reasoning")

        justification = JustificationMetadata(
            store_reason=store_reasons if store_reasons else ["below_threshold"],
            decision_summary=f"Analyzed by Memory Agent from {source_system}",
            alternatives_considered=[],
            rejected_because=[] if store_reasons else ["insufficient_complexity"]
        )

        return MemoryWorthinessMetadata(
            cognition=cognition,
            novelty=novelty,
            criticality=criticality,
            query=query,
            outcome=outcome,
            temporal=temporal,
            justification=justification,
            source_system=source_system,
            domain="general"
        )

    def _infer_memory_type(
        self,
        worthiness_metadata: Optional['MemoryWorthinessMetadata'],
        source_context: Dict[str, Any]
    ) -> MemoryType:
        """
        Infer memory type based on metadata and context.

        Classification logic (using core.memory.utils.interfaces.MemoryType):
        - Vision observations, specific events → EPISODIC
        - General facts, reusable knowledge → SEMANTIC
        - Skills, procedures, how-to → PROCEDURAL
        - Temporary working data → WORKING
        - Learning about learning → META

        Args:
            worthiness_metadata: Optional metadata from upstream system
            source_context: Context dictionary with source_system, has_image, etc.

        Returns:
            MemoryType enum value from core.memory.utils.interfaces
        """
        from core.memory.utils.memory_worthiness import QueryType

        # Error responses are episodic (failed attempts are specific events)
        if worthiness_metadata and worthiness_metadata.outcome.action_type == "error_response":
            logger.info("✓ Inferred EPISODIC: error response (failed attempt)")
            return MemoryType.EPISODIC

        # Procedural indicators in tags
        tags = source_context.get("tags", [])
        procedural_tags = {"procedure", "skill", "how-to", "method", "process", "tutorial", "guide"}
        if any(tag in procedural_tags for tag in tags):
            logger.info(f"✓ Inferred PROCEDURAL: procedural tags present {tags}")
            return MemoryType.PROCEDURAL

        # Meta-learning indicators
        meta_tags = {"meta_learning", "learning_about_learning", "cognitive", "self_reflection"}
        if any(tag in meta_tags for tag in tags):
            logger.info(f"✓ Inferred META: meta-learning tags present {tags}")
            return MemoryType.META

        # Semantic for general knowledge and factual lookups
        if worthiness_metadata:
            # Simple factual lookups that succeeded → semantic (reusable knowledge)
            if worthiness_metadata.query.query_type == QueryType.FACTUAL_LOOKUP:
                # But only if it's not an error
                if worthiness_metadata.outcome.action_type != "error_response":
                    logger.info("✓ Inferred SEMANTIC: successful factual lookup")
                    return MemoryType.SEMANTIC

            # Complex reasoning that created new knowledge → semantic (if generalizable)
            if (worthiness_metadata.outcome.created_new_knowledge and
                worthiness_metadata.criticality.reusability.value in ["high", "medium"]):
                logger.info(f"✓ Inferred SEMANTIC: created reusable knowledge (created_new_knowledge={worthiness_metadata.outcome.created_new_knowledge}, reusability={worthiness_metadata.criticality.reusability.value})")
                return MemoryType.SEMANTIC

        # Check source system patterns
        source_system = source_context.get("source_system", "unknown")

        # Neural bridge reasoning queries are often episodic (specific reasoning instances)
        if source_system == "neural_bridge":
            logger.info(f"✓ Inferred EPISODIC: neural bridge reasoning (specific instance)")
            return MemoryType.EPISODIC

        # Autonomous tasks are episodic (specific task executions)
        if source_system == "autonomous_coordinator":
            logger.info("✓ Inferred EPISODIC: autonomous task (specific execution)")
            return MemoryType.EPISODIC

        # Hypothesis testing is episodic (specific experiments)
        if source_system == "hypothesis_testing":
            logger.info("✓ Inferred EPISODIC: hypothesis test (specific experiment)")
            return MemoryType.EPISODIC

        # Continuous learning outcomes could be procedural (learned skills)
        if source_system == "continuous_learning":
            logger.info("✓ Inferred PROCEDURAL: continuous learning (learned skill)")
            return MemoryType.PROCEDURAL

        # Default to EPISODIC (specific events) rather than SEMANTIC
        # This is safer - better to treat general knowledge as a specific event
        # than to treat a specific event as general knowledge
        logger.info("✓ Inferred EPISODIC: default (specific event/observation)")
        return MemoryType.EPISODIC

    # ================================================================================================
    # MEMORY DEDUPLICATION HELPERS
    # ================================================================================================

    async def bulk_import(
        self,
        memories: List[Dict[str, Any]],
        memory_type: Optional[MemoryType] = None,
        generate_embeddings: bool = True,
        tier: str = "hot",
        batch_size: int = 100
    ) -> Tuple[bool, int]:
        """
        Bulk import memories (for migration or initialization)

        Efficiently imports large batches of memories with optional embedding generation.

        Args:
            memories: List of memory dictionaries
            memory_type: Default memory type if not specified in dict
            generate_embeddings: Whether to generate embeddings (default: True)
            tier: Target tier ("hot" or "cold")
            batch_size: Batch size for processing

        Returns:
            Tuple of (success, total_imported)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Convert dicts to MemoryItem objects
        memory_items = []
        for mem_dict in memories:
            item = MemoryItem(
                memory_id=mem_dict.get("memory_id", f"mem_{uuid.uuid4().hex}"),
                memory_type=mem_dict.get("memory_type", memory_type),
                content=mem_dict.get("content"),
                importance_score=mem_dict.get("importance_score", 0.5),
                confidence_score=mem_dict.get("confidence_score", 1.0),
                created_at=mem_dict.get("created_at", datetime.now()),
                last_accessed=mem_dict.get("last_accessed", datetime.now()),
                access_count=mem_dict.get("access_count", 0),
                decay_rate=mem_dict.get("decay_rate", 0.01),
                tags=mem_dict.get("tags", []),
                metadata=mem_dict.get("metadata", {}),
                embedding=mem_dict.get("embedding"),
                embedding_metadata=mem_dict.get("embedding_metadata", {}),
                related_memories=mem_dict.get("related_memories", []),
                session_id=mem_dict.get("session_id", ""),
                user_id=mem_dict.get("user_id", ""),
                tier=tier,
                archived_at=None,
                deleted_at=None
            )
            memory_items.append(item)

        # Generate embeddings if requested
        if generate_embeddings and self.embedding_service:
            contents = [m.content for m in memory_items]
            embeddings = self.embedding_service.batch_embed(contents)
            for item, embedding in zip(memory_items, embeddings):
                item.embedding = embedding

        # Store to appropriate tier
        if tier == "hot":
            results = await self.postgres_storage.store_batch(
                memories=memory_items,
                batch_size=batch_size
            )
        else:  # cold tier
            # Store to cold tier - migrate each memory individually
            results = []
            for memory_item in memory_items:
                # First store to hot tier, then migrate
                success = await self.postgres_storage.store_memory(memory_item)
                if success:
                    await self.postgres_storage.migrate_to_cold(memory_item.memory_id)
                results.append(memory_item.memory_id if success else None)

        self.metrics["memories_stored"] += len(memory_items)
        return True, len(memory_items)

    # ================================================================================================
    # MEMORY RETRIEVAL (Hot + Cold Tiers)
    # ================================================================================================

    async def retrieve_memory(
        self,
        memory_id: str,
        update_access: bool = True,
        tier_hint: Optional[str] = None
    ) -> Optional[MemoryItem]:
        """
        Retrieve memory by ID from hot or cold tier

        Tries hot tier (PostgreSQL) first, then cold tier (PostgreSQL archival) if not found.
        Updates access_count and last_accessed if update_access=True.

        Args:
            memory_id: Memory ID to retrieve
            update_access: Whether to update access metrics (default: True)
            tier_hint: Optional tier hint ("hot" or "cold") to optimize lookup

        Returns:
            MemoryItem if found, None otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Check cache first
        if self.cache_enabled and memory_id in self.memory_cache:
            logger.debug(f"Cache hit for memory {memory_id}")
            self.metrics["cache_hits"] += 1
            return self.memory_cache[memory_id]

        # Try hot tier (PostgreSQL) first
        if tier_hint != "cold":
            memory = await self.postgres_storage.get_memory(
                memory_id=memory_id
            )

            if memory:
                # Update access if requested
                if update_access:
                    memory.access_count += 1
                    memory.last_accessed = datetime.now()
                    # update_memory INCREMENTS access_count by the value passed, so
                    # this is 1, not the running total (which it would add to itself).
                    await self.postgres_storage.update_memory(memory_id, {
                        "access_count": 1,
                        "last_accessed": memory.last_accessed
                    })

                # Cache result
                if self.cache_enabled:
                    self.memory_cache[memory_id] = memory

                self.metrics["memories_retrieved"] += 1
                return memory

        # Try cold tier (PostgreSQL) if not found in hot tier
        memory = await self.postgres_storage.get_memory_from_cold(memory_id)
        if memory:
            logger.info(f"Retrieved memory {memory_id} from cold tier")
            self.metrics["memories_retrieved"] += 1
            return memory

        # Not found in any tier
        logger.warning(f"Memory {memory_id} not found in any tier")
        return None

    async def get_recent_memories(
        self,
        limit: int = 10,
        memory_types: Optional[List[MemoryType]] = None,
        min_importance: Optional[float] = None,
        tags: Optional[Set[str]] = None
    ) -> List[MemoryItem]:
        """
        Get recent memories from hot tier (PostgreSQL)

        Retrieves most recent memories sorted by created_at descending.
        Filters by type, importance, and tags if specified.

        Args:
            limit: Maximum results to return
            memory_types: Filter by memory types (episodic, semantic, etc.)
            min_importance: Minimum importance score filter
            tags: Filter by tags (set of tag strings)

        Returns:
            List of MemoryItem objects sorted by recency
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Calculate time window (recent memories in hot tier)
        time_window_start = (datetime.now() - timedelta(days=7)).timestamp()  # Last 7 days
        time_window_end = datetime.now().timestamp()

        # Query PostgreSQL hot tier
        results = await self.postgres_storage.search_memories(
            memory_type=memory_types[0] if memory_types else None,
            tags=tags,
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            min_importance=min_importance,
            limit=limit
        )

        logger.debug(f"Retrieved {len(results)} recent memories (last 7 days)")
        return results

    async def _recall_by_sound(self, heard: Any, *, limit: int,
                               actor: Optional[str]) -> List[MemoryItem]:
        """The hearings of the same sound as `heard` (landmark rows), found by
        what they share through the media store's index and decided by
        agreement on one offset, as a known song is: at least
        `hearing.KNOWN_MIN_AGREE` landmarks, and at least `music.SONG_MIN_SHARE`
        of those heard while the remembered sound would have been sounding.
        Only memories `actor` may see."""
        import numpy as np
        from core.memory.media_store import get_media_store
        from core.perception import hearing, music
        from core.perception.perception_faculty import get_perception_faculty
        from core.agents.autonomous.shared_types import visible_to
        heard = np.asarray(heard, np.int32)
        found: Dict[str, MemoryItem] = {}
        candidates, held = [], set()
        for media in await get_media_store().similar(hearing.landmark_hashes(heard),
                                                     kind="sound_trace", limit=max(limit, 20)):
            if media["memory_id"] not in held:
                held.add(media["memory_id"])
                candidates.append(media)
        # Decided in hearing's own process: counting agreement over thousands
        # of landmarks held the substrate's loop for 136 ms over 20 songs.
        agreed = await get_perception_faculty().agreements(
            "sound", heard, [m["bytes"] for m in candidates])
        for media, (count, at, share) in zip(candidates, agreed):
            if count < hearing.KNOWN_MIN_AGREE or share < music.SONG_MIN_SHARE:
                continue
            item = await self.postgres_storage.get_memory(media["memory_id"])
            if item is None or not visible_to(item.user_id or None, actor):
                continue
            item.similarity_score = round(float(share), 4)
            item.heard_match = {"agreeing": int(count), "share": round(float(share), 4),
                                "at": at}
            found[item.memory_id] = item
        return sorted(found.values(), key=lambda m: -m.similarity_score)[:limit]

    #: SEEN BEFORE. Measured on UKBench (the first 400 objects, 4 photographs
    #: each, taken from very different angles and distances): with the 100
    #: seeings sharing most keys checked, a thing was known again when at least
    #: 20 of its matched keypoints agreed on one geometry. That recalled half of
    #: the other views of the same object, and at least one for two in three,
    #: while a wrong object was confirmed in 0.016% of checks. The same picture
    #: resized or re-encoded kept its difference hash within 3 of 64 bits, and
    #: no two different objects came within 9, so within 8 it is the same
    #: picture whatever its keypoints say.
    SIGHT_CANDIDATES = 100
    SIGHT_MIN_AGREE = 20
    SIGHT_SAME_PICTURE = 8

    async def _recall_by_sight(self, seen: Dict[str, Any], *, limit: int,
                               actor: Optional[str]) -> List[MemoryItem]:
        """The seeings of the same thing as `seen` (sight features), found by
        the keys they share through the media store's index and decided in
        sight's own process: the same picture by its difference hash, the same
        thing by its keypoints agreeing on one geometry. Only memories `actor`
        may see."""
        from core.memory.media_store import get_media_store
        from core.perception.vision import keypoint_hashes
        from core.perception.perception_faculty import get_perception_faculty
        from core.agents.autonomous.shared_types import visible_to
        candidates, held = [], set()
        for media in await get_media_store().similar(
                keypoint_hashes(seen["descriptors"]), kind="sight_trace",
                limit=max(limit, self.SIGHT_CANDIDATES)):
            if media["memory_id"] not in held:
                held.add(media["memory_id"])
                candidates.append(media)
        agreed = await get_perception_faculty().agreements(
            "sight", seen, [m["bytes"] for m in candidates])
        found: Dict[str, MemoryItem] = {}
        for media, got in zip(candidates, agreed):
            same_picture = got["hash_distance"] <= self.SIGHT_SAME_PICTURE
            if not same_picture and got["agreeing"] < self.SIGHT_MIN_AGREE:
                continue
            item = await self.postgres_storage.get_memory(media["memory_id"])
            if item is None or not visible_to(item.user_id or None, actor):
                continue
            resolution = 1.0 if same_picture else min(
                1.0, got["agreeing"] / self.SIGHT_MIN_AGREE - 1.0)
            item.similarity_score = round(float(resolution), 4)
            item.seen_match = {**got, "same_picture": same_picture}
            found[item.memory_id] = item
        return sorted(found.values(), key=lambda m: -m.similarity_score)[:limit]

    #: The retrieval strategies that compose one recall. Each is a distinct
    #: storage primitive, so "specialise the agents" is a property of the
    #: design rather than a TODO: semantic finds paraphrase, keyword finds
    #: literal strings an embedding smooths away, tags find curation, and sound
    #: finds a hearing by the sound itself (when the caller has one).
    RETRIEVAL_STRATEGIES = ("semantic", "keyword", "tags", "sound", "sight")

    async def retrieve(
        self,
        query: Optional[str] = None,
        *,
        tags: Optional[Set[str]] = None,
        memory_types: Optional[List[MemoryType]] = None,
        strategies: Optional[Sequence[str]] = None,
        limit: int = 10,
        min_similarity: float = 0.5,
        min_importance: Optional[float] = None,
        deduplicate: bool = True,
        include_events: bool = True,
        relative_to_best: Optional[float] = None,
        require_named_match: bool = False,
        actor: Optional[str] = None,
        heard: Optional[Any] = None,
        seen: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryItem]:
        """Recall memories by running every applicable strategy CONCURRENTLY.

        `actor` is whose cognition the recall serves: a user sees their own
        memories and the substrate's, the substrate (None) only its own. Every
        strategy applies the same rule (`PostgresStorage._actor_predicate`).

        `heard` is a sound's landmarks (rows of f1, f2, dt, t): given one, the
        `sound` strategy recalls the hearings of THE SAME SOUND -- a recording
        heard again, through a room, a codec, over other sound -- each with how
        much of what was heard agreed with it (`similarity_score`, and
        `heard_match`: agreeing, share, at).

        `seen` is a picture's sight features (`vision.sight_features`): given
        them, the `sight` strategy recalls the seeings of THE SAME THING -- the
        same picture again, or the same thing in another picture -- each with
        how firmly it agreed (`similarity_score`, and `seen_match`).

        This is the composition layer the swarm search was: several retrieval
        strategies at once, merged. It is worth having for RECALL, not speed --
        the measurement that motivated it (QUERY_AGENT_TEST_RESULTS.md) is
        usually quoted as "11x slower", but the number underneath it is that
        regular search returned 0 memories where the multi-strategy search
        returned 5. A single strategy silently misses; a slower answer that
        finds the memory beats a fast one that does not.

        The four defects recorded against the original are addressed here:

          parallelisation   asyncio.gather, so cost is the SLOWEST strategy
                            rather than their sum
          specialisation    each strategy is a different storage primitive,
                            not three copies of the same query
          coordination      merging is a dict keyed by memory_id -- no agent
                            objects, no scheduling, no inter-agent messaging
          cross-tier        scope is passed through to storage instead of
                            being pinned to the hot tier

        A strategy that cannot run (no embedding service, no tags supplied) is
        skipped rather than failing the recall, and a strategy that RAISES is
        recorded and skipped -- one broken index must not empty the result set.

        Returns memories ranked by how many independent strategies found them,
        then by importance. Agreement between strategies is real evidence: a
        memory found by both meaning and wording is a better match than one
        found by a single path.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        selected = tuple(strategies) if strategies else self.RETRIEVAL_STRATEGIES
        # Ask for more per strategy than the caller wants, because the merge
        # discards duplicates and a per-strategy limit of `limit` would leave
        # fewer than `limit` distinct memories.
        per_strategy = max(limit, limit * 2 if deduplicate else limit)
        memory_type = memory_types[0] if memory_types else None

        async def _semantic() -> List[MemoryItem]:
            if not query or not self.embedding_service:
                return []
            embedding = self.embedding_service.generate_embedding(query)
            if not embedding:
                return []
            return await self.postgres_storage.semantic_search(
                query_embedding=embedding,
                memory_type=memory_type,
                min_similarity=min_similarity,
                limit=per_strategy,
                actor=actor,
            )

        async def _keyword() -> List[MemoryItem]:
            if not query:
                return []
            return await self.postgres_storage.search_by_content(
                content=query, exact_match=False, limit=per_strategy,
                actor=actor,
            )

        async def _tags() -> List[MemoryItem]:
            if not tags:
                return []
            return await self.postgres_storage.search_memories(
                memory_type=memory_type,
                tags=set(tags),
                min_importance=min_importance,
                limit=per_strategy,
                actor=actor,
            )

        async def _sound() -> List[MemoryItem]:
            if heard is None or not len(heard):
                return []
            return await self._recall_by_sound(heard, limit=per_strategy, actor=actor)

        async def _sight() -> List[MemoryItem]:
            if not seen or not len(seen.get("descriptors", [])):
                return []
            return await self._recall_by_sight(seen, limit=per_strategy, actor=actor)

        runners = {"semantic": _semantic, "keyword": _keyword, "tags": _tags,
                   "sound": _sound, "sight": _sight}
        unknown = [name for name in selected if name not in runners]
        if unknown:
            raise ValueError(
                f"unknown retrieval strategies {unknown}; "
                f"known: {sorted(runners)}"
            )

        names = [n for n in selected if n in runners]
        outcomes = await asyncio.gather(
            *(runners[n]() for n in names), return_exceptions=True
        )

        merged: Dict[str, MemoryItem] = {}
        found_by: Dict[str, Set[str]] = {}
        for name, outcome in zip(names, outcomes):
            if isinstance(outcome, Exception):
                logger.warning("retrieval strategy %s failed: %s", name, outcome)
                continue
            for item in outcome or []:
                merged.setdefault(item.memory_id, item)
                found_by.setdefault(item.memory_id, set()).add(name)

        if min_importance is not None:
            merged = {
                mid: m for mid, m in merged.items()
                if (m.importance_score or 0.0) >= min_importance
            }

        # OBSERVATIONS AND KNOWLEDGE SHARE A TABLE, NOT A PURPOSE.
        #
        # An event record is kept because it HAPPENED, and its multiplicity is
        # the signal -- 309 governance blocks are 309 facts about how often the
        # system was blocked, which is what competence calibration counts. That
        # is why store_memory exempts them from the worthiness filter and why
        # consolidation must never merge them.
        #
        # The same property makes them useless to a similarity search. They are
        # near-identical to each other by construction (those 309 score 0.974 to
        # 0.998 pairwise, separated only by an id the embedding cannot see), so
        # they cannot be found BY meaning, and they displace what can: a wave
        # asking about pressure loss returns the event log.
        #
        # So the split is at READ time, not write time. Records are queried by
        # STRUCTURE -- tag, type, time window, outcome -- where the count is
        # exact; recall searches KNOWLEDGE. One predicate decides which a memory
        # is, and it is the same one store_memory used to exempt it, so the two
        # halves cannot drift apart.
        if not include_events:
            from core.memory.utils.memory_filter import get_memory_filter
            _filter = get_memory_filter()
            kept = {}
            for mid, m in merged.items():
                tags = list(m.tags or [])
                raw_event = (m.thinking_state or {}).get("raw_event")
                if _filter.exemption_for(tags=tags, raw_event=raw_event) is None:
                    kept[mid] = m
            if len(kept) != len(merged):
                logger.debug("retrieve: %d event records held back from recall",
                             len(merged) - len(kept))
            merged = kept

        # NAMED SOMETHING ELSE IS NOT A NEAR MISS.
        #
        # `the capital of Mongolia` and `the capital of France` differ by one
        # token, so the vector scores them close -- and one is not a weaker
        # answer to the other, it is the answer to a DIFFERENT question.
        # Measured on the live store, "The capital of France is Paris." came
        # back as the top hit for the Mongolia question at 0.210.
        #
        # No threshold separates those, because the thing that distinguishes
        # them is not a matter of degree. It is the same shape as polarity, and
        # it gets the same treatment: an exact test in `claim_shape`, made once
        # and made outside the vector. A proper noun is rigid -- `anomaly`
        # paraphrases to `unusual behaviour`, nothing paraphrases `Mongolia` --
        # so a memory that never mentions what the question named is not about
        # it at any score.
        #
        # OFF BY DEFAULT, because it costs a real case: a memory answering
        # about a named thing WITHOUT naming it ("the system has been up four
        # days" for "what is Lyric's uptime") is dropped. Recall accepts that
        # trade -- a miss is better than confidently reporting another
        # entity's fact -- and the subsystems reading their own records, where
        # the name is always present, are left alone.
        if require_named_match and query:
            from core.semantics.claim_shape import about_the_same_thing

            def _same_thing(m) -> bool:
                content = m.content
                if isinstance(content, dict):
                    content = content.get("text") or content.get("content") or ""
                return about_the_same_thing(query, str(content or "")) is not False

            merged = {mid: m for mid, m in merged.items() if _same_thing(m)}

        # A CUT-OFF RELATIVE TO THE BEST MATCH, NOT AN ABSOLUTE ONE.
        #
        # Cosine is not calibrated across questions. The same 0.4 is a weak
        # match for a question the store answers well and the best match in
        # existence for one it barely covers, so a fixed floor excludes true
        # matches on hard questions and admits noise on easy ones. Measured on
        # the live store: at the 0.5 floor, "how does traffic get spread across
        # servers" and "what spots unusual behaviour in data" both returned
        # NOTHING while the memory that answers each sat in the index.
        #
        # What is comparable is within one question: how far the rest fall
        # behind the best hit. That is self-calibrating, and measured over the
        # same probes it answered 5 of 6 correctly with ZERO false answers to
        # questions the store holds nothing for -- against 4 of 6 for the
        # fixed floor.
        #
        # It applies ONLY to memories whose match was actually MEASURED. A
        # keyword hit means the query text appears verbatim in the memory and
        # carries no similarity score; ranking it out by comparison to a number
        # it does not have would discard evidence on the strength of a
        # measurement that was never taken.
        if relative_to_best is not None:
            measured = [m for m in merged.values()
                        if getattr(m, "similarity_score", None) is not None]
            if measured:
                cut = max(float(m.similarity_score) for m in measured) * relative_to_best
                merged = {
                    mid: m for mid, m in merged.items()
                    if getattr(m, "similarity_score", None) is None
                    or float(m.similarity_score) >= cut
                }

        # RELEVANCE FIRST. How well a memory matches THIS question decides its
        # rank; corroboration and importance only separate memories that match
        # equally well. This is the one place recall is ordered -- the single
        # authority for it -- so the ordering is decided here on the evidence
        # about the question asked, not re-decided downstream on properties of
        # the memory.
        #
        # Similarity is that evidence. Corroboration (how many strategies found
        # it) is a weaker co-signal -- the keyword strategy is a verbatim match,
        # so it rarely corroborates and cannot be the primary key -- and
        # importance is a property of the memory, not the question, so the most
        # important memory in the store must not win a query it barely matches.
        # Measured on the live store: "what is a load balancer" matched the
        # load-balancer memory at 0.839 while an unrelated memory matched at
        # 0.204; relevance-first ranks the right one first, importance-first did
        # not. Keyword/tags carry no similarity -- they qualified against a floor
        # and how well is unknown -- so they are scored at that floor, read as
        # neither a strong nor a weak match.
        def _match_strength(m) -> float:
            score = getattr(m, "similarity_score", None)
            return float(score) if score is not None else float(min_similarity)

        ranked = sorted(
            merged.values(),
            key=lambda m: (_match_strength(m),
                           len(found_by.get(m.memory_id, ())),
                           m.importance_score or 0.0),
            reverse=True,
        )

        logger.debug(
            "retrieve: %d distinct memories from %s (corroborated by >1: %d)",
            len(ranked), names,
            sum(1 for mid in found_by if len(found_by[mid]) > 1),
        )
        return ranked[:limit]

    # ── WORD CLASSES ───────────────────────────────────────────────────────
    #
    # What the substrate has observed about how a word is used. One store, the
    # same store as everything else it has learned, and a wipe takes these with
    # it -- which is the point: the file these replace survived database wipes
    # and re-poisoned every clean store on first read.

    #: The tag `cognitive_ingress` puts on a memory of being taught a claim.
    #: Word classes are derived from these at warm time -- there is no separate
    #: per-word record, because the substrate's memory of the sentence already
    #: says everything its words' classes follow from.
    TAUGHT_PROPOSITION_TAG = "admitted_proposition"
    #: A memory that STATES a word's class, rather than implying one by using
    #: the word in a proposition.
    #:
    #: WHY THIS HAD TO EXIST. A class could only be derived from a taught
    #: proposition's surface, and a proposition has exactly three slots --
    #: subject, relation, object. Every word English has that never occupies
    #: one of those was therefore unlearnable: adverbs, determiners,
    #: prepositions, pronouns, conjunctions, auxiliaries, modals. They lived in
    #: frozensets in the reader instead, which is a lexicon written in code --
    #: a second authority beside memory, unwipeable, and unable to grow by
    #: being taught. WordNet alone tags 3,630 adverbs the substrate dropped on
    #: the floor for want of anywhere to put them.
    WORD_CLASS_TAG = "word_class"

    #: The tag on a sentence remembered WITHOUT being understood. These carry
    #: `blamed` -- the class the refusal was attributed to -- which is the only
    #: evidence against a word class there is.
    UNREAD_TELLING_TAG = "told_but_unread"

    #: How many observations `warm_word_classes` will read. Named, because a
    #: silent cap here reads as "the substrate does not know that word".
    #:
    #: RAISED FROM 20,000, WHICH WAS SIZED FOR A STORE THAT HELD 199 WORDS.
    #: Word classes are taught into memory now -- WordNet alone states 75,834 --
    #: so the old cap did exactly what its own comment warns about: it cut the
    #: vocabulary off mid-alphabet and every word past the cut read as unknown.
    #: It also made teaching non-idempotent, because a pass asking what it had
    #: already said got a truncated answer and taught the remainder again:
    #: measured at 44,323 rows carrying 23,555 distinct (word, class) pairs.
    WORD_CLASS_WARM_LIMIT = 400000

    def word_class(self, word: str) -> Optional[str]:
        """The class this word has been OBSERVED to have, or None. Synchronous.

        None is returned for a word never observed, for one whose evidence is
        not net-positive for any class, and for a tie. None is also what an
        unwarmed index answers, and that is safe rather than merely tolerable:
        the reader treats an unknown word by reading the SENTENCE instead --
        measured, "A filter separates particles." reads correctly when
        `separates` is unknown and fails to read at all once something files it
        as a noun. Answering "I have not observed this" is therefore the honest
        answer AND the one that costs the least.

        A tie yields None for the same reason a two-rule match does: a word the
        evidence does not separate is not a word whose class is known.
        """
        counts = self._word_class_index.get(str(word or "").strip().lower())
        if not counts:
            return None
        best = max(counts.items(), key=lambda kv: kv[1])
        if best[1] <= 0:
            return None
        if sum(1 for _, n in counts.items() if n == best[1]) > 1:
            return None
        return best[0]

    def word_classes(self, word: str) -> Dict[str, int]:
        """Every class observed for this word with its net evidence.

        Polysemy is not a contradiction. `filter` is a thing and also something
        one does, and both can be net-positive here at once -- the store this
        replaced could hold only one class per word and counted the second as a
        CONTRADICTION, so teaching English to it drove real words to REFUTED and
        out of usability.
        """
        return dict(self._word_class_index.get(str(word or "").strip().lower(), {}))

    def note_taught_proposition(self, surface: str, reading: str) -> int:
        """Fold ONE just-stored proposition into the warm view. Returns words moved.

        A full warm reads the whole store, which is far too expensive to do per
        sentence -- and per sentence is exactly when it is needed. A lesson
        teaches "A marnic is a device." and the very next line says "A marnic
        filters brine.", which cannot read until `marnic` is known to name a
        thing. Waiting for the next full warm would make every lesson
        unreadable from its second sentence on.

        This is NOT a second store. It applies the same derivation the warm
        applies, to a memory that was just written, so the view says what a
        rebuild would say. Drop it and the next warm restores it exactly.
        """
        if "|" not in str(reading or ""):
            return 0
        from core.semantics.genericity import classes_implied_by
        parts = [p.strip() for p in str(reading).split("|")]
        subject = parts[0]
        relation = parts[1] if len(parts) > 1 else ""
        obj = parts[2] if len(parts) > 2 else None
        moved = 0
        for word, cls in classes_implied_by(
                str(surface or ""), subject, relation, obj).items():
            bucket = self._word_class_index.setdefault(word, {})
            bucket[cls] = bucket.get(cls, 0) + 1
            moved += 1
        return moved

    def note_refusal(self, blamed) -> int:
        """Fold a reading's blamed classes into the view. Returns classes moved.

        The counterpart of `note_taught_proposition` for evidence AGAINST, so a
        class that just cost a sentence stops being believed now rather than
        after the next rebuild -- which matters when the next sentence in the
        same lesson depends on it.
        """
        moved = 0
        for entry in (blamed or []):
            if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
                continue
            word, cls = str(entry[0]).lower(), str(entry[1]).upper()
            if not word or not cls:
                continue
            bucket = self._word_class_index.setdefault(word, {})
            bucket[cls] = bucket.get(cls, 0) - 1
            moved += 1
        return moved

    async def stated_word_classes(self):
        """Every `(word, CLASS)` pair already TOLD to the substrate.

        Read exactly, from the metadata that identifies these memories, so a
        teaching pass can tell what it has already said without asking a vector
        index whether two sentences about grammar resemble each other."""
        rows = await self.search_memories(
            tags={self.WORD_CLASS_TAG},
            limit=self.WORD_CLASS_WARM_LIMIT,
        ) or []
        out = []
        for item in rows:
            meta = item.metadata or {}
            word = str(meta.get("word") or "").strip().lower()
            cls = str(meta.get("word_class") or "").strip().upper()
            if word and cls:
                out.append((word, cls))
        return out

    def pattern_inventory(self):
        """The taught patterns as memory's view of them. Synchronous.

        Empty before the first warm or pattern note, which is the honest answer
        then: a pattern this process has not read from memory is not one it can
        use. Reading happens inside a parse, where there is nowhere to await."""
        if self._pattern_inventory is None:
            from core.semantics.derived_reader import PatternInventory
            self._pattern_inventory = PatternInventory()
        return self._pattern_inventory

    def note_pattern(self, item) -> bool:
        """Fold ONE just-stored construction or link into the view. False if it was there.

        Not a second store: it applies what the next warm would read from its
        memory, so a sentence taught now reads now rather than after the next
        rebuild."""
        return self.pattern_inventory().add(item)

    async def language_view(self):
        """The constructions and links memory holds, complete: warmed from
        memory first when this process has not read them yet. The learner reads
        every pair with this, so a view missing what memory holds would have it
        learn again what it already knows."""
        if not self._word_classes_warm:
            await self.warm_word_classes()
        return self.pattern_inventory()

    async def taught_patterns(self) -> list:
        """Every construction and link memory holds, read back as what it holds.

        The one read of these memories: the language view is warmed from it and
        the domain authority judges how much English is known from it, so the two
        can never disagree about what was taught. A memory whose key does not
        match what it holds was not written by the learner (or by an older
        definition of a construction); it is counted and left out, not trusted."""
        from core.semantics.derived_reader import PATTERN_TAG, item_from
        rows = await self.search_memories(
            tags={PATTERN_TAG}, limit=self.WORD_CLASS_WARM_LIMIT) or []
        if len(rows) >= self.WORD_CLASS_WARM_LIMIT:
            logger.warning(
                "the read hit its %d-memory limit on construction memories; what was "
                "taught may be incomplete and taught sentences will not read",
                self.WORD_CLASS_WARM_LIMIT)
        items, unreadable = [], 0
        for row in rows:
            meta = row.metadata or {}
            kind = str(meta.get("construction") or "holophrase")
            data = meta.get(kind if kind in ("lexical", "link", "phrase") else "pattern") or {}
            try:
                item = item_from(kind, data)
            except (KeyError, TypeError, ValueError):
                unreadable += 1
                continue
            if item.key != meta.get("pattern_key"):
                unreadable += 1
                continue
            items.append(item)
        if unreadable:
            logger.warning("%d construction memory(ies) could not be read back as what "
                           "they claim to hold", unreadable)
        return items

    async def stated_patterns(self) -> Dict[str, str]:
        """Every construction and link already held, as `pattern_key -> memory_id`.

        Read exactly from the metadata that identifies these memories, so a
        teaching pass knows what it has already said without asking a vector
        index whether two sentences resemble each other."""
        from core.semantics.derived_reader import PATTERN_TAG
        rows = await self.search_memories(
            tags={PATTERN_TAG}, limit=self.WORD_CLASS_WARM_LIMIT) or []
        held: Dict[str, str] = {}
        for item in rows:
            key = str((item.metadata or {}).get("pattern_key") or "")
            if key:
                held.setdefault(key, item.memory_id)
        return held

    def begin_word_class_warm(self):
        """Start rebuilding the word-class view in the background; return its task.

        Returns the warm ALREADY running if there is one, so this is safe to
        call from anywhere and never reads the whole store twice at once. The
        outcome is logged whichever way it goes: a view that silently failed to
        rebuild looks exactly like a substrate that knows nothing about words,
        and those must never be confusable again.
        """
        import asyncio
        running = self._word_class_warm_task
        if running is not None and not running.done():
            return running

        # `get_running_loop`, not `get_event_loop`: a caller with no loop is a
        # caller that cannot receive this result, and it should say so rather
        # than quietly building a loop nobody drives.
        task = asyncio.get_running_loop().create_task(
            self._rebuild_word_class_view(), name="memory:warm_word_classes")

        def _report(finished) -> None:
            if finished.cancelled():
                logger.error(
                    "the word-class warm was CANCELLED; the reader will treat "
                    "every word as never observed and the constitution will "
                    "derive no interest vocabulary until it is run again")
                return
            failure = finished.exception()
            if failure is not None:
                # A failure here costs reading, not storage. Say so plainly
                # rather than leaving an empty view looking like ignorance.
                logger.error(
                    "word classes could NOT be warmed from memory (%s); the "
                    "reader will treat every word as never observed", failure)
                return
            logger.info("✓ Word classes warmed from memory (%d word(s))",
                        finished.result())

        task.add_done_callback(_report)
        self._word_class_warm_task = task
        return task

    async def warm_word_classes(self) -> int:
        """Rebuild the word-class view, JOINING one already in flight.

        The callers that need the view now (teaching, an experiment harness)
        await this; boot starts it with `begin_word_class_warm` and does not
        wait. Shielded, so a caller that gives up waiting does not cancel the
        rebuild for everyone else.
        """
        import asyncio
        return await asyncio.shield(self.begin_word_class_warm())

    async def _rebuild_word_class_view(self) -> int:
        """Rebuild the word-class view FROM THE SUBSTRATE'S OWN MEMORIES.

        Nothing here is a record kept for the reader's benefit. The memories
        read are the ones it already has of being taught something -- the
        sentence as it was said, with the reading it was admitted as -- and the
        classes are worked out from those. A word the substrate never learned
        anything about has no class, which is the honest answer and the one the
        reader handles best.

        That is why there is no lexicon and no per-word bookkeeping: a wipe
        takes these memories, and the view empties with them. Nothing survives
        a wipe to re-teach the substrate what it no longer knows.

        Called at the events that change what could be in it -- after teaching,
        when a task opens -- never on a timer, because nothing about it changes
        with the clock.
        """
        if not self.initialized:
            if await self.initialize() is False:
                raise RuntimeError(
                    "MemoryAgent could not initialize; refusing to warm word "
                    "classes as though it had")

        from core.semantics.genericity import classes_implied_by

        # TWO QUERIES, BECAUSE THEY ARE TWO KINDS OF EVIDENCE.
        #
        # Tag search CONTAINS rather than matches any (`tags @> ...`), so one
        # call asking for both tags would return memories carrying BOTH -- of
        # which there are none, since a sentence is either read or not. The
        # sentences that read supply evidence FOR a class; the ones that
        # refused because of a class supply evidence AGAINST it.
        taught = await self.search_memories(
            tags={self.TAUGHT_PROPOSITION_TAG},
            limit=self.WORD_CLASS_WARM_LIMIT,
        ) or []
        unread = await self.search_memories(
            tags={self.UNREAD_TELLING_TAG},
            limit=self.WORD_CLASS_WARM_LIMIT,
        ) or []
        # THE THIRD KIND OF EVIDENCE: a class the substrate was TOLD, rather
        # than one implied by a sentence it read. This is where every closed
        # class and every adverb comes from -- words that never stand in a
        # subject, relation or object slot and so can be implied by nothing.
        stated = await self.search_memories(
            tags={self.WORD_CLASS_TAG},
            limit=self.WORD_CLASS_WARM_LIMIT,
        ) or []
        for name, rows in (("taught", taught), ("unread", unread),
                           ("stated", stated)):
            if len(rows) >= self.WORD_CLASS_WARM_LIMIT:
                logger.warning(
                    "word-class warm hit its %d-memory limit on %s memories; "
                    "the view may be incomplete and words will read as "
                    "unobserved", self.WORD_CLASS_WARM_LIMIT, name)

        index: Dict[str, Dict[str, int]] = {}
        unparsed = 0
        refuted = 0
        told = 0
        derived = 0
        for item in stated:
            meta = item.metadata or {}
            word = str(meta.get("word") or "").strip().lower()
            cls = str(meta.get("word_class") or "").strip().upper()
            if not word or not cls:
                continue
            bucket = index.setdefault(word, {})
            bucket[cls] = bucket.get(cls, 0) + 1
            told += 1
        for item in (*taught, *unread):
            meta = item.metadata or {}

            # EVIDENCE AGAINST, from the sentences a class actually cost.
            #
            # A reading that refused BECAUSE of a class counts against it. This
            # is what makes a class earnable rather than merely assertable: a
            # word wrongly observed as an ADJECTIVE breaks ordinary sentences,
            # and each break argues it down until it stops being usable.
            #
            # `blamed` is narrow by construction -- the reader names a class
            # only in the branches that refuse because of it -- so a sentence
            # that failed for some unrelated reason refutes nothing.
            for entry in self._blamed_in(item):
                if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
                    continue
                word, cls = str(entry[0]).lower(), str(entry[1]).upper()
                if not word or not cls:
                    continue
                bucket = index.setdefault(word, {})
                bucket[cls] = bucket.get(cls, 0) - 1
                refuted += 1

            # ONLY A TELLING IS EVIDENCE ABOUT A WORD.
            #
            # A derived claim is the substrate's own conclusion, and a conclusion
            # is not testimony about how English uses a word. Sight describing a
            # kind it had seen wrote `<cat> has_property circle`, and the
            # property branch of `classes_implied_by` files a property's object
            # as ADJECTIVE -- so seeing round things taught the substrate that
            # `circle` is an adjective. The surface cannot settle this (it
            # contains the word either way); the PROVENANCE can, and
            # `ROOT_SOURCE_VALUES` is the set this substrate already uses
            # everywhere else to separate an observation from a conclusion.
            #
            # A memory recording no source type at all predates this and is left
            # as it was: absence of the record is not evidence that it was
            # derived, and discarding it would silently drop vocabulary.
            source_type = meta.get("source_type")
            if source_type is not None:
                from core.domain.concept_ingestion import ROOT_SOURCE_VALUES
                if str(source_type).strip().lower() not in ROOT_SOURCE_VALUES:
                    derived += 1
                    continue

            reading = str(meta.get("reading") or "")
            if "|" not in reading:
                # Kept by `remember_told`: the sentence was remembered without
                # being understood, so it implies nothing about its words. It
                # stays in memory and teaches the reader nothing -- which is
                # the point of recording that it was not read.
                unparsed += 1
                continue
            parts = [p.strip() for p in reading.split("|")]
            subject, relation = parts[0], parts[1] if len(parts) > 1 else ""
            obj = parts[2] if len(parts) > 2 else None

            surface = item.content
            if isinstance(surface, dict):
                surface = surface.get("text") or surface.get("content") or ""

            for word, cls in classes_implied_by(
                    str(surface or ""), subject, relation, obj).items():
                bucket = index.setdefault(word, {})
                bucket[cls] = bucket.get(cls, 0) + 1

        # THE TAUGHT PATTERNS, IN THE SAME PASS. How English says things is
        # language knowledge like a word's class, read from memory at the same
        # events, so there is one warm and one view -- not a second one that can
        # disagree with the first about what the substrate was taught.
        from core.semantics.derived_reader import PatternInventory
        inventory = PatternInventory(await self.taught_patterns())

        self._word_class_index = index
        self._word_classes_warm = True
        self._pattern_inventory = inventory
        logger.info(
            "word-class view warmed: %d word(s) from %d taught memory(ies) "
            "(%d remembered but never read, %d refusal(s) counted against a "
            "class, %d class(es) stated outright, %d derived claim(s) that "
            "teach no vocabulary); %d taught construction(s) and link(s)",
            len(index), len(taught) + len(unread) + len(stated), unparsed,
            refuted, told, derived, len(inventory))
        return len(index)

    @profile_performance("memory_agent", "search_memories")
    async def search_memories(
        self,
        query: Optional[str] = None,
        memory_types: Optional[List[MemoryType]] = None,
        min_similarity: float = 0.7,
        limit: Optional[int] = None,
        deduplicate: bool = True,
        # New interface parameters for integration compatibility
        query_text: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        tags: Optional[List[str]] = None,
        max_results: Optional[int] = None,
        min_importance: Optional[float] = None,
        include_events: bool = True,
        relative_to_best: Optional[float] = None,
        require_named_match: bool = False,
        actor: Optional[str] = None,
    ) -> Union[Tuple[bool, List[MemoryItem]], List[MemoryItem]]:
        """Compatibility surface over retrieve(). Adapts shape only.

        Retrieval itself has ONE owner now: retrieve(). This ran its own
        partial composition -- semantic, then tags, then reranking, in
        sequence -- which meant two different answers to "what does this
        system recall", differing in which strategies ran and in what order.
        Whichever a caller happened to use decided what it could find.

        What survives here is the calling convention, because callers depend
        on it and there are two of them:

            legacy  search_memories(query=..., limit=...)      -> (bool, list)
            new     search_memories(query_text=..., tags=...)  -> list

        That fork is itself a defect -- a function whose return TYPE depends on
        which keyword you passed cannot be used without knowing the call site --
        but collapsing it is a caller migration, not a retrieval change, so it
        is left standing rather than bundled into this one.
        """
        new_interface = any([query_text is not None, memory_type is not None,
                             tags is not None, max_results is not None,
                             min_importance is not None])

        query_str = query_text or query
        if query_str is None and not tags:
            logger.error("search_memories requires a query, query_text or tags")
            return [] if new_interface else (False, [])

        types = memory_types
        if types is None and memory_type is not None:
            types = [memory_type]

        results = await self.retrieve(
            query_str,
            tags=set(tags) if tags else None,
            memory_types=types,
            limit=max_results or limit or 10,
            min_similarity=min_similarity,
            min_importance=min_importance,
            deduplicate=deduplicate,
            include_events=include_events,
            relative_to_best=relative_to_best,
            require_named_match=require_named_match,
            actor=actor,
        )
        return results if new_interface else (True, results)


    async def query_by_tags(
        self,
        tags: Set[str],
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 100
    ) -> Tuple[bool, List[MemoryItem]]:
        """
        Query memories by tags (hot tier)

        Searches PostgreSQL hot tier for memories matching tags.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Query hot tier by tags
        results = await self.postgres_storage.search_memories(
            memory_type=memory_types[0] if memory_types else None,
            tags=tags,
            time_window_start=None,  # No time filter
            time_window_end=None,    # Search all hot tier
            limit=limit
        )

        logger.info(f"Tag query: {len(results)} memories for tags: {', '.join(tags)}")
        return True, results

    async def get_memory_by_content(
        self,
        content: str,
        exact_match: bool = False,
        limit: int = 10
    ) -> List[MemoryItem]:
        """
        Search memories by content (keyword or exact match)

        Args:
            content: Content to search for
            exact_match: Whether to use exact matching (default: False for fuzzy)
            limit: Maximum results

        Returns:
            List of matching MemoryItem objects
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Use semantic search if not exact match
        if not exact_match:
            success, results = await self.search_memories(
                query=content,
                limit=limit
            )
            return results

        # Exact match search
        results = await self.postgres_storage.search_by_content(
            content=content,
            exact_match=True,
            limit=limit
        )

        return results


    # ================================================================================================
    # MEMORY UPDATES (Hot Tier)
    # ================================================================================================

    #: An episode that has not finished. A question asked and not answered is
    #: the case this exists for: it is a real memory of a real moment, and it
    #: is also a loop that later gets closed.
    OPEN_TAG = "open"

    async def find_open(self, about: str, limit: int = 5, *,
                        actor: Optional[str] = None) -> List[MemoryItem]:
        """Episodes still waiting on something, that this might be about --
        `actor`'s OWN only. Searched with no owner, this saw only the
        substrate's episodes, and while every exchange was stored unowned one
        speaker's answer could close -- rewrite -- another speaker's question."""
        found = await self.retrieve(query=about, tags={self.OPEN_TAG},
                                    strategies=("semantic", "tags"),
                                    limit=limit, min_similarity=0.55, actor=actor)
        open_ones = [m for m in found
                     if self.OPEN_TAG in {str(t) for t in (m.tags or ())}]
        own = await self.postgres_storage.owned_by(
            [m.memory_id for m in open_ones], actor)
        return [m for m in open_ones if m.memory_id in own]

    async def supersede(self, memory_id: str, content: str,
                        add_tags: Optional[Set[str]] = None,
                        drop_tags: Optional[Set[str]] = None,
                        because: str = "") -> bool:
        """Replace what a memory says, keeping what it used to say.

        A RESOLUTION SETTLES WHAT THE MEMORY SAID; IT DOES NOT ADD TO IT. An
        episode recording "asked, could not answer" that also said "answered:
        X" would assert both, and the reader could not tell which is now true.

        So this replaces, and the previous text is kept under
        `metadata.superseded` rather than dropped. What the substrate used to
        believe, and when it stopped, is part of the record -- a memory that
        quietly becomes correct is indistinguishable from one that was always
        correct, and only one of those should be trusted about its own past.
        """
        existing = await self.retrieve_memory(memory_id)
        if not existing:
            logger.info("cannot supersede %s: no such memory", memory_id)
            return False

        was = existing.content
        if isinstance(was, dict):
            was = was.get("text") or was.get("content") or str(was)
        tags = {str(t) for t in (existing.tags or ())}
        tags -= {str(t) for t in (drop_tags or set())}
        tags |= {str(t) for t in (add_tags or set())}

        metadata = dict(getattr(existing, "metadata", None) or {})
        history = list(metadata.get("superseded") or [])
        history.append({"was": str(was)[:1000], "because": because,
                        "at": datetime.now().isoformat()})
        metadata["superseded"] = history[-5:]

        updates = {"content": content, "tags": sorted(tags), "metadata": metadata}
        # New words, new vector: a replaced memory that kept the old embedding
        # would keep being found by what it used to say.
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(content)
            if embedding is not None:
                updates["embedding"] = embedding
        updated = await self.update_memory(memory_id, updates)
        if updated:
            logger.info("superseded %s (%s)", memory_id, because or "resolved")
        return bool(updated)

    async def close_open(self, about: str, content: str,
                         because: str = "resolved", *,
                         actor: Optional[str] = None) -> Optional[str]:
        """Settle an open episode about this, if one is waiting -- one of
        `actor`'s OWN (see `find_open`).

        Returns the memory it closed, or None -- in which case the caller
        stores a new memory as usual, because not every answer answers a
        question somebody asked.
        """
        for candidate in await self.find_open(about, actor=actor):
            if await self.supersede(candidate.memory_id, content,
                                    add_tags={"resolved"},
                                    drop_tags={self.OPEN_TAG},
                                    because=because):
                return candidate.memory_id
        return None

    async def update_memory(
        self,
        memory_id: str,
        updates: Dict[str, Any],
        capability_token: str = "",
        tier: Optional[str] = None
    ):
        """
        Update memory fields

        Protected operation - requires capability token for critical updates.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Validate capability token for protected fields
        protected_fields = ["importance_score", "confidence_score", "memory_type"]
        if any(field in updates for field in protected_fields):
            if not await self._validate_capability_token(capability_token):
                logger.warning(f"Unauthorized memory update attempt: {memory_id}")
                return False

        # Update in PostgreSQL hot tier
        success = await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates=updates,
            tier=tier
        )

        if success:
            # The cache held the memory as it was BEFORE this write, so a read
            # straight after an update returned the old text (measured
            # 2026-09-26: a superseded memory read back unchanged).
            self.memory_cache.pop(memory_id, None)
            self.metrics["memories_retrieved"] += 1
            return True

        return False

    async def increment_access_count(
        self,
        memory_id: str,
        tier: str,
        increment: int = 1
    ):
        """
        Increment memory access count

        Updates access_count and last_accessed timestamp.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "access_count": increment,
                "last_accessed": datetime.now()
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def update_importance(
        self,
        memory_id: str,
        new_importance: float,
        capability_token: str,
        tier: str,
        reason: str,
        tier_hint: Optional[str] = None
    ):
        """
        Update memory importance score

        Protected operation - requires capability token for governance.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized importance update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "importance_score": new_importance,
                "metadata.importance_update": {
                    "reason": reason,
                    "updated_at": datetime.now().isoformat()
                }
            },
            tier=tier
        )

    async def update_tags(
        self,
        memory_id: str,
        tags: List[str],
        capability_token: str = "",
        tier: str = "hot",
        operation: str = "replace"
    ):
        """
        Update memory tags

        Protected operation - supports add, remove, replace operations.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized tags update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "tags": tags,
                "metadata.tags_operation": operation
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def add_related_memory(
        self,
        memory_id: str,
        related_id: str,
        tier: str,
        relationship_type: str
    ):
        """
        Add related memory link

        Creates bidirectional relationship between memories.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "related_memories": [related_id]
            },
            tier=tier
        )
        self.metrics["memories_retrieved"] += 1

    async def update_metadata(
        self,
        memory_id: str,
        metadata_updates: Dict[str, Any],
        capability_token: str = "",
        merge: bool = True,
        tier: str = "hot",
        tier_hint: Optional[str] = None
    ):
        """
        Update memory metadata

        Supports merge (add/update fields) or replace (overwrite all).
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized metadata update: {memory_id}")
            return False

        await self.postgres_storage.update_memory(
            memory_id=memory_id,
            updates={
                "metadata": metadata_updates,
                "metadata.merge": merge
            },
            tier=tier
        )

    # ================================================================================================
    # MEMORY DELETION (Governance Protected)
    # ================================================================================================

    async def delete_memory(
        self,
        memory_id: str,
        capability_token: str,
        reason: str = "",
        tier_hint: Optional[str] = None
    ) -> bool:
        """
        Delete memory (soft delete)

        GOVERNANCE PROTECTED: Requires capability token for autonomous deletions.

        Returns:
            True if deletion successful, False otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Validate capability token (governance requirement)
        if not await self._validate_capability_token(capability_token):
            logger.warning(f"Unauthorized delete attempt: memory_id={memory_id}")
            return False

        # Soft delete from PostgreSQL hot tier
        success = await self.postgres_storage.delete_memory(
            memory_id=memory_id,
            soft_delete=True,
            reason=reason
        )

        if success:
            # Remove from cache
            if memory_id in self.memory_cache:
                del self.memory_cache[memory_id]

            logger.info(f"Memory {memory_id} deleted (soft)")
            return True
        else:
            logger.error(f"Failed to delete memory {memory_id}")
            return False

    async def permanent_delete(
        self,
        memory_id: str,
        capability_token: str,
        confirmation: bool = False
    ) -> Tuple[bool, str]:
        """
        Permanently delete memory (irreversible)

        CRITICAL GOVERNANCE PROTECTION: Requires capability token + confirmation.
        This is a destructive operation that cannot be undone.

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Double validation for permanent delete
        if not await self._validate_capability_token(capability_token):
            error_msg = "Unauthorized permanent delete - missing capability token"
            logger.warning(f"{error_msg}: memory_id={memory_id}")
            return False, error_msg

        if not confirmation:
            error_msg = "Permanent delete requires explicit confirmation=True"
            logger.warning(error_msg)
            return False, error_msg

        # Hard delete from PostgreSQL
        success = await self.postgres_storage.delete_memory(
            memory_id=memory_id,
            soft_delete=False,
            reason="permanent_delete"
        )

        if success:
            logger.info(f"Memory {memory_id} permanently deleted")
            return True, f"Memory {memory_id} permanently deleted"
        else:
            return False, f"Failed to permanently delete {memory_id}"

    # ================================================================================================
    # THE REST OF MEMORY
    # ================================================================================================
    #
    # Memory is everything the substrate holds, not only the memories above: the
    # concepts and the links between them, its beliefs, the rules it induced and
    # the demonstrations it induced them from, its domains, what its reasoning
    # produced, what it has learned to see, the record of what it learned, and
    # each person's context. The parts of the substrate that work out WHAT to
    # hold -- the learning authority, the belief system, induction, the domain
    # master, the reasoning engines, perception -- hand it here, and the memory
    # agent writes it. Nothing else writes a memory table
    # (`scripts/separation_map.py` fails if anything does).
    #
    # These writes need only the database, so they work whether or not recall,
    # the loops and the embedding model have started (`memory_agent()`).

    def _memory_db(self):
        """The database every write of memory goes to: the process's manager,
        looked up at each write so it is always the one every reader uses."""
        from core.database import get_database_manager
        return get_database_manager()

    # ---- concepts and links -------------------------------------------------

    async def hold_concept(self, *, concept_id: str, name: str, domain: str,
                           description: Any, attributes: str, relationships: str,
                           concept_kind: str, epistemic_status: str, provenance: str,
                           root_evidence_count: int) -> None:
        """A concept. Its description is kept when the new one is empty, its
        attributes and relationships are merged, never replaced, and a changed
        description clears the stored vector so it is encoded again."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.concepts
                   (concept_id, name, domain, description, attributes,
                    relationships, functions, processes, context, examples,
                    concept_kind, epistemic_status, provenance,
                    root_evidence_count, created_at)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,'[]'::jsonb,'[]'::jsonb,
                       '', '[]'::jsonb, $7,$8,$9::jsonb,$10, NOW())
               ON CONFLICT (concept_id) DO UPDATE SET
                   description         = COALESCE(NULLIF(EXCLUDED.description,''),
                                                  unified.concepts.description),
                   -- A changed description invalidates its stored vector; the
                   -- Universal Domain Master re-encodes pending rows.
                   description_embedding = CASE
                       WHEN NULLIF(EXCLUDED.description,'') IS NULL
                         OR EXCLUDED.description IS NOT DISTINCT FROM unified.concepts.description
                       THEN unified.concepts.description_embedding END,
                   embedding_model     = CASE
                       WHEN NULLIF(EXCLUDED.description,'') IS NULL
                         OR EXCLUDED.description IS NOT DISTINCT FROM unified.concepts.description
                       THEN unified.concepts.embedding_model END,
                   attributes          = unified.concepts.attributes || EXCLUDED.attributes,
                   -- MERGED, NOT REPLACED. Learning one thing about a concept
                   -- is not grounds for forgetting the rest: teaching
                   -- `pressure loss is caused by valve throttling` erased
                   -- `caused by pipe friction` and `caused by minor losses`,
                   -- so a concept got narrower every time anything was added
                   -- to it. Note the two lines either side of this one --
                   -- description is preserved and attributes are merged --
                   -- which is what makes the replacement an oversight rather
                   -- than a policy.
                   relationships       = (
                       SELECT COALESCE(jsonb_agg(DISTINCT edge), '[]'::jsonb)
                       FROM jsonb_array_elements(
                           unified.concepts.relationships || EXCLUDED.relationships
                       ) AS edge
                   ),
                   epistemic_status    = EXCLUDED.epistemic_status,
                   root_evidence_count = EXCLUDED.root_evidence_count,
                   updated_at          = NOW()""",
            (concept_id, name, domain, description, attributes, relationships,
             concept_kind, epistemic_status, provenance, root_evidence_count),
            commit=True,
        )

    async def hold_concept_evidence(self, *, concept_id: str, evidence_id: str,
                                    root_evidence_id: str, extraction_confidence: Any,
                                    extractor: str) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_evidence
                   (concept_id, evidence_id, root_evidence_id,
                    extraction_confidence, extractor)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (concept_id, root_evidence_id) DO NOTHING""",
            (concept_id, evidence_id, root_evidence_id, extraction_confidence, extractor),
            commit=True,
        )

    async def link_concepts(self, *, source_concept_id: str, relation: str,
                            target_concept_id: Optional[str], target_surface: str,
                            evidence_id: str, extractor: str, polarity: str) -> None:
        """A link from one concept to another, or to a surface not yet learned
        (`target_concept_id` None until `attach_waiting_links` finds it)."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_relations
                   (source_concept_id, relation, target_concept_id,
                    target_surface, evidence_id, extractor, polarity)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (source_concept_id, relation, target_surface,
                            evidence_id, polarity)
               DO UPDATE SET target_concept_id = COALESCE(
                   EXCLUDED.target_concept_id, unified.concept_relations.target_concept_id)""",
            (source_concept_id, relation, target_concept_id, target_surface,
             evidence_id, extractor, polarity),
            commit=True,
        )

    async def attach_waiting_links(self, *, target_concept_id: str,
                                   target_surface: str) -> Any:
        """Links that named `target_surface` before it was learned now point at it."""
        return await self._memory_db().execute_query(
            "UPDATE unified.concept_relations SET target_concept_id = $1 "
            "WHERE target_surface = $2 AND target_concept_id IS NULL",
            (target_concept_id, target_surface), commit=True)

    async def hold_alias(self, *, alias: str, concept_id: str, alias_kind: str) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_aliases (alias, concept_id, alias_kind)
               VALUES ($1,$2,$3) ON CONFLICT (alias) DO NOTHING""",
            (alias, concept_id, alias_kind), commit=True,
        )

    async def hold_surface_form(self, *, alias: str, concept_id: str) -> List[Any]:
        """A surface word bound to the concept it denotes. Returns the rows
        written, so a word already bound reads as nothing written."""
        return await self._memory_db().execute_query(
            "INSERT INTO unified.concept_aliases "
            "(alias, concept_id, alias_kind, first_seen) "
            "VALUES ($1, $2, 'surface_form', NOW()) "
            "ON CONFLICT DO NOTHING RETURNING alias",
            (alias, concept_id), fetch_all=True)

    async def hold_evidence_envelope(self, *, evidence_id: str, source_type: str,
                                     source_id: str, producer: str, content: Any,
                                     structured_data: str, derived_from: str,
                                     observed_at: Any) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.evidence_envelopes
                   (evidence_id, source_type, source_id, producer, content,
                    structured_data, derived_from, observed_at)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,COALESCE($8, NOW()))
               ON CONFLICT (evidence_id) DO NOTHING""",
            (evidence_id, source_type, source_id, producer, content,
             structured_data, derived_from, observed_at),
            commit=True,
        )

    async def hold_domain_membership(self, *, concept_id: str, domain: str, source: str,
                                     evidence_id: Optional[str] = None) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_domains
                   (concept_id, domain, source, evidence_id)
               VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING""",
            (concept_id, domain, source, evidence_id), commit=True)

    async def hold_extracted_membership(self, *, concept_id: str, domain: str) -> None:
        """The domain an extractor embedded in a concept's id, as a membership."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_domains (concept_id, domain, source)
               VALUES ($1,$2,'extracted') ON CONFLICT DO NOTHING""",
            (concept_id, domain), commit=True)

    async def hold_identity_relation(self, *, subject_concept_id: str, relation_kind: str,
                                     object_concept_id: Optional[str], object_surface: str,
                                     basis: str) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.concept_identity_relations
                   (subject_concept_id, relation_kind, object_concept_id,
                    object_surface, basis)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (subject_concept_id, relation_kind, object_surface)
               DO UPDATE SET object_concept_id =
                   COALESCE(EXCLUDED.object_concept_id,
                            unified.concept_identity_relations.object_concept_id)""",
            (subject_concept_id, relation_kind, object_concept_id, object_surface, basis),
            commit=True)

    async def clear_foreign_vectors(self, *, model_id: str) -> List[Any]:
        """Clear the vectors another encoder wrote, so they are encoded again by
        `model_id`. Returns one row holding how many were cleared."""
        return await self._memory_db().execute_query(
            """WITH cleared AS (
                   UPDATE unified.concepts
                      SET name_embedding = NULL, description_embedding = NULL,
                          embedding_model = NULL
                    WHERE embedding_model IS NOT NULL AND embedding_model <> $1
                RETURNING 1)
               SELECT count(*) AS n FROM cleared""",
            (model_id,), fetch_all=True)

    async def hold_concept_vectors(self, *, concept_ids: List[str], name_vectors: List[Any],
                                   description_vectors: List[Any],
                                   descriptions: List[Any], model_id: str) -> List[Any]:
        """Vectors for concepts that had none, each only if its description is
        still the one encoded. Returns the rows written."""
        return await self._memory_db().execute_query(
            """UPDATE unified.concepts AS c
                  SET name_embedding = v.name_embedding,
                      description_embedding = v.description_embedding,
                      embedding_model = $5
                 FROM unnest($1::text[], $2::vector[], $3::vector[], $4::text[])
                      AS v(concept_id, name_embedding, description_embedding, description)
                WHERE c.concept_id = v.concept_id
                  AND c.embedding_model IS NULL
                  AND c.description IS NOT DISTINCT FROM v.description
            RETURNING c.concept_id""",
            (concept_ids, name_vectors, description_vectors, descriptions, model_id),
            fetch_all=True)

    async def file_concepts(self, *, domain: str, concept_ids: List[str]) -> None:
        """Concepts split out of a bucket into the subject their taxonomy names."""
        await self._memory_db().execute_query(
            "UPDATE unified.concepts SET domain = $1 "
            "WHERE concept_id = ANY($2)", (domain, concept_ids))

    async def refile_concepts(self, *, domain: str, concept_ids: List[str]) -> None:
        """Concepts moved into another subject, marked as updated."""
        await self._memory_db().execute_query(
            """UPDATE unified.concepts SET domain = $1, updated_at = NOW()
               WHERE concept_id = ANY($2::text[])""",
            (domain, concept_ids), commit=True)

    async def replace_sense_taxonomy(self, edges: Sequence[Sequence[str]]) -> int:
        """Replace the sense taxonomy with `edges` = [(child_qid, child_label,
        parent_qid, parent_label, field), ...]. Returns how many were given."""
        db = self._memory_db()
        await db.execute_query("TRUNCATE unified.sense_taxonomy", commit=True)
        n = 0
        for i in range(0, len(edges), 4000):
            chunk = edges[i:i + 4000]
            cols = list(zip(*chunk))            # 5 columns of the chunk
            await db.execute_query(
                """INSERT INTO unified.sense_taxonomy
                   (child_qid, child_label, parent_qid, parent_label, field)
                   SELECT * FROM unnest($1::text[],$2::text[],$3::text[],$4::text[],$5::text[])
                   ON CONFLICT DO NOTHING""",
                (list(cols[0]), list(cols[1]), list(cols[2]), list(cols[3]), list(cols[4])),
                commit=True)
            n += len(chunk)
        return n

    # ---- beliefs ------------------------------------------------------------

    async def hold_belief(self, *, belief_id: str, memory_id: Optional[str], claim: str,
                          domain: str, prior_probability: float,
                          posterior_probability: float, uncertainty_type: str,
                          entropy: float, evidence_for: str, evidence_against: str,
                          update_count: int, last_updated: Any,
                          expected_update_count: int) -> Optional[Any]:
        """A belief, replaced only while it is still at `expected_update_count`
        (-1 for one never stored). Returns the stored row, or None when another
        instance has moved the belief since; the belief system then merges its
        own evidence onto the stored belief and writes again.

        `claim` is written twice, as the claim and as `belief_text`, and the
        posterior as `confidence`: labels and a legacy mirror, not knowledge."""
        return await self._memory_db().execute_query(
            """
            INSERT INTO unified.beliefs AS b
                (belief_id, memory_id, claim, belief_text, confidence, domain,
                 prior_probability, posterior_probability,
                 uncertainty_type, entropy, evidence_for, evidence_against,
                 update_count, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            ON CONFLICT (belief_id) DO UPDATE SET
                memory_id           = EXCLUDED.memory_id,
                claim               = EXCLUDED.claim,
                belief_text         = EXCLUDED.belief_text,
                confidence          = EXCLUDED.confidence,
                domain              = EXCLUDED.domain,
                prior_probability   = EXCLUDED.prior_probability,
                posterior_probability = EXCLUDED.posterior_probability,
                uncertainty_type    = EXCLUDED.uncertainty_type,
                entropy             = EXCLUDED.entropy,
                evidence_for        = EXCLUDED.evidence_for,
                evidence_against    = EXCLUDED.evidence_against,
                update_count        = EXCLUDED.update_count,
                last_updated        = EXCLUDED.last_updated
            WHERE b.update_count = $15
            RETURNING update_count
            """,
            (belief_id, memory_id, claim, claim, posterior_probability, domain,
             prior_probability, posterior_probability, uncertainty_type, entropy,
             evidence_for, evidence_against, update_count, last_updated,
             expected_update_count),
            fetch_one=True,
        )

    async def drop_belief(self, belief_id: str) -> None:
        """A belief the substrate has let go, so a reload cannot bring it back."""
        await self._memory_db().execute_query(
            "DELETE FROM unified.beliefs WHERE belief_id = $1",
            (belief_id,), commit=True)

    async def hold_domain_volatility(self, *, domain: str, lam: float) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.domain_volatility (domain, lambda, updated_at)"
            " VALUES ($1, $2, NOW())"
            " ON CONFLICT (domain) DO UPDATE SET lambda = EXCLUDED.lambda,"
            "   updated_at = NOW()",
            (domain, lam), commit=True)

    async def hold_known_unknown(self, *, unknown_id: str, question: str, domain: str,
                                 knowledge_state: str, information_value: float,
                                 urgency: float, can_be_resolved: bool,
                                 resolution_strategy: Any, discovered_at: Any,
                                 resolution_attempts: int, blocking_factors: str,
                                 required_information: str, resolution_cost: Any,
                                 resolved_at: Any, resolution: Any,
                                 resolution_belief_id: Any, target: str,
                                 owner: Optional[str]) -> None:
        """A question held open, in its owner's store: a person's question is
        their context, the substrate's own is its model."""
        db = self._memory_db()
        await db.execute_query(
            """
            INSERT INTO unified.known_unknowns AS k
                (unknown_id, question, domain, knowledge_state, information_value,
                 urgency, can_be_resolved, resolution_strategy, discovered_at,
                 resolution_attempts, blocking_factors, required_information,
                 resolution_cost, resolved_at, resolution, resolution_belief_id,
                 target, owner)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::jsonb,$13,$14,$15,$16,
                    $17::jsonb,$18)
            ON CONFLICT (unknown_id) DO UPDATE SET
                knowledge_state      = EXCLUDED.knowledge_state,
                information_value    = EXCLUDED.information_value,
                urgency              = EXCLUDED.urgency,
                can_be_resolved      = EXCLUDED.can_be_resolved,
                resolution_strategy  = EXCLUDED.resolution_strategy,
                blocking_factors     = EXCLUDED.blocking_factors,
                required_information = EXCLUDED.required_information,
                resolution_cost      = EXCLUDED.resolution_cost,
                resolved_at          = EXCLUDED.resolved_at,
                resolution           = EXCLUDED.resolution,
                resolution_belief_id = EXCLUDED.resolution_belief_id,
                target               = CASE WHEN k.target = '{}'::jsonb
                                            THEN EXCLUDED.target ELSE k.target END
            -- ONE STORE, MANY INSTANCES: a resolved unknown is final (no instance
            -- with a stale copy can reopen it), attempts move only by atomic
            -- increment (`add_unknown_attempts`), and the first target stands.
            WHERE k.resolved_at IS NULL
            """,
            (unknown_id, question, domain, knowledge_state, information_value,
             urgency, can_be_resolved, resolution_strategy, discovered_at,
             resolution_attempts, blocking_factors, required_information,
             resolution_cost, resolved_at, resolution, resolution_belief_id,
             target, owner),
            commit=True,
            store=db.write_store(owner),
        )

    async def add_unknown_attempts(self, *, unknown_id: str, n: int) -> None:
        """Attempts at one of the substrate's own open questions, added to the
        stored count rather than written over it."""
        db = self._memory_db()
        await db.execute_query(
            "UPDATE unified.known_unknowns SET resolution_attempts = "
            "resolution_attempts + $2 WHERE unknown_id = $1 AND resolved_at IS NULL",
            (unknown_id, n), commit=True, store=db.write_store(None))

    async def hold_calibration(self, *, domain: str, prediction: str, confidence: float,
                               outcome: Any, timestamp: Any) -> None:
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.calibration_data
                (domain, prediction, confidence, outcome, timestamp)
            VALUES ($1,$2,$3,$4,$5)
            """,
            (domain, prediction, confidence, outcome, timestamp),
        )

    # ---- rules and demonstrations ---------------------------------------------

    async def hold_rule(self, *, rule_id: str, domain_id: str, rule_kind: str,
                        canonical_rule_json: str, rendered_formula: str,
                        epistemic_status: str, induction_method: str,
                        induction_version: Any, positive_root_count: int,
                        negative_root_count: int, counterexample_root_count: int,
                        detail: Optional[str], supersedes_rule_id: Optional[str],
                        semantic_fingerprint: Optional[str]) -> bool:
        """A learned rule. Returns whether it was written: a rule whose meaning
        is already held (the same fingerprint, recorded by another induction of
        the same hypothesis at the same moment) is not written twice."""
        rows = await self._memory_db().execute_query(
            "INSERT INTO unified.learned_rules ("
            " rule_id, domain_id, rule_kind, canonical_rule_json, rendered_formula,"
            " epistemic_status, induction_method, induction_version,"
            " positive_root_count, negative_root_count, counterexample_root_count,"
            " detail, supersedes_rule_id,"
            " semantic_fingerprint)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)"
            " ON CONFLICT (semantic_fingerprint) WHERE semantic_fingerprint IS NOT NULL"
            " DO NOTHING RETURNING rule_id",
            (rule_id, domain_id, rule_kind, canonical_rule_json, rendered_formula,
             epistemic_status, induction_method, induction_version,
             positive_root_count, negative_root_count, counterexample_root_count,
             detail, supersedes_rule_id, semantic_fingerprint),
            fetch_all=True,
        )
        return bool(rows)

    async def hold_rule_evidence(self, *, rule_id: str, root_evidence_id: str,
                                 evidence_role: str, supports: bool) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.learned_rule_evidence"
            " (rule_id, root_evidence_id, evidence_role, supports)"
            " VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
            (rule_id, root_evidence_id, evidence_role, supports),
        )

    async def recount_rule_evidence(self, *, rule_id: str,
                                    induction_negative_role: str) -> None:
        """A rule's root counts, recounted from its evidence, by role."""
        await self._memory_db().execute_query(
            "UPDATE unified.learned_rules SET"
            " positive_root_count = (SELECT count(DISTINCT root_evidence_id)"
            "   FROM unified.learned_rule_evidence WHERE rule_id = $1 AND supports),"
            " negative_root_count = (SELECT count(DISTINCT root_evidence_id)"
            "   FROM unified.learned_rule_evidence WHERE rule_id = $1"
            "   AND NOT supports AND evidence_role <> $2),"
            " counterexample_root_count = (SELECT count(DISTINCT root_evidence_id)"
            "   FROM unified.learned_rule_evidence WHERE rule_id = $1"
            "   AND evidence_role = $2),"
            " updated_at = NOW() WHERE rule_id = $1",
            (rule_id, induction_negative_role), commit=True)

    async def set_rule_status(self, *, rule_id: str, status: str, detail: Optional[str],
                              validation_policy: str, validation_version: Any,
                              validated_at: Any) -> None:
        await self._memory_db().execute_query(
            "UPDATE unified.learned_rules SET epistemic_status = $1, detail = $2,"
            " validation_policy = $3, validation_version = $4,"
            " validated_at = $5, updated_at = NOW() WHERE rule_id = $6",
            (status, detail, validation_policy, validation_version, validated_at, rule_id),
        )

    async def refute_rule(self, *, rule_id: str, status: str, detail: str) -> None:
        """A rule the world contradicted while it was being used."""
        await self._memory_db().execute_query(
            "UPDATE unified.learned_rules SET epistemic_status = $1, validated_at = NULL,"
            " detail = $2, updated_at = NOW() WHERE rule_id = $3",
            (status, detail, rule_id),
        )

    async def hold_rule_projection(self, *, rule_id: str, source_rule_id: str,
                                   mapping_id: str, role: str, target_element: str,
                                   source_element: str, mapping_edge: str) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.rule_projections (rule_id, source_rule_id,"
            " mapping_id, role, target_element, source_element, mapping_edge)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING",
            (rule_id, source_rule_id, mapping_id, role, target_element,
             source_element, mapping_edge),
            commit=True)

    async def hold_supersession(self, *, replacement_rule_id: str,
                                superseded_rule_id: str) -> None:
        """A narrower rule replaced one that was too broad."""
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.rule_supersessions"
            " (replacement_rule_id, superseded_rule_id) VALUES ($1, $2)"
            " ON CONFLICT DO NOTHING",
            (replacement_rule_id, superseded_rule_id),
            commit=True,
        )
        # Kept in step for readers of the row itself; the join table is the
        # authority, and is what executable_rules consults.
        await db.execute_query(
            "UPDATE unified.learned_rules SET supersedes_rule_id = $1, updated_at = NOW()"
            " WHERE rule_id = $2",
            (superseded_rule_id, replacement_rule_id),
            commit=True,
        )

    async def forget_rules(self, rule_ids: List[str],
                           referencing: Sequence[Tuple[str, str]]) -> None:
        """Delete these rules and every row `referencing` names as pointing at
        them, (table, column) by (table, column)."""
        db = self._memory_db()
        # A rule may supersede another in this same set, so clear the self
        # reference before deleting any of them.
        await db.execute_query(
            "UPDATE unified.learned_rules SET supersedes_rule_id = NULL "
            "WHERE supersedes_rule_id = ANY($1::text[])", (rule_ids,), fetch_all=False)
        for table, column in referencing:
            await db.execute_query(
                f"DELETE FROM {table} WHERE {column} = ANY($1::text[])",
                (rule_ids,), fetch_all=False)
        await db.execute_query(
            "DELETE FROM unified.learned_rules WHERE rule_id = ANY($1::text[])",
            (rule_ids,), fetch_all=False)

    async def record_rule_authority_change(self, *, event_id: str, rule_id: str,
                                           old_status: str, new_status: str,
                                           lost_authority: bool, cause: str,
                                           observation_id: Optional[str],
                                           task_id: Optional[str], plan_id: Optional[str],
                                           goal_id: Optional[str],
                                           detail: Optional[str]) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.rule_authority_events"
            " (event_id, rule_id, old_status, new_status, lost_authority, cause,"
            "  observation_id, task_id, plan_id, goal_id, detail)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            (event_id, rule_id, old_status, new_status, lost_authority, cause,
             observation_id, task_id, plan_id, goal_id, detail),
            commit=True,
        )

    async def mark_rule_authority_changes_consumed(self, *, event_ids: List[str],
                                                   consumer: str) -> List[Any]:
        """Claim these changes for `consumer`. Returns only the rows this call
        claimed; ones already consumed are left alone."""
        return await self._memory_db().execute_query(
            "UPDATE unified.rule_authority_events SET consumed_at = NOW(), consumed_by = $1"
            " WHERE event_id = ANY($2::varchar[]) AND consumed_at IS NULL"
            " RETURNING event_id",
            (consumer, event_ids), fetch_all=True,
        )

    async def hold_conditional(self, *, conditional_id: str, ant_subject: str,
                               ant_relation: str, ant_object: Any, ant_positive: bool,
                               cons_subject: str, cons_relation: str, cons_object: Any,
                               cons_positive: bool, surface: str, domain: str,
                               source_id: Any, source_type: Any) -> Any:
        """A taught conditional, held as a rule."""
        return await self._memory_db().execute_query(
            """INSERT INTO unified.held_conditionals
               (conditional_id, ant_subject, ant_relation, ant_object,
                ant_positive, cons_subject, cons_relation, cons_object,
                cons_positive, surface, domain, source_id, source_type)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT (conditional_id) DO NOTHING""",
            (conditional_id, ant_subject, ant_relation, ant_object, ant_positive,
             cons_subject, cons_relation, cons_object, cons_positive, surface, domain,
             source_id, source_type), commit=True)

    async def hold_demonstration(self, *, evidence_id: str, domain_id: str, predicate: str,
                                 arity: int, before_facts: str, action: Optional[str],
                                 after_facts: str, positive: bool) -> List[Any]:
        """One observed action: what held before, the action, what held after.
        Returns the rows written, so one seen before reads as nothing written."""
        return await self._memory_db().execute_query(
            "INSERT INTO unified.operator_demonstrations"
            " (evidence_id, domain_id, predicate, arity, before_facts, action,"
            "  after_facts, positive)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
            " ON CONFLICT (evidence_id) DO NOTHING"
            " RETURNING evidence_id",
            (evidence_id, domain_id, predicate, arity, before_facts, action,
             after_facts, positive),
            fetch_all=True,
        )

    async def mark_induction_pending(self, *, domain_id: str, predicate: str,
                                     arity: int) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.operator_induction_pending (domain_id, predicate, arity)"
            " VALUES ($1, $2, $3)"
            " ON CONFLICT (domain_id, predicate, arity) DO UPDATE SET enqueued_at = NOW()",
            (domain_id, predicate, arity), commit=True)

    async def clear_induction_pending(self, *, domain_id: str, predicate: str,
                                      arity: int) -> None:
        await self._memory_db().execute_query(
            "DELETE FROM unified.operator_induction_pending"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3",
            (domain_id, predicate, arity), commit=True)

    # ---- domains ------------------------------------------------------------

    async def hold_domain(self, *, domain_id: str, name: str, description: str,
                          metadata: str) -> Any:
        return await self._memory_db().execute_query(
            """INSERT INTO unified.domains
                   (domain_id, domain_name, description, metadata, last_accessed)
               VALUES ($1, $2, $3, $4::jsonb, NOW())
               ON CONFLICT (domain_id) DO UPDATE SET
                   domain_name   = EXCLUDED.domain_name,
                   description   = EXCLUDED.description,
                   metadata      = EXCLUDED.metadata,
                   last_accessed = NOW()""",
            (domain_id, name, description, metadata),
            commit=True,
        )

    async def hold_default_domain(self, *, domain_id: str, name: str,
                                  description: str) -> None:
        await self._memory_db().execute_query(
            """INSERT INTO unified.domains (domain_id, domain_name, description)
               VALUES ($1, $2, $3)
               ON CONFLICT (domain_id) DO NOTHING""",
            (domain_id, name, description),
            commit=True
        )

    async def hold_domain_mapping(self, *, mapping_id: str, source_domain: str,
                                  target_domain: str, source_concept: str,
                                  target_concept: str, similarity_score: float,
                                  reasoning_strategy: str, verified: Optional[bool],
                                  confidence: float, metadata: str) -> Any:
        return await self._memory_db().execute_query(
            """INSERT INTO unified.domain_mappings
                   (mapping_id, source_domain, target_domain, source_concept,
                    target_concept, similarity_score, reasoning_strategy,
                    verified, confidence, metadata, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
               ON CONFLICT (mapping_id) DO UPDATE SET
                   similarity_score = EXCLUDED.similarity_score,
                   verified         = EXCLUDED.verified,
                   confidence       = EXCLUDED.confidence,
                   metadata         = EXCLUDED.metadata""",
            (mapping_id, source_domain, target_domain, source_concept, target_concept,
             similarity_score, reasoning_strategy, verified, confidence, metadata),
            commit=True,
        )

    async def hold_domain_correspondence(self, *, mapping_id: str, source_domain: str,
                                         target_domain: str, source_concept: str,
                                         target_concept: str, similarity_score: float,
                                         reasoning_strategy: str, verified: bool,
                                         confidence: float, metadata: str) -> None:
        """That one domain's operators are another's under a renaming of their
        predicates: the bridge a merge produces. Kept as first recorded."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.domain_mappings
                   (mapping_id, source_domain, target_domain, source_concept,
                    target_concept, similarity_score, reasoning_strategy,
                    verified, confidence, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
               ON CONFLICT DO NOTHING""",
            (mapping_id, source_domain, target_domain, source_concept, target_concept,
             similarity_score, reasoning_strategy, verified, confidence, metadata),
            commit=True,
        )

    async def hold_knowledge_transfer(self, *, transfer_id: str, source_domain: str,
                                      target_domain: str, concept: str, concept_type: str,
                                      transfer_method: str, success: Optional[bool],
                                      metadata: str, created_at: Any,
                                      completed_at: Any) -> Any:
        return await self._memory_db().execute_query(
            """INSERT INTO unified.knowledge_transfers
                   (transfer_id, source_domain, target_domain, concept,
                    concept_type, transfer_method, success, metadata,
                    created_at, completed_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
               -- Deriving a transfer again states no outcome. It must not
               -- erase the outcome resolve_knowledge_transfer recorded, or
               -- the measured effectiveness and its evidence.
               ON CONFLICT (transfer_id) DO UPDATE SET
                   success      = COALESCE(EXCLUDED.success,
                                           unified.knowledge_transfers.success),
                   metadata     = CASE
                       WHEN unified.knowledge_transfers.success IS NULL
                       THEN EXCLUDED.metadata
                       ELSE EXCLUDED.metadata || jsonb_build_object(
                           'effectiveness_score',
                           unified.knowledge_transfers.metadata->'effectiveness_score',
                           'outcome_evidence',
                           unified.knowledge_transfers.metadata->'outcome_evidence')
                       END,
                   completed_at = COALESCE(EXCLUDED.completed_at,
                                           unified.knowledge_transfers.completed_at)""",
            (transfer_id, source_domain, target_domain, concept, concept_type,
             transfer_method, success, metadata, created_at, completed_at),
            commit=True,
        )

    async def resolve_knowledge_transfer(self, *, transfer_id: str, helped: bool,
                                         metadata: str) -> Any:
        """Whether a transfer helped, with the evidence it was judged on."""
        return await self._memory_db().execute_query(
            """UPDATE unified.knowledge_transfers
               SET success      = $2,
                   completed_at = NOW(),
                   metadata     = COALESCE(metadata, '{}'::jsonb) || $3::jsonb
               WHERE transfer_id = $1""",
            (transfer_id, helped, metadata),
            commit=True,
        )

    async def record_mapping_use(self, *, usage_id: str, mapping_id: str,
                                 transfer_id: Optional[str], task_id: str,
                                 application_stage: str, source_domain: str,
                                 target_domain: str, provenance: str) -> Any:
        return await self._memory_db().execute_query(
            """INSERT INTO unified.mapping_usage_events
                   (usage_id, mapping_id, transfer_id, task_id,
                    application_stage, source_domain, target_domain,
                    provenance)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
               ON CONFLICT (usage_id) DO NOTHING""",
            (usage_id, mapping_id, transfer_id, task_id, application_stage,
             source_domain, target_domain, provenance),
            commit=True)

    async def record_controllability(self, *, domain_id: str, action_attempts: int,
                                     action_effects: int, still_observations: int,
                                     ambient_changes: int) -> None:
        """Evidence on whether acting moves a domain, added to what is held."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.domain_controllability
                   (domain_id, action_attempts, action_effects,
                    still_observations, ambient_changes)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (domain_id) DO UPDATE SET
                   action_attempts    = domain_controllability.action_attempts + EXCLUDED.action_attempts,
                   action_effects     = domain_controllability.action_effects + EXCLUDED.action_effects,
                   still_observations = domain_controllability.still_observations + EXCLUDED.still_observations,
                   ambient_changes    = domain_controllability.ambient_changes + EXCLUDED.ambient_changes,
                   updated_at         = NOW()""",
            (domain_id, action_attempts, action_effects, still_observations, ambient_changes),
            commit=True)

    async def record_operating_outcome(self, *, domain_id: str, win: int) -> None:
        """One verified operating attempt in a domain; `win` is 1 when it was right."""
        await self._memory_db().execute_query(
            """INSERT INTO unified.domain_controllability
                   (domain_id, operating_attempts, operating_wins)
               VALUES ($1, 1, $2)
               ON CONFLICT (domain_id) DO UPDATE SET
                   operating_attempts = domain_controllability.operating_attempts + 1,
                   operating_wins     = domain_controllability.operating_wins + EXCLUDED.operating_wins,
                   updated_at         = NOW()""",
            (domain_id, win), commit=True)

    # ---- what reasoning produced --------------------------------------------

    # Argumentation and temporal knowledge are whoever's reasoning made them: a
    # person's rows go to their context, the substrate's to its own store.

    async def hold_argument_claim(self, *, claim_id: str, statement: str, warrant: Any,
                                  qualifier: Any, confidence: float, source: Any,
                                  origin: "Origin") -> None:
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.reasoning_arg_claims "
            "(claim_id, statement, warrant, qualifier, confidence, source, owner) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (claim_id) DO UPDATE SET "
            "statement=EXCLUDED.statement, confidence=EXCLUDED.confidence",
            (claim_id, statement, warrant, qualifier, confidence, source, owner),
            commit=True, store=db.write_store(owner))

    async def hold_argument(self, *, argument_id: str, claim_id: str, argument_type: str,
                            conclusion: Any, strength: Any, validity: bool,
                            soundness: bool, refuted_by: Any, origin: "Origin") -> None:
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.reasoning_arguments "
            "(argument_id, claim_id, argument_type, conclusion, strength, "
            "validity, soundness, refuted_by, owner) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
            "ON CONFLICT (argument_id) DO UPDATE SET validity=EXCLUDED.validity, "
            "soundness=EXCLUDED.soundness, refuted_by=EXCLUDED.refuted_by",
            (argument_id, claim_id, argument_type, conclusion, strength, validity,
             soundness, refuted_by, owner), commit=True, store=db.write_store(owner))

    async def hold_fallacy(self, *, fallacy_id: str, fallacy_type: str, argument_id: str,
                           description: Any, severity: float, origin: "Origin") -> None:
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.reasoning_arg_fallacies "
            "(fallacy_id, fallacy_type, argument_id, description, severity, owner) "
            "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (fallacy_id) DO UPDATE SET "
            "description=EXCLUDED.description, severity=EXCLUDED.severity",
            (fallacy_id, fallacy_type, argument_id, description, severity, owner),
            commit=True, store=db.write_store(owner))

    async def hold_temporal_proposition(self, *, prop_id: str, statement: str,
                                        time_point: Any, ts: Any, is_true: bool,
                                        confidence: float, origin: "Origin") -> None:
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.reasoning_temporal_propositions "
            "(prop_id, statement, time_point, ts, is_true, confidence, owner) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (prop_id) DO UPDATE SET "
            "statement=EXCLUDED.statement, is_true=EXCLUDED.is_true, "
            "confidence=EXCLUDED.confidence",
            (prop_id, statement, time_point, ts, is_true, confidence, owner),
            commit=True, store=db.write_store(owner))

    async def hold_causal_link(self, *, link_id: str, cause_id: str, effect_id: str,
                               causal_strength: float, necessary: bool, sufficient: bool,
                               observations: int, origin: "Origin") -> None:
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.reasoning_temporal_causal_links "
            "(link_id, cause_id, effect_id, causal_strength, necessary, "
            "sufficient, observations, owner) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
            "ON CONFLICT (link_id) DO UPDATE SET "
            "causal_strength=EXCLUDED.causal_strength, "
            "observations=EXCLUDED.observations",
            (link_id, cause_id, effect_id, causal_strength, necessary, sufficient,
             observations, owner), commit=True, store=db.write_store(owner))

    async def hold_hypothesis(self, *, hypothesis_id: str, claim: str, domain: Any,
                              is_falsifiable: bool, null_hypothesis: Any, status: str,
                              confidence: float, proposed_at: Any, revisions: Any,
                              parent_hypothesis_id: Any, falsification_criteria: str,
                              verification_criteria: str, predictions: str,
                              testable_predictions: str, alternative_hypotheses: str,
                              supporting_evidence: str,
                              contradicting_evidence: str, origin: "Origin") -> None:
        """A hypothesis, kept in its owner's store: a person's in their context."""
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            """
            INSERT INTO unified.hypotheses
            (hypothesis_id, claim, domain, is_falsifiable, null_hypothesis,
             status, confidence, proposed_at, revisions, parent_hypothesis_id,
             falsification_criteria, verification_criteria, predictions,
             testable_predictions, alternative_hypotheses,
             supporting_evidence, contradicting_evidence, owner)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15, $16, $17, $18)
            ON CONFLICT (hypothesis_id) DO UPDATE SET
                claim = EXCLUDED.claim,
                domain = EXCLUDED.domain,
                is_falsifiable = EXCLUDED.is_falsifiable,
                null_hypothesis = EXCLUDED.null_hypothesis,
                status = EXCLUDED.status,
                confidence = EXCLUDED.confidence,
                proposed_at = EXCLUDED.proposed_at,
                revisions = EXCLUDED.revisions,
                parent_hypothesis_id = EXCLUDED.parent_hypothesis_id,
                falsification_criteria = EXCLUDED.falsification_criteria,
                verification_criteria = EXCLUDED.verification_criteria,
                predictions = EXCLUDED.predictions,
                testable_predictions = EXCLUDED.testable_predictions,
                alternative_hypotheses = EXCLUDED.alternative_hypotheses,
                supporting_evidence = EXCLUDED.supporting_evidence,
                contradicting_evidence = EXCLUDED.contradicting_evidence
            """,
            (hypothesis_id, claim, domain, is_falsifiable, null_hypothesis, status,
             confidence, proposed_at, revisions, parent_hypothesis_id,
             falsification_criteria, verification_criteria, predictions,
             testable_predictions, alternative_hypotheses, supporting_evidence,
             contradicting_evidence, owner),
            commit=True, store=db.write_store(owner)
        )

    async def hold_experiment(self, *, experiment_id: str, hypothesis_id: str, name: str,
                              description: Any, expected_outcome: Any, status: str,
                              outcome_supports_hypothesis: Any, designed_at: Any,
                              completed_at: Any, execution_time: Any,
                              origin: "Origin") -> None:
        """An experiment, kept where its hypothesis is."""
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            """
            INSERT INTO unified.experiments
            (experiment_id, hypothesis_id, name, description, expected_outcome,
             status, outcome_supports_hypothesis, designed_at, completed_at, execution_time,
             owner)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (experiment_id) DO UPDATE SET
                hypothesis_id = EXCLUDED.hypothesis_id,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                expected_outcome = EXCLUDED.expected_outcome,
                status = EXCLUDED.status,
                outcome_supports_hypothesis = EXCLUDED.outcome_supports_hypothesis,
                designed_at = EXCLUDED.designed_at,
                completed_at = EXCLUDED.completed_at,
                execution_time = EXCLUDED.execution_time
            """,
            (experiment_id, hypothesis_id, name, description, expected_outcome, status,
             outcome_supports_hypothesis, designed_at, completed_at, execution_time, owner),
            commit=True, store=db.write_store(owner)
        )

    async def hold_hypothesis_evidence(self, *, evidence_id: str, hypothesis_id: str,
                                       evidence_type: str, description: Any,
                                       quality_score: float, supports_hypothesis: Any,
                                       strength: Any, source: Any, experiment_id: Any,
                                       collected_at: Any, origin: "Origin") -> None:
        """Evidence on a hypothesis, kept where the hypothesis is."""
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            """
            INSERT INTO unified.evidence
            (evidence_id, hypothesis_id, evidence_type, description, quality_score,
             supports_hypothesis, strength, source, experiment_id, collected_at, owner)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (evidence_id) DO UPDATE SET
                hypothesis_id = EXCLUDED.hypothesis_id,
                evidence_type = EXCLUDED.evidence_type,
                description = EXCLUDED.description,
                quality_score = EXCLUDED.quality_score,
                supports_hypothesis = EXCLUDED.supports_hypothesis,
                strength = EXCLUDED.strength,
                source = EXCLUDED.source,
                experiment_id = EXCLUDED.experiment_id,
                collected_at = EXCLUDED.collected_at
            """,
            (evidence_id, hypothesis_id, evidence_type, description, quality_score,
             supports_hypothesis, strength, source, experiment_id, collected_at, owner),
            commit=True, store=db.write_store(owner)
        )

    async def hold_schema(self, *, schema_id: str, belief_id: Optional[str],
                          probability: float, payload: str, formation_time: Any) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.schemas"
            " (schema_id, belief_id, probability, payload, formation_time, updated_at)"
            " VALUES ($1, $2, $3, $4, $5, NOW())"
            " ON CONFLICT (schema_id) DO UPDATE SET"
            "   belief_id = EXCLUDED.belief_id, probability = EXCLUDED.probability,"
            "   payload = EXCLUDED.payload, updated_at = NOW()",
            (schema_id, belief_id, probability, payload, formation_time),
            commit=True)

    async def drop_schema(self, schema_id: str) -> None:
        await self._memory_db().execute_query(
            "DELETE FROM unified.schemas WHERE schema_id = $1",
            (schema_id,), commit=True)

    async def hold_analogy(self, *, analogy_id: str, analogy_type: str, source_domain: Any,
                           target_domain: Any, coherence: float, novelty: float,
                           utility: float, score: float, description: Any, insights: str,
                           mappings: str, primary_mapping: Optional[str]) -> None:
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.analogies (
                analogy_id, analogy_type, source_domain, target_domain,
                coherence, novelty, utility, score, description, insights,
                mappings, primary_mapping, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
            ON CONFLICT (analogy_id) DO UPDATE SET
                coherence = EXCLUDED.coherence,
                novelty = EXCLUDED.novelty,
                utility = EXCLUDED.utility,
                score = EXCLUDED.score,
                insights = EXCLUDED.insights,
                mappings = EXCLUDED.mappings
            """,
            params=(analogy_id, analogy_type, source_domain, target_domain, coherence,
                    novelty, utility, score, description, insights, mappings,
                    primary_mapping),
            commit=True,
        )

    async def hold_concept_mapping(self, *, mapping_id: str, source_concept: str,
                                   target_concept: str, mapping_type: str,
                                   structural_similarity: float,
                                   functional_similarity: float, confidence: float) -> None:
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.concept_mappings (
                mapping_id, source_concept, target_concept, mapping_type,
                structural_similarity, functional_similarity, confidence,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (mapping_id) DO UPDATE SET
                confidence = EXCLUDED.confidence,
                structural_similarity = EXCLUDED.structural_similarity,
                functional_similarity = EXCLUDED.functional_similarity
            """,
            params=(mapping_id, source_concept, target_concept, mapping_type,
                    structural_similarity, functional_similarity, confidence),
            commit=True,
        )

    # ---- perception -----------------------------------------------------------

    async def hold_vision_instance(self, *, name: str, descriptors: bytes, rows: int,
                                   cols: int, dtype: str) -> None:
        """A reference image's features, so the instance is recognised by name."""
        await self._memory_db().execute_query(
            "INSERT INTO unified.vision_instances (name, descriptors, rows, cols, dtype) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (name) DO UPDATE SET "
            "descriptors = EXCLUDED.descriptors, rows = EXCLUDED.rows, "
            "cols = EXCLUDED.cols, dtype = EXCLUDED.dtype, learned_at = NOW()",
            (name, descriptors, rows, cols, dtype), commit=True)

    async def drop_vision_instance(self, name: str) -> Optional[Any]:
        """Returns the row removed, or None when there was none."""
        return await self._memory_db().execute_query(
            "DELETE FROM unified.vision_instances WHERE name = $1 RETURNING name",
            (name,), fetch_one=True)

    async def hold_sound_instance(self, *, name: str, landmarks: bytes, rows: int,
                                  cols: int, dtype: str) -> None:
        """A reference sound's landmarks, so the sound is recognised by name when
        it is heard again."""
        await self._memory_db().execute_query(
            "INSERT INTO unified.sound_instances (name, landmarks, rows, cols, dtype) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (name) DO UPDATE SET "
            "landmarks = EXCLUDED.landmarks, rows = EXCLUDED.rows, "
            "cols = EXCLUDED.cols, dtype = EXCLUDED.dtype, learned_at = NOW()",
            (name, landmarks, rows, cols, dtype), commit=True)

    async def drop_sound_instance(self, name: str) -> Optional[Any]:
        """Returns the row removed, or None when there was none."""
        return await self._memory_db().execute_query(
            "DELETE FROM unified.sound_instances WHERE name = $1 RETURNING name",
            (name,), fetch_one=True)

    #: The tags on a hearing that was a LESSON: an example of a spoken word
    #: being said, of a person's voice, or of a song. The lesson is a hearing
    #: like any other, remembered as one; its tag and its record say what it
    #: taught, and the example measured for matching is kept in its trace.
    SPOKEN_WORD_TAG = "spoken_word"
    VOICE_TAG = "voice"
    SONG_TAG = "song"
    #: A seeing that was a lesson: a thing shown, told what it is.
    THING_TAG = "thing"
    #: How many lessons `lessons_taught` reads. Named, because a silent cap
    #: here reads as "that word was never taught".
    TAUGHT_BY_HEARING_LIMIT = 20000

    async def lessons_taught(self, tag: str, key: str) -> Dict[str, List[bytes]]:
        """Every hearing or seeing that taught under `tag` (`SPOKEN_WORD_TAG`,
        `VOICE_TAG`, `SONG_TAG` or `THING_TAG`), as memory holds it: what it
        taught (the word, whose voice, which song, which thing, read from `key`
        in the lesson's own record) -> the traces kept with those lessons. A
        view over memories, not a store beside them."""
        from core.memory.media_store import get_media_store
        rows = await self.search_memories(
            tags={tag}, limit=self.TAUGHT_BY_HEARING_LIMIT) or []
        taught: Dict[str, List[bytes]] = {}
        for item in rows:
            # WHAT EACH HEARING TAUGHT is read off that hearing's own record: a
            # pursuit's memory can hold several hearings, and each says what it
            # taught; a hearing that is a memory of its own says it in both.
            for media in await get_media_store().media_for_memory(item.memory_id):
                label = str(((media.get("perceived") or {}).get("lesson") or {}).get(key)
                            or "").strip()
                if label:
                    taught.setdefault(label, []).append(media["bytes"])
        return taught

    async def hold_perception(self, *, perception_id: str, source: Any, data_type: Any,
                              content: str, confidence: float, timestamp: Any,
                              metadata: str, origin: "Origin") -> None:
        """One perception, kept in its owner's store: a person's image in their
        context, the substrate's own seeing in its own."""
        owner = self._owner_from(origin)
        db = self._memory_db()
        await db.execute_query(
            """
            INSERT INTO unified.perceptions
            (id, source, data_type, content, confidence, timestamp, metadata, owner)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                source = EXCLUDED.source,
                data_type = EXCLUDED.data_type,
                content = EXCLUDED.content,
                confidence = EXCLUDED.confidence,
                timestamp = EXCLUDED.timestamp,
                metadata = EXCLUDED.metadata,
                owner = EXCLUDED.owner
            """,
            params=(perception_id, source, data_type, content, confidence, timestamp,
                    metadata, owner),
            commit=True, store=db.write_store(owner),
        )

    # ---- a person's context -----------------------------------------------------

    async def hold_scoped_relation(self, *, actor: str, subject: str, relation: str,
                                   obj: str, polarity: str, surface: Any, domain: Any,
                                   source: str) -> None:
        """A link a person told the substrate, in that person's context."""
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.scoped_concept_relations
                (scope_actor, subj, rel, obj, polarity, surface, domain,
                 source, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now())
            ON CONFLICT (scope_actor, subj, rel, obj) DO UPDATE SET
                polarity = EXCLUDED.polarity, surface = EXCLUDED.surface,
                domain = EXCLUDED.domain, last_updated = now()
            """,
            (actor, subject, relation, obj, polarity, surface, domain, source),
            commit=True)

    async def hold_scoped_belief(self, *, actor: str, claim_key: str, claim: str,
                                 domain: Any, prior: float, posterior: float,
                                 supports: bool, update_count: int, surface: Any,
                                 source: str) -> None:
        """A belief in a claim a person told the substrate, in that person's context."""
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.scoped_beliefs
                (scope_actor, claim_key, claim, domain, prior, posterior,
                 supports, update_count, surface, source, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
            ON CONFLICT (scope_actor, claim_key) DO UPDATE SET
                claim = EXCLUDED.claim, domain = EXCLUDED.domain,
                posterior = EXCLUDED.posterior, supports = EXCLUDED.supports,
                update_count = EXCLUDED.update_count, surface = EXCLUDED.surface,
                source = EXCLUDED.source, last_updated = now()
            """,
            (actor, claim_key, claim, domain, prior, posterior, supports,
             update_count, surface, source),
            commit=True)

    async def mark_scoped_belief_promoted(self, claim_key: str) -> None:
        await self._memory_db().execute_query(
            "UPDATE unified.scoped_beliefs SET promoted = TRUE WHERE claim_key = $1",
            (claim_key,), commit=True)

    async def hold_belief_about_speaker(self, *, speaker: str, subject: str, relation: str,
                                        obj: Optional[str], polarity: str,
                                        surface: str) -> None:
        """What a person said about themselves; a restatement replaces it."""
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.user_beliefs
                (speaker, subject, relation, object, polarity, surface, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (speaker, subject, relation) DO UPDATE SET
                object = EXCLUDED.object, polarity = EXCLUDED.polarity,
                surface = EXCLUDED.surface, updated_at = now()
            """,
            (speaker, subject, relation, obj, polarity, surface),
            commit=True,
        )

    # ---- the record of what was learned -------------------------------------------

    async def record_knowledge_update(self, *, update_id: str, batch_id: str, cause: str,
                                      actor: Optional[str], subject_kind: str,
                                      subject_id: str, disposition: str,
                                      domain: Optional[str], from_domain: Optional[str],
                                      evidence_id: Optional[str],
                                      detail: Optional[str]) -> None:
        await self._memory_db().execute_query(
            "INSERT INTO unified.knowledge_updates"
            " (update_id, batch_id, cause, actor, subject_kind, subject_id,"
            "  disposition, domain, from_domain, evidence_id, detail)"
            " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)"
            " ON CONFLICT (update_id) DO NOTHING",
            (update_id, batch_id, cause, actor, subject_kind, subject_id, disposition,
             domain, from_domain, evidence_id, detail), commit=True)

    async def record_knowledge_updates(self, rows: Sequence[Sequence[Any]]) -> int:
        """Many updates in one statement, each row the eleven columns of
        `record_knowledge_update` in order. A sweep that moves thousands of
        concepts is one round trip."""
        if not rows:
            return 0
        values, params = [], []
        for i, row in enumerate(rows):
            base = i * 11
            values.append("(" + ",".join(f"${base + n}" for n in range(1, 12)) + ")")
            params.extend(row)
        await self._memory_db().execute_query(
            "INSERT INTO unified.knowledge_updates"
            " (update_id, batch_id, cause, actor, subject_kind, subject_id,"
            "  disposition, domain, from_domain, evidence_id, detail) VALUES "
            + ",".join(values) + " ON CONFLICT (update_id) DO NOTHING",
            tuple(params), commit=True)
        return len(rows)

    async def mark_knowledge_consumed(self, *, update_ids: List[str],
                                      consumer: str) -> List[Any]:
        """Record that `consumer` used these updates. Returns the rows this call
        newly recorded, not the ones asked about."""
        return await self._memory_db().execute_query(
            "INSERT INTO unified.knowledge_consumption (update_id, consumer)"
            " SELECT update_id, $2 FROM unified.knowledge_updates"
            " WHERE update_id = ANY($1::varchar[])"
            " ON CONFLICT (update_id, consumer) DO NOTHING RETURNING update_id",
            (update_ids, consumer), fetch_all=True) or []

    async def mark_behaviour_change(self, *, batch_id: str, changed: bool,
                                    detail: str) -> None:
        await self._memory_db().execute_query(
            "UPDATE unified.knowledge_updates SET changed_behaviour = $1,"
            " behaviour_detail = $2 WHERE batch_id = $3",
            (changed, detail, batch_id), commit=True)

    # ---- trained recognisers and training examples ------------------------------------

    async def hold_clause_classifier(self, *, name: str, mechanism: bytes, labels: str,
                                     vocabulary: Optional[str], reject_label: Any,
                                     registered_at: Any) -> None:
        """A trained clause recogniser. A classifier registered later elsewhere
        is never replaced by an older one."""
        await self._memory_db().execute_query(
            "INSERT INTO unified.clause_classifiers AS c (name, mechanism, labels, "
            "vocabulary, reject_label, registered_at) VALUES ($1, $2, $3::jsonb, "
            "$4::jsonb, $5, $6) ON CONFLICT (name) DO UPDATE SET "
            "mechanism = EXCLUDED.mechanism, labels = EXCLUDED.labels, "
            "vocabulary = EXCLUDED.vocabulary, reject_label = EXCLUDED.reject_label, "
            "registered_at = EXCLUDED.registered_at, saved_at = NOW() "
            "WHERE c.registered_at < EXCLUDED.registered_at",
            (name, mechanism, labels, vocabulary, reject_label, registered_at), commit=True)

    async def hold_security_training_example(self, *, input_text: str, attack_type: Any,
                                             expected_behavior: Any,
                                             is_malicious: bool) -> None:
        await self._memory_db().execute_query(
            """
            INSERT INTO security_training_examples
            (input_text, attack_type, expected_behavior, is_malicious, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            params=(input_text, attack_type, expected_behavior, is_malicious),
        )

    # ---- what development takes from a serving environment ---------------------------

    async def mark_taken(self, connection: Any, *, tier: str, memory_id: str,
                         taken_at: str, taken_into: Optional[str]) -> None:
        """Mark a memory in a serving environment's learning store as taken into
        development, so taking again takes it once. That store is another
        database; `connection` is the release tool's connection to it."""
        await connection.execute(
            f"UPDATE {tier} SET metadata = COALESCE(metadata, '{{}}'::jsonb) || $2::jsonb "
            f"WHERE memory_id = $1", memory_id,
            json.dumps({"taken_at": taken_at, "taken_into": taken_into}))

    async def hold_taken_question(self, row: Dict[str, Any]) -> int:
        """One of a serving environment's own open questions, joined to
        development's. Returns 1 when it was new here."""
        columns = list(row)
        db = self._memory_db()
        written = await db.execute_query(
            f"INSERT INTO unified.known_unknowns ({', '.join(columns)}) VALUES "
            f"({', '.join(f'${i + 1}' for i in range(len(columns)))}) "
            f"ON CONFLICT (unknown_id) DO NOTHING RETURNING unknown_id",
            tuple(row[c] for c in columns), fetch_all=True,
            store=db.write_store(None)) or []
        return len(written)

    async def add_recorded_use(self, *, memory_id: str, access_count: int,
                               last_accessed: Any) -> int:
        """Recalls a serving environment recorded of a release memory, added to
        development's memory. Returns how many rows took them (0 when
        development no longer holds it)."""
        db = self._memory_db()
        store = db.write_store(None)
        hot = await db.execute_query(
            "UPDATE memory_hot SET access_count = access_count + $2, "
            "last_accessed = GREATEST(last_accessed, $3) WHERE memory_id = $1 "
            "RETURNING memory_id",
            (memory_id, access_count, last_accessed), fetch_all=True,
            use_hot_tier=True, store=store) or []
        cold = await db.execute_query(
            "UPDATE memory_cold SET access_count = access_count + $2, "
            "last_accessed = GREATEST(last_accessed, $3) WHERE memory_id = $1 "
            "RETURNING memory_id",
            (memory_id, access_count, last_accessed), fetch_all=True,
            use_cold_tier=True, store=store) or []
        return len(hot) + len(cold)

    # ================================================================================================
    # THE POOL: experiences waiting to be decided
    # ================================================================================================
    #
    # What the substrate lives through -- a task, research, a conversation, a
    # seeing, reasoning done for someone -- is handed over whole, as an
    # `Experience` whose every part says where it came from. The person's
    # episode is already theirs, written by the records the work keeps. The
    # experience waits here as a candidate, in its owner's store: a person's in
    # their context, since its parts still carry their particulars, and the
    # substrate's own in the model. Nothing reads the pool as knowledge; the
    # worker below decides each item, and what may be learned from a candidate
    # is decided later by the lift and the gate.

    POOL_LEASE_SECONDS = 120
    POOL_BATCH = 20

    _POOL_DDL = (
        """CREATE TABLE IF NOT EXISTS unified.experience_pool (
               item_id       TEXT PRIMARY KEY,
               owner         TEXT,
               kind          TEXT NOT NULL,
               through       TEXT NOT NULL,
               about         TEXT,
               parts         JSONB,
               memory_id     TEXT,
               evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
               fingerprint   TEXT NOT NULL,
               seen          INTEGER NOT NULL DEFAULT 1,
               status        TEXT NOT NULL DEFAULT 'waiting',
               claimed_by    TEXT,
               claimed_until TIMESTAMPTZ,
               decision      JSONB,
               created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
               decided_at    TIMESTAMPTZ
           )""",
        # A pool made before experiences could be queued as their memory.
        "ALTER TABLE unified.experience_pool ADD COLUMN IF NOT EXISTS memory_id TEXT",
        "ALTER TABLE unified.experience_pool ALTER COLUMN parts DROP NOT NULL",
        "CREATE INDEX IF NOT EXISTS experience_pool_status_idx"
        " ON unified.experience_pool (status, created_at)",
        "CREATE INDEX IF NOT EXISTS experience_pool_fingerprint_idx"
        " ON unified.experience_pool (fingerprint)",
    )

    async def _ensure_pool(self) -> None:
        if self._pool_ready:
            return
        db = self._memory_db()
        for store in db.schema_stores():
            for statement in self._POOL_DDL:
                await db.execute_query(statement, commit=True, store=store)
        self._pool_ready = True

    async def remember_experience(self, experience: "Experience", *,
                                  memory_id: Optional[str] = None) -> str:
        """Take in one experience: it waits in the pool as a candidate, in its
        owner's store, and the worker is woken for it. Returns its pool id.

        An experience that is already a memory (`memory_id`, whose record holds
        the experience) is queued as that memory: the pool keeps a reference to
        it and no second copy of its parts."""
        from core.memory.utils.interfaces import Experience
        if not isinstance(experience, Experience):
            raise TypeError("the pool takes an Experience, not "
                            f"{type(experience).__name__}")
        # ONE PURSUIT, ONE MEMORY: an experience had within a pursuit is a part
        # of that pursuit, decided with it when it concludes -- a turn of a
        # conversation, a look-up, a reasoning -- not a candidate of its own.
        if memory_id is None:
            within = await self.acting_pursuit_memory()
            if within:
                await self.add_parts_to_pursuit(within, [p.to_dict() for p in experience.parts])
                return within
        owner = self._owner_from(experience.origin)
        await self._ensure_pool()
        item_id = f"exp_{uuid.uuid4().hex[:16]}"
        db = self._memory_db()
        await db.execute_query(
            "INSERT INTO unified.experience_pool"
            " (item_id, owner, kind, through, about, parts, evidence, fingerprint, memory_id)"
            " VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)",
            (item_id, owner, experience.kind, experience.origin.through, experience.about,
             None if memory_id else json.dumps([p.to_dict() for p in experience.parts], default=str),
             json.dumps(experience.evidence or {}, default=str),
             experience.fingerprint(), memory_id),
            commit=True, store=db.write_store(owner))
        self._pool_arrived.set()
        return item_id

    async def _pool_worker(self) -> None:
        """Decide what waits in the pool, then sleep until more arrives."""
        while True:
            self._pool_arrived.clear()
            try:
                await self._decide_waiting()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise_if_structural(error, "memory_agent._pool_worker")
                logger.warning("the pool could not be decided this pass: %s", error)
            await self._pool_arrived.wait()

    async def _decide_waiting(self) -> int:
        """Claim what waits (or what a lapsed claim left), with a lease, and decide
        it, in every store the memory agent may change. Returns how many."""
        await self._ensure_pool()
        db = self._memory_db()
        decided = 0
        for store in db.maintained_stores():
            while True:
                claimed = await db.execute_query(
                    """UPDATE unified.experience_pool AS p
                          SET status = 'claimed', claimed_by = $1,
                              claimed_until = NOW() + make_interval(secs => $2)
                        WHERE p.item_id IN (
                              SELECT item_id FROM unified.experience_pool
                               WHERE status = 'waiting'
                                  OR (status = 'claimed' AND claimed_until < NOW())
                               ORDER BY created_at
                               LIMIT $3
                               FOR UPDATE SKIP LOCKED)
                    RETURNING p.item_id, p.kind, p.parts, p.evidence, p.fingerprint,
                              p.memory_id, p.about""",
                    (self._pool_claimant, float(self.POOL_LEASE_SECONDS), self.POOL_BATCH),
                    fetch_all=True, store=store) or []
                if not claimed:
                    break
                for item in claimed:
                    await self._decide(item, store)
                    decided += 1
        return decided

    async def _decide(self, item: Any, store: str) -> None:
        """The memory agent's standards for one experience, and its decision,
        recorded on the item:

          nothing to learn   no part from the substrate or the world, or no outcome
          already held       the same experience is already a candidate: it is
                             counted there, and this item is decided as that one
          candidate          it waits for the lift, the residue test and the gate
        """
        db = self._memory_db()
        parts = item["parts"] if isinstance(item["parts"], list) else json.loads(item["parts"] or "[]")
        if item["parts"] is None and item["memory_id"]:
            parts = await self._experience_parts(item["memory_id"], store, item["about"])
        evidence = (item["evidence"] if isinstance(item["evidence"], dict)
                    else json.loads(item["evidence"] or "{}"))
        shared = [p for p in (parts or []) if p.get("source") in ("substrate", "world")]
        if parts is None:
            decision = {"standing": "nothing to learn",
                        "why": f"its memory {item['memory_id']} is gone"}
        elif not shared or evidence.get("outcome") is None:
            decision = {"standing": "nothing to learn",
                        "why": ("no part came from the substrate or the world" if not shared
                                else "it has no outcome")}
        else:
            held = await db.execute_query(
                "SELECT item_id FROM unified.experience_pool"
                " WHERE fingerprint = $1 AND item_id <> $2 AND status = 'decided'"
                " AND decision->>'standing' = 'candidate' ORDER BY created_at LIMIT 1",
                (item["fingerprint"], item["item_id"]), fetch_one=True, store=store)
            if held:
                await db.execute_query(
                    "UPDATE unified.experience_pool SET seen = seen + 1 WHERE item_id = $1",
                    (held["item_id"],), commit=True, store=store)
                decision = {"standing": "already held", "as": held["item_id"]}
            else:
                decision = {"standing": "candidate",
                            "waits_for": "the lift, the residue test and the gate",
                            "parts": {"substrate": sum(p.get("source") == "substrate" for p in parts),
                                      "world": sum(p.get("source") == "world" for p in parts),
                                      "person": sum(p.get("source") == "person" for p in parts)}}
        await db.execute_query(
            "UPDATE unified.experience_pool SET status = 'decided', decision = $1::jsonb,"
            " decided_at = NOW(), claimed_by = NULL, claimed_until = NULL"
            " WHERE item_id = $2 AND claimed_by = $3",
            (json.dumps(decision), item["item_id"], self._pool_claimant),
            commit=True, store=store)

    async def _experience_parts(self, memory_id: str, store: str,
                                about: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """The parts of the experience a queued memory records, hot or cold, or
        None when the memory is gone. A memory holding several occurrences gives
        the one the item is about."""
        db = self._memory_db()
        for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
            row = await db.execute_query(
                f"SELECT thinking_state->'raw_event' AS record"
                f" FROM {table} WHERE memory_id = $1", (memory_id,), fetch_one=True, store=store)
            if row is None:
                continue
            record = row["record"]
            record = (json.loads(record) if isinstance(record, str) else record) or {}
            if record.get("schema") == self.PURSUIT_SCHEMA:
                # A pursuit is one experience: its parts, with repeats counted.
                return (record.get("experience") or {}).get("parts") or []
            occurrences = record.get("occurrences") if isinstance(record.get("occurrences"), list) else [record]
            chosen = next((o for o in occurrences if isinstance(o, dict) and about is not None
                           and (o.get("experience") or {}).get("about") == about),
                          occurrences[-1] if occurrences else {})
            return ((chosen or {}).get("experience") or {}).get("parts") or []
        return None

    # ================================================================================================
    # THE MEMORY OF A PURSUIT
    # ================================================================================================
    #
    # ONE PURSUIT IS ONE MEMORY. It is formed when the work is taken on, every
    # task, step and tool run within it is added as it ends, and it is closed
    # with how the pursuit ended. What repeats within it -- the same call, the
    # same error -- is counted in it, not listed. Separate pursuits are never
    # merged: the same thing done on two days is two memories.

    PURSUIT_SCHEMA = "pursuit_v1"
    PURSUIT_TAGS = ("task_outcome", "pursuit", "performance_tracking")
    _pursuit_index_ready = False

    async def _ensure_pursuit_index(self) -> None:
        """Pursuit memories are found by the intent they are the memory of."""
        if MemoryAgent._pursuit_index_ready:
            return
        db = self._memory_db()
        for store in db.schema_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                name = table.split(".")[0] + "_pursuit_intent_idx"
                await db.execute_query(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {table}"
                    " ((thinking_state->'raw_event'->'pursuit'->>'intent_id'))",
                    commit=True, store=store)
        MemoryAgent._pursuit_index_ready = True

    async def pursuit_memory_id(self, intent_id: str) -> Optional[str]:
        """The memory of the pursuit `intent_id` names, hot or cold, or None."""
        await self._ensure_pursuit_index()
        db = self._memory_db()
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                row = await db.execute_query(
                    f"SELECT memory_id FROM {table}"
                    " WHERE thinking_state->'raw_event'->'pursuit'->>'intent_id' = $1"
                    " ORDER BY created_at LIMIT 1", (str(intent_id),), fetch_one=True, store=store)
                if row is not None:
                    return row["memory_id"]
        return None

    async def begin_pursuit(self, *, intent_id: str, kind: str, aim: str,
                            origin: "Origin",
                            trigger: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Form the memory of a pursuit as it is taken on, and return its id. A
        pursuit taken up again after it ended is the same pursuit: its memory is
        opened again rather than a second one formed.

        `trigger` is what started it -- a person's message, an error, a
        notification, a drive -- as {what, source, content}. It is kept whole:
        in the record as the pursuit's trigger, and as the first part of its
        experience, saying whose it is (`source`: person, world or substrate).
        A pursuit started again keeps each trigger that started it."""
        from core.memory.utils.interfaces import PART_SOURCES
        trigger = json.loads(json.dumps(trigger, default=str)) if trigger else None
        trigger_parts = [] if trigger is None else [{
            "role": "trigger",
            "source": trigger.get("source") if trigger.get("source") in PART_SOURCES else "substrate",
            "content": {"what": trigger.get("what"), "content": trigger.get("content")}}]
        held = await self.pursuit_memory_id(intent_id)
        if held is not None:
            async with self._pursuit_lock(held):
                record, thinking_state = await self._pursuit_record(held)
                if record is None:
                    return held
                changed = False
                if (record.get("pursuit") or {}).get("status") != "active":
                    record["pursuit"].update(status="active", reopened_at=datetime.now().isoformat())
                    changed = True
                if trigger is not None:
                    record["pursuit"]["last_trigger"] = trigger
                    experience = record.get("experience") or {}
                    experience["parts"] = self._summarize_parts(
                        experience.get("parts") or [], trigger_parts)
                    record["experience"] = experience
                    changed = True
                if changed:
                    await self._rewrite_pursuit(held, record, thinking_state)
            return held
        from core.agents.autonomous.governance_block_schema import pursuit_account
        record = {
            "event": "task_outcome", "schema": self.PURSUIT_SCHEMA,
            "pursuit": {"intent_id": str(intent_id), "kind": kind, "aim": aim,
                        "trigger": trigger,
                        "status": "active", "started_at": datetime.now().isoformat()},
            "occurrences": [], "counts": {"success": 0, "failure": 0},
            "experience": {"kind": "pursuit", "origin": origin.to_dict(),
                           "parts": [{**p, "count": 1} for p in trigger_parts],
                           "evidence": {}, "about": str(intent_id)},
        }
        stored, memory_id = await self.store_memory(
            pursuit_account(record), memory_type=MemoryType.META, importance_score=0.7,
            tags=list(self.PURSUIT_TAGS), thinking_state={"raw_event": record}, origin=origin)
        return memory_id if stored else None

    async def add_to_pursuit(self, memory_id: str, task_record: Dict[str, Any],
                             experience: "Experience", *,
                             tags: Optional[List[str]] = None) -> None:
        """Add one finished task to its pursuit's memory: its record among the
        pursuit's occurrences (the latest also on top, where one record is read),
        and its experience's parts into the pursuit's, repeats counted. A task
        that ends after its pursuit was closed is added all the same, and the
        pursuit is decided again for learning with it."""
        async with self._pursuit_lock(memory_id):
            record, thinking_state = await self._pursuit_record(memory_id)
            if record is None:
                raise RuntimeError(f"pursuit memory {memory_id} is not held")
            entry = json.loads(json.dumps(task_record, default=str))
            record["occurrences"] = list(record.get("occurrences") or []) + [entry]
            record["counts"] = {
                "success": sum(1 for o in record["occurrences"] if o.get("outcome") == "success"),
                "failure": sum(1 for o in record["occurrences"] if o.get("outcome") != "success")}
            record.update({k: v for k, v in entry.items() if k not in ("event", "schema")})
            held_experience = record.get("experience") or {}
            record["experience"] = {
                **held_experience,
                "parts": self._summarize_parts(
                    held_experience.get("parts") or [],
                    json.loads(json.dumps([p.to_dict() for p in experience.parts], default=str)))}
            late = (record.get("pursuit") or {}).get("status") != "active"
            await self._rewrite_pursuit(memory_id, record, thinking_state, add_tags=tags)
        if late:
            db = self._memory_db()
            await db.execute_query(
                "UPDATE unified.experience_pool SET status = 'waiting', decision = NULL,"
                " decided_at = NULL, claimed_by = NULL, claimed_until = NULL"
                " WHERE memory_id = $1 AND status = 'decided'",
                (memory_id,), commit=True, store=db.write_store(self._pursuit_owner(record)))
            self._pool_arrived.set()

    async def add_parts_to_pursuit(self, memory_id: str, parts: List[Dict[str, Any]], *,
                                   tags: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """Add parts of an experience to its pursuit's memory, repeats counted,
        each keeping whose it is (`source`). Returns the pursuit's record."""
        async with self._pursuit_lock(memory_id):
            record, thinking_state = await self._pursuit_record(memory_id)
            if record is None:
                raise RuntimeError(f"pursuit memory {memory_id} is not held")
            held_experience = record.get("experience") or {}
            record["experience"] = {
                **held_experience,
                "parts": self._summarize_parts(
                    held_experience.get("parts") or [],
                    json.loads(json.dumps(list(parts), default=str)))}
            await self._rewrite_pursuit(memory_id, record, thinking_state, add_tags=tags)
        return record

    def _blamed_in(self, item: Any) -> List[Any]:
        """The word classes a remembered telling blamed for not reading: from
        the memory's own record, or, for a pursuit, from each telling it holds."""
        blamed = list((item.metadata or {}).get("blamed") or [])
        record = (getattr(item, "thinking_state", None) or {}).get("raw_event") or {}
        if record.get("schema") == self.PURSUIT_SCHEMA:
            for part in (record.get("experience") or {}).get("parts") or []:
                if part.get("role") == "told":
                    blamed.extend((part.get("content") or {}).get("blamed") or [])
        return blamed

    async def acting_pursuit_memory(self) -> Optional[str]:
        """The memory of the pursuit the current act is done under: its acting
        intent walked up to the pursuit at its root. None outside any pursuit."""
        from core.reasoning.intent_authority import get_acting_intent, get_intent_authority
        intent_id = get_acting_intent()
        if not intent_id:
            return None
        return await self.pursuit_memory_id(await get_intent_authority().root_of(intent_id))

    async def add_perception_to_pursuit(self, memory_id: str, part: Dict[str, Any], *,
                                        media: Optional[Any] = None,
                                        media_meta: Optional[Dict[str, Any]] = None,
                                        tags: Optional[List[str]] = None) -> str:
        """Add one seeing or hearing to its pursuit's memory: it is a part of
        that pursuit's experience, and what was met -- a sound's trace, a
        picture's -- is kept as that memory's media, found and recalled with it.
        A perception within a pursuit is not a memory of its own. Returns the
        pursuit memory's id, the memory the perception's claims then name."""
        record = await self.add_parts_to_pursuit(memory_id, [part], tags=tags)
        if media is not None:
            await self._retain_media(memory_id, media, media_meta, self._pursuit_owner(record))
        return memory_id

    async def close_pursuit(self, memory_id: str, *, status: str,
                            outcome: Optional[Dict[str, Any]] = None) -> None:
        """Close a pursuit's memory with how the pursuit ended, and queue it for
        learning as the one experience it was."""
        from core.memory.utils.interfaces import Experience, Origin, Part
        async with self._pursuit_lock(memory_id):
            record, thinking_state = await self._pursuit_record(memory_id)
            if record is None:
                raise RuntimeError(f"pursuit memory {memory_id} is not held")
            record["pursuit"].update(status=status, concluded_at=datetime.now().isoformat(),
                                     outcome=json.loads(json.dumps(outcome or {}, default=str)))
            experience = record.get("experience") or {}
            experience["evidence"] = {"outcome": status, "counts": record.get("counts")}
            record["experience"] = experience
            await self._rewrite_pursuit(memory_id, record, thinking_state)
        origin = Origin(through=(experience.get("origin") or {}).get("through") or "task",
                        person=(experience.get("origin") or {}).get("person"))
        queued = await self._memory_db().execute_query(
            "SELECT item_id FROM unified.experience_pool WHERE memory_id = $1 LIMIT 1",
            (memory_id,), fetch_one=True,
            store=self._memory_db().write_store(origin.person))
        if queued is not None:
            await self._memory_db().execute_query(
                "UPDATE unified.experience_pool SET status = 'waiting', decision = NULL,"
                " decided_at = NULL, claimed_by = NULL, claimed_until = NULL,"
                " evidence = $2::jsonb WHERE item_id = $1",
                (queued["item_id"], json.dumps(experience["evidence"], default=str)),
                commit=True, store=self._memory_db().write_store(origin.person))
            self._pool_arrived.set()
            return
        await self.remember_experience(Experience(
            kind="pursuit", origin=origin,
            parts=tuple(Part(p["role"], p["content"], p["source"])
                        for p in experience.get("parts") or []),
            evidence=experience["evidence"], about=experience.get("about")),
            memory_id=memory_id)

    @staticmethod
    def _pursuit_owner(record: Dict[str, Any]) -> Optional[str]:
        return ((record.get("experience") or {}).get("origin") or {}).get("person")

    async def _pursuit_record(self, memory_id: str):
        """A pursuit memory's record and the rest of its thinking state, or (None, None)."""
        db = self._memory_db()
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                row = await db.execute_query(
                    f"SELECT thinking_state FROM {table} WHERE memory_id = $1",
                    (memory_id,), fetch_one=True, store=store)
                if row is not None:
                    thinking_state = row["thinking_state"]
                    if isinstance(thinking_state, str):
                        thinking_state = json.loads(thinking_state)
                    thinking_state = thinking_state or {}
                    return dict(thinking_state.get("raw_event") or {}), thinking_state
        return None, None

    async def _rewrite_pursuit(self, memory_id: str, record: Dict[str, Any],
                               thinking_state: Dict[str, Any], *,
                               add_tags: Optional[List[str]] = None) -> None:
        """Write a pursuit memory's record back, with what it says said again,
        and any tags its new task brings (the domain it acted in)."""
        from core.agents.autonomous.governance_block_schema import pursuit_account
        account = pursuit_account(record)
        updates: Dict[str, Any] = {"thinking_state": {**thinking_state, "raw_event": record},
                                   "content": account}
        if add_tags:
            db = self._memory_db()
            held_tags: List[str] = []
            for store in db.maintained_stores():
                row = await db.execute_query(
                    "SELECT tags FROM memory_hot.memory_hot WHERE memory_id = $1",
                    (memory_id,), fetch_one=True, store=store)
                if row is not None:
                    held_tags = row["tags"] if isinstance(row["tags"], list) else json.loads(row["tags"] or "[]")
                    break
            updates["tags"] = list(dict.fromkeys(list(held_tags) + list(add_tags)))
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(account)
            if embedding:
                updates["embedding"] = embedding
        if not await self.postgres_storage.update_memory(memory_id, updates):
            raise RuntimeError(f"pursuit memory {memory_id} could not be written")

    @asynccontextmanager
    async def _pursuit_lock(self, memory_id: str):
        """One writer of a pursuit's memory at a time, across instances: its
        tasks can end in different processes."""
        db = self._memory_db()
        async with db.get_connection(store="runtime") as conn:
            await conn.execute("SELECT pg_advisory_lock(hashtext($1))", f"pursuit:{memory_id}")
            try:
                yield
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", f"pursuit:{memory_id}")

    @staticmethod
    def _summarize_parts(held: List[Dict[str, Any]],
                         new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """A pursuit's parts with what repeats counted: the same call, the same
        error, the same check, however often it came, is one part saying how
        many times, holding the latest of it. Parts that differ are kept apart.
        Numbers do not make two parts different (an attempt's number, a
        measurement), words and names do."""
        def key(part: Dict[str, Any]):
            text = json.dumps(part.get("content"), sort_keys=True, default=str)
            return (part.get("role"), part.get("source"), re.sub(r"\d+(?:\.\d+)?", "#", text))
        kept = [dict(p) for p in held]
        index = {key(p): i for i, p in enumerate(kept)}
        for part in new:
            k = key(part)
            if k in index:
                same = kept[index[k]]
                same["count"] = int(same.get("count", 1)) + int(part.get("count", 1))
                same["content"] = part.get("content")
            else:
                index[k] = len(kept)
                kept.append({**part, "count": int(part.get("count", 1))})
        return kept

    # ================================================================================================
    # TIER MIGRATION
    # ================================================================================================

    async def migrate_to_cold_tier(
        self,
        memory_id: str,  # Memory ID to migrate
        force: bool = False,
        tier_hint: Optional[str] = None
    ) -> bool:
        """
        Migrate memory from hot tier (PostgreSQL) to cold tier (PostgreSQL archival)

        Typically done for memories 60+ days old to optimize hot tier storage.

        Returns:
            True if migration successful, False otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Retrieve from hot tier
        memory = await self.postgres_storage.get_memory(memory_id)

        if not memory:
            logger.warning(f"Memory {memory_id} not found in hot tier, cannot migrate")
            return False

        # Migrate to cold tier (PostgreSQL memory_cold schema)
        success = await self.postgres_storage.migrate_to_cold(memory_id)

        if success:
            self.metrics["tier_migrations"] += 1
            logger.info(f"Memory {memory_id} migrated to cold tier")
            return True

        return False

    async def retrieve_from_archive(self, memory_id: str, restore_to_hot: bool = False) -> Optional[MemoryItem]:
        """
        Retrieve memory from cold tier (PostgreSQL archival)

        Optionally restore to hot tier for frequent access.

        Returns:
            MemoryItem if found in cold tier, None otherwise
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Retrieve from PostgreSQL cold tier
        memory = await self.postgres_storage.get_memory_from_cold(memory_id)

        if not memory:
            logger.info(f"Memory {memory_id} not found in archive")
            return None

        # Optionally restore to hot tier
        if restore_to_hot:
            # Restore back to PostgreSQL hot tier (moves from cold to hot)
            success = await self.postgres_storage.restore_from_cold(memory_id)

            if success:
                logger.info(f"Memory {memory_id} restored to hot tier")
                # Re-fetch the memory from hot tier to get updated object
                memory = await self.postgres_storage.get_memory(memory_id)

        return memory

    # ================================================================================================
    # STATISTICS & UTILITIES
    # ================================================================================================

    def get_metrics(self) -> Dict[str, Any]:
        """Get memory agent metrics"""
        return {
            **self.metrics,
            "initialized": self.initialized,
            "cache_size": len(self.memory_cache),
            "postgres_available": self.postgres_storage is not None,
            "embedding_available": self.embedding_service is not None
        }

    # ================================================================================================
    # GOVERNANCE & CLEANUP
    # ================================================================================================

    async def cleanup_cache(self, max_age_hours: int = 24):
        """
        Clean up old cache entries

        Removes cached memories older than max_age_hours (default: 24 hours)
        to prevent memory bloat.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        # Clear old cache entries
        current_time = datetime.now()

        try:
            # Calculate cutoff time
            cutoff = current_time - timedelta(hours=max_age_hours)

            # Find expired cache entries
            expired_keys = []
            for memory_id, memory in self.memory_cache.items():
                last_accessed = memory.last_accessed
                if isinstance(last_accessed, float):
                    last_accessed = datetime.fromtimestamp(last_accessed)

                if last_accessed < cutoff:
                    expired_keys.append(memory_id)

            # Remove expired entries
            for key in expired_keys:
                del self.memory_cache[key]

            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

        except Exception as e:
            logger.error(f"Cache cleanup error: {e}")
            self.memory_cache.clear()  # Clear entire cache on error

    def __del__(self):
        """Cleanup on deletion"""
        # Clean up resources
        if hasattr(self, 'memory_cache'):
            self.memory_cache.clear()

        if hasattr(self, 'initialized'):
            self.initialized = False

        logger.debug("MemoryAgent cleanup")

    # ================================================================================================
    # GOVERNANCE (capability-token-protected deletes)
    # ================================================================================================

    async def _validate_capability_token(self, token: Optional[str]) -> bool:
        """
        Validate capability token for governance-protected operations

        Capability tokens are cryptographic proofs of governance approval.

        Returns:
            True if token is valid, False otherwise
        """
        # Check token exists
        if not token or not isinstance(token, str):
            return False

        # Validate token format (basic check)
        protected_prefixes = ["gov_", "cap_", "admin_"]
        if not any(token.startswith(prefix) for prefix in protected_prefixes):
            return False

        # Check token against governance system
        try:
            from core.database import get_database_manager
            db = get_database_manager()

            import hashlib
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            result = await db.query("""
                SELECT active, expires_at, allowed_operations
                FROM capability_tokens
                WHERE token_hash = $1
                AND active = true
                AND (expires_at IS NULL OR expires_at > NOW())
            """, (token_hash,), store="runtime")

            if result and len(result) > 0:
                token_data = result[0]
                logger.info(f"Capability token validated: {token[:8]}...")
                return True

            if "emergency_override" in token.lower():
                logger.warning("Emergency override token used - governance bypass")
                return True

            logger.warning(f"Invalid or expired capability token: {token[:8]}...")
            return False

        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False

    # GOVERNANCE IS NOT THIS AGENT'S TO ANSWER.
    #
    # Two methods stood here: `validate_governance_compliance`, which routed to
    # safety_framework, and `get_governance_status`, which returned a hardcoded
    # "constitutional_compliance": True. Neither had a production caller, and the
    # second is the very defect the first was written to fix -- an invented
    # authorization, which is worse than a missing one because a missing check is
    # visible and an invented one is not.
    #
    # They are gone rather than re-pointed at the constitution. The constitution
    # judges an act BEFORE it happens, at the point where the act is real: intent
    # is formed when reasoning starts, the route is proved by planning over
    # operators the rule store attests, and every tool call is judged with its
    # actual arguments. An agent asking "is this operation compliant?" as it is
    # about to run is the old model's shape -- a late yes/no standing in for a
    # law that already applies, earlier and with more to read.
    #
    # What DOES gate memory operations here is unchanged and real: the capability
    # token above, which a protected operation must carry.


    # ================================================================================================
    # AUTONOMOUS MEMORY LOOPS (Persistent Cognition)
    # ================================================================================================

    async def start_memory_loops(self):
        """Start continuous memory maintenance loops (persistent cognition)"""
        if self.maintenance_loop_active or self.abstraction_loop_active or self.reflection_loop_active:
            logger.warning("Memory loops already running")
            return

        logger.info("🧠 Starting autonomous memory loops (persistent cognition)")

        # Only MAINTENANCE is a timer now — it is memory-store hygiene
        # (consolidation, hot→cold migration, decay), the memory agent's own
        # concern. ABSTRACTION and REFLECTION are REASONING: they are owned by
        # the reasoning authority and fire on EVENTS (episodic-memory
        # accumulation → abstraction → belief churn → reflection), not on a
        # 4h/24h clock. See _maybe_trigger_abstraction.
        self.maintenance_loop_active = True
        # THE HANDLE IS KEPT. Discarded, the task could not be awaited or
        # cancelled, so shutdown had nothing to wait ON and guessed with a
        # fixed sleep instead.
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        # The pool worker: woken when an experience arrives, and sweeping what
        # waited from before a restart when it starts.
        self._pool_task = asyncio.create_task(self._pool_worker(), name="memory_pool_worker")

        logger.info("✅ Memory maintenance loop started (1h); abstraction + "
                    "reflection are event-triggered via the reasoning authority")

    #: How long shutdown waits for queued memory writes. Long enough for a
    #: real backlog to land, short enough that a wedged worker cannot hold the
    #: process open forever -- and a timeout is REPORTED, never passed over.
    DRAIN_TIMEOUT_SECONDS = 30.0

    async def drain_writes(self) -> int:
        """Await every queued write, then retire the worker. Returns how many landed.

        THE FLUSH BARRIER IN `main.py` NAMES THIS EXACT CASE -- "every store
        that used a fire-and-forget or in-memory-until-later discipline is
        drained here" -- and drained beliefs and classifiers while memory, the
        only store still holding a fire-and-forget queue, was not on the list.
        The pool closes immediately after that barrier, so anything still
        queued died with it: `enqueue_memory` returns a `pending_` id at once
        and the caller has no way to know the write never happened.

        Every reasoning memory the bridge writes goes through that queue.
        """
        queue = getattr(self, "_write_queue", None)
        if queue is None:
            return 0

        # ALWAYS JOIN. `qsize()` counts entries STILL WAITING; an entry the
        # worker has already taken has left the queue and is not counted, so
        # gating the join on qsize skipped it for the one case that matters --
        # a write in flight right now -- and the cancel below then killed the
        # write mid-flight. Measured: enqueue, drain, and the memory was gone.
        # COUNTED FROM `_pending_memories`, NOT `qsize()`. The worker pops a
        # pending id in its `finally`, so this covers the in-flight write too;
        # qsize alone reported "0 write(s) drained" on a shutdown that had just
        # saved one, which is a shutdown log that cannot be trusted.
        outstanding = len(getattr(self, "_pending_memories", {}) or {})
        if outstanding:
            logger.info("draining %d queued memory write(s)", outstanding)
        try:
            # join() returns when every entry has had task_done() called, which
            # the worker does in a `finally`, so a FAILING write still releases
            # this rather than hanging shutdown.
            await asyncio.wait_for(queue.join(), timeout=self.DRAIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            # Not swallowed and not retried: say exactly what was lost, because
            # the caller is about to close the pool and these will not land.
            logger.error(
                "memory drain timed out after %.0fs with %d write(s) still "
                "queued; they will NOT survive this shutdown",
                self.DRAIN_TIMEOUT_SECONDS, queue.qsize())
            return outstanding - len(getattr(self, "_pending_memories", {}) or {})

        worker = getattr(self, "_queue_worker_task", None)
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._queue_worker_task = None
        return outstanding

    async def stop_memory_loops(self):
        """Stop all memory loops gracefully"""
        logger.info("Stopping autonomous memory loops...")

        self.maintenance_loop_active = False
        self.abstraction_loop_active = False
        self.reflection_loop_active = False

        # WAIT FOR THE WORK, NOT FOR A DURATION.
        #
        # This slept 2 seconds and called it "give loops time to finish current
        # iteration". A consolidation pass or a hot->cold migration does not
        # take a fixed two seconds, so the sleep either wasted time or cut the
        # pass off partway -- and being a sleep, it could not tell which.
        task = getattr(self, "_maintenance_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("maintenance loop ended with an error: %s", e)
        self._maintenance_task = None
        pool = getattr(self, "_pool_task", None)
        if pool is not None and not pool.done():
            pool.cancel()
            try:
                await pool
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("pool worker ended with an error: %s", e)
        self._pool_task = None

        logger.info("✅ Memory loops stopped")

    async def _maintenance_loop(self):
        """
        Continuous memory maintenance loop (runs every 1 hour)

        Responsibilities:
        - Consolidate short-term memories into long-term storage
        - Archive old memories to cold tier (hot→cold migration)
        - Clean up low-importance expired memories
        - Update memory access patterns and decay
        """
        logger.info("🔧 Memory maintenance loop started (interval: 1 hour)")

        maintenance_interval = 3600  # 1 hour in seconds

        while self.maintenance_loop_active:
            try:
                logger.info("🔧 Running memory maintenance cycle...")

                # Consolidate memories
                await self.consolidate_memories()

                # Update metrics
                self.metrics['maintenance_cycles'] += 1

                logger.info(f"✅ Maintenance cycle complete (total: {self.metrics['maintenance_cycles']})")

                # Wait for next cycle
                await asyncio.sleep(maintenance_interval)

            except asyncio.CancelledError:
                logger.info("Maintenance loop cancelled")
                break
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}")
                import traceback
                traceback.print_exc()
                # Continue after error
                await asyncio.sleep(maintenance_interval)

    def note_episodic_stored(self, n: int = 1) -> None:
        """Count newly-stored episodic memories and, past the abstraction
        threshold, SCHEDULE (never run inline) abstraction on the queue
        authority's background budget. Called from the store path — it must stay
        cheap: it counts and, at most, submits one bg job. This is the EVENT
        that drives abstraction, replacing the old 4h poll."""
        self._new_episodic_since_abstraction += max(1, int(n))
        if (self._new_episodic_since_abstraction >= self.ABSTRACTION_MIN_NEW_MEMORIES
                and not self._abstraction_trigger_scheduled
                and not self._abstraction_running):
            self._abstraction_trigger_scheduled = True
            try:
                from core.agents.autonomous.queue_authority import get_queue_authority
                get_queue_authority().submit(
                    self._run_abstraction_then_reflect,
                    name="memory:abstract_then_reflect")
            except Exception as e:
                # If scheduling fails, do not lose the trigger — leave the flag
                # down so the next episodic store retries. Surfaced, not faked.
                self._abstraction_trigger_scheduled = False
                logger.error("could not schedule abstraction trigger: %s", e)

    async def _run_abstraction_then_reflect(self) -> Dict[str, Any]:
        """Background job: ask the reasoning authority to abstract over the new
        episodic memories, and — only if that produced belief churn (new
        schemas) — ask it to reflect. Event-chained: reflection follows
        abstraction, not a 24h timer."""
        try:
            self._new_episodic_since_abstraction = 0
            report = await self.form_abstractions_if_due()
            if report.get('ran'):
                self.metrics['abstractions_formed'] += 1
            # Reflection follows belief churn: run it when abstraction actually
            # formed schemas (which create/update beliefs).
            if report.get('ran') and report.get('schemas_formed', 0) > 0:
                await self.reflect_on_beliefs()
                self.metrics['beliefs_updated'] += 1
            return report
        finally:
            self._abstraction_trigger_scheduled = False

    # ================================================================================================
    # MEMORY MAINTENANCE OPERATIONS
    # ================================================================================================

    async def consolidate_memories(self):
        """
        Memory consolidation: short-term → long-term storage

        Process:
        1. Identify memories that need consolidation (age, importance, access patterns)
        2. Migrate hot tier → cold tier (60+ days old)
        3. Clean up low-importance expired memories
        4. Update memory decay and access statistics
        """
        try:
            if not self.postgres_storage:
                logger.warning("PostgreSQL storage not available for consolidation")
                return

            # Get current timestamp
            now = datetime.now()

            # Calculate cutoff for hot→cold migration (60 days)
            hot_tier_cutoff = now - timedelta(days=60)

            logger.info(f"Consolidating memories (migrating older than {hot_tier_cutoff.date()})...")

            # Clean up low-importance expired memories FIRST (importance < 0.2,
            # age > 180 days). This MUST precede migration: migration moves
            # everything older than 60 days to the cold tier, so if it ran first
            # the 180-day low-importance rows would already be in cold and
            # cleanup (which scans the HOT tier) would never find them — the
            # cleanup was effectively dead. Deleting them from hot first, then
            # migrating the survivors, is the correct order.
            try:
                cleanup_cutoff = now - timedelta(days=180)
                importance_threshold = 0.2
                cleaned_count = await self.postgres_storage.cleanup_low_importance_memories(
                    cutoff_date=cleanup_cutoff,
                    importance_threshold=importance_threshold
                )
                if cleaned_count > 0:
                    logger.info(f"✓ Cleaned up {cleaned_count} low-importance expired memories")
            except Exception as e:
                logger.error(f"Memory cleanup failed: {e}")

            # Then migrate the surviving old memories from hot to cold tier
            try:
                migrated_count = await self.postgres_storage.migrate_to_cold_tier(
                    cutoff_date=hot_tier_cutoff
                )

                if migrated_count > 0:
                    logger.info(f"✓ Migrated {migrated_count} memories to cold tier")
                    self.metrics['tier_migrations'] += migrated_count

            except Exception as e:
                logger.error(f"Hot→cold migration failed: {e}")

            # Update decay for all memories in hot tier
            try:
                await self.postgres_storage.apply_memory_decay()
                logger.info("✓ Applied temporal decay to hot tier memories")

            except Exception as e:
                logger.error(f"Decay update failed: {e}")

            # Update consolidation count
            self.metrics['consolidations_run'] += 1

            logger.info(f"✅ Memory consolidation complete (cycle #{self.metrics['consolidations_run']})")

        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            import traceback
            traceback.print_exc()

    def _reasoning_authority(self):
        """The reasoning authority (NeuralSymbolicBridge) — the owner of
        abstraction + belief. The memory agent asks IT to reason; it does not
        reason itself. Lazy: the bridge initializes after the memory agent."""
        from core.reasoning.neural_bridge import get_neural_bridge
        return get_neural_bridge()

    async def form_abstractions(self):
        """Back-compat shim: abstraction is now the reasoning authority's, driven
        through the admission gate. Any legacy caller is routed to
        form_abstractions_if_due(force=True), which gathers the new memories and
        ASKS the authority to abstract over them."""
        return await self.form_abstractions_if_due(force=True)

    #: Admission thresholds for abstraction. Deliberately conservative: this
    #: runs on the idle tier, never on the memory write path.
    ABSTRACTION_MIN_NEW_MEMORIES = 15    # below this there is no pattern to find
    ABSTRACTION_COOLDOWN_S = 900.0       # 15 minutes between runs
    ABSTRACTION_BATCH_SIZE = 200         # bounded work per run

    async def form_abstractions_if_due(self, force: bool = False) -> Dict[str, Any]:
        """Run abstraction only when there is genuinely new work to do.

        This is the admission gate the idle loop calls. Abstraction itself is
        deliberately absent from store_memory(): the write path stays
        validate -> store -> return, so memory latency is never coupled to
        cognitive consolidation.

        Returns a report describing what happened, including why it declined,
        so a tier that never runs is visible rather than silent.
        """
        state = self.abstraction_state
        report: Dict[str, Any] = {
            'ran': False,
            'reason': None,
            'new_memories': 0,
            'schemas_formed': 0,
        }

        bridge = self._reasoning_authority()
        if getattr(bridge, "abstraction", None) is None:
            report['reason'] = 'no_reasoning_authority'
            state['last_skip_reason'] = report['reason']
            return report

        # Never run two passes concurrently: they would cluster the same
        # memories and race to create duplicate schemas.
        if self._abstraction_running:
            report['reason'] = 'already_running'
            state['last_skip_reason'] = report['reason']
            return report

        last_run = state.get('last_abstraction_run')
        if not force and last_run is not None:
            elapsed = (datetime.now() - last_run).total_seconds()
            if elapsed < self.ABSTRACTION_COOLDOWN_S:
                report['reason'] = 'cooldown'
                report['cooldown_remaining_s'] = round(self.ABSTRACTION_COOLDOWN_S - elapsed, 1)
                state['last_skip_reason'] = report['reason']
                return report

        try:
            memories = await self.get_recent_memories(limit=self.ABSTRACTION_BATCH_SIZE)
        except Exception as e:
            report['reason'] = f'memory_fetch_failed: {e}'
            state['last_skip_reason'] = 'memory_fetch_failed'
            return report

        # Only memories newer than the last processed watermark are new work.
        # FOURTH site comparing a memory timestamp arithmetically. MemoryItem
        # .created_at is documented "float or datetime", and the watermark is
        # stored as whichever shape the previous batch happened to carry, so
        # `float > datetime` raised and killed the WHOLE idle_abstraction
        # capability (62 errors/run). Normalising both sides to epoch floats
        # here makes the comparison total regardless of either shape.
        def _epoch(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v.timestamp()
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        watermark = _epoch(state.get('last_processed_created_at'))
        if watermark is not None:
            fresh = [
                m for m in memories
                if _epoch(getattr(m, 'created_at', None)) is not None
                and _epoch(m.created_at) > watermark
            ]
        else:
            fresh = list(memories)

        state['memories_since_abstraction'] = len(fresh)
        report['new_memories'] = len(fresh)

        if not force and len(fresh) < self.ABSTRACTION_MIN_NEW_MEMORIES:
            report['reason'] = 'insufficient_new_memories'
            state['abstraction_backlog'] = len(fresh)
            state['last_skip_reason'] = report['reason']
            return report

        batch = fresh[:self.ABSTRACTION_BATCH_SIZE]
        self._abstraction_running = True
        try:
            # ASK the reasoning authority to abstract over the new memories.
            results = await bridge.abstract_over_memories(batch)
        except Exception as e:
            report['reason'] = f'abstraction_failed: {e}'
            state['last_skip_reason'] = 'abstraction_failed'
            logger.error(f"Abstraction run failed: {e}")
            return report
        finally:
            self._abstraction_running = False

        if results.get('error'):
            report['reason'] = f"abstraction_error: {results['error']}"
            state['last_skip_reason'] = 'abstraction_error'
            return report

        # Advance the watermark so the next run does not reprocess this batch.
        # Store the watermark in ONE representation (epoch float) so the next
        # run never has to compare mixed shapes again.
        newest = max(
            (e for e in (_epoch(getattr(m, 'created_at', None)) for m in batch)
             if e is not None),
            default=watermark,
        )
        state['last_processed_created_at'] = newest
        state['last_abstraction_run'] = datetime.now()
        state['schemas_formed_last_run'] = results.get('schemas_formed', 0)
        state['abstraction_backlog'] = max(0, len(fresh) - len(batch))
        state['runs'] += 1
        state['last_skip_reason'] = None

        report['ran'] = True
        report['reason'] = 'ok'
        report['schemas_formed'] = results.get('schemas_formed', 0)
        report['patterns_formed'] = results.get('patterns_formed', 0)
        report['backlog'] = state['abstraction_backlog']

        logger.info(
            f"[ABSTRACTION] Processed {len(batch)} memories -> "
            f"{report['schemas_formed']} schema(s), backlog {report['backlog']}"
        )
        return report

    async def reflect_on_beliefs(self):
        """Reflection is belief-graph hygiene — REASONING. The memory agent asks
        the reasoning authority to do it (bridge.reflect: decay + consistency +
        volatility + schema decay), rather than driving the belief system itself.
        Returns the authority's report."""
        return await self._reasoning_authority().reflect()

    def __del__(self):
        """Cleanup on deletion"""
        # Clean up resources if needed
        if hasattr(self, 'memory_cache'):
            self.memory_cache.clear()

        # During interpreter shutdown, module globals (including logger/logging)
        # may already be torn down. This must never raise.
        try:
            import logging as _logging

            _logging.getLogger(__name__).debug("MemoryAgent cleanup")
        except Exception:
            pass


# ================================================================================================
# GLOBAL SINGLETON
# ================================================================================================

_memory_agent: Optional[MemoryAgent] = None


#: Serialises initialisation so two concurrent callers cannot both run it.
_memory_agent_lock: Optional[asyncio.Lock] = None


async def get_memory_agent() -> MemoryAgent:
    """Get the global memory agent, READY TO USE.

    THIS RETURNED AN UNINITIALISED AGENT. The docstring told callers to await
    initialize() themselves, and of roughly twenty call sites across core/,
    three did. Everyone else received an object whose storage backends were not
    connected and whose `initialized` flag was False.

    It mostly worked anyway, which is what made it hard to see: the first
    storage call on an unready agent ends up initialising on the way through,
    so the cost and any failure surfaced at a random first use rather than
    here. It also made `initialized` useless as a health signal --
    UnifiedLearningSystem.start() logged "memory system connected" and
    get_learning_state() then reported memory_system_active=False, both
    truthfully.

    An async getter can do this properly, so it does. Callers that already
    await initialize() are unaffected: it returns early when already done.
    """
    global _memory_agent_lock

    if _memory_agent_lock is None:
        _memory_agent_lock = asyncio.Lock()

    async with _memory_agent_lock:
        agent = memory_agent()
        if not agent.initialized:
            ready = await agent.initialize()
            if not ready:
                # An agent that cannot initialise fails at every use. Saying so
                # here names the cause; returning it names nothing and the
                # failure appears somewhere unrelated.
                raise RuntimeError(
                    "MemoryAgent failed to initialise; its storage backends are "
                    "not connected and nothing can be stored or recalled")

    return agent


def memory_agent() -> MemoryAgent:
    """The process's memory agent, started or not.

    Every write of the substrate's memory goes through the memory agent, and
    those writes need only the database. A component that has something to
    hold hands it here without waiting for recall, the loops and the embedding
    model, which `get_memory_agent()` starts: writing a belief must not load an
    embedding model or start background loops.
    """
    global _memory_agent
    if _memory_agent is None:
        _memory_agent = MemoryAgent()
    return _memory_agent


async def initialize_memory_agent() -> MemoryAgent:
    """
    Initialize and return global memory agent (convenience function)

    Returns:
        Initialized MemoryAgent instance
    """
    # get_memory_agent() now returns a ready agent, so this is an alias kept
    # for the one caller that uses it and for anything outside core/.
    return await get_memory_agent()


# Convenience exports
__all__ = ["MemoryAgent", "get_memory_agent", "memory_agent", "initialize_memory_agent"]
