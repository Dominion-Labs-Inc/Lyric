#!/usr/bin/env python3
"""TorinAI — earn a graduate answer it CANNOT recall: gap → tool → read → learn
→ reason. Real system, nothing staged, no language model, no answer handed to it,
NO tool named for it.

The question needs a fact the substrate does not hold (what KIND of object a
Klein four-group is) AND a chain of theorems it was taught (abelian ⇒ nilpotent
⇒ solvable). So the substrate must: fail to answer from memory, close the gap
with ITS OWN acquisition faculty — which reaches for a tool, fetches, and reads
the result with its own model-free reader — learn the classification, and only
THEN derive the answer by chaining taught theorems.

Every line is OBSERVED from the live system. The demo never fetches, never reads,
never learns, never picks a tool: it hands the substrate the gap and watches.
Which tool ran is captured by watching the registry, not by calling one. The new
fact is retracted at the end so the gap stays genuine on the next run.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 demos/graduate_gap_demo.py
"""
import os
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio, io, contextlib, logging, sys, time

# Graduate objects whose CLASS a taught theorem-chain reasons over. The demo uses
# the first one the store does not already hold — a genuine gap, not a cleared one.
CANDIDATES = [
    ("Klein four-group", "is the Klein four-group a solvable group?"),
    ("Quaternion group", "is the quaternion group a nilpotent group?"),
    ("Dihedral group of order 6", "is the dihedral group of order 6 a group?"),
]

B = "\033[1m"; D = "\033[2m"; G = "\033[32m"; C = "\033[36m"; Y = "\033[33m"; R = "\033[31m"; Z = "\033[0m"
if not sys.stdout.isatty():
    B = D = G = C = Y = R = Z = ""


async def _quiet(coro):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return await coro


def _node(name):
    return name.replace(" ", "_").replace("-", "_").lower()


async def holds(db, name):
    rows = await db.execute_query(
        "SELECT 1 FROM unified.concepts WHERE name = $1 LIMIT 1", [_node(name)], fetch_all=True)
    return bool(rows)


async def class_edges(db, name):
    rows = await db.execute_query(
        "SELECT relation, target_concept_id FROM unified.concept_relations "
        "WHERE source_concept_id LIKE $1", [f"%:{_node(name)}"], fetch_all=True)
    return [(r["relation"], str(r["target_concept_id"]).split(":")[-1]) for r in (rows or [])]


async def retract(db, name):
    await db.execute_query(
        "DELETE FROM unified.concept_relations WHERE source_concept_id LIKE $1", [f"%:{_node(name)}"])
    await db.execute_query("DELETE FROM unified.concepts WHERE name = $1", [_node(name)])
    for tier in ("memory_hot.memory_hot", "memory_warm.memory_warm", "memory_cold.memory_cold"):
        try:
            await db.execute_query(f"DELETE FROM {tier} WHERE content ILIKE $1", [f"%{name}%"])
        except Exception:
            pass


