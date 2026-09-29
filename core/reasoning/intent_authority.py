#!/usr/bin/env python3
"""Intent — the substrate's own account of what it is trying to do and why.

Owned by the reasoning authority. This module is that owner's store and lifecycle;
the `NeuralSymbolicBridge` holds it and is the only thing that WRITES intent.
Everyone else — the constitution, learning, appraisal's integrity, goal creation —
only reads. See `docs/design/INTENT_AUTHORITY.md` for the rationale and the model.

TWO STORES, ONE INTENT, split at record time:

  * SHAPE  — substrate-wide, in `unified.intents`. The reasoning skeleton and the
             anonymous lesson: operator, laws, verdict, action class, outcome
             class. NO arguments, no text, no actor id. What learning reads.
  * CONTENT — actor-scoped, in `unified.scoped_intents`, partitioned by
             `scope_actor`. The aim in the user's terms, the message context, the
             topic, the bound specifics. Deleted with the actor's profile; shared
             goal creation never reads it.

The two are linked by `intent_id`. Deleting an actor removes the content rows and
the continuity index; the shape rows remain, carrying no trace of who — the
lesson survives, the tie to the person does not.

IDENTITY IS A TREE. Continuity is resolved by a level-typed key, not a flat one:
a conversation intent is found by `thread:<thread_id>` within its actor; a goal
raised while working is its OWN intent, found by `goal:<goal_id>`, with a
`parent_intent_id` pointing at whatever raised it. Goals never use the thread
key, so a goal raised inside a thread cannot collapse into the conversation's
intent. Topic is content, refreshed as understanding sharpens — never identity.
"""
from __future__ import annotations

import contextvars

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from core.database import TorinUnifiedDatabase

logger = logging.getLogger(__name__)


def _blob(value: Any) -> Any:
    """A JSONB column that asyncpg may hand back as str, dict/list, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


#: The actor for the substrate's OWN reasoning — its intentions on its own
#: behalf, not a user's. Its content lives under this scope like any actor's.
#: WHO THE SUBSTRATE IS, named in ONE place.
#:
#: This module declared its own `SUBSTRATE_ACTOR = "substrate"` while
#: `shared_types` declared `"__substrate__"`, and `is_substrate_actor` — the one
#: function that decides whether work is the substrate's own or a user's —
#: recognised only the second. 875 of the substrate's own intents were filed
#: under a name its own ownership test answered False for.
#:
#: Nothing noticed while nothing consumed the answer. The moment ownership became
#: load-bearing in Law 3 (the substrate may risk its own things, not a user's),
#: the split became a governance fault: the substrate would treat its own work as
#: a stranger's and refuse acts it has every right to take.
#:
#: `shared_types` is the owner because that is where `actor_for` lives — the
#: function whose docstring already says "ONE RULE, IN ONE PLACE, so the
#: internal/external line cannot be drawn differently at different call sites."
#: The rule was in one place; the constant it compares against was in two.
#:
#: The underscores are deliberate: `actor_for` refuses a user id equal to it, so
#: the substrate's identity cannot be claimed by someone signing in.
from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR, store_for_owner  # noqa: E402

#: Where the SHAPE rows are kept: the substrate's running record of what it is
#: pursuing (postgres_config: `unified.intents` is runtime). An actor's CONTENT
#: rows are kept with their owner (`IntentStore._content_store`).
SHAPE_STORE = "runtime"


def continuity_thread(thread_id: str) -> str:
    """The continuity key for a conversation thread."""
    return f"thread:{thread_id}"


def continuity_goal(goal_id: str) -> str:
    """The continuity key for a goal — its own identity, never the thread's."""
    return f"goal:{goal_id}"


def continuity_question(query: str) -> str:
    """The continuity key for a standalone reasoning with no thread or goal.

    Keyed by the normalized query so asking the same thing again refreshes the
    same intent rather than proliferating one per call — bounded continuity for
    reasoning that carries no other anchor."""
    import hashlib
    normalized = " ".join((query or "").lower().split())
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"question:{digest}"


