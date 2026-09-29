"""Governance block META memory schema and validation.

This module defines the canonical structure for governance_block
META memories written by the autonomous coordinator and queried by
intrinsic motivation / reasoning components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class GovernanceBlock:
    """Structured representation of a governance block META memory."""

    task_id: str
    task_type: str
    task_description: str
    block_type: str
    block_reason: str
    task_source: str
    domain: str
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceBlock":
        """Validate and construct from a raw dict.

        Raises ValueError if required fields are missing or malformed.
        """

        required_fields = [
            "task_id",
            "task_type",
            "task_description",
            "block_type",
            "block_reason",
            "task_source",
            "domain",
            "timestamp",
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Missing fields in GovernanceBlock: {', '.join(missing)}")

        # Basic type checks
        for field in [
            "task_id",
            "task_type",
            "task_description",
            "block_type",
            "block_reason",
            "task_source",
            "domain",
        ]:
            if not isinstance(data[field], str):
                raise ValueError(f"Field '{field}' must be a string")

        # Parse timestamp
        ts = data["timestamp"]
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid timestamp format: {ts}") from exc
        elif isinstance(ts, datetime):
            timestamp = ts
        else:
            raise ValueError("Field 'timestamp' must be ISO string or datetime")

        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_description=data["task_description"],
            block_type=data["block_type"],
            block_reason=data["block_reason"],
            task_source=data["task_source"],
            domain=data["domain"],
            timestamp=timestamp,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""

        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "block_type": self.block_type,
            "block_reason": self.block_reason,
            "task_source": self.task_source,
            "domain": self.domain,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TaskOutcomeRecord:
    """Structured representation of a task outcome / performance META memory."""

    task_id: str
    task_type: str
    task_description: str
    outcome: str  # "success" or "failure"
    confidence: float
    domain: str
    task_source: str
    timestamp: datetime
    result_summary: str | None = None
    failure_reason: str | None = None
    #: The knowledge domain the task acted in, or None when it named none.
    #: `domain` is the operation bucket outcomes are recalled by.
    knowledge_domain: str | None = None
    #: The INDEPENDENT groundings the completion judgment rested on — DID/SAW
    #: evidence items ({epoch, channel, provenance, supports, strength}). Stored
    #: WITH the outcome so a later memory query returns not just "a similar task
    #: succeeded/failed" but WHAT evidence made it so — past experience with its
    #: evidence.
    evidence: List[Dict[str, Any]] | None = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskOutcomeRecord":
        """Validate and construct from a raw dict.

        Raises ValueError if required fields are missing or malformed.
        """

        required_fields = [
            "task_id",
            "task_type",
            "task_description",
            "outcome",
            "confidence",
            "domain",
            "task_source",
            "timestamp",
        ]

        missing = [f for f in required_fields if f not in data]
        if missing:
            raise ValueError(f"Missing fields in TaskOutcomeRecord: {', '.join(missing)}")

        # Basic type checks
        for field in [
            "task_id",
            "task_type",
            "task_description",
            "outcome",
            "domain",
            "task_source",
        ]:
            if not isinstance(data[field], str):
                raise ValueError(f"Field '{field}' must be a string")

        if not isinstance(data["confidence"], (int, float)):
            raise ValueError("Field 'confidence' must be a number")

        knowledge_domain = data.get("knowledge_domain")
        if knowledge_domain is not None and not isinstance(knowledge_domain, str):
            raise ValueError("Field 'knowledge_domain' must be a string or None")

        ts = data["timestamp"]
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts)
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid timestamp format: {ts}") from exc
        elif isinstance(ts, datetime):
            timestamp = ts
        else:
            raise ValueError("Field 'timestamp' must be ISO string or datetime")

        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            task_description=data["task_description"],
            outcome=data["outcome"],
            confidence=float(data["confidence"]),
            domain=data["domain"],
            task_source=data["task_source"],
            timestamp=timestamp,
            result_summary=data.get("result_summary"),
            failure_reason=data.get("failure_reason"),
            knowledge_domain=knowledge_domain,
            evidence=data.get("evidence"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dict."""

        payload: Dict[str, Any] = {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "outcome": self.outcome,
            "confidence": float(self.confidence),
            "domain": self.domain,
            "knowledge_domain": self.knowledge_domain,
            "task_source": self.task_source,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.result_summary is not None:
            payload["result_summary"] = self.result_summary
        if self.failure_reason is not None:
            payload["failure_reason"] = self.failure_reason
        if self.evidence is not None:
            payload["evidence"] = self.evidence

        return payload


TASK_OUTCOME_EVENT = "task_outcome"


def task_outcome_from_memory(memory: Any) -> "TaskOutcomeRecord | None":
    """Recover the structured TaskOutcomeRecord from a stored memory.

    The coordinator stores one event in two representations:
      - ``content``                     : a narrative *string* (human / embedding)
      - ``thinking_state["raw_event"]`` : the structured record

    ``thinking_state["raw_event"]`` is authoritative. The narrative is lossy and
    is never parsed back — reconstructing cognitive state from prose would create
    a second, divergent interpretation of a single observation.

    Accepts a MemoryItem (duck-typed on ``.content`` / ``.thinking_state``) or a
    plain dict. Returns None if the memory is not a task outcome, or if the
    record fails validation.
    """

    if isinstance(memory, dict):
        thinking_state = memory.get("thinking_state")
        content = memory.get("content")
    else:
        thinking_state = getattr(memory, "thinking_state", None)
        content = getattr(memory, "content", None)

    candidates = []
    if isinstance(thinking_state, dict):
        candidates.append(thinking_state.get("raw_event"))
    # In-process callers and tests may hand over the record dict directly,
    # before it has been through the narrative-building store path.
    candidates.append(content)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("event") != TASK_OUTCOME_EVENT:
            continue
        try:
            return TaskOutcomeRecord.from_dict(candidate)
        except ValueError:
            continue

    return None


def task_occurrences(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every occurrence a task outcome record holds, oldest first. A record kept
    before occurrences were merged is one occurrence."""
    if isinstance(record.get("occurrences"), list):
        return [o for o in record["occurrences"] if isinstance(o, dict)]
    return [{k: v for k, v in record.items() if k not in ("occurrences", "counts")}]


def task_outcomes_from_memory(memory: Any) -> List["TaskOutcomeRecord"]:
    """One TaskOutcomeRecord per occurrence the memory holds, oldest first; an
    empty list when it is not a task outcome. Read as `task_outcome_from_memory`
    reads the latest."""
    thinking_state = (memory.get("thinking_state") if isinstance(memory, dict)
                      else getattr(memory, "thinking_state", None))
    record = thinking_state.get("raw_event") if isinstance(thinking_state, dict) else None
    if not isinstance(record, dict) or record.get("event") != TASK_OUTCOME_EVENT:
        return []
    out = []
    for occurrence in task_occurrences(record):
        try:
            out.append(TaskOutcomeRecord.from_dict(occurrence))
        except ValueError:
            continue
    return out


def task_outcome_account(task_description: str, occurrences: List[Dict[str, Any]]) -> str:
    """What the substrate says of a task it was asked to do, from every time it
    did it: once, as it always has ("I was asked to … I did it."), and when it
    was asked again, how often it went each way and why it could not."""
    def times(n: int) -> str:
        return "" if n == 1 else f" {n} times"

    import re
    done = sum(1 for o in occurrences if o.get("outcome") == "success")
    # The same reason is the same however its measurements came out: a belief
    # at 0.00 against a bar of 0.95 one time and 0.98 the next is one reason,
    # said as it was said last.
    reasons: Dict[str, List[str]] = {}
    for occurrence in occurrences:
        if occurrence.get("outcome") != "success":
            reason = str(occurrence.get("failure_reason") or "").strip().rstrip(".")
            reasons.setdefault(re.sub(r"\d+(?:\.\d+)?", "#", reason), []).append(reason)
    said = [f"I was asked to {task_description}."]
    if done:
        said.append(f"I did it{times(done)}.")
    for alike in reasons.values():
        said.append(f"I could not{times(len(alike))}" + (f", because {alike[-1]}." if alike[-1] else "."))
    return " ".join(said)


def pursuit_account(record: Dict[str, Any]) -> str:
    """What a pursuit's memory says: each task within it, in the order it was
    first done, with how often it went each way (`task_outcome_account`); and,
    once the pursuit has ended, how it ended."""
    pursuit = record.get("pursuit") or {}
    by_task: Dict[str, List[Dict[str, Any]]] = {}
    for occurrence in task_occurrences(record) if record.get("occurrences") else []:
        by_task.setdefault(str(occurrence.get("task_description") or ""), []).append(occurrence)
    said = [task_outcome_account(description, occurrences)
            for description, occurrences in by_task.items()]
    if not said:
        said = [f"I was asked to {pursuit.get('aim') or 'do something'}."]
    # WHAT WAS HEARD AND SEEN within it is part of it, and said with it, so the
    # pursuit is found by what was met in it as by what was done.
    verbs = {"heard": "heard", "seen": "saw"}
    for part in (record.get("experience") or {}).get("parts") or []:
        role, content = part.get("role"), part.get("content") or {}
        if role == "told" and isinstance(content, dict) and content.get("sentence"):
            said.append(f'I was told "{str(content["sentence"]).strip()}"'
                        + (", and could not read it." if content.get("unread") else "."))
            continue
        if role == "reply" and str(content if not isinstance(content, dict)
                                   else content.get("reply") or "").strip():
            text = str(content if not isinstance(content, dict) else content.get("reply"))
            said.append(f'I replied "{text.strip()}".')
            continue
        if role not in verbs:
            continue
        caption = str(content.get("caption") or "").strip().rstrip(".") if isinstance(content, dict) else ""
        if caption:
            count = int(part.get("count") or 1)
            said.append(f"I {verbs[role]} {caption}"
                        + (f" ({count} times)" if count > 1 else "") + ".")
    if pursuit.get("status") not in (None, "active", "forming"):
        said.append(f"The pursuit ended: {pursuit['status']}.")
    return " ".join(said)


__all__ = [
    "GovernanceBlock",
    "TaskOutcomeRecord",
    "TASK_OUTCOME_EVENT",
    "pursuit_account",
    "task_occurrences",
    "task_outcome_account",
    "task_outcome_from_memory",
    "task_outcomes_from_memory",
]