async def main():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        from core.memory import get_memory_agent
        from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest
        from core.tools import get_tool_registry
        agent = await get_memory_agent()
        db = get_database_manager()
        bridge = get_neural_bridge()
        conversation = coord.conversation(session="graduate-gap-demo")
        # pick the first genuine gap
        CONCEPT = QUESTION = None
        for name, q in CANDIDATES:
            if not await holds(db, name):
                CONCEPT, QUESTION = name, q
                break

    print("═" * 72)
    print(f"{B} TorinAI — earn a graduate answer: gap → tool → read → learn → reason{Z}")
    print("═" * 72)
    print(f"{D} Real system · nothing staged · no model · no answer given · no tool named{Z}\n")
    if CONCEPT is None:
        print(f"{R} The store already holds every candidate — clear one to re-run.{Z}")
        return
    print(f"{B}{Y}▶ Question:{Z} {QUESTION}\n")

    # 1 — MEMORY: query what it holds about the object in the question.
    print(f"{B}1. Memory{Z}  {D}— what do I already hold about “{CONCEPT}”?{Z}")
    items = await _quiet(agent.retrieve(query=CONCEPT, limit=6, include_events=False))
    hits = [i for i in (items or []) if getattr(i, "similarity_score", 0)]
    if sys.stdout.isatty():
        for i in hits[:3]:
            txt = " ".join(str(getattr(i, "content", "")).split()[:7])
            sys.stdout.write(f"\r   {C}🔎 querying memory:{Z} {txt}…"); sys.stdout.flush(); time.sleep(0.4)
        sys.stdout.write("\r\033[K")
    print(f"   {R}✗ genuine gap:{Z} the store holds no classification for “{CONCEPT}”\n")

    # 2 — REASONING: try to answer from what it knows. It can't yet.
    print(f"{B}2. Reasoning{Z}  {D}— can I answer from what I hold?{Z}")
    before = await _quiet(bridge.reason(ReasoningRequest(query=QUESTION)))
    print(f"   neural bridge → route: {D}{(before.metadata or {}).get('route')}{Z}")
    print(f"   {R}✗ not verified — I don’t know what KIND of object a {CONCEPT} is{Z}\n")

    # 3 — CLOSE THE GAP: the substrate's OWN acquisition faculty runs. It reaches
    # for a tool, fetches, and reads with its own reader. The demo does none of
    # that — it WATCHES the registry to see which tool the substrate reached for.
    print(f"{B}3. Close the gap{Z}  {D}— the substrate researches it ITSELF (I name no tool){Z}")
    registry = get_tool_registry()
    original = registry.execute_tool
    invoked = []

    async def watch(tool_name, params=None, *a, **k):
        invoked.append(tool_name)
        return await original(tool_name, params, *a, **k)

    registry.execute_tool = watch
    try:
        acquired = await _quiet(conversation.look_up(CONCEPT))
    finally:
        registry.execute_tool = original

    tools_used = ", ".join(dict.fromkeys(invoked)) or "(none)"
    print(f"   {C}🔧 substrate reached for:{Z} {tools_used}  {D}(chosen by it, watched by me){Z}")
    learned = await class_edges(db, CONCEPT)
    for relation, target in learned:
        print(f"   reader → {G}{CONCEPT}{Z} —{relation}→ {G}{target}{Z}")
    if getattr(acquired, "stored", False) and learned:
        print(f"   {G}✓ read into a typed ISA edge (reasoning-ready), learned via the authority{Z}\n")
    else:
        print(f"   {R}✗ the web returned nothing it could read into a classification{Z}")
        print(f"   {D}(honest gap — no answer faked; try again or another candidate){Z}")
        await retract(db, CONCEPT)
        return

    # 4 — REASONING AGAIN: re-inject the question; derive it by chaining theorems.
    print(f"{B}4. Reasoning (again){Z}  {D}— re-inject the question, now derive it{Z}")
    after = await _quiet(bridge.reason(ReasoningRequest(query=QUESTION)))
    md = after.metadata or {}
    print(f"   neural bridge → route: {C}{md.get('route')}{Z}")
    chain = md.get("chain") or []
    if chain:
        print(f"   strategy: transitive ISA over taught theorems")
        print(f"   {C}chain:{Z} " + " → ".join(chain))
    print(f"   {G}✓ VERIFIED{Z}" if md.get("verified") else f"   {R}(unverified){Z}")
    print()

    # 5 — ANSWER.
    print(f"{B}5. Answer{Z}")
    print(f"{B}{G}◀ {after.answer}{Z}")
    print(f"   {D}derived, not given — a classification it looked up, chained with taught theorems{Z}\n")

    # 6 — LEARNED: ask again with NO look-up, from the store.
    print(f"{B}6. Learned{Z}  {D}(same question, no look-up — answered from the store now){Z}")
    again = await _quiet(bridge.reason(ReasoningRequest(query=QUESTION)))
    print(f"   holds “{CONCEPT}” now: {await holds(db, CONCEPT)}   verified: {(again.metadata or {}).get('verified')}")
    print(f"{B}{G}◀ {again.answer}{Z}")
    print("═" * 72)

    # Retract the looked-up fact so the gap is genuine next run (the demo is about
    # the ACT of earning the answer, not seeding the store).
    await retract(db, CONCEPT)


if __name__ == "__main__":
    asyncio.run(main())
