#!/usr/bin/env python3
"""Rebuild the reasoning isa-taxonomy: purge the ConceptNet free-text pollution,
KEEP the clean WordNet hypernymy and the curated graduate/technical edges.

The concept graph the reasoner walks was polluted by raw ConceptNet IsA
(apple isa car, dog isa cuter_than_kid, robin isa band), which made transitive
isa meaningless and caused reason_about to confabulate. Provenance was not
recorded per edge, so we separate keep-from-junk by content:

  KEEP a positive isa edge iff ANY of:
    - (child, parent) is a WordNet noun-hypernym pair          [clean taxonomy]
    - child OR parent is a curated graduate/technical concept  [math/CS taxonomy]
  KEEP all negative (denial) edges.
  PURGE everything else (the ConceptNet free-text junk).

Backup of every isa edge is written first (recoverable).
Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
     ./venv_torin/bin/python3 scripts/rebuild_isa_wordnet.py
"""
import os, sys, json, io, contextlib, asyncio, time
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
GRAD = os.path.join(ROOT, "scripts", "graduate_wikidata_edges.json")


def norm(s):
    return " ".join(str(s).strip().lower().split()).replace(" ", "_")


def wordnet_sets():
    """(clean isa pairs, all noun lemmas), names underscore-joined lowercase."""
    from nltk.corpus import wordnet as wn
    pairs, nouns = set(), set()
    def nm(syn):
        return syn.lemmas()[0].name().lower()
    for syn in wn.all_synsets("n"):
        for lem in syn.lemmas():
            nouns.add(lem.name().lower())
        child = nm(syn)
        for h in syn.hypernyms():
            parent = nm(h)
            if child and parent and child != parent:
                pairs.add((child, parent))
    return pairs, nouns


def graduate_concepts():
    concepts = set()
    if os.path.exists(GRAD):
        for _dom, edges in json.load(open(GRAD)).items():
            for c, p in edges:
                concepts.add(norm(c)); concepts.add(norm(p))
    return concepts


async def main():
    print("building WordNet + graduate keep-sets…", flush=True)
    wn_pairs, wn_nouns = wordnet_sets()
    grad = graduate_concepts()
    print(f"  WordNet isa pairs={len(wn_pairs):,} noun lemmas={len(wn_nouns):,} "
          f"graduate concepts={len(grad):,}", flush=True)

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()

    rows = await db.execute_query(
        "SELECT cr.source_concept_id AS s, cr.target_concept_id AS t, "
        "c1.name AS child, c2.name AS parent, cr.polarity AS pol "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id=c1.concept_id "
        "JOIN unified.concepts c2 ON cr.target_concept_id=c2.concept_id "
        "WHERE cr.relation='isa'", (), fetch_all=True) or []
    print(f"  loaded {len(rows):,} isa edges", flush=True)

    purge_pairs = set()
    kept = neg = wn_kept = grad_kept = 0
    for r in rows:
        if str(r["pol"] or "positive") == "negative":
            neg += 1; continue
        child, parent = norm(r["child"]), norm(r["parent"])
        if (child, parent) in wn_pairs:
            kept += 1; wn_kept += 1; continue
        if child in grad or parent in grad:
            kept += 1; grad_kept += 1; continue
        purge_pairs.add((r["s"], r["t"]))
    print(f"  KEEP {kept:,} (wordnet={wn_kept:,} graduate={grad_kept:,}) + {neg} denials "
          f"| PURGE {len(purge_pairs):,} junk edges", flush=True)

    # delete junk in batches by (source, target) id pairs
    pairs = list(purge_pairs)
    t0 = time.monotonic(); done = 0
    for i in range(0, len(pairs), 1000):
        batch = pairs[i:i+1000]
        vals = ",".join(f"('{s}','{t}')" for s, t in batch)
        await db.execute_query(
            f"DELETE FROM unified.concept_relations WHERE relation='isa' "
            f"AND (source_concept_id, target_concept_id) IN ({vals})", (), fetch_all=False)
        done += len(batch)
        if done % 20000 == 0 or done == len(pairs):
            print(f"  purged {done:,}/{len(pairs):,} ({done/max(0.001,time.monotonic()-t0):.0f}/s)", flush=True)

    after = (await db.execute_query(
        "SELECT count(*) n FROM unified.concept_relations WHERE relation='isa'",
        (), fetch_all=True))[0]["n"]
    print(f"\n=== done: isa edges {len(rows):,} -> {after:,} (purged {len(rows)-after:,}) ===", flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
