#!/usr/bin/env python3
"""TEACH the substrate a broad slice of general-knowledge taxonomy from Wikidata,
through the ONE teaching path — the same shape as teach_graduate_wikidata.py.

Wikidata's `subclass of` (P279) graph is a hand-built knowledge resource like
WordNet, and a subclass edge IS a chainable implication ("every sparrow is a
bird"). This pulls P279 edges under broad everyday roots (animals, plants, food,
vehicles, …), keeps only NOTABLE concepts (those with an English Wikipedia
article — dropping Wikidata's obscure article-less long tail), and admits each
`child isa parent` through `learning.learn_facts` with WIKIDATA provenance — the
authoritative teaching channel, never the conversation path.

  --fetch    pull edges from Wikidata into the cache, then stop
  --teach    teach from the cache (fetches first if the cache is missing)
Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/teach_general_wikidata.py --fetch
"""
import os, sys, json, time, urllib.request, urllib.parse, socket, io, contextlib, asyncio

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "general_wikidata_edges.json")
socket.setdefaulttimeout(240)

# Broad everyday roots. Per-root counts are printed on --fetch, so a mistyped QID
# shows +0 and can be dropped. Kept to a manageable first slice; add roots to scale.
GENERAL_ROOTS = {
    "Q729": "animal",
    "Q756": "plant",
    "Q2095": "food",
    "Q42889": "vehicle",
    "Q11344": "chemical element",
    "Q34770": "language",
    "Q34379": "musical instrument",
    "Q12136": "disease",
    "Q39546": "tool",
    "Q41176": "building",
    "Q15324": "body of water",
    "Q349": "sport",
    "Q7278": "political ideology",
    "Q11436": "aircraft",
    "Q334166": "occupation",
}


def _sparql(query):
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "TorinAI-teach/1.0 (research)"})
    text = urllib.request.urlopen(req).read().decode("utf-8")
    return json.loads(text, strict=False)["results"]["bindings"]


def _root_edges(qid):
    """(child_label, parent_label) P279 edges in this root's closure, child
    notable (has an English Wikipedia article), both English-labeled."""
    q = """SELECT DISTINCT ?cl ?pl WHERE {
      ?child wdt:P279* wd:%s . ?child wdt:P279 ?parent .
      ?article schema:about ?child ; schema:isPartOf <https://en.wikipedia.org/> .
      ?child rdfs:label ?cl . FILTER(LANG(?cl)="en")
      ?parent rdfs:label ?pl . FILTER(LANG(?pl)="en")
    } LIMIT 40000""" % qid
    for attempt in range(3):
        try:
            return [(r["cl"]["value"], r["pl"]["value"]) for r in _sparql(q)]
        except Exception as e:
            if attempt == 2:
                print(f"    root {qid} FAILED: {str(e)[:70]}", flush=True)
                return []
            time.sleep(5 * (attempt + 1))


def fetch():
    out = {"general": []}
    seen = set()
    for qid, name in GENERAL_ROOTS.items():
        edges = _root_edges(qid)
        fresh = [(c, p) for (c, p) in edges
                 if c.lower() != p.lower() and (c.lower(), p.lower()) not in seen]
        for c, p in fresh:
            seen.add((c.lower(), p.lower()))
        out["general"].extend([c, p] for c, p in fresh)
        print(f"  {name:22} +{len(fresh):5} (root total {len(edges)})", flush=True)
    with open(CACHE, "w") as f:
        json.dump(out, f)
    print(f"\ncached: {len(out['general']):,} edges -> {CACHE}", flush=True)
    return out


async def teach():
    if not os.path.exists(CACHE):
        fetch()
    with open(CACHE) as f:
        data = json.load(f)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.semantics.cognitive_ingress import Provenance
    prov = Provenance(producer="teacher", source_id="wikidata_general",
                      source_type="USER_SUPPLIED")
    edges = data["general"]
    total = len(edges)
    t0 = time.monotonic()

    def report(c):
        rate = c["total"] / max(0.001, time.monotonic() - t0)
        print(f"  {c['total']:,}/{total:,} admitted={c['admitted']:,} "
              f"already={c['already']:,} refused={c['refused']:,} ({rate:.0f}/s)", flush=True)

    facts = ((c.lower(), "isa", p.lower()) for c, p in edges)
    counts = await learning.learn_facts(facts, provenance=prov, domain="general",
                                        fan_out=False, remember=False, progress=report)
    report(counts)


if __name__ == "__main__":
    if "--teach" in sys.argv:
        asyncio.run(teach())
    else:
        fetch()
