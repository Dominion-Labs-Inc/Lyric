#!/usr/bin/env python3
"""
TorinAI Unified Learning System
Integrated learning system combining all learning components
"""

import hashlib
import logging
import asyncio
import json
from contextvars import ContextVar
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
from core.database.logging_database import LoggingDatabase

# Import Slack notifier for learning milestone notifications
from core.integration.slack_notifier import get_slack_notifier

logger = logging.getLogger(__name__)


from ..memory import MemoryManager, CognitiveExperience, MemoryType, MemoryPriority
from .meta_learning import MetaLearner, get_meta_learner
from .learning_interfaces import (
    ILearningSystem,
    LearningType,
    LearningExample,
    LearningResult,
)
from .meta_learning import TaskFamily, task_family_for_task_type
# THE ONE LEARNING AUTHORITY. UnifiedLearningSystem was once the DECLARED
# authority; a correct model-free ILearningAuthority was then built in a
# separate learning_authority.py instead of fixing THIS class, leaving two
# owners of the one concept "learning". That file is now deleted and its whole
# implementation lives here: UnifiedLearningSystem IS the learning authority
# (propose -> evidence attests, model-free, one boundary on what may propose,
# induction + rule store), with the meta-learning strategies as first-class
# parts of it. These are the imports that implementation needs.
from core.capability import raise_if_structural
from core.learning.learning_interfaces import ILearningAuthority
from core.learning.rule_induction import (CandidateRule, InductionResult,
                                          InductionStatus, TrainingExample,
                                          get_rule_inducer)
from core.learning.rule_store import EpistemicStatus, get_rule_store

# LearningType (how we are learning) -> TaskFamily (what kind of task it is).
# meta_learning registers and selects strategies by TaskFamily; this system
# speaks LearningType. Passing a LearningType through matched nothing, so
# select_strategy() returned None and its caller dereferenced it.
# HOW SOMETHING WAS LEARNED -> WHAT KIND OF PROBLEM IT IS.
#
# This covered 6 of LearningType's 10 members and was read with a
# `.get(learning_type, TaskFamily.CLASSIFICATION)` default, so the four
# substrate types -- the ones naming how the substrate ACTUALLY learns -- were
# silently filed as classification. Combined with the same default catching
# every unstated family, 10,601 of 11,720 recorded decisions were scored
# against the classification arms without anything deciding they were
# classification problems. `classification_transfer` reached 519 trials at
# confidence 1.000 on work that was largely not classification.
#
# CONTRIBUTION is deliberately absent. Admitting a proposal against evidence is
# not a learning problem with strategy alternatives to choose between, so there
# is no honest family for it, and inventing one would put a strategy's credit
# on an event no strategy influenced. Unmapped is stated below, not defaulted.
_LEARNING_TYPE_TO_TASK_FAMILY = {
    LearningType.SUPERVISED: TaskFamily.CLASSIFICATION,
    LearningType.UNSUPERVISED: TaskFamily.PERCEPTION,
    LearningType.REINFORCEMENT: TaskFamily.REINFORCEMENT,
    LearningType.TRANSFER: TaskFamily.CLASSIFICATION,
    LearningType.CONTINUAL: TaskFamily.SEQUENCE,
    LearningType.META: TaskFamily.REASONING,
    # A rule generalised from demonstrations is a reasoning problem.
    LearningType.INDUCTION: TaskFamily.REASONING,
    # A procedure derived from I/O pairs produces a program.
    LearningType.SYNTHESIS: TaskFamily.GENERATION,
    LearningType.CAUSAL: TaskFamily.REASONING,
}

# Import domain knowledge system for transfer learning
from core.domain import (
    CrossDomainReasoner, DomainRegistry, UniversalOntology, UnknownDomain,
    UnresolvedDomainReference)
from core.capability import raise_if_structural

#: How deep learning has recurred WITHIN THE CURRENT TASK.
#:
#: This replaces `self._learning_in_progress` + `self._current_nesting_depth`,
#: two instance attributes shared by every caller of the singleton. They could
#: not tell recursion from concurrency, and `learn_from_example` awaits
#: repeatedly, so any two parallel tasks interleaved through them. Measured
#: with five concurrent (NOT nested) calls: one was rejected outright with
#: "Circular dependency detected", and the guard was left at
#: `in_progress=True, depth=0` afterwards -- stuck, so every later call counted
#: as nested and the system would refuse all learning after three more.
#:
#: A ContextVar is per-task and inherited by awaited callees, which is exactly
#: the distinction the guard needs: a nested call sees its caller's depth, a
#: sibling task starts at zero. Nothing to reset, so it cannot be left corrupt.
_learning_depth: "ContextVar[int]" = ContextVar("learning_depth", default=0)


