#!/usr/bin/env python3
"""
Domain Types and Core Abstractions
Fundamental types for universal domain representation and cross-domain reasoning
"""

import uuid
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Optional, Any, Tuple, Union
from datetime import datetime
import json

import numpy as np

logger = logging.getLogger(__name__)


class DomainType(Enum):
    """Types of knowledge domains"""
    SCIENTIFIC = "scientific"
    TECHNICAL = "technical"
    BUSINESS = "business"
    CREATIVE = "creative"
    SOCIAL = "social"
    PHYSICAL = "physical"
    ABSTRACT = "abstract"
    MATHEMATICAL = "mathematical"
    LINGUISTIC = "linguistic"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    CAUSAL = "causal"
    ETHICAL = "ethical"
    AESTHETIC = "aesthetic"
    PRACTICAL = "practical"
    #: a place the substrate INHABITS (not a subject it knows about) — the environment it lives and
    #: acts in. Tagged so environments are first-class and resolved empirically (by probing), not
    #: looked up. Registering one records a max-uncertainty belief, so it becomes a target to explore.
    ENVIRONMENT = "environment"


class ConceptType(Enum):
    """Types of concepts within domains"""
    ENTITY = "entity"
    PROCESS = "process"
    PROPERTY = "property"
    RELATION = "relation"
    EVENT = "event"
    STATE = "state"
    RULE = "rule"
    PATTERN = "pattern"
    PRINCIPLE = "principle"
    CONSTRAINT = "constraint"
    GOAL = "goal"
    METHOD = "method"
    #: A number names a quantity and a date names a point in time. Neither is an
    #: ENTITY -- a decade is not a kind of thing the way a bird is -- so a
    #: recognised literal is filed under its own type rather than mis-classed or
    #: refused as "a bare number that names no thing".
    QUANTITY = "quantity"
    TEMPORAL = "temporal"


class ConceptDimension(Enum):
    """Dimensions for concept analysis"""
    STRUCTURAL = "structural"
    FUNCTIONAL = "functional"
    CAUSAL = "causal"
    TEMPORAL = "temporal"
    SPATIAL = "spatial"
    SEMANTIC = "semantic"
    PRAGMATIC = "pragmatic"
    CONTEXTUAL = "contextual"
    EMERGENT = "emergent"
    HIERARCHICAL = "hierarchical"


@dataclass
class DomainConcept:
    """A concept within a specific domain"""
    concept_id: str
    name: str
    domain_id: str
    concept_type: ConceptType
    
    # Core properties
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Relationships
    parent_concepts: Set[str] = field(default_factory=set)
    child_concepts: Set[str] = field(default_factory=set)
    related_concepts: Set[str] = field(default_factory=set)
    
    # Cross-domain mappings
    analogous_concepts: Dict[str, str] = field(default_factory=dict)  # domain_id -> concept_id
    
    # Semantic properties
    semantic_weight: float = 1.0
    abstraction_level: float = 0.5  # 0=concrete, 1=abstract
    complexity_score: float = 0.5
    
    # Temporal properties
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    
    # Usage statistics
    usage_count: int = 0
    relevance_score: float = 1.0
    
    def __post_init__(self):
        if not self.concept_id:
            self.concept_id = str(uuid.uuid4())


@dataclass
class DomainRelation:
    """A relationship between concepts"""
    relation_id: str
    source_concept_id: str
    target_concept_id: str
    relation_type: str
    
    # Relationship properties
    strength: float = 1.0  # 0-1 strength of relationship
    directionality: str = "bidirectional"  # bidirectional, unidirectional
    confidence: float = 1.0
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    domain_id: str = ""
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.relation_id:
            self.relation_id = str(uuid.uuid4())


@dataclass
class DomainKnowledge:
    """Knowledge within a domain"""
    knowledge_id: str
    domain_id: str
    knowledge_type: str
    
    # Content
    title: str
    content: Dict[str, Any]
    summary: str = ""
    
    # Structure
    concepts: List[str] = field(default_factory=list)  # concept_ids
    relations: List[str] = field(default_factory=list)  # relation_ids
    
    # Metadata
    tags: Set[str] = field(default_factory=set)
    source: str = ""
    confidence: float = 1.0
    importance: float = 1.0
    
    # Cross-domain aspects
    transferable_patterns: List[str] = field(default_factory=list)
    applicable_domains: Set[str] = field(default_factory=set)
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.knowledge_id:
            self.knowledge_id = str(uuid.uuid4())


