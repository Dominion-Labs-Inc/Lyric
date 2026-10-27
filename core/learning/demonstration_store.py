#!/usr/bin/env python3
"""The ground demonstrations an operator is induced from, kept so induction can
be re-run as experience accumulates.

Induction needs at least two positive demonstrations, and the preconditions it
recovers are only as sharp as the negatives it has seen. A single executed
action is one demonstration; it cannot, by itself, teach an operator. So the
substrate must remember every before/action/after it observes and re-induce
over the growing set -- which is what "the substrate learns from its own
experience" concretely requires.

This is deliberately NOT the concept-ingestion demonstration path. That path
(`submit_demonstration`) records a transition's STRUCTURE -- predicate and arity
-- into the concept graph for the cross-domain matcher, and drops the ground
arguments. Induction cannot run on structure alone: `MOVE(z,HALL,LAB)` and
`MOVE(z,LAB,VAULT)` are the two positives that align to the general rule, and
their arguments are exactly what alignment reads. So the ground examples are
kept here, in full, keyed by the operator signature they teach.

One authority, one thing: this stores ground demonstrations and hands them back
as TrainingExamples. It does not induce, judge, or apply -- those belong to the
RuleInducer, the RuleStore, and the executor respectively.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.learning.rule_induction import Fact, RuleEffects, TrainingExample

logger = logging.getLogger(__name__)


# Producer trigger (event-driven induction). The coordinator registers a cheap,
# synchronous, non-raising callback here; enqueuing a pending induction signature
# then WAKES the induction drain instead of a fixed-interval poll sweeping for
# backlog. Every producer of a demonstration converges on `append` below, so this
# is the one correct place to fire it. Opt-in: unset (standalone/test contexts)
# means recording behaves exactly as before.
_ON_PENDING: Optional[Callable[[], None]] = None


def set_on_pending(callback: Optional[Callable[[], None]]) -> None:
    """Register (or clear, with None) the callback fired right after a signature
    is enqueued for induction. Must be cheap and must not raise."""
    global _ON_PENDING
    _ON_PENDING = callback


DDL = """
CREATE TABLE IF NOT EXISTS unified.operator_demonstrations (
    evidence_id   VARCHAR PRIMARY KEY,
    domain_id     VARCHAR NOT NULL,
    predicate     VARCHAR NOT NULL,
    arity         INTEGER NOT NULL,
    before_facts  JSONB   NOT NULL,
    action        VARCHAR,
    after_facts   JSONB   NOT NULL,
    positive      BOOLEAN NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- WHOSE WORK IT WAS: a person's demonstration holds their particulars (the files of their task), and an operator
-- induced from such demonstrations is the world's only once nothing of them is left in it
-- (docs/research/SEPARATION_MAP.md §11.6). NULL is the substrate's own work.
ALTER TABLE unified.operator_demonstrations ADD COLUMN IF NOT EXISTS owner VARCHAR;
-- WHEN A CHANGE THE WORLD MADE ON ITS OWN WAS SEEN: since when what held before
-- it had held, and when the change was read. How long a regularity takes is
-- learned from these (`lags`). NULL for an act's demonstration.
ALTER TABLE unified.operator_demonstrations ADD COLUMN IF NOT EXISTS before_at TIMESTAMPTZ;
ALTER TABLE unified.operator_demonstrations ADD COLUMN IF NOT EXISTS after_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS operator_demonstrations_signature
    ON unified.operator_demonstrations (domain_id, predicate, arity, created_at);

-- The signatures with demonstrations recorded but not yet re-induced. This is
-- the queue that lets recording (cheap, on the acting path) and induction
-- (expensive, off it) run apart: a new demonstration enqueues its signature
-- here, and the always-online learner drains it in the background. A SET, not a
-- log -- one row per signature, re-marked idempotently -- so a burst of
-- demonstrations for one operator is one unit of pending work, not many.
CREATE TABLE IF NOT EXISTS unified.operator_induction_pending (
    domain_id   VARCHAR NOT NULL,
    predicate   VARCHAR NOT NULL,
    arity       INTEGER NOT NULL,
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain_id, predicate, arity)
);
"""


#: What begins the signature of a change the world made on its own.
REGULARITY_PREFIX = "~"


def regularity_signature(effects: RuleEffects, things=frozenset()) -> Tuple[str, int]:
    """The signature a change the world made on its own is filed under: what it
    added and took away, with the thing that changed left open and the places
    it changed in named -- `AT(_,INBOX)` gone and `AT(_,DONE)` come is one kind
    of change, a move from DONE to ARCHIVE another. Changes of one kind are
    evidence for one regularity, as demonstrations of one act are for one
    operator.

    The thing is a variable in a regularity's effects, and in a change the
    world was seen to make, a term in `things` (`world_change_examples`)."""
    from core.learning.rule_induction import is_variable

    def shape(fact: Fact) -> str:
        return f"{fact.predicate}(" + ",".join(
            "_" if is_variable(t) or t in things else t for t in fact.args) + ")"

    parts = sorted({"+" + shape(f) for f in effects.add} | {"-" + shape(f) for f in effects.delete})
    return REGULARITY_PREFIX + "|".join(parts), 0


def is_regularity_signature(predicate: str) -> bool:
    return str(predicate).startswith(REGULARITY_PREFIX)


def _facts_json(facts: Sequence[Fact]) -> str:
    return json.dumps([str(f) for f in facts])


def _parse_facts(payload) -> tuple:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return tuple(Fact.parse(text) for text in payload)


class DemonstrationStore:
    """Persists ground demonstrations and reloads them by operator signature."""

    def __init__(self, db_manager=None):
        self._db = db_manager

    def db(self):
        if self._db is None:
            from core.database import get_database_manager
            self._db = get_database_manager()
        return self._db

    async def _ready(self):
        db = self.db()
        if not getattr(db, "initialized", False):
            await db.initialize()

    async def ensure_schema(self):
        await self._ready()
        for statement in filter(None, (s.strip() for s in DDL.split(";"))):
            await self.db().execute_query(statement)

    #: The signature a demonstration with no action is filed under. An
    #: actionless demonstration is not about one operator -- it is contrastive
    #: evidence about the whole domain: a state held, nothing was done, and the
    #: effects did not occur on their own. It teaches every operator that its
    #: action is NECESSARY, which is why it belongs to the domain, not a
    #: predicate.
    CONTRASTIVE = ("", 0)

    async def append(self, example: TrainingExample, *, domain_id: str,
                     owner: Optional[str] = None,
                     regularity: Optional[Tuple[str, int]] = None,
                     before_at: Optional[datetime] = None,
                     after_at: Optional[datetime] = None) -> bool:
        """Record one demonstration.

        An action-ful demonstration is filed under the operator signature it
        teaches. An ACTIONLESS one is filed as domain-level contrastive evidence
        -- a state in which no action was taken and the effects did not follow,
        which is what proves an action is necessary rather than incidental.
        Induction from action-ful demonstrations alone cannot establish that:
        the preconditions co-occur with the action in every positive, so the
        more general rule that drops the action fits the same evidence.

        Idempotent on `evidence_id`: an observation has one identity, and the
        same transition arriving twice must not read as independent
        corroboration. `owner` is whose work it was, None for the substrate's
        own. Returns True if a new row was written.

        A CHANGE THE WORLD MADE ON ITS OWN is also actionless, and is the
        opposite of a contrastive negative: something DID follow with nothing
        done. Filed as contrastive it would teach every operator that its
        effects need no act. So it is filed under its own `regularity`
        signature (`regularity_signature`), with when what held before it was
        first seen holding (`before_at`) and when the change was read
        (`after_at`).
        """
        if not example.evidence_id:
            raise ValueError(
                "a demonstration carries no evidence_id; without it the store "
                "cannot keep one observation from counting twice")
        if not domain_id:
            raise ValueError("a demonstration must belong to a domain")
        if regularity is not None and example.action is not None:
            raise ValueError("a change with an act in it is the act's demonstration, "
                             "not a regularity of the world")

        await self.ensure_schema()
        if regularity is not None:
            predicate, arity = regularity
        else:
            predicate, arity = (
                example.action.signature if example.action is not None
                else self.CONTRASTIVE)
        from core.agents.memory_agent import memory_agent
        rows = await memory_agent().hold_demonstration(
            evidence_id=example.evidence_id, domain_id=domain_id, predicate=predicate,
            arity=arity, before_facts=_facts_json(example.before),
            action=str(example.action) if example.action is not None else None,
            after_facts=_facts_json(example.after), positive=bool(example.positive), owner=owner,
            before_at=before_at, after_at=after_at)
        written = bool(rows)
        if written:
            # Enqueue the signature for off-band induction. Cheap (one upsert),
            # so recording stays a hot-path operation; the hypothesis search it
            # triggers happens later, off the acting path. An actionless
            # contrastive enqueues under CONTRASTIVE -- the drain expands it to
            # every operator in the domain, because a new contrastive sharpens
            # them all.
            await self._mark_pending(domain_id, predicate, arity)
            # WAKE the induction drain (event-driven): a signature is now pending.
            # All demonstration producers converge here, so this fires for the
            # executor AND for exploration-recorded signatures alike.
            if _ON_PENDING is not None:
                try:
                    _ON_PENDING()
                except Exception as _cb_err:
                    logger.debug("on_pending callback failed (non-fatal): %s", _cb_err)
        logger.info("demonstration %s for %s in %s: %s", example.evidence_id,
                    predicate if regularity is not None
                    else f"{predicate}/{arity}" if example.action else "contrastive",
                    domain_id, "recorded" if written else "already present")
        return written

    async def acted_in(self, *, domain_id: str, after: datetime, before: datetime) -> bool:
        """Whether the substrate is recorded acting in a domain between two
        moments: a demonstration of one of its acts was filed there then. What
        a process restarted since can know of acts before it began."""
        await self.ensure_schema()
        row = await self.db().execute_query(
            "SELECT 1 AS acted FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND action IS NOT NULL"
            " AND created_at > $2 AND created_at <= $3 LIMIT 1",
            (domain_id, after, before), fetch_one=True)
        return row is not None

    async def lags(self, *, domain_id: str, predicate: str, arity: int) -> Dict[str, float]:
        """How long each change filed under a regularity signature took, in
        seconds: from when what held before it was first seen holding to when
        the change was read. Only changes with both times."""
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT evidence_id, EXTRACT(EPOCH FROM (after_at - before_at)) AS seconds"
            " FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3 AND positive"
            " AND before_at IS NOT NULL AND after_at IS NOT NULL",
            (domain_id, predicate, arity), fetch_all=True,
        ) or []
        return {str(r["evidence_id"]): float(r["seconds"]) for r in rows}

    async def owners(self, evidence_ids: Sequence[str]) -> Dict[str, Optional[str]]:
        """Whose work each demonstration was: `{evidence_id: owner}`, None for the substrate's own."""
        ids = sorted({str(i) for i in evidence_ids if i})
        if not ids:
            return {}
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT evidence_id, owner FROM unified.operator_demonstrations WHERE evidence_id = ANY($1::text[])",
            (ids,), fetch_all=True) or []
        return {str(r["evidence_id"]): r["owner"] for r in rows}

    async def _mark_pending(self, domain_id: str, predicate: str, arity: int) -> None:
        from core.agents.memory_agent import memory_agent
        await memory_agent().mark_induction_pending(
            domain_id=domain_id, predicate=predicate, arity=arity)

    async def pending_signatures(self, *, limit: Optional[int] = None,
                                 with_marks: bool = False) -> List[tuple]:
        """Signatures awaiting re-induction, oldest enqueue first; `with_marks`
        adds when each was last marked, for `clear_pending`."""
        await self.ensure_schema()
        query = ("SELECT domain_id, predicate, arity, enqueued_at FROM"
                 " unified.operator_induction_pending ORDER BY enqueued_at")
        if limit is not None:
            query += f" LIMIT {int(limit)}"
        rows = await self.db().execute_query(query, fetch_all=True) or []
        if with_marks:
            return [(r["domain_id"], r["predicate"], r["arity"], r["enqueued_at"]) for r in rows]
        return [(r["domain_id"], r["predicate"], r["arity"]) for r in rows]

    async def clear_pending(self, *, domain_id: str, predicate: str, arity: int,
                            marked: Any = None) -> None:
        """Clear a signature's pending mark. Given `marked`, the time the mark
        was read before inducing, a mark made since -- a demonstration recorded
        while the signature was being induced -- is kept for the next pass.
        Cleared outright, that demonstration was never judged: Lyric acted, the
        world refused, the record re-marked the signature mid-judgement, and the
        drain's clear removed the mark (RULE-AUTHORITY-02's live arm: a rule
        kept its authority with the refusal on record)."""
        from core.agents.memory_agent import memory_agent
        await memory_agent().clear_induction_pending(
            domain_id=domain_id, predicate=predicate, arity=arity, marked=marked)

    async def load(self, *, domain_id: str, predicate: str,
                   arity: int) -> List[TrainingExample]:
        """Every demonstration recorded for one operator signature, oldest first.

        Oldest first so an induction/held-out split by recency is stable: the
        rule is induced from what was seen earlier and judged against what came
        after, and a run that reordered them could validate a rule on an
        observation it was induced from.
        """
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT evidence_id, before_facts, action, after_facts, positive"
            " FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3"
            " ORDER BY created_at, evidence_id",
            (domain_id, predicate, arity), fetch_all=True,
        ) or []

        return [self._example(row) for row in rows]

    async def load_contrastive(self, *, domain_id: str) -> List[TrainingExample]:
        """The domain's actionless contrastive negatives, oldest first.

        Included in the induction basis of every operator so induction can
        establish that the action -- not the co-occurring preconditions alone --
        produces the effect. Without them a runtime that only ever executes
        actions would induce operators that drop the action entirely.
        """
        await self.ensure_schema()
        predicate, arity = self.CONTRASTIVE
        rows = await self.db().execute_query(
            "SELECT evidence_id, before_facts, action, after_facts, positive"
            " FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 AND predicate = $2 AND arity = $3"
            " ORDER BY created_at, evidence_id",
            (domain_id, predicate, arity), fetch_all=True,
        ) or []
        return [self._example(row) for row in rows]

    @staticmethod
    def _example(row) -> TrainingExample:
        action = row["action"]
        return TrainingExample(
            before=_parse_facts(row["before_facts"]),
            action=Fact.parse(action) if action else None,
            after=_parse_facts(row["after_facts"]),
            positive=bool(row["positive"]),
            evidence_id=row["evidence_id"],
        )

    async def signatures(self, *, domain_id: str) -> List[tuple]:
        """The (predicate, arity) signatures with demonstrations in a domain."""
        await self.ensure_schema()
        rows = await self.db().execute_query(
            "SELECT DISTINCT predicate, arity FROM unified.operator_demonstrations"
            " WHERE domain_id = $1 ORDER BY predicate, arity",
            (domain_id,), fetch_all=True,
        ) or []
        return [(row["predicate"], row["arity"]) for row in rows]

    async def domains_with_signatures(self) -> set:
        """The domains holding demonstrations of at least one operator signature, contrastive ones and regularities of
        the world aside: where there is an operator to sharpen."""
        await self.ensure_schema()
        predicate, arity = self.CONTRASTIVE
        rows = await self.db().execute_query(
            "SELECT DISTINCT domain_id FROM unified.operator_demonstrations"
            " WHERE NOT (predicate = $1 AND arity = $2) AND NOT starts_with(predicate, $3)",
            (predicate, arity, REGULARITY_PREFIX), fetch_all=True,
        ) or []
        return {row["domain_id"] for row in rows}


_store: Optional[DemonstrationStore] = None


def get_demonstration_store() -> DemonstrationStore:
    global _store
    if _store is None:
        _store = DemonstrationStore()
    return _store
