#!/usr/bin/env python3
"""
Universal Domain Master
=======================
Cross-domain orchestration and knowledge integration system

Purpose:
- Coordinate between multiple knowledge domains
- Execute cross-domain queries with analogical reasoning
- Manage knowledge transfer between domains
- Integrate with Domain Registry and Universal Ontology systems

Features:
- 15 knowledge domains (scientific, technical, business, creative, etc.)
- 7 reasoning strategies (analogical, structural, functional, etc.)
- PostgreSQL persistence (unified.*) for domain relationships
- Tool-based architecture (not autonomous orchestrator)
- Domain-to-domain knowledge mapping
"""

import logging
import asyncio
import heapq
import time
import uuid
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Sequence, Set, Tuple
from datetime import datetime
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


# The 15 knowledge domains — imported, not redeclared.
#
# A byte-identical 15-member copy lived here. Identity-based equality made it a
# silent shadow: a registry DomainType reaching this module's _resolve failed
# `isinstance(dt, DomainType)`, fell through to `str(dt)`, and arrived at the
# resolver as 'DomainType.PHYSICAL' rather than 'physical' — an unresolvable
# reference produced by two enums that print the same thing.
#
# domain_types owns it: Domain.domain_type is typed by it and the registry
# builds its category/field membership graph from it.
from core.domain.domain_types import DomainType  # noqa: E402


# THE 7 cross-domain reasoning strategies — imported, not redeclared.
#
# This module defined its own ReasoningStrategy enum with byte-identical members
# to the one in cross_domain_reasoner. Enum equality is identity-based, so
# `master.ReasoningStrategy.ANALOGICAL == reasoner.ReasoningStrategy.ANALOGICAL`
# was False. _generate_mappings passes this value into ReasoningContext, and the
# reasoner looks the strategy up in a dict keyed by ITS enum:
#
#     strategy_func = self.strategies.get(context.strategy)   -> None
#     return ReasoningResult(success=False,
#                            new_insights=["Unsupported reasoning strategy"])
#
# So every one of the seven strategies was unreachable through the master, and
# the failure surfaced as success=False with confidence 0.0 — indistinguishable
# from "these domains have nothing in common". Verified by direct execution.
#
# The reasoner owns the strategies (it maps each member to a method), so it owns
# the vocabulary that names them.
from core.domain.cross_domain_reasoner import ReasoningStrategy  # noqa: E402


# Concept vocabulary — imported, not redeclared.
#
# This module defined a second 12-member ConceptType that had DIVERGED from
# domain_types.ConceptType: `relationship`/`structure` here versus
# `relation`/`rule` there. Ten members overlapped, so a concept typed by one was
# untypeable by the other -- the same defect that made all seven reasoning
# strategies unreachable, but in the vocabulary itself.
#
# domain_types owns it: DomainConcept is typed by it, the registry deserialises
# through it, and universal_ontology maps all twelve members. The two members
# unique to this copy had zero uses repo-wide.
from core.domain.domain_types import ConceptType  # noqa: E402

from core.domain.domain_types import (  # noqa: E402
    CONCEPT_DESCRIPTION_WEIGHT, CONCEPT_NAME_WEIGHT, CrossDomainMapping,
    DomainConcept, concept_group, concept_similarity_scores,
    concept_structure_table, domain_signature, domain_similarity,
    semantic_floor, text_key,
)


@dataclass
class CrossDomainQuery:
    """Query spanning multiple domains"""
    query_id: str
    query_text: str
    source_domains: List[DomainType]
    target_domains: List[DomainType]
    reasoning_strategy: ReasoningStrategy = ReasoningStrategy.ANALOGICAL

    # Query parameters
    max_results: int = 10
    min_similarity: float = 0.7
    include_explanations: bool = True

    # Execution context
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainMapping:
    """Mapping between concepts in different domains"""
    mapping_id: str
    # Canonical registry domain ids (the FIELD: "physics"), not DomainType
    # categories. The field is the identity the concepts actually belong to;
    # storing the category here would discard which field produced the mapping
    # and make the row unreadable back into a domain.
    source_domain: str
    target_domain: str
    source_concept: str
    target_concept: str

    # Mapping metadata
    similarity_score: float
    reasoning_strategy: ReasoningStrategy
    # TRI-STATE: None = proposed and untested, True = accepted, False = refuted.
    # Declared `bool = False` while _generate_mappings passes None and the
    # reader below hands back a nullable column -- so the annotation described a
    # type this field never held, and any construction omitting it silently
    # marked its own mapping refuted.
    verified: Optional[bool] = None
    confidence: float = 0.0

    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainIntegrationResult:
    """Result from domain integration operation"""
    query_id: str
    success: bool

    # Results
    mappings: List[DomainMapping] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    explanations: List[str] = field(default_factory=list)

    # Performance metrics
    execution_time: float = 0.0
    domains_queried: int = 0
    mappings_found: int = 0

    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class DeficitType(Enum):
    """The kind of epistemic deficiency behind a goal the substrate could not plan.

    Ordered from the most upstream (a symbol with no meaning) to the least
    (deficient but not localised). When several goal conditions fail for
    different reasons, the most upstream one is the blocker to act on.

    This is a MEASUREMENT the domain authority makes about a domain's knowledge
    state -- a sibling of competence, controllability, and learning progress. It
    is NOT a decision about what to do: the disposition (explore / replan /
    disengage) belongs to the AppraisalSystem, which this feeds through the
    signals in `_DEFICIT_SIGNALS`. The type additionally carries WHICH learning
    operation a chosen exploration should run -- the one thing appraisal does not
    decide -- so it can ride an exploration target as a routing key.
    """

    CONCEPT_GAP = "concept_gap"            # the goal predicate is unrepresented
    OPERATOR_GAP = "operator_gap"          # no action produces the predicate
    CAUSAL_GAP = "causal_gap"              # a hypothesis produces it, unvalidated
    BINDING_GAP = "binding_gap"            # validated, but no tool to act it
    RELATION_GAP = "relation_gap"          # blocked on an unreachable relation
    PREREQUISITE_GAP = "prerequisite_gap"  # blocked on an unreachable state
    OBSERVATION_GAP = "observation_gap"    # the world cannot be read
    WORLD_PREVENTS = "world_prevents"      # proved impossible; no learning helps
    UNKNOWN_GAP = "unknown_gap"            # deficient, not yet localised


#: Upstream-first priority. A goal blocked by several deficits is blocked by its
#: most upstream one -- fixing a downstream gap cannot help while an upstream one
#: stands. WORLD_PREVENTS is absolute (a proof), so it outranks everything.
_DEFICIT_PRIORITY: List[DeficitType] = [
    DeficitType.WORLD_PREVENTS,
    DeficitType.OBSERVATION_GAP,
    DeficitType.CONCEPT_GAP,
    DeficitType.OPERATOR_GAP,
    DeficitType.CAUSAL_GAP,
    DeficitType.BINDING_GAP,
    DeficitType.RELATION_GAP,
    DeficitType.PREREQUISITE_GAP,
    DeficitType.UNKNOWN_GAP,
]

#: How each deficit reads AS A MEASUREMENT the AppraisalSystem consumes: the
#: value of learning more here (epistemic opportunity, 0..1) and the causal
#: attribution (an OutcomeClass string, honouring the credit invariant -- a
#: learnable gap is the substrate's own repertoire and moves competence; a world
#: proof or a missing observer/binding is not its strategy's fault and must not).
#: This is deliberately NOT a table of actions (explore/replan/...): those are
#: appraisal's to derive from these signals. Kept here, with the measurement.
_DEFICIT_SIGNALS: Dict[DeficitType, Tuple[float, str]] = {
    DeficitType.CONCEPT_GAP: (0.9, "strategy_failure"),
    DeficitType.OPERATOR_GAP: (0.9, "strategy_failure"),
    DeficitType.CAUSAL_GAP: (0.8, "strategy_failure"),
    DeficitType.RELATION_GAP: (0.7, "strategy_failure"),
    DeficitType.PREREQUISITE_GAP: (0.7, "strategy_failure"),
    DeficitType.BINDING_GAP: (0.3, "infrastructure_failure"),
    DeficitType.OBSERVATION_GAP: (0.1, "infrastructure_failure"),
    DeficitType.WORLD_PREVENTS: (0.0, "external_failure"),
    DeficitType.UNKNOWN_GAP: (0.4, "indeterminate"),
}


class LearningOperation(Enum):
    """The operation a deficit calls for -- the one thing appraisal does NOT
    decide. Appraisal owns the disposition (explore / replan / disengage); once
    it favours learning, WHICH operation follows from the deficit KIND, not from
    disposition. This is the routing key a deficit carries.

    Only the first three are autonomous, model-free operations the substrate can
    run now (all through the always-online explorer). ACHIEVE_PREREQUISITE
    recurses to the intermediate it lacks. ESCALATE is the honest answer when the
    deficiency needs input the substrate cannot self-supply (a relation from
    another domain, a concept proposal, a tool binding, an observer) -- it is not
    a stubbed operation, it is the substrate correctly declining to invent one.
    DISENGAGE is a proved dead end.
    """

    LEARN_OPERATOR = "learn_operator"              # explore for an action producing it
    VALIDATE_CAUSE = "validate_cause"              # contrastives to confirm a hypothesis
    PROBE = "probe"                                # broad exploration to localise
    ACHIEVE_PREREQUISITE = "achieve_prerequisite"  # reach the missing precondition first
    TRANSFER_RELATION = "transfer_relation"        # project the relation from a source domain
    ESCALATE = "escalate"                          # needs input the substrate cannot supply
    DISENGAGE = "disengage"                        # no learning is justified


#: deficit KIND -> the learning operation it calls for. RELATION/CONCEPT/BINDING/
#: OBSERVATION all ESCALATE, but for DISTINCT reasons the deficit_type preserves;
#: the operation coarsens where the honest response is the same ("needs external
#: input"), while the diagnosis stays specific.
_DEFICIT_OPERATION: Dict["DeficitType", "LearningOperation"] = {
    DeficitType.OPERATOR_GAP: LearningOperation.LEARN_OPERATOR,
    DeficitType.CAUSAL_GAP: LearningOperation.VALIDATE_CAUSE,
    DeficitType.PREREQUISITE_GAP: LearningOperation.ACHIEVE_PREREQUISITE,
    DeficitType.RELATION_GAP: LearningOperation.TRANSFER_RELATION,
    DeficitType.CONCEPT_GAP: LearningOperation.ESCALATE,
    DeficitType.BINDING_GAP: LearningOperation.ESCALATE,
    DeficitType.OBSERVATION_GAP: LearningOperation.ESCALATE,
    DeficitType.WORLD_PREVENTS: LearningOperation.DISENGAGE,
    DeficitType.UNKNOWN_GAP: LearningOperation.PROBE,
}


