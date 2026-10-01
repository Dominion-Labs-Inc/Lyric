#!/usr/bin/env python3
"""
BehaviorArbiter — turns disposition into a decision for THIS situation.

    AppraisalState        "how I stand toward things"      (recommends)
          ↓
    BehaviorArbiter       "what that means right now"      (decides)
          ↓
    BehavioralDirective   consumed by existing control points

The arbiter consumes appraisal PRESSURES. It never re-reads the underlying
evidence — that interpretation already happened once, in AppraisalState.

The Constitution and safety sit ABOVE this. Caution is not permission: the arbiter
only decides how conservatively to operate inside space already permitted, and
never widens what is allowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# A pressure must clear this to change behaviour, so noise near zero does not
# produce twitchy mode-switching.
ACT_THRESHOLD = 0.35


@dataclass
class BehavioralDirective:
    """What to do next, and why."""

    mode: str = "proceed"

    exploration: float = 0.0
    persistence: float = 0.0
    replan: float = 0.0
    escalation: float = 0.0
    caution: float = 0.0
    avoidance: float = 0.0
    approach: float = 0.0

    should_explore: bool = False
    should_replan: bool = False
    should_escalate: bool = False
    should_avoid: bool = False
    should_approach: bool = False
    #: Stay with the current approach. The counterweight to `should_replan`:
    #: replan says the approach is wrong, persistence says it is right and not
    #: finished. `persistence_pressure` was derived on every appraisal, carried
    #: here as a float, and had no boolean and no consumer at all — so "keep
    #: going" was the one disposition the substrate could feel and never act on.
    should_persist: bool = False

    max_goals: int = 1
    #: THE MOOD THE SUBSTRATE CARRIED INTO THIS DECISION (§9.2 of
    #: docs/design/AFFECT_ARCHITECTURE.md). None until affect has been
    #: established — a cold start has no mood, and 0.0 would be a fabricated
    #: neutral one.
    mood_valence: Optional[float] = None
    mood_arousal: Optional[float] = None
    #: "repair" | "explore" | None — which way the mood tilted the work. NOT a
    #: separate decision: it reports how `max_goals` and the reason codes were
    #: shaped, so the tilt is inspectable rather than implied.
    mood_tilt: Optional[str] = None
    verification_intensity: float = 0.5

    reason_codes: List[str] = field(default_factory=list)
    appraisal: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "should_explore": self.should_explore,
            "should_replan": self.should_replan,
            "should_escalate": self.should_escalate,
            "should_avoid": self.should_avoid,
            "should_approach": self.should_approach,
            "should_persist": self.should_persist,
            "max_goals": self.max_goals,
            "mood_valence": self.mood_valence,
            "mood_arousal": self.mood_arousal,
            "mood_tilt": self.mood_tilt,
            "verification_intensity": round(self.verification_intensity, 4),
            "reason_codes": list(self.reason_codes),
        }


class BehaviorArbiter:
    #: How far from its own baseline a mood must sit to colour the work. Below
    #: this it is the substrate's usual state, not a mood.
    MOOD_DEADBAND: float = 0.05

    """Decides how disposition applies to the current situation."""

    def decide(
        self,
        appraisal: Optional[Any],
        *,
        slots_available: Optional[int] = None,
        queue_pressure: Optional[str] = None,
    ) -> BehavioralDirective:
        """Decide from appraisal's pressures and the REAL capacity to act.

        `slots_available` and `queue_pressure` are the acting capacity, owned by
        the task queue. They used to default to `1` and `"nominal"` — an
        always-room-for-one-more-and-the-backlog-is-fine reading that the queue
        never stated and that was wrong exactly when it mattered, because a
        loaded queue is when exploration should stop. Seven of the nine callers
        passed neither, so the exploration gate was decided against fabricated
        numbers in almost every case.

        They are now OPTIONAL-AS-IN-UNKNOWN, not optional-as-in-assume-fine. A
        caller that cannot state the capacity gets a directive that refuses
        self-initiated exploration and says `capacity_unknown`. Not knowing
        whether there is room is not permission to take room.
        """
        d = BehavioralDirective()
        # WHAT IS ACTUALLY KNOWN ABOUT ROOM TO ACT.
        capacity_known = slots_available is not None and queue_pressure is not None
        slots = int(slots_available) if slots_available is not None else 0

        if appraisal is None:
            # No appraisal yet is NOT a reason to act boldly or to freeze.
            # Proceed with the system's neutral default and say so.
            d.reason_codes.append("no_appraisal")
            if not capacity_known:
                d.reason_codes.append("capacity_unknown")
            d.max_goals = max(1, min(slots, 1)) if capacity_known else 1
            return d

        d.exploration = appraisal.exploration_pressure
        d.persistence = appraisal.persistence_pressure
        d.replan = appraisal.replan_pressure
        d.escalation = appraisal.escalation_pressure
        d.caution = appraisal.caution_pressure
        d.avoidance = appraisal.avoidance_pressure
        d.approach = appraisal.approach_pressure
        d.appraisal = {
            "valence": appraisal.valence,
            "attribution": appraisal.attribution,
            "risk": appraisal.risk,
        }

        # ── mode: the single dominant response ──────────────────────────────
        ranked = sorted(
            (
                ("escalate", d.escalation),
                ("replan", d.replan),
                ("avoid", d.avoidance),
                ("approach", d.approach),
                ("explore", d.exploration),
                ("persist", d.persistence),
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )
        top_name, top_value = ranked[0]
        d.mode = top_name if top_value >= ACT_THRESHOLD else "proceed"
        d.reason_codes.append(f"dominant:{top_name}:{top_value:.2f}")

        d.should_escalate = d.escalation >= ACT_THRESHOLD
        d.should_replan = d.replan >= ACT_THRESHOLD
        d.should_persist = d.persistence >= ACT_THRESHOLD
        # AVOIDANCE: back off from self-initiated engagement. APPROACH: lean in.
        # A genuine avoid state suppresses approach (you don't commit while retreating).
        d.should_avoid = d.avoidance >= ACT_THRESHOLD
        d.should_approach = d.approach >= ACT_THRESHOLD and not d.should_avoid

        # ── exploration admission ───────────────────────────────────────────
        # Escalation means the blocker is outside us; avoidance means back off —
        # both make thrashing through more self-directed exploration the wrong
        # response, so neither admits new self-initiated work.
        d.should_explore = (
            d.exploration >= ACT_THRESHOLD
            and not d.should_escalate
            and not d.should_avoid
            and capacity_known
            and slots > 0
            and queue_pressure == "nominal"
        )
        if not capacity_known:
            d.reason_codes.append("capacity_unknown")
        if d.should_escalate and d.exploration >= ACT_THRESHOLD:
            d.reason_codes.append("exploration_suppressed_by_escalation")
        if d.should_avoid and d.exploration >= ACT_THRESHOLD:
            d.reason_codes.append("exploration_suppressed_by_avoidance")
        if capacity_known and queue_pressure != "nominal":
            d.reason_codes.append(f"queue_pressure:{queue_pressure}")

        # Breadth scales with self-initiated engagement pressure, capped by real
        # slots. A confident approach state leans in — it can widen breadth beyond
        # bare epistemic pull; avoidance already closed should_explore above.
        _breadth = max(d.exploration, d.approach) if d.should_approach else d.exploration
        d.max_goals = max(1, min(slots, int(round(_breadth * 3)))) \
            if d.should_explore else 0

        # ── MOOD COLOURS THE WORK (§9.2 / §9.3) ─────────────────────────────
        #
        # The mood the substrate carried in — slow, object-less, and earned over
        # sessions — biases WHICH work wins and HOW MUCH, and it was reaching
        # nothing: affect's only consumer was `render()`, the substrate putting
        # its feelings into words. Appraisal did not read it and neither did
        # this. A feeling that changes nothing is a readout, not a state.
        #
        #   valence < 0  -> REPAIR. Something is declining; focus, do not scatter.
        #   valence >= 0 -> EXPLORE. Steady or improving; widen.
        #   arousal      -> intensity, how much to take on this cycle.
        #
        # §9.3 THE DEATH-SPIRAL INVARIANT, and it is the point of the design:
        # a negative mood REDIRECTS effort, it never suppresses it. "Bad mood ->
        # explore less" would have a struggling substrate learn less and stay
        # struggling. So a tilt toward repair narrows breadth to focus it and
        # CANNOT take goal generation below one while there is anything to act
        # on. A struggling substrate does FOCUSED work, not less work.
        # THE MOOD IS PART OF THE STATE IT IS ALREADY READING, not an argument
        # handed to it. See the note on `mood_valence` below.
        mood_valence = getattr(appraisal, "mood_valence", None)
        mood_arousal = getattr(appraisal, "mood_arousal", None)
        mood_baseline = getattr(appraisal, "mood_baseline", None) or 0.0
        if mood_valence is not None:
            d.mood_valence = float(mood_valence)
            d.mood_arousal = None if mood_arousal is None else float(mood_arousal)
            # LOW FOR THIS SUBSTRATE, not merely below zero, and outside a
            # deadband. Measured at a cold start: a carried valence of -0.0001
            # — float noise around an unestablished mood — read as a bad mood
            # and tilted every decision into repair. A mood varies around its
            # own baseline (that is what allostatic means), and a departure
            # smaller than MOOD_DEADBAND is not a departure.
            if d.mood_valence < mood_baseline - self.MOOD_DEADBAND:
                d.mood_tilt = "repair"
                if d.max_goals > 0:
                    # Narrow toward the deficit; never to nothing.
                    d.max_goals = max(1, min(d.max_goals, 1 + int(slots > 3)))
                d.reason_codes.append(f"mood_repair:{d.mood_valence:+.2f}")
            else:
                d.mood_tilt = "explore"
                if d.max_goals > 0 and d.mood_arousal is not None:
                    # Arousal sets intensity, bounded by real slots.
                    lifted = int(round(d.max_goals * (1.0 + d.mood_arousal)))
                    d.max_goals = max(1, min(slots, lifted))
                d.reason_codes.append(f"mood_explore:{d.mood_valence:+.2f}")
        if d.should_approach:
            d.reason_codes.append(f"approach:{d.approach:.2f}")
        if d.should_avoid:
            d.reason_codes.append(f"avoid:{d.avoidance:.2f}")

        # ── verification intensity ──────────────────────────────────────────
        # Caution buys evidence, not permission.
        d.verification_intensity = min(1.0, 0.5 + 0.5 * d.caution)
        if d.caution >= ACT_THRESHOLD:
            d.reason_codes.append(f"elevated_verification:{d.verification_intensity:.2f}")

        return d


_arbiter: Optional[BehaviorArbiter] = None


def get_behavior_arbiter() -> BehaviorArbiter:
    global _arbiter
    if _arbiter is None:
        _arbiter = BehaviorArbiter()
    return _arbiter
