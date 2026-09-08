#!/usr/bin/env python3
"""TEACH the substrate English IsA taxonomy from the ConceptNet bulk dump — OFFLINE.

No HTTP-per-query. One file is downloaded once
(data/bulk/conceptnet-assertions-5.7.0.csv.gz), and this streams it locally,
keeps English `/r/IsA` edges, and teaches each `child isa parent` through the ONE
learning path with FAN-OUT ON (beliefs per fact + domain crystallization +
lexicon). Prior->after snapshot is written to docs/teaching_sessions/.

ConceptNet CSV row (tab-separated):
    /a/[/r/IsA/,/c/en/dog/,/c/en/animal/]  /r/IsA  /c/en/dog  /c/en/animal  {json}

  --limit N   teach only the first N edges (smoke)
  --domain S  domain to teach into (default: general)
Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
     ./venv_torin/bin/python3 scripts/teach_conceptnet.py
"""
import os, sys, gzip, io, time, contextlib, asyncio
from datetime import datetime, timezone

os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUMP = os.path.join(ROOT, "data", "bulk", "conceptnet-assertions-5.7.0.csv.gz")
SESS_DIR = os.path.join(ROOT, "docs", "teaching_sessions")


def _term(uri):
    """/c/en/hot_dog/n -> 'hot dog'; non-English -> None."""
    p = uri.split("/")
    if len(p) < 4 or p[2] != "en":
        return None
    return p[3].replace("_", " ").strip().lower()


def build_isa(limit=None):
    """Stream the ConceptNet dump; yield unique English (child, 'isa', parent)."""
    edges, seen = [], set()
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            cols = line.split("\t")
            if len(cols) < 4 or cols[1] != "/r/IsA":
                continue
            c, p = _term(cols[2]), _term(cols[3])
            if not c or not p or c == p or not c[0].isalnum():
                continue
            key = (c, p)
            if key in seen:
                continue
            seen.add(key)
            edges.append((c, "isa", p))
            if limit and len(edges) >= limit:
                break
    return edges


async def _snapshot(db):
    async def q(sql):
        return await db.execute_query(sql, (), fetch_all=True) or []
    beliefs = (await q("SELECT count(*) n FROM unified.beliefs"))[0]["n"]
    concepts = (await q("SELECT count(*) n FROM unified.concepts"))[0]["n"]
    doms = [r["domain_id"] for r in await q("SELECT domain_id FROM unified.domains ORDER BY domain_id")]
    by_dom = {r["domain"]: r["n"] for r in await q(
        "SELECT domain, count(*) n FROM unified.beliefs GROUP BY domain")}
    return {"beliefs": beliefs, "concepts": concepts, "domains": doms, "by_dom": by_dom}


async def _flush():
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    us = get_uncertainty_system()
    for _ in range(3):
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()
        await asyncio.sleep(1.5)


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--domain", default="general")
    args = ap.parse_args()

    if not os.path.exists(DUMP):
        print(f"ERROR: dump not found at {DUMP} — download it first.", flush=True)
        return 1

    print("parsing ConceptNet dump (offline)…", flush=True)
    t0 = time.monotonic()
    facts = build_isa(args.limit)
    print(f"  {len(facts):,} unique English IsA edges parsed in {time.monotonic()-t0:.1f}s", flush=True)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.database import get_database_manager
        from core.semantics.cognitive_ingress import Provenance
        db = get_database_manager(); await db.initialize()

    label = "conceptnet-english" + ("-smoke" if args.limit else "")
    prior = await _snapshot(db)
    print(f"[{label}] facts={len(facts):,} — prior beliefs={prior['beliefs']:,} "
          f"domains={len(prior['domains'])}", flush=True)

    prov = Provenance(producer="teacher", source_id="conceptnet_5.7.0",
                      source_type="USER_SUPPLIED")
    tt = time.monotonic()

    def report(c):
        rate = c["total"] / max(0.001, time.monotonic() - tt)
        print(f"  {c['total']:,}/{len(facts):,} admitted={c['admitted']:,} "
              f"already={c['already']:,} refused={c['refused']:,} ({rate:.0f}/s)", flush=True)

    counts = await learning.learn_facts(facts, provenance=prov, domain=args.domain,
                                        fan_out=True, remember=False, progress=report)
    report(counts)
    print("  flushing beliefs…", flush=True)
    await _flush()
    post = await _snapshot(db)
    elapsed = time.monotonic() - tt

    os.makedirs(SESS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_doms = [d for d in post["domains"] if d not in set(prior["domains"])]
    d = args.domain
    lines = [
        f"# Teaching session — {label}",
        f"*{datetime.now(timezone.utc).isoformat()} · ConceptNet 5.7.0 (offline bulk dump) · "
        f"fan-out ON (beliefs + domain + lexicon) · model-free (no LLM)*", "",
        "## Taught",
        f"- English IsA edges (ConceptNet): **{len(facts):,}**  → `{counts}`",
        f"- Domain: `{d}`", f"- Elapsed (teach): {elapsed:.1f}s", "",
        "## Substrate: prior → after", "",
        "| Store | Prior | After | Δ |", "|---|--:|--:|--:|",
        f"| Beliefs (all) | {prior['beliefs']:,} | {post['beliefs']:,} | +{post['beliefs']-prior['beliefs']:,} |",
        f"| Beliefs (`{d}`) | {prior['by_dom'].get(d,0):,} | {post['by_dom'].get(d,0):,} | +{post['by_dom'].get(d,0)-prior['by_dom'].get(d,0):,} |",
        f"| Concepts | {prior['concepts']:,} | {post['concepts']:,} | +{post['concepts']-prior['concepts']:,} |",
        f"| Domains | {len(prior['domains'])} | {len(post['domains'])} | +{len(post['domains'])-len(prior['domains'])} |",
        "", f"**Domains added:** {', '.join(new_doms) if new_doms else '(none new — existing domains reinforced)'}",
        "", "---", ""]
    path = os.path.join(SESS_DIR, f"{ts}_{label}.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n=== report -> docs/teaching_sessions/{ts}_{label}.md ===", flush=True)
    print(f"beliefs {prior['beliefs']:,} -> {post['beliefs']:,} (+{post['beliefs']-prior['beliefs']:,}) | "
          f"concepts {prior['concepts']:,} -> {post['concepts']:,} | "
          f"domains {len(prior['domains'])} -> {len(post['domains'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
