#!/usr/bin/env python3
"""TEACH the substrate broad English + English-language-arts taxonomy from Wikidata,
through the ONE teaching path (learning.learn_facts, WIKIDATA provenance).

Wikidata's `subclass of` (P279) graph is a hand-built knowledge resource like
WordNet, and a subclass edge IS a chainable implication ("every sparrow is a
bird"). This pulls P279 edges under broad roots, keeps only NOTABLE concepts
(those with an English Wikipedia article — dropping Wikidata's obscure
article-less long tail), and teaches each `child isa parent` with FAN-OUT ON, so
a taught fact reaches BELIEFS (one per fact), the DOMAIN (crystallized on the
spot), and the LEXICON — never the conversation path.

Two root groups, taught into two domains:
  - general       → broad world knowledge (animals, plants, food, science, …)
  - language_arts → English language arts (parts of speech, literary forms,
                    figures of speech, poetry, grammar, …)

  --fetch          pull edges from Wikidata into the cache, then stop
  --teach          teach from the cache (fetches first if the cache is missing)
  --smoke          tiny fetch+teach (2 roots, small LIMIT) to verify the pipeline
  --limit N        cap edges per root (default 40000; smoke uses 300)

Run:  PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
      ./venv_torin/bin/python3 scripts/teach_general_wikidata.py --teach
"""
import os, sys, json, time, urllib.request, urllib.parse, socket, io, contextlib, asyncio
from datetime import datetime, timezone

os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "general_wikidata_edges.json")
SESS_DIR = os.path.join(ROOT, "docs", "teaching_sessions")
socket.setdefaulttimeout(300)

# Broad world-knowledge roots. Per-root counts print on --fetch, so a mistyped QID
# shows +0 and is harmless. Redundant roots (bird⊂animal) are fine — edges dedup.
GENERAL_ROOTS = {
    "Q729": "animal", "Q5113": "bird", "Q152": "fish", "Q7377": "mammal",
    "Q1390": "insect", "Q10908": "amphibian", "Q10811": "reptile",
    "Q756": "plant", "Q10884": "tree", "Q506": "flower", "Q764": "fungus",
    "Q2095": "food", "Q3314483": "fruit", "Q11004": "vegetable",
    "Q40050": "drink", "Q154": "alcoholic beverage", "Q10943": "cheese",
    "Q42889": "vehicle", "Q1229765": "watercraft", "Q11436": "aircraft",
    "Q11344": "chemical element", "Q214609": "material",
    "Q34770": "language", "Q34379": "musical instrument", "Q188451": "music genre",
    "Q12136": "disease", "Q12140": "medication", "Q8386": "drug",
    "Q39546": "tool", "Q11019": "machine", "Q7397": "software", "Q8366": "algorithm",
    "Q41176": "building", "Q811979": "architectural structure",
    "Q15324": "body of water", "Q271669": "landform", "Q7946": "mineral", "Q8063": "rock",
    "Q349": "sport", "Q11410": "game", "Q11639": "dance",
    "Q7278": "political ideology", "Q9174": "religion", "Q178885": "deity",
    "Q2239243": "mythical creature", "Q9134": "mythology",
    "Q12737077": "occupation", "Q11460": "clothing", "Q728": "weapon",
    "Q14745": "furniture", "Q1075": "color", "Q9415": "emotion",
    "Q11862": "academic discipline", "Q336": "science", "Q11016": "technology",
    "Q735": "art", "Q8142": "currency", "Q47574": "unit of measurement",
    "Q634": "planet", "Q523": "star", "Q6999": "astronomical object",
    "Q17444909": "mathematical object", "Q1445650": "holiday",
    "Q4936952": "anatomical structure",
}
# Deliberately NOT roots: organization (Q43229), event (Q1656682), taxon (Q16521) —
# these are named-entity trees (every company, every species), not English
# vocabulary; they are the worst timeout offenders and the wrong scope. Common
# creatures/plants already come in under animal/plant.