#: THE LIFECYCLE, NAMED BY ITS OWNER. A pursuit is either still being pursued
#: or it is over. `standing` spelled both sets out inline, and the task gate now
#: asks the same question of a single intent — may work on this pursuit still
#: begin — so the answer lives here, beside the status it describes, rather than
#: being re-spelled by every reader that needs it.
#:
#: THREE OF THE LIVE STATES ARE THE CONSTITUTION'S. A halt is "not now", a
#: REPLAN is "not by this route", a REDIRECT is "not in this form" — none of them
#: says the aim was met, and none says it was given up. Every one of them used to
#: be reconciled as `abandoned`, so the substrate's own record said it had QUIT
#: pursuits its law had only sent back, and could not tell, later, why the work
#: had stopped. A BLOCK — "this may not happen" — is the one refusal that ends a
#: pursuit, and it has its own status, `refused`.
LIVE = ("forming", "active", "halted", "replanned", "redirected")
CONCLUDED = ("fulfilled", "abandoned", "refused")
#: Sent back by the constitution: still pursued, but NOT by the act or route that
#: was stopped. Work that IS that act or route must not start again as it was; the
#: pursuit resumes when planning returns to it, with a new route or the permitted
#: form — which is a return, and reopens it.
SENT_BACK = ("replanned", "redirected")


@dataclass
class Intent:
    """The substrate's held intent. `shape` is substrate-wide; `content` is the
    actor's and dies with the profile. Convenience readers reach into them."""
    intent_id: str
    origin_kind: str                       # thread | goal | question | self_goal
    actor: str
    continuity_key: str
    parent_intent_id: Optional[str] = None
    shape: Dict[str, Any] = field(default_factory=dict)
    content: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    outcome: Optional[Dict[str, Any]] = None
    status: str = "forming"                # see LIVE / CONCLUDED above
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # ── convenience reads (never storage) ────────────────────────────────────
    @property
    def aim(self) -> str:
        return str(self.content.get("aim", ""))

    @property
    def topic(self) -> str:
        return str(self.content.get("topic", ""))

    @property
    def operator(self) -> str:
        return str(self.shape.get("operator", ""))

    @property
    def proved(self) -> bool:
        return bool(self.shape.get("proved"))

    @property
    def domain(self) -> str:
        """The domain the proved route belongs to."""
        return str(self.shape.get("domain") or "")

    @property
    def goal_conditions(self) -> List[str]:
        """The goal state reasoning found a route to."""
        return [str(c) for c in (self.shape.get("goal_conditions") or [])]

    @property
    def rule_id(self) -> str:
        """The learned rule licensing this route's first operator."""
        ids = self.shape.get("rule_ids") or []
        return str(ids[0]) if ids else str(self.shape.get("rule_id") or "")

    @property
    def concluded(self) -> bool:
        """The pursuit is over — realized, given up, or refused. Work that is a
        step of it is no longer anyone's to begin."""
        return self.status in CONCLUDED

    @property
    def sent_back(self) -> bool:
        """The constitution replanned or redirected it: still pursued, but not by
        the act or route that was stopped."""
        return self.status in SENT_BACK

    def predicate(self) -> str:
        """The operator's predicate — `MOVE_FILE` of `MOVE_FILE(?X0, A, B)`."""
        return self.operator.split("(", 1)[0].strip() if self.operator else ""

    @property
    def proof(self) -> str:
        """Why this counts as proved, in the authority's own terms.

        There is no re-verification to report: an intent is proved because the
        planner's search found this route over operators the rule store attests
        are executable, and only the planner can record that. A reader is not
        re-litigating a claim, it is reading what was recorded."""
        if not self.proved:
            return "no proved route recorded"
        rules = ", ".join(str(r) for r in (self.shape.get("rule_ids") or [])) or "none"
        return (f"planner proved {self.shape.get('steps', 0)} step(s) in domain "
                f"{self.domain or '?'} over rule(s) {rules}")

    def stated(self) -> bool:
        """Reasoning proved a route: an operator, a goal it reaches, and a proof.
        A goal with no proved act is a wish; an act with no goal is a thing
        happening for no stated reason."""
        return bool(self.operator and self.shape.get("goal_conditions") and self.proved)

    def shape_view(self) -> "Intent":
        """The actor-free view: what a substrate-wide reader (learning) may see.
        Content, actor and continuity are stripped — only the anonymous lesson,
        the tree links and the outcome remain."""
        return Intent(
            intent_id=self.intent_id, origin_kind=self.origin_kind, actor="",
            continuity_key="", parent_intent_id=self.parent_intent_id,
            shape=dict(self.shape), content={}, history=[], outcome=self.outcome,
            status=self.status, version=self.version, created_at=self.created_at,
            updated_at=self.updated_at)


