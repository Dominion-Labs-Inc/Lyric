#!/usr/bin/env python3
"""TAUGHT-IN-ENGLISH-01 — can the substrate be taught in natural language, and
answer in natural language?

────────────────────────────────────────────────────────────────────────────
WHAT THIS MEASURES, AND WHY MEMORY IS THE ONLY SOURCE

The substrate holds 306,743 concepts and 581,000 beliefs, and 305,452 of those
concepts were BULK-LOADED from WordNet, ConceptNet and Wikidata before the
teaching door always wrote a memory (resolved 2026-09-20, docs/TEACHING.md
§7.3). The substrate has no recollection of learning any of it.

That material is therefore not what this experiment is about and is not
measured here. Knowledge the substrate was not TAUGHT is untaught knowledge,
whatever table it sits in. So the only store consulted for acquisition is
`memory_hot` — if a taught fact is not in memory, it was not learned.

The question is the one a design partner will ask first:

    Can I teach it the way I would teach a person — in sentences — and will it
    answer me in sentences?

────────────────────────────────────────────────────────────────────────────
HYPOTHESES, REGISTERED BEFORE RUNNING

  H1  Teaching in plain English writes MEMORIES. Not concepts, not rows in a
      graph — memories, because that is what the substrate recalls from.

  H2  It can answer, in plain English, questions whose answers it was told
      directly (what a thing is; what it does).

  H3  It can answer questions whose answers it was NOT told directly, but
      which follow from two things it was told. This separates recall from
      comprehension, and it is the one that matters: parroting a sentence back
      is retrieval, not understanding.

  STATED IN ADVANCE so a null result is not reframed afterwards:
    - H3 may fail while H1 and H2 hold. That would mean the substrate stores
      and recalls English but does not compose over it, which is a precise and
      reportable finding, not a failure of the experiment.
    - Answers are judged on CONTENT (does the reply carry the right thing), not
      on phrasing. The expected token for each question is stated below so the
      judgement is fixed before the answers are seen.

────────────────────────────────────────────────────────────────────────────
DESIGN

Invented vocabulary, asserted absent before teaching, so nothing already in the
store can supply an answer and the ground truth is exactly what was said.
Everything is taught through `understand` — the same path a person talking to
it uses — and every question is asked the same way.
"""
import asyncio
import contextlib
import io
import os
import sys
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
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
    "A clogged threlp stops a marnic.",
]

#: (question, what a correct answer must carry, why this question is here).
#: Fixed before any answer is seen.
TOLD_DIRECTLY = [
    ("What is a marnic?", ("device",), "it was told this in so many words"),
    ("What does a marnic do?", ("filter", "brine"), "told directly"),
    ("What is a threlp?", ("membrane",), "told directly"),
    ("What does a dovick do?", ("clean", "threlp"), "told directly"),
]

#: Never stated. Each follows from TWO taught sentences.
NOT_TOLD = [
    ("What is inside a marnic?", ("threlp",),
     "'a marnic contains a threlp' — asked from the other side"),
    ("What stops a marnic?", ("threlp", "clog"),
     "'a clogged threlp stops a marnic' — asked from the effect"),
    ("What cleans the thing inside a marnic?", ("dovick",),
     "joins 'a marnic contains a threlp' with 'a dovick cleans a threlp'"),
]

#: What an answer that DOES NOT answer looks like. The substrate says so
#: plainly, which is the behaviour we want -- the problem was that the scoring
#: did not listen.
_REFUSALS = (
    "i hold nothing for",
    "i don't hold",
    "i do not hold",
    "i did not have",
    "i don't have",
)


def answers(question, answer, expected):
    """Whether this reply ANSWERS the question, not merely contains a word.

    THE FIRST VERSION OF THIS SCORED A REFUSAL AS CORRECT. Asked "What stops a
    marnic?", the substrate replied, honestly:

        I remember: A marnic is a device.
        A marnic contains threlp. It filters brine. It is a device.
        I hold nothing for stops. Tell me what it is and I will keep it.

    `any(e in answer.lower() for e in ("threlp", "clog"))` matched `threlp` --
    out of the recall line about what a marnic CONTAINS, which has nothing to
    do with what stops one. The substrate said it did not know and was marked
    right, so the experiment was measuring its own string matching.

    Two things are required now, and both make the test HARDER, never easier:

      * THE REPLY MUST NOT REFUSE. A reply that says it holds nothing for the
        thing asked about is not a wrong answer, it is not an answer, and it
        cannot count as one whatever else the reply quotes.
      * THE TOKEN MUST BE IN THE ANSWER, NOT THE PREAMBLE. Everything after
        "I remember:" up to the newline is the substrate quoting what recall
        returned -- it is what it looked at, not what it concluded. A token
        found only there means recall surfaced the right memory and the
        substrate did not use it, which is exactly the distinction H3 exists
        to draw.

    Returns (passed, why_not) so a failure says which test it failed.
    """
    low = answer.lower()
    for phrase in _REFUSALS:
        if phrase in low:
            return False, "refused"

    # Drop the "I remember: ..." recall preamble, line by line.
    body = "\n".join(line for line in answer.splitlines()
                      if not line.lower().lstrip().startswith("i remember:"))
    hit = [e for e in expected if e in body.lower()]
    if hit:
        return True, ""
    if any(e in low for e in expected):
        return False, "only in the recalled preamble, not in the answer"
    return False, "the answer does not carry it"


CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def observe(name, detail):
    print(f"  [ ..  ] {name} — {detail}")


async def main():
    quiet = io.StringIO()
    print("starting the substrate...", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.database.unified_database_postgres import TorinUnifiedDatabase
    db = TorinUnifiedDatabase()
    if not db.initialized:
        await db.initialize()

    check("the LIVE substrate is running and registered",
          get_autonomous_coordinator() is coordinator)

    like = [f"%{t}%" for t in TERMS]

    async def one(sql, params=None):
        rows = await db.execute_query(sql, params, fetch_all=True) or []
        return rows[0]["n"] if rows else 0

    async def memories():
        """THE ONLY STORE THIS EXPERIMENT TREATS AS KNOWLEDGE."""
        rows = await db.execute_query(
            "SELECT memory_type, content FROM memory_hot.memory_hot "
            "WHERE lower(content) LIKE ANY($1)", (like,), fetch_all=True) or []
        return rows

    # REPEATABLE BY CONSTRUCTION. A prior run's memories would answer the
    # questions and the result would measure the last run, not this one. The
    # invented vocabulary exists nowhere else, so removing exactly what mentions
    # it restores the baseline without touching anything the substrate learned
    # for real.
    # MEMORIES ARE NOT THE ONLY TRACE A RUN LEAVES. Clearing them alone left the
    # CONCEPTS from the previous run in place, and the substrate answered "a
    # marnic contains threlp, it is a device" before being taught anything —
    # the baseline check caught it, and every number in that run was measuring
    # the run before it. Everything the invented vocabulary touched goes.
    stale = await memories()
    cleared = {}
    for table, column in (("memory_hot.memory_hot", "content"),
                          ("unified.concepts", "name"),
                          ("unified.concept_relations", "source_concept_id"),
                          ("unified.concept_relations", "target_surface"),
                          ("unified.concept_domains", "concept_id"),
                          ("unified.beliefs", "belief_text")):
        try:
            n = await one(f"SELECT COUNT(*) n FROM {table} "
                          f"WHERE lower({column}) LIKE ANY($1)", (like,))
            if n:
                await db.execute_query(
                    f"DELETE FROM {table} WHERE lower({column}) LIKE ANY($1)", (like,))
                cleared[f"{table}.{column}"] = n
        except Exception as e:
            print(f"  [setup] could not clear {table}.{column}: {type(e).__name__}")
    if cleared:
        print(f"  [setup] cleared traces of a previous run: {cleared}")
    before = await memories()
    check("the substrate has no memory of this subject yet",
          len(before) == 0, f"{len(before)} memory(ies) mentioning {TERMS}")
    if before:
        print("\n  baseline violated. Stopping.")
        return 1

    session = coordinator.conversation(session=f"taught:{uuid4().hex[:8]}")

    async def say(sentence):
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            u = await session.understand(sentence)
        return str(getattr(u, "reply", "") or "").strip()

    naive = await say("What is a marnic?")
    check("and cannot answer about it before being taught",
          "device" not in naive.lower(), f"-> {naive[:90]!r}")

    # ── the lesson, in plain English ─────────────────────────────────────────
    print("\n== Teaching it, in sentences ==")
    for sentence in LESSON:
        reply = await say(sentence)
        print(f"    said: {sentence:<44} heard: {reply[:52]!r}")

    # ── H1 ───────────────────────────────────────────────────────────────────
    print("\n== H1. Did being told in English put it in MEMORY? ==")
    after = await memories()
    kinds = {}
    for row in after:
        kinds[row["memory_type"]] = kinds.get(row["memory_type"], 0) + 1
    check("being taught in English wrote memories",
          len(after) > 0, f"{len(before)} -> {len(after)}  by type: {kinds}")
    check("it remembers a memory PER thing it was told",
          len(after) >= len(LESSON),
          f"{len(after)} memory(ies) for {len(LESSON)} sentence(s)")

    # ── H2 ───────────────────────────────────────────────────────────────────
    print("\n== H2. Can it answer, in English, what it was told? ==")
    told_right = 0
    for question, expected, why in TOLD_DIRECTLY:
        answer = await say(question)
        ok, why_not = answers(question, answer, expected)
        told_right += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {question:<34} -> {answer[:74]!r}")
        if not ok:
            print(f"         ({why_not})")
    check("it answers what it was told directly",
          told_right == len(TOLD_DIRECTLY),
          f"{told_right}/{len(TOLD_DIRECTLY)} correct")

    # ── H3 ───────────────────────────────────────────────────────────────────
    print("\n== H3. Can it answer what it was NEVER told, but follows? ==")
    composed = 0
    for question, expected, why in NOT_TOLD:
        answer = await say(question)
        ok, why_not = answers(question, answer, expected)
        composed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {question:<40} -> {answer[:66]!r}")
        print(f"         ({why})")
        if not ok:
            print(f"         -> {why_not}")
    check("it composes over what it was taught",
          composed == len(NOT_TOLD), f"{composed}/{len(NOT_TOLD)} correct")

    observe("recall vs comprehension",
            f"told-directly {told_right}/{len(TOLD_DIRECTLY)}, "
            f"never-told {composed}/{len(NOT_TOLD)}")

    passed = sum(1 for c in CHECKS if c["passed"])
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
