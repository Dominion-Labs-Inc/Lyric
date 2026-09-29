#!/usr/bin/env python3
"""RELEASE-01's serving process: one staging or production process, serving the release its settings name.

`--start-only` checks the release and stops: it prints whether this process would serve. Otherwise it starts the
substrate, serves one person, stores a memory of its own, recalls a memory of the release, maintains memory,
and idles for `--idle` seconds, counting every refusal as it happens. Then it tries, on purpose, to learn a fact
of its own and to move a belief, and reports what was refused. The report is the JSON on its last line.

Run by RELEASE-01 with LYRIC_ENVIRONMENT, LYRIC_RELEASE and POSTGRES_DATABASE set.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ALICE = "user:alice:release01"


async def start_only() -> dict:
    from core.database import get_database_manager
    from core.database.releases import ReleaseError
    db = get_database_manager()
    try:
        await db.initialize()
    except ReleaseError as error:
        return {"started": False, "refused": str(error)}
    report = {"started": True, "environment": db.environment, "release": db.release,
              "databases": db.config.databases()}
    await db.close()
    return report


async def serve(mark: str, idle: float) -> dict:
    from core.memory import Origin
    from core.database import get_database_manager
    from core.database.postgres_config import ModelFrozenError, StoreRoutingError
    db = get_database_manager()
    routed = []
    for name in ("_route", "_pool_for"):
        original = getattr(db, name)

        def counted(*args, _original=original, _name=name, **kwargs):
            try:
                return _original(*args, **kwargs)
            except StoreRoutingError as error:
                if not isinstance(error, ModelFrozenError):
                    routed.append(f"{_name}: {error}")
                raise
        setattr(db, name, counted)
    await db.initialize()
    log = io.StringIO()
    out = {"environment": db.environment, "release": db.release}
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        from core.main import get_system
        system = get_system()
        await system.start()
        try:
            await asyncio.sleep(20)
            from core.learning import get_learning_authority
            from core.memory import get_memory_agent
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            from core.reasoning.concept_graph_reasoning import answer_over_graph
            from core.semantics.relation_types import SemanticRelation
            learning = get_learning_authority()
            agent = await get_memory_agent()
            told = await learning.learn_fact("florpane", "isa", "gadget", domain="release_01", quality=0.9,
                                             actor=ALICE)
            _, alice_memory = await agent.store_memory(content=f"Alice's note: the {mark} gauge reads low.",
                                                       origin=Origin.of(ALICE, "RELEASE-01"), tags=["release_01"], importance_score=0.9)
            _, own_memory = await agent.store_memory(
                content=f"The substrate's note while serving: {mark} was asked about today.",
                tags=["release_01"], importance_score=0.9, origin=Origin.own("RELEASE-01"))
            released = await agent.postgres_storage.search_by_content(mark, actor=None, limit=10)
            recalled = [m.memory_id for m in released]
            for memory_id in recalled:
                await agent.postgres_storage.get_memory(memory_id)
            answer = await answer_over_graph(db, "florpane", SemanticRelation.ISA, "gadget", actor=ALICE)
            decayed = await agent.postgres_storage.apply_memory_decay()
            cleaned = await agent.postgres_storage.cleanup_low_importance_memories(
                cutoff_date=__import__("datetime").datetime.now(), importance_threshold=0.0)
            await asyncio.sleep(idle)
            out.update(
                routing_refusals=list(routed), frozen_refusals=list(db.frozen_refusals),
                schema_checks=db.metrics["release_schema_checks"],
                alice_told=getattr(told, "admitted", None), alice_memory=alice_memory, own_memory=own_memory,
                recalled=recalled, alice_answer=str(getattr(answer, "verdict", None)),
                decay_ran=decayed, cleaned=cleaned)

            us = get_uncertainty_system()
            beliefs_before = {k: (b.posterior_probability, b.update_count) for k, b in us.beliefs.items()}
            own = await learning.learn_fact("florpane", "isa", "gizmo", domain="release_01", quality=0.9)
            try:
                us.create_belief("a belief production would form", "release_01")
                belief_refused = None
            except ModelFrozenError as error:
                belief_refused = str(error)
            some = next(iter(us.beliefs), None)
            try:
                if some is not None:
                    us.update_belief(some, {"source": "release_01"}, evidence_supports=True)
                moved_refused = None
            except ModelFrozenError as error:
                moved_refused = str(error)
            beliefs_after = {k: (b.posterior_probability, b.update_count) for k, b in us.beliefs.items()}
            out.update(
                own_learning_admitted=getattr(own, "admitted", None),
                own_learning_refusals=list(getattr(own, "refusals", []) or []),
                belief_refused=belief_refused, belief_move_refused=moved_refused,
                beliefs_unchanged=beliefs_before == beliefs_after, beliefs_held=len(beliefs_after),
                frozen_refusals_after=list(db.frozen_refusals))
        finally:
            await system.shutdown()
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-only", action="store_true")
    parser.add_argument("--mark", default="")
    parser.add_argument("--idle", type=float, default=60.0)
    args = parser.parse_args()
    result = asyncio.run(start_only() if args.start_only else serve(args.mark, args.idle))
    print(json.dumps(result, default=str))