class IntentStore:
    """Persistence for intent: the two tables, and atomic writes across them.

    No silent degrade — a create writes both rows or neither. A read of an intent
    the actor does not own returns None, not another actor's content."""

    def __init__(self) -> None:
        self.db = TorinUnifiedDatabase()
        self._schema_ready = False

    async def _ready(self) -> None:
        if not self.db.initialized:
            await self.db.initialize()
        if self._schema_ready:
            return
        await self.db.execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.intents (
                intent_id        TEXT PRIMARY KEY,
                parent_intent_id TEXT,
                origin_kind      TEXT NOT NULL,
                shape            JSONB NOT NULL DEFAULT '{}'::jsonb,
                outcome          JSONB,
                status           TEXT NOT NULL DEFAULT 'forming',
                version          INTEGER NOT NULL DEFAULT 1,
                created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            commit=True)
        await self.db.execute_query(
            "CREATE INDEX IF NOT EXISTS intents_parent_idx "
            "ON unified.intents (parent_intent_id)",
            commit=True)
        # Content rows are kept with their owner (`_content_store`): the substrate's
        # beside the shape rows, a person's in their context. The table exists in both.
        for store in self.db.schema_stores(SHAPE_STORE):
            await self.db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS unified.scoped_intents (
                    scope_actor    TEXT NOT NULL,
                    intent_id      TEXT NOT NULL,
                    continuity_key TEXT NOT NULL,
                    content        JSONB NOT NULL DEFAULT '{}'::jsonb,
                    history        JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (scope_actor, intent_id),
                    UNIQUE (scope_actor, continuity_key)
                )
                """,
                commit=True, store=store)
        self._schema_ready = True

    @staticmethod
    def _content_store(actor: str) -> str:
        """Where an actor's content rows are kept: the substrate's own beside the
        shape rows (runtime), a person's in their context."""
        return store_for_owner(actor, SHAPE_STORE)

    def _one_database(self, actor: str) -> bool:
        """Whether this actor's content row is in the same database as the shape
        rows, so both can be written in one transaction."""
        return (self.db.config.database_for(SHAPE_STORE)
                == self.db.config.database_for(self._content_store(actor)))

    async def resolve(self, actor: str, continuity_key: str) -> Optional[str]:
        """The intent_id this actor already holds for this key, or None."""
        await self._ready()
        row = await self.db.execute_query(
            "SELECT intent_id FROM unified.scoped_intents "
            "WHERE scope_actor = $1 AND continuity_key = $2",
            (actor, continuity_key), fetch_one=True, store=self._content_store(actor))
        return row["intent_id"] if row else None

    _INSERT_SHAPE = ("INSERT INTO unified.intents "
                     "(intent_id, parent_intent_id, origin_kind, shape, outcome, "
                     " status, version) "
                     "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)")
    _INSERT_CONTENT = ("INSERT INTO unified.scoped_intents "
                       "(scope_actor, intent_id, continuity_key, content, history) "
                       "VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)")

    async def create(self, intent: Intent) -> Intent:
        """Write both rows, or neither. The shape row is substrate-wide, the
        content row is the actor's.

        One transaction when both rows are in one database (development, or the
        substrate's own intent). A person's content row in staging or production
        is in another database, so the shape row is written first and removed
        again if the content row cannot be; the content row's failure is raised
        as it was (a concurrent former winning the key stays a UniqueViolation)."""
        await self._ready()
        shape = (intent.intent_id, intent.parent_intent_id, intent.origin_kind,
                 json.dumps(intent.shape),
                 json.dumps(intent.outcome) if intent.outcome is not None else None,
                 intent.status, intent.version)
        content = (intent.actor, intent.intent_id, intent.continuity_key,
                   json.dumps(intent.content), json.dumps(intent.history))
        if self._one_database(intent.actor):
            async with self.db.get_connection(store=SHAPE_STORE) as conn:
                async with conn.transaction():
                    await conn.execute(self._INSERT_SHAPE, *shape)
                    await conn.execute(self._INSERT_CONTENT, *content)
        else:
            await self.db.execute_query(self._INSERT_SHAPE, shape, commit=True)
            try:
                await self.db.execute_query(self._INSERT_CONTENT, content, commit=True,
                                            store=self._content_store(intent.actor))
            except BaseException:
                await self.db.execute_query(
                    "DELETE FROM unified.intents WHERE intent_id = $1",
                    (intent.intent_id,), commit=True)
                raise
        loaded = await self.load_full(intent.intent_id, intent.actor)
        if loaded is None:                       # never silently lose a write
            raise RuntimeError(
                f"intent {intent.intent_id} vanished immediately after create")
        return loaded

    _UPDATE_SHAPE = ("UPDATE unified.intents SET shape = $2::jsonb, "
                     "outcome = $3::jsonb, status = $4, version = $5, "
                     "updated_at = now() WHERE intent_id = $1")
    _UPDATE_CONTENT = ("UPDATE unified.scoped_intents SET content = $3::jsonb, "
                       "history = $4::jsonb, updated_at = now() "
                       "WHERE scope_actor = $1 AND intent_id = $2")

    async def update(self, intent: Intent) -> Intent:
        """Rewrite the live node across both tables, both or neither. Version and
        timestamps are advanced by the caller (the authority).

        One transaction when both rows are in one database. Otherwise the shape
        row as it stood is read first, the shape is rewritten, and if the content
        row cannot be, the shape is put back as it was before the failure is raised."""
        await self._ready()
        shape = (intent.intent_id, json.dumps(intent.shape),
                 json.dumps(intent.outcome) if intent.outcome is not None else None,
                 intent.status, intent.version)
        content = (intent.actor, intent.intent_id, json.dumps(intent.content),
                   json.dumps(intent.history))
        if self._one_database(intent.actor):
            async with self.db.get_connection(store=SHAPE_STORE) as conn:
                async with conn.transaction():
                    await conn.execute(self._UPDATE_SHAPE, *shape)
                    await conn.execute(self._UPDATE_CONTENT, *content)
        else:
            before = await self.db.execute_query(
                "SELECT shape, outcome, status, version, updated_at FROM unified.intents "
                "WHERE intent_id = $1", (intent.intent_id,), fetch_one=True)
            await self.db.execute_query(self._UPDATE_SHAPE, shape, commit=True)
            try:
                await self.db.execute_query(self._UPDATE_CONTENT, content, commit=True,
                                            store=self._content_store(intent.actor))
            except BaseException:
                if before is not None:
                    await self.db.execute_query(
                        "UPDATE unified.intents SET shape = $2::jsonb, outcome = $3::jsonb, "
                        "status = $4, version = $5, updated_at = $6 WHERE intent_id = $1",
                        (intent.intent_id, json.dumps(_blob(before["shape"]) or {}),
                         json.dumps(_blob(before["outcome"])) if before["outcome"] is not None else None,
                         before["status"], before["version"], before["updated_at"]),
                        commit=True)
                raise
        loaded = await self.load_full(intent.intent_id, intent.actor)
        if loaded is None:
            raise RuntimeError(
                f"intent {intent.intent_id} vanished immediately after update")
        return loaded

    async def set_outcome(self, intent_id: str, outcome: Dict[str, Any],
                          status: str) -> None:
        """Attach the outcome to the shape row (substrate-wide) and set status."""
        await self._ready()
        await self.db.execute_query(
            "UPDATE unified.intents SET outcome = $2::jsonb, status = $3, "
            "updated_at = now() WHERE intent_id = $1",
            (intent_id, json.dumps(outcome), status), commit=True)

    async def load_full(self, intent_id: str, actor: str) -> Optional[Intent]:
        """Shape + this actor's content. None if the actor does not own it."""
        await self._ready()
        # Two reads, not a join: the actor's content row may be in another database
        # than the shape row. Both must exist, as the join required.
        shape = await self.db.execute_query(
            "SELECT intent_id, parent_intent_id, origin_kind, shape, "
            "       outcome, status, version, created_at, updated_at "
            "FROM unified.intents WHERE intent_id = $1",
            (intent_id,), fetch_one=True)
        if not shape:
            return None
        content = await self.db.execute_query(
            "SELECT continuity_key, content, history FROM unified.scoped_intents "
            "WHERE intent_id = $1 AND scope_actor = $2",
            (intent_id, actor), fetch_one=True, store=self._content_store(actor))
        if not content:
            return None
        row = {**shape, **content}
        return Intent(
            intent_id=row["intent_id"], origin_kind=row["origin_kind"], actor=actor,
            continuity_key=row["continuity_key"],
            parent_intent_id=row["parent_intent_id"],
            shape=_blob(row["shape"]) or {}, content=_blob(row["content"]) or {},
            history=_blob(row["history"]) or [], outcome=_blob(row["outcome"]),
            status=row["status"], version=row["version"],
            created_at=row["created_at"], updated_at=row["updated_at"])

    async def load_shape(self, intent_id: str) -> Optional[Intent]:
        """The substrate-wide view: shape and links only, no actor, no content."""
        await self._ready()
        row = await self.db.execute_query(
            "SELECT intent_id, parent_intent_id, origin_kind, shape, outcome, "
            "       status, version, created_at, updated_at "
            "FROM unified.intents WHERE intent_id = $1",
            (intent_id,), fetch_one=True)
        if not row:
            return None
        return Intent(
            intent_id=row["intent_id"], origin_kind=row["origin_kind"], actor="",
            continuity_key="", parent_intent_id=row["parent_intent_id"],
            shape=_blob(row["shape"]) or {}, content={}, history=[],
            outcome=_blob(row["outcome"]), status=row["status"],
            version=row["version"], created_at=row["created_at"],
            updated_at=row["updated_at"])

    async def standing(self, stale_after_hours: int = 24) -> Dict[str, Any]:
        """WHAT THE SUBSTRATE IS PURSUING RIGHT NOW, substrate-wide.

        Actor-free by construction — only the shape column is read, never
        `scoped_intents`. A reader asking this question is asking about the
        substrate as a whole, and whose request any single goal was is none of
        its business.

        This is the read a per-act view cannot give. An intent is a standing
        thing with a lifecycle and a parent; a gate that fetches one by id and
        asks "is this act its operator" sees a permit. What governance needs is
        the SET: how many goals are live, how many have a proved route, how many
        concluded without anyone recording what happened, and how many have sat
        untouched long enough that nothing is really pursuing them.
        """
        await self._ready()
        rows = await self.db.execute_query(
            """
            SELECT status,
                   count(*)                                        AS n,
                   count(*) FILTER (WHERE shape->>'proved' = 'true') AS proved,
                   count(*) FILTER (WHERE outcome IS NOT NULL)     AS reconciled,
                   count(*) FILTER (WHERE parent_intent_id IS NOT NULL) AS child,
                   count(*) FILTER (WHERE updated_at < now()
                                    - make_interval(hours => $1))  AS stale,
                   -- WHICH INTENTS CAN EVER BE CLOSED AGAINST THE WORLD.
                   -- Reconciliation asks whether the conditions an intent named
                   -- now hold. An intent that names none — a question engaged
                   -- with, rather than a state to bring about — has nothing to
                   -- check, so it can never conclude that way. Counting it in a
                   -- conclusion rate makes the rate describe a population that
                   -- was never eligible.
                   count(*) FILTER (
                       WHERE jsonb_typeof(shape->'goal_conditions') = 'array'
                         AND jsonb_array_length(shape->'goal_conditions') > 0
                   )                                               AS concludable
            FROM unified.intents
            GROUP BY status
            """,
            (int(stale_after_hours),))
        by_status: Dict[str, Dict[str, int]] = {}
        for row in rows or []:
            by_status[str(row["status"])] = {
                "count": int(row["n"]), "proved": int(row["proved"]),
                "reconciled": int(row["reconciled"]), "child": int(row["child"]),
                "stale": int(row["stale"]),
                "concludable": int(row["concludable"])}
        live = {s: b for s, b in by_status.items() if s in LIVE}
        concluded = {s: b for s, b in by_status.items() if s in CONCLUDED}
        return {
            "by_status": by_status,
            "live": sum(b["count"] for b in live.values()),
            "live_proved": sum(b["proved"] for b in live.values()),
            "live_stale": sum(b["stale"] for b in live.values()),
            "concluded": sum(b["count"] for b in concluded.values()),
            "concluded_reconciled": sum(b["reconciled"] for b in concluded.values()),
            "total": sum(b["count"] for b in by_status.values()),
            "stale_after_hours": int(stale_after_hours),
            #: Intents that NAME A WORLD STATE, and so could be closed against
            #: it. The rest are engagements with a question: real intents with a
            #: real lifecycle, but nothing reconciliation can check.
            "concludable": sum(b["concludable"] for b in by_status.values()),
            "concludable_live": sum(b["concludable"] for b in live.values()),
            "concludable_concluded": sum(b["concludable"] for b in concluded.values()),
        }

    async def forget_dangling(self, actor: str, continuity_key: str) -> int:
        """Drop a continuity row whose shape row no longer exists.

        Only ever called after `load_full` has already reported the shape gone,
        and scoped to the one (actor, key) that failed — it cannot remove a row
        that still points at something. Returns rows removed.
        """
        await self._ready()
        store = self._content_store(actor)
        rows = await self.db.execute_query(
            "SELECT intent_id FROM unified.scoped_intents "
            "WHERE scope_actor = $1 AND continuity_key = $2",
            (actor, continuity_key), fetch_all=True, store=store) or []
        ids = [r["intent_id"] for r in rows]
        if not ids:
            return 0
        present = {r["intent_id"] for r in await self.db.execute_query(
            "SELECT intent_id FROM unified.intents WHERE intent_id = ANY($1::text[])",
            (ids,), fetch_all=True) or []}
        gone = [i for i in ids if i not in present]
        if not gone:
            return 0
        row = await self.db.execute_query(
            "WITH gone AS ("
            "  DELETE FROM unified.scoped_intents"
            "   WHERE scope_actor = $1 AND continuity_key = $2 AND intent_id = ANY($3::text[])"
            "  RETURNING 1) SELECT count(*) AS n FROM gone",
            (actor, continuity_key, gone), fetch_one=True, store=store)
        return int(row["n"]) if row else 0

    async def forget_actor(self, actor: str) -> int:
        """Profile deletion: drop this actor's content and continuity index. The
        shape rows remain, now unlinkable to the actor. Returns rows removed."""
        await self._ready()
        row = await self.db.execute_query(
            "WITH gone AS (DELETE FROM unified.scoped_intents "
            "WHERE scope_actor = $1 RETURNING 1) SELECT count(*) AS n FROM gone",
            (actor,), fetch_one=True, store=self._content_store(actor))
        return int(row["n"]) if row else 0


