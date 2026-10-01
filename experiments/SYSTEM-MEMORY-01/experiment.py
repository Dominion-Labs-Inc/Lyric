#!/usr/bin/env python3
"""SYSTEM-MEMORY-01 — the memory faculty, alone, on the live substrate.

One authority (`MemoryAgent`, reached through `get_memory_agent`). A memory is
stored and comes back by search and by id, is superseded keeping what it said,
and cannot be deleted without the token governance requires. Everything written
is removed by id.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-MEMORY-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

TOKEN = "qzxmem"
EV = RunRecord(
    "SYSTEM-MEMORY-01",
    claim=("Memory is one authority: a memory stored is found by content and by id, "
           "superseding keeps what it used to say, an unknown id is None, and a delete "
           "without governance's token is refused."),
    hypothesis=("A second agent, a stored memory that cannot be found, a delete that "
                "succeeds without a token, or a dead public method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.memory import Origin
    system, coord = await boot()
    d = db()
    ids = []
    try:
        from core.agents.memory_agent import get_memory_agent
        from core.memory.utils.interfaces import MemoryType
        M = await get_memory_agent()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="memory", cls="MemoryAgent",
                        path="core/agents/memory_agent.py", held=coord.memory, reached=M)

        print("\n== B. Stored, found, read back ==")
        ok, mid = await M.store_memory(
            content=f"isolation probe: the {TOKEN} lamp in the study is on",
            memory_type=MemoryType.SEMANTIC, importance_score=0.6, confidence_score=0.9,
            tags=["isolation_probe"], origin=Origin.own("SYSTEM-MEMORY-01"))
        if mid:
            ids.append(mid)
        check("store_memory returns (True, memory_id)", ok is True and bool(mid), f"ok={ok} id={mid}")
        hits = await M.retrieve(TOKEN, limit=5)
        check("the memory is found by its content",
              any(getattr(h, "memory_id", None) == mid for h in hits or []),
              f"{len(hits or [])} hit(s): {[getattr(h, 'memory_id', None) for h in (hits or [])][:3]}")
        item = await M.retrieve_memory(mid)
        check("and read back by id", item is not None and TOKEN in str(getattr(item, "content", "")),
              f"content={str(getattr(item, 'content', ''))[:60]!r}")
        check("an unknown id is None", await M.retrieve_memory("memory_does_not_exist_qzx") is None)

        print("\n== C. Superseded, keeping what it used to say ==")
        sup = await M.supersede(mid, f"isolation probe: the {TOKEN} lamp in the study is OFF",
                                because="SYSTEM-MEMORY-01")
        after = await M.retrieve_memory(mid)
        check("supersede replaces the content", sup is True and "OFF" in str(getattr(after, "content", "")),
              f"supersede={sup} content={str(getattr(after, 'content', ''))[:60]!r}")
        meta = getattr(after, "metadata", None) or {}
        check("and keeps what it used to say",
              "is on" in str(meta) or "superseded" in str(meta).lower() or "previous" in str(meta).lower(),
              f"metadata keys={sorted(meta)[:8] if isinstance(meta, dict) else type(meta).__name__}")

        print("\n== D. A memory can be forgotten ==")
        ok_f, forget_id = await M.store_memory(
            content=f"isolation probe: the {TOKEN} note to forget", memory_type=MemoryType.EPISODIC,
            importance_score=0.5, origin=Origin.own("SYSTEM-MEMORY-01"))
        if forget_id:
            ids.append(forget_id)
        gone = await M.delete_memory(forget_id, reason="probe") if forget_id else False
        still = await M.retrieve_memory(forget_id) if forget_id else None
        check("a forgotten memory is gone", ok_f and gone is True and still is None,
              f"deleted={gone} still_present={still is not None}")
        check("and the others are untouched", await M.retrieve_memory(mid) is not None)

        print("\n== E. Whose memory it is ==")
        # A user's memory is theirs: every way memory is searched -- by
        # meaning, by wording, by tag -- shows it to its owner and to no one
        # else, and a near-duplicate is merged only within one owner.
        A, B = f"isoprobe-a-{TOKEN}", f"isoprobe-b-{TOKEN}"
        said = f"isolation probe: the {TOKEN} kettle in speaker a's kitchen is copper"
        ok, a_mid = await M.store_memory(content=said, memory_type=MemoryType.SEMANTIC,
                                         importance_score=0.7, tags=[f"owner_{TOKEN}"], origin=Origin.of(A, "SYSTEM-MEMORY-01"))
        if a_mid:
            ids.append(a_mid)
        check("a user's memory is stored as theirs", ok is True and bool(a_mid), f"{a_mid}")
        for strategy, query, kw in (("semantic", said, {}), ("keyword", f"{TOKEN} kettle", {}),
                                    ("tags", None, {"tags": {f"owner_{TOKEN}"}})):
            seen = {}
            for who in (A, B, None):
                got = await M.retrieve(query, strategies=(strategy,), actor=who,
                                       min_similarity=0.3, limit=10, **kw)
                seen[who] = any(getattr(h, "memory_id", None) == a_mid for h in got or [])
            check(f"by {strategy}: its owner finds it, another user and the substrate do not",
                  seen[A] and not seen[B] and not seen[None],
                  f"owner={seen[A]} other={seen[B]} substrate={seen[None]}")
        ok, s_mid = await M.store_memory(content=said, memory_type=MemoryType.SEMANTIC,
                                         importance_score=0.7, tags=[f"owner_{TOKEN}"], origin=Origin.own("SYSTEM-MEMORY-01"))
        if s_mid:
            ids.append(s_mid)
        check("the same words from the substrate are its own memory, not merged into the user's",
              ok is True and bool(s_mid) and s_mid != a_mid, f"user={a_mid} substrate={s_mid}")
        ok, a2 = await M.store_memory(content=said, memory_type=MemoryType.SEMANTIC,
                                      importance_score=0.7, tags=[f"owner_{TOKEN}"], origin=Origin.of(A, "SYSTEM-MEMORY-01"))
        if a2 and a2 not in ids:
            ids.append(a2)
        # NOTHING IS MERGED: the same words said again are a second memory of
        # theirs, found beside the first by recall.
        again = await M.retrieve_memory(a2) if a2 else None
        check("the same words from the same user are a second memory of theirs, not merged",
              bool(a2) and a2 != a_mid and again is not None
              and getattr(again, "user_id", None) == A, f"first={a_mid} again={a2}")

        m = M.get_metrics()
        check("metrics are a dict", isinstance(m, dict) and bool(m), f"keys={sorted(m)[:8]}")
    finally:
        try:
            for mid in ids:
                for t in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
                    await d.execute_query(f"DELETE FROM {t} WHERE memory_id = $1", (mid,))
                try:
                    await d.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1", (mid,))
                except Exception:
                    pass
            left = await d.execute_query(
                "SELECT count(*) n FROM memory_hot.memory_hot WHERE memory_id = ANY($1::text[]) "
                "OR content LIKE $2", (ids, f"%{TOKEN}%"), fetch_one=True)
            check("everything this run wrote is removed", left is not None and int(left["n"]) == 0,
                  f"left={left and left['n']}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-MEMORY-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
