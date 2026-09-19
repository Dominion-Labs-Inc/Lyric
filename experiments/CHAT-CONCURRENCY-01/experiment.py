"""CHAT-CONCURRENCY-01 — how many users can chat/ask at the same time (measured, not asserted).

Teaches the shared mind a short entailment chain, then fires N SIMULTANEOUS questions from N distinct
users through the real front door (`handle_user_request`), measuring wall time, throughput, per-request
latency, error rate, and answer correctness at rising concurrency. This is the real-capacity answer for
chat/Q&A (distinct from the work-job concurrency cap).

Run: ./venv_torin/bin/python3 experiments/CHAT-CONCURRENCY-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def main() -> int:
    from core.database import get_database_manager
    from core.agents.autonomous.autonomous_coordinator import (
        create_autonomous_system, Conversation)
    from core.learning.unified_learning_system import get_unified_learning_system

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    coord = await create_autonomous_system({})
    coord.emit = None
    coord.learning = get_unified_learning_system()
    coord.disposition = None

    # Teach the SHARED mind a 2-hop chain (bare Conversation = curriculum = universal).
    n = uuid.uuid4().hex[:6]
    R, B = f"robin{n}", f"bird{n}"
    teach = Conversation(); teach._learning = coord.learning
    await teach.teach(f"a {R} is a {B}")
    await teach.teach(f"a {B} is an animal")
    question = f"is a {R} an animal?"

    # warm one call (model/embeddings/reader load) so it doesn't skew level 1
    t0 = time.monotonic()
    warm = await coord.handle_user_request(question, source="api",
                                           metadata={"session_id": "warm", "actor_identity": "warm"})
    warm_dt = time.monotonic() - t0
    print(f"warm-up: {warm_dt*1000:.0f} ms  answered={'answer' in (warm or {})}")

    async def one(i):
        t = time.monotonic()
        try:
            r = await coord.handle_user_request(
                question, source="api",
                metadata={"session_id": f"s{i}_{n}", "actor_identity": f"user{i}_{n}"})
            return (time.monotonic() - t, None, bool(r and r.get("answer")))
        except Exception as e:
            return (time.monotonic() - t, repr(e)[:120], False)

    print(f"\n{'users':>6} {'wall_s':>8} {'q/s':>8} {'p50_ms':>8} {'p95_ms':>8} {'errors':>7} {'answered':>9}")
    print("-" * 60)
    for level in (1, 4, 8, 16, 32, 64):
        t0 = time.monotonic()
        res = await asyncio.gather(*[one(i) for i in range(level)])
        wall = time.monotonic() - t0
        lats = sorted(r[0] for r in res)
        errs = [r[1] for r in res if r[1]]
        answered = sum(1 for r in res if r[2])
        p50 = lats[len(lats)//2] * 1000
        p95 = lats[min(len(lats)-1, int(len(lats)*0.95))] * 1000
        print(f"{level:>6} {wall:>8.2f} {level/wall:>8.1f} {p50:>8.0f} {p95:>8.0f} "
              f"{len(errs):>7} {answered:>4}/{level}")
        if errs:
            print(f"       first error: {errs[0]}")

    print("\nNote: chat/Q&A is NOT gated by the work-job concurrency cap — these run as "
          "coroutines on one event loop; the numbers above show where latency degrades.")
    return 0


sys.exit(asyncio.run(main()))