class IntentAuthority:
    """The reasoning authority's ownership of intent: form, refresh, get,
    reconcile. Reasoning calls `form` when it engages with something and `refresh`
    as it returns to it; `reconcile` attaches the outcome once the act completes.
    """

    def __init__(self, store: Optional[IntentStore] = None) -> None:
        self.store = store or IntentStore()

    async def form(self, origin_kind: str, actor: str, continuity_key: str, *,
                   shape: Optional[Dict[str, Any]] = None,
                   content: Optional[Dict[str, Any]] = None,
                   parent_intent_id: Optional[str] = None) -> Intent:
        """Find-or-create the intent for (actor, continuity_key). A first
        engagement creates it; a return refreshes it. The caller chooses the key,
        which is what makes a goal-in-a-thread its own intent rather than the
        thread's (it keys on `goal:<id>`, not `thread:<id>`)."""
        existing_id = await self.store.resolve(actor, continuity_key)
        if existing_id is not None:
            try:
                return await self.refresh(existing_id, actor, shape=shape,
                                          content=content, returning=True)
            except KeyError:
                # A CONTINUITY ROW POINTING AT A SHAPE THAT IS GONE.
                #
                # `resolve` reads `scoped_intents`; `refresh` needs the matching
                # `intents` row. If the shape row was removed and the content row
                # survived, every future engagement on that key raised and the
                # caller formed NO INTENT AT ALL — reasoning then produced acts
                # nothing could explain, which Law 2 replans.
                #
                # Measured: two such rows existed, both `question:` keys. They
                # were unreachable while the substrate's actor was spelled two
                # different ways and surfaced the moment that was unified.
                #
                # The dangling pointer is dropped and the pursuit is opened
                # fresh. Nothing is lost: what it pointed at no longer exists.
                logger.warning(
                    "intent %s is named by %s's continuity %r but its shape row "
                    "is gone; forming a new intent for that pursuit",
                    existing_id, actor, continuity_key)
                await self.store.forget_dangling(actor, continuity_key)
        intent = Intent(
            intent_id=uuid.uuid4().hex, origin_kind=origin_kind, actor=actor,
            continuity_key=continuity_key, parent_intent_id=parent_intent_id,
            shape=dict(shape or {}), content=dict(content or {}),
            history=[], status="forming", version=1)
        try:
            return await self.store.create(intent)
        except asyncpg.UniqueViolationError:
            # A concurrent former won the key; take theirs and refresh onto it.
            existing_id = await self.store.resolve(actor, continuity_key)
            if existing_id is None:
                raise
            return await self.refresh(existing_id, actor, shape=shape,
                                      content=content, returning=True)

    async def refresh(self, intent_id: str, actor: str, *,
                      shape: Optional[Dict[str, Any]] = None,
                      content: Optional[Dict[str, Any]] = None,
                      returning: bool = False) -> Intent:
        """Update the live node with firmer understanding, keeping identity and
        appending the previous state to history. Refresh is not rebuild.

        `returning` is `form` finding a pursuit it already holds — the substrate
        ENGAGING with it again, which is different from reasoning settling what
        it just did. A return to a pursuit whose last attempt ENDED reopens it:
        concluded, or stopped by the constitution (halted, replanned,
        redirected) — a new route after a REPLAN is exactly such a return.

        MEASURED BEFORE THIS: a goal whose first route stopped was reconciled
        `abandoned`; the planner then proved a second route and recorded it
        through `form` — same intent, version advanced, the new rule on its
        shape — and the status stayed `abandoned` with the FIRST route's outcome.
        The substrate was pursuing a goal its own record said it had given up.
        Nothing minded while no reader asked whether a pursuit was still live;
        the task gate now asks exactly that, and any step of the second route
        reaching it would have been refused for the first route's end.

        The earlier conclusion is not discarded. It is kept on the SHAPE, which
        is substrate-wide, so the lesson of the attempt that ended survives the
        actor's deletion exactly as a reconciled outcome does; and the history
        entry records the full previous state, status and outcome included.
        """
        current = await self.store.load_full(intent_id, actor)
        if current is None:
            raise KeyError(f"no intent {intent_id} for actor {actor!r} to refresh")
        current.history.append({
            "at": datetime.now().isoformat(),
            "version": current.version,
            "status": current.status,
            "outcome": current.outcome,
            "shape": dict(current.shape),
            "content": dict(current.content),
        })
        if returning and current.status not in ("forming", "active"):
            earlier = list(current.shape.get("earlier_attempts") or [])
            earlier.append({"status": current.status, "outcome": current.outcome,
                            "version": current.version})
            current.shape["earlier_attempts"] = earlier
            current.status = "active"
            current.outcome = None
        if shape:
            current.shape.update(shape)
        if content:
            current.content.update(content)
        current.version += 1
        if current.status == "forming":
            current.status = "active"
        return await self.store.update(current)

    async def get(self, actor: str, continuity_key: str) -> Optional[Intent]:
        """The intent this actor holds for this key, full view, or None."""
        intent_id = await self.store.resolve(actor, continuity_key)
        if intent_id is None:
            return None
        return await self.store.load_full(intent_id, actor)

    async def get_by_id(self, intent_id: str,
                        actor: Optional[str] = None) -> Optional[Intent]:
        """With an actor, the full view (content included) if they own it; without,
        the substrate-wide shape view."""
        if actor is not None:
            return await self.store.load_full(intent_id, actor)
        return await self.store.load_shape(intent_id)

    async def root_of(self, intent_id: str) -> str:
        """The pursuit an intent is part of: the intent walked up through what
        raised it, to the one nothing raised."""
        current, seen = str(intent_id), set()
        while current not in seen:
            seen.add(current)
            held = await self.get_by_id(current)
            parent = getattr(held, "parent_intent_id", None) if held is not None else None
            if not parent:
                return current
            current = str(parent)
        return current

    async def reconcile(self, intent_id: str, outcome: Dict[str, Any], *,
                        status: str = "fulfilled") -> None:
        """The act completed: attach what actually happened, so learning and
        integrity can read meant-vs-happened. The outcome is substrate-wide."""
        await self.store.set_outcome(intent_id, outcome, status)

    async def standing(self, stale_after_hours: int = 24) -> Dict[str, Any]:
        """What the substrate is pursuing right now, substrate-wide and actor-free.

        The constitution reads this to answer Law 4 about the SYSTEM rather than
        about one act: a goal set is a standing thing, and whether the substrate
        is pursuing goals it has no proved route to — or has quietly stopped
        pursuing goals nobody closed — is a property of the set, not of any
        member of it."""
        return await self.store.standing(stale_after_hours)

    async def forget_actor(self, actor: str) -> int:
        """Profile deletion. Content and continuity go; the anonymous shape stays."""
        return await self.store.forget_actor(actor)