@dataclass
class EpistemicDeficit:
    """A typed account of why a goal is unreachable, with its evidence.

    Produced by the domain authority; consumed as a measurement (never a
    decision). `target_predicate` is the goal predicate the deficiency is about
    -- the one the substrate must learn to produce, observe, or represent.
    `evidence` records the structural facts the type was read from, so the
    diagnosis is inspectable rather than asserted.
    """

    domain_id: str
    deficit_type: DeficitType
    target_predicate: Optional[str] = None
    confidence: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def epistemic_opportunity(self) -> float:
        """The value of learning more here -- a property of the deficit KIND."""
        return _DEFICIT_SIGNALS[self.deficit_type][0]

    @property
    def outcome_class(self) -> str:
        """The causal attribution this failure carries, as an OutcomeClass value."""
        return _DEFICIT_SIGNALS[self.deficit_type][1]

    @property
    def operation(self) -> "LearningOperation":
        """The learning operation this deficit calls for -- the routing key."""
        return _DEFICIT_OPERATION[self.deficit_type]

    @property
    def remedy_reason(self) -> str:
        """Why an ESCALATE deficit needs input the substrate cannot self-supply.

        Distinct per kind even though several share the ESCALATE operation, so an
        escalation carries what it is actually waiting for.
        """
        return {
            DeficitType.RELATION_GAP:
                "needs the missing relation from a source domain (transfer, not self-supplied)",
            DeficitType.CONCEPT_GAP:
                "needs a concept proposal for an unrepresented predicate (model-optional)",
            DeficitType.BINDING_GAP:
                "needs a tool binding for the operator's action",
            DeficitType.OBSERVATION_GAP:
                "needs an observation capability for the domain",
        }.get(self.deficit_type, "needs input the substrate cannot supply from here")

    def appraisal_signals(self) -> Dict[str, Any]:
        """The signals the AppraisalSystem consumes for this failure.

        `epistemic` carries the learning opportunity as rising uncertainty
        (open questions remain); `outcome_class` carries the attribution. The
        AppraisalSystem -- not this method -- turns them into disposition.
        """
        return {
            "epistemic": {"uncertainty_increase": self.epistemic_opportunity},
            "outcome_class": self.outcome_class,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "deficit_type": self.deficit_type.value,
            "target_predicate": self.target_predicate,
            "confidence": self.confidence,
            "epistemic_opportunity": self.epistemic_opportunity,
            "outcome_class": self.outcome_class,
            "operation": self.operation.value,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpistemicDeficit":
        """Rebuild a deficit from its `to_dict` form so a consumer that received
        only the serialised measurement (the executor result carries `deficit` as
        a dict) can run the closure against the live object. The derived
        properties -- operation, opportunity, attribution -- recompute from the
        type, so only the stored fields are carried; the derived keys in the dict
        are ignored rather than trusted."""
        return cls(
            domain_id=data["domain_id"],
            deficit_type=DeficitType(data["deficit_type"]),
            target_predicate=data.get("target_predicate"),
            confidence=data.get("confidence", 1.0),
            evidence=dict(data.get("evidence") or {}),
        )


# ======================================================================
# CONCEPT VECTORS AND CONCEPT-LEVEL CORRESPONDENCE
#
# Owned by UniversalDomainMaster. A concept's name and description are encoded
# once, when the concept is written, and stored on its unified.concepts row.
# Correspondence between two domains is scored from those stored vectors in a
# worker thread and reused until either domain's concepts change.
# ======================================================================

#: float32 similarity blocks are this many elements (~128 MB).
_BLOCK_ELEMENTS = 1 << 25
#: Candidate pairs rescored exactly per batch.
_EXACT_BATCH = 32_768
#: float32 dot products of unit vectors are within ~1e-6 of the float64 value;
#: the candidate floor is lowered by this so no passing pair is filtered out.
_FLOAT32_MARGIN = 1e-4


class _ConceptVectorStore:
    """Stored concept vectors held in memory, loaded from unified.concepts on use.

    Rows are append-only and arrays are replaced, never resized in place, so a
    worker thread scoring arrays it was handed never sees a row change.
    """

    def __init__(self):
        self.index: Dict[str, int] = {}
        self.size = 0
        self.garbage = 0
        self.names: Optional[np.ndarray] = None
        self.descriptions: Optional[np.ndarray] = None
        self.name_keys: Optional[np.ndarray] = None
        self.description_keys: Optional[np.ndarray] = None
        self._text_ids: Dict[str, int] = {}

    def _text_id(self, text: Optional[str]) -> int:
        key = text_key(text)
        return self._text_ids.setdefault(key, len(self._text_ids)) if key else -1

    def _allocate(self, capacity: int, dim: int) -> None:
        names = np.zeros((capacity, dim), dtype=np.float32)
        descriptions = np.zeros((capacity, dim), dtype=np.float32)
        name_keys = np.full(capacity, -1, dtype=np.int64)
        description_keys = np.full(capacity, -1, dtype=np.int64)
        if self.names is not None and self.garbage > max(100_000, len(self.index)):
            live = np.fromiter(self.index.values(), dtype=np.int64, count=len(self.index))
            order = np.argsort(live)
            live = live[order]
            names[:live.size] = self.names[live]
            descriptions[:live.size] = self.descriptions[live]
            name_keys[:live.size] = self.name_keys[live]
            description_keys[:live.size] = self.description_keys[live]
            ids = list(self.index.keys())
            self.index = {ids[k]: row for row, k in enumerate(order.tolist())}
            self.size, self.garbage = live.size, 0
        elif self.names is not None:
            names[:self.size] = self.names[:self.size]
            descriptions[:self.size] = self.descriptions[:self.size]
            name_keys[:self.size] = self.name_keys[:self.size]
            description_keys[:self.size] = self.description_keys[:self.size]
        self.names, self.descriptions = names, descriptions
        self.name_keys, self.description_keys = name_keys, description_keys

    def put(self, entries: List[Tuple[str, Optional[str], Optional[str],
                                      Optional[np.ndarray], Optional[np.ndarray]]]) -> None:
        """entries: (concept_id, name, description, name_vector, description_vector)."""
        if not entries:
            return
        dim = next((len(v) for e in entries for v in e[3:] if v is not None), None)
        if dim is None and self.names is None:
            from core.memory.utils.embedding_service import EMBEDDING_DIMENSIONS
            dim = EMBEDDING_DIMENSIONS
        dim = dim or self.names.shape[1]
        end = self.size + len(entries)
        if self.names is None or end > len(self.names) or self.names.shape[1] != dim:
            if self.names is not None and self.names.shape[1] != dim:
                raise ValueError(
                    f"stored concept vectors are {dim}-dimensional; this store "
                    f"holds {self.names.shape[1]}")
            self._allocate(max(end, 2 * (0 if self.names is None else len(self.names)), 4096), dim)
            end = self.size + len(entries)
        for offset, (concept_id, name, description, name_vec, desc_vec) in enumerate(entries):
            for text, vec, what in ((name, name_vec, "name"), (description, desc_vec, "description")):
                if bool(text_key(text)) != (vec is not None):
                    raise ValueError(
                        f"concept {concept_id}: {what} text and stored vector disagree "
                        f"(text {'present' if text_key(text) else 'absent'}, vector "
                        f"{'present' if vec is not None else 'absent'})")
            row = self.size + offset
            self.names[row] = name_vec if name_vec is not None else 0.0
            self.descriptions[row] = desc_vec if desc_vec is not None else 0.0
            self.name_keys[row] = self._text_id(name) if name_vec is not None else -1
            self.description_keys[row] = (self._text_id(description)
                                          if desc_vec is not None else -1)
            if concept_id in self.index:
                self.garbage += 1
            self.index[concept_id] = row
        self.size = end

    def discard(self, concept_ids: Sequence[str]) -> None:
        for concept_id in concept_ids:
            if self.index.pop(concept_id, None) is not None:
                self.garbage += 1


@dataclass(frozen=True)
class _ConceptSide:
    """One domain's concepts, in order, as rows of a vector store snapshot."""
    concept_ids: Tuple[str, ...]
    rows: np.ndarray
    names: np.ndarray
    descriptions: np.ndarray
    name_keys: np.ndarray
    description_keys: np.ndarray
    groups: np.ndarray
    group_table: Tuple[Tuple[frozenset, str, float], ...]


def _build_side(concepts: List[DomainConcept], rows: np.ndarray,
                names: np.ndarray, descriptions: np.ndarray,
                name_keys: np.ndarray, description_keys: np.ndarray) -> _ConceptSide:
    table: Dict[Tuple[frozenset, str, float], int] = {}
    groups = np.empty(len(concepts), dtype=np.int32)
    for position, concept in enumerate(concepts):
        groups[position] = table.setdefault(concept_group(concept), len(table))
    return _ConceptSide(
        concept_ids=tuple(c.concept_id for c in concepts), rows=rows,
        names=names, descriptions=descriptions,
        name_keys=name_keys[rows], description_keys=description_keys[rows],
        groups=groups, group_table=tuple(table))


def _encode_concept_texts(names: List[Optional[str]], descriptions: List[Optional[str]]
                          ) -> Tuple[List[Optional[np.ndarray]], List[Optional[np.ndarray]]]:
    """Unit vectors for each non-empty text; None where there is no text. Blocking."""
    from core.memory.utils.embedding_service import get_embedding_service
    texts: List[str] = []
    slots: List[Tuple[int, int]] = []
    for kind, column in enumerate((names, descriptions)):
        for position, text in enumerate(column):
            if text_key(text):
                texts.append(text)
                slots.append((kind, position))
    vectors = get_embedding_service().encode_normalized(texts)
    out: Tuple[List[Optional[np.ndarray]], List[Optional[np.ndarray]]] = (
        [None] * len(names), [None] * len(descriptions))
    for (kind, position), vector in zip(slots, vectors):
        out[kind][position] = vector
    return out


def _key_positions(keys: np.ndarray) -> Dict[int, np.ndarray]:
    """text id -> positions holding it, for texts that are present."""
    order = np.argsort(keys, kind="stable")
    ordered = keys[order]
    unique, starts, counts = np.unique(ordered, return_index=True, return_counts=True)
    return {int(k): order[a:a + c] for k, a, c in zip(unique.tolist(), starts.tolist(),
                                                       counts.tolist()) if k >= 0}


def _exact_pair_scores(src: _ConceptSide, tgt: _ConceptSide, structure: np.ndarray,
                       ii: np.ndarray, jj: np.ndarray) -> np.ndarray:
    """Concept similarity for aligned pairs (src[ii], tgt[jj]), in float64."""
    name_cos = np.einsum("ij,ij->i", src.names[src.rows[ii]].astype(np.float64),
                         tgt.names[tgt.rows[jj]].astype(np.float64))
    desc_cos = np.einsum("ij,ij->i", src.descriptions[src.rows[ii]].astype(np.float64),
                         tgt.descriptions[tgt.rows[jj]].astype(np.float64))
    sn, tn = src.name_keys[ii], tgt.name_keys[jj]
    sd, td = src.description_keys[ii], tgt.description_keys[jj]
    return concept_similarity_scores(
        name_cos, desc_cos, sn == tn, sd == td,
        (sn < 0) | (tn < 0), (sd < 0) | (td < 0),
        structure[src.groups[ii], tgt.groups[jj]])


def _slice_side(side: _ConceptSide, positions: Sequence[int]) -> _ConceptSide:
    """The concepts of `side` at `positions` (ascending), same store and groups."""
    idx = np.asarray(positions, dtype=np.int64)
    return _ConceptSide(
        concept_ids=tuple(side.concept_ids[i] for i in positions), rows=side.rows[idx],
        names=side.names, descriptions=side.descriptions,
        name_keys=side.name_keys[idx], description_keys=side.description_keys[idx],
        groups=side.groups[idx], group_table=side.group_table)


def _score_correspondence(src: _ConceptSide, tgt: _ConceptSide, threshold: float,
                          depth: int, count_all: bool) -> Dict[str, Any]:
    """Concept pairs scoring above `threshold`. Exact; blocking.

    `strongest`: the `depth` strongest as (score, source_id, target_id), strongest
    first, ties in source-then-target order. `complete`: whether those are every
    passing pair. With `count_all`, also `pairs` and `total` over every passing
    pair, and `rows` / `cols`: concept id -> (pairs, total) for each concept with
    a passing pair.

    Keeping only the strongest, blocks are float32 and a pair is rescored in
    float64 only if its semantic term clears the floor for the current depth-th
    best, which rises as the scan goes. Counting every pair needs every passing
    score, so blocks are float64 and scores are taken from them.
    """
    n, m = len(src.concept_ids), len(tgt.concept_ids)
    result: Dict[str, Any] = {"source_concepts": n, "target_concepts": m,
                              "pairs": 0 if count_all else None,
                              "total": 0.0 if count_all else None,
                              "strongest": [], "complete": True,
                              "rows": {} if count_all else None,
                              "cols": {} if count_all else None}
    if n == 0 or m == 0:
        return result
    dtype = np.float64 if count_all else np.float32
    margin = 1e-9 if count_all else _FLOAT32_MARGIN
    structure = concept_structure_table(list(src.group_table), list(tgt.group_table))
    max_structure = float(structure.max())
    target_names = tgt.names[tgt.rows].astype(dtype, copy=False)
    target_descriptions = tgt.descriptions[tgt.rows].astype(dtype, copy=False)
    name_positions = _key_positions(tgt.name_keys)
    description_positions = _key_positions(tgt.description_keys)
    strongest: List[Tuple[float, int, int]] = []
    block_elements = _BLOCK_ELEMENTS // (2 if count_all else 1)
    step = max(1, min(n, block_elements // m))
    if count_all:
        row_pairs = np.zeros(n, dtype=np.int64)
        row_total = np.zeros(n, dtype=np.float64)
        col_pairs = np.zeros(m, dtype=np.int64)
        col_total = np.zeros(m, dtype=np.float64)

    for i0 in range(0, n, step):
        i1 = min(n, i0 + step)
        rows = src.rows[i0:i1]
        name_sim = src.names[rows].astype(dtype, copy=False) @ target_names.T
        desc_sim = src.descriptions[rows].astype(dtype, copy=False) @ target_descriptions.T
        np.maximum(name_sim, 0.0, out=name_sim)
        np.maximum(desc_sim, 0.0, out=desc_sim)
        if count_all:
            # Scores are read from these blocks, so they hold exact similarities.
            np.minimum(name_sim, 1.0, out=name_sim)
            np.minimum(desc_sim, 1.0, out=desc_sim)
        for block, keys, positions in ((name_sim, src.name_keys, name_positions),
                                       (desc_sim, src.description_keys, description_positions)):
            for offset, key in enumerate(keys[i0:i1].tolist()):
                if key >= 0 and key in positions:
                    block[offset, positions[key]] = 1.0
        if count_all:
            semantic = desc_sim * CONCEPT_DESCRIPTION_WEIGHT
        else:
            # Only a bound is needed from float32 blocks; pairs are rescored.
            semantic = np.multiply(desc_sim, CONCEPT_DESCRIPTION_WEIGHT, out=desc_sim)
        semantic += CONCEPT_NAME_WEIGHT * name_sim
        np.maximum(semantic, name_sim, out=semantic)

        bar = threshold
        if not count_all and len(strongest) >= depth:
            bar = max(threshold, strongest[0][0])
        ii, jj = np.nonzero(semantic > semantic_floor(bar, max_structure) - margin)
        del semantic
        if ii.size == 0:
            continue

        if count_all:
            flags = np.zeros(ii.size, dtype=bool)
            scores = concept_similarity_scores(
                name_sim[ii, jj], desc_sim[ii, jj], flags, flags, flags, flags,
                structure[src.groups[ii + i0], tgt.groups[jj]])
            batches = [(ii + i0, jj, scores)]
        else:
            batches = []
            ii = ii + i0
            for b0 in range(0, ii.size, _EXACT_BATCH):
                bi, bj = ii[b0:b0 + _EXACT_BATCH], jj[b0:b0 + _EXACT_BATCH]
                batches.append((bi, bj, _exact_pair_scores(src, tgt, structure, bi, bj)))
        del name_sim, desc_sim

        for bi, bj, scores in batches:
            passing = scores > threshold
            if not passing.any():
                continue
            bi, bj, scores = bi[passing], bj[passing], scores[passing]
            if count_all:
                result["pairs"] += int(scores.size)
                result["total"] += float(scores.sum())
                np.add.at(row_pairs, bi, 1)
                np.add.at(row_total, bi, scores)
                np.add.at(col_pairs, bj, 1)
                np.add.at(col_total, bj, scores)
            if scores.size > depth:
                kth = np.partition(scores, scores.size - depth)[scores.size - depth]
                tied = np.nonzero(scores >= kth)[0]
                order = np.lexsort((bj[tied], bi[tied], -scores[tied]))[:depth]
                if tied.size > depth:
                    result["complete"] = False
                chosen = tied[order]
                if scores.size > chosen.size:
                    result["complete"] = False
                bi, bj, scores = bi[chosen], bj[chosen], scores[chosen]
            for score, i, j in zip(scores.tolist(), bi.tolist(), bj.tolist()):
                item = (score, -i, -j)
                if len(strongest) < depth:
                    heapq.heappush(strongest, item)
                else:
                    result["complete"] = False
                    if item > strongest[0]:
                        heapq.heapreplace(strongest, item)

    if not count_all and len(strongest) >= depth:
        # The scan stopped rescoring pairs below the rising bar, so pairs beyond
        # the depth may exist unseen.
        result["complete"] = False
    result["strongest"] = [(score, src.concept_ids[-i], tgt.concept_ids[-j])
                           for score, i, j in sorted(strongest, reverse=True)]
    if count_all:
        result["rows"] = {src.concept_ids[i]: (int(row_pairs[i]), float(row_total[i]))
                          for i in np.nonzero(row_pairs)[0].tolist()}
        result["cols"] = {tgt.concept_ids[j]: (int(col_pairs[j]), float(col_total[j]))
                          for j in np.nonzero(col_pairs)[0].tolist()}
    return result


def _update_correspondence(prev: Dict[str, Any], src: _ConceptSide, tgt: _ConceptSide,
                           changed_src: Set[str], changed_tgt: Set[str],
                           threshold: float, depth: int,
                           count_all: bool) -> Optional[Dict[str, Any]]:
    """`prev` brought up to date after the concepts in `changed_src` /
    `changed_tgt` joined, left or changed; None when that cannot be done
    exactly, and the caller scores in full. Blocking.

    Only pairs touching a changed concept are scored. Pairs between unchanged
    concepts keep their scores, and their relative order: a re-registered
    concept moves to the end of its domain, the others keep their order.
    """
    n, m = len(src.concept_ids), len(tgt.concept_ids)
    if (len(changed_src) > max(1000, n // 10) or len(changed_tgt) > max(1000, m // 10)
            or (count_all and changed_src and changed_tgt)
            or (count_all and changed_src and prev.get("rows") is None)
            or (count_all and changed_tgt and prev.get("cols") is None)):
        return None
    src_pos = {cid: i for i, cid in enumerate(src.concept_ids)}
    tgt_pos = {cid: j for j, cid in enumerate(tgt.concept_ids)}

    parts = []
    changed_rows = sorted(src_pos[c] for c in changed_src if c in src_pos)
    if changed_rows:
        parts.append(_score_correspondence(
            _slice_side(src, changed_rows), tgt, threshold, depth, count_all))
    changed_cols = sorted(tgt_pos[c] for c in changed_tgt if c in tgt_pos)
    if changed_cols:
        changed_row_set = set(changed_rows)
        unchanged_rows = [i for i in range(n) if i not in changed_row_set]
        if unchanged_rows:
            parts.append(_score_correspondence(
                _slice_side(src, unchanged_rows), _slice_side(tgt, changed_cols),
                threshold, depth, count_all))

    def rank(entry):
        return (-entry[0], src_pos[entry[1]], tgt_pos[entry[2]])

    kept = [e for e in prev["strongest"] if e[1] not in changed_src and e[2] not in changed_tgt]
    # A list that is not every passing pair of its region is exact only down to
    # its own last entry: anything it left out ranks after that.
    bounds = []
    if not prev["complete"]:
        if not kept:
            return None
        bounds.append(max(rank(e) for e in kept))
    for part in parts:
        if not part["complete"]:
            bounds.append(max(rank(e) for e in part["strongest"]))
    candidates = sorted(kept + [e for part in parts for e in part["strongest"]], key=rank)
    if bounds:
        bound = min(bounds)
        candidates = [e for e in candidates if rank(e) <= bound]
    result: Dict[str, Any] = {
        "source_concepts": n, "target_concepts": m,
        "strongest": candidates[:depth],
        "complete": not bounds and len(candidates) <= depth,
        "pairs": None, "total": None, "rows": None, "cols": None,
    }
    if count_all:
        if changed_src:
            rows = {c: v for c, v in prev["rows"].items() if c not in changed_src}
            removed = [prev["rows"][c] for c in changed_src if c in prev["rows"]]
            for part in parts:
                rows.update(part["rows"])
            result["rows"] = rows
        else:
            cols = {c: v for c, v in prev["cols"].items() if c not in changed_tgt}
            removed = [prev["cols"][c] for c in changed_tgt if c in prev["cols"]]
            for part in parts:
                cols.update(part["cols"])
            result["cols"] = cols
        result["pairs"] = (prev["pairs"] - sum(p for p, _t in removed)
                           + sum(part["pairs"] for part in parts))
        result["total"] = (prev["total"] - sum(t for _p, t in removed)
                           + sum(part["total"] for part in parts))
    return result


class UniversalDomainMaster:
    """
    Universal Domain Master - Cross-Domain Orchestration Tool

    Singleton tool that coordinates cross-domain knowledge integration
    and reasoning. Enables agents to execute queries spanning multiple
    knowledge domains with intelligent reasoning strategies.

    Architecture:
    - Tool-based interface (not autonomous orchestrator)
    - Integration with Domain Registry
    - PostgreSQL persistence (unified.*) for domain relationships
    - 15 domain types with 7 reasoning strategies
    - Concept mapping and knowledge transfer

    Features:
    - Cross-domain query execution
    - Knowledge transfer orchestration
    - Domain-to-domain mapping
    - Analogical reasoning
    - Concept alignment
    """

    # Bounded cognition: a category reference expands to its member fields, and
    # a category-vs-category query is |sources| x |targets| reasoning calls. Cap
    # the expansion per side; the resolver ranks by concept overlap first and
    # logs whatever it drops, so the bound is visible rather than silent.
    MAX_RESOLVED_FIELDS: int = 4

    _instance: Optional['UniversalDomainMaster'] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Prevent re-initialization
        if hasattr(self, '_initialized'):
            return

        self.db = None  # Will be set to TorinUnifiedDatabase in initialize()

        # Domain registry cache
        self.domain_cache: Dict[DomainType, Dict[str, Any]] = {}
        self.mapping_cache: Dict[Tuple[DomainType, DomainType], List[DomainMapping]] = {}

        # Statistics
        self.stats = {
            'total_queries': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'total_mappings': 0
        }

        # Concept vectors and what is derived from them, each entry keyed by the
        # registry content version it was computed from.
        self._schema_ready = False
        self._vectors = _ConceptVectorStore()
        self._sides: Dict[str, Tuple[Tuple[int, int], _ConceptSide]] = {}
        self._signatures: Dict[str, Tuple[Tuple[int, int], Any]] = {}
        self._correspondences: Dict[tuple, Tuple[tuple, Dict[str, Any]]] = {}
        self._correspondence_runs: Dict[tuple, Tuple[tuple, "asyncio.Task"]] = {}
        self._pair_mappings: Dict[tuple, Tuple[tuple, List["DomainMapping"]]] = {}
        self._embedding_backfill: Optional["asyncio.Task"] = None

        self._initialized = True
        logger.info("🧰 UniversalDomainMaster initialized as Singleton tool (not autonomous orchestrator)")

    async def initialize(self):
        """Initialize database and load domain registry"""
        try:
            await self._database()

            # Load domain definitions
            await self._load_domain_registry()

            logger.info("✓ Universal Domain Master initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Universal Domain Master: {e}")
            raise

    async def _database(self):
        """The database, initialized, with the concept vector columns present."""
        if self.db is None:
            from core.database import get_database_manager
            self.db = get_database_manager()
        if not self.db.initialized:
            await self.db.initialize()
        if not self._schema_ready:
            await self._ensure_concept_vector_schema()
            self._schema_ready = True
        return self.db

    async def ensure_concept_schema(self) -> None:
        """For writers of unified.concepts, whose upsert maintains these columns."""
        await self._database()

    async def _ensure_concept_vector_schema(self) -> None:
        """name_embedding / description_embedding / embedding_model on unified.concepts.

        Columns are added only when missing: ADD COLUMN takes an exclusive lock
        even when IF NOT EXISTS makes it a no-op. Vectors written by any other
        model are cleared, because they are not comparable with this model's.

        A frozen release is not maintained: what it lacks is refused as a
        mismatch by the manager, and its vectors are left as they were cut. Any
        written by another model are reported; development re-encodes them and
        cuts the next release.
        """
        from core.memory.utils.embedding_service import (
            EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_ID)
        db = self.db
        present = {r["column_name"] for r in await db.execute_query(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'unified' AND table_name = 'concepts'
                 AND column_name IN ('name_embedding', 'description_embedding',
                                     'embedding_model')""", fetch_all=True,
            store="model") or []}
        wanted = [("name_embedding", f"vector({EMBEDDING_DIMENSIONS})"),
                  ("description_embedding", f"vector({EMBEDDING_DIMENSIONS})"),
                  ("embedding_model", "TEXT")]
        missing = [f"ADD COLUMN {name} {ddl}" for name, ddl in wanted if name not in present]
        if missing:
            await db.execute_query(
                f"ALTER TABLE unified.concepts {', '.join(missing)}", commit=True)
            logger.info("unified.concepts: added %s", ", ".join(missing))
        indexed = await db.execute_query(
            """SELECT 1 FROM pg_indexes WHERE schemaname = 'unified'
               AND indexname = 'idx_concepts_embedding_pending'""", fetch_all=True,
            store="model")
        if not indexed:
            await db.execute_query(
                """CREATE INDEX idx_concepts_embedding_pending ON unified.concepts
                   (concept_id) WHERE embedding_model IS NULL""", commit=True)
        if getattr(db, "frozen", False):
            foreign = (await db.execute_query(
                """SELECT count(*) AS n FROM unified.concepts
                   WHERE embedding_model IS NOT NULL AND embedding_model <> $1""",
                (EMBEDDING_MODEL_ID,), fetch_all=True))[0]["n"]
            if foreign:
                logger.warning(
                    "release %s: %d concept vector(s) were written by a model other than %s; "
                    "a frozen release is not re-encoded (development re-encodes, then cuts)",
                    db.release, foreign, EMBEDDING_MODEL_ID)
            return
        from core.agents.memory_agent import memory_agent
        cleared = (await memory_agent().clear_foreign_vectors(
            model_id=EMBEDDING_MODEL_ID))[0]["n"]
        if cleared:
            logger.warning(
                "unified.concepts: cleared %d vector(s) written by a model other "
                "than %s; they will be re-encoded", cleared, EMBEDDING_MODEL_ID)

    async def _load_domain_registry(self):
        """Load domain definitions from database"""
        if not self.db:
            return

        # Check if domains exist
        count_result = await self.db.execute_query(
            "SELECT COUNT(*) as count FROM unified.domains",
            fetch_all=True
        )
        count = count_result[0]['count'] if count_result else 0

        if count == 0:
            # Initialize default domains
            await self._initialize_default_domains()

        # Load into cache
        rows = await self.db.execute_query(
            "SELECT domain_id, domain_name, description, metadata FROM unified.domains",
            fetch_all=True
        )

        # This cache is keyed by DomainType -- it holds only the CATEGORY-shaped
        # rows ("domain_<DomainType>"). A LEARNED domain (conversation, zoology,
        # vision, sensor, ...) is not a DomainType classification: it is a domain
        # the substrate has actually learned, tracked by the DomainRegistry, and it
        # correctly does NOT map here. So a non-category id is the EXPECTED case,
        # not an anomaly -- skip it quietly (debug), never warn.
        skipped_learned = 0
        for row in rows:
            # Parse domain_id to get domain_type (format: "domain_scientific")
            domain_id = row['domain_id']
            domain_type_str = domain_id.replace('domain_', '')
            try:
                domain_type = DomainType(domain_type_str)
                self.domain_cache[domain_type] = {
                    'domain_id': row['domain_id'],
                    'domain_name': row['domain_name'],
                    'description': row['description'],
                    'concepts': []  # Can be extracted from metadata JSONB if needed
                }
            except ValueError:
                skipped_learned += 1
                logger.debug("domain %s is a learned domain, not a DomainType "
                             "category — tracked by the registry, not this cache", domain_id)

        logger.info("Loaded %d DomainType categories into cache (%d learned "
                    "domains tracked elsewhere)", len(self.domain_cache), skipped_learned)

    async def _initialize_default_domains(self):
        """RETIRED: seeding the DomainType categories into unified.domains.

        This wrote all 15 DomainType values as domain rows on every startup
        (ON CONFLICT DO NOTHING, so the rows carried their original 2026-02-13
        timestamps and looked historical rather than re-asserted). Verified
        against the live registry, nothing read them:

          * a category reference resolves through the FIELD domains' own
            domain_type -- resolve_domain_reference("physical") still returns
            physics/fluid_mechanics/mechanics/... with every category row
            removed
          * the one exception, domain_abstract, is a precondition of
            DomainRegistry._project_universal_level, which now provides it
            itself rather than depending on this module's startup order

        What they did do is make 15 concept-less rows count as registered
        domains, so the registry reported "15 empty domains" beside its 18 real
        fields and every category looked like a knowledge domain holding
        nothing. A domain is something Torin has learned; a DomainType is a
        classification of one. Persisting the classifications as domains put
        both in one table with no way to tell them apart.

        Left as a no-op rather than deleted so the existing rows are not
        removed implicitly -- dropping them is a data decision, not a code one.
        """
        return

    async def _initialize_default_domains_RETIRED(self):
        if not self.db:
            return

        default_domains = [
            (DomainType.SCIENTIFIC, "Scientific Domain", "Natural sciences and research"),
            (DomainType.TECHNICAL, "Technical Domain", "Engineering and technology"),
            (DomainType.BUSINESS, "Business Domain", "Commerce and economics"),
            (DomainType.CREATIVE, "Creative Domain", "Arts and creative expression"),
            (DomainType.SOCIAL, "Social Domain", "Human interaction and society"),
            (DomainType.PHYSICAL, "Physical Domain", "Physical world and materials"),
            (DomainType.ABSTRACT, "Abstract Domain", "Abstract concepts and theory"),
            (DomainType.MATHEMATICAL, "Mathematical Domain", "Mathematics and logic"),
            (DomainType.LINGUISTIC, "Linguistic Domain", "Language and communication"),
            (DomainType.TEMPORAL, "Temporal Domain", "Time and sequence"),
            (DomainType.SPATIAL, "Spatial Domain", "Space and location"),
            (DomainType.CAUSAL, "Causal Domain", "Cause and effect relationships"),
            (DomainType.ETHICAL, "Ethical Domain", "Ethics and morality"),
            (DomainType.AESTHETIC, "Aesthetic Domain", "Beauty and aesthetics"),
            (DomainType.PRACTICAL, "Practical Domain", "Practical applications")
        ]

        from core.agents.memory_agent import memory_agent
        for domain_type, name, description in default_domains:
            await memory_agent().hold_default_domain(
                domain_id=f"domain_{domain_type.value}", name=name,
                description=description)

    # ==================================================================
    # DOMAIN CREATION & DISCOVERY — the single authority
    #
    # A domain is something the substrate has learned or can act in. A
    # DomainType merely classifies one. Nothing in the codebase created a
    # domain at runtime: `register_domain` had zero callers and the only rows
    # in unified.domains were the 15 DomainType categories seeded once. So the
    # substrate could learn operators in a domain forever and that domain never
    # became a thing the rest of the system could refer to. These methods are
    # where that changes, and they live HERE because the Universal Domain Master
    # is the authority for the domain system -- creation included.
    # ==================================================================

    async def _registry(self):
        """The domain store this authority writes through.

        The registry owns persistence and indexing; the Master owns the
        DECISION to bring a domain into existence. One store, one authority --
        not a second cache of domains keyed by DomainType, which is what
        `domain_cache` was and why classifications and learned domains were
        indistinguishable.
        """
        from core.domain.domain_registry import get_domain_registry
        registry = get_domain_registry()
        if not registry.initialized:
            await registry.initialize()
        return registry

    def is_learned_domain(self, domain) -> bool:
        """A domain the substrate actually has capability in, not a DomainType
        category seeded into the same table."""
        return bool((getattr(domain, "boundaries", None) or {}).get("origin") == "learned")

    async def ensure_domain(
        self, domain_id: str, *, name: Optional[str] = None,
        description: str = "", domain_type: Optional[DomainType] = None,
    ) -> "Any":
        """Register an operational domain as a first-class Domain, idempotently.

        THE SINGLE AUTHORITY for a domain coming into existence. When the
        substrate first has real capability in a domain -- a binding, a learned
        operator, grounded evidence -- this makes that domain something beliefs,
        exploration, cross-domain transfer and concepts can all refer to by one
        identity.

        Idempotent: an already-registered domain is returned unchanged. This is
        the first caller `DomainRegistry.register_domain` has ever had; routing
        every creation through here keeps one account of what domains exist.
        """
        from core.domain.domain_types import Domain

        registry = await self._registry()
        existing = registry.domains.get(domain_id)
        if existing is not None:
            return existing

        # Classify only if not told. A learned domain is ABSTRACT until it earns
        # a sharper type -- the same honest default the concept loader uses for
        # an unmapped field, rather than guessing.
        if domain_type is None:
            field = domain_id.replace("domain_", "")
            domain_type = registry._FIELD_TO_DOMAIN_TYPE.get(field, DomainType.ABSTRACT)

        domain = Domain(
            domain_id=domain_id,
            name=name or domain_id.replace("_", " ").strip().title() or domain_id,
            domain_type=domain_type,
            description=description or (
                f"Operational domain the substrate acts and learns in: {domain_id}"),
            # MARK IT LEARNED so it is never confused with a DomainType category
            # in the same table -- the distinction the retired seeder's own note
            # said nothing recorded.
            boundaries={"origin": "learned"},
            maturity_score=0.1,  # newly discovered; competence is low
        )
        if not await registry.register_domain(domain):
            raise RuntimeError(f"domain {domain_id} could not be registered")
        # A domain the substrate has just discovered is one it is not yet
        # competent in. Record that as an epistemic belief at maximum
        # uncertainty so the domain SURFACES in the epistemic engine's unstable
        # regions -- which is what intrinsic motivation reads to choose what to
        # explore. Exploration then flows here through the designed motivation
        # system, not a bespoke selector.
        try:
            await self.ensure_competence_belief(domain_id)
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "universal_domain_master.ensure_domain.belief")
            logger.info("competence belief for %s deferred: %s", domain_id, e)
        logger.info("UDM registered operational domain %s (type=%s)",
                    domain_id, domain_type.value)
        return domain

    async def _ensure_domain_for_capability(self, domain_id: str) -> None:
        """Register a domain the substrate has just shown capability in, without
        letting a registration hiccup break the recording that called this. A
        structural fault (a real wiring bug) still surfaces via
        raise_if_structural; only a transient failure degrades to a log, because
        the competence/controllability evidence is the primary work here and must
        not be lost to a domain-registry problem."""
        if not (isinstance(domain_id, str) and domain_id.strip()):
            return
        try:
            await self.ensure_domain(domain_id)
        except Exception as e:
            from core.capability import raise_if_structural
            raise_if_structural(e, "universal_domain_master._ensure_domain_for_capability")
            logger.info("domain registration for %s deferred: %s", domain_id, e)

    # ── DOMAIN COMPETENCE AS AN EPISTEMIC BELIEF ──────────────────────────
    # Operator-learning competence per domain is tracked as a belief so the
    # SAME intrinsic-motivation machinery that chooses every other exploration
    # target chooses which domain to learn operators in. A belief at ~0.5
    # posterior has near-maximal entropy and appears in get_unstable_regions;
    # as operators are learned its posterior rises and it exits the set. This
    # is the competence drive's inverted-U for free: explore where competence
    # is UNCERTAIN, not where it is mastered or hopeless.

    def _competence_claim(self, domain_id: str) -> str:
        return f"the substrate has learned the operators of domain {domain_id}"

    @staticmethod
    def _uncertainty():
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system()

    async def _remember_domain(self, domain_id: str) -> Optional[str]:
        """Remember that the substrate HAS this domain, and return the memory id.

        A competence belief is a stance on something the substrate has MET, and
        the belief authority enforces exactly that: a belief naming no memory is
        refused ("a belief is a stance on something the substrate has met, not a
        place to keep a claim"). Encountering a domain IS such an event — it is
        the moment the substrate first had real capability or knowledge here —
        so it is remembered, and the competence belief is about that memory.

        Without this the whole competence spine was dead: measured on the live
        store, 415 domains and ZERO competence beliefs, every one silently
        refused (the guard logs only the 1st and every 100th). Nothing surfaced
        for exploration, learning progress had no history, and the drive that
        reads competence had nothing to read.
        """
        try:
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType
            agent = await get_memory_agent()
            from core.memory import Origin
            stored, memory_id = await agent.store_memory(
                origin=Origin.own("domains"),
                content=(f"The substrate has a domain it can learn and act in: "
                         f"{domain_id}."),
                memory_type=MemoryType.SEMANTIC,
                importance_score=0.7,
                confidence_score=1.0,
                tags=["domain", self.DOMAIN_MEMORY_TAG],
                source_context={"producer": "domain_authority",
                                "source_id": domain_id, "domain_id": domain_id})
            return memory_id
        except Exception as error:
            logger.warning("could not remember domain %s (%s); its competence "
                           "belief will be refused as ungrounded",
                           domain_id, error)
            return None

    #: Tag on the memory that a domain exists, so the record of meeting a domain
    #: is findable as the kind of thing it is rather than only by its wording.
    DOMAIN_MEMORY_TAG = "domain_existence"

    async def ensure_competence_belief(self, domain_id: str):
        """The belief tracking whether the substrate has learned a domain's
        operators, created at maximum uncertainty if absent.

        GROUNDED IN THE MEMORY OF MEETING THE DOMAIN. It used to be created with
        no subject at all, which the belief authority refuses — so this method
        returned a belief object that never reached the store, and every caller
        downstream (exploration surfacing, learning progress, the competence
        drive) read an empty set and behaved as if the substrate had no domains.
        """
        unc = self._uncertainty()
        claim = self._competence_claim(domain_id)
        existing = next((b for b in unc.beliefs.values()
                         if b.claim == claim and b.domain == domain_id), None)
        if existing is None:
            from core.learning.unified_learning_system import get_unified_learning_system
            memory_id = await self._remember_domain(domain_id)
            # NO `evidence=` HERE, DELIBERATELY. `create_belief` applies any
            # non-empty evidence dict as a SUPPORTING observation, and its own
            # docstring warns that a source-only dict "would silently nudge every
            # no-evidence belief up from its prior". Measured when this was first
            # written that way: the belief landed at 0.818 instead of 0.5, which
            # defeats the entire point — a domain at that posterior has low
            # entropy and never appears in the unstable regions intrinsic
            # motivation reads to choose what to explore.
            #
            # The memory is the belief's SUBJECT, not evidence for it. Knowing a
            # domain exists is not evidence that its operators have been learned.
            existing = get_unified_learning_system().create_belief(
                claim, domain=domain_id, prior=0.5)
            if memory_id:
                existing.memory_id = memory_id
            # Durable, not fire-and-forget: competence decides what the substrate
            # explores after a restart, so it must actually reach the store.
            await unc.flush_belief(existing.belief_id)
        return existing

    #: One exploration cycle is one weak, noisy data point about competence, not
    #: a confident verdict. A low evidence quality dampens the belief so
    #: competence is EARNED over several cycles: a single failure only nudges the
    #: belief (a domain is not abandoned after one bad cycle), and competence
    #: does not reach certainty in a handful of successes. Measured: at 0.15 one
    #: failure from 0.5 leaves entropy ~0.96 (still explored), while it takes
    #: several consistent cycles to move the belief out of the exploration set.
    COMPETENCE_EVIDENCE_QUALITY: float = 0.15

    async def record_competence_evidence(
        self, domain_id: str, *, learned: bool,
        quality: Optional[float] = None) -> None:
        """Move a domain's competence belief toward learned / not-learned.

        A newly learned operator is evidence the substrate is becoming competent
        (posterior up, entropy down → the domain eventually leaves exploration).
        A cycle that acted and learned nothing is weak evidence against, so a
        domain that yields nothing stops being chased -- but only after several
        cycles, never after one (see COMPETENCE_EVIDENCE_QUALITY).
        """
        if quality is None:
            quality = self.COMPETENCE_EVIDENCE_QUALITY
        # A learned operator IS the substrate first having real capability in a
        # domain -- exactly ensure_domain's stated trigger. Register it here so a
        # domain the substrate can act in is never left without a first-class
        # identity beliefs/exploration/transfer/concepts can refer to. Idempotent
        # and off the hot path. (Was the missing wire: learned-operator domains
        # existed only as rule-store strings, invisible to the domain authority.)
        await self._ensure_domain_for_capability(domain_id)
        unc = self._uncertainty()
        belief = await self.ensure_competence_belief(domain_id)
        from core.learning.unified_learning_system import get_unified_learning_system
        get_unified_learning_system().update_belief(
            belief.belief_id, {"source": "operator_learning", "quality": quality},
            evidence_supports=learned)
        # Flush the update durably -- a competence change that only lives in
        # memory would be undone by the next restart, and the domain would be
        # re-explored as if nothing had been learned.
        await unc.flush_belief(belief.belief_id)

    async def refresh_competence_beliefs(self) -> int:
        """Decay every competence belief toward uncertainty by the time elapsed
        since it was last touched.

        Competence that is no longer being earned erodes, so a domain the
        substrate WRONGLY believes it has mastered drifts back into the unstable
        set and is re-verified against the world -- which corrects a false
        estimate through failure. Called each exploration cycle. Returns how many
        competence beliefs were decayed.
        """
        unc = self._uncertainty()
        prefix = "the substrate has learned the operators of domain "
        decayed = 0
        for belief in list(unc.beliefs.values()):
            if isinstance(belief.claim, str) and belief.claim.startswith(prefix):
                await unc.decay_belief(belief.belief_id)
                decayed += 1
        return decayed

    #: How many recent competence observations to measure progress over.
    LEARNING_PROGRESS_WINDOW: int = 4
    #: A surfaced domain whose competence is not RISING by at least this much
    #: over the window is not worth exploring now: it is stuck (noise, no
    #: expected information gain) or falling (already being classified as
    #: blocked). Optimism for the unexplored is handled separately.
    MIN_LEARNING_PROGRESS: float = 0.01
    #: Learning progress assigned to a domain with too little history to measure
    #: -- optimism in the face of the unknown, so a fresh domain is tried before
    #: it is judged.
    OPTIMISTIC_PROGRESS: float = 1.0

    def competence_belief(self, domain_id: str):
        """This domain's operator-competence belief, or None if it has none --
        what the substrate believes about whether it has learned to act here."""
        return self._competence_belief_of(domain_id)

    def _competence_belief_of(self, domain_id: str):
        unc = self._uncertainty()
        claim = self._competence_claim(domain_id)
        return next((b for b in unc.beliefs.values()
                     if b.claim == claim and b.domain == domain_id), None)

    def learning_progress(self, domain_id: str) -> float:
        """Signed learning progress: how much competence has RISEN over the
        recent window (`confidence_history`).

        This is the derivative of competence, the principled form of expected
        information gain. A domain being learned has POSITIVE progress and is
        worth more exploration; one that is stuck (noise -- competence
        oscillates, net ~0) or falling (being classified as unlearnable) has
        zero/negative progress and is deprioritized. A domain with too little
        history to measure is optimistic, so it is tried before it is judged.

        Progress is measured in-memory; after a restart it resets to optimistic
        while the competence LEVEL persists -- the substrate re-measures the
        rate by exploring, which is the honest thing to do, and never wrongly
        skips a domain on a rate it no longer remembers.
        """
        belief = self._competence_belief_of(domain_id)
        if belief is None:
            return 0.0
        history = belief.confidence_history
        if len(history) < 2:
            return self.OPTIMISTIC_PROGRESS
        window = min(self.LEARNING_PROGRESS_WINDOW, len(history) - 1)
        return history[-1] - history[-1 - window]

    #: Below this, the substrate's actions do not meaningfully move the domain
    #: (they produce no effect, or the world changes on its own regardless):
    #: uncontrollable, so exploring it cannot build steerable competence.
    CONTROLLABILITY_FLOOR: float = 0.05

    async def _ensure_controllability_table(self):
        if not self.db:
            return
        await self.db.execute_query(
            """CREATE TABLE IF NOT EXISTS unified.domain_controllability (
                   domain_id          VARCHAR PRIMARY KEY,
                   action_attempts    BIGINT NOT NULL DEFAULT 0,
                   action_effects     BIGINT NOT NULL DEFAULT 0,
                   still_observations BIGINT NOT NULL DEFAULT 0,
                   ambient_changes    BIGINT NOT NULL DEFAULT 0,
                   updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        # operating-outcome accounting shares this authority (one owner for all
        # per-domain action accounting -- controllability is "do my acts MOVE the
        # domain"; operating is "when I acted to DO a task here, was the outcome
        # RIGHT"). Distinct measurements, same table; added to existing rows too.
        await self.db.execute_query(
            "ALTER TABLE unified.domain_controllability "
            "ADD COLUMN IF NOT EXISTS operating_attempts BIGINT NOT NULL DEFAULT 0")
        await self.db.execute_query(
            "ALTER TABLE unified.domain_controllability "
            "ADD COLUMN IF NOT EXISTS operating_wins BIGINT NOT NULL DEFAULT 0")

    async def record_controllability(
        self, domain_id: str, *, action_attempts: int = 0, action_effects: int = 0,
        still_observations: int = 0, ambient_changes: int = 0) -> None:
        """Accumulate evidence about whether the substrate's actions move a
        domain. `action_*` come from acting (attempts, and how many changed the
        world); the observation counts come from watching the world with NO
        action taken (and how often it moved anyway). Persisted so controllability
        survives a restart, since it is expensive to re-measure."""
        # Acting in a domain is the substrate having real capability in it, so the
        # domain becomes first-class here too (idempotent) -- even if the
        # controllability table write below is skipped for lack of a db.
        await self._ensure_domain_for_capability(domain_id)
        if not self.db:
            return
        await self._ensure_controllability_table()
        from core.agents.memory_agent import memory_agent
        await memory_agent().record_controllability(
            domain_id=domain_id, action_attempts=int(action_attempts),
            action_effects=int(action_effects),
            still_observations=int(still_observations),
            ambient_changes=int(ambient_changes))

    async def controllability(self, domain_id: str) -> float:
        """How much the substrate's actions move a domain, in [0,1].

        `action_effect_rate * (1 - ambient_rate)`: controllable means acting
        produces effects AND the world is otherwise stable. Actions that produce
        nothing, or a world that moves on its own, both drive it toward 0 -- an
        uncontrollable domain the substrate cannot learn to steer, which is
        distinct from noise (noise is caught by learning progress). Optimistic
        (1.0) with no evidence yet, so a fresh domain is tried before it is
        judged.
        """
        if not self.db:
            return 1.0
        await self._ensure_controllability_table()
        rows = await self.db.execute_query(
            "SELECT action_attempts, action_effects, still_observations, "
            "ambient_changes FROM unified.domain_controllability WHERE domain_id=$1",
            (domain_id,), fetch_all=True)
        if not rows:
            return 1.0
        row = rows[0]
        attempts = row["action_attempts"] or 0
        if attempts == 0:
            return 1.0  # not yet acted here -- optimistic
        action_effect_rate = (row["action_effects"] or 0) / attempts
        still = row["still_observations"] or 0
        ambient_rate = ((row["ambient_changes"] or 0) / still) if still else 0.0
        return max(0.0, min(1.0, action_effect_rate * (1.0 - ambient_rate)))

    #: Minimum operating outcomes before earned reliability is allowed to move the
    #: operability bar. Below this, the Wilson bound is reported but treated as
    #: NEUTRAL (no shift) -- a single right/wrong operation must not swing trust,
    #: the same "earned over several, never one" discipline as competence. Mirrors
    #: the learning-progress window.
    OPERATING_MIN_SAMPLE: int = 4

    async def record_operating_outcome(
        self, domain_id: str, *, success: bool,
        outcome_class: Optional["OutcomeClass"] = None,
    ) -> bool:
        """Record one OPERATING outcome in a domain -- the substrate acted to DO a
        task there (answer/troubleshoot/modify) and the result was verified RIGHT
        (success) or WRONG. This is the EARNED half of operability: proven-correct
        operation lowers the knowledge bar it must clear to act there again; being
        wrong raises it. Distinct from competence (did I LEARN the operators) and
        controllability (do my acts MOVE the world) -- correctness, not either of
        those. Persisted so earned trust survives a restart.

        THE CREDIT INVARIANT APPLIES HERE, at the one place this posterior moves
        rather than at the call sites -- the same discipline `track_learning_outcome`
        enforces for strategy arms, and for the same reason: an outcome that says
        nothing about operating correctly must not be allowed to move a signal that
        governs whether the substrate may act in this domain at all.

        The motivating case was MEASURED, not hypothesized: a goal the substrate
        could not PLAN executed nothing -- no tool invoked, no world change -- and
        still landed as `operating_attempts += 1, wins += 0`. A knowledge deficit
        was being recorded as an operating failure, and because `earned` raises the
        KNOW->DO bar when it falls, not knowing how to act in a domain made the
        substrate LESS free to act there. That is self-reinforcing in the wrong
        direction: the remedy for a deficit is to operate and learn, and the
        deficit was closing that door on itself.

        Returns whether the outcome was credited, so a caller can tell a denied
        outcome from a recorded one instead of inferring it from the counters.
        """
        from core.learning.meta_learning import OutcomeClass, is_credit_eligible

        if outcome_class is None:
            # Conservative default, deliberately loud: a caller that forgets to
            # classify loses a data point audibly rather than silently teaching
            # the substrate a false thing about how well it operates.
            outcome_class = OutcomeClass.INDETERMINATE
            logger.warning(
                "record_operating_outcome called without outcome_class for %s -- "
                "denied credit as INDETERMINATE", domain_id)
        if not is_credit_eligible(outcome_class):
            logger.info(
                "operating outcome for %s NOT credited (%s): it establishes "
                "nothing about operating correctness here",
                domain_id, outcome_class.value)
            return False

        await self._ensure_domain_for_capability(domain_id)
        if not self.db:
            return False
        await self._ensure_controllability_table()
        from core.agents.memory_agent import memory_agent
        await memory_agent().record_operating_outcome(
            domain_id=domain_id, win=1 if success else 0)
        return True

    async def operating_reliability(self, domain_id: str) -> Dict[str, Any]:
        """How reliably the substrate operates CORRECTLY in a domain, as the
        lower bound of the Wilson 95% interval on its operating win-rate -- the
        conservative, sample-size-aware estimate the StrategyAdaptationGate uses.

        `earned` in [0,1] is the shift signal: the Wilson lower bound once enough
        outcomes have accrued, else a NEUTRAL 0.5 (optimism withheld BOTH ways
        until earned -- too few outcomes neither lowers nor raises the bar). The
        lower bound is the right statistic: a handful of wins does not yet earn a
        bar drop (wide interval, low floor), while a consistent record does."""
        from core.agents.autonomous.idle_work_playbook import StrategyAdaptationGate
        attempts = wins = 0
        if self.db:
            await self._ensure_controllability_table()
            rows = await self.db.execute_query(
                "SELECT operating_attempts, operating_wins FROM "
                "unified.domain_controllability WHERE domain_id=$1",
                (domain_id,), fetch_all=True)
            if rows:
                attempts = rows[0]["operating_attempts"] or 0
                wins = rows[0]["operating_wins"] or 0
        lo, hi = StrategyAdaptationGate._wilson_ci(wins, attempts) if attempts else (0.0, 1.0)
        enough = attempts >= self.OPERATING_MIN_SAMPLE
        earned = round(lo, 4) if enough else 0.5
        return {"domain": domain_id, "attempts": int(attempts), "wins": int(wins),
                "win_rate": round(wins / attempts, 4) if attempts else None,
                "wilson_lower": round(lo, 4), "wilson_upper": round(hi, 4),
                "earned": earned, "enough_history": enough}

    async def diagnose_deficit(
        self, domain_id: str, goal_conditions, world, outcome,
    ) -> "EpistemicDeficit":
        """WHAT kind of knowledge is missing behind a goal that would not plan.

        A sibling of competence, controllability, and learning progress: a
        model-free MEASUREMENT of a domain's knowledge state, read from signals
        that already exist -- the planner's verdict, the rule store, the
        bindings, and the domain's vocabulary. It makes no decision; it returns a
        typed deficit whose `appraisal_signals()` feed the AppraisalSystem, which
        owns the disposition. The default is UNKNOWN_GAP: the substrate may know
        THAT it is deficient before it knows HOW, and manufacturing a specific
        type it cannot support would be worse than admitting that.

        Returns exactly one deficit: when several goal conditions fail for
        different reasons, the most UPSTREAM one, since a downstream fix cannot
        help while an upstream deficiency stands.
        """
        from core.execution.operator_binding import get_binding_registry
        from core.learning.rule_induction import Fact
        from core.learning.rule_store import get_rule_store

        registry = get_binding_registry()

        # OBSERVATION dominates: a world that cannot be read leaves nothing to
        # reason over, and every other diagnosis would rest on a world never
        # observed.
        bindings = list(registry.bindings_for(domain_id) or ())
        if registry.observe_world(domain_id) is None:
            return EpistemicDeficit(
                domain_id, DeficitType.OBSERVATION_GAP,
                evidence={"bindings": len(bindings)})

        # A planner UNREACHABLE over a COMPLETE operator set means "no plan with
        # the operators I have NOW", not "impossible". Alone it does not
        # distinguish a learnable OPERATOR_GAP from a genuine world constraint --
        # an empty operator set is trivially "complete" and its exhaustion proves
        # only that nothing has been learned yet. So this is NOT WORLD_PREVENTS on
        # its own; it upgrades an otherwise-UNKNOWN result AFTER the structural
        # analysis has found the pieces are all there (see below).
        status = getattr(getattr(outcome, "status", None), "value",
                         getattr(outcome, "status", None))
        unreachable_proof = (
            status == "unreachable" and bool(getattr(outcome, "grounding_complete", False)))

        rules = await get_rule_store().load(domain_id=domain_id)
        actable = {b.predicate for b in bindings}
        world_facts = self._parse_facts(world or [], Fact)
        world_predicates = {f.predicate for f in world_facts}
        goal_facts = self._parse_facts(goal_conditions, Fact)

        vocabulary: Set[str] = set(world_predicates) | set(actable)
        executable_effect_predicates: Set[str] = set()
        for stored in rules:
            rule = stored.rule
            for fact in (*rule.effects.add, *rule.effects.delete, *rule.body):
                vocabulary.add(fact.predicate)
            if rule.action is not None:
                vocabulary.add(rule.action.predicate)
            if stored.is_executable:
                executable_effect_predicates |= {e.predicate for e in rule.effects.add}

        unmet = [g for g in goal_facts if g not in world_facts]
        if not unmet:
            return EpistemicDeficit(
                domain_id, DeficitType.UNKNOWN_GAP, confidence=0.5,
                evidence={"note": "goal conditions already hold; failure is elsewhere"})

        diagnoses: List[EpistemicDeficit] = []
        for goal in unmet:
            predicate = goal.predicate
            producers = [r for r in rules
                         if any(e.predicate == predicate for e in r.rule.effects.add)]
            actionable = [r for r in producers if r.rule.action is not None]
            executable = [r for r in actionable if r.is_executable]
            deficit_type, evidence = self._classify_deficit(
                predicate, world_predicates=world_predicates, vocabulary=vocabulary,
                actionable=actionable, executable=executable, actable=actable,
                executable_effect_predicates=executable_effect_predicates)
            diagnoses.append(EpistemicDeficit(
                domain_id, deficit_type, target_predicate=predicate, evidence=evidence))

        diagnoses.sort(key=lambda d: _DEFICIT_PRIORITY.index(d.deficit_type))
        chosen = diagnoses[0]

        # WORLD_PREVENTS is the upgrade of an otherwise-UNKNOWN result: every
        # unmet goal predicate is structurally SUFFICIENT (represented, produced
        # by a validated bound operator whose preconditions are reachable) and yet
        # the planner PROVED the goal unreachable over its complete operator set.
        # The pieces are all there and still cannot be composed -- that is a
        # genuine constraint of the world, and no learning operation would help.
        # Absent that proof, structural sufficiency is UNKNOWN (deficient but
        # unlocalised), never "impossible".
        if chosen.deficit_type is DeficitType.UNKNOWN_GAP and unreachable_proof:
            chosen = EpistemicDeficit(
                domain_id, DeficitType.WORLD_PREVENTS,
                target_predicate=chosen.target_predicate,
                evidence={"planning_status": "unreachable",
                          "operators_considered": getattr(outcome, "operators_considered", None),
                          "note": "structurally sufficient yet proved unreachable"})

        if len(diagnoses) > 1:
            chosen.evidence["other_unmet"] = [
                {d.target_predicate: d.deficit_type.value} for d in diagnoses[1:]]
        logger.info("deficit diagnosis for %s: %s (%s)", domain_id,
                    chosen.deficit_type.value, chosen.target_predicate)
        return chosen

    @staticmethod
    def _classify_deficit(
        predicate, *, world_predicates, vocabulary, actionable, executable,
        actable, executable_effect_predicates,
    ) -> Tuple["DeficitType", Dict[str, Any]]:
        """Diagnose one unmet goal predicate from local structural facts.

        Branch order follows the causal chain from symbol to action: represented?
        -> any operator produces it? -> any VALIDATED? -> bound to a tool? -> are
        its preconditions reachable? -> else undiagnosed.
        """
        # CONCEPT: the predicate appears nowhere in the domain. The substrate has
        # no representation to attach an operator to.
        if predicate not in vocabulary:
            return DeficitType.CONCEPT_GAP, {"predicate_in_vocabulary": False}

        # OPERATOR: represented, but nothing the substrate knows PRODUCES it.
        if not actionable:
            return DeficitType.OPERATOR_GAP, {"actionable_producers": 0}

        # CAUSAL: an actionable rule claims to produce it, but none is VALIDATED
        # -- a hypothesis, not an established operator. The fix is evidence.
        if not executable:
            return DeficitType.CAUSAL_GAP, {
                "hypothesised_producers": len(actionable), "validated_producers": 0}

        # BINDING: a VALIDATED operator produces it, but none of the validated
        # producers' actions is bound to a tool -- known in principle, cannot act.
        bound = [r for r in executable
                 if r.rule.action is not None and r.rule.action.predicate in actable]
        if not bound:
            unbound = sorted({r.rule.action.predicate for r in executable
                              if r.rule.action is not None})
            return DeficitType.BINDING_GAP, {"unbound_actions": unbound}

        # A bound, validated operator exists; the block is a PRECONDITION it needs
        # that the world lacks and no validated operator can produce. Relational
        # (arity >= 2) is a missing RELATION; unary is a missing PREREQUISITE.
        missing: List[Any] = []
        for producer in bound:
            gaps = [pre for pre in producer.rule.preconditions
                    if pre.predicate not in world_predicates
                    and pre.predicate not in executable_effect_predicates]
            if not gaps:
                missing = []
                break
            if not missing or len(gaps) < len(missing):
                missing = gaps
        if missing:
            relational = [m for m in missing if len(m.args) >= 2]
            chosen = relational[0] if relational else missing[0]
            deficit = DeficitType.RELATION_GAP if relational else DeficitType.PREREQUISITE_GAP
            return deficit, {"missing_precondition": str(chosen)}

        # Represented, produced, validated, bound, preconditions reachable -- and
        # still no plan. Real, but the local signals do not localise it.
        return DeficitType.UNKNOWN_GAP, {"note": "no local signal separates the deficit"}

    @staticmethod
    def _parse_facts(conditions, Fact) -> Set[Any]:
        """Parse fact strings, dropping any that do not parse -- a malformed
        condition is not evidence of a deficit type."""
        facts: Set[Any] = set()
        for condition in conditions:
            try:
                facts.add(Fact.parse(str(condition)))
            except ValueError:
                logger.debug("deficit diagnosis skipped unparseable condition %r", condition)
        return facts

    async def address_deficit(self, deficit: "EpistemicDeficit", *, _depth: int = 0) -> Dict[str, Any]:
        """Run the learning operation a diagnosed deficit calls for.

        The deficit's KIND already fixed WHICH operation (its `.operation`); this
        executes it against the existing subsystems, never re-deciding. It is the
        step that makes the discrimination matter: an OPERATOR_GAP explores for an
        action, a CAUSAL_GAP gathers the contrastives that validate a hypothesis,
        a PREREQUISITE_GAP turns to the intermediate it lacks -- and a deficit the
        substrate cannot resolve from here (a relation or concept it must be
        given, a binding or observer that must be wired) ESCALATEs honestly rather
        than burning the budget exploring for an operator that was never missing.

        Runs no model. Returns what the operation did; it does not decide whether
        to run -- that is appraisal's, upstream.
        """
        from core.learning.exploration import SubstrateExplorer, get_proposer

        op = deficit.operation
        domain = deficit.domain_id
        base = {"domain": domain, "deficit_type": deficit.deficit_type.value,
                "operation": op.value}

        if op in (LearningOperation.LEARN_OPERATOR, LearningOperation.VALIDATE_CAUSE,
                  LearningOperation.PROBE):
            proposer = get_proposer(domain)
            if proposer is None:
                # The operation is right; the substrate just has no way to act in
                # this domain yet. That is a binding/observer gap, not a licence
                # to fake exploration.
                return {**base, "ran": False, "reason": "no proposer registered for domain"}
            # Explore RECORDS (and enqueues signatures for induction); it does not
            # induce here. Controllability comes from the ACTING this cycle and is
            # recorded now; COMPETENCE follows the induction that the always-online
            # learner drains off the acting path -- learning is what moves
            # competence, not the acting that fed it -- so it is not recorded here.
            summary = await SubstrateExplorer().explore(domain, proposer, max_actions=8)
            await self.record_controllability(
                domain,
                action_attempts=summary.get("acted", 0),
                action_effects=summary.get("positive", 0),
                still_observations=summary.get("still_observations", 0),
                ambient_changes=summary.get("ambient_changes", 0))
            return {**base, "ran": True, "summary": summary}

        if op is LearningOperation.ACHIEVE_PREREQUISITE:
            # The operator for the goal exists and is bound; what blocks it is a
            # precondition the world lacks. Turn to THAT as its own goal: diagnose
            # what is missing about the precondition and address it (one level --
            # a chain of prerequisites is pursued across cycles, not by unbounded
            # recursion in one call).
            missing = deficit.evidence.get("missing_precondition")
            if not missing or _depth >= 1:
                return {**base, "ran": False, "reason": "prerequisite not localised"
                        if not missing else "prerequisite chain deferred to next cycle"}
            from core.execution.operator_binding import get_binding_registry
            observed = get_binding_registry().observe_world(domain)
            world = sorted(str(f) for f in observed) if observed is not None else []
            sub = await self.diagnose_deficit(domain, [missing], world, None)
            result = await self.address_deficit(sub, _depth=_depth + 1)
            return {**base, "ran": result.get("ran", False),
                    "prerequisite": missing, "resolved_via": result}

        if op is LearningOperation.TRANSFER_RELATION:
            # The operator for the goal exists and is bound; what blocks it is a
            # relational precondition the domain has no way to produce. Seek that
            # relation from a domain that HAS it: project the source's
            # relation-producing operator across the correspondence its shared
            # operators establish. The projection is a CANDIDATE -- analogy
            # proposes, only this domain's own evidence attests. If no source can
            # supply it, escalate honestly rather than pretend.
            from core.learning.rule_induction import Fact
            missing = deficit.evidence.get("missing_precondition")
            try:
                relation = Fact.parse(str(missing)).predicate if missing else deficit.target_predicate
            except ValueError:
                relation = deficit.target_predicate
            result = await self.transfer_relation(domain, relation)
            if result.get("transferred"):
                return {**base, "ran": True, **result}
            return {**base, "ran": False, "escalated": True,
                    "reason": deficit.remedy_reason, "transfer": result}

        if op is LearningOperation.ESCALATE:
            return {**base, "ran": False, "escalated": True,
                    "reason": deficit.remedy_reason}

        # DISENGAGE
        return {**base, "ran": False, "disengaged": True,
                "reason": "the world forbids the goal; no learning is justified"}

    async def transfer_relation(self, target_domain: str, relation_predicate: str) -> Dict[str, Any]:
        """Acquire a relation a domain cannot produce by projecting the operator
        that produces it from a domain that can.

        Model-free and structural. A source domain qualifies when its operators
        SHARE enough structure with the target to fix a predicate correspondence
        (`_partial_correspondence`), and it has an operator -- one the target
        LACKS -- whose effect adds a binary relation. That operator is projected
        into the target vocabulary: its shared preconditions renamed through the
        correspondence, its own action carried across, its produced relation
        mapped to the one the target needs. Any operator with a precondition the
        correspondence does NOT cover is skipped -- importing a source's private
        vocabulary would be inventing, not transferring.

        The projection lands as a CANDIDATE with zero evidence, and it does so
        THROUGH THE LEARNING AUTHORITY (`admit_projection`), not by writing to
        the rule store behind it: the analogy engine is a registered contributor
        and the authority is the single writer of admitted proposals. The
        analogy has PROPOSED that this domain can produce the relation, and only
        this domain's own observations can raise it to executable. So a
        successful transfer converts a RELATION_GAP into a CAUSAL_GAP -- a
        hypothesis to validate -- not a finished capability.
        """
        from core.learning.analogical_projection import project, ProjectionOutcome
        from core.learning.rule_store import get_rule_store
        from core.learning.unified_learning_system import get_learning_authority

        store = get_rule_store()
        authority = get_learning_authority()
        from collections import defaultdict
        by_domain: Dict[str, List[Any]] = defaultdict(list)
        for stored in await store.executable_rules():
            if stored.rule.action is not None and stored.domain_id:
                by_domain[stored.domain_id].append(stored)

        target_ops = [s.rule for s in by_domain.get(target_domain, [])]
        if not target_ops:
            return {"transferred": False,
                    "reason": "the target has no operators to fix a correspondence"}

        for source_domain, stored_ops in by_domain.items():
            if source_domain == target_domain:
                continue
            source_ops = [s.rule for s in stored_ops]
            mapping, aligned = self._partial_correspondence(source_ops, target_ops)
            # The correspondence -- fixed by the operators the two domains SHARE --
            # is what says which source relation IS the one the target needs.
            # Only a producer of THAT relation is transferred; mapping an
            # arbitrary binary relation onto the target would be guessing, not
            # transferring (the shared goal operator already names the pairing).
            source_relations = {sp for sp, tp in mapping.items() if tp == relation_predicate}
            if not source_relations:
                continue
            aligned_ids = {id(r) for r in aligned}
            for stored in stored_ops:
                producer = stored.rule
                if id(producer) in aligned_ids:
                    continue  # already an operator the target has
                if not any(f.predicate in source_relations and f.arity >= 2
                           for f in producer.effects.add):
                    continue
                # Everything the producer touches EXCEPT its own action must be
                # covered by the correspondence; importing a source's private
                # precondition would be inventing, not transferring. The action
                # itself is carried across -- it is the capability the target
                # lacks, and it remains an unbound symbol until a binding is
                # supplied (a further, honest gap).
                touched = ({f.predicate for f in producer.preconditions}
                           | {f.predicate for f in producer.effects.add}
                           | {f.predicate for f in producer.effects.delete})
                if any(p not in mapping for p in touched):
                    continue
                corr = {p: mapping[p] for p in touched}
                corr[producer.action.predicate] = mapping.get(
                    producer.action.predicate, producer.action.predicate)
                result = project(
                    producer, corr, source_rule_id=stored.rule_id,
                    source_domain=source_domain, target_domain=target_domain)
                if result.outcome is not ProjectionOutcome.FULL_PROJECTION:
                    continue
                admission = await authority.admit_projection(
                    result, contributor="analogical_projection")
                if not admission.accepted:
                    logger.info("projection %s->%s declined by authority: %s",
                                source_domain, target_domain, admission.reason)
                    continue
                logger.info("transferred relation %s into %s from %s (candidate %s)",
                            relation_predicate, target_domain, source_domain,
                            admission.rule_id)
                return {"transferred": True, "source_domain": source_domain,
                        "source_rule_id": stored.rule_id, "rule_id": admission.rule_id,
                        "produces": relation_predicate, "mapping": corr}
        return {"transferred": False,
                "reason": "no source domain has a mappable operator producing the relation"}

    async def select_exploration_target(self, explorable_domains, targets) -> Optional[str]:
        """The domain to explore now: among the operator-domains intrinsic
        motivation surfaced and we can explore, the CONTROLLABLE one with the
        highest LEARNING PROGRESS, or None if none qualifies.

        Motivation supplies the candidates (uncertain, worth attention); two
        signals choose among them so the substrate seeks controllable
        information gain rather than raw entropy:
          - CONTROLLABILITY gates: a domain whose outcomes the substrate cannot
            steer (actions inert, or the world moves on its own) is dropped, even
            if it looks uncertain and even if its competence is drifting.
          - LEARNING PROGRESS ranks the rest: competence that is rising is
            productive; stuck (noise) or falling (unlearnable) drops out.
        A fresh domain is optimistic on both and gets tried before it is judged.
        Severing any input still removes exactly its own contribution.
        """
        explorable = set(explorable_domains or ())
        seen, candidates = set(), []
        for target in targets or ():
            domain = self.is_competence_belief(target)
            if domain in explorable and domain not in seen:
                seen.add(domain)
                if await self.controllability(domain) < self.CONTROLLABILITY_FLOOR:
                    continue  # the substrate cannot steer this domain -- skip it
                candidates.append((domain, self.learning_progress(domain)))
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[1], reverse=True)
        domain, progress = candidates[0]
        if progress < self.MIN_LEARNING_PROGRESS:
            return None  # nothing controllable is making progress -- do not chase it
        return domain

    def is_competence_belief(self, target) -> Optional[str]:
        """If an exploration target is a domain-competence belief, the domain it
        is about; else None. Lets the exploration tier pick the operator-domain
        targets out of everything intrinsic motivation surfaces."""
        claim = getattr(target, "claim", None) or (
            getattr(target, "metadata", {}) or {}).get("claim", "")
        prefix = "the substrate has learned the operators of domain "
        if isinstance(claim, str) and claim.startswith(prefix):
            return getattr(target, "domain", None) or claim[len(prefix):]
        return None

    async def learned_domains(self) -> List["Any"]:
        """Every operational domain the substrate has, excluding the DomainType
        categories that share the table."""
        registry = await self._registry()
        return [d for d in registry.domains.values() if self.is_learned_domain(d)]

    async def similar_domains(self, domain_id: str, *, threshold: float = 0.0):
        """Domains most similar to a known one, by concept structure.

        [(Domain, score)] strongest first; [] for an unregistered domain. Each
        domain's signature is computed off the event loop once per content
        version, so a ranking is set arithmetic over cached signatures.
        """
        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        if domain is None:
            return []
        target = await self._signature(registry, domain)
        ranked = []
        for other_id, other in list(registry.domains.items()):
            if other_id == domain_id:
                continue
            score = domain_similarity(target, await self._signature(registry, other))
            if score >= threshold:
                ranked.append((other, score))
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked

    async def _signature(self, registry, domain):
        version = registry.concept_version(domain.domain_id)
        cached = self._signatures.get(domain.domain_id)
        if cached is not None and cached[0] == version:
            return cached[1]
        signature = await asyncio.to_thread(domain_signature, domain)
        if registry.concept_version(domain.domain_id) == version:
            self._signatures[domain.domain_id] = (version, signature)
        return signature

    #: A suggested concept mapping must score above this; at most this many.
    SUGGESTION_THRESHOLD: float = 0.6
    SUGGESTION_LIMIT: int = 10

    async def suggest_mappings(self, source_domain_id: str, target_domain_id: str
                               ) -> List[CrossDomainMapping]:
        """Concept-level correspondences between two domains -- the mapping
        ground truth transfer consumes.

        The strongest concept pairs scoring above SUGGESTION_THRESHOLD, at most
        SUGGESTION_LIMIT, as unvalidated candidates (validated=None). Raises
        UnknownDomain for an unregistered domain.
        """
        registry = await self._registry()
        found = await self._concept_correspondence(
            registry, source_domain_id, target_domain_id,
            threshold=self.SUGGESTION_THRESHOLD, keep=self.SUGGESTION_LIMIT,
            count_all=False)
        return [
            CrossDomainMapping(
                mapping_id=registry._mapping_key(
                    source_domain_id, target_domain_id,
                    source_concept, target_concept, "similarity"),
                source_domain_id=source_domain_id,
                target_domain_id=target_domain_id,
                source_concept_id=source_concept,
                target_concept_id=target_concept,
                mapping_type="similarity",
                strength=score,
                confidence=score * 0.8,
                validated=None,
            )
            for score, source_concept, target_concept in found["strongest"][:self.SUGGESTION_LIMIT]
        ]

    async def structural_similarities(self, source_domain_id: str, target_domain_id: str,
                                      *, threshold: float, keep: int) -> Dict[str, Any]:
        """Every concept pair scoring above `threshold`: how many (`pairs`), their
        summed score (`total`) and the `keep` strongest as
        (score, source_concept_id, target_concept_id)."""
        registry = await self._registry()
        found = await self._concept_correspondence(
            registry, source_domain_id, target_domain_id,
            threshold=threshold, keep=keep, count_all=True)
        return {"source_concepts": found["source_concepts"],
                "target_concepts": found["target_concepts"],
                "pairs": found["pairs"], "total": found["total"],
                "strongest": found["strongest"][:keep]}

    async def concept_similarity(self, source_domain_id: str, source_concept_id: str,
                                 target_domain_id: str, target_concept_id: str) -> float:
        """Similarity of two concepts, each read from the domain holding it."""
        registry = await self._registry()
        concepts = []
        for domain_id, concept_id in ((source_domain_id, source_concept_id),
                                      (target_domain_id, target_concept_id)):
            domain = registry.domains.get(domain_id)
            if domain is None:
                from core.domain.domain_registry import UnknownDomain
                raise UnknownDomain([domain_id], sorted(registry.domains))
            concept = domain.concepts.get(concept_id)
            if concept is None:
                raise LookupError(f"{domain_id} holds no concept {concept_id!r}")
            concepts.append(concept)
        store = await self._vectors_for(concepts)
        rows = np.array([store.index[c.concept_id] for c in concepts], dtype=np.int64)
        src = _build_side(concepts[:1], rows[:1], store.names, store.descriptions,
                          store.name_keys, store.description_keys)
        tgt = _build_side(concepts[1:], rows[1:], store.names, store.descriptions,
                          store.name_keys, store.description_keys)
        structure = concept_structure_table(list(src.group_table), list(tgt.group_table))
        zero = np.zeros(1, dtype=np.int64)
        return float(_exact_pair_scores(src, tgt, structure, zero, zero)[0])

    async def _concept_correspondence(self, registry, source_domain_id: str,
                                      target_domain_id: str, *, threshold: float,
                                      keep: int, count_all: bool) -> Dict[str, Any]:
        """Scored once per content version of the two domains; concurrent callers
        of the same question share one computation."""
        missing = [d for d in (source_domain_id, target_domain_id) if d not in registry.domains]
        if missing:
            from core.domain.domain_registry import UnknownDomain
            raise UnknownDomain(missing, sorted(registry.domains))
        key = (source_domain_id, target_domain_id, threshold, keep, count_all)
        version = (registry.concept_version(source_domain_id),
                   registry.concept_version(target_domain_id))
        cached = self._correspondences.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        running = self._correspondence_runs.get(key)
        if running is None or running[0] != version or running[1].done():
            task = asyncio.create_task(self._compute_correspondence(
                registry, key, version, threshold, keep, count_all))
            running = (version, task)
            self._correspondence_runs[key] = running

            def _finished(done, key=key):
                if self._correspondence_runs.get(key, (None, None))[1] is done:
                    del self._correspondence_runs[key]
            task.add_done_callback(_finished)
        return await asyncio.shield(running[1])

    #: A result keeps this many times `keep` strongest pairs, so concepts can
    #: leave or change without scoring the whole pair again.
    CORRESPONDENCE_DEPTH_FACTOR: int = 4

    async def _compute_correspondence(self, registry, key: tuple, version: tuple,
                                      threshold: float, keep: int,
                                      count_all: bool) -> Dict[str, Any]:
        source_domain_id, target_domain_id = key[0], key[1]
        src = await self._concept_side(registry, registry.domains[source_domain_id])
        tgt = await self._concept_side(registry, registry.domains[target_domain_id])
        depth = keep * self.CORRESPONDENCE_DEPTH_FACTOR
        started = time.monotonic()
        result, how = None, "scored"
        previous = self._correspondences.get(key)
        if previous is not None:
            changed_src = registry.concept_changes(source_domain_id, previous[0][0], version[0])
            changed_tgt = registry.concept_changes(target_domain_id, previous[0][1], version[1])
            if changed_src is not None and changed_tgt is not None:
                result = await asyncio.to_thread(
                    _update_correspondence, previous[1], src, tgt, changed_src,
                    changed_tgt, threshold, depth, count_all)
                if result is not None and not result["complete"] and len(result["strongest"]) < keep:
                    result = None  # too few exact pairs left to answer from
                if result is not None:
                    how = (f"updated for {len(changed_src)}+{len(changed_tgt)} "
                           f"changed concept(s)")
        if result is None:
            result = await asyncio.to_thread(
                _score_correspondence, src, tgt, threshold, depth, count_all)
        elapsed = time.monotonic() - started
        if elapsed >= 1.0:
            logger.info(
                "Concept correspondence %s (%d) -> %s (%d) %s in %.1fs off the "
                "event loop: %s pair(s) above %.2f",
                source_domain_id, len(src.concept_ids), target_domain_id,
                len(tgt.concept_ids), how, elapsed,
                result["pairs"] if count_all else len(result["strongest"][:keep]), threshold)
        if (registry.concept_version(source_domain_id),
                registry.concept_version(target_domain_id)) == version:
            self._correspondences[key] = (version, result)
        return result

    async def _concept_side(self, registry, domain) -> _ConceptSide:
        version = registry.concept_version(domain.domain_id)
        cached = self._sides.get(domain.domain_id)
        if cached is not None and cached[0] == version:
            return cached[1]
        concepts = list(domain.concepts.values())
        store = await self._vectors_for(concepts)
        rows = np.fromiter((store.index[c.concept_id] for c in concepts),
                           dtype=np.int64, count=len(concepts))
        side = await asyncio.to_thread(
            _build_side, concepts, rows, store.names, store.descriptions,
            store.name_keys, store.description_keys)
        if registry.concept_version(domain.domain_id) == version:
            self._sides[domain.domain_id] = (version, side)
        return side

    async def _vectors_for(self, concepts: List[DomainConcept]) -> _ConceptVectorStore:
        """The vector store, holding every one of `concepts` on return.

        Stored vectors are read from unified.concepts; a concept whose vectors
        are not stored yet is encoded and stored first. A concept projected from
        the universal ontology has no row and is encoded in memory. Any other
        concept the registry holds but the table does not is a store
        inconsistency and raises.
        """
        store = self._vectors
        while True:
            wanted = [c for c in concepts if c.concept_id not in store.index]
            if not wanted:
                return store
            db = await self._database()
            by_id = {c.concept_id: c for c in wanted}
            ids = list(by_id)
            found: Set[str] = set()
            pending: List[str] = []
            for k in range(0, len(ids), 5_000):
                part = ids[k:k + 5_000]
                rows = await db.execute_query(
                    """SELECT concept_id, name, description, embedding_model,
                              name_embedding, description_embedding
                       FROM unified.concepts WHERE concept_id = ANY($1::text[])""",
                    (part,), fetch_all=True) or []
                ready = []
                for row in rows:
                    found.add(row["concept_id"])
                    if row["embedding_model"] is None:
                        pending.append(row["concept_id"])
                    else:
                        ready.append((row["concept_id"], row["name"], row["description"],
                                      row["name_embedding"], row["description_embedding"]))
                store.put(ready)
            if pending:
                await self.embed_pending_concepts(pending)
            unstored = [by_id[c] for c in ids if c not in found]
            projected = [c for c in unstored
                         if (c.properties or {}).get("source") == "universal_ontology"]
            if len(projected) != len(unstored):
                strays = [c.concept_id for c in unstored
                          if (c.properties or {}).get("source") != "universal_ontology"]
                raise LookupError(
                    f"{len(strays)} concept(s) held by the domain registry have no "
                    f"unified.concepts row: {strays[:5]}")
            if projected:
                names = [c.name for c in projected]
                descriptions = [c.description for c in projected]
                name_vecs, desc_vecs = await asyncio.to_thread(
                    _encode_concept_texts, names, descriptions)
                store.put([(c.concept_id, c.name, c.description, nv, dv)
                           for c, nv, dv in zip(projected, name_vecs, desc_vecs)])

    #: Concepts encoded and written per round.
    EMBED_BATCH: int = 256

    async def embed_pending_concepts(self, concept_ids: Optional[Sequence[str]] = None) -> int:
        """Encode and store vectors for concepts that have none (embedding_model
        IS NULL), all of them or only `concept_ids`. Returns the number written.

        Encoding runs in a worker thread. A row whose description changed after
        it was read is not written and is read again next round.

        A frozen release is not maintained: it is cut with every concept encoded
        (releases.cut refuses otherwise), so here nothing is encoded or written.
        """
        from pgvector import Vector
        from core.memory.utils.embedding_service import EMBEDDING_MODEL_ID
        db = await self._database()
        if getattr(db, "frozen", False):
            return 0
        scope = sorted({str(c) for c in concept_ids if c}) if concept_ids is not None else None
        if scope is not None and not scope:
            return 0
        written = 0
        unwritten_rounds = 0
        next_report = 25_000
        while True:
            if scope is None:
                rows = await db.execute_query(
                    """SELECT concept_id, name, description FROM unified.concepts
                       WHERE embedding_model IS NULL LIMIT $1""",
                    (self.EMBED_BATCH,), fetch_all=True) or []
            else:
                rows = await db.execute_query(
                    """SELECT concept_id, name, description FROM unified.concepts
                       WHERE embedding_model IS NULL AND concept_id = ANY($1::text[])
                       LIMIT $2""", (scope, self.EMBED_BATCH), fetch_all=True) or []
            if not rows:
                return written
            name_vecs, desc_vecs = await asyncio.to_thread(
                _encode_concept_texts, [r["name"] for r in rows],
                [r["description"] for r in rows])
            from core.agents.memory_agent import memory_agent
            stored = await memory_agent().hold_concept_vectors(
                concept_ids=[r["concept_id"] for r in rows],
                name_vectors=[Vector(v) if v is not None else None for v in name_vecs],
                description_vectors=[Vector(v) if v is not None else None
                                     for v in desc_vecs],
                descriptions=[r["description"] for r in rows],
                model_id=EMBEDDING_MODEL_ID) or []
            self._vectors.discard([r["concept_id"] for r in stored])
            written += len(stored)
            unwritten_rounds = 0 if stored else unwritten_rounds + 1
            if unwritten_rounds >= 3:
                raise RuntimeError(
                    f"concept vectors for {len(rows)} pending concept(s) were encoded "
                    f"but not stored in 3 consecutive rounds "
                    f"(first: {rows[0]['concept_id']}); the rows are changing under "
                    f"the writer or the update does not match them")
            if scope is None and written >= next_report:
                logger.info("Concept embeddings: %d stored so far", written)
                next_report += 25_000

    def start_concept_embedding(self) -> "asyncio.Task":
        """Store vectors for every concept that has none. Runs in the background;
        its failure is logged at ERROR and re-raised inside the task."""
        if self._embedding_backfill is None or self._embedding_backfill.done():
            self._embedding_backfill = asyncio.create_task(
                self._backfill_concept_embeddings(), name="udm-concept-embedding")
        return self._embedding_backfill

    async def _backfill_concept_embeddings(self) -> int:
        try:
            db = await self._database()
            pending = (await db.execute_query(
                "SELECT count(*) AS n FROM unified.concepts WHERE embedding_model IS NULL",
                fetch_all=True))[0]["n"]
            if not pending:
                logger.info("Concept embeddings: every concept has stored vectors")
                return 0
            if getattr(db, "frozen", False):
                logger.warning("Concept embeddings: release %s holds %d concept(s) without "
                               "vectors; a frozen release is not encoded", db.release, pending)
                return 0
            logger.info("Concept embeddings: %d concept(s) have no stored vectors; "
                        "encoding them in the background", pending)
            started = time.monotonic()
            written = await self.embed_pending_concepts()
            logger.info("Concept embeddings: stored vectors for %d concept(s) in %.0fs",
                        written, time.monotonic() - started)
            return written
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Concept embeddings: background encoding failed", exc_info=True)
            raise

    async def concepts_written(self, concept_ids: Sequence[str]) -> None:
        """The concept write path reports what it wrote: the registry re-reads
        those concepts and their text vectors are stored."""
        ids = sorted({str(c) for c in concept_ids if c})
        if not ids:
            return
        registry = await self._registry()
        await registry.refresh_concepts(ids)
        self._vectors.discard(ids)
        await self.embed_pending_concepts(ids)

    async def record_mapping(self, mapping: CrossDomainMapping) -> bool:
        """The one writer of cross-domain mappings; the registry stores them."""
        registry = await self._registry()
        return await registry.add_cross_domain_mapping(mapping)

    async def record_knowledge_transfer(self, transfer) -> bool:
        registry = await self._registry()
        return await registry.create_knowledge_transfer(transfer)

    async def record_mapping_usage(self, mapping_ids: List[str], **usage) -> int:
        registry = await self._registry()
        return await registry.record_mapping_usage(mapping_ids, **usage)

    # ==================================================================
    # DOMAIN DISCOVERY BY CRYSTALLIZATION
    #
    # WHEN a provisional operational domain (a bucket of learned operators under
    # a string domain_id) becomes a first-class Domain is not decided by contact
    # -- minting on contact is how "21 domains for one topic" happened. It is
    # decided by structure: a provisional domain crystallizes when its operators
    # are coherent AND structurally DISTINCT from every domain already known,
    # and MERGES when they are the same structure under a renaming.
    #
    # Distinctness is judged on OPERATOR structure, not concepts, because an
    # explored domain may hold only operators. Predicate NAMES are abstracted
    # away: MOVE(x,a,b) and MOVE_FILE(f,s,d) with the same wiring are the same
    # operator wearing different names -- which is exactly a transfer bridge.
    #
    # The one irreversible mistake is a WRONG MERGE: it destroys a domain's
    # identity. So this is conservative -- it crystallizes unless a merge is
    # positively established, and never the reverse.
    # ==================================================================

    @staticmethod
    def _operator_skeleton(rule) -> Optional[tuple]:
        """A predicate-agnostic structural signature of one learned operator.

        Variables are canonicalized by first appearance (action arguments seed
        the order, so an operator whose variables all come through its action --
        the common case -- is fully canonical). Constants are kept, since they
        constrain structure. Predicate NAMES are dropped: what remains is the
        wiring -- which literal shares which variable with the action and with
        the effects. Two operators that differ only in what their predicates are
        called produce the same skeleton.
        """
        from core.reasoning.unification import is_variable

        action = getattr(rule, "action", None)
        if action is None:
            return None

        order: Dict[str, str] = {}

        def canon(arg: str) -> str:
            if is_variable(arg):
                if arg not in order:
                    order[arg] = f"v{len(order)}"
                return order[arg]
            return f"c:{arg}"

        # Action first, in argument order, to seed the canonical variable names.
        action_sig = (action.arity, tuple(canon(a) for a in action.args))

        def lit(role: str, f) -> tuple:
            return (role, f.arity, tuple(canon(a) for a in f.args))

        body = sorted(lit("PRE", f) for f in rule.body if f != action)
        add = sorted(lit("ADD", f) for f in rule.effects.add)
        dele = sorted(lit("DEL", f) for f in rule.effects.delete)
        return (action_sig, tuple(body), tuple(add), tuple(dele))

    async def _domain_operators(self, domain_id: str) -> List[Any]:
        """The validated, executable operators of an operational domain."""
        from core.learning.rule_store import get_rule_store
        stored = await get_rule_store().executable_rules(domain_id=domain_id)
        return [s.rule for s in stored if getattr(s.rule, "action", None) is not None]

    def _operators_coherent(self, rules: List[Any]) -> bool:
        """The operators form one domain, not unrelated fragments.

        Coherent means their predicates connect: the graph whose nodes are
        operators and whose edges join operators that share any predicate is
        connected. A single operator is trivially coherent. Fragments that share
        nothing are not yet a domain and should keep accumulating before they
        crystallize.
        """
        if len(rules) <= 1:
            return bool(rules)

        def preds(rule) -> set:
            ps = {f.predicate for f in rule.body}
            ps |= {f.predicate for f in rule.effects.add}
            ps |= {f.predicate for f in rule.effects.delete}
            return ps

        pred_sets = [preds(r) for r in rules]
        # union-find over operators sharing a predicate
        parent = list(range(len(rules)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                if pred_sets[i] & pred_sets[j]:
                    parent[find(i)] = find(j)
        return len({find(i) for i in range(len(rules))}) == 1

    def _correspondence(self, source: List[Any], target: List[Any]) -> Optional[Dict[str, str]]:
        """A consistent predicate renaming under which every source operator is
        an existing target operator, or None.

        The sound MERGE criterion: a mapping is returned only when the WHOLE
        source operator set maps onto the target's under one predicate bijection.
        Anything short of that returns None -- the domains are treated as
        distinct, which is the safe error (a wrong merge destroys identity; a
        missed merge only fragments, and a later pass can still merge).

        This is the full-alignment special case of `_partial_correspondence`, so
        the alignment logic lives in exactly one place.
        """
        mapping, aligned = self._partial_correspondence(source, target)
        if mapping and len(aligned) == len(source):
            return mapping
        return None

    def _partial_correspondence(
        self, source: List[Any], target: List[Any]
    ) -> Tuple[Dict[str, str], List[Any]]:
        """The predicate renaming induced by the operators source and target SHARE.

        Aligns every source operator that has a structural (skeleton) match in the
        target, accumulating ONE consistent predicate bijection; source operators
        with no consistent match are left out and reported via `aligned`, so a
        caller can tell shared structure from novel. Unlike a full correspondence
        this does not require the WHOLE source set to map -- which is exactly what
        lets an operator the target LACKS be projected across the mapping its
        shared operators establish (the basis of relation transfer).

        Literals are aligned by their PREDICATE-AGNOSTIC key -- role, arity and
        canonical variable positions -- so AT(v0,v1) aligns with LOC(v0,v1) even
        though the names sort differently; a permutation search finds a consistent
        predicate assignment where a key covers several literals.
        """
        import itertools
        from collections import defaultdict
        from core.reasoning.unification import is_variable

        def canon(rule) -> Dict[str, str]:
            order: Dict[str, str] = {}
            seq = list(rule.action.args)
            for f in sorted(rule.body, key=lambda x: x.arity):
                seq += list(f.args)
            for f in sorted(rule.effects.add, key=lambda x: x.arity):
                seq += list(f.args)
            for f in sorted(rule.effects.delete, key=lambda x: x.arity):
                seq += list(f.args)
            for a in seq:
                if is_variable(a) and a not in order:
                    order[a] = f"v{len(order)}"
            return order

        def keyed(rule):
            order = canon(rule)

            def k(role, f):
                return (role, f.arity,
                        tuple(order.get(a, f"c:{a}") for a in f.args))
            by_key: Dict[tuple, List[str]] = defaultdict(list)
            by_key[k("ACT", rule.action)].append(rule.action.predicate)
            for f in rule.body:
                if f != rule.action:
                    by_key[k("PRE", f)].append(f.predicate)
            for f in rule.effects.add:
                by_key[k("ADD", f)].append(f.predicate)
            for f in rule.effects.delete:
                by_key[k("DEL", f)].append(f.predicate)
            return by_key

        target_by_skel: Dict[tuple, List[Any]] = defaultdict(list)
        for rule in target:
            skel = self._operator_skeleton(rule)
            if skel is not None:
                target_by_skel[skel].append(rule)

        mapping: Dict[str, str] = {}
        inverse: Dict[str, str] = {}

        def align(src, tgt) -> bool:
            s_keys, t_keys = keyed(src), keyed(tgt)
            if set(s_keys) != set(t_keys):
                return False
            if any(len(s_keys[k]) != len(t_keys[k]) for k in s_keys):
                return False
            keys = list(s_keys)

            def backtrack(i, fwd, rev) -> bool:
                if i == len(keys):
                    mapping.update(fwd)
                    inverse.update(rev)
                    return True
                sps, tps = s_keys[keys[i]], t_keys[keys[i]]
                for perm in itertools.permutations(tps):
                    nf, nr, ok = dict(fwd), dict(rev), True
                    for sp, tp in zip(sps, perm):
                        if nf.get(sp, mapping.get(sp)) not in (None, tp):
                            ok = False
                            break
                        if nr.get(tp, inverse.get(tp)) not in (None, sp):
                            ok = False
                            break
                        nf[sp], nr[tp] = tp, sp
                    if ok and backtrack(i + 1, nf, nr):
                        return True
                return False

            return backtrack(0, {}, {})

        aligned: List[Any] = []
        for rule in source:
            skel = self._operator_skeleton(rule)
            if any(align(rule, cand) for cand in target_by_skel.get(skel, [])):
                aligned.append(rule)
        return mapping, aligned

    #: Marker written into a domain's `boundaries` once discovery has DECIDED
    #: about it. Its ABSENCE is what makes a domain provisional.
    CRYSTALLIZED_MARK: str = "crystallized"

    def is_crystallized(self, domain) -> bool:
        """Has discovery already decided about this domain?

        REGISTERED IS NOT DECIDED. `ensure_domain` FILES a bucket so beliefs,
        concepts and exploration have one identity to refer to; it happens on the
        first fact taught. `crystallize` DECIDES whether that bucket is a subject
        of its own or an existing subject re-learned under another name. Those are
        two different acts and conflating them is what made discovery dead code.
        """
        return bool((getattr(domain, "boundaries", None) or {}).get(
            self.CRYSTALLIZED_MARK))

    async def provisional_domains(self) -> List[str]:
        """Operational domains that have validated operators and that discovery
        has not yet DECIDED about -- the candidates for crystallization.

        A provisional domain is a bucket where learning has been accumulating
        under a string domain_id. It becomes a decided domain only once discovery
        rules it a subject of its own or a merge into one.

        THIS PREDICATE USED TO BE `d not in registry.domains` -- "not yet
        registered". That made the whole discovery path unreachable by
        construction, because the learning fan-out calls `ensure_domain(domain)`
        on the FIRST FACT taught, long before any operator is induced in that
        domain. Measured on the live store: every one of the four domains holding
        executable operators was registered BEFORE its first rule existed, so
        `provisional_domains()` returned [] on every wake and `crystallize()` --
        which is what decides new-vs-merge and records cross-domain analogies --
        had never run on a real domain in the substrate's life. Registration is
        not the decision; the absence of the decision is.
        """
        from core.learning.rule_store import get_rule_store
        registry = await self._registry()
        rules = await get_rule_store().executable_rules()
        domain_ids = {r.domain_id for r in rules if getattr(r, "domain_id", None)}
        return sorted(
            d for d in domain_ids
            if not (registry.domains.get(d) is not None
                    and self.is_crystallized(registry.domains[d])))

    async def discover_domains(self, *, limit: int = 8) -> Dict[str, Any]:
        """Crystallize provisional operational domains -- the discovery step,
        meant to run in idle work.

        Each provisional domain is either minted as a new first-class domain or
        merged into an existing one, decided by operator structure. This is the
        substrate's map of subjects growing from what it has actually learned.
        """
        from core.memory import knowledge_ledger as ledger
        outcomes = []
        token = ledger.begin_batch("domain_discovery.operational_sweep")
        try:
            for domain_id in (await self.provisional_domains())[:max(0, int(limit))]:
                try:
                    outcome = await self.crystallize(domain_id)
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(e, "universal_domain_master.discover_domains")
                    logger.error("crystallize(%s) failed: %s", domain_id, e)
                    continue
                outcomes.append(outcome)
                # ONLY A DECISION THAT CHANGED SOMETHING IS AN UPDATE, which is
                # the rule `rule_authority.record_authority_change` already
                # states: "a no-op transition is not an event". `incoherent` and
                # `empty` leave the domain exactly as provisional as it was, so
                # recording them writes a row per sweep about nothing changing --
                # measured, 549 identical `rejected` rows for one domain that
                # simply had not earned a decision yet. The decline is logged;
                # it is not a knowledge update.
                disposition = {
                    "crystallized": ledger.Disposition.NEW,
                    "merged": ledger.Disposition.MERGED,
                }.get(outcome.get("status"))
                if disposition is None:
                    continue
                try:
                    await ledger.record(self.db, ledger.KnowledgeUpdate(
                        subject_kind="domain", subject_id=domain_id,
                        disposition=disposition, domain=domain_id,
                        from_domain=outcome.get("into"),
                        detail=(f"{outcome.get('status')}; "
                                f"operators={outcome.get('operators')} "
                                f"analogies={outcome.get('analogies')}")))
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(
                        e, "universal_domain_master.discover_domains.ledger")
                    logger.warning("decision on %s not recorded: %s", domain_id, e)
        finally:
            ledger.end_batch(token)
        return {
            "examined": len(outcomes),
            "crystallized": sum(1 for o in outcomes if o.get("status") == "crystallized"),
            "merged": sum(1 for o in outcomes if o.get("status") == "merged"),
            "outcomes": outcomes,
        }

    #: The buckets knowledge arrives in when the producer named no subject.
    #: `general` is the default domain across the learning path; `conversation`
    #: is the channel the conversational path teaches into. NEITHER IS A
    #: SUBJECT -- they are holding areas that declarative discovery must split
    #: into subjects, which is precisely what never happened: the idle sweep was
    #: pointed at `conversation` alone (0 concepts on the live store) while
    #: `general` held 82,676 and no scheduled caller ever touched it.
    UNDIFFERENTIATED_CHANNELS: tuple = ("general", "conversation")

    #: Written into a channel domain's `boundaries`: the concept count at the
    #: last taxonomic pass. The walk is over the whole isa graph, so it is run
    #: when the channel has grown enough to possibly yield a new subject, not on
    #: every admitted fact.
    #:
    #: TWO MARKS, NOT ONE, because a survey and a split are not the same event.
    #: Recording a survey under the split's mark would mean that the day
    #: DECLARATIVE_APPLY is turned on, the split is skipped until the channel
    #: grows by another whole floor -- the survey would have silently spent the
    #: budget of the apply that never happened.
    SPLIT_WATERMARK: str = "taxonomic_split_at_count"
    SURVEY_WATERMARK: str = "taxonomic_survey_at_count"

    #: A subject must have more than one kind under it. Below this a root is a
    #: funnel produced by an inverted hypernym, not a field of knowledge.
    SUBJECT_MIN_DIRECT_CHILDREN: int = 2

    #: A taxonomic root needs this many descendants before it is a subject.
    #: Below it, a root is a stray edge rather than a field of knowledge, and
    #: minting a domain for it is how one topic acquired 21.
    TAXONOMIC_DOMAIN_MIN_SIZE: int = 40

    #: How far up an `isa` chain to walk before giving up. Bounded because taught
    #: taxonomy contains cycles (`apple isa car` is well attested in crowd data)
    #: and an unbounded walk would not return.
    TAXONOMIC_WALK_CAP: int = 24

    async def crystallize_taxonomic_domains(
        self, *, from_field: str = "general", min_size: Optional[int] = None,
        limit: int = 0, apply: bool = False,
    ) -> Dict[str, Any]:
        """Split an undifferentiated bucket into subjects USING THE TAXONOMY.

        WHY NOT `discover_concept_domains`. That one groups by CONNECTED
        COMPONENT, which is right for a web of `part_of`/`made_of` edges and
        wrong for a taxonomy: an `isa` hierarchy is connected by construction,
        so every concept reaches every other through a shared ancestor and the
        whole bucket comes back as one cluster. Pointed at the real blob it
        would rename `general` and change nothing.

        Measured on the live store: 174,277 concepts sat in `general` — 57% of
        everything the substrate has been taught — while the idle loop
        crystallized from `conversation`, a bucket of 86. The analogy engine
        reads `unified.concepts` grouped by domain, so more than half the
        knowledge was outside the system that is supposed to carry it between
        subjects, and the boot warning "15/181 domains hold no concepts" was
        literally true while the concepts were all in one heap.

        WHAT A CONCEPT'S DOMAIN IS. The thing it is a kind of. Walking `isa`
        upward to a bounded depth gives 2,156 roots over 352,974 edges, and the
        large ones are real fields — person, activity, physical_tool, clothing,
        measure, group. Nothing is invented and nothing is imported: the subject
        map comes out of the taxonomy the substrate was already taught.

        A root with fewer than `min_size` descendants is left where it is. It is
        a stray edge, not a field, and the honest answer for a concept the
        taxonomy cannot place is that it stays unplaced.

        Reports by default; pass `apply=True` to re-file and register. The
        default is a dry run because this rewrites the domain of every taught
        concept, and a survey is cheap where a mistake is not.
        """
        from collections import defaultdict

        floor = self.TAXONOMIC_DOMAIN_MIN_SIZE if min_size is None else int(min_size)
        if not self.db:
            from core.database import get_database_manager
            self.db = get_database_manager()
            if not self.db.initialized:
                await self.db.initialize()

        import json as _json

        def _norm(value: Any) -> str:
            return "_".join(str(value or "").strip().lower().split())

        from collections import defaultdict as _dd
        parents: Dict[str, set] = _dd(set)

        def _link(child: str, up: str) -> None:
            # EVERY HYPERNYM IS KEPT, because a word has more than one sense and
            # keeping only the first files it under whichever sense happened to
            # be ingested first. Measured: `path` is taught as a kind of way,
            # trail, route, line, continuous_function, string, address AND name
            # — all real senses — and first-parent-wins put it under `name`,
            # whose root is `person`. Not a bad edge; an arbitrary choice
            # between good ones.
            if child and up and child != up:
                parents[child].add(up)

        # TAUGHT TAXONOMY LIVES IN TWO PLACES, and reading one of them finds a
        # fifth of it. Relations promoted to the graph are rows in
        # `concept_relations`; everything else is still on the concept as a
        # `relationships` list — `[["isa", "picture", "positive"]]`. Measured:
        # of 174,277 concepts in `general`, only 24,716 have a row, so reading
        # rows alone left 152,088 unplaced and the split moved almost nothing.
        edges = await self.db.execute_query(
            "SELECT source_concept_id, target_surface FROM unified.concept_relations "
            "WHERE relation = 'isa'", fetch_all=True) or []
        for edge in edges:
            _link(str(edge["source_concept_id"] or "").split(":", 1)[-1],
                  _norm(edge["target_surface"]))

        held = await self.db.execute_query(
            "SELECT name, relationships FROM unified.concepts "
            "WHERE relationships IS NOT NULL", fetch_all=True) or []
        # THIS WALK IS CPU-BOUND AND LONG -- 82,676 concepts over 108,736 isa
        # edges takes minutes. It runs from a coalesced REACTION task, so without
        # yielding it would hold the event loop for the whole sweep and freeze
        # the reactive drain, the coordination loop and every other await in the
        # substrate. Yielding costs nothing and keeps the substrate alive while
        # it thinks about its own subject map.
        for _n, row in enumerate(held):
            if _n % 2000 == 0:
                await asyncio.sleep(0)
            raw = row["relationships"]
            try:
                links = _json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                continue
            for link in links or []:
                if not isinstance(link, (list, tuple)) or len(link) < 2:
                    continue
                relation, target = link[0], link[1]
                polarity = link[2] if len(link) > 2 else "positive"
                # A NEGATED HYPERNYM IS NOT A PARENT. "x is not a y" places
                # nothing, and treating it as placement would file a concept
                # under the one subject it was taught it does not belong to.
                if _norm(relation) == "isa" and str(polarity).lower() != "negative":
                    _link(_norm(row["name"]), _norm(target))

        def roots_of(name: str) -> List[str]:
            """Every subject this concept's hypernym chains reach.

            A taxonomy with several senses per word is a DAG, not a tree, so
            this walks all of it, bounded: taught taxonomy contains cycles
            (`apple isa car` is well attested) and an unbounded walk over a DAG
            with cycles does not return.
            """
            seen = {name}
            found: Dict[str, int] = {}
            frontier, depth = [name], 0
            while frontier and depth < self.TAXONOMIC_WALK_CAP:
                nxt = []
                for node in frontier:
                    up = parents.get(node)
                    if not up:
                        if node != name and node not in found:
                            found[node] = depth
                        continue
                    for parent_name in up:
                        if parent_name not in seen:
                            seen.add(parent_name)
                            nxt.append(parent_name)
                frontier, depth = nxt, depth + 1
            # A chain that hit the cap without terminating still names where it
            # got to; dropping it would lose the concept entirely.
            if found:
                return found
            return {n: depth for n in frontier if n != name}

        rows = await self.db.execute_query(
            "SELECT concept_id, name FROM unified.concepts WHERE domain = $1",
            (from_field,), fetch_all=True) or []

        placed: Dict[str, List[str]] = defaultdict(list)
        spans: Dict[str, List[str]] = defaultdict(list)   # concept -> its subjects
        unplaced = 0
        for _n, row in enumerate(rows):
            if _n % 500 == 0:
                await asyncio.sleep(0)     # see the note on the parents build
            key = _norm(row["name"]) or str(row["concept_id"] or "").split(":", 1)[-1]
            found = roots_of(key) if key in parents else {}
            found = {r: d for r, d in found.items() if r and r != key}
            if not found:
                unplaced += 1
                continue
            # THE HOME IS THE NEAREST SUBJECT -- the closest genus this concept
            # is a kind of. The others are not discarded; they are recorded as
            # MEMBERSHIP, which is what `unified.concept_domains` exists for.
            #
            # IT USED TO BE `max(Counter(found))`, described as "the subject the
            # most of this concept's hypernym chains arrive at". THE COUNTS WERE
            # ALL 1. The walk shares one `seen` set, so each root is appended
            # exactly once no matter how many chains reach it -- which collapses
            # `max(tally, key=lambda r: (tally[r], r))` to `max` over the NAME:
            # the alphabetically last root won every time. Measured: 65,056 of
            # 82,676 concepts filed under `x_linked_recessive` because `x` sorts
            # last; delete that edge and 65,048 moved to `written`, because `w`
            # sorts next. Two different mega-buckets, one arbitrary tie-break.
            # Distance is real evidence and is already in hand from the walk.
            spans[row["concept_id"]] = sorted(found)
            home = min(found, key=lambda r: (found[r], r))
            placed[home].append(row["concept_id"])

        # A root that IS the channel is not a split -- it would re-file the
        # bucket onto itself and register the channel as its own subject. The
        # component-based twin has always had this guard; the taxonomic one
        # did not.
        #
        # AND A FIELD HAS SEVERAL KINDS UNDER IT. A root that the whole bucket
        # reaches through ONE direct child is not a subject, it is a funnel
        # created by a single inverted hypernym -- a genus taught as a kind of
        # its own species. Measured on the live store: `inheritance isa
        # x_linked_recessive` (one row; x_linked_recessive has no parents, so
        # the walk terminates there) made that leaf term the root of 65,056 of
        # 82,676 concepts -- 79% of everything taught -- while every legitimate
        # subject had 9 to 478 direct children. Requiring more than one is what
        # distinguishes a field from a funnel, and it is structural: a field
        # with exactly one kind under it IS that one kind.
        direct_children: Dict[str, set] = _dd(set)
        for _child, _ups in parents.items():
            for _up in _ups:
                direct_children[_up].add(_child)
        subjects = {}
        funnels: List[Dict[str, Any]] = []
        for r, ids in placed.items():
            if len(ids) < floor or r == from_field:
                continue
            if len(direct_children.get(r, ())) < self.SUBJECT_MIN_DIRECT_CHILDREN:
                funnels.append({"root": r, "would_have_taken": len(ids),
                                "direct_children": len(direct_children.get(r, ()))})
                logger.warning(
                    "taxonomic split: %r reached by %d concepts through only %d "
                    "direct child(ren) -- a funnel from an inverted hypernym, "
                    "not a subject; left in %s",
                    r, len(ids), len(direct_children.get(r, ())), from_field)
                continue
            subjects[r] = ids
        ordered = sorted(subjects.items(), key=lambda kv: -len(kv[1]))
        if limit:
            ordered = ordered[:limit]

        outcomes: List[Dict[str, Any]] = []
        for root, concept_ids in ordered:
            outcome = {"domain": root, "concepts": len(concept_ids),
                       "status": "would_crystallize"}
            if apply:
                try:
                    await self.ensure_domain(
                        root, name=root.replace("_", " "),
                        description=(f"Taught concepts that are a kind of "
                                     f"{root.replace('_', ' ')}."))
                    from core.agents.memory_agent import memory_agent
                    await memory_agent().file_concepts(domain=root, concept_ids=concept_ids)
                    # Membership records every sense, through the existing
                    # writer, so a polysemous concept is findable from each
                    # subject it genuinely belongs to rather than only its home.
                    from core.domain.concept_identity import ConceptIdentityService
                    identity = ConceptIdentityService(self.db)
                    for concept_id in concept_ids:
                        for subject in spans.get(concept_id, ()):
                            if len(placed.get(subject, ())) >= floor:
                                try:
                                    await identity.add_membership(
                                        concept_id, subject, source="taxonomy")
                                except Exception:
                                    pass   # never fatal; the home is recorded
                    outcome["status"] = "crystallized"
                    from core.memory import knowledge_ledger as _ledger
                    try:
                        await _ledger.record(self.db, _ledger.KnowledgeUpdate(
                            subject_kind="domain", subject_id=root,
                            disposition=_ledger.Disposition.NEW, domain=root,
                            from_domain=from_field,
                            cause="domain_discovery.taxonomic_split",
                            detail=(f"{len(concept_ids)} concept(s) split out of "
                                    f"{from_field} by isa root")))
                    except Exception as _e:
                        from core.capability import raise_if_structural
                        raise_if_structural(
                            _e, "universal_domain_master.taxonomic_split.ledger")
                        logger.warning("taxonomic subject %s not recorded: %s",
                                       root, _e)
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(e,
                        "universal_domain_master.crystallize_taxonomic_domains")
                    logger.error("could not crystallize %s: %s", root, e)
                    outcome["status"] = f"failed: {type(e).__name__}"
            outcomes.append(outcome)

        return {
            "from_field": from_field, "applied": bool(apply),
            "examined": len(rows),
            "isa_edges": len(edges),
            "roots_found": len(placed),
            "subjects": len(subjects),
            "would_move": sum(len(ids) for _r, ids in ordered),
            "left_unplaced": unplaced,
            "below_floor": sum(len(ids) for r, ids in placed.items()
                               if len(ids) < floor),
            "funnels": funnels,
            "outcomes": outcomes[:20],
        }

    async def discover_concept_domains(self, *, from_field: str = "conversation",
                                       min_size: int = 3,
                                       limit: int = 8) -> Dict[str, Any]:
        """Crystallize DECLARATIVE domains from the concept-relation graph.

        The declarative twin of `discover_domains`. That one mints a domain from
        a coherent bucket of learned OPERATORS; this one from a coherent cluster
        of taught CONCEPTS. Taught facts accumulate as concepts under the CHANNEL
        they arrived through (`conversation`), undifferentiated by subject, so
        nothing about a subject ever separates into its own domain and the
        cross-domain analogy engine -- which reads `unified.concepts` grouped by
        domain -- sees one blob instead of distinct subjects.

        A connected cluster of those concepts (an ISA hierarchy, a web of
        made_of/part_of edges) IS a subject the substrate has been taught. Each
        such cluster of at least `min_size` concepts is crystallized into its own
        domain (named for the cluster's most-connected concept, its hub) via the
        one registration authority `ensure_domain`, and its concepts are re-filed
        under that field -- where crystallization, competence beliefs, and the
        analogy engine can all see it as a distinct subject.

        Coherence is the SAME connected-graph test `_operators_coherent` uses,
        here over concepts joined by a relation rather than operators sharing a
        predicate. A cluster too small to be a subject is left in the channel to
        keep accumulating, never crystallized on one edge.
        """
        import json
        from collections import defaultdict

        if not self.db:
            from core.database import get_database_manager
            self.db = get_database_manager()
            if not self.db.initialized:
                await self.db.initialize()

        rows = await self.db.execute_query(
            "SELECT concept_id, name, relationships FROM unified.concepts "
            "WHERE domain = $1", (from_field,), fetch_all=True) or []
        if not rows:
            return {"examined": 0, "crystallized": 0, "outcomes": [],
                    "note": f"no concepts filed under {from_field!r}"}

        ids = [r["concept_id"] for r in rows]
        idx = {cid: i for i, cid in enumerate(ids)}
        by_name = {r["name"]: r["concept_id"] for r in rows}
        id_to_name = {r["concept_id"]: r["name"] for r in rows}

        parent = list(range(len(ids)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        degree: Dict[str, int] = defaultdict(int)
        targets_of: Dict[str, List[str]] = {}   # concept_id -> related concept names
        for r in rows:
            rels = r["relationships"]
            if isinstance(rels, str):
                try:
                    rels = json.loads(rels or "[]")
                except (ValueError, TypeError):
                    rels = []
            names: List[str] = []
            for rel in (rels or ()):
                if not isinstance(rel, (list, tuple)) or len(rel) < 2:
                    continue
                target = str(rel[1])
                names.append(target)
                # An edge joins two concepts only when BOTH are concepts here --
                # a relation to something not yet taught contributes no cluster.
                if target in by_name and target != r["name"]:
                    parent[find(idx[r["concept_id"]])] = find(idx[by_name[target]])
                    degree[r["name"]] += 1
                    degree[target] += 1
            targets_of[r["concept_id"]] = names

        # Which EXISTING domain (if any) each relation target already lives in.
        # A taught fact whose object is a concept in an already-crystallized
        # subject means this cluster GROWS that subject, rather than minting a
        # new one -- which is what stops incremental teaching from stranding a
        # late concept in the channel after its neighbours crystallized.
        all_targets = sorted({t for ts in targets_of.values() for t in ts})
        name_domain: Dict[str, str] = {}
        if all_targets:
            # Grow only into REAL subject domains. Exclude the `wordnet` bulk
            # dump (the same unreliable import purged from the lexicon): almost
            # every English word has a wordnet concept, so without this a taught
            # cluster whose object happens to be an ordinary word ("bird") would
            # be pulled into that 5k-row junk domain instead of its own subject.
            ext_rows = await self.db.execute_query(
                "SELECT name, domain FROM unified.concepts "
                "WHERE name = ANY($1) AND domain <> $2 AND domain <> 'wordnet'",
                (all_targets, from_field), fetch_all=True) or []
            for er in ext_rows:
                name_domain.setdefault(er["name"], er["domain"])

        # INCOMING links too. A relation runs one way in the store, so a chain
        # taught as "wemp is a snod" files the edge under `wemp`; if `wemp` has
        # already crystallized, `snod` belongs with it even though the edge points
        # AT snod, not from it. Without this a chain crystallized mid-teaching
        # splits: the tail, linked to the head only by incoming edges, mints a
        # second domain. Map each existing-domain concept's targets so a cluster
        # is grown by a link in either direction.
        points_to: Dict[str, set] = defaultdict(set)
        ext_concepts = await self.db.execute_query(
            "SELECT domain, relationships FROM unified.concepts "
            "WHERE domain <> $1 AND domain <> 'wordnet'",
            (from_field,), fetch_all=True) or []
        for er in ext_concepts:
            erels = er["relationships"]
            if isinstance(erels, str):
                try:
                    erels = json.loads(erels or "[]")
                except (ValueError, TypeError):
                    erels = []
            for rel in (erels or ()):
                if isinstance(rel, (list, tuple)) and len(rel) >= 2:
                    points_to[str(rel[1])].add(er["domain"])

        components: Dict[int, List[str]] = defaultdict(list)
        for cid in ids:
            components[find(idx[cid])].append(cid)

        registry = await self._registry()
        outcomes: List[Dict[str, Any]] = []
        refiled: List[str] = []
        for members in components.values():
            # Does this cluster link (either direction) to exactly one existing
            # domain? Outgoing: a member's relation target lives there. Incoming:
            # a concept there points at a member.
            linked = {name_domain[t] for cid in members
                      for t in targets_of.get(cid, ())
                      if name_domain.get(t) and name_domain[t] != from_field}
            linked |= {d for cid in members
                       for d in points_to.get(id_to_name[cid], ())
                       if d != from_field}
            if len(linked) == 1:
                # GROW that subject: attach the cluster to it, whatever its size
                # (a single late concept belongs with the subject it names).
                field = next(iter(linked))
                domain_id = f"domain_{field}"
                await self.ensure_domain(
                    domain_id, name=field.replace("_", " ").title())
                await self._refile_concepts(members, field)
                refiled.extend(members)
                outcomes.append({"domain_id": domain_id, "field": field,
                                 "hub": field, "concepts": len(members),
                                 "grew": True})
                if len(outcomes) >= limit:
                    break
                continue
            if len(members) < min_size:
                continue
            hub = max((id_to_name[c] for c in members),
                      key=lambda n: degree.get(n, 0))
            field = hub.strip().lower().replace(" ", "_")
            if not field or field == from_field:
                continue
            domain_id = f"domain_{field}"
            await self.ensure_domain(domain_id,
                                     name=hub.replace("_", " ").title())
            # Re-file the cluster's concepts under their subject's field, where
            # the analogy engine groups them as a distinct subject.
            await self._refile_concepts(members, field)
            refiled.extend(members)
            outcomes.append({"domain_id": domain_id, "field": field,
                             "hub": hub, "concepts": len(members)})
            if len(outcomes) >= limit:
                break

        # The registry re-reads exactly the re-filed concepts, so the new
        # membership is live for reasoning and transfer immediately.
        if outcomes:
            await registry.refresh_concepts(refiled)
            # Declarative knowledge coverage: now that each domain holds its
            # concepts, set how well-developed its knowledge is from the graph.
            for o in outcomes:
                o["maturity"] = await self.update_knowledge_coverage(o["domain_id"])

        return {"examined": len(components), "crystallized": len(outcomes),
                "outcomes": outcomes}

    async def _channel_concept_count(self, channel: str) -> int:
        if not self.db:
            from core.database import get_database_manager
            self.db = get_database_manager()
        rows = await self.db.execute_query(
            "SELECT count(*) n FROM unified.concepts WHERE domain = $1",
            (channel,))
        return int(rows[0]["n"]) if rows else 0

    def _watermark_key(self, applied: bool) -> str:
        return self.SPLIT_WATERMARK if applied else self.SURVEY_WATERMARK

    async def _split_watermark(self, channel: str,
                               applied: Optional[bool] = None) -> Optional[int]:
        registry = await self._registry()
        domain = registry.domains.get(channel)
        if domain is None:
            return None
        key = self._watermark_key(self.DECLARATIVE_APPLY if applied is None else applied)
        mark = (getattr(domain, "boundaries", None) or {}).get(key)
        return int(mark) if isinstance(mark, (int, float)) else None

    async def _record_split_watermark(self, channel: str, count: int,
                                      applied: Optional[bool] = None) -> None:
        registry = await self._registry()
        domain = registry.domains.get(channel)
        if domain is None:
            return
        key = self._watermark_key(self.DECLARATIVE_APPLY if applied is None else applied)
        boundaries = dict(getattr(domain, "boundaries", None) or {})
        boundaries[key] = int(count)
        domain.boundaries = boundaries
        await registry.register_domain(domain)

    #: Whether the automatic sweep may APPLY a declarative split -- either
    #: splitter -- which rewrites the `domain` of every concept it places.
    #:
    #: OFF, and the reason is measured twice over, not cautious.
    #:
    #: THE TAXONOMIC SPLITTER. With placement corrected it produces 74 subjects
    #: over 10,277 concepts -- but a large share of those subjects are adjectives
    #: and past participles taught as genera: `cooked`, `assessed`, `emitted`,
    #: `written`, `artificial`, `added`. That is an UPSTREAM reading defect (a
    #: premodifier taken as the hypernym, the same family as a postmodified
    #: subject read as the head), and the substrate's own word classes cannot
    #: separate them -- asked directly, `cooked` comes back NOUN 4 / ADJECTIVE 1
    #: and `written` NOUN 6 / ADJECTIVE 1.
    #:
    #: THE COMPONENT SPLITTER IS WORSE HERE, and this was measured the hard way:
    #: pointed at `general` it moved 78,978 of 82,676 concepts into a single
    #: "subject" named `city` -- its highest-degree hub -- and minted `also`,
    #: `his`, `so`, `later`, `capable`, `supreme` and `extensively` as domains
    #: from other hubs. `crystallize_taxonomic_domains`' own docstring predicts
    #: exactly this: connected-component grouping is right for a web of
    #: part_of/made_of edges and WRONG for an `isa` hierarchy, which is connected
    #: by construction, so the whole bucket comes back as one cluster and the
    #: "split" is a rename. That run was reverted.
    #:
    #: So the sweep SURVEYS and logs the subject map on every wake, and writes
    #: nothing, until the taught taxonomy is sound. A direct caller with a small,
    #: genuinely relational channel (DOM-KG-01's `conversation`) still applies --
    #: this gate is on the automatic sweep over the undifferentiated channels,
    #: which is where the damage was done.
    DECLARATIVE_APPLY: bool = False

    async def discover_taught_domains(self) -> Dict[str, Any]:
        """Split every undifferentiated CHANNEL into the subjects it holds.

        The declarative half of discovery, over the buckets knowledge actually
        arrives in rather than one hardcoded channel name. Two splitters, each
        on the structure it is right for and both already owned by this
        authority:

          * `crystallize_taxonomic_domains` -- groups by `isa` root. Right for a
            taught taxonomy, which is connected by construction and which the
            component splitter would return as one cluster.
          * `discover_concept_domains` -- groups by connected component over
            `part_of`/`made_of`/etc. Right for a relational web.

        THE TAXONOMIC SPLITTER HAD NO CALLER ANYWHERE IN THE CODEBASE. It was
        written against a measurement of this exact defect and then never
        scheduled, so the only subjects it ever produced were from a hand run.
        This is its caller.

        The taxonomic walk covers the whole `isa` graph, so it runs when a
        channel has grown by at least one subject-floor since its last split --
        not on every admitted fact. Below the floor a channel cannot yield a
        subject at all, so there is nothing to do.
        """
        from core.memory import knowledge_ledger as ledger
        token = ledger.begin_batch("domain_discovery.declarative_sweep")
        try:
            return await self._discover_taught_domains()
        finally:
            ledger.end_batch(token)

    async def _discover_taught_domains(self) -> Dict[str, Any]:
        results: Dict[str, Any] = {"channels": {}}
        for channel in self.UNDIFFERENTIATED_CHANNELS:
            count = await self._channel_concept_count(channel)
            entry: Dict[str, Any] = {"concepts": count}
            if count >= self.TAXONOMIC_DOMAIN_MIN_SIZE:
                last = await self._split_watermark(channel)
                due = last is None or (count - last) >= self.TAXONOMIC_DOMAIN_MIN_SIZE
                entry["taxonomic_due"] = due
                if due:
                    taxonomic = await self.crystallize_taxonomic_domains(
                        from_field=channel, apply=self.DECLARATIVE_APPLY)
                    entry["taxonomic"] = {
                        "applied": self.DECLARATIVE_APPLY,
                        "subjects": taxonomic.get("subjects"),
                        "moved": taxonomic.get("would_move"),
                        "unplaced": taxonomic.get("left_unplaced"),
                        "funnels_rejected": len(taxonomic.get("funnels") or []),
                    }
                    if not self.DECLARATIVE_APPLY:
                        logger.info(
                            "taxonomic survey of %s: %d subject(s) over %d "
                            "concept(s), %d funnel(s) rejected -- NOT applied "
                            "(DECLARATIVE_APPLY is off; see its note)",
                            channel, taxonomic.get("subjects") or 0,
                            taxonomic.get("would_move") or 0,
                            len(taxonomic.get("funnels") or []))
                    await self._record_split_watermark(
                        channel, await self._channel_concept_count(channel))
            # THE COMPONENT SPLITTER HAS NO SURVEY MODE -- it re-files as it
            # goes -- so while the gate is shut it is not called at all here.
            # Calling it "to see what it would do" IS doing it; that is how
            # 78,978 concepts were renamed to `city`.
            if self.DECLARATIVE_APPLY:
                try:
                    component = await self.discover_concept_domains(from_field=channel)
                    entry["component"] = {
                        "examined": component.get("examined"),
                        "crystallized": component.get("crystallized"),
                    }
                except Exception as e:
                    from core.capability import raise_if_structural
                    raise_if_structural(e,
                        "universal_domain_master.discover_taught_domains")
                    logger.error("component split of %s failed: %s", channel, e)
            else:
                entry["component"] = {"applied": False,
                                      "reason": "DECLARATIVE_APPLY is off"}
            results["channels"][channel] = entry
        results["crystallized"] = sum(
            (int((c.get("taxonomic") or {}).get("subjects") or 0)
             if (c.get("taxonomic") or {}).get("applied") else 0)
            + int((c.get("component") or {}).get("crystallized") or 0)
            for c in results["channels"].values())
        results["surveyed_subjects"] = sum(
            int((c.get("taxonomic") or {}).get("subjects") or 0)
            for c in results["channels"].values())
        return results

    async def _refile_concepts(self, concept_ids: List[str], field: str) -> None:
        """Move concepts into a subject, AND SAY SO.

        THIS WAS A BARE UPDATE, and it is the reason a sweep that moved 78,978
        concepts out of `general` into an invented subject could not be
        attributed afterwards. There was no envelope, no membership row and no
        disposition -- the only trace was `unified.concepts.updated_at`, so
        establishing who had done what meant grouping bulk UPDATEs by microsecond
        and reading concept names to guess. Two records are written now, neither
        a new account of provenance:

          * MEMBERSHIP, through `ConceptIdentityService`, which owns
            `unified.concept_domains`. Writing the `domain` column here while
            that table went untouched was two writers for one fact.
          * A `moved` KNOWLEDGE UPDATE per concept, carrying the domain it left,
            under the batch its caller opened -- so the burst has one
            originating cause instead of N unattributed rows.
        """
        ids = list(concept_ids)
        if not ids:
            return
        # WHERE IT CAME FROM, read before the move. Afterwards it is unknowable,
        # which is exactly the position today's incident left the store in.
        before = {r["concept_id"]: r["domain"] for r in await self.db.execute_query(
            "SELECT concept_id, domain FROM unified.concepts "
            "WHERE concept_id = ANY($1::text[])", (ids,), fetch_all=True) or []}
        from core.agents.memory_agent import memory_agent
        await memory_agent().refile_concepts(domain=field, concept_ids=ids)
        from core.memory import knowledge_ledger as ledger
        try:
            from core.domain.concept_identity import ConceptIdentityService
            identity = ConceptIdentityService(self.db)
            for concept_id in ids:
                await identity.add_membership(concept_id, field, source="refile")
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "universal_domain_master._refile_concepts")
            logger.warning("membership for the refile into %s not recorded: %s",
                           field, error)
        try:
            await ledger.record_many(self.db, [
                ledger.KnowledgeUpdate(
                    subject_kind="concept", subject_id=cid,
                    disposition=ledger.Disposition.MOVED,
                    domain=field, from_domain=before.get(cid),
                    detail="refiled by declarative domain discovery")
                for cid in ids])
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "universal_domain_master._refile_concepts.ledger")
            logger.warning("knowledge updates for the refile into %s not "
                           "recorded: %s", field, error)

    async def update_knowledge_coverage(self, domain_id: str) -> float:
        """Set a domain's `maturity_score` from the DEVELOPMENT of its concept
        graph -- the declarative-knowledge-coverage signal.

        `maturity_score` means "how well-developed the domain knowledge is" and
        was written once at 0.1 and never moved again; `structural_complexity`
        already computes exactly that from the graph (size, connectedness,
        relational variety) but was used only inside domain similarity. This
        connects the two: as a taught domain's concept graph grows, its coverage
        rises, persisted so it survives a restart. It is SEPARATE from operator
        competence (`record_competence_evidence`, earned by acting): this
        measures what the substrate KNOWS about a domain, not what it can DO in
        it -- so a taught domain can be knowledge-rich and operator-empty, and
        the two never contaminate each other (the credit invariant holds).
        """
        from core.domain.domain_types import coverage_from_counts
        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        if domain is None:
            return 0.0

        # MEASURED FROM THE STORE, which is what actually holds a taught domain.
        # This read `structural_complexity(domain)`, which counts the registry
        # object's in-memory `concepts` dict -- and teaching never fills it: a
        # taught fact goes to `unified.concepts` with a `domain` column. So every
        # taught domain measured 0.0 however much it held. Measured directly:
        # six facts taught into a fresh domain, and remeasuring moved its
        # maturity from 0.1 DOWN to 0.0.
        if not self.db:
            from core.database import get_database_manager
            self.db = get_database_manager()
        # BY EVERY SPELLING OF THE DOMAIN, because a domain has two and this
        # query used only one. A declarative domain is registered as
        # `domain_<field>` while its concepts are re-filed under the bare
        # `<field>` -- which `DomainRegistry._domain_key` documents as "the
        # spelling unified.* columns use". So counting `WHERE domain =
        # 'domain_glindar'` found ZERO of the concepts that had just been filed
        # under `glindar`, and every crystallized declarative domain measured 0.0
        # coverage however much it held. An operational domain (`warehouse`,
        # `kite17`) has no prefix, so both spellings are the same string and the
        # set collapses to one.
        keys = sorted({domain_id, registry._domain_key(domain_id)})
        rows = await self.db.execute_query(
            """SELECT
                   (SELECT count(*) FROM unified.concepts
                     WHERE domain = ANY($1::text[])) AS concepts,
                   (SELECT count(*) FROM unified.concept_relations r
                      JOIN unified.concepts c ON c.concept_id = r.source_concept_id
                     WHERE c.domain = ANY($1::text[])) AS edges,
                   (SELECT count(DISTINCT r.relation) FROM unified.concept_relations r
                      JOIN unified.concepts c ON c.concept_id = r.source_concept_id
                     WHERE c.domain = ANY($1::text[])) AS kinds""",
            (keys,))
        if not rows:
            return domain.maturity_score
        row = rows[0]
        held = int(row["concepts"] or 0)
        links = int(row["edges"] or 0)
        kinds = int(row["kinds"] or 0)

        # THE LANGUAGE DOMAIN'S KNOWLEDGE IS ITS CONSTRUCTIONS. How English says
        # things is held in memory as taught constructions, not as concepts
        # filed under `english`, so counting concepts alone measured English at
        # zero however much of it had been taught (measured 2026-09-27: nine
        # taught patterns, a domain record reading nothing). Memory is asked the
        # same way the language view is warmed (`taught_patterns`): each
        # construction is a unit of what is known; each fact a meaning states,
        # and each link between a slot and its filler, is a link; the link kinds
        # the facts use are its relational variety.
        from core.semantics.derived_reader import ENGLISH_DOMAIN, Link, Pattern
        if domain_id == ENGLISH_DOMAIN:
            from core.memory import get_memory_agent
            items = await (await get_memory_agent()).taught_patterns()
            patterns = [i for i in items if isinstance(i, Pattern)]
            held += sum(1 for i in items if not isinstance(i, Link))
            links += (sum(len(p.meaning.facts) for p in patterns)
                      + sum(1 for i in items if isinstance(i, Link)))
            kinds += len({f.relation for p in patterns for f in p.meaning.facts})

        domain.maturity_score = coverage_from_counts(held, links, kinds)
        await registry._persist_domain(domain)

        # THIS FACULTY JUST CONSUMED THAT DOMAIN'S KNOWLEDGE. It read the
        # concepts admitted there and turned them into a coverage score, which
        # is a real downstream use, not the admission repeating itself -- it
        # runs from the EVIDENCE_ADMITTED reaction, after the fact is already in.
        # Drained only after the score is durably persisted, for the same reason
        # the planning engine drains authority events last: marking first would
        # let a crash lose the event while the work looks done.
        try:
            from core.memory import knowledge_ledger as ledger
            pending = await ledger.pending_updates(
                self.db, consumer="domain_coverage", domain=domain_id,
                subject_kind="proposition")
            if pending:
                await ledger.mark_consumed(
                    self.db, [p["update_id"] for p in pending], "domain_coverage")
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(
                error, "universal_domain_master.update_knowledge_coverage.ledger")
            logger.debug("knowledge updates for %s not drained: %s", domain_id, error)
        return domain.maturity_score

    async def detect_knowledge_gap(self, domain_id: str, subject: str,
                                   relation: str, *, owner: Optional[str] = None):
        """Localize a DECLARATIVE knowledge gap in a domain and register it as a
        known-unknown -- the declarative twin of a CONCEPT_GAP.

        A domain can be MATURE (a rich concept graph, high knowledge coverage) and
        still be MISSING a specific fact: an in-domain question -- "what does
        <subject> <relation>?" -- the graph cannot answer because that relation was
        never taught about that subject. That is the substrate having LITTLE
        INFORMATION here, which is a different thing from LACKING THE OPERATORS to
        act here. This registers it as a KNOWN_UNKNOWN scoped to the domain (the
        epistemic system's account of what the substrate knows it does not know,
        resolvable by ACQUISITION -- research or teaching -- not by exploring for an
        operator), and it deliberately does NOT touch the domain's operator
        competence belief. A knowledge gap is never recorded as a competence loss;
        the two axes stay orthogonal, which is what lets the substrate answer "I
        don't have that fact yet" instead of "I am not competent in this domain".

        Returns the KnownUnknown, or None when there is no localized gap here: the
        subject is not a concept of this domain (a different question entirely), or
        the relation is already present (no gap to register).

        `owner` is whose question raised it: a person's is kept in their context,
        not among the substrate's own open questions (bayesian_uncertainty, S3).
        """
        held = await self.holds_relation(domain_id, subject, relation)
        if held is None:
            return None                     # no such domain, or not an in-domain subject
        if held:
            return None                     # the relation is present -- not a gap

        # A localized declarative gap. Register it; competence is untouched.
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        return unc.register_known_unknown(
            question=f"what does {subject} {relation}?",
            domain=domain_id,
            blocking_factors=[
                f"the relation {relation!r} is unrepresented for {subject!r} "
                f"in {domain_id} (a knowledge gap, not an operator gap)"],
            required_info=[f"{subject} {relation} <?>"],
            target={"kind": "relation", "subject": subject, "relation": relation},
            owner=owner)

    async def holds_relation(self, domain_id: str, subject: str,
                             relation: str) -> Optional[bool]:
        """Whether this domain's concept `subject` carries `relation` -- the one
        test a declarative gap is detected by (False) and closed by (True).
        None when the domain does not exist or `subject` is not one of its
        concepts: not a question this domain can answer either way."""
        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        if domain is None:
            return None
        concept = next((c for c in domain.concepts.values() if c.name == subject),
                       None)
        if concept is None:
            return None
        relationships = (concept.properties or {}).get("relationships") or []
        return any(isinstance(r, (list, tuple)) and r and str(r[0]) == relation
                   for r in relationships)

    async def has_domain(self, domain_id: str) -> bool:
        """Whether the substrate holds `domain_id` as a domain."""
        registry = await self._registry()
        return registry.domains.get(domain_id) is not None

    async def concept_names(self, domain_id: str) -> List[str]:
        """The names of this domain's concepts (empty when there is no such
        domain)."""
        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        return [c.name for c in domain.concepts.values()] if domain else []

    async def knowledge_sparsity_map(self, domain_id: str) -> Dict[str, Any]:
        """WHICH regions of a domain are thin — the localized complement of the
        single global `maturity_score`.

        `structural_complexity` reports one number for the whole domain;
        `detect_knowledge_gap` answers about one specific fact. This sits between:
        it ranks the domain's concepts by their connectivity (degree = relations
        the concept participates in, in either direction), so the SPARSE concepts
        — low degree, typically leaves reached by a single edge — surface as the
        regions where knowledge is thinnest and a gap most likely sits. It is the
        map a proactive acquisition step would read to decide WHERE to ask next.
        A concept's degree is a measurement of knowledge density around it, not a
        competence claim: a sparse region means "little is held here", never "the
        substrate cannot act here".
        """
        from collections import defaultdict

        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        if domain is None:
            return {"domain_id": domain_id, "error": "unknown domain"}
        concepts = domain.concepts
        if not concepts:
            return {"domain_id": domain_id, "concepts": 0, "sparse_concepts": [],
                    "sparsest": [], "mean_degree": 0.0,
                    "maturity": domain.maturity_score}

        incoming: Dict[str, int] = defaultdict(int)
        for c in concepts.values():
            for target in (c.related_concepts or ()):
                incoming[str(target)] += 1

        rows: List[Dict[str, Any]] = []
        for c in concepts.values():
            out_deg = len(c.related_concepts or ())
            in_deg = incoming.get(c.name, 0)
            rows.append({"concept": c.name, "degree": out_deg + in_deg,
                         "out": out_deg, "in": in_deg})
        rows.sort(key=lambda r: (r["degree"], r["concept"]))

        degrees = [r["degree"] for r in rows]
        mean = sum(degrees) / len(degrees)
        # Thin = strictly below the mean degree (at least the leaves), so the
        # threshold is the domain's own distribution, never a tuned constant.
        threshold = max(1.0, mean)
        sparse = [r["concept"] for r in rows if r["degree"] < threshold]
        return {"domain_id": domain_id, "concepts": len(concepts),
                "mean_degree": round(mean, 2),
                "sparsest": rows[:5],
                "sparse_concepts": sparse,
                "maturity": domain.maturity_score}

    async def crystallize(self, provisional_domain_id: str) -> Dict[str, Any]:
        """Decide whether a provisional operational domain is new or already
        known, and act on it.

        Returns a decision: 'crystallized' (registered as a new first-class
        domain), 'merged' (its operators are an existing domain's under a
        recorded predicate correspondence), 'incoherent' (its operators do not
        yet form one domain), or 'empty'/'already_registered'.
        """
        registry = await self._registry()
        # ALREADY DECIDED, not merely already filed. A registered-but-undecided
        # domain is exactly what this function exists to rule on, so registration
        # can no longer short-circuit it.
        existing = registry.domains.get(provisional_domain_id)
        if existing is not None and self.is_crystallized(existing):
            return {"status": "already_crystallized",
                    "domain_id": provisional_domain_id}

        rules = await self._domain_operators(provisional_domain_id)
        if not rules:
            return {"status": "empty", "domain_id": provisional_domain_id}

        if not self._operators_coherent(rules):
            return {"status": "incoherent", "domain_id": provisional_domain_id,
                    "operators": len(rules)}

        # Compare against every registered LEARNED domain's operators. A
        # registered domain with no operators (a DomainType category) offers
        # nothing to match and is skipped.
        #
        # A correspondence that is the IDENTITY -- every predicate maps to
        # itself -- means the same vocabulary, so this is the same subject
        # re-learned or extended under a different id: MERGE. A correspondence
        # that RENAMES predicates means the same STRUCTURE over a different
        # vocabulary: that is an ANALOGY between two distinct subjects (movement
        # and warehouse logistics share the shape of "a thing moves along a
        # link"), and merging them would destroy the distinction. Those become
        # transfer bridges on a domain that still crystallizes as its own.
        analogies: List[tuple] = []
        for other in await self.learned_domains():
            # NEVER AGAINST ITSELF. A candidate is registered (that is what
            # `ensure_domain` does on the first fact taught) and so appears in
            # `learned_domains()`; its correspondence with itself is trivially
            # the identity, which reads as "the same subject re-learned" and
            # merged the domain into itself. Invisible while `provisional` meant
            # "unregistered", because then the candidate could not be in this
            # list at all.
            if other.domain_id == provisional_domain_id:
                continue
            target = await self._domain_operators(other.domain_id)
            if not target:
                continue
            correspondence = self._correspondence(rules, target)
            if correspondence is None:
                continue
            if all(k == v for k, v in correspondence.items()):
                await self._record_domain_correspondence(
                    provisional_domain_id, other.domain_id, correspondence)
                logger.info("crystallize: %s is %s (same vocabulary) -- merged",
                            provisional_domain_id, other.domain_id)
                await self._mark_crystallized(provisional_domain_id,
                                              merged_into=other.domain_id)
                return {"status": "merged", "domain_id": provisional_domain_id,
                        "into": other.domain_id, "correspondence": correspondence}
            analogies.append((other.domain_id, correspondence))

        # No same-vocabulary match: a new domain. Record any structural
        # analogies as transfer bridges, then crystallize it as its own.
        domain = await self.ensure_domain(provisional_domain_id)
        for other_id, correspondence in analogies:
            await self._record_domain_correspondence(
                provisional_domain_id, other_id, correspondence)
        if analogies:
            logger.info("crystallize: %s is new, analogous to %s",
                        provisional_domain_id, [o for o, _ in analogies])
        await self._mark_crystallized(provisional_domain_id)
        return {"status": "crystallized", "domain_id": provisional_domain_id,
                "domain_type": domain.domain_type.value, "operators": len(rules),
                "analogies": [o for o, _ in analogies]}

    async def _mark_crystallized(self, domain_id: str, *,
                                 merged_into: Optional[str] = None) -> None:
        """Record that discovery has DECIDED about this domain.

        Without this the decision is not durable and every sweep re-decides the
        same domains forever -- re-recording correspondences and re-logging. The
        mark lives in `boundaries`, which the registry serialises into
        `unified.domains.metadata` and rebuilds on load, so the decision survives
        a restart. Written through `register_domain`, the one persistence
        authority, never a second UPDATE of the same row.
        """
        registry = await self._registry()
        domain = registry.domains.get(domain_id)
        if domain is None:
            return
        boundaries = dict(getattr(domain, "boundaries", None) or {})
        boundaries[self.CRYSTALLIZED_MARK] = datetime.now().isoformat()
        if merged_into:
            boundaries["merged_into"] = merged_into
        domain.boundaries = boundaries
        await registry.register_domain(domain)

    async def _record_domain_correspondence(
        self, source_domain: str, target_domain: str, mapping: Dict[str, str]) -> None:
        """Persist that one domain's operators are another's under a predicate
        renaming -- the transfer bridge a merge produces."""
        if not self.db:
            return
        from core.agents.memory_agent import memory_agent
        await memory_agent().hold_domain_correspondence(
            mapping_id=f"opcorr_{source_domain}_{target_domain}",
            source_domain=source_domain, target_domain=target_domain,
            source_concept=source_domain, target_concept=target_domain,
            similarity_score=1.0, reasoning_strategy=ReasoningStrategy.ANALOGICAL.value,
            verified=True, confidence=1.0,
            metadata=json.dumps({"kind": "operator_correspondence", "mapping": mapping}))

    async def execute_cross_domain_query(
        self,
        query: CrossDomainQuery
    ) -> DomainIntegrationResult:
        """
        Execute cross-domain query

        Finds relationships and mappings between concepts across
        multiple knowledge domains using the specified reasoning strategy.
        """
        start_time = datetime.now()
        self.stats['total_queries'] += 1

        logger.info(
            f"Executing cross-domain query: {query.query_text[:100]}... "
            f"(strategy: {query.reasoning_strategy.value})"
        )

        try:
            # Find mappings between source and target domains
            mappings = await self._find_cross_domain_mappings(
                query.source_domains,
                query.target_domains,
                query.reasoning_strategy,
                query.min_similarity
            )

            # Generate insights
            insights = await self._generate_insights(mappings, query)

            # Generate explanations if requested
            explanations = []
            if query.include_explanations:
                explanations = await self._generate_explanations(mappings, query)

            # Calculate execution time
            execution_time = (datetime.now() - start_time).total_seconds()

            # Store query record
            await self._store_query_record(query, mappings, execution_time, success=True)

            self.stats['successful_queries'] += 1

            result = DomainIntegrationResult(
                query_id=query.query_id,
                success=True,
                mappings=mappings,
                insights=insights,
                explanations=explanations,
                execution_time=execution_time,
                domains_queried=len(query.source_domains) + len(query.target_domains),
                mappings_found=len(mappings)
            )

            logger.info(
                f"✓ Cross-domain query completed: {len(mappings)} mappings found "
                f"in {execution_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Cross-domain query failed: {e}")
            self.stats['failed_queries'] += 1

            execution_time = (datetime.now() - start_time).total_seconds()

            return DomainIntegrationResult(
                query_id=query.query_id,
                success=False,
                error=str(e),
                execution_time=execution_time
            )

    def _resolve_references(self, registry, refs, *, rank_against: Optional[str] = None):
        """Domain references -> canonical registry fields holding concepts.

        Either level resolves: a field names itself, a DomainType category
        expands to its member fields, exact match winning. The fan-out is bounded
        by MAX_RESOLVED_FIELDS and the resolver logs what it drops.
        """
        from core.domain.domain_registry import UnresolvedDomainReference
        out, seen = [], set()
        for ref in refs:
            name = ref.value if isinstance(ref, DomainType) else str(ref)
            try:
                resolved = registry.resolve_domain_reference(
                    name, require_concepts=True,
                    max_targets=self.MAX_RESOLVED_FIELDS, rank_against=rank_against)
            except UnresolvedDomainReference as e:
                logger.warning("Skipping unresolved domain reference: %s", e)
                continue
            for rd in resolved:
                if rd.domain_id not in seen:
                    seen.add(rd.domain_id)
                    out.append(rd)
        return out

    async def _find_cross_domain_mappings(
        self,
        source_domains: List[DomainType],
        target_domains: List[DomainType],
        strategy: ReasoningStrategy,
        min_similarity: float
    ) -> List[DomainMapping]:
        """Mappings between the domains a query names, for one strategy.

        Each reference resolves to fields. For every field pair the reasoner
        generates candidates once per content version of the two fields and
        they are stored; the answer is everything stored for that pair and
        strategy that is not refuted. `mapping_cache` holds the answer per
        reference pair of the latest query.
        """
        registry = await self._registry()
        mappings: List[DomainMapping] = []
        seen: Set[str] = set()
        for source_ref in source_domains:
            for target_ref in target_domains:
                answered: List[DomainMapping] = []
                for source in self._resolve_references(registry, [source_ref]):
                    for target in self._resolve_references(
                            registry, [target_ref], rank_against=source.domain_id):
                        if source.domain_id == target.domain_id:
                            continue
                        answered.extend(await self._pair_mappings_for(
                            registry, source, target, strategy, min_similarity))
                self.mapping_cache[(source_ref, target_ref)] = answered
                for mapping in answered:
                    if mapping.mapping_id not in seen:
                        seen.add(mapping.mapping_id)
                        mappings.append(mapping)
        return mappings

    async def _pair_mappings_for(self, registry, source, target,
                                 strategy: ReasoningStrategy,
                                 min_similarity: float) -> List[DomainMapping]:
        key = (source.domain_id, target.domain_id, strategy, min_similarity)
        version = (registry.concept_version(source.domain_id),
                   registry.concept_version(target.domain_id))
        cached = self._pair_mappings.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        await self._generate_mappings(registry, source, target, strategy, min_similarity)
        db = await self._database()
        rows = await db.execute_query(
            """SELECT mapping_id, source_domain, target_domain, source_concept,
                      target_concept, similarity_score, reasoning_strategy,
                      verified, confidence
               FROM unified.domain_mappings
               WHERE source_domain = $1 AND target_domain = $2
                 AND reasoning_strategy = $3
                 AND similarity_score >= $4
                 -- verified IS NULL  = candidate, never ontologically judged
                 -- verified IS TRUE  = accepted knowledge
                 -- verified IS FALSE = rejected; must never be returned
                 AND (verified IS NULL OR verified IS TRUE)
               ORDER BY similarity_score DESC, mapping_id""",
            (registry._domain_key(source.domain_id), registry._domain_key(target.domain_id),
             strategy.value, min_similarity),
            fetch_all=True) or []
        found = [
            DomainMapping(
                mapping_id=row['mapping_id'],
                source_domain=row['source_domain'],
                target_domain=row['target_domain'],
                source_concept=row['source_concept'],
                target_concept=row['target_concept'],
                similarity_score=row['similarity_score'],
                reasoning_strategy=strategy,
                verified=row['verified'],
                confidence=row['confidence'],
            )
            for row in rows
        ]
        if (registry.concept_version(source.domain_id),
                registry.concept_version(target.domain_id)) == version:
            self._pair_mappings[key] = (version, found)
        return found

    async def _generate_mappings(self, registry, source, target,
                                 strategy: ReasoningStrategy,
                                 min_similarity: float) -> int:
        """Generate and store candidate mappings for one field pair via the
        reasoner. Returns how many were stored.

        CrossDomainReasoner implements the seven strategies over real concept
        identities. Everything stored here is a CANDIDATE (validated=None): no
        ontological validation has been performed. A failure raises; it is not
        reported as "no mappings".
        """
        from core.domain.cross_domain_reasoner import (
            get_cross_domain_reasoner, ReasoningContext as XDomainContext,
        )
        reasoner = get_cross_domain_reasoner()
        await reasoner.initialize()
        result = await reasoner.reason_across_domains(XDomainContext(
            source_domain_id=source.domain_id,
            target_domain_id=target.domain_id,
            reasoning_goal=(
                f"identify conceptual correspondences from the "
                f"{source.name} domain to the {target.name} domain"
            ),
            strategy=strategy,
            confidence_threshold=min_similarity,
            # The reasoner's own quality gate stays ON: it answers "is this a
            # well-formed candidate", a different question from ontological
            # acceptance.
            require_validation=True,
        ))
        if not result.success:
            return 0

        stored = 0
        for gm in result.generated_mappings:
            similarity = float(gm.strength or gm.confidence or 0.0)
            if similarity < min_similarity:
                continue
            mapping = CrossDomainMapping(
                mapping_id=registry._mapping_key(
                    source.domain_id, target.domain_id,
                    gm.source_concept_id, gm.target_concept_id, strategy.value),
                source_domain_id=source.domain_id,
                target_domain_id=target.domain_id,
                source_concept_id=gm.source_concept_id,
                target_concept_id=gm.target_concept_id,
                mapping_type=strategy.value,
                strength=similarity,
                confidence=float(gm.confidence if gm.confidence is not None else similarity),
                validated=None,
            )
            if not await self.record_mapping(mapping):
                raise RuntimeError(
                    f"cross-domain mapping {mapping.mapping_id} could not be stored")
            stored += 1
        if stored:
            logger.info(
                "Generated %d cross-domain CANDIDATE mapping(s) %s -> %s (%s) — unvalidated",
                stored, source.domain_id, target.domain_id, strategy.value)
        return stored

    async def _generate_insights(
        self,
        mappings: List[DomainMapping],
        query: CrossDomainQuery
    ) -> List[str]:
        """Generate insights from mappings"""
        insights = []

        if not mappings:
            return insights

        # Generate summary insights
        insights.append(
            f"Found {len(mappings)} cross-domain mappings using "
            f"{query.reasoning_strategy.value} reasoning"
        )

        # Domain coverage
        source_domains = {m.source_domain for m in mappings}
        target_domains = {m.target_domain for m in mappings}
        insights.append(
            f"Coverage: {len(source_domains)} source domains, "
            f"{len(target_domains)} target domains"
        )

        # Average similarity
        avg_similarity = sum(m.similarity_score for m in mappings) / len(mappings)
        insights.append(f"Average similarity: {avg_similarity:.2f}")

        return insights

    async def _generate_explanations(
        self,
        mappings: List[DomainMapping],
        query: CrossDomainQuery
    ) -> List[str]:
        """Generate explanations for mappings"""
        explanations = []

        for mapping in mappings[:5]:  # Limit to top 5
            explanation = (
                f"{mapping.source_concept} ({mapping.source_domain}) maps to "
                f"{mapping.target_concept} ({mapping.target_domain}) "
                f"with {mapping.similarity_score:.0%} similarity using "
                f"{mapping.reasoning_strategy.value} reasoning"
            )
            explanations.append(explanation)

        return explanations

    async def _store_query_record(
        self,
        query: CrossDomainQuery,
        mappings: List[DomainMapping],
        execution_time: float,
        success: bool
    ):
        """Store query execution record"""
        if not self.db:
            return

        await self.db.execute_query(
            """INSERT INTO unified.cross_domain_queries
               (query_id, query_text, source_domains, target_domains,
                reasoning_strategy, execution_time, mappings_found, success)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               ON CONFLICT (query_id) DO NOTHING""",
            (
                query.query_id,
                query.query_text,
                ','.join(d.value for d in query.source_domains),
                ','.join(d.value for d in query.target_domains),
                query.reasoning_strategy.value,
                execution_time,
                len(mappings),
                success
            ),
            commit=True
        )

    async def get_statistics(self) -> Dict[str, Any]:
        """Get domain master statistics"""
        return {
            **self.stats,
            "domains_loaded": len(self.domain_cache),
            "cached_mappings": sum(len(v) for v in self.mapping_cache.values())
        }

    async def shutdown(self):
        """Shutdown and cleanup"""
        if self._embedding_backfill is not None and not self._embedding_backfill.done():
            self._embedding_backfill.cancel()
            try:
                await self._embedding_backfill
            except asyncio.CancelledError:
                pass
        # Database connection is managed by TorinUnifiedDatabase singleton
        # No need to close here
        logger.info("Universal Domain Master shutdown complete")


# Global instance
_universal_domain_master: Optional[UniversalDomainMaster] = None


def get_universal_domain_master() -> UniversalDomainMaster:
    """Get global Universal Domain Master instance"""
    global _universal_domain_master
    if _universal_domain_master is None:
        _universal_domain_master = UniversalDomainMaster()
    return _universal_domain_master


# Alias for backwards compatibility
get_domain_master = get_universal_domain_master
