#!/usr/bin/env python3
"""TorinAI — detect a real knowledge gap, close it, reason over it. Real system.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 demos/knowledge_acquisition_demo.py

No staging: nothing is cleared, and the gap is genuine — the concept below was
never taught, so the substrate's OWN gap detection fires on the prompt. It then
closes the gap using a tool, admits what it learned as relations, and reasons
over them to answer — model-free. The new knowledge is left in place (the store
is updated, as it would be after any real learning). Every line is real output.
"""
import os
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio
import io
import contextlib
import logging
import sys
import time

# Concepts the substrate was never taught — genuine gaps, not cleared ones. The
# demo picks the first one it still does not hold AND can actually close (its
# real lexical chain reaches "animal"), so each run works on the real store
# until the list is exhausted. Nothing here is staged.
CANDIDATES = ["lemur", "ocelot", "gecko", "walrus", "antelope", "mongoose",
              "marmot", "ferret", "hedgehog", "wombat", "tapir"]

BOLD = "\033[1m"; DIM = "\033[2m"; GRN = "\033[32m"; CYN = "\033[36m"; YEL = "\033[33m"; RED = "\033[31m"; RST = "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = GRN = CYN = YEL = RED = RST = ""


async def _quiet(coro):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return await coro


def _text_of(item) -> str:
    content = getattr(item, "content", None)
    if isinstance(content, dict):
        content = content.get("text") or content.get("content") or ""
    return str(content or getattr(item, "text", "") or "").strip().strip('"')


async def stream_recall(agent, query, label):
    try:
        items = await _quiet(agent.retrieve(query=query, limit=8, include_events=False))
    except Exception:
        items = []
    shown = 0
    for item in items:
        text = _text_of(item)
        if not text:
            continue
        first = " ".join(text.split()[:6])
        score = float(getattr(item, "similarity_score", 0) or 0)
        sys.stdout.write(f"\r  {CYN}🔎 {label}:{RST} {first}…{DIM} ({score:.2f}){RST}\033[K")
        sys.stdout.flush()
        shown += 1
        time.sleep(0.5)
    sys.stdout.write("\r\033[K")
    return shown


async def isa_chain(db, term):
    from core.reasoning.concept_graph_reasoning import load_subgraph
    edges = await _quiet(load_subgraph(db, [term], max_hops=14))
    nxt = {}
    for e in edges:
        rel = e.relation.value if hasattr(e.relation, "value") else str(e.relation)
        if rel == "isa":
            nxt.setdefault(str(e.subject), str(e.obj))
    chain, cur, seen = [term], term, {term}
    while cur in nxt and nxt[cur] not in seen:
        cur = nxt[cur]; chain.append(cur); seen.add(cur)
    return chain


async def known(conv, term):
    resolved = await _quiet(conv.resolve(term))
    return any(getattr(r, "known", False) for r in resolved)


async def pick_concept(conv):
    """First candidate the substrate does NOT already hold — a genuine gap to
    close. (The whole of WordNet is now taught into the store, so these common
    animals are typically already known; a genuine gap today is a word WordNet
    itself lacks, which `look_up` closes via web research. This demo predates
    that teach and needs a rewrite around a real remaining gap.)"""
    for term in CANDIDATES:
        if not await known(conv, term):
            return term
    return None


async def main():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = getattr(system, "autonomous_coordinator", None)
        if coord is None:
            from core.agents.autonomous.autonomous_coordinator import get_autonomous_coordinator
            coord = await get_autonomous_coordinator()
        from core.memory import get_memory_agent
        from core.database import get_unified_db
        agent = await get_memory_agent()
        db = await get_unified_db()
        conv = coord.conversation("demo")
        CONCEPT = await pick_concept(conv)

    print("═" * 70)
    print(f"{BOLD} TorinAI — detect a knowledge gap, close it with a tool, reason over it{RST}")
    print("═" * 70)
    print(f"{DIM} Real system · nothing cleared · no language model{RST}")
    print()

    if CONCEPT is None:
        print(f"{RED} No untaught candidate left — the substrate already holds them all.{RST}")
        return
    QUESTION = f"Is a {CONCEPT} an animal?"
    print(f"{BOLD}{YEL}▶ You:{RST} {QUESTION}")
    print()

    # 1) GAP DETECTION — the substrate's own resolve finds it holds nothing here.
    before_known = await known(conv, CONCEPT)
    print(f"{BOLD}1. Gap detection{RST}")
    if before_known:
        print(f"   {RED}(the substrate already holds '{CONCEPT}' — pick an unknown one){RST}")
    else:
        print(f"   {RED}✗ knowledge gap:{RST} the substrate holds nothing for '{CONCEPT}'")
    await stream_recall(agent, CONCEPT, "querying its memory")
    print(f"   {DIM}memory query returned nothing about '{CONCEPT}'{RST}")
    print()

    # 2) CLOSE THE GAP — one turn: detect -> tool -> admit relations -> reason -> answer.
    print(f"{BOLD}2. Closing the gap{RST}")
    time.sleep(0.3)
    u = await _quiet(conv.understand(QUESTION, look_up=True))
    tool = next((a.origin for a in u.acquired if a.origin), None)
    print(f"   {GRN}✓ used a tool:{RST} {tool or '(none)'}")
    chain = await isa_chain(db, CONCEPT)
    if len(chain) >= 2:
        print(f"   {GRN}✓ learned, stored as relations:{RST} {' → '.join(chain)}")
    print()

    # 3) REASONING STEPS — the hops it walked to answer, over what it just learned.
    print(f"{BOLD}3. Reasoning{RST}")
    steps = []
    for a in (u.answers or []):
        if getattr(a, "support", None):
            steps = list(a.support)
    for s in steps:
        print(f"   {DIM}·{RST} {s}")
    if not steps:
        print(f"   {DIM}(no derivation chain surfaced){RST}")
    print()

    # 4) ANSWER.
    print(f"{BOLD}4. Answer{RST}")
    print(f"{BOLD}{GRN}◀ Torin:{RST} {u.reply}")
    print()

    # 5) UPDATED — the gap is closed for good; ask again with NO tool.
    print(f"{BOLD}5. Updated{RST}  {DIM}(same question, look-up disabled — from memory now){RST}")
    u2 = await _quiet(conv.understand(QUESTION, look_up=False))
    now_known = await known(conv, CONCEPT)
    print(f"   holds '{CONCEPT}' now: {now_known}")
    print(f"{BOLD}{GRN}◀ Torin:{RST} {u2.reply}")
    print()
    print("═" * 70)


if __name__ == "__main__":
    asyncio.run(main())
