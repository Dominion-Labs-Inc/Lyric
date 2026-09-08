#!/usr/bin/env python3
"""Teach English through the ONE substrate learning pipeline, WITH FAN-OUT ON, and
DOCUMENT the session.

Unlike the older reference-taxonomy teach (fan_out=False), this drives the real
learning authority so a taught `child isa parent` fact fans out to BELIEFS
(one observe_claim per clause), the DOMAIN (crystallised), and the LEXICON. Every
run writes a session report to docs/teaching_sessions/<ts>.md documenting the
substrate BEFORE and AFTER — prior beliefs -> resulting beliefs, domains, concepts,
lexicon — so each teaching session is auditable.

  --limit N   teach only the first N isa facts (for a validating session)
  --label S   a name for the session
  --no-facts / --no-pos   skip one half

Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 TORIN_NO_WATCHDOG=1 \
     ./venv_torin/bin/python3 scripts/teach_session.py --limit 1200 --label wordnet-validate
"""
from __future__ import annotations

import os
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")

import asyncio, contextlib, io, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SESS_DIR = ROOT / "docs" / "teaching_sessions"

CLS = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE"}


def build_isa(limit=None):
    """`(child, 'isa', parent)` from WordNet noun hypernyms — the taxonomy that,
    fanned out, becomes beliefs and a crystallised domain."""
    from nltk.corpus import wordnet as wn
    def name(syn):
        return syn.lemmas()[0].name().replace("_", " ").strip().lower()
    edges = set()
    for syn in wn.all_synsets("n"):
        child = name(syn)
        for hyper in syn.hypernyms():
            parent = name(hyper)
            if child and parent and child != parent and " " not in child and " " not in parent:
                edges.add((child, "isa", parent))
    facts = sorted(edges)
    return facts[:limit] if limit else facts


