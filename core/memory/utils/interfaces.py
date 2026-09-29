"""
Memory system interfaces for storage and context management
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


@dataclass(frozen=True)
class Origin:
    """Where something handed to the memory agent came from.

    Every hand-off carries one, and the memory agent decides from it whose
    memory it is: what a person gave or asked is theirs, what the substrate did
    on its own is its own. No caller decides that, and a hand-off that does not
    say where it came from is refused -- a missing owner once meant the
    substrate's own, which is how a person's words became the substrate's.

    `through` names the door or the work it came through ("conversation",
    "task", "see", "teaching", ...). `person` is the person it came from, as an
    actor id, or None for the substrate's own; it has no default, so saying
    "none" is a decision, not an omission."""
    through: str
    person: Optional[str]

    def __post_init__(self):
        if not self.through or not str(self.through).strip():
            raise ValueError("an origin must name what it came through")

    @classmethod
    def own(cls, through: str) -> "Origin":
        """The substrate's own: no person gave it."""
        return cls(through=through, person=None)

    @classmethod
    def of(cls, actor: Optional[str], through: str) -> "Origin":
        """From an actor as the code holds one: a person's actor id, or the
        substrate's (`SUBSTRATE_ACTOR`, or None where the code already means it)."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if is_substrate_actor(actor):
            return cls.own(through)
        return cls(through=through, person=str(actor))

    @property
    def theirs(self) -> str:
        """Where what the work was given, and what it gave back, came from: the
        request, the words, the question, and the result, reply or answer. The
        person's when the work was done for them; on the substrate's own work,
        its own."""
        return "person" if self.person else "substrate"

    @property
    def material(self) -> str:
        """Where the material the work was done on came from, and what came back
        from it: a file a tool read, an image and what was seen in it. The
        person's when it was theirs; the substrate's own work is done on the
        world."""
        return "person" if self.person else "world"

    def to_dict(self) -> Dict[str, Any]:
        return {"through": self.through, "person": self.person}


#: Where a part of an experience came from:
#:
#:   person     what the person gave (their words, request, files, image), what
#:              came back from their material, and what they were given back
#:   world      what the world answered by itself: a source read, an error met,
#:              a check, and on the substrate's own work, what came back from
#:              its material
#:   substrate  what the substrate did: its steps, queries, fixes and
#:              derivations, how it placed and answered what it was given, and
#:              on its own work, what it asked and answered itself
#:
#: `Origin.theirs` and `Origin.material` say which, for the work's own ends and
#: for its material.
PART_SOURCES = ("person", "world", "substrate")


@dataclass(frozen=True)
class Part:
    """One part of an experience, and where it came from (`PART_SOURCES`)."""
    role: str
    content: Any
    source: str

    def __post_init__(self):
        if not self.role or not str(self.role).strip():
            raise ValueError("a part of an experience must name its role")
        if self.source not in PART_SOURCES:
            raise ValueError(f"a part comes from one of {PART_SOURCES}, not {self.source!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "source": self.source, "content": self.content}


@dataclass(frozen=True)
class Experience:
    """Something the substrate lived through -- a task, a piece of research, a
    conversation, a seeing, reasoning done for someone -- handed to the memory
    agent whole: whose work it was (`origin`), its parts each with where it came
    from, and its evidence (the outcome and what checked it).

    The memory agent keeps it in the pool as a candidate, in its owner's store.
    Nothing is learned from it until the lift and the gate decide what, if
    anything, is general and well evidenced."""
    kind: str
    origin: Origin
    parts: Tuple[Part, ...]
    evidence: Dict[str, Any]
    about: Optional[str] = None

    def __post_init__(self):
        if not self.kind or not str(self.kind).strip():
            raise ValueError("an experience must name its kind")
        if not isinstance(self.origin, Origin):
            raise TypeError("an experience must say whose work it was (an Origin)")
        if not all(isinstance(p, Part) for p in self.parts):
            raise TypeError("an experience is made of Parts")

    def fingerprint(self) -> str:
        """The same experience, however often it happens: its kind and what the
        substrate and the world contributed, not when or for whom."""
        import hashlib
        import json
        shared = sorted(json.dumps([p.role, p.source, p.content], sort_keys=True, default=str)
                        for p in self.parts if p.source != "person")
        return hashlib.sha256(json.dumps([self.kind, shared]).encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "origin": self.origin.to_dict(),
                "parts": [p.to_dict() for p in self.parts],
                "evidence": dict(self.evidence or {}), "about": self.about}


class MemoryType(Enum):
    """Types of memory storage"""
    EPISODIC = "episodic"      # Specific experiences and events
    SEMANTIC = "semantic"      # General knowledge and facts
    PROCEDURAL = "procedural"  # Skills and procedures
    WORKING = "working"        # Temporary processing memory
    META = "meta"              # Learning about learning (cognitive)


class MemoryPriority(Enum):
    """Memory storage priority"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    TRANSIENT = "transient"


