"""What one knowledge update DID -- the record that makes an ontology change answerable.

WHY THIS EXISTS. On 2026-09-25 a domain sweep moved 78,978 concepts out of
`general` into a single invented subject, and 93 more into nine unrelated
domains. Answering "who did that, and to what?" took reverse-engineering:
grouping `unified.concepts.updated_at` by microsecond to find the bulk UPDATEs,
then reading concept names to guess whether `paleface` belonged in `vision`.
That is forensics, not telemetry.

WHAT WAS ALREADY THERE, AND IS NOT DUPLICATED HERE. Provenance is already
durable and this table REFERENCES it rather than copying it:

  * `unified.evidence_envelopes` -- producer, source_type, source_id (WHO CAUSED
    IT), content + observed_at (WHAT WAS OBSERVED), structured_data +
    derived_from (WHAT WAS INFERRED). 635,525 rows.
  * `unified.concept_evidence` -- root_evidence_id and extractor (WHAT EVIDENCE
    SUPPORTS IT, and which faculty extracted it). 244,376 rows.
  * `unified.concept_domains` -- domain membership with its source and evidence
    (WHAT DOMAIN DID IT ENTER). 96,944 rows.

WHAT WAS MISSING, AND IS HERE. Four things, none of which had any home:

  * DISPOSITION -- new / updated / merged / moved / rejected. `Admission`
    computes exactly this (concepts_created, concepts_reinforced, refusals,
    contradicts) and the caller throws it away, so the store could not say
    whether an admission had been accepted or refused.
  * THE BATCH -- the unit a burst of writes belongs to. Without it a sweep's
    79,071 writes are 79,071 unrelated rows.
  * THE CONSUMER -- `concept_evidence.extractor` says who PRODUCED a fact.
    Nothing said who later READ it.
  * BEHAVIOUR CHANGE -- whether the update altered what the substrate can or
    will do.

`changed_behaviour` is NULL until something reports on it, never False. False
would be the claim "this changed nothing", and nothing has looked. This is the
same rule that governs `ThreatSense.level()` and `ActingRule.support`: untested
is not the same as negative.
"""
from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Disposition(str, Enum):
    """What became of the thing this update was about."""

    NEW = "new"              # it did not exist here before
    UPDATED = "updated"      # it existed and this reinforced or altered it
    MERGED = "merged"        # it was found to be something already known
    MOVED = "moved"          # its domain changed; `from_domain` says from where
    REJECTED = "rejected"    # admission refused it; `detail` says why
    #: Seen before from the same source and deliberately not counted twice.
    #: NOT `rejected` -- nothing was wrong with it -- and NOT `updated`, because
    #: treating a repeat as fresh evidence is exactly what the ingress dedup
    #: exists to prevent. The same lesson as 125 byte-identical demonstrations
    #: generalising to a basis of one: repetition is not evidence.
    UNCHANGED = "unchanged"


DDL = """
CREATE TABLE IF NOT EXISTS unified.knowledge_updates (
    update_id         VARCHAR PRIMARY KEY,
    batch_id          VARCHAR NOT NULL,
    cause             VARCHAR NOT NULL,
    actor             VARCHAR,
    subject_kind      VARCHAR NOT NULL,
    subject_id        VARCHAR NOT NULL,
    disposition       VARCHAR NOT NULL,
    domain            VARCHAR,
    from_domain       VARCHAR,
    evidence_id       VARCHAR,
    detail            TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_behaviour BOOLEAN,
    behaviour_detail  TEXT
);

-- WHO CONSUMED AN UPDATE: one row per (update, faculty). A single
-- consumed_by column was copied from rule_authority_events, where it fits --
-- an authority event has exactly one consumer. Knowledge has many: coverage
-- reads a fact the instant it is admitted, and under first-drain-wins it would
-- claim every update, so reasoning's later use of the same fact could never be
-- recorded at all.
CREATE TABLE IF NOT EXISTS unified.knowledge_consumption (
    update_id   VARCHAR NOT NULL REFERENCES unified.knowledge_updates(update_id)
                ON DELETE CASCADE,
    consumer    VARCHAR NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (update_id, consumer)
);

ALTER TABLE unified.knowledge_updates DROP COLUMN IF EXISTS consumed_at;
ALTER TABLE unified.knowledge_updates DROP COLUMN IF EXISTS consumed_by;
CREATE INDEX IF NOT EXISTS knowledge_updates_evidence_idx
    ON unified.knowledge_updates (evidence_id);

CREATE INDEX IF NOT EXISTS knowledge_updates_batch_idx
    ON unified.knowledge_updates (batch_id);
CREATE INDEX IF NOT EXISTS knowledge_updates_subject_idx
    ON unified.knowledge_updates (subject_kind, subject_id);
CREATE INDEX IF NOT EXISTS knowledge_updates_when_idx
    ON unified.knowledge_updates (occurred_at);
DROP INDEX IF EXISTS unified.knowledge_updates_unconsumed_idx;
"""

