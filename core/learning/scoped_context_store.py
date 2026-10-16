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
  * `unified.scoped_beliefs` — how strongly the claim is held, in LOG-ODDS,
    moved with the IDENTICAL kernel the shared graph uses (`evidence_step`, no
    cap), the posterior read from it, so a scoped belief is a real revisable
    belief, not a lesser record.

Nothing here reaches the world: what is about the world is judged at the one door
(docs/research/SEPARATION_MAP.md §11).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.database import LyricUnifiedDatabase
from core.reasoning.bayesian_uncertainty import (evidence_step, log_odds_of,
                                                 probability_of)

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
        self.db = LyricUnifiedDatabase()
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
        # WHICH OF THE PERSON'S CONTEXTS each row came through: personal, or work and the organization's
        # (`Origin.context`, docs/research/SEPARATION_MAP.md §11.3).
        for table in ("scoped_beliefs", "scoped_concept_relations"):
            for column in ("context TEXT NOT NULL DEFAULT 'personal'", "organization TEXT"):
                await self.db.execute_query(
                    f"ALTER TABLE unified.{table} ADD COLUMN IF NOT EXISTS {column}", commit=True)
        # HOW STRONGLY IT IS HELD, in log-odds, with no cap; the posterior is read from it.
        await self.db.execute_query(
            "ALTER TABLE unified.scoped_beliefs ADD COLUMN IF NOT EXISTS log_odds DOUBLE PRECISION", commit=True)
        self._schema_ready = True

    async def observe(self, actor: str, subject: str, relation: str,
                      obj: Optional[str], *, claim: str,
                      positive: bool = True,
                      quality: float = 0.9, domain: str = "conversation",
                      surface: Optional[str] = None,
                      source: str = "taught", context: str = "personal",
                      organization: Optional[str] = None) -> Dict[str, Any]:
        """Record one telling of `subject relation obj` within `actor`'s context
        (`context`: personal, or work and the `organization`'s):
        the scoped EDGE (skipped for a bare node with no object — nothing to
        chain) and the scoped BELIEF on the claim. The belief moves with the same
        kernel the shared graph uses. Returns the scoped state.

        The parts are the EDGE and must already be the ingress's canonical terms
        (`shape_proposition`) — the overlay matches them against concept names.
        `claim` is the BELIEF's proposition, spelled as the shared side spells it
        so the promotion gate can match the two."""
        if not actor:
            raise ValueError("a scoped fact must name the actor it belongs to")
        if not claim:
            raise ValueError("a scoped fact must name the claim its belief is in")
        await self._ready()
        surface = surface or claim

        # EDGE: only when there is an object to point at (a real relation to
        # chain). A bare node ("X is") makes no edge, exactly as on the shared side.
        if obj:
            from core.agents.memory_agent import memory_agent
            await memory_agent().hold_scoped_relation(
                actor=actor, subject=str(subject), relation=str(relation), obj=str(obj),
                polarity="positive" if positive else "negative", surface=surface,
                domain=domain, source=source, context=context, organization=organization)

        # BELIEF: find-or-create by (actor, claim_key), move the posterior.
        belief = await self._observe_belief(actor, claim, domain,
                                            supports=positive, quality=quality,
                                            source=source, surface=surface,
                                            context=context, organization=organization)
        return {"scope_actor": actor, "claim": claim,
                "claim_key": belief["claim_key"], "domain": domain,
                "posterior": belief["posterior"],
                "update_count": belief["update_count"],
                "edge": bool(obj), "created": belief["created"]}

    async def observe_claim(self, actor: str, claim: str, *, domain: str,
                            supports: bool = True, quality: float = 0.9,
                            source: str = "taught",
                            surface: Optional[str] = None, context: str = "personal",
                            organization: Optional[str] = None) -> Dict[str, Any]:
        """Move `actor`'s scoped BELIEF in `claim` with no edge — for a claim
        that asserts no relation of its own, such as a told conditional, whose
        clauses are hypotheses and must not be walked as facts."""
        if not actor:
            raise ValueError("a scoped claim must name the actor it belongs to")
        await self._ready()
        return await self._observe_belief(actor, claim, domain, supports=supports,
                                          quality=quality, source=source,
                                          surface=surface or claim, context=context,
                                          organization=organization)

    async def _observe_belief(self, actor: str, claim: str, domain: str, *,
                              supports: bool, quality: float, source: str,
                              surface: str, context: str,
                              organization: Optional[str]) -> Dict[str, Any]:
        key = scoped_claim_key(claim)
        from core.agents.memory_agent import memory_agent
        # Held in working memory, it moves from there (a conversation not remembered told it before).
        row = next((r for r in memory_agent().working_beliefs([actor]) if r["claim_key"] == key), None) or \
            await self.db.execute_query(
                "SELECT posterior, log_odds, update_count FROM unified.scoped_beliefs "
                "WHERE scope_actor = $1 AND claim_key = $2",
                (actor, key), fetch_one=True)
        if row is None:
            # A new claim starts even and its first observation counts once
            # (the shared store's rule, `BayesianUncertaintySystem.observe_claim`).
            # The prior used to be the observation's own quality, with that same
            # observation then applied again.
            prior, held, update_count = 0.5, 0.0, 1
        else:
            prior = float(row["posterior"])
            held = float(row["log_odds"]) if row["log_odds"] is not None else log_odds_of(prior)
            update_count = int(row["update_count"]) + 1
        held += evidence_step(quality, supports)
        posterior = probability_of(held)
        await memory_agent().hold_scoped_belief(
            actor=actor, claim_key=key, claim=str(claim), domain=domain, prior=prior,
            posterior=posterior, log_odds=held, supports=supports, update_count=update_count,
            surface=surface, source=source, context=context, organization=organization)
        return {"claim_key": key, "posterior": posterior,
                "update_count": update_count, "created": row is None}

    @staticmethod
    async def _composed(actor: str) -> List[str]:
        """The contexts in `actor`'s Shared World Context: their own, and the Work Context of each organization they
        are authorized for (`MemoryAgent.shared_world_context`). Lyric's own knowledge is not kept here."""
        from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR
        from core.agents.memory_agent import memory_agent
        return [owner for owner in await memory_agent().shared_world_context(actor) if owner != SUBSTRATE_ACTOR]

    async def edges_for_actor(self, actor: str, roots: List[str]
                              ) -> List[Dict[str, Any]]:
        """The scoped edges in this actor's Shared World Context (their own, and
        their organizations' Work Context) whose subject is in `roots` — the rows
        the graph overlay unions into a walk done ON THIS ACTOR'S BEHALF. Shape
        matches the shared graph's `_SUBGRAPH_SQL` (subj/rel/obj/pol)."""
        if not actor or not roots:
            return []
        await self._ready()
        rows = await self.db.execute_query(
            "SELECT subj, rel, obj, polarity AS pol "
            "FROM unified.scoped_concept_relations "
            "WHERE scope_actor = ANY($1::text[]) AND subj = ANY($2)",
            (await self._composed(actor), [str(r) for r in roots]), fetch_all=True)
        from core.agents.memory_agent import memory_agent
        wanted = {str(r) for r in roots}
        working = [{k: r[k] for k in ("subj", "rel", "obj", "pol")}
                   for r in memory_agent().working_relations(await self._composed(actor)) if r["subj"] in wanted]
        return working + [dict(r) for r in (rows or [])]

    async def edges_naming(self, actor: str, names: List[str]
                           ) -> List[Dict[str, Any]]:
        """This actor's scoped edges that NAME any of `names`, as subject or as
        object, with the surface they were told in -- what a conversation needs
        to know that the speaker has told it about a thing, including a thing
        they only ever named as what something else is."""
        if not actor or not names:
            return []
        await self._ready()
        rows = await self.db.execute_query(
            "SELECT subj, rel, obj, polarity AS pol, surface "
            "FROM unified.scoped_concept_relations "
            "WHERE scope_actor = ANY($1::text[]) AND (subj = ANY($2) OR obj = ANY($2))",
            (await self._composed(actor), [str(n) for n in names]), fetch_all=True)
        from core.agents.memory_agent import memory_agent
        wanted = {str(n) for n in names}
        working = [{k: r[k] for k in ("subj", "rel", "obj", "pol", "surface")}
                   for r in memory_agent().working_relations(await self._composed(actor))
                   if r["subj"] in wanted or r["obj"] in wanted]
        return working + [dict(r) for r in (rows or [])]

    async def particulars_of(self, actor: str, kind: str) -> List[str]:
        """The particular things of a kind this actor's context holds (`printer_1` for `printer`), the one last
        spoken of first: which "the printer" may be (docs/research/SEPARATION_MAP.md §11.10)."""
        if not actor or not kind:
            return []
        await self._ready()
        rows = await self.db.execute_query(
            "SELECT subj, MAX(last_updated) AS at FROM unified.scoped_concept_relations "
            "WHERE scope_actor = ANY($1::text[]) AND rel = 'instance of' AND obj = $2 AND polarity = 'positive' "
            "GROUP BY subj ORDER BY at DESC",
            (await self._composed(actor), str(kind)), fetch_all=True)
        from core.agents.memory_agent import memory_agent
        working = [r["subj"] for r in memory_agent().working_relations(await self._composed(actor))
                   if r["rel"] == "instance of" and r["obj"] == str(kind) and r["pol"] == "positive"]
        return list(dict.fromkeys(working[::-1] + [str(r["subj"]) for r in (rows or [])]))

    async def beliefs_for_actor(self, actor: str, domain: Optional[str] = None,
                                limit: int = 50) -> List[Dict[str, Any]]:
        """This actor's context beliefs, most-recently-moved first. The substrate
        reasoning for this actor may see these; its universal reasoning never does."""
        if not actor:
            return []
        await self._ready()
        owners = await self._composed(actor)
        if domain:
            rows = await self.db.execute_query(
                "SELECT claim, domain, posterior, update_count, scope_actor, context, organization, "
                "last_updated FROM unified.scoped_beliefs "
                "WHERE scope_actor = ANY($1::text[]) AND domain = $2 "
                "ORDER BY last_updated DESC LIMIT $3",
                (owners, domain, limit), fetch_all=True)
        else:
            rows = await self.db.execute_query(
                "SELECT claim, domain, posterior, update_count, scope_actor, context, organization, "
                "last_updated FROM unified.scoped_beliefs "
                "WHERE scope_actor = ANY($1::text[]) ORDER BY last_updated DESC LIMIT $2",
                (owners, limit), fetch_all=True)
        from core.agents.memory_agent import memory_agent
        working = [{k: r[k] for k in ("claim", "domain", "posterior", "update_count", "scope_actor", "context",
                                      "organization")}
                   for r in memory_agent().working_beliefs(owners) if not domain or r["domain"] == domain]
        return (working + [dict(r) for r in (rows or [])])[:limit]

    async def belief(self, actor: str, claim: str) -> Optional[Dict[str, Any]]:
        """This actor's belief in one claim (its posterior and how often it was
        moved), or None when none is held in their Shared World Context: their
        own first, then an organization's they are authorized for. Read only on
        their behalf."""
        if not actor:
            return None
        await self._ready()
        from core.agents.memory_agent import memory_agent
        key = scoped_claim_key(claim)
        working = next((r for r in memory_agent().working_beliefs(await self._composed(actor))
                        if r["claim_key"] == key), None)
        if working is not None:
            return {k: working[k] for k in ("claim", "posterior", "update_count", "scope_actor")}
        row = await self.db.execute_query(
            "SELECT claim, posterior, update_count, scope_actor FROM unified.scoped_beliefs "
            "WHERE scope_actor = ANY($1::text[]) AND claim_key = $2 "
            "ORDER BY (scope_actor = $3) DESC, last_updated DESC LIMIT 1",
            (await self._composed(actor), scoped_claim_key(claim), str(actor)), fetch_one=True)
        return dict(row) if row else None

_SCOPED_CONTEXT_STORE: Optional[ScopedContextStore] = None


def get_scoped_context_store() -> ScopedContextStore:
    """The one actor-scoped context store (process singleton)."""
    global _SCOPED_CONTEXT_STORE
    if _SCOPED_CONTEXT_STORE is None:
        _SCOPED_CONTEXT_STORE = ScopedContextStore()
    return _SCOPED_CONTEXT_STORE