@dataclass
class Domain:
    """A knowledge domain with its structure and characteristics"""
    domain_id: str
    name: str
    domain_type: DomainType
    
    # Domain characteristics
    description: str
    scope: str = ""
    boundaries: Dict[str, Any] = field(default_factory=dict)
    
    # Structure
    concepts: Dict[str, DomainConcept] = field(default_factory=dict)
    relations: Dict[str, DomainRelation] = field(default_factory=dict)
    knowledge: Dict[str, DomainKnowledge] = field(default_factory=dict)
    
    # Hierarchical structure
    parent_domains: Set[str] = field(default_factory=set)
    child_domains: Set[str] = field(default_factory=set)
    
    # Cross-domain connections
    related_domains: Dict[str, float] = field(default_factory=dict)  # domain_id -> similarity_score
    
    # Domain-specific properties
    core_principles: List[str] = field(default_factory=list)
    methodologies: List[str] = field(default_factory=list)
    vocabulary: Dict[str, str] = field(default_factory=dict)
    
    # Metrics
    complexity_score: float = 0.5
    formalization_level: float = 0.5  # How formal/structured the domain is
    maturity_score: float = 0.5  # How well-developed the domain knowledge is
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.domain_id:
            self.domain_id = str(uuid.uuid4())
    
    def add_concept(self, concept: DomainConcept) -> None:
        """Add a concept to this domain"""
        concept.domain_id = self.domain_id
        self.concepts[concept.concept_id] = concept
        self.updated_at = datetime.now()
    
    def add_relation(self, relation: DomainRelation) -> None:
        """Add a relation to this domain"""
        relation.domain_id = self.domain_id
        self.relations[relation.relation_id] = relation
        self.updated_at = datetime.now()
    
    def add_knowledge(self, knowledge: DomainKnowledge) -> None:
        """Add knowledge to this domain"""
        knowledge.domain_id = self.domain_id
        self.knowledge[knowledge.knowledge_id] = knowledge
        self.updated_at = datetime.now()
    
    def get_concept_by_name(self, name: str) -> Optional[DomainConcept]:
        """Get a concept by name"""
        for concept in self.concepts.values():
            if concept.name.lower() == name.lower():
                return concept
        return None
    
    def get_related_concepts(self, concept_id: str) -> List[DomainConcept]:
        """Get all concepts related to a given concept"""
        if concept_id not in self.concepts:
            return []
        
        concept = self.concepts[concept_id]
        related_ids = (concept.parent_concepts | 
                      concept.child_concepts | 
                      concept.related_concepts)
        
        return [self.concepts[cid] for cid in related_ids if cid in self.concepts]


@dataclass
class CrossDomainMapping:
    """Mapping between concepts across domains"""
    mapping_id: str
    source_domain_id: str
    target_domain_id: str
    source_concept_id: str
    target_concept_id: str
    
    # Mapping properties
    mapping_type: str  # analogy, similarity, transformation, etc.
    strength: float = 1.0
    confidence: float = 1.0
    bidirectional: bool = True
    
    # Transformation information
    transformation_rules: Dict[str, Any] = field(default_factory=dict)
    context_requirements: Dict[str, Any] = field(default_factory=dict)
    
    # Validation. TRI-STATE, and the third state is the important one:
    #   None  -- proposed, never put to the ontological test
    #   True  -- tested, structure was preserved
    #   False -- tested, structure was NOT preserved
    # This was a plain `bool = False`, so a freshly suggested candidate and a
    # candidate the validator had actually refuted were the same value. Every
    # consumer -- unified.domain_mappings' readers included -- filters on
    # `verified IS NULL OR verified IS TRUE` precisely to keep those apart, and
    # a default of False marked every untested suggestion as refuted.
    validated: Optional[bool] = None
    validation_score: float = 0.0
    
    # Usage
    usage_count: int = 0
    success_rate: float = 0.0
    
    # Temporal
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.mapping_id:
            self.mapping_id = str(uuid.uuid4())


