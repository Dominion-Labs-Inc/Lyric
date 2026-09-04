#!/usr/bin/env python3
"""TEACH the substrate the full graduate mathematics + CS concept taxonomy from
Wikidata, through the ONE learning path.

Wikidata's `subclass of` (P279) graph is a hand-built knowledge resource, like
WordNet -- and a subclass edge IS a chainable implication: "every Banach space
is a vector space". This pulls the P279 subclass edges under a curated set of
graduate math and CS roots, keeping only NOTABLE concepts (those with an English
Wikipedia article, which drops Wikidata's obscure article-less long tail), and
teaches each `child isa parent` through `learning.learn_facts` -- the same
concept graph the reasoner already walks for `ocelot isa animal`.

  --fetch    pull edges from Wikidata into the cache, then stop
  --teach    teach from the cache (fetches first if the cache is missing)
Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/teach_graduate_wikidata.py --fetch
"""
import os, sys, json, time, urllib.request, urllib.parse, socket, io, contextlib, asyncio

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graduate_wikidata_edges.json")
socket.setdefaulttimeout(240)

MATH_ROOTS = {
    # algebraic structure (Q205464) is dropped: its 18k+ result comes back
    # truncated/malformed, and its content is covered by the specific algebra
    # roots below plus the cross-closures (topological/Lie groups, etc.).
    "Q179899": "topological space",
    "Q125977": "vector space", "Q719395": "category", "Q161172": "ring",
    "Q190109": "field", "Q11563": "number", "Q83478": "group",
    "Q11348": "function", "Q203920": "manifold", "Q192276": "measure",
    "Q44337": "matrix", "Q18848": "module", "Q200726": "probability distribution",
    "Q11214": "differential equation",
}
CS_ROOTS = {
    "Q8366": "algorithm", "Q175263": "data structure",
    "Q176452": "finite-state machine", "Q373045": "formal grammar",
    "Q908207": "complexity class", "Q1056428": "type theory",
    "Q192161": "formal language", "Q787116": "automaton",
    "Q787114": "abstract machine", "Q163310": "turing machine",
    "Q9143": "programming language", "Q3262192": "decision problem",
    "Q205084": "computational complexity", "Q2651576": "model of computation",
}


def _sparql(query):
    url = "https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={"User-Agent": "TorinAI-teach/1.0 (research)"})
    text = urllib.request.urlopen(req).read().decode("utf-8")
    # strict=False: some Wikidata labels carry raw control characters that break
    # strict JSON parsing; they are data, not a reason to lose the whole response.
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
    out = {"mathematics": [], "computer_science": []}
    for field, roots in (("mathematics", MATH_ROOTS), ("computer_science", CS_ROOTS)):
        seen = set()
        for qid, name in roots.items():
            edges = _root_edges(qid)
            fresh = [(c, p) for (c, p) in edges
                     if c.lower() != p.lower() and (c.lower(), p.lower()) not in seen]
            for c, p in fresh:
                seen.add((c.lower(), p.lower()))
            out[field].extend([c, p] for c, p in fresh)
            print(f"  [{field[:4]}] {name:26} +{len(fresh):5} (root total {len(edges)})", flush=True)
    with open(CACHE, "w") as f:
        json.dump(out, f)
    print(f"\ncached: {len(out['mathematics']):,} math + "
          f"{len(out['computer_science']):,} CS edges -> {CACHE}", flush=True)
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
    prov = Provenance(producer="teacher", source_id="wikidata_graduate",
                      source_type="USER_SUPPLIED")
    for field in ("mathematics", "computer_science"):
        edges = data[field]
        total = len(edges)
        t0 = time.monotonic()

        def report(c):
            rate = c["total"] / max(0.001, time.monotonic() - t0)
            print(f"  [{field}] {c['total']:,}/{total:,} admitted={c['admitted']:,} "
                  f"already={c['already']:,} refused={c['refused']:,} ({rate:.0f}/s)", flush=True)

        facts = ((c.lower(), "isa", p.lower()) for c, p in edges)
        counts = await learning.learn_facts(facts, provenance=prov, domain=field,
                                            fan_out=False, remember=False, progress=report)
        report(counts)


if __name__ == "__main__":
    if "--teach" in sys.argv:
        asyncio.run(teach())
    else:
        fetch()
