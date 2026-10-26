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

Integration:
- Single entry point exported from core/memory/__init__.py
- Constitutional constraints enforcement

Author: Lyric System
Version: 8.0
"""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json
import logging
import os
import re
import time

from core.structural_defects import raise_if_structural
import uuid
from typing import Callable, Dict, Any, FrozenSet, List, Optional, Sequence, Set, Tuple, Union
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


def _json_value(value: Any) -> Any:
    """A JSONB value as Python: the driver hands it back as its text."""
    return json.loads(value) if isinstance(value, str) else value


class _KeylessWrites:
    """The memory database, behind a guard that keeps keys out of it: every
    statement's parameters are cleaned of the substrate's keys before they reach
    the store (core.security.secrets). Everything else is the handle itself."""

    __slots__ = ("_db",)

    def __init__(self, db):
        self._db = db

    async def execute_query(self, query, params=None, *args, **kwargs):
        if params is not None:
            from core.security.secrets import get_secrets_authority
            params = get_secrets_authority().redact(params)
        return await self._db.execute_query(query, params, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._db, name)


class MemoryAgent(IMemoryConsolidation):
    """
    Memory Agent - Primary Memory Coordination Interface

    Coordinates hot tier (PostgreSQL 0-60 days), cold tier (PostgreSQL 60+ days),
    and semantic search capabilities for Lyric memory system.

    Architecture:
        - PostgreSQL Hot: Fast hot tier storage for recent memories (memory_hot schema)
        - PostgreSQL Cold: Cold tier archival for historical memories (memory_cold schema)
        - Embeddings: Semantic similarity search across tiers with pgvector

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
        # WORKING MEMORY: what a conversation held not to remember was told, for as long as the process holds it,
        # each person's apart (`not_remembered`). The links, the beliefs, the rules and what they said of themselves,
        # as the store would hold them, read with what the store holds wherever their context is read.
        self._working_relations: Dict[str, Dict[Tuple[str, str, str], Dict[str, Any]]] = {}
        self._working_beliefs: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._working_rules: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._working_speaker: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}
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
        #: What each word is said of (`remember_said`), the same kind of view: `(relation, word, side) ->` the
        #: memory holding it, the words and the things it is said of with how often, and the observations counted.
        #: Rebuilt at every warm; the kinds each relation's words are said of (`_said_spread`) are worked out from it
        #: when first asked and kept until the view changes.
        self._said_view: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        #: The sentences memory holds as analysed, read as memory-based learning reads them (`structure_view`).
        self._structure_view = None
        #: The word groups memory holds (`word_groups`), which the structure view stands beside each word.
        self._word_groups = None
        #: The word forms memory holds (`word_forms`), which the language view reads a word it holds nothing of by.
        self._word_forms = None
        #: The sentences memory holds with their happenings' arguments annotated (`argument_view`), and the lessons'
        #: sentences it holds with their taught meanings, learned from by the composer (`composition_view`).
        self._argument_view = None
        self._composition_view = None
        #: English's grammar as memory reads with it (`grammar_view`): built when first asked after a warm, from the
        #: sentences held analysed, what memory holds of things (`_grammar_links`: each thing's kinds, which are
        #: particular ones, what an adjective's definition is written with) and the sentences held with their taught
        #: meanings (`_grammar_taught`).
        self._grammar_view = None
        self._grammar_links: List[Tuple[str, str, str]] = []
        self._grammar_taught: List[Any] = []
        #: The sentences memory holds as derived by hand in a categorial grammar (`remember_derived`), which the
        #: grammar chooses each word's category by (`grammar.Derived`, `GrammarView.hold_derived`).
        self._grammar_derived: List[Any] = []
        #: What each word names, as the sentences recorded whole name it ((word, class) -> names, counted): "medal"
        #: as a noun names `award decoration` (`name_of`).
        self._record_names: Dict[Tuple[str, str], Counter] = {}
        #: The words held recorded whole (`teaching_sources.WordRecord`), for English's grammar (`grammar_view`).
        self._grammar_words: List[Any] = []
        #: Each taught sentence's memory, what the grammar learned from it, and the rules it was learned under
        #: (`GrammarView.rules`; None: not learned from yet), by the sentence's key (`_composition_memories`,
        #: `keep_grammar_learning`).
        self._grammar_learned: Dict[str, Tuple[str, Optional[List[Any]], Optional[str]]] = {}
        #: What reading taught of how words are used, each sentence's, as memory keeps it (`READ_ENGLISH_TAG`).
        self._read_english: List[Dict[str, Any]] = []
        self._said_spread: Dict[Tuple[str, str], Dict[str, float]] = {}
        #: How many things memory holds connected to each thing a listener has asked about (`_fans`), with how many
        #: things memory holds at all when they were counted: what each thing's associative strength is measured
        #: against (`listening_evidence`). Counted when first asked, and again after every warm.
        self._fan_view: Dict[str, int] = {}
        self._things_held: Optional[int] = None
        #: The memory holding the words heard after each word (`remember_heard`), by the word. What was heard is the
        #: language view's (`PatternInventory.hear`); rebuilt into it at every warm.
        self._heard_memory: Dict[str, str] = {}
        #: The single in-flight warm, so concurrent callers JOIN it instead of
        #: each re-reading the whole store. None when none is running.
        self._word_class_warm_task = None
        #: Set when the loops are being stopped, so a warm cancelled by that stop is not reported as a failed one.
        self._stopping_loops = False

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
        can find it before it lands in postgres. How important it is, is
        decided here (`importance_of`).

        Returns a provisional memory_id (starts with 'pending_').
        """
        if "user_id" in kwargs:
            raise TypeError("enqueue_memory() got an unexpected keyword argument 'user_id': "
                            "say where the memory came from (origin); the memory agent "
                            "decides whose it is")
        if "importance_score" in kwargs:
            raise TypeError("enqueue_memory() got an unexpected keyword argument 'importance_score': "
                            "how important a memory is, the memory agent decides (importance_of)")
        return self._enqueue(content, memory_type,
                             self.importance_of(tags, confidence=confidence_score, source_context=source_context),
                             confidence_score, tags, source_context, origin=origin, **kwargs)

    def _enqueue(self, content: str, memory_type, importance_score: float, confidence_score: float, tags,
                 source_context, *, origin: "Origin", **kwargs) -> str:
        """Put a memory, its importance decided, on the write queue (`enqueue_memory`)."""
        import uuid
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

    #: What a memory of English is kept under (`source_context`): how a sentence was analysed, taught with its meaning,
    #: argued, grouped, formed or derived, and how a reading used its words (`keep_grammar_learning`).
    _LANGUAGE_RECORDS = ("analysed", "taught", "argued", "word_group", "word_forms", "read_english", "derived",
                         "record", "word_record")

    async def _readable_claim(self, content, source_context):
        """The substrate-readable CLAIM a memory asserts, its shape, and its
        facts -- or ``(None, None, ())``.

        A memory is recalled as a PREMISE, so it is useful to the substrate's
        reasoning only when it asserts a claim it can hold as facts. This reads
        that at WRITE time, once, from the recorded conclusion when there is one,
        else the content, with any reasoning-status prefix stripped.

        A claim the substrate MADE carries its facts (`claim_facts`, in the
        reading engine's form); it is the claim as made and is not read again.
        Any other text is read by the one reader (`derived_reader`): it is a
        claim when it reads, as one utterance, to a telling the listener can tell
        is meant (`derived_reader.heard`: memory asked which thing each word
        names, where a word names several). A prose episode, a
        question, a measurement, or anything the substrate was not taught to read
        has no claim, and is left without one rather than dressed up as one: a
        fabricated premise is worse than an absent one, because it is recalled as
        knowledge.

        Returns the clean claim, its ``ClaimShape`` (the polarity the embedding
        vector provably cannot recover, stored beside the memory instead of
        guessed at recall), and the facts it states.
        """
        from core.semantics.claim_shape import shape_of
        from core.semantics.derived_reader import Meaning, MeaningFact, heard, read_text

        if isinstance(source_context, dict) and any(field in source_context for field in self._LANGUAGE_RECORDS):
            # HOW ENGLISH WAS TAUGHT OR READ IS NO CLAIM ABOUT THE WORLD: a sentence analysed, taught with its meaning,
            # its arguments annotated, how a reading used its words. Read as a claim each time one was kept, the
            # treebank's 12,544 took 4.7 hours to teach, every sentence read whole by the grammar (2026-10-24).
            return None, None, ()
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
        if len(utterances) != 1:
            return None, None, ()
        chosen = await heard(utterances[0].readings)
        if chosen is None:
            return None, None, ()
        meaning = chosen.meaning
        if meaning.act != "tell":
            return None, None, ()
        return candidate, shape_of(meaning), meaning.facts

    #: HOW IMPORTANT A MEMORY IS AS IT FORMS, BY WHAT IT IS (`importance_of`): the first of its tags naming its
    #: kind. Importance is how long a memory stays at hand (it fades 1% a day, `decayed_importance`, and recall hands
    #: back only what stands at 0.5 or more: at 0.75 for 41 days, at 0.6 for 18) and whether it may be forgotten
    #: (under 0.2 after 180 days, `consolidate_memories`). Each producer chose its own before (2026-10-23); these
    #: are the values they chose, so nothing recall hands back changed with who decides.
    IMPORTANCE_BY_KIND = {
        # What it was taught and told: how English goes, and the tellings it holds as knowledge.
        "language_pattern": 0.75, "word_class": 0.75, "pronunciation": 0.75, "listening": 0.75,
        "admitted_proposition": 0.75, "told_but_unread": 0.75,
        # What it gathered of how English is used from what it was taught, and a lesson's label.
        "said_of": 0.6, "heard_after": 0.6, "analysed_sentence": 0.6, "word_forms": 0.6, "word_group": 0.6,
        "taught_sentence": 0.6, "argued_sentence": 0.6, "lesson": 0.6,
        # Its ways of working, and how one has gone in a person's work.
        "method": 0.6, "standing": 0.5,
        # What happened in its work: a pursuit, a step that failed, an exchange, a review of what it was taught, a
        # domain it has, an expectation it checked, evidence on a hypothesis and an experiment run on one.
        "task_outcome": 0.7, "task_execution": 0.7, "user_exchange": 0.7, "review": 0.7, "domain": 0.7,
        "expectation": 0.6, "hypothesis": 0.6, "hypothesis_testing": 0.8,
        # What it found checking itself against its own laws.
        "constitution": 1.0,
        # An example it learned from. AS IMPORTANT WRONG AS RIGHT: its producer stored it at its accuracy, so an
        # example it got wrong formed at 0 and was the first thing forgotten (four on lyric_dev, 2026-10-23).
        "learning": 0.5,
    }
    #: What it concluded is as important as it is sure of it: reasoning, a prediction, what two domains have in
    #: common, how well it detects an attack.
    CONCLUSION_KINDS = frozenset({"reasoning", "prediction", "cross_domain", "cross_domain_reasoning",
                                  "security_training", "security_model"})

    def importance_of(self, tags: Optional[Sequence[str]], *, confidence: float = 1.0,
                      source_context: Optional[Dict[str, Any]] = None) -> float:
        """How important a memory is as it forms, decided by the memory agent from what it is: by the first of its
        tags naming a kind (`IMPORTANCE_BY_KIND`); a conclusion as important as it is sure (`CONCLUSION_KINDS`); a goal
        it set itself 0.8, and up to 0.2 more by the reward it expects of it (`reward_potential`); a percept 0.6, and
        0.5 as the account of a perception formed as evidence for what is believed of it (`evidence_id`). Anything
        else forms at 0.5. What a reasoning took to reach is weighed where it is handed over (`take_in_reasoning`)."""
        context = source_context or {}
        for tag in tags or ():
            kind = str(tag).lower()
            if kind in self.IMPORTANCE_BY_KIND:
                return self.IMPORTANCE_BY_KIND[kind]
            if kind in self.CONCLUSION_KINDS:
                return max(0.0, min(1.0, float(confidence or 0.0)))
            if kind == "goal":
                return max(0.0, min(1.0, 0.8 + 0.2 * float(context.get("reward_potential") or 0.0)))
            if kind == "percept":
                return 0.5 if context.get("evidence_id") else 0.6
        return 0.5

    @staticmethod
    def _owner_from(origin: Any) -> Optional[str]:
        """Whose memory a hand-off is, decided from where it came from: a
        person's gift or request is that person's; their work for an
        organization is that organization's (its Work Context, with every memory
        that comes with it); the substrate's own work is its own (None). A
        hand-off that does not say where it came from is refused rather than
        filed as the substrate's own."""
        from core.memory.utils.interfaces import Origin
        if not isinstance(origin, Origin):
            raise TypeError("a hand-off to the memory agent must say where it came "
                            f"from (an Origin), not {type(origin).__name__}")
        return origin.owner

    async def store_memory(
        self,
        content: str,
        memory_type: Optional[MemoryType] = None,
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
        formed_importance: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Store one memory through the one memory pipeline (`_store_memory`).

        HOW IMPORTANT IT IS, THE MEMORY AGENT DECIDES, by what it is (`importance_of`); the caller hands over what
        it is (its tags, its confidence, where it came from), never how important. `formed_importance` is only for
        a memory taken from another store (`releases`), which keeps the importance it formed with there.

        WHOSE IT IS, THE MEMORY AGENT DECIDES, from `origin`: where it came
        from -- which door or work, and the person it came from, or none for
        the substrate's own. The caller says where it came from, never whose it
        is. When each caller named an owner, the ones that forgot filed a
        person's words as the substrate's own knowledge; now a hand-off with no
        origin is refused. The origin is kept with the memory.
        """
        owner = self._owner_from(origin)
        return await self._store_memory(
            content, memory_type=memory_type, importance_score=formed_importance,
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
        importance_score: Optional[float] = None,
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
            importance_score: Importance score (0.0-1.0) - decided here by what the memory is (`importance_of`)
                unless the memory agent already decided it (`take_in_reasoning`) or it was formed in another store
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
        # NO KEY IS REMEMBERED. Whatever reached this (a tool's output, a
        # sentence someone typed, a reasoning trace) has every key replaced by
        # its name before anything is kept (core.security.secrets). Media bytes
        # are what was met and are kept as they are.
        from core.security.secrets import get_secrets_authority
        _keys = get_secrets_authority()
        content = _keys.redact(content)
        tags, source_context, embedding_metadata = (
            _keys.redact(tags), _keys.redact(source_context), _keys.redact(embedding_metadata))
        reasoning_trace, thinking_state, system_state = (
            _keys.redact(reasoning_trace), _keys.redact(thinking_state), _keys.redact(system_state))
        decision_factors, emotional_context, media_meta = (
            _keys.redact(decision_factors), _keys.redact(emotional_context), _keys.redact(media_meta))
        logger.debug(f"\n[MEMORY_AGENT.STORE_MEMORY] Called with:")
        logger.debug(f"  Content length: {len(content)} chars")
        logger.debug(f"  Memory type: {memory_type}")
        logger.debug(f"  Tags: {tags}")
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

        # Attached media marks the memory as a percept -- a picture, a sound or
        # a text it met -- for worthiness and search. The bytes say which, and
        # their digest is WHAT was met (`met`), which is how two memories of
        # different things are told apart when their accounts read alike. What
        # several senses took in at one moment is one memory with each part's
        # media, and what was met is all of them together.
        met_parts = self._media_parts(media, media_meta)
        if met_parts:
            import hashlib
            from core.memory.media_store import media_kind
            digests = [hashlib.sha256(data).hexdigest() for data, _meta in met_parts]
            flags = {flag: True for flag in (
                {"image": "has_image", "video": "has_video", "audio": "has_sound"}.get(
                    media_kind(data) or "") for data, _meta in met_parts) if flag}
            source_context = {**(source_context or {}),
                              "met": (digests[0] if len(digests) == 1 else
                                      hashlib.sha256("".join(sorted(digests)).encode()).hexdigest()),
                              **flags}

        if importance_score is None:
            importance_score = self.importance_of(tags, confidence=confidence_score, source_context=source_context)

        # ========== STEP 1: GENERATE OR EXTRACT METADATA ==========
        logger.debug(f"[MEMORY_AGENT.STORE_MEMORY] STEP 1: Generate/extract metadata")
        worthiness_metadata = None

        # WHETHER IT IS WORTH KEEPING IS THE MEMORY AGENT'S, from what it was handed: a producer's own account of
        # why it should be stored (`thinking_state["worthiness_metadata"]`) was taken in its place before
        # (2026-10-23), so the abstract reasoning engine and hypothesis testing judged their own results.
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
        # events, learning updates, mapping verdicts and
        # critical failures are records other subsystems read back, not
        # candidates to be judged for novelty.
        # What was taught is kept because it was taught: the origin, which
        # store_memory and enqueue_memory both keep in source_context, says so.
        from core.memory.utils.memory_filter import get_memory_filter as _get_filter
        _raw_event_early = (thinking_state or {}).get("raw_event")
        _exemption = _get_filter().exemption_for(
            tags=tags, raw_event=_raw_event_early, origin=(source_context or {}).get("origin"))
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
            from core.perception.perception_faculty import get_acting_percept
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
        #
        # NOR IS A RECORD OF HOW ENGLISH IS USED: what was heard after a word,
        # what a word is said of. Its content is the substrate's own note
        # ("Heard after bug: is"); read as a sentence it took a quarter of a
        # second each and stated nothing (0 claims in 30,505 of them), so
        # WordNet's tens of thousands were hours of a teaching pass (2026-10-09).
        if ((source_context or {}).get("pattern_key")
                or {self.HEARD_TAG, self.SAID_OF_TAG, self.LISTENING_TAG} & set(tags or ())):
            _claim, _claim_shape, _claim_facts = None, None, ()
        else:
            _claim, _claim_shape, _claim_facts = await self._readable_claim(content, source_context)
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
                for data, meta in met_parts:
                    await self._retain_media(memory_id, data, meta, user_id)
                # EVENT: a new episodic memory is what abstraction feeds on.
                # Count it (and, past threshold, schedule abstraction on the
                # queue authority). Cheap — never reasons on the write path.
                if memory_type == MemoryType.EPISODIC:
                    self.note_episodic_stored()
                return True, memory_id
            else:
                # A WRITE THAT FAILED IS AN ERROR, not a memory declined. Returned as "not stored", it read like the
                # filter's decision, and a construction taught while the store timed out was lost with a log line.
                raise RuntimeError(f"memory {memory_id} was not stored: PostgreSQL returned success=False")

        except Exception as e:
            logger.error(f"[MEMORY_AGENT.STORE_MEMORY] ✗ {type(e).__name__}: {e}")
            raise

    #: How long before a memory formed a perception counts as contemporaneous with it.
    PERCEPTUAL_WINDOW_SECONDS = 120.0

    async def _perceptual_state(self, owner: Optional[str]) -> Optional[Dict[str, Any]]:
        """What was being perceived when a memory of `owner`'s formed: the most
        recent perceptions of the window, of that owner's own, whole, each saying
        whose it was. None when there were none -- a reading, never invented.

        ONLY THE MEMORY'S OWN OWNER'S. A person's image is theirs: stamped on
        every memory that forms near it, it would go into the substrate's own
        memories and other people's. The substrate's own seeing (its environment)
        does not belong in a person's memory either.

        WHAT A MEMORY OF PERCEIVING HOLDS IS POINTED TO, NEVER COPIED (`_perceived`)."""
        from core.memory.utils.interfaces import Origin
        from core.perception.perception_faculty import get_perception_faculty
        try:
            now = datetime.now().timestamp()
            fresh = [p for p in get_perception_faculty().recent_percepts(limit=64)
                     if now - float(getattr(p, "timestamp", 0.0)) <= self.PERCEPTUAL_WINDOW_SECONDS
                     and isinstance(getattr(p, "origin", None), Origin)
                     and self._owner_from(p.origin) == (owner or None)][-8:]
        except Exception as e:
            logger.warning(f"Perceptual state snapshot failed: {type(e).__name__}: {e}")
            return None
        if not fresh:
            return None
        return {"captured_at": datetime.now().isoformat(),
                "perceptions": [self._perceived(p, now) for p in fresh]}

    def _perceived(self, percept: Any, now: float) -> Dict[str, Any]:
        """One perception as a memory forming near it records it.

        A PERCEPTION IS KEPT ONCE. What the senses take in is remembered when it is met (`remember_met`): the memory
        of perceiving holds what was sensed, and the digest identifies the very bytes. A memory forming near it
        names that memory and the digest. It held a copy of the whole content instead, so every memory formed within
        the window carried each document read in it again: 928 MB of copied text in the sandbox and 122 MB in main
        (2026-10-08), 73 KB a memory where one without is under 8 KB. A perception no memory holds (a recognition, an
        input told) is kept whole here, where it is held."""
        entry = {"source": percept.source, "data_type": percept.data_type,
                 "confidence": None if percept.confidence is None else round(float(percept.confidence), 4),
                 "age_s": round(now - float(percept.timestamp), 2),
                 "owner": self._owner_from(percept.origin)}
        metadata = getattr(percept, "metadata", None) or {}
        if metadata.get("memory_id"):
            entry["memory_id"] = str(metadata["memory_id"])
            if metadata.get("digest"):
                entry["digest"] = str(metadata["digest"])
        else:
            entry["content"] = percept.content
        return entry

    @staticmethod
    def _media_parts(media: Any, media_meta: Optional[Dict[str, Any]]) -> List[Tuple[bytes, Dict[str, Any]]]:
        """What was met, as (bytes, perceived) pairs: one picture, sound or
        text's trace with `media_meta`, or -- for what several senses took in
        at one moment -- a list of (media, perceived) pairs, one per part."""
        if media is None:
            return []
        from core.memory.media_store import _read_bytes
        if isinstance(media, list):
            return [(_read_bytes(data), dict(meta or {})) for data, meta in media]
        return [(_read_bytes(media), dict(media_meta or {}))]

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
            if kind in ("sound_trace", "sight_trace", "text_trace") \
                    and isinstance(media, (bytes, bytearray)):
                keys = self._trace_keys(kind, bytes(media))
            await get_media_store().store_media(
                memory_id, media, perceived=media_meta or {}, owner=owner, keys=keys)
        except Exception as media_error:
            logger.error("memory %s stored but its media was not retained: %s",
                         memory_id, media_error)

    @staticmethod
    def _trace_keys(kind: str, data: bytes):
        """The keys a kept trace is found by: a sound's landmark hashes, a
        picture's keypoint keys, a text's runs of words. None when the trace
        keeps no features."""
        if kind == "text_trace":
            from core.perception.reading import trace_keys
            runs = trace_keys(data)
            return None if runs is None else [int(k) for k in runs]
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
            done = {k: run.get(k) for k in ("tool", "args", "success") if k in run}
            # How long the run took, as the registry timed it. A run that never
            # reached the tool (refused, or raised before it) has no time.
            if run.get("seconds") is not None:
                done["seconds"] = run["seconds"]
            parts.append(Part("tool_run", done, "substrate"))
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

        from core.learning.unified_learning_system import work_category
        evidence = {"outcome": "success" if success else "failure",
                    "confidence": float(confidence),
                    "checks": len(meta.get("completion_evidence") or []),
                    "verification_state": result.get("verification_state"),
                    "task_type": getattr(getattr(task, "type", None), "value", None),
                    # Which kind of work it was -- a task asked for on its own, a project's, a workflow's run -- for
                    # its owner's shared learning switch of that kind.
                    "category": work_category(meta)}
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
            if item is None or not visible_to(item.user_id or None, await self.shared_world_context(actor)):
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
            if item is None or not visible_to(item.user_id or None, await self.shared_world_context(actor)):
                continue
            resolution = 1.0 if same_picture else min(
                1.0, got["agreeing"] / self.SIGHT_MIN_AGREE - 1.0)
            item.similarity_score = round(float(resolution), 4)
            item.seen_match = {**got, "same_picture": same_picture}
            found[item.memory_id] = item
        return sorted(found.values(), key=lambda m: -m.similarity_score)[:limit]

    async def _recall_by_text(self, read: Any, *, limit: int,
                              actor: Optional[str]) -> List[MemoryItem]:
        """The readings of the same text as `read` (its runs of words), found
        by the runs they share through the media store's index and decided in
        reading's own process, as a sound is by its landmarks and a picture by
        its keypoints: at least `reading.READ_MIN_SHARED` runs shared, and at
        least `reading.READ_MIN_SHARE` of the shorter text. The same document,
        a new version of it, or a page of it quoted in another are all read
        before. Only memories `actor` may see."""
        from core.memory.media_store import get_media_store
        from core.perception import reading
        from core.perception.perception_faculty import get_perception_faculty
        from core.agents.autonomous.shared_types import visible_to
        met = [int(k) for k in read]
        candidates, held = [], set()
        for media in await get_media_store().similar(met, kind="text_trace",
                                                     limit=max(limit, 20)):
            if media["memory_id"] not in held:
                held.add(media["memory_id"])
                candidates.append(media)
        agreed = await get_perception_faculty().agreements(
            "text", met, [m["bytes"] for m in candidates])
        found: Dict[str, MemoryItem] = {}
        for media, (shared, share, same) in zip(candidates, agreed):
            if shared < reading.READ_MIN_SHARED or share < reading.READ_MIN_SHARE:
                continue
            item = await self.postgres_storage.get_memory(media["memory_id"])
            if item is None or not visible_to(item.user_id or None, await self.shared_world_context(actor)):
                continue
            item.similarity_score = round(float(share), 4)
            item.read_match = {"shared": int(shared), "share": round(float(share), 4),
                               "same_text": bool(same)}
            found[item.memory_id] = item
        return sorted(found.values(), key=lambda m: -m.similarity_score)[:limit]

    #: The retrieval strategies that compose one recall. Each is a distinct
    #: storage primitive, so "specialise the agents" is a property of the
    #: design rather than a TODO: semantic finds paraphrase, keyword finds
    #: literal strings an embedding smooths away, tags find curation, and sound,
    #: sight and text find what was met by the sound, the picture or the words
    #: themselves (when the caller has one).
    RETRIEVAL_STRATEGIES = ("semantic", "keyword", "tags", "sound", "sight", "text")

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
        read: Optional[Any] = None,
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

        `read` is a text's runs of words (`reading.shingles`): given them, the
        `text` strategy recalls the readings of THE SAME TEXT -- the same
        document again, a new version of it, a page of it quoted elsewhere --
        each with how much agreed (`similarity_score`, and `read_match`).

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

        async def _text() -> List[MemoryItem]:
            if read is None or not len(read):
                return []
            return await self._recall_by_text(read, limit=per_strategy, actor=actor)

        runners = {"semantic": _semantic, "keyword": _keyword, "tags": _tags,
                   "sound": _sound, "sight": _sight, "text": _text}
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

        # A STRATEGY THAT FAILED IS NOT ONE THAT FOUND NOTHING. Logged and passed over, a recall whose every way
        # failed came back empty and was taken for "nothing remembered": a word-class warm read so under load held
        # no words, and the reader went on as though it had never met one (2026-10-08).
        failed = [(name, outcome) for name, outcome in zip(names, outcomes) if isinstance(outcome, BaseException)]
        if failed:
            name, outcome = failed[0]
            raise RuntimeError(f"recall by {', '.join(n for n, _ in failed)} failed: "
                               f"{type(outcome).__name__}: {outcome}") from outcome
        merged: Dict[str, MemoryItem] = {}
        found_by: Dict[str, Set[str]] = {}
        for name, outcome in zip(names, outcomes):
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
        # the signal -- 309 task failures are 309 facts about how often the
        # system failed, which is what competence calibration counts. That
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

    async def stated_pronunciations(self):
        """Every `(word, phones, how often real text uses it)` taught, read exactly from the metadata of the
        memories that hold them, as `stated_word_classes` reads classes."""
        rows = await self._rows_tagged(self.PRONUNCIATION_TAG)
        out = []
        for item in rows:
            meta = item.metadata or {}
            word = str(meta.get("word") or "").strip().lower()
            phones = " ".join(str(meta.get("said_as") or "").split())
            if word and phones:
                out.append((word, phones, int(meta.get("used") or 0)))
        return out

    async def stated_word_classes(self):
        """Every `(word, CLASS)` pair already TOLD to the substrate.

        Read exactly, from the metadata that identifies these memories, so a
        teaching pass can tell what it has already said without asking a vector
        index whether two sentences about grammar resemble each other."""
        rows = await self._rows_tagged(self.WORD_CLASS_TAG)
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
        from core.semantics.derived_reader import item_from
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        items, unreadable = [], 0
        for _, meta in await self._construction_rows():
            await give_way()
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
        held: Dict[str, str] = {}
        for memory_id, meta in await self._construction_rows():
            key = str(meta.get("pattern_key") or "")
            if key:
                held.setdefault(key, memory_id)
        return held

    _construction_index_ready = False

    async def _construction_rows(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Every construction and link memory holds -- Lyric's own, taught -- as (memory id, what it holds), read
        whole by its tag from both tiers of every store memory keeps.

        Read directly, not through retrieval: retrieval ranks all of memory to find what fits a query, and asked for
        a set whole it ran 62 s under teaching, timed out, and came back empty -- so the view warmed from it would
        have held no English at all. Read so, it is one indexed query."""
        from core.database.releases import SUBSTRATE_OWNERS
        from core.semantics.derived_reader import PATTERN_TAG
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        db = self._memory_db()
        await self._tags_index()
        rows_out: List[Tuple[str, Dict[str, Any]]] = []
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                rows = await db.execute_query(
                    f"SELECT memory_id, metadata FROM {table}"
                    " WHERE tags @> $1::jsonb AND COALESCE(user_id, '') = ANY($2::text[])"
                    " ORDER BY created_at",
                    (json.dumps([PATTERN_TAG]), list(SUBSTRATE_OWNERS)), fetch_all=True, store=store) or []
                for row in rows:
                    await give_way()
                    meta = row["metadata"]
                    meta = json.loads(meta) if isinstance(meta, str) else dict(meta or {})
                    rows_out.append((row["memory_id"], meta))
        return rows_out

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
            if finished.cancelled() and self._stopping_loops:
                logger.info("the word-class warm stopped with the memory agent")
                return
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
        from core.utils.give_way import GiveWay
        # Every set read here is tens of thousands of memories, worked through in one pass. Unbroken, the pass held
        # the loop 22 s past a 30 s boot timer while the substrate was starting, and it runs again when each
        # teaching pass ends with everything live (2026-10-09).
        give_way = GiveWay()

        # TWO QUERIES, BECAUSE THEY ARE TWO KINDS OF EVIDENCE.
        #
        # Tag search CONTAINS rather than matches any (`tags @> ...`), so one
        # call asking for both tags would return memories carrying BOTH -- of
        # which there are none, since a sentence is either read or not. The
        # sentences that read supply evidence FOR a class; the ones that
        # refused because of a class supply evidence AGAINST it.
        taught = await self._rows_tagged(self.TAUGHT_PROPOSITION_TAG)
        unread = await self._rows_tagged(self.UNREAD_TELLING_TAG)
        # THE THIRD KIND OF EVIDENCE: a class the substrate was TOLD, rather
        # than one implied by a sentence it read. This is where every closed
        # class and every adverb comes from -- words that never stand in a
        # subject, relation or object slot and so can be implied by nothing.
        stated = await self._rows_tagged(self.WORD_CLASS_TAG)

        index: Dict[str, Dict[str, int]] = {}
        unparsed = 0
        refuted = 0
        told = 0
        derived = 0
        for item in stated:
            await give_way()
            meta = item.metadata or {}
            word = str(meta.get("word") or "").strip().lower()
            cls = str(meta.get("word_class") or "").strip().upper()
            if not word or not cls:
                continue
            bucket = index.setdefault(word, {})
            bucket[cls] = bucket.get(cls, 0) + 1
            told += 1
        for item in (*taught, *unread):
            await give_way()
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
        # Added one at a time, as the constructor adds them, so the loop is given its turn between them.
        inventory = PatternInventory()
        for item in await self.taught_patterns():
            inventory.add(item)
            await give_way()
        # WHAT WORDS ARE SAID OF, in the same pass: how English uses a word, read from memory at the same events.
        said = await self._said_memories()
        # AND HOW THE WORDS OF A SENTENCE GO TOGETHER: the sentences held as analysed; which phrases are a
        # happening's arguments; and the lessons' sentences with their meanings, which the composer learns from.
        groups = await self._word_group_memories()
        forms = await self._word_form_memories()
        inventory.held_forms = forms.bases_of
        structure = await self._analysed_memories(groups)
        arguments = await self._argued_memories()
        composition, taught_sentences = await self._composition_memories(arguments)
        derived = await self._derived_memories()
        # AND THE WORDS RECORDED WHOLE, before any sentence: each layer of each into the view that learns from it.
        self._record_names, self._grammar_words = {}, []
        for row, word in await self._word_record_memories():
            await give_way()
            self._learn_word_record(word, index, forms)
            self._grammar_words.append(word)
        # AND THE SENTENCES RECORDED WHOLE: each layer of each into the view that learns from it.
        for row, record in await self._record_memories():
            await give_way()
            self._learn_record_words(record, index)
            structure.add(record.analysed())
            for item in record.forms():
                forms.hold(item)
            derived.append(record.derived())
            recorded = record.taught()
            composition.hold(recorded)
            taught_sentences.append(recorded)
            kept = (row.metadata or {}).get("grammar_learned") or {}
            self._grammar_learned[recorded.key()] = (row.memory_id, kept.get("counted"), kept.get("rules"))
        # AND WHAT READING TAUGHT OF HOW WORDS ARE USED (`keep_grammar_learning`).
        self._read_english = [record for row in await self._rows_tagged(self.READ_ENGLISH_TAG)
                              for record in ((row.metadata or {}).get("read_english") or ())]
        # AND WHAT THINGS ARE, as English's grammar asks it of the words it reads (`grammar_view`).
        grammar_links = await self._grammar_knowledge()
        # AND WHAT WAS HEARD AFTER WHAT, into the same view.
        heard, self._heard_memory = await self._heard_memories()
        for word, (after, two) in heard.items():
            await give_way()
            for other in after:
                inventory.hear((word, other))
            for earlier, others in two.items():
                for other in others:
                    inventory.hear((earlier, word, other))

        self._word_class_index = index
        self._word_classes_warm = True
        # The reader stands a word where its class's part stands (`PatternInventory.of_its_class`): the same index,
        # kept current as each proposition is taught (`note_taught_proposition`).
        inventory.word_classes = index
        self._pattern_inventory = inventory
        self._said_view, self._said_spread = said, {}
        self._structure_view, self._word_groups, self._word_forms = structure, groups, forms
        self._argument_view, self._composition_view = arguments, composition
        self._grammar_links, self._grammar_taught, self._grammar_view = grammar_links, taught_sentences, None
        self._grammar_derived = derived
        self._fan_view, self._things_held = {}, None
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
        tier: Optional[str] = None
    ):
        """
        Update memory fields
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

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
        tier: str,
        reason: str,
        tier_hint: Optional[str] = None
    ) -> bool:
        """
        Update memory importance score, saying why on the memory.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        return await self.update_memory(
            memory_id,
            {"importance_score": new_importance,
             "metadata": {"importance_update": {"reason": reason,
                                                "updated_at": datetime.now().isoformat()}},
             "metadata.merge": True},
            tier=tier)

    async def update_tags(
        self,
        memory_id: str,
        tags: List[str],
        tier: str = "hot",
        operation: str = "replace"
    ) -> bool:
        """
        Update memory tags: `replace` them, or `add` or `remove` these.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if operation not in ("replace", "add", "remove"):
            raise ValueError(f"tags are replaced, added or removed, not {operation!r}")
        new = list(dict.fromkeys(tags))
        if operation != "replace":
            held = await self.retrieve_memory(memory_id)
            if held is None:
                return False
            current = list(getattr(held, "tags", None) or [])
            new = (list(dict.fromkeys(current + new)) if operation == "add"
                   else [t for t in current if t not in set(new)])
        return await self.update_memory(memory_id, {"tags": new}, tier=tier)

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

        return await self.update_memory(
            memory_id, {"metadata": metadata_updates, "metadata.merge": merge}, tier=tier)

    # ================================================================================================
    # FORGETTING A MEMORY
    # ================================================================================================

    async def delete_memory(self, memory_id: str, reason: str = "") -> bool:
        """Forget a memory: its row and what it kept of what was met are
        removed. There is no soft delete -- the store has no deleted state, so
        a forgotten memory is gone. Returns True when it was removed."""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')
        if not await self.postgres_storage.delete_memory(memory_id):
            logger.error("Failed to forget memory %s", memory_id)
            return False
        from core.memory.media_store import get_media_store
        media = await get_media_store().forget_memory(memory_id)
        self.memory_cache.pop(memory_id, None)
        logger.info("Memory %s forgotten (%s media)%s", memory_id, media,
                    f": {reason}" if reason else "")
        return True

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
        looked up at each write so it is always the one every reader uses, and
        handed back behind the guard that keeps keys out of every concept,
        belief, rule and record written through it."""
        from core.database import get_database_manager
        return _KeylessWrites(get_database_manager())

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
                            evidence_id: str, extractor: str, polarity: str,
                            source_name: Optional[str] = None) -> None:
        """A link from one concept to another, or to a surface not yet learned
        (`target_concept_id` None until `attach_waiting_links` finds it).

        ONE SPELLING OF A RELATION: written as the ingress writes it, with spaces
        ("has property"), whichever producer named it ("has_property"), so the
        same relation is never two rows apart by how it was spelled. Readers take
        either (`concept_graph_reasoning._typed_edge`).

        WHAT A THING IS, KNOWN AT ONCE: a kind taken in of the concept named
        `source_name` ("Harvard is a university.", told, read in a document,
        taught) is what English's grammar asks of it from then on (`grammar_view`,
        `Words.hear_kind`), not from the next warm: the grammar decides what a
        phrase says by what its things are (`grammar.Lexicon.selected`)."""
        relation = " ".join(str(relation).replace("_", " ").split())
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
        kind = {"isa": "isa", "is a": "isa", "instance of": "instance_of"}.get(relation)
        if kind and polarity == "positive" and source_name:
            self._grammar_links.append((str(source_name), kind, str(target_surface)))
            if self._grammar_view is not None:
                self._grammar_view.words.hear_kind(str(source_name), kind, str(target_surface))

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

    # ---- what identity resolution put on the wrong concept -------------------

    async def release_evidence(self, *, concept_id: str, evidence_ids: List[str],
                               entries: List[List[str]]) -> Dict[str, int]:
        """Take off a concept what these observations wrote on it, where identity resolution put them on the wrong
        one: their links from it, their evidence and domain records, and `entries`, the relationships they merged
        into its own row ([relation, target, polarity], as `hold_concept` merges them), unless what remains still
        holds one. Its root evidence is counted again from what remains. Returns what was taken off."""
        db = self._memory_db()
        links = await db.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id = $1 AND evidence_id = ANY($2::text[]) "
            "RETURNING relation, target_surface, polarity", (concept_id, list(evidence_ids)),
            fetch_all=True, commit=True) or []
        evidence = await db.execute_query(
            "DELETE FROM unified.concept_evidence WHERE concept_id = $1 AND evidence_id = ANY($2::text[]) "
            "RETURNING 1", (concept_id, list(evidence_ids)), fetch_all=True, commit=True) or []
        domains = await db.execute_query(
            "DELETE FROM unified.concept_domains WHERE concept_id = $1 AND evidence_id = ANY($2::text[]) "
            "RETURNING 1", (concept_id, list(evidence_ids)), fetch_all=True, commit=True) or []
        kept = {(r["relation"], r["target_surface"], r["polarity"]) for r in await db.execute_query(
            "SELECT relation, target_surface, polarity FROM unified.concept_relations WHERE source_concept_id = $1",
            (concept_id,), fetch_all=True) or []}
        rows = await db.execute_query("SELECT relationships FROM unified.concepts WHERE concept_id = $1",
                                      (concept_id,), fetch_all=True) or []
        held = rows[0]["relationships"] if rows else []
        held = json.loads(held) if isinstance(held, str) else list(held or [])
        released = {tuple(e) for e in entries}
        remaining = [e for e in held if tuple(e) not in released or tuple(e) in kept]
        await db.execute_query(
            "UPDATE unified.concepts SET relationships = $2::jsonb, root_evidence_count = ("
            " SELECT count(DISTINCT root_evidence_id) FROM unified.concept_evidence WHERE concept_id = $1),"
            " updated_at = NOW() WHERE concept_id = $1",
            (concept_id, json.dumps(remaining)), commit=True)
        return {"links": len(links), "evidence": len(evidence), "domains": len(domains),
                "entries": len(held) - len(remaining)}

    async def release_alias(self, *, alias: str, concept_id: str) -> bool:
        """An alias that names the wrong concept, let go: the next reading of the name resolves it afresh."""
        rows = await self._memory_db().execute_query(
            "DELETE FROM unified.concept_aliases WHERE alias = $1 AND concept_id = $2 RETURNING 1",
            (alias, concept_id), fetch_all=True, commit=True) or []
        return bool(rows)

    async def free_links(self, *, target_concept_id: str, target_surfaces: List[str]) -> int:
        """Links that named these surfaces and were attached to the wrong concept, waiting again for theirs
        (`attach_waiting_links`). Returns how many."""
        rows = await self._memory_db().execute_query(
            "UPDATE unified.concept_relations SET target_concept_id = NULL "
            "WHERE target_concept_id = $1 AND target_surface = ANY($2::text[]) RETURNING 1",
            (target_concept_id, list(target_surfaces)), fetch_all=True, commit=True) or []
        return len(rows)

    async def release_envelope(self, evidence_id: str) -> bool:
        """The record of an observation written wrong, let go once nothing holds it: no concept, link or domain
        record rests on it. Its observation, read again, is stored as written then (an envelope keeps the first
        record of its id, `hold_evidence_envelope`), so a wrong record left standing would be the one kept. False
        where something still rests on it, or there is no such record."""
        rows = await self._memory_db().execute_query(
            "DELETE FROM unified.evidence_envelopes e WHERE e.evidence_id = $1"
            " AND NOT EXISTS (SELECT 1 FROM unified.concept_evidence ce"
            " WHERE ce.evidence_id = $1 OR ce.root_evidence_id = $1)"
            " AND NOT EXISTS (SELECT 1 FROM unified.concept_relations cr WHERE cr.evidence_id = $1)"
            " AND NOT EXISTS (SELECT 1 FROM unified.concept_domains cd WHERE cd.evidence_id = $1)"
            " AND NOT EXISTS (SELECT 1 FROM unified.concept_identity_relations ci WHERE ci.evidence_id = $1)"
            " AND NOT EXISTS (SELECT 1 FROM unified.learned_rule_evidence lr WHERE lr.root_evidence_id = $1)"
            " RETURNING 1", (evidence_id,), fetch_all=True, commit=True) or []
        return bool(rows)

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
                          posterior_probability: float, log_odds: float, uncertainty_type: str,
                          entropy: float, new_evidence: str,
                          update_count: int, last_updated: Any,
                          expected_update_count: int) -> Optional[Any]:
        """A belief, replaced only while it is still at `expected_update_count`
        (-1 for one never stored), with the observations made since it was last
        stored (`new_evidence`: a JSON list of `{"supports": bool, "entry": ...}`
        in the order they were made) added to its evidence. Returns the stored
        row, or None when another instance has moved the belief since; then
        nothing is written, and the belief system merges its own evidence onto
        the stored belief and writes again.

        THE EVIDENCE IS ADDED, NEVER REWRITTEN: one row each in
        `unified.belief_evidence`, in the same statement as the belief, so they
        are stored together or not at all. The whole list used to be written
        again into the belief's row at every observation: a frame taught by
        16,000 sentences rewrote 2.7 million characters for the next one.

        `claim` is written twice, as the claim and as `belief_text`, and the
        posterior as `confidence`: labels and a legacy mirror, not knowledge.
        `log_odds` is how strongly it is held; the posterior is read from it."""
        return await self._memory_db().execute_query(
            """
            WITH held AS (
                INSERT INTO unified.beliefs AS b
                    (belief_id, memory_id, claim, belief_text, confidence, domain,
                     prior_probability, posterior_probability,
                     uncertainty_type, entropy, update_count, last_updated, log_odds)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$14)
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
                    update_count        = EXCLUDED.update_count,
                    last_updated        = EXCLUDED.last_updated,
                    log_odds            = EXCLUDED.log_odds
                WHERE b.update_count = $13
                RETURNING update_count
            ), added AS (
                INSERT INTO unified.belief_evidence (belief_id, supports, entry)
                SELECT $1, (made.value->>'supports')::boolean, made.value->'entry'
                FROM held, jsonb_array_elements($15::jsonb) WITH ORDINALITY AS made(value, n)
                ORDER BY made.n
            )
            SELECT update_count FROM held
            """,
            (belief_id, memory_id, claim, claim, posterior_probability, domain,
             prior_probability, posterior_probability, uncertainty_type, entropy,
             update_count, last_updated, expected_update_count, log_odds, new_evidence),
            fetch_one=True,
        )

    async def belief_evidence(self, belief_id: str) -> Tuple[List[Any], List[Any]]:
        """One belief's evidence as stored: the observations for it and against it, each in the order made."""
        rows = await self._memory_db().execute_query(
            "SELECT supports, entry FROM unified.belief_evidence WHERE belief_id = $1 ORDER BY seq",
            (belief_id,), fetch_all=True) or []
        for_it: List[Any] = []
        against: List[Any] = []
        for row in rows:
            (for_it if row["supports"] else against).append(_json_value(row["entry"]))
        return for_it, against

    async def every_belief_evidence(self) -> Dict[str, Tuple[List[Any], List[Any]]]:
        """Every belief's evidence as stored, by belief: what the beliefs are loaded with."""
        rows = await self._memory_db().execute_query(
            "SELECT belief_id, supports, entry FROM unified.belief_evidence ORDER BY seq",
            fetch_all=True) or []
        evidence: Dict[str, Tuple[List[Any], List[Any]]] = {}
        for row in rows:
            for_it, against = evidence.setdefault(row["belief_id"], ([], []))
            (for_it if row["supports"] else against).append(_json_value(row["entry"]))
        return evidence

    async def settle_belief_evidence(self, store: Optional[str] = None) -> Dict[str, int]:
        """Evidence still held as a list on a belief's row, as beliefs were stored before 2026-10-08, moved into
        `unified.belief_evidence`, one row each in the order of its list, and the row's lists emptied: in one
        statement, so a belief's evidence is in one place or the other, never both and never neither. A belief
        with none left there is not touched, so this is done once and costs nothing after."""
        row = await self._memory_db().execute_query(
            """
            WITH listed AS (
                SELECT belief_id, evidence_for, evidence_against FROM unified.beliefs
                WHERE jsonb_array_length(COALESCE(evidence_for, '[]'::jsonb)) > 0
                   OR jsonb_array_length(COALESCE(evidence_against, '[]'::jsonb)) > 0
                FOR UPDATE
            ), moved AS (
                INSERT INTO unified.belief_evidence (belief_id, supports, entry)
                SELECT belief_id, supports, entry FROM (
                    SELECT l.belief_id, true AS supports, e.value AS entry, e.n
                    FROM listed l, jsonb_array_elements(COALESCE(l.evidence_for, '[]'::jsonb))
                         WITH ORDINALITY AS e(value, n)
                    UNION ALL
                    SELECT l.belief_id, false, e.value, e.n
                    FROM listed l, jsonb_array_elements(COALESCE(l.evidence_against, '[]'::jsonb))
                         WITH ORDINALITY AS e(value, n)
                ) listed_entries
                ORDER BY belief_id, supports DESC, n
                RETURNING 1
            ), emptied AS (
                UPDATE unified.beliefs b
                SET evidence_for = '[]'::jsonb, evidence_against = '[]'::jsonb
                FROM listed WHERE b.belief_id = listed.belief_id
                RETURNING 1
            )
            SELECT (SELECT count(*) FROM moved) AS entries, (SELECT count(*) FROM emptied) AS beliefs
            """,
            fetch_one=True, commit=True, **({"store": store} if store else {}))
        return {"entries": int(row["entries"]) if row else 0, "beliefs": int(row["beliefs"]) if row else 0}

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

    async def calibration_records(self) -> List[Any]:
        """Every prediction held against its outcome (`hold_calibration`), oldest
        first: what each domain's calibration is restored from."""
        return await self._memory_db().execute_query(
            "SELECT domain, confidence, outcome FROM unified.calibration_data"
            " ORDER BY timestamp, id",
            fetch_all=True) or []

    # ---- expectations of the world (the predictive intelligence system) -------------

    async def hold_prediction_result(self, *, prediction_id: str, domain: str, horizon: str,
                                     predicted_value: Optional[float],
                                     actual_value: Optional[float], confidence: float,
                                     accuracy: float, calibration: float,
                                     predicted_at: datetime) -> None:
        """How one forecast scored against what happened, kept once."""
        await self._memory_db().execute_query(
            "INSERT INTO unified.prediction_results"
            " (prediction_id, domain, horizon, predicted_value, actual_value, confidence,"
            "  accuracy, calibration, predicted_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
            " ON CONFLICT (prediction_id) DO NOTHING",
            (prediction_id, domain, horizon, predicted_value, actual_value, confidence,
             accuracy, calibration, predicted_at), commit=True)

    async def hold_expectation(self, *, expectation_id: str, rule_id: str, domain_id: str,
                               add_facts: str, delete_facts: str, held_facts: str,
                               since: datetime, due: datetime, owner: Optional[str],
                               committed: bool) -> bool:
        """What the substrate now expects a world to do on its own, and by when.
        Returns whether it was new: an expectation already held is not held
        twice."""
        rows = await self._memory_db().execute_query(
            "INSERT INTO unified.held_expectations"
            " (expectation_id, rule_id, domain_id, add_facts, delete_facts, held_facts,"
            "  since, due, owner, committed)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)"
            " ON CONFLICT (expectation_id) DO NOTHING RETURNING expectation_id",
            (expectation_id, rule_id, domain_id, add_facts, delete_facts, held_facts,
             since, due, owner, committed), fetch_all=True) or []
        return bool(rows)

    async def settle_expectation(self, *, expectation_id: str, status: str,
                                 attribution: Optional[str], detail: str,
                                 memory_id: Optional[str]) -> bool:
        """How a held expectation ended, once: confirmed, unmet or not judgeable.
        Returns False when it had already ended."""
        rows = await self._memory_db().execute_query(
            "UPDATE unified.held_expectations SET status = $2, attribution = $3, detail = $4,"
            " memory_id = $5, settled_at = NOW()"
            " WHERE expectation_id = $1 AND status = 'pending' RETURNING expectation_id",
            (expectation_id, status, attribution, detail, memory_id), fetch_all=True) or []
        return bool(rows)

    async def departed_expectations(self, *, domain_id: str) -> List[Any]:
        """The expectations of one domain's world settled as the world departing:
        what a later change may yet show to have happened, only late."""
        return await self._memory_db().execute_query(
            "SELECT expectation_id, rule_id, domain_id, add_facts, delete_facts, held_facts,"
            " since, due, owner, committed FROM unified.held_expectations"
            " WHERE domain_id = $1 AND status = 'unmet' AND attribution = 'external_failure'",
            (domain_id,), fetch_all=True) or []

    async def confirm_late(self, *, expectation_id: str, detail: str) -> bool:
        """An expectation settled as the world departing that happened after all,
        later than its due time: it held. Returns False when it was not so settled."""
        rows = await self._memory_db().execute_query(
            "UPDATE unified.held_expectations SET status = 'confirmed', attribution = 'rule_evidence',"
            " detail = $2 WHERE expectation_id = $1 AND status = 'unmet'"
            " AND attribution = 'external_failure' RETURNING expectation_id",
            (expectation_id, detail), fetch_all=True) or []
        return bool(rows)

    async def pending_expectations(self, *, domain_id: Optional[str] = None) -> List[Any]:
        """The expectations still waiting on the world, in one domain or in all,
        soonest due first."""
        query = ("SELECT expectation_id, rule_id, domain_id, add_facts, delete_facts, held_facts,"
                 " since, due, owner, committed FROM unified.held_expectations"
                 " WHERE status = 'pending'")
        params: tuple = ()
        if domain_id is not None:
            query += " AND domain_id = $1"
            params = (domain_id,)
        return await self._memory_db().execute_query(
            query + " ORDER BY due", params or None, fetch_all=True) or []

    async def expectations_of(self, *, domain_id: str) -> List[Any]:
        """Every expectation held of one domain's world and how each ended, oldest first."""
        return await self._memory_db().execute_query(
            "SELECT expectation_id, rule_id, owner, committed, status, attribution, detail,"
            " since, due, settled_at, memory_id FROM unified.held_expectations"
            " WHERE domain_id = $1 ORDER BY created_at, expectation_id",
            (domain_id,), fetch_all=True) or []

    async def expectation_outcomes(self, *, domain_id: str) -> List[Any]:
        """How the expectations held of one domain's world ended, counted per
        regularity that formed them, by status and attribution."""
        return await self._memory_db().execute_query(
            "SELECT rule_id, status, attribution, count(*) AS n FROM unified.held_expectations"
            " WHERE domain_id = $1 GROUP BY rule_id, status, attribution",
            (domain_id,), fetch_all=True) or []

    async def forget_expectations(self, *, domain_id: str) -> int:
        """Forget every expectation held of one domain's world."""
        rows = await self._memory_db().execute_query(
            "DELETE FROM unified.held_expectations WHERE domain_id = $1 RETURNING expectation_id",
            (domain_id,), fetch_all=True) or []
        return len(rows)

    async def forget_calibration(self, *, domain: str) -> int:
        """Forget every prediction held in one calibration domain. Returns how
        many were forgotten."""
        rows = await self._memory_db().execute_query(
            "DELETE FROM unified.calibration_data WHERE domain = $1 RETURNING id",
            (domain,), fetch_all=True) or []
        return len(rows)

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
                                 after_facts: str, positive: bool,
                                 owner: Optional[str] = None,
                                 before_at: Optional[datetime] = None,
                                 after_at: Optional[datetime] = None) -> List[Any]:
        """One observed action: what held before, the action, what held after,
        and whose work it was (`owner`, None for the substrate's own): a person's
        demonstration holds their particulars. A change the world made on its
        own carries when what held before it was first seen and when the change
        was read (`before_at`, `after_at`). Returns the rows written, so one
        seen before reads as nothing written."""
        return await self._memory_db().execute_query(
            "INSERT INTO unified.operator_demonstrations"
            " (evidence_id, domain_id, predicate, arity, before_facts, action,"
            "  after_facts, positive, owner, before_at, after_at)"
            " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
            " ON CONFLICT (evidence_id) DO NOTHING"
            " RETURNING evidence_id",
            (evidence_id, domain_id, predicate, arity, before_facts, action,
             after_facts, positive, owner, before_at, after_at),
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
        from core.memory.remembering import remembered
        if not remembered():
            return
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
        from core.memory.remembering import remembered
        if not remembered():
            return
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
    #: A hearing told which of the sounds words are made of is said when (`learn_phones`).
    PHONES_TAG = "spoken_sounds"
    #: How a word is said, as the phones of a pronouncing dictionary (`learn_pronunciations`).
    PRONUNCIATION_TAG = "pronunciation"
    VOICE_TAG = "voice"
    SONG_TAG = "song"
    #: A seeing that was a lesson: a thing shown, told what it is.
    THING_TAG = "thing"
    #: How many lessons `lessons_taught` reads. Named, because a silent cap
    #: here reads as "that word was never taught".
    TAUGHT_BY_HEARING_LIMIT = 20000

    #: The tag a lesson is found by, for what it teaches (`lessons_taught`).
    LESSON_TAGS = {"word": "spoken_word", "phones": "spoken_sounds", "person": "voice", "song": "song",
                   "thing": "thing"}

    async def take_in_lesson(self, content: Dict[str, Any], origin: Any, trace_kind: str) -> bool:
        """Whether a lesson just remembered (a perceiving's `content`, with its `lesson` and `trace`) is the
        world's, and, a person's lesson about a kind, kept as the world's (`share_lesson`)
        (docs/research/SEPARATION_MAP.md §11.3 and §11.6).

        WHOSE: Lyric's own lessons are the world's. A person's lesson about a kind -- a word said, the sounds of
        words, a thing shown as what it is ("a printer") -- is about the world; one about their own particular -- a
        voice, a thing or a song given a name the world does not hold ("Rex") -- is theirs, and stays in their
        memory, where their own recall finds it. So is a lesson given as theirs (`theirs`): their wake phrase, said
        in their own voice to set up Listening, is for their ears alone.

        JUDGED: a picture or a sound already remembered as another thing (the same picture, the same recording,
        named otherwise) is counted against what the lesson says, and the lesson is not taken for everyone."""
        from core.perception.perception_faculty import PerceptionFaculty, _term, decode_trace
        lesson = PerceptionFaculty.lesson_of(content.get("lesson"))
        if lesson is None or not content.get("trace"):
            return False
        key, label = lesson
        if origin.person is None:
            return True
        if key == "person" or (content.get("lesson") or {}).get("theirs"):
            return False
        if key in ("thing", "song") and str(label)[:1].isupper() and not await self._world_holds({str(label)}):
            return False
        if key == "thing":
            against = {name for earlier in content.get("seen_before") or [] if earlier.get("same_picture")
                       for name in earlier.get("named") or [] if _term(name) != _term(label)}
        else:
            against = {name for earlier in content.get("heard_before") or [] if earlier.get("support")
                       for name in earlier.get("named") or [] if _term(name) != _term(label)}
        if against:
            logger.info("lesson %r of %s not taken for everyone: the same %s is remembered as %s", label,
                        origin.person, "picture" if key == "thing" else "sound", ", ".join(sorted(against)))
            return False
        return await self.share_lesson(key, str(label), decode_trace(content["trace"]), trace_kind) is not None

    async def share_lesson(self, key: str, label: str, trace: bytes, trace_kind: str) -> Optional[str]:
        """A lesson someone gave, the world's (docs/research/SEPARATION_MAP.md §11.6): what it taught (`key`:
        word, phones, song, thing; `label`: what), kept with its trace -- the keypoints or landmarks it is known
        again by, never the picture or the recording, and nothing else of where it was given -- as the substrate's
        own, so every recognition reads it (`lessons_taught`). Returns the memory's id."""
        from core.memory.utils.interfaces import MemoryType, Origin
        tag = self.LESSON_TAGS[key]
        stored, memory_id = await self.store_memory(
            content=str(label), memory_type=MemoryType.SEMANTIC,
            tags=["lesson", tag], origin=Origin.own("lesson"),
            source_context={"source_system": "lesson", "lesson": {key: label}},
            media=trace, media_meta={"kind": trace_kind, "lesson": {key: label}})
        return memory_id if stored else None

    async def lessons_taught(self, tag: str, key: str, *, actor: Optional[str] = None) -> Dict[str, List[bytes]]:
        """Every hearing or seeing that taught under `tag` (`SPOKEN_WORD_TAG`,
        `VOICE_TAG`, `SONG_TAG` or `THING_TAG`), as memory holds it: what it
        taught (the word, whose voice, which song, which thing, read from `key`
        in the lesson's own record) -> the traces kept with those lessons. A
        view over memories, not a store beside them. Lyric's own lessons; with
        `actor`, theirs too (a person's own wake phrase, taught in their voice,
        is theirs and listened for by their ears alone)."""
        from core.memory.media_store import get_media_store
        rows = await self.search_memories(
            tags={tag}, limit=self.TAUGHT_BY_HEARING_LIMIT, actor=actor) or []
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

    # ---- a person's context -----------------------------------------------------

    async def hold_for_person(self, actor: str, subject: str, relation: str, obj: Optional[str], *,
                              positive: bool, quality: float, domain: str, surface: str, source: str,
                              context: str = "personal", organization: Optional[str] = None) -> Any:
        """A fact about a person's own things, held in their context: the link and their belief in it
        (`ScopedContextStore.observe`), where answering them finds it and the world never does
        (docs/research/SEPARATION_MAP.md §11.3). Returns the `Decision`, standing `theirs`. What the store cannot
        hold, or what is too weakly supported, is refused here as at the world's door."""
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import Decision
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY, shape_proposition
        claim = " ".join(str(p) for p in (subject, relation, obj) if p)
        subject_term, relation_term, obj_term, refusal = shape_proposition(subject, relation, obj)
        if refusal:
            return Decision(claim, positive, "refused", [refusal])
        if quality < MIN_ADMIT_QUALITY:
            return Decision(claim, positive, "refused", [
                f"insufficient support: quality {quality:.3f} < floor {MIN_ADMIT_QUALITY}"])
        owner, context, organization = self.held_where(actor, context, organization)
        await get_scoped_context_store().observe(
            owner, subject_term, relation_term, obj_term, claim=claim, positive=positive, quality=quality,
            domain=domain, surface=surface, source=source, context=context, organization=organization)
        return Decision(claim, positive, "theirs")

    async def hold_scoped_relation(self, *, actor: str, subject: str, relation: str,
                                   obj: str, polarity: str, surface: Any, domain: Any,
                                   source: str, context: str = "personal",
                                   organization: Optional[str] = None) -> None:
        """A link a person told the substrate, in that person's context: personal, or work and the
        organization's. Not remembered, held in working memory instead (`working_relations`)."""
        from core.memory.remembering import remembered
        if not remembered():
            self._working_relations.setdefault(actor, {})[(subject, relation, obj)] = {
                "subj": subject, "rel": relation, "obj": obj, "pol": polarity, "surface": surface,
                "scope_actor": actor, "at": time.time()}
            return
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.scoped_concept_relations
                (scope_actor, subj, rel, obj, polarity, surface, domain,
                 source, context, organization, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
            ON CONFLICT (scope_actor, subj, rel, obj) DO UPDATE SET
                polarity = EXCLUDED.polarity, surface = EXCLUDED.surface,
                domain = EXCLUDED.domain, context = EXCLUDED.context,
                organization = EXCLUDED.organization, last_updated = now()
            """,
            (actor, subject, relation, obj, polarity, surface, domain, source, context, organization),
            commit=True)

    async def hold_scoped_belief(self, *, actor: str, claim_key: str, claim: str,
                                 domain: Any, prior: float, posterior: float, log_odds: float,
                                 supports: bool, update_count: int, surface: Any,
                                 source: str, context: str = "personal",
                                 organization: Optional[str] = None) -> None:
        """A belief in a claim a person told the substrate, in that person's context: personal, or work and the
        organization's. Not remembered, held in working memory instead (`working_beliefs`)."""
        from core.memory.remembering import remembered
        if not remembered():
            self._working_beliefs.setdefault(actor, {})[claim_key] = {
                "claim": claim, "claim_key": claim_key, "domain": domain, "posterior": posterior,
                "log_odds": log_odds, "update_count": update_count, "scope_actor": actor, "context": context,
                "organization": organization, "at": time.time()}
            return
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.scoped_beliefs
                (scope_actor, claim_key, claim, domain, prior, posterior,
                 supports, update_count, surface, source, context, organization, log_odds, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13, now())
            ON CONFLICT (scope_actor, claim_key) DO UPDATE SET
                claim = EXCLUDED.claim, domain = EXCLUDED.domain,
                posterior = EXCLUDED.posterior, log_odds = EXCLUDED.log_odds, supports = EXCLUDED.supports,
                update_count = EXCLUDED.update_count, surface = EXCLUDED.surface,
                source = EXCLUDED.source, context = EXCLUDED.context,
                organization = EXCLUDED.organization, last_updated = now()
            """,
            (actor, claim_key, claim, domain, prior, posterior, supports,
             update_count, surface, source, context, organization, log_odds),
            commit=True)

    async def hold_scoped_rule(self, *, actor: str, claim_key: str, ant_subject: str, ant_relation: str,
                               ant_object: Optional[str], ant_positive: bool, cons_subject: str,
                               cons_relation: str, cons_object: Optional[str], cons_positive: bool,
                               surface: Any, domain: Any, context: str = "personal",
                               organization: Optional[str] = None) -> None:
        """A rule a person told the substrate, its two clauses kept as the world's held rules keep theirs
        (`hold_conditional`), in that person's context: personal, or work and the organization's. `claim_key` is
        the person's belief in it. Not remembered, held in working memory instead (`working_rules`)."""
        from core.memory.remembering import remembered
        row = {"ant_subject": ant_subject, "ant_relation": ant_relation, "ant_object": ant_object,
               "ant_positive": ant_positive, "cons_subject": cons_subject, "cons_relation": cons_relation,
               "cons_object": cons_object, "cons_positive": cons_positive, "surface": surface}
        if not remembered():
            self._working_rules.setdefault(actor, {})[claim_key] = {**row, "at": time.time()}
            return
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.scoped_conditionals
                (scope_actor, claim_key, ant_subject, ant_relation, ant_object, ant_positive,
                 cons_subject, cons_relation, cons_object, cons_positive, surface, domain,
                 context, organization, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14, now())
            ON CONFLICT (scope_actor, claim_key) DO UPDATE SET
                surface = EXCLUDED.surface, domain = EXCLUDED.domain, context = EXCLUDED.context,
                organization = EXCLUDED.organization, last_updated = now()
            """,
            (actor, claim_key, ant_subject, ant_relation, ant_object, ant_positive, cons_subject, cons_relation,
             cons_object, cons_positive, surface, domain, context, organization),
            commit=True)

    def working_relations(self, owners: Sequence[str]) -> List[Dict[str, Any]]:
        """The links held in working memory for any of `owners`, in the store's row shape (subj, rel, obj, pol,
        surface): what a conversation not remembered was told."""
        return [{k: v for k, v in row.items() if k != "at"}
                for owner in owners for row in self._working_relations.get(str(owner), {}).values()]

    def working_beliefs(self, owners: Sequence[str]) -> List[Dict[str, Any]]:
        """The beliefs held in working memory for any of `owners`, most recently moved first."""
        rows = [row for owner in owners for row in self._working_beliefs.get(str(owner), {}).values()]
        return [{k: v for k, v in row.items() if k != "at"} for row in sorted(rows, key=lambda r: -r["at"])]

    def working_rules(self, owners: Sequence[str]) -> List[Dict[str, Any]]:
        """The rules held in working memory for any of `owners`, in the store's row shape (each clause's subject,
        relation, object and polarity, and the surface): what a conversation not remembered was told."""
        return [{k: v for k, v in row.items() if k != "at"}
                for owner in owners for row in self._working_rules.get(str(owner), {}).values()]

    # ---- a person's Shared World Context: composed, never stored -------------------------------------------
    #
    # docs/research/SEPARATION_MAP.md §11.13. What Lyric may reason over for one person is World Knowledge (Lyric's
    # own), their Personal Context, and the Work Context of each organization they are authorized for, each kept
    # where its owner keeps it. It is composed at the moment Lyric works for them -- the same for every instance of
    # theirs, phone or desktop or web -- and nothing is copied or merged into anything else. A person leaving an
    # organization takes its Work Context out of their composition; it stays the organization's.

    _work_authorizations_ready = False

    async def ensure_work_authorizations(self) -> None:
        """The record of which organizations' Work Context each person is authorized for, made where it does not
        exist yet."""
        if MemoryAgent._work_authorizations_ready:
            return
        # Through `ensure_schema`, which holds an advisory lock while it creates: two first callers at once both
        # found the table missing and both created it, and the second failed on Postgres's catalog
        # (`duplicate key ... pg_type_typname_nsp_index`) at the first question asked of a fresh store (2026-10-10).
        await self._memory_db().ensure_schema("work_authorizations", ["""
            CREATE TABLE IF NOT EXISTS unified.work_authorizations (
                person        TEXT NOT NULL,
                organization  TEXT NOT NULL,
                authorized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                revoked_at    TIMESTAMPTZ,
                PRIMARY KEY (person, organization)
            )
            """])
        MemoryAgent._work_authorizations_ready = True

    async def authorize_work(self, person: str, organization: str) -> None:
        """That `person` acts for `organization`, as the identity that authenticated them says: its Work Context
        is part of their Shared World Context from now. Authorizing again, after they left, puts it back."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if is_substrate_actor(person) or not organization:
            raise ValueError("a Work Context is authorized for a person, by a named organization")
        await self.ensure_work_authorizations()
        await self._memory_db().execute_query(
            "INSERT INTO unified.work_authorizations (person, organization) VALUES ($1, $2) "
            "ON CONFLICT (person, organization) DO UPDATE SET revoked_at = NULL, "
            "authorized_at = CASE WHEN unified.work_authorizations.revoked_at IS NULL "
            "THEN unified.work_authorizations.authorized_at ELSE now() END",
            (str(person), str(organization)), commit=True)

    async def unlink_work(self, person: str, organization: str) -> bool:
        """`person` no longer acts for `organization`: its Work Context leaves their Shared World Context and stays
        the organization's, every memory and fact of it in place. Their Personal Context goes on with them.
        Returns whether they were authorized for it."""
        await self.ensure_work_authorizations()
        rows = await self._memory_db().execute_query(
            "UPDATE unified.work_authorizations SET revoked_at = now() "
            "WHERE person = $1 AND organization = $2 AND revoked_at IS NULL RETURNING person",
            (str(person), str(organization)), fetch_all=True, commit=True)
        return bool(rows)

    async def work_contexts(self, person: Optional[str]) -> Tuple[str, ...]:
        """The organizations whose Work Context `person` is authorized for now."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if is_substrate_actor(person):
            return ()
        await self.ensure_work_authorizations()
        rows = await self._memory_db().execute_query(
            "SELECT organization FROM unified.work_authorizations WHERE person = $1 AND revoked_at IS NULL "
            "ORDER BY organization", (str(person),), fetch_all=True) or []
        return tuple(str(r["organization"]) for r in rows)

    @staticmethod
    def memory_type_of(kind: Optional[str], *, verified: bool):
        """What kind of memory a conclusion is kept as. UNVERIFIED IS NEVER A FACT: a deduction the reasoning
        authority could not verify is one it might have got wrong, and recalled as general knowledge it would launder
        an unchecked step into a fact. A verified conclusion of a kind of thinking that yields facts
        (`neural_bridge._FACT_YIELDING_KINDS`, the reasoning authority's) is SEMANTIC; anything else is EPISODIC,
        better a general fact kept as a specific event than a specific event as a general fact. Chosen by the
        reasoning authority before (`neural_bridge._memory_type_for`, until 2026-10-23)."""
        from core.reasoning.neural_bridge import _FACT_YIELDING_KINDS
        if verified and str(kind or "").strip().lower() in _FACT_YIELDING_KINDS:
            return MemoryType.SEMANTIC
        return MemoryType.EPISODIC

    def take_in_reasoning(self, *, query: str, steps: Sequence[str], answer: Optional[str], confidence: float,
                          kind: Optional[str], verified: bool, mode: Optional[str], premises: int, multimodal: bool,
                          origin: "Origin", reason: Optional[str] = None) -> Optional[str]:
        """A reasoning the reasoning authority finished, handed over as it happened: whether it is kept as a memory
        recall can hand back (`recall_for`), how important it is, what kind of memory it is and how it is written
        are the memory agent's. The reasoning authority decided them itself before (`_capture_reasoning_memory`,
        until 2026-10-23). Returns the pending id, or None where nothing is kept.

        ONE MEMORY OF ONE REASONING, saying what led to its answer (`reason`, the reasoning authority's own account,
        never a phrase chosen off a confidence score; where there is none it says so) and whether it was verified.
        The coordinator's `reason_about` wrote a second memory of the same reasoning with its own importance ("I was
        asked: ... I answered: ...", until 2026-10-23), so every question asked through it was remembered twice.

        Nothing is kept of a reasoning that concluded nothing, nor of one that took almost no reasoning and is
        unsure (`effort` under 0.15, confidence under 0.6). The effort is how many steps it took, how much it was
        given to reason with, how unsure it stayed, and a picture or a video it answered about; importance grows with
        it and with confidence, and with what was seen. Its conclusion is kept as the claim it makes (`conclusion`),
        the episode written out beside it."""
        if not answer:
            return None
        effort = (min(len(steps or ()) / 5.0, 0.4) + min(premises / 10.0, 0.3)
                  + min((1.0 - confidence) * 0.2, 0.1))
        if multimodal and confidence > 0.5 and not any(
                phrase in answer.lower() for phrase in ("sorry", "cannot see", "not visible", "unable to",
                                                        "can't see", "image you intended", "please upload")):
            effort += 0.3       # only a picture or a video it did answer about
        effort = min(effort, 1.0)
        if effort < 0.15 and confidence < 0.6:
            logger.debug(f"Skipping trivial reasoning trace (effort={effort:.2f}, confidence={confidence:.2f})")
            return None
        steps_block = ""
        if steps and list(steps) != ["Direct neural inference"]:
            steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
            steps_block = f"\n\nReasoning steps:\n{steps_text}"
        importance = min(0.4 + effort * 0.4 + confidence * 0.2, 1.0)
        if multimodal:
            importance = min(importance + 0.1, 1.0)
        mode_tag = mode or "hybrid"
        tags = ["reasoning", mode_tag]
        if kind and kind not in tags:
            tags.append(str(kind))      # the kind of thinking, not only the route it took
        if multimodal:
            tags.append("multimodal")
        if len(steps or ()) >= 3:
            tags.append("multi_step")
        because = (f" I concluded this because {reason}." if reason else " I did not record what led me to it.")
        standing = "" if verified else " I have not verified this."
        return self._enqueue(
            content=f"Query: {query[:500]}{steps_block}\n\nAnswer: {answer[:800]}{because}{standing}",
            memory_type=self.memory_type_of(kind, verified=verified),
            importance_score=importance,
            confidence_score=confidence,
            tags=tags,
            source_context={
                "source": "neural_bridge",
                "mode": mode_tag,
                "query_length": len(query),
                # THE CLAIM, KEPT AS A CLAIM: what a past conclusion contributes to later reasoning is the
                # conclusion ("disk exhaustion causes checkout timeout"), not a document about having concluded it.
                "conclusion": answer,
                "conclusion_confidence": confidence,
                "conclusion_kind": kind,
                "verified": verified,
                "reason": reason,
            },
            reasoning_trace=list(steps or ()),
            origin=origin,
        )

    async def recall_for(self, query: Optional[str], *, actor: Optional[str] = None, heard: Optional[Any] = None,
                         seen: Optional[Dict[str, Any]] = None, limit: int = 3,
                         min_similarity: float = 0.6, min_importance: float = 0.5) -> List[Dict[str, Any]]:
        """What memory hands a request: the memories of the sound being heard and the picture being seen first,
        recalled by them, then those its words find, each with the claim it makes (`claim`), visible to `actor`.

        EVERY REQUEST IS RECALLED FOR, AND WHAT MEMORY HOLDS OF IT DECIDES WHAT IS HANDED OVER: a memory naming
        something the request names (`require_named_match`), as like it as `min_similarity`, of importance now
        (`decayed_importance`), knowledge and not an event or taught language (`include_events=False`). A
        conversation's recall has always run for every turn (`live_recall`). Recall here was gated by how complex
        the request was (2026-10-23, the reasoning authority's score), and that score falls as Lyric learns: every
        word taught made a request less complex, so the more Lyric was taught the less it would remember. Before
        that the memory injector and its policy gated it on a word count.

        A memory not yet written is found among those waiting (`_pending_memories`) by the words it shares."""
        from core.memory.utils.interfaces import decayed_importance
        words = (query or "").lower()
        by_words = bool(words.strip())
        if not by_words and heard is None and seen is None:
            return []
        try:
            results = []
            if heard is not None:
                results = list(await self.retrieve(strategies=["sound"], heard=heard, actor=actor, limit=limit))
            if seen is not None:
                held = {r.memory_id for r in results}
                results += [r for r in await self.retrieve(strategies=["sight"], seen=seen, actor=actor, limit=limit)
                            if r.memory_id not in held]
            if by_words:
                # KNOWLEDGE ONLY: event records (task outcomes, safety events, verdicts) are kept for their count
                # and answer nothing about a topic; found by likeness they only take the places of what is known.
                success, found = await self.search_memories(
                    query=query, limit=limit, min_similarity=min_similarity, include_events=False,
                    require_named_match=True, actor=actor)
                if not success:
                    logger.warning("memory search failed")
                    found = []
                held = {r.memory_id for r in results}
                results += [r for r in found if r.memory_id not in held]
            memories: List[Dict[str, Any]] = []
            for result in results:
                importance = decayed_importance(getattr(result, 'importance_score', 1.0),
                                                getattr(result, 'created_at', None))
                if importance < min_importance:
                    continue
                # WHAT THIS MEMORY CLAIMS: a writer that knew its conclusion kept it as `conclusion`, and that is
                # what the memory asserts; otherwise its content is all there is.
                metadata = result.metadata or {}
                claim = None
                if isinstance(metadata, dict):
                    source = metadata.get('source_context')
                    claim = ((metadata.get('conclusion') or source.get('conclusion')) if isinstance(source, dict)
                             else metadata.get('conclusion'))
                memories.append({
                    'memory_id': result.memory_id,
                    'content': result.content,
                    'claim': str(claim).strip() if claim else None,
                    # Set only where likeness was measured: a memory found by its wording or its tag has none.
                    'relevance_score': getattr(result, 'similarity_score', None),
                    'importance_score': importance,
                    'timestamp': result.created_at,
                    'metadata': metadata,
                    'reasoning_trace': getattr(result, 'reasoning_trace', None),
                    'intent_id': getattr(result, 'intent_id', None),
                    'intent_version': getattr(result, 'intent_version', None),
                    'percept_id': getattr(result, 'percept_id', None),
                    'percept_digest': getattr(result, 'percept_digest', None),
                    'heard_match': getattr(result, 'heard_match', None),
                    'seen_match': getattr(result, 'seen_match', None),
                })
            pending = getattr(self, '_pending_memories', {})
            if pending and by_words:
                from core.agents.autonomous.shared_types import visible_to
                composed = await self.shared_world_context(actor)
                query_words = set(words.split())
                for pid, entry in list(pending.items()):
                    if entry.get('importance_score', 0) < min_importance:
                        continue
                    # Not yet in the store, so the store's rule of whose it is has not been applied: applied here.
                    if not visible_to((entry.get('kwargs') or {}).get('user_id'), composed):
                        continue
                    content_words = set(entry['content'].lower().split())
                    overlap = len(query_words & content_words) / max(len(query_words), 1)
                    if overlap < 0.1:
                        continue
                    memories.append({'memory_id': pid, 'content': entry['content'], 'claim': None,
                                     'relevance_score': overlap,
                                     'importance_score': entry.get('importance_score', 0.5),
                                     'timestamp': None, 'metadata': {'pending': True}})
                    if len(memories) >= limit:
                        break
            return memories[:limit]
        except Exception as e:
            # A WIRING FAULT MUST NOT READ AS "NOTHING WAS REMEMBERED": structural faults are raised; only a failed
            # retrieval is empty, and says so.
            raise_if_structural(e, 'memory_agent.recall_for')
            logger.error(f"memory recall failed: {e}")
            return []

    async def shared_world_context(self, actor: Optional[str]) -> Tuple[str, ...]:
        """The owners composed into what Lyric may reason over for `actor`: Lyric's own (World Knowledge), the
        person's (Personal Context), and each organization's they are authorized for (its Work Context). For
        Lyric's own work, only its own: it is never coloured by whoever is connected."""
        from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR, is_substrate_actor, work_owner
        if is_substrate_actor(actor):
            return (SUBSTRATE_ACTOR,)
        return (SUBSTRATE_ACTOR, str(actor), *(work_owner(o) for o in await self.work_contexts(actor)))

    @staticmethod
    def held_where(actor: str, context: str, organization: Optional[str]) -> Tuple[str, str, Optional[str]]:
        """Where something a person gave is held: `(owner, context, organization)` -- their own Personal Context,
        or the organization's Work Context. An organization's owner given as the actor is its Work Context."""
        from core.agents.autonomous.shared_types import WORK_OWNER_PREFIX, is_work_owner, work_owner
        if is_work_owner(actor):
            return str(actor), "work", str(actor)[len(WORK_OWNER_PREFIX):]
        if context == "work":
            return work_owner(organization), "work", organization
        return str(actor), "personal", None

    _user_beliefs_ready = False

    async def ensure_user_beliefs(self) -> None:
        """The table of what people said about themselves, made where it does not exist yet."""
        if MemoryAgent._user_beliefs_ready:
            return
        await self._memory_db().execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.user_beliefs (
                speaker    TEXT NOT NULL,
                subject    TEXT NOT NULL,
                relation   TEXT NOT NULL,
                object     TEXT,
                polarity   TEXT NOT NULL DEFAULT 'positive',
                surface    TEXT,
                source     TEXT NOT NULL DEFAULT 'conversation',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (speaker, subject, relation)
            )
            """,
            commit=True,
        )
        # WHICH OF THE PERSON'S CONTEXTS it came through: personal, or work and the organization's
        # (`Origin.context`, docs/research/SEPARATION_MAP.md §11.3).
        for column in ("context TEXT NOT NULL DEFAULT 'personal'", "organization TEXT"):
            await self._memory_db().execute_query(
                f"ALTER TABLE unified.user_beliefs ADD COLUMN IF NOT EXISTS {column}", commit=True)
        MemoryAgent._user_beliefs_ready = True

    # ---- what someone told: taken in, split by what it is about -------------------
    #
    # docs/research/SEPARATION_MAP.md §11.10. A telling is split fact by fact. What is about the person -- naming
    # them, or a particular thing or a name that is theirs -- is held in their context at once, so the next turn
    # answers from it. What is about the world is a claim for the learning authority's one door, judged by whether
    # it is true, with the telling as its evidence: a person is a source like a page, neither proof nor
    # disqualification. The memory agent decides where each part goes and keeps no judge of truth.

    async def take_in_telling(self, telling: Any) -> List[Tuple[str, Any, Any]]:
        """Take in what someone told (`interfaces.Telling`). Returns, for each fact and each rule, `(kind, it,
        Decision)`: kind "fact" or "rule", the fact or the rule's `(antecedent, consequent)`, and what became of it
        (standing `theirs` where it is the person's)."""
        from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
        from core.learning.unified_learning_system import Evidence, get_learning_authority
        person = telling.origin.person
        parties = {str(person), SUBSTRATE_ACTOR}
        theirs = set(telling.theirs) | (set(telling.names) - await self._world_holds(set(telling.names)))
        authority = get_learning_authority()
        evidence = Evidence(source=f"person:{person}", key=str(person), source_type="USER_SUPPLIED",
                            quality=telling.quality, producer=f"telling:{telling.origin.through}")
        where = {"context": telling.origin.context, "organization": telling.origin.organization}
        out: List[Tuple[str, Any, Any]] = []
        # A CONVERSATION NOT REMEMBERED TEACHES THE WORLD NOTHING: what it is told is the speaker's, held in working
        # memory, the premises of what it is asked next (`not_remembered`), and never taken to the world's door.
        from core.memory.remembering import remembered
        premises = not remembered()
        for fact in telling.facts:
            terms = set(fact.terms())
            if terms & parties:
                decision = await self._hold_about_speaker(telling.speaker, fact, telling.sentence, **where)
            elif terms & theirs or premises:
                decision = await self.hold_for_person(
                    str(person), fact.subject, fact.relation, fact.obj, positive=fact.positive,
                    quality=telling.quality, domain="conversation", surface=telling.sentence, source="told",
                    **where)
            else:
                decision = await authority.consider(
                    fact.subject, fact.relation, fact.obj, positive=fact.positive, surface=telling.sentence,
                    evidence=evidence, domain="conversation")
            out.append(("fact", fact, decision))
        for antecedent, consequent in telling.rules:
            terms = {str(side.get(k)) for side in (antecedent, consequent) for k in ("subject", "obj")
                     if side.get(k)}
            if terms & (parties | theirs) or premises:
                decision = await self.hold_rule_for_person(
                    str(person), antecedent, consequent, quality=telling.quality, domain="conversation",
                    surface=telling.sentence, **where)
            else:
                decision = await authority.consider_rule(
                    antecedent, consequent, surface=telling.sentence, evidence=evidence, domain="conversation")
            out.append(("rule", (antecedent, consequent), decision))
        return out

    async def take_in_unread(self, sentence: str, *, origin: Any) -> Any:
        """A sentence someone told that did not read: kept verbatim and marked unread, theirs, recallable by meaning
        now and re-readable once the English it needs is taught (`CognitiveIngress.remember_told`). Nothing in it
        is taken as said. Returns the ingress's `Admission`."""
        from core.semantics.cognitive_ingress import Provenance, get_cognitive_ingress
        return await get_cognitive_ingress().remember_told(
            sentence, Provenance(producer="conversation", source_id=str(origin.person or "you"),
                                 source_type="USER_SUPPLIED"),
            blamed=None, origin=origin)

    async def take_in_tool(self, tool: Any) -> Any:
        """One of Lyric's own tools, as it declares itself -- what it takes and what it does -- handed on as Lyric's
        own observation of its means (`evidence_producers.submit_tool_declaration`). Returns the
        `IngestionResult`."""
        from core.domain.evidence_producers import submit_tool_declaration
        return await submit_tool_declaration(tool)

    async def take_in_tool_use(self, name: str, parameters: Dict[str, Any], succeeded: bool, *,
                               category: str) -> Any:
        """One use of a tool: which tool, the names of what it was given -- never their values, which are the
        task's -- and whether it worked (`evidence_producers.submit_tool_invocation`). Returns the
        `IngestionResult`."""
        from core.domain.evidence_producers import submit_tool_invocation
        return await submit_tool_invocation(name, parameters or {}, bool(succeeded), category=category)

    async def take_in_percept(self, subject: str, modality: str, content: Dict[str, Any], *,
                              origin: Any, memory_id: Optional[str] = None, domain: Optional[str] = None) -> Any:
        """Something perceived, as the senses structured it, handed on as evidence: each modality has its producer
        (a sensor reading, an image, a video, a sound, a document read, a device, a location fix), which says what
        in it is nameable, holds what is the owner's in their context and takes what is about the world to the one
        door (`evidence_producers`). Anything else -- a named component in a named state -- takes the general
        perception producer. `domain`, when given, is where it is filed; else the producer's own. Whose it is
        travels with it. Returns the producer's `IngestionResult`."""
        from core.domain import evidence_producers as ep
        producer = {
            "sensor": ep.submit_sensor_reading,
            "image": ep.submit_image,
            "video": ep.submit_video,
            "audio": ep.submit_audio,
            "document": ep.submit_reading,
            "device": ep.submit_device,
            "location": ep.submit_location,
        }.get(str(modality or "").strip().lower())
        filed = {"domain": domain} if domain else {}
        if producer is not None:
            return await producer(subject, content or {}, memory_id=memory_id, origin=origin, **filed)
        return await ep.submit_perception(subject, modality, content or {}, memory_id=memory_id, origin=origin,
                                          **filed)

    async def take_outcome_to_learning(self, memory: Any, content: Dict[str, Any], *, domain: Optional[str],
                                       mark: str) -> Tuple[str, int]:
        """One task outcome remembered (`content`, its TaskOutcomeRecord), handed to the learning authority as an
        example of work in `domain`, as the task's owner's experience, and marked with `mark` so it is handed once.
        Returns (status, transfers): 'expanded', 'no_knowledge_domain', or the learning's error class, and the
        cross-domain transfers written.

        A task that acted in no domain has nothing to learn from and is marked. One whose domain holds nothing yet
        is NOT marked: it is handed again once that domain has been learned (`domain_empty`)."""
        from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
        from core.learning.learning_interfaces import LearningExample
        from core.learning.unified_learning_system import get_learning_authority
        if domain is None:
            if not await self.update_memory(memory.memory_id, {
                    "metadata": {mark: datetime.now().isoformat(), "domain_expansion": "no_knowledge_domain"},
                    "metadata.merge": True}):
                raise RuntimeError(
                    f"task outcome {memory.memory_id} names no domain but could "
                    f"not be marked; it would be reconsidered on every pass")
            return ("no_knowledge_domain", 0)
        result = await get_learning_authority().learn_with_domain_context(
            LearningExample(
                example_id=memory.memory_id,
                # Whose experience the task was: its outcome memory's owner.
                actor=getattr(memory, "user_id", None) or SUBSTRATE_ACTOR,
                inputs={
                    "task_id": content.get("task_id"),
                    "task_type": content.get("task_type"),
                    "task_description": content.get("task_description"),
                    "task_source": content.get("task_source"),
                },
                targets={
                    "outcome": content.get("outcome"),
                    "result_summary": content.get("result_summary"),
                    "failure_reason": content.get("failure_reason"),
                },
                # The recorded confidence IS the quality of this example.
                quality_score=float(content.get("confidence", 0.0) or 0.0),
                task_type=content.get("task_type"),
                domain=str(domain),
                source="task_outcome",
            ),
            str(domain),
        )
        if not result.success:
            return ((result.metadata or {}).get("error_class") or "learning_failed", 0)
        # EXPANDED means the domain layer processed this outcome -- not that the learning strategy earned credit for
        # it (separate facts).
        cross = (result.metadata or {}).get("cross_domain") or {}
        if not await self.update_memory(memory.memory_id, {
                "metadata": {mark: datetime.now().isoformat()}, "metadata.merge": True}):
            # An unmarked outcome would be handed again and the meta-learner would count the repeat as fresh
            # evidence. Stop rather than quietly build up duplicate trials.
            raise RuntimeError(
                f"task outcome {memory.memory_id} was expanded but could not be "
                f"marked; continuing would re-learn it on every pass")
        return ("expanded", len(cross.get("transfers") or []))

    async def take_in_demonstration(self, example: Any, *, domain: str, owner: Optional[str]) -> bool:
        """One thing Lyric did, as it was seen before and after: kept as a demonstration of its act for the learner
        to induce from (`DemonstrationStore.append`, which wakes induction). `owner` is whose task it was, None for
        Lyric's own: a person's holds their particulars, and what is learned from it is lifted. Returns whether it
        was new."""
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().append(example, domain_id=domain, owner=owner)

    async def take_in_transition(self, example: Any, *, domain: str, owner: Optional[str], source_id: str) -> Any:
        """The same act as a root observation of the world (`evidence_producers.submit_demonstration`): what
        changed, projected through the one door with the act as its evidence, a person's work lifted. Returns the
        `IngestionResult`."""
        from core.domain.concept_ingestion import EvidenceSourceType
        from core.domain.evidence_producers import submit_demonstration
        return await submit_demonstration(
            example, domain_id=domain, source_type=EvidenceSourceType.TASK_ARTIFACT,
            producer="substrate_execution", source_id=source_id, owner=owner)

    async def take_in_recognised(self, naming: Any, *, domain: str, origin: Any) -> Any:
        """What Lyric's learned classifier named a thing it perceived (`UnifiedLearningSystem.name_instance`). A
        thing in a person's percept (`origin`) is their particular, so what it was named is held in their context,
        personal or work; a thing Lyric met itself is the world's, and its naming a claim for the one door, with
        the classifier's evidence. Returns the `Decision`."""
        from core.learning.unified_learning_system import get_learning_authority
        if origin.person is not None:
            return await self.hold_for_person(
                origin.person, naming.instance, "isa", naming.category, positive=True,
                quality=naming.evidence.quality, domain=domain, surface=naming.claim,
                source=naming.evidence.source, context=origin.context, organization=origin.organization)
        return await get_learning_authority().consider(
            naming.instance, "isa", naming.category, domain=domain, evidence=naming.evidence)

    async def take_in_verdict(self, memory_ids: Sequence[str], *, confirmed: bool, said: str, about: str) -> int:
        """A person's verdict on what they told ("That's right.", "That's wrong."): each memory the telling made is
        flagged with it, annotated and never overwritten -- recall reads the flag. What the verdict says of the
        claim itself is a telling (`take_in_telling`), judged at the one door. Returns how many were flagged."""
        flagged = 0
        for memory_id in memory_ids:
            if await self.update_memory(memory_id, {
                    "metadata": {"feedback": {"verdict": "confirmed" if confirmed else "corrected",
                                              "surface": said, "about": about, "at": time.time()}},
                    "metadata.merge": True}):
                flagged += 1
        return flagged

    async def take_in_observed(self, subject: str, relation: str, obj: Optional[str], *, evidence: Any,
                               domain: str, positive: bool = True, description: str = "",
                               surface: Optional[str] = None) -> Any:
        """Something Lyric observed itself -- of the place it runs in, of an experiment it ran, of kinds it saw, a
        thing it named -- a claim about the world for the one door, with the evidence it came with
        (`learning_authority.consider`). Returns the `Decision`."""
        from core.learning.unified_learning_system import get_learning_authority
        return await get_learning_authority().consider(
            subject, relation, obj, positive=positive, evidence=evidence, domain=domain,
            description=description, surface=surface)

    async def take_in_research(self, findings: Sequence[Tuple[str, str, str, str, str]]) -> List[Tuple[Any, Any]]:
        """What research found, each finding `(subject, relation, object, page, what it said)` a claim for the one
        door with its page as evidence: the page the source, its site the independence key, so one site counts once
        however many of its pages say it and sites that agree count each (docs/research/SEPARATION_MAP.md §11.4).
        Returns `(finding, Decision)` for each."""
        from urllib.parse import urlparse
        from core.learning.unified_learning_system import Evidence, get_learning_authority
        authority = get_learning_authority()
        out: List[Tuple[Any, Any]] = []
        for finding in findings:
            subject, relation, obj, page, said = finding
            site = urlparse(str(page)).netloc or str(page)
            evidence = Evidence(source=str(page), key=f"site:{site}", source_type="RESEARCH_FINDING",
                                quality=0.9, producer="research")
            out.append((finding, await authority.consider(
                subject, relation, obj, surface=said or None, description=said, evidence=evidence,
                domain="researched")))
        return out

    async def _world_holds(self, names: Set[str]) -> Set[str]:
        """Of these names, the ones the world holds a thing under: a name the world does not hold is the
        person's own ("Ava"), one it does is the world's ("Paris")."""
        from core.semantics.cognitive_ingress import normalize_term
        if not names:
            return set()
        spelled = {normalize_term(n) or n: n for n in names}
        rows = await self._memory_db().execute_query(
            "SELECT name FROM unified.concepts WHERE name = ANY($1::text[])",
            (sorted(spelled),), fetch_all=True) or []
        return {spelled[str(r["name"])] for r in rows if str(r["name"]) in spelled}

    async def _hold_about_speaker(self, speaker: str, fact: Any, surface: str, *, context: str,
                                  organization: Optional[str]) -> Any:
        """A fact naming the person themselves, held as a belief about them (`hold_belief_about_speaker`)."""
        from core.learning.unified_learning_system import Decision
        claim = " ".join(str(p) for p in (fact.subject, fact.relation, fact.obj) if p)
        await self.hold_belief_about_speaker(
            speaker=speaker, subject=fact.subject, relation=fact.relation, obj=fact.obj,
            polarity="positive" if fact.positive else "negative", surface=surface, context=context,
            organization=organization)
        return Decision(claim, fact.positive, "theirs")

    async def hold_belief_for_person(self, actor: str, claim: str, *, domain: str, supports: bool, quality: float,
                                     source: str, context: str = "personal",
                                     organization: Optional[str] = None) -> float:
        """A person's belief in a claim, moved by one observation, in their context (`ScopedContextStore
        .observe_claim`): how a method goes in their work, a hypothesis they hold. Returns its posterior."""
        from core.learning.scoped_context_store import get_scoped_context_store
        owner, context, organization = self.held_where(actor, context, organization)
        held = await get_scoped_context_store().observe_claim(
            owner, claim, domain=domain, supports=supports, quality=quality, source=source, context=context,
            organization=organization)
        return float(held["posterior"])

    async def hold_rule_for_person(self, actor: str, antecedent: Dict[str, Any], consequent: Dict[str, Any], *,
                                   quality: float, domain: str, surface: str, context: str = "personal",
                                   organization: Optional[str] = None) -> Any:
        """A rule about a person's own things, held in their context, asserting neither side: its two clauses, which
        the reasoner chains over when it works for them, and their belief in it (`ScopedContextStore.observe_rule`).
        Returns the `Decision`, standing `theirs`. What the store cannot hold, or what is too weakly supported, is
        refused here as at the world's door."""
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import Decision
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY, shape_proposition

        def said(clause: Dict[str, Any]) -> str:
            return ("" if clause.get("positive", True) else "not ") + " ".join(
                str(clause.get(k) or "") for k in ("subject", "relation", "obj")).strip()
        claim = " ".join(f"if {said(antecedent)} then {said(consequent)}".split())
        shaped = []
        for tag, side in (("antecedent", antecedent), ("consequent", consequent)):
            subject, relation, obj, refusal = shape_proposition(side.get("subject"), side.get("relation"),
                                                                side.get("obj"))
            if refusal:
                return Decision(claim, True, "refused", [f"{tag} {refusal}"])
            shaped.append((subject, relation, obj, bool(side.get("positive", True))))
        if quality < MIN_ADMIT_QUALITY:
            return Decision(claim, True, "refused", [
                f"insufficient support: quality {quality:.3f} < floor {MIN_ADMIT_QUALITY}"])
        owner, context, organization = self.held_where(actor, context, organization)
        await get_scoped_context_store().observe_rule(
            owner, *shaped, claim=claim, domain=domain, quality=quality, source="told_rule", surface=surface,
            context=context, organization=organization)
        return Decision(claim, True, "theirs")

    async def said_of_themselves(self, speaker: str, person: str, *, limit: int = 50) -> List[Dict[str, Any]]:
        """What a speaker said of themselves, most-recent first, in `person`'s Shared World Context: what they said
        personally, and what they said at work for an organization whose Work Context they are authorized for."""
        await self.ensure_user_beliefs()
        rows = await self._memory_db().execute_query(
            "SELECT subject, relation, object, polarity, surface, context, organization, updated_at "
            "FROM unified.user_beliefs WHERE speaker = $1 AND (context = 'personal' OR organization = ANY($3)) "
            "ORDER BY updated_at DESC LIMIT $2",
            (str(speaker), limit, list(await self.work_contexts(person))), fetch_all=True)
        working = sorted(self._working_speaker.get(str(speaker), {}).values(), key=lambda r: -r["at"])
        return [{k: v for k, v in r.items() if k != "at"} for r in working] + [dict(r) for r in (rows or [])]

    async def hold_belief_about_speaker(self, *, speaker: str, subject: str, relation: str,
                                        obj: Optional[str], polarity: str, surface: str,
                                        context: str = "personal", organization: Optional[str] = None) -> None:
        """What a person said about themselves, in the context it came through; a restatement replaces it. Not
        remembered, held in working memory instead."""
        from core.memory.remembering import remembered
        if not remembered():
            self._working_speaker.setdefault(str(speaker), {})[(subject, relation)] = {
                "subject": subject, "relation": relation, "object": obj, "polarity": polarity, "surface": surface,
                "context": context, "organization": organization, "at": time.time()}
            return
        await self.ensure_user_beliefs()
        await self._memory_db().execute_query(
            """
            INSERT INTO unified.user_beliefs
                (speaker, subject, relation, object, polarity, surface, context, organization, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now())
            ON CONFLICT (speaker, subject, relation) DO UPDATE SET
                object = EXCLUDED.object, polarity = EXCLUDED.polarity,
                surface = EXCLUDED.surface, context = EXCLUDED.context,
                organization = EXCLUDED.organization, updated_at = now()
            """,
            (speaker, subject, relation, obj, polarity, surface, context, organization),
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
        # A statement carries at most 32,767 values; a sweep of 6,077 rows at
        # eleven each carried 66,847, and the whole record of it was refused
        # after what it recorded had been done. Written in as many statements
        # as that takes.
        per_statement = 32767 // 11
        for start in range(0, len(rows), per_statement):
            values, params = [], []
            for i, row in enumerate(rows[start:start + per_statement]):
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
        newly recorded, not the ones asked about. Nothing is recorded where what happens now is
        not remembered (`core.memory.remembering`): a use no one keeps is no record."""
        from core.memory.remembering import remembered
        if not remembered():
            return []
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
        from core.memory.remembering import remembered
        if not remembered():
            return ""
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
        # THE LIFT, for an experience there is something to learn from: what its
        # tasks did, compared with tasks of the same shape done before.
        if decision["standing"] in ("candidate", "already held") and item["memory_id"]:
            decision["lift"] = await self._lift(item)
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
    # THE LIFT (MEMORY_AGENT_MAP §10.2)
    # ================================================================================================
    #
    # A method is what a task did: its steps, each a tool with its arguments.
    #
    #   FROM THE FIRST TASK THAT WORKED   the first task of a shape (`unified_learning_system.shape_of`)
    #                  whose outcome the credit gate counts and that worked is
    #                  lifted at once (`lift.lift_one`), into the world's METHOD
    #                  MEMORY: what Lyric overcame for one person it can do again,
    #                  for them and for anyone (SEPARATION_MAP §11.4). What it keeps
    #                  as a constant is no one's particular (`_no_ones`): its tools'
    #                  own vocabulary (a truth value, a value the tool declares the
    #                  argument takes) and what the world holds a thing under; every
    #                  other value -- a path, a text, a name -- was that task's and
    #                  is a variable, so nothing of the person is in it. What its
    #                  fix changed (`causal_rules`), where it is no one's, is kept
    #                  on the method (`fixes`), so a later task meets it before it
    #                  meets the failure (`Capabilities.known_fix`).
    #   tasks that waited   a task of the shape that did not work, or whose outcome
    #                  did not count, before anything of the shape worked, waits;
    #                  when the method forms, each that is an instance of it is a
    #                  witness of it.
    #   later tasks    an instance is one more witness; a task that worked and is
    #                  not an instance widens it (`rule_induction.generalize_sequence`); a failure that
    #                  is not an instance says nothing of it.
    #   a person's own   when a person's task and an earlier one of theirs, both
    #                  instances of the world's method, have in common something
    #                  only they supplied (`person_residue`), what they have in common
    #                  is their own method, in their context, beside the world's.
    #
    # Every task that is an instance of a method is one witness of whether it
    # works, counted once (its occurrence id is kept on the method) and only when
    # the credit gate counts its outcome. The belief is the learning authority's
    # (`observe_method_outcome`); the memory agent keeps no second judge.
    #
    # Lifted from the steps a task declared (its `method`). A learned operator's
    # acts are lifted by rule induction already, from demonstrations.

    METHOD_SCHEMA = "method_v1"
    METHOD_TAGS = ("method", "lifted")
    _method_index_ready = False

    async def _ensure_method_index(self) -> None:
        """Method memories are found by their shape."""
        if MemoryAgent._method_index_ready:
            return
        db = self._memory_db()
        for store in db.schema_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                name = table.split(".")[0] + "_method_shape_idx"
                await db.execute_query(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {table}"
                    " ((thinking_state->'raw_event'->'method'->>'shape'))",
                    commit=True, store=store)
        MemoryAgent._method_index_ready = True

    async def _method_memory(self, shape: str, owner: Optional[str]):
        """The method memory of this shape that `owner` holds (None: the world's),
        as (memory_id, record, thinking_state), or None."""
        from core.database.releases import SUBSTRATE_OWNERS
        await self._ensure_method_index()
        db = self._memory_db()
        owners = list(SUBSTRATE_OWNERS) if owner is None else [str(owner)]
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                row = await db.execute_query(
                    f"SELECT memory_id, thinking_state FROM {table}"
                    " WHERE thinking_state->'raw_event'->'method'->>'shape' = $1"
                    "   AND thinking_state->'raw_event'->>'schema' = $2"
                    "   AND COALESCE(user_id, '') = ANY($3::text[])"
                    " ORDER BY created_at LIMIT 1",
                    (shape, self.METHOD_SCHEMA, owners), fetch_one=True, store=store)
                if row is not None:
                    thinking_state = row["thinking_state"]
                    if isinstance(thinking_state, str):
                        thinking_state = json.loads(thinking_state)
                    thinking_state = thinking_state or {}
                    return row["memory_id"], dict(thinking_state.get("raw_event") or {}), thinking_state
        return None

    @staticmethod
    def _method_account(record: Dict[str, Any]) -> str:
        """What a method memory says: the steps, what it overcame, and how often
        it was seen."""
        method = record.get("method") or {}
        seen = len(record.get("instances") or {})
        overcame = "".join(
            f" Where {', '.join(fix.get('failed_tools') or []) or 'a step'} failed, it set "
            + ", ".join(f"{use['tool']} {use['arg']} to {use['value']!r}" for use in fix.get("use") or []) + "."
            for fix in record.get("fixes") or [])
        return ("A way of working, lifted from tasks that worked: "
                + "; then ".join(method.get("steps") or []) + "." + overcame
                + (f" Seen {seen} times." if seen else ""))

    async def _form_method(self, shape: str, general, owner: Optional[str],
                           fixes: Sequence[Dict[str, Any]] = ()) -> str:
        """Keep a lifted method as a memory, the world's or `owner`'s, with the
        fixes it overcame failures by."""
        from core.learning.rule_induction import formulas
        from core.memory.utils.interfaces import MemoryType, Origin
        record = {"event": "method", "schema": self.METHOD_SCHEMA,
                  "method": {"shape": shape, "steps": formulas(general)},
                  "fixes": list(fixes), "instances": {}}
        stored, memory_id = await self.store_memory(
            self._method_account(record), memory_type=MemoryType.PROCEDURAL,
            tags=list(self.METHOD_TAGS), thinking_state={"raw_event": record},
            origin=Origin.of(owner, "lift"))
        if not stored or not memory_id:
            raise RuntimeError(f"the method lifted for {shape} could not be kept")
        return memory_id

    async def _rewrite_method(self, memory_id: str, record: Dict[str, Any],
                              thinking_state: Dict[str, Any]) -> None:
        account = self._method_account(record)
        updates: Dict[str, Any] = {"thinking_state": {**(thinking_state or {}), "raw_event": record},
                                   "content": account}
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(account)
            if embedding:
                updates["embedding"] = embedding
        if not await self.postgres_storage.update_memory(memory_id, updates):
            raise RuntimeError(f"method memory {memory_id} could not be written")

    async def _waiting_of_shape(self, shape: str, other_than: str) -> List[Dict[str, Any]]:
        """The tasks of this shape, from other pursuits, that wait for a method
        of it: each its pool item, store and entry, oldest first."""
        db = self._memory_db()
        probe = json.dumps({"lift": {"waiting": [{"shape": shape}]}})
        waiting: List[Dict[str, Any]] = []
        for store in db.maintained_stores():
            rows = await db.execute_query(
                "SELECT item_id, decision FROM unified.experience_pool"
                " WHERE status = 'decided' AND decision @> $1::jsonb ORDER BY decided_at",
                (probe,), fetch_all=True, store=store) or []
            for row in rows:
                decision = row["decision"] if isinstance(row["decision"], dict) else json.loads(row["decision"])
                for entry in (decision.get("lift") or {}).get("waiting") or []:
                    if entry.get("shape") == shape and entry.get("memory_id") != other_than:
                        waiting.append({"item_id": row["item_id"], "store": store, "entry": entry})
        return waiting

    async def _stop_waiting(self, waiting: Dict[str, Any], method_id: str, *, instance: bool) -> None:
        """A waiting task met the method of its shape: its pool item says which,
        and whether the task was an instance of it (a witness) or not (apart)."""
        db = self._memory_db()
        row = await db.execute_query(
            "SELECT decision FROM unified.experience_pool WHERE item_id = $1",
            (waiting["item_id"],), fetch_one=True, store=waiting["store"])
        if row is None:
            return
        decision = row["decision"] if isinstance(row["decision"], dict) else json.loads(row["decision"])
        lift = decision.setdefault("lift", {})
        lift["waiting"] = [e for e in lift.get("waiting") or [] if e.get("occurrence") != waiting["entry"]["occurrence"]]
        lift.setdefault("instances" if instance else "apart", []).append(
            {"occurrence": waiting["entry"]["occurrence"], "method": method_id,
             "memory_id": waiting["entry"]["memory_id"]})
        await db.execute_query(
            "UPDATE unified.experience_pool SET decision = $1::jsonb WHERE item_id = $2",
            (json.dumps(decision), waiting["item_id"]), commit=True, store=waiting["store"])

    async def _earlier_instance(self, owner: str, method_id: str, other_than: str) -> Optional[Dict[str, Any]]:
        """The latest earlier task of `owner`'s that was an instance of this
        method, as its pool entry ({occurrence, method}), or None."""
        db = self._memory_db()
        probe = json.dumps({"lift": {"instances": [{"method": method_id}]}})
        for store in db.maintained_stores():
            rows = await db.execute_query(
                "SELECT decision FROM unified.experience_pool"
                " WHERE owner = $1 AND status = 'decided' AND decision @> $2::jsonb"
                " ORDER BY decided_at DESC", (str(owner), probe), fetch_all=True, store=store) or []
            for row in rows:
                decision = row["decision"] if isinstance(row["decision"], dict) else json.loads(row["decision"])
                for entry in reversed((decision.get("lift") or {}).get("instances") or []):
                    if entry.get("method") == method_id and entry.get("occurrence") != other_than:
                        return entry
        return None

    async def _task_of(self, memory_id: str, occurrence_id: str):
        """A task held in a pursuit memory: (its occurrence, the pursuit's owner,
        what its person supplied or None), or None when it is gone."""
        from core.learning.unified_learning_system import person_terms
        from core.memory.utils.interfaces import task_occurrences
        record, _ = await self._pursuit_record(memory_id)
        if not record:
            return None
        for index, occurrence in enumerate(task_occurrences(record)):
            if self._occurrence_id(memory_id, occurrence, index) == occurrence_id:
                owner = self._pursuit_owner(record)
                parts = (record.get("experience") or {}).get("parts") or []
                return occurrence, owner, (person_terms(parts) if owner else None)
        return None

    @staticmethod
    def _occurrence_id(memory_id: str, occurrence: Dict[str, Any], index: int) -> str:
        return f"{memory_id}#{occurrence.get('task_id') or index}"

    @staticmethod
    def _category_of(occurrence: Dict[str, Any]) -> str:
        """The kind of work a task was (`work_category`), as its occurrence keeps it. One kept before the kinds were
        told apart (2026-10-12) was a task asked for on its own: no request named a project or a workflow before."""
        return str(occurrence.get("category") or "tasks")

    @staticmethod
    def _counted(occurrence: Dict[str, Any]) -> Tuple[bool, bool]:
        """(counted, worked): whether the credit gate counts this task's outcome,
        and whether it worked, from the verdict kept with it."""
        from core.learning.meta_learning import OutcomeClass, is_credit_eligible
        verdict = occurrence.get("verdict") or {}
        try:
            counted = is_credit_eligible(OutcomeClass(verdict.get("outcome_class")))
        except ValueError:
            counted = False
        return counted, bool(verdict.get("success"))

    async def _witness(self, memory_id: str, record: Dict[str, Any], thinking_state: Dict[str, Any],
                       instances: List[Tuple[str, Dict[str, Any], Optional[str]]], *, world: bool) -> int:
        """Count each task (occurrence id, occurrence, its person) once on the
        method, then hand each counted outcome to the learning authority. The
        method is written first: an outcome lost between the two is not counted,
        and one counted twice could not be taken back.

        WHEN A STANDING CROSSES, IT IS RECORDED: the world's on the method's own
        record (`standing`), a person's in their own context (`_note_person`).
        Each is a list of {settled, at}: settled in favour from that moment, or
        no longer. Unlocked and withdrawn are read from these by the
        capabilities faculty, which owns what they mean."""
        from core.capabilities import settled_in_favour
        from core.integration.universal_domain_master import UniversalDomainMaster
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import get_learning_authority
        held = record.setdefault("instances", {})
        fresh = []
        for occurrence_id, occurrence, person in instances:
            if occurrence_id in held:
                continue
            counted, worked = self._counted(occurrence)
            # The reward this experience carried (`_evaluate_outcome`), kept with
            # the instance; it counts toward the capability's reward only where
            # the outcome counts.
            reward = (occurrence.get("reward") or {}).get("valence")
            held[occurrence_id] = {"counted": counted, "worked": worked,
                                   **({"reward": float(reward)} if reward is not None else {})}
            if counted:
                fresh.append((occurrence_id, worked, person, reward, self._category_of(occurrence)))
        await self._rewrite_method(memory_id, record, thinking_state)
        authority = get_learning_authority()
        claim = authority.method_claim(memory_id)
        for occurrence_id, worked, person, reward, category in fresh:
            world_before = person_before = None
            if world:
                belief = authority.belief_for_claim(claim)
                world_before = settled_in_favour(belief.posterior_probability if belief else None)
            if person:
                mine = await get_scoped_context_store().belief(person, claim)
                person_before = settled_in_favour(mine["posterior"] if mine else None)
            moved = {}
            if world:
                moved["world"] = await authority.observe_method_outcome(
                    memory_id, worked=worked, observation=occurrence_id, owner=person, category=category)
            if person:
                # How the method goes in this person's work: their belief, in their context.
                moved["person"] = await self.hold_belief_for_person(
                    person, claim, domain="methods", supports=worked,
                    quality=UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY, source="experience")
            now = datetime.now().isoformat()
            if world and settled_in_favour(moved.get("world")) != world_before:
                fresh_record, fresh_state = await self._pursuit_record(memory_id)
                history = fresh_record.setdefault("standing", [])
                history.append({"settled": settled_in_favour(moved.get("world")), "at": now})
                await self._rewrite_method(memory_id, fresh_record, fresh_state)
                record["standing"] = history
            if person:
                crossed = settled_in_favour(moved.get("person")) != person_before
                if crossed or reward is not None:
                    await self._note_person(person, memory_id, at=now,
                                            settled=settled_in_favour(moved.get("person")) if crossed else None,
                                            reward=reward)
        return len(fresh)

    STANDING_SCHEMA = "standing_v1"

    async def _standing_memory(self, person: str, method_id: str):
        """A person's record of how their standing in a method moved, as
        (memory_id, record, thinking_state), or None."""
        db = self._memory_db()
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                row = await db.execute_query(
                    f"SELECT memory_id, thinking_state FROM {table}"
                    " WHERE thinking_state->'raw_event'->>'schema' = $1"
                    "   AND thinking_state->'raw_event'->>'method' = $2 AND user_id = $3"
                    " ORDER BY created_at LIMIT 1",
                    (self.STANDING_SCHEMA, method_id, str(person)), fetch_one=True, store=store)
                if row is not None:
                    thinking_state = row["thinking_state"]
                    if isinstance(thinking_state, str):
                        thinking_state = json.loads(thinking_state)
                    thinking_state = thinking_state or {}
                    return row["memory_id"], dict(thinking_state.get("raw_event") or {}), thinking_state
        return None

    async def _note_person(self, person: str, method_id: str, *, at: str,
                           settled: Optional[bool] = None, reward: Optional[float] = None,
                           counted: Optional[str] = None) -> None:
        """Record, in the person's own context, how a method has gone in their
        work: when their standing became settled in favour (or stopped being),
        the reward their counted outcomes carried (`reward`: n and sum), and,
        for a world method their work does not go into, each occurrence counted
        in their standing (`counted`, see `_witness_standing`)."""
        from core.memory.utils.interfaces import MemoryType, Origin
        held = await self._standing_memory(person, method_id)
        if held is None:
            record = {"event": "standing", "schema": self.STANDING_SCHEMA, "method": method_id,
                      "history": [] if settled is None else [{"settled": settled, "at": at}],
                      "reward": {"n": 0, "sum": 0.0} if reward is None else {"n": 1, "sum": float(reward)},
                      **({"counted": [counted]} if counted else {})}
            stored, _ = await self.store_memory(
                f"How my way of working {method_id} has gone in your work.",
                memory_type=MemoryType.PROCEDURAL, tags=["standing"],
                thinking_state={"raw_event": record}, origin=Origin.of(person, "lift"))
            if not stored:
                raise RuntimeError(f"the standing of {method_id} could not be kept for its person")
            return
        memory_id, record, thinking_state = held
        if settled is not None:
            record.setdefault("history", []).append({"settled": settled, "at": at})
        if reward is not None:
            totals = record.setdefault("reward", {"n": 0, "sum": 0.0})
            totals["n"] = int(totals.get("n", 0)) + 1
            totals["sum"] = float(totals.get("sum", 0.0)) + float(reward)
        if counted:
            record.setdefault("counted", []).append(counted)
        if not await self.postgres_storage.update_memory(
                memory_id, {"thinking_state": {**(thinking_state or {}), "raw_event": record}}):
            raise RuntimeError(f"standing memory {memory_id} could not be written")

    async def standing_history(self, method_id: str, person: Optional[str]) -> List[Dict[str, Any]]:
        """How a standing in a method has moved: the world's (person None), from
        the method's record, or a person's, from their own context."""
        if person is None:
            record, _ = await self._pursuit_record(method_id)
            return list((record or {}).get("standing") or [])
        held = await self._standing_memory(person, method_id)
        return list((held[1] if held else {}).get("history") or [])

    async def person_reward(self, method_id: str, person: str) -> Optional[float]:
        """The mean reward a person's counted outcomes of a method carried, from
        their own context, or None when none carried one."""
        held = await self._standing_memory(person, method_id)
        totals = (held[1] if held else {}).get("reward") or {}
        return (float(totals["sum"]) / int(totals["n"])) if int(totals.get("n") or 0) else None

    async def methods_held(self, owner: Optional[str]) -> List[Tuple[str, Dict[str, Any]]]:
        """Every method memory `owner` holds (None: the world's), as
        (memory_id, record), oldest first."""
        from core.database.releases import SUBSTRATE_OWNERS
        db = self._memory_db()
        owners = list(SUBSTRATE_OWNERS) if owner is None else [str(owner)]
        held: List[Tuple[str, Dict[str, Any]]] = []
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                rows = await db.execute_query(
                    f"SELECT memory_id, thinking_state->'raw_event' AS record FROM {table}"
                    " WHERE thinking_state->'raw_event'->>'schema' = $1"
                    "   AND COALESCE(user_id, '') = ANY($2::text[])"
                    " ORDER BY created_at", (self.METHOD_SCHEMA, owners), fetch_all=True, store=store) or []
                for row in rows:
                    record = row["record"]
                    held.append((row["memory_id"], json.loads(record) if isinstance(record, str) else dict(record)))
        return held

    @staticmethod
    def _fixes_of(occurrence: Dict[str, Any], kept: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """What a task changed to overcome a failure (its `causal_rules`: where
        these tools failed, this argument set to this value), as fixes a method
        keeps: {failed_tools, use}. For the world's method only the changes to a
        value in `kept` (`_no_ones`); a person's own keeps every change."""
        from core.learning.unified_learning_system import value_text
        fixes = []
        for rule in occurrence.get("causal_rules") or []:
            use = [{"tool": u["tool"], "arg": u["arg"], "value": u.get("value")}
                   for u in (rule or {}).get("use") or []
                   if isinstance(u, dict) and u.get("tool") and u.get("arg")
                   and (kept is None or value_text(u.get("value")) in kept)]
            if use:
                fixes.append({"failed_tools": sorted((rule.get("when") or {}).get("failed_tools") or []),
                              "use": use})
        return fixes

    @staticmethod
    def _add_fixes(record: Dict[str, Any], fixes: Sequence[Dict[str, Any]]) -> None:
        held = record.setdefault("fixes", [])
        for fix in fixes:
            if fix not in held:
                held.append(fix)

    @staticmethod
    def _declared_parameters(tool_name: str) -> Dict[str, Any]:
        """A tool's declared parameters by name, from the tool registry."""
        from core.tools.tool_registry import declared_parameters
        from core.tools.tool_registry import get_tool_registry
        tool = get_tool_registry().get_tool(tool_name)
        return {str(p.name): p for p in declared_parameters(tool)} if tool is not None else {}

    async def _no_ones(self, occurrence: Dict[str, Any], facts) -> Set[str]:
        """The values of a task's method that are no one's particular: its
        tools' own vocabulary (`lift.vocabulary`), and what the world holds a
        thing under (SEPARATION_MAP §11.3: a term the world holds is about the
        world, whoever said it). Every other value -- a path, a text, a name --
        was what that task was about."""
        from core.learning.rule_induction import constant_values
        from core.learning.unified_learning_system import vocabulary
        words = vocabulary(occurrence.get("method"), self._declared_parameters)
        return words | await self._world_holds(constant_values(facts) - words)

    async def _lift_one(self, occurrence: Dict[str, Any], facts):
        """The first task of a shape that worked, as the world's method
        (`lift.lift_one`), and the fixes it keeps: what is no one's particular
        (`_no_ones`) stays, every other value is a variable."""
        from core.learning.unified_learning_system import lift_one
        kept = await self._no_ones(occurrence, facts)
        return lift_one(facts, kept), self._fixes_of(occurrence, kept)

    async def _lift(self, item: Any) -> Dict[str, Any]:
        """Lift what this experience's tasks did (see THE LIFT above). Returns
        what was done, for the item's decision: the tasks that are instances of a
        method, the methods lifted, the tasks still waiting, and the ones apart
        (a failure that is not an instance of the method of its shape)."""
        from core.learning.unified_learning_system import get_learning_authority
        from core.learning.rule_induction import from_formulas, generalize_sequence, is_instance
        from core.learning.unified_learning_system import method_facts, person_terms, shape_of
        from core.memory.utils.interfaces import task_occurrences
        done: Dict[str, Any] = {"instances": [], "lifted": [], "waiting": [], "apart": []}
        memory_id = item["memory_id"]
        record, _ = await self._pursuit_record(memory_id)
        if not record:
            return done
        owner = self._pursuit_owner(record)
        terms = person_terms((record.get("experience") or {}).get("parts") or []) if owner else None
        waiting_here: Dict[str, List[Tuple[str, Dict[str, Any], Optional[str]]]] = {}
        for index, occurrence in enumerate(task_occurrences(record)):
            # WHETHER IT GOES INTO SHARED LEARNING, asked of the learning authority, which holds the owner's switch
            # for each kind of work: a task whose kind its owner has turned off is learned for them alone
            # (`_lift_own`), and nothing of it is written to the world's methods.
            shares = await get_learning_authority().shares_learning(owner, self._category_of(occurrence))
            shape = shape_of(occurrence.get("method"))
            facts = method_facts(occurrence.get("method"))
            if shape is None or facts is None:
                continue
            occurrence_id = self._occurrence_id(memory_id, occurrence, index)
            task = (occurrence_id, occurrence, owner)
            counted, worked = self._counted(occurrence)
            async with self._memory_db().advisory_lock(f"method:{shape}", store="runtime"):
                if not shares:
                    await self._lift_own(shape, facts, task, memory_id, done)
                    continue
                held = await self._method_memory(shape, None)
                if held is None:
                    if not (counted and worked):
                        waiting_here.setdefault(shape, []).append(task)
                        done["waiting"].append({"occurrence": occurrence_id, "shape": shape,
                                                "memory_id": memory_id})
                        continue
                    general, fixes = await self._lift_one(occurrence, facts)
                    method_id = await self._form_method(shape, general, None, fixes)
                    formed = await self._method_memory(shape, None)
                    if formed is None or formed[0] != method_id:
                        raise RuntimeError(f"the method kept for {shape} is not the one found by its shape")
                    # THE TASKS THAT WAITED for it, this experience's own and others', each a witness of it
                    # where it is an instance of it.
                    witnesses = [task]
                    for earlier in waiting_here.pop(shape, []):
                        done["waiting"] = [e for e in done["waiting"] if e["occurrence"] != earlier[0]]
                        if is_instance(general, method_facts(earlier[1].get("method"))):
                            witnesses.append(earlier)
                            done["instances"].append({"occurrence": earlier[0], "method": method_id,
                                                      "memory_id": memory_id})
                        else:
                            done["apart"].append({"occurrence": earlier[0], "method": method_id})
                    for waiting in await self._waiting_of_shape(shape, other_than=memory_id):
                        other = await self._task_of(waiting["entry"]["memory_id"], waiting["entry"]["occurrence"])
                        if other is not None and not await get_learning_authority().shares_learning(
                                other[1], self._category_of(other[0])):
                            # Its owner has turned shared learning off for its kind since: it is no witness of the
                            # world's method, and waits as it was.
                            continue
                        other_facts = method_facts(other[0].get("method")) if other else None
                        instance = bool(other_facts) and is_instance(general, other_facts)
                        if instance:
                            witnesses.append((waiting["entry"]["occurrence"], other[0], other[1]))
                        await self._stop_waiting(waiting, method_id, instance=instance)
                    await self._witness(method_id, formed[1], formed[2], witnesses, world=True)
                    done["lifted"].append({"method": method_id, "shape": shape, "whose": "world",
                                           "from": occurrence_id, "witnesses": len(witnesses)})
                    done["instances"].append({"occurrence": occurrence_id, "method": method_id,
                                              "memory_id": memory_id})
                    if owner is not None:
                        await self._lift_theirs(shape, method_id, memory_id, task, facts, terms, done)
                    continue
                method_id, method_record, thinking_state = held
                general = from_formulas((method_record.get("method") or {}).get("steps") or [])
                if not is_instance(general, facts):
                    if not (counted and worked):
                        done["apart"].append({"occurrence": occurrence_id, "method": method_id})
                        continue
                    widened = generalize_sequence(general, facts)
                    if widened is None:
                        continue
                    method_record["method"]["steps"] = [f.to_formula() for f in widened]
                self._add_fixes(method_record, self._fixes_of(occurrence, await self._no_ones(occurrence, facts)))
                await self._witness(method_id, method_record, thinking_state, [task], world=True)
                done["instances"].append({"occurrence": occurrence_id, "method": method_id,
                                          "memory_id": memory_id})
                if owner is not None:
                    await self._lift_theirs(shape, method_id, memory_id, task, facts, terms, done)
        return done

    async def _lift_theirs(self, shape: str, world_method: str, memory_id: str,
                           task: Tuple[str, Dict[str, Any], Optional[str]], facts, terms: Optional[Set[str]],
                           done: Dict[str, Any]) -> None:
        """A PERSON'S OWN WAY OF WORKING. Their task is an instance of the
        world's method; if an earlier task of theirs was too, and what the two
        have in common keeps something only they supplied (`person_residue`),
        that is their own method, in their context, beside the world's, which
        never holds it. A task that is an instance of their own method is a
        witness of it."""
        from core.learning.rule_induction import (constant_values, from_formulas,
                                                  generalize_sequence, is_instance)
        from core.learning.unified_learning_system import method_facts, person_residue
        occurrence_id, occurrence, owner = task
        theirs = await self._method_memory(shape, owner)
        if theirs is not None:
            method_id, record, thinking_state = theirs
            if is_instance(from_formulas((record.get("method") or {}).get("steps") or []), facts):
                self._add_fixes(record, self._fixes_of(occurrence))
                await self._witness(method_id, record, thinking_state, [task], world=False)
                done["instances"].append({"occurrence": occurrence_id, "method": method_id,
                                          "memory_id": memory_id})
            return
        earlier = await self._earlier_instance(owner, world_method, other_than=occurrence_id)
        if earlier is None or not earlier.get("memory_id"):
            return
        other = await self._task_of(earlier["memory_id"], earlier["occurrence"])
        if other is None or other[1] != owner:
            return
        other_occurrence, _, other_terms = other
        other_facts = method_facts(other_occurrence.get("method"))
        general = generalize_sequence(other_facts, facts) if other_facts else None
        if general is None or not person_residue(constant_values(general), [other_terms, terms]):
            return
        fixes = self._fixes_of(other_occurrence)
        method_id = await self._form_method(
            shape, general, owner, fixes + [fix for fix in self._fixes_of(occurrence) if fix not in fixes])
        formed = await self._method_memory(shape, owner)
        if formed is None or formed[0] != method_id:
            raise RuntimeError(f"the method kept for {shape} is not the one found by its shape")
        await self._witness(method_id, formed[1], formed[2],
                            [(earlier["occurrence"], other_occurrence, owner), task], world=False)
        done["lifted"].append({"method": method_id, "shape": shape, "whose": "person",
                               "from": [earlier["occurrence"], occurrence_id]})
        done["instances"].append({"occurrence": occurrence_id, "method": method_id, "memory_id": memory_id})

    async def _lift_own(self, shape: str, facts, task: Tuple[str, Dict[str, Any], Optional[str]],
                        memory_id: str, done: Dict[str, Any]) -> None:
        """THE LIFT FOR A TASK WHOSE OWNER HAS TURNED SHARED LEARNING OFF FOR ITS KIND. What it did is learned for
        them alone, in their context: their own method of its shape, from their first task of it that worked,
        witnessed or widened by the ones after. A world method their task is an instance of moves their own standing
        in it (`_witness_standing`). Nothing is written to the world's methods, their fixes or their belief."""
        from core.learning.rule_induction import from_formulas, generalize_sequence, is_instance
        occurrence_id, occurrence, owner = task
        counted, worked = self._counted(occurrence)
        theirs = await self._method_memory(shape, owner)
        if theirs is not None:
            method_id, record, thinking_state = theirs
            general = from_formulas((record.get("method") or {}).get("steps") or [])
            if not is_instance(general, facts):
                if not (counted and worked):
                    done["apart"].append({"occurrence": occurrence_id, "method": method_id})
                    return
                widened = generalize_sequence(general, facts)
                if widened is None:
                    return
                record["method"]["steps"] = [f.to_formula() for f in widened]
            self._add_fixes(record, self._fixes_of(occurrence))
            await self._witness(method_id, record, thinking_state, [task], world=False)
            done["instances"].append({"occurrence": occurrence_id, "method": method_id, "memory_id": memory_id})
            return
        world = await self._method_memory(shape, None)
        if world is not None and is_instance(from_formulas((world[1].get("method") or {}).get("steps") or []), facts):
            await self._witness_standing(world[0], task)
            done["instances"].append({"occurrence": occurrence_id, "method": world[0], "memory_id": memory_id})
            return
        if not (counted and worked):
            return
        general, _ = await self._lift_one(occurrence, facts)
        method_id = await self._form_method(shape, general, owner, self._fixes_of(occurrence))
        formed = await self._method_memory(shape, owner)
        if formed is None or formed[0] != method_id:
            raise RuntimeError(f"the method kept for {shape} is not the one found by its shape")
        await self._witness(method_id, formed[1], formed[2], [task], world=False)
        done["lifted"].append({"method": method_id, "shape": shape, "whose": "person", "from": occurrence_id,
                               "witnesses": 1})
        done["instances"].append({"occurrence": occurrence_id, "method": method_id, "memory_id": memory_id})

    async def _witness_standing(self, method_id: str, task: Tuple[str, Dict[str, Any], Optional[str]]) -> None:
        """One task whose owner has turned shared learning off for its kind, as a witness of a world method in their own
        standing only: their belief in it moves in their context, counted once. The occurrence is kept on their
        standing record, since the world's method, where it is otherwise kept, is not theirs to write."""
        from core.capabilities import settled_in_favour
        from core.integration.universal_domain_master import UniversalDomainMaster
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.learning.unified_learning_system import get_learning_authority
        occurrence_id, occurrence, owner = task
        counted, worked = self._counted(occurrence)
        held = await self._standing_memory(owner, method_id)
        if not counted or (held is not None and occurrence_id in (held[1].get("counted") or [])):
            return
        reward = (occurrence.get("reward") or {}).get("valence")
        # Counted first: an outcome lost between the two is not counted, and one counted twice could not be taken
        # back (as `_witness`).
        await self._note_person(owner, method_id, at=datetime.now().isoformat(), reward=reward,
                                counted=occurrence_id)
        claim = get_learning_authority().method_claim(method_id)
        mine = await get_scoped_context_store().belief(owner, claim)
        before = settled_in_favour(mine["posterior"] if mine else None)
        moved = await self.hold_belief_for_person(
            owner, claim, domain="methods", supports=worked,
            quality=UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY, source="experience")
        if settled_in_favour(moved) != before:
            await self._note_person(owner, method_id, at=datetime.now().isoformat(),
                                    settled=settled_in_favour(moved))

    #: How far up its kinds a thing is followed when asking whether a fact is held of it: deeper than any chain of
    #: kinds WordNet has (19 at most).
    KINDS_FOLLOWED = 24
    #: How far up its kinds a thing is followed when asking what it is connected to: near enough that two things
    #: meeting there are about the same thing (a bank of a river and the river), not as far as `entity`, where
    #: everything meets.
    KINDS_NEAR = 2

    # ================================================================================================
    # WHAT WORDS ARE SAID OF
    # ================================================================================================
    #
    # "Red wine", "ate the bread": not facts about wine or bread, but how English uses "red" and "eat". A listener
    # goes by it where nothing it knows tells two things a word names apart (Resnik 1997): red is said of physical
    # things, so the table that is red is the furniture, not the array. ONE MEMORY FOR EACH WORD, RELATION AND
    # SIDE, holding every word and thing it has been said of, with how often, and each observation counted, so the
    # same source again moves nothing.

    # WHAT THE LISTENER COUNTED ===================================================================================
    #
    # What each piece of the listener's evidence is worth, as it counted it on sentences whose meaning it was taught
    # (`derived_reader.listening_counts`). ONE MEMORY, the one the counts' beliefs are about: a belief names the
    # memory it is a stance on, or it is not stored.

    LISTENING_TAG = "listening"

    async def listening_memory(self) -> Optional[str]:
        """The memory of what the listener counted, its id; None until it has counted anything."""
        from core.database.releases import SUBSTRATE_OWNERS
        db = self._memory_db()
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                rows = await db.execute_query(
                    f"SELECT memory_id FROM {table}"
                    " WHERE tags @> $1::jsonb AND COALESCE(user_id, '') = ANY($2::text[])"
                    " ORDER BY created_at LIMIT 1",
                    (json.dumps([self.LISTENING_TAG]), list(SUBSTRATE_OWNERS)), fetch_all=True, store=store) or []
                if rows:
                    return rows[0]["memory_id"]
        return None

    SAID_OF_TAG = "said_of"

    async def _said_memories(self) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
        """The memories of what words are said of, read back as the view (`_said_view`)."""
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        rows = await self._rows_tagged(self.SAID_OF_TAG)
        view: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in rows:
            await give_way()
            said = (row.metadata or {}).get("said") or {}
            key = (str(said.get("relation") or ""), str(said.get("word") or ""), str(said.get("side") or ""))
            if not all(key):
                continue
            view[key] = {"memory_id": row.memory_id,
                         "words": dict(said.get("words") or {}), "things": dict(said.get("things") or {}),
                         "seen": {tuple(seen) for seen in said.get("seen") or ()}}
        return view

    async def remember_said(self, uses, progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Remember what words are said of. `uses`: `(relation, word, side, other, times, observation, named)`: the
        word stands on `side` ("subject" or "object") of the relation and `other` on the far side, met `times`
        times, as `observation` saw it; `named` is "word" where `other` is a word whose sense was not given (a
        corpus: "red wine") and "thing" where it is the thing itself (a sentence taught with its meaning). Each
        observation is counted once, however often it is told. Returns counts: `remembered` (memories formed or
        added to), `already` (uses held from that observation), `total`. `progress(done, of)` is told every 1,000
        words: a whole source's are hours of writing, and a pass that says nothing for them reads as stuck."""
        from core.memory.utils.interfaces import Origin
        if not self._word_classes_warm:
            await self.warm_word_classes()
        grouped: Dict[Tuple[str, str, str], List[Tuple[str, int, str, str]]] = {}
        counts = {"remembered": 0, "already": 0, "total": 0}
        for relation, word, side, other, times, observation, named in uses:
            counts["total"] += 1
            key = (str(relation), str(word).strip().lower(), str(side))
            grouped.setdefault(key, []).append((str(other).strip().lower(), int(times), str(observation),
                                                "things" if named == "thing" else "words"))
        for done, (key, said) in enumerate(grouped.items(), 1):
            if progress is not None and done % 1000 == 0:
                progress(done, len(grouped))
            held = self._said_view.get(key) or {"memory_id": None, "words": {}, "things": {}, "seen": set()}
            fresh = [(other, times, observation, kind) for other, times, observation, kind in said
                     if (observation, other) not in held["seen"]]
            counts["already"] += len(said) - len(fresh)
            if not fresh:
                continue
            for other, times, observation, kind in fresh:
                held[kind][other] = held[kind].get(other, 0) + times
                held["seen"].add((observation, other))
            relation, word, side = key
            most = sorted({**held["words"], **held["things"]}.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
            content = (f'"{word}" ({relation}, {side}) is said of '
                       + ", ".join(f"{other} ({times})" for other, times in most))
            record = {"said": {"relation": relation, "word": word, "side": side, "words": held["words"],
                               "things": held["things"], "seen": sorted(map(list, held["seen"]))}}
            if held["memory_id"] is None:
                stored, memory_id = await self.store_memory(
                    content=content, memory_type=MemoryType.SEMANTIC,
                    confidence_score=0.9, tags=["language", self.SAID_OF_TAG], source_context=record,
                    origin=Origin.own("teaching"))
                if not stored or not memory_id:
                    raise RuntimeError(f"what {key[1]!r} is said of was not kept: the memory was declined")
                held["memory_id"] = memory_id
            elif not await self.update_memory(held["memory_id"], {"content": content, "metadata": record,
                                                                  "metadata.merge": True}):
                raise RuntimeError(f"what {key[1]!r} is said of was not updated in {held['memory_id']}")
            # The view is kept in step with the memory it is a view of; the kinds words are said of are worked out
            # again when next asked.
            self._said_view[key] = held
            self._said_spread.pop((relation, side), None)
            counts["remembered"] += 1
        return counts

    # HOW THE WORDS OF A SENTENCE GO TOGETHER. A sentence analysed by hand (a treebank's: each word's class, the
    # word it depends on and as what) is kept whole, ONE MEMORY FOR EACH USE of a sentence, as it was analysed, and
    # read as memory-based learning reads examples: each decision by what the sentences held did in the most
    # specific situation like it they met (`structure.StructureView`). Nothing is reduced to rules when it is kept.

    STRUCTURE_TAG = "analysed_sentence"

    async def _analysed_memories(self, groups=None):
        """The sentences held as analysed, read back as the view (`structure_view`), each word's groups beside it where
        groups are held (`_word_group_memories`)."""
        from core.semantics.structure import Analysed
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        view = self._new_structure_view(groups)
        for row in await self._rows_tagged(self.STRUCTURE_TAG):
            await give_way()
            analysed = (row.metadata or {}).get("analysed")
            if analysed:
                view.add(Analysed.from_dict(analysed))
        return view

    def structure_view(self):
        """The sentences held as analysed, as the reader reads them. Synchronous; empty before the first warm."""
        if self._structure_view is None:
            self._structure_view = self._new_structure_view(self.word_groups())
        return self._structure_view

    def _new_structure_view(self, groups=None):
        """An empty structure view that asks what memory holds of a word no sentence held used
        (`StructureView.held_classes`): measured on main both ways, it read the treebank's held-out parts and the
        lessons better than the words' endings alone (2026-10-16 (10)); and stands each word's groups beside it
        where memory holds word groups (`StructureView.grouping`): learned from EWT, it read EWT dev and PUD nearly a
        point better with them (`experiments/GROUPS-01`); from every treebank taught, 0.1 point better, and GUM's
        held-out test 0.6 (`experiments/STRUCTURE-03`)."""
        from core.semantics.structure import StructureView
        view = StructureView()
        view.held_classes = self._held_word_classes
        if groups is not None:
            view.group_by(groups.grouping())
        return view

    # WHICH WORDS KEEP THE SAME COMPANY. Words grouped by the company they keep in a great deal of text, counted
    # (`word_groups.counted_groups`), are kept ONE MEMORY FOR EACH GROUP, its words whole; the structure reader weighs
    # a word it met rarely or never by its group (`StructureView.grouping`).

    WORD_GROUP_TAG = "word_group"

    async def _word_group_memories(self):
        """The word groups held, read back as the view (`word_groups`)."""
        from core.semantics.word_groups import WordGroup, WordGroups
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        groups = WordGroups()
        for row in await self._rows_tagged(self.WORD_GROUP_TAG):
            await give_way()
            data = (row.metadata or {}).get("word_group")
            if data:
                groups.hold(WordGroup.from_dict(data))
        return groups

    def word_groups(self):
        """The word groups memory holds. Synchronous; empty before the first warm."""
        if self._word_groups is None:
            from core.semantics.word_groups import WordGroups
            self._word_groups = WordGroups()
        return self._word_groups

    # THE FORMS A WORD IS WRITTEN IN. Each word of a treebank analysed by hand is given its base form and what form
    # it is; kept ONE MEMORY FOR EACH BASE WORD, every form the treebank wrote it in, and read by the language view
    # for a word it holds nothing of ("hired" is `hire`: `PatternInventory.names_of_shape`).

    WORD_FORMS_TAG = "word_forms"

    async def _word_form_memories(self):
        """The word forms held, read back as the view (`word_forms`)."""
        from core.semantics.word_forms import HeldForms, WordForms
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        forms = HeldForms()
        for row in await self._rows_tagged(self.WORD_FORMS_TAG):
            await give_way()
            data = (row.metadata or {}).get("word_forms")
            if data:
                forms.hold(WordForms.from_dict(data))
        return forms

    def word_forms(self):
        """The word forms memory holds. Synchronous; empty before the first warm."""
        if self._word_forms is None:
            from core.semantics.word_forms import HeldForms
            self._word_forms = HeldForms()
        return self._word_forms

    async def remember_word_forms(self, forms, progress: Optional[Callable[[int, int], None]] = None
                                  ) -> Dict[str, Any]:
        """Remember the forms words are written in (`word_forms.WordForms`), one memory each base word; one held
        already is not held again. The language view reads a word by them from now on. Returns `kept` and counts, as
        `remember_argued`."""
        held = await self._remember_whole(
            forms, view=self.word_forms, tag=self.WORD_FORMS_TAG, field="word_forms", progress=progress,
            content=lambda item: item.said(), add=lambda view, item: view.hold(item))
        self.pattern_inventory().held_forms = self.word_forms().bases_of
        return held

    async def remember_word_groups(self, groups, progress: Optional[Callable[[int, int], None]] = None
                                   ) -> Dict[str, Any]:
        """Remember word groups (`word_groups.WordGroup`), one memory each; one held already is not held again. The
        structure view stands the groups held beside each word from now on. Returns `kept` and counts, as
        `remember_argued`."""
        held = await self._remember_whole(
            groups, view=self.word_groups, tag=self.WORD_GROUP_TAG, field="word_group", progress=progress,
            content=lambda item: item.said(), add=lambda view, item: view.hold(item))
        if held["remembered"]:
            self.structure_view().group_by(self.word_groups().grouping())
        return held

    def _held_word_classes(self, word: str) -> Dict[str, int]:
        """What memory holds of a word's classes, by the treebank's names, from the reader's view as it is now
        (`structure.held_classes`): the word-class view is rebuilt at each warm, so it is looked up when asked."""
        from core.semantics.structure import held_classes
        return held_classes(self.pattern_inventory())(word)

    async def remember_analysed(self, analysed, progress: Optional[Callable[[int, int], None]] = None
                                ) -> Dict[str, Any]:
        """Remember sentences as they were analysed (`structure.Analysed`), one memory each; a use of a sentence held
        already is not held again. Returns `kept` (each analysis newly held, with its memory's id), and counts:
        `remembered`, `already`, `total`. `progress(done, of)` is told every 1,000 sentences."""
        from core.memory.utils.interfaces import Origin
        if not self._word_classes_warm:
            await self.warm_word_classes()
        view = self.structure_view()
        analysed = list(analysed)
        kept: List[Tuple[Any, str]] = []
        counts = {"remembered": 0, "already": 0, "total": len(analysed)}
        for done, item in enumerate(analysed, 1):
            if progress is not None and done % 1000 == 0:
                progress(done, len(analysed))
            if item.key() in view:
                counts["already"] += 1
                continue
            stored, memory_id = await self.store_memory(
                content=item.said(), memory_type=MemoryType.SEMANTIC, confidence_score=0.9,
                tags=["language", self.STRUCTURE_TAG], source_context={"analysed": item.to_dict()},
                origin=Origin.own("teaching"))
            if not stored or not memory_id:
                raise RuntimeError(f"{item.text!r} as analysed was not kept: the memory was declined")
            view.add(item)
            kept.append((item, memory_id))
            counts["remembered"] += 1
        return {"kept": kept, **counts}

    # WHICH PHRASES ARE A HAPPENING'S ARGUMENTS, AND WHAT A SENTENCE MEANS COMPOSED. A sentence whose happenings'
    # arguments were annotated by hand (PropBank's, `argument_structure.Argued`) is kept whole, one memory for each,
    # as is each sentence of the lessons and of the Parallel Meaning Bank with the meaning it was taught to have
    # (`composition.TaughtSentence`, the PMB's with where each term is said); the composer learns from both
    # (`composition.CompositionView`), each sentence read with the structure and names memory has when it is learned
    # from. Nothing is reduced to rules when it is kept.

    ARGUED_TAG = "argued_sentence"
    TAUGHT_SENTENCE_TAG = "taught_sentence"

    async def _argued_memories(self):
        """The sentences held with their happenings' arguments, read back as the view (`argument_view`)."""
        from core.semantics.argument_structure import ArgumentStructureView, Argued
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        view = ArgumentStructureView()
        for row in await self._rows_tagged(self.ARGUED_TAG):
            await give_way()
            argued = (row.metadata or {}).get("argued")
            if argued:
                view.hold(Argued.from_dict(argued))
        return view

    async def _composition_memories(self, arguments):
        """The sentences held with their meanings (the lessons', the PMB's), as the composer's view
        (`composition_view`), the arguments behind them, and each of them as held, which English's grammar learns from
        (`grammar_view`); each is read when the view is first asked."""
        from core.semantics.composition import CompositionView, TaughtSentence
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        view = CompositionView(arguments if len(arguments) else None, lay_out=self.lay_out)
        held: List[Any] = []
        self._grammar_learned = {}
        for row in await self._rows_tagged(self.TAUGHT_SENTENCE_TAG):
            await give_way()
            taught = (row.metadata or {}).get("taught")
            if taught:
                item = TaughtSentence.from_dict(taught)
                view.hold(item)
                held.append(item)
                # WHAT THE GRAMMAR LEARNED FROM IT, kept with it (`keep_grammar_learning`), and the rules it was
                # learned under: taken where they are the grammar's now (`grammar_view`).
                kept = (row.metadata or {}).get("grammar_learned") or {}
                self._grammar_learned[item.key()] = (row.memory_id, kept.get("counted"), kept.get("rules"))
        return view, held

    # WHAT EACH WORD TAKES BESIDE THE WORDS AROUND IT. A sentence derived by hand in a categorial grammar (the PMB's
    # checked CCG derivations, `grammar.Derived`: each word's category in its sentence, its part of speech, lemma,
    # sense and roles, how the words were combined) is kept whole, one memory each; English's grammar counts what each
    # says a word takes beside the words around it (`Lexicon.hear_derived`). Nothing is reduced to rules when it is
    # kept.

    DERIVED_TAG = "derived_sentence"

    async def _derived_memories(self) -> List[Any]:
        """The sentences held as derived by hand, as memory holds them, for English's grammar (`grammar_view`)."""
        from core.semantics.grammar import Derived
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        held: List[Any] = []
        for row in await self._rows_tagged(self.DERIVED_TAG):
            await give_way()
            data = (row.metadata or {}).get("derived")
            if data:
                held.append(Derived.from_dict(data))
        return held

    async def remember_derived(self, derived, progress: Optional[Callable[[int, int], None]] = None
                               ) -> Dict[str, Any]:
        """Remember sentences as they were derived by hand (`grammar.Derived`), one memory each; one held already is
        not held again, and one held otherwise from the same sentence of the same document is corrected
        (`_correct_whole`). English's grammar chooses each word's category by them from now on. Returns `kept`,
        `corrected` and counts, as `remember_argued`."""
        return await self._remember_whole(
            derived, view=lambda: None, tag=self.DERIVED_TAG, field="derived", progress=progress,
            content=lambda item: item.said(), add=lambda _, item: self._hold_derived(item),
            drop=lambda _, item: self._drop_derived(item))

    def _hold_derived(self, item) -> None:
        """A sentence held as derived by hand, handed to English's grammar."""
        self._grammar_derived.append(item)
        if self._grammar_view is not None:
            self._grammar_view.hold_derived(item)

    RECORD_TAG = "sentence_record"

    async def _record_memories(self) -> List[Tuple[Any, Any]]:
        """The sentences held recorded whole (`teaching_sources.SentenceRecord`), each with its memory's row."""
        from core.learning.teaching_sources import SentenceRecord
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        held: List[Tuple[Any, Any]] = []
        for row in await self._rows_tagged(self.RECORD_TAG):
            await give_way()
            data = (row.metadata or {}).get("record")
            if data:
                held.append((row, SentenceRecord.from_dict(data)))
        return held

    async def remember_records(self, records, progress: Optional[Callable[[int, int], None]] = None
                               ) -> Dict[str, Any]:
        """Remember sentences recorded whole (`teaching_sources.SentenceRecord`: every layer of a sentence by word
        position), ONE MEMORY EACH, and hand each layer to the part of reading that learns from it: the words and
        what each is joined to to the structure reader, each word's form to the forms held, the derivation and the
        meaning to English's grammar and the composer. One held already is not held again; one recorded otherwise
        of the same sentence corrects it (`_correct_whole`). A record whose layers do not hold together
        (`SentenceRecord.problems`) is refused, never held. Returns `kept`, `corrected` and counts, as
        `remember_argued`, and `refused`: each refused record's id and what is wrong with it."""
        records = list(records)
        refused = [(r.id, r.problems()) for r in records if r.problems()]
        whole = [r for r in records if not r.problems()]
        held = await self._remember_whole(
            whole, view=self.composition_view, tag=self.RECORD_TAG, field="record", progress=progress,
            content=lambda item: item.said(), add=self._hold_record, drop=self._drop_record)
        held["refused"] = refused
        return held

    def _hold_record(self, view, record) -> None:
        """A sentence recorded whole, each layer handed to the part of reading that learns from it."""
        self._learn_record_words(record, self._word_class_index)
        self.structure_view().add(record.analysed())
        for item in record.forms():
            self.word_forms().hold(item)
        self._hold_derived(record.derived())
        self._hold_taught(view, record.taught())

    WORD_RECORD_TAG = "word_record"

    async def _word_record_memories(self) -> List[Tuple[Any, Any]]:
        """The words held recorded whole (`teaching_sources.WordRecord`), each with its memory's row."""
        from core.learning.teaching_sources import WordRecord
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        held: List[Tuple[Any, Any]] = []
        for row in await self._rows_tagged(self.WORD_RECORD_TAG):
            await give_way()
            data = (row.metadata or {}).get("word_record")
            if data:
                held.append((row, WordRecord.from_dict(data)))
        return held

    async def remember_word_records(self, records, progress: Optional[Callable[[int, int], None]] = None
                                    ) -> Dict[str, Any]:
        """Remember words recorded whole (`teaching_sources.WordRecord`: every form, every sense, how a verb is used),
        ONE MEMORY EACH, and hand each layer to the part of reading that learns from it: its forms to the forms held,
        its classes and names to the word classes and names memory holds, its frames and its places to English's
        grammar. One held already is not held again; one recorded otherwise corrects it. A record that does not hold
        together (`WordRecord.problems`) is refused, never held. Returns as `remember_records`."""
        records = list(records)
        refused = [(r.word, r.problems()) for r in records if r.problems()]
        whole = [r for r in records if not r.problems()]
        held = await self._remember_whole(
            whole, view=lambda: None, tag=self.WORD_RECORD_TAG, field="word_record", progress=progress,
            content=lambda item: item.said(), add=lambda _, item: self._hold_word_record(item),
            drop=lambda _, item: self._drop_word_record(item))
        held["refused"] = refused
        return held

    def _learn_word_record(self, word, index: Dict[str, Dict[str, int]], forms) -> None:
        """What a word recorded whole says of it, into memory's views: each form a form of the word (`forms`), the
        classes each form is used as (`index`, the word classes memory holds), what the word names as each class
        (`_record_names`)."""
        for item in word.forms_held():
            forms.hold(item)
        for written, classes in word.classes().items():
            bucket = index.setdefault(written, {})
            for cls, n in classes.items():
                bucket[cls] = bucket.get(cls, 0) + n
        for cls, name in word.names().items():
            for f in word.forms:
                if f.word_class == cls:
                    self._record_names.setdefault((f.form.lower(), cls), Counter())[name] += 1

    def _hold_word_record(self, word) -> None:
        """A word recorded whole, each layer handed to the part of reading that learns from it."""
        self._learn_word_record(word, self._word_class_index, self.word_forms())
        self._grammar_words.append(word)
        if self._grammar_view is not None:
            self._grammar_view.hold_word(word)

    def _drop_word_record(self, word) -> None:
        """A word recorded whole, taken back from English's grammar (recorded otherwise since)."""
        key = word.key()
        self._grammar_words = [w for w in self._grammar_words if w.key() != key]
        if self._grammar_view is not None:
            self._grammar_view.drop_word(word)

    def _learn_record_words(self, record, index: Dict[str, Dict[str, int]]) -> None:
        """What a sentence recorded whole says of its words: the class each is used as, written so and as its base,
        into the word classes memory holds (`index`: the conversation asks it whether a word is known, "I don't know
        'fastened' yet", of a word the record taught), and what each word names where one word says a thing of a
        kind (`_record_names`: "medal" names `award decoration`, read as `medal` before; TRAIN-FORMAT-01,
        lyric_dev2, 2026-10-26)."""
        from core.semantics.derived_reader import is_variable
        for w in record.words:
            if w.word_class in ("PUNCTUATION", "SYMBOL"):
                continue
            for written in dict.fromkeys((w.form.lower(), w.lemma.lower())):
                bucket = index.setdefault(written, {})
                bucket[w.word_class] = bucket.get(w.word_class, 0) + 1
        said = dict(record.terms)
        for f in record.facts:
            if f.relation != "instance_of" or not f.positive or is_variable(f.obj):
                continue
            words = said.get(f.subject) or said.get(f.obj) or ()
            if len(words) != 1:
                continue
            w = record.words[words[0]]
            for written in dict.fromkeys((w.form.lower(), w.lemma.lower())):
                self._record_names.setdefault((written, w.word_class), Counter())[f.obj] += 1

    def _drop_record(self, view, record) -> None:
        """A sentence recorded whole, taken back from the parts of reading that learned from it (recorded otherwise
        since). The structure reader and the forms keep the analysis: a use of a sentence, as a corpus counts it."""
        self._drop_derived(record.derived())
        self._drop_taught(view, record.taught())

    def _drop_derived(self, item) -> None:
        """A sentence held as derived by hand, taken back from English's grammar (derived otherwise since)."""
        key = item.key()
        self._grammar_derived = [d for d in self._grammar_derived if d.key() != key]
        if self._grammar_view is not None:
            self._grammar_view.drop_derived(item)

    async def _grammar_knowledge(self) -> List[Tuple[str, str, str]]:
        """What memory holds of things that English's grammar asks of the words it reads (`grammar_words.Knowledge`):
        each thing's kinds (`isa`) and what particular ones are (`instance of`); and, for a thing held as a kind of
        nothing (an adjective's sense: "British"), what its definition is written with (`defined with`: the United
        Kingdom), which the grammar takes as what it is of. Read once a warm, held in this process."""
        rows = await self._memory_db().execute_query(
            "SELECT c1.name AS subject, cr.relation, COALESCE(c2.name, cr.target_surface) AS target"
            " FROM unified.concept_relations cr"
            " JOIN unified.concepts c1 ON c1.concept_id = cr.source_concept_id"
            " LEFT JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
            " WHERE cr.polarity = 'positive' AND (cr.relation IN ('isa', 'is a', 'instance of', 'instance_of')"
            " OR (cr.relation IN ('defined with', 'defined_with') AND NOT EXISTS ("
            "  SELECT 1 FROM unified.concept_relations x WHERE x.source_concept_id = cr.source_concept_id"
            "  AND x.relation IN ('isa', 'is a', 'instance of', 'instance_of'))))",
            fetch_all=True) or []
        return [(str(r["subject"]), "isa" if r["relation"] in ("isa", "is a") else str(r["relation"]),
                 str(r["target"])) for r in rows if r["subject"] and r["target"]]

    def grammar_view(self):
        """English's grammar as memory reads with it (`grammar.GrammarView`): each word as memory holds it (how the
        sentences it holds analysed use it, how memory names it, what memory holds its thing to be:
        `grammar_words.HeldWords`), what the sentences memory holds derived by hand say each word takes beside the
        words around it, and learned from the sentences memory holds with their taught meanings, each with what the
        grammar learned from it before where that was under the grammar's rules now (`GrammarView.rules`).
        Synchronous; built when first asked after a warm (reading the analysed sentences and learning from the taught
        ones takes a while), plain before the first warm."""
        if self._grammar_view is None:
            from core.semantics.grammar import GrammarView, closed_uses
            from core.semantics.grammar_words import GraphKnowledge, HeldWords
            knowledge = GraphKnowledge(classes=self._net_word_classes, names=self._held_name)
            for subject, relation, target in self._grammar_links:
                knowledge.add(subject, relation, target)
            analysed = self._structure_view.analysed() if self._structure_view is not None else ()
            view = GrammarView(HeldWords(analysed, closed_uses(), self.name_of, knowledge, self._word_forms,
                                         recorded=self.recorded_name), structure=self._structure_view)
            for word in self._grammar_words:
                view.hold_word(word)
            for derived in self._grammar_derived:
                view.hold_derived(derived)
            for taught in self._grammar_taught:
                _, counted, rules = self._grammar_learned.get(taught.key(), (None, None, None))
                view.hold(taught, counted if rules == view.rules else None)
            for record in self._read_english:
                view.hold_read(record)
            self._grammar_view = view
        return self._grammar_view

    #: What reading taught of English is kept under (`keep_grammar_learning`).
    READ_ENGLISH_TAG = "read_english"

    async def keep_grammar_learning(self) -> int:
        """WHAT THE GRAMMAR LEARNED FROM EACH SENTENCE IS KEPT WITH THE SENTENCE, under the rules it was learned by
        (`GrammarView.rules`: the grammar's as written and the sentences derived by hand it holds), so a start adds it
        up and reads again only a sentence learned under other rules, or not yet learned from (`grammar_view`). Kept
        nowhere, it was learned again from all 9,882 sentences at every start, four minutes, a person's first turn
        waiting on it (2026-10-24). Returns how many were kept."""
        from core.utils.give_way import GiveWay
        if self._grammar_view is None:
            return 0
        give_way, kept = GiveWay(), 0
        # WHAT READING TAUGHT, one memory for what was read since the last keeping: how each sentence used its words
        # (`GrammarView._learn_from_reading`), taken back at every warm (`grammar_view`). Lyric's own English, learned.
        read = self._grammar_view.unkept_read()
        if read:
            from core.memory.utils.interfaces import Origin
            stored, _ = await self.store_memory(
                content=f"How {len(read)} sentence(s) read used their words", memory_type=MemoryType.SEMANTIC,
                confidence_score=0.9, tags=["language", self.READ_ENGLISH_TAG], source_context={"read_english": read},
                origin=Origin.own("reading"))
            if not stored:
                raise RuntimeError("what reading taught was not kept: the memory was declined")
            self._read_english.extend(read)
            kept += len(read)
        rules = self._grammar_view.rules
        for key, counted in self._grammar_view.unkept().items():
            memory_id = self._grammar_learned.get(key, (None, None, None))[0]
            if memory_id is None:
                continue        # taught since the warm: kept once a warm knows its memory
            if await self.update_memory(memory_id, {
                    "metadata": {"grammar_learned": {"rules": rules, "counted": [list(c) for c in counted]}},
                    "metadata.merge": True}):
                self._grammar_learned[key] = (memory_id, [list(c) for c in counted], rules)
                kept += 1
            await give_way()
        return kept

    def _net_word_classes(self, word: str) -> Dict[str, float]:
        """The kinds of word memory holds a word as, with net evidence for them, for the grammar. Named as the
        structure view's lookup was (`_held_word_classes`) until 2026-10-23, it replaced that one: the structure
        reader was handed the reader's class names (MODAL, not the treebank's AUXILIARY; NOUN and never NAME)."""
        return {cls: float(n) for cls, n in self.word_classes(word).items() if n > 0}

    def _held_name(self, words: Sequence[str], word_class: str) -> Optional[str]:
        """The name memory holds these words by together ("credit card", "pass away"), as a word of that class; None
        where it holds none."""
        view = self.pattern_inventory()
        for lexical in view.lexicals_with_words(tuple(w.lower() for w in words), loose=True):
            value = lexical.value
            if " " not in value.replace("_", " ").strip():
                continue
            classes = self.word_classes(value)
            if not classes or any(word_class in (c, "NOUN" if c == "NAME" else c) and n > 0
                                  for c, n in classes.items()):
                return value.replace("_", " ")
        # WORDS HELD TOGETHER AS A WORD OF THE CLASS: a verb of several words is taught as one ("'look up' is used
        # as a verb.", `WordNetSource._word_classes`), and no fact says it in words of its own.
        together = " ".join(w.lower() for w in words)
        if len(words) > 1 and self.word_classes(together).get(word_class, 0) > 0:
            return together
        return None

    def _hold_taught(self, view, item) -> None:
        """A sentence held with its taught meaning, folded into the composer's view and English's grammar."""
        view.hold(item)
        if self._grammar_view is not None:
            self._grammar_view.hold(item)
        else:
            self._grammar_taught.append(item)

    def _drop_taught(self, view, item) -> None:
        """A sentence held with its taught meaning, taken back from the composer's view and English's grammar
        (corrected since)."""
        view.drop(item)
        if self._grammar_view is not None:
            self._grammar_view.drop(item)
        key = item.key()
        self._grammar_taught = [t for t in self._grammar_taught if t.key() != key]

    def argument_view(self):
        """The sentences held with their happenings' arguments, as the argument view. Synchronous; empty before the
        first warm."""
        if self._argument_view is None:
            from core.semantics.argument_structure import ArgumentStructureView
            self._argument_view = ArgumentStructureView()
        return self._argument_view

    def composition_view(self):
        """The composer, learned from the sentences memory holds with their meanings (`composition`): the lessons',
        the PMB's. Synchronous; empty before the first warm."""
        if self._composition_view is None:
            from core.semantics.composition import CompositionView
            self._composition_view = CompositionView(None, lay_out=self.lay_out)
        return self._composition_view

    def lay_out(self, sentence: str):
        """A sentence as the composer reads it (`composition.lay`): split as Lyric splits a sentence, read by
        memory's structure view, each word named as memory names it (`name_of`). None for a sentence of no words."""
        from core.semantics.composition import lay
        from core.semantics.sentence_machine import form_of
        from core.semantics.structure import words_of
        words = words_of(form_of(sentence))
        if not words:
            return None
        read = self.structure_view().read(words)
        return lay(read.words, read.classes, read.heads, read.relations, self.name_of, self.known_name)

    def recorded_name(self, word: str, word_class: str) -> Optional[str]:
        """What the words and sentences recorded whole name a word as a class (`_record_names`), the most named; None
        where none does. Asked before any other name (`name_of`, the grammar's `HeldWords._name`)."""
        folded = str(word).casefold()
        recorded = self._record_names.get((folded, word_class)) or (
            self._record_names.get((folded, "NAME")) if word_class == "NOUN" else None)
        return recorded.most_common(1)[0][0] if recorded else None

    def name_of(self, word: str, word_class: str) -> str:
        """The thing a word names, as memory names it: the word itself, or the held word it is a shape of, where
        memory holds that word as this class; a verb's shape first ("hired" read as a verb is `hire`, as the frames
        read "breathes" `breathe`, so a telling composed meets the question its frame reads: "Did the company hire
        engineers?", UNDERSTANDS-PROSE-01, 2026-10-18; memory holds "hired" too, the adjective, and counts its
        classes by how it is written). Else, of the things held fillers of the word name (a word in another case is
        the same word), else of the held word it is a shape of ("breathes", `breathe`), the word itself where it is
        one of them, else the one memory holds a word of this class names, else the first; the word itself where
        memory holds nothing of it. Never another sense of this class in the word's place: "help" the noun stays
        `help`, not `aid`."""
        from core.semantics.structure import _HELD_AS
        folded = word.casefold()
        recorded = self.recorded_name(word, word_class)
        if recorded:
            return recorded
        view = self.pattern_inventory()
        shapes = [n for n in view.names_of_shape(folded) if n != folded]
        written_as = [folded] + shapes

        def held_names(written: str) -> List[str]:
            return list(dict.fromkeys(l.value for l in view.lexicals_with_words((written,), loose=True)))

        def of_class(name: str) -> bool:
            return any(word_class in _HELD_AS.get(cls, (cls,)) and n > 0
                       for cls, n in view.word_classes.get(name, {}).items())
        for written in (shapes + [folded] if word_class == "VERB" else written_as):
            if of_class(written) and written in held_names(written):
                return written
        for written in written_as:
            names = held_names(written)
            if not names:
                if written != folded:
                    return written
                continue
            if written in names:
                return written
            for name in names:
                if of_class(name):
                    return name
            return names[0]
        return folded

    def known_name(self, words: Sequence[str]) -> bool:
        """Whether memory holds these words as one name ("blue whale")."""
        return bool(self.pattern_inventory().lexicals_with_words(tuple(words), loose=True))

    async def remember_argued(self, argued, progress: Optional[Callable[[int, int], None]] = None
                              ) -> Dict[str, Any]:
        """Remember sentences with their happenings' arguments (`argument_structure.Argued`), one memory each; one
        held already is not held again. Returns `kept` (each newly held, with its memory's id), and counts:
        `remembered`, `already`, `total`."""
        return await self._remember_whole(
            argued, view=self.argument_view, tag=self.ARGUED_TAG, field="argued", progress=progress,
            content=lambda item: item.said(), add=lambda view, item: view.hold(item))

    async def remember_taught_sentences(self, taught, progress: Optional[Callable[[int, int], None]] = None
                                        ) -> Dict[str, Any]:
        """Remember sentences with their taught meanings (`composition.TaughtSentence`: the lessons', the PMB's), one
        memory each; one held already is not held again, and one held with another meaning from the same source is
        corrected (`_correct_whole`). Returns `kept`, `corrected` and counts, as `remember_argued`."""
        return await self._remember_whole(
            taught, view=self.composition_view, tag=self.TAUGHT_SENTENCE_TAG, field="taught", progress=progress,
            content=lambda item: item.said(), add=self._hold_taught, drop=self._drop_taught)

    async def _remember_whole(self, items, *, view, tag: str, field: str, content, add, drop=None,
                              progress: Optional[Callable[[int, int], None]]) -> Dict[str, Any]:
        """Keep each item whole, one memory each, as `remember_analysed` keeps sentences analysed, and fold it into
        the view (`view()`, asked after memory is warm: a warm builds the view anew). AN ITEM TAUGHT AGAIN, CORRECTED,
        corrects the memory holding what it said before: an item that says what it is about (`identity()`: a
        taught sentence's source and sentence) and a memory held before this pass about the same, holding it
        otherwise, is `_correct_whole`d, never kept beside it (the PMB's denied happenings said as the lessons say
        them, 2026-10-20 (28)); the view drops the earlier one (`drop`)."""
        from core.memory.utils.interfaces import Origin
        if not self._word_classes_warm:
            await self.warm_word_classes()
        view = view()
        items = list(items)
        held: Dict[str, str] = {}
        about: Dict[Any, Tuple[str, Dict[str, Any], Any]] = {}
        for row in await self._rows_tagged(tag):
            data = (row.metadata or {}).get(field)
            if data:
                was = self._whole_item(field, data)
                held[was.key()] = row.memory_id
                identity = getattr(was, "identity", lambda: None)()
                if identity is not None:
                    about[identity] = (row.memory_id, dict(row.metadata or {}), was)
        kept: List[Tuple[Any, str]] = []
        already: List[Tuple[Any, str]] = []
        corrected: List[Tuple[Any, str, Any]] = []
        counts = {"remembered": 0, "already": 0, "corrected": 0, "total": len(items)}
        for done, item in enumerate(items, 1):
            if progress is not None and done % 1000 == 0:
                progress(done, len(items))
            if item.key() in held:
                already.append((item, held[item.key()]))
                counts["already"] += 1
                continue
            identity = getattr(item, "identity", lambda: None)()
            earlier = about.pop(identity, None) if identity is not None else None
            if earlier is not None:
                memory_id, metadata, was = earlier
                await self._correct_whole(memory_id, metadata, field=field, item=item, was=was,
                                          content=content(item))
                if drop is not None:
                    drop(view, was)
                add(view, item)
                held[item.key()] = memory_id
                corrected.append((item, memory_id, was))
                counts["corrected"] += 1
                continue
            stored, memory_id = await self.store_memory(
                content=content(item), memory_type=MemoryType.SEMANTIC, confidence_score=0.9,
                tags=["language", tag], source_context={field: item.to_dict()}, origin=Origin.own("teaching"))
            if not stored or not memory_id:
                raise RuntimeError(f"{content(item)[:80]!r} was not kept: the memory was declined")
            add(view, item)
            held[item.key()] = memory_id
            kept.append((item, memory_id))
            counts["remembered"] += 1
        return {"kept": kept, "held_already": already, "corrected_items": corrected, **counts}

    async def _correct_whole(self, memory_id: str, metadata: Dict[str, Any], *, field: str, item, was,
                             content: str) -> None:
        """The memory holding `was` says `item` instead, keeping what it said before (`metadata.superseded`, as
        `supersede` keeps a memory's earlier words): a memory that quietly became correct could not be told from one
        always correct."""
        history = list(metadata.get("superseded") or [])
        history.append({"was": was.to_dict(), "because": "taught again, corrected", "at": datetime.now().isoformat()})
        metadata = {**metadata, field: item.to_dict(), "superseded": history[-5:]}
        updates: Dict[str, Any] = {"content": content, "metadata": metadata}
        if self.embedding_service:
            embedding = self.embedding_service.generate_embedding(content)
            if embedding is not None:
                updates["embedding"] = embedding
        if not await self.update_memory(memory_id, updates):
            raise RuntimeError(f"{content[:80]!r} was not corrected: memory {memory_id} was not updated")
        logger.info("corrected %s: %s", memory_id, content[:120])

    @staticmethod
    def _whole_item(field: str, data):
        """An item kept whole, as its memory holds it."""
        if field == "argued":
            from core.semantics.argument_structure import Argued
            return Argued.from_dict(data)
        if field == "word_group":
            from core.semantics.word_groups import WordGroup
            return WordGroup.from_dict(data)
        if field == "word_forms":
            from core.semantics.word_forms import WordForms
            return WordForms.from_dict(data)
        if field == "derived":
            from core.semantics.grammar import Derived
            return Derived.from_dict(data)
        if field == "record":
            from core.learning.teaching_sources import SentenceRecord
            return SentenceRecord.from_dict(data)
        if field == "word_record":
            from core.learning.teaching_sources import WordRecord
            return WordRecord.from_dict(data)
        from core.semantics.composition import TaughtSentence
        return TaughtSentence.from_dict(data)

    # WHAT WAS HEARD AFTER WHAT. A construction holds its slots' fillers each apart, so which word went after which
    # is not in it ("might open" and "often opens", one phrase "?slot0 ?slot1"); the sentences taught had it, and it
    # is kept: ONE MEMORY FOR EACH WORD, holding the words heard right after it, and, of each word heard before it,
    # the words heard after the two ("did not": chase, kick; "has not": opened). Saying puts a word only where a word
    # like it was heard (`derived_reader._unheard`). Heard is heard: a sentence taught again adds nothing.

    HEARD_TAG = "heard_after"

    async def _heard_memories(self) -> Tuple[Dict[str, Tuple[List[str], Dict[str, List[str]]]], Dict[str, str]]:
        """The memories of what was heard after each word: the words, and of each word heard before it, the words
        heard after the two; and the memory holding each word's."""
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        rows = await self._rows_tagged(self.HEARD_TAG)
        heard: Dict[str, Tuple[List[str], Dict[str, List[str]]]] = {}
        held: Dict[str, str] = {}
        for row in rows:
            await give_way()
            record = (row.metadata or {}).get("heard") or {}
            word = str(record.get("word") or "")
            if not word:
                continue
            heard[word] = ([str(other) for other in record.get("after") or ()],
                           {str(earlier): [str(other) for other in others]
                            for earlier, others in (record.get("after_two") or {}).items()})
            held[word] = row.memory_id
        return heard, held

    async def remember_heard(self, sentences,
                             progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Remember, for each sentence taught (`sentences`: each its words, marks and all), each word heard right
        after another, and after the two before it (`PatternInventory.hear`), in the memory of the word before it.
        Returns counts: `remembered` (memories formed or added to) and `heard` (pairs, and words after two, not
        heard before). `progress(done, of)` is told every 1,000 words, in the order they are written (alphabetical):
        WordNet's sentences hold tens of thousands, written for hours."""
        from core.memory.utils.interfaces import Origin
        if not self._word_classes_warm:
            await self.warm_word_classes()
        view = self.pattern_inventory()
        fresh: Dict[str, int] = {}
        for words in sentences:
            for heard in view.hear(words):
                fresh[heard[-2]] = fresh.get(heard[-2], 0) + 1
        counts = {"remembered": 0, "heard": sum(fresh.values())}
        for done, word in enumerate(sorted(fresh), 1):
            if progress is not None and done % 1000 == 0:
                progress(done, len(fresh))
            after = sorted(view.heard_after(word))
            content = f"Heard after {word}: " + ", ".join(after[:24]) + (", ..." if len(after) > 24 else "")
            record = {"heard": {"word": word, "after": after,
                                "after_two": {earlier: sorted(others) for earlier, others in view.heard_two(word).items()}}}
            memory_id = self._heard_memory.get(word)
            if memory_id is None:
                stored, memory_id = await self.store_memory(
                    content=content, memory_type=MemoryType.SEMANTIC,
                    confidence_score=0.9, tags=["language", self.HEARD_TAG], source_context=record,
                    origin=Origin.own("teaching"))
                if not stored or not memory_id:
                    raise RuntimeError(f"what was heard after {word!r} was not kept: the memory was declined")
                self._heard_memory[word] = memory_id
            elif not await self.update_memory(memory_id, {"content": content, "metadata": record,
                                                          "metadata.merge": True}):
                raise RuntimeError(f"what was heard after {word!r} was not updated in {memory_id}")
            counts["remembered"] += 1
        return counts

    async def _kinds_above(self, names) -> Dict[str, Dict[str, int]]:
        """Each named thing's kinds as memory holds them, and how far up each is (itself at 0)."""
        names = sorted({n for n in names if n})
        if not names:
            return {}
        rows = await self._memory_db().execute_query(
            "WITH RECURSIVE kinds(start, name, depth) AS ("
            " SELECT name::text, name::text, 0 FROM unified.concepts WHERE name = ANY($1::text[])"
            " UNION"
            " SELECT k.start, COALESCE(c2.name, cr.target_surface)::text, k.depth + 1"
            " FROM kinds k JOIN unified.concepts c1 ON c1.name = k.name"
            " JOIN unified.concept_relations cr ON cr.source_concept_id = c1.concept_id"
            " LEFT JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
            " WHERE cr.relation IN ('isa', 'is a') AND cr.polarity = 'positive' AND k.depth < $2)"
            " SELECT start, name, MIN(depth) AS depth FROM kinds GROUP BY start, name",
            (names, self.KINDS_FOLLOWED), fetch_all=True) or []
        up: Dict[str, Dict[str, int]] = {}
        for row in rows:
            up.setdefault(row["start"], {})[row["name"]] = int(row["depth"])
        return up

    async def _said_kinds(self, others: Dict[str, Dict[str, int]]) -> Tuple[Dict[str, float], float]:
        """How what was said of is spread over kinds: for each kind, the share of the uses whose thing is of it, and
        how many uses that is. A word whose sense was not given is shared among the things memory knows it names
        (Resnik's 1/senses); a word or thing memory knows nothing of counts in none."""
        from core.semantics.cognitive_ingress import normalize_term
        view = self.pattern_inventory()
        senses: Dict[Tuple[str, str], List[str]] = {}
        for kind, said in others.items():
            for other in said:
                if kind == "things":
                    senses[(kind, other)] = [normalize_term(other)]
                else:
                    named = {normalize_term(lx.value) for lx in view.lexicals_with_words((other,), loose=True)
                             if view.counts(lx)}
                    senses[(kind, other)] = sorted(named)
        up = await self._kinds_above(n for names in senses.values() for n in names)
        spread: Dict[str, float] = {}
        total = 0.0
        for (kind, other), names in senses.items():
            known = [n for n in names if n in up]
            if not known:
                continue
            times = others[kind][other]
            total += times
            for name in known:
                for above in up[name]:
                    spread[above] = spread.get(above, 0.0) + times / len(known)
        return ({k: v / total for k, v in spread.items()} if total else {}), total

    async def said_selection(self, facts, senses) -> Dict[Tuple[str, str, str, bool], float]:
        """For each fact (as `derived_reader.held_key` writes it) that says something of one of `senses`, how much
        more likely that thing is, given what the fact's other word is said of, than it is at all: ACT-R's
        associative strength by its own definition, `ln(P(k|w) / P(k))`, in nats, so it adds to a base level
        (`derived_reader.meant`). Taken over every kind the thing is, averaged (what words are said of is counted
        by kind, as Resnik 1997 counts it), and with one use spread as anything is, so a word met a few times moves
        little. "The table is red.": red is said of physical things more than things are at all, and of
        arrangements and groups less, so the table that is furniture gains and the array loses. Nothing for a fact
        whose word memory holds nothing said of.

        Chosen by measurement (SENSE-SAID-01): on the adjective–noun and verb–object pairs of WordNet's hand-tagged
        definitions, this added to how often each sense is met beat the most frequent sense (58.8% and 58.3%
        against 57.4% and 56.6%); the lift at the kind Resnik's association picks did not, and taking the word's
        selection first and frequency only on a tie fell to 42.5% and 44.6%."""
        import math
        from core.semantics.cognitive_ingress import normalize_term
        if not self._word_classes_warm:
            await self.warm_word_classes()
        senses = {normalize_term(s) for s in senses}
        wanted: Dict[Tuple[str, str, str, bool], List[Tuple[str, Tuple[str, str, str]]]] = {}
        for key in facts:
            # Said or denied, the word is said of the thing: "The table is not red." says red of a table.
            relation, subject, obj = key[0], normalize_term(key[1]), normalize_term(key[2])
            for thing, word, side in ((subject, obj, "object"), (obj, subject, "subject")):
                if thing in senses and (relation, word, side) in self._said_view:
                    wanted.setdefault(tuple(key), []).append((thing, (relation, word, side)))
        if not wanted:
            return {}
        up = await self._kinds_above(thing for asks in wanted.values() for thing, _ in asks)
        chosen: Dict[Tuple[str, str, str, bool], float] = {}
        # What each word is said of, worked out once for the call: a sentence read a thousand ways asks it of the
        # same few words a thousand times.
        said_by: Dict[Tuple[str, str, str], Tuple[Dict[str, float], float]] = {}
        for key, asks in wanted.items():
            score = 0.0
            for thing, (relation, word, side) in asks:
                if (relation, side) not in self._said_spread:
                    # How anything at all is spread over kinds when this relation is said of it, from every word
                    # said so: what `P(k)` is measured against.
                    every: Dict[str, Dict[str, int]] = {"words": {}, "things": {}}
                    for (r, _, s), held in self._said_view.items():
                        if (r, s) == (relation, side):
                            for kind in ("words", "things"):
                                for other, times in held[kind].items():
                                    every[kind][other] = every[kind].get(other, 0) + times
                    self._said_spread[(relation, side)] = (await self._said_kinds(every))[0]
                prior = self._said_spread[(relation, side)]
                if (relation, word, side) not in said_by:
                    held = self._said_view[(relation, word, side)]
                    said_by[(relation, word, side)] = await self._said_kinds(
                        {"words": held["words"], "things": held["things"]})
                given, uses = said_by[(relation, word, side)]
                kinds = sorted(k for k in up.get(thing, {thing: 0}) if prior.get(k))
                if not kinds or not uses:
                    continue
                # One use more, spread as anything is: `P(k|w)` as `(n P(k|w) + P(k)) / (n + 1)`. Over every kind
                # the thing is, so a kind the word is never said of counts against it as much as one it is said of
                # counts for it.
                score += sum(math.log((uses * given.get(k, 0.0) + prior[k]) / (uses + 1) / prior[k])
                             for k in kinds) / len(kinds)
            chosen[key] = round(score, 4)
        return chosen

    async def coarse_senses(self, senses) -> FrozenSet[FrozenSet[str]]:
        """Which of `senses` are one coarse sense: one a near kind of the other, or both near kinds of one thing
        (`KINDS_NEAR`), as memory holds what each is. The table that is furniture and the table a meal is laid on
        are one; the furniture and the array of data are not. A listener need not tell such senses apart to have
        understood."""
        from core.semantics.cognitive_ingress import normalize_term
        named = {sense: normalize_term(sense) for sense in senses}
        up = await self._kinds_above(named.values())
        near = {sense: {k for k, depth in up.get(name, {name: 0}).items() if depth <= self.KINDS_NEAR} | {name}
                for sense, name in named.items()}
        ordered = sorted(near)
        return frozenset(frozenset((a, b)) for i, a in enumerate(ordered) for b in ordered[i + 1:]
                         if near[a] & near[b])

    async def listening_evidence(self, facts, senses, context) -> Tuple[Dict[Tuple[str, str, str, bool], int],
                                                                       Dict[str, float],
                                                                       Dict[Tuple[str, str, str, bool], int]]:
        """What memory knows that bears on which thing a word was meant to name: what a listener asks when a
        sentence can be taken more than one way (`derived_reader.listening`).

        `held`: for each fact (as `derived_reader.held_key` writes it: relation, subject, object, positive), how
        firmly memory holds it. 2 when memory holds it of the things themselves ("a salmon is a fish", held when a
        salmon is held to be a food fish and a food fish a fish); 1 when it holds it of what they are kinds of, on
        either side ("I ate fish": an eating done to food, and the food sense of fish is a food). A denial is held
        only as told of the things themselves.

        `defined`: for each fact, 2 when one thing's definition is written with the other, 1 when with what the other
        is a near kind of: what memory knows of the two that no fact between them says.

        `related`: for each of `senses`, how much the rest of what was said and what was talked of before
        (`context`) raise it, in nats: ACT-R's spreading activation. Each thing of `context` the sense is connected
        to in memory (a fact of any kind between the two, or between what they are near kinds of, `KINDS_NEAR`;
        one a near kind of the other; both near kinds of one thing; or the thing itself, talked of before) gives
        its associative strength by ACT-R's own definition, `ln(P(i|j) / P(i))`: `P(i|j)` one over how many things
        memory holds connected to it (its fan, `_fans`), `P(i)` one over how many things memory holds. Each of the
        n things of `context` gives a 1/n share, as ACT-R divides its source activation. A thing connected to
        everything (a person, near half of what is said) tells a sense little; one connected to few (a river) tells
        it much.

        AN ACTIVATION, NOT A RANK OF ITS OWN. Counted as a rank before how often each sense is met, one connection
        took the rare sense: "Tom walked from the house." was the Tom of an ethnic slur (met once, beside 395 for
        the Tom of the lessons), "The dog jumped over the chair." a dog that is an andiron, held up as furniture is
        (2026-10-11, 23 of the 67 taught sentences main did not read as taught). Measured on WordNet's hand-tagged
        definitions (SENSE-RELATED-01): first, it took 63.0% of the senses tagged; added to the base level, 65.3%;
        the most frequent sense alone, 58.5%."""
        from core.semantics.cognitive_ingress import normalize_term
        facts = [tuple(f) for f in facts]
        senses, context = list(dict.fromkeys(senses)), list(dict.fromkeys(context))
        names = {term: normalize_term(term)
                 for term in [t for f in facts for t in (f[1], f[2])] + senses + context}
        if not names:
            return {}, {}, {}

        def kind_of(relation: str) -> str:
            # ONE NAME FOR EACH RELATION, as the register writes it: memory holds "part of", "antonym of", "instance
            # of", and the reader asks of `part_of`, `antonym_of`, `instance_of`. Compared as written, nothing but
            # what a thing is a kind of was ever found held (UNDERSTANDS-WORDNET-01, 2026-10-13).
            name = str(relation).strip().replace(" ", "_")
            return "isa" if name in ("isa", "is_a") else name

        def symmetric(relation: str) -> bool:
            from core.semantics.relation_types import SemanticRelation, get_spec
            try:
                return get_spec(SemanticRelation(relation)).symmetric
            except ValueError:
                return False

        rows = await self._memory_db().execute_query(
            "WITH RECURSIVE kinds(start, name, depth) AS ("
            " SELECT name::text, name::text, 0 FROM unified.concepts WHERE name = ANY($1::text[])"
            " UNION"
            " SELECT k.start, COALESCE(c2.name, cr.target_surface)::text, k.depth + 1"
            " FROM kinds k JOIN unified.concepts c1 ON c1.name = k.name"
            " JOIN unified.concept_relations cr ON cr.source_concept_id = c1.concept_id"
            " LEFT JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
            " WHERE cr.relation IN ('isa', 'is a') AND cr.polarity = 'positive' AND k.depth < $2)"
            " SELECT k.start, k.name AS kind, MIN(k.depth) AS depth, cr.relation,"
            " COALESCE(c2.name, cr.target_surface) AS target, cr.polarity"
            " FROM kinds k LEFT JOIN unified.concepts c1 ON c1.name = k.name"
            " LEFT JOIN unified.concept_relations cr ON cr.source_concept_id = c1.concept_id"
            " LEFT JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
            " GROUP BY k.start, k.name, cr.relation, COALESCE(c2.name, cr.target_surface), cr.polarity",
            (sorted(set(names.values())), self.KINDS_FOLLOWED), fetch_all=True) or []
        # Each thing's kinds, by how far up; what each thing (and each kind) is held to stand in, and to what.
        up: Dict[str, Dict[str, int]] = {}
        said: Dict[str, set] = {}
        for row in rows:
            start, kind, depth = row["start"], row["kind"], int(row["depth"])
            kinds = up.setdefault(start, {start: 0})
            kinds[kind] = min(kinds.get(kind, depth), depth)
            if row["relation"] is None:
                continue
            relation, target = kind_of(row["relation"]), row["target"]
            positive = row["polarity"] == "positive"
            said.setdefault(kind, set()).add((relation, target, positive))
            if relation == "isa" and positive:
                kinds[target] = min(kinds.get(target, depth + 1), depth + 1)

        def kinds_of(name: str, within: int = self.KINDS_FOLLOWED) -> set:
            return {k for k, d in up.get(name, {name: 0}).items() if d <= within} | {name}

        held: Dict[Tuple[str, str, str, bool], int] = {}
        for key in facts:
            relation, subject, obj, positive = kind_of(key[0]), names[key[1]], names[key[2]], bool(key[3])
            # A symmetric relation held the other way round is held ("incoming is the opposite of outgoing").
            if (relation, obj, positive) in said.get(subject, ()) or (
                    symmetric(relation) and (relation, subject, positive) in said.get(obj, ())) or (
                    relation == "isa" and positive and obj != subject and obj in kinds_of(subject)):
                held[key] = 2
            elif positive and relation != "isa" and any((relation, o, True) in said.get(s, ())
                                                        for s in kinds_of(subject) for o in kinds_of(obj)):
                # NOT FOR WHAT A THING IS A KIND OF. That a thing is a Y is held when Y is among its kinds (above);
                # its kinds and Y's kinds always meet somewhere general ("a whole is an object"), so the animal
                # was held a device as firmly as the computer's mouse that is one.
                held[key] = 1

        def near(name: str) -> set:
            return kinds_of(name, self.KINDS_NEAR)

        # WHAT A THING'S DEFINITION IS WRITTEN WITH (`defined with`: each word of a definition linked by WordNet's own
        # authors to the sense it is used in). "A bus is a vehicle." is held nowhere as a kind, the bus being public
        # transport, and its definition says it: "a vehicle carrying many passengers". Asked only of kinds, memory
        # answered that it knew nothing, and the car that is a bus, held a vehicle, was taken (2026-10-14). 2 when
        # either thing's definition is written with the other; 1 when with what the other is a near kind of (a door
        # "will close the entrance to a room or building", and a house is a building).
        def written_with(name: str) -> set:
            return {target for relation, target, positive in said.get(name, ()) if relation == "defined_with" and positive}
        defined: Dict[Tuple[str, str, str, bool], int] = {}
        for key in facts:
            subject, obj = names[key[1]], names[key[2]]
            if not key[3] or subject == obj:
                continue
            if obj in written_with(subject) or subject in written_with(obj):
                defined[key] = 2
            elif written_with(subject) & near(obj) or written_with(obj) & near(subject):
                defined[key] = 1

        def connected(a: str, b: str) -> bool:
            here, there = near(a), near(b)
            if here & there:
                # One is a near kind of the other, or both are near kinds of one thing: a computer's mouse and a
                # computer are both devices; the animal and the computer meet nowhere near.
                return True
            return any(target in there for k in here for _, target, _ in said.get(k, ())) or \
                any(target in here for k in there for _, target, _ in said.get(k, ()))

        # The thing itself talked of before counts as what it is connected to: a word keeps its sense in one
        # conversation (one sense per discourse).
        import math
        sources = {other: names[other] for other in context}
        fans = await self._fans(sources.values()) if sources else {}
        held_at_all = await self._things() if sources else 0
        related: Dict[str, float] = {}
        for sense in senses:
            strength = sum(math.log(held_at_all / fans[name]) for name in sources.values()
                           if connected(names[sense], name)) / max(1, len(sources))
            if strength:
                related[sense] = round(strength, 6)
        return held, related, defined

    async def _things(self) -> int:
        """How many things memory holds: what one thing's share of all of them is measured against."""
        if self._things_held is None:
            rows = await self._memory_db().execute_query("SELECT count(*) AS n FROM unified.concepts", fetch_all=True)
            self._things_held = max(1, int(rows[0]["n"])) if rows else 1
        return self._things_held

    async def _fans(self, names) -> Dict[str, int]:
        """How many things memory holds connected to each of `names`, as `listening_evidence` connects two things:
        its fan, ACT-R's. A thing is connected to what is within `KINDS_NEAR` kinds below anything it is near, holds
        a fact of, or is held a fact of; and to what is within as many below anything a fact is held of that names
        what it is near. The thing itself is among them. Counted once for each name until the next warm."""
        wanted = sorted({name for name in names if name not in self._fan_view})
        if wanted:
            rows = await self._memory_db().execute_query(
                "WITH RECURSIVE up(start, name, depth) AS ("
                " SELECT n::text, n::text, 0 FROM unnest($1::text[]) AS n"
                " UNION"
                " SELECT u.start, c2.name::text, u.depth + 1 FROM up u JOIN unified.concepts c1 ON c1.name = u.name"
                " JOIN unified.concept_relations cr ON cr.source_concept_id = c1.concept_id"
                " JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
                " WHERE cr.relation IN ('isa', 'is a') AND cr.polarity = 'positive' AND u.depth < $2),"
                " near AS (SELECT DISTINCT start, name FROM up),"
                " seeds(start, name) AS ("
                " SELECT start, name FROM near"
                " UNION"
                " SELECT n.start, COALESCE(c2.name, cr.target_surface)::text FROM near n"
                " JOIN unified.concepts c1 ON c1.name = n.name"
                " JOIN unified.concept_relations cr ON cr.source_concept_id = c1.concept_id"
                " LEFT JOIN unified.concepts c2 ON c2.concept_id = cr.target_concept_id"
                " UNION"
                " SELECT n.start, c1.name::text FROM near n JOIN unified.concepts c2 ON c2.name = n.name"
                " JOIN unified.concept_relations cr ON cr.target_concept_id = c2.concept_id"
                " JOIN unified.concepts c1 ON c1.concept_id = cr.source_concept_id"
                " UNION"
                " SELECT n.start, c1.name::text FROM near n"
                " JOIN unified.concept_relations cr ON cr.target_concept_id IS NULL AND cr.target_surface = n.name"
                " JOIN unified.concepts c1 ON c1.concept_id = cr.source_concept_id),"
                " down(start, name, depth) AS ("
                " SELECT start, name, 0 FROM seeds"
                " UNION"
                " SELECT d.start, c1.name::text, d.depth + 1 FROM down d JOIN unified.concepts c2 ON c2.name = d.name"
                " JOIN unified.concept_relations cr ON cr.target_concept_id = c2.concept_id"
                " JOIN unified.concepts c1 ON c1.concept_id = cr.source_concept_id"
                " WHERE cr.relation IN ('isa', 'is a') AND cr.polarity = 'positive' AND d.depth < $2)"
                " SELECT start, count(DISTINCT name) AS fan FROM down GROUP BY start",
                (wanted, self.KINDS_NEAR), fetch_all=True) or []
            for row in rows:
                self._fan_view[row["start"]] = max(1, int(row["fan"]))
            for name in wanted:
                self._fan_view.setdefault(name, 1)
        return {name: self._fan_view[name] for name in names}

    async def task_occurrences(self) -> List[Dict[str, Any]]:
        """Every time the substrate did a task of its own, as its task memories
        record it, hot and cold: `task_type`, `knowledge_domain`, `outcome`,
        `task_id`, `created_at`. ONE ROW PER OCCURRENCE: a task asked again is
        merged into the memory that holds it, which keeps each time it was done;
        a memory from before occurrences were merged is one. A task done for a
        person is that person's memory, and is not among these."""
        tiers = []
        for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
            tiers.append(
                "SELECT o->>'task_type' AS task_type, o->>'knowledge_domain' AS knowledge_domain,"
                " o->>'outcome' AS outcome, o->>'task_id' AS task_id,"
                " CASE WHEN o->>'timestamp' ~ '^\\d{4}-\\d{2}-\\d{2}T'"
                " THEN (o->>'timestamp')::timestamp ELSE m.created_at END AS created_at"
                f" FROM {table} m,"
                " jsonb_array_elements(COALESCE(m.thinking_state->'raw_event'->'occurrences',"
                " jsonb_build_array(m.thinking_state->'raw_event'))) AS o"
                " WHERE m.tags @> '[\"task_outcome\"]'::jsonb"
                " AND (m.user_id IS NULL OR m.user_id IN ('', '__substrate__'))")
        return list(await self._memory_db().execute_query(
            " UNION ALL ".join(tiers), fetch_all=True, store="model") or [])

    async def capture_statistics(self, *, within_s: float = 3600.0) -> Dict[str, Any]:
        """How fully the memories formed in the last `within_s` seconds carry
        what the substrate was thinking: how many there are, and how many hold
        a thinking state, a reasoning trace and decision factors (hot tier,
        where new memories form)."""
        row = await self._memory_db().execute_query(
            "SELECT COUNT(*) AS total,"
            " COUNT(*) FILTER (WHERE jsonb_typeof(thinking_state) = 'object'"
            "   AND thinking_state <> '{}'::jsonb) AS with_thinking_state,"
            " COUNT(*) FILTER (WHERE jsonb_typeof(reasoning_trace) = 'array'"
            "   AND jsonb_array_length(reasoning_trace) > 0) AS with_reasoning_trace,"
            " COUNT(*) FILTER (WHERE jsonb_typeof(decision_factors) IN ('array', 'object')"
            "   AND decision_factors NOT IN ('[]'::jsonb, '{}'::jsonb)) AS with_decision_factors,"
            " COALESCE(AVG(jsonb_array_length(reasoning_trace))"
            "   FILTER (WHERE jsonb_typeof(reasoning_trace) = 'array'), 0) AS avg_reasoning_trace_length"
            " FROM memory_hot.memory_hot WHERE created_at > NOW() - make_interval(secs => $1)",
            (float(within_s),), fetch_one=True, store="model")
        return dict(row)

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

    async def tool_runs(self) -> Dict[str, Dict[str, Any]]:
        """The tool runs a task did, by tool: how many ran (`runs`), how many
        succeeded and failed, and over the runs that were timed, how many
        (`timed`) and their total `seconds`.

        Read from the tool-run parts of every task and pursuit memory, hot and
        cold, in every store the memory agent keeps. Only the tool's name, whether
        the run succeeded and how long it took are read: nothing of its arguments,
        and nothing of whose work it was. A run the experience holds no verdict
        for (`success` missing) is counted as a run and as neither.

        Tools that run outside a task's own steps are recorded where their
        faculty keeps them, not here: a learned operator's run as runtime
        evidence on its rule, a look-up as the parts of its research experience,
        a reading in the act's frame (filed with the act as a demonstration) and
        in the constitution's reading ledger, an exploration act as a
        demonstration."""
        from core.memory.utils.interfaces import TASK_OUTCOME_EVENT
        db = self._memory_db()
        by_tool: Dict[str, Dict[str, Any]] = {}
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                rows = await db.execute_query(
                    "SELECT part FROM ("
                    f"  SELECT thinking_state->'raw_event'->'experience'->'parts' AS parts FROM {table}"
                    "   WHERE thinking_state->'raw_event'->>'event' = $1"
                    "     AND jsonb_typeof(thinking_state->'raw_event'->'experience'->'parts') = 'array'"
                    ") AS held, jsonb_array_elements(held.parts) AS part"
                    " WHERE part->>'role' = 'tool_run'",
                    (TASK_OUTCOME_EVENT,), fetch_all=True, store=store) or []
                for row in rows:
                    part = row["part"]
                    part = json.loads(part) if isinstance(part, str) else part
                    content = part.get("content") or {}
                    name = content.get("tool")
                    if not name:
                        continue
                    count = int(part.get("count", 1))
                    tally = by_tool.setdefault(str(name), {
                        "runs": 0, "succeeded": 0, "failed": 0, "timed": 0, "seconds": 0.0})
                    tally["runs"] += count
                    if content.get("success") is True:
                        tally["succeeded"] += count
                    elif content.get("success") is False:
                        tally["failed"] += count
                    measure = part.get("measured") or {}
                    if "seconds" in (measure.get("sums") or {}):
                        tally["timed"] += int(measure.get("n", 0))
                        tally["seconds"] += float(measure["sums"]["seconds"])
        return by_tool

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
        from core.memory.utils.interfaces import pursuit_account
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
            pursuit_account(record), memory_type=MemoryType.META,
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
            # The kind of work it was (`task_experience`), kept on the occurrence it is about.
            if experience.evidence.get("category"):
                entry["category"] = experience.evidence["category"]
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

    async def _tags_index(self) -> None:
        """The indexes every whole-set read by tag goes through, made once in every store memory keeps: the tags'
        own, for a tag few memories carry, and one the read answers from alone, in its order, for a tag many carry.

        A TAG MANY CARRY IS NO NARROWER BY ITS INDEX: 576,968 of main's 1,444,052 memories are taught propositions,
        and finding them by the tags' index, or by none, read every one from the table (2.4 GB) to see whose it is
        and when it was made, 38 s and more where the table was not cached, past the 60 s a statement has, and the
        warm failed (2026-10-21). Read from `_tagged_idx` alone, in its order, it is 0.2 s."""
        if MemoryAgent._construction_index_ready:
            return
        db = self._memory_db()
        for store in db.schema_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                schema = table.split(".")[0]
                await db.execute_query(f"CREATE INDEX IF NOT EXISTS {schema}_tags_gin_idx ON {table} USING gin (tags)",
                                       commit=True, store=store)
                await db.execute_query(f"CREATE INDEX IF NOT EXISTS {schema}_tagged_idx ON {table}"
                                       f" (created_at, memory_id) INCLUDE (user_id, tags)", commit=True, store=store)
        MemoryAgent._construction_index_ready = True

    async def claims_of(self, memory_ids: Sequence[str]) -> Dict[str, List[list]]:
        """The facts each memory claims (`claim_facts`, as made or as read when it was stored), by memory id; a
        memory claiming none is absent. Read directly from both tiers of every store, by id."""
        ids = [str(m) for m in memory_ids if m]
        if not ids:
            return {}
        db = self._memory_db()
        out: Dict[str, List[list]] = {}
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                rows = await db.execute_query(
                    f"SELECT memory_id, metadata->'claim_facts' AS facts FROM {table}"
                    " WHERE memory_id = ANY($1::text[]) AND metadata ? 'claim_facts'",
                    (ids,), fetch_all=True, store=store) or []
                for row in rows:
                    facts = row["facts"]
                    facts = json.loads(facts) if isinstance(facts, str) else facts
                    if facts:
                        out.setdefault(row["memory_id"], facts)
        return out

    async def _rows_tagged(self, tag: str) -> List[Any]:
        """Every memory of Lyric's own carrying `tag`, read whole by its tag from both tiers of every store memory
        keeps: its id, content, metadata and raw event, and nothing else.

        READ DIRECTLY, NOT THROUGH RETRIEVAL, as the constructions are (`_construction_rows`). Retrieval ranks all
        of memory to find what fits a query, reads every column (each memory's embedding, and any perception copied
        into it), and stops at a cap. Asked for the word classes whole, it took 56 s with 385,000 memories held,
        against a 60 s limit on a query; a failed strategy came back as no rows; and past its cap it kept the first
        400,000, while WordNet's facts alone are 636,000. A view read short or empty reads every word past it as
        never met, and the run that read it said nothing of it (2026-10-08). Read so, it is one indexed query."""
        from types import SimpleNamespace
        from core.database.releases import SUBSTRATE_OWNERS
        from core.utils.give_way import GiveWay
        give_way = GiveWay()
        await self._tags_index()
        db = self._memory_db()
        out: List[Any] = []
        for store in db.maintained_stores():
            for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                async for row in self._tagged_pages(db, table, store, tag, SUBSTRATE_OWNERS):
                    await give_way()
                    content, meta, raw = row["content"], row["metadata"], row["raw_event"]
                    out.append(SimpleNamespace(
                        memory_id=row["memory_id"],
                        content=(json.loads(content) if isinstance(content, str) else content) if content else {},
                        metadata=json.loads(meta) if isinstance(meta, str) else dict(meta or {}),
                        thinking_state={"raw_event": json.loads(raw) if isinstance(raw, str) else raw} if raw else {}))
        return out

    #: Rows read whole in one query. The set is found first, by its ids alone; the rows are then read by id this
    #: many at a time, so no query reads more than this many memories' content, however many carry the tag.
    _TAGGED_PAGE = 2000

    async def _tagged_pages(self, db, table: str, store: str, tag: str, owners) -> Any:
        """Lyric's own memories in `table` carrying `tag`, oldest first.

        IN TWO STEPS. One query returned a page of 50,000 whole rows (content, metadata, raw event) by keyset; each
        page fetched every row carrying the tag from the heap to filter and sort them, then read the page's content
        out of TOAST. With the store's pages cached it fitted in the 60 s a statement has (the 76,818 taught
        propositions at a teaching pass's end); on a cold copy of the store it did not, and the view would not warm
        (2026-10-10). So: the ids and creation times first (the tag's index, no content), then the rows by id, a
        bounded number at a time."""
        found = await db.execute_query(
            f"SELECT memory_id FROM {table} WHERE tags @> $1::jsonb AND COALESCE(user_id, '') = ANY($2::text[])"
            f" ORDER BY created_at, memory_id",
            (json.dumps([tag]), list(owners)), fetch_all=True, store=store) or []
        ids = [row["memory_id"] for row in found]
        for start in range(0, len(ids), self._TAGGED_PAGE):
            batch = ids[start:start + self._TAGGED_PAGE]
            rows = await db.execute_query(
                f"SELECT memory_id, created_at, content, metadata, thinking_state->'raw_event' AS raw_event"
                f" FROM {table} WHERE memory_id = ANY($1::text[]) ORDER BY created_at, memory_id",
                (batch,), fetch_all=True, store=store) or []
            for row in rows:
                yield row

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
        for data, meta in self._media_parts(media, media_meta):
            await self._retain_media(memory_id, data, meta, self._pursuit_owner(record))
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
        kept = experience.get("origin") or {}
        origin = Origin(through=kept.get("through") or "task", person=kept.get("person"),
                        context=kept.get("context"), organization=kept.get("organization"))
        queued = await self._memory_db().execute_query(
            "SELECT item_id FROM unified.experience_pool WHERE memory_id = $1 LIMIT 1",
            (memory_id,), fetch_one=True,
            store=self._memory_db().write_store(origin.owner))
        if queued is not None:
            await self._memory_db().execute_query(
                "UPDATE unified.experience_pool SET status = 'waiting', decision = NULL,"
                " decided_at = NULL, claimed_by = NULL, claimed_until = NULL,"
                " evidence = $2::jsonb WHERE item_id = $1",
                (queued["item_id"], json.dumps(experience["evidence"], default=str)),
                commit=True, store=self._memory_db().write_store(origin.owner))
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
        """Whose a pursuit is, from the origin it was begun with: the person's, the organization's for work done
        for it, or None for the substrate's own (`Origin.owner`)."""
        from core.memory.utils.interfaces import Origin
        kept = (record.get("experience") or {}).get("origin") or {}
        if not kept.get("person"):
            return None
        return Origin(through=kept.get("through") or "task", person=kept.get("person"),
                      context=kept.get("context"), organization=kept.get("organization")).owner

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
        from core.memory.utils.interfaces import pursuit_account
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
        async with self._memory_db().advisory_lock(f"pursuit:{memory_id}", store="runtime"):
            yield

    @staticmethod
    def _summarize_parts(held: List[Dict[str, Any]],
                         new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """A pursuit's parts with what repeats counted: the same call, the same
        error, the same check, however often it came, is one part saying how
        many times, holding the latest of it. Parts that differ are kept apart.
        Numbers do not make two parts different (an attempt's number, a
        measurement), words and names do.

        WHAT THE REPEATS MEASURED IS ADDED UP, not overwritten: `measured` holds
        how many of them carried numbers (`n`) and the sum of each number
        (`sums`), so the mean of a measurement (how long a tool took) is known
        over every repeat that measured it. A part held from before this was
        kept, repeated and carrying only its latest numbers, counts as measured
        nowhere: what its earlier repeats measured is gone, and is not guessed."""
        def key(part: Dict[str, Any]):
            text = json.dumps(part.get("content"), sort_keys=True, default=str)
            return (part.get("role"), part.get("source"), re.sub(r"\d+(?:\.\d+)?", "#", text))

        def measured(part: Dict[str, Any]) -> Tuple[int, Dict[str, float]]:
            held_measure = part.get("measured")
            if held_measure is not None:
                return (int(held_measure.get("n", 0)),
                        {k: float(v) for k, v in (held_measure.get("sums") or {}).items()})
            content = part.get("content")
            numbers = ({k: float(v) for k, v in content.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
                       if isinstance(content, dict) else {})
            if numbers and int(part.get("count", 1)) == 1:
                return 1, numbers
            return 0, {}

        def with_measure(part: Dict[str, Any], n: int, sums: Dict[str, float]) -> None:
            if n:
                part["measured"] = {"n": n, "sums": sums}
            else:
                part.pop("measured", None)

        kept = [dict(p) for p in held]
        index = {key(p): i for i, p in enumerate(kept)}
        for part in new:
            k = key(part)
            if k in index:
                same = kept[index[k]]
                n_held, sums = measured(same)
                n_new, sums_new = measured(part)
                for field_name, value in sums_new.items():
                    sums[field_name] = sums.get(field_name, 0.0) + value
                same["count"] = int(same.get("count", 1)) + int(part.get("count", 1))
                same["content"] = part.get("content")
                with_measure(same, n_held + n_new, sums)
            else:
                index[k] = len(kept)
                n_new, sums_new = measured(part)
                added = {**part, "count": int(part.get("count", 1))}
                with_measure(added, n_new, sums_new)
                kept.append(added)
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
    # CLEANUP
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

    # JUDGING AN ACT IS NOT THIS AGENT'S.
    #
    # The Constitution judges an act BEFORE it happens, at the point where the
    # act is real: intent is formed when reasoning starts, the route is proved by
    # planning over operators the rule store attests, and every tool call is
    # judged with its actual arguments. An agent asking "is this operation
    # compliant?" as it is about to run would be a late yes/no standing in for a
    # law that already applies, earlier and with more to read. So nothing here
    # gates a memory operation: this agent is the one writer of memory, and what
    # reaches it has already been judged.


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
        # A warm still reading the store stops with the agent: stopping is not the warm failing.
        warm = self._word_class_warm_task
        if warm is not None and not warm.done():
            self._stopping_loops = True
            warm.cancel()
            try:
                await warm
            except asyncio.CancelledError:
                pass

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
        A memory's importance fades with age where it is read (`decayed_importance`), not here: written back each
        cycle, the whole age's fading compounded hourly.
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
