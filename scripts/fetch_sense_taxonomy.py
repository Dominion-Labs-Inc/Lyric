#!/usr/bin/env python3
"""Fetch the graduate math/CS `subclass of` graph from Wikidata KEYED BY QID.

A Wikidata QID is a SENSE identity: the algebraic group (Q83478) and a collective
group are different items, where the surface word "group" is not. Reasoning over
the QID edges is therefore sense-exact -- it cannot bridge a technical term into a
common-sense homonym the way the name-keyed concept graph does. This pulls, for a
curated set of graduate roots, the P279 edges as (child_qid, child_label,
parent_qid, parent_label), keeping notable children (English Wikipedia article),
and caches them for `core/reasoning/sense_taxonomy.py` to load.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/fetch_sense_taxonomy.py
"""
import os, sys, json, time, urllib.request, urllib.parse, socket

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sense_taxonomy_edges.json")
socket.setdefaulttimeout(240)

# reuse the same verified roots as the concept-graph teach
from teach_graduate_wikidata import MATH_ROOTS, CS_ROOTS  # noqa: E402  (same dir on sys.path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _sparql(query):
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "TorinAI-teach/1.0 (research)"})
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"), strict=False)["results"]["bindings"]


def _root_edges(qid):
    q = """SELECT DISTINCT ?child ?cl ?parent ?pl WHERE {
      ?child wdt:P279* wd:%s . ?child wdt:P279 ?parent .
      ?article schema:about ?child ; schema:isPartOf <https://en.wikipedia.org/> .
      ?child rdfs:label ?cl . FILTER(LANG(?cl)="en")
      ?parent rdfs:label ?pl . FILTER(LANG(?pl)="en")
    } LIMIT 40000""" % qid
    for attempt in range(3):
        try:
            rows = _sparql(q)
            return [(r["child"]["value"].split("/")[-1], r["cl"]["value"],
                     r["parent"]["value"].split("/")[-1], r["pl"]["value"]) for r in rows]
        except Exception as e:
            if attempt == 2:
                print(f"    root {qid} FAILED: {str(e)[:70]}", flush=True)
                return []
            time.sleep(5 * (attempt + 1))


def _parents_of(qids_labels):
    """Direct P279 parents of a batch of QIDs (no article filter, no transitive
    path -- cheap). Returns [(child_qid, child_label, parent_qid, parent_label)]."""
    values = " ".join("wd:" + q for q in qids_labels)
    q = """SELECT ?x ?p ?pl WHERE {
      VALUES ?x { %s } ?x wdt:P279 ?p .
      ?p rdfs:label ?pl . FILTER(LANG(?pl)="en")
    }""" % values
    for attempt in range(3):
        try:
            rows = _sparql(q)
            return [(r["x"]["value"].split("/")[-1], qids_labels[r["x"]["value"].split("/")[-1]],
                     r["p"]["value"].split("/")[-1], r["pl"]["value"]) for r in rows]
        except Exception as e:
            if attempt == 2:
                return []
            time.sleep(5 * (attempt + 1))


def _close_chains(out, seen, field_of):
    """Walk the frontier -- nodes that appear only as parents, never as children,
    so their own upward edges were dropped by the child-article filter -- and
    fetch their direct parents until every chain reaches its root. Cheap
    batched direct-parent lookups, not transitive paths."""
    for _round in range(8):
        children = {e[0] for e in out}
        labels = {}
        for cq, cl, pq, pl, f in out:
            labels[pq] = pl
        frontier = {q: labels[q] for q in (labels.keys() - children)}
        if not frontier:
            break
        added = 0
        keys = list(frontier)
        for i in range(0, len(keys), 200):
            batch = {k: frontier[k] for k in keys[i:i + 200]}
            for cq, cl, pq, pl in _parents_of(batch):
                if cq == pq or (cq, pq) in seen:
                    continue
                seen.add((cq, pq))
                out.append([cq, cl, pq, pl, field_of.get(cq, "mathematics")])
                added += 1
        print(f"  close round {_round + 1}: frontier={len(frontier)} +{added} edges", flush=True)
        if not added:
            break


def main():
    out = []
    seen = set()
    field_of = {}
    for field, roots in (("mathematics", MATH_ROOTS), ("computer_science", CS_ROOTS)):
        for qid, name in roots.items():
            n = 0
            for cq, cl, pq, pl in _root_edges(qid):
                field_of.setdefault(cq, field)
                if cq == pq or (cq, pq) in seen:
                    continue
                seen.add((cq, pq))
                out.append([cq, cl, pq, pl, field])
                n += 1
            print(f"  [{field[:4]}] {name:26} +{n}", flush=True)
    _close_chains(out, seen, field_of)
    with open(CACHE, "w") as f:
        json.dump(out, f)
    print(f"\ncached {len(out):,} QID edges -> {CACHE}", flush=True)
    return out


async def _load(edges):
    from core.database import get_database_manager
    from core.reasoning.sense_taxonomy import load_edges
    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    n = await load_edges(db, edges)
    print(f"loaded {n:,} edges into unified.sense_taxonomy", flush=True)


if __name__ == "__main__":
    import asyncio
    edges = main()
    asyncio.run(_load(edges))