_INTENT_AUTHORITY: Optional[IntentAuthority] = None


def get_intent_authority() -> IntentAuthority:
    """The one intent authority (process singleton), owned by reasoning."""
    global _INTENT_AUTHORITY
    if _INTENT_AUTHORITY is None:
        _INTENT_AUTHORITY = IntentAuthority()
    return _INTENT_AUTHORITY


# ── which intent the substrate is acting under, right now ────────────────────
#
# THE GATE CANNOT BE HANDED AN INTENT. `Constitution.judge` takes an intent ID
# and fetches what was recorded, because an account of why the substrate is
# acting that travels with the act is an account the act can forge. But the tool
# gate sits at `execute_tool(tool_name, parameters)`, which has nowhere to put an
# id -- and threading one through every tool signature would put the claim back
# in the caller's hands anyway.
#
# So the acting intent is bound to the async CONTEXT: the coordinator runs tasks
# concurrently, and a module global would let one task's intent authorise
# another task's act. A ContextVar gives every asyncio task its
# own copy automatically.
#
# What travels is only the ID. The constitution still reads the intent from this
# authority, so binding a fabricated id names nothing and judges as no intent at
# all -- which is what an unrecorded claim should be worth.
_acting_intent: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "torin_acting_intent", default=None)


def set_acting_intent(intent_id: Optional[str]):
    """Bind the intent this act is being done under. Returns the reset token."""
    return _acting_intent.set(str(intent_id) if intent_id else None)


