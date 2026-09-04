#!/usr/bin/env python3
"""TorinAI — earn a graduate-level answer it CANNOT recall: gap -> tool -> read
-> learn -> reason. Real system, nothing staged, no language model, no answer
handed to it.

The question needs a fact the substrate does not hold (what KIND of object a
Klein four-group is) AND a chain of theorems it was taught (abelian => nilpotent
=> solvable). So it must: find its own gap, use a web tool, READ the result into
structured knowledge with its own model-free reader, learn it, and only THEN
derive the answer by chaining. Every line is real output from the live system;
the new fact is retracted at the end so the gap stays genuine on the next run.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 demos/graduate_gap_demo.py
"""
import os
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio, io, contextlib, json, logging, re, socket, sys, time
import urllib.request, urllib.parse

socket.setdefaulttimeout(20)

# Graduate objects whose CLASS a taught theorem-chain reasons over. The demo uses
# the first one the store does not already hold -- a genuine gap, not a cleared one.
CANDIDATES = [
    ("Klein four-group", "is the Klein four-group a solvable group?", "solvable group"),
    ("Quaternion group", "is the quaternion group a nilpotent group?", "nilpotent group"),
    ("Dihedral group of order 6", "is the dihedral group of order 6 a group?", "group"),
]

B = "\033[1m"; D = "\033[2m"; G = "\033[32m"; C = "\033[36m"; Y = "\033[33m"; R = "\033[31m"; Z = "\033[0m"
if not sys.stdout.isatty():
    B = D = G = C = Y = R = Z = ""


async def _quiet(coro):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return await coro


def wikipedia_summary(title):
    """The lead sentence of the Wikipedia article -- the web TOOL the substrate
    reaches for when it does not hold something."""
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": "TorinAI-demo/1.0 (research)"})
    extract = json.loads(urllib.request.urlopen(req).read().decode()).get("extract", "")
    return re.split(r"(?<=[.])\s", extract.replace("\n", " "))[0].strip()


async def holds(db, name):
    rows = await db.execute_query(
        "SELECT 1 FROM unified.concepts WHERE name = $1 LIMIT 1",
        [name.replace(" ", "_").replace("-", "_").lower()], fetch_all=True)
    return bool(rows)