# English language arts roots — parts of speech, literary forms, figures of speech,
# poetry, grammar, rhetoric.
LANGUAGE_ARTS_ROOTS = {
    "Q34770": "language", "Q8171": "word", "Q82042": "part of speech",
    "Q24905": "verb", "Q1084": "noun", "Q34698": "adjective", "Q380057": "adverb",
    "Q36224": "pronoun", "Q43249": "morpheme", "Q9788": "letter",
    "Q8192": "writing system", "Q980357": "grammatical category",
    "Q177691": "grammatical tense", "Q187931": "phrase", "Q41796": "sentence",
    "Q7725634": "literary work", "Q223393": "literary genre", "Q47461344": "written work",
    "Q8261": "novel", "Q11826": "essay", "Q25372": "drama", "Q676": "prose",
    "Q482": "poetry", "Q5185279": "poem", "Q1318295": "narrative",
    "Q168929": "figure of speech", "Q1762471": "rhetorical device",
    "Q212457": "metre", "Q170539": "rhyme", "Q184511": "idiom", "Q35102": "proverb",
    "Q483394": "genre", "Q8253": "fiction", "Q2198855": "literary movement",
}


def _sparql(query):
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "TorinAI-teach/1.0 (research)"})
    text = urllib.request.urlopen(req).read().decode("utf-8")
    return json.loads(text, strict=False)["results"]["bindings"]


def _closure(qid, limit=40000):
    """(child,parent) notable P279 edges in qid's closure. Returns (edges, capped):
    capped=True means the result hit `limit` and is truncated. Raises on transport
    error (504, truncated JSON) so the caller can chunk."""
    q = """SELECT DISTINCT ?cl ?pl WHERE {
      ?child wdt:P279* wd:%s . ?child wdt:P279 ?parent .
      ?article schema:about ?child ; schema:isPartOf <https://en.wikipedia.org/> .
      ?child rdfs:label ?cl . FILTER(LANG(?cl)="en")
      ?parent rdfs:label ?pl . FILTER(LANG(?pl)="en")
    } LIMIT %d""" % (qid, limit)
    rows = _sparql(q)
    return [(r["cl"]["value"], r["pl"]["value"]) for r in rows], len(rows) >= limit


def _children(qid):
    """Direct subclass QIDs of qid (fast, anchored)."""
    q = "SELECT ?c WHERE { ?c wdt:P279 wd:%s }" % qid
    try:
        return [r["c"]["value"].rsplit("/", 1)[-1] for r in _sparql(q)]
    except Exception:
        return []


# A node with more direct subclasses than this is an ENTITY EXPLOSION (every
# individual compound/species/etc.), not a vocabulary category — never chunk it.
MAX_CHUNK_CHILDREN = 3000


def _root_edges(qid, limit=40000):
    """Notable P279 closure edges under qid. Plain closure first (handles the
    normal roots, accepting a 40k truncation for the big-but-tractable ones like
    food/vehicle). Only if the closure 504s/truncates do we fall back to ONE
    bounded level of chunk-by-child — and we REFUSE to chunk an entity explosion
    (>MAX_CHUNK_CHILDREN direct children). No recursion: bounded query count."""
    for attempt in range(3):
        try:
            edges, _capped = _closure(qid, limit)
            return edges  # a truncated 40k slice is fine for vocabulary
        except Exception as e:
            if attempt == 2:
                break
            time.sleep(5 * (attempt + 1))
    kids = _children(qid)
    if not kids or len(kids) > MAX_CHUNK_CHILDREN:
        why = "entity explosion" if kids else "no children"
        print(f"    {qid} SKIPPED (closure failed; {len(kids):,} children — {why})", flush=True)
        return []
    print(f"    chunking {qid} -> {len(kids)} children (one level)", flush=True)
    acc, seen = [], set()
    for kid in kids:
        try:
            e, _c = _closure(kid, limit)
        except Exception:
            e = []
        for c, p in e:
            key = (c.lower(), p.lower())
            if key not in seen:
                seen.add(key); acc.append((c, p))
    return acc


def _fetch_group(roots, limit):
    out, seen = [], set()
    for qid, name in roots.items():
        edges = _root_edges(qid, limit)
        fresh = [(c, p) for (c, p) in edges
                 if c.lower() != p.lower() and (c.lower(), p.lower()) not in seen]
        for c, p in fresh:
            seen.add((c.lower(), p.lower()))
        out.extend([c, p] for c, p in fresh)
        print(f"  {name:24} +{len(fresh):5} (root total {len(edges)})", flush=True)
        time.sleep(1)  # be gentle on the public endpoint — fewer load-induced 504s
    return out


def fetch(smoke=False, limit=40000):
    if smoke:
        gen = _fetch_group({"Q5113": "bird"}, limit)
        la = _fetch_group({"Q82042": "part of speech"}, limit)
    else:
        print("[general]", flush=True)
        gen = _fetch_group(GENERAL_ROOTS, limit)
        print("[language_arts]", flush=True)
        la = _fetch_group(LANGUAGE_ARTS_ROOTS, limit)
    out = {"general": gen, "language_arts": la}
    with open(CACHE, "w") as f:
        json.dump(out, f)
    print(f"\ncached: general={len(gen):,} language_arts={len(la):,} -> {CACHE}", flush=True)
    return out


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