@dataclass
class KnowledgeTransfer:
    """A knowledge transfer operation between domains"""
    transfer_id: str
    source_domain_id: str
    target_domain_id: str
    
    # Transfer content
    source_knowledge_ids: List[str] = field(default_factory=list)
    target_knowledge_ids: List[str] = field(default_factory=list)
    
    # Transfer properties
    transfer_type: str = "analogy"  # analogy, abstraction, specialization, etc.
    success_probability: float = 0.5
    
    # Mappings used
    concept_mappings: List[str] = field(default_factory=list)  # mapping_ids
    
    # Results
    transferred_concepts: List[str] = field(default_factory=list)
    new_insights: List[str] = field(default_factory=list)
    validation_results: Dict[str, Any] = field(default_factory=dict)
    
    # Metrics
    effectiveness_score: float = 0.0
    novelty_score: float = 0.0
    
    # Temporal
    initiated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def __post_init__(self):
        if not self.transfer_id:
            self.transfer_id = str(uuid.uuid4())


# Concept similarity.
#
# Meaning dominates (0.6); structure corroborates it and is gated on it, so
# shared metadata amplifies a real resemblance and contributes nothing to an
# imaginary one. A cross-domain analogy has different names by definition, so
# the description carries the semantic term on its own when names differ.
#
# ONE definition over arrays. Text meaning comes from stored unit vectors
# (UniversalDomainMaster owns them); nothing here encodes text.
CONCEPT_SEMANTIC_WEIGHT = 0.60
CONCEPT_NAME_WEIGHT = 0.30
CONCEPT_DESCRIPTION_WEIGHT = 0.70
CONCEPT_CORROBORATION_SATURATION = 0.35


def text_key(text: Optional[str]) -> str:
    """The form under which two concept texts count as identical. '' = no text."""
    return (text or "").strip().lower()


def concept_structure_table(
    groups_a: List[Tuple[frozenset, str, float]],
    groups_b: List[Tuple[frozenset, str, float]],
) -> np.ndarray:
    """Structural term for every pair of structure groups.

    A group is (property keys, concept type, abstraction level); the term is
    0.20 * property-key Jaccard + 0.10 * type match + 0.10 * abstraction proximity.
    """
    table = np.zeros((len(groups_a), len(groups_b)), dtype=np.float64)
    for i, (keys_a, type_a, level_a) in enumerate(groups_a):
        for j, (keys_b, type_b, level_b) in enumerate(groups_b):
            overlap = (len(keys_a & keys_b) / len(keys_a | keys_b)
                       if keys_a and keys_b else 0.0)
            table[i, j] = (0.20 * overlap
                           + 0.10 * (1.0 if type_a == type_b else 0.0)
                           + 0.10 * (1.0 - min(1.0, abs(level_a - level_b))))
    return table


def concept_group(concept: "DomainConcept") -> Tuple[frozenset, str, float]:
    ctype = concept.concept_type
    return (frozenset((concept.properties or {}).keys()),
            ctype.value if isinstance(ctype, Enum) else str(ctype),
            float(concept.abstraction_level))


def concept_similarity_scores(
    name_cosine: np.ndarray, description_cosine: np.ndarray,
    name_identical: np.ndarray, description_identical: np.ndarray,
    name_absent: np.ndarray, description_absent: np.ndarray,
    structure: np.ndarray,
) -> np.ndarray:
    """Similarity for aligned arrays of concept pairs, rounded to 4 places.

    Per text: absent on either side -> 0, identical key -> 1, otherwise the
    cosine of the two unit vectors clamped to [0, 1].
    """
    name_sim = np.clip(name_cosine, 0.0, 1.0)
    name_sim = np.where(name_identical, 1.0, name_sim)
    name_sim = np.where(name_absent, 0.0, name_sim)
    desc_sim = np.clip(description_cosine, 0.0, 1.0)
    desc_sim = np.where(description_identical, 1.0, desc_sim)
    desc_sim = np.where(description_absent, 0.0, desc_sim)
    semantic = np.maximum(name_sim, CONCEPT_NAME_WEIGHT * name_sim
                          + CONCEPT_DESCRIPTION_WEIGHT * desc_sim)
    corroboration = np.minimum(1.0, semantic / CONCEPT_CORROBORATION_SATURATION)
    score = CONCEPT_SEMANTIC_WEIGHT * semantic + corroboration * structure
    return np.round(np.minimum(score, 1.0), 4)


def semantic_floor(threshold: float, max_structure: float) -> float:
    """Smallest semantic term that can still score above `threshold`.

    The score is increasing in the semantic term and bounded by the largest
    structural term, so any pair below this floor cannot pass.
    """
    saturation = CONCEPT_CORROBORATION_SATURATION
    weight = CONCEPT_SEMANTIC_WEIGHT
    if weight * saturation + max_structure > threshold:
        return threshold / (weight + max_structure / saturation)
    return (threshold - max_structure) / weight


