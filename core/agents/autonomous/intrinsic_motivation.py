#!/usr/bin/env python3
"""
Intrinsic Motivation System
Implements 7-dimensional intrinsic motivation for autonomous behavior
(what the substrate pursues to get better at its job — by learning)
"""

from core.capability import raise_if_structural
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import json
import numpy as np
import math
import random
import time
import hashlib

from core.database import LyricUnifiedDatabase

logger = logging.getLogger(__name__)


class MotivationDimension:
    """Individual dimension of intrinsic motivation"""
    CURIOSITY = "curiosity"  # Novel exploration
    COMPETENCE = "competence"  # Skill improvement
    NOVELTY = "novelty"  # New experiences
    MASTERY = "mastery"  # Deep understanding
    AUTONOMY = "autonomy"  # Self-direction
    SOCIAL = "social"  # Collaboration
    IMPACT = "impact"  # Meaningful change


@dataclass
class MotivationWeights:
    """Weights for each motivation dimension"""
    curiosity: float = 1.2  # Highest priority
    competence: float = 0.9
    novelty: float = 0.85
    mastery: float = 0.7
    autonomy: float = 1.0
    social: float = 0.9
    impact: float = 0.8


@dataclass
class IntrinsicReward:
    """Reward for a single event — deliberately not a motivation dimension.

    A dimension is a drive level ("how strongly is curiosity active now").
    A reward is event-scoped ("how much did this event advance that drive").
    They are not interchangeable: the competence drive is an inverted-U, so
    delegating competence_reward to _calculate_competence would pay the system
    least exactly when it performs best.
    """
    dimension: str
    reward_value: float
    components: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _numeric_vector(experience: Dict[str, Any]) -> Dict[str, float]:
    """Numeric fields of an experience, for novelty comparison."""
    if not isinstance(experience, dict):
        return {}
    return {
        k: float(v)
        for k, v in experience.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def _normalised_distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Mean per-field relative difference over the fields the two share."""
    shared = set(a) & set(b)
    if not shared:
        return 1.0
    total = 0.0
    for key in shared:
        scale = max(abs(a[key]), abs(b[key]), 1.0)
        total += min(1.0, abs(a[key] - b[key]) / scale)
    return total / len(shared)


@dataclass
class MotivationProfile:
    """Complete motivation profile for the system"""
    dimensions: Dict[str, float] = field(default_factory=dict)
    weights: MotivationWeights = field(default_factory=MotivationWeights)

    # Instantaneous drive level: the weighted mean of the 7 dimensions, in
    # [0,1]. Recomputed from scratch on every calculate_motivation() call.
    #: The overall drive level — the weighted mean of the drives measured.
    #: None when NOTHING could be measured; appraisal reads it as its
    #: `activation` and already treats None as unmeasured rather than flat.
    total_intrinsic_reward: Optional[float] = None

    # Accumulated event rewards. A DIFFERENT quantity: unbounded running sum of
    # what individual experiences were worth to the drives.
    #
    # These two used to share the field above. log_intrinsic_reward() did
    # `+= reward_value` and calculate_motivation() did `= weighted_mean(...)`,
    # so every persisted reward's contribution was wiped on the next motivation
    # refresh — the reward→drive edge could never survive one cycle.
    accumulated_event_reward: float = 0.0
    event_reward_count: int = 0

    influence_percentage: float = 0.60  # share of pursuit decisions motivation weighs in on
    last_updated: Optional[datetime] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def mean_event_reward(self) -> float:
        """Average worth of recent experience to the drives. [-1, 1]."""
        if not self.event_reward_count:
            return 0.0
        return self.accumulated_event_reward / self.event_reward_count


@dataclass
class GoalEmbedding:
    """Stored goal with embedding for novelty tracking"""
    description: str
    embedding: np.ndarray
    theme: str
    component: str
    abstraction_level: str
    objective_type: str
    timestamp: datetime
    repeat_count: int = 0


@dataclass
class MutationDimensions:
    """Dimensions that can be mutated in goals"""
    component: str  # Target component
    abstraction_level: str  # low/medium/high
    objective_type: str  # explore/optimize/fix/learn
    time_horizon: str  # immediate/short/long



def _unmeasured_stats(domain: str, reason: str) -> Dict[str, Any]:
    """Honest 'no measurement' result.

    success_rate/failure_rate/confidence are None — NOT 0.5. A fabricated
    midpoint made 0 observations indistinguishable from a genuinely coin-flip
    domain, and consumers silently inherited it as if it were data. Callers
    needing a prior must apply one explicitly, with provenance.
    """
    return {
        "success_rate": None,
        "failure_rate": None,
        "avg_outcome_label_confidence": None,
        "successes": 0,
        "failures": 0,
        "total_attempts": 0,
        "measured": False,
        "unmeasured_reason": reason,
        "domain": domain,
    }


@dataclass
class CapabilityEvidence:
    """What we have OBSERVED about a capability — evidence, not a verdict.

    Deliberately stops short of `estimated_competence`. Raw success rate is not
    competence: 4/4 causal successes and 8/9 technical successes both look
    "high" while resting on very different support, and 1/1 is not mastery.
    Producing a single maturity number here would recreate the defect this
    layer exists to prevent — an authoritative-looking scalar with no
    justification for its aggregation.

    task_diversity / difficulty_coverage / recency_coverage are None until
    something can actually measure them. They are named so their absence is
    visible rather than quietly assumed adequate.
    """

    capability: str
    successes: int = 0
    failures: int = 0
    attempts: int = 0
    empirical_success_rate: Optional[float] = None

    # "How sure were we this task succeeded?" — NOT confidence in the rate.
    outcome_label_confidence: Optional[float] = None

    task_diversity: Optional[float] = None
    difficulty_coverage: Optional[float] = None
    recency_coverage: Optional[float] = None

    evidence_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_domain_stats(cls, capability: str, stats: Dict[str, Any]) -> "CapabilityEvidence":
        """Lift statistical observation into structured evidence. No inference."""
        return cls(
            capability=capability,
            successes=int(stats.get("successes", 0) or 0),
            failures=int(stats.get("failures", 0) or 0),
            attempts=int(stats.get("total_attempts", 0) or 0),
            empirical_success_rate=stats.get("success_rate"),
            outcome_label_confidence=stats.get("avg_outcome_label_confidence"),
        )

    @property
    def is_measured(self) -> bool:
        return self.attempts > 0

    @property
    def support(self) -> str:
        """Qualitative sample support. Names the sparsity the ratio hides."""
        if self.attempts == 0:
            return "none"
        if self.attempts < 3:
            return "anecdotal"
        if self.attempts < 10:
            return "sparse"
        return "moderate"


@dataclass
class Fitness:
    """The substrate's model fitness RIGHT NOW — the quantity whose rate of
    change is valence (see docs/AFFECT_ARCHITECTURE.md §2).

    Each term is in [0,1] with higher = fitter, or None when it could not be
    measured this tick. A None term is EXCLUDED from `scalar` (renormalised over
    what was measured) and named in `unmeasured` — a missing input never reads as
    zero fitness. `scalar` is None only when nothing at all was measurable.
    """
    competence: Optional[float]     # saturating fn of executable-operator count
    coherence: Optional[float]      # 1 − mean belief entropy (belief-model settledness)
    certainty: Optional[float]      # 1 − mean component epistemic_uncertainty
    measured: List[str] = field(default_factory=list)
    unmeasured: List[str] = field(default_factory=list)
    scalar: Optional[float] = None
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class DriveReading:
    """One drive, as it was actually measured this tick.

    `level` is the mean of the terms that could be read, in [0,1] with higher =
    more to gain in this direction, or None when NOTHING about the drive could be
    measured. A drive is never a baseline: the terms it rests on are named in
    `terms`, the ones that were quiet are named in `unmeasured`, and `sources`
    carries the raw counts the terms were derived from, so a level can be argued
    with rather than taken on trust.
    """
    name: str
    level: Optional[float]
    terms: Dict[str, float] = field(default_factory=dict)
    unmeasured: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)



@dataclass
class CoreAffect:
    """The substrate's felt state: valence (getting better/worse) and arousal
    (how much is moving). Both are None when a trend cannot yet be derived — no
    prior reading, or no fitness term measured in BOTH readings. A feeling is
    reported only when it is grounded in a real, like-for-like change; it is
    never fabricated from a single point or from a change in what was measured.
    """
    valence: Optional[float]        # signed: rising fitness (+) / falling (−), (−1,1)
    arousal: Optional[float]        # intensity of change, [0,1]
    delta: Optional[float]          # the like-for-like fitness change valence is of
    measured_over: List[str] = field(default_factory=list)  # terms the delta used
    fitness: Optional["Fitness"] = None                     # the current reading
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class AffectState:
    """The substrate's affect as PERSISTENT STATE — not a reading.

    This is what is rehydrated on startup and read from the substrate's runtime:
    the current named emotion (from appraisal), why it holds (cause), how strong
    (intensity), plus the slow mood it sits on. It is a FACT carried across
    restarts — the substrate resumes in doubt if it went down in doubt; no new
    appraisal is required merely because the process restarted. `version`
    increments on each affect TRANSITION (a new appraisal changing the emotion),
    so the state has provenance, not just a value.
    """
    emotion: Optional[str]        # dominant named emotion: eagerness/doubt/frustration/satisfaction
    intensity: Optional[float]    # its magnitude, [0,1]
    cause: Optional[str]          # attribution — why (e.g. strategy_failure)
    #: WHAT the feeling is about. `cause` is the attribution and answers WHY an
    #: outcome went as it did; this answers ABOUT WHAT, and the two are not the
    #: same question. Without it an emotion can only be waited out.
    about: Optional[str]
    valence: float                # persistent mood valence (fitness trend), decayed to read
    arousal: float
    baseline: float               # temperament: the trait the mood varies around
    version: int                  # increments per affect transition — provenance
    updated_at: Optional[str] = None
    loaded: bool = False          # True if rehydrated from the store; False = cold start

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class Mood:
    """The substrate's persistent core affect — a slow, object-less valence×arousal
    it carries between sessions, varying around a slowly-drifting baseline (its
    temperament). This is the felt state that survives restart: the substrate wakes
    in the mood it earned. `loaded` distinguishes a restored mood from an honest
    cold-start neutral (never a fabricated prior mood)."""
    valence: float          # slow core-affect valence, [−1,1]
    arousal: float          # slow activation, [0,1]
    baseline: float         # the trait level valence varies around (allostatic)
    event_count: int        # experienced affective ticks integrated so far
    loaded: bool = False    # True if restored from Postgres; False = cold start

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


class IntrinsicMotivationSystem:
    """
    Intrinsic Motivation System

    Calculates motivation across 7 dimensions:
    1. Curiosity (1.2x) - Novel exploration
    2. Competence (0.9x) - Skill improvement
    3. Novelty (0.85x) - New experiences
    4. Mastery (0.7x) - Deep understanding
    5. Autonomy (1.0x) - Self-direction
    6. Social (0.9x) - Collaboration
    7. Impact (0.8x) - Meaningful change

    Weighs in on what the substrate pursues to get better at its job (by learning)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.active = False

        # Motivation profile
        self.profile = MotivationProfile()
        self.weights = MotivationWeights()

        # The previous fitness reading, held so valence (its RATE of change) can be
        # computed on the next tick. None until the first reading — the substrate
        # cannot feel a trend from a single point (docs/AFFECT_ARCHITECTURE.md §2).
        self._last_fitness: Optional["Fitness"] = None

        # Persistent CORE AFFECT (mood) — the slow, durable felt STATE. It is not
        # driven by any loop: real events (task outcomes, competence/belief change)
        # update it through update_affect(), and it fades toward the baseline over
        # elapsed WALL-CLOCK time, computed lazily on read (mood()/valence()), so
        # the mood is always current without anything polling it. Loaded from
        # Postgres on initialize(); neutral cold-start defaults.
        self._mood_valence: float = 0.0
        self._mood_arousal: float = 0.0
        self._baseline_valence: float = 0.0   # temperament: the trait mood varies around
        self._affect_event_count: int = 0
        self._affect_loaded: bool = False
        # The current named affect (a FACT that persists and rehydrates as-is —
        # the substrate resumes in this emotion on restart, no re-appraisal).
        self._affect_emotion: Optional[str] = None
        self._affect_intensity: Optional[float] = None
        self._affect_cause: Optional[str] = None
        #: what the current emotion is ABOUT (appraisal's object), so the feeling
        #: can be addressed rather than only outlived.
        self._affect_about: Optional[str] = None
        self._affect_about_domain: Optional[str] = None
        self._affect_version: int = 0
        #: doubts that faded and were handed to the belief authority as open
        #: questions, and doubts that faded with no object to make a question of.
        #: The second is an honest gap, counted rather than hidden.
        self._questions_kept: int = 0
        self._questions_lost: int = 0
        #: wall-clock anchor of the last affect update; the decay-on-read measures
        #: elapsed time from here. None until the first update (nothing to decay).
        self._last_affect_at: Optional[datetime] = None

        # Database for persistence (optional - gracefully degrades)
        self.db = None


        # Configuration
        self.influence_percentage = self.config.get("influence_percentage", 0.60)
        self.profile.influence_percentage = self.influence_percentage

        # Motivation history (recent calculations)
        self.history_limit = self.config.get("history_limit", 100)
        #: History entries recorded since the profile was last saved: the store
        #: APPENDS them, so entries recorded by other instances are kept too.
        self._unsaved_history: List[Dict[str, Any]] = []

        # Previously generated goals, to avoid repetition, for this process.
        self._recent_goal_descriptions: List[str] = []
        self._max_recent_goals = 20

        # ========== NEW: 4 Advanced Features ==========

        # 1. NOVELTY TRACKER: Stores embeddings of intrinsic goals
        self._goal_embeddings: List[GoalEmbedding] = []
        self._embedding_service = None  # Set during initialize()
        # Similarity threshold for DOWNSTREAM novelty/dedup guidance only. It is
        # NOT a formation gate: goal formation is deterministic and never vetoed by
        # the similarity model (severing MiniLM must not change whether a goal forms).
        self._novelty_threshold = 0.75

        # 2. ENTROPY INJECTOR: Non-deterministic boot-time context
        self._boot_entropy = self._generate_boot_entropy()
        logger.info(f"Boot entropy injected: {self._boot_entropy[:50]}...")

        # Use boot entropy to seed per-session sampling so early exploration
        # does not converge to identical goal distributions across restarts.
        try:
            self._boot_entropy_seed = int(hashlib.sha256(self._boot_entropy.encode()).hexdigest()[:8], 16)
        except Exception:
            self._boot_entropy_seed = random.randint(0, 2**32 - 1)
        self._entropy_rng = random.Random(self._boot_entropy_seed)
        try:
            self._entropy_np_rng = np.random.default_rng(self._boot_entropy_seed)
        except Exception:
            self._entropy_np_rng = None

        # 3. EXPLORATION DECAY: Theme-based decay tracking
        self._theme_counts: Dict[str, int] = {}  # theme -> repeat_count
        self._decay_rate = 0.3  # Decay coefficient for exp(-decay_rate * count)

        # 4. GOAL MUTATION ENGINE: Dimensional mutation parameters
        self._mutation_enabled = True
        self._mutation_dimensions = {
            'components': ['memory_agent', 'neural_bridge', 'learning', 'security'],
            'abstraction_levels': ['low', 'medium', 'high'],
            'objective_types': ['research', 'explore', 'learn', 'analyze', 'optimize', 'investigate', 'improve'],
            'time_horizons': ['immediate', 'short', 'long']
        }
        # ==============================================

        # UNCERTAINTY QUANTIFICATION: Component metrics tracking
        self._component_baselines: Dict[str, Dict[str, float]] = {}  # component -> metrics baseline
        self._metric_history: Dict[str, List[Dict[str, float]]] = {}  # component -> history of metrics

        # Weighted priority coefficients
        self._priority_weights = {
            'epistemic_uncertainty': 1.0,
            'impact_radius': 0.8,
            'performance_degradation': 0.6,
            'novelty_potential': 0.4,
            'recent_exploration_penalty': -0.5
        }


        #: The last full drive measurement, keyed by drive name — what each
        #: level was read from, and which sources were quiet.
        self._drive_readings: Dict[str, DriveReading] = {}
        # Initialize dimensions
        self._initialize_dimensions()

        logger.info("Intrinsic motivation system initialized with advanced novelty features")


    async def log_intrinsic_reward(
        self,
        task_id: str,
        task_type: str,
        reward_value: float,
        outcome_quality: float,
        success: bool,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Persist an intrinsic reward score to the unified.intrinsic_motivation table.

        This is the long-term memory for the reward system: every task outcome
        is recorded so competence calibration and curiosity calculations have
        real historical data to work from across restarts.

        Schema: id, timestamp, motivation_type, score, context, metadata
        """
        if not self.db:
            return
        try:
            import uuid as _uuid
            import json as _json
            _row_id = str(_uuid.uuid4())
            _meta = _json.dumps({
                'task_id': task_id,
                'task_type': task_type,
                'outcome_quality': outcome_quality,
                'success': success,
                **(extra or {}),
            })
            await self.db.execute_query(
                """
                INSERT INTO intrinsic_motivation
                    (id, timestamp, motivation_type, score, context, metadata)
                VALUES ($1, NOW(), 'task_outcome', $2, $3, $4)
                """,
                params=(_row_id, reward_value, task_id[:64], _meta),
                commit=True,
            )
            # Accumulate on the EVENT reward, not the drive level — writing to
            # total_intrinsic_reward here meant calculate_motivation() erased it.
            self.profile.accumulated_event_reward += reward_value
            self.profile.event_reward_count += 1
            logger.debug(
                f"Persisted intrinsic reward: task={task_id[:8]} "
                f"type={task_type} reward={reward_value:.3f} success={success}"
            )
        except Exception as _e:
            logger.warning(f"log_intrinsic_reward DB write failed (non-fatal): {_e}")

    async def initialize(self) -> bool:
        """Bring the motivation system up. Mirror of shutdown().

        The coordinator's module loop calls initialize() on every subsystem;
        this class never had one, so the loop raised AttributeError and the
        whole coordinator failed to start. It also left three fields at their
        constructor defaults forever:

          - self.db is None, so log_intrinsic_reward() returns early and
            theme counts always read 0 (making novelty decay exp(0) = 1.0,
            i.e. never decaying)
          - self.active is False, so calculate_motivation() returns {}
          - self._embedding_service is None, which line 154 documents as
            "Set during initialize()"

        Both dependencies are required, not optional. PostgreSQL is the live
        store and all-MiniLM-L6-v2 is present locally. If either is missing
        that is a real fault: without the database no motivation reward is
        ever persisted, and without embeddings every goal looks equally novel.
        Both are logged as errors so the failure is visible rather than silent.
        """
        try:
            self._initialize_dimensions()

            from core.database import get_database_manager
            self.db = get_database_manager()

            from core.memory.utils.embedding_service import get_embedding_service
            self._embedding_service = get_embedding_service()

            await self.load_profile()
            await self._restore_event_rewards()
            await self._load_affect()   # restore persistent mood — wake in the mood it earned

            self.active = True
            logger.info("Intrinsic motivation system initialized")
            return True

        except Exception as e:
            logger.error(
                f"Failed to initialize motivation system: {e} — "
                f"rewards will not persist and goal novelty cannot be computed"
            )
            return False

    async def shutdown(self) -> None:
        """Shutdown the motivation system"""
        try:
            # Save current profile
            await self.save_profile()
            self.active = False
            logger.info("Intrinsic motivation system shutdown")
        except Exception as e:
            logger.error(f"Error during motivation shutdown: {e}")

    # ========== FEATURE 1: NOVELTY TRACKER ==========
    def _generate_boot_entropy(self) -> str:
        """
        FEATURE 2: ENTROPY INJECTOR
        Generate non-deterministic boot-time context for exploration variance
        """
        # Combine multiple entropy sources
        timestamp = str(time.time())
        process_id = str(random.randint(1000, 9999))
        random_bytes = str(random.getrandbits(256))

        # Create unique hash
        entropy_string = f"{timestamp}_{process_id}_{random_bytes}"
        entropy_hash = hashlib.sha256(entropy_string.encode()).hexdigest()

        # Add human-readable component
        boot_context = f"BOOT_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{entropy_hash[:16]}"
        return boot_context



    async def _store_goal_embedding(self, goal_description: str, theme: str,
                                   component: str, abstraction: str, objective: str) -> None:
        """
        FEATURE 1: NOVELTY TRACKER
        Store goal embedding for similarity checking
        """
        try:
            # Get embedding service if not initialized
            if not self._embedding_service:
                try:
                    from core.memory.utils.embedding_service import get_embedding_service
                    self._embedding_service = get_embedding_service()
                except Exception as e:
                    logger.warning(f"Embedding service unavailable: {e}")
                    return

            # Generate embedding for goal description
            embedding = self._embedding_service.generate_embedding(goal_description)
            if embedding is None:
                logger.warning("Failed to generate embedding for goal")
                return

            # Store to database
            await self._store_goal_embedding_to_db(
                goal_description, theme, component, abstraction, objective,
                np.array(embedding)
            )

            # Also maintain in-memory cache for quick similarity checks (last 100)
            goal_emb = GoalEmbedding(
                description=goal_description,
                embedding=np.array(embedding),
                theme=theme,
                component=component,
                abstraction_level=abstraction,
                objective_type=objective,
                timestamp=datetime.now(),
                repeat_count=await self._get_theme_count_from_db(theme)
            )

            self._goal_embeddings.append(goal_emb)

            # Keep only last 100 embeddings in cache
            if len(self._goal_embeddings) > 100:
                self._goal_embeddings = self._goal_embeddings[-100:]

            logger.debug(f"Stored goal embedding: {theme} (cache: {len(self._goal_embeddings)})")

        except Exception as e:
            logger.error(f"Error storing goal embedding: {e}")

    async def _calculate_goal_similarity(self, goal_description: str) -> Tuple[float, Optional[GoalEmbedding]]:
        """
        FEATURE 1: NOVELTY TRACKER
        Calculate cosine similarity with stored goals
        Returns: (max_similarity, most_similar_goal)
        """
        try:
            if not self._embedding_service:
                return 0.0, None

            # Load from database if cache is empty
            if not self._goal_embeddings:
                self._goal_embeddings = await self._load_goal_embeddings_from_db(limit=100)

            if not self._goal_embeddings:
                return 0.0, None

            # Generate embedding for new goal
            new_embedding = self._embedding_service.generate_embedding(goal_description)
            if new_embedding is None:
                return 0.0, None

            new_emb = np.array(new_embedding)

            # Calculate cosine similarity with all stored goals
            max_similarity = 0.0
            most_similar = None

            for stored_goal in self._goal_embeddings:
                similarity = self._cosine_similarity(new_emb, stored_goal.embedding)
                if similarity > max_similarity:
                    max_similarity = similarity
                    most_similar = stored_goal

            return max_similarity, most_similar

        except Exception as e:
            logger.error(f"Error calculating goal similarity: {e}")
            return 0.0, None

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        try:
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot_product / (norm_a * norm_b))
        except Exception:
            return 0.0

    async def _calculate_exploration_decay(self, theme: str, base_weight: float = 1.0) -> float:
        """
        FEATURE 3: EXPLORATION DECAY
        Calculate decayed weight based on theme repetition
        Formula: theme_weight = base_weight * exp(-decay_rate * repeat_count)
        """
        # Get count from database
        repeat_count = await self._get_theme_count_from_db(theme)

        # Apply exponential decay
        decayed_weight = base_weight * math.exp(-self._decay_rate * repeat_count)

        logger.debug(f"Theme '{theme}' decay: {repeat_count} repeats → weight {decayed_weight:.3f}")
        return decayed_weight


    async def _increment_theme_count(self, theme: str) -> None:
        """Increment repetition count for a theme"""
        await self._increment_theme_count_in_db(theme)
        # Update in-memory cache as well
        self._theme_counts[theme] = self._theme_counts.get(theme, 0) + 1
        logger.debug(f"Theme '{theme}' count: {self._theme_counts[theme]}")

    def _extract_theme(self, goal_description: str) -> str:
        """Extract high-level theme from goal description"""
        goal_lower = goal_description.lower()

        # Map keywords to themes
        if any(word in goal_lower for word in ['chaos', 'resilience', 'fault injection', 'create_chaos', 'failure propagation', 'recovery']):
            return 'resilience'
        elif any(word in goal_lower for word in ['compare', 'comparative', 'benchmark', 'delta', 'vs ', 'versus', 'pattern']):
            return 'comparative'
        elif any(word in goal_lower for word in ['security', 'audit', 'vulnerability', 'threat', 'authentication', 'sanitiz']):
            return 'security'
        elif any(word in goal_lower for word in ['performance', 'optimize', 'speed', 'latency', 'throughput', 'concurrent']):
            return 'performance'
        elif any(word in goal_lower for word in ['error', 'bug', 'fail', 'crash', 'fix', 'flaky', 'regression']):
            return 'debugging'
        elif any(word in goal_lower for word in ['web_search', 'http_request', 'research', 'paper', 'arxiv', 'framework']):
            return 'world_awareness'
        elif any(word in goal_lower for word in ['learn', 'understand', 'analyze', 'study', 'explore', 'investigate']):
            return 'learning'
        elif any(word in goal_lower for word in ['test', 'run_pytest', 'verify', 'validate', 'coverage']):
            return 'testing'
        elif any(word in goal_lower for word in ['improve']):
            return 'self_improvement'
        elif any(word in goal_lower for word in ['trace', 'architecture', 'execution path', 'neural_bridge', 'source']):
            return 'architecture'
        elif any(word in goal_lower for word in ['data', 'storage', 'database', 'memory']):
            return 'data'
        else:
            return 'exploration'

    def _extract_component(self, goal_description: str) -> str:
        """Extract target component from goal description"""
        goal_lower = goal_description.lower()

        for component in self._mutation_dimensions['components']:
            if component.lower() in goal_lower:
                return component

        # Default
        return 'system'

    def _extract_abstraction(self, goal_description: str) -> str:
        """Extract abstraction level from goal description"""
        goal_lower = goal_description.lower()

        # High-level indicators
        if any(word in goal_lower for word in ['architecture', 'system', 'design', 'strategy']):
            return 'high'
        # Low-level indicators
        elif any(word in goal_lower for word in ['implementation', 'code', 'function', 'specific']):
            return 'low'
        # Default to medium
        else:
            return 'medium'

    def _extract_objective(self, goal_description: str) -> str:
        """Extract objective type from goal description"""
        goal_lower = goal_description.lower()

        for objective in self._mutation_dimensions['objective_types']:
            if objective.lower() in goal_lower:
                return objective

        # Default based on keywords
        if any(word in goal_lower for word in ['explore', 'investigate', 'discover']):
            return 'explore'
        elif any(word in goal_lower for word in ['fix', 'resolve', 'repair']):
            return 'fix'
        elif any(word in goal_lower for word in ['optimize', 'improve', 'enhance']):
            return 'optimize'
        else:
            return 'learn'

    # =================================================

    def _initialize_dimensions(self) -> None:
        """No drive has been measured yet, so none is held.

        This used to seed all seven at 0.5. A drive nobody has measured is not a
        drive at half strength — it is an absent reading, and 0.5 is
        indistinguishable in the store from a genuine mid-level pull. The
        substrate reported "how strongly each drive is active right now" as seven
        0.5s until the first refresh, and anything that failed to measure fell
        back to the same number. Absence is now absence.
        """
        self.profile.dimensions = {}

    async def calculate_motivation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate intrinsic motivation based on current context

        Args:
            context: Current system context (perception, goals, tasks, etc.)

        Returns:
            Dict with motivation state including dimensions and total reward
        """
        if not self.active:
            logger.warning("Motivation system not active")
            return {}

        try:
            # THE QUEUE IS AN AUTHORITY, NOT A CONTEXT ITEM. Autonomy and social
            # are read from what the substrate is actually holding and who filed
            # it, so they come from the queue itself rather than whatever the
            # caller happened to pass.
            queue = context.get("task_queue")
            if queue is None:
                from .queue_authority import get_queue_authority
                queue = get_queue_authority()

            # Recorded task outcomes — the only honest source for "how much of
            # what I do actually fails".
            performance_stats = await self.get_domain_performance_stats(domain="all")

            # EVERY DRIVE, MEASURED. Each reading carries the terms it rests on
            # and names the ones that were unreadable, so `dimensions` holds only
            # levels that were genuinely measured — a drive nothing could be read
            # for is ABSENT, not 0.5.
            readings = [
                await self._measure_curiosity(),
                await self._measure_competence(),
                await self._measure_novelty(),
                await self._measure_mastery(),
                await self._measure_autonomy(queue),
                await self._measure_social(queue),
                await self._measure_impact(performance_stats),
            ]
            self._drive_readings = {r.name: r for r in readings}
            dimensions = {r.name: r.level for r in readings if r.level is not None}
            unreadable = [r.name for r in readings if r.level is None]
            if unreadable:
                logger.info("drives unmeasured this tick (absent, not defaulted): %s",
                            ", ".join(unreadable))

            # Update profile
            self.profile.dimensions = dimensions
            self.profile.last_updated = datetime.now()

            # Calculate total intrinsic reward (weighted sum)
            total_reward = self._calculate_total_reward(dimensions)
            self.profile.total_intrinsic_reward = total_reward

            # Add to history
            self._add_to_history({
                "timestamp": datetime.now().isoformat(),
                "dimensions": dimensions.copy(),
                "total_reward": total_reward
            })

            # Return motivation state
            return {
                "dimensions": dimensions,
                "weights": {
                    "curiosity": self.weights.curiosity,
                    "competence": self.weights.competence,
                    "novelty": self.weights.novelty,
                    "mastery": self.weights.mastery,
                    "autonomy": self.weights.autonomy,
                    "social": self.weights.social,
                    "impact": self.weights.impact
                },
                "total_reward": total_reward,
                # WHAT EACH DRIVE WAS READ FROM. A level on its own cannot be
                # argued with; this carries the terms and the raw counts under
                # them, and names the sources that were quiet.
                "drive_readings": {name: r.to_dict()
                                   for name, r in self._drive_readings.items()},
                "drives_unmeasured": unreadable,
                # Drive LEVEL (total_reward, weighted mean of the 7 dimensions)
                # and the WORTH of recent experience are different quantities.
                # They shared one field until now, so the second was erased on
                # every refresh and could never reach behaviour.
                "mean_event_reward": self.profile.mean_event_reward,
                "event_reward_count": self.profile.event_reward_count,
                "influence_percentage": self.influence_percentage,
                "timestamp": self.profile.last_updated.isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to calculate motivation: {e}")
            return {}

    # =========================================================================
    # DRIVE MEASUREMENT
    # =========================================================================
    #
    # A drive is HOW MUCH THERE IS TO GAIN in one direction, measured from the
    # authorities that own the evidence — never a baseline, never the shape of a
    # goal's wording.
    #
    # What these replace. Every drive was a constant (0.5, or 0.7, or 0.4)
    # adjusted by keyword matches on goal text — `"explore" in description` moved
    # curiosity, `"help"` moved social, `"master"` moved mastery — and each
    # swallowed its exceptions into the same middling default. So a drive could
    # be changed by how a goal was PHRASED, could not be told apart from an
    # unmeasured one, and read 0.5 whenever anything went wrong. The appraisal
    # module states the rule they broke: "Every field is sourced from something
    # already measured elsewhere. Where a signal is genuinely unavailable it is
    # None — never imputed to a middling default."
    #
    # THREE PROPERTIES, held by every drive below:
    #
    #   * MULTI-SOURCE. No drive is one axis. Each is the mean of independent
    #     terms read from DIFFERENT authorities — the rule store, the
    #     demonstration store, the epistemic engine, the belief authority, the
    #     domain authority, the queue, appraisal — so no single reading can carry
    #     a drive on its own, and a drive does not collapse when one source is
    #     quiet.
    #   * MEASURED-ONLY. A term that cannot be read this tick is NAMED in
    #     `unmeasured` and excluded from the mean; it never contributes a zero
    #     and never a half. A drive with no measurable term at all is None, and
    #     absent from `dimensions`.
    #   * ONE DIRECTION. Every drive reads as OPPORTUNITY: high means there is
    #     something to gain here. The old set was inconsistent — competence was
    #     "opportunities for skill improvement exist" while autonomy was "the
    #     system HAS freedom", a satisfaction reading — so the two moved opposite
    #     ways on the same event and their weighted sum meant nothing.

    #: How many open items saturate a count-based term. A count is not a level:
    #: these convert "how many" into "how much pull" with a smooth knee, so one
    #: more open question matters a lot at 2 and little at 200. UNITS, not
    #: setpoints — the shape is stated here rather than buried in each term.
    _OPEN_QUESTION_SCALE = 12.0
    _UNSTABLE_REGION_SCALE = 8.0
    _PENDING_INDUCTION_SCALE = 5.0

    @staticmethod
    def _saturate(count: float, scale: float) -> float:
        """A count as a level in [0,1), with a smooth knee at `scale`."""
        import math
        return math.tanh(max(0.0, float(count)) / float(scale))

    @staticmethod
    def _drive_level(terms: Dict[str, Optional[float]]) -> Tuple[Optional[float],
                                                                 Dict[str, float],
                                                                 List[str]]:
        """The drive as the mean of its MEASURED terms, with the rest named.

        Returns (level, measured_terms, unmeasured_names). An unmeasured term is
        excluded from the mean rather than contributing a zero, so a drive is
        never dragged down by a source that was simply quiet — the same rule
        `sense_fitness` already holds for fitness.
        """
        measured = {k: max(0.0, min(1.0, float(v)))
                    for k, v in terms.items() if v is not None}
        unmeasured = [k for k, v in terms.items() if v is None]
        level = (sum(measured.values()) / len(measured)) if measured else None
        return level, measured, unmeasured

    # ── shared machinery for every drive ──────────────────────────────────────

    #: An operator resting on fewer than this many independent positive roots is
    #: thinly evidenced: it works, but not yet on enough ground to be called
    #: mastered. Matches the bar `_confidence_goals` already uses.
    _MASTERY_ROOT_BAR = 3
    #: Below this many recorded attempts, a failure rate is noise rather than a
    #: measurement, so impact's failure term is honestly unmeasured.
    _IMPACT_MIN_ATTEMPTS = 5

    async def _query(self, sql: str):
        """One read against the substrate's own store, or None if it cannot be
        reached. Never a default row — an unreachable store leaves the term
        unmeasured."""
        db = self.db
        if db is None:
            from core.database import get_database_manager
            db = get_database_manager()
        if not getattr(db, "initialized", False):
            return None
        return await db.execute_query(sql)

    def _competence_domains(self, udm) -> List[str]:
        """The domains the substrate holds a competence belief about, picked out
        of the belief store by the DOMAIN AUTHORITY'S own predicate — so the
        claim's wording stays owned in one place."""
        from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
        out: List[str] = []
        for belief in get_bayesian_uncertainty().beliefs.values():
            domain = udm.is_competence_belief(belief)
            if domain:
                out.append(domain)
        return out

    def _reading(self, name: str, sources: Dict[str, Any],
                 terms: Dict[str, Optional[float]]) -> "DriveReading":
        level, measured, unmeasured = self._drive_level(terms)
        return DriveReading(name=name, level=level, terms=measured,
                            unmeasured=unmeasured, sources=sources)

    async def _appraisal_state(self):
        """The substrate's current appraisal, or None. READ ONLY.

        Motivation does not compute pressures. It used to: `_experience_pressure`
        derived its own exploration pressure from the sign of accumulated reward,
        and `appraisal.py`'s module docstring names that exact function as the
        coupling AppraisalState was built to replace — "interpretation happens
        ONCE, with context, rather than N times in N consumers". It never was
        replaced; it stayed the live curiosity driver. The sign of one scalar
        cannot tell explore from replan from caution, which is the whole reason
        the appraisal authority exists, so the pressure is read from it.
        """
        try:
            from core.agents.autonomous.appraisal import get_appraisal_system
            return get_appraisal_system().current_state
        except Exception as error:
            logger.debug("drives: appraisal unreadable: %s", error)
            return None

    async def _measure_curiosity(self) -> "DriveReading":
        """The pull toward what is KNOWN to be unknown.

        Sources: the appraisal authority (exploration pressure, context-weighted),
        the belief authority (open questions it has registered), and the epistemic
        engine (regions of the model that will not settle).
        """
        sources: Dict[str, Any] = {}

        pressure = None
        state = await self._appraisal_state()
        if state is not None and state.exploration_pressure is not None:
            pressure = float(state.exploration_pressure)
            sources["exploration_pressure"] = round(pressure, 4)

        open_questions = None
        try:
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            unresolved = sum(
                1 for u in get_bayesian_uncertainty().known_unknowns.values()
                if not getattr(u, "resolved", False))
            open_questions = self._saturate(unresolved, self._OPEN_QUESTION_SCALE)
            sources["open_questions"] = unresolved
        except Exception as error:
            logger.debug("drives: open questions unreadable: %s", error)

        unsettled = None
        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            regions = len(get_epistemic_engine().get_unstable_regions())
            unsettled = self._saturate(regions, self._UNSTABLE_REGION_SCALE)
            sources["unstable_regions"] = regions
        except Exception as error:
            logger.debug("drives: unstable regions unreadable: %s", error)

        return self._reading(MotivationDimension.CURIOSITY, sources, {
            "exploration_pressure": pressure,
            "open_questions": open_questions,
            "unsettled_belief": unsettled,
        })

    async def _measure_competence(self) -> "DriveReading":
        """The pull to become able to DO more.

        Sources: the rule store (how little of the operator space is executable —
        the room to grow), the demonstration store (evidence already gathered and
        waiting to become an operator — skill within reach), and the domain
        authority (competence actually RISING, which says the effort is paying).
        """
        import math
        sources: Dict[str, Any] = {}

        room = None
        try:
            from core.learning.rule_store import get_rule_store
            rules = await get_rule_store().executable_rules()
            n = sum(1 for r in rules
                    if getattr(getattr(r, "rule", None), "action", None) is not None)
            room = 1.0 - math.tanh(n / self._COMPETENCE_SCALE)
            sources["executable_operators"] = n
        except Exception as error:
            logger.debug("drives: executable operators unreadable: %s", error)

        within_reach = None
        try:
            from core.learning.demonstration_store import get_demonstration_store
            pending = len(await get_demonstration_store().pending_signatures())
            within_reach = self._saturate(pending, self._PENDING_INDUCTION_SCALE)
            sources["pending_induction"] = pending
        except Exception as error:
            logger.debug("drives: pending induction unreadable: %s", error)

        paying_off = None
        try:
            from core.integration.universal_domain_master import \
                get_universal_domain_master
            udm = get_universal_domain_master()
            progress = [udm.learning_progress(d) for d in self._competence_domains(udm)]
            rising = [p for p in progress if p is not None and p > 0]
            if progress:
                paying_off = len(rising) / len(progress)
                sources["domains_with_rising_competence"] = f"{len(rising)}/{len(progress)}"
        except Exception as error:
            logger.debug("drives: learning progress unreadable: %s", error)

        return self._reading(MotivationDimension.COMPETENCE, sources, {
            "room_to_grow": room,
            "skill_within_reach": within_reach,
            "effort_paying_off": paying_off,
        })

    async def _measure_novelty(self) -> "DriveReading":
        """The pull toward what has NOT been encountered — distinct from curiosity,
        which is about gaps the substrate has already named.

        Sources: the domain authority (domains it has never acted in, so it has no
        idea whether its actions move them) and the concept store (things it holds
        by name alone, with no relation to anything — encountered but not met).
        """
        sources: Dict[str, Any] = {}

        untried = None
        try:
            rows = await self._query(
                "SELECT count(*) FILTER (WHERE action_attempts = 0) AS untried, "
                "count(*) AS known FROM unified.domain_controllability")
            if rows:
                known = int(rows[0]["known"] or 0)
                if known:
                    untried = int(rows[0]["untried"] or 0) / known
                    sources["untried_domains"] = f"{rows[0]['untried']}/{known}"
        except Exception as error:
            logger.debug("drives: untried domains unreadable: %s", error)

        unmet = None
        try:
            rows = await self._query(
                "SELECT count(*) AS total, count(*) FILTER ("
                "  WHERE NOT EXISTS (SELECT 1 FROM unified.concept_relations r "
                "                    WHERE r.source_concept_id = c.concept_id)"
                ") AS isolated FROM unified.concepts c")
            if rows:
                total = int(rows[0]["total"] or 0)
                if total:
                    unmet = int(rows[0]["isolated"] or 0) / total
                    sources["concepts_held_by_name_only"] = f"{rows[0]['isolated']}/{total}"
        except Exception as error:
            logger.debug("drives: isolated concepts unreadable: %s", error)

        return self._reading(MotivationDimension.NOVELTY, sources, {
            "untried_ground": untried,
            "unmet_concepts": unmet,
        })

    async def _measure_mastery(self) -> "DriveReading":
        """The pull to go DEEPER into what is already held — distinct from
        competence, which is about being able to do more things at all.

        Sources: the rule store (operators that work but rest on thin evidence —
        depth to gain where breadth already exists) and the epistemic engine
        (a belief model that has not settled is one not yet mastered).
        """
        sources: Dict[str, Any] = {}

        thin_evidence = None
        try:
            from core.learning.rule_store import get_rule_store
            rules = [r for r in await get_rule_store().executable_rules()
                     if getattr(getattr(r, "rule", None), "action", None) is not None]
            if rules:
                shallow = sum(1 for r in rules
                              if int(getattr(r, "positive_root_count", 0) or 0)
                              < self._MASTERY_ROOT_BAR)
                thin_evidence = shallow / len(rules)
                sources["thinly_evidenced_operators"] = f"{shallow}/{len(rules)}"
        except Exception as error:
            logger.debug("drives: operator evidence depth unreadable: %s", error)

        unsettled_model = None
        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            coherence = get_epistemic_engine().model_coherence()
            if coherence is not None:
                unsettled_model = 1.0 - float(coherence)
                sources["belief_coherence"] = round(float(coherence), 4)
        except Exception as error:
            logger.debug("drives: belief coherence unreadable: %s", error)

        return self._reading(MotivationDimension.MASTERY, sources, {
            "thin_evidence": thin_evidence,
            "unsettled_model": unsettled_model,
        })

    async def _measure_autonomy(self, queue: Any) -> "DriveReading":
        """The pull to act under its OWN direction.

        Read as opportunity, like every other drive: high when there is room to
        self-direct that is not being used. The old version read the opposite way
        — 0.9 in autonomous mode, 0.4 in supervised — which is how SATISFIED the
        need is, so it moved against every other dimension in the same sum.

        Sources: the queue's acting pool (slots free to spend on its own work) and
        the queue's composition (how much of what it is doing was its own idea).
        """
        sources: Dict[str, Any] = {}

        room_to_act = None
        try:
            pool = queue.pool_stats()
            cap = int(pool["max_parallel"])
            if cap > 0:
                room_to_act = max(0, cap - int(pool["active"])) / cap
                sources["free_slots"] = f"{max(0, cap - int(pool['active']))}/{cap}"
        except Exception as error:
            logger.debug("drives: acting pool unreadable: %s", error)

        externally_set = None
        try:
            from .shared_types import TaskSource
            # The work still OWED -- the queue authority's one answer to what is
            # active. This read every task the queue held, finished ones
            # included, so work done hours ago still counted as waiting.
            tasks = queue.active_tasks()
            if tasks:
                own = sum(1 for t in tasks
                          if getattr(t, "source", None) in
                          (TaskSource.AUTONOMOUS, TaskSource.SYSTEM))
                externally_set = 1.0 - (own / len(tasks))
                sources["self_initiated"] = f"{own}/{len(tasks)}"
        except Exception as error:
            logger.debug("drives: queue composition unreadable: %s", error)

        return self._reading(MotivationDimension.AUTONOMY, sources, {
            "room_to_act": room_to_act,
            "externally_set_work": externally_set,
        })

    async def _measure_social(self, queue: Any) -> "DriveReading":
        """The pull to engage with someone — read as opportunity, not sentiment.

        In an offline substrate this is not chatter: it is whether anyone is
        waiting on it, and whether it is stuck on something it cannot settle
        alone. Sources: the queue (work filed by a person, still open) and the
        appraisal authority (escalation pressure — the failure is outside the
        substrate, so the way forward runs through someone else).
        """
        sources: Dict[str, Any] = {}

        awaited = None
        try:
            from .shared_types import TaskSource
            # The work still OWED -- the queue authority's one answer to what is
            # active. This read every task the queue held, finished ones
            # included, so work done hours ago still counted as waiting.
            tasks = queue.active_tasks()
            if tasks:
                theirs = sum(1 for t in tasks
                             if getattr(t, "source", None) in
                             (TaskSource.API, TaskSource.MANUAL))
                awaited = theirs / len(tasks)
                sources["work_filed_by_people"] = f"{theirs}/{len(tasks)}"
        except Exception as error:
            logger.debug("drives: user work unreadable: %s", error)

        needs_someone = None
        state = await self._appraisal_state()
        if state is not None and state.escalation_pressure is not None:
            needs_someone = float(state.escalation_pressure)
            sources["escalation_pressure"] = round(needs_someone, 4)

        return self._reading(MotivationDimension.SOCIAL, sources, {
            "someone_is_waiting": awaited,
            "needs_someone": needs_someone,
        })

    async def _measure_impact(self, performance_stats: Optional[Dict[str, Any]]
                              ) -> "DriveReading":
        """The pull toward change that matters — how much is currently BROKEN or
        unclosed that the substrate could move.

        Sources: recorded task outcomes (what share of real attempts fail), the
        belief authority (ignorance it has registered and not yet closed), and
        appraisal (whether its actions move anything at all — impact needs
        purchase, not just something to fix).
        """
        sources: Dict[str, Any] = {}

        failing = None
        if performance_stats and int(performance_stats.get("total_attempts") or 0) >= \
                self._IMPACT_MIN_ATTEMPTS:
            rate = performance_stats.get("failure_rate")
            if isinstance(rate, (int, float)):
                failing = float(rate)
                sources["failure_rate"] = round(failing, 4)
                sources["attempts"] = performance_stats.get("total_attempts")

        unclosed = None
        try:
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            unknowns = get_bayesian_uncertainty().known_unknowns.values()
            open_now = sum(1 for u in unknowns if not getattr(u, "resolved", False))
            unclosed = self._saturate(open_now, self._OPEN_QUESTION_SCALE)
            sources["unclosed_deficits"] = open_now
        except Exception as error:
            logger.debug("drives: unclosed deficits unreadable: %s", error)

        purchase = None
        state = await self._appraisal_state()
        if state is not None and state.controllability is not None:
            purchase = float(state.controllability)
            sources["controllability"] = round(purchase, 4)

        return self._reading(MotivationDimension.IMPACT, sources, {
            "work_is_failing": failing,
            "unclosed_ignorance": unclosed,
            "purchase_on_the_world": purchase,
        })

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _calculate_total_reward(self, dimensions: Dict[str, float]) -> Optional[float]:
        """The overall drive level: the temperament-weighted mean of the drives
        ACTUALLY MEASURED, renormalised over them.

        This used to read each dimension with `dimensions.get(name, 0.5)` and
        divide by the full weight of all seven. So an unmeasured drive was not
        merely missing — it was asserted to be exactly half strength, and it
        pulled the total toward 0.5 with the same authority as a measured one.
        Two substrates, one that measured nothing and one that measured every
        drive at 0.5, produced an identical number.

        Now an unmeasured drive is absent from `dimensions` and absent from both
        sides of the division. Nothing measured at all returns None — the
        substrate has no read on its own drive, which is a fact about it, not a
        middling level.
        """
        weights = {
            MotivationDimension.CURIOSITY: self.weights.curiosity,
            MotivationDimension.COMPETENCE: self.weights.competence,
            MotivationDimension.NOVELTY: self.weights.novelty,
            MotivationDimension.MASTERY: self.weights.mastery,
            MotivationDimension.AUTONOMY: self.weights.autonomy,
            MotivationDimension.SOCIAL: self.weights.social,
            MotivationDimension.IMPACT: self.weights.impact,
        }
        num = sum(weights[k] * float(v) for k, v in dimensions.items()
                  if k in weights and v is not None)
        den = sum(weights[k] for k, v in dimensions.items()
                  if k in weights and v is not None)
        return (num / den) if den > 0 else None

    # ========================================================================
    # EVENT REWARDS
    #
    # These are NOT the _calculate_<dimension>() drive levels, and must not be
    # implemented by delegating to them.
    #
    #   dimension = "how strongly is this drive active right now"
    #   reward    = "how much did this particular event advance that drive"
    #
    # The competence drive is an inverted-U: a success rate above 0.8 drops it
    # to 0.4 because there is no room left to grow. Aliasing the reward to it
    # would pay the system least exactly when it performs best. The coordinator
    # called these five names for a long time and none of them existed, so
    # every call raised AttributeError -- see the notes on each caller.
    # ========================================================================

    SKILL_HISTORY = 20

    def _skill_history(self) -> Dict[str, List[float]]:
        if not hasattr(self, "_skill_perf"):
            self._skill_perf: Dict[str, List[float]] = {}
        return self._skill_perf

    async def calculate_competence_reward(
        self, skill_name: str, performance: float, success: bool
    ) -> IntrinsicReward:
        """Learning progress on one skill: improvement over its own baseline.

        Absolute performance would pay forever for an already-mastered skill.
        Progress decays toward zero as a skill saturates -- the same behaviour
        the competence drive expresses as its inverted-U, without inverting the
        sign of the reward.
        """
        performance = _clamp(performance)
        history = self._skill_history().setdefault(str(skill_name), [])
        baseline = (sum(history) / len(history)) if history else None

        history.append(performance)
        if len(history) > self.SKILL_HISTORY:
            del history[:-self.SKILL_HISTORY]

        if baseline is None:
            value = 0.5 * performance          # no baseline yet: provisional credit
        else:
            value = performance - baseline     # learning progress; may be negative
        if not success:
            value = min(0.0, value) - 0.1 * (1.0 - performance)

        return IntrinsicReward(
            dimension=MotivationDimension.COMPETENCE,
            reward_value=round(max(-1.0, min(1.0, value)), 4),
            components={
                "performance": performance,
                "baseline": baseline if baseline is not None else performance,
                "observations": float(len(history)),
            },
        )

    async def calculate_curiosity_reward(self, signals: Dict[str, Any]) -> IntrinsicReward:
        """Information gain actually realised.

        question_complexity pays only through answer_depth: a hard question
        left unanswered is curiosity aroused, not curiosity satisfied.
        """
        gain = _clamp(signals.get("information_gain", 0.0))
        reduction = _clamp(signals.get("uncertainty_reduction", 0.0))
        complexity = _clamp(signals.get("question_complexity", 0.0))
        depth = _clamp(signals.get("answer_depth", 0.0))

        value = 0.4 * gain + 0.4 * reduction + 0.2 * (complexity * depth)

        return IntrinsicReward(
            dimension=MotivationDimension.CURIOSITY,
            reward_value=round(_clamp(value), 4),
            components={
                "information_gain": gain,
                "uncertainty_reduction": reduction,
                "resolved_complexity": round(complexity * depth, 4),
            },
        )

    async def calculate_novelty_reward(self, experience: Dict[str, Any]) -> IntrinsicReward:
        """Distance of this experience from the recent ones already recorded.

        Reuses the profile history the system already keeps rather than opening
        a second store of the same thing.
        """
        vector = _numeric_vector(experience)
        if not vector:
            return IntrinsicReward(MotivationDimension.NOVELTY, 0.0, {"comparable_fields": 0.0})

        previous = [
            _numeric_vector(entry.get("experience", {}))
            for entry in (self.profile.history or [])[-self.SKILL_HISTORY:]
        ]
        comparable = [p for p in previous if p and set(p) & set(vector)]

        if not comparable:
            value = 1.0        # nothing to compare against: maximally novel
        else:
            value = min(_normalised_distance(vector, p) for p in comparable)

        self._add_to_history({"experience": experience, "novelty": value})

        return IntrinsicReward(
            dimension=MotivationDimension.NOVELTY,
            reward_value=round(_clamp(value), 4),
            components={"compared_against": float(len(comparable))},
        )

    async def calculate_autonomy_reward(self, signals: Dict[str, Any]) -> IntrinsicReward:
        """Self-direction: acting on its own initiative, with a real choice.

        The exploration term peaks at a balanced ratio -- neither pure
        exploitation nor pure exploration is autonomous behaviour.
        """
        self_initiated = bool(signals.get("self_initiated", False))
        choice_made = bool(signals.get("choice_made", False))
        ratio = _clamp(signals.get("exploration_ratio", 0.5))
        balance = 1.0 - abs(ratio - 0.5) * 2.0

        value = (0.5 if self_initiated else 0.0) + (0.3 if choice_made else 0.0) + 0.2 * balance

        return IntrinsicReward(
            dimension=MotivationDimension.AUTONOMY,
            reward_value=round(_clamp(value), 4),
            components={
                "self_initiated": float(self_initiated),
                "choice_made": float(choice_made),
                "exploration_balance": round(balance, 4),
            },
        )

    # ========================================================================
    # EXPLORATION TARGETS
    #
    # Exposure, not new computation. EpistemicEngine.get_unstable_regions()
    # already returns EpistemicTargets -- high-entropy beliefs and stalled
    # hypotheses -- sorted by entropy descending, and its own docstring calls
    # them "a high-uncertainty region that intrinsic motivation should explore".
    # ========================================================================

    async def get_top_exploration_targets(self, limit: int = 5) -> List[Any]:
        """The most uncertain regions worth exploring, most uncertain first.

        Raises rather than returning [] when the epistemic engine is
        unavailable: "nothing to explore" and "the subsystem is broken" must
        not be the same observation.
        """
        from core.reasoning.epistemic_engine import get_epistemic_engine

        targets = get_epistemic_engine().get_unstable_regions()
        return list(targets or [])[:max(0, int(limit))]

    async def mark_target_explored(self, target_id: str) -> None:
        """Record that a target was acted on.

        Feeds the existing recent-exploration penalty in _calculate_goal_priority
        via the theme counter, so repeatedly chasing the same region is damped.
        """
        await self._increment_theme_count(self._extract_theme(str(target_id)))

    def _add_to_history(self, entry: Dict[str, Any]) -> None:
        """Add motivation calculation to history"""
        try:
            self.profile.history.append(entry)
            self._unsaved_history.append(entry)

            # Trim history if too long
            if len(self.profile.history) > self.history_limit:
                self.profile.history = self.profile.history[-self.history_limit:]

        except Exception as e:
            logger.error(f"Error adding to history: {e}")

    #: THE MOTIVATION PROFILE LIVES IN THE STORE. It was a JSON file under the
    #: repo's data/: a wipe of the store left the drives it had measured behind,
    #: an instance of the model run from another checkout never saw them, and
    #: every instance rewrote the whole file -- history included -- with its own
    #: copy. The drives are MEASURED each tick from the shared world, so the
    #: latest measurement is the profile (one row; a newer reading is never
    #: replaced by an older one). The history is what each instance experienced,
    #: so it is APPENDED, never rewritten.
    _PROFILE_DDL = (
        """CREATE TABLE IF NOT EXISTS unified.motivation_profile (
               profile_id              TEXT PRIMARY KEY,
               dimensions              JSONB NOT NULL,
               total_intrinsic_reward  DOUBLE PRECISION NOT NULL,
               measured_at             TIMESTAMPTZ
           )""",
        """CREATE TABLE IF NOT EXISTS unified.motivation_history (
               entry_id     BIGSERIAL PRIMARY KEY,
               entry        JSONB NOT NULL,
               recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
           )""")
    #: The one profile: the substrate's.
    PROFILE_ID = "substrate"

    async def _profile_store(self):
        from core.database import get_database_manager
        db = self.db or get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()
        if not getattr(self, "_profile_schema_ready", False):
            for ddl in self._PROFILE_DDL:
                await db.execute_query(ddl, (), commit=True)
            self._profile_schema_ready = True
        return db

    async def save_profile(self) -> bool:
        """Write the latest measured drives, and append the history recorded since
        the last save, to the store."""
        try:
            db = await self._profile_store()
            # NOTHING MEASURED, NOTHING TO SAVE. `total_intrinsic_reward` is None
            # until a drive has been measured (by design: appraisal reads None as
            # unmeasured), and the stored profile is only ever the newest
            # MEASUREMENT. float(None) here raised before the history below was
            # written, so every run that ended before its first measurement lost
            # its motivation history too (measured 2026-09-27, SEPARATION-01).
            if self.profile.total_intrinsic_reward is not None:
                await db.execute_query(
                    "INSERT INTO unified.motivation_profile AS p (profile_id, dimensions, "
                    "total_intrinsic_reward, measured_at) VALUES ($1, $2::jsonb, $3, $4) "
                    "ON CONFLICT (profile_id) DO UPDATE SET dimensions = EXCLUDED.dimensions, "
                    "total_intrinsic_reward = EXCLUDED.total_intrinsic_reward, "
                    "measured_at = EXCLUDED.measured_at "
                    "WHERE p.measured_at IS NULL OR p.measured_at <= EXCLUDED.measured_at",
                    (self.PROFILE_ID, json.dumps(self.profile.dimensions),
                     float(self.profile.total_intrinsic_reward),
                     # Measured in local time; stored as the instant it was.
                     (self.profile.last_updated.astimezone()
                      if self.profile.last_updated else None)),
                    commit=True)
            pending, self._unsaved_history = self._unsaved_history, []
            for entry in pending:
                await db.execute_query(
                    "INSERT INTO unified.motivation_history (entry) VALUES ($1::jsonb)",
                    (json.dumps(entry, default=str),), commit=True)
            # Bounded as the in-process history is: the newest `history_limit`.
            await db.execute_query(
                "DELETE FROM unified.motivation_history WHERE entry_id < ("
                "SELECT min(entry_id) FROM (SELECT entry_id FROM unified.motivation_history "
                "ORDER BY entry_id DESC LIMIT $1) newest)", (int(self.history_limit),),
                commit=True)
            return True
        except Exception as e:
            logger.error(f"Failed to save the motivation profile to the store: {e}")
            return False

    async def load_profile(self) -> bool:
        """Read the latest measured drives and the recent history from the store.
        False when none has been stored yet (nothing measured is absent, not
        defaulted)."""
        try:
            db = await self._profile_store()
            row = await db.execute_query(
                "SELECT dimensions, total_intrinsic_reward, measured_at "
                "FROM unified.motivation_profile WHERE profile_id = $1",
                (self.PROFILE_ID,), fetch_one=True)
            history = await db.execute_query(
                "SELECT entry FROM (SELECT entry_id, entry FROM unified.motivation_history "
                "ORDER BY entry_id DESC LIMIT $1) newest ORDER BY entry_id",
                (int(self.history_limit),), fetch_all=True) or []
            self.profile.history = [
                h["entry"] if isinstance(h["entry"], dict) else json.loads(h["entry"])
                for h in history]
            if row is None:
                logger.info("No motivation profile stored yet; no drive is held")
                return False
            dims = row["dimensions"]
            self.profile.dimensions = dims if isinstance(dims, dict) else json.loads(dims)
            self.profile.total_intrinsic_reward = float(row["total_intrinsic_reward"])
            self.profile.last_updated = row["measured_at"]
            logger.info("Motivation profile loaded from the store")
            return True

        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'intrinsic_motivation.load_profile')
            logger.error(f"Failed to load the motivation profile from the store: {e}")
            return False

    async def get_motivation_state(self) -> Dict[str, Any]:
        """Get current motivation state"""
        return {
            "dimensions": self.profile.dimensions.copy(),
            "total_reward": self.profile.total_intrinsic_reward,
            "influence_percentage": self.influence_percentage,
            "last_updated": self.profile.last_updated.isoformat() if self.profile.last_updated else None,
            "active": self.active
        }

    @staticmethod
    def _allocate_drive_budget(total: int, valence: Optional[float],
                               deficits: Dict[str, Optional[float]]) -> Dict[str, int]:
        """Split the goal budget across the DRIVES, biased by mood.

        Each drive targets a fitness dimension; its base weight is that dimension's
        measured deficit — the substrate pursues what it most lacks. A NEGATIVE
        mood (declining fitness) SHARPENS the split onto the worst deficit (repair
        — fix what is breaking, weight²); a POSITIVE mood FLATTENS it (explore —
        spread across drives, weight^½). A drive whose dimension is unmeasurable
        gets weight 0. Allocation is largest-remainder so the budgets sum EXACTLY
        to `total`, so the mood re-splits the DISTRIBUTION and never reduces the
        COUNT — the death-spiral invariant, by construction."""
        w = {k: (d if d is not None else 0.0) for k, d in deficits.items()}
        if valence is not None and valence < -0.15:
            w = {k: v * v for k, v in w.items()}          # repair: concentrate on worst
        elif valence is not None and valence > 0.15:
            w = {k: v ** 0.5 for k, v in w.items()}       # explore: flatten / spread
        s = sum(w.values())
        if s <= 0:                                         # no measured deficit → even
            measurable = [k for k, d in deficits.items() if d is not None] or list(deficits)
            w = {k: (1.0 if k in measurable else 0.0) for k in deficits}
            s = sum(w.values()) or 1.0
        raw = {k: total * w[k] / s for k in w}
        base = {k: int(raw[k]) for k in raw}
        remainder = total - sum(base.values())
        for k in sorted(w, key=lambda x: raw[x] - base[x], reverse=True)[:max(0, remainder)]:
            base[k] += 1
        return base

    async def _operator_confidence(self) -> Optional[float]:
        """Mean validation strength of the executable operators — positive roots /
        (positive + negative). Low means the substrate's operators are only weakly
        confirmed. None when there are no executable operators (nothing yet to be
        confident about); never fabricated."""
        try:
            from core.learning.rule_store import get_rule_store
            rules = await get_rule_store().executable_rules()
        except Exception as e:
            logger.debug("operator confidence unreadable: %s", e)
            return None
        strengths = []
        for r in rules:
            p = getattr(r, "positive_root_count", 0) or 0
            n = getattr(r, "negative_root_count", 0) or 0
            if p + n > 0:
                strengths.append(p / (p + n))
        return (sum(strengths) / len(strengths)) if strengths else None

    async def _competence_goals(self, budget: int) -> List:
        """BUILD-COMPETENCE goals — target the learning frontier so acting gathers
        the evidence a missing/forming operator needs. Grounded in
        pending_signatures; empty when there is no material (honest, never an
        invented goal).

        A pending signature is one of THREE typed shapes, not one:
          * a real operator signature (non-empty predicate) — a per-operator goal
            to gather more evidence for that forming operator;
          * the CONTRASTIVE sentinel ``("", 0)`` — NOT malformed: the documented
            domain-level state (demonstration_store.CONTRASTIVE) meaning the domain
            gained an actionless negative that sharpens EVERY operator. It is a
            legitimate DOMAIN-level competence opportunity, so it yields a
            domain-scoped goal, mirroring how the drain expands it across the
            domain (learning_authority.drain_pending_induction);
          * anything else with a blank predicate/domain — genuinely CORRUPT (a
            demonstration must belong to a domain and, if action-ful, to a real
            predicate). REJECTED loudly with a named reason so the bad row is
            visible, never turned into a blank-named goal.
        """
        if budget <= 0:
            return []
        from .shared_types import Goal, Priority
        import uuid
        try:
            from core.learning.demonstration_store import get_demonstration_store
            store = get_demonstration_store()
            pending = await store.pending_signatures(limit=budget)
        except Exception as e:
            logger.debug("competence goals: pending signatures unreadable: %s", e)
            return []
        contrastive = store.CONTRASTIVE  # the store owns what the sentinel is
        goals = []
        for domain, predicate, arity in pending[:budget]:
            has_domain = isinstance(domain, str) and bool(domain.strip())
            has_predicate = isinstance(predicate, str) and bool(predicate.strip())
            if not has_domain:
                # A demonstration must belong to a domain (append() enforces this);
                # a blank domain in the queue is genuinely corrupt.
                logger.warning(
                    "competence goal REJECTED (CORRUPT_DOMAIN): domain=%r predicate=%r "
                    "arity=%r — pending signature with no domain", domain, predicate, arity)
                continue
            if (predicate, arity) == contrastive:
                # Domain-level contrastive evidence — a real competence opportunity,
                # not a malformed operator. Act in the domain to gather evidence
                # that will sharpen its operators when they are next re-induced.
                g = Goal(
                    id=f"competence_goal_{uuid.uuid4().hex[:8]}",
                    description=(f"Build competence: gather evidence in domain {domain} — "
                                f"new contrastive evidence sharpens all its operators"),
                    priority=Priority.MEDIUM, curiosity_value=0.5, expected_novelty=0.4,
                    expected_competence_gain=0.9, intrinsic_reward_potential=0.7,
                )
                g.metadata.update({"drive": "competence", "domain_id": domain,
                                   "scope": "domain_contrastive"})
                goals.append(g)
                continue
            if not has_predicate:
                # Blank predicate that is NOT the contrastive sentinel (e.g. arity
                # != 0): a truly malformed signature, surfaced not hidden.
                logger.warning(
                    "competence goal REJECTED (MALFORMED_SIGNATURE): domain=%r predicate=%r "
                    "arity=%r — blank predicate is not the contrastive sentinel",
                    domain, predicate, arity)
                continue
            g = Goal(
                id=f"competence_goal_{uuid.uuid4().hex[:8]}",
                description=(f"Build competence: gather evidence for operator "
                            f"{predicate}/{arity} in domain {domain} so it can be validated"),
                priority=Priority.MEDIUM, curiosity_value=0.5, expected_novelty=0.4,
                expected_competence_gain=0.9, intrinsic_reward_potential=0.7,
            )
            g.metadata.update({"drive": "competence", "domain_id": domain,
                               "predicate": predicate, "arity": arity})
            goals.append(g)
        return goals

    async def _confidence_goals(self, budget: int) -> List:
        """BUILD-CONFIDENCE goals — target executable operators that are only
        weakly validated (few confirming roots), to re-validate them with fresh
        evidence. Grounded in rule_store; empty when every operator is well
        confirmed (honest).

        Only ACTION-ful operators qualify: re-validation strengthens confidence
        by ACTING to gather a fresh confirming demonstration, so an actionless
        observation rule (rule.action is None) has nothing to act on and is
        skipped. The operator SIGNATURE (predicate, arity) is carried so the
        execution handler can re-induce exactly this operator, not guess it from
        the rule id."""
        if budget <= 0:
            return []
        from .shared_types import Goal, Priority
        import uuid
        try:
            from core.learning.rule_store import get_rule_store
            rules = await get_rule_store().executable_rules()
        except Exception as e:
            logger.debug("confidence goals: rules unreadable: %s", e)
            return []
        weak = sorted(rules, key=lambda r: (getattr(r, "positive_root_count", 0) or 0))
        goals = []
        for r in weak:
            if len(goals) >= budget:
                break
            p = getattr(r, "positive_root_count", 0) or 0
            if p >= 3:                       # already well-confirmed — not thin
                continue
            # The signature is the operator the handler must re-induce. An
            # actionless rule has no operator to act on — skip it rather than
            # emit a confidence goal that cannot be executed.
            action = getattr(getattr(r, "rule", None), "action", None)
            if action is None:
                continue
            predicate, arity = action.signature
            dom = getattr(r, "domain_id", None) or "unattributed"
            g = Goal(
                id=f"confidence_goal_{uuid.uuid4().hex[:8]}",
                description=(f"Build confidence: re-validate operator {predicate}/{arity} "
                            f"({r.rule_id}) in domain {dom} (only {p} confirming root(s))"),
                priority=Priority.MEDIUM, curiosity_value=0.4, expected_novelty=0.3,
                expected_competence_gain=0.5, intrinsic_reward_potential=0.6,
            )
            g.metadata.update({"drive": "confidence", "domain_id": dom, "rule_id": r.rule_id,
                               "predicate": predicate, "arity": arity,
                               "positive_root_count": p})
            goals.append(g)
        return goals

    async def generate_curiosity_driven_goals(
        self,
        max_goals: int = 1,
        system_context: Optional[Dict[str, Any]] = None
    ) -> List:
        """
        Generate goals using uncertainty-weighted sampling (ICM/RND-inspired).

        No LLM templates - pure metric-driven generation:
        1. Quantify epistemic uncertainty per component
        2. Detect uncertainty gradients (Δ from baseline)
        3. Score candidates: w1*uncertainty + w2*impact + w3*perf_deg + w4*novelty - w5*recent
        4. Sample stochastically from top candidates

        Args:
            max_goals: Maximum number of goals to generate
            system_context: Current system state including errors, metrics, recent tasks

        Returns:
            List of Goal objects with metric-driven priorities
        """
        try:
            from .shared_types import Goal, Priority
            import uuid

            # MOOD MODULATION over FOUR DRIVES. Read the substrate's OWN affect +
            # fitness (never handed in as context) and let the mood shape WHICH
            # drive wins — the homeostatic link between feeling and motivation.
            #   certainty  → component-uncertainty goals (curiosity)
            #   coherence  → epistemic/belief goals      (curiosity)
            #   competence → build-competence goals      (mastery)
            #   confidence → validate-operator goals     (confidence)
            # See docs/AFFECT_ARCHITECTURE.md §9.
            fit = await self.sense_fitness()
            affect = self.affect_state()
            valence, arousal = affect.valence, affect.arousal
            confidence = await self._operator_confidence()
            deficits = {
                "certainty":  (1.0 - fit.certainty) if fit.certainty is not None else None,
                "coherence":  (1.0 - fit.coherence) if fit.coherence is not None else None,
                "competence": (1.0 - fit.competence) if fit.competence is not None else None,
                "confidence": (1.0 - confidence) if confidence is not None else None,
            }

            # AROUSAL sets INTENSITY (how many goals): high arousal (fitness moving
            # fast / high stakes) → more; settled → fewer. Floored at 1 whenever the
            # caller wanted any goal, so neither a calm NOR a struggling mood can
            # take generation to zero — the floor is the death-spiral guard.
            if max_goals >= 1:
                effective_max = max(1, min(2 * max_goals,
                                           int(round(max_goals * (0.5 + arousal)))))
            else:
                effective_max = 0
            budgets = self._allocate_drive_budget(effective_max, valence, deficits)
            mode = ("repair" if (valence is not None and valence < -0.15)
                    else "explore" if (valence is not None and valence > 0.15) else "neutral")
            logger.info("🎭 %s mood (valence=%s, arousal=%.2f) max_goals %d→%d; budgets=%s",
                        mode, "n/a" if valence is None else round(valence, 3),
                        arousal, max_goals, effective_max, budgets)

            goals = []
            certainty_goals = []

            # CERTAINTY drive — component-uncertainty goals.
            component_metrics = await self._quantify_component_uncertainties(system_context)
            if component_metrics and budgets["certainty"] > 0:
                uncertainty_deltas = await self._calculate_uncertainty_gradients(component_metrics)
                candidates = []
                for component, metrics in component_metrics.items():
                    priority_score = await self._calculate_goal_priority(
                        component=component, metrics=metrics,
                        delta=uncertainty_deltas.get(component, 0.0))
                    candidates.append({'component': component, 'metrics': metrics,
                                       'delta': uncertainty_deltas.get(component, 0.0),
                                       'priority_score': priority_score})
                certainty_goals = await self._sample_goal_candidates(candidates, budgets["certainty"])
                for g in certainty_goals:
                    g.metadata.setdefault("drive", "certainty")
                goals.extend(certainty_goals)

            # COMPETENCE drive — build-competence goals from the learning frontier.
            competence_goals = await self._competence_goals(budgets["competence"])
            goals.extend(competence_goals)
            # CONFIDENCE drive — re-validate weakly-confirmed operators.
            confidence_goals = await self._confidence_goals(budgets["confidence"])
            goals.extend(confidence_goals)

            # COHERENCE drive — epistemic/belief goals. Given its own budget PLUS
            # any budget the other drives could not spend (so effort is never
            # wasted, and a stable system can still resolve an unstable belief).
            epistemic_budget = max(budgets["coherence"], effective_max - len(goals))
            coherence_goals = await self._generate_epistemic_goals(epistemic_budget)
            for g in coherence_goals:
                g.metadata.setdefault("drive", "coherence")
            goals.extend(coherence_goals)

            # BOUNDARY COUNTS — the lifecycle of every candidate is visible, so a
            # count that drops between stages has a named owner (no silent 5→0).
            produced = {"certainty": len(certainty_goals),
                        "competence": len(competence_goals),
                        "confidence": len(confidence_goals),
                        "coherence": len(coherence_goals)}
            logger.info("drive budgets=%s produced=%s total=%d",
                        budgets, produced, len(goals))

            # NO FALLBACK. Goals come only from real substrate signals — component
            # uncertainties, unstable beliefs, the competence frontier, and weakly
            # confirmed operators. When ALL are empty there is genuinely nothing to
            # pursue from measured state, and the honest answer is no goal this
            # cycle — never an invented one, and never from the model.
            if not goals:
                logger.info("No measured drive signals this cycle — no intrinsic goal")
                return []
            return goals

        except Exception as e:
            # A STRUCTURAL bug (NameError, AttributeError, a wiring fault) is NOT a
            # legitimate "no goals" — surface it, do not let it masquerade as an
            # empty result. Only a genuine runtime hiccup degrades to no-goal.
            raise_if_structural(e, "generate_curiosity_driven_goals")
            logger.error(f"Error generating curiosity-driven goals: {e}", exc_info=True)
            return []

    async def get_domain_performance_stats(self, domain: str = "all") -> Dict[str, Any]:
        """
        Query META memory for domain performance statistics

        Args:
            domain: Specific domain or "all" for overall stats

        Returns:
            Dictionary with success rate, failure rate, avg confidence
        """
        try:
            from core.memory.utils.interfaces import task_outcomes_from_memory
            from core.memory import get_memory_agent
            from core.memory.utils.interfaces import MemoryType

            memory_agent = await get_memory_agent()

            # UNMEASURED, not 50%. A fabricated midpoint made "no observations"
            # indistinguishable from "a genuinely coin-flip domain", and every
            # consumer downstream inherited that lie.
            if not memory_agent or not memory_agent.initialized:
                return _unmeasured_stats(domain, reason="memory_agent_unavailable")

            # Query META task outcomes.
            # `domain` used to be passed as query_text, which only nudged
            # semantic ranking — it never constrained the result set, so every
            # domain reported the global average. The domain is filtered below
            # on the authoritative record field instead of a search string.
            memories = await memory_agent.search_memories(
                query_text="task_outcome",
                memory_type=MemoryType.META,
                tags=["task_outcome", "performance_tracking"],
                max_results=500,
            )

            if not memories:
                return _unmeasured_stats(domain, reason="no_task_outcome_memories")

            # Calculate statistics
            successes = 0
            failures = 0
            total_confidence = 0.0

            skipped = 0
            for memory in memories:
                # EACH TIME THE TASK WAS DONE: a task asked again is one memory
                # holding every occurrence, and each is an outcome.
                records = task_outcomes_from_memory(memory)
                if not records:
                    # Not a task outcome, or a malformed one. Never guess from
                    # the narrative — a parsed sentence is a second, divergent
                    # reading of an observation that already has a record.
                    skipped += 1
                    continue

                for record in records:
                    if domain != "all" and record.domain != domain:
                        continue

                    if record.outcome == "success":
                        successes += 1
                    elif record.outcome == "failure":
                        failures += 1

                    total_confidence += float(record.confidence)

            if skipped:
                logger.debug(
                    "get_domain_performance_stats: %d/%d memories carried no "
                    "structured task outcome", skipped, len(memories)
                )

            total = successes + failures
            if total == 0:
                return _unmeasured_stats(domain, reason="no_outcomes_for_domain")

            # STATISTICAL OBSERVATION — deliberately NOT a competence estimate.
            # 4/4 causal successes is an empirical success rate of 1.000; it is
            # not "causal reasoning capability = 1.000". Consumers that need a
            # capability estimate must build one from CapabilityEvidence, which
            # carries the sample size, diversity and recency this cannot.
            stats = {
                "success_rate": successes / total,
                "failure_rate": failures / total,
                # RENAMED. Sitting next to success_rate as `avg_confidence` this
                # read as "confidence in the rate". It is not: it is how sure we
                # were about each individual outcome LABEL. Two different
                # confidences that must never share a field again.
                "avg_outcome_label_confidence": total_confidence / total,
                "successes": successes,
                "failures": failures,
                "total_attempts": total,
                "measured": True,
                "domain": domain,
            }

            logger.info(f"📊 Domain '{domain}' stats: {stats['success_rate']:.1%} success rate ({total} attempts)")

            return stats

        except Exception as e:
            logger.error(f"Failed to get domain performance stats: {e}")
            # A failure to measure is UNMEASURED, never a 50% result.
            return _unmeasured_stats(domain, reason=f"error: {type(e).__name__}")

    # =========================================================================
    # UNCERTAINTY-WEIGHTED GOAL SAMPLING (ICM/RND-Inspired)
    # =========================================================================

    #: Combination weights for the fitness scalar. A UNIT choice over the terms,
    #: not a set-point; the scalar is renormalised over whatever was measured, so a
    #: missing term never reads as zero fitness. Competence weighted slightly
    #: higher: having operators to act with is the substrate's most direct fitness.
    _FITNESS_WEIGHTS = {"competence": 0.4, "coherence": 0.3, "certainty": 0.3}

    #: Soft scale turning an unbounded executable-operator count into a [0,1]
    #: competence signal via tanh. NOT a threshold — a saturating unit, so more
    #: operators always reads as more competent with diminishing marginal effect.
    #: Valence is the DERIVATIVE of fitness, so this scale sets units, not behaviour.
    _COMPETENCE_SCALE = 25.0

    async def sense_fitness(self, system_context: Optional[Dict[str, Any]] = None) -> "Fitness":
        """Read the substrate's model fitness NOW from the authorities that own its
        parts — competence (operators it can execute), coherence (belief-model
        settledness), certainty (inverse component uncertainty). Reads only; owns
        none of them. A part that cannot be measured this tick is excluded and
        named, never zero-filled (docs/AFFECT_ARCHITECTURE.md, Invariant 1).

        `system_context` (the coordinator's goal-context) is needed for the
        certainty term; without it certainty is honestly unmeasured.
        """
        import math
        measured: List[str] = []
        unmeasured: List[str] = []
        sources: Dict[str, Any] = {}

        # COMPETENCE — the executable operators the substrate actually has.
        competence: Optional[float] = None
        try:
            from core.learning.rule_store import get_rule_store
            rules = await get_rule_store().executable_rules()
            n = sum(1 for r in rules
                    if getattr(getattr(r, "rule", None), "action", None) is not None)
            competence = math.tanh(n / self._COMPETENCE_SCALE)
            sources["executable_operators"] = n
            measured.append("competence")
        except Exception as e:
            unmeasured.append("competence")
            logger.debug("fitness: competence unreadable: %s", e)

        # COHERENCE — how settled the belief model is, from its owner (the
        # epistemic engine), which returns None when there are no beliefs yet.
        coherence: Optional[float] = None
        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            coherence = get_epistemic_engine().model_coherence()
            if coherence is None:
                unmeasured.append("coherence")
            else:
                sources["belief_coherence"] = round(coherence, 4)
                measured.append("coherence")
        except Exception as e:
            unmeasured.append("coherence")
            logger.debug("fitness: coherence unreadable: %s", e)

        # CERTAINTY — inverse of mean component epistemic uncertainty. Needs the
        # system context; without it, honestly unmeasured (not assumed certain).
        certainty: Optional[float] = None
        if system_context:
            try:
                comp = await self._quantify_component_uncertainties(system_context)
                us = [m.get("epistemic_uncertainty") for m in comp.values()
                      if isinstance(m.get("epistemic_uncertainty"), (int, float))]
                if us:
                    certainty = max(0.0, min(1.0, 1.0 - sum(us) / len(us)))
                    sources["components"] = len(us)
                    measured.append("certainty")
                else:
                    unmeasured.append("certainty")
            except Exception as e:
                unmeasured.append("certainty")
                logger.debug("fitness: certainty unreadable: %s", e)
        else:
            unmeasured.append("certainty")

        # SCALAR — weighted mean over MEASURED terms only, renormalised so a
        # missing term is absent rather than a zero dragging fitness down.
        terms = {"competence": competence, "coherence": coherence, "certainty": certainty}
        num = sum(self._FITNESS_WEIGHTS[k] * v for k, v in terms.items() if v is not None)
        den = sum(self._FITNESS_WEIGHTS[k] for k, v in terms.items() if v is not None)
        scalar = (num / den) if den > 0 else None

        return Fitness(
            competence=competence, coherence=coherence, certainty=certainty,
            measured=measured, unmeasured=unmeasured, scalar=scalar, sources=sources,
        )

    #: Sensitivity of valence to a per-tick fitness change. A UNIT (gain), not a
    #: set-point: a fitness change of ~0.1 per tick reads as a clearly felt
    #: valence (tanh(8·0.1) ≈ 0.66). Larger swings saturate toward ±1.
    _VALENCE_GAIN = 8.0

    @staticmethod
    def _fitness_delta(now: "Fitness", prev: "Fitness") -> Tuple[Optional[float], List[str]]:
        """The change in fitness between two readings, computed ONLY over the terms
        measured in BOTH. This compares like-for-like: a term that appeared or
        vanished between ticks changes the term SET, not fitness, and must not
        register as a feeling. Returns (delta, terms_used); delta is None when no
        term was measured in both."""
        weights = IntrinsicMotivationSystem._FITNESS_WEIGHTS
        common = [k for k in ("competence", "coherence", "certainty")
                  if getattr(now, k) is not None and getattr(prev, k) is not None]
        if not common:
            return None, []
        num = sum(weights[k] * (getattr(now, k) - getattr(prev, k)) for k in common)
        den = sum(weights[k] for k in common)
        return (num / den if den > 0 else None), common

    @staticmethod
    def _affect_from_appraisal(state):
        """The dominant named emotion, its intensity, its cause and WHAT IT IS
        ABOUT — read from the substrate's OWN appraisal (not from any environment
        context). None when the situation has not been appraised, so nothing is
        invented.

        Returns (emotion, intensity, cause, about, about_domain)."""
        if state is None:
            return None, None, None, None, None
        emotions = {"eagerness": state.eagerness, "doubt": state.doubt,
                    "frustration": state.frustration, "satisfaction": state.satisfaction}
        measured = {k: v for k, v in emotions.items() if isinstance(v, (int, float))}
        about = getattr(state, "about", None)
        about_domain = getattr(state, "about_domain", None)
        if not measured:
            return None, None, state.attribution, about, about_domain
        emotion, intensity = max(measured.items(), key=lambda kv: kv[1])
        return (emotion, round(float(intensity), 4), state.attribution,
                about, about_domain)

    async def update_affect(self) -> "AffectState":
        """Fold a fitness-relevant EVENT (a task outcome) into the substrate's affect.

        Reads the substrate's OWN state — its appraisal (for the named emotion and
        cause) and its fitness (competence/coherence) for the mood valence. It is
        NOT handed environment context, and it is NOT a loop tick: the mood decays
        on read between events. An affect TRANSITION happens only when a new
        appraisal actually produces an emotion; otherwise the current (possibly
        rehydrated) emotion is retained — a restart alone does not change the
        feeling. The resulting STATE is persisted and returned.
        """
        import math
        from datetime import datetime, timezone
        at = datetime.now(timezone.utc)

        # --- the named emotion + cause, from the substrate's own appraisal ---
        try:
            from core.agents.autonomous.appraisal import get_appraisal_system
            ap_state = get_appraisal_system().current_state
        except Exception as e:
            logger.debug("affect: appraisal unreadable: %s", e)
            ap_state = None
        (emotion, intensity, cause,
         about, about_domain) = self._affect_from_appraisal(ap_state)
        if emotion is not None:
            # a real appraisal produced an emotion → an affect TRANSITION
            self._affect_emotion, self._affect_intensity, self._affect_cause = emotion, intensity, cause
            # WHAT it is about moves with it. Kept when the new appraisal names
            # nothing, for the same reason appraisal carries it forward: an
            # update silent about the object has not made the feeling objectless.
            if about is not None:
                self._affect_about, self._affect_about_domain = about, about_domain
            self._affect_version += 1
        else:
            # A FEELING DOES NOT OUTLIVE ITS OWN BASIS.
            #
            # This retained the previous emotion at FULL INTENSITY, forever,
            # whenever appraisal could measure none — and appraisal measures
            # none whenever its constituents are unmeasured, which is most of
            # the time outside a task. Measured on the live substrate:
            # `eagerness` held at 0.4364 with `cause=None` across 784 versions,
            # on a mood of 0.000 — a feeling frozen at the last moment anything
            # supported it, still colouring behaviour.
            #
            # The mood already knew better: it relaxes toward baseline on a
            # half-life, which is why it needs no loop. The emotion is given the
            # same treatment. It FADES rather than vanishing, because the design
            # wants persistence — the substrate resumes in doubt if it went down
            # in doubt — and fading keeps that while letting an unsupported
            # feeling go. Re-measuring it refreshes it; nothing else does.
            #
            # NOT A TRANSITION, deliberately: `version` counts times the
            # substrate came to feel something, and fading is the absence of
            # that, not an instance of it.
            self._affect_intensity = self._faded_intensity(at)
            if (self._affect_intensity is not None
                    and self._affect_intensity < self._EMOTION_FLOOR):
                # Below the floor there is no longer a feeling to name, and
                # saying there is would be the substrate reporting a state it
                # is not in.
                #
                # But a doubt is not only a feeling, so it does not only go.
                self._keep_the_question()
                self._affect_emotion = None
                self._affect_intensity = None
                self._affect_cause = None
                self._affect_about = None
                self._affect_about_domain = None

        # --- the mood valence from the fitness trend (the substrate's own state) ---
        now = await self.sense_fitness()
        prev = self._last_fitness
        self._last_fitness = now
        delta, _used = (None, [])
        if prev is not None:
            delta, _used = self._fitness_delta(now, prev)

        self._mood_valence, self._mood_arousal = self._decayed(at)  # decay to now
        if delta is not None:
            v = math.tanh(self._VALENCE_GAIN * delta)
            a_intensity = min(1.0, abs(delta) * self._VALENCE_GAIN)
            k = self._MOOD_INTEGRATION
            self._mood_valence += k * (v - self._mood_valence)
            self._mood_arousal += k * (a_intensity - self._mood_arousal)
            self._affect_event_count += 1
            self._baseline_valence += self._BASELINE_DRIFT * (self._mood_valence - self._baseline_valence)
        self._mood_valence = max(-1.0, min(1.0, self._mood_valence))
        self._baseline_valence = max(-1.0, min(1.0, self._baseline_valence))
        self._mood_arousal = max(0.0, min(1.0, self._mood_arousal))
        self._last_affect_at = at
        await self._persist_affect()
        return self.affect_state()

    # ── persistent mood (core affect) — STATE, decayed on read, not a loop ─────
    #: Event-integration weights. α pulls mood toward the felt valence per EVENT;
    #: β lets the trait follow lived mood (allostatic load). Not set-points — the
    #: rates at which experience moves the felt state.
    _MOOD_INTEGRATION = 0.2    # α: how far mood moves toward an event's valence
    _BASELINE_DRIFT = 0.01     # β: how far the trait follows lived mood per event
    #: Fade time-constants (wall-clock, seconds). Mood relaxes toward the baseline
    #: with this half-life; arousal subsides faster. Units, not set-points — they
    #: set how long a mood lingers, and are why affect needs no polling loop.
    _MOOD_HALFLIFE_S = 1800.0     # ~30 min — a mood lingers
    _AROUSAL_HALFLIFE_S = 600.0   # ~10 min — activation settles sooner
    #: An EMOTION is faster than a mood — it is about something, and it goes
    #: when what it was about stops being measurable. Shorter than the mood it
    #: sits on, for the same reason a fright passes sooner than a bad week.
    _EMOTION_HALFLIFE_S = 900.0   # ~15 min
    #: Below this there is no feeling left to name. Naming one anyway would have
    #: the substrate report a state it is not in.
    _EMOTION_FLOOR = 0.05

    def _keep_the_question(self) -> None:
        """A DOUBT that fades was never answered — keep the question.

        Fading is alleviation by TIME, and for most feelings that is the whole
        of it. A satisfaction that fades was about something finished; a
        frustration that fades was about something that stopped resisting or
        stopped mattering. Nothing is lost when they go.

        Doubt is not symmetric with them. Doubt is an open question wearing a
        feeling — `(1 − confidence) + epistemic_opportunity + risk` — and if the
        feeling lapses with nothing recorded, the substrate has stopped
        wondering about something it never settled. That is strictly worse than
        staying uncertain: the uncertainty does not become knowledge, it becomes
        invisible to the very machinery that exists to resolve it.

        So the feeling is allowed to go and the QUESTION is handed to its owner
        — the belief authority's known-unknowns, where a gap is resolvable by
        acquisition and where the curiosity drive already reads it (see
        `_measure_curiosity`). Idempotent: a doubt that recurs and fades
        repeatedly is one open question, not a pile of them.

        NO OBJECT, NO QUESTION. A doubt that faded without appraisal ever naming
        what it was about cannot be written down without inventing a subject, so
        it is counted as lost rather than fabricated into a question the
        substrate never had.
        """
        if self._affect_emotion != "doubt":
            return
        about = self._affect_about
        if not about:
            self._questions_lost += 1
            logger.warning(
                "a doubt faded with nothing naming what it was about — the "
                "feeling went and no question was kept (%d so far)",
                self._questions_lost)
            return
        question = f"what is unresolved about {about}?"
        # `self` is the domain this substrate already files what it learns
        # about ITSELF under (`record_finding`). Filing under an invented name
        # would leave the question somewhere nothing looks.
        domain = self._affect_about_domain or "self"
        try:
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            unc = get_bayesian_uncertainty()
            if any(u.question == question and u.domain == domain
                   for u in unc.known_unknowns.values()):
                return                      # already open; one question, not many
            unc.register_known_unknown(
                question=question,
                domain=domain,
                blocking_factors=[
                    f"a doubt about {about} faded without being resolved"],
                required_info=[f"evidence that settles {about}"],
                target={"kind": "settled", "about": about})
            self._questions_kept += 1
            logger.info("doubt about %s faded — question kept as a known-unknown "
                        "in %s", about, domain)
        except Exception as error:
            self._questions_lost += 1
            logger.error("a doubt about %s faded and the question could NOT be "
                         "kept (%s) — the substrate has stopped wondering about "
                         "something it never settled", about, error)

    def _faded_intensity(self, at: "datetime") -> Optional[float]:
        """The current emotion's intensity, faded for the time since it was last
        supported by an appraisal. None when there is no emotion to fade."""
        if self._affect_intensity is None or self._last_affect_at is None:
            return self._affect_intensity
        import math
        dt = (at - self._last_affect_at).total_seconds()
        if dt <= 0:
            return self._affect_intensity
        return float(self._affect_intensity) * math.exp(
            -dt / self._EMOTION_HALFLIFE_S)

    def _decayed(self, at: "datetime") -> Tuple[float, float]:
        """The mood and arousal decayed toward baseline / rest for the wall-clock
        elapsed since the last event. Computed lazily so the felt state is always
        current WITHOUT any loop maintaining it. No last event → nothing to decay."""
        if self._last_affect_at is None:
            return self._mood_valence, self._mood_arousal
        import math
        dt = (at - self._last_affect_at).total_seconds()
        if dt <= 0:
            return self._mood_valence, self._mood_arousal
        vf = math.exp(-dt / self._MOOD_HALFLIFE_S)
        af = math.exp(-dt / self._AROUSAL_HALFLIFE_S)
        v = self._baseline_valence + (self._mood_valence - self._baseline_valence) * vf
        a = self._mood_arousal * af
        return v, a

    def mood(self) -> "Mood":
        """The substrate's mood RIGHT NOW — the stored mood decayed to the current
        time. Always current on read; no loop maintains it."""
        from datetime import datetime, timezone
        v, a = self._decayed(datetime.now(timezone.utc))
        return Mood(valence=round(v, 4), arousal=round(a, 4),
                    baseline=round(self._baseline_valence, 4),
                    event_count=self._affect_event_count, loaded=self._affect_loaded)

    def valence(self) -> float:
        """The substrate's felt valence now — decayed to the current time."""
        from datetime import datetime, timezone
        v, _ = self._decayed(datetime.now(timezone.utc))
        return round(v, 4)

    def affect_state(self) -> "AffectState":
        """The substrate's affect as STATE — the current named emotion (a fact that
        rehydrated as-is), its cause and intensity, and the mood decayed to now.
        This is what the coordinator reads from the substrate; it is never
        reconstructed from the database or handed in as context."""
        from datetime import datetime, timezone
        v, a = self._decayed(datetime.now(timezone.utc))
        return AffectState(
            emotion=self._affect_emotion, intensity=self._affect_intensity,
            cause=self._affect_cause, about=self._affect_about,
            valence=round(v, 4), arousal=round(a, 4),
            baseline=round(self._baseline_valence, 4), version=self._affect_version,
            updated_at=(self._last_affect_at.isoformat() if self._last_affect_at else None),
            loaded=self._affect_loaded,
        )

    async def _ensure_affect_table(self) -> None:
        if not self.db:
            return
        await self.db.execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.affect_state (
                id               INTEGER PRIMARY KEY DEFAULT 1,
                emotion          TEXT,
                intensity        DOUBLE PRECISION,
                cause            TEXT,
                about            TEXT,
                about_domain     TEXT,
                mood_valence     DOUBLE PRECISION NOT NULL DEFAULT 0,
                mood_arousal     DOUBLE PRECISION NOT NULL DEFAULT 0,
                baseline_valence DOUBLE PRECISION NOT NULL DEFAULT 0,
                version          INTEGER NOT NULL DEFAULT 0,
                event_count      INTEGER NOT NULL DEFAULT 0,
                updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT affect_state_singleton CHECK (id = 1)
            )
            """,
            commit=True,
        )
        # Idempotent columns for a table created by an earlier revision.
        for col, ddl in (("emotion", "TEXT"), ("intensity", "DOUBLE PRECISION"),
                         ("cause", "TEXT"), ("about", "TEXT"),
                         ("about_domain", "TEXT"),
                         ("version", "INTEGER NOT NULL DEFAULT 0")):
            await self.db.execute_query(
                f"ALTER TABLE unified.affect_state ADD COLUMN IF NOT EXISTS {col} {ddl}",
                commit=True,
            )

    async def _persist_affect(self) -> None:
        """Write the current affect STATE to Postgres so it rehydrates on restart —
        the named emotion + cause + version, not just the mood reading."""
        if not self.db:
            return
        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.affect_state
                    (id, emotion, intensity, cause, about, about_domain,
                     mood_valence, mood_arousal,
                     baseline_valence, version, event_count, updated_at)
                VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now())
                ON CONFLICT (id) DO UPDATE SET
                    emotion=$1, intensity=$2, cause=$3, about=$4,
                    about_domain=$5, mood_valence=$6,
                    mood_arousal=$7, baseline_valence=$8, version=$9,
                    event_count=$10, updated_at=now()
                """,
                params=(self._affect_emotion, self._affect_intensity, self._affect_cause,
                        self._affect_about, self._affect_about_domain,
                        self._mood_valence, self._mood_arousal, self._baseline_valence,
                        self._affect_version, self._affect_event_count),
                commit=True,
            )
        except Exception as e:
            logger.warning("affect persist failed: %s", e)

    async def _load_affect(self) -> None:
        """Restore mood + baseline from Postgres on startup. No row ⇒ honest
        cold-start neutral (never a fabricated prior mood)."""
        if not self.db:
            return
        try:
            await self._ensure_affect_table()
            row = await self.db.execute_query(
                "SELECT emotion, intensity, cause, about, about_domain, "
                "mood_valence, mood_arousal, "
                "baseline_valence, version, event_count, updated_at "
                "FROM unified.affect_state WHERE id=1",
                fetch_one=True,
            )
            if row:
                # rehydrate the affect STATE as a fact — the substrate resumes in
                # this emotion; no re-appraisal happens merely because it restarted.
                self._affect_emotion = row["emotion"]
                self._affect_intensity = float(row["intensity"]) if row["intensity"] is not None else None
                self._affect_cause = row["cause"]
                self._affect_about = row["about"]
                self._affect_about_domain = row["about_domain"]
                self._affect_version = int(row["version"] or 0)
                self._mood_valence = float(row["mood_valence"])
                self._mood_arousal = float(row["mood_arousal"])
                self._baseline_valence = float(row["baseline_valence"])
                self._affect_event_count = int(row["event_count"])
                # restore the decay anchor so time spent OFFLINE fades the mood too:
                # a mood earned yesterday should read faded when the substrate wakes.
                self._last_affect_at = row["updated_at"]
                self._affect_loaded = True
                logger.info("Affect rehydrated: emotion=%s about=%s cause=%s v=%d mood_valence=%.3f baseline=%.3f (n=%d)",
                            self._affect_emotion, self._affect_about,
                            self._affect_cause, self._affect_version,
                            self._mood_valence, self._baseline_valence, self._affect_event_count)
            else:
                logger.info("No persisted affect — cold start at neutral")
        except Exception as e:
            logger.warning("affect load failed, cold start: %s", e)

    async def _quantify_component_uncertainties(self, system_context: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """
        Step 1: Quantify epistemic uncertainty per component from system signals.

        Distinguishes:
        - Epistemic uncertainty (can be reduced by learning)
        - Aleatoric uncertainty (inherent randomness)
        - Structural flaws (deterministic failures)
        """
        component_metrics = {}

        if not system_context:
            return component_metrics

        # Extract component failures from failed_tasks
        failed_tasks = system_context.get('failed_tasks', [])
        task_stats = {}  # component -> {failures, total, confidence_scores}

        for task in failed_tasks:
            component = self._extract_component_from_task(task)
            if component not in task_stats:
                task_stats[component] = {'failures': 0, 'total': 0, 'confidence_scores': []}

            task_stats[component]['total'] += 1
            if task.get('status') == 'failed':
                task_stats[component]['failures'] += 1

            if 'confidence' in task:
                task_stats[component]['confidence_scores'].append(task['confidence'])

        # Extract performance degradation from performance_metrics
        performance_metrics = system_context.get('performance_metrics', {})

        # Extract error patterns from recent_errors
        recent_errors = system_context.get('recent_errors', [])
        error_stats = {}  # component -> {error_types, error_variance}

        for error in recent_errors:
            component = error.get('component', 'unknown')
            if component not in error_stats:
                error_stats[component] = {'error_types': set(), 'error_count': 0}

            error_stats[component]['error_types'].add(error.get('type', 'unknown'))
            error_stats[component]['error_count'] += 1

        # Extract knowledge gaps
        knowledge_gaps = system_context.get('knowledge_gaps', [])
        gap_stats = {}  # component -> uncertainty_score

        for gap in knowledge_gaps:
            component = gap.get('component', 'unknown')
            gap_stats[component] = gap.get('uncertainty', 0.5)

        # Combine all signals into component_metrics
        all_components = set(task_stats.keys()) | set(error_stats.keys()) | set(gap_stats.keys()) | set(performance_metrics.keys())

        for component in all_components:
            # Calculate failure_rate
            task_info = task_stats.get(component, {'failures': 0, 'total': 0, 'confidence_scores': []})
            failure_rate = task_info['failures'] / task_info['total'] if task_info['total'] > 0 else 0.0

            # Calculate confidence_variance
            conf_scores = task_info['confidence_scores']
            confidence_variance = np.var(conf_scores) if len(conf_scores) > 1 else 0.0

            # Calculate prediction_error (from performance_metrics if available)
            perf_data = performance_metrics.get(component, {})
            # Ensure perf_data is a dict (could be int/float from malformed system_context)
            if not isinstance(perf_data, dict):
                perf_data = {}
            prediction_error = perf_data.get('prediction_error', failure_rate * 0.7)

            # Calculate performance_degradation
            current_perf = perf_data.get('current', 1.0)
            baseline_perf = perf_data.get('baseline', 1.0)
            performance_degradation = max(0, 1.0 - (current_perf / baseline_perf)) if baseline_perf > 0 else 0.0

            # Calculate epistemic_uncertainty (distinguishing from aleatoric/structural)
            error_info = error_stats.get(component, {'error_types': set(), 'error_count': 0})
            error_diversity = len(error_info['error_types'])

            # High variance + high error = epistemic (learnable)
            # Low variance + high error = aleatoric or structural flaw
            if confidence_variance > 0.15 and prediction_error > 0.3:
                epistemic_uncertainty = min(0.9, prediction_error + confidence_variance * 0.5)
            elif confidence_variance < 0.05 and prediction_error > 0.4:
                # Deterministic failure - structural, not epistemic
                epistemic_uncertainty = 0.2
            else:
                # Mix of epistemic and aleatoric
                epistemic_uncertainty = gap_stats.get(component, prediction_error * 0.6)

            # Calculate impact_radius based on component type
            impact_radius = self._calculate_impact_radius(component, error_info['error_count'])

            # Calculate novelty_potential (inverse of exploration frequency)
            theme = self._extract_theme(component)
            exploration_frequency = await self._get_theme_count_from_db(theme)
            novelty_potential = max(0.1, 1.0 - (exploration_frequency * 0.1))

            component_metrics[component] = {
                'epistemic_uncertainty': round(epistemic_uncertainty, 3),
                'confidence_variance': round(confidence_variance, 3),
                'prediction_error': round(prediction_error, 3),
                'failure_rate': round(failure_rate, 3),
                'impact_radius': impact_radius,
                'performance_degradation': round(performance_degradation, 3),
                'novelty_potential': round(novelty_potential, 3)
            }

        return component_metrics

    def _extract_component_from_task(self, task: Dict[str, Any]) -> str:
        """Extract component name from task description or metadata"""
        if 'component' in task:
            return task['component']

        description = task.get('description', '').lower()
        # Map keywords to components
        component_keywords = {
            'memory': 'memory_agent',
            'neural': 'neural_bridge',
            'learning': 'learning',
            'security': 'security',
            'tool': 'tool_execution',
            'database': 'database',
            'api': 'api_layer'
        }

        for keyword, component in component_keywords.items():
            if keyword in description:
                return component

        return 'unknown'

    def _calculate_impact_radius(self, component: str, error_count: int) -> float:
        """Calculate impact radius: 0.0=component, 0.5=system, 1.0=user-facing"""
        # User-facing components have highest impact
        user_facing = ['api_layer', 'security']
        system_critical = ['memory_agent', 'neural_bridge', 'database']

        if component in user_facing:
            base_impact = 1.0
        elif component in system_critical:
            base_impact = 0.7
        else:
            base_impact = 0.3

        # Scale by error frequency
        error_multiplier = min(1.0, 1.0 + (error_count * 0.05))
        return min(1.0, base_impact * error_multiplier)

    async def _calculate_uncertainty_gradients(self, component_metrics: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """
        Step 2: Calculate uncertainty gradients (Δ from rolling baseline).

        Rising uncertainty is more important than static high uncertainty.
        """
        deltas = {}

        for component, metrics in component_metrics.items():
            epistemic = metrics.get('epistemic_uncertainty', 0.0)

            # Get baseline from database
            baseline_data = await self._get_component_baseline_from_db(component)

            if not baseline_data:
                # First observation, no gradient
                baseline_data = {'epistemic_uncertainty': epistemic}
                await self._update_component_baseline_in_db(component, baseline_data)
                deltas[component] = 0.0
            else:
                baseline = baseline_data.get('epistemic_uncertainty', epistemic)
                deltas[component] = epistemic - baseline

                # Update rolling baseline (exponential moving average, α=0.3)
                new_baseline = 0.3 * epistemic + 0.7 * baseline
                baseline_data['epistemic_uncertainty'] = new_baseline
                await self._update_component_baseline_in_db(component, baseline_data)

                # Also update in-memory cache
                self._component_baselines[component] = baseline_data

            # Store in history (both database and memory cache)
            await self._store_metric_history_to_db(component, metrics)

            # Update in-memory cache
            if component not in self._metric_history:
                self._metric_history[component] = []
            self._metric_history[component].append(metrics.copy())
            # Keep last 50 entries in cache
            if len(self._metric_history[component]) > 50:
                self._metric_history[component] = self._metric_history[component][-50:]

        return deltas

    async def _calculate_goal_priority(self, component: str, metrics: Dict[str, float], delta: float) -> float:
        """
        Step 3: Calculate weighted priority score.

        GoalPriority =
            w1 * EpistemicUncertainty
          + w2 * ImpactRadius
          + w3 * PerformanceDegradation
          + w4 * NoveltyPotential
          - w5 * RecentExplorationPenalty
        """
        w = self._priority_weights

        # Extract metrics
        epistemic_uncertainty = metrics.get('epistemic_uncertainty', 0.0)
        impact_radius = metrics.get('impact_radius', 0.5)  # 0=component, 0.5=system, 1.0=user-facing
        perf_degradation = metrics.get('performance_degradation', 0.0)
        novelty_potential = metrics.get('novelty_potential', 0.5)

        # Recent exploration penalty (have we explored this component recently?)
        recent_penalty = 0.0
        theme = self._extract_theme(component)
        repeat_count = await self._get_theme_count_from_db(theme)
        if repeat_count > 0:
            recent_penalty = min(repeat_count * 0.1, 1.0)  # Cap at 1.0

        # Boost for rising uncertainty (gradient)
        uncertainty_with_gradient = epistemic_uncertainty + max(0, delta) * 0.5

        priority = (
            w['epistemic_uncertainty'] * uncertainty_with_gradient +
            w['impact_radius'] * impact_radius +
            w['performance_degradation'] * perf_degradation +
            w['novelty_potential'] * novelty_potential +
            w['recent_exploration_penalty'] * recent_penalty
        )

        return max(0.0, priority)  # No negative priorities

    async def _sample_goal_candidates(self, candidates: List[Dict], max_goals: int) -> List:
        """
        Step 4: Stochastic sampling from top candidates (softmax).

        Avoids deterministic "always pick highest" which causes tunneling.
        """
        from .shared_types import Goal, Priority
        import uuid

        if not candidates:
            return []

        # Sort by priority
        candidates_sorted = sorted(candidates, key=lambda x: x['priority_score'], reverse=True)

        # Take top 2*max_goals candidates
        top_candidates = candidates_sorted[:max_goals * 2]

        if not top_candidates:
            return []

        # Softmax sampling (temperature = 0.5 for moderate stochasticity)
        scores = np.array([c['priority_score'] for c in top_candidates])
        temperature = 0.5
        exp_scores = np.exp(scores / temperature)
        probabilities = exp_scores / exp_scores.sum()

        # Sample without replacement
        num_to_sample = min(max_goals, len(top_candidates))
        # Use boot-entropy-seeded RNG to avoid identical early-session sampling
        # when metrics are stable.
        rng = getattr(self, "_entropy_np_rng", None)
        if rng is None:
            sampled_indices = np.random.choice(
                len(top_candidates),
                size=num_to_sample,
                replace=False,
                p=probabilities
            )
        else:
            sampled_indices = rng.choice(
                len(top_candidates),
                size=num_to_sample,
                replace=False,
                p=probabilities
            )

        # Generate goals from sampled candidates
        goals = []
        for idx in sampled_indices:
            candidate = top_candidates[idx]
            goal = await self._create_metric_driven_goal(candidate)
            if goal:
                goals.append(goal)

        return goals

    async def _create_metric_driven_goal(self, candidate: Dict):
        """
        Create goal directly from metrics - NO LLM, NO templates.

        Format: "component shows X variance and Y error (Δ +Z from baseline) → action"
        """
        from .shared_types import Goal, Priority
        import uuid

        component = candidate['component']
        metrics = candidate['metrics']
        delta = candidate['delta']
        priority_score = candidate['priority_score']

        # AN ABSENT METRIC IS NOT A GOOD SCORE.
        #
        # These defaulted to 0.0, and every gate below reads them as "better
        # than threshold": 0.0 prediction_error and 0.0 failure_rate mean
        # flawless, 0.0 confidence_variance means perfectly certain. So a
        # component whose metrics were never collected produced the same
        # reading as a component measured as healthy — and since the whole
        # point of this generator is to raise goals about components that are
        # doing BADLY, missing data silently suppressed exactly the goals it
        # exists to create. The worse the instrumentation, the healthier the
        # component looked.
        #
        # Absent stays absent. Present-but-zero is still a real measurement and
        # is kept, so this distinguishes "measured 0.0" from "never measured".
        MEASURES = ('epistemic_uncertainty', 'confidence_variance',
                    'prediction_error', 'failure_rate')
        measured = {k: metrics[k] for k in MEASURES
                    if metrics.get(k) is not None}

        if not measured:
            logger.debug(
                "No metric measured for %s (%s absent); no metric-driven goal — "
                "a goal about performance cannot be built from missing data",
                component, "/".join(MEASURES))
            return None

        epistemic_unc = measured.get('epistemic_uncertainty')
        confidence_var = measured.get('confidence_variance')
        prediction_error = measured.get('prediction_error')
        failure_rate = measured.get('failure_rate')

        def over(value, threshold):
            """True only when a MEASURED value exceeds the threshold."""
            return value is not None and value > threshold

        # Build metric-driven description
        metric_summary = f"{component} shows "
        metric_parts = []

        if over(confidence_var, 0.2):
            metric_parts.append(f"{confidence_var:.2f} confidence variance")
        if over(prediction_error, 0.3):
            metric_parts.append(f"{prediction_error:.0%} prediction error")
        if over(failure_rate, 0.2):
            metric_parts.append(f"{failure_rate:.0%} failure rate")

        if not metric_parts:
            # Name whichever measure actually exists, rather than printing a
            # fabricated 0.00 epistemic uncertainty for a component that was
            # measured on a different axis entirely.
            key, value = next(iter(measured.items()))
            metric_parts.append(f"{value:.2f} {key.replace('_', ' ')}")

        metric_summary += ", ".join(metric_parts)

        # Add gradient if significant
        if abs(delta) > 0.1:
            metric_summary += f" (Δ {delta:+.2f} from baseline)"

        # Determine action based on dominant signal
        if over(prediction_error, 0.4):
            action = "analyze prediction failures and model assumptions"
        elif over(failure_rate, 0.4):
            action = "investigate failure patterns and error handling"
        elif over(confidence_var, 0.3):
            action = "profile uncertainty sources and input distribution"
        else:
            action = "explore capability boundaries and edge cases"

        description = f"{metric_summary} → {action}"

        # NOVELTY IS NOT A GATE AND NOT A PRIORITY INPUT. Whether this component
        # merits a goal, and its priority, are decided by the measured metrics
        # above — deterministic and model-free. MiniLM's similarity is computed
        # and stored ONLY for DOWNSTREAM dedup/retrieval (recorded as metadata,
        # maintaining the embedding index); it never suppresses a metric-valid
        # goal and never feeds the goal's priority/novelty fields. Severing MiniLM
        # must not change whether the goal forms OR how it ranks.
        similarity, _ = await self._calculate_goal_similarity(description)

        # Store embedding (maintain the index for downstream novelty/retrieval)
        theme = self._extract_theme(description)
        await self._store_goal_embedding(description, theme, component, "metric_driven", "investigate")
        await self._increment_theme_count(theme)

        # Create goal
        goal = Goal(
            id=f"intrinsic_goal_{uuid.uuid4().hex[:8]}",
            description=description,
            priority=Priority.LOW,
            # Derived from measurements, never from a substituted default: a
            # curiosity value invented from an absent uncertainty is a number
            # the ranker cannot tell from a real one.
            curiosity_value=(epistemic_unc * 0.9) if epistemic_unc is not None
                            else float(priority_score),
            # DETERMINISTIC — the theme-frequency novelty the substrate measures.
            # MiniLM does not feed this.
            expected_novelty=(metrics['novelty_potential'] * 0.8
                              if metrics.get('novelty_potential') is not None else 1.0),
            expected_competence_gain=0.7,
            intrinsic_reward_potential=priority_score
        )

        # Tag goal with source component and pre-task uncertainty for closed-loop completion gate
        goal.metadata["target_component"] = component
        goal.metadata["uncertainty_before"] = epistemic_unc
        goal.metadata["novelty_similarity"] = similarity  # guidance, not a gate

        logger.info(f"Created metric-driven goal (priority={priority_score:.2f}): {description[:80]}...")
        return goal


    async def _generate_epistemic_goals(self, max_goals: int) -> List:
        """
        Generate goals targeting high-entropy beliefs and stalled hypotheses.

        Queries EpistemicEngine.get_unstable_regions() for the current set of
        beliefs with entropy > 0.85 and stalled hypotheses (old + low evidence).
        Returns Goal objects tagged with requires_epistemic_output=True so the
        executor gate enforces that completing them mutates the belief graph.

        Priority is proportional to entropy: high entropy = high exploration drive.
        Does NOT invert — we want to explore uncertainty, not certainty.

        Args:
            max_goals: Maximum number of epistemic goals to return.

        Returns:
            List of Goal objects (may be empty if no unstable regions found).
        """
        if max_goals <= 0:
            return []

        from .shared_types import Goal, Priority
        import uuid

        try:
            from core.reasoning.epistemic_engine import get_epistemic_engine
            targets = get_epistemic_engine().get_unstable_regions()
        except Exception as e:
            logger.warning(f"_generate_epistemic_goals: EpistemicEngine unavailable: {e}")
            return []

        if not targets:
            return []

        # A detected KNOWLEDGE GAP is a concrete, resolvable acquisition target
        # produced from a real question; a high-entropy belief is a diffuse
        # experiment target. Every crystallized domain contributes a competence
        # belief at posterior 0.5 (maximal entropy), so beliefs are MANY and gaps
        # are FEW -- taking a single entropy-sorted prefix would let the belief
        # sea starve the gaps out of the budget entirely. Reserve up to half the
        # budget for gaps (still entropy-ranked among themselves), so a detected
        # gap is reliably pursued while beliefs keep the rest.
        gaps = [t for t in targets if t.target_type == "knowledge_gap"]
        others = [t for t in targets if t.target_type != "knowledge_gap"]
        n_gap = min(len(gaps), max(1, max_goals // 2)) if gaps else 0
        selected = gaps[:n_gap] + others[:max_goals - n_gap]

        goals = []
        for target in selected:
            description = target.description

            # Novelty is GUIDANCE, not a veto. An unstable belief that needs
            # resolving does not stop mattering because a similar goal was issued
            # — the entropy decides. Similarity is kept as metadata guidance (and
            # for downstream dedup), never a suppressor of a real epistemic goal.
            try:
                similarity, _ = await self._calculate_goal_similarity(description)
            except Exception:
                similarity = 0.0
                self.logger.warning("Novelty check failed: %s", description)

            # Store embedding for future novelty checks
            try:
                theme = self._extract_theme(description)
                await self._store_goal_embedding(
                    description, theme, target.domain, "epistemic", "investigate"
                )
                await self._increment_theme_count(theme)
            except Exception as e:
                self.logger.error("Error storing goal embedding: %s", str(e))

            # Priority proportional to entropy: [0.85, 1.0] → [0.0, 1.0]
            priority_score = (target.entropy - 0.85) / 0.15
            priority_score = max(0.05, min(1.0, priority_score))

            goal = Goal(
                id=f"epistemic_goal_{uuid.uuid4().hex[:8]}",
                description=description,
                priority=Priority.MEDIUM if priority_score > 0.5 else Priority.LOW,
                curiosity_value=target.entropy,
                # DETERMINISTIC. MiniLM does not feed priority/novelty; the goal
                # forms and ranks from entropy either way.
                expected_novelty=0.8,
                expected_competence_gain=0.6,
                intrinsic_reward_potential=priority_score,
            )
            # Tag with all epistemic metadata — executor and coordinator read this
            goal.metadata.update(target.metadata)
            goal.metadata["novelty_similarity"] = similarity  # guidance, not a gate

            logger.info(
                f"Epistemic goal (entropy={target.entropy:.3f}, "
                f"type={target.target_type}): {description[:80]}..."
            )
            goals.append(goal)

        return goals

    # =========================================================================
    # PLAN DIVERSITY ENFORCEMENT & TOOL REPETITION PENALTY
    # =========================================================================

    async def _store_goal_embedding_to_db(self, goal_description: str, theme: str,
                                          component: str, abstraction: str, objective: str,
                                          embedding: np.ndarray) -> None:
        """Store goal embedding to novelty_detections table"""
        if not self.db:
            return

        try:
            experience_hash = hashlib.md5(goal_description.encode()).hexdigest()

            # Calculate novelty score (0 if first time, otherwise based on similarity)
            novelty_score = 1.0  # Default high novelty for new goals

            await self.db.execute_query(
                """
                INSERT INTO novelty_detections (
                    id,
                    timestamp,
                    experience_hash,
                    novelty_score,
                    context,
                    metadata
                ) VALUES ($1, $2, $3, $4, $5, $6)
                """,
                params=(
                    f"novelty_{int(time.time() * 1000)}_{experience_hash[:8]}",
                    datetime.now(),
                    experience_hash,
                    float(novelty_score),
                    json.dumps({'description': goal_description, 'theme': theme}),
                    json.dumps({
                        'theme': theme,
                        'component': component,
                        'abstraction_level': abstraction,
                        'objective_type': objective,
                        'embedding': embedding.tolist() if isinstance(embedding, np.ndarray) else embedding,
                        'repeat_count': await self._get_theme_count_from_db(theme),
                    }),
                ),
                commit=True,
            )

            logger.debug(f"Stored goal embedding to DB: {theme}")

        except Exception as e:
            logger.error(f"Failed to store goal embedding to DB: {e}")

    async def _load_goal_embeddings_from_db(self, limit: int = 100) -> List[GoalEmbedding]:
        """Load recent goal embeddings from novelty_detections table"""
        if not self.db:
            return []

        try:
            results = await self.db.execute_query(
                """
                SELECT context, metadata, timestamp
                FROM novelty_detections
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                params=(limit,),
                fetch_all=True,
            )

            if not results:
                return []

            goal_embeddings = []
            for row in results:
                try:
                    context = json.loads(row['context']) if isinstance(row['context'], str) else row['context']
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                    embedding_data = metadata.get('embedding', [])
                    embedding = np.array(embedding_data) if embedding_data else np.zeros(384)

                    goal_emb = GoalEmbedding(
                        description=context.get('description', ''),
                        embedding=embedding,
                        theme=metadata.get('theme', 'unknown'),
                        component=metadata.get('component', 'unknown'),
                        abstraction_level=metadata.get('abstraction_level', 'medium'),
                        objective_type=metadata.get('objective_type', 'explore'),
                        timestamp=row['timestamp'],
                        repeat_count=metadata.get('repeat_count', 0)
                    )
                    goal_embeddings.append(goal_emb)

                except Exception as parse_error:
                    logger.debug(f"Failed to parse goal embedding row: {parse_error}")
                    continue

            logger.debug(f"Loaded {len(goal_embeddings)} goal embeddings from DB")
            return goal_embeddings

        except Exception as e:
            logger.error(f"Failed to load goal embeddings from DB: {e}")
            return []

    async def _restore_event_rewards(self, window: int = 100) -> None:
        """Reload recent event rewards so drive state survives a restart.

        unified.intrinsic_motivation already held every reward ever computed and
        NOTHING read them back: the only query against this table filters
        motivation_type='theme_count'. Rewards were write-only, so on every
        restart the system's sense of how worthwhile its recent experience had
        been reset to zero.
        """
        if not self.db:
            logger.warning("Cannot restore event rewards: no database handle")
            return
        try:
            # get_database_manager() hands back an UNINITIALISED manager; whether
            # someone else has initialised it by now is an ordering accident.
            # initialize() is idempotent, so make this self-sufficient rather
            # than silently restoring zero rewards.
            if not getattr(self.db, 'initialized', False):
                await self.db.initialize()

            rows = await self.db.execute_query(
                """
                SELECT score FROM intrinsic_motivation
                WHERE motivation_type = 'task_outcome'
                ORDER BY timestamp DESC LIMIT $1
                """,
                params=(window,),
                fetch_all=True,
            )
            if not rows:
                return
            values = [float(r['score']) for r in rows if r['score'] is not None]
            if not values:
                return
            self.profile.accumulated_event_reward = sum(values)
            self.profile.event_reward_count = len(values)
            logger.info(
                "Restored %d event rewards (mean %.4f) from unified.intrinsic_motivation",
                len(values), self.profile.mean_event_reward,
            )
        except Exception as e:
            logger.warning(f"Could not restore event rewards: {e}")

    async def _get_theme_count_from_db(self, theme: str) -> int:
        """Get theme repetition count from database"""
        if not self.db:
            return 0

        try:
            results = await self.db.execute_query(
                """
                SELECT COUNT(*) AS count
                FROM intrinsic_motivation
                WHERE motivation_type = 'theme_count' AND context = $1
                """,
                params=(theme,),
                fetch_all=True,
            )

            if results and len(results) > 0:
                return results[0]['count']
            return 0

        except Exception as e:
            logger.error(f"Failed to get theme count from DB: {e}")
            return 0

    async def _increment_theme_count_in_db(self, theme: str) -> None:
        """Increment theme repetition count in database"""
        if not self.db:
            return

        try:
            # Insert or update theme count
            await self.db.execute_query(
                """
                INSERT INTO intrinsic_motivation (
                    id,
                    timestamp,
                    motivation_type,
                    score,
                    context,
                    metadata
                ) VALUES ($1, $2, 'theme_count', 1, $3, $4)
                ON CONFLICT (id) DO UPDATE SET
                    score = intrinsic_motivation.score + 1,
                    timestamp = EXCLUDED.timestamp,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    f"theme_{theme}_{int(time.time())}",
                    datetime.now(),
                    theme,
                    json.dumps({'theme': theme, 'updated': datetime.now().isoformat()}),
                ),
                commit=True,
            )

            logger.debug(f"Incremented theme count in DB: {theme}")

        except Exception as e:
            logger.error(f"Failed to increment theme count in DB: {e}")

    async def _get_component_baseline_from_db(self, component: str) -> Optional[Dict[str, float]]:
        """Get component baseline metrics from component_health table"""
        if not self.db:
            return None

        try:
            results = await self.db.execute_query(
                """
                SELECT metadata, health_score, last_updated
                FROM component_health
                WHERE component_name = $1
                ORDER BY last_updated DESC
                LIMIT 1
                """,
                params=(component,),
                fetch_all=True,
            )

            if results and len(results) > 0:
                row = results[0]
                metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

                return {
                    'epistemic_uncertainty': metadata.get('epistemic_uncertainty', 0.5),
                    'impact_radius': metadata.get('impact_radius', 0.5),
                    'performance_degradation': metadata.get('performance_degradation', 0.0),
                    'novelty_potential': metadata.get('novelty_potential', 0.5),
                    'health_score': float(row['health_score']) if row['health_score'] else 0.5
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get component baseline from DB: {e}")
            return None

    async def _update_component_baseline_in_db(self, component: str, metrics: Dict[str, float]) -> None:
        """Update component baseline metrics in component_health table"""
        if not self.db:
            return

        try:
            # Calculate health score from metrics
            # 0-100, the scale unified.component_health is declared on
            # (ComponentHealth.health_score: float = 100.0  # 0-100) and the
            # scale every consumer gates against: assessment treats < 90 as
            # needing improvement, and the deployment hard gate blocks below 80.
            # Writing the raw 0-1 value put rows of 0.8-1.0 in that column, so
            # every component read as catastrophically unhealthy -- assessment
            # fired on all of them and the deployment gate could never open.
            health_score = (1.0 - metrics.get('epistemic_uncertainty', 0.5)) * 100.0

            await self.db.execute_query(
                """
                INSERT INTO component_health (
                    component_name,
                    status,
                    error_count,
                    success_count,
                    health_score,
                    last_updated,
                    metadata
                ) VALUES ($1, $2, 0, 0, $3, $4, $5)
                ON CONFLICT (component_name) DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    component,
                    'monitoring',
                    float(health_score),
                    datetime.now(),
                    json.dumps(metrics),
                ),
                commit=True,
            )

            logger.debug(f"Updated component baseline in DB: {component}")

        except Exception as e:
            logger.error(f"Failed to update component baseline in DB: {e}")

    async def _store_metric_history_to_db(self, component: str, metrics: Dict[str, float]) -> None:
        """Store metric history entry to component_health table"""
        if not self.db:
            return

        try:
            # 0-100, the scale unified.component_health is declared on
            # (ComponentHealth.health_score: float = 100.0  # 0-100) and the
            # scale every consumer gates against: assessment treats < 90 as
            # needing improvement, and the deployment hard gate blocks below 80.
            # Writing the raw 0-1 value put rows of 0.8-1.0 in that column, so
            # every component read as catastrophically unhealthy -- assessment
            # fired on all of them and the deployment gate could never open.
            health_score = (1.0 - metrics.get('epistemic_uncertainty', 0.5)) * 100.0

            await self.db.execute_query(
                """
                INSERT INTO component_health (
                    component_name, status, error_count, success_count,
                    health_score, last_updated, metadata
                ) VALUES ($1, 'history', 0, 0, $2, $3, $4)
                ON CONFLICT (component_name) 
                DO UPDATE SET
                    health_score = EXCLUDED.health_score,
                    last_updated = EXCLUDED.last_updated,
                    metadata = EXCLUDED.metadata
                """,
                params=(
                    component,
                    health_score,
                    datetime.now(),
                    json.dumps(metrics)
                ),
                commit=True
            )

            logger.debug(f"Stored metric history to DB: {component}")

        except Exception as e:
            logger.error(f"Failed to store metric history to DB: {e}")

    async def _load_metric_history_from_db(self, component: str, limit: int = 50) -> List[Dict[str, float]]:
        """Load metric history from component_health table"""
        if not self.db:
            return []

        try:
            results = await self.db.execute_query(
                """
                SELECT metadata, last_updated
                FROM component_health
                WHERE component_name = $1 AND status = 'history'
                ORDER BY last_updated DESC
                LIMIT $2
                """,
                params=(component, limit),
                fetch_all=True,
            )

            history = []
            for row in results:
                try:
                    metadata = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']
                    history.append(metadata)
                except Exception as parse_error:
                    logger.debug(f"Failed to parse metric history row: {parse_error}")
                    continue

            # Reverse to get chronological order
            history.reverse()

            logger.debug(f"Loaded {len(history)} metric history entries from DB for {component}")
            return history

        except Exception as e:
            logger.error(f"Failed to load metric history from DB: {e}")
            return []

    async def get_skill_recommendations(self, max_skills: int = 10) -> List[Tuple[str, float]]:
        """
        Get skill/domain recommendations ranked by learning potential

        Ranks domains based on:
        - Prior success rate (META memory)
        - Bayesian belief confidence
        - Abstraction coverage (schemas formed)
        - Cross-domain transfer potential

        Args:
            max_skills: Maximum number of skills to return

        Returns:
            List of (domain_name, score) tuples sorted by score descending
        """
        try:
            from core.integration.universal_domain_master import get_universal_domain_master, DomainType
            from core.memory import get_memory_agent
            from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty
            from core.reasoning.hierarchical_abstraction import get_hierarchical_abstraction

            domain_master = get_universal_domain_master()
            memory_agent = await get_memory_agent()
            bayesian = get_bayesian_uncertainty()
            abstraction = get_hierarchical_abstraction()

            # Score each domain
            domain_scores: Dict[str, float] = {}

            for domain_type in DomainType:
                domain_name = domain_type.value
                score = 0.0

                # Factor 1: META memory success rate (40% weight)
                perf_stats = await self.get_domain_performance_stats(domain_name)
                success_rate = perf_stats.get("success_rate", 0.5)
                total_attempts = perf_stats.get("total_attempts", 0)

                # Reward domains with moderate success (learning zone: 50-80%)
                if 0.5 <= success_rate <= 0.8:
                    meta_score = 0.8
                elif 0.3 <= success_rate < 0.5:
                    meta_score = 0.6  # Challenging but improvable
                elif success_rate > 0.8:
                    meta_score = 0.3  # Too easy, low learning potential
                else:
                    meta_score = 0.4  # Very challenging

                # Boost if we have data
                if total_attempts > 0:
                    meta_score *= 1.2

                score += meta_score * 0.4

                # Factor 2: Bayesian belief confidence (25% weight)
                if bayesian and hasattr(bayesian, 'beliefs'):
                    domain_beliefs = [
                        belief for belief in bayesian.beliefs.values()
                        if belief.domain == domain_name
                    ]

                    if domain_beliefs:
                        avg_confidence = sum(b.posterior_probability for b in domain_beliefs) / len(domain_beliefs)
                        # Reward moderate confidence (learning zone)
                        if 0.4 <= avg_confidence <= 0.7:
                            belief_score = 0.8
                        elif avg_confidence < 0.4:
                            belief_score = 0.5  # Low confidence, needs work
                        else:
                            belief_score = 0.3  # High confidence, less to learn

                        score += belief_score * 0.25
                    else:
                        # No beliefs = unexplored domain
                        score += 0.6 * 0.25

                # Factor 3: Abstraction coverage (20% weight)
                if abstraction and hasattr(abstraction, 'active_schemas'):
                    domain_schemas = [
                        schema for schema in abstraction.active_schemas.values()
                        if schema.metadata.get('domain') == domain_name
                    ]

                    schema_count = len(domain_schemas)

                    # Reward domains with some but not too many schemas
                    if 2 <= schema_count <= 8:
                        abstraction_score = 0.8  # Good coverage, room to grow
                    elif schema_count < 2:
                        abstraction_score = 0.6  # Underdeveloped
                    else:
                        abstraction_score = 0.4  # Well-covered

                    score += abstraction_score * 0.20
                else:
                    score += 0.5 * 0.20

                # Factor 4: Cross-domain transfer potential (15% weight)
                # Query domain master for mappings
                if domain_master and hasattr(domain_master, 'mapping_cache'):
                    # Count mappings involving this domain
                    mapping_count = 0
                    for (source, target), mappings in domain_master.mapping_cache.items():
                        if source == domain_type or target == domain_type:
                            mapping_count += len(mappings)

                    # Reward domains with transfer potential
                    if mapping_count > 5:
                        transfer_score = 0.8  # High transfer potential
                    elif mapping_count > 0:
                        transfer_score = 0.6
                    else:
                        transfer_score = 0.4  # No known transfers

                    score += transfer_score * 0.15
                else:
                    score += 0.5 * 0.15

                domain_scores[domain_name] = score

            # Sort by score descending
            sorted_skills = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)

            # Return top N
            top_skills = sorted_skills[:max_skills]

            if top_skills:
                logger.info(f"🎯 Top skill recommendations: {', '.join(f'{s[0]}({s[1]:.2f})' for s in top_skills[:3])}")

            return top_skills

        except Exception as e:
            logger.error(f"Failed to get skill recommendations: {e}", exc_info=True)
            # Return default recommendations
            return [
                ("technical", 0.7),
                ("scientific", 0.65),
                ("practical", 0.6)
            ]

    # =========================================================================
    # HYPOTHESIS TESTING INTEGRATION
    # =========================================================================

    async def convert_goal_to_hypothesis(
        self,
        goal: Dict[str, Any]
    ) -> Optional[str]:
        """
        Convert an intrinsic exploration goal into a testable hypothesis.

        Args:
            goal: Goal dictionary with description, component, etc.

        Returns:
            hypothesis_id if hypothesis was created, None otherwise
        """
        try:
            # Route through the REASONING AUTHORITY — it owns the hypothesis
            # subsystem now. Intrinsic motivation ASKS the authority to generate a
            # hypothesis rather than reaching the hypothesis system directly (the
            # single-authority rule). Substrate-native: a goal becomes a
            # falsifiable claim the substrate can test, no model involved.
            from core.reasoning.neural_bridge import get_neural_bridge

            description = goal.get('description', '')
            component = goal.get('component', 'system')
            objective_type = goal.get('objective_type', 'explore')

            claim = self._goal_to_hypothesis_claim(description, objective_type)
            predictions = self._generate_hypothesis_predictions(goal, objective_type)

            hypothesis_id = await get_neural_bridge().generate_hypothesis(
                claim=claim,
                domain=component,
                predictions=predictions,
                alternatives=self._generate_alternative_hypotheses(goal),
            )
            if hypothesis_id is None:
                return None

            logger.info(f"✓ Created hypothesis {hypothesis_id} from goal: {description[:60]}...")

            # Store mapping between goal and hypothesis
            if hasattr(goal, 'get') and 'id' in goal:
                await self._store_goal_hypothesis_mapping(goal['id'], hypothesis_id)

            return hypothesis_id

        except Exception as e:
            logger.error(f"Failed to convert goal to hypothesis: {e}")
            return None

    def _goal_to_hypothesis_claim(self, description: str, objective_type: str) -> str:
        """Convert goal description into falsifiable hypothesis claim"""
        description_lower = description.lower()

        # Map objective types to hypothesis formats
        if objective_type == 'explore':
            if 'uncertainty' in description_lower:
                return f"Exploring {description} will reduce epistemic uncertainty by >10%"
            else:
                return f"{description} will reveal novel patterns or insights"

        elif objective_type == 'optimize':
            return f"{description} will improve performance metrics by >5%"

        elif objective_type == 'fix':
            return f"{description} will reduce error rate by >20%"

        elif objective_type == 'learn':
            return f"{description} will increase domain competence score by >0.1"

        else:
            # Generic explorative claim
            return f"Investigating {description} will produce measurable system improvements"

    def _generate_hypothesis_predictions(
        self,
        goal: Dict[str, Any],
        objective_type: str
    ) -> List[str]:
        """Generate testable predictions from goal"""
        predictions = []
        component = goal.get('component', 'system')

        if objective_type == 'explore':
            predictions.append(f"Component {component} uncertainty will decrease after exploration")
            predictions.append(f"Novelty detection will identify new patterns in {component}")
            predictions.append(f"Confidence scores for {component} will increase")

        elif objective_type == 'optimize':
            predictions.append(f"{component} performance metrics will improve")
            predictions.append(f"Resource utilization in {component} will be more efficient")
            predictions.append(f"Latency or error rates in {component} will decrease")

        elif objective_type == 'fix':
            predictions.append(f"Error count in {component} will decrease by >20%")
            predictions.append(f"Health score for {component} will improve")
            predictions.append(f"Failure rate in {component} will be reduced")

        elif objective_type == 'learn':
            predictions.append(f"Domain knowledge score for {component} will increase")
            predictions.append(f"Reasoning depth for {component} tasks will improve")
            predictions.append(f"Confidence in {component} decisions will be higher")

        return predictions

    def _generate_alternative_hypotheses(self, goal: Dict[str, Any]) -> List[str]:
        """Generate alternative explanations to test against"""
        description = goal.get('description', '')
        component = goal.get('component', 'system')

        return [
            f"{description} will have no measurable effect (null hypothesis)",
            f"{description} will reveal existing knowledge, not new insights",
            f"Random exploration would yield equivalent results",
            f"The observed effects are due to other system changes, not {component}",
        ]

    async def _store_goal_hypothesis_mapping(
        self,
        goal_id: str,
        hypothesis_id: str
    ) -> None:
        """Store mapping between goal and hypothesis for tracking"""
        if not self.db:
            return

        try:
            await self.db.execute_query(
                """
                INSERT INTO unified.novelty_detections
                (novelty_id, goal_description, theme, component, metadata)
                VALUES ($1, $2, 'hypothesis_mapping', 'intrinsic_motivation', $3)
                ON CONFLICT (novelty_id) DO UPDATE SET
                    metadata = EXCLUDED.metadata
                """,
                (
                    f"goal_hyp_map_{goal_id}",
                    f"Goal-Hypothesis mapping: {goal_id} -> {hypothesis_id}",
                    json.dumps({
                        'goal_id': goal_id,
                        'hypothesis_id': hypothesis_id,
                        'created_at': datetime.now().isoformat()
                    })
                ),
                commit=True
            )

            logger.debug(f"Stored goal-hypothesis mapping: {goal_id} -> {hypothesis_id}")

        except Exception as e:
            logger.error(f"Failed to store goal-hypothesis mapping: {e}")



# ============================================================================
# Singleton accessor
# ============================================================================

_intrinsic_motivation_system: Optional[IntrinsicMotivationSystem] = None


def get_intrinsic_motivation_system(
    config: Optional[Dict[str, Any]] = None,
) -> IntrinsicMotivationSystem:
    """Get global IntrinsicMotivationSystem instance (singleton).

    The first caller may provide configuration; later calls ignore
    config overrides and return the existing instance.
    """
    global _intrinsic_motivation_system

    if _intrinsic_motivation_system is None:
        _intrinsic_motivation_system = IntrinsicMotivationSystem(config=config)
    else:
        if config:
            logger.debug(
                "get_intrinsic_motivation_system called with config after "
                "initialization; ignoring override and returning existing "
                "singleton"
            )

    return _intrinsic_motivation_system