def build_pos(limit=None):
    from nltk.corpus import wordnet as wn
    from collections import defaultdict
    weight = defaultdict(lambda: defaultdict(float))
    for syn in wn.all_synsets():
        cls = CLS.get(syn.pos())
        if not cls:
            continue
        for lemma in syn.lemmas():
            w = lemma.name().replace("_", " ").strip().lower()
            if " " in w or not w.isalpha():
                continue
            weight[w][cls] += lemma.count() + 0.01
    out = []
    for w, by in weight.items():
        ranked = sorted(by.items(), key=lambda kv: kv[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            continue
        out.append((w, ranked[0][0]))
    out.sort()
    return out[:limit] if limit else out


async def snapshot(db):
    async def q(sql):
        return await db.execute_query(sql, (), fetch_all=True) or []
    beliefs = (await q("SELECT count(*) AS n FROM unified.beliefs"))[0]["n"]
    lexical = (await q("SELECT count(*) AS n FROM unified.beliefs WHERE domain='lexical'"))[0]["n"]
    concepts = (await q("SELECT count(*) AS n FROM unified.concepts"))[0]["n"]
    doms = [r["domain_id"] for r in await q("SELECT domain_id FROM unified.domains ORDER BY domain_id")]
    from core.semantics.lexicon import get_lexicon
    lexicon = len(getattr(get_lexicon(), "_entries", {}) or {})
    return {"beliefs": beliefs, "lexical_beliefs": lexical, "concepts": concepts,
            "domains": doms, "lexicon": lexicon}


async def flush_beliefs():
    """Beliefs persist fire-and-forget; drain the backlog and let in-flight writes
    settle so a taught belief is durable before we snapshot (and before exit)."""
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    us = get_uncertainty_system()
    for _ in range(3):
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()
        await asyncio.sleep(1.5)
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()


async def sample_beliefs(db, domain, n=12):
    rows = await db.execute_query(
        "SELECT claim, posterior_probability FROM unified.beliefs "
        "WHERE domain = $1 ORDER BY updated_at DESC NULLS LAST LIMIT $2",
        (domain, n), fetch_all=True) or []
    return [(r["claim"], round(float(r["posterior_probability"] or 0.0), 4)) for r in rows]


async def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--label", default="wordnet-english")
    ap.add_argument("--no-facts", action="store_true")
    ap.add_argument("--no-pos", action="store_true")
    ap.add_argument("--remember", action="store_true", help="also store each fact as a memory")
    args = ap.parse_args()

    facts = [] if args.no_facts else build_isa(args.limit)
    pos = [] if args.no_pos else build_pos(args.limit)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.database import get_database_manager
        from core.semantics.cognitive_ingress import Provenance
        db = get_database_manager(); await db.initialize()

    domain = "lexical"
    print(f"[{args.label}] facts={len(facts):,} pos={len(pos):,} — snapshotting prior state…", flush=True)
    prior = await snapshot(db)
    prior_sample = await sample_beliefs(db, domain)

    t0 = time.monotonic()
    pos_counts = {}
    if pos:
        pos_counts = learning.learn_words(pos, source="wordnet", authoritative=True)
        print(f"  POS: {pos_counts}", flush=True)

    fact_counts = {}
    if facts:
        prov = Provenance(producer="teacher", source_id="wordnet_english",
                          source_type="USER_SUPPLIED")

        def report(c):
            print(f"  facts {c['total']:,}/{len(facts):,} admitted={c.get('admitted',0):,} "
                  f"already={c.get('already',0):,} refused={c.get('refused',0):,}", flush=True)

        # FAN-OUT ON: each taught clause becomes a belief; the domain crystallises.
        fact_counts = await learning.learn_facts(
            facts, provenance=prov, domain=domain,
            fan_out=True, remember=args.remember, progress=report)
        print(f"  facts: {fact_counts}", flush=True)

    elapsed = time.monotonic() - t0
    print("  flushing beliefs to durable storage…", flush=True)
    await flush_beliefs()
    post = await snapshot(db)
    post_sample = await sample_beliefs(db, domain)

    # ── write the session report ──────────────────────────────────────────
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_domains = [d for d in post["domains"] if d not in set(prior["domains"])]
    lines = [
        f"# Teaching session — {args.label}",
        f"*{datetime.now(timezone.utc).isoformat()} · fan-out ON (beliefs + domain + lexicon) · model-free (no LLM)*",
        "",
        "## Taught",
        f"- ISA facts (WordNet noun taxonomy): **{len(facts):,}**  → `{fact_counts}`",
        f"- Parts of speech (WordNet lemmas): **{len(pos):,}**  → `{pos_counts}`",
        f"- Elapsed: {elapsed:.1f}s",
        "",
        "## Substrate: prior → after",
        "",
        "| Store | Prior | After | Δ |",
        "|---|--:|--:|--:|",
        f"| Beliefs (all) | {prior['beliefs']:,} | {post['beliefs']:,} | +{post['beliefs']-prior['beliefs']:,} |",
        f"| Beliefs (`lexical`) | {prior['lexical_beliefs']:,} | {post['lexical_beliefs']:,} | +{post['lexical_beliefs']-prior['lexical_beliefs']:,} |",
        f"| Concepts | {prior['concepts']:,} | {post['concepts']:,} | +{post['concepts']-prior['concepts']:,} |",
        f"| Lexicon words | {prior['lexicon']:,} | {post['lexicon']:,} | +{post['lexicon']-prior['lexicon']:,} |",
        f"| Domains | {len(prior['domains'])} | {len(post['domains'])} | +{len(post['domains'])-len(prior['domains'])} |",
        "",
        f"**Domains added:** {', '.join(new_domains) if new_domains else '(none — existing `lexical` domain reinforced)'}",
        "",
        "## Beliefs: prior → resulting (sample, domain `lexical`)",
        "",
        "_Before this session:_",
        "",
    ]
    lines += [f"- `{c}` → {p}" for c, p in prior_sample] or ["- (none held)"]
    lines += ["", "_After this session:_", ""]
    lines += [f"- `{c}` → {p}" for c, p in post_sample] or ["- (none)"]
    lines += ["", "---", f"*Report: docs/teaching_sessions/{ts}.md*", ""]
    report_path = SESS_DIR / f"{ts}_{args.label}.md"
    report_path.write_text("\n".join(lines))
    print(f"\n=== session report -> {report_path.relative_to(ROOT)} ===", flush=True)
    print(f"beliefs {prior['beliefs']:,} -> {post['beliefs']:,} (+{post['beliefs']-prior['beliefs']:,}), "
          f"lexical {prior['lexical_beliefs']:,} -> {post['lexical_beliefs']:,} "
          f"(+{post['lexical_beliefs']-prior['lexical_beliefs']:,})  |  "
          f"lexicon {prior['lexicon']:,} -> {post['lexicon']:,}  |  "
          f"domains {len(prior['domains'])} -> {len(post['domains'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
