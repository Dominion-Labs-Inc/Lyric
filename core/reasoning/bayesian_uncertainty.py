#!/usr/bin/env python3
"""
Bayesian Uncertainty Tracking System
=====================================
Extends the Singleton's confidence scoring with proper epistemic humility:
- Bayesian uncertainty quantification
- Known unknowns database
- Confidence calibration against actual accuracy
- Information value estimation

Integrates with existing reasoning and learning systems.
"""

import asyncio
import logging
import json
import math
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict
from core.database import LyricUnifiedDatabase

logger = logging.getLogger(__name__)


# ======================================================================
# THE BELIEF-UPDATE KERNEL (the ONE implementation of the math)
# ======================================================================
# Extracted so every store that moves a posterior on evidence uses the
# IDENTICAL update -- the universal one-mind belief graph
# (`BayesianUncertaintySystem`) and the actor-scoped context store
# (`core.learning.scoped_context_store`). There must be exactly one place
# the odds-based Bayesian update lives, or the two partitions would drift.
_LR_STRENGTH = 3.0       # likelihood-ratio strength at quality=1.0 (exp(±3) ≈ 20x / 0.05x)
_POSTERIOR_FLOOR = 1e-6  # clamp so entropy never collapses to an irrefutable 0/1


def posterior_from_evidence(prior: float, quality: float,
                            supports: bool) -> Tuple[float, float]:
    """Odds-based Bayesian update: P(H|E)/P(¬H|E) = [P(H)/P(¬H)] * LR, with
    LR = exp(±_LR_STRENGTH * quality). Symmetric, bounded, no zero-probability
    singularities. Returns (posterior, likelihood_ratio), UNCLAMPED — the caller
    clamps when it stores (see `clamp_posterior`), so reversal/Δ detection can see
    the raw move first, exactly as the belief graph has always done."""
    lr = math.exp((_LR_STRENGTH if supports else -_LR_STRENGTH) * quality)
    prior_odds = prior / max(1e-9, 1.0 - prior)
    new_odds = prior_odds * lr
    return new_odds / (1.0 + new_odds), lr


def clamp_posterior(posterior: float) -> float:
    """Clamp a posterior to the open interval so a belief can never become
    permanently irrefutable/irrecoverable (entropy collapsing to zero)."""
    return max(_POSTERIOR_FLOOR, min(1.0 - _POSTERIOR_FLOOR, posterior))


def belief_entropy(probability: float) -> float:
    """Shannon entropy of a Bernoulli belief: H = -p·log2(p) - (1-p)·log2(1-p)."""
    if probability <= 0.0 or probability >= 1.0:
        return 0.0
    return -(probability * math.log2(probability) +
             (1 - probability) * math.log2(1 - probability))


class UncertaintyType(Enum):
    """Types of uncertainty"""
    ALEATORIC = "aleatoric"  # Irreducible randomness
    EPISTEMIC = "epistemic"  # Reducible through learning
    MODEL = "model"  # Uncertainty about model structure
    PARAMETRIC = "parametric"  # Uncertainty about parameters


class KnowledgeState(Enum):
    """What we know about what we know"""
    KNOWN_KNOWN = "known_known"  # We know it and know we know it
    KNOWN_UNKNOWN = "known_unknown"  # We know we don't know it
    UNKNOWN_UNKNOWN = "unknown_unknown"  # We don't know we don't know it
    PARTIAL = "partial"  # We know something but not everything


class RelationType(Enum):
    """Types of relationships between beliefs"""
    IMPLIES = "implies"  # A → B (if A is true, B must be true)
    CONTRADICTS = "contradicts"  # A ⊥ B (if A is true, B must be false)
    SUPPORTS = "supports"  # A ⇒ B (A provides evidence for B, but doesn't strictly imply)
    WEAKENS = "weakens"  # A weakens B (A provides evidence against B)
    REQUIRES = "requires"  # A requires B (A cannot be true unless B is true)
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"  # A ⊕ B (exactly one can be true)


@dataclass
class BeliefRelationship:
    """Represents a logical relationship between two beliefs"""
    relationship_id: str
    source_belief_id: str  # Belief A
    target_belief_id: str  # Belief B
    relation_type: RelationType
    strength: float = 1.0  # How strong is this relationship? (0.0-1.0)

    # Metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    discovered_by: str = "system"  # "system", "human", "llm"
    confidence: float = 1.0  # How confident are we in this relationship?

    def reverse_relation(self) -> RelationType:
        """Get the reverse relationship type"""
        if self.relation_type == RelationType.IMPLIES:
            return RelationType.REQUIRES  # B ← A means B requires A
        elif self.relation_type == RelationType.CONTRADICTS:
            return RelationType.CONTRADICTS  # Symmetric
        elif self.relation_type == RelationType.SUPPORTS:
            return RelationType.SUPPORTS  # Keep as supports (evidence flows both ways)
        elif self.relation_type == RelationType.WEAKENS:
            return RelationType.WEAKENS
        elif self.relation_type == RelationType.REQUIRES:
            return RelationType.IMPLIES
        elif self.relation_type == RelationType.MUTUALLY_EXCLUSIVE:
            return RelationType.MUTUALLY_EXCLUSIVE  # Symmetric
        return self.relation_type


@dataclass
class BayesianBelief:
    """How strongly the substrate believes a MEMORY to be true.

    WHAT A BELIEF IS ABOUT IS A MEMORY, NOT A SENTENCE. `claim` was the subject,
    and mirrored into `belief_text`, so the store held its own copy of the
    proposition with no reference to the memory of having been told it. It then
    became a second knowledge store: measured on the live store, the taxonomy
    was being WALKED through it --
    `SELECT belief_text ... WHERE lower(belief_text) LIKE 'term isa %'` -- with a
    dedicated index built to make that fast, and a reasoner answering yes/no from
    `WHERE lower(claim) = 'x isa y'`. 581,443 rows, none of them linked to a
    memory, 61% of them perception recognitions filed as things it had been told.

    The Bayesian machinery below is right and unchanged: prior, likelihood,
    posterior, evidence for and against, entropy, temporal decay. What changes is
    the subject. A belief points AT a memory and says how much the substrate
    credits it; the memory holds what was actually said or seen.

    `claim` is kept as a human-readable label for logs and nothing reads it as
    knowledge.
    """
    belief_id: str
    claim: str
    domain: str

    # Bayesian components
    prior_probability: float  # P(H) - belief before evidence
    likelihood: float  # P(E|H) - probability of evidence given hypothesis
    posterior_probability: float  # P(H|E) - belief after evidence

    #: The memory this belief is about. Without it there is nothing to believe —
    #: see `_persist`, which refuses to store a belief that names no memory.
    #: Defaulted (and so declared after the required fields) so that every
    #: existing construction site still builds; the refusal is at persistence,
    #: where it is visible, rather than as a TypeError at import.
    memory_id: Optional[str] = None

    # Evidence tracking
    evidence_for: List[Dict[str, Any]] = field(default_factory=list)
    evidence_against: List[Dict[str, Any]] = field(default_factory=list)
    evidence_quality: float = 0.5  # How reliable is the evidence?

    # Uncertainty
    uncertainty_type: UncertaintyType = UncertaintyType.EPISTEMIC
    credible_interval: Tuple[float, float] = (0.0, 1.0)  # 95% credible interval
    entropy: float = 1.0  # Information-theoretic uncertainty

    # Temporal decay (prevents epistemic ossification)
    decay_rate: float = 0.01  # Domain-adaptive λ for exp(-λΔt)
    last_evidence_time: datetime = field(default_factory=datetime.now)  # When last evidence arrived
    time_since_reinforcement: float = 0.0  # Hours since last supporting evidence

    # Metadata
    last_updated: datetime = field(default_factory=datetime.now)
    update_count: int = 0
    confidence_history: List[float] = field(default_factory=list)

    # ── Bookkeeping for writing to the ONE store many instances share ──────
    #: The `update_count` of the stored row as this instance last read or wrote
    #: it (None: never stored). A write only replaces the row if it is still at
    #: this version; otherwise another instance has updated it.
    stored_count: Optional[int] = field(default=None, repr=False, compare=False)
    #: Evidence applied here since the last successful write, as
    #: (evidence, supports, effective weight) -- re-applied on top of the stored
    #: belief when another instance got there first, so neither update is lost.
    unsaved_evidence: List[Any] = field(default_factory=list, repr=False, compare=False)


@dataclass
class KnownUnknown:
    """Explicit representation of something we know we don't know"""
    unknown_id: str
    question: str
    domain: str
    knowledge_state: KnowledgeState
    
    # Why don't we know this?
    blocking_factors: List[str] = field(default_factory=list)  # What prevents knowing?
    required_information: List[str] = field(default_factory=list)  # What info would resolve this?
    
    # Value of resolving
    information_value: float = 0.0  # How valuable would knowing this be?
    urgency: float = 0.0  # How urgently do we need to know?
    
    # Resolution
    can_be_resolved: bool = True
    resolution_cost: float = 0.0  # Cost to acquire knowledge
    resolution_strategy: Optional[str] = None  # How to find out
    
    # Tracking
    discovered_at: datetime = field(default_factory=datetime.now)
    resolution_attempts: int = 0

    #: WHAT WOULD SATISFY IT, structured, so learning can be checked against it
    #: rather than against the wording of `question`:
    #:   {"kind": "operator", "predicate": P | None}   -- an operator gap in `domain`
    #:   {"kind": "relation", "subject": S, "relation": R}  -- a declarative gap
    #:   {"kind": "settled",  "about": X}              -- a doubt about X
    target: Dict[str, Any] = field(default_factory=dict)

    # How it was resolved -- kept, because a resolved unknown is a record of
    # what became known and on what grounds, not a row to forget.
    resolved_at: Optional[datetime] = None
    resolution: Optional[str] = None
    resolution_belief_id: Optional[str] = None

    #: WHOSE QUESTION IT IS. None: the substrate's own. A question raised by a
    #: person's words is that person's context, kept in their store and never in
    #: the substrate's own research.
    owner: Optional[str] = None



@dataclass
class ResolutionGrounds:
    """Why a known unknown may be marked resolved -- the learning authority's
    verdict on the three things that must all be learned: the KNOWLEDGE the
    unknown asks for is held, the BELIEF in it is settled and grounded in what
    was met, and the DOMAIN holds it. Each is (satisfied, what was found).
    The belief store records a resolution only from satisfied grounds."""
    unknown_id: str
    knowledge: Tuple[bool, str]
    belief: Tuple[bool, str]
    domain: Tuple[bool, str]
    answer: Optional[str] = None
    belief_id: Optional[str] = None

    @property
    def satisfied(self) -> bool:
        return all(ok for ok, _ in (self.knowledge, self.belief, self.domain))

    def summary(self) -> str:
        return "; ".join(f"{name}: {'yes' if ok else 'no'} ({why})" for name, (ok, why) in
                         (("knowledge", self.knowledge), ("belief", self.belief),
                          ("domain", self.domain)))

