#!/usr/bin/env python3
"""Actor-scoped CONTEXT layer — the per-user half of the self.

The substrate is one mind. Its general competence — the concept graph the
reasoner walks (`unified.concept_relations`) and the belief posteriors over
claims (`unified.beliefs`) — is identity-free and shared: it is what ships in a
snapshot and what every deployment runs. A thing a *user* tells the substrate is
not world knowledge until it has been independently corroborated; it is that
user's CONTEXT. Folding it into the shared graph/beliefs would (a) let one user
rewrite the one mind everyone shares and (b) leak that user's context into every
other deployment and every other user. Both are disqualifying for the
multi-tenant / air-gapped targets.

So a user-originated fact lands HERE instead, partitioned by `scope_actor` (the
same actor key the memory store isolates on — see
`core.agents.autonomous.shared_types.actor_for`). This layer mirrors the shared
mind in the two representations that matter for reasoning:

  * `unified.scoped_concept_relations` — the EDGE (subject -rel-> object), so the
    reasoner can CHAIN over a user's context when it is acting FOR that user
    (the overlay read in `concept_graph_reasoning`), exactly as it chains the
    shared graph. Never read on anyone else's behalf.
  * `unified.scoped_beliefs` — the POSTERIOR (how strongly the claim is held),
    moved with the IDENTICAL kernel the shared graph uses
    (`posterior_from_evidence`), so a scoped belief is a real revisable belief,
    not a lesser record.

A scoped fact PROMOTES into the shared mind only on INDEPENDENT corroboration (a
different actor holds the same claim, or the substrate itself already holds it).
That promotion — owned by the learning authority, which holds both layers — is
the single bridge from context to the one mind.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.database import TorinUnifiedDatabase
from core.reasoning.bayesian_uncertainty import (posterior_from_evidence,
                                                 clamp_posterior)

logger = logging.getLogger(__name__)


def scoped_claim_key(claim: Any) -> str:
    """Normalized key a claim is matched by WITHIN a scope — identical
    normalization to the universal graph's `_claim_key`, so the same surface
    claim lines up across the two stores (which is what the promotion gate and
    the corroboration check rely on)."""
    return " ".join(str(claim).strip().lower().split())


class ScopedContextStore:
    """Per-actor context: scoped edges + scoped beliefs. One owner, two tables."""

    def __init__(self) -> None:
        self.db = TorinUnifiedDatabase()
        self._schema_ready = False

    async def _ready(self) -> None:
        """Ensure the pool is up and both tables exist. No silent degrade: if the
        database is not initialized we initialize it, we do not drop the write."""
        if not self.db.initialized:
            await self.db.initialize()
        if self._schema_ready:
            return
        await self.db.execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.scoped_beliefs (
                scope_actor   TEXT NOT NULL,
                claim_key     TEXT NOT NULL,
                claim         TEXT NOT NULL,
                domain        TEXT NOT NULL DEFAULT 'conversation',
                prior         DOUBLE PRECISION NOT NULL,
                posterior     DOUBLE PRECISION NOT NULL,
                supports      BOOLEAN NOT NULL DEFAULT TRUE,
                update_count  INTEGER NOT NULL DEFAULT 1,
                surface       TEXT,
                source        TEXT NOT NULL DEFAULT 'taught',
                promoted      BOOLEAN NOT NULL DEFAULT FALSE,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_updated  TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (scope_actor, claim_key)
            )
            """,
            commit=True)
        await self.db.execute_query(
            "CREATE INDEX IF NOT EXISTS scoped_beliefs_claim_idx "
            "ON unified.scoped_beliefs (claim_key)",
            commit=True)
        await self.db.execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.scoped_concept_relations (
                scope_actor   TEXT NOT NULL,
                subj          TEXT NOT NULL,
                rel           TEXT NOT NULL,
                obj           TEXT NOT NULL,
                polarity      TEXT NOT NULL DEFAULT 'positive',
                surface       TEXT,
                domain        TEXT NOT NULL DEFAULT 'conversation',
                source        TEXT NOT NULL DEFAULT 'taught',
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_updated  TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (scope_actor, subj, rel, obj)
            )
            """,
            commit=True)
        # The overlay read walks edges forward from a frontier of subjects.
        await self.db.execute_query(
            "CREATE INDEX IF NOT EXISTS scoped_relations_subj_idx "
            "ON unified.scoped_concept_relations (scope_actor, subj)",
            commit=True)
        self._schema_ready = True

    async def observe(self, actor: str, subject: str, relation: str,
                      obj: Optional[str], *, positive: bool = True,
                      quality: float = 0.9, domain: str = "conversation",
                      surface: Optional[str] = None,
                      source: str = "taught") -> Dict[str, Any]:
        """Record one telling of `subject relation obj` within `actor`'s context:
        the scoped EDGE (skipped for a bare node with no object — nothing to
        chain) and the scoped BELIEF on the claim. The belief moves with the same
        kernel the shared graph uses. Returns the scoped state."""
        if not actor:
            raise ValueError("a scoped fact must name the actor it belongs to")
        await self._ready()
        claim = " ".join(str(p) for p in (subject, relation, obj) if p)
        surface = surface or claim

        # EDGE: only when there is an object to point at (a real relation to
        # chain). A bare node ("X is") makes no edge, exactly as on the shared side.
        if obj:
            await self.db.execute_query(
                """
                INSERT INTO unified.scoped_concept_relations
                    (scope_actor, subj, rel, obj, polarity, surface, domain,
                     source, last_updated)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8, now())
                ON CONFLICT (scope_actor, subj, rel, obj) DO UPDATE SET
                    polarity = EXCLUDED.polarity, surface = EXCLUDED.surface,
                    domain = EXCLUDED.domain, last_updated = now()
                """,
                (actor, str(subject), str(relation), str(obj),
                 "positive" if positive else "negative", surface, domain, source),
                commit=True)

        # BELIEF: find-or-create by (actor, claim_key), move the posterior.
        belief = await self._observe_belief(actor, claim, domain,
                                            supports=positive, quality=quality,
                                            source=source, surface=surface)
        return {"scope_actor": actor, "claim": claim,
                "claim_key": belief["claim_key"], "domain": domain,
                "posterior": belief["posterior"],
                "update_count": belief["update_count"],
                "edge": bool(obj), "created": belief["created"]}

    async def _observe_belief(self, actor: str, claim: str, domain: str, *,
                              supports: bool, quality: float, source: str,
                              surface: str) -> Dict[str, Any]:
        key = scoped_claim_key(claim)
        row = await self.db.execute_query(
            "SELECT posterior, update_count FROM unified.scoped_beliefs "
            "WHERE scope_actor = $1 AND claim_key = $2",
            (actor, key), fetch_one=True)
        if row is None:
            prior = quality if supports else (1.0 - quality)
            posterior, _ = posterior_from_evidence(prior, quality, supports)
            update_count = 1
        else:
            prior = float(row["posterior"])
            posterior, _ = posterior_from_evidence(prior, quality, supports)
            update_count = int(row["update_count"]) + 1
        posterior = clamp_posterior(posterior)
        await self.db.execute_query(
            """
            INSERT INTO unified.scoped_beliefs
                (scope_actor, claim_key, claim, domain, prior, posterior,
                 supports, update_count, surface, source, last_updated)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
            ON CONFLICT (scope_actor, claim_key) DO UPDATE SET
                claim = EXCLUDED.claim, domain = EXCLUDED.domain,
                posterior = EXCLUDED.posterior, supports = EXCLUDED.supports,
                update_count = EXCLUDED.update_count, surface = EXCLUDED.surface,
                source = EXCLUDED.source, last_updated = now()
            """,
            (actor, key, str(claim), domain, prior, posterior, supports,
             update_count, surface, source),
            commit=True)
        return {"claim_key": key, "posterior": posterior,
                "update_count": update_count, "created": row is None}

    async def edges_for_actor(self, actor: str, roots: List[str]
                              ) -> List[Dict[str, Any]]:
        """This actor's POSITIVE scoped edges whose subject is in `roots` — the
        rows the graph overlay unions into a walk done ON THIS ACTOR'S BEHALF.
        Shape matches the shared graph's `_SUBGRAPH_SQL` (subj/rel/obj/pol)."""
        if not actor or not roots:
            return []
        await self._ready()
        rows = await self.db.execute_query(
            "SELECT subj, rel, obj, polarity AS pol "
            "FROM unified.scoped_concept_relations "
            "WHERE scope_actor = $1 AND subj = ANY($2)",
            (actor, [str(r) for r in roots]), fetch_all=True)
        return [dict(r) for r in (rows or [])]

    async def beliefs_for_actor(self, actor: str, domain: Optional[str] = None,
                                limit: int = 50) -> List[Dict[str, Any]]:
        """This actor's context beliefs, most-recently-moved first. The substrate
        reasoning for this actor may see these; its universal reasoning never does."""
        if not actor:
            return []
        await self._ready()
        if domain:
            rows = await self.db.execute_query(
                "SELECT claim, domain, posterior, update_count, promoted, "
                "last_updated FROM unified.scoped_beliefs "
                "WHERE scope_actor = $1 AND domain = $2 "
                "ORDER BY last_updated DESC LIMIT $3",
                (actor, domain, limit), fetch_all=True)
        else:
            rows = await self.db.execute_query(
                "SELECT claim, domain, posterior, update_count, promoted, "
                "last_updated FROM unified.scoped_beliefs "
                "WHERE scope_actor = $1 ORDER BY last_updated DESC LIMIT $2",
                (actor, limit), fetch_all=True)
        return [dict(r) for r in (rows or [])]

    async def independent_holders(self, claim: str, *, exclude_actor: str,
                                  min_posterior: float = 0.5) -> List[str]:
        """The OTHER actors who hold `claim` as believed (posterior ≥ threshold),
        excluding `exclude_actor`. Independent corroboration for the promotion gate:
        a context belief may promote to the shared mind only when a source
        independent of the one that asserted it also holds it."""
        await self._ready()
        key = scoped_claim_key(claim)
        rows = await self.db.execute_query(
            "SELECT DISTINCT scope_actor FROM unified.scoped_beliefs "
            "WHERE claim_key = $1 AND scope_actor <> $2 AND posterior >= $3",
            (key, exclude_actor, min_posterior), fetch_all=True)
        return [r["scope_actor"] for r in (rows or [])]

    async def mark_promoted(self, claim: str) -> None:
        """Flag every scoped copy of `claim` promoted, so a corroborated claim is
        lifted into the shared mind exactly once, not on every re-telling."""
        await self._ready()
        key = scoped_claim_key(claim)
        await self.db.execute_query(
            "UPDATE unified.scoped_beliefs SET promoted = TRUE WHERE claim_key = $1",
            (key,), commit=True)

    async def is_promoted(self, claim: str) -> bool:
        """Whether this claim has already been promoted to the shared mind."""
        await self._ready()
        key = scoped_claim_key(claim)
        row = await self.db.execute_query(
            "SELECT bool_or(promoted) AS promoted FROM unified.scoped_beliefs "
            "WHERE claim_key = $1",
            (key,), fetch_one=True)
        return bool(row and row["promoted"])


_SCOPED_CONTEXT_STORE: Optional[ScopedContextStore] = None


def get_scoped_context_store() -> ScopedContextStore:
    """The one actor-scoped context store (process singleton)."""
    global _SCOPED_CONTEXT_STORE
    if _SCOPED_CONTEXT_STORE is None:
        _SCOPED_CONTEXT_STORE = ScopedContextStore()
    return _SCOPED_CONTEXT_STORE
