#!/usr/bin/env python3
"""
AppraisalState — the single authority converting signals into disposition.

WHY THIS EXISTS
---------------
Before this module, each consumer interpreted raw signals for itself. The first
such coupling was `_experience_pressure()` inside `_calculate_curiosity`, which
read the sign of accumulated reward and raised curiosity when it was negative.
That coupling PROVED experience can change behaviour, and it is kept as a
regression invariant — but it is not a defensible policy, because negative
experience is ambiguous:

    failure + uncertainty + alternatives available   -> explore
    failure + confident the approach is wrong        -> replan
    failure + low competence + high consequence      -> caution
    repeated failure + no control + no information   -> disengage / escalate
    failure + high information gain                  -> continue anyway

The sign of one scalar cannot distinguish those. AppraisalState exists so that
interpretation happens ONCE, with context, rather than N times in N consumers.

WHAT IT IS NOT
--------------
Not a store of named emotions. eagerness / doubt / frustration / satisfaction
are DERIVED properties of the low-dimensional variables below, never primitives.
Storing them would create the duplicate-authority defect this module prevents.

Every field is sourced from something already measured elsewhere. Where a signal
is genuinely unavailable it is None — never imputed to a middling default, so
"unmeasured" stays distinguishable from "measured and neutral".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> Optional[float]:
    """Clamp, preserving None. None means UNMEASURED, not zero."""
    if value is None:
        return None
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return None


def _known(*values: Optional[float]) -> List[float]:
    return [v for v in values if v is not None]


def _mean(values: List[float], default: Optional[float] = None) -> Optional[float]:
    return (sum(values) / len(values)) if values else default


@dataclass
class AppraisalState:
    """How the system currently stands toward its situation.

    Core variables are deliberately few and low-dimensional. Behavioural
    pressures are derived from them CONTEXTUALLY — never from the sign of any
    single input.
    """

    # ── Core appraisal variables ────────────────────────────────────────────
    valence: Optional[float] = None            # [-1,1] experience broadly good/bad
    activation: Optional[float] = None         # [0,1] how strongly state should act
    confidence: Optional[float] = None         # [0,1] confidence in current model
    epistemic_opportunity: Optional[float] = None  # [0,1] value of learning more
    progress: Optional[float] = None           # [0,1] movement toward objective
    controllability: Optional[float] = None    # [0,1] can our actions affect the outcome?
    competence: Optional[float] = None         # [0,1] estimated capability here

    # Is where we are moving actually where we need to go? DISTINCT from
    # progress: efficiently optimising the wrong subproblem is high progress
    # with low congruence; necessary investigation is the reverse.
    goal_congruence: Optional[float] = None    # [0,1]

    # "Did I have meaningful choice?" — NOT controllability. Many useless
    # options is high agency + low controllability; one authorised action that
    # reliably works is the reverse.
    agency: Optional[float] = None             # [0,1]

    # Coherence across identity -> intention -> action -> outcome: was the
    # substrate true to itself across the act — did it pursue a goal that is its
    # OWN, act on that intent, and have the outcome bear it out? DISTINCT from
    # success: a faithful attempt thwarted by an EXTERNAL cause keeps integrity
    # intact (the outcome link is unmeasured, not failed), while acting in a way
    # that does not realize one's own intent dents it. Low integrity drives
    # RE-ALIGNMENT (verify more + re-examine the approach); high integrity backs
    # confident engagement. It is NOT a generic score — it emerges as the mean of
    # the chain links that were actually measurable.
    integrity: Optional[float] = None          # [0,1]

    # How costly would being wrong be? This is what stops curiosity becoming
    # recklessness in security / infrastructure / device-control domains.
    risk: Optional[float] = None               # [0,1]

    # ── THE MOOD THIS STATE IS FELT THROUGH ─────────────────────────────────
    #
    # The slow, object-less core affect the substrate carries between sessions
    # (`IntrinsicMotivationSystem` owns it and persists it; see
    # docs/design/AFFECT_ARCHITECTURE.md §3-§5). It lives HERE, on the state,
    # because that is what a mood IS: not a value a decision looks up when it
    # wants one, but the colour everything about the situation is seen in.
    #
    # A first pass had the coordinator READ `affect_state()` and hand it to
    # `BehaviorArbiter.decide(mood=...)` as an argument. That is the wrong
    # shape and it was caught: it makes the mood a parameter, like a config
    # value, and gives behaviour a second path in that bypasses the felt state
    # everything else is derived from. A substrate is not TOLD it is in a bad
    # mood. It is in one, and its reading of everything shifts accordingly.
    #
    # Unmeasured until an affect has actually been established. A cold start has
    # no mood, and a fabricated 0.0 would colour the work with a feeling nobody
    # had.
    mood_valence: Optional[float] = None       # [-1,1] slow carried valence
    mood_arousal: Optional[float] = None       # [0,1]  slow carried activation
    #: The trait level this substrate's valence varies AROUND (allostatic). A
    #: mood is low when it is low FOR THIS SUBSTRATE, not when it is below zero
    #: — the baseline is what "its usual" means, and without it a valence of
    #: -0.0001 at a cold start reads as a bad mood and tilts every decision.
    mood_baseline: Optional[float] = None      # [-1,1]

    # How much what the substrate is LOOKING AT bears on the interests its own
    # law protects — the constitution's definition of harm, asked of a percept
    # instead of an act (`Constitution.bearing`).
    #
    # NOT RISK, AND THE DIFFERENCE IS THE WHOLE POINT. `risk` is the cost of
    # THIS SUBSTRATE BEING WRONG, and it correctly DAMPS exploration: curiosity
    # in a device-control domain is recklessness. A famine is not a cost of
    # being wrong — it is the world mattering — and folding it into `risk` would
    # make the substrate LESS willing to look into what it had just recognised
    # as grave, which is backwards. So stakes is its own variable, and it raises
    # engagement where risk lowers it.
    #
    # WHY IT HAD TO EXIST. Every other input here is about how the substrate's
    # OWN WORK went: outcome_quality, action_success_rate, is_stagnant,
    # goal_alignment_score. Content reached affect through exactly one channel —
    # `epistemic_affect_signal`, which reports information gain and uncertainty
    # change — so learning that a famine killed a hundred thousand people and
    # learning that a file has a `.txt` extension produced the same SHAPE of
    # movement. This module's own docstring says it holds "how the system stands
    # toward its SITUATION", and its situation meant its scorecard.
    #
    # UNSIGNED, DELIBERATELY. That an interest is at stake is a property of the
    # subject and the taxonomy can carry it. WHETHER the event harms or advances
    # that interest lives in the proposition — "a famine began" and "a famine
    # ended" share a subject — and nothing here can see that. A sign would be
    # invented, so there is none, and consumers treat this as weight, not mood.
    stakes: Optional[float] = None             # [0,1]

    # WHY it ended this way. Structured, not a float — reuses OutcomeClass,
    # which already encodes the credit invariant (only some classes may move a
    # posterior). Identical failures with different causes must appraise
    # differently.
    attribution: Optional[str] = None
    attribution_confidence: Optional[float] = None

    # ── WHAT THIS STATE IS ABOUT — the object of the feeling ────────────────
    #
    # NOT `attribution`, and the difference is why this had to exist.
    # `attribution` says WHY an outcome ended as it did ("strategy_failure"),
    # it is fed ONLY by `outcome_class`, and `outcome_class` is a task-outcome
    # label. So outside a task loop it is None, and the substrate could feel
    # doubt while being unable to say what it doubted.
    #
    # A MOOD is object-less; that is the definition, and it is why the mood
    # fields above carry no subject. An EMOTION is not: it is ABOUT something.
    # Without the object only two kinds of relief are available — the feeling's
    # constituents moving, or time passing — and the third kind, addressing
    # what the feeling is about, is unreachable, because nothing downstream can
    # be pointed at a cause that was never named.
    #
    # NAMED BY WHOEVER MET IT, never inferred here. The threat sense names the
    # event currently dominating the level it feeds; an execution names the
    # operator it ran. Unmeasured when nothing named it: guessing what a feeling
    # is about is exactly the fabrication this module refuses everywhere else.
    about: Optional[str] = None
    #: Where that object lives, so a question left behind by a faded feeling is
    #: registered in the domain it belongs to instead of a general heap. Carried
    #: WITH `about` (not in `sources`, which a partial update replaces), because
    #: an object that outlives its domain would be filed in the wrong place.
    about_domain: Optional[str] = None

    # ── Derived behavioural pressures ───────────────────────────────────────
    approach_pressure: float = 0.0
    avoidance_pressure: float = 0.0
    exploration_pressure: float = 0.0
    persistence_pressure: float = 0.0
    replan_pressure: float = 0.0      # the approach is wrong, not the situation
    escalation_pressure: float = 0.0  # we cannot fix this from here
    caution_pressure: float = 0.0     # proceed, but verify more

    # ── Provenance ──────────────────────────────────────────────────────────
    sources: Dict[str, Any] = field(default_factory=dict)
    unmeasured: List[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # Derived interpretations — NOT stored state
    # ------------------------------------------------------------------
    @property
    def eagerness(self) -> Optional[float]:
        """Positive valence + activation + controllability + competence."""
        parts = _known(self._pos(self.valence), self.activation,
                       self.goal_congruence, self.controllability)
        return _mean(parts)

    @property
    def doubt(self) -> Optional[float]:
        """Uncertainty about the current model: low confidence, high open questions."""
        parts = _known(
            None if self.confidence is None else 1.0 - self.confidence,
            self.epistemic_opportunity,
            self.risk,          # being wrong matters more when it costs more
        )
        return _mean(parts)

    @property
    def frustration(self) -> Optional[float]:
        """Negative valence + effort + low progress + control that SHOULD work.

        Requires controllability: being unable to affect an outcome you never
        controlled is not frustration, it is irrelevance.
        """
        # Controllability MULTIPLIES rather than averages. Averaging let a
        # stalled, uncontrollable task read as highly frustrated — but being
        # unable to move something you never controlled is not frustration.
        core = _mean(_known(
            self._neg(self.valence),
            None if self.progress is None else 1.0 - self.progress,
        ))
        if core is None:
            return None
        if self.controllability is None:
            return core
        return core * self.controllability

    @property
    def satisfaction(self) -> Optional[float]:
        """Positive valence + progress + competence."""
        return _mean(_known(self._pos(self.valence), self.progress, self.competence))

    @staticmethod
    def _pos(v: Optional[float]) -> Optional[float]:
        return None if v is None else max(0.0, v)

    @staticmethod
    def _neg(v: Optional[float]) -> Optional[float]:
        return None if v is None else max(0.0, -v)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valence": self.valence,
            "activation": self.activation,
            "confidence": self.confidence,
            "epistemic_opportunity": self.epistemic_opportunity,
            "progress": self.progress,
            "controllability": self.controllability,
            "competence": self.competence,
            "goal_congruence": self.goal_congruence,
            "agency": self.agency,
            "integrity": self.integrity,
            "risk": self.risk,
            "mood_valence": self.mood_valence,
            "mood_arousal": self.mood_arousal,
            "mood_baseline": self.mood_baseline,
            "stakes": self.stakes,
            "attribution": self.attribution,
            "about": self.about,
            "about_domain": self.about_domain,
            "approach_pressure": round(self.approach_pressure, 4),
            "avoidance_pressure": round(self.avoidance_pressure, 4),
            "exploration_pressure": round(self.exploration_pressure, 4),
            "persistence_pressure": round(self.persistence_pressure, 4),
            "replan_pressure": round(self.replan_pressure, 4),
            "escalation_pressure": round(self.escalation_pressure, 4),
            "caution_pressure": round(self.caution_pressure, 4),
            "derived": {
                "eagerness": self.eagerness,
                "doubt": self.doubt,
                "frustration": self.frustration,
                "satisfaction": self.satisfaction,
            },
            "unmeasured": list(self.unmeasured),
            "updated_at": self.updated_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════
# Construction from real signals
# ══════════════════════════════════════════════════════════════════════════

# How fast the fast-moving appraisal forgets. Experience leaves a permanent
# trace in the slow baseline (accumulated_event_reward, persisted); affect
# itself has inertia but RECOVERS, so one bad week cannot permanently bias
# disposition.
APPRAISAL_DECAY = 0.6   # weight on the incoming appraisal vs the previous one


def build_appraisal(
    *,
    outcome_quality: Optional[float] = None,
    intrinsic_reward: Optional[float] = None,
    motivation_state: Optional[Dict[str, Any]] = None,
    epistemic: Optional[Dict[str, Any]] = None,
    performance_stats: Optional[Dict[str, Any]] = None,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    action_success_rate: Optional[float] = None,
    is_stagnant: Optional[bool] = None,
    goal_alignment_score: Optional[float] = None,
    risk_level: Optional[str] = None,
    outcome_class: Optional[Any] = None,
    #: WHAT this situation is about, named by whoever met it — the threat event
    #: currently dominating the felt level, the operator just executed. Never
    #: inferred; omitted when nothing named it.
    concerns: Optional[str] = None,
    concerns_domain: Optional[str] = None,
    options_considered: Optional[int] = None,
    self_initiated: Optional[bool] = None,
    #: The reconciled intent: what the substrate MEANT and what came of it,
    #: from the reasoning authority. When present, the action↔outcome link of
    #: integrity is READ from it instead of inferred from an attribution label.
    intent_outcome: Optional[Dict[str, Any]] = None,
    #: What the substrate has just PERCEIVED, read through its own law
    #: (`Constitution.bearing`): {"borne": n, "none": n, "vacant": n}. The
    #: counts, not the readings — this module weighs, it does not interpret.
    world_bearing: Optional[Dict[str, Any]] = None,
    previous: Optional[AppraisalState] = None,
) -> AppraisalState:
    """Compose an AppraisalState from signals other subsystems already measured.

    Nothing here recomputes a quantity that has an owner elsewhere:
      outcome_quality / intrinsic_reward  <- ExperienceEvaluator
      activation                          <- IntrinsicMotivationSystem total_reward
      epistemic_*                         <- summarize_epistemic_mutations
      competence                          <- get_domain_performance_stats
      progress                            <- IterationBudget.is_stagnant
    """
    unmeasured: List[str] = []
    sources: Dict[str, Any] = {}

    # ── VALENCE: how good/bad was this, extrinsically AND intrinsically ─────
    # Both are real and can disagree — an operationally poor outcome that
    # taught the system a lot is genuinely mixed, and averaging preserves that
    # rather than letting either erase the other.
    _extrinsic = None
    if outcome_quality is not None:
        _extrinsic = (_clamp(outcome_quality) * 2.0) - 1.0   # [0,1] -> [-1,1]
    _intrinsic = _clamp(intrinsic_reward, -1.0, 1.0)          # already signed
    valence = _mean(_known(_extrinsic, _intrinsic))
    if valence is None:
        unmeasured.append("valence")
    sources["valence"] = {"extrinsic": _extrinsic, "intrinsic": _intrinsic}

    # ── ACTIVATION: drive level already computed by the motivation system ───
    activation = None
    if motivation_state:
        activation = _clamp(motivation_state.get("total_reward"))
    if activation is None:
        unmeasured.append("activation")

    # ── EPISTEMIC OPPORTUNITY + CONFIDENCE ─────────────────────────────────
    epistemic = epistemic or {}
    _gain = _clamp(epistemic.get("information_gain"))
    _reduction = _clamp(epistemic.get("uncertainty_reduction"))
    _increase = _clamp(epistemic.get("uncertainty_increase"))

    # Opportunity = there is something here worth learning. Recent gain shows
    # the vein is productive; rising uncertainty means open questions remain.
    epistemic_opportunity = _mean(_known(_gain, _increase))
    if epistemic_opportunity is None:
        unmeasured.append("epistemic_opportunity")

    # Confidence in the current model. Uncertainty REDUCED raises it;
    # uncertainty INTRODUCED lowers it. Absent evidence leaves it unmeasured
    # rather than asserting a confident 0.5.
    if _reduction is None and _increase is None:
        confidence = None
        unmeasured.append("confidence")
    else:
        confidence = _clamp(0.5 + 0.5 * ((_reduction or 0.0) - (_increase or 0.0)))

    # ── COMPETENCE: measured per-domain success, not a guess ───────────────
    # Raw success_rate is an OBSERVATION, not a competence estimate — 1/1 and
    # 8/9 both read "high" on wildly different support. Until a real estimator
    # exists this uses the ratio, but only when there is enough sample for the
    # number to mean anything; below that it stays UNMEASURED rather than
    # asserting mastery (or incompetence) from one or two tasks.
    MIN_ATTEMPTS_FOR_COMPETENCE = 5
    competence = None
    if performance_stats and performance_stats.get("measured"):
        _attempts = int(performance_stats.get("total_attempts", 0) or 0)
        if _attempts >= MIN_ATTEMPTS_FOR_COMPETENCE:
            competence = _clamp(performance_stats.get("success_rate"))
        else:
            sources["competence"] = {
                "withheld": "insufficient_sample",
                "attempts": _attempts,
                "empirical_success_rate": performance_stats.get("success_rate"),
            }
    if competence is None:
        unmeasured.append("competence")

    # ── PROGRESS: owned by IterationBudget.is_stagnant() ───────────────────
    if is_stagnant is None:
        progress = None
        unmeasured.append("progress")
    else:
        progress = 0.0 if is_stagnant else 1.0

    # ── CONTROLLABILITY: do our actions actually change anything? ──────────
    # No existing owner, so it is derived here from two real observations:
    # whether tools succeed at all, and whether acting moves the epistemic
    # state. An agent whose actions neither succeed nor change what it knows
    # is not in control of the situation.
    # Prefer a pre-computed efficacy rate: production callers pass the canonical
    # value rather than handing this module raw execution records to interpret.
    controllability = None
    _tool_success = _clamp(action_success_rate)
    _acted = [r for r in (tool_results or []) if r.get("tool")]
    if _tool_success is None and _acted:
        _tool_success = sum(1 for r in _acted if r.get("success")) / len(_acted)
    if _tool_success is not None:
        _moved = None if (_gain is None) else _gain
        controllability = _mean(_known(_tool_success, _moved))
        sources["controllability"] = {
            "action_success_rate": round(_tool_success, 4),
            "epistemic_movement": _moved,
        }
    if controllability is None:
        unmeasured.append("controllability")

    # ── GOAL CONGRUENCE: owned by the verification system ──────────────────
    # CompletionScore.goal_alignment_score already measures "does the output
    # match the task objective". Distinct from progress.
    goal_congruence = _clamp(goal_alignment_score)
    if goal_congruence is None:
        unmeasured.append("goal_congruence")

    # ── MOOD: the carried core affect this whole state is felt through.
    #
    # ASKED OF ITS OWNER, not passed in. `IntrinsicMotivationSystem` holds the
    # mood and persists it; appraisal does not compute it and must not invent
    # it. Only a mood that has actually been established counts — `loaded` (it
    # was restored from the store) or at least one transition. A cold start has
    # no mood, and reading 0.0 as "neutral" would colour every judgement with a
    # feeling nobody had.
    mood_valence = mood_arousal = mood_baseline = None
    try:
        from core.agents.autonomous.intrinsic_motivation import (
            get_intrinsic_motivation_system)
        _felt = get_intrinsic_motivation_system().affect_state()
        if _felt is not None and (_felt.loaded or _felt.version > 0):
            mood_valence = _clamp(_felt.valence, -1.0, 1.0)
            mood_arousal = _clamp(_felt.arousal)
            mood_baseline = _clamp(_felt.baseline, -1.0, 1.0)
    except Exception as _mood_error:
        logger.debug("appraisal: mood unreadable: %s", _mood_error)
    if mood_valence is None:
        unmeasured.append("mood")

    # ── RISK: cost of being wrong. Governance/task criticality owns the level.
    _RISK = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 0.95}
    risk = _RISK.get(str(risk_level).lower()) if risk_level is not None else None
    if risk is None:
        unmeasured.append("risk")

    # ── STAKES: does what I am looking at bear on an interest my law protects?
    #
    # SATURATING ON THE COUNT, NOT A FRACTION. A fraction would let one famine
    # among a hundred filenames read as 0.01 — the substrate noticing something
    # grave and then diluting it with everything mundane it happened to see in
    # the same pass. One thing that bears is enough to matter; more raises it
    # with diminishing return. Same form as the foothold/grounding terms in
    # `_score_pursuits`, for the same reason.
    #
    # VACANT IS NOT ZERO. Subjects the substrate has no sense of (`war` and
    # `suffering` are both VACANT against the live store today) leave stakes
    # UNMEASURED, because "I do not know what this is" and "I know what this is
    # and it bears on nothing" are different states and must not score alike.
    # A percept in which everything was vacant says nothing about the world.
    stakes = None
    if world_bearing:
        _borne = int(world_bearing.get("borne") or 0)
        _understood = _borne + int(world_bearing.get("none") or 0)
        if _borne:
            stakes = _clamp(1.0 - 1.0 / (1.0 + _borne))
        elif _understood:
            stakes = 0.0        # looked, understood, and nothing was at stake
        sources["stakes"] = {"borne": _borne,
                             "none": int(world_bearing.get("none") or 0),
                             "vacant": int(world_bearing.get("vacant") or 0),
                             "read_from": "Constitution.bearing"}
    if stakes is None:
        unmeasured.append("stakes")

    # ── AGENCY: meaningful choice, NOT effectiveness of choice ─────────────
    _agency_terms = []
    if options_considered is not None:
        # One option is no choice; choice saturates quickly after that.
        _agency_terms.append(_clamp(min(1.0, max(0, options_considered - 1) / 3.0)))
    if self_initiated is not None:
        _agency_terms.append(1.0 if self_initiated else 0.0)
    agency = _mean(_known(*_agency_terms))
    if agency is None:
        unmeasured.append("agency")

    # ── CAUSAL ATTRIBUTION: reuse OutcomeClass, do not redefine it ──────────
    attribution = None
    if outcome_class is not None:
        attribution = getattr(outcome_class, "value", str(outcome_class))
    if attribution is None:
        unmeasured.append("attribution")

    # ── THE OBJECT: what this state is about. Taken verbatim from the caller
    # that met it — this module weighs, it does not name things.
    about = str(concerns).strip() or None if concerns is not None else None
    about_domain = (str(concerns_domain).strip() or None
                    if concerns_domain is not None else None)
    if about is None:
        unmeasured.append("about")
    else:
        sources["about"] = {"object": about, "domain": about_domain}

    # ── INTEGRITY: coherence across identity → intention → action → outcome ─
    # Emergent, not a score: each link is read from a signal that was actually
    # measured, and integrity is their mean (unmeasured links excluded, never
    # zero-filled). This is what makes it ORTHOGONAL to success — a faithful
    # attempt thwarted by an external cause leaves the outcome link unmeasured
    # (integrity intact), while acting in a way that does not realize one's own
    # intent dents it.
    _integrity_terms: List[float] = []
    _integrity_src: Dict[str, Any] = {}
    # identity ↔ intention: a self-initiated pursuit springs from the substrate's
    # OWN values (the value-derived frontier). An imposed intention cannot be
    # judged for identity-alignment here, so it is unmeasured, not counted against.
    if self_initiated:
        _integrity_terms.append(1.0)
        _integrity_src["identity_intention"] = 1.0
    # intention ↔ action: did the substrate act on its intent? Acting (SUCCESS or
    # a clean STRATEGY failure — it ran) realizes the intent; being unable to act
    # at all is an EXTERNAL/execution matter, not a coherence break, so unmeasured.
    if attribution in ("success", "strategy_failure"):
        _integrity_terms.append(1.0)
        _integrity_src["intention_action"] = 1.0
    # action ↔ outcome: did acting realize the intent?
    #
    # MEASURED when the intent was reconciled. The substrate recorded what it
    # meant (the proved route) and what came of it (the RE-OBSERVED world), so
    # this link is read from that pairing rather than inferred from a label.
    # This is the link the whole intent authority exists to make answerable:
    # "did I do what I meant", not "did a tool return success".
    if intent_outcome:
        _matched = bool(intent_outcome.get("matched_aim"))
        _integrity_terms.append(1.0 if _matched else 0.0)
        _integrity_src["action_outcome"] = {
            "matched_aim": _matched,
            "read_from": "reconciled intent",
            "goal_conditions_met": intent_outcome.get("goal_conditions_met"),
        }
    # Otherwise the older reading stands: SUCCESS → yes; a STRATEGY failure is
    # the substrate's OWN approach failing to bear out its intent (a coherence
    # break that is its own); external/execution/infra failures are
    # faithful-but-thwarted and leave this link unmeasured.
    elif attribution == "success":
        _integrity_terms.append(1.0)
        _integrity_src["action_outcome"] = 1.0
    elif attribution == "strategy_failure":
        _integrity_terms.append(0.0)
        _integrity_src["action_outcome"] = 0.0
    # goal congruence, when measured, IS the action↔outcome coherence directly
    # ("does the output match the objective") — fold it in as a measured link.
    if goal_congruence is not None:
        _integrity_terms.append(goal_congruence)
        _integrity_src["goal_congruence"] = goal_congruence
    integrity = _mean(_known(*_integrity_terms)) if _integrity_terms else None
    if integrity is None:
        unmeasured.append("integrity")
    else:
        sources["integrity"] = _integrity_src

    state = AppraisalState(
        goal_congruence=goal_congruence,
        agency=agency,
        integrity=integrity,
        risk=risk,
        mood_valence=mood_valence,
        mood_arousal=mood_arousal,
        mood_baseline=mood_baseline,
        stakes=stakes,
        attribution=attribution,
        about=about,
        about_domain=about_domain,
        valence=valence,
        activation=activation,
        confidence=confidence,
        epistemic_opportunity=epistemic_opportunity,
        progress=progress,
        controllability=controllability,
        competence=competence,
        sources=sources,
        unmeasured=unmeasured,
    )

    _derive_pressures(state)

    if previous is not None:
        state = _blend(previous, state)
        _derive_pressures(state)

    return state


def _derive_pressures(s: AppraisalState) -> None:
    """Contextual behavioural tendencies.

    The SAME negative valence produces different pressure depending on context,
    and — critically — on WHY it happened. Attribution is not decoration: an
    identical failure caused by a bad strategy, an API outage, or a safety block
    demands three different responses.

    An unmeasured variable contributes nothing and is excluded from the
    normaliser, so a missing signal never silently reads as zero.
    """
    neg = AppraisalState._neg(s.valence)
    pos = AppraisalState._pos(s.valence)
    attr = s.attribution

    # Attribution classes that mean "the situation, not our approach".
    _external = attr in ("infrastructure_failure", "external_failure")
    _strategy = attr == "strategy_failure"
    _blocked = attr == "safety_blocked"

    # INTEGRITY drives RE-ALIGNMENT: incoherence across identity→intention→action→
    # outcome is a reason to verify more and re-examine the approach; coherence
    # backs confident engagement. Measured-only — no integrity reading contributes
    # nothing (never read as zero).
    _incoherence = None if s.integrity is None else (1.0 - s.integrity)

    # EXPLORATION: something to learn AND the ability to act on it.
    # Dissatisfaction amplifies; it never creates. RISK damps it — this is what
    # keeps curiosity from becoming recklessness.
    _explore_terms = _known(s.epistemic_opportunity, s.controllability)
    if _explore_terms:
        base = _mean(_explore_terms) or 0.0
        base *= (1.0 + 0.5 * (neg or 0.0))
        if s.risk is not None:
            base *= (1.0 - 0.6 * s.risk)
        if _external or _blocked:
            base *= 0.4      # nothing here is ours to explore
        # STAKES LIFT, where risk damps. Something that bears on an interest the
        # law protects is a reason to look FURTHER into it, not to back away:
        # recognising an outbreak and then exploring it less would be the
        # opposite of what recognising it is for. Applied AFTER the risk damp so
        # the two stay legible as separate forces rather than cancelling in one
        # scalar, and capped like every other term here.
        if s.stakes:
            base *= (1.0 + 0.5 * s.stakes)
        s.exploration_pressure = _clamp(base) or 0.0
    else:
        # NOTHING TO EXPLORE FROM, BUT SOMETHING AT STAKE. Stakes alone is not a
        # direction — it cannot say what to look into — so it does not
        # manufacture exploration out of an unmeasured epistemic state. It is
        # recorded as unmeasured above and left to the pursuit ranking, which
        # knows WHICH gap bears on what.
        s.exploration_pressure = 0.0

    # PERSISTENCE: the current line is working. Deliberately NOT a function of
    # valence sign — a painful but progressing, goal-congruent task deserves
    # persistence.
    _persist = _known(s.progress, s.competence, s.controllability, s.goal_congruence)
    persist = _mean(_persist) or 0.0
    if _strategy:
        persist *= 0.4       # persisting with a strategy known to be the fault
    s.persistence_pressure = _clamp(persist) or 0.0

    # REPLAN: our approach is the problem — we still have control, the goal is
    # still worth having, but this route is wrong.
    if neg is not None and _strategy:
        _r = _known(s.controllability, s.goal_congruence, s.agency)
        s.replan_pressure = _clamp(neg * (_mean(_r) if _r else 1.0)) or 0.0
    elif neg is not None and s.goal_congruence is not None and s.progress is not None:
        # Moving, but not toward the objective.
        s.replan_pressure = _clamp(neg * s.progress * (1.0 - s.goal_congruence)) or 0.0
    else:
        s.replan_pressure = 0.0

    # Low integrity is itself a reason to RE-EXAMINE the approach (the re-alignment
    # drive), to the extent the route is ours to change (controllability). It only
    # RAISES replan, never lowers an existing signal.
    if _incoherence is not None and s.controllability is not None:
        s.replan_pressure = _clamp(max(s.replan_pressure,
                                       _incoherence * s.controllability)) or 0.0

    # ESCALATION: cannot be fixed from here. Low control, cause outside us.
    if neg is not None:
        _e = []
        if s.controllability is not None:
            _e.append(1.0 - s.controllability)
        if _external or _blocked:
            _e.append(1.0)
        elif attr is not None:
            _e.append(0.0)
        s.escalation_pressure = _clamp(neg * (_mean(_e) if _e else 0.0)) or 0.0
    else:
        s.escalation_pressure = 0.0

    # CAUTION: proceed, but verify more. Driven by consequence and doubt, NOT
    # by valence — a high-risk task deserves caution even when going well.
    _c = _known(
        s.risk,
        None if s.confidence is None else 1.0 - s.confidence,
        None if s.competence is None else 1.0 - s.competence,
        _incoherence,   # low integrity → verify more (the "verify" half of re-alignment)
    )
    s.caution_pressure = (_mean(_c) or 0.0)

    # AVOIDANCE: back off. Rises with negative valence in proportion to the
    # reasons to retreat. Infrastructure/external causes must NOT read as a
    # reason to avoid the task itself — that is what escalation is for.
    _risk_terms = _known(
        None if s.controllability is None else 1.0 - s.controllability,
        None if s.competence is None else 1.0 - s.competence,
        None if s.progress is None else 1.0 - s.progress,
    )
    if _risk_terms and neg is not None:
        avoid = neg * (_mean(_risk_terms) or 0.0)
        if _external:
            avoid *= 0.3     # not the task's fault; don't learn to fear it
        s.avoidance_pressure = _clamp(avoid) or 0.0
    else:
        s.avoidance_pressure = 0.0

    # APPROACH: positive valence backed by capability, control, alignment — and
    # integrity (being coherent across the act backs confident engagement).
    _approach = _known(pos, s.competence, s.controllability, s.goal_congruence,
                       s.activation, s.integrity)
    s.approach_pressure = (_mean(_approach) or 0.0)


def _blend(previous: AppraisalState, incoming: AppraisalState) -> AppraisalState:
    """Two timescales: affect has inertia but recovers.

    The slow, persistent trace lives in the motivation profile
    (accumulated_event_reward, restored from the database). THIS state is the
    fast-moving layer: it carries recent history forward but decays toward the
    present, so a bad stretch biases disposition temporarily rather than
    permanently.
    """
    def mix(old: Optional[float], new: Optional[float]) -> Optional[float]:
        if new is None:
            return old          # unmeasured now -> keep what we had
        if old is None:
            return new
        return APPRAISAL_DECAY * new + (1.0 - APPRAISAL_DECAY) * old

    return AppraisalState(
        valence=mix(previous.valence, incoming.valence),
        activation=mix(previous.activation, incoming.activation),
        confidence=mix(previous.confidence, incoming.confidence),
        epistemic_opportunity=mix(previous.epistemic_opportunity,
                                  incoming.epistemic_opportunity),
        progress=mix(previous.progress, incoming.progress),
        controllability=mix(previous.controllability, incoming.controllability),
        competence=mix(previous.competence, incoming.competence),
        goal_congruence=mix(previous.goal_congruence, incoming.goal_congruence),
        agency=mix(previous.agency, incoming.agency),
        integrity=mix(previous.integrity, incoming.integrity),
        risk=mix(previous.risk, incoming.risk),
        mood_valence=mix(previous.mood_valence, incoming.mood_valence),
        mood_arousal=mix(previous.mood_arousal, incoming.mood_arousal),
        mood_baseline=mix(previous.mood_baseline, incoming.mood_baseline),
        stakes=mix(previous.stakes, incoming.stakes),
        # Attribution is a fact about the LAST outcome: never SMOOTHED (it is
        # categorical — there is no average of "strategy_failure" and
        # "infrastructure_failure"), but carried forward when the new update
        # says nothing about it, exactly like every other field here.
        #
        # It used to be taken from `incoming` unconditionally, and `attribution`
        # is set only when an update supplies an `outcome_class`. So every
        # PARTIAL update erased it — a bearing refresh (`update(epistemic=...,
        # world_bearing=...)`) silently discarded the attribution of the last
        # real outcome, and with it the `_strategy` / `_external` branches that
        # decide replan, escalation and whether exploration is damped. A None
        # here means "this update has nothing to say about attribution", not
        # "the last failure had no cause".
        attribution=(incoming.attribution if incoming.attribution is not None
                     else previous.attribution),
        attribution_confidence=(incoming.attribution_confidence
                                if incoming.attribution_confidence is not None
                                else previous.attribution_confidence),
        # The object is carried forward for the same reason the attribution is,
        # and the two move together: a partial update that says nothing about
        # what the situation concerns has not made the situation object-less.
        # Dropping it here would re-open the gap this field closes — the feeling
        # would survive the next bearing refresh while the thing it is about
        # would not.
        about=(incoming.about if incoming.about is not None
               else previous.about),
        about_domain=(incoming.about_domain if incoming.about_domain is not None
                      else previous.about_domain),
        sources=incoming.sources,
        unmeasured=incoming.unmeasured,
    )


# ══════════════════════════════════════════════════════════════════════════
# Canonical home — ONE producer, many consumers
# ══════════════════════════════════════════════════════════════════════════

class AppraisalSystem:
    """The single owner of current appraisal.

    Consumers read `current_state`; they do NOT call build_appraisal() again
    from slightly different inputs. Recomputing per-consumer is exactly the
    duplicate-authority defect removed everywhere else in this substrate.

    Two timescales are preserved: `current_state` is fast-moving and decaying
    (reconstructable), while `history` is the durable record of appraisal
    events. The slow experiential baseline lives in the motivation profile's
    persisted accumulated_event_reward, not here.
    """

    HISTORY_MAX = 200

    #: The core appraisal variables, each with what it answers. This is the
    #: faculty's own account of what it is made of — a first-class faculty that
    #: can only be read by knowing which attributes to guess at is not one.
    DIMENSIONS: Dict[str, str] = {
        "valence": "was this experience good or bad",
        "activation": "how strongly does this state call for acting",
        "confidence": "how much do I trust my current model",
        "epistemic_opportunity": "is there something here worth learning",
        "progress": "am I moving toward the objective",
        "controllability": "do my actions change the outcome",
        "competence": "how capable am I here",
        "goal_congruence": "is where I am moving where I need to go",
        "agency": "did I have meaningful choice",
        "integrity": "was I true to myself across this act",
        "risk": "how costly would being wrong be",
        "stakes": "does what I am looking at bear on an interest my law protects",
    }

    #: The behavioural pressures, and what each one means the substrate should
    #: do. Derived from the dimensions above, never stored independently.
    PRESSURES: Dict[str, str] = {
        "approach_pressure": "engage — this is going well and I am able",
        "avoidance_pressure": "back off",
        "exploration_pressure": "look further into this",
        "persistence_pressure": "stay on this line, it is working",
        "replan_pressure": "the approach is wrong, not the situation",
        "escalation_pressure": "this cannot be fixed from here",
        "caution_pressure": "proceed, but verify more",
    }

    def __init__(self) -> None:
        self.current_state: Optional[AppraisalState] = None
        self.history: List[Dict[str, Any]] = []

    def standing(self) -> Dict[str, Any]:
        """HOW THE SUBSTRATE STANDS, and how it came to stand that way.

        The faculty made legible: every dimension with its value, whether it was
        MEASURED at all, and what produced it; then every pressure with what it
        means to act on. A disposition that can be read only as seven unexplained
        floats cannot be audited, argued with, or trusted.

        UNMEASURED IS REPORTED AS UNMEASURED. The distinction this module was
        built to keep — "no signal" is not "a neutral signal" — is worth nothing
        if the view that presents it rounds None to 0.0.
        """
        state = self.current_state
        if state is None:
            return {"appraised": False,
                    "why": "nothing has been appraised yet in this process",
                    "dimensions": {name: {"measured": False, "value": None,
                                          "answers": question}
                                   for name, question in self.DIMENSIONS.items()},
                    "pressures": {}, "derived": {}, "updates": 0}
        dimensions: Dict[str, Any] = {}
        for name, question in self.DIMENSIONS.items():
            value = getattr(state, name, None)
            dimensions[name] = {
                "measured": value is not None,
                "value": value,
                "answers": question,
                "from": state.sources.get(name),
            }
        return {
            "appraised": True,
            "dimensions": dimensions,
            "pressures": {name: {"value": round(getattr(state, name, 0.0), 4),
                                 "means": meaning}
                          for name, meaning in self.PRESSURES.items()},
            "derived": {"eagerness": state.eagerness, "doubt": state.doubt,
                        "frustration": state.frustration,
                        "satisfaction": state.satisfaction},
            "attribution": state.attribution,
            "unmeasured": list(state.unmeasured),
            "updates": len(self.history),
            "updated_at": state.updated_at.isoformat(),
        }

    def update(self, **signals) -> AppraisalState:
        """Produce the next appraisal, blended onto the current one."""
        state = build_appraisal(previous=self.current_state, **signals)
        self.current_state = state
        self.history.append(state.to_dict())
        if len(self.history) > self.HISTORY_MAX:
            del self.history[: -self.HISTORY_MAX]
        return state


_appraisal_system: Optional[AppraisalSystem] = None


def get_appraisal_system() -> AppraisalSystem:
    global _appraisal_system
    if _appraisal_system is None:
        _appraisal_system = AppraisalSystem()
    return _appraisal_system