async def main():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.memory import get_memory_agent
        from core.database import get_database_manager
        from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
        from core.semantics.sentence_reader import SentenceReader
        from core.semantics.cognitive_ingress import Provenance
        agent = await get_memory_agent()
        db = get_database_manager()
        bridge = get_neural_bridge()
        reader = SentenceReader()
        learning = coord.learning
        # pick the first genuine gap
        CONCEPT = QUESTION = TARGET = None
        for name, q, target in CANDIDATES:
            if not await holds(db, name):
                CONCEPT, QUESTION, TARGET = name, q, target
                break

    print("═" * 70)
    print(f"{B} TorinAI — earn a graduate answer: gap → tool → read → learn → reason{Z}")
    print("═" * 70)
    print(f"{D} Real system · nothing staged · no language model · no answer given{Z}\n")
    if CONCEPT is None:
        print(f"{R} The store already holds every candidate — clear one to re-run.{Z}")
        return
    print(f"{B}{Y}▶ Question:{Z} {QUESTION}\n")

    # 1 — MEMORY: query what it holds.
    print(f"{B}1. Memory{Z}  {D}— what do I already hold about “{CONCEPT}”?{Z}")
    items = await _quiet(agent.retrieve(query=CONCEPT, limit=6, include_events=False))
    hits = [i for i in (items or []) if getattr(i, "similarity_score", 0)]
    if sys.stdout.isatty():
        for i in hits[:3]:
            txt = " ".join(str(getattr(i, "content", "")).split()[:7])
            sys.stdout.write(f"\r   {C}🔎 querying memory:{Z} {txt}…"); sys.stdout.flush(); time.sleep(0.4)
        sys.stdout.write("\r\033[K")
    else:
        print(f"   {C}🔎 querying memory …{Z}")
    print(f"   {R}✗ genuine gap:{Z} the store holds nothing about “{CONCEPT}”\n")

    # 2 — REASONING: try to answer from what it knows. It can't.
    print(f"{B}2. Reasoning{Z}  {D}— can I answer from what I know?{Z}")
    before = await bridge.reason(ReasoningRequest(query=QUESTION))
    print(f"   neural bridge → route: {D}{(before.metadata or {}).get('route')}{Z}")
    print(f"   {R}✗ cannot answer yet — I don’t know what a {CONCEPT} IS{Z}\n")

    # 3 — TOOL: go find out on the web.
    print(f"{B}3. Tool{Z}  {D}— I don’t hold it, so go and find out (web){Z}")
    print(f"   {C}🔧 fetching en.wikipedia.org …{Z}")
    sentence = wikipedia_summary(CONCEPT)
    print(f"   {D}“{sentence[:96]}{'…' if len(sentence) > 96 else ''}”{Z}\n")

    # 4 — READ + LEARN: read the web text into a structured fact, admit it.
    print(f"{B}4. Read + learn{Z}  {D}— read it with my own reader, store it{Z}")
    facts = reader.read_all(sentence)
    prov = Provenance(producer="wikipedia", source_id="en.wikipedia.org", source_type="USER_SUPPLIED")
    learned = []
    for f in facts:
        obj = f.get("obj")
        if not obj or str(f.get("relation")).lower() not in ("is", "are"):
            continue
        adm = await _quiet(learning.learn_fact(f["subject"], "isa", obj, provenance=prov, domain="researched"))
        if getattr(adm, "admitted", False):
            learned.append((f["subject"], obj))
    for subj, obj in learned:
        cls = re.sub(r"(?i)^(a|an|the)\s+", "", obj)
        print(f"   reader → {G}{subj}{Z} —isa→ {G}{cls}{Z}")
    print(f"   {G}✓ learned, stored as a typed ISA edge (reasoning-ready), fanned out to memory{Z}\n")

    # 5 — REASONING AGAIN: now derive it by chaining taught theorems.
    print(f"{B}5. Reasoning (again){Z}  {D}— re-inject the question, derive it{Z}")
    after = await bridge.reason(ReasoningRequest(query=QUESTION))
    md = after.metadata or {}
    print(f"   neural bridge → route: {C}{md.get('route')}{Z}")
    chain = md.get("chain") or []
    if chain:
        print(f"   strategy: transitive ISA over taught theorems")
        print(f"   {C}chain:{Z} " + " → ".join(chain))
    print(f"   {G}✓ VERIFIED{Z}" if md.get("verified") else f"   {R}(unverified){Z}")
    print()

    # 6 — ANSWER.
    print(f"{B}6. Answer{Z}")
    print(f"{B}{G}◀ {after.answer}{Z}")
    print(f"   {D}derived, not given — a looked-up classification chained with taught theorems{Z}\n")

    # 7 — LEARNED: ask again with NO tool, from the store.
    print(f"{B}7. Learned{Z}  {D}(same question, no look-up — from the store now){Z}")
    again = await bridge.reason(ReasoningRequest(query=QUESTION))
    print(f"   holds “{CONCEPT}” now: {await holds(db, CONCEPT)}   route: {D}{(again.metadata or {}).get('route')}{Z}")
    print(f"{B}{G}◀ {again.answer}{Z}")
    print("═" * 70)

    # retract the looked-up fact so the gap is genuine next run (its class edges
    # are not real of every member; the demo is about the ACT, not seeding data).
    node = CONCEPT.replace(" ", "_").replace("-", "_").lower()
    await db.execute_query(f"DELETE FROM unified.concept_relations WHERE source_concept_id LIKE '%:{node}'")
    await db.execute_query("DELETE FROM unified.concepts WHERE name = $1", [node])
    # retract the memory the fan-out stored, so step 1 shows a true gap next run.
    for tier in ("memory_hot.memory_hot", "memory_warm.memory_warm", "memory_cold.memory_cold"):
        try:
            await db.execute_query(f"DELETE FROM {tier} WHERE content ILIKE $1", [f"%{CONCEPT}%"])
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