@dataclass
class ConfidenceCalibration:
    """Tracks calibration of confidence vs actual accuracy"""
    calibration_id: str
    domain: str
    
    # Calibration data: predicted_confidence -> actual_accuracy
    calibration_bins: Dict[float, List[float]] = field(default_factory=lambda: defaultdict(list))
    
    # Metrics
    brier_score: float = 0.0  # Proper scoring rule (lower is better)
    calibration_error: float = 0.0  # How far off are predictions?
    overconfidence_bias: float = 0.0  # Positive = overconfident, Negative = underconfident
    
    # Statistics
    total_predictions: int = 0
    correct_predictions: int = 0
    samples_needed: int = 100  # Need this many for good calibration


class BayesianUncertaintySystem:
    """
    Bayesian Uncertainty Tracking for the Singleton
    
    Provides epistemic humility by:
    1. Quantifying uncertainty properly (Bayesian inference)
    2. Tracking known unknowns explicitly
    3. Calibrating confidence against reality
    4. Estimating information value
    """
    
    #: THE ONE BOUNDARY BETWEEN AN UNSETTLED BELIEF AND A SETTLED ONE. Above it
    #: a belief is an unstable region exploration targets (the epistemic
    #: engine); at or below it the substrate has settled it one way or the
    #: other, which is what "learned enough" means when a known unknown is
    #: resolved. 0.7 bits ~ a posterior outside (0.28, 0.72).
    UNSTABLE_ENTROPY: float = 0.7

    def __init__(self, db_path: Optional[str] = None):
        # All persistence goes through the unified PostgreSQL database.
        self.unified_db = LyricUnifiedDatabase()
        
        # Bayesian beliefs
        self.beliefs: Dict[str, BayesianBelief] = {}
        # O(1) find-by-claim for observe_claim. Was a linear scan over every
        # belief -- O(n) per call, O(n^2) across a teaching run -- the root cause
        # of multi-hour teaching stalls. Kept in sync at every add/load/delete.
        # Claim key -> ids of the beliefs holding that claim, in registration
        # order; domain -> ids. Reads by claim or domain use these instead of
        # scanning every belief, and the LAST id for a claim is the one belief
        # observe_claim moves and belief_for_claim returns.
        self._claim_ids: Dict[str, List[str]] = {}
        self._domain_ids: Dict[str, Set[str]] = {}

        # Writes that could not reach the DB yet (not initialized). Exposed in
        # get_statistics() so a degraded-persistence window is a visible number
        # rather than a silent assumption.
        self.persistence_drops: int = 0

        # A persistent substrate must not LOSE a belief update if the DB is not
        # ready — a correct reversal dropped here would silently disappear on
        # restart. So un-writable updates are BUFFERED by belief_id (latest state
        # wins; rows are upserted) and REPLAYED by `flush_pending_writes` once
        # persistence is available (startup load, and every durable flush).
        self._pending_writes: Dict[str, "BayesianBelief"] = {}
        #: Live fire-and-forget belief-write tasks, TRACKED so a shutdown flush can
        #: await them. Without this, `_save_belief` orphaned every write to
        #: `loop.create_task` and a process exiting before the task ran lost the
        #: belief -- the "half of knowledge survives restart" defect. `drain_writes`
        #: awaits this set; the done-callback keeps it self-pruning.
        self._write_tasks: set = set()

        # Known unknowns -- the OPEN ones. Restored from unified.known_unknowns at
        # startup (`load_from_db`), so what the substrate knows it does not know
        # survives a restart; curiosity and the epistemic engine read this set.
        self.known_unknowns: Dict[str, KnownUnknown] = {}
        #: Known-unknown writes not yet persisted, by id (latest state wins),
        #: replayed by `flush_pending_writes` -- the guarantee beliefs have.
        self._pending_unknown_writes: Dict[str, KnownUnknown] = {}
        #: Attempts counted here and not yet added to the stored count, by id.
        self._pending_unknown_attempts: Dict[str, int] = {}
        self._known_unknowns_schema_ready = False

        # Confidence calibration by domain
        self.calibrations: Dict[str, ConfidenceCalibration] = {}

        # Domain volatility tracking (for adaptive decay rates)
        self.domain_volatility: Dict[str, float] = defaultdict(lambda: 0.01)  # λ per domain
        self.domain_belief_changes: Dict[str, List[float]] = defaultdict(list)  # Track magnitude of updates
        self.domain_regime_shifts: Dict[str, int] = defaultdict(int)  # Count contradictions/reversals

        # Belief dependency graph (for constraint propagation)
        self.relationships: Dict[str, BeliefRelationship] = {}  # relationship_id -> relationship
        self.forward_edges: Dict[str, Set[str]] = defaultdict(set)  # belief_id -> {relationship_ids}
        self.backward_edges: Dict[str, Set[str]] = defaultdict(set)  # belief_id -> {relationship_ids}
        self.propagation_queue: List[Tuple[str, float, str]] = []  # (belief_id, delta, reason)

        # Statistics
        self.stats = {
            'beliefs_tracked': 0,
            'known_unknowns_discovered': 0,
            'known_unknowns_resolved': 0,
            'calibration_updates': 0,
            'overconfidence_detected': 0,
            'underconfidence_detected': 0,
            'temporal_decays_applied': 0,
            'regime_shifts_detected': 0,
            'relationships_discovered': 0,
            'constraint_propagations': 0,
            'consistency_violations': 0
        }
        
        # Initialize local persistence database
        self._init_database()
    
    def _init_database(self):
        """No-op: persistence is handled by PostgreSQL via unified_db."""
        logger.info("Bayesian uncertainty system ready (PostgreSQL persistence via unified_db)")
    
    # ==================================================================================
    # BAYESIAN BELIEF UPDATING
    # ==================================================================================
    
    def _refuse_if_frozen(self, what: str) -> None:
        """Where the model is a frozen release (staging, production), beliefs do
        not move: a belief is part of the model, and production answers only from
        its release. Refused before anything in this process changes, so what it
        answers from stays the release."""
        db = self.unified_db
        if getattr(db, "frozen", False):
            raise db.frozen_refusal(what)

    def create_belief(
        self,
        claim: str,
        domain: str,
        prior: float = 0.5,
        evidence: Optional[Dict[str, Any]] = None
    ) -> BayesianBelief:
        """
        Create a new Bayesian belief with prior probability.
        
        Args:
            claim: The proposition to track
            domain: Knowledge domain
            prior: Initial belief (default 0.5 = maximum uncertainty)
            evidence: Optional initial evidence
        """
        self._refuse_if_frozen(f"a new belief: {str(claim)[:120]}")
        belief_id = f"belief_{uuid.uuid4().hex[:12]}"
        
        belief = BayesianBelief(
            belief_id=belief_id,
            claim=claim,
            domain=domain,
            prior_probability=prior,
            likelihood=1.0,
            posterior_probability=prior,
            entropy=self._calculate_entropy(prior)
        )
        
        # Register before applying evidence. update_belief() looks the belief
        # up by id and raises "Belief not found" otherwise, so creating a
        # belief with initial evidence always failed -- the belief was only
        # added to self.beliefs on the line after the update attempt.
        self._register_belief(belief)
        self.stats['beliefs_tracked'] += 1

        if evidence:
            belief = self.update_belief(belief_id, evidence)
        
        # Persist to database
        self._save_belief(belief)
        
        logger.debug(f"Created belief: {claim} (prior={prior:.3f})")
        return belief

    @staticmethod
    def _claim_key(claim: Any) -> str:
        """Normalized key a claim is indexed and matched by."""
        return " ".join(str(claim).strip().lower().split())

    @staticmethod
    def _domain_key(domain: Any) -> str:
        return (domain or "").strip().lower()

    def _register_belief(self, belief: "BayesianBelief") -> None:
        self.beliefs[belief.belief_id] = belief
        ids = self._claim_ids.setdefault(self._claim_key(belief.claim), [])
        if belief.belief_id in ids:
            ids.remove(belief.belief_id)
        ids.append(belief.belief_id)
        self._domain_ids.setdefault(self._domain_key(belief.domain), set()).add(belief.belief_id)

    def _unregister_belief(self, belief_id: str) -> None:
        belief = self.beliefs.pop(belief_id)
        key = self._claim_key(belief.claim)
        ids = self._claim_ids.get(key, [])
        if belief_id in ids:
            ids.remove(belief_id)
        if not ids:
            self._claim_ids.pop(key, None)
        members = self._domain_ids.get(self._domain_key(belief.domain), set())
        members.discard(belief_id)
        if not members:
            self._domain_ids.pop(self._domain_key(belief.domain), None)

    def _claim_belief_id(self, claim: Any) -> Optional[str]:
        ids = self._claim_ids.get(self._claim_key(claim))
        return ids[-1] if ids else None

    def observe_claim(self, claim: str, domain: str = "language", *,
                      supports: bool = True, quality: float = 0.9,
                      source: str = "taught",
                      observation: Optional[str] = None,
                      memory_id: Optional[str] = None) -> BayesianBelief:
        """Find-or-create the belief for a claim and record one observation of it.

        `update_belief` needs an existing belief and `create_belief` mints a new
        id every call, so neither answers "record that I was TOLD this"
        idempotently. This is that entry — the one door a learning method uses to
        move a belief: the first telling creates the belief (its prior reflects
        the telling), each later telling reinforces or contradicts the SAME
        belief, so a taught fact moves a posterior instead of spawning parallel
        beliefs about the same claim.

        `observation` IDENTIFIES WHAT VOUCHES FOR THE CLAIM, and re-presenting
        the same witness is not new evidence.

        This was idempotent about the BELIEF and not about the OBSERVATION, and
        the difference is the whole of the following. Evidence carried only
        `{quality, source}` — nothing said WHICH observation it was — so a
        standing fact re-read at every boot appended an entry and moved the
        posterior every time. Measured on the live store before this: 3,395
        beliefs observed more than ten times, 2,588 more than a hundred, and
        `misp_get_event provides get_system_info` at **674 observations,
        posterior 0.999999** — the substrate near-certain of a tool's declared
        signature because it had rebooted 674 times. One witness, counted 674
        times.

        That is epoch intuition applied where it is invalid. Showing a network
        the same data again is training; showing a Bayesian belief the same
        evidence again fabricates a second witness.

        The identity already existed and was dropped at the seam:
        `submit_tool_capability` stamps `evidence_id=_stable_id("toolcap", name)`
        — identical on every boot — and the comment beside it says "the envelope
        id already collapses them in the store". It does, for the concept layer;
        it never reached this one.

        With `observation` supplied, a repeat is recognised and the belief is
        returned UNTOUCHED: no appended evidence, no posterior move, no
        `update_count`. Without it the old behaviour stands — a caller that
        cannot identify its observation may genuinely be reporting a new event,
        and inventing an identity for it would be the opposite error.
        """
        key = self._claim_key(claim)
        existing_id = self._claim_belief_id(key)
        if existing_id is not None and existing_id not in self.beliefs:
            existing_id = None  # stale index entry -> treat as new
        evidence = {"quality": quality, "source": source}
        if observation:
            evidence["observation"] = str(observation)
        # THE MEMORY THAT VOUCHES FOR THIS, recorded as EVIDENCE — which is
        # where this system already tracks what a belief rests on, and where it
        # belongs. A belief is not an annotation on one memory: it outlives the
        # episode that formed it (you believe Paris is in France and recall no
        # lesson), it can rest on many memories at once, and one memory supports
        # several beliefs. `evidence_for` / `evidence_against` are already
        # many-per-belief and are already what `update_belief` weighs, decays
        # and reverses on.
        if memory_id:
            evidence["memory_id"] = str(memory_id)

        if existing_id is not None and observation:
            held = self.beliefs[existing_id]
            already = any(
                str(entry.get("observation") or "") == str(observation)
                for entry in (*held.evidence_for, *held.evidence_against)
                if isinstance(entry, dict))
            if already:
                logger.debug(
                    "observation %r already recorded for %r; belief left at "
                    "%.6f (re-presenting a witness is not new evidence)",
                    observation, claim, held.posterior_probability)
                return held

        if existing_id is None:
            prior = quality if supports else (1.0 - quality)
            belief = self.create_belief(claim=claim, domain=domain, prior=prior,
                                        evidence=evidence)
        else:
            belief = self.update_belief(existing_id, evidence,
                                        evidence_supports=supports)
        # The most recent memory to vouch for it is mirrored onto the belief so
        # a reader can find one without walking the evidence list. It is a
        # POINTER, not the subject: the evidence list above is the real record,
        # and a belief resting on five memories has five entries there.
        if belief is not None and memory_id:
            belief.memory_id = str(memory_id)
        return belief

    def update_belief(
        self,
        belief_id: str,
        evidence: Dict[str, Any],
        evidence_supports: bool = True
    ) -> BayesianBelief:
        """
        Update belief using Bayesian inference with temporal decay: P(H|E) ∝ P(E|H) * P(H)

        Process:
        1. Apply temporal decay to prior (prevents ossification)
        2. Update with new evidence (Bayesian)
        3. Detect regime shifts (belief reversals)
        4. Update domain volatility (adaptive λ)

        Args:
            belief_id: Belief to update
            evidence: Evidence data
            evidence_supports: Whether evidence supports the claim
        """
        if belief_id not in self.beliefs:
            raise ValueError(f"Belief not found: {belief_id}")
        self._refuse_if_frozen(f"a belief moved: {str(self.beliefs[belief_id].claim)[:120]}")

        belief = self.beliefs[belief_id]

        # STEP 1: Apply temporal decay BEFORE new evidence
        # This prevents early conclusions from becoming gravity wells
        original_prior = belief.posterior_probability
        decayed_prior = self._apply_temporal_decay(belief)
        belief.posterior_probability = decayed_prior  # Use decayed value as prior

        # Track evidence
        if evidence_supports:
            belief.evidence_for.append(evidence)
        else:
            belief.evidence_against.append(evidence)

        # Calculate likelihood: P(E|H)
        evidence_weight = evidence.get('quality', belief.evidence_quality)

        # INTEGRATION D: Adjust evidence weight based on cross-domain support
        evidence_weight = self._adjust_evidence_with_domain_support(
            belief, evidence, evidence_weight
        )

        # STEP 2: Bayesian update with decayed prior
        prior = decayed_prior

        # Odds-based Bayesian update via the shared kernel (the ONE place this
        # math lives; see `posterior_from_evidence` at module scope). quality=0
        # → no move; quality=1 → ≈20x/0.05x; symmetric, bounded, no singularities.
        posterior, likelihood = posterior_from_evidence(
            prior, evidence_weight, evidence_supports)
        belief.unsaved_evidence.append((evidence, bool(evidence_supports),
                                        float(evidence_weight)))

        # STEP 3: Detect regime shift (belief reversal across 0.5 threshold)
        is_reversal = False
        if (original_prior > 0.5 and posterior < 0.5) or (original_prior < 0.5 and posterior > 0.5):
            is_reversal = True
            logger.warning(
                f"Belief reversal detected: '{belief.claim[:40]}' "
                f"crossed 0.5 threshold ({original_prior:.3f} → {posterior:.3f})"
            )

        # Calculate belief change magnitude
        belief_change = abs(posterior - original_prior)

        # STEP 4: Update domain volatility (adaptive decay rate)
        self._update_domain_volatility(belief.domain, belief_change, is_reversal)

        # Update belief state. Clamp (shared helper) to the open interval so
        # entropy never collapses to an irrefutable/irrecoverable 0 or 1.
        belief.posterior_probability = clamp_posterior(posterior)
        belief.likelihood = likelihood
        belief.entropy = self._calculate_entropy(belief.posterior_probability)
        belief.last_updated = datetime.now()
        belief.last_evidence_time = datetime.now()  # Reset evidence timer
        belief.time_since_reinforcement = 0.0  # Just got evidence
        belief.update_count += 1
        belief.confidence_history.append(posterior)

        # Update decay rate from domain
        belief.decay_rate = self.domain_volatility[belief.domain]

        # Update credible interval (simplified - using standard error)
        std_error = math.sqrt(posterior * (1 - posterior) / max(belief.update_count, 1))
        belief.credible_interval = (
            max(0.0, posterior - 1.96 * std_error),
            min(1.0, posterior + 1.96 * std_error)
        )

        # Persist update
        self._save_belief(belief)

        # STEP 5: Propagate constraints through belief graph
        # This ensures global coherence: when A changes, update all beliefs that depend on A
        probability_delta = posterior - original_prior
        if abs(probability_delta) > 0.05:  # Only propagate significant changes
            self.propagate_constraints(belief_id, probability_delta, max_depth=5)

        logger.debug(
            f"Updated belief '{belief.claim[:50]}': "
            f"{original_prior:.3f} → {decayed_prior:.3f} (decay) → {posterior:.3f} (evidence) "
            f"(entropy={belief.entropy:.3f}, λ={belief.decay_rate:.4f})"
        )

        return belief
    
    def _calculate_entropy(self, probability: float) -> float:
        """Shannon entropy of the belief (delegates to the shared kernel so there
        is one entropy implementation across the universal and scoped stores)."""
        return belief_entropy(probability)

    def _apply_temporal_decay(self, belief: BayesianBelief) -> float:
        """
        Apply exponential decay to belief probability toward uncertainty.
        Prevents epistemic ossification by requiring continuous evidence reinforcement.

        Formula: P(H)_t+1 = P(H)_t + (0.5 - P(H)_t) * (1 - exp(-λΔt))

        This drifts beliefs toward maximum uncertainty (0.5) in absence of reinforcing evidence.
        """
        now = datetime.now()
        time_delta = (now - belief.last_evidence_time).total_seconds() / 3600.0  # Hours

        # Get domain-adaptive decay rate
        lambda_decay = self.domain_volatility.get(belief.domain, 0.01)

        # Calculate decay factor
        decay_factor = 1 - math.exp(-lambda_decay * time_delta)

        # Drift toward 0.5 (maximum uncertainty)
        current_prob = belief.posterior_probability
        decayed_prob = current_prob + (0.5 - current_prob) * decay_factor

        # Update time tracking
        belief.time_since_reinforcement = time_delta

        if abs(decayed_prob - current_prob) > 0.01:
            self.stats['temporal_decays_applied'] += 1
            logger.debug(
                f"Temporal decay applied to '{belief.claim[:40]}': "
                f"{current_prob:.3f} → {decayed_prob:.3f} "
                f"(Δt={time_delta:.1f}h, λ={lambda_decay:.4f})"
            )

        return decayed_prob

    def _update_domain_volatility(self, domain: str, belief_change: float, is_reversal: bool = False):
        """
        Update domain-adaptive decay rate λ based on observed volatility.

        High volatility domains → higher λ → faster decay (require more frequent evidence)
        Stable domains → lower λ → slower decay (beliefs persist longer)
        """
        # Track belief change magnitude
        self.domain_belief_changes[domain].append(belief_change)

        # Keep last 50 updates for rolling volatility
        if len(self.domain_belief_changes[domain]) > 50:
            self.domain_belief_changes[domain] = self.domain_belief_changes[domain][-50:]

        # Detect regime shifts (major belief reversals)
        if is_reversal:
            self.domain_regime_shifts[domain] += 1
            self.stats['regime_shifts_detected'] += 1
            logger.warning(f"Regime shift detected in domain '{domain}' (total: {self.domain_regime_shifts[domain]})")

        # Calculate volatility metrics
        avg_change = sum(self.domain_belief_changes[domain]) / len(self.domain_belief_changes[domain])
        regime_penalty = min(self.domain_regime_shifts[domain] * 0.005, 0.05)  # Cap at 0.05

        # Adaptive λ: base rate + volatility component + regime penalty
        new_lambda = 0.01 + (avg_change * 0.1) + regime_penalty
        new_lambda = max(0.005, min(0.1, new_lambda))  # Clamp [0.005, 0.1]

        old_lambda = self.domain_volatility[domain]
        self.domain_volatility[domain] = new_lambda

        if abs(new_lambda - old_lambda) > 0.001:
            logger.info(
                f"Domain '{domain}' λ updated: {old_lambda:.4f} → {new_lambda:.4f} "
                f"(volatility={avg_change:.3f}, shifts={self.domain_regime_shifts[domain]})"
            )

    # ==================================================================================
    # BELIEF DEPENDENCY GRAPH & CONSTRAINT PROPAGATION
    # ==================================================================================

    def add_relationship(
        self,
        source_belief_id: str,
        target_belief_id: str,
        relation_type: RelationType,
        strength: float = 1.0,
        confidence: float = 1.0,
        discovered_by: str = "system"
    ) -> str:
        """
        Add a logical relationship between two beliefs.

        This creates edges in the belief dependency graph for constraint propagation.

        Args:
            source_belief_id: Source belief (A in "A → B")
            target_belief_id: Target belief (B in "A → B")
            relation_type: Type of relationship (implies, contradicts, etc.)
            strength: Relationship strength (0.0-1.0)
            confidence: Confidence in this relationship (0.0-1.0)
            discovered_by: Who/what discovered this relationship

        Returns:
            relationship_id
        """
        relationship_id = f"rel_{uuid.uuid4().hex[:12]}"

        relationship = BeliefRelationship(
            relationship_id=relationship_id,
            source_belief_id=source_belief_id,
            target_belief_id=target_belief_id,
            relation_type=relation_type,
            strength=strength,
            discovered_by=discovered_by,
            confidence=confidence
        )

        # Store relationship
        self.relationships[relationship_id] = relationship

        # Update graph edges
        self.forward_edges[source_belief_id].add(relationship_id)
        self.backward_edges[target_belief_id].add(relationship_id)

        self.stats['relationships_discovered'] += 1

        logger.info(
            f"Relationship added: {source_belief_id[:8]} {relation_type.value} {target_belief_id[:8]} "
            f"(strength={strength:.2f}, confidence={confidence:.2f})"
        )

        # Immediately activate: propagate the source belief's current epistemic
        # influence to the newly connected target.
        # activation_delta = how far source deviates from neutral (0.5).
        # Shallow max_depth=3 on creation — deeper cascades fire on update_belief().
        source = self.beliefs.get(source_belief_id)
        if source is not None:
            activation_delta = source.posterior_probability - 0.5
            if abs(activation_delta) > 0.05:
                self.propagate_constraints(
                    source_belief_id, activation_delta, max_depth=3
                )

        return relationship_id

    def propagate_constraints(
        self,
        changed_belief_id: str,
        probability_delta: float,
        max_depth: int = 5,
        visited: Optional[Set[str]] = None
    ):
        """
        Propagate belief updates through the dependency graph.

        When belief A changes, recursively update all beliefs that depend on A:
        - A → B (implies): Increase in P(A) increases P(B)
        - A ⊥ B (contradicts): Increase in P(A) decreases P(B)
        - A ⇒ B (supports): Increase in P(A) slightly increases P(B)

        Args:
            changed_belief_id: Belief that just changed
            probability_delta: How much it changed (positive or negative)
            max_depth: Maximum propagation depth (prevent infinite loops)
            visited: Set of already-visited beliefs (for cycle detection)
        """
        if max_depth <= 0:
            return

        if visited is None:
            visited = set()

        if changed_belief_id in visited:
            logger.warning(f"Cycle detected in belief graph at {changed_belief_id[:8]}")
            return

        visited.add(changed_belief_id)

        # Get all forward relationships from this belief
        forward_rels = self.forward_edges.get(changed_belief_id, set())

        for rel_id in forward_rels:
            relationship = self.relationships[rel_id]
            target_id = relationship.target_belief_id

            if target_id not in self.beliefs:
                continue

            target_belief = self.beliefs[target_id]

            # Compute propagation effect
            effect = self._compute_propagation_effect(
                relationship.relation_type,
                probability_delta,
                relationship.strength,
                relationship.confidence
            )

            if abs(effect) < 0.01:  # Threshold: ignore tiny effects
                continue

            # Apply effect to target belief
            old_prob = target_belief.posterior_probability
            new_prob = max(0.0, min(1.0, old_prob + effect))  # Clamp [0, 1]

            if abs(new_prob - old_prob) > 0.01:
                target_belief.posterior_probability = new_prob
                target_belief.entropy = self._calculate_entropy(new_prob)
                target_belief.last_updated = datetime.now()

                self.stats['constraint_propagations'] += 1

                logger.debug(
                    f"Constraint propagation: {target_id[:8]} "
                    f"{old_prob:.3f} → {new_prob:.3f} "
                    f"(via {relationship.relation_type.value} from {changed_belief_id[:8]})"
                )

                # Recursively propagate
                self.propagate_constraints(
                    target_id,
                    new_prob - old_prob,
                    max_depth - 1,
                    visited
                )

    def _compute_propagation_effect(
        self,
        relation_type: RelationType,
        delta: float,
        strength: float,
        confidence: float
    ) -> float:
        """
        Compute how much a belief change should affect a related belief.

        Returns the probability delta to apply to the target belief.
        """
        base_effect = delta * strength * confidence

        if relation_type == RelationType.IMPLIES:
            # A → B: If A increases, B increases (scaled by strength)
            return base_effect * 0.8

        elif relation_type == RelationType.CONTRADICTS:
            # A ⊥ B: If A increases, B decreases
            return -base_effect * 0.9

        elif relation_type == RelationType.SUPPORTS:
            # A ⇒ B: Weak positive influence
            return base_effect * 0.4

        elif relation_type == RelationType.WEAKENS:
            # A weakens B: Weak negative influence
            return -base_effect * 0.4

        elif relation_type == RelationType.REQUIRES:
            # B requires A: If A decreases significantly, B must decrease
            if delta < -0.2:  # Only propagate large decreases
                return delta * strength * 0.7
            return 0.0

        elif relation_type == RelationType.MUTUALLY_EXCLUSIVE:
            # A ⊕ B: If A increases, B decreases (zero-sum)
            return -base_effect * 0.95

        return 0.0

    def check_consistency(self) -> Dict[str, Any]:
        """
        Check global consistency of the belief graph.

        Detects:
        - Implication violations (A → B but P(A) > P(B))
        - Contradiction violations (A ⊥ B but both have high probability)
        - Mutual exclusivity violations (A ⊕ B but both high)
        - Circular dependencies

        Returns consistency report with violations.
        """
        violations = {
            'implication_violations': [],
            'contradiction_violations': [],
            'mutual_exclusivity_violations': [],
            'circular_dependencies': [],
            'total_violations': 0
        }

        for rel_id, relationship in self.relationships.items():
            source_id = relationship.source_belief_id
            target_id = relationship.target_belief_id

            if source_id not in self.beliefs or target_id not in self.beliefs:
                continue

            source_prob = self.beliefs[source_id].posterior_probability
            target_prob = self.beliefs[target_id].posterior_probability

            relation = relationship.relation_type

            # Check implication violations: A → B requires P(A) ≤ P(B) + ε
            if relation == RelationType.IMPLIES:
                if source_prob > target_prob + 0.15:  # Tolerance
                    violations['implication_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob,
                        'violation_magnitude': source_prob - target_prob
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

            # Check contradiction violations: A ⊥ B requires P(A) + P(B) ≈ 1
            elif relation == RelationType.CONTRADICTS:
                prob_sum = source_prob + target_prob
                if not (0.8 <= prob_sum <= 1.2):  # Should sum to ~1
                    violations['contradiction_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob,
                        'prob_sum': prob_sum
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

            # Check mutual exclusivity: A ⊕ B requires exactly one high
            elif relation == RelationType.MUTUALLY_EXCLUSIVE:
                if source_prob > 0.7 and target_prob > 0.7:
                    violations['mutual_exclusivity_violations'].append({
                        'source': source_id,
                        'target': target_id,
                        'source_prob': source_prob,
                        'target_prob': target_prob
                    })
                    violations['total_violations'] += 1
                    self.stats['consistency_violations'] += 1

        if violations['total_violations'] > 0:
            logger.warning(
                f"Consistency check found {violations['total_violations']} violations: "
                f"{len(violations['implication_violations'])} implications, "
                f"{len(violations['contradiction_violations'])} contradictions, "
                f"{len(violations['mutual_exclusivity_violations'])} mutual exclusivity"
            )

        return violations

    def get_belief(self, belief_id: str) -> Optional["BayesianBelief"]:
        """The held belief for an id, or None. The completion decision reads the
        posterior off this to judge whether the goal is grounded-confident."""
        return self.beliefs.get(belief_id)

    def belief_for_claim(self, claim: str) -> Optional["BayesianBelief"]:
        """The held belief whose claim matches (normalised), or None — a fresh
        retrieval by proposition. Used by completion SAW to independently check
        whether a learned claim is actually held in the store now."""
        belief_id = self._claim_belief_id(claim)
        return self.beliefs.get(belief_id) if belief_id else None

    def beliefs_for_domain(self, domain: str, limit: int = 8) -> List[Dict[str, Any]]:
        """The SPECIFIC beliefs held in a domain — claim + posterior, most-recently
        moved first. Task outcomes (via the epistemic engine) and learning (via
        observe_claim) both move these, so they ARE the substrate's accumulated
        understanding of the domain. Used to stamp a memory with the pertinent
        beliefs at the time it formed, not just an aggregate count."""
        key = self._domain_key(domain)
        if not key:
            return []
        items = [self.beliefs[bid] for bid in self._domain_ids.get(key, ())]
        items.sort(key=lambda b: getattr(b, "last_updated", None) or datetime.min,
                   reverse=True)
        return [{"belief_id": b.belief_id, "claim": b.claim,
                 "posterior": round(float(b.posterior_probability), 4),
                 "updated_at": (b.last_updated.isoformat()
                                if getattr(b, "last_updated", None) else None)}
                for b in items[:limit]]

    def get_belief_uncertainty(self, belief_id: str) -> Dict[str, Any]:
        """Get comprehensive uncertainty information for a belief"""
        if belief_id not in self.beliefs:
            return {"error": "Belief not found"}
        
        belief = self.beliefs[belief_id]
        
        return {
            'claim': belief.claim,
            'probability': belief.posterior_probability,
            'credible_interval': belief.credible_interval,
            'entropy': belief.entropy,
            'uncertainty_type': belief.uncertainty_type.value,
            'evidence_count': len(belief.evidence_for) + len(belief.evidence_against),
            'evidence_balance': len(belief.evidence_for) - len(belief.evidence_against),
            'updates': belief.update_count,
            'interpretation': self._interpret_uncertainty(belief)
        }
    
    def _interpret_uncertainty(self, belief: BayesianBelief) -> str:
        """Human-readable interpretation of uncertainty"""
        prob = belief.posterior_probability
        entropy = belief.entropy
        
        if entropy < 0.2:
            certainty = "very certain"
        elif entropy < 0.5:
            certainty = "fairly certain"
        elif entropy < 0.8:
            certainty = "moderately uncertain"
        else:
            certainty = "very uncertain"
        
        if prob > 0.9:
            belief_str = "strongly believe this is true"
        elif prob > 0.7:
            belief_str = "believe this is likely true"
        elif prob > 0.5:
            belief_str = "slightly lean towards true"
        elif prob > 0.3:
            belief_str = "slightly lean towards false"
        elif prob > 0.1:
            belief_str = "believe this is likely false"
        else:
            belief_str = "strongly believe this is false"
        
        return f"I {belief_str} ({certainty}, entropy={entropy:.2f})"
    
    # ==================================================================================
    # KNOWN UNKNOWNS TRACKING
    # ==================================================================================
    
    def register_known_unknown(
        self,
        question: str,
        domain: str,
        blocking_factors: Optional[List[str]] = None,
        required_info: Optional[List[str]] = None,
        *,
        target: Dict[str, Any],
        owner: Optional[str] = None,
    ) -> KnownUnknown:
        """
        Explicitly register something we know we don't know.

        This is epistemic humility in action - acknowledging ignorance.

        `target` is WHAT WOULD SATISFY IT (see `KnownUnknown.target`). It is
        required: an unknown that does not say what would answer it can only be
        checked against its wording, never against what has been learned.

        `owner` is whose question it is. A person's (raised by their words) is
        their context: it is kept in their store and does NOT join the
        substrate's own open questions, which its research and resolution work
        on -- researching it would send their context out.
        """
        if not (isinstance(target, dict) and target.get("kind") in
                ("operator", "relation", "settled")):
            raise ValueError(f"a known unknown must say what would satisfy it; "
                             f"target={target!r}")
        from core.agents.autonomous.shared_types import is_substrate_actor
        unknown_id = f"unknown_{uuid.uuid4().hex[:12]}"

        unknown = KnownUnknown(
            unknown_id=unknown_id,
            question=question,
            domain=domain,
            knowledge_state=KnowledgeState.KNOWN_UNKNOWN,
            blocking_factors=blocking_factors or [],
            required_information=required_info or [],
            target=dict(target),
            owner=None if is_substrate_actor(owner) else owner,
        )
        
        # Calculate information value (how valuable is knowing this?)
        unknown.information_value = self._estimate_information_value(unknown)
        
        # Determine resolution strategy
        unknown.resolution_strategy = self._suggest_resolution_strategy(unknown)
        
        if unknown.owner is None:
            self.known_unknowns[unknown_id] = unknown
            self.stats['known_unknowns_discovered'] += 1
        else:
            self.stats['people_questions_kept'] = self.stats.get('people_questions_kept', 0) + 1

        # Persist to database
        self._save_known_unknown(unknown)

        logger.info("Registered known unknown%s: %s (value=%.3f)",
                    "" if unknown.owner is None else " (a person's, kept in their context)",
                    question, unknown.information_value)
        return unknown
    
    def _estimate_information_value(self, unknown: KnownUnknown) -> float:
        """Estimate the value of resolving this unknown (0.0 to 1.0)"""
        value = 0.5  # Base value
        
        # High value if affects many decisions
        if 'decision' in unknown.question.lower() or 'should' in unknown.question.lower():
            value += 0.2
        
        # High value if in critical domain
        critical_domains = ['safety', 'security', 'self_improvement', 'reasoning']
        if any(domain in unknown.domain.lower() for domain in critical_domains):
            value += 0.2
        
        # High value if many blocking factors (resolving unlocks much)
        value += min(0.1 * len(unknown.blocking_factors), 0.3)
        
        return min(value, 1.0)
    
    def _suggest_resolution_strategy(self, unknown: KnownUnknown) -> str:
        """Suggest how to resolve this unknown"""
        strategies = []
        
        # Can we research it?
        if any('research' in factor.lower() for factor in unknown.blocking_factors):
            strategies.append("autonomous_research")
        
        # Can we experiment?
        if any('test' in factor.lower() or 'experiment' in factor.lower() 
               for factor in unknown.blocking_factors):
            strategies.append("sandbox_experiment")
        
        # Need external data?
        if any('data' in info.lower() for info in unknown.required_information):
            strategies.append("data_collection")
        
        # Need reasoning?
        if any('understand' in info.lower() or 'reason' in info.lower() 
               for info in unknown.required_information):
            strategies.append("deep_reasoning")
        
        return ", ".join(strategies) if strategies else "unclear"
    
    def get_high_value_unknowns(self, min_value: float = 0.7) -> List[KnownUnknown]:
        """Get known unknowns worth resolving (high information value)"""
        return [
            unknown for unknown in self.known_unknowns.values()
            if unknown.information_value >= min_value and unknown.can_be_resolved
        ]
    
    @staticmethod
    def is_grounded(belief: "BayesianBelief") -> bool:
        """Whether a belief rests on something the substrate MET: it names a
        memory, or some evidence for or against it does. The rule a belief must
        meet to be stored, and to count toward resolving a known unknown."""
        return bool(getattr(belief, "memory_id", None)) or any(
            isinstance(e, dict) and e.get("memory_id")
            for e in (*belief.evidence_for, *belief.evidence_against))

    def note_resolution_attempt(self, unknown_id: str) -> None:
        """Count one attempt to resolve an open unknown that was not yet
        learned enough, durably -- as an atomic increment of the stored count,
        so attempts made by several instances all count."""
        import asyncio
        unknown = self.known_unknowns.get(unknown_id)
        if unknown is None:
            return
        unknown.resolution_attempts += 1
        self._pending_unknown_attempts[unknown_id] = (
            self._pending_unknown_attempts.get(unknown_id, 0) + 1)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return   # kept; the next durable flush writes it
        task = loop.create_task(self._write_unknown_attempts(unknown_id))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    async def _write_unknown_attempts(self, unknown_id: str) -> bool:
        """Add this instance's unwritten attempts to the stored count."""
        n = self._pending_unknown_attempts.pop(unknown_id, 0)
        if not n:
            return True
        try:
            if not self.unified_db.initialized:
                raise RuntimeError("database not initialized")
            from core.agents.memory_agent import memory_agent
            await memory_agent().add_unknown_attempts(unknown_id=unknown_id, n=n)
            return True
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "bayesian_uncertainty._write_unknown_attempts")
            self._pending_unknown_attempts[unknown_id] = (
                self._pending_unknown_attempts.get(unknown_id, 0) + n)
            logger.warning("attempts on %s not persisted (kept): %s", unknown_id, error)
            return False

    def set_target(self, unknown_id: str, target: Dict[str, Any]) -> None:
        """Record what would satisfy an open unknown, durably -- for unknowns
        registered before targets existed."""
        unknown = self.known_unknowns.get(unknown_id)
        if unknown is not None:
            unknown.target = dict(target)
            self._save_known_unknown(unknown)

    def resolve_known_unknown(self, unknown_id: str,
                              grounds: "ResolutionGrounds") -> bool:
        """Record that an open known unknown is resolved -- ONLY on satisfied
        grounds from the learning authority (`UnifiedLearningSystem.
        resolve_known_unknown`), which checks that the knowledge, the belief
        and the domain are all learned enough. The resolution is WRITTEN: it
        used to be dropped from memory only, so the row stayed open forever and
        nothing reloaded it; and it minted a fresh belief at 0.7 grounded in
        nothing. The answer is now the belief the grounds found, by id.

        Returns False when the unknown is not open; raises when the grounds do
        not satisfy it or belong to another unknown."""
        if not isinstance(grounds, ResolutionGrounds) or grounds.unknown_id != unknown_id:
            raise ValueError("a known unknown is resolved only on its own grounds")
        if not grounds.satisfied:
            raise ValueError(f"not learned enough to resolve {unknown_id}: "
                             f"{grounds.summary()}")
        unknown = self.known_unknowns.get(unknown_id)
        if unknown is None:
            return False
        unknown.knowledge_state = KnowledgeState.KNOWN_KNOWN
        unknown.resolved_at = datetime.now()
        unknown.resolution = grounds.answer or grounds.summary()
        unknown.resolution_belief_id = grounds.belief_id
        self._save_known_unknown(unknown)
        del self.known_unknowns[unknown_id]
        self.stats['known_unknowns_resolved'] += 1
        logger.info("Resolved unknown %s (%s): %s", unknown_id, unknown.question,
                    grounds.summary())
        return True

    # ==================================================================================
    # CONFIDENCE CALIBRATION
    # ==================================================================================
    
    def record_prediction(
        self,
        domain: str,
        predicted_confidence: float,
        actual_outcome: bool
    ):
        """
        Record a prediction with confidence and actual outcome.
        Used to calibrate future confidence estimates.
        """
        self._refuse_if_frozen(f"confidence calibration moved: {domain}")
        # Get or create calibration for domain
        if domain not in self.calibrations:
            self.calibrations[domain] = ConfidenceCalibration(
                calibration_id=f"cal_{domain}_{uuid.uuid4().hex[:8]}",
                domain=domain
            )
        
        calibration = self.calibrations[domain]
        
        # Bin the confidence (round to nearest 0.1)
        confidence_bin = round(predicted_confidence, 1)
        
        # Record actual outcome (1.0 for correct, 0.0 for incorrect)
        actual_value = 1.0 if actual_outcome else 0.0
        calibration.calibration_bins[confidence_bin].append(actual_value)
        
        # Update statistics
        calibration.total_predictions += 1
        if actual_outcome:
            calibration.correct_predictions += 1
        
        # Recalculate calibration metrics
        self._update_calibration_metrics(calibration)
        
        # Persist to database
        self._save_calibration_data(domain, predicted_confidence, actual_value)
        
        self.stats['calibration_updates'] += 1
    
    def _update_calibration_metrics(self, calibration: ConfidenceCalibration):
        """Update Brier score and calibration error"""
        if calibration.total_predictions < 10:
            return  # Need minimum samples
        
        # Calculate Brier score: mean squared error of probabilities
        brier_sum = 0.0
        total_samples = 0
        
        for confidence_bin, outcomes in calibration.calibration_bins.items():
            for outcome in outcomes:
                brier_sum += (confidence_bin - outcome) ** 2
                total_samples += 1
        
        if total_samples > 0:
            calibration.brier_score = brier_sum / total_samples
        
        # Calculate calibration error: average difference between confidence and accuracy
        calibration_errors = []
        
        for confidence_bin, outcomes in calibration.calibration_bins.items():
            if outcomes:
                actual_accuracy = sum(outcomes) / len(outcomes)
                calibration_errors.append(confidence_bin - actual_accuracy)
        
        if calibration_errors:
            calibration.calibration_error = sum(abs(e) for e in calibration_errors) / len(calibration_errors)
            calibration.overconfidence_bias = sum(calibration_errors) / len(calibration_errors)
            
            # Track bias
            if calibration.overconfidence_bias > 0.1:
                self.stats['overconfidence_detected'] += 1
            elif calibration.overconfidence_bias < -0.1:
                self.stats['underconfidence_detected'] += 1
    
    def get_calibrated_confidence(
        self,
        domain: str,
        raw_confidence: float
    ) -> float:
        """
        Adjust raw confidence based on historical calibration.
        
        If we're systematically overconfident, this corrects for it.
        """
        if domain not in self.calibrations:
            return raw_confidence  # No calibration data yet
        
        calibration = self.calibrations[domain]
        
        if calibration.total_predictions < calibration.samples_needed:
            return raw_confidence  # Not enough data
        
        # Apply bias correction
        corrected = raw_confidence - calibration.overconfidence_bias
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, corrected))
    
    def should_defer_to_expert(
        self,
        domain: str,
        confidence: float,
        entropy: float
    ) -> Dict[str, Any]:
        """
        Decide if uncertainty is too high and should defer to human/expert.
        
        Returns decision and reasoning.
        """
        # Get calibrated confidence
        calibrated_conf = self.get_calibrated_confidence(domain, confidence)
        
        # Decision criteria
        defer = False
        reasons = []
        
        # High uncertainty (entropy)
        if entropy > 0.8:
            defer = True
            reasons.append("Very high uncertainty (entropy > 0.8)")
        
        # Low confidence after calibration
        if calibrated_conf < 0.3:
            defer = True
            reasons.append(f"Low calibrated confidence ({calibrated_conf:.2f})")
        
        # Critical domain with moderate uncertainty
        critical_domains = ['safety', 'security', 'self_improvement']
        if domain in critical_domains and (entropy > 0.5 or calibrated_conf < 0.7):
            defer = True
            reasons.append(f"Critical domain with insufficient certainty")
        
        # Known unknowns in this domain
        relevant_unknowns = [
            u for u in self.known_unknowns.values()
            if u.domain == domain and u.information_value > 0.5
        ]
        if relevant_unknowns:
            defer = True
            reasons.append(f"Known unknowns exist in this domain ({len(relevant_unknowns)})")
        
        return {
            'should_defer': defer,
            'reasons': reasons,
            'calibrated_confidence': calibrated_conf,
            'original_confidence': confidence,
            'entropy': entropy,
            'recommendation': (
                "Defer to expert or gather more information"
                if defer else
                "Proceed with caution but can make decision"
            )
        }
    
    # ==================================================================================
    # PERSISTENCE
    # ==================================================================================
    
    # ==================================================================================
    # PERSISTENCE — PostgreSQL via unified_db
    # ==================================================================================

    async def _merge_stored_belief(self, belief: BayesianBelief) -> bool:
        """Another instance moved this belief since this one last stored it.
        Take the STORED belief and re-apply this instance's own new evidence on
        top of it, with the kernel `update_belief` uses. Returns whether there is
        anything of this instance's to write (False: adopt the stored belief)."""
        import json as _json
        row = await self.unified_db.execute_query(
            "SELECT posterior_probability, update_count, evidence_for, evidence_against, "
            "last_updated FROM unified.beliefs WHERE belief_id = $1",
            (belief.belief_id,), fetch_one=True)
        if row is None:
            belief.stored_count = None     # gone from the store: write it anew
            return True

        def _list(value):
            return _json.loads(value) if isinstance(value, str) else list(value or [])

        posterior = float(row["posterior_probability"])
        evidence_for = _list(row["evidence_for"])
        evidence_against = _list(row["evidence_against"])
        for evidence, supports, weight in belief.unsaved_evidence:
            posterior, _ = posterior_from_evidence(posterior, weight, supports)
            (evidence_for if supports else evidence_against).append(evidence)
        belief.posterior_probability = clamp_posterior(posterior)
        belief.entropy = self._calculate_entropy(belief.posterior_probability)
        belief.evidence_for, belief.evidence_against = evidence_for, evidence_against
        belief.stored_count = int(row["update_count"])
        belief.update_count = belief.stored_count + len(belief.unsaved_evidence)
        if not belief.unsaved_evidence:
            belief.last_updated = row["last_updated"] or belief.last_updated
            return False
        return True

    async def _write_belief_row(self, belief: BayesianBelief, *, commit: bool = True) -> bool:
        """Write one belief to unified.beliefs. Returns whether it was written.

        Shared by the fire-and-forget `_save_belief` and the awaited
        `flush_belief`, so the two paths cannot drift.
        """
        import json as _json
        if not self.unified_db.initialized:
            # Do NOT drop the write — a persistent substrate must not lose a belief
            # reversal. BUFFER the latest state per belief_id (rows are upserted)
            # for replay by `flush_pending_writes` once the DB is up. Still counted
            # and surfaced so the degraded window is observable, not silent.
            self._pending_writes[belief.belief_id] = belief
            self.persistence_drops += 1
            if self.persistence_drops == 1 or self.persistence_drops % 50 == 0:
                logger.warning(
                    f"Epistemic persistence not yet available (database "
                    f"initializing): {self.persistence_drops} write(s) buffered "
                    f"for replay; {len(self._pending_writes)} belief(s) pending."
                )
            return False
        # A BELIEF NAMES THE MEMORY IT IS ABOUT, OR IT IS NOT A BELIEF.
        #
        # Refused here rather than stored with a null subject, because a row
        # whose only content is a proposition IS the second knowledge store this
        # change exists to remove. Measured before it: 581,443 rows, none linked
        # to a memory; the taxonomy was being walked through `belief_text`, and
        # on every boot ~1,800 tool signatures ("move_file requires
        # source_path") were written as things the substrate believed.
        #
        # Loud, not silent: a caller that has something to say about a memory
        # should say which memory, and one that has no memory in hand is
        # recording knowledge in the wrong place — which is a defect to see, not
        # to absorb.
        grounded = self.is_grounded(belief)
        if not grounded:
            self._unsubjected_beliefs = getattr(self, "_unsubjected_beliefs", 0) + 1
            if self._unsubjected_beliefs == 1 or self._unsubjected_beliefs % 100 == 0:
                logger.warning(
                    "belief %r rests on no remembered evidence and was NOT "
                    "stored (%d so far): a belief is a stance on something the "
                    "substrate has met, not a place to keep a claim",
                    str(getattr(belief, "claim", ""))[:60], self._unsubjected_beliefs)
            return False

        try:
            # `claim` and `belief_text` are a human-readable LABEL for logs and
            # nothing reads them as knowledge; the subject is `memory_id`.
            #
            # ONE STORE, MANY INSTANCES. The row is replaced only if it is still
            # at the version this instance last saw; otherwise another instance
            # has moved the belief since, and a plain upsert (what this was)
            # would overwrite its update -- last writer wins. On a conflict this
            # instance's own new evidence is re-applied on top of the stored
            # belief with the same kernel, and that is written instead.
            from core.agents.memory_agent import memory_agent
            for _ in range(5):
                row = await memory_agent().hold_belief(
                    belief_id=belief.belief_id, memory_id=belief.memory_id,
                    claim=belief.claim, domain=belief.domain,
                    prior_probability=belief.prior_probability,
                    posterior_probability=belief.posterior_probability,
                    uncertainty_type=belief.uncertainty_type.value,
                    entropy=belief.entropy,
                    evidence_for=_json.dumps(belief.evidence_for),
                    evidence_against=_json.dumps(belief.evidence_against),
                    update_count=belief.update_count, last_updated=belief.last_updated,
                    expected_update_count=(-1 if belief.stored_count is None
                                           else belief.stored_count))
                if row is not None:
                    belief.stored_count = int(row["update_count"])
                    belief.unsaved_evidence.clear()
                    return True
                if not await self._merge_stored_belief(belief):
                    return True      # nothing of ours to add: the stored belief stands
            logger.warning("belief %s: still conflicting after 5 merges; kept for the "
                           "next write", belief.belief_id)
            return False
        except Exception as e:
            # Was logger.debug -- a total persistence failure of the belief
            # graph is not a debug-level event.
            logger.warning(f"_save_belief failed for {belief.belief_id}: {e}")
            return False

    def _save_belief(self, belief: BayesianBelief):
        """Persist a belief fire-and-forget from sync callers (non-blocking).

        Committed when it runs, but NOT awaited -- fine for high-frequency
        updates where a lost write is recoverable. A belief that MUST survive a
        restart (domain competence, which decides what the substrate explores
        after reboot) should use `flush_belief`, which awaits the committed
        write. With no running loop (some sync/test contexts) this path cannot
        schedule anything, another reason the durable path is explicit.
        """
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # TRACK the task so a shutdown flush (drain_writes) can await it.
            # Buffer the latest state too, so `flush_pending_writes` is a backstop
            # if the process dies before this task runs -- either path persists it.
            self._pending_writes[belief.belief_id] = belief
            task = loop.create_task(self._write_belief_row(belief, commit=True))
            self._write_tasks.add(task)
            task.add_done_callback(lambda t: (
                self._write_tasks.discard(t),
                self._pending_writes.pop(belief.belief_id, None)
                if not t.cancelled() and not t.exception() and t.result() else None))
        except RuntimeError:
            # No running loop (e.g. tests): buffer for the next durable flush /
            # startup replay rather than silently dropping the write.
            self._pending_writes[belief.belief_id] = belief

    async def drain_writes(self) -> int:
        """Await every outstanding fire-and-forget belief write, then replay any
        buffered backlog. The shutdown flush barrier calls this BEFORE the DB pool
        closes, so no belief is lost to an un-run `create_task` on exit. Returns
        the number of write tasks awaited."""
        import asyncio
        tasks = list(self._write_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.flush_pending_writes()
        return len(tasks)

    async def flush_pending_writes(self) -> int:
        """Replay belief writes that were BUFFERED while the DB was unavailable, so
        nothing is lost across the degraded window. Called once persistence is up
        (startup load, and every durable flush). Writes the latest buffered state
        per belief and keeps any that still fail, so a persistent failure never
        drops silently. Returns the number persisted."""
        if not self.unified_db.initialized:
            return 0
        written = 0
        for belief in list(self._pending_writes.values()):
            if await self._write_belief_row(belief, commit=True):
                self._pending_writes.pop(belief.belief_id, None)
                written += 1
        # Known unknowns are replayed by the same guarantee -- their state, then
        # the attempts counted since.
        for unknown_id in list(self._pending_unknown_attempts):
            await self._write_unknown_attempts(unknown_id)
        for unknown in list(self._pending_unknown_writes.values()):
            if await self._write_known_unknown(unknown):
                if self._pending_unknown_writes.get(unknown.unknown_id) is unknown:
                    self._pending_unknown_writes.pop(unknown.unknown_id, None)
                written += 1
        if written:
            logger.info(
                "Epistemic persistence: replayed %d buffered belief write(s); "
                "%d still pending", written, len(self._pending_writes))
        return written

    async def flush_belief(self, belief_id: str) -> bool:
        """Write a belief to unified.beliefs synchronously and committed, so it
        survives a real restart. For decision-critical beliefs that must not be
        lost to fire-and-forget -- competence beliefs are flushed on every
        update by the domain authority, and a task's COMPLETION belief is flushed
        once its evidence is in, so a completion (or its reversal) is durable."""
        belief = self.beliefs.get(belief_id)
        if belief is None:
            return False
        if not self.unified_db.initialized:
            await self.unified_db.initialize()
        await self.flush_pending_writes()  # replay any backlog first
        return await self._write_belief_row(belief, commit=True)

    async def _delete_belief_row(self, belief_id: str) -> bool:
        """Remove a belief from unified.beliefs — used when reflection decays a
        belief to near-neutral and drops it from memory. Without this the row
        lived on and load_from_db would resurrect a belief the substrate had
        deliberately let go."""
        if not self.unified_db.initialized:
            self.persistence_drops += 1
            return False
        try:
            from core.agents.memory_agent import memory_agent
            await memory_agent().drop_belief(belief_id)
            return True
        except Exception as e:
            logger.warning("_delete_belief_row failed for %s: %s", belief_id, e)
            return False

    _VOLATILITY_DDL = """
    CREATE TABLE IF NOT EXISTS unified.domain_volatility (
        domain      VARCHAR PRIMARY KEY,
        lambda      DOUBLE PRECISION NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    async def _ensure_volatility_table(self) -> None:
        if getattr(self, "_volatility_schema_ready", False):
            return
        if not self.unified_db.initialized:
            await self.unified_db.initialize()
        await self.unified_db.execute_query(self._VOLATILITY_DDL.strip())
        self._volatility_schema_ready = True

    async def save_domain_volatility(self) -> int:
        """Persist per-domain λ so adaptive decay rates survive a restart. Reflection
        recomputes these from observed belief change; without persistence every
        restart reset them to the 0.01 default and the substrate re-learned
        volatility it already knew. Returns rows written."""
        try:
            await self._ensure_volatility_table()
            written = 0
            from core.agents.memory_agent import memory_agent
            for domain, lam in list(self.domain_volatility.items()):
                await memory_agent().hold_domain_volatility(domain=domain, lam=float(lam))
                written += 1
            return written
        except Exception as e:
            logger.warning("save_domain_volatility failed: %s", e)
            return 0

    async def _load_domain_volatility(self) -> int:
        try:
            await self._ensure_volatility_table()
            rows = await self.unified_db.execute_query(
                "SELECT domain, lambda FROM unified.domain_volatility",
                fetch_all=True) or []
            for r in rows:
                self.domain_volatility[r["domain"]] = float(r["lambda"])
            if rows:
                logger.info("restored volatility for %d domain(s)", len(rows))
            return len(rows)
        except Exception as e:
            logger.warning("_load_domain_volatility failed: %s", e)
            return 0

    async def decay_belief(self, belief_id: str) -> Optional[BayesianBelief]:
        """Apply temporal decay to a belief WITHOUT new evidence.

        `_apply_temporal_decay` runs only inside `update_belief`, so a belief
        that stops receiving evidence -- a domain the substrate believes it has
        mastered and no longer explores -- never decays and its estimate
        ossifies. That is exactly how a FALSE competence estimate becomes
        permanent: unchecked, it is trusted forever.

        This drifts an unreinforced belief back toward 0.5 by the time elapsed
        since it was last touched, so stale competence erodes, re-enters the
        unstable set, and is re-verified against the world -- which corrects it
        if it was wrong. The clock is `last_updated` (time since the last touch,
        evidence or decay), so repeated calls apply only the new increment
        rather than compounding the same interval.
        """
        belief = self.beliefs.get(belief_id)
        if belief is None:
            return None
        now = datetime.now()
        dt_hours = (now - belief.last_updated).total_seconds() / 3600.0
        if dt_hours <= 0:
            return belief
        lambda_decay = self.domain_volatility.get(belief.domain, belief.decay_rate)
        factor = 1 - math.exp(-lambda_decay * dt_hours)
        current = belief.posterior_probability
        decayed = current + (0.5 - current) * factor
        if abs(decayed - current) > 1e-9:
            belief.posterior_probability = decayed
            belief.entropy = self._calculate_entropy(decayed)
            belief.last_updated = now
            belief.time_since_reinforcement = (
                now - belief.last_evidence_time).total_seconds() / 3600.0
            self.stats['temporal_decays_applied'] = self.stats.get(
                'temporal_decays_applied', 0) + 1
            await self.flush_belief(belief_id)
        return belief

    #: The table's shape, owned here. It had ten columns, none for what blocks
    #: an unknown, what would resolve it, or how it WAS resolved -- so even a
    #: reader could not have rebuilt one, and nothing read it (write-only state).
    _KNOWN_UNKNOWNS_DDL = (
        """CREATE TABLE IF NOT EXISTS unified.known_unknowns (
               unknown_id          VARCHAR PRIMARY KEY,
               question            TEXT NOT NULL,
               domain              VARCHAR,
               knowledge_state     VARCHAR NOT NULL,
               information_value   DOUBLE PRECISION,
               urgency             DOUBLE PRECISION,
               can_be_resolved     BOOLEAN,
               resolution_strategy TEXT,
               discovered_at       TIMESTAMP,
               resolution_attempts INTEGER)""",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS "
        "blocking_factors JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS "
        "required_information JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS "
        "resolution_cost DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS resolution TEXT",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS resolution_belief_id TEXT",
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS "
        "target JSONB NOT NULL DEFAULT '{}'::jsonb",
        # WHOSE QUESTION IT IS: NULL is the substrate's own; a person's id is
        # theirs, and the row is kept in their context.
        "ALTER TABLE unified.known_unknowns ADD COLUMN IF NOT EXISTS owner TEXT",
    )

    #: WHERE THE SUBSTRATE'S OWN QUESTIONS ARE READ FROM: the model. A new one is
    #: written through the manager's `write_store` (the learning store, where the
    #: model is a frozen release); a person's goes to their context.
    KNOWN_UNKNOWNS_STORE = "model"

    async def _ensure_known_unknowns_schema(self) -> None:
        if self._known_unknowns_schema_ready:
            return
        for store in self.unified_db.schema_stores():
            for statement in self._KNOWN_UNKNOWNS_DDL:
                await self.unified_db.execute_query(statement, commit=True, store=store)
        self._known_unknowns_schema_ready = True

    async def _write_known_unknown(self, unknown: KnownUnknown) -> bool:
        """Upsert one known unknown's WHOLE state, committed. True when written;
        False (and it stays buffered) when persistence is not up or the write
        failed -- never a silent drop."""
        import json as _json
        if not self.unified_db.initialized:
            self.persistence_drops += 1
            return False
        try:
            await self._ensure_known_unknowns_schema()
            from core.agents.memory_agent import memory_agent
            await memory_agent().hold_known_unknown(
                unknown_id=unknown.unknown_id, question=unknown.question,
                domain=unknown.domain, knowledge_state=unknown.knowledge_state.value,
                information_value=unknown.information_value, urgency=unknown.urgency,
                can_be_resolved=unknown.can_be_resolved,
                resolution_strategy=unknown.resolution_strategy,
                discovered_at=unknown.discovered_at,
                resolution_attempts=unknown.resolution_attempts,
                blocking_factors=_json.dumps(list(unknown.blocking_factors)),
                required_information=_json.dumps(list(unknown.required_information)),
                resolution_cost=unknown.resolution_cost, resolved_at=unknown.resolved_at,
                resolution=unknown.resolution,
                resolution_belief_id=unknown.resolution_belief_id,
                target=_json.dumps(dict(unknown.target or {})), owner=unknown.owner)
            return True
        except Exception as error:
            from core.capability import raise_if_structural
            raise_if_structural(error, "bayesian_uncertainty._write_known_unknown")
            logger.warning("known unknown %s not persisted (kept for replay): %s",
                           unknown.unknown_id, error)
            return False

    def _save_known_unknown(self, unknown: KnownUnknown):
        """Persist a known unknown from a sync caller: buffered, then written by a
        TRACKED task, so `drain_writes` awaits it at shutdown and
        `flush_pending_writes` replays it if the database was not up. It was an
        untracked `create_task` that could lose the write on exit, and a
        resolution was never written at all."""
        import asyncio
        self._pending_unknown_writes[unknown.unknown_id] = unknown
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return   # buffered; the next durable flush / startup load writes it
        task = loop.create_task(self._write_known_unknown(unknown))
        self._write_tasks.add(task)
        task.add_done_callback(lambda t: (
            self._write_tasks.discard(t),
            self._pending_unknown_writes.pop(unknown.unknown_id, None)
            if not t.cancelled() and not t.exception() and t.result()
            and self._pending_unknown_writes.get(unknown.unknown_id) is unknown else None))

    async def refresh_known_unknowns(self) -> Dict[str, int]:
        """Bring this instance's open set in line with the ONE store: add the
        open unknowns other instances registered, and drop the ones resolved
        elsewhere (never one this instance has not written yet)."""
        before = set(self.known_unknowns)
        stored_open = await self._load_known_unknowns()
        dropped = [uid for uid in before
                   if uid not in stored_open and uid not in self._pending_unknown_writes]
        for uid in dropped:
            self.known_unknowns.pop(uid, None)
        return {"open": len(self.known_unknowns),
                "added": len(set(self.known_unknowns) - before), "dropped": len(dropped)}

    async def _load_known_unknowns(self) -> set:
        """Restore every OPEN known unknown (not yet resolved) into memory.
        Returns the ids the store holds open."""
        import json as _json
        await self._ensure_known_unknowns_schema()
        # The substrate's own open questions only: a person's are their context,
        # never worked on by its research.
        rows = await self.unified_db.execute_query(
            "SELECT * FROM unified.known_unknowns "
            "WHERE resolved_at IS NULL AND knowledge_state <> $1 AND owner IS NULL",
            (KnowledgeState.KNOWN_KNOWN.value,), fetch_all=True,
            store=self.KNOWN_UNKNOWNS_STORE) or []
        loaded = 0
        for row in rows:
            def _list(value):
                if isinstance(value, str):
                    value = _json.loads(value)
                return list(value or [])
            unknown = KnownUnknown(
                unknown_id=row["unknown_id"],
                question=row["question"],
                domain=row["domain"] or "general",
                knowledge_state=KnowledgeState(row["knowledge_state"]),
                blocking_factors=_list(row["blocking_factors"]),
                required_information=_list(row["required_information"]),
                information_value=float(row["information_value"] or 0.0),
                urgency=float(row["urgency"] or 0.0),
                can_be_resolved=bool(row["can_be_resolved"]),
                resolution_cost=float(row["resolution_cost"] or 0.0),
                resolution_strategy=row["resolution_strategy"],
                discovered_at=row["discovered_at"] or datetime.now(),
                resolution_attempts=int(row["resolution_attempts"] or 0),
                target=(_json.loads(row["target"]) if isinstance(row["target"], str)
                        else dict(row["target"] or {})),
            )
            if unknown.unknown_id not in self.known_unknowns:
                self.known_unknowns[unknown.unknown_id] = unknown
                loaded += 1
        logger.info("Bayesian uncertainty: restored %d open known unknown(s)", loaded)
        return {row["unknown_id"] for row in rows}

    def _save_calibration_data(self, domain: str, predicted_confidence: float, actual_outcome: float):
        """Persist calibration data point to PostgreSQL. Fire-and-forget."""
        import asyncio
        async def _write():
            try:
                if not self.unified_db.initialized:
                    # A silent return made a dropped write indistinguishable from
                    # a successful one: epistemic state was computed, assumed
                    # persisted, and lost. Count and surface it so missing
                    # persistence is observable rather than inferred.
                    self.persistence_drops += 1
                    if self.persistence_drops == 1 or self.persistence_drops % 50 == 0:
                        logger.warning(
                            f"Epistemic persistence unavailable (database not "
                            f"initialized): {self.persistence_drops} write(s) dropped. "
                            f"This state will not survive a restart."
                        )
                    return
                from core.agents.memory_agent import memory_agent
                await memory_agent().hold_calibration(
                    domain=domain, prediction=f"{domain} confidence calibration",
                    confidence=predicted_confidence, outcome=actual_outcome,
                    timestamp=datetime.now())
            except Exception as e:
                logger.debug(f"_save_calibration_data non-fatal: {e}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            pass

    async def load_from_db(self):
        """Load persisted beliefs from PostgreSQL into memory at startup.

        Call once after unified_db is initialized, before the agent loop starts.
        Restores the belief graph so epistemic state survives process restarts.
        """
        import json as _json
        try:
            rows = await self.unified_db.execute_query(
                "SELECT belief_id, claim, domain, prior_probability, posterior_probability, "
                "uncertainty_type, entropy, evidence_for, evidence_against, update_count, last_updated "
                "FROM unified.beliefs",
                fetch_all=True,
            ) or []
            loaded = 0
            for row in rows:
                try:
                    b = BayesianBelief(
                        belief_id=row["belief_id"],
                        claim=row["claim"],
                        domain=row["domain"] or "general",
                        prior_probability=float(row["prior_probability"]),
                        likelihood=0.5,
                        posterior_probability=float(row["posterior_probability"]),
                        uncertainty_type=UncertaintyType(row["uncertainty_type"] or "epistemic"),
                        entropy=float(row["entropy"]),
                        evidence_for=_json.loads(row["evidence_for"]) if row["evidence_for"] else [],
                        evidence_against=_json.loads(row["evidence_against"]) if row["evidence_against"] else [],
                        update_count=int(row["update_count"] or 0),
                        last_updated=row["last_updated"] if row["last_updated"] else datetime.now(),
                    )
                    b.stored_count = b.update_count
                    self._register_belief(b)
                    self.stats["beliefs_tracked"] += 1
                    loaded += 1
                except Exception as row_err:
                    logger.debug(f"load_from_db: skipping malformed row: {row_err}")
            logger.info(f"Bayesian uncertainty: loaded {loaded} belief(s) from PostgreSQL")
            # What it knows it does not know survives a restart too. Nothing read
            # this table before: every restart began with no known unknowns, and
            # curiosity and the epistemic engine, which read this set, lost every
            # open question the substrate had found.
            await self._load_known_unknowns()
            # Restore adaptive decay rates too, so reflection's volatility work
            # survives a restart rather than resetting to the 0.01 default.
            await self._load_domain_volatility()
            # Persistence is up now — replay anything buffered before the DB was
            # ready, so no early belief update is lost.
            await self.flush_pending_writes()
        except Exception as e:
            logger.warning(f"load_from_db failed (non-fatal, starting with empty beliefs): {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics"""
        return {
            **self.stats,
            'active_beliefs': len(self.beliefs),
            'persistence_drops': self.persistence_drops,
            'persistence_healthy': self.persistence_drops == 0,
            'known_unknowns': len(self.known_unknowns),
            'calibrated_domains': len(self.calibrations),
            'high_value_unknowns': len(self.get_high_value_unknowns()),
            'overconfidence_rate': (
                self.stats['overconfidence_detected'] /
                max(self.stats['calibration_updates'], 1)
            )
        }

    async def apply_temporal_decay_to_all_beliefs(self) -> Dict[str, Any]:
        """
        Apply temporal decay to all beliefs (prevent epistemic ossification)

        Returns:
            Dictionary with decay statistics
        """
        try:
            now = datetime.now()
            beliefs_decayed = 0
            beliefs_removed = 0
            total_decay = 0.0

            for belief_id, belief in list(self.beliefs.items()):
                # Calculate time since last evidence
                time_delta = (now - belief.last_evidence_time).total_seconds() / 3600.0  # hours

                if time_delta > 1.0:  # Apply decay after 1 hour
                    # Apply temporal decay
                    decayed_prob = self._apply_temporal_decay(belief)

                    # Track decay amount
                    decay_amount = abs(belief.posterior_probability - decayed_prob)
                    total_decay += decay_amount

                    # Update belief
                    belief.posterior_probability = decayed_prob
                    belief.time_since_reinforcement = time_delta

                    beliefs_decayed += 1

                    # Remove belief if it decayed to near-neutral (0.45-0.55)
                    # Evidence count is the two evidence lists — BayesianBelief has
                    # no `evidence_count` attribute; reading one raised AttributeError
                    # the moment any belief reached the neutral band, aborting the
                    # whole decay loop and returning zeroed stats (a silent negative:
                    # "0 decayed" actually meant "the method crashed").
                    _evidence_count = len(belief.evidence_for) + len(belief.evidence_against)
                    if 0.45 <= decayed_prob <= 0.55 and _evidence_count < 3:
                        self._unregister_belief(belief_id)
                        beliefs_removed += 1
                        # DURABLE: the belief was dropped from memory, so drop its
                        # row too — otherwise load_from_db resurrects it.
                        await self._delete_belief_row(belief_id)
                    else:
                        # DURABLE: persist the decayed posterior so the decay
                        # survives a restart (was in-memory only).
                        await self._write_belief_row(belief, commit=True)

            avg_decay = total_decay / max(beliefs_decayed, 1)

            logger.info(f"✓ Applied decay to {beliefs_decayed} beliefs (avg decay: {avg_decay:.4f})")

            return {
                # The ACTUAL count of beliefs deleted this pass. This used to report
                # `len(neutral beliefs still present)` — the beliefs that were KEPT
                # (evidence_count >= 3), the inverse of "removed".
                'beliefs_decayed': beliefs_decayed,
                'avg_decay_amount': avg_decay,
                'beliefs_removed': beliefs_removed
            }

        except Exception as e:
            # A wiring bug (AttributeError/TypeError/...) must RE-RAISE, never be
            # recorded as "0 decayed" — that silent-negative is exactly how the
            # neutral-band AttributeError above aborted the loop invisibly. Genuine
            # runtime errors carry an explicit `error` marker so a caller can tell
            # failure from an empty result.
            from core.capability import raise_if_structural
            raise_if_structural(e, "bayesian_uncertainty.apply_temporal_decay_to_all_beliefs")
            logger.error(f"Failed to apply belief decay: {e}")
            return {
                'beliefs_decayed': 0,
                'avg_decay_amount': 0.0,
                'beliefs_removed': 0,
                'error': str(e),
            }

    async def check_belief_consistency(self) -> Dict[str, Any]:
        """
        Check belief consistency and propagate constraint updates

        Returns:
            Dictionary with consistency check results
        """
        try:
            violations_found = 0
            constraints_propagated = 0

            # Check for contradictions in belief graph.
            # The relationship/belief attribute names below were WRONG — a
            # BeliefRelationship exposes source_belief_id/target_belief_id/
            # relation_type (not belief_id_a/belief_id_b/relationship_type) and a
            # BayesianBelief has claim (not hypothesis) and no evidence_count. Every
            # one of those raised AttributeError on the first relationship, so this
            # repair pass was inert exactly when it had work to do — "0 violations"
            # meant "the method crashed", the silent-negative this fixes.
            for rel_id, relationship in self.relationships.items():
                belief_a = self.beliefs.get(relationship.source_belief_id)
                belief_b = self.beliefs.get(relationship.target_belief_id)

                if not belief_a or not belief_b:
                    continue

                evidence_a = len(belief_a.evidence_for) + len(belief_a.evidence_against)
                evidence_b = len(belief_b.evidence_for) + len(belief_b.evidence_against)

                # Check CONTRADICTS relationship
                if relationship.relation_type == RelationType.CONTRADICTS:
                    # If both beliefs have high confidence, that's a violation
                    if belief_a.posterior_probability > 0.7 and belief_b.posterior_probability > 0.7:
                        violations_found += 1
                        logger.warning(
                            f"⚠️  Consistency violation: {belief_a.claim} contradicts {belief_b.claim}"
                        )

                        # Reduce confidence in the weaker belief (fewer evidence items)
                        if evidence_a < evidence_b:
                            belief_a.posterior_probability *= 0.9
                            await self._write_belief_row(belief_a, commit=True)
                        else:
                            belief_b.posterior_probability *= 0.9
                            await self._write_belief_row(belief_b, commit=True)

                        constraints_propagated += 1

                # Check IMPLIES relationship
                elif relationship.relation_type == RelationType.IMPLIES:
                    # If A is likely and A→B, then B should be likely
                    if belief_a.posterior_probability > 0.7 and belief_b.posterior_probability < 0.3:
                        # Propagate implication
                        boost = (belief_a.posterior_probability - 0.5) * relationship.strength * 0.3
                        belief_b.posterior_probability = min(1.0, belief_b.posterior_probability + boost)
                        # DURABLE: the propagated constraint must persist too.
                        await self._write_belief_row(belief_b, commit=True)
                        constraints_propagated += 1

            logger.info(f"✓ Checked {len(self.relationships)} belief relationships")

            if violations_found > 0:
                logger.warning(f"⚠️  Found {violations_found} consistency violations")

            return {
                'violations_found': violations_found,
                'constraints_propagated': constraints_propagated,
                'relationships_checked': len(self.relationships)
            }

        except Exception as e:
            # Re-raise a wiring bug rather than report "0 violations" (which is what
            # the wrong-attribute-name crashes did — a repair pass inert exactly when
            # it had work). Runtime errors carry an explicit `error` marker.
            from core.capability import raise_if_structural
            raise_if_structural(e, "bayesian_uncertainty.check_belief_consistency")
            logger.error(f"Failed to check belief consistency: {e}")
            return {
                'violations_found': 0,
                'constraints_propagated': 0,
                'relationships_checked': 0,
                'error': str(e),
            }

    async def update_domain_volatility_metrics(self) -> Dict[str, Any]:
        """
        Update domain volatility metrics based on belief changes

        Returns:
            Dictionary with volatility update results
        """
        try:
            domains_updated = 0

            for domain, changes in self.domain_belief_changes.items():
                if len(changes) > 0:
                    # Calculate average change magnitude
                    avg_change = sum(changes) / len(changes)

                    # Calculate regime shift penalty
                    regime_penalty = min(self.domain_regime_shifts[domain] * 0.005, 0.05)

                    # Update volatility (λ)
                    new_lambda = 0.01 + (avg_change * 0.1) + regime_penalty
                    new_lambda = max(0.005, min(new_lambda, 0.1))  # Clamp to [0.005, 0.1]

                    self.domain_volatility[domain] = new_lambda

                    domains_updated += 1

            # DURABLE: persist the recomputed per-domain λ so adaptive decay
            # rates survive a restart (was in-memory only).
            if domains_updated:
                await self.save_domain_volatility()

            logger.info(f"✓ Updated volatility metrics for {domains_updated} domains")

            return {
                'domains_updated': domains_updated,
                'avg_volatility': sum(self.domain_volatility.values()) / max(len(self.domain_volatility), 1)
            }

        except Exception as e:
            # Re-raise wiring bugs. On a genuine runtime error report avg_volatility
            # as None (UNKNOWN) — the old 0.01 default read as a real, healthy "low
            # volatility" value, a fabricated-on-failure metric that hid the crash.
            from core.capability import raise_if_structural
            raise_if_structural(e, "bayesian_uncertainty.update_domain_volatility_metrics")
            logger.error(f"Failed to update domain volatility: {e}")
            return {
                'domains_updated': 0,
                'avg_volatility': None,
                'error': str(e),
            }

    def _adjust_evidence_with_domain_support(
        self,
        belief: BayesianBelief,
        evidence: Dict[str, Any],
        base_weight: float
    ) -> float:
        """
        INTEGRATION D: Adjust evidence weight based on cross-domain support from UDM

        Queries Universal Domain Master to check if similar beliefs in other domains
        support this evidence, boosting weight if cross-domain consensus exists.
        """
        try:
            # Check if evidence includes domain information
            evidence_domain = evidence.get('domain', belief.domain)

            # If evidence comes from a different high-credibility domain, boost weight
            high_credibility_domains = ['scientific', 'mathematical', 'technical']

            if evidence_domain in high_credibility_domains and evidence_domain != belief.domain:
                # Cross-domain evidence from high-credibility source
                return min(1.0, base_weight * 1.15)

            # If evidence comes from same domain, use base weight
            return base_weight

        except Exception as e:
            logger.debug(f"Domain-based evidence adjustment failed: {e}")
            return base_weight  # Fallback to base weight


# Global instance
_uncertainty_system: Optional[BayesianUncertaintySystem] = None


def get_uncertainty_system() -> BayesianUncertaintySystem:
    """Get or create global uncertainty system"""
    global _uncertainty_system

    if _uncertainty_system is None:
        _uncertainty_system = BayesianUncertaintySystem()

    return _uncertainty_system


# Alias for compatibility
def get_bayesian_uncertainty() -> BayesianUncertaintySystem:
    """Alias for get_uncertainty_system()"""
    return get_uncertainty_system()