_schema_ready: set = set()

#: WHERE THE LEDGER IS KEPT. It records changes to the substrate's own knowledge
#: (rules, domains, concepts, patterns), so it is part of the model
#: (postgres_config.STORE_TABLES). A person's facts go to their own context, which
#: the ledger does not record. Named here because one schema statement drops an
#: index, and an index's name does not say whose table it is on -- unnamed, the
#: separated copy refused it on every ledger write, and the schema was never marked
#: ready (measured 2026-09-27, 356 refusals in one boot). Against a frozen release
#: the schema is checked, not run, and the ledger records nothing: nothing changes.
LEDGER_STORE = "model"


async def ensure_schema(db) -> None:
    key = id(db)
    if key in _schema_ready:
        return
    for statement in filter(None, (s.strip() for s in DDL.split(";"))):
        await db.execute_query(statement, store=LEDGER_STORE)
    _schema_ready.add(key)


# ── THE BATCH ────────────────────────────────────────────────────────────────
# A ContextVar, for the same reason the acting context is one: the writers that
# need to join a batch are several frames below the operation that started it,
# and threading a batch_id through every signature would mean every caller could
# forget it. An update recorded outside any batch gets its own -- it is still a
# batch of one, never an unattributed row.

@dataclass(frozen=True)
class Batch:
    batch_id: str
    cause: str
    actor: Optional[str] = None


_batch: contextvars.ContextVar[Optional[Batch]] = contextvars.ContextVar(
    "knowledge_update_batch", default=None)


def begin_batch(cause: str, *, actor: Optional[str] = None) -> Any:
    """Open a batch. Returns the token to pass to `end_batch` in a finally."""
    return _batch.set(Batch(batch_id=f"kub_{uuid.uuid4().hex[:12]}",
                            cause=str(cause), actor=actor))


def end_batch(token: Any) -> None:
    _batch.reset(token)


def current_batch() -> Optional[Batch]:
    return _batch.get()


@dataclass
class KnowledgeUpdate:
    subject_kind: str
    subject_id: str
    disposition: Disposition
    domain: Optional[str] = None
    from_domain: Optional[str] = None
    evidence_id: Optional[str] = None
    detail: str = ""
    #: Only set when there is no enclosing batch and the caller knows the cause.
    cause: Optional[str] = None
    actor: Optional[str] = None
    update_id: str = ""
    batch_id: str = ""

    def stamped(self) -> "KnowledgeUpdate":
        batch = current_batch()
        cause = self.cause or (batch.cause if batch else None)
        if not cause:
            raise ValueError(
                f"knowledge update for {self.subject_kind} {self.subject_id} has "
                "no cause: either open a batch or name the cause. An update "
                "nobody can be asked about is the defect this table exists for")
        return KnowledgeUpdate(
            subject_kind=self.subject_kind, subject_id=self.subject_id,
            disposition=self.disposition, domain=self.domain,
            from_domain=self.from_domain, evidence_id=self.evidence_id,
            detail=self.detail, cause=cause,
            actor=self.actor or (batch.actor if batch else None),
            update_id=self.update_id or f"ku_{uuid.uuid4().hex[:12]}",
            batch_id=self.batch_id or (batch.batch_id if batch
                                       else f"kub_{uuid.uuid4().hex[:12]}"))