#: WHOSE WORK THIS IS — bound by the acting paths beside the intent, for the same
#: reason and with the same mechanism.
#:
#: The constitution deliberately does not read WHO ASKED (`_resolve_intent` takes
#: the actor-free shape view). This is a different question: whose THINGS the act
#: is about to touch. Without it the laws applied identically to the substrate's
#: own scratch file and to a customer's records — and a rule that is right for the
#: substrate's own credential ("it can be re-issued, so destroy it") became the
#: substrate deciding on a user's behalf that re-issuing THEIR key was an
#: acceptable cost to bear.
#:
#: Read through `is_substrate_actor`, so what reaches the laws is a regime and
#: never an identity.
_acting_actor: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "torin_acting_actor", default=None)


def set_acting_actor(actor: Optional[str]):
    """Bind whose work the current act belongs to. Returns the reset token."""
    return _acting_actor.set(str(actor) if actor else None)


def get_acting_actor() -> Optional[str]:
    """Whose work the current act belongs to, or None when unbound."""
    return _acting_actor.get()


def reset_acting_actor(token) -> None:
    """Release the binding set by `set_acting_actor`."""
    _acting_actor.reset(token)



#: WHICH TASK the current act is a step of, as `(task id, description)`. Bound
#: beside the intent and the actor, and for the same reason: the tool registry is
#: where every tool run passes, whoever calls it, and a run is recorded there
#: once -- attributed to the task it served, or to none when the caller had no
#: task (a conversation looking something up).
_acting_task: "contextvars.ContextVar[Optional[Tuple[str, str]]]" = contextvars.ContextVar(
    "torin_acting_task", default=None)


