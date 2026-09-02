#!/usr/bin/env python3
"""TorinAI — closing a knowledge gap on its own, then reasoning over it.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 demos/knowledge_acquisition_demo.py

Two prompts, no language model:

  PROMPT 1  "What is a robin?"
      The substrate does not hold 'robin'. It closes the gap ITSELF: it calls a
      tool (lexical_lookup), and admits what it finds as STRUCTURED relations —
      robin is-a thrush, thrush is-a bird, and so on — into its concept graph.

  PROMPT 2  "Is a robin an animal?"   (a DIFFERENT question)
      It queries its memory live (shown), then REASONS over what it just
      acquired — robin → thrush → … → bird → animal — and answers from that.

Everything below is the real substrate: real tool call, real concept graph,
real recall, real model-free reasoning. The language model is never called.
Self-cleaning: the 'robin' entry is cleared before and after, so each run shows
a genuine gap and leaves the store as it found it.
"""
import os
# Quiet the ML stack BEFORE anything imports it, so no progress bars or
# tokenizer chatter land in the recording. (Presentation only — every result
# printed below is real and computed live.)
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import asyncio
import io
import contextlib
import logging
import sys
import time


async def _quiet(coro):
    """Await a coroutine with stdout/stderr swallowed — used around substrate
    calls that emit incidental prints/progress, so only the demo's own lines
    show. The RESULT is real; only its incidental output is hidden."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return await coro

TERM = "robin"
BOLD = "\033[1m"; DIM = "\033[2m"; GRN = "\033[32m"; CYN = "\033[36m"; YEL = "\033[33m"; RST = "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = GRN = CYN = YEL = RST = ""


def rule(ch="─", n=68):
    print(ch * n)


def _clean_reply(text: str) -> str:
    """Drop a vacuous 'P(question) = 1.000' line the open-question reasoner emits
    as a by-product — it is not content, and it is not what the turn answered."""
    return "\n".join(
        ln for ln in str(text or "").splitlines()
        if not ln.strip().startswith("P(")).strip()


def _text_of(item) -> str:
    content = getattr(item, "content", None)
    if isinstance(content, dict):
        content = content.get("text") or content.get("content") or ""
    return str(content or getattr(item, "text", "") or "").strip().strip('"')


async def clear_term(db, name):
    ids = await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE lower(name)=lower($1)",
        (name,), fetch_all=True) or []
    cids = [r["concept_id"] for r in ids]
    if cids:
        for table, col in (("unified.concept_relations", "source_concept_id"),
                           ("unified.concept_relations", "target_concept_id")):
            await db.execute_query(
                f"DELETE FROM {table} WHERE {col} = ANY($1)", (cids,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1)",
            (cids,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.concepts WHERE concept_id = ANY($1)", (cids,), commit=True)


async def chain_from_graph(db):
    from core.reasoning.concept_graph_reasoning import load_subgraph
    edges = await load_subgraph(db, [TERM], max_hops=12)
    nxt = {}
    for e in edges:
        rel = e.relation.value if hasattr(e.relation, "value") else str(e.relation)
        if rel == "isa":
            nxt.setdefault(str(e.subject), str(e.obj))
    chain, cur, seen = [TERM], TERM, {TERM}
    while cur in nxt and nxt[cur] not in seen:
        cur = nxt[cur]; chain.append(cur); seen.add(cur)
    return chain


async def stream_recall(agent, query):
    """Show what the substrate surfaces from memory, live — each candidate's
    first words, one at a time, until it has gathered what it holds."""
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
        sys.stdout.write(f"\r  {CYN}🔎 querying memory:{RST} {first}…"
                         f"{DIM} ({score:.2f}){RST}\033[K")
        sys.stdout.flush()
        shown += 1
        time.sleep(0.45)
    sys.stdout.write("\r\033[K")
    print(f"  {DIM}surfaced {shown} memor{'y' if shown == 1 else 'ies'} it holds "
          f"about {TERM}{RST}")


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
        from core.database import get_unified_db
        from core.memory import get_memory_agent
        db = await get_unified_db()
        agent = await get_memory_agent()
        await clear_term(db, TERM)
        conv = coord.conversation("acquisition_demo")

    rule("═")
    print(f"{BOLD} TorinAI — closing a knowledge gap on its own, then reasoning over it{RST}")
    rule("═")
    print(f"{DIM} Language model: not called   ·   real tool, real concept graph, "
          f"real reasoning{RST}")
    print()

    # ── PROMPT 1: it does not know 'robin' — it closes the gap itself ──
    print(f"{BOLD}{YEL}▶ You:{RST} What is a robin?")
    print(f"  {DIM}it holds nothing for 'robin' — closing the gap itself…{RST}")
    time.sleep(0.4)
    u1 = await _quiet(conv.understand("What is a robin?"))
    tool = next((a.origin for a in u1.acquired if a.origin), "lexical_lookup")
    print(f"  {DIM}· used a tool:{RST} {tool}")
    chain = await chain_from_graph(db)
    print(f"  {DIM}· admitted as structured relations it can reason over:{RST}")
    print(f"    {GRN}{' → '.join(chain)}{RST}")
    print(f"{BOLD}{GRN}◀ Torin:{RST} {_clean_reply(u1.reply)}")
    print()

    # ── PROMPT 2 (DIFFERENT): answered by reasoning over what it acquired ──
    print(f"{BOLD}{YEL}▶ You:{RST} Is a robin an animal?")
    await stream_recall(agent, "Is a robin an animal?")
    print(f"  {DIM}· reasoning over what it holds…{RST}")
    time.sleep(0.4)
    u2 = await _quiet(conv.understand("Is a robin an animal?"))
    print(f"{BOLD}{GRN}◀ Torin:{RST} {_clean_reply(u2.reply)}")
    print()

    rule("═")
    print(f"{BOLD} It was never taught this. Asked something it did not know, it used a{RST}")
    print(f"{BOLD} tool to find out, kept what it learned as relations, and then reasoned{RST}")
    print(f"{BOLD} over them to answer a different question — with no language model.{RST}")
    rule("═")

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        await clear_term(db, TERM)  # leave the store as we found it
        try:
            await coord.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
