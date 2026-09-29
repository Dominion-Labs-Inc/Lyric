#!/usr/bin/env python3
"""MEMORY-INTENT-01 — a memory records WHAT THE SUBSTRATE WAS TRYING TO ACHIEVE.

The record already held how it reasoned (`reasoning_trace`), what weighed on it
(`decision_factors`), how it felt (`appraisal_snapshot`) and what condition it
was in (`system_state`) — and not the GOAL any of that served. A derivation
without its conclusion: the substrate could reconstruct how it thought and never
what it was thinking toward.

Measured before this ran: intent appeared in 0 of 9,308 memories as a relation
(85 incidental text mentions inside `content`).

  A  CAPTURE     forming a memory while pursuing something records the pursuit,
                 by ID, with the VERSION that was current at the time.
  B  LINK, NOT COPY  the intent's shape is not duplicated into the memory — one
                 account of what was meant, owned by the intent authority.
  C  HINDSIGHT   refreshing the intent afterwards does NOT re-describe the past
                 act: the stored version still names the state it was pursued
                 under, and the intent's own history holds it.
  D  BOTH DIRECTIONS  memory → pursuit, and pursuit → the episodes of acting on it.
  E  INJECTION   the pursuit REACHES THE READER, rather than being stored and
                 dropped the way `reasoning_trace` is.
  F  BASELINE    what fraction of the existing record carries each kind of
                 contemporaneous context. Coverage is thin and is reported.

Run: ./venv_lyric/bin/python3 experiments/MEMORY-INTENT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "MEMORY-INTENT-01",
    claim=("An episode is recorded with the pursuit it belonged to — by id and by "
           "the intent version current at the time — so the substrate can ask "
           "both 'what was I trying to do when this happened' and 'what happened "
           "while I pursued that', and a later refinement of the goal cannot "
           "re-describe a past act."),
    hypothesis=("If the link were a COPY of the intent's shape, refreshing the "
                "intent would leave two diverging accounts of what was meant. If "
                "it were the id ALONE, hindsight would silently re-describe past "
                "acts under a goal the substrate only later refined into. Only id "
                "PLUS version answers 'at the time' honestly."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.memory import Origin
    from core.database import get_unified_db
    from core.memory import get_memory_agent
    from core.memory.utils.interfaces import MemoryType
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR,
        set_acting_intent, reset_acting_intent)

    db = await get_unified_db()
    if not db.initialized:
        await db.initialize()
    A = get_intent_authority()

    # ── F. BASELINE, before anything this run writes ────────────────────────
    print("\n== F. What the existing record carries ==")
    total = (await db.execute_query(
        "SELECT count(*) n FROM memory_hot.memory_hot", fetch_one=True))["n"]
    coverage = {}
    for col in ("intent_id", "appraisal_snapshot", "reasoning_trace",
                "decision_factors", "emotional_context", "system_state"):
        r = await db.execute_query(
            f"SELECT count(*) n FROM memory_hot.memory_hot "
            f"WHERE {col} IS NOT NULL AND {col}::text NOT IN ('null','{{}}','')",
            fetch_one=True)
        coverage[col] = int(r["n"])
        EV.metric(f"coverage_{col}", round(coverage[col] / total, 4) if total else None,
                  "fraction", f"{coverage[col]} of {total} memories")
        print(f"     {col:20} {coverage[col]:5} / {total}")
    EV.metric("memories_total", total, "count")
    check("the record carries contemporaneous context on some memories",
          coverage["appraisal_snapshot"] > 0 and coverage["reasoning_trace"] > 0,
          f"appraisal {coverage['appraisal_snapshot']}, "
          f"reasoning {coverage['reasoning_trace']}")
    EV.note("Coverage is thin and is reported rather than rounded up: these "
            "fields sit on a minority of memories, so a capability built on them "
            "answers for that minority. The fix is at the write sites.")

    # ── A. CAPTURE ──────────────────────────────────────────────────────────
    print("\n== A. Forming a memory while pursuing something records the pursuit ==")
    key = f"memint_{uuid4().hex[:8]}"
    intent = await A.form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(key),
        shape={"proved": True, "operator": "MOVE_FILE(?f, ?a, ?b)",
               "goal_conditions": ["FILE_IN(?f, ?b)"], "rule_ids": [],
               "domain": "memint", "steps": 1},
        content={"aim": "archive the quarterly report"})
    v_at_time = intent.version

    agent = await get_memory_agent()
    token = set_acting_intent(intent.intent_id)
    try:
        mem_id = await agent.store_memory(
            content=f"archived the quarterly report [{key}]",
            memory_type=MemoryType.EPISODIC,
            importance_score=0.9, origin=Origin.own("MEMORY-INTENT-01"))
    finally:
        reset_acting_intent(token)
    # store_memory returns (ok, memory_id).
    ok, mem_id = mem_id if isinstance(mem_id, tuple) else (bool(mem_id), mem_id)
    check("a memory was formed", bool(ok) and bool(mem_id), str(mem_id)[:28])

    row = await db.execute_query(
        "SELECT intent_id, intent_version, content FROM memory_hot.memory_hot "
        "WHERE memory_id = $1", (str(mem_id),), fetch_one=True)
    check("it recorded the pursuit it belonged to, by id",
          bool(row) and row["intent_id"] == intent.intent_id,
          f"stored={row['intent_id'][:16] if row and row['intent_id'] else None}")
    check("and the intent VERSION current at the time",
          bool(row) and row["intent_version"] == v_at_time,
          f"stored v{row['intent_version'] if row else None}, was v{v_at_time}")
    EV.metric("intent_version_at_capture", v_at_time, "version")

    # ── B. LINK, NOT COPY ───────────────────────────────────────────────────
    print("\n== B. The link is an ID — the intent's shape is not duplicated ==")
    body = str(row["content"]) if row else ""
    check("the memory does not carry a copy of the intent's goal conditions",
          "FILE_IN(?f, ?b)" not in body and "MOVE_FILE" not in body,
          f"{len(body)} bytes of content, no operator or goal state in it")
    EV.note("Intent is live, revisable state owned by the intent authority; a "
            "memory is a permanent record of what happened. Snapshotting the "
            "shape here would create a second account of what was meant, free to "
            "diverge from the first — the duplicate-authority defect in the one "
            "place where 'what I was trying to do' must have a single answer.")

    # ── C. HINDSIGHT CANNOT REWRITE THE PAST ────────────────────────────────
    print("\n== C. Refreshing the intent does not re-describe the past act ==")
    refreshed = await A.refresh(
        intent.intent_id, SUBSTRATE_ACTOR,
        shape={"goal_conditions": ["FILE_IN(?f, ?b)", "¬FILE_IN(?f, ?a)"]},
        content={"aim": "archive the quarterly report AND clear the inbox"})
    check("the pursuit genuinely moved on", refreshed.version > v_at_time,
          f"v{v_at_time} → v{refreshed.version}")
    row2 = await db.execute_query(
        "SELECT intent_version FROM memory_hot.memory_hot WHERE memory_id = $1",
        (str(mem_id),), fetch_one=True)
    check("the memory still names the version it was pursued under — hindsight "
          "did not rewrite it",
          bool(row2) and row2["intent_version"] == v_at_time,
          f"memory still v{row2['intent_version'] if row2 else None}, "
          f"intent now v{refreshed.version}")
    # THE FULL VIEW, with the actor. `get_by_id` WITHOUT an actor returns the
    # substrate-wide SHAPE view, which strips `history` along with the rest of
    # the actor-scoped content — correctly: a reader entitled only to the
    # anonymous skeleton is not entitled to the owner's record of how their
    # pursuit changed. Asking the shape view for history is asking the wrong
    # view, not finding a missing feature.
    held = await A.get_by_id(intent.intent_id, SUBSTRATE_ACTOR)
    check("and the earlier state is recoverable from the intent's own history",
          bool(held) and any(h.get("version") == v_at_time
                             for h in (held.history or [])),
          f"{len(held.history or []) if held else 0} prior state(s) held")
    shape_only = await A.get_by_id(intent.intent_id)
    check("while the actor-free SHAPE view withholds that history, as it should",
          bool(shape_only) and not (shape_only.history or []),
          "shape view carries no owner-scoped history")

    # ── D. BOTH DIRECTIONS ──────────────────────────────────────────────────
    print("\n== D. Memory → pursuit, and pursuit → the episodes of acting on it ==")
    back = await A.get_by_id(row["intent_id"])
    check("from the memory, the pursuit resolves", bool(back),
          back.operator if back else None)
    episodes = await db.execute_query(
        "SELECT memory_id FROM memory_hot.memory_hot WHERE intent_id = $1",
        (intent.intent_id,))
    check("from the pursuit, its episodes resolve", len(episodes or []) >= 1,
          f"{len(episodes or [])} episode(s)")
    EV.metric("episodes_per_pursuit", len(episodes or []), "count")

    # ── E. IT REACHES THE READER ────────────────────────────────────────────
    print("\n== E. The pursuit is rendered, not stored and dropped ==")
    # THROUGH THE REAL RETRIEVAL PATH, and that is the whole point of this
    # section. The first version of this check called `_pursuit_suffix` with a
    # HAND-BUILT dict — which proves the function formats a string and nothing
    # about whether the pipeline ever delivers one. It hid a live defect for as
    # long as it stood: `_row_to_memory_item` did not map `intent_id` or
    # `intent_version`, so every retrieved MemoryItem reported None for both and
    # "(while pursuing …)" could not render from a real recall. The link
    # survived the write and died on the read. A test that constructs its own
    # input cannot see that, which is what made it worth nothing here.
    from core.memory.utils.memory_injector import _pursuit_suffix
    recalled = await agent.retrieve_memory(str(mem_id))
    check("the memory comes back from the store at all", recalled is not None,
          type(recalled).__name__ if recalled else "None")
    check("and carries the pursuit through RETRIEVAL, not just through the write",
          recalled is not None
          and getattr(recalled, "intent_id", None) == intent.intent_id
          and getattr(recalled, "intent_version", None) == v_at_time,
          f"intent_id={getattr(recalled, 'intent_id', None)}, "
          f"version={getattr(recalled, 'intent_version', None)}")
    rendered = _pursuit_suffix({
        "intent_id": getattr(recalled, "intent_id", None),
        "intent_version": getattr(recalled, "intent_version", None)})
    check("so a recalled memory RENDERS the pursuit to its reader",
          intent.intent_id in rendered and f"v{v_at_time}" in rendered,
          rendered.strip())
    check("a memory without one renders nothing extra",
          _pursuit_suffix({"content": "x"}) == "")
    EV.note("What this section is for: a field that reaches no consumer is not "
            "wired, however faithfully it is stored. It must therefore be "
            "checked through the path a reader actually uses — the moment it "
            "builds its own input it stops testing the wiring and starts "
            "testing string formatting.")
    EV.note("`reasoning_trace` is read out of the row and carried through "
            "retrieval, then dropped by every template — present in the pipeline "
            "and invisible to the reader. A field that reaches no consumer is not "
            "wired, however faithfully it is stored.")

    # ── cleanup: both rows of the intent, and the probe memory ──────────────
    try:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
            (str(mem_id),), commit=True)
        await db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE intent_id = $1",
            (intent.intent_id,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.intents WHERE intent_id = $1",
            (intent.intent_id,), commit=True)
    except Exception as e:
        print(f"  (cleanup: {e})")

    passed = sum(1 for ok in results if ok)
    total_checks = len(results)
    print(f"\n==== MEMORY-INTENT-01: {passed}/{total_checks} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == total_checks else 1


sys.exit(asyncio.run(main()))
