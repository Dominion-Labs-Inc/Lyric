#!/usr/bin/env python3
"""Memory against the REAL system: store → reason() → recall into cognition.

Not a CRUD smoke test. This drives the actual reasoning entry point
(`NeuralSymbolicBridge.reason`) and asserts that a memory written to the store
is (a) retrievable, and (b) INJECTED INTO COGNITION on a later, related,
above-floor query — i.e. it lands in `request.context` where the eleven kinds of
thinking read their premises. Injection runs before the model, so the cognition
assertion holds whether or not the LLM produces an answer.

Run inside the sandbox against the real DB + llama-server:

    docker run --rm --add-host=host.docker.internal:host-gateway \
      -e POSTGRES_HOST=host.docker.internal \
      -e LLM_SERVER_URL=http://host.docker.internal:8099 \
      -e PYTHONPATH=/repo -w /repo \
      -v "$PWD":/repo:ro -v "$HOME/.cache":/root/.cache \
      torinai-sandbox:latest python tests/memory/test_memory_real_loop.py

Exit 0 = all assertions held. Non-zero = a real failure, printed.
"""

import asyncio
import hashlib
import sys
import time


def _tok(seed: str) -> str:
    return "zrl" + hashlib.sha1(seed.encode()).hexdigest()[:8]


async def _cleanup(agent, memory_id: str) -> None:
    try:
        store = getattr(agent, "postgres_storage", None)
        if store and hasattr(store, "delete_memory"):
            await store.delete_memory(memory_id)
    except Exception:
        pass  # best effort; the row is harmless if it lingers


async def run() -> int:
    from core.memory import Origin
    from core.memory import get_memory_agent
    from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest

    results: list[tuple[bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((ok, name))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))

    agent = await get_memory_agent()
    await agent.initialize()
    # What was taught of English, in view, as a running Lyric has it: the reader
    # reads the query `reason` is asked.
    await agent.warm_word_classes()
    bridge = get_neural_bridge()
    if hasattr(bridge, "initialize"):
        await bridge.initialize()

    # ISOLATION: drop rows left by earlier runs so ranking is deterministic and
    # this run's memory is the unambiguous top match for its own scenario.
    try:
        _okp, prior = await agent.search_memories(
            query="orbital telemetry buffer downlink scheduler ring allocator", limit=25)
        for r in (prior or []):
            if "real_loop_test" in (getattr(r, "tags", None) or []):
                await agent.postgres_storage.delete_memory(r.memory_id)
    except Exception:
        pass

    tok = _tok(str(time.time()))
    # A UNIQUE scenario (distinctive nouns + a per-run token) so nothing already
    # in the store competes with it semantically -- the memory that reaches
    # cognition must be THIS one, not a neighbour on a well-trodden topic.
    claim = (f"the {tok} orbital telemetry buffer overflows when the {tok} "
             f"downlink scheduler starves the ring allocator and the flush never runs")

    # ---- 1. STORE ----------------------------------------------------------
    ok, mem_id = await agent.store_memory(
        content=claim, tags=["reasoning", "real_loop_test"], origin=Origin.own("test_memory_real_loop"))
    check("store_memory persists the conclusion", bool(ok) and bool(mem_id),
          f"id={mem_id}")

    # ---- 2. RETRIEVE (wait until embedded/searchable) ----------------------
    # The unique nouns keep it ranking to THIS memory, so a 0-injection here is a
    # real failure.
    probe_q = (f"why does the {tok} orbital telemetry buffer keep overflowing, "
               f"and how does the {tok} downlink scheduler starve the ring "
               f"allocator, and what is the root cause I should investigate to fix it")
    found = None
    sim = 0.0
    for i in range(20):
        _ok, res = await agent.search_memories(query=probe_q, limit=5)
        hit = next((r for r in (res or []) if getattr(r, "memory_id", None) == mem_id), None)
        if hit is not None:
            found = hit
            sim = float(getattr(hit, "similarity_score", 0.0) or 0.0)
            break
        await asyncio.sleep(0.5)
    check("stored memory is retrievable by paraphrase", found is not None,
          f"similarity={sim:.3f} after {i * 0.5:.1f}s")

    # ---- 3. THE MEMORY AGENT hands this query its memory -------------------
    # What memory holds of a request decides what it hands over: the stored
    # conclusion names what the query names.
    handed = await agent.recall_for(probe_q, limit=3)
    check("the memory agent hands this query its memory", any(m["memory_id"] == mem_id for m in handed),
          f"handed={[m['memory_id'] for m in handed]}")

    # ---- 4. REACHES COGNITION via the real reason() loop -------------------
    # Injection prepends recalled claims into request.context before any model
    # runs. Assert the distinctive token lands there — memory reached cognition.
    req = ReasoningRequest(query=probe_q, cached_memories=None)
    await bridge.reason(req)
    ctx = req.context or []
    reached = any(tok in str(c) for c in ctx)
    check("memory reached cognition (injected into reason() context)", reached,
          f"context items={len(ctx)}; first={str(ctx[0])[:80] if ctx else '—'}")

    # ---- 5. AND a request memory holds nothing of is handed nothing ---------
    # How a word is used ("'hello' is used as a noun.") is taught language, not
    # knowledge: it is not handed over, so "hello" gets nothing.
    nothing = await agent.recall_for("hello", limit=3)
    check("a request memory holds nothing of is handed nothing", not nothing,
          f"handed={[str(m.get('claim') or m.get('content'))[:60] for m in nothing]}")

    await _cleanup(agent, mem_id)

    passed = sum(1 for ok, _ in results if ok)
    print(f"\n  {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as error:
        import traceback
        traceback.print_exc()
        print(f"\n  ERROR: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