class RetrievalScope(Enum):
    """How far back a retrieval is allowed to see.

    Distinct from MemoryScope (below), which classifies a memory's retention and
    mutability. This one is about reach across storage tiers at query time.

    Tiering is a storage-cost decision, not an epistemic one. A memory that has
    aged into the cold tier is still something the system experienced; making it
    unreachable turns a latency optimisation into amnesia. Scope lets a caller
    trade recall for latency *deliberately* — it is never a silent default.

    HISTORICAL is the default for cognitive consumers. RECENT must be chosen.
    """
    RECENT = "recent"          # hot tier only — an explicit latency/cost choice
    HISTORICAL = "historical"  # hot + cold — everything the system remembers
    ALL = "all"                # reserved for additional tiers


class MemoryStatus(Enum):
    """Memory processing status"""
    RAW = "raw"               # Unprocessed memory
    PROCESSED = "processed"   # Fully processed
    ARCHIVED = "archived"     # Long-term storage


class MemoryOperation(Enum):
    """Memory operations and retrieval methods"""
    READ = "read"
    WRITE = "write"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    EXACT_MATCH = "exact_match"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    TEMPORAL = "temporal"


class AutobiographicalActionType(Enum):
    """Types of autobiographical actions for memory system"""
    CONTENT_GENERATION = "content_generation"
    DECISION_MAKING = "decision_making"
    LEARNING = "learning"
    COMMUNICATION = "communication"
    PROBLEM_SOLVING = "problem_solving"