def _json_safe(value: Any) -> Any:
    """Coerce a value into something the memory store can serialise.

    source_context carries the producer's example verbatim under
    'example_data', so it holds whatever a caller put there -- an enum, a
    dataclass, a datetime. The hot tier serialises that column as JSON and a
    single non-serialisable object fails the WHOLE insert: the memory is lost
    and the lane reports nothing but "Memory agent rejected: None", which is
    indistinguishable from the worthiness filter declining it.

    Observed by putting a LearningType on the example so the strategy could be
    selected by task family -- a correct change that silently stopped every
    learning memory from persisting. Whether an outcome is recorded must not
    depend on which Python types a producer happened to use.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return str(value)


# ── INDUCTION BASIS BOUNDS (moved from the deleted learning_authority.py) ──────
# The induction basis is BOUNDED so the hypothesis search stays tractable as
# demonstrations accumulate (measured: ~0.03s at 12 examples, ~0.9s at 16, ~17s
# at 20, non-terminating past that), while the information LGG needs saturates
# early. Held-out validation (reserved separately) remains the correctness guard.
_BASIS_POSITIVES = 8
_BASIS_NEGATIVES = 8
_BASIS_CONTRASTIVE = 6


def _bounded_basis(
    signature_basis: List["TrainingExample"],
    contrastive: "Sequence[TrainingExample]",
) -> List["TrainingExample"]:
    """A bounded, constant-diverse subset of the evidence for one induction.

    Exact-duplicate demonstrations are dropped; among the rest, selection
    round-robins over distinct ground ACTIONS so a capped sample spans different
    constants (what LGG needs to variabilise an argument position). Positives,
    negatives and contrastives are bounded independently.
    """
    def _fingerprint(example: "TrainingExample"):
        return (example.positive, example.action,
                tuple(sorted((f.predicate, f.args) for f in example.before)),
                tuple(sorted((f.predicate, f.args) for f in example.after)))

    def _spread(examples: List["TrainingExample"], cap: int) -> List["TrainingExample"]:
        seen: set = set()
        unique: List["TrainingExample"] = []
        for example in examples:
            key = _fingerprint(example)
            if key in seen:
                continue
            seen.add(key)
            unique.append(example)
        if len(unique) <= cap:
            return unique
        buckets: Dict[Any, List["TrainingExample"]] = {}
        order: List[Any] = []
        for example in unique:
            if example.action not in buckets:
                buckets[example.action] = []
                order.append(example.action)
            buckets[example.action].append(example)
        selected: List["TrainingExample"] = []
        depth = 0
        while len(selected) < cap and any(len(buckets[a]) > depth for a in order):
            for action in order:
                if depth < len(buckets[action]):
                    selected.append(buckets[action][depth])
                    if len(selected) >= cap:
                        break
            depth += 1
        return selected

    positives = _spread([e for e in signature_basis if e.positive], _BASIS_POSITIVES)
    negatives = _spread([e for e in signature_basis if not e.positive], _BASIS_NEGATIVES)
    contrastives = _spread(list(contrastive), _BASIS_CONTRASTIVE)
    return positives + negatives + contrastives


def _relevant_frame(basis: List["TrainingExample"]) -> List["TrainingExample"]:
    """Scope each demonstration to the object the action transforms.

    A full-world observation makes Plotkin LGG explode (w facts of a predicate
    over n positives -> w**n body literals). An operator is about the object it
    changes -- the term shared by the action's ADD and DELETE effects -- so each
    demonstration's LEARNING state is restricted to facts mentioning that object.
    Held-out validation is left on the FULL world, so a scoped rule must still
    fire in reality.
    """
    tallies: Dict[int, int] = {}
    acted_positives = 0
    for example in basis:
        if example.action is None or not example.positive:
            continue
        acted_positives += 1
        added = set(example.after) - set(example.before)
        deleted = set(example.before) - set(example.after)
        persistent = ({t for fact in added for t in fact.args}
                      & {t for fact in deleted for t in fact.args})
        for index, arg in enumerate(example.action.args):
            if arg in persistent:
                tallies[index] = tallies.get(index, 0) + 1
    if not tallies:
        return basis
    object_positions = {i for i, count in tallies.items()
                        if count * 2 >= acted_positives}
    if not object_positions:
        object_positions = {max(tallies, key=lambda i: tallies[i])}

    def scoped(example: "TrainingExample") -> "TrainingExample":
        if example.action is None:
            return example
        anchors = {example.action.args[i] for i in object_positions
                   if i < len(example.action.args)}
        if not anchors:
            return example
        before = tuple(f for f in example.before if set(f.args) & anchors)
        after = tuple(f for f in example.after if set(f.args) & anchors)
        if not before and not after:
            return example
        from dataclasses import replace
        return replace(example, before=before, after=after)

    return [scoped(example) for example in basis]


class ContributionKind(Enum):
    """What a contributor is offering. None of these are evidence."""
    HYPOTHESIS = "hypothesis"          # a candidate rule to consider
    SITUATION = "situation"            # an experiment worth running
    FORMALIZATION = "formalization"    # a structure read out of unstructured input
    LESSON = "lesson"                  # teaching material


from dataclasses import dataclass as _dataclass, field as _field


@_dataclass(frozen=True)
class Contribution:
    """An offer from a proposer. Carries no confidence, deliberately: a
    proposer's certainty about its own output is not a measurement of the world,
    and admitting one would let a fluent contributor grade its own work."""
    contributor: str
    kind: ContributionKind
    payload: Any
    rationale: str = ""
    domain_id: Optional[str] = None


@_dataclass
class Admission:
    """What the authority did with a contribution, and why."""
    accepted: bool
    reason: str
    contributor: str
    kind: ContributionKind
    #: Always CANDIDATE when accepted. A contribution cannot arrive validated.
    status: Optional["EpistemicStatus"] = None
    rule_id: Optional[str] = None

    @property
    def is_knowledge(self) -> bool:
        """Never true on admission. Present so callers cannot forget to ask."""
        return self.status is EpistemicStatus.VALIDATED


class FeatureEncoder:
    """Symbolic features → the boolean vector a clause machine reads.

    An OBJECT rather than a closure, deliberately: the encoder has to survive the
    process, and a lambda over a captured vocabulary does not. A classifier that
    comes back from disk without its encoder is not a degraded classifier, it is a
    broken one — it gets handed whatever its route passes (a file path, for a
    vision route) and asked to treat that as features.

    The vocabulary is FIXED at training time and the order is the contract: bit k
    is `vocabulary[k]`. A feature the classifier never trained on is dropped
    rather than appended, because appending would shift every later bit and quietly
    re-map every clause the machine learned.
    """

    __slots__ = ("vocabulary", "_index")

    def __init__(self, vocabulary: Sequence[str]) -> None:
        self.vocabulary: Tuple[str, ...] = tuple(str(v) for v in vocabulary)
        self._index = {v: i for i, v in enumerate(self.vocabulary)}

    def __len__(self) -> int:
        return len(self.vocabulary)

    def __call__(self, features) -> "Any":
        import numpy as np
        bits = np.zeros(len(self.vocabulary), dtype=np.int8)
        for f in (features or ()):
            k = self._index.get(str(f))
            if k is not None:
                bits[k] = 1
        return bits

    def unknown(self, features) -> Tuple[str, ...]:
        """Features this encoder has no bit for — what the machine cannot see
        about this instance. Surfaced so a caller can tell a confident vote over
        a well-covered instance from one over an instance it is half blind to."""
        return tuple(sorted({str(f) for f in (features or ())
                             if str(f) not in self._index}))


class UnifiedLearningSystem(ILearningAuthority, ILearningSystem):
    """Unified learning system that coordinates all learning components"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, domain_master=None):
        # The authority core: what owns the rule store, the inducer, and the
        # propose/attest boundary. This class IS the learning authority (its
        # induction/contribute methods are below), so these back its own state.
        self._store: Any = None
        self._inducer: Any = None
        self._contributors: Dict[str, str] = {}
        self._admissions: List["Admission"] = []
        #: Parametric perceptual learners (Convolutional Tsetlin Machines) OWNED
        #: by the authority: {name: {"model": CTM, "labels": [class->category],
        #: "encode": callable|None}}. The model is a MECHANISM; its recognitions
        #: are knowledge only once they pass the gate via `recognize` -> learn_fact.
        self._clause_classifiers: Dict[str, Dict[str, Any]] = {}
        self.config = config or {}
        self.domain_master = domain_master
        self.initialized = False

        # Initialize components
        self.memory_system = None  # Will be injected by main.py
        meta_db_path = config.get('meta_learning_db_path', 'meta_learning.db') if config else 'meta_learning.db'
        # Use global MetaLearner singleton so meta-learning is shared
        self.meta_learning = get_meta_learner(config=self.config.get("meta_learning_config"))

        # Domain knowledge integration for transfer learning (use singletons)
        self.domain_registry = None
        self.universal_ontology = None
        self.cross_domain_reasoner = None  # Will be initialized in initialize() method - needs domain_registry and universal_ontology

        self.domain_learning_stats = {
            "cross_domain_transfers": 0,
            "domain_specific_learning": 0,
            "transfer_learning_successes": 0
        }

        # Logging Database - For comprehensive learning activity logging (compliance & accountability)
        self.log_db = LoggingDatabase()
        # Note: Will be initialized in async start() method

        # System state. The queue is bounded: it used to grow for the life of
        # the process because nothing ever removed from it.
        self.active_learning_tasks = []
        self._max_queued_events = 200
        #: Strong references to in-flight event tasks. Without these, asyncio
        #: only holds a weak reference and a task can be garbage-collected
        #: mid-flight, losing the learning silently.
        self._event_tasks: set = set()
        # PER-PROCESS COUNTERS ONLY. These reset on restart, which is fine for
        # what they are, but they must not be confused with the recorded totals
        # -- `get_learning_metrics` reports both, labelled.
        #
        # `knowledge_base_size` was removed from here: nothing ever assigned it,
        # so it was reported as 0 forever, including in the Slack milestone
        # ("Knowledge Base Size: 0"). It is measured now, from the stores that
        # actually hold knowledge.
        self.system_metrics = {
            "total_learning_sessions": 0,
            "successful_adaptations": 0,
            "cross_domain_insights": 0
        }

        # Exploration quota tracking (for MetaLearner hard gate)
        self.recent_strategy_usage = []  # Track last 100 strategy selections
        self.max_recent_strategies = 100

        # Circular dependency guard. The depth itself lives in the
        # `_learning_depth` ContextVar so it is per-task; only the limit is
        # configurable state on the instance.
        self._max_nesting_depth = 3

        # Slack notifier for learning milestones
        self.slack_notifier = get_slack_notifier()
    
    #: Fire-and-forget notification tasks, held so the event loop cannot
    #: garbage-collect them mid-flight. asyncio keeps only a weak reference to a
    #: task, so a create_task() whose result nobody stores can vanish before it
    #: runs -- silently, and only sometimes.
    _pending_notifications: set = set()

    def _notify(self, **kwargs) -> None:
        """Send a Slack notification WITHOUT holding the learning path.

        A notification is a side effect. Whether a chat message was delivered
        says nothing about whether learning succeeded, so nothing here waits to
        find out.

        This was `self._notify(...)` at six sites,
        and the cost of that landed somewhere it had no business being: every
        AbstractReasoningEngine.reason() call blocked indefinitely at
        `_update_learning`, because reasoning -> learning -> notification, and
        the notification would not resolve. Instrumenting the awaits showed it
        exactly --

            ENTER select_strategy  EXIT 4ms
            ENTER store_memory     EXIT 148ms
            ENTER slack            (never exits)

        -- so every registered kind of thinking was unreachable through its own
        engine because a webhook was unreachable. `SEND_DEADLINE_SECONDS` in the
        notifier now bounds that at 35 s for every caller, but a bound is not
        the same as not waiting: reasoning should not pay 35 s either, and it
        has no reason to wait even 35 ms.

        Failures are logged and dropped. There is nothing sensible for a
        learning routine to DO about an undelivered chat message.
        """
        notifier = getattr(self, "slack_notifier", None)
        if notifier is None:
            return
        try:
            task = asyncio.ensure_future(notifier.send_notification(**kwargs))
        except RuntimeError:
            # No running loop -- called from sync context during teardown.
            logger.debug("notification skipped: no running event loop")
            return
        self._pending_notifications.add(task)
        task.add_done_callback(self._pending_notifications.discard)

        def _log_failure(finished):
            if finished.cancelled():
                return
            error = finished.exception()
            if error is not None:
                logger.warning("notification failed: %s: %s",
                               type(error).__name__, error)
        task.add_done_callback(_log_failure)

    async def start(self) -> None:
        """Start the unified learning system

        Raises:
            RuntimeError: If critical learning components fail to initialize
        """
        try:
            # Initialize logging database
            await self.log_db.initialize()
            logger.info("✅ Logging database initialized for learning activity tracking")

            # The learning system holds no model handle. A language model is the
            # TEACHER's alone; learning here is substrate-native (it proposes
            # candidates; evidence attests). Nothing in this file generates.

            # CRITICAL: Get memory system if not already set
            if self.memory_system is None:
                logger.info("Getting memory system from global singleton...")
                from core.memory import get_memory_agent
                self.memory_system = await get_memory_agent()

            # "CONNECTED" WAS ASSERTED, NOT CHECKED.
            #
            # get_memory_agent() returns the singleton WITHOUT initialising it
            # -- its own docstring tells the caller to await initialize()
            # next -- and this logged the tick regardless. Verified:
            # get_learning_state() reported memory_system_active=False right
            # after start() said the memory system was connected. It worked
            # anyway only because store_memory initialises lazily on first use,
            # so the first learning call of every process paid that cost and
            # any failure surfaced there instead of here.
            #
            # initialize() is idempotent (it returns early when already
            # initialised), so calling it is safe whoever else has.
            if hasattr(self.memory_system, "initialize"):
                await self.memory_system.initialize()

            if not getattr(self.memory_system, "initialized", False):
                raise RuntimeError(
                    "Memory system did not initialise; learning would be "
                    "recorded against a store that is not ready")

            logger.info("✅ Memory system connected and initialised")

            # Get domain systems if not already set
            if self.domain_registry is None:
                logger.info("Getting domain registry from global singleton...")
                from core.domain.domain_registry import get_domain_registry
                self.domain_registry = get_domain_registry()

            if self.universal_ontology is None:
                logger.info("Getting universal ontology from global singleton...")
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()

            if self.cross_domain_reasoner is None:
                logger.info("Getting cross-domain reasoner from global singleton...")
                from core.domain.cross_domain_reasoner import get_cross_domain_reasoner
                self.cross_domain_reasoner = get_cross_domain_reasoner()

            logger.info("✅ Domain systems connected")
            
            # CRITICAL: Initialize meta-learning system
            logger.info("Initializing meta-learning system...")

            await self.meta_learning.initialize()  # This raises on failure

            if not self.meta_learning.active:
                raise RuntimeError("MetaLearningSystem is not active after initialization")

            logger.info("✅ Meta-learning system initialized")

            # The authority's own recognised proposers. contribute() (and
            # admit_projection) admit a proposal ONLY from a registered
            # contributor -- an anonymous proposal has no traceable origin and
            # is rejected. Registration is provenance, not permission to attest:
            # what is admitted enters as a CANDIDATE with zero evidence, and only
            # the world attests.
            #
            # Only faculties that propose a RULE HYPOTHESIS are named here. The
            # analogy engine is the one such proposer today: it used to write
            # projected operators straight into the store, and now proposes them
            # through admit_projection(). The causal analyzer is NOT here: it is
            # a diagnostic that reasons via
            # the neural bridge and writes no rules. Neither bypasses the store,
            # so neither is a rule contributor.
            self._contributors.setdefault(
                "analogical_projection", "structural-analogy operator proposer")
            logger.info("✅ Learning contributors registered: %s",
                        ", ".join(sorted(self._contributors)))

            # Reload any persisted clause classifiers so a trained perceptual
            # learner survives a restart (its recognitions already persist as
            # beliefs; this restores the MECHANISM that produces them).
            try:
                restored = self.load_classifiers()
                if restored:
                    logger.info("Restored %d persisted clause classifier(s)", restored)
            except Exception as error:
                logger.warning("clause-classifier reload failed: %s", error)

            self.initialized = True
            logger.info("✅ Unified learning system started successfully")

            # NOTE: No Slack notification here - system startup notification is sent by main.py
            # to avoid duplicate notifications

        except RuntimeError as re:
            # RuntimeError we raised - just re-raise
            self.initialized = False

            # 📢 Slack alert for initialization failure
            self._notify(
                message=f"🚨 **Learning System Initialization Failed**\n"
                        f"• Error: {str(re)}\n"
                        f"• Type: RuntimeError\n"
                        f"• Impact: Learning functionality unavailable\n"
                        f"• Action: Check component initialization",
                channel="ALERTS",
                severity="error"
            )
            raise

        except Exception as e:
            logger.error(f"Unexpected error starting unified learning system: {e}")
            self.initialized = False

            # 📢 Slack alert for unexpected initialization error
            self._notify(
                message=f"🚨 **Learning System Critical Error**\n"
                        f"• Error: {type(e).__name__}\n"
                        f"• Message: {str(e)}\n"
                        f"• Impact: Learning system failed to start\n"
                        f"• Action: Review logs for full stack trace",
                channel="ALERTS",
                severity="error"
            )

            raise RuntimeError(
                f"Unexpected error during learning system initialization: {e}\n"
                f"Check logs for full stack trace."
            ) from e
    
    async def _report_unmapped_learning_type(self, learning_type_name: str) -> None:
        """Record that a learning type has no family, on the failure record.

        A warning in a log file is what the CLASSIFICATION default effectively
        was -- invisible to every consumer. This puts it where the systems that
        watch for gaps can read it.
        """
        try:
            from core.observability import failure_record

            await failure_record.report(
                component="learning.unified_learning_system",
                failure_type="unmapped_learning_type",
                description=(f"Learning type {learning_type_name!r} has no "
                             f"TaskFamily; the example could not be scored "
                             f"against any strategy pool"),
                source_system="unified_learning_system",
                severity="medium",
                metadata={"learning_type": learning_type_name})
        except Exception as error:
            logger.error("Could not report unmapped learning type %r: %s",
                         learning_type_name, error)

    async def learn_from_example(self, example: Dict[str, Any]):
        """Learn from example - route to memory system + meta-learning

        This method NO LONGER uses learning_engine (deleted).
        Instead, it routes to:
        1. Meta-learning for strategy selection
        2. Memory system for persistent storage
        3. Meta-learning for outcome tracking

        Raises:
            RuntimeError: If circular dependency detected (learning calling learning)
        """
        if not self.initialized:
            await self.start()

        # CIRCULAR DEPENDENCY GUARD. Counts recursion within THIS task only, so
        # parallel learning is not mistaken for a cycle. See _learning_depth.
        depth = _learning_depth.get() + 1
        if depth > self._max_nesting_depth:
            logger.error(
                "🛑 CIRCULAR DEPENDENCY DETECTED: learning recursed %d levels "
                "within one task (limit %d)", depth, self._max_nesting_depth)
            raise RuntimeError(
                f"Circular dependency detected: learning called itself {depth} "
                f"levels deep within a single task. This prevents deadlock. "
                f"Check for autonomous_coordinator <-> learning circular calls."
            )
        if depth > 1:
            logger.warning("Learning nested call within one task (depth %d)", depth)

        depth_token = _learning_depth.set(depth)

        start_time = time.time()
        learning_id = str(uuid.uuid4())

        try:
            # KNOWLEDGE FIRST, through the one gate. This lane credits a strategy,
            # but if the example STATES a fact, that fact is knowledge and must be
            # admitted / believed / filed like any taught fact -- not left only in
            # a strategy posterior or a memory row. Fires before the strategy
            # machinery so a declarative claim lands even when no strategy pool
            # maps to this learning type. A payload that states no claim routes
            # nothing (the credit invariant).
            await self._route_declarative_takeaway(
                example, domain=str(example.get('domain') or 'conversation'))

            # Extract learning type.
            #
            # Accepted as either the enum or its value, because the mapping
            # below is keyed by the ENUM: a producer that states
            # 'type': 'continual' would otherwise miss the lookup and fall to
            # the CLASSIFICATION default while appearing to have declared
            # itself. An unrecognised name is reported rather than silently
            # becoming SUPERVISED.
            learning_type = example.get('type') or LearningType.SUPERVISED
            if not isinstance(learning_type, LearningType):
                try:
                    learning_type = LearningType(str(learning_type).lower())
                except ValueError:
                    logger.warning(
                        "Unknown learning type %r; treating as SUPERVISED",
                        learning_type)
                    learning_type = LearningType.SUPERVISED
            learning_type_name = learning_type.value

            # 🧠 Use meta-learning to select optimal strategy with HARD GATE
            logger.info(f"📚 Learning from example (type: {learning_type_name})")

            # Calculate exploration quota used
            exploration_quota = self._calculate_exploration_quota()

            # Two different taxonomies meet here. This layer describes HOW it is
            # learning (LearningType: supervised/unsupervised/...); meta_learning
            # keys its strategies by WHAT KIND of task it is (TaskFamily:
            # classification/perception/...). Passing a LearningType straight
            # through never matched any registered strategy, so select_strategy
            # returned None and the next line dereferenced it.
            # The map is a LOSSY BRIDGE and the producer often knows better.
            # Six LearningTypes fan into eight TaskFamilies, so REASONING is
            # reachable only via META and CONTROL/GENERATION/REGRESSION not at
            # all. A reasoning engine reporting a derivation had to arrive as
            # CONTINUAL and be scored against the sequence arms, which say
            # nothing about reasoning. A stated family is used as given; the map
            # remains the fallback for callers that only speak LearningType.
            stated_family = example.get('task_family')
            task_family = None
            if stated_family is not None:
                if isinstance(stated_family, TaskFamily):
                    task_family = stated_family
                else:
                    try:
                        task_family = TaskFamily(str(stated_family).lower())
                    except ValueError:
                        logger.warning(
                            "Unknown task_family %r; deriving from learning type",
                            stated_family)
            if task_family is None:
                task_family = _LEARNING_TYPE_TO_TASK_FAMILY.get(learning_type)
            if task_family is None:
                # NO DEFAULT FAMILY. A learning type with no family has no arm
                # pool to be scored against, and choosing one anyway credits a
                # strategy for work it did not do -- which is exactly how the
                # classification arms accumulated 10,601 decisions.
                #
                # This returns rather than continuing, matching the existing
                # `strategy is None` path a few lines down: everything after
                # this point is written around a selected strategy (usage
                # tracking, memory tags, outcome credit), so there is no
                # "learn anyway" branch to fall into. The caller gets a named
                # reason instead of a silent mis-filing.
                logger.warning(
                    "No task family for learning type %r; no strategy pool "
                    "exists for it (add it to _LEARNING_TYPE_TO_TASK_FAMILY "
                    "if it has one)", learning_type_name)
                await self._report_unmapped_learning_type(learning_type_name)
                return {'success': False, 'error': 'unmapped_learning_type',
                        'learning_type': learning_type_name}

            # CAPTURE THE DECISION so the outcome can be joined back onto it.
            #
            # select_strategy writes the decision row (chosen arm, propensity,
            # candidates, context) and hands back its id through _decision_sink;
            # track_learning_outcome closes that row with what actually
            # happened. This lane passed neither, so every decision it made was
            # written open and never closed: 1,891 of 1,894 rows sat at
            # outcome_known=false with performance_score NULL. The propensity
            # needed for off-policy estimation was being recorded faithfully and
            # the reward beside it never was, which is the half that cannot be
            # reconstructed afterwards.
            decision_sink: Dict[str, Any] = {}
            strategy = await self.meta_learning.select_strategy(
                task_type=task_family,
                prefer_fast=False,
                min_confidence=0.5,
                enable_hard_gate=True,  # HARD GATE: Block unreliable strategies
                exploration_quota_used=exploration_quota,
                # The BASE decision problem. Namespaced arms in the same family
                # (executor:*, tasktype:*) belong to the coordinator's own
                # decisions and are not alternatives to a learning strategy.
                exclude_namespaced=True,
                decision_context={'learning_type': learning_type_name,
                                  'domain': example.get('domain'),
                                  'source': example.get('source')},
                _decision_sink=decision_sink,
            )
            decision_id = decision_sink.get("decision_id")

            gate_blocked = decision_sink.get("gate_blocked")
            if strategy is None and gate_blocked is None:
                logger.error(
                    f"No learning strategy available for {learning_type} "
                    f"(mapped to {task_family}). Registered families: "
                    f"{sorted({s.task_type.value for s in self.meta_learning.strategies.values()})}"
                )
                return {'success': False, 'error': 'no_strategy_available'}

            # Every arm failed the production gate. The example is still
            # learned from -- stored, and its domain still consulted for
            # transfer -- but no arm is credited with it, because none was fit
            # to be chosen. The selection is recorded so the exploration budget
            # counts it as a decision that spent none.
            self._track_strategy_usage(strategy)

            if strategy is not None:
                logger.info(
                    f"🎯 Meta-learning selected strategy: {strategy.strategy_type} "
                    f"(trials={strategy.trials}, success_rate={strategy.success_rate:.1%}, "
                    f"exploration_quota={exploration_quota:.1%})"
                )

            # 💾 ASK memory agent to store (it handles categorization, weighting, type)
            memory_id = None
            if self.memory_system:
                # Memory agent decides: memory_type, priority, worthiness, categorization
                # We just provide content + source_context (raw metadata)
                success, memory_id = await self.memory_system.store_memory(
                    content=f"Learning: {example.get('content', str(example)[:200])}",
                    importance_score=example.get('accuracy', 0.5),  # Hint for importance weighting
                    # strategy.strategy_id, not the dataclass. Memory lowercases
                    # every tag, so passing the object raised
                    # "'LearningStrategy' object has no attribute 'lower'" and
                    # the memory was rejected -- which surfaced only as
                    # "Memory agent rejected: None".
                    tags=['learning', learning_type_name, 'unified_learning_system']
                         + ([strategy.strategy_id] if strategy is not None else []),
                    # JSON-safe at the boundary. 'example_data' is the
                    # producer's payload verbatim and this column is serialised
                    # as JSON, so one enum or dataclass in it loses the whole
                    # memory.
                    source_context=_json_safe({
                        'learning_id': learning_id,
                        'learning_type': learning_type_name,
                        'strategy': strategy.strategy_id if strategy is not None else None,
                        'strategy_type': (str(strategy.strategy_type)
                                          if strategy is not None else None),
                        'strategy_gate_blocked': gate_blocked,
                        # The OUTCOME AS STATED, not defaulted to a win. This
                        # read `example.get('success', True)`, so an example
                        # that said nothing was persisted as a success while the
                        # credit path below correctly recorded it as unknown --
                        # the stored record and the posterior disagreed.
                        'success': example.get('success'),
                        'accuracy': example.get('accuracy', 0.0),
                        'timestamp': time.time(),
                        'source': 'unified_learning_system',
                        'example_data': example
                    })
                )

                if success:
                    logger.info(f"💾 Memory agent stored learning: {memory_id}")
                else:
                    logger.warning(f"⚠️  Memory agent rejected: {memory_id}")

                # 📢 Slack notification for important learning milestones
                # STATED, not defaulted. `example.get('success', True)` fired
                # this "High-Accuracy Learning Achieved" alert for examples that
                # said nothing about their outcome -- while the credit path
                # below correctly classed the very same example as
                # INSUFFICIENT_EVIDENCE. The notification claimed a win the
                # posterior refused to award.
                if (strategy is not None and example.get('success') is True
                        and example.get('accuracy', 0.0) > 0.9):
                    self._notify(
                        message=f"🎓 **High-Accuracy Learning Achieved**\n"
                                f"• Type: {learning_type}\n"
                                f"• Strategy: {strategy.strategy_id}\n"
                                f"• Accuracy: {example.get('accuracy', 0.0):.2%}\n"
                                f"• Memory ID: {memory_id}",
                        channel="ACTIVITY",
                        severity="info"
                    )
            else:
                logger.warning("⚠️  Memory system not available - learning NOT persisted!")

                # 📢 Slack alert for missing memory system
                self._notify(
                    message="⚠️ **Learning System Warning**\n"
                            f"Memory system unavailable - learning experience NOT persisted!\n"
                            f"Learning ID: {learning_id}",
                    channel="ALERTS",
                    severity="warning"
                )

            # 📊 Track outcome in meta-learning for strategy optimization
            #
            # `example.get('success', True)` defaulted an unknown outcome to a
            # win, so any example lacking the key silently rewarded whatever
            # strategy was selected. Absent means unknown, and unknown earns no
            # credit.
            from core.learning.meta_learning import OutcomeClass, is_credit_eligible
            raw_success = example.get('success')
            if isinstance(raw_success, bool):
                success = raw_success
                outcome_class = (
                    OutcomeClass.SUCCESS if success else OutcomeClass.STRATEGY_FAILURE
                )
            else:
                success = False
                outcome_class = OutcomeClass.INSUFFICIENT_EVIDENCE
            metrics = {
                'accuracy': example.get('accuracy', 0.0),
                'confidence': example.get('confidence', 0.0),
                # The duration of the WORK, when the producer states it.
                # Measuring locally times this method's own bookkeeping -- 0.12s
                # against a 43s reasoning operation in the observed case -- and
                # that number becomes strategy.avg_time_ms and the efficiency
                # term of effectiveness_score, so the score would rank
                # strategies by how fast their paperwork was.
                'latency': float(
                    example.get('duration_s') or (time.time() - start_time)),
            }

            # Signature is (task_type, strategy_type, success, performance_score,
            # time_ms). It was called with strategy=/metrics=, which raised
            # TypeError on every invocation — so the bandit's successes/failures
            # never incremented and Thompson sampling drew from Beta(1,1) forever.
            if strategy is not None:
                await self.meta_learning.track_learning_outcome(
                    task_type=task_family,
                    strategy_type=strategy.strategy_type,
                    success=success,
                    performance_score=float(metrics.get('accuracy') or 0.0),
                    time_ms=float(metrics.get('latency') or 0.0) * 1000.0,
                    outcome_class=outcome_class,
                    context={'confidence': metrics.get('confidence'),
                             'learning_type': learning_type_name},
                    decision_id=decision_id,
                )

            # Update system metrics
            self.system_metrics['total_learning_sessions'] += 1
            if success:
                self.system_metrics['successful_adaptations'] += 1

            logger.info(f"✅ Learning complete in {metrics['latency']:.2f}s - Success: {success}")

            # CRITICAL: Log learning activity for compliance.
            #
            # This called log_activity(activity_type=, details=), which is not on
            # LoggingDatabase -- the class exposes log_operation(operation_type,
            # component, message, level, metadata). It sits in the SUCCESS path,
            # directly after "Learning complete", so every successful
            # learn_from_example raised AttributeError here; the except handler
            # then called the same missing method and raised again, so the
            # original outcome was never reported either. learn_from_example is
            # the one learning entry point the coordinator invokes.
            await self.log_db.log_operation(
                operation_type='learning',
                component='unified_learning_system',
                message=f"learning {learning_id} success={success}",
                level='INFO',
                metadata={
                    'learning_id': learning_id,
                    'learning_type': learning_type_name,
                    'strategy': strategy.strategy_id if strategy is not None else None,
                    'strategy_type': (str(strategy.strategy_type)
                                      if strategy is not None else None),
                    'strategy_gate_blocked': gate_blocked,
                    'success': success,
                    'accuracy': example.get('accuracy', 0.0),
                    'latency': metrics['latency'],
                    'memory_id': memory_id,
                    'source': example.get('source', 'user_interaction')
                }
            )

            # 📢 Slack notification for learning milestones (every 100 adaptations)
            if self.system_metrics["successful_adaptations"] % 100 == 0 and success:
                self._notify(
                    message=f"🎓 **Learning Milestone Reached**\n"
                            f"• Total Sessions: {self.system_metrics['total_learning_sessions']}\n"
                            f"• Successful Adaptations: {self.system_metrics['successful_adaptations']}\n"
                            f"• Latest Accuracy: {example.get('accuracy', 0.0):.2%}",
                    channel="ACTIVITY",
                    severity="success"
                )

            # CROSS-DOMAIN: learning in a domain looks for what it already
            # knows elsewhere.
            #
            # Every part of this existed and none of it was reachable:
            # self.cross_domain_reasoner was assigned at :169 and never read,
            # transfer_learning_across_domains (:822) had zero callers,
            # learn_with_domain_context (:897) had zero callers, and the
            # cross_domain_transfers / cross_domain_insights counters were
            # incremented by code nothing invoked. learn_from_example is the one
            # entry point the coordinator actually calls, so the transfer path
            # attaches here rather than to a new lane beside it.
            transfer = None
            domain = example.get('domain') or example.get('domain_id')
            if domain:
                # Gated on the DOMAIN, not on `success`. `success` here is the
                # credit signal -- it reports whether the selected strategy
                # earned credit, and an example that does not state its outcome
                # is INSUFFICIENT_EVIDENCE (:378-385) rather than a failure.
                # Whether a strategy earned credit is a different question from
                # whether Torin already holds a structure that applies here, and
                # an attempt that went badly is if anything MORE reason to ask
                # it. Gating on success meant the transfer path could not fire
                # for any example lacking an explicit outcome.
                transfer = await self._transfer_from_known_domains(
                    str(domain), task_id=example.get('task_id'))

            return {
                'success': success,
                # The IDENTIFIER. Returning the dataclass leaked an internal
                # object into every caller's payload, and anything that tried to
                # serialise the result failed on it.
                'strategy_used': strategy.strategy_id if strategy is not None else None,
                # Present when no arm passed the production gate: per-arm reasons.
                'strategy_gate_blocked': gate_blocked,
                'stored_in_memory': memory_id is not None,
                'memory_id': memory_id,
                'learning_id': learning_id,
                'metrics': metrics,
                'cross_domain': transfer,
                # WHY the outcome was what it was, and whether it moved a
                # posterior. `success` alone cannot separate "the strategy
                # failed" from "nothing could be concluded": both are False, and
                # only the first is evidence about the strategy. Callers that
                # need that distinction were reduced to guessing from it.
                'outcome_class': outcome_class.value,
                'credit_applied': strategy is not None and is_credit_eligible(outcome_class),
            }

        except Exception as e:
            logger.error(f"❌ Learning from example failed: {e}")

            # 📢 ROBUST Slack alert for learning failure
            self._notify(
                message=f"🚨 **Learning System Failure**\n"
                        f"• Error: {type(e).__name__}\n"
                        f"• Message: {str(e)}\n"
                        f"• Example Type: {example.get('type', 'unknown')}\n"
                        f"• Session: {self.system_metrics['total_learning_sessions']}\n"
                        f"• Successful Adaptations: {self.system_metrics['successful_adaptations']}",
                channel="ALERTS",
                severity="error"
            )

            # Log error with full stack trace
            import traceback
            try:
                await self.log_db.log_operation(
                    operation_type='learning_error',
                    component='unified_learning_system',
                    message=f"{type(e).__name__}: {e}",
                    level='ERROR',
                    metadata={
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                        'example_type': example.get('type', 'unknown'),
                        'stack_trace': traceback.format_exc()
                    }
                )
            except Exception as log_error:
                # An error handler that raises destroys the error it was handling.
                # This one called a missing method and replaced every real
                # learning failure with AttributeError: log_activity.
                logger.error("Could not record learning failure %r: %s", e, log_error)

            return {
                "success": False,
                "error": str(e),
                "strategy_used": None,
                "stored_in_memory": False
            }

        finally:
            # Restore this task's depth exactly as it was. A token reset cannot
            # leave the guard in a state that rejects future work, which the
            # previous flag-and-counter pair demonstrably could.
            _learning_depth.reset(depth_token)


    def _calculate_exploration_quota(self) -> float:
        """
        Calculate % of recent cycles that used exploration strategies

        Returns:
            Float 0.0-1.0 representing exploration quota used
        """
        if not self.recent_strategy_usage:
            return 0.0

        # Count strategies with < 20 trials (exploration threshold). A decision
        # in which no arm passed the gate (None) chose nothing and spent no
        # exploration; it still counts as a decision, or a budget exhausted once
        # would never recover.
        exploration_count = sum(
            1 for strategy in self.recent_strategy_usage
            if strategy is not None and strategy.trials < 20
        )

        return exploration_count / len(self.recent_strategy_usage)

    def _track_strategy_usage(self, strategy):
        """
        Track strategy usage for exploration quota calculation

        Args:
            strategy: LearningStrategy that was just used
        """
        # Add to recent usage
        self.recent_strategy_usage.append(strategy)

        # Keep only last N strategies
        if len(self.recent_strategy_usage) > self.max_recent_strategies:
            self.recent_strategy_usage.pop(0)

        if strategy is None:
            return
        logger.debug(
            f"Strategy usage tracked: {strategy.strategy_id} "
            f"(recent={len(self.recent_strategy_usage)}, "
            f"exploration={self._calculate_exploration_quota():.1%})"
        )

    async def process_interaction(self, user_input: str, system_response: str) -> None:
        """Process a user interaction for learning"""
        interaction_example = {
            "input": user_input,
            "output": system_response,
            "context": {"interaction_type": "chat", "timestamp": asyncio.get_event_loop().time()}
        }
        
        await self.learn_from_example(interaction_example)
    
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "initialized": self.initialized,
            "components": {
                "memory_system": getattr(self.memory_system, 'initialized', False),
                "meta_learning": getattr(self.meta_learning, 'initialized', False),
            },
            "metrics": self.system_metrics,
            "active_tasks": len(self.active_learning_tasks)
        }
    
    # ILearningSystem interface implementations
    async def initialize(self) -> bool:
        """Initialize the unified learning system
        
        Raises:
            RuntimeError: If initialization fails
        """
        await self.start()  # This raises on failure
        return True
    
    async def learn_from_data(self, data: Dict[str, Any], learning_type) -> Any:
        """Learn from provided data"""
        # The caller's learning_type has to travel INTO the example.
        #
        # It was only echoed back in the envelope below, while
        # learn_from_example reads example['type'] -- a key nothing ever set --
        # and so defaulted every event to SUPERVISED, which the table at :46
        # maps to CLASSIFICATION. learn_from_experience declares CONTINUAL and
        # the outcome was still recorded against CLASSIFICATION; the other five
        # TaskFamily branches were unreachable no matter what a caller asked
        # for. A payload that names its own type is the more specific statement
        # and still wins.
        result = await self.learn_from_example({'type': learning_type, **data})
        return {
            'event_id': f"unified_{int(time.time())}",
            'event_type': learning_type,
            'data': data,
            'outcome': result,
            'timestamp': time.time(),
            # The example's OWN stated confidence, or None. This was a literal
            # 0.8 on every envelope regardless of what happened -- including
            # for a learning call that failed -- so a caller reading it learned
            # only that someone had typed 0.8.
            'confidence': data.get('confidence'),
        }
    
    async def learn_from_experience(self, experience: Dict[str, Any]) -> Any:
        """Learn from experience data"""
        return await self.learn_from_data(experience, LearningType.CONTINUAL)
    
    async def learn_from_feedback(self, feedback: Dict[str, Any]) -> Any:
        """A verdict on a claim the substrate already made and already remembers.

        IT DOES NOT STORE A MEMORY OF ITS OWN. The interaction it is about
        already made one (the ingress `_remember`); a second record of the same
        thing would double-count it and split its evidence. This FLAGS that
        existing memory -- annotating it, never overwriting it -- and routes the
        verdict to the right owner.

        It also does NOT push a taught-fact verdict through the strategy-credit
        lane. A user agreeing or disagreeing with a fact is not evidence about
        which LEARNING STRATEGY was a good choice, and crediting an arm for it
        would teach the meta-learner a false relation (the exact defect the
        credit invariant exists to prevent). A strategy is credited only when
        the feedback is about a DECIDED action -- it carries a `decision_id`,
        and then the verdict is that decision's outcome.

        `feedback` keys: `memory_id` (the memory to flag), `success`
        (True confirms / False corrects), optional `content`/`about`, and --
        for action feedback only -- `decision_id`, `task_type`, `strategy_type`.
        """
        if not isinstance(feedback, dict):
            return {"event_type": "feedback", "memory_flagged": False,
                    "error": "feedback must be a dict carrying a memory_id"}

        memory_id = feedback.get("memory_id")
        verdict = bool(feedback.get("success"))

        # 1. FLAG THE EXISTING MEMORY -- merge only, so the claim's content and
        #    any prior metadata are untouched. `metadata` without merge, and
        #    `tags`, both REPLACE their column, so neither is used here.
        flagged = False
        if memory_id and self.memory_system and hasattr(self.memory_system, "update_memory"):
            try:
                flagged = await self.memory_system.update_memory(memory_id, {
                    "metadata": {"feedback": {
                        "verdict": "confirmed" if verdict else "corrected",
                        "surface": feedback.get("content"),
                        "about": feedback.get("about"),
                        "at": time.time(),
                    }},
                    "metadata.merge": True,
                })
            except Exception as error:
                raise_if_structural(error, "unified_learning_system.learn_from_feedback")
                logger.warning("feedback flag failed for %s: %s", memory_id, error)

        # NOTE: importance is a PROTECTED field (MemoryAgent gates
        # importance_score/confidence_score/memory_type behind a capability
        # token), so a correction does not silently rewrite the memory's weight
        # here -- that write would be refused and return False, a silent no-op.
        # The verdict lives in the flag; making a corrected memory actually
        # recall LESS is recall's job, reading metadata.feedback.verdict, and is
        # done there deliberately rather than smuggled through the gate.

        # 2. ACTION feedback (a decision was made) credits that decision's
        #    strategy; taught-fact feedback does not touch the meta-learner.
        credited = False
        decision_id = feedback.get("decision_id")
        task_type = feedback.get("task_type")
        strategy_type = feedback.get("strategy_type")
        if decision_id and task_type and strategy_type and self.meta_learning:
            from core.learning.meta_learning import OutcomeClass, TaskFamily
            try:
                family = task_type if isinstance(task_type, TaskFamily) else TaskFamily(str(task_type).lower())
                await self.meta_learning.track_learning_outcome(
                    task_type=family, strategy_type=strategy_type,
                    success=verdict,
                    performance_score=1.0 if verdict else 0.0,
                    time_ms=0.0, decision_id=decision_id,
                    outcome_class=(OutcomeClass.SUCCESS if verdict
                                   else OutcomeClass.STRATEGY_FAILURE))
                credited = True
            except Exception as error:
                raise_if_structural(error, "unified_learning_system.learn_from_feedback")
                logger.warning("feedback strategy credit failed: %s", error)

        # 3. FACT feedback moves the BELIEF, through the gate. A verdict on a
        #    claim the substrate made is evidence about that claim: a confirmation
        #    reinforces its posterior, a correction LOWERS it (the belief layer's
        #    own override/reversal path). A structured claim is admitted via
        #    learn_fact (positive=verdict); a bare claim string moves its existing
        #    posterior via observe_claim. Strategy credit (above) stays separate --
        #    a fact verdict is not evidence about a strategy (the credit invariant).
        belief_moved = False
        claim_domain = str(feedback.get("domain") or "conversation")
        if feedback.get("subject") and feedback.get("relation"):
            admission = await self._route_declarative_takeaway(
                {**feedback, "positive": verdict}, domain=claim_domain)
            belief_moved = bool(getattr(admission, "admitted", False))
        else:
            claim = feedback.get("claim") or feedback.get("content") or feedback.get("about")
            if isinstance(claim, str) and claim.strip():
                try:
                    self.observe_claim(claim, domain=claim_domain, supports=verdict,
                                       source="feedback")
                    belief_moved = True
                except Exception as error:
                    raise_if_structural(error, "unified_learning_system.learn_from_feedback")
                    logger.warning("feedback belief move failed: %s", error)

        return {
            "event_type": "feedback",
            "memory_id": memory_id,
            "memory_flagged": flagged,
            "verdict": "confirmed" if verdict else "corrected",
            "strategy_credited": credited,
            "belief_moved": belief_moved,
        }
    
    async def transfer_learning(self, source_domain: str, target_domain: str) -> bool:
        """Transfer learning between domains.

        Delegates to the real implementation. This returned a bare ``True``
        unconditionally -- reporting a transfer that was never attempted, while
        transfer_learning_across_domains sat 200 lines below doing the actual
        work of proposing, validating and persisting the mappings.
        """
        result = await self.transfer_learning_across_domains(
            source_domain, target_domain, {"trigger": "transfer_learning"})
        return bool(result.get("success"))
    
    async def knowledge_base_size(self) -> Optional[Dict[str, int]]:
        """What the substrate actually holds, by store. None if unreadable.

        There was a `knowledge_base_size` counter in `system_metrics` that
        nothing ever wrote to, so every consumer -- including the Slack
        milestone -- reported 0. A count of what is known is measurable; it was
        just never measured.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            rows = await db.execute_query(
                """SELECT (SELECT count(*) FROM unified.concepts)            AS concepts,
                          (SELECT count(*) FROM unified.learned_rules)       AS rules,
                          (SELECT count(*) FROM memory_hot.memory_hot)       AS memories""",
                None, fetch_all=True)
        except Exception as error:
            logger.error("Knowledge base size unavailable: %s", error)
            return None
        if not rows:
            return None
        row = rows[0]
        return {"concepts": int(row["concepts"]), "rules": int(row["rules"]),
                "memories": int(row["memories"]),
                "total": int(row["concepts"]) + int(row["rules"]) + int(row["memories"])}

    async def get_learning_metrics(self) -> Dict[str, Any]:
        """Learning metrics: this process's counters, and the recorded totals.

        Returned `self.system_metrics` alone -- three counters that start at
        zero every run. A caller asking a long-lived system how much it had
        learned got whatever had happened since the last restart, with nothing
        saying so.
        """
        try:
            recorded = await self.get_experience_count()
        except RuntimeError as error:
            # None, not 0: an unreadable store is not an empty one.
            logger.error("Recorded experience count unavailable: %s", error)
            recorded = None
        return {
            "this_process": dict(self.system_metrics),
            "recorded_experiences": recorded,
            "knowledge_base": await self.knowledge_base_size(),
            # TOOL METRICS the engine emits per run — success rate and latency,
            # per tool — from the one collector (AdaptiveToolLearning /
            # tool_usage_history). Surfaced here so "what has it learned" includes
            # how its tools actually perform, not just what it holds.
            "tool_usage": await self._tool_usage_metrics(),
        }

    async def _tool_usage_metrics(self) -> Optional[Dict[str, Any]]:
        """The tool-metrics summary from the owner, or None if unavailable.
        Read through the owner (the single collector), never a second query."""
        try:
            from core.learning.adaptive_tool_owner import get_adaptive_tool_learning
            return await get_adaptive_tool_learning().metrics_summary()
        except Exception as error:
            logger.debug("tool-usage metrics unavailable: %s", error)
            return None

    async def get_learning_state(self) -> Dict[str, Any]:
        """Get current learning system state for self-improvement analysis"""
        return {
            'initialized': self.initialized,
            'active_tasks': len(self.active_learning_tasks),
            'total_learning_sessions': self.system_metrics.get('total_learning_sessions', 0),
            'successful_adaptations': self.system_metrics.get('successful_adaptations', 0),
            'knowledge_base': await self.knowledge_base_size(),
            # `x is not None` was true by construction for meta_learning (set
            # unconditionally in __init__) and for the other two after start(),
            # so all three reported "active" without checking anything. Each is
            # now asked whether it is actually initialised, and None means the
            # component is absent rather than inactive.
            'memory_system_active': (None if self.memory_system is None
                                     else bool(getattr(self.memory_system, 'initialized', False))),
            'meta_learning_active': (None if self.meta_learning is None
                                     else bool(getattr(self.meta_learning, 'active', False))),
            'recent_tasks': self.active_learning_tasks[-5:] if self.active_learning_tasks else []
        }
    
    async def consolidate_learning(self) -> Dict[str, Any]:
        """Consolidate recent learning. NOT IMPLEMENTED.

        Returned {'consolidated': True} without consolidating anything.
        Consolidation is owned by the memory agent's tiering.
        """
        raise NotImplementedError(
            "consolidate_learning is not implemented. Memory consolidation is "
            "owned by MemoryAgent (hot/cold tiering); call it there.")
    
    def learn_from_event(self, event: Dict[str, Any]) -> bool:
        """Learn from an autonomous system event. Returns whether learning began.

        THIS RETURNED True HAVING LEARNED NOTHING. It appended the event to
        `active_learning_tasks` -- a list that is only ever appended to, never
        drained and never learned from -- and reported success. The interface
        documents the return as "learning success", so every caller was told
        the event had been learned from when it had merely been remembered.
        The list also grew without bound for the life of the process.

        The method is synchronous and cannot await, so the event is handed to
        the real learning path as a task. The return value now states what
        actually happened: True when learning was started, False when there is
        no running loop to start it on -- in which case the event is queued and
        the queue is bounded.
        """
        record = {'type': 'event', 'data': event, 'timestamp': time.time()}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: nothing can be learned right now. Say so rather than
            # reporting success, and keep the queue bounded.
            self.active_learning_tasks.append(record)
            del self.active_learning_tasks[:-self._max_queued_events]
            logger.warning(
                "learn_from_event called with no running event loop; the event "
                "was queued (%d held) but nothing has been learned from it",
                len(self.active_learning_tasks))
            return False

        # The event's own fields travel into the example, so an event that
        # states its outcome earns or loses credit like any other example.
        example = {k: v for k, v in event.items() if k != 'type'}
        example.setdefault('type', event.get('type', LearningType.CONTINUAL))
        example.setdefault('source', 'autonomous_event')

        task = loop.create_task(self.learn_from_example(example))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

        record['task_scheduled'] = True
        self.active_learning_tasks.append(record)
        del self.active_learning_tasks[:-self._max_queued_events]
        return True

    
    async def predict_optimal_retry_delay(self, context: Dict[str, Any]) -> float:
        """Predict optimal retry delay. NOT IMPLEMENTED.

        Returned the constant 3.0 while its name promised a prediction from
        context, so a caller could not tell a learned delay from a literal.
        """
        raise NotImplementedError(
            "predict_optimal_retry_delay is not implemented; it returned a "
            "hardcoded 3.0. Use an explicit backoff policy at the call site "
            "until a real predictor exists.")
    
    async def process_experience(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        """Process experience data for learning"""
        result = await self.learn_from_example(experience)
        return {'processed': True, 'unified_result': result}
    
    async def update_strategy_effectiveness(self, strategy: str, effectiveness: float) -> bool:
        """Update effectiveness for a strategy. NOT IMPLEMENTED.

        Wrote `strategy_<name>` keys into system_metrics -- a counters dict
        reported as system metrics -- creating a second, unpersisted copy of a
        number MetaLearner already owns, derives from trials and stores in
        meta_learning_strategies.effectiveness_score.
        """
        raise NotImplementedError(
            "update_strategy_effectiveness is not implemented. Strategy "
            "effectiveness is owned and persisted by MetaLearner; record the "
            "outcome via track_learning_outcome and let it derive the score.")
    
    async def recommend_strategies(self, context: Dict[str, Any]) -> List[str]:
        """Recommend strategies for a context. NOT IMPLEMENTED.

        Returned a fixed list of four subsystem names -- not strategies, not
        derived from the context, and not any arm the bandit can select.
        """
        raise NotImplementedError(
            "recommend_strategies is not implemented; it returned a fixed list "
            "of subsystem names. Use MetaLearner.select_strategy, which ranks "
            "real registered arms by their measured posteriors.")
    
    async def drain_events(self, timeout: float = 30.0) -> Dict[str, int]:
        """Wait for event-driven learning to finish. Call before shutting down.

        `learn_from_event` is synchronous and hands the work to a task, so if
        the process exits first that learning is abandoned mid-flight: the
        decision row was written when the arm was selected and the outcome
        never arrives. Verified -- one such row was left open by a test process
        that exited before its task completed.

        Returns what happened, so a caller can see whether the wait was enough
        rather than assuming it was.
        """
        pending = [t for t in self._event_tasks if not t.done()]
        if not pending:
            return {"pending": 0, "completed": 0, "timed_out": 0}

        logger.info("Draining %d in-flight learning task(s)", len(pending))
        done, not_done = await asyncio.wait(pending, timeout=timeout)
        if not_done:
            # Stated, not silently dropped: these will need reaping.
            logger.warning(
                "%d learning task(s) did not finish within %.0fs; their "
                "decisions will be closed as INDETERMINATE by the reaper",
                len(not_done), timeout)
        return {"pending": len(pending), "completed": len(done),
                "timed_out": len(not_done)}

    async def query_experiences(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search recorded learning experiences.

        THE QUERY WAS IGNORED. This returned the last ten entries of an
        in-process list regardless of what was asked for, so every query got
        the same answer and none of it survived a restart.

        `unified.operation_logs` is where `learn_from_example` records each
        completed experience (595 of them, all written by this component), so
        that is what a query searches. Supported keys: `learning_type`,
        `strategy`, `success`, `source`, `since_minutes`, `limit`.
        """
        clauses = ["component = 'unified_learning_system'",
                   "operation_type = 'learning'"]
        params: List[Any] = []

        for key in ("learning_type", "strategy", "source"):
            if query.get(key) is not None:
                params.append(str(query[key]))
                clauses.append(f"metadata->>'{key}' = ${len(params)}")
        if isinstance(query.get("success"), bool):
            clauses.append(
                f"(metadata->>'success')::boolean IS {str(query['success']).upper()}")
        if query.get("since_minutes"):
            clauses.append(
                f"created_at > NOW() - INTERVAL '{int(query['since_minutes'])} minutes'")

        limit = max(1, min(int(query.get("limit", 50)), 500))
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                f"SELECT log_id, message, metadata, created_at FROM unified.operation_logs "
                f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT {limit}",
                tuple(params) or None, fetch_all=True) or []
        except Exception as error:
            # Empty would read as "no experience matches", which is a different
            # answer from "the store could not be searched".
            logger.error("Experience query failed: %s", error)
            raise RuntimeError(
                f"Could not search recorded experiences: {error}") from error

        out: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            out.append({"log_id": row["log_id"], "message": row["message"],
                        "recorded_at": row["created_at"], **(metadata or {})})
        return out

    async def get_experience_count(self) -> int:
        """How many learning experiences have been recorded, in total.

        Counted `len(self.active_learning_tasks)` -- an in-process list that
        holds queued events rather than experiences, and starts empty every
        run. The recorded count is 595 and survives restarts.
        """
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                "SELECT count(*) AS n FROM unified.operation_logs "
                "WHERE component = 'unified_learning_system' "
                "  AND operation_type = 'learning'", None, fetch_all=True)
        except Exception as error:
            logger.error("Experience count unavailable: %s", error)
            raise RuntimeError(
                f"Could not count recorded experiences: {error}") from error
        return int(rows[0]["n"]) if rows else 0
    
    async def predict_outcome(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Predict an outcome for a context. NOT IMPLEMENTED.

        Returned predicted_success=0.85, confidence=0.8 and the reasoning
        string 'unified_learning_analysis' for every input -- constants dressed
        as an analysis, which is the one shape a consumer cannot detect as
        fabricated.
        """
        raise NotImplementedError(
            "predict_outcome is not implemented; it returned constant "
            "0.85/0.8 for every context. PredictiveIntelligenceSystem is the "
            "prediction owner.")

    async def _transfer_from_known_domains(self, target_domain: str,
                                           max_sources: int = 3,
                                           task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """When learning in a domain, ask what already-learned domain applies.

        This is the call site transfer_learning_across_domains never had. It
        answers the question the cross-domain layer exists for -- "does a
        structure I already hold fit this?" -- at the moment new learning
        arrives, which is when the answer can still change what is stored.

        Sources are ranked by the registry's own similarity so a transfer is
        attempted against the domains most likely to carry a correspondence,
        rather than every domain in the store. A domain never transfers from
        itself.
        """
        registry = self.domain_registry
        if registry is None:
            from core.domain.domain_registry import get_domain_registry
            registry = get_domain_registry()
            self.domain_registry = registry
        # Initialize REGARDLESS of who assigned it. start() (:156-159) sets
        # self.domain_registry from the singleton accessor and never awaits
        # initialize(), so registry.domains is empty and every domain reads as
        # "not registered" -- an assigned handle that is not a loaded registry.
        if not registry.initialized:
            await registry.initialize()

        # RESOLVE the reference; do not coerce it.
        #
        # This built `f"domain_{target_domain}"` by hand -- the exact coercion
        # resolve_domain_reference exists to replace. The live producer
        # (_infer_domain_from_task) classifies work into CATEGORIES
        # ("scientific", "technical"), and `domain_scientific` is a registered
        # domain holding ZERO concepts, so the coercion resolved to a real-but-
        # empty node and every transfer came back "nothing similar". The
        # concepts were never in the category; they are in the fields beneath
        # it, which is what the resolver returns.
        try:
            resolved = registry.resolve_domain_reference(
                target_domain, require_concepts=True)
        except UnresolvedDomainReference:
            # Naming something that does not exist is a different fact from
            # naming a real domain with nothing in it, and is kept separate.
            logger.info(
                "Cross-domain transfer skipped: %r resolves to no registered domain",
                target_domain)
            return {"attempted": False, "reason": "target domain not registered"}

        if not resolved:
            logger.info(
                "Cross-domain transfer skipped: %r resolves only to domains "
                "holding no concepts", target_domain)
            return {"attempted": False, "reason": "target domain holds no concepts"}

        # A category names many fields. Transfer INTO the best-attested one:
        # the resolver already ranks by concept count, and reasoning into every
        # member would multiply one observation into many transfers that share
        # a single piece of evidence.
        canonical = resolved[0].domain_id
        if len(resolved) > 1:
            logger.info(
                "%r resolved to %d populated field(s); transferring into %s",
                target_domain, len(resolved), canonical)

        from core.integration.universal_domain_master import get_universal_domain_master
        udm = get_universal_domain_master()
        try:
            # Through the Master -- the authority for the domain system.
            similar = await udm.similar_domains(canonical, threshold=0.0)
        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
            logger.warning("Similarity ranking unavailable: %s", e)
            return {"attempted": False, "reason": f"similarity unavailable: {e}"}

        # TWO-STAGE SELECTION: cheap filter, then rank on the real signal.
        #
        # Ranking by domain similarity alone correlates only 0.209 with the
        # concept-level mapping strength transfer actually consumes — they
        # answer different questions ("are these fields alike?" versus "do these
        # two concepts correspond?"). Ranking on the proxy put a domain with
        # ZERO mappings in the top three while domains at 0.80 were skipped.
        #
        # Concept-level mappings are the ground truth and cost a scoring pass per
        # domain pair, so similarity is used for what it is good for --
        # narrowing the field -- and the shortlist is then ordered by what will
        # actually be transferred.
        shortlist = [d.domain_id for d, _score in similar
                     if d.domain_id != canonical and d.concepts][:max_sources * 3]

        scored = []
        probe_failures = []
        for candidate in shortlist:
            try:
                mappings = await udm.suggest_mappings(candidate, canonical)
            except Exception as e:
                raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
                logger.error("Mapping probe %s -> %s failed: %s", candidate, canonical, e)
                probe_failures.append((candidate, f"{type(e).__name__}: {e}"))
                continue
            if mappings:
                scored.append((max(m.strength for m in mappings), len(mappings), candidate))

        scored.sort(reverse=True)
        sources = [c for _s, _n, c in scored[:max_sources]]
        if scored:
            logger.info(
                "Transfer sources for %s ranked by mapping strength: %s",
                canonical, [(c, round(s, 3)) for s, _n, c in scored[:max_sources]])
        if not sources:
            # Two different real negatives, kept apart. "No other populated
            # domain" is a statement about coverage; "populated domains exist
            # but none share a mapping" is a statement about correspondence, and
            # only the second says anything about this domain's relationship to
            # what Torin knows.
            if probe_failures:
                reason = (f"{len(probe_failures)} of {len(shortlist)} mapping probe(s) "
                          f"failed; the rest share no mapping")
            elif not shortlist:
                reason = "no other populated domain"
            else:
                reason = f"{len(shortlist)} domain(s) searched, none share a mapping"
            return {"attempted": True, "sources_considered": len(shortlist),
                    "transfers": [], "reason": reason, "probe_failures": probe_failures}

        transfers = []
        for src in sources:
            result = await self.transfer_learning_across_domains(
                src, canonical,
                {"trigger": "learn_from_example", "task_id": task_id})
            if result and result.get("success"):
                # "mapping_count" is the key transfer_learning_across_domains
                # actually returns. Reading "mappings_found" with a .get default
                # reported 0 mappings on every SUCCESSFUL transfer -- the same
                # source that had just been ranked first on 10 real mappings.
                # A default silently supplies a plausible value for a key that
                # does not exist, which is why the contradiction survived.
                #
                # It counts VALIDATED mappings. The candidate total is reported
                # beside it rather than in place of it, so a transfer can never
                # be read as larger than what survived validation.
                transfers.append({"source": src,
                                  "validated": result["mapping_count"],
                                  "candidates": result["candidates_considered"]})

        logger.info(
            "Cross-domain: learning in %s consulted %d known domain(s), %d transferred",
            canonical, len(sources), len(transfers))
        return {"attempted": True, "sources_considered": len(sources),
                "transfers": transfers, "probe_failures": probe_failures}

    async def transfer_learning_across_domains(self, source_domain: str, target_domain: str,
                                               knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Transfer learned knowledge from one domain to another"""
        try:
            logger.info(f"Transfer learning: {source_domain} -> {target_domain}")

            # THE ATTEMPT IS COUNTED HERE, THE SUCCESS BELOW.
            #
            # Both counters were incremented on the same line in the success
            # branch, so `transfer_learning_successes` was always exactly equal
            # to `cross_domain_transfers` and one of the two carried no
            # information -- while get_domain_learning_stats reported them side
            # by side as if they were independent facts. A success rate could
            # never be anything but 100%.
            self.domain_learning_stats["cross_domain_transfers"] += 1

            # Cross-domain mapping is owned by the Universal Domain Master: it
            # proposes the candidates and is the one writer of mappings,
            # transfers and their usage.
            from core.integration.universal_domain_master import get_universal_domain_master
            udm = get_universal_domain_master()

            # start() assigns the ontology handle without initialising it, the
            # same defect the registry had; validation would then run against an
            # unloaded ontology.
            if self.universal_ontology is None:
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()
            if not getattr(self.universal_ontology, "initialized", False):
                await self.universal_ontology.initialize()

            mappings = await udm.suggest_mappings(source_domain, target_domain)

            # VALIDATE, then PERSIST WITH THE VERDICT.
            #
            # The suggestion is a fresh proposal, and before this path stored
            # them nothing did, which is why unified.domain_mappings
            # held 0 rows while 29 candidates were being found. add_cross_domain_
            # mapping and create_knowledge_transfer both existed with zero
            # callers; each takes exactly the dataclass produced here.
            #
            # Every candidate is stored WITH what was decided about it:
            #   validated=True   structure survived the test -> knowledge
            #   validated=False  structure was measurable and did not correspond
            #   validated=None   too little structure to judge -> still a candidate
            # All three are persisted, because the readers of this table
            # (_load_mappings, UniversalDomainMaster._find_cross_domain_mappings)
            # select `verified IS NULL OR verified IS TRUE` -- they are built to
            # tell an untested proposal from a refuted one. Dropping the
            # indeterminate rows would throw away that distinction, and storing
            # any of them without a verdict is how a proposal silently becomes
            # knowledge.
            accepted, rejected, indeterminate = [], [], []
            for candidate in mappings:
                verdict = await self.universal_ontology.validate_cross_domain_mapping({
                    "source_concept_id": candidate.source_concept_id,
                    "target_concept_id": candidate.target_concept_id,
                })
                candidate.validation_score = float(verdict.get("confidence", 0.0) or 0.0)
                if verdict["verdict"] == "ACCEPTED":
                    candidate.validated = True
                    accepted.append(candidate)
                elif verdict["verdict"] == "REJECTED":
                    candidate.validated = False
                    rejected.append(candidate)
                else:
                    indeterminate.append(candidate)
                if not await udm.record_mapping(candidate):
                    raise RuntimeError(
                        f"Cross-domain mapping {candidate.mapping_id} could not be "
                        f"stored; refusing to report a transfer that was not recorded")

            logger.info(
                "Cross-domain %s -> %s: %d candidate(s) -> %d accepted, %d rejected, "
                "%d indeterminate",
                source_domain, target_domain, len(mappings),
                len(accepted), len(rejected), len(indeterminate))

            # Only a VALIDATED mapping may carry a transfer. This is the line
            # between transfer proposed and transfer learned.
            mapping = accepted[0] if accepted else None
            if mapping is not None:
                from core.domain.domain_types import KnowledgeTransfer
                # Identified by WHAT IS TRANSFERRED, not by when it ran. A uuid4
                # here wrote a fresh row on every pass, so re-deriving the same
                # transfer accumulated identical rows that a reader would count
                # as repeated independent transfers. Re-running now updates the
                # one row the transfer corresponds to.
                digest = hashlib.sha256("\x1f".join(
                    [source_domain, target_domain, "structural_analogy"]
                    + sorted(m.mapping_id for m in accepted)).encode()).hexdigest()[:32]
                transfer = KnowledgeTransfer(
                    transfer_id=f"xfer_{digest}",
                    source_domain_id=source_domain,
                    target_domain_id=target_domain,
                    source_knowledge_ids=[m.source_concept_id for m in accepted],
                    target_knowledge_ids=[m.target_concept_id for m in accepted],
                    transfer_type="structural_analogy",
                    success_probability=mapping.validation_score,
                    # mapping_ids -- the field is List[str], and the mappings are
                    # already persisted rows, so the transfer references them
                    # rather than restating the concept pairs.
                    concept_mappings=[m.mapping_id for m in accepted],
                    transferred_concepts=[m.target_concept_id for m in accepted],
                    validation_results={
                        "accepted": len(accepted), "rejected": len(rejected),
                        "indeterminate": len(indeterminate),
                    },
                    effectiveness_score=mapping.validation_score,
                )
                if not await udm.record_knowledge_transfer(transfer):
                    raise RuntimeError(
                        f"Knowledge transfer {transfer.transfer_id} could not be "
                        f"stored; refusing to report an unrecorded transfer")
                # APPLIED, not merely discovered. usage_count is what separates a
                # correspondence Torin keeps relying on from one it derived once,
                # and nothing had ever incremented it.
                # ATTRIBUTABLE. A usage event names the task it was applied to,
                # which is what lets transfer evaluation later ask "did the tasks
                # this mapping touched differ from the ones it did not?" rather
                # than only "did the domain improve afterwards?". Without a task
                # the application is unattributable, so it is not recorded as a
                # use at all.
                task_id = (knowledge or {}).get("task_id")
                if task_id:
                    await udm.record_mapping_usage(
                        [m.mapping_id for m in accepted],
                        task_id=str(task_id),
                        transfer_id=transfer.transfer_id,
                        provenance={"trigger": (knowledge or {}).get("trigger"),
                                    "source_domain": source_domain,
                                    "target_domain": target_domain})
                else:
                    logger.info(
                        "Transfer %s applied with no task identity; usage not "
                        "recorded (it could not be attributed to an outcome)",
                        transfer.transfer_id)

            if mapping:
                # Apply the mapping to transfer knowledge
                transferred_knowledge = {
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "original_knowledge": knowledge,
                    "transferred_knowledge": (
                        mapping.to_dict() if hasattr(mapping, "to_dict")
                        else str(mapping)
                    ),
                    # The counts are kept APART. "mapping_count" previously
                    # reported every candidate the similarity scan produced, so a
                    # transfer in which the validator accepted 2 of 10 was
                    # reported to the caller as 10 mappings -- the eight refuted
                    # ones counted as transferred knowledge.
                    "mapping_count": len(accepted),
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                    # The mapping's OWN confidence, or None. The default was
                    # 0.7, and `or 0.7` additionally rewrote a genuine 0.0 --
                    # so a mapping the validator had no confidence in was
                    # reported at 0.7, the same figure as one that was never
                    # measured.
                    "confidence": (float(mapping.confidence)
                                   if getattr(mapping, "confidence", None) is not None
                                   else None),
                    "success": True
                }

                self.domain_learning_stats["transfer_learning_successes"] += 1
                self.system_metrics["cross_domain_insights"] += 1

                logger.info(f"Transfer learning successful: {source_domain} -> {target_domain}")
                return transferred_knowledge
            else:
                # Two different negatives. "Nothing looked similar enough to
                # propose" and "things were proposed and the validator refuted
                # them" say opposite things about these two domains, and only
                # the second is evidence about their correspondence.
                if not mappings:
                    error, error_class = ("No candidate mapping proposed",
                                          "no_candidate")
                else:
                    error = (f"{len(mappings)} candidate(s) proposed, none validated "
                             f"({len(rejected)} refuted, {len(indeterminate)} unjudgeable)")
                    error_class = "no_validated_mapping"
                logger.info("Transfer learning %s -> %s: %s",
                            source_domain, target_domain, error)
                return {
                    "success": False,
                    "error": error,
                    "error_class": error_class,
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                }

        except UnknownDomain as e:
            logger.warning(f"Transfer learning on unregistered domain(s): {e}")
            return {
                "success": False,
                "error": str(e),
                "error_class": "unknown_domain",
                "unregistered_domains": e.missing,
            }
        except Exception as e:
            # A defect here must not come back as "no mapping found" -- that is
            # exactly how the missing find_cross_domain_mapping() stayed hidden.
            raise_if_structural(e, "UnifiedLearningSystem.transfer_learning_across_domains")
            logger.error(f"Error in transfer learning: {e}", exc_info=True)
            return {"success": False, "error": str(e), "error_class": "operational"}

    async def learn_with_domain_context(self, example: LearningExample,
                                        domain: str) -> LearningResult:
        """Learn from example with domain-specific context"""
        try:
            logger.info(f"Domain-specific learning in domain: {domain}")

            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = self.domain_registry = get_domain_registry()
            if not registry.initialized:
                await registry.initialize()

            # RESOLVE the reference. Do not create a domain from it.
            #
            # This did `get_domain(domain)` and, on a miss, REGISTERED a new
            # empty Domain named after the reference. The caller's references
            # are CATEGORIES ('scientific', 'technical') produced by
            # _infer_domain_from_task, so what it created were empty
            # category-level domains -- which is where the 15 concept-less
            # domains beside the 18 real fields came from. Each one then made
            # the category look registered and populated-by-zero, so every
            # lookup through it returned a well-formed empty answer.
            #
            # A domain is something Torin has learned, not something minted on
            # first mention. The registry already resolves a category to the
            # fields beneath it; the reference is answered, never invented.
            resolved = registry.resolve_domain_reference(domain, require_concepts=True)
            if not resolved:
                logger.info(
                    "Domain-specific learning skipped: %r holds no learned concepts",
                    domain)
                return LearningResult(
                    result_id=str(uuid.uuid4()),
                    success=False,
                    learned_knowledge={},
                    error=f"domain reference {domain!r} holds no learned concepts",
                    metadata={"domain": domain, "domain_specific": True,
                              # Both facts present on EVERY path. A caller that
                              # has to check which keys exist before reading
                              # them is back to guessing what a result means.
                              "learning_recorded": False,
                              "strategy_earned_credit": False,
                              "error_class": "domain_empty"},
                )

            # The FIELD is what carries concepts and what the transfer path
            # reasons over. The caller's original reference is kept in metadata
            # so a category-level question stays distinguishable from a
            # field-level one.
            field = resolved[0].domain_id
            if field != domain:
                logger.info("Domain reference %r resolved to field %s", domain, field)

            # Perform learning using unified learning system.
            #
            # A fourth defect in the same method: `{**example}` was spreading a
            # LearningExample dataclass, which is not a mapping ->
            # TypeError: 'LearningExample' object is not a mapping. TypeError is
            # in STRUCTURAL_DEFECT_TYPES, so raise_if_structural below re-raises
            # it and even the except-branch LearningResult never returns.
            # learn_from_example takes Dict[str, Any]; convert at the boundary.
            # Resolved before the payload so an unknown task type simply
            # leaves the family unstated rather than raising here.
            _stated_family = task_family_for_task_type(example.task_type)

            payload = {
                **asdict(example),
                'domain': field,
                'domain_specific': True,
                # STATED, not defaulted. Without a 'type' this fell to
                # SUPERVISED -> CLASSIFICATION, so every task outcome was scored
                # against the classification arms by omission rather than by any
                # decision. A completed task is experience accumulated over
                # time, which is what CONTINUAL names, and the existing table at
                # :48 maps it to SEQUENCE. This lane earned no credit at all
                # before the outcome was readable, so nothing it built up is
                # being moved.
                'type': LearningType.CONTINUAL,
                # THE FAMILY THE WORK ACTUALLY BELONGS TO.
                #
                # Without this the family came from LearningType.CONTINUAL ->
                # SEQUENCE, so a completed execution task was scored
                # against the sequence arms. The example already carries the
                # coordinator's task type; TASK_TYPE_TO_FAMILY is the authority
                # on what family that is, and two task types (execution,
                # planning) are CONTROL work -- the family whose arms choose
                # between APPROACHES and
                # which had never once been selected.
                #
                # Omitted when the task type is absent or unknown, so the
                # CONTINUAL mapping still applies rather than a guess.
                **({'task_family': _stated_family} if _stated_family else {}),
                # Lifted to the top level because the transfer path reads it
                # there. Without the task identity a mapping application cannot
                # be tied to the outcome it may have influenced, which is the
                # difference between counting uses and attributing them.
                'task_id': (example.inputs or {}).get('task_id'),
            }

            # THE OUTCOME THE PRODUCER RECORDED, LIFTED TO WHERE IT IS READ.
            #
            # TaskOutcomeRecord states the result as targets['outcome'] --
            # "success" or "failure" -- and its confidence as quality_score.
            # asdict() puts both one level down from where learn_from_example
            # looks (it reads top-level 'success' and 'accuracy'), so every task
            # outcome arrived stating nothing about how it went and was
            # correctly classified INSUFFICIENT_EVIDENCE. 269 consecutive
            # outcomes were recorded that way, 4 of the 5 underlying tasks
            # having actually succeeded: the strategy could never earn or lose
            # credit from the one signal this tier exists to deliver.
            #
            # Only an outcome that is actually stated is lifted. An example that
            # says nothing about how it went stays INSUFFICIENT_EVIDENCE, which
            # is the honest reading and the case the test at
            # test_domain_expansion_chain.py pins as (recorded=True,
            # credit=False).
            outcome = (example.targets or {}).get('outcome')
            if isinstance(outcome, str) and outcome.lower() in ('success', 'failure'):
                succeeded = outcome.lower() == 'success'
                quality = float(example.quality_score or 0.0)
                payload['success'] = succeeded
                # performance_score measures HOW WELL the work went, not how
                # sure we are that it went badly -- so a confident failure
                # scores 0.0, not 0.9.
                payload['accuracy'] = quality if succeeded else 0.0
                payload['confidence'] = quality

            learning_result = await self.learn_from_example(payload)

            # LEARNED and EARNED CREDIT are different facts.
            #
            # learn_from_example's 'success' is the CREDIT signal: whether the
            # selected strategy earned credit for this example. An example that
            # states no outcome is INSUFFICIENT_EVIDENCE, not a failure. This
            # returned that flag as its own `success`, so an example that was
            # learned from perfectly well -- including one whose cross-domain
            # transfer ran and produced validated mappings -- came back as
            # success=False with no error and no error_class. A caller cannot
            # tell that from a real failure, and the only honest reading of a
            # bare False is "it did not work".
            #
            # `error` present means learn_from_example actually failed. Its
            # absence means the example WAS learned from, and the credit
            # question is reported separately.
            failure = learning_result.get('error')
            recorded = failure is None
            # A success no arm was credited with (none passed the production
            # gate) earned no strategy credit.
            earned_credit = (bool(learning_result.get('success', False))
                             and bool(learning_result.get('credit_applied', False)))

            if recorded:
                self.domain_learning_stats["domain_specific_learning"] += 1
                logger.info(
                    "Domain-specific learning recorded for %s (strategy credit: %s)",
                    field, "earned" if earned_credit else "not earned")

            metrics = learning_result.get('metrics', {}) or {}
            return LearningResult(
                result_id=learning_result.get('memory_id') or str(uuid.uuid4()),
                success=recorded,
                learned_knowledge=learning_result.get('learned_knowledge', {}) or {},
                accuracy=float(metrics.get('accuracy', 0.0) or 0.0),
                confidence=float(metrics.get('confidence', 0.0) or 0.0),
                error=failure,
                metadata={
                    "domain": field,
                    "domain_reference": domain,
                    "domain_specific": True,
                    # The two facts, named separately and always both present.
                    # `success` IS learning_recorded -- stated here so the
                    # relationship is checkable rather than conventional. The
                    # state the old interface could not represent at all is
                    # (recorded=True, credit=False): an example learned from
                    # whose strategy earned no credit. That is the normal case
                    # for an outcome carrying no accuracy signal, and it used to
                    # arrive at every caller as a bare success=False.
                    "learning_recorded": recorded,
                    "strategy_earned_credit": earned_credit,
                    # strategy_earned_credit=False meant two opposite things:
                    # "the posterior did not move because nothing could be
                    # concluded" and "the posterior moved, recording a failure".
                    # Those are the difference between no evidence and negative
                    # evidence, so the class and the credit decision are stated
                    # rather than left to be inferred from a single False.
                    "outcome_class": learning_result.get('outcome_class'),
                    "credit_applied": learning_result.get('credit_applied', False),
                    "cross_domain": learning_result.get('cross_domain'),
                    "metrics": metrics,
                    **({} if recorded else {"error_class": "learn_from_example_failed"}),
                },
            )

        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem.learn_with_domain_context")
            logger.error(f"Error in domain-specific learning: {e}", exc_info=True)
            return LearningResult(
                result_id=str(uuid.uuid4()),
                success=False,
                learned_knowledge={},
                error=str(e),
                metadata={"domain": domain, "domain_specific": True,
                          "learning_recorded": False,
                          "strategy_earned_credit": False,
                          "error_class": type(e).__name__},
            )

    def get_domain_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about domain knowledge usage in learning"""
        return {
            "cross_domain_transfers": self.domain_learning_stats["cross_domain_transfers"],
            "domain_specific_learning": self.domain_learning_stats["domain_specific_learning"],
            "transfer_learning_successes": self.domain_learning_stats["transfer_learning_successes"],
            "total_cross_domain_insights": self.system_metrics["cross_domain_insights"],
            # Meaningful only now that attempts and successes are counted
            # separately. None with no attempts: a rate over zero tries is
            # undefined, and 0.0 would read as "every transfer failed".
            "transfer_success_rate": (
                self.domain_learning_stats["transfer_learning_successes"]
                / self.domain_learning_stats["cross_domain_transfers"]
                if self.domain_learning_stats["cross_domain_transfers"] else None),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # CAPABILITY BASELINES + REGRESSION (owned by the authority — learning is
    # what changes competence, so "is a capability improving or regressing over
    # the long horizon?" is the authority's question). Generic over
    # (component, metric, value): a caller records a measurement each cycle; the
    # authority holds the durable baseline and reports which capabilities are
    # degrading. A caller that can confirm a degradation against a live reading
    # verifies it itself — this owns the baseline store + the degrading query and
    # nothing that couples it back to a specific consumer.
    # ═══════════════════════════════════════════════════════════════════════

    #: A capability counts as improving/degrading only past this ± percent change
    #: from its baseline; smaller moves are stable (noise, not a trend).
    _CAPABILITY_TREND_PCT = 5.0

    async def _ensure_capability_schema(self) -> None:
        if getattr(self, "_capability_schema_ready", False):
            return
        from core.database import get_database_manager
        await get_database_manager().execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.long_term_baselines (
                component_name         TEXT NOT NULL,
                metric_name            TEXT NOT NULL,
                baseline_value         DOUBLE PRECISION NOT NULL,
                established_date       DATE NOT NULL DEFAULT CURRENT_DATE,
                cycles_tracked         INTEGER NOT NULL DEFAULT 1,
                last_cycle_value       DOUBLE PRECISION,
                trend_status           TEXT NOT NULL DEFAULT 'baseline_established',
                statistical_confidence DOUBLE PRECISION,
                created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (component_name, metric_name)
            )
            """,
            commit=True)
        self._capability_schema_ready = True

    async def track_capability_baseline(self, component_name: str, metric_name: str,
                                        current_value: float, *,
                                        establish: bool = True) -> Dict[str, Any]:
        """Track a capability metric against its long-term baseline.

        Establishes a baseline on first sight; on each later call compares the
        current value to it and records the trend (improving / degrading / stable
        by ±`_CAPABILITY_TREND_PCT`). Because the baseline persists across the whole
        lifetime, a capability that erodes over many cycles reads `degrading` even
        while each single cycle looked fine. No fabrication: a zero baseline yields
        a direction-only verdict, never a fake 0%.

        `establish=False` lets a caller that judges this reading unfit to BE a first
        baseline (e.g. a zero taken while the component was down — a zero baseline is
        a floor nothing can fall through, masking all later regression) record an
        update to an EXISTING baseline while refusing to create a new one from it.
        """
        from core.database import get_database_manager
        await self._ensure_capability_schema()
        db = get_database_manager()
        current_value = float(current_value)
        row = await db.execute_query(
            "SELECT baseline_value, cycles_tracked, last_cycle_value, trend_status "
            "FROM unified.long_term_baselines "
            "WHERE component_name = $1 AND metric_name = $2",
            params=(component_name, metric_name), fetch_one=True)

        if not row:
            if not establish:
                return {"status": "skipped_no_baseline"}
            await db.execute_query(
                "INSERT INTO unified.long_term_baselines "
                "(component_name, metric_name, baseline_value, established_date, "
                " cycles_tracked, last_cycle_value, trend_status) "
                "VALUES ($1, $2, $3, CURRENT_DATE, 1, $3, 'baseline_established')",
                params=(component_name, metric_name, current_value), commit=True)
            return {"status": "baseline_established", "baseline_value": current_value,
                    "cycles_tracked": 1, "trend_status": "baseline_established"}

        # Postgres returns NUMERIC as Decimal -- float() both sides before arithmetic,
        # or `current - baseline` raises on every comparison after the first.
        baseline_value = float(row["baseline_value"])
        cycles_tracked = int(row["cycles_tracked"]) + 1
        # Undefined (not 0) against a zero baseline: a percentage of zero has no
        # value, and 0.0 would read as "stable" on a comparison that cannot be made.
        pct_change = (((current_value - baseline_value) / baseline_value) * 100.0
                      if baseline_value != 0 else None)
        if pct_change is None:
            trend_status = ("improving" if current_value > baseline_value
                            else "degrading" if current_value < baseline_value else "stable")
        elif pct_change > self._CAPABILITY_TREND_PCT:
            trend_status = "improving"
        elif pct_change < -self._CAPABILITY_TREND_PCT:
            trend_status = "degrading"
        else:
            trend_status = "stable"

        await db.execute_query(
            "UPDATE unified.long_term_baselines "
            "SET cycles_tracked = $1, last_cycle_value = $2, trend_status = $3, updated_at = NOW() "
            "WHERE component_name = $4 AND metric_name = $5",
            params=(cycles_tracked, current_value, trend_status, component_name, metric_name),
            commit=True)
        return {"status": "updated", "baseline_value": baseline_value,
                "last_cycle_value": current_value, "cycles_tracked": cycles_tracked,
                "trend_status": trend_status,
                "pct_change": None if pct_change is None else round(pct_change, 2)}

    async def get_capability_regressions(self) -> List[Dict[str, Any]]:
        """Every capability whose long-term baseline is currently `degrading`.

        Returns the raw degrading rows (component, metric, baseline, last value,
        cycles tracked, days tracked). It does NOT judge operational noise vs real
        capability loss — a caller with a live reading verifies that against its
        own current data, which keeps the authority free of consumer coupling.
        """
        from core.database import get_database_manager
        await self._ensure_capability_schema()
        rows = await get_database_manager().execute_query(
            "SELECT component_name, metric_name, baseline_value, last_cycle_value, "
            "cycles_tracked, (CURRENT_DATE - established_date) AS days_tracked "
            "FROM unified.long_term_baselines WHERE trend_status = 'degrading'",
            fetch_all=True) or []
        out = []
        for r in rows:
            d = dict(r)
            for col in ("baseline_value", "last_cycle_value"):
                if d.get(col) is not None:
                    d[col] = float(d[col])
            out.append(d)
        return out

    async def record_metric(self, component_name: str, metric_name: str, value: float, *,
                            metric_type: str = "meta", baseline_value: Optional[float] = None,
                            target_value: Optional[float] = None,
                            metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Record a measured quantity: upsert the metric's definition (latest value +
        trend vs its baseline) and APPEND the value to its time series. This is the
        durable, queryable record of a metric over time, re-homed onto the authority
        so contributors (e.g. the meta-metrics monitor mirroring the meta-learner's
        standards) persist their metrics through the one owner. No fabrication: a
        zero/absent baseline gives a direction-only or no trend, never a fake 0%.
        """
        import json as _json
        from core.database import get_database_manager
        db = get_database_manager()
        value = float(value)
        base = None if baseline_value is None else float(baseline_value)
        # improvement % is undefined (not 0) against a zero/absent baseline.
        pct = (((value - base) / abs(base)) * 100.0) if base not in (None, 0) else None
        if pct is None:
            trend = ("improving" if base is not None and value > base
                     else "degrading" if base is not None and value < base else "stable")
        elif pct > self._CAPABILITY_TREND_PCT:
            trend = "improving"
        elif pct < -self._CAPABILITY_TREND_PCT:
            trend = "degrading"
        else:
            trend = "stable"
        meta_json = _json.dumps(metadata or {}, default=str)
        row = await db.execute_query(
            "INSERT INTO improvement_metrics "
            "(component_name, metric_type, metric_name, baseline_value, current_value, "
            " target_value, improvement_percentage, trend, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
            "ON CONFLICT (component_name, metric_name) DO UPDATE SET "
            "  baseline_value = EXCLUDED.baseline_value, current_value = EXCLUDED.current_value, "
            "  target_value = EXCLUDED.target_value, "
            "  improvement_percentage = EXCLUDED.improvement_percentage, "
            "  trend = EXCLUDED.trend, metadata = EXCLUDED.metadata, updated_at = NOW() "
            "RETURNING metric_id",
            params=(component_name, metric_type, metric_name, base, value, target_value,
                    pct, trend, meta_json), fetch_one=True, commit=True)
        metric_id = row["metric_id"]
        await db.execute_query(
            "INSERT INTO metric_measurements (metric_id, value, metadata) VALUES ($1, $2, $3)",
            params=(metric_id, value, meta_json), commit=True)
        return {"metric_id": int(metric_id), "current_value": value, "trend": trend,
                "improvement_percentage": None if pct is None else round(pct, 2)}

    async def benchmark_capability(self, *, cycle_id: Optional[str] = None,
                                   domains: Optional[List[str]] = None,
                                   sample_size: Optional[int] = None) -> Dict[str, Any]:
        """Measure the substrate's capability on the frozen benchmark suite, and track
        each domain's score as a long-term capability baseline.

        The authority owns capability measurement: it runs the suite (substrate-first,
        answered by the neural bridge, graded by a frozen grader — so it measures the
        substrate, not a model) and feeds the resulting domain + overall scores into
        `track_capability_baseline`, so a benchmark that shows the substrate getting
        WORSE over cycles surfaces as a real capability regression. Returns the cycle's
        report. No fabrication: an unmeasured domain is None, not zero.
        """
        from core.learning.capability_benchmark import get_capability_benchmark_suite
        suite = get_capability_benchmark_suite()
        cid = cycle_id or f"benchmark_{int(time.time())}"
        report = await suite.run_benchmarks(cid, domains=domains, sample_size=sample_size)
        # Each measured domain score (and the overall) becomes a tracked capability
        # baseline on 0-100, so regression detection rides on real benchmark movement.
        for dom in ("reasoning", "coding", "analysis", "comprehension"):
            s = getattr(report, f"{dom}_score", None)
            if s is not None:
                await self.track_capability_baseline("learning_benchmark", dom, float(s) * 100.0)
        if report.overall_score is not None:
            await self.track_capability_baseline(
                "learning_benchmark", "overall", float(report.overall_score) * 100.0)
        return {
            "cycle_id": report.cycle_id,
            "overall_score": report.overall_score,
            "reasoning_score": report.reasoning_score,
            "coding_score": report.coding_score,
            "analysis_score": report.analysis_score,
            "comprehension_score": report.comprehension_score,
            "tests_passed": report.tests_passed,
            "tests_failed": report.tests_failed,
            "confidence_interval": report.confidence_interval,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # LEARNING AUTHORITY (moved in from the deleted learning_authority.py).
    # This class IS the authority: it owns the substrate's learners and the
    # boundary around what may propose. A contributor may PROPOSE (a hypothesis,
    # a situation, a formalization); it may NOT ATTEST -- nothing it offers is
    # evidence. Everything admitted through contribute() enters as CANDIDATE with
    # zero evidence roots; only world-supplied outcomes move it.
    # ═══════════════════════════════════════════════════════════════════════

    @property
    def store(self):
        if self._store is None:
            self._store = get_rule_store()
        return self._store

    @property
    def inducer(self):
        if self._inducer is None:
            self._inducer = get_rule_inducer()
        return self._inducer

    def register_contributor(self, name: str, role: str) -> None:
        """Named so provenance survives. An anonymous proposal is untraceable."""
        self._contributors[name] = role
        logger.info(f"learning contributor registered: {name} ({role})")

    @property
    def contributors(self) -> Dict[str, str]:
        return dict(self._contributors)

    async def train_clause_classifier(
            self, name: str, members: Dict[str, Sequence[str]], *,
            others: Sequence[str] = (), domain: str = "perception",
            epochs: int = 40, reject_label: str = "none_of_these",
            config: Any = None) -> Dict[str, Any]:
        """Grow a CLAUSE POPULATION for these categories, from the same labelled
        instances `induce_category` generalises from — the second of the two
        recognition paths, learned by the one teaching.

        The two are the same family at different scales, which is why they live
        side by side on this authority. Anti-unification keeps ONE conjunction
        per category: exact, legible, learnable from two examples, and unable to
        represent a category that is a DISJUNCTION of conditions ("a red circle
        OR a blue square") — it reports `multiple_hypotheses` and waits for the
        demonstration that would decide it. A Tsetlin population keeps many
        weighted clauses arguing for and against, so it represents disjunction,
        improves with more data, and abstains when the vote is not decisive. It
        needs more examples to say anything. Neither replaces the other, and
        keeping both is what lets either be removed without vision losing the
        ability to name what it sees.

        Trained over OBSERVED features only, the same restriction naming and
        induction carry: a classifier fitted on what the substrate concluded
        would be learning from its own output.

        `members` maps category → instance ids. `others` are instances that
        belong to none of them, and become an explicit REJECTION class — without
        one a vote always has a winner, so every blob ever seen would be named
        something. A refusal has to be a class the machine can argue FOR.

        Returns what was learned: the vocabulary, the classes, training accuracy,
        and the clauses themselves, because a recognition that cannot say why is
        not worth having."""
        import numpy as np
        from core.learning.tsetlin_gpu import BatchTsetlinMachine
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        from core.database import get_database_manager

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        labels = [str(c) for c in members]
        if len(labels) < 2 and not others:
            raise ValueError(
                f"a clause classifier votes BETWEEN classes; {len(labels)} class "
                f"and no rejection examples leaves nothing to vote on")

        rows: List[Tuple[int, List[str]]] = []
        per_class: Dict[str, int] = {}
        for index, category in enumerate(labels):
            for subject in members[category]:
                feats, _ev = await observed_instance_features(db, str(subject))
                if not feats:
                    raise ValueError(
                        f"{subject!r} has no observed features to learn from — "
                        f"it was never seen, or everything it holds was concluded")
                rows.append((index, feats))
                per_class[category] = per_class.get(category, 0) + 1
        reject_index = len(labels)
        for subject in others:
            feats, _ev = await observed_instance_features(db, str(subject))
            if feats:
                rows.append((reject_index, feats))
                per_class[reject_label] = per_class.get(reject_label, 0) + 1
        if others:
            labels = labels + [reject_label]

        vocabulary = sorted({f for _c, feats in rows for f in feats})
        if not vocabulary:
            raise ValueError("no observed features across any example")
        encoder = FeatureEncoder(tuple(vocabulary))
        X = np.stack([encoder(feats) for _c, feats in rows]).astype(np.int8)
        y = np.asarray([c for c, _f in rows], dtype=np.int64)

        model = BatchTsetlinMachine(len(labels), len(vocabulary), config=config)
        model.fit(X, y, epochs=int(epochs))
        predicted = model.predict(X)
        accuracy = float((predicted == y).mean())

        self.register_clause_classifier(
            name, model, labels, encode=encoder, vocabulary=vocabulary,
            reject_label=reject_label if others else None)
        clauses = {
            labels[c]: [" & ".join(lits) for lits in (
                model.clause_literals(c, j, vocabulary) for j in range(0, model.m, 2))
                if lits][:6]
            for c in range(len(labels))}
        logger.info("🧠 clause classifier %r trained: %d class(es), %d feature(s), "
                    "%d example(s), training accuracy %.3f",
                    name, len(labels), len(vocabulary), len(rows), accuracy)
        return {"name": name, "classes": labels, "vocabulary": vocabulary,
                "examples": len(rows), "per_class": per_class,
                "training_accuracy": round(accuracy, 4), "domain": domain,
                "clauses": clauses, "reject_label": reject_label if others else None}

    def register_clause_classifier(self, name: str, model: Any, labels,
                                   *, encode: Any = None,
                                   vocabulary: Optional[Sequence[str]] = None,
                                   reject_label: Optional[str] = None) -> None:
        """Own a trained clause classifier (a Tsetlin Machine) on the ONE
        authority. `labels` maps class index → category name; `encode` turns a raw
        input into the model's boolean feature array (None if the caller passes
        already-encoded features). The model is a MECHANISM and learns nothing by
        being registered — it is a recognizer whose findings become knowledge only
        through `recognize`, which routes them through the gate. No classifier
        reaches the ingress / beliefs / domain itself.

        `vocabulary` is the feature order the boolean array is in. Held because a
        model without it is unreadable AND unusable after a restart: the encoder
        is a live object that does not survive `torch.save`, so a reloaded
        classifier came back with `encode=None` and was then handed whatever its
        route passes — a file path, for a vision route — and asked to treat it as
        features. Persisting the vocabulary is what lets the encoder be rebuilt
        instead of silently lost.

        `reject_label` names the class that means NONE OF THESE. A vote always
        has a winner, so without a class the machine can argue FOR when nothing
        fits, every instance it ever sees gets named something. When that class
        wins, `recognize` returns None — the machine declining, not failing."""
        self._clause_classifiers[name] = {
            "model": model, "labels": list(labels), "encode": encode,
            "vocabulary": list(vocabulary) if vocabulary else None,
            "reject_label": str(reject_label) if reject_label else None}
        self.register_contributor(f"clause_classifier:{name}", "perception")

    def clause_classifier_vocabulary(self, name: str) -> Optional[List[str]]:
        """The feature order a registered classifier reads, or None if it was
        registered without one (a pixel-level model, or a caller that encodes
        for itself)."""
        entry = self._clause_classifiers.get(name) or {}
        vocab = entry.get("vocabulary")
        return list(vocab) if vocab else None

    def has_clause_classifier(self, name: str) -> bool:
        """Whether a clause classifier is registered under `name` — the public
        predicate a perception route checks before attaching it (so nothing reaches
        into the private registry)."""
        return name in self._clause_classifiers

    def _classifier_dir(self) -> str:
        """Durable home for persisted clause classifiers (the mechanism). Under the
        repo's data/ so it survives a restart like every other durable store."""
        import os
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(root, "data", "classifiers")

    def save_classifiers(self, directory: Optional[str] = None) -> int:
        """Persist every registered clause classifier's MECHANISM to disk (TA state,
        weights, polarity, shape — via torch.save of the model object) so a trained
        recognizer survives process death. Returns the count saved.

        The VOCABULARY is persisted with it, and that is what makes the restored
        classifier usable rather than merely present. The encoder itself is a live
        object; saving it would pickle a class reference and break on any rename.
        Saving the feature order instead lets `load_classifiers` rebuild an
        equivalent encoder, which is the difference between a recognizer that
        works after a restart and one that is handed a file path and asked to
        read it as features."""
        import os, torch
        d = directory or self._classifier_dir()
        os.makedirs(d, exist_ok=True)
        saved = 0
        for name, entry in self._clause_classifiers.items():
            try:
                torch.save({"model": entry["model"], "labels": entry["labels"],
                            "vocabulary": entry.get("vocabulary"),
                            "reject_label": entry.get("reject_label")},
                           os.path.join(d, f"{name}.pt"))
                saved += 1
            except Exception as error:
                logger.warning("could not persist clause classifier %r: %s", name, error)
        return saved

    def load_classifiers(self, directory: Optional[str] = None) -> int:
        """Restore persisted clause classifiers on startup (see save_classifiers).
        Tensors are mapped back onto the working device, and the ENCODER is
        rebuilt from the persisted vocabulary — so a symbolic-feature classifier
        comes back able to read an instance, not just able to exist. One saved
        before vocabularies were persisted has none, and comes back with
        `encode=None` as before: it expects pre-encoded features, which is said
        out loud here rather than discovered when it mis-reads its first input."""
        import os, glob, torch
        from core.learning.tsetlin_gpu import pick_device
        d = directory or self._classifier_dir()
        if not os.path.isdir(d):
            return 0
        dev = pick_device("mps")
        restored = 0
        for path in glob.glob(os.path.join(d, "*.pt")):
            name = os.path.splitext(os.path.basename(path))[0]
            try:
                ck = torch.load(path, map_location=str(dev), weights_only=False)
                m = ck["model"]
                # re-home the state tensors on the working device
                for attr in ("ta", "w", "pol", "_pos"):
                    if hasattr(m, attr):
                        setattr(m, attr, getattr(m, attr).to(dev))
                if hasattr(m, "dev"):
                    m.dev = dev
                vocab = ck.get("vocabulary")
                self._clause_classifiers[name] = {
                    "model": m, "labels": ck["labels"],
                    "encode": FeatureEncoder(vocab) if vocab else None,
                    "vocabulary": list(vocab) if vocab else None,
                    "reject_label": ck.get("reject_label")}
                if not vocab:
                    logger.warning(
                        "clause classifier %r restored WITHOUT a vocabulary — it "
                        "can only be given pre-encoded features; a route that "
                        "hands it raw input will mis-read it", name)
                restored += 1
            except Exception as error:
                logger.warning("could not restore clause classifier %r: %s", name, error)
        return restored

    async def recognize(self, name: str, instance: Any, instance_id: str, *,
                        domain: str = "perception", threshold: float = 0.0) -> Any:
        """Recognize `instance` with the named clause classifier and TEACH the
        finding through the one gate. The model predicts a class and a margin-based
        confidence in (0,1); the recognition `instance_id isa <category>` is admitted
        via `learn_fact` with PERCEPTION provenance and the confidence as evidence
        QUALITY — so the ingress decides admit/refuse/already-present, the belief
        layer moves the single posterior, and the domain crystallizes. The
        classifier never decides what sticks. Returns the `Admission`, or None when
        no such classifier is registered or the confidence is below `threshold`."""
        entry = self._clause_classifiers.get(name)
        if entry is None:
            logger.warning("recognize: no clause classifier %r registered", name)
            return None
        import numpy as np
        import torch
        model, labels, encode = entry["model"], entry["labels"], entry["encode"]
        x = np.asarray(encode(instance) if encode else instance)
        # add the batch axis if a single example was passed (image: H,W,B -> 1,H,W,B;
        # flat features: F -> 1,F).
        single_ndim = 3 if getattr(model, "H", None) else 1
        if x.ndim == single_ndim:
            x = x[None, ...]
        s = model.scores(x)[0].to(torch.float32)          # (C,)
        cls = int(s.argmax())
        top2 = torch.topk(s, k=min(2, s.numel())).values
        margin = float(top2[0] - (top2[1] if top2.numel() > 1 else 0.0))
        denom = float(s.abs().max()) or 1.0
        confidence = max(0.0, min(1.0, 0.5 + 0.5 * margin / denom))
        if confidence < threshold or cls >= len(labels):
            return None
        # THE MACHINE DECLINING IS AN ANSWER. A vote always has a winner, so the
        # rejection class is how "none of these" gets to win; naming an instance
        # after it would turn an abstention into a claim.
        if entry.get("reject_label") and str(labels[cls]) == entry["reject_label"]:
            logger.info("recognize: %r declined to name %s — the rejection class "
                        "won at %.3f", name, instance_id, confidence)
            return None
        from core.semantics.cognitive_ingress import Provenance

        # WHAT KIND OF CLAIM A CLASSIFIER MAKES depends on what it read.
        #
        # A model reading PIXELS is making an observation: there is no earlier
        # claim between the sensor and its answer, so it introduces root evidence
        # like any other sensor. A model reading the substrate's own SYMBOLIC
        # features is drawing a conclusion FROM claims already held — the same
        # act an induced rule performs, at a different scale — and entering that
        # as a fresh observation would let it corroborate the features it was
        # read from, and let `observed_instance_features` hand its own output
        # back to it as a premise. The vocabulary is the discriminator, and it is
        # present exactly when the classifier reads symbols.
        vocabulary = entry.get("vocabulary")
        if vocabulary:
            from core.reasoning.concept_graph_reasoning import (
                observed_instance_features)
            from core.database import get_database_manager
            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()
            feats, lineage = await observed_instance_features(db, str(instance_id))
            if not lineage:
                logger.warning(
                    "recognize: %r would name %s a %s, but %s carries no observed "
                    "evidence — a conclusion with no lineage is not admitted",
                    name, instance_id, labels[cls], instance_id)
                return None
            blind = encode.unknown(feats) if isinstance(encode, FeatureEncoder) else ()
            if blind:
                logger.info(
                    "recognize: %r read %s with %d feature(s) it never trained on "
                    "(%s) — the vote is over what it CAN see",
                    name, instance_id, len(blind), ", ".join(blind))
            prov = Provenance(producer=f"clause_classifier:{name}",
                              source_id=str(instance_id),
                              source_type="INDUCED_RULE",
                              derived_from=tuple(lineage))
        else:
            prov = Provenance(producer=f"clause_classifier:{name}",
                              source_id=str(instance_id), source_type="PERCEPTION")
        return await self.learn_fact(
            str(instance_id), "isa", str(labels[cls]), domain=domain,
            provenance=prov, quality=confidence)

    def induce(self, examples, target_predicate: Optional[str] = None):
        """Learn a rule from demonstrations. The world is the only teacher here."""
        return self.inducer.induce(examples, target_predicate=target_predicate)

    async def record(self, result, examples, *, domain_id: str,
                     rule_kind: str = "state_transition"):
        """Persist what induction produced, against the demonstrations that
        produced it (keyed on the demonstrations, not a bare list of ids)."""
        return await self.store.record_induction(
            result, examples, domain_id=domain_id, rule_kind=rule_kind)

    async def induce_category(self, category: str, positives, negatives=(), *,
                              domain: str = "perception"):
        """Learn a rule that NAMES `category`, from labeled example instances.

        Each example is a subject whose atomic feature facts already live in the
        concept graph -- taught, or perceived through the vision faculty and
        admitted as `blobN isa red`, `blobN isa circular`. A positive IS a
        `category`; a negative is not, and refutes an overgeneral rule.
        Anti-unification over the positives' features yields a rule such as
        red(?X) & circular(?X) -> category(?X); it is persisted (CANDIDATE) in the
        one induced-rule authority, where the reasoner applies it to name new
        instances. Returns the InductionResult (`.rule` when one was learned).

        Raises with fewer than two positives (one case cannot be generalized) or
        when an example carries no feature facts to generalize from -- refusing,
        never inventing a rule from nothing."""
        from core.learning.rule_induction import (
            Fact, TrainingExample, predicate_name)
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        from core.database import get_database_manager

        head = predicate_name(category)
        if not head:
            raise ValueError(f"category {category!r} is not a usable predicate name")
        positives = list(positives)
        if len(positives) < 2:
            raise ValueError(
                f"category induction needs >= 2 positive examples; got "
                f"{len(positives)}: one example is a case, not a generalization")

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        async def _example(subject: str, is_positive: bool):
            # INDUCTION GENERALISES OVER WHAT WAS OBSERVED, not over what was
            # concluded. Once naming became a reflex (`recognise_sensed`), every
            # blob the substrate recognises carries the names it was given as
            # ordinary `isa` edges, and reading those back as features would let
            # a rule be induced whose premise is another rule's conclusion --
            # `circle & vivid_red & stopsign -> newcat`, resting on a `stopsign`
            # nothing ever saw. Measured: with the reflex live and all edges
            # read, induction over the same stimuli stopped producing a rule at
            # all, because the shared derived names swamped the real features.
            #
            # So the premises come from root-sourced evidence only. A feature the
            # substrate was TAUGHT is USER_SUPPLIED and still counts; only a
            # conclusion it drew is excluded. The cost is real and stated: a
            # category cannot be induced from a premise that is itself derived,
            # which is a relation between CATEGORIES and belongs in the taxonomy,
            # not in instance-level induction.
            #
            # The category being learned is the LABEL, never a feature. A positive
            # named by an earlier induction (the naming fan-out below writes
            # `subject isa category`) would otherwise carry the head in its own
            # `before`, so labelling it "adds" nothing and induction finds no
            # effect to explain -- every re-teach of a category failed that way.
            observed, _evidence = await observed_instance_features(db, subject)
            feats = [p for p in (predicate_name(f) for f in observed)
                     if p and p != head]
            before = tuple(sorted({Fact(p, (subject,)) for p in feats}))
            if not before:
                return None
            after = before + ((Fact(head, (subject,)),) if is_positive else ())
            return TrainingExample(before=before, after=after, positive=is_positive,
                                   evidence_id=f"cat_{head}_{subject}")

        examples = []
        for subject in positives:
            ex = await _example(subject, True)
            if ex is None:
                raise ValueError(
                    f"example {subject!r} has no feature facts to generalize from")
            examples.append(ex)
        for subject in negatives:
            ex = await _example(subject, False)
            if ex is not None:
                examples.append(ex)

        result = self.induce(examples, target_predicate=head)
        # EVERY SURVIVING HYPOTHESIS IS KEPT, and that is deliberate: the store
        # holds a version space for a later demonstration to collapse. What used
        # to go wrong was downstream -- naming fired on the FIRST hypothesis that
        # matched, so an undetermined category still produced confident names
        # (two `small` positives against `medium` negatives yielded
        # `small(?X) -> greentriangle(?X)` beside the conjunction, and a small
        # violet circle was named a green triangle). Ambiguity is resolved where
        # it is answerable: naming requires the hypotheses to AGREE, and an
        # undetermined category reports the demonstration that would decide it.
        if result.candidates:
            await self.record(result, examples, domain_id=domain,
                              rule_kind="classification")
            # The induction's CONCLUSION lands through the one gate, not only in
            # the rule store: each positive IS the category, so admit `subject isa
            # category` via learn_fact -- the ingress resolves identity, the belief
            # layer moves a posterior, the domain crystallizes. Without this the
            # named category exists only as a CANDIDATE rule the belief/domain
            # stores never see. Confidence rides as evidence quality.
            from core.semantics.cognitive_ingress import Provenance
            # The positives were SUPPLIED as labeled members of the category, so
            # the per-instance naming is supplied ground truth (admissible), not a
            # self-derived root that would corroborate itself.
            prov = Provenance(producer="learning", source_id=f"induction:{head}",
                              source_type="USER_SUPPLIED")
            for subject in positives:
                try:
                    await self.learn_fact(str(subject), "isa", str(category),
                                          domain=domain, provenance=prov)
                except Exception as error:
                    logger.debug("induce_category naming fan-out skipped for %r: %s",
                                 subject, error)
        return result

    # ── The one door for TOLD knowledge ──────────────────────────────────────
    #
    # Every KIND of learning is a method on this authority, and each fans out to
    # the SAME systems, so nothing that depends on learning has to reach a second
    # door: a fact and a rule both update REASONING (the concept graph the
    # reasoner chains over), BELIEFS (a posterior), the LEXICON (parts of speech),
    # the DOMAIN (crystallization, via the emitted event), MEMORY (a recallable
    # claim, through the ingress), and METRICS. Callers stop reaching into the
    # ingress / belief system / lexicon directly and come here.

    async def learn_fact(self, subject: str, relation: str, obj: Optional[str],
                         *, positive: bool = True, surface: Optional[str] = None,
                         provenance: Any = None, domain: str = "conversation",
                         description: str = "", word_class_of: Any = None,
                         emit: Any = None, quality: float = 0.9,
                         actor: Optional[str] = None) -> Any:
        """Learn a TOLD declarative fact ("a robin is a bird"), fanning out to
        every system that depends on learning. Returns the ingress `Admission`,
        so a caller keeps the same contract it had when it called the ingress.

        `actor` decides the general-vs-context partition — the ROUTER. None / the
        substrate id (the default, so all internal and substrate-originated
        learning is universal) = the one shared mind: the fact enters the concept
        graph the reasoner walks for everyone and moves a universal belief. A real
        user's id = that user's scoped context: the fact NEVER touches the shared
        graph or beliefs (it is diverted to the scoped context layer), unless and
        until it is independently corroborated and promoted."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if not is_substrate_actor(actor):
            return await self._learn_scoped_fact(
                actor, subject, relation, obj, positive=positive, surface=surface,
                domain=domain, quality=quality, description=description,
                word_class_of=word_class_of, emit=emit, provenance=provenance)
        from core.semantics.cognitive_ingress import (get_cognitive_ingress,
                                                      Provenance)
        surface = surface or " ".join(
            str(p) for p in (subject, relation, obj) if p)
        prov = provenance or Provenance(producer="learning", source_id="you",
                                        source_type="USER_SUPPLIED")
        # REASONING (+ MEMORY): the concept graph is the knowledge store the
        # reasoner walks; the ingress also stores the recallable claim.
        admission = await get_cognitive_ingress().admit_relation(
            subject=subject, relation=relation, obj=obj, surface=surface,
            provenance=prov, positive=positive, description=description,
            domain=domain, word_class_of=word_class_of, quality=quality)
        if admission.admitted:
            await self._fan_out_learning(
                surface=surface, claim=" ".join(
                    str(p) for p in (subject, relation, obj) if p),
                clauses=[(subject, relation, obj)], positive=positive,
                domain=domain, quality=quality,
                emit=emit, emit_payload={"subject": subject, "relation": relation,
                                         "obj": obj, "domain": domain})
        return admission

    async def learn_facts(self, facts, *, provenance: Any = None,
                          domain: str = "conversation", fan_out: bool = True,
                          remember: bool = True, progress: Any = None,
                          actor: Optional[str] = None,
                          quality: float = 0.9) -> Dict[str, int]:
        """Teach MANY declarative facts through the ONE path, at lexicon scale.

        Same authority as `learn_fact` — every relation is admitted through the
        cognitive ingress (the concept graph the reasoner walks) — but the fan-out
        to beliefs / lexicon / domain / metrics happens ONCE over the whole batch
        of admitted clauses, not once per fact. Teaching a whole taxonomy fact by
        fact re-runs that fan-out tens of thousands of times; this keeps the single
        owner and its admission checks while making a reference-sized teach
        practical. Returns {admitted, already, refused, total}.

        `actor` routes exactly as in `learn_fact`: a real user's id diverts every
        fact to that user's scoped context (never the shared graph/beliefs), with
        the same per-fact promotion gate; None / substrate takes the shared path.
        """
        from core.agents.autonomous.shared_types import is_substrate_actor
        if not is_substrate_actor(actor):
            counts = {"admitted": 0, "already": 0, "refused": 0, "total": 0}
            for subject, relation, obj in facts:
                counts["total"] += 1
                try:
                    await self._learn_scoped_fact(
                        actor, subject, relation, obj, positive=True,
                        surface=None, domain=domain, quality=quality, description="",
                        word_class_of=None, emit=None, provenance=provenance)
                    counts["admitted"] += 1
                except Exception:
                    counts["refused"] += 1
                if progress and counts["total"] % 1000 == 0:
                    progress(counts)
            return counts
        from core.semantics.cognitive_ingress import (get_cognitive_ingress,
                                                      Provenance)
        prov = provenance or Provenance(producer="learning", source_id="you",
                                        source_type="USER_SUPPLIED")
        ingress = get_cognitive_ingress()
        counts = {"admitted": 0, "already": 0, "refused": 0, "total": 0}
        admitted_clauses = []
        for subject, relation, obj in facts:
            counts["total"] += 1
            surface = " ".join(str(p) for p in (subject, relation, obj) if p)
            try:
                admission = await ingress.admit_relation(
                    subject=subject, relation=relation, obj=obj, surface=surface,
                    provenance=prov, positive=True, domain=domain,
                    remember=remember)
            except Exception:
                counts["refused"] += 1
                continue
            if getattr(admission, "admitted", False):
                counts["admitted"] += 1
                admitted_clauses.append((subject, relation, obj))
            elif getattr(admission, "already_present", False):
                counts["already"] += 1
            else:
                counts["refused"] += 1
            if progress and counts["total"] % 1000 == 0:
                progress(counts)
        # Fan out ONCE over everything that was newly admitted.
        if fan_out and admitted_clauses:
            await self._fan_out_learning(
                surface=f"{len(admitted_clauses)} taught facts",
                claim=f"{len(admitted_clauses)} taught facts",
                clauses=admitted_clauses, positive=True, domain=domain,
                emit=None, emit_payload={"kind": "bulk_facts", "domain": domain,
                                         "count": len(admitted_clauses)},
                # THE SAME ACT AS `learn_fact`, so the same declared quality —
                # teaching in bulk is teaching. This was the default, unstated,
                # which is how a corpus taught at scale came to set the prior of
                # most of what the substrate believes without anyone choosing it.
                quality=quality)
        return counts

    async def learn_concept(self, name: str, *, domain: str = "conversation",
                            description: str = "", relationships: Any = None,
                            provenance: Any = None, emit: Any = None,
                            actor: Optional[str] = None) -> list:
        """Learn a CONCEPT -- a node and its relationships -- through the ONE path.

        A concept with edges is admitted per edge (subject = `name`, each fanning
        out); a concept with none is admitted as a bare node so it still exists in
        the graph. This is the method a discoverer of concepts (e.g. analogy)
        calls INSTEAD of writing `unified.concepts` directly, so a derived concept
        goes through the same ingress, identity resolution, aliasing, domain
        membership, and fan-out as a taught one. `relationships` is an iterable of
        (relation, object) pairs. Returns the per-edge admissions."""
        rels = [tuple(r) for r in (relationships or []) if r and len(tuple(r)) >= 2]
        admissions = []
        if rels:
            first = True
            for rel, obj in ((r[0], r[1]) for r in rels):
                admissions.append(await self.learn_fact(
                    name, str(rel), (str(obj) if obj is not None else None),
                    provenance=provenance, domain=domain,
                    description=(description if first else ""), emit=emit,
                    actor=actor))
                first = False
        else:
            # Bare node: a valid relation is required by the ingress even though
            # no edge is created when the object is None, so `is` names the copula
            # and the admission is the node alone.
            admissions.append(await self.learn_fact(
                name, "is", None, provenance=provenance, domain=domain,
                description=description, emit=emit, actor=actor))
        return admissions

    async def learn_rule(self, antecedent: Dict[str, Any],
                         consequent: Dict[str, Any], *, surface: str,
                         provenance: Any = None, domain: str = "conversation",
                         emit: Any = None, actor: Optional[str] = None,
                         quality: float = 0.9) -> Any:
        """Learn a TOLD conditional ("if the valve is closed then the tank
        overflows") as a held rule, fanning out the same way a fact does — the
        rule lands in the held-conditional store the reasoner chains over, its
        clauses feed the lexicon, its implication moves a posterior, the domain
        crystallizes, and it is counted. Returns the ingress `Admission`.

        `actor` routes as in `learn_fact`. A real user's taught RULE must NOT
        enter the shared held-conditional store (the Z3 rules the reasoner chains
        for everyone) — that would leak one user's rule into the shared mind. So a
        user rule is held in the scoped context layer (its implication as a scoped
        belief, its antecedent/consequent as scoped edges). Reasoning over a
        user's scoped RULES (the Z3 overlay) is the next increment after the
        concept-graph overlay; until it lands, a user rule is captured and
        isolated but not yet chained on that user's behalf."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if not is_substrate_actor(actor):
            return await self._learn_scoped_rule(
                actor, antecedent, consequent, surface=surface, domain=domain,
                provenance=provenance)
        from core.semantics.cognitive_ingress import (get_cognitive_ingress,
                                                      Provenance)
        prov = provenance or Provenance(producer="learning", source_id="you",
                                        source_type="USER_SUPPLIED")
        admission = await get_cognitive_ingress().admit_conditional(
            antecedent, consequent, surface=surface, provenance=prov, domain=domain)
        if admission.admitted:
            claim = (f"if {antecedent.get('subject')} {antecedent.get('relation')} "
                     f"{antecedent.get('obj') or ''} then "
                     f"{consequent.get('subject')} {consequent.get('relation')} "
                     f"{consequent.get('obj') or ''}")
            await self._fan_out_learning(
                surface=surface, claim=" ".join(claim.split()),
                clauses=[(antecedent.get("subject"), antecedent.get("relation"),
                          antecedent.get("obj")),
                         (consequent.get("subject"), consequent.get("relation"),
                          consequent.get("obj"))],
                positive=True, domain=domain, emit=emit,
                emit_payload={"kind": "conditional", "surface": surface,
                              "domain": domain},
                # A TOLD conditional is told, like a told fact: same act, same
                # declared quality. An INDUCED rule is a different act with its
                # own support and does not come through here.
                quality=quality)
        return admission

    async def _learn_scoped_rule(self, actor: str, antecedent: Dict[str, Any],
                                 consequent: Dict[str, Any], *, surface: str,
                                 domain: str, provenance: Any) -> Any:
        """A USER's told conditional -> that user's scoped context, never the
        shared Z3 rule store. The antecedent and consequent are held as scoped
        edges (so each side's facts are captured in the user's context) and the
        implication as a scoped belief. Returns an `Admission`."""
        from core.semantics.cognitive_ingress import Admission
        from core.learning.scoped_context_store import get_scoped_context_store
        store = get_scoped_context_store()
        for part in (antecedent, consequent):
            await store.observe(
                actor, part.get("subject"), part.get("relation"),
                part.get("obj"), positive=True, quality=0.9, domain=domain,
                surface=surface, source="taught_rule")
        claim = " ".join((
            f"if {antecedent.get('subject')} {antecedent.get('relation')} "
            f"{antecedent.get('obj') or ''} then "
            f"{consequent.get('subject')} {consequent.get('relation')} "
            f"{consequent.get('obj') or ''}").split())
        await store._observe_belief(actor, claim, domain, supports=True,
                                    quality=0.9, source="taught_rule",
                                    surface=surface)
        return Admission(proposition=claim, surface=surface, admitted=True,
                         refusals=[])

    async def _route_declarative_takeaway(self, payload: Dict[str, Any], *,
                                          domain: str) -> Any:
        """Route a learning payload's DECLARATIVE takeaway through the one gate.

        Every learning door converges here for the knowledge it carries: the
        procedural/meta-learning lane credits a STRATEGY, but a stated fact is
        KNOWLEDGE and must be admitted, believed, and filed like any taught fact —
        not left in a strategy posterior or a memory row the reasoner never walks.
        So any payload carrying a structured claim (subject/relation/object, or a
        `fact`/`claim` triple) is admitted through `learn_fact`: the ingress decides
        admit/refuse/already-present, the belief layer moves the single posterior
        (a correction, `positive=False`, LOWERS it), and the domain crystallizes.

        Confidence rides as EVIDENCE QUALITY; the learner never decides what sticks.
        Does NOTHING when the payload states no claim — a strategy-only outcome
        never mints a belief (the credit invariant). Returns the `Admission` or None.
        """
        try:
            subj = payload.get("subject")
            rel = payload.get("relation")
            obj = payload.get("object", payload.get("obj"))
            triple = payload.get("fact") or payload.get("claim")
            positive = payload.get("positive", True)
            q = payload.get("confidence", payload.get("quality"))
            if not (subj and rel) and isinstance(triple, (list, tuple)) and len(triple) >= 2:
                subj, rel = triple[0], triple[1]
                obj = triple[2] if len(triple) > 2 else None
            if not (subj and rel):
                return None  # no declarative claim -> nothing to admit (credit invariant)
            quality = float(q) if isinstance(q, (int, float)) else 0.9
            quality = max(0.0, min(1.0, quality))
            from core.semantics.cognitive_ingress import Provenance
            prov = Provenance(
                producer="learning",
                source_id=str(payload.get("source") or "experience"),
                source_type=str(payload.get("provenance_type") or "USER_SUPPLIED"))
            return await self.learn_fact(
                str(subj), str(rel), (str(obj) if obj is not None else None),
                positive=bool(positive), domain=domain, provenance=prov,
                quality=quality)
        except Exception as error:
            logger.debug("declarative-takeaway routing skipped: %s", error)
            return None

    def learn_word(self, word: str, word_class: str, *,
                   source: str = "taught") -> Any:
        """Learn a WORD's part of speech — the one door for lexical acquisition."""
        from core.semantics.lexicon import get_lexicon
        lex = get_lexicon()
        entry = lex.propose(word, word_class, source)
        lex.save()
        self.system_metrics["total_learning_sessions"] = \
            self.system_metrics.get("total_learning_sessions", 0) + 1
        return entry

    def learn_words(self, words, *, source: str = "taught",
                    authoritative: bool = False) -> Dict[str, int]:
        """Teach MANY words' parts of speech through the one door, saving ONCE.

        `learn_word` writes the whole lexicon to disk on every call; teaching a
        reference vocabulary that way rewrites the file tens of thousands of
        times. This proposes every (word, class) and persists once at the end,
        the lexical-scale counterpart of `learn_facts`. A class outside
        NOUN/ADJECTIVE/VERB is counted as refused rather than raising, so one bad
        row never aborts a batch. `authoritative` lets a trusted lexical source's
        POS tag correct an earlier unconfirmed guess (never a read-confirmed
        one). Returns {proposed, already, refused, total}."""
        from core.semantics.lexicon import get_lexicon, CLASSES
        lex = get_lexicon()
        counts = {"proposed": 0, "already": 0, "refused": 0, "total": 0}
        for word, word_class in words:
            counts["total"] += 1
            head = str(word or "").strip().lower()
            if not head or word_class not in CLASSES:
                counts["refused"] += 1
                continue
            existing = lex.entry(head)
            lex.propose(head, word_class, source, authoritative=authoritative)
            if existing is not None and existing.word_class == word_class:
                counts["already"] += 1
            else:
                counts["proposed"] += 1
        lex.save()
        self.system_metrics["total_learning_sessions"] = \
            self.system_metrics.get("total_learning_sessions", 0) + 1
        return counts

    def create_belief(self, claim: str, domain: str, prior: float = 0.5,
                      evidence: Any = None, *, source: str = "derived") -> Any:
        """Record a belief THROUGH the one authority.

        A belief is a knowledge write like any other: a reasoning conclusion, a
        taught fact, and a perception all move the SAME belief store, so they
        enter by one door instead of each reaching the substrate directly. This
        delegates to the belief substrate (bayesian_uncertainty) and tags the
        source, so `create_belief` on the authority and on the substrate return
        the identical object -- the reasoners keep their contract, the writes
        gain one owner. Beliefs are revisable: what is created today `update_belief`
        can move tomorrow."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # Source is PROVENANCE, not evidence. Only tag+apply an observation when
        # the caller actually supplied evidence; with no evidence the belief must
        # stand at its prior (the belief substrate applies any non-empty evidence
        # dict as a supporting observation, so a source-only dict would silently
        # nudge every no-evidence belief up from its prior — e.g. a completion
        # belief minted low would drift toward done before any real evidence).
        if isinstance(evidence, dict) and evidence:
            ev = dict(evidence)
            ev.setdefault("source", source)
        else:
            ev = None
        return get_uncertainty_system().create_belief(
            claim, domain, prior=prior, evidence=ev)

    def update_belief(self, belief_id: str, evidence: Dict[str, Any],
                      evidence_supports: bool = True) -> Any:
        """Revise a held belief THROUGH the one authority (see create_belief).
        A Bayesian update on the single belief store -- what was believed can
        change as evidence arrives."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().update_belief(
            belief_id, evidence, evidence_supports=evidence_supports)

    def get_belief(self, belief_id: str) -> Any:
        """The held belief for an id (or None) THROUGH the one authority — the
        completion decision reads its posterior."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().get_belief(belief_id)

    def belief_for_claim(self, claim: str) -> Any:
        """A held belief matching a claim (or None) THROUGH the one authority — a
        fresh retrieval by proposition, for completion SAW."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().belief_for_claim(claim)

    def beliefs_for_domain(self, domain: str, limit: int = 8) -> Any:
        """The specific beliefs held in a domain (claim + posterior) THROUGH the one
        authority — for stamping a memory with its pertinent beliefs."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().beliefs_for_domain(domain, limit=limit)

    async def flush_belief(self, belief_id: str) -> bool:
        """Durably persist a belief (awaited, committed) THROUGH the one authority —
        for decision-critical beliefs that MUST survive a restart, such as a task's
        completion belief. Also replays any writes buffered while the DB was down."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return await get_uncertainty_system().flush_belief(belief_id)

    def observe_claim(self, claim: str, domain: str = "language", *,
                      supports: bool = True, quality: float = 0.9,
                      source: str = "observed") -> Any:
        """Record ONE observation of a claim THROUGH the one authority, idempotently.

        The find-or-create-by-claim door (see create_belief): the first
        observation of a claim mints its belief; each later observation moves the
        SAME posterior, so repeated evidence about one claim reinforces or
        contradicts a single belief instead of spawning parallels. This is the door
        the COMPLETION belief uses -- the substrate observes "this task's goal
        holds" as execution produces evidence, and the one belief accumulates
        toward (or away from) done. Delegates to the belief substrate; beliefs are
        revisable."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().observe_claim(
            claim, domain, supports=supports, quality=quality, source=source)

    async def fan_out_ingested(self, result: Any, *, domain: str = "researched",
                               surface: str = "", quality: float) -> int:
        """Run the learning fan-out over what an ingestion ALREADY admitted.

        A producer that writes through `concept_ingestion.ingest` directly
        (research, a tool capability, a perception) lands the concept graph but
        skips the lexicon and beliefs. This closes that gap WITHOUT a second
        write path: it takes the `IngestionResult.admitted_relations` and runs
        them through the SAME `_fan_out_learning` every learn_* method uses, so
        the vocabulary is learned and every observation moves a posterior. Idempotent
        and isolated -- a producer never fails because a fan-out arm did. Returns
        the number of relations fanned out.

        `quality` IS THE PRODUCER'S OWN EVIDENCE QUALITY, and is required. It
        used to be omitted, so every produced observation -- a perception above
        all -- took `_fan_out_learning`'s 0.9 default no matter what the producer
        knew. Measured on the live store: a detection reported at 0.01 and one
        reported at 0.99 both became beliefs at prior 0.900, because the
        detector's confidence reached a string attribute on a concept and went no
        further. The producer is the only party that knows how good its evidence
        is, so it is the party that has to say."""
        rels = getattr(result, "admitted_relations", None) or []
        n = 0
        for edge in rels:
            subj, rel, obj, positive = edge[0], edge[1], edge[2], edge[3]
            if not subj or not rel:
                continue
            # THE EDGE'S OWN SUPPORT WINS over the envelope's, where the producer
            # stated one. An observation is not uniform: a blob's colour is read
            # off the pixels and its shape is inferred from a lossy polygon
            # approximation, and both arrived at one envelope quality as though
            # equally well founded. None means the producer stated nothing for
            # this edge -- not that it is unsupported -- so the envelope's
            # quality stands rather than a number being invented for it.
            edge_quality = edge[4] if len(edge) > 4 and edge[4] is not None else None
            claim = " ".join(str(p) for p in (subj, rel, obj) if p)
            try:
                await self._fan_out_learning(
                    surface=surface or claim, claim=claim,
                    clauses=[(subj, rel, obj)], positive=bool(positive),
                    domain=domain, emit=None,
                    emit_payload={"kind": "ingested", "domain": domain,
                                  "subject": subj, "relation": rel, "obj": obj},
                    quality=(edge_quality if edge_quality is not None else quality),
                    save_lexicon=False)  # bulk stream: accumulate, flush later
                n += 1
            except Exception as error:
                logger.debug("fan_out_ingested arm failed for %r: %s",
                             claim, error)
        return n

    async def _fan_out_learning(self, *, surface: str, claim: str,
                                clauses: List[tuple], positive: bool,
                                domain: str, emit: Any,
                                emit_payload: Dict[str, Any],
                                quality: float,
                                save_lexicon: bool = True) -> None:
        """The shared fan-out every learn_* method runs after admission, so a
        fact and a rule touch the SAME systems: LEXICON, BELIEFS, METRICS, and
        the DOMAIN (via the emitted event). Each arm is isolated — one failing
        never rolls back what already landed, and never breaks the caller.

        `quality` IS REQUIRED, and was a `= 0.9` default until it was measured.
        Three of the four callers relied on it — bulk teaching, taught rules, and
        every evidence producer — so the number that became the PRIOR of
        204,865 of the substrate's 205,861 beliefs was one nobody had stated.
        The worst of it was on the perception path: a detector's confidence
        travelled as far as a string attribute on a concept and was dropped
        here, so a recognition reported at 0.01 and one reported at 0.99 landed
        as byte-identical beliefs at prior 0.900.
        A default cannot be told apart from a judgement once it is in the store,
        which is exactly why there is no longer one: a caller that cannot say how
        good its evidence is has to say so at the call site, in front of a
        reader, rather than inherit an answer.

        BELIEFS ARE UNIVERSAL AND REVISABLE. Every write is an observation that
        moves a posterior -- a tool capability, a perception, a research finding,
        a taught fact all update what the substrate holds to be true, and what it
        believes today it can revise tomorrow. So there is no "this kind does not
        touch beliefs": everything does.

        `save_lexicon=False` updates the lexicon in memory but does NOT flush it
        to disk -- the shared 14MB file must not be rewritten once per item in a
        bulk stream (e.g. registering hundreds of tool capabilities at startup).
        The in-memory entries accumulate on the singleton and persist on the next
        flush (a conversational `learn_fact` saves the whole file)."""
        from core.semantics.lexicon import observe_proposition, get_lexicon
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # LEXICON: teaching teaches parts of speech. Persist ONCE over the whole
        # batch -- observe_proposition writes the lexicon to disk per call, and a
        # reference-sized teach would rewrite that file once per clause.
        lexicon_touched = 0
        for (subj, rel, obj) in clauses:
            if not subj or not rel:
                continue
            try:
                lexicon_touched += observe_proposition(
                    surface, subj, rel, obj, source="taught", save=False)
            except Exception as error:
                logger.debug("learning fan-out (lexicon) failed: %s", error)
        if lexicon_touched and save_lexicon:
            try:
                get_lexicon().save()
            except Exception as error:
                logger.debug("learning fan-out (lexicon save) failed: %s", error)
        # BELIEFS: every taught clause moves a UNIVERSAL posterior. This fan-out
        # runs only on the substrate/shared path -- the general-vs-context
        # partition is decided UPSTREAM, in the public learn_* methods: a user's
        # telling is diverted to the scoped context layer before it ever reaches
        # here (and the shared concept graph), so nothing in this fan-out is
        # per-user. A promoted fact re-enters through the same shared path, so its
        # belief is moved here too. One belief PER admitted clause; the surface
        # claim only when no structured clauses were supplied.
        # THE ADMISSION FLOOR, ON EVERY PATH THAT MOVES A BELIEF.
        #
        # `MIN_ADMIT_QUALITY` guarded `cognitive_ingress.admit` — the taught
        # path — and nothing else. Produced evidence reaches beliefs through
        # `concept_ingestion.ingest` instead, and both modules describe
        # themselves as "the only write path", so a perception was admitted at
        # any quality at all while a taught fact at 0.30 was refused. Measured
        # before this: a detection reported at confidence 0.01 became a held
        # belief; the same claim, taught, could not.
        #
        # One floor, asked once, where every caller already has to state its
        # quality. Below it the substrate holds NOTHING rather than a belief it
        # barely credits: "I do not know what this is" is absence, not a weak
        # posterior that has already entered the graph and will be reasoned over
        # like any other. That is the product's stated rule, and it was true of
        # one door out of two.
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        us = get_uncertainty_system()
        propositions = [" ".join(str(p) for p in c if p)
                        for c in clauses if c and c[0] and c[1]]
        if quality < MIN_ADMIT_QUALITY:
            logger.info(
                "belief fan-out REFUSED for %d proposition(s) in %s: evidence "
                "quality %.3f < floor %.2f — held as absence, not as a weak "
                "belief", len(propositions or ([claim] if claim else [])),
                domain, quality, MIN_ADMIT_QUALITY)
            propositions = []
            claim = ""
        for proposition in (propositions or ([claim] if claim else [])):
            try:
                us.observe_claim(proposition, domain=domain, supports=positive,
                                 quality=quality, source="taught")
            except Exception as error:
                logger.debug("learning fan-out (beliefs) failed: %s", error)
        # METRICS: the learning is counted.
        self.system_metrics["total_learning_sessions"] = \
            self.system_metrics.get("total_learning_sessions", 0) + 1
        # DOMAIN: crystallize the taught domain. On the conversational path an
        # emitter is wired, so the crystallization is deferred off the reply path
        # (Phase 3 reaction). A standalone caller (bulk teach, tests) has no event
        # bus -- rather than leave the domain to the idle tier, crystallize it
        # immediately through the SINGLE domain authority, so bulk teaching affects
        # the domain on the spot. Either way it is the one owner (`ensure_domain`),
        # never a second registrar; `ensure_domain` is idempotent.
        if emit is not None:
            try:
                await emit(emit_payload)
            except Exception as error:
                logger.debug("learning fan-out (domain emit) failed: %s", error)
        elif domain:
            try:
                from core.integration.universal_domain_master import (
                    get_universal_domain_master)
                dm = self.domain_master or get_universal_domain_master()
                await dm.ensure_domain(domain)
            except Exception as error:
                logger.debug("learning fan-out (domain ensure) failed: %s", error)

    async def _learn_scoped_fact(self, actor: str, subject: str, relation: str,
                                 obj: Optional[str], *, positive: bool,
                                 surface: Optional[str], domain: str,
                                 quality: float, description: str,
                                 word_class_of: Any, emit: Any,
                                 provenance: Any) -> Any:
        """A USER's told fact -> that user's CONTEXT, never the shared mind.

        The fact is held in the scoped context layer (edge + belief), isolated
        from the concept graph the reasoner walks for everyone and from the
        universal belief store. It is then checked for promotion: if an
        INDEPENDENT source corroborates it (a different actor holds the same
        claim, or the substrate already holds it universally), the fact is lifted
        into the one mind through the normal shared path — once — and every scoped
        copy is flagged promoted. Without corroboration it stays context. This is
        the anti-poisoning floor and the tenant-isolation guarantee in one rule:
        a user can never write the shared mind directly. Returns an `Admission`
        so the caller keeps the same contract `learn_fact` always returned."""
        from core.semantics.cognitive_ingress import Admission
        from core.learning.scoped_context_store import get_scoped_context_store
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        claim = " ".join(str(p) for p in (subject, relation, obj) if p)
        surface = surface or claim
        store = get_scoped_context_store()
        await store.observe(actor, subject, relation, obj, positive=positive,
                            quality=quality, domain=domain, surface=surface,
                            source="taught")

        # PROMOTION GATE — the one bridge from context to the shared mind.
        promoted = False
        if positive and not await store.is_promoted(claim):
            holders = await store.independent_holders(
                claim, exclude_actor=actor, min_posterior=0.5)
            existing = get_uncertainty_system().belief_for_claim(claim)
            substrate_holds = (existing is not None
                               and existing.posterior_probability >= 0.5)
            if holders or substrate_holds:
                # Corroborated -> admit to the shared graph + universal belief via
                # the normal shared path, then flag so it lifts exactly once.
                await self.learn_fact(
                    subject, relation, obj, positive=positive, surface=surface,
                    provenance=provenance, domain=domain, description=description,
                    word_class_of=word_class_of, emit=emit, quality=quality,
                    actor=None)  # actor=None -> the shared mind
                await store.mark_promoted(claim)
                promoted = True
                logger.info(
                    "scoped fact promoted to the shared mind on independent "
                    "corroboration: '%s' (holders=%d, substrate_held=%s)",
                    claim[:60], len(holders), substrate_holds)

        return Admission(
            proposition=claim, surface=surface, admitted=True,
            concepts_created=([] if promoted else [str(subject)]),
            polarity=("positive" if positive else "negative"),
            refusals=[])

    async def record_demonstration(self, example, *, domain_id: str) -> bool:
        """Keep one executed demonstration; do NOT induce here.

        The hot-path half of learning: the executor calls it right after acting,
        so it must be cheap. Induction (a hypothesis search) is left to the
        always-online learner (`reinduce_operator`). Returns whether a new
        demonstration was written (False if already recorded).
        """
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().append(example, domain_id=domain_id)

    async def reinduce_operator(self, *, domain_id: str, predicate: str,
                                arity: int) -> Dict[str, Any]:
        """Re-induce one operator from its accumulated demonstrations, off the
        hot path, and promote it to executable when independent experience
        confirms it. The always-online half of learning."""
        return await self._induce_signature(
            domain_id=domain_id, predicate=predicate, arity=arity)

    async def drain_pending_induction(self, *, limit: int = 50) -> Dict[str, Any]:
        """Induce every signature that gathered demonstrations since it was last
        induced. Acting only RECORDS (and enqueues); this drains the queue. A
        pending CONTRASTIVE expands to all the domain's signatures. Returns which
        domains gained a newly executable operator (learning is what changes
        competence, not the acting that fed it)."""
        from core.learning.demonstration_store import get_demonstration_store

        demos = get_demonstration_store()
        pending = await demos.pending_signatures(limit=limit)
        induced: List[Dict[str, Any]] = []
        by_domain: Dict[str, bool] = {}

        async def run(domain_id: str, predicate: str, arity: int):
            outcome = await self._induce_signature(
                domain_id=domain_id, predicate=predicate, arity=arity)
            induced.append(outcome)
            by_domain[domain_id] = by_domain.get(domain_id, False) or bool(
                outcome.get("executable"))

        for domain_id, predicate, arity in pending:
            try:
                if (predicate, arity) == demos.CONTRASTIVE:
                    for p, a in await demos.signatures(domain_id=domain_id):
                        if (p, a) != demos.CONTRASTIVE:
                            await run(domain_id, p, a)
                else:
                    await run(domain_id, predicate, arity)
            finally:
                await demos.clear_pending(
                    domain_id=domain_id, predicate=predicate, arity=arity)

        return {"drained": len(pending), "induced": induced, "by_domain": by_domain}

    async def _induce_signature(self, *, domain_id: str, predicate: str,
                                arity: int) -> Dict[str, Any]:
        """Load a signature's demonstrations and re-induce its operator. Off the
        hot path by construction: this is the expensive half. Contrastive
        negatives from the whole domain enter the basis; the most recent
        action-ful demonstrations are held back to validate independently."""
        from core.learning.demonstration_store import get_demonstration_store

        rule_kind = predicate.lower()
        demos = get_demonstration_store()
        signature_examples = await demos.load(
            domain_id=domain_id, predicate=predicate, arity=arity)
        contrastive = await demos.load_contrastive(domain_id=domain_id)

        positives = [e for e in signature_examples if e.positive]
        summary: Dict[str, Any] = {
            "status": "insufficient_evidence",
            "demonstrations": len(signature_examples),
            "contrastive": len(contrastive),
            "positives": len(positives),
            "domain_id": domain_id,
            "signature": f"{predicate}/{arity}",
            "rule_id": None,
            "executable": False,
        }
        if len(positives) < 2:
            return summary

        signature_basis = list(signature_examples)
        held_out: List = []
        while len(held_out) < 2 and len(signature_basis) > 1:
            if sum(1 for e in signature_basis[:-1] if e.positive) >= 2:
                held_out.insert(0, signature_basis.pop())
            else:
                break

        basis = _relevant_frame(_bounded_basis(signature_basis, contrastive))
        result = self.induce(basis)
        summary["status"] = result.status.value
        if result.status is not InductionStatus.RULE_LEARNED:
            return summary

        stored = await self.record(
            result, basis, domain_id=domain_id, rule_kind=rule_kind)
        if not stored:
            return summary
        record = stored[0]
        summary["rule_id"] = record.rule_id

        if held_out:
            try:
                await self.store.validate(record, held_out)
            except Exception as e:
                raise_if_structural(e, "unified_learning_system._induce_signature")
                logger.info("validation of %s deferred: %s", record.rule_id, e)

        promoted = [r for r in await self.store.executable_rules(domain_id=domain_id)
                    if r.rule_id == record.rule_id]
        summary["executable"] = bool(promoted)
        if promoted:
            projected = await self._project_operator_to_concepts(
                promoted[0], basis, domain_id=domain_id)
            summary["projected_to_concepts"] = projected
        summary["status"] = "operator_executable" if promoted else "operator_candidate"
        return summary

    async def _project_operator_to_concepts(self, record, basis, *,
                                            domain_id: str) -> bool:
        """Record the operator's induction roots in the concept graph, then
        project the operator itself as a derivative of them, so the operator and
        concept learning systems meet. Never fatal to learning."""
        try:
            from core.domain.concept_ingestion import EvidenceSourceType
            from core.domain.evidence_producers import (
                submit_demonstration, submit_learned_rule)

            roots: List[str] = []
            for example in basis:
                if example.action is None or not example.evidence_id:
                    continue
                await submit_demonstration(
                    example, domain_id=domain_id,
                    source_type=EvidenceSourceType.TASK_ARTIFACT,
                    producer="operator_learning",
                    source_id=f"{domain_id}:{example.action.predicate}")
                roots.append(example.evidence_id)

            if not roots:
                return False
            await submit_learned_rule(record, roots, producer="operator_learning")
            return True
        except Exception as e:
            raise_if_structural(e, "unified_learning_system._project_operator_to_concepts")
            logger.info("operator->concept projection deferred for %s: %s",
                        getattr(record, "rule_id", "?"), e)
            return False

    def derive_procedure(self, operators, guards, examples, terminal: str = "RESULT",
                         max_rules: Optional[int] = None):
        """Derive a length-general procedure from input/output evidence alone --
        a SECOND ACQUISITION MODE, not a second learner. It can only compose
        operators already learned, so nothing derived here widens what the
        substrate can do -- only what it can do in sequence."""
        from core.learning.procedure_synthesis import (DEFAULT_MAX_RULES,
                                                       derive_procedure)
        return derive_procedure(
            operators, guards, examples, terminal=terminal,
            max_rules=DEFAULT_MAX_RULES if max_rules is None else max_rules)

    def induce_causal_structure(self, observations):
        """Learn which conditions gate an outcome, from trials. Owns
        ProbabilisticVersionSpace (the learner EDU-10/EDU-11 measured). Returns
        the fitted version space, or None if the trials are unusable."""
        from itertools import product

        from core.learning.probabilistic_version_space import (
            ProbabilisticVersionSpace, StructuralHypothesis)

        trials = [o for o in (observations or [])
                  if isinstance(o, dict) and isinstance(o.get("conditions"), (list, tuple))
                  and "outcome" in o]
        if not trials:
            return None

        conditions: List[str] = []
        for trial in trials:
            for condition in trial["conditions"]:
                if condition not in conditions:
                    conditions.append(condition)
        conditions.sort()
        if not conditions:
            return None

        space = ProbabilisticVersionSpace(hypotheses=[
            StructuralHypothesis(
                frozenset(c for c, a in zip(conditions, assignment) if a == 1),
                frozenset(c for c, a in zip(conditions, assignment) if a == 2))
            for assignment in product((0, 1, 2), repeat=len(conditions))])

        for trial in trials:
            outcome = trial["outcome"]
            if outcome is None:
                space.observe(frozenset(trial["conditions"]), "unknown")
            else:
                space.observe(frozenset(trial["conditions"]),
                              "success" if outcome else "failure")
        return space

    def induce_sequence_rule(self, terms):
        """Learn the rule behind a numeric sequence, and what comes next.
        Delegates to RuleInducer (no second numeric learner). Returns
        (InductionResult, next_value); next_value is None whenever the induced
        rule does not determine one (MULTIPLE_HYPOTHESES is a real answer)."""
        from core.learning.rule_induction import (Fact, InductionStatus,
                                                  TrainingExample,
                                                  arithmetic_background,
                                                  canonical_term, is_number)
        from core.reasoning.unification import match_body

        values = [canonical_term(str(t)) for t in (terms or [])]
        if len(values) < 3 or not all(is_number(v) for v in values):
            return None, None

        examples = []
        for before, after in zip(values, values[1:]):
            background = tuple(arithmetic_background([before, after]))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ())) + background,
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),) + background,
                positive=True))
            wrong = canonical_term(str(float(after) + 1))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ()))
                       + tuple(arithmetic_background([before, wrong])),
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),),
                positive=False))

        result = self.inducer.induce(examples)
        if result.status is not InductionStatus.RULE_LEARNED or not result.rule:
            return result, None

        last = values[-1]
        state = set(arithmetic_background([last])) | {
            Fact("CURRENT", (last,)), Fact("ADVANCE", ())}
        for literal in result.rule.body:
            if literal.predicate in ("PLUS", "TIMES") and len(literal.args) == 3:
                step = literal.args[1]
                if not is_number(step):
                    continue
                base, factor = float(last), float(step)
                nxt = base + factor if literal.predicate == "PLUS" else base * factor
                state.add(Fact(literal.predicate,
                               (last, step, canonical_term(str(nxt)))))

        for bindings in match_body(result.rule.body, frozenset(state)):
            for effect in result.rule.effects.substitute(bindings).add:
                if effect.predicate == "CURRENT" and effect.is_ground:
                    return result, effect.args[0]
        return result, None

    # ---- the contribution boundary --------------------------------------

    async def contribute(self, contribution: "Contribution") -> "Admission":
        """Admit a proposal -- as a CANDIDATE carrying no evidence, or not at
        all. A rejected contribution is not an error; declining is the common
        case. What must never happen is a contribution arriving with any status
        other than CANDIDATE."""
        if contribution.contributor not in self._contributors:
            admission = Admission(
                False, "contributor is not registered; a proposal with no "
                       "traceable origin cannot be admitted",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        if contribution.kind is not ContributionKind.HYPOTHESIS:
            admission = Admission(
                True, "accepted as a proposal; not stored as knowledge",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        rule = contribution.payload
        if not isinstance(rule, CandidateRule):
            admission = Admission(
                False, f"hypothesis payload is {type(rule).__name__}, not a CandidateRule",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        try:
            stored = await self.store.record_induction(
                rule,
                domain_id=contribution.domain_id or "unassigned",
                evidence_ids=[],
            )
        except Exception as e:
            raise_if_structural(e, "unified_learning_system.contribute")
            admission = Admission(False, f"could not record proposal: {e}",
                                  contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        admission = Admission(
            True, "admitted as CANDIDATE with no evidence roots",
            contribution.contributor, contribution.kind,
            status=EpistemicStatus.CANDIDATE,
            rule_id=getattr(stored, "rule_id", None))
        self._admissions.append(admission)
        return admission

    async def admit_projection(self, projection, *, contributor: str,
                               rule_kind: str = "projected") -> "Admission":
        """Admit an analogically-projected operator through the ONE boundary.

        A projection is a HYPOTHESIS like any other contribution -- analogy
        proposes, only target-domain evidence attests -- so it enters as a
        CANDIDATE with zero evidence roots and cannot reach executable authority
        except through `validate()`. It gets its own entry point rather than
        going through `contribute()` for one reason: `record_projection` also
        writes the element-level provenance (`rule_projections`) that lets a
        later contradiction be blamed on the specific correspondence that was
        wrong. A bare CandidateRule contribution would drop that, so the
        authority delegates to the projection recorder while still enforcing the
        same rule it enforces for contribute(): the proposer must be registered,
        and nothing arrives above CANDIDATE.
        """
        if contributor not in self._contributors:
            admission = Admission(
                False, "contributor is not registered; a projection with no "
                       "traceable origin cannot be admitted",
                contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        if not getattr(projection, "is_proposable", False):
            admission = Admission(
                False, f"{getattr(projection, 'outcome', '?')} is not proposable; "
                       "a partial operator would be tested and the world's answer "
                       "attributed to a rule the analogy never claimed",
                contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        try:
            stored = await self.store.record_projection(projection, rule_kind=rule_kind)
        except Exception as e:
            raise_if_structural(e, "unified_learning_system.admit_projection")
            admission = Admission(False, f"could not record projection: {e}",
                                  contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        admission = Admission(
            True, "projection admitted as CANDIDATE with no evidence roots",
            contributor, ContributionKind.HYPOTHESIS,
            status=EpistemicStatus.CANDIDATE,
            rule_id=getattr(stored, "rule_id", None))
        self._admissions.append(admission)
        return admission

    @property
    def admissions(self) -> List["Admission"]:
        """The full record, accepted and rejected alike."""
        return list(self._admissions)

    async def rules(self, domain_id: Optional[str] = None):
        return await self.store.load(domain_id=domain_id)

    async def metrics(self) -> Dict[str, Any]:
        accepted = [a for a in self._admissions if a.accepted]
        return {
            "contributors": self.contributors,
            "contributions_seen": len(self._admissions),
            "contributions_accepted": len(accepted),
            "contributions_promoted_to_knowledge": sum(
                1 for a in accepted if a.is_knowledge),
        }

    async def shutdown(self) -> None:
        """Lifecycle teardown. The authority owns no long-lived async resources
        of its own -- persistence is delegated to the demonstration/rule stores,
        torn down with the database pool. Honest no-op."""
        return None


# Singleton instance
_unified_learning_system = None


def get_unified_learning_system() -> UnifiedLearningSystem:
    """Get global unified learning system instance (singleton)"""
    global _unified_learning_system
    if _unified_learning_system is None:
        _unified_learning_system = UnifiedLearningSystem()
    return _unified_learning_system


def get_learning_authority() -> UnifiedLearningSystem:
    """The one learning authority. `UnifiedLearningSystem` IS the authority now
    (the model-free ILearningAuthority implementation was folded into this class
    and learning_authority.py deleted), so this and `get_unified_learning_system`
    return the same object."""
    return get_unified_learning_system()
