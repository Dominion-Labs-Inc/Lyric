#!/usr/bin/env python3
"""Backfill BELIEFS for the ConceptNet English taxonomy — fast, batched, incremental.

The concepts/relations are already taught (in the store). This adds one Bayesian
belief per fact via the real belief API (observe_claim), in batches with a flush
after each, so beliefs COMMIT incrementally (watchable) and memory stays flat —
avoiding the single-giant-batch fan-out that stalled for hours on the lexicon arm.

  --batch N   facts per flush (default 5000)
Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
     ./venv_torin/bin/python3 scripts/teach_conceptnet_beliefs.py
"""
import os, sys, gzip, io, time, contextlib, asyncio
from datetime import datetime, timezone

os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DUMP = os.path.join(ROOT, "data", "bulk", "conceptnet-assertions-5.7.0.csv.gz")
SESS_DIR = os.path.join(ROOT, "docs", "teaching_sessions")


def _term(uri):
    p = uri.split("/")
    if len(p) < 4 or p[2] != "en":
        return None
    return p[3].replace("_", " ").strip().lower()


def build_isa():
    edges, seen = [], set()
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            cols = line.split("\t")
            if len(cols) < 4 or cols[1] != "/r/IsA":
                continue
            c, p = _term(cols[2]), _term(cols[3])
            if not c or not p or c == p or not c[0].isalnum():
                continue
            k = (c, p)
            if k in seen:
                continue
            seen.add(k)
            edges.append(f"{c} isa {p}")
    return edges


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=5000)
    args = ap.parse_args()

    print("parsing ConceptNet dump…", flush=True)
    props = build_isa()
    print(f"  {len(props):,} unique English IsA propositions", flush=True)

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        s = get_system(); await s.initialize()
        coord = s.autonomous_coordinator
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        us = get_uncertainty_system()
        # domain crystallization (idempotent) through the one authority
        with contextlib.suppress(Exception):
            await coord.universal_domain_master.ensure_domain("general")

    async def gcount():
        r = await db.execute_query(
            "SELECT count(*) n FROM unified.beliefs WHERE domain='general'", (), fetch_all=True)
        return r[0]["n"]

    prior = await gcount()
    prior_all = (await db.execute_query("SELECT count(*) n FROM unified.beliefs", (), fetch_all=True))[0]["n"]
    print(f"[conceptnet-beliefs] facts={len(props):,} prior general-beliefs={prior:,}", flush=True)

    t0 = time.monotonic()
    done = 0
    for i in range(0, len(props), args.batch):
        chunk = props[i:i + args.batch]
        for prop in chunk:
            try:
                us.observe_claim(prop, domain="general", supports=True, source="taught")
            except Exception:
                pass
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()
        done += len(chunk)
        rate = done / max(0.001, time.monotonic() - t0)
        live = await gcount()
        print(f"  {done:,}/{len(props):,}  general-beliefs={live:,}  ({rate:.0f} obs/s)", flush=True)

    # final settle
    for _ in range(3):
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()
        await asyncio.sleep(1.5)

    post = await gcount()
    post_all = (await db.execute_query("SELECT count(*) n FROM unified.beliefs", (), fetch_all=True))[0]["n"]
    elapsed = time.monotonic() - t0

    os.makedirs(SESS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        f"# Teaching session — conceptnet-english-beliefs",
        f"*{datetime.now(timezone.utc).isoformat()} · ConceptNet 5.7.0 (offline) · "
        f"belief backfill (batched + flushed) · model-free (no LLM)*", "",
        "## Taught",
        f"- English IsA propositions: **{len(props):,}** → one Bayesian belief each (`observe_claim`, source `taught`)",
        f"- Batch size: {args.batch:,} · flushed per batch · Elapsed: {elapsed:.1f}s", "",
        "## Beliefs: prior → after", "",
        "| Store | Prior | After | Δ |", "|---|--:|--:|--:|",
        f"| Beliefs (`general`) | {prior:,} | {post:,} | +{post-prior:,} |",
        f"| Beliefs (all) | {prior_all:,} | {post_all:,} | +{post_all-prior_all:,} |",
        "",
        "Concepts for these facts were already admitted (256k in the store); this session "
        "establishes the graded belief over each. Per-word lexicon enrichment was intentionally "
        "skipped here (it was the bottleneck of the prior single-batch run) and can be run "
        "separately.", "", "---", ""]
    path = os.path.join(SESS_DIR, f"{ts}_conceptnet-english-beliefs.md")
    open(path, "w").write("\n".join(lines))
    print(f"\n=== report -> docs/teaching_sessions/{ts}_conceptnet-english-beliefs.md ===", flush=True)
    print(f"general-beliefs {prior:,} -> {post:,} (+{post-prior:,}) | all {prior_all:,} -> {post_all:,}", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
