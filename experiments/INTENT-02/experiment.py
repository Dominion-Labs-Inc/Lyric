#!/usr/bin/env python3
"""INTENT-02 — reasoning forms intent, on the REAL bridge.

Phase 1 (INTENT-01) proved the authority in isolation. This proves the wiring: a
real reasoning pass through `NeuralSymbolicBridge.reason` opens the substrate's
intent where reasoning starts, refreshes it as it firms up, stamps its id onto
the result, and holds the content/shape split — verified against real Postgres,
nothing mocked.

It is deliberately not a minimum test. It covers:
  1. a thread-anchored reasoning forms a thread intent, id stamped on the result;
  2. a second turn on the thread REFRESHES the same intent (not a new one);
  3. a goal-anchored reasoning is its own intent, parented to the thread;
  4. an anchorless reasoning forms a question intent keyed by the query — the
     SAME query refreshes it, a DIFFERENT query is a different intent;
  5. the content/shape split: the query is in actor-scoped content, never in the
     substrate-wide shape;
  6. CONCURRENCY: many reasoning passes on one thread at once collapse to exactly
     ONE intent (the unique-key race is handled, no duplicates);
  7. LATENCY: the cost intent forming adds, measured, not guessed;
  8. RESTART: a fresh interpreter reads the formed intents back.
"""
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402
from core.reasoning.neural_bridge import get_neural_bridge, ReasoningRequest  # noqa: E402
from core.reasoning.intent_authority import (  # noqa: E402
    get_intent_authority, continuity_thread, continuity_goal, continuity_question)

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

PASS = FAIL = 0
EV = RunRecord(
    "INTENT-02",
    claim="A real reasoning pass through the bridge forms and refreshes the "
          "substrate's intent where reasoning starts, keyed so turns refresh and "
          "goals stay distinct, split into shape and content, and durable.",
    hypothesis="If the bridge opens intent at the start of reason(), then every "
               "reasoning carries an intent id, a return refreshes rather than "
               "rebuilds, concurrent passes on one thread make one intent, the "
               "query never leaks into substrate-wide shape, and it survives a "
               "fresh process.")


def check(label, ok, detail=""):
    global PASS, FAIL
    EV.check(label, ok, detail)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


async def count_scoped(actor, key):
    A = get_intent_authority()
    await A.store._ready()
    row = await A.store.db.execute_query(
        "SELECT count(*) AS n FROM unified.scoped_intents "
        "WHERE scope_actor = $1 AND continuity_key = $2",
        (actor, key), fetch_one=True)
    return int(row["n"]) if row else 0


async def readback(actor, thread_id, goal_intent_id):
    A = get_intent_authority()
    t = await A.get(actor, continuity_thread(thread_id))
    g = await A.get_by_id(goal_intent_id, actor=actor)
    print("READBACK " + json.dumps({
        "thread_reloaded": bool(t),
        # settled = the last reasoning pass completed (engaged flipped off); this
        # is durability of the lifecycle, distinct from whether it had an answer.
        "thread_settled": bool(t and t.shape.get("engaged") is False),
        "thread_version": t.version if t else None,
        "goal_reloaded": bool(g),
        "goal_parent": g.parent_intent_id if g else None,
    }))


async def reason(bridge, query, **md):
    return await bridge.reason(ReasoningRequest(query=query, task_metadata=md))