async def record(db, update: KnowledgeUpdate) -> KnowledgeUpdate:
    """Write one update down."""
    from core.agents.memory_agent import memory_agent
    stamped = update.stamped()
    await ensure_schema(db)
    await memory_agent().record_knowledge_update(
        update_id=stamped.update_id, batch_id=stamped.batch_id, cause=stamped.cause,
        actor=stamped.actor, subject_kind=stamped.subject_kind,
        subject_id=stamped.subject_id, disposition=stamped.disposition.value,
        domain=stamped.domain, from_domain=stamped.from_domain,
        evidence_id=stamped.evidence_id, detail=stamped.detail)
    return stamped


async def record_many(db, updates: List[KnowledgeUpdate]) -> int:
    """Write a batch's rows in one statement. A sweep that moves 79,000 concepts
    must not become 79,000 round trips -- that cost is exactly why the writer it
    replaces was a single bare UPDATE with no record at all."""
    if not updates:
        return 0
    from core.agents.memory_agent import memory_agent
    await ensure_schema(db)
    stamped = [u.stamped() for u in updates]
    return await memory_agent().record_knowledge_updates([
        (s.update_id, s.batch_id, s.cause, s.actor, s.subject_kind, s.subject_id,
         s.disposition.value, s.domain, s.from_domain, s.evidence_id, s.detail)
        for s in stamped])


async def pending_updates(db, *, consumer: str, domain: Optional[str] = None,
                          subject_kind: Optional[str] = None,
                          limit: int = 500) -> List[Dict[str, Any]]:
    """Updates THIS consumer has not yet claimed, oldest first.

    Per consumer, because knowledge is read by several faculties: that coverage
    has used a fact says nothing about whether reasoning has.
    """
    await ensure_schema(db)
    params: List[Any] = [consumer]
    where = ["NOT EXISTS (SELECT 1 FROM unified.knowledge_consumption c "
             "WHERE c.update_id = k.update_id AND c.consumer = $1)"]
    if domain is not None:
        params.append(domain)
        where.append(f"k.domain = ${len(params)}")
    if subject_kind is not None:
        params.append(subject_kind)
        where.append(f"k.subject_kind = ${len(params)}")
    params.append(int(limit))
    rows = await db.execute_query(
        "SELECT k.update_id, k.batch_id, k.cause, k.subject_kind, k.subject_id,"
        " k.disposition, k.domain, k.evidence_id, k.occurred_at"
        " FROM unified.knowledge_updates k"
        f" WHERE {' AND '.join(where)} ORDER BY k.occurred_at, k.update_id"
        f" LIMIT ${len(params)}", tuple(params), fetch_all=True) or []
    return [dict(r) for r in rows]


async def mark_consumed(db, update_ids: List[str], consumer: str) -> int:
    """Record that `consumer` used these updates. Returns how many THIS call
    newly recorded.

    COUNTING THE INPUT WOULD BE A FALSE SUCCESS: the number asked about is not
    the number recorded, and a repeat by the same faculty would report work it
    had already reported. `RETURNING` makes the answer the rows that changed.
    """
    ids = [i for i in dict.fromkeys(update_ids) if i]
    if not ids:
        return 0
    from core.agents.memory_agent import memory_agent
    await ensure_schema(db)
    rows = await memory_agent().mark_knowledge_consumed(update_ids=ids, consumer=consumer)
    return len(rows)


async def mark_consumed_by_evidence(db, evidence_ids: List[str], consumer: str) -> int:
    """Record use by the EVIDENCE a faculty rested on.

    The reasoning routes know what they rested on as evidence-envelope ids --
    the key shared by `concept_relations`, `evidence_envelopes` and this table --
    not as update ids. Resolved here so a consumer never has to guess.
    """
    ids = [e for e in dict.fromkeys(evidence_ids) if e]
    if not ids:
        return 0
    await ensure_schema(db)
    rows = await db.execute_query(
        "SELECT update_id FROM unified.knowledge_updates WHERE evidence_id = ANY($1)",
        (ids,), fetch_all=True) or []
    return await mark_consumed(db, [r["update_id"] for r in rows], consumer)


async def mark_behaviour_change(db, *, batch_id: str, changed: bool,
                                detail: str = "") -> None:
    """Record whether this batch altered what the substrate can or will do.

    Called with `changed=False` only by something that actually LOOKED. Left
    untouched, the column stays NULL, which reads as "nobody has asked".
    """
    from core.agents.memory_agent import memory_agent
    await ensure_schema(db)
    await memory_agent().mark_behaviour_change(
        batch_id=batch_id, changed=bool(changed), detail=detail)