class AutobiographicalImportance(Enum):
    """Importance levels for autobiographical memories"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MemoryScope(Enum):
    """Memory scope for retention and mutability enforcement"""
    DIAGNOSTIC = "diagnostic"                   # Auto-expire (debugging)
    LEARNING_CANDIDATE = "learning_candidate"   # Requires review for promotion
    PRECEDENT = "precedent"                     # Immutable reference
    GOVERNANCE = "governance"                   # Immutable, read-only, audit trail


@dataclass
class MemoryEntry:
    """Memory entry data structure"""
    memory_id: str
    memory_type: MemoryType
    content: Dict[str, Any]
    priority: MemoryPriority
    timestamp: float
    access_count: int = 0
    last_accessed: float = 0.0
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ContextData:
    """Context information"""
    context_id: str
    scope: str
    data: Dict[str, Any]
    timestamp: float
    relevance_score: float = 0.0
    active: bool = True


@dataclass
class MemoryItem:
    """Single memory item representation with cognitive state tracking"""
    memory_id: str
    memory_type: MemoryType
    content: Dict[str, Any]

    # Essential metadata
    created_at: Any = field(default_factory=lambda: datetime.now().timestamp())  # Can be float or datetime
    last_accessed: Optional[Any] = None  # Can be float or datetime
    importance_score: float = 1.0
    confidence_score: float = 1.0
    status: MemoryStatus = MemoryStatus.RAW

    # Cognitive state tracking - For self-awareness
    thinking_state: Optional[Dict[str, Any]] = None  # Reasoning process, chain of thought
    system_state: Optional[Dict[str, Any]] = None  # System state at time of memory (CPU, services, dependencies)
    emotional_context: Optional[Dict[str, Any]] = None  # Sentiment, confidence, motivation
    reasoning_trace: Optional[List[str]] = None  # Step-by-step thought process
    decision_factors: Optional[Dict[str, Any]] = None  # What influenced this memory
    #: Why the memory system RETAINED this episode. Separated from
    #: thinking_state because it is computed by the memory subsystem AFTER
    #: the episode -- filing it under "cognitive state at the time" made the
    #: record temporally false.
    memory_admission: Optional[Dict[str, Any]] = None
    #: Contemporaneous appraisal -- valence, confidence, agency, risk,
    #: epistemic_opportunity and the action pressures -- read from the live
    #: AppraisalSystem. Replaces the single `autonomous_confidence` float
    #: that `emotional_context` carried, which was the memory's importance
    #: score under a name that implied something else.
    appraisal_snapshot: Optional[Dict[str, Any]] = None
    #: WHAT THE SUBSTRATE WAS TRYING TO ACHIEVE when this happened — the intent
    #: this episode belonged to, by ID.
    #:
    #: The record already carried how it reasoned (`reasoning_trace`), what
    #: weighed on it (`decision_factors`), how it felt (`appraisal_snapshot`) and
    #: what condition it was in (`system_state`) — and not the GOAL any of that
    #: served. A derivation without its conclusion: the substrate could
    #: reconstruct how it thought and never what it was thinking toward.
    #:
    #: A LINK, NEVER A COPY. Intent is live, revisable state owned by the intent
    #: authority; a memory is a permanent record of what happened. Snapshotting
    #: the intent's shape here would create a second account of what was meant,
    #: free to diverge from the first — the duplicate-authority defect, in the
    #: one place where "what I was trying to do" must have a single answer.
    intent_id: Optional[str] = None
    #: WHICH VERSION of that intent was current when this happened.
    #:
    #: `refresh` firms an intent up as understanding improves and climbs
    #: `version`, keeping the prior states in `history`. So "what was I trying to
    #: do at the time" and "what does that pursuit say now" are different
    #: questions, and the id alone answers only the second. Without the version a
    #: past act is recalled under a goal the substrate only later refined into —
    #: a memory quietly re-described by hindsight.
    intent_version: Optional[int] = None

    #: WHICH PERCEPT this memory is of — by reference, resolving to
    #: `unified.perceptions`.
    #:
    #: TESTIMONY VERSUS A RECORD. The substrate could already say "I recall
    #: seeing that", and a memory formed while perceiving carried a
    #: `perceptual_state` snapshot — but attached by RECENCY, a 120-second
    #: window over whatever had been perceived lately. That is a correlation,
    #: not a link: it says something was in view around then, and it degrades
    #: exactly when it matters most, when several things were seen close
    #: together. "I saw that employee send that email" then rests on the
    #: substrate's word plus a nearby timestamp.
    #:
    #: A reference is defensible where a recollection is not. The percept holds
    #: what was actually sensed — for an image the blobs and their `isa`
    #: features, the dimensions, and the sha256 of the exact bytes — so the
    #: claim resolves to a record of the seeing rather than to a memory of it.
    #:
    #: MODALITY-AGNOSTIC BY CONSTRUCTION. This is `percept_id`, not `image_id`,
    #: because hearing and voice arrive through the same perceptual door and
    #: must link the same way. A field named for one sense would have to be
    #: added again for the next.
    percept_id: Optional[str] = None
    #: The content digest of what was perceived (an image's sha256), carried
    #: alongside the id so the OBJECT is identifiable even if the percept row is
    #: pruned — the percept is the account of the seeing, this is the thing seen.
    #: Never a substitute for the link: absent a percept, this stays None rather
    #: than standing in for one.
    percept_digest: Optional[str] = None

    # Optional properties
    embeddings: Optional[List[float]] = None
    embedding: Optional[List[float]] = None  # Singular alias
    embedding_metadata: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_memories: List[str] = field(default_factory=list)
    tags: Any = field(default_factory=set)  # Can be Set or List
    access_count: int = 0

    # Storage tier and lifecycle
    tier: str = 'hot'
    decay_rate: float = 0.01
    session_id: str = ''
    user_id: str = ''
    archived_at: Optional[Any] = None
    deleted_at: Optional[Any] = None


@dataclass
class MemoryQuery:
    """Memory query specification"""
    query_id: str
    content: str

    # Query parameters
    memory_types: List[MemoryType] = field(default_factory=list)
    operation: MemoryOperation = MemoryOperation.SEMANTIC_SIMILARITY
    max_results: int = 10
    min_confidence: float = 0.0

    # Optional constraints
    time_window_start: Optional[float] = None
    time_window_end: Optional[float] = None
    tags: Set[str] = field(default_factory=set)
    metadata_filters: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemorySearchResult:
    """Results from memory search"""
    query_id: str
    memories: List[MemoryItem]
    total_matches: int = 0
    search_time: float = 0.0
    relevance_scores: List[float] = field(default_factory=list)


@dataclass
class CognitiveExperience:
    """Advanced cognitive learning experience with pattern recognition"""
    experience_id: str
    content: Dict[str, Any]
    memory_type: MemoryType
    priority: MemoryPriority = MemoryPriority.MEDIUM
    domain: str = "general"

    # Temporal information
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    updated_at: Optional[float] = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    duration: Optional[float] = None

    # Context and relationships
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    emotional_context: Dict[str, Any] = field(default_factory=dict)
    related_experiences: Set[str] = field(default_factory=set)

    # Learning metrics
    confidence_score: float = 1.0
    importance_score: float = 1.0
    recency_score: float = 1.0
    confidence: float = 1.0
    relevance: float = 1.0
    novelty: float = 0.5

    # Access tracking
    access_count: int = 0
    last_accessed: Optional[float] = None

    # Tags and categorization
    tags: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.experience_id:
            self.experience_id = str(uuid.uuid4())
        if self.updated_at is None:
            self.updated_at = self.created_at


@dataclass
class PromotionDecision:
    """Decision about promoting cognitive experience to persistent memory"""
    promote: bool
    reason: str
    scope: str  # diagnostic, learning_candidate, precedent, governance
    action: str = "store"  # store | discard | aggregate


class IMemoryStore(ABC):
    """Interface for memory storage operations"""
    
    @abstractmethod
    async def store_memory(self, memory: MemoryEntry) -> str:
        """Store a memory entry"""
        pass
    
    @abstractmethod
    async def retrieve_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        """Retrieve specific memory by ID"""
        pass
    
    @abstractmethod
    async def search_memories(self, query: Dict[str, Any]) -> List[MemoryEntry]:
        """Search for memories matching query"""
        pass
    
    @abstractmethod
    async def update_memory(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """Update existing memory"""
        pass
    
    @abstractmethod
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry"""
        pass
    
    @abstractmethod
    async def consolidate_memories(self, memory_type: MemoryType) -> int:
        """Consolidate memories of specific type"""
        pass