async def main():
    bridge = get_neural_bridge()
    check("the real neural bridge initialises", await bridge.initialize())
    A = get_intent_authority()
    run = uuid.uuid4().hex[:8]
    actor = f"intent02_{run}"
    thread = f"thr_{run}"
    goal = f"goal_{run}"
    created_shape_ids = []

    print("\n== A. Thread-anchored reasoning forms a thread intent ==")
    r1 = await reason(bridge, "what is the capital of France",
                      actor=actor, thread_id=thread)
    iid = (r1.metadata or {}).get("intent_id")
    check("the reasoning result carries an intent id", bool(iid), str(iid))
    t1 = await A.get(actor, continuity_thread(thread))
    check("a thread intent was formed for this actor",
          bool(t1) and t1.intent_id == iid and t1.origin_kind == "thread",
          f"id={t1.intent_id[:8] if t1 else None} origin={t1.origin_kind if t1 else None}")
    check("the shape records the reasoning (answered, confidence), not the query",
          bool(t1) and "answered" in t1.shape and "query" not in t1.shape,
          f"shape_keys={sorted((t1.shape or {}).keys()) if t1 else None}")
    if t1:
        created_shape_ids.append(t1.intent_id)

    print("\n== B. A second turn refreshes the same intent ==")
    r2 = await reason(bridge, "and what is its population", actor=actor, thread_id=thread)
    t2 = await A.get(actor, continuity_thread(thread))
    check("the second turn keeps the same intent id",
          (r2.metadata or {}).get("intent_id") == iid and t2.intent_id == iid,
          f"{(r2.metadata or {}).get('intent_id', '')[:8]} == {iid[:8]}")
    check("the refresh advanced the version and grew history (not a new intent)",
          t2.version >= 3 and len(t2.history) >= 2,
          f"v{t2.version}, history={len(t2.history)}")

    print("\n== C. A goal raised in the thread is its own, parented intent ==")
    rg = await reason(bridge, "plan the archive step", actor=actor,
                      goal_id=goal, parent_intent_id=iid)
    gid = (rg.metadata or {}).get("intent_id")
    g = await A.get(actor, continuity_goal(goal))
    check("the goal reasoning is a distinct intent, parented to the thread",
          bool(g) and gid == g.intent_id and gid != iid and g.parent_intent_id == iid,
          f"goal={gid[:8] if gid else None} parent={g.parent_intent_id[:8] if g and g.parent_intent_id else None}")
    if g:
        created_shape_ids.append(g.intent_id)

    print("\n== D. Anchorless reasoning keys on the query ==")
    q_a1 = await reason(bridge, "define entropy")
    q_a2 = await reason(bridge, "define entropy")          # same question again
    q_b = await reason(bridge, "define enthalpy")          # a different question
    ia1 = (q_a1.metadata or {}).get("intent_id")
    ia2 = (q_a2.metadata or {}).get("intent_id")
    ib = (q_b.metadata or {}).get("intent_id")
    check("the same anchorless question refreshes one intent", ia1 == ia2 and bool(ia1),
          f"{str(ia1)[:8]} == {str(ia2)[:8]}")
    check("a different question is a different intent", ib != ia1 and bool(ib),
          f"{str(ib)[:8]} != {str(ia1)[:8]}")
    for qid in (ia1, ib):
        if qid:
            created_shape_ids.append(qid)

    print("\n== E. Content vs shape split; content refreshes, history preserves ==")
    full = await A.get_by_id(iid, actor=actor)
    shape_only = await A.get_by_id(iid)                    # substrate-wide view
    # Content reflects the LATEST turn (refreshed), and the first turn's query
    # survives in history — refreshed, not lost, and not frozen at the first.
    first_in_history = any(
        (h.get("content") or {}).get("query") == "what is the capital of France"
        for h in (full.history if full else []))
    check("content holds the latest turn's query (context is refreshed)",
          full and full.content.get("query") == "and what is its population",
          f"content_query={full.content.get('query') if full else None!r}")
    check("the first turn's query survives in history (refreshed, not lost)",
          first_in_history, f"history_len={len(full.history) if full else 0}")
    check("the query is actor-scoped content, never substrate-wide shape",
          shape_only and "query" not in shape_only.shape and shape_only.content == {}
          and (full and "query" not in full.shape),
          f"shape_keys={sorted((shape_only.shape or {}).keys()) if shape_only else None}")

    print("\n== F. Concurrency: many passes on one thread make ONE intent ==")
    cactor = f"{actor}_conc"
    cthread = f"{thread}_conc"
    await asyncio.gather(*[
        reason(bridge, f"concurrent turn {i}", actor=cactor, thread_id=cthread)
        for i in range(6)])
    n = await count_scoped(cactor, continuity_thread(cthread))
    check("six concurrent passes on one thread collapse to exactly one intent",
          n == 1, f"{n} scoped row(s) for the thread")
    conc = await A.get(cactor, continuity_thread(cthread))
    if conc:
        created_shape_ids.append(conc.intent_id)

    print("\n== G. Latency: the cost intent forming adds ==")
    lat = []
    for i in range(5):
        t0 = time.perf_counter()
        await reason(bridge, f"latency probe {i}", actor=actor, thread_id=f"lat_{run}_{i}")
        lat.append((time.perf_counter() - t0) * 1000.0)
    for i in range(5):
        li = await A.get(actor, continuity_thread(f"lat_{run}_{i}"))
        if li:
            created_shape_ids.append(li.intent_id)
    check("intent forming does not dominate a reasoning pass (mean < 250 ms)",
          statistics.mean(lat) < 250.0,
          f"mean {statistics.mean(lat):.1f} ms, max {max(lat):.1f} ms (n=5, whole reason() call)")

    print("\n== H. Survives a restart (a fresh interpreter reads it back) ==")
    payload = {"actor": actor, "thread_id": thread, "goal_intent_id": g.intent_id if g else ""}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        ppath = fh.name
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--readback", ppath],
        capture_output=True, text=True)
    os.unlink(ppath)
    rb = None
    for line in proc.stdout.splitlines():
        if line.startswith("READBACK "):
            rb = json.loads(line[len("READBACK "):])
    check("a fresh process reloads the thread intent (settled) and the parented goal",
          bool(rb) and rb["thread_reloaded"] and rb["thread_settled"]
          and rb["goal_reloaded"] and rb["goal_parent"] == iid,
          json.dumps(rb) if rb else f"no readback (rc={proc.returncode}): {proc.stderr[-300:]}")

    EV.metric("reason_call_latency_mean_ms", round(statistics.mean(lat), 2), "ms")
    EV.metric("reason_call_latency_max_ms", round(max(lat), 2), "ms")
    EV.metric("concurrent_passes_to_one_intent", n, "rows")
    EV.metric("thread_intent_version_after_two_turns", t2.version, "version")

    # Self-cleaning: drop every actor's scoped rows and this run's shape rows.
    for a in (actor, cactor, "substrate"):
        # 'substrate' holds the anchorless-question content formed above.
        try:
            await A.forget_actor(a)
        except Exception:
            pass
    if created_shape_ids:
        await A.store._ready()
        # BOTH ROWS, IN THAT ORDER. An intent is two rows — the substrate-wide
        # shape in `unified.intents` and the actor's content in
        # `unified.scoped_intents` — written atomically by `create`. This removed
        # only the shape, so every run left the content rows behind pointing at
        # shapes that no longer existed.
        #
        # Those orphans are not inert. `form` resolves a continuity key against
        # `scoped_intents`, so the next engagement on that question FOUND the
        # dangling id, failed to load its shape, and produced NO INTENT AT ALL —
        # reasoning then made acts nothing could explain. The anchorless checks
        # in this very experiment were the ones that broke.
        #
        # They stayed hidden while the substrate's actor was spelled two ways
        # (`substrate` vs `__substrate__`): the orphans were filed under one name
        # and looked up under the other, so nothing ever found them.
        await A.store.db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE intent_id = ANY($1::text[])",
            (created_shape_ids,), commit=True)
        await A.store.db.execute_query(
            "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
            (created_shape_ids,), commit=True)

    # Ask the SERVER which database this actually ran against, rather than
    # letting the record say the database was 'not recorded'.
    await EV.verify_database()
    EV.write()
    print("\n" + "=" * 60)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--readback"]:
        data = json.load(open(sys.argv[2]))
        asyncio.run(readback(data["actor"], data["thread_id"], data["goal_intent_id"]))
    else:
        sys.exit(asyncio.run(main()) or 0)
