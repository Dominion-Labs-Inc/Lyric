#!/usr/bin/env python3
"""What has been established about one capability, for one person.

The profile says what must hold. This says what actually does, and refuses when
it does not. It is the only thing here that answers a permission question, and it
answers it one way by default: NO.

WHY IT IS BUILT TO REFUSE. Every condition starts UNKNOWN, and unknown refuses
with the name of the authority that would answer it. There is no path through
this object that returns "may exercise" from absent evidence, no default that
passes, and no way to get a permissive answer without having taken the live
readings — ``may_exercise`` demands them as an argument rather than reading a
stored copy, because a stored risk reading is a stale reading presented as a
current one.

NOTHING RECORDS FINDINGS HERE YET. This is the shell: the authorities named in
``STANDING_CONDITIONS`` each own their answer, and none of them has been wired to
report it. Held in memory, so nothing survives a restart — which is honest for a
shell and must change before any capability is exercised for a real person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .profile import LIVE_READS, CapabilityProfile


class Standing(Enum):
    """Where one condition stands. There is no fourth value meaning "probably"."""

    ESTABLISHED = "established"
    UNKNOWN = "unknown"
    #: Was established and was taken back. Distinct from UNKNOWN on purpose: a
    #: capability that regressed is not the same as one that never ran, and the
    #: refusal should say which.
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class Finding:
    """One authority's answer about one condition, and who gave it."""

    condition: str
    standing: Standing
    #: The authority that answered. A finding with no owner is an assertion.
    owner: str
    detail: str = ""
    at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError(
                f"a finding about '{self.condition}' must name the authority "
                f"that established it; an unattributed finding is an assertion")


class CapabilityStanding:
    """One person's standing in one capability."""

    def __init__(self, profile: CapabilityProfile, actor: str) -> None:
        if not actor:
            raise ValueError("standing is always someone's; name the actor")
        self.profile = profile
        self.actor = actor
        self._findings: Dict[str, Finding] = {}

    # ── recording what an authority established ──────────────────────────────

    def record(self, finding: Finding) -> None:
        """Take one authority's answer.

        Refuses a condition this capability does not require (a finding nobody
        asked for would sit here looking like progress) and refuses anything read
        live (storing it is the stale-reading defect).
        """
        if finding.condition in LIVE_READS:
            raise ValueError(
                f"'{finding.condition}' is read at the moment of exercise and "
                f"must not be stored; pass it to may_exercise instead")
        if finding.condition not in self.profile.requires:
            raise ValueError(
                f"{self.profile.id} does not require '{finding.condition}', so "
                f"there is nothing here for that answer to mean")
        self._findings[finding.condition] = finding

    def withdraw(self, condition: str, owner: str, detail: str) -> None:
        """Take a condition back. Recorded, not deleted — a capability that
        regressed should be able to say what took it."""
        self.record(Finding(condition=condition, standing=Standing.WITHDRAWN,
                            owner=owner, detail=detail))

    def standing_of(self, condition: str) -> Standing:
        found = self._findings.get(condition)
        return found.standing if found else Standing.UNKNOWN

    # ── the one permission answer ────────────────────────────────────────────

    def may_exercise(self, live_readings: Mapping[str, Finding]
                     ) -> Tuple[bool, str]:
        """May this run for this person, unasked, right now?

        ``live_readings`` must carry one finding for every name in the profile's
        ``reads_live``, taken now by the faculty that owns it. A missing one
        refuses: the alternative is answering a question about the present from
        something recorded in the past.

        Returns (False, reason) far more often than (True, …), and the reason
        always names the condition and its owner, so "not yet" is answerable
        rather than mysterious.
        """
        for condition in self.profile.requires:
            found = self._findings.get(condition)
            if found is None:
                return False, (
                    f"{self.profile.id}: '{condition}' has not been established "
                    f"for {self.actor}; it is answered by "
                    f"{self.profile.owner_of(condition)}")
            if found.standing is Standing.WITHDRAWN:
                return False, (
                    f"{self.profile.id}: '{condition}' was withdrawn for "
                    f"{self.actor} by {found.owner}"
                    + (f" — {found.detail}" if found.detail else ""))
            if found.standing is not Standing.ESTABLISHED:
                return False, (
                    f"{self.profile.id}: '{condition}' stands as "
                    f"{found.standing.value} for {self.actor}")

        for live in self.profile.reads_live:
            reading = live_readings.get(live)
            if reading is None:
                return False, (
                    f"{self.profile.id}: '{live}' was not read; it is read at "
                    f"the moment of exercise by {self.profile.owner_of(live)}, "
                    f"and an unread reading is not a favourable one")
            if reading.standing is not Standing.ESTABLISHED:
                return False, (f"{self.profile.id}: {live} reads "
                               f"{reading.standing.value} now"
                               + (f" — {reading.detail}" if reading.detail else ""))

        missing = self.profile.requires
        return True, (f"{self.profile.id}: every condition established for "
                      f"{self.actor} ({', '.join(missing)}), live readings taken")

    # ── description for the map, which is NOT a permission ───────────────────

    def progress(self) -> Dict[str, object]:
        """How far along this person's standing is — for showing on the map.

        NOT an answer to whether it may run. ``may_exercise`` is the only thing
        that answers that, and it needs live readings this cannot have.
        """
        established = [c for c in self.profile.requires
                       if self.standing_of(c) is Standing.ESTABLISHED]
        withdrawn = [c for c in self.profile.requires
                     if self.standing_of(c) is Standing.WITHDRAWN]
        unknown = [c for c in self.profile.requires
                   if self.standing_of(c) is Standing.UNKNOWN]
        return {
            "capability": self.profile.id,
            "actor": self.actor,
            "established": established,
            "withdrawn": withdrawn,
            "unknown": unknown,
            "of": len(self.profile.requires),
        }


class CapabilityMap:
    """One person's map: their standing in each capability the platform holds.

    A registry of profiles plus that person's standing in each. It answers
    nothing itself — every question goes to the standing, which refuses.
    """

    def __init__(self, actor: str, profiles: Iterable[CapabilityProfile]) -> None:
        if not actor:
            raise ValueError("a capability map is always someone's")
        self.actor = actor
        self._profiles: Dict[str, CapabilityProfile] = {}
        self._standing: Dict[str, CapabilityStanding] = {}
        for profile in profiles:
            if profile.id in self._profiles:
                raise ValueError(
                    f"two capabilities share the id '{profile.id}'; standing is "
                    f"keyed by it, so they would share a person's progress")
            self._profiles[profile.id] = profile
            self._standing[profile.id] = CapabilityStanding(profile, actor)

    def __len__(self) -> int:
        return len(self._profiles)

    def profiles(self) -> Tuple[CapabilityProfile, ...]:
        return tuple(self._profiles.values())

    def standing(self, capability_id: str) -> CapabilityStanding:
        try:
            return self._standing[capability_id]
        except KeyError:
            raise KeyError(
                f"this map holds no capability '{capability_id}'; it holds "
                f"{sorted(self._profiles)}") from None

    def progress(self) -> Tuple[Dict[str, object], ...]:
        """The map as it would be shown. Descriptions, not permissions."""
        return tuple(s.progress() for s in self._standing.values())