def set_acting_task(task_id: Optional[str], description: str = ""):
    """Bind the task the current act serves. Returns the reset token."""
    return _acting_task.set((str(task_id), str(description or "")) if task_id else None)


def get_acting_task() -> Optional[Tuple[str, str]]:
    """`(task id, description)` of the task the current act serves, or None."""
    return _acting_task.get()


def reset_acting_task(token) -> None:
    """Release the binding set by `set_acting_task`."""
    _acting_task.reset(token)


def get_acting_intent() -> Optional[str]:
    """The intent id bound to the current async context, or None."""
    return _acting_intent.get()


#: The REFUSAL an act is carrying out. When the constitution redirects, it names
#: a permitted form of the same act; whatever performs that form binds the id of
#: the judgement here, so the gate can tell "the constitution's own alternative"
#: from "some other act arriving unannounced". Same ContextVar reasoning as the
#: intent above: concurrent tasks must not inherit each other's authorisation,
#: and only the ID travels — the constitution holds the judgement itself.
_carrying_out: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "torin_carrying_out_judgment", default=None)


def set_carrying_out(judgment_id: Optional[str]):
    """Bind the redirect this act is carrying out. Returns the reset token."""
    return _carrying_out.set(str(judgment_id) if judgment_id else None)


def get_carrying_out() -> Optional[str]:
    """The judgement id whose alternative this act is, or None."""
    return _carrying_out.get()


def reset_carrying_out(token) -> None:
    try:
        _carrying_out.reset(token)
    except Exception:
        pass


def reset_acting_intent(token) -> None:
    try:
        _acting_intent.reset(token)
    except (ValueError, LookupError):
        # A token from another context is not this context's to reset; losing the
        # reset is harmless (the context ends), silently ignoring a real error is
        # not, so only these two are caught.
        pass
