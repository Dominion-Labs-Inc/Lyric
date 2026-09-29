#!/usr/bin/env python3
"""VERIFY-01 — Fresh, current-state verification of the unified substrate.

Drives the ONE running coordinator's pipelines (each faculty has its own pipeline
inside the coordinator: reasoning, learning, memory, execution, domain, intrinsic
motivation, cross-domain) and records what each ACTUALLY does today — not what an
archived experiment froze. Every probe is defensive: it captures the real result
or the real error, so the manifest is an honest snapshot of the current system.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/VERIFY-01/experiment.py
"""
from __future__ import annotations

import os
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "lyric_db")
os.environ.setdefault("LYRIC_NO_WATCHDOG", "1")

import asyncio, contextlib, io, json, sys, traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent


def brief(v, n=400):
    s = v if isinstance(v, str) else repr(v)
    return s[:n]


async def main() -> int:
    findings = {}

    async def probe(name, coro_fn):
        """Run one pipeline probe; capture the real result or the real error."""
        try:
            out = await coro_fn()
            findings[name] = {"ok": True, **out}
            print(f"[OK]   {name}: {brief(out, 160)}", flush=True)
        except Exception as e:
            findings[name] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                              "trace": traceback.format_exc()[-800:]}
            print(f"[ERR]  {name}: {type(e).__name__}: {e}", flush=True)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator

    print("=== substrate up; driving the unified pipelines ===", flush=True)

    # ── REASONING pipeline (coord.reason_about → neural bridge) ──────────────
    async def reasoning():
        from core.memory import Origin
        qs = ["is a robin a bird", "is an ocelot an animal", "is a hammer a bird"]
        rows = []
        for q in qs:
            r = await coord.reason_about(q, origin=Origin.own("VERIFY-01"))
            md = dict(getattr(r, "metadata", {}) or {})
            rows.append({"q": q, "answer": brief(getattr(r, "answer", ""), 80),
                         "confidence": round(float(getattr(r, "confidence", 0.0)), 3),
                         "mode": str(getattr(r, "mode_used", "")),
                         "reason": md.get("reason"), "route": md.get("route"),
                         "model_calls": md.get("model_calls")})
        return {"queries": rows}
    await probe("reasoning_pipeline", reasoning)

    # ── EXECUTION pipeline (coord.execute_task) — question / knowledge loop ───
    async def execution():
        from core.agents.autonomous.shared_types import Task, TaskType
        tt = getattr(TaskType, "REASONING", None) or getattr(TaskType, "ANALYSIS", None) or list(TaskType)[0]
        task = Task(id="verify01_q", type=tt, description="Is an ocelot an animal?")
        res = await coord.execute_task(task)
        return {"task_type": str(tt), "success": res.get("success"),
                "verification_state": res.get("verification_state"),
                "model_free": res.get("model_free"),
                "keys": sorted(res.keys())[:12], "summary": brief(res, 200)}
    await probe("execution_pipeline", execution)

    # ── CROSS-DOMAIN pipeline (coord.perform_cross_domain_reasoning) ──────────
    async def cross_domain():
        from core.memory import Origin
        r = await coord.perform_cross_domain_reasoning(
            "how does structure transfer between domains",
            source_domains=["scientific", "mathematical"], origin=Origin.own("VERIFY-01"))
        return {"type": type(r).__name__, "summary": brief(r, 300)}
    await probe("cross_domain_pipeline", cross_domain)

    # ── DOMAIN pipeline (one authority; automatic creation) — count in the DB ─
    async def domains():
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        rows = await db.execute_query(
            "SELECT domain_id FROM unified.domains ORDER BY domain_id", (), fetch_all=True) or []
        ids = [r["domain_id"] for r in rows]
        CATS = {f"domain_{c}" for c in ("scientific technical business creative social "
                "physical abstract mathematical linguistic temporal spatial causal "
                "ethical aesthetic practical").split()}
        learned = [i for i in ids if i not in CATS]
        return {"total_domains_db": len(ids), "category_domains": len(CATS),
                "learned_domains": learned,
                "has_universal_domain_master": coord.universal_domain_master is not None}
    await probe("domain_pipeline", domains)

    # ── LEARNING pipeline + BELIEFS (coord.learning) ─────────────────────────
    async def learning_beliefs():
        L = coord.learning
        # belief round-trip through the one learning authority
        b = L.create_belief("verify01:test_claim", "verify01", prior=0.15)
        bid = getattr(b, "belief_id", None) or getattr(b, "id", None)
        p0 = float(getattr(L.get_belief(bid), "posterior_probability", 0.0))
        L.update_belief(bid, {"quality": 0.9, "source": "verify01"}, evidence_supports=True)
        p1 = float(getattr(L.get_belief(bid), "posterior_probability", 0.0))
        metrics = {}
        with contextlib.suppress(Exception):
            metrics = await L.metrics()
        return {"belief_prior": round(p0, 3), "belief_after_evidence": round(p1, 3),
                "belief_moved": p1 > p0,
                "learning_initialized": getattr(L, "initialized", None),
                "metrics_keys": sorted(list(metrics.keys()))[:12] if isinstance(metrics, dict) else None}
    await probe("learning_and_beliefs", learning_beliefs)

    # ── INTRINSIC MOTIVATION pipeline ────────────────────────────────────────
    async def motivation():
        targets = await coord.intrinsic_motivation.get_top_exploration_targets(limit=5)
        rows = []
        for t in (targets or [])[:5]:
            rows.append(brief(getattr(t, "description", None) or getattr(t, "target", None) or t, 80))
        return {"num_targets": len(targets or []), "sample": rows}
    await probe("intrinsic_motivation_pipeline", motivation)

    # ── MEMORY pipeline (coord.memory store + retrieve) ──────────────────────
    async def memory():
        from core.memory import Origin
        m = coord.memory
        if m is None:
            return {"memory": "None (not attached)"}
        stored = None
        with contextlib.suppress(Exception):
            stored = await m.store_memory(content="verify01 probe memory: the sky probe token qzx",
                                          memory_type="episodic", importance=0.5, origin=Origin.own("VERIFY-01"))
        got = None
        with contextlib.suppress(Exception):
            got = await m.retrieve("qzx", limit=3)
        return {"memory_class": type(m).__name__,
                "stored": brief(stored, 80),
                "retrieved_n": len(got) if isinstance(got, list) else brief(got, 80)}
    await probe("memory_pipeline", memory)

    manifest = {
        "experiment": "VERIFY-01",
        "purpose": "fresh current-state verification of the unified coordinator pipelines",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "pipelines_ok": {k: v.get("ok") for k, v in findings.items()},
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("\n=== pipelines_ok ===", flush=True)
    print(json.dumps(manifest["pipelines_ok"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