class IContextManager(ABC):
    """Interface for context management"""
    
    @abstractmethod
    async def create_context(self, scope: str, data: Dict[str, Any]) -> str:
        """Create new context"""
        pass
    
    @abstractmethod
    async def get_context(self, context_id: str) -> Optional[ContextData]:
        """Get specific context"""
        pass
    
    @abstractmethod
    async def update_context(self, context_id: str, updates: Dict[str, Any]) -> bool:
        """Update existing context"""
        pass
    
    @abstractmethod
    async def merge_contexts(self, context_ids: List[str]) -> str:
        """Merge multiple contexts"""
        pass
    
    @abstractmethod
    async def get_relevant_context(self, query: Dict[str, Any]) -> List[ContextData]:
        """Get context relevant to query"""
        pass
    
    @abstractmethod
    async def activate_context(self, context_id: str) -> bool:
        """Activate a context"""
        pass
    
    @abstractmethod
    async def deactivate_context(self, context_id: str) -> bool:
        """Deactivate a context"""
        pass


class IMemorySystem(ABC):
    """Main memory system interface"""
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the memory system"""
        pass
    
    @abstractmethod
    async def store(self, content: Dict[str, Any], memory_type: MemoryType, priority: MemoryPriority = MemoryPriority.MEDIUM) -> str:
        """Store content in memory"""
        pass
    
    @abstractmethod
    async def recall(self, query: Dict[str, Any], memory_types: Optional[List[MemoryType]] = None) -> List[MemoryEntry]:
        """Recall memories matching query"""
        pass
    
    @abstractmethod
    async def forget(self, criteria: Dict[str, Any]) -> int:
        """Forget memories matching criteria"""
        pass
    
    @abstractmethod
    async def associate(self, memory_id: str, associations: List[str]) -> bool:
        """Create associations between memories"""
        pass
    
    @abstractmethod
    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        pass
    
    @abstractmethod
    async def optimize_memory(self) -> Dict[str, Any]:
        """Optimize memory storage and retrieval"""
        pass
    
    @abstractmethod
    async def backup_memory(self, backup_path: str) -> bool:
        """Backup memory system"""
        pass
    
    @abstractmethod
    async def restore_memory(self, backup_path: str) -> bool:
        """Restore memory from backup"""
        pass
    
    @abstractmethod
    async def store_memory(self, content: Dict[str, Any], memory_type: str = "episodic", metadata: Optional[Dict[str, Any]] = None) -> str:
        """Store memory with content and metadata"""
        pass
    
    @abstractmethod
    async def query_memories(self, query: str, memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query memories by text query"""
        pass
    
    @abstractmethod
    async def search_memories(self, query: str, limit: Optional[int] = None, memory_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search memories with optional limit"""
        pass


__all__ = [
    # Enums
    'MemoryType',
    'MemoryPriority',
    'MemoryStatus',
    'MemoryOperation',
    'AutobiographicalActionType',
    'AutobiographicalImportance',
    'MemoryScope',

    # Dataclasses
    'MemoryEntry',
    'ContextData',
    'MemoryItem',
    'MemoryQuery',
    'MemorySearchResult',
    'CognitiveExperience',
    'PromotionDecision',

    # Interfaces
    'IMemoryStore',
    'IContextManager',
    'IMemorySystem',
]