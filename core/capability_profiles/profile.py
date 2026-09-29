#!/usr/bin/env python3
"""What the substrate may carry out for a person, unasked.

A CAPABILITY PROFILE is one standing authority: a kind of work the substrate may
take all the way to an outcome for a particular person, without being asked each
time. "Schedule the appointments people request" is one. It is NOT a set of
tools, and it does not restrict which tools the work may use — the substrate
picks whatever the outcome takes, including making something that does not exist
yet.

NAMING, BECAUSE THE WORD IS ALREADY TAKEN FOUR TIMES in this tree and conflating
them would be the duplicate-authority defect in the one place it is least
recoverable:

  * ``core.capability``            — whether a piece of CODE is really there.
  * ``core.tools.capabilities``    — what a TOOL can do, for tool discovery
                                     (``ToolCapabilityProfile`` lives there).
  * ``Constitution.act_capabilities`` — what an ACT would do (egress, capture,
                                     credentials), read to judge it.
  * ``CONNECTOR_CAPABILITIES_V2.md`` — a connector bundle with ``enabled`` and
                                     ``mode: read|auto``, toggled by the user.
                                     Never implemented, and superseded by this:
                                     a capability here is EARNED, not toggled.

This module is the fifth and the only one about EARNED OPERATIONAL AUTHORITY.

THREE KINDS OF PRECONDITION, AND THE DIFFERENCE IS THE WHOLE DESIGN
-------------------------------------------------------------------
1. STANDING conditions (``STANDING_CONDITIONS``) are established over time and
   held: the person's granted authority, proven competence, a known environment,
   their established preferences, how it went last time. These are what
   "progression" is made of.

2. LIVE reads (``LIVE_READS``) are read at the moment of exercise and never
   stored. Risk is one. A stored "risk: LOW" is a stale reading presented as a
   current one, which is the shape of every false-success defect in this
   codebase.

3. THE CONSTITUTION IS NOT A PRECONDITION AT ALL. It judges each act, with that
   act's arguments, inside the same cycle that performs it. Asking it in advance
   "would you allow this capability" would be a second judge answering a
   question already owned — the defect ``TASK-GATE-01`` checks E and F exist to
   catch. So a profile may not name it, and ``NOT_A_CONDITION`` enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

#: Conditions that can be established in advance, each with the authority that
#: owns the answer. A profile names the ones its work genuinely needs; nothing
#: here answers them, because none of these authorities belongs to this module.
STANDING_CONDITIONS: Dict[str, str] = {
    "authority_granted":
        "the person's own grant, as the substrate perceives it from its "
        "environment (Law 1 reads it when it judges an act on a person)",
    "competence_proven":
        "the rule store — validated executable operators in the domains this "
        "work acts in",
    "environment_known":
        "the substrate's situation facet — the environment domain it is in, and "
        "whether that environment is novel",
    "preferences_established":
        "per-actor scoped context — what this person has been observed to "
        "prefer, and what they have said they want",
    "outcomes_borne_out":
        "the evidence record — what actually happened the last times this "
        "capability was exercised for this person",
}

#: Read when the capability is about to be exercised, never stored. Each names
#: the faculty that is asked at that moment.
LIVE_READS: Dict[str, str] = {
    "risk": "the substrate's felt threat-sense, as the `risk` pressure",
    "internal_state": "self-state — interoception and affect",
    "not_halted": "the constitution's halt state (`may_start`)",
}

#: Naming any of these as a condition would make this module a second judge of a
#: question another authority already owns.
NOT_A_CONDITION: Dict[str, str] = {
    "constitution":
        "the constitution judges each ACT as it happens, with that act's "
        "arguments; a capability-level verdict would be a second answer",
    "safety": "same — safety is judged of the act, not of the kind of work",
    "permission": "too vague to name an owner; say which condition is meant",
}


@dataclass(frozen=True)
class CapabilityProfile:
    """One kind of work the substrate may carry out for a person, unasked.

    The profile is a DECLARATION. It says what outcome the capability owns, what
    work that outcome takes, which acts the work needs to be able to perform,
    what must be established before it may run unasked, what is read live, and
    what takes it back. It holds no state about any person and decides nothing —
    ``CapabilityStanding`` holds what has been established, and refuses when it
    has not.
    """

    #: Stable identifier, used as the key for a person's standing in it.
    id: str
    #: What a person would call it.
    name: str
    #: The outcome it owns, in one sentence. The test of a good one: reaching it
    #: is checkable in the world, not in the plan's account of itself.
    outcome: str
    #: The work the outcome takes, in order. This is what a planner has to be
    #: able to NAME; work it cannot name collapses into one opaque step.
    work: Tuple[str, ...]
    #: The acts the work must be able to perform, by the name the substrate
    #: knows them by. An act with no surface is an honest gap, not a detail.
    acts: Tuple[str, ...]
    #: Standing conditions that must ALL be established before it runs unasked.
    requires: Tuple[str, ...]
    #: What is read at the moment of exercise. Never stored.
    reads_live: Tuple[str, ...] = tuple(LIVE_READS)
    #: What takes the capability back, in the words of the thing that does it.
    withdrawn_by: Tuple[str, ...] = ()
    #: Free notes — what is known to be missing, decisions taken, open questions.
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id or not self.name or not self.outcome:
            raise ValueError("a capability profile needs an id, a name and the "
                             "outcome it owns")
        if not self.work:
            raise ValueError(
                f"{self.id}: names no work. A capability whose work is unstated "
                f"cannot be planned and cannot be checked afterwards")
        if not self.acts:
            raise ValueError(
                f"{self.id}: names no acts. Then nothing it does touches the "
                f"world, and 'carrying it out' could never be verified")
        if not self.requires:
            # A capability requiring nothing would be exercisable for every
            # person the moment it exists. That is the whole failure this design
            # is against, so it is refused at construction rather than caught
            # later by whoever reads a permissive answer.
            raise ValueError(
                f"{self.id}: requires nothing, so it would be permitted for "
                f"everyone. Name at least one condition from "
                f"{sorted(STANDING_CONDITIONS)}")
        for condition in self.requires:
            if condition in NOT_A_CONDITION:
                raise ValueError(
                    f"{self.id}: '{condition}' is not a precondition — "
                    f"{NOT_A_CONDITION[condition]}")
            if condition in LIVE_READS:
                raise ValueError(
                    f"{self.id}: '{condition}' is read live and never stored; "
                    f"put it in reads_live, not requires")
            if condition not in STANDING_CONDITIONS:
                raise ValueError(
                    f"{self.id}: '{condition}' names no condition anyone owns. "
                    f"Known: {sorted(STANDING_CONDITIONS)}")
        for live in self.reads_live:
            if live not in LIVE_READS:
                raise ValueError(
                    f"{self.id}: '{live}' is not something read live. Known: "
                    f"{sorted(LIVE_READS)}")

    def owner_of(self, condition: str) -> str:
        """The authority that answers this condition — never this module."""
        if condition in STANDING_CONDITIONS:
            return STANDING_CONDITIONS[condition]
        if condition in LIVE_READS:
            return LIVE_READS[condition]
        raise KeyError(f"{self.id}: nothing owns '{condition}'")

    def acts_without_a_surface(self, known_acts) -> Tuple[str, ...]:
        """The acts this capability needs that the substrate cannot perform.

        ``known_acts`` is what the tool registry says exists. Asked of the
        registry rather than derived here: one owner for what the substrate can
        do. A non-empty answer means this capability cannot reach its outcome
        no matter what any person has granted — which is worth knowing before
        anything is wired, not after.
        """
        known = {str(a) for a in known_acts}
        return tuple(a for a in self.acts if a not in known)

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id, "name": self.name, "outcome": self.outcome,
            "work": list(self.work), "acts": list(self.acts),
            "requires": list(self.requires), "reads_live": list(self.reads_live),
            "withdrawn_by": list(self.withdrawn_by), "notes": list(self.notes),
        }