async def report(db, *, since: Any = None) -> Dict[str, Any]:
    """The runtime's knowledge-update account, per batch.

    This is the difference between "the ontology grew by 93 concepts" and "9
    domains received 83 distinct updates, each with an originating event, a
    semantic identity, an admission state and its downstream consumers".
    """
    await ensure_schema(db)
    where, params = "", ()
    if since is not None:
        where, params = " WHERE occurred_at >= $1", (since,)
    totals = await db.execute_query(
        "SELECT count(*) updates, count(DISTINCT batch_id) batches,"
        " count(DISTINCT domain) domains, count(DISTINCT subject_id) subjects,"
        " count(*) FILTER (WHERE EXISTS (SELECT 1 FROM unified.knowledge_consumption c"
        "   WHERE c.update_id = k.update_id)) consumed,"
        " count(*) FILTER (WHERE changed_behaviour IS TRUE) changed_behaviour,"
        " count(*) FILTER (WHERE changed_behaviour IS NULL) behaviour_unknown"
        f" FROM unified.knowledge_updates k{where}", params)
    by_consumer = await db.execute_query(
        "SELECT c.consumer, count(*) n FROM unified.knowledge_consumption c"
        " JOIN unified.knowledge_updates k ON k.update_id = c.update_id"
        f"{where.replace('occurred_at', 'k.occurred_at')} GROUP BY 1 ORDER BY n DESC",
        params, fetch_all=True) or []
    by_disposition = await db.execute_query(
        "SELECT disposition, count(*) n FROM unified.knowledge_updates"
        f"{where} GROUP BY 1 ORDER BY n DESC", params, fetch_all=True) or []
    by_cause = await db.execute_query(
        "SELECT cause, count(DISTINCT batch_id) batches, count(*) updates"
        f" FROM unified.knowledge_updates{where} GROUP BY 1 ORDER BY updates DESC"
        " LIMIT 20", params, fetch_all=True) or []
    row = dict(totals[0]) if totals else {}
    return {
        "updates": int(row.get("updates") or 0),
        "batches": int(row.get("batches") or 0),
        "domains": int(row.get("domains") or 0),
        "subjects": int(row.get("subjects") or 0),
        "consumed": int(row.get("consumed") or 0),
        "by_consumer": {r["consumer"]: r["n"] for r in by_consumer},
        "changed_behaviour": int(row.get("changed_behaviour") or 0),
        "behaviour_unknown": int(row.get("behaviour_unknown") or 0),
        "by_disposition": {r["disposition"]: r["n"] for r in by_disposition},
        "by_cause": [dict(r) for r in by_cause],
    }


async def explain(db, *, batch_id: str) -> Dict[str, Any]:
    """Everything answerable about one batch, provenance joined from where it
    already lives rather than copied into this table."""
    await ensure_schema(db)
    head = await db.execute_query(
        "SELECT batch_id, cause, actor, min(occurred_at) started,"
        " max(occurred_at) ended, count(*) updates"
        " FROM unified.knowledge_updates WHERE batch_id = $1"
        " GROUP BY batch_id, cause, actor", (batch_id,))
    rows = await db.execute_query(
        "SELECT k.subject_kind, k.subject_id, k.disposition, k.domain,"
        " k.from_domain, k.detail, k.changed_behaviour,"
        " (SELECT array_agg(c.consumer ORDER BY c.consumed_at)"
        "    FROM unified.knowledge_consumption c"
        "   WHERE c.update_id = k.update_id) consumed_by,"
        " e.producer, e.source_type, e.source_id, e.content observed,"
        " e.structured_data inferred, e.derived_from"
        " FROM unified.knowledge_updates k"
        " LEFT JOIN unified.evidence_envelopes e ON e.evidence_id = k.evidence_id"
        " WHERE k.batch_id = $1 ORDER BY k.occurred_at LIMIT 200",
        (batch_id,), fetch_all=True) or []
    return {"batch": dict(head[0]) if head else None,
            "updates": [dict(r) for r in rows]}
