#!/usr/bin/env python3
"""KNOWS-WORDNET-01 — does the substrate actually KNOW what it was taught?

A teaching run reports how many facts it ADMITTED. That is a claim about the
writer, not about the substrate: it says an edge was accepted, not that the
substrate can be asked and will answer. This asks.

The source of truth is `WordNetSource` itself -- the same records the teaching
pass offers -- so the question is always "you were offered this; do you hold
it?", never a question about some other corpus.

FOUR LEVELS, reported separately, because they are different claims:

  ADMITTED   the edge is in the concept graph (a store read)
  DERIVABLE  the reasoning authority answers YES when asked (graph reasoning,
             so a fact reachable only by transitivity still counts as known)
  CLASSED    the part of speech the source stated is held for that word
  SAYABLE    the substrate can put the fact back into words

AND A NEGATIVE CONTROL, without which the numbers above mean nothing: pairs
built from real WordNet terms that WordNet does NOT relate. A substrate that
answers YES to everything scores 100% on recall and 0% here. Both are printed;
neither is meaningful alone.

Nothing is taught by this experiment. It only asks.

    ./venv_lyric/bin/python3 experiments/KNOWS-WORDNET-01/experiment.py [N]
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
logging.disable(logging.INFO)

SAMPLE = int(sys.argv[1]) if len(sys.argv) > 1 else 500
SEED = 20260924


def say(*a):
    print(*a, flush=True)


async def main() -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        from core.learning.teaching_sources import WordNetSource
        from core.reasoning.concept_graph_reasoning import answer_over_graph
        from core.reasoning.relation_algebra import TRUE
        from core.semantics.relation_types import SemanticRelation
        from core.semantics.cognitive_ingress import normalize_term
        db = get_database_manager()

    # ── the source of truth: what WordNet OFFERS ────────────────────────────
    source = WordNetSource()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        offered = list(source.records())
    facts = [r for r in offered if r.relation and r.subject and r.obj]
    classed = [(w, c) for r in offered for w, c in (r.word_classes or ())]
    say(f"WordNet offers {len(facts):,} facts and {len(classed):,} stated "
        f"word classes")

    rng = random.Random(SEED)
    asked = rng.sample(facts, min(SAMPLE, len(facts)))
    asked_classes = rng.sample(classed, min(SAMPLE, len(classed))) if classed else []
    say(f"asking about {len(asked)} facts and {len(asked_classes)} word classes "
        f"(seed {SEED})\n")

    # ── 1. ADMITTED: is the edge in the graph? ──────────────────────────────
    admitted = 0
    for r in asked:
        rows = await db.execute_query(
            "SELECT 1 FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
            "WHERE c.name = $1 AND cr.relation = $2 "
            "AND (cr.target_surface = $3 OR EXISTS ("
            "  SELECT 1 FROM unified.concepts c2 "
            "  WHERE c2.concept_id = cr.target_concept_id AND c2.name = $3)) "
            "LIMIT 1",
            (normalize_term(r.subject), r.relation, normalize_term(r.obj)))
        admitted += bool(rows)

    # ── 2. DERIVABLE: does the reasoning authority answer YES? ──────────────
    derivable = 0
    for r in asked:
        try:
            rel = SemanticRelation(r.relation)
        except ValueError:
            continue
        ans = await answer_over_graph(db, r.subject, rel, r.obj, max_hops=4)
        derivable += (ans.verdict == TRUE)

    # ── 3. CLASSED: is the stated part of speech held? ──────────────────────
    # Word classes live in the WARM VIEW the memory agent derives from what it
    # remembers being told -- there is no second word-class store to read.
    # Polysemy is not a contradiction, so a word is CLASSED when the stated
    # class is among those with net-positive evidence, not when it is the only
    # one.
    from core.agents.memory_agent import get_memory_agent
    agent = await get_memory_agent()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        warm = await agent.warm_word_classes()
    say(f"warm word-class view holds {warm:,} words")
    held_classes = 0
    for word, want in asked_classes:
        observed = agent.word_classes(word) or {}
        held_classes += int(observed.get(str(want).upper(), 0) > 0)

    # ── 4. SAYABLE: can it put a known fact back into words? ────────────────
    sayable = 0
    spoken = []
    conversation = coord.conversation("knows_wordnet_01")
    for r in asked[:25]:
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                understanding = await conversation.understand(
                    f"what is a {r.subject}?")
            said = getattr(understanding, "reply", "")
        except Exception:
            said = ""
        text = str(said or "")
        if normalize_term(r.obj).split()[-1].lower() in text.lower():
            sayable += 1
            if len(spoken) < 3:
                spoken.append(text[:110])

    # ── 5. NEGATIVE CONTROL: pairs WordNet does NOT relate ──────────────────
    #
    # Without this the recall figures are unfalsifiable: a substrate that says
    # YES to everything scores 100% above. Subjects and objects are drawn from
    # REAL WordNet terms and paired at random, then any pair the source
    # actually asserts is dropped -- so a YES here is a fact the substrate
    # invented, not one it was taught.
    real_pairs = {(normalize_term(r.subject), normalize_term(r.obj))
                  for r in facts}
    subjects = [r.subject for r in rng.sample(facts, min(400, len(facts)))]
    objects = [r.obj for r in rng.sample(facts, min(400, len(facts)))]
    controls, guard = [], 0
    while len(controls) < min(200, SAMPLE) and guard < 20000:
        guard += 1
        s, o = rng.choice(subjects), rng.choice(objects)
        if s == o or (normalize_term(s), normalize_term(o)) in real_pairs:
            continue
        controls.append((s, o))
    invented = 0
    for s, o in controls:
        ans = await answer_over_graph(db, s, SemanticRelation.ISA, o, max_hops=4)
        invented += (ans.verdict == TRUE)

    # ── report ──────────────────────────────────────────────────────────────
    n, nc = len(asked), len(asked_classes) or 1
    pct = lambda a, b: f"{100.0 * a / b:5.1f}%" if b else "  n/a"
    say("==== KNOWS-WORDNET-01 ====")
    say(f"  ADMITTED   {admitted:5}/{n:<5} {pct(admitted, n)}  the edge is in the graph")
    say(f"  DERIVABLE  {derivable:5}/{n:<5} {pct(derivable, n)}  the authority answers YES")
    say(f"  CLASSED    {held_classes:5}/{nc:<5} {pct(held_classes, nc)}  the stated part of speech is held")
    say(f"  SAYABLE    {sayable:5}/{min(25, n):<5} {pct(sayable, min(25, n))}  it can say the fact back")
    say(f"  INVENTED   {invented:5}/{len(controls):<5} {pct(invented, len(controls))}  "
        f"*** must be ~0: pairs WordNet does NOT relate ***")
    for line in spoken:
        say(f"    said: {line}")

    record = {
        "experiment": "KNOWS-WORDNET-01",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED, "sample": SAMPLE,
        "offered": {"facts": len(facts), "word_classes": len(classed)},
        "asked": {"facts": n, "word_classes": len(asked_classes),
                  "sayable": min(25, n), "controls": len(controls)},
        "admitted": admitted, "derivable": derivable,
        "classed": held_classes, "sayable": sayable, "invented": invented,
    }
    (HERE / "results").mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (HERE / "results" / f"{stamp}.json").write_text(json.dumps(record, indent=2))
    say(f"\n  run record: experiments/KNOWS-WORDNET-01/results/{stamp}.json")
    sys.stdout.flush()
    os._exit(0)


asyncio.run(main())
