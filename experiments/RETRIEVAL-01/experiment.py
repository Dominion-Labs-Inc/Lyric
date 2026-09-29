#!/usr/bin/env python3
"""RETRIEVAL-01 — when the substrate cannot answer, is the memory missing, or is
it there and not reached?

────────────────────────────────────────────────────────────────────────────
WHAT THIS FOLLOWS FROM

TAUGHT-IN-ENGLISH-01 established that teaching in plain English writes memories
and that the substrate answers from them. One question kept failing:

    told:   "A marnic filters brine."      (now stored, verbatim)
    asked:  "What does a marnic do?"
    answer: "A marnic is a device. A marnic contains threlp."

The sentence that answers the question is in memory and the reply does not use
it. Storing it was the fix I claimed would solve this; it did not, so the cause
is downstream of storage and has not been located.

────────────────────────────────────────────────────────────────────────────
HYPOTHESES — mutually exclusive, so the run distinguishes them

  RA  NOT RETRIEVED. `retrieve()` does not return the memory for that question
      at all. Then the defect is in retrieval — embedding, thresholds, or
      strategy coverage — and the answering path never had it.

  RB  RETRIEVED AND DROPPED. `retrieve()` returns it, and the answering path
      still does not use it. Then retrieval is fine and the defect is in what
      composes the reply.

  RC  RETRIEVED BUT OUTRANKED. It comes back below other memories that the
      composer takes first. A ranking problem, distinct from both.

  The run reports, per question: whether the answering memory is present, at
  what RANK, with what SCORE, against what outranked it — and what `understand`
  actually replied. Those three facts separate RA, RB and RC without argument.

  `min_similarity` is swept (0.0 / 0.3 / 0.5 / 0.7) because `retrieve` defaults
  to 0.5 and `search_memories` to 0.7. If the memory appears only at a lower
  floor, the threshold IS the defect and the number is the evidence.

────────────────────────────────────────────────────────────────────────────
This experiment teaches through the ordinary conversational path and clears
every trace of a previous run first — a prior run's rows would answer the
questions and the result would measure the run before it.
"""
import asyncio
import contextlib
import io
import os
import sys
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TERMS = ("marnic", "threlp", "dovick")
LESSON = [
    "A marnic is a device.",
    "A marnic filters brine.",
    "A marnic contains a threlp.",
    "A threlp is a membrane.",
    "A threlp separates salt from water.",
    "A dovick cleans a threlp.",
]

#: (question, the sentence that answers it). The target is fixed in advance.
PROBES = [
    ("What does a marnic do?", "A marnic filters brine."),
    ("What is a marnic?", "A marnic is a device."),
    ("What does a threlp do?", "A threlp separates salt from water."),
]

CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    quiet = io.StringIO()
    print("starting the substrate...", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    from core.database.unified_database_postgres import LyricUnifiedDatabase
    from core.memory import get_memory_agent
    db = LyricUnifiedDatabase()
    if not db.initialized:
        await db.initialize()
    agent = await get_memory_agent()
    like = [f"%{t}%" for t in TERMS]

    # ── clean slate ──────────────────────────────────────────────────────────
    for table, column in (("memory_hot.memory_hot", "content"),
                          ("unified.concepts", "name"),
                          ("unified.concept_relations", "source_concept_id"),
                          ("unified.concept_relations", "target_surface"),
                          ("unified.concept_domains", "concept_id"),
                          ("unified.beliefs", "belief_text")):
        with contextlib.suppress(Exception):
            await db.execute_query(
                f"DELETE FROM {table} WHERE lower({column}) LIKE ANY($1)", (like,))
    rows = await db.execute_query(
        "SELECT COUNT(*) n FROM memory_hot.memory_hot WHERE lower(content) LIKE ANY($1)",
        (like,), fetch_all=True) or []
    check("clean baseline — nothing about this subject is held",
          (rows[0]["n"] if rows else 0) == 0)

    # ── teach it, the ordinary way ───────────────────────────────────────────
    session = coordinator.conversation(session=f"retr:{uuid4().hex[:8]}")
    print("\n== Teaching ==")
    for sentence in LESSON:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await session.understand(sentence)
    stored = await db.execute_query(
        "SELECT content FROM memory_hot.memory_hot WHERE lower(content) LIKE ANY($1)",
        (like,), fetch_all=True) or []
    held = [str(r["content"]).strip().strip('"') for r in stored]
    print(f"    {len(held)} memory(ies) stored")
    for h in held:
        print(f"      · {h[:76]}")

    # ── the discriminating measurement ───────────────────────────────────────
    print("\n== Retrieval, asked directly, per question ==")
    verdicts = []
    for question, target in PROBES:
        # THE WINDOW IS SWEPT, NOT ASSUMED. A first pass fixed limit=10 and
        # reported the memory ABSENT at every threshold — it was at RANK 15,
        # and the measurement had simply not looked that far. A retrieval
        # experiment whose window is narrower than the effect it is measuring
        # reports the wrong hypothesis with total confidence.
        present_at = {}
        for floor in (0.0, 0.3, 0.5, 0.7):
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                try:
                    items = await agent.retrieve(question, limit=50,
                                                 min_similarity=floor)
                except Exception as e:
                    items = []
                    print(f"    retrieve raised at {floor}: {type(e).__name__}: {e}")
            contents = [str(getattr(i, "content", "")).strip().strip('"') for i in items]
            rank = next((n for n, c in enumerate(contents, 1)
                         if target.lower().rstrip(".") in c.lower()), None)
            present_at[floor] = (rank, len(contents), contents[:3])

        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            u = await coordinator.conversation(
                session=f"retr_ask:{uuid4().hex[:8]}").understand(question)
        reply = str(getattr(u, "reply", "") or "").strip()

        print(f"\n  Q: {question}")
        print(f"     target memory: {target!r}")
        for floor, (rank, n, top) in present_at.items():
            mark = f"rank {rank}" if rank else "ABSENT"
            print(f"     min_similarity={floor}: {mark} of {n} returned")
        print(f"     top-3 at 0.0: {[t[:38] for t in present_at[0.0][2]]}")
        print(f"     understand replied: {reply[:96]!r}")

        found_any = any(r for r, _n, _t in present_at.values())
        # WITHIN THE WINDOW A CALLER ACTUALLY USES. `retrieve` defaults to
        # limit=10, so a memory at rank 15 is real but unreachable in practice —
        # which is a different defect from not being retrievable at all, and the
        # one that was actually happening.
        rank_at_default = present_at[0.5][0]
        found_default = rank_at_default is not None and rank_at_default <= 10
        used = target.lower().rstrip(".").split("a marnic ")[-1][:6] in reply.lower() \
            or target.lower().rstrip(".") in reply.lower()
        verdicts.append({"question": question, "found_any": bool(found_any),
                         "found_default": bool(found_default),
                         "rank_default": present_at[0.5][0], "used": bool(used)})

    # ── the verdict ──────────────────────────────────────────────────────────
    print("\n== Which hypothesis does the evidence support? ==")
    never = [v for v in verdicts if not v["found_any"]]
    only_low = [v for v in verdicts if v["found_any"] and not v["found_default"]]
    found_unused = [v for v in verdicts if v["found_default"] and not v["used"]]
    found_used = [v for v in verdicts if v["found_default"] and v["used"]]

    check("retrieval returns the answering memory AT ALL (rejects RA)",
          len(never) == 0,
          f"never retrieved at any threshold: {[v['question'] for v in never]}")
    check("it is reachable within the DEFAULT window (limit=10, floor=0.5)",
          len(only_low) == 0,
          f"retrievable but ranked past the default window: "
          f"{[(v['question'], f'rank {v[chr(114)+chr(97)+chr(110)+chr(107)+chr(95)+chr(100)+chr(101)+chr(102)+chr(97)+chr(117)+chr(108)+chr(116)]}') for v in only_low]}")
    check("and the reply USES what retrieval returned (rejects RB/RC)",
          len(found_unused) == 0,
          f"retrieved but unused: {[(v['question'], f'rank {v[chr(114)+chr(97)+chr(110)+chr(107)+chr(95)+chr(100)+chr(101)+chr(102)+chr(97)+chr(117)+chr(108)+chr(116)]}') for v in found_unused]}")

    print(f"\n  answered correctly: {len(found_used)}/{len(PROBES)}")
    passed = sum(1 for c in CHECKS if c["passed"])
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
