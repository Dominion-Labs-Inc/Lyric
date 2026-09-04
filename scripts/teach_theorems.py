#!/usr/bin/env python3
"""TEACH the substrate graduate mathematics and computer science as held rules.

Each theorem in `data/graduate_theorems.py` is taught through the ONE learning
path (`learning.learn_rule` -> the held-conditional store the reasoner chains
over). After teaching, a handful of chains are PROVED end to end: a single
supposition is admitted as a fact and a conclusion several theorems away is
asked, and the substrate must return it verified, by chaining -- not asserted.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/teach_theorems.py
"""
import os, sys, asyncio, io, contextlib
os.environ.setdefault("TQDM_DISABLE", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graduate_theorems import MATH, CS, as_rules


#: (field domain, supposition subject+property, asked conclusion) -- a chain the
#: taught rules must PROVE, each conclusion two or more theorems from the fact.
_CHECKS = [
    ("mathematics", "complex function", "holomorphic", "is the complex function smooth?"),
    ("mathematics", "space", "hilbert", "is the space metric?"),
    ("mathematics", "matrix", "real symmetric", "is the matrix diagonalizable?"),
    ("mathematics", "ring", "euclidean domain", "is the ring an integral domain?"),
    ("computer_science", "formal language", "regular", "is the formal language recursively enumerable?"),
    ("computer_science", "decision problem", "np complete", "is the decision problem in pspace?"),
    ("computer_science", "graph", "tree", "is the graph bipartite?"),
]


async def _teach(learning, prov, entries, domain):
    from core.semantics.cognitive_ingress import Provenance
    admitted = already = refused = 0
    for antecedent, consequent, surface in as_rules(entries):
        adm = await learning.learn_rule(antecedent, consequent, surface=surface,
                                        provenance=prov, domain=domain)
        if getattr(adm, "already_present", False):
            already += 1
        elif getattr(adm, "admitted", False):
            admitted += 1
        else:
            refused += 1
            print(f"  REFUSED: {surface}  -> {getattr(adm,'refusals',None)}", flush=True)
    return admitted, already, refused


async def main():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        s = get_system(); await s.initialize()
        learning = s.autonomous_coordinator.learning
        from core.semantics.cognitive_ingress import Provenance
        from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
        bridge = get_neural_bridge()
    prov = Provenance(producer="teacher", source_id="graduate_theorems",
                      source_type="USER_SUPPLIED")

    for label, entries, domain in (("mathematics", MATH, "mathematics"),
                                   ("computer science", CS, "computer_science")):
        a, al, r = await _teach(learning, prov, entries, domain)
        print(f"{label}: {a} taught, {al} already held, {r} refused "
              f"(of {len(entries)})", flush=True)

    print("\nproving chains end to end:", flush=True)
    proved = 0
    for domain, subject, prop, question in _CHECKS:
        # admit the single supposition as a typed fact (isa loads into the graph)
        await learning.learn_fact(subject, "isa", prop, provenance=prov, domain=domain)
        res = await bridge.reason(ReasoningRequest(query=question))
        md = res.metadata or {}
        ok = bool(md.get("verified")) and "held_rules" in (md.get("route") or [])
        proved += ok
        chain = " -> ".join(md.get("chain") or []) if ok else ""
        print(f"  [{'PROVED' if ok else 'no'}] given a {subject} is {prop}: "
              f"{question}  {chain}", flush=True)
        # retract the supposition -- it was a query input, not a taught fact
        from core.database import get_database_manager
        db = get_database_manager()
        await db.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id LIKE $1 "
            "AND target_surface = $2",
            [f"%:{subject.replace(' ', '_')}", prop.replace(" ", "_")])
    print(f"\n{proved}/{len(_CHECKS)} chains proved.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