async def teach(smoke=False, limit=40000):
    if not os.path.exists(CACHE):
        fetch(smoke=smoke, limit=limit)
    with open(CACHE) as f:
        data = json.load(f)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.database import get_database_manager
        from core.semantics.cognitive_ingress import Provenance
        db = get_database_manager(); await db.initialize()

    label = "wikidata-smoke" if smoke else "wikidata-english-full"
    prior = await _snapshot(db)
    print(f"[{label}] general={len(data['general']):,} language_arts={len(data['language_arts']):,} "
          f"— prior beliefs={prior['beliefs']:,} domains={len(prior['domains'])}", flush=True)

    t0 = time.monotonic()
    group_counts = {}
    for group, domain in (("general", "general"), ("language_arts", "language_arts")):
        edges = data.get(group) or []
        if not edges:
            continue
        total = len(edges)

        def report(c, _g=group, _t=total):
            rate = c["total"] / max(0.001, time.monotonic() - t0)
            print(f"  [{_g}] {c['total']:,}/{_t:,} admitted={c['admitted']:,} "
                  f"already={c['already']:,} refused={c['refused']:,} ({rate:.0f}/s)", flush=True)

        prov = Provenance(producer="teacher", source_id=f"wikidata_{group}",
                          source_type="USER_SUPPLIED")
        facts = [(c.lower(), "isa", p.lower()) for c, p in edges]
        # FAN-OUT ON: each taught fact becomes a belief; the domain crystallizes.
        counts = await learning.learn_facts(facts, provenance=prov, domain=domain,
                                            fan_out=True, remember=False, progress=report)
        group_counts[group] = counts
        report(counts)

    print("  flushing beliefs…", flush=True)
    await _flush()
    post = await _snapshot(db)
    elapsed = time.monotonic() - t0

    os.makedirs(SESS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_doms = [d for d in post["domains"] if d not in set(prior["domains"])]
    lines = [
        f"# Teaching session — {label}",
        f"*{datetime.now(timezone.utc).isoformat()} · Wikidata P279 · fan-out ON "
        f"(beliefs + domain + lexicon) · model-free (no LLM)*", "",
        "## Taught", ]
    for g, c in group_counts.items():
        lines.append(f"- **{g}** (domain `{g}`): `{c}`")
    lines += [f"- Elapsed: {elapsed:.1f}s", "",
        "## Substrate: prior → after", "",
        "| Store | Prior | After | Δ |", "|---|--:|--:|--:|",
        f"| Beliefs (all) | {prior['beliefs']:,} | {post['beliefs']:,} | +{post['beliefs']-prior['beliefs']:,} |",
        f"| Beliefs (`general`) | {prior['by_dom'].get('general',0):,} | {post['by_dom'].get('general',0):,} | +{post['by_dom'].get('general',0)-prior['by_dom'].get('general',0):,} |",
        f"| Beliefs (`language_arts`) | {prior['by_dom'].get('language_arts',0):,} | {post['by_dom'].get('language_arts',0):,} | +{post['by_dom'].get('language_arts',0)-prior['by_dom'].get('language_arts',0):,} |",
        f"| Concepts | {prior['concepts']:,} | {post['concepts']:,} | +{post['concepts']-prior['concepts']:,} |",
        f"| Domains | {len(prior['domains'])} | {len(post['domains'])} | +{len(post['domains'])-len(prior['domains'])} |",
        "", f"**Domains added:** {', '.join(new_doms) if new_doms else '(none new — existing domains reinforced)'}",
        "", "---", ""]
    path = os.path.join(SESS_DIR, f"{ts}_{label}.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"\n=== report -> docs/teaching_sessions/{ts}_{label}.md ===", flush=True)
    print(f"beliefs {prior['beliefs']:,} -> {post['beliefs']:,} "
          f"(+{post['beliefs']-prior['beliefs']:,}) | concepts {prior['concepts']:,} -> {post['concepts']:,} "
          f"| domains {len(prior['domains'])} -> {len(post['domains'])}", flush=True)


if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    lim = 300 if smoke else 40000
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    if "--teach" in sys.argv or smoke:
        asyncio.run(teach(smoke=smoke, limit=lim))
    else:
        fetch(smoke=smoke, limit=lim)