def _surface_key(text: str) -> str:
    """Canonical form for matching a relation target against a concept name.

    Relation targets are stored as the surface form the evidence used
    ('pressure loss'); concept names are canonical ('pressure_loss'). Comparing
    them raw matched 8 of 153 domain pairs when the underlying graph connects
    many more.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")


def _relation_vocabulary(domain: Domain) -> Set[str]:
    """The relation types a domain's concepts actually use.

    Read from concept.properties['relationships'], populated for 89 of 90
    learned concepts. Domain.vocabulary and Domain.relations are both empty for
    every learned domain, so neither can serve here.
    """
    verbs: Set[str] = set()
    for concept in domain.concepts.values():
        for pair in (concept.properties or {}).get("relationships", []) or []:
            if isinstance(pair, (list, tuple)) and pair:
                verbs.add(_surface_key(pair[0]))
    return {v for v in verbs if v}


def structural_complexity(domain: Domain) -> float:
    """Complexity COMPUTED from the graph, in [0, 1].

    Domain.complexity_score is the dataclass default 0.5 for all 33 learned
    domains — nothing computes it — so the complexity term of the similarity
    score was `0.2 * (1 - 0)` for every pair: a constant contributing no
    information while appearing to.

    Size, connectedness and relational variety, each saturating so a large
    domain does not dominate.
    """
    return coverage_from_counts(
        len(domain.concepts),
        sum(len(c.related_concepts or ()) for c in domain.concepts.values()),
        len(_relation_vocabulary(domain)))


def coverage_from_counts(concepts: int, edges: int, relation_kinds: int) -> float:
    """The complexity formula itself, over COUNTS rather than a loaded graph.

    Split out because the same measurement has two legitimate sources. An
    in-memory `Domain` carries its concepts, and `structural_complexity` reads
    them. A TAUGHT domain does not: teaching writes to `unified.concepts` with a
    `domain` column and never fills the registry object's `concepts` dict — so
    measuring a taught domain from the object returns 0.0 no matter how much it
    holds. Measured: wiring knowledge coverage to fire on admission moved a
    freshly taught domain from 0.1 to 0.0, because the thing being measured was
    empty while the store held six concepts.

    Both callers now compute the same number from whichever source actually
    knows, instead of one of them silently measuring nothing.
    """
    if not concepts:
        return 0.0
    size = min(1.0, concepts / 20.0)
    density = min(1.0, (edges / concepts) / 4.0)
    variety = min(1.0, relation_kinds / 12.0)
    return round(0.4 * size + 0.3 * density + 0.3 * variety, 4)


@dataclass(frozen=True)
class DomainSignature:
    """What domain similarity reads from a domain, computed once per content version."""
    domain_type: Optional[DomainType]
    names: frozenset
    targets: frozenset
    verbs: frozenset
    complexity: float


def domain_signature(domain: Domain) -> DomainSignature:
    """O(concepts); run it off the event loop for large domains."""
    concepts = list(domain.concepts.values())
    return DomainSignature(
        domain_type=domain.domain_type,
        names=frozenset(_surface_key(c.name) for c in concepts),
        targets=frozenset(_surface_key(t) for c in concepts
                          for t in (c.related_concepts or ())),
        verbs=frozenset(_relation_vocabulary(domain)),
        complexity=structural_complexity(domain),
    )


def domain_similarity(sig1: DomainSignature, sig2: DomainSignature) -> float:
    """Similarity between two domains, from measures that can actually fire.

        type affinity        0.15  same DomainType
        conceptual coupling  0.35  relation targets naming the other's concepts
        structural signature 0.30  shared relation vocabulary (Jaccard)
        scale affinity       0.20  computed complexity

    Concept-name overlap is not a term: under the identity model a concept
    shared by two domains is ONE concept with two memberships.
    """
    score = 0.0
    if sig1.domain_type == sig2.domain_type:
        score += 0.15
    if sig1.names and sig2.names:
        crossing = len(sig1.targets & sig2.names) + len(sig2.targets & sig1.names)
        reachable = len(sig1.targets) + len(sig2.targets)
        if reachable:
            score += 0.35 * min(1.0, crossing / reachable)
    if sig1.verbs and sig2.verbs:
        score += 0.30 * (len(sig1.verbs & sig2.verbs) / len(sig1.verbs | sig2.verbs))
    score += 0.20 * (1.0 - abs(sig1.complexity - sig2.complexity))
    return round(min(score, 1.0), 4)