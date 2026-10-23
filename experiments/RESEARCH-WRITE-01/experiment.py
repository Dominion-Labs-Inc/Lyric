#!/usr/bin/env python3
"""RESEARCH-WRITE-01 — the live substrate is given a topic, told to research it,
write what it learned to a file, and verify the file before calling it done.

WHY THIS AND NOT ANOTHER FILE-MOVE. Every operator the store held was a file
relocation relearned in a sandbox, and the experiments that produced them all
handed the substrate a tool and a pair of paths. That measures the harness. This
gives it a GOAL, in words, and nothing else: it is set the way the substrate
sets its own (`set_goal`), the live queue hands it out, its pursuit decomposes
it and walks the steps through the live coordinator, the live knowledge loop
does the research, and completion is judged by re-reading the world rather than
by the tool's own report.

WHAT IT TOUCHES, all of it live and none of it stubbed:
    goals               set_goal -> its intent -> the queue
    the pursuit         _pursue_described_goal -> plan_described_goal -> each step
    knowledge loop      `understand` — memory, then reasoning, then a gap
    tool usage          whatever the substrate decides to run
    verification        the file is read BACK and its contents checked
    completion          claimed only after that reading
    learning            the write should leave a before/action/after behind

NOTHING HERE NAMES A TOOL. If the substrate does not write the file, that is the
result, and the experiment says so rather than writing it on the substrate's
behalf and reporting success.
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

# THE STANDARD RECORD. This printed its result and wrote NOTHING: every run of it
# left no record at all, only whatever the terminal happened to keep.
EV = RunRecord(
    "RESEARCH-WRITE-01",
    claim=("Given a goal in words and no tool, the live substrate researches the "
           "topic, writes what it learned to a file, and verifies the file before "
           "calling the goal done."),
    hypothesis=("If the pursuit decomposes the goal, the knowledge loop does the "
                "research, the creation step makes the declared artefact, and "
                "completion re-reads the world, then the file exists with researched "
                "content and completion is claimed only after reading it back."))

TOPIC = "photosynthesis"
CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    EV.check(name, bool(passed), detail)
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.agents.autonomous.shared_types import Priority, SUBSTRATE_ACTOR
    from core.database.unified_database_postgres import LyricUnifiedDatabase
    from core.reasoning.intent_authority import continuity_goal, get_intent_authority

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator)

    # WHAT THE PURSUIT DID, recorded as it returns it. The queue keeps a failed
    # job's error and not its steps, so the steps are read where they are made.
    walked = {}
    _pursue = coordinator._pursue_described_goal

    async def recorded_pursuit(task):
        out = await _pursue(task)
        if out is not None:
            walked[task.id] = out
        return out
    coordinator._pursue_described_goal = recorded_pursuit

    db = LyricUnifiedDatabase()
    if not db.initialized:
        await db.initialize()

    async def count(sql):
        rows = await db.execute_query(sql, fetch_all=True) or []
        return rows[0]["n"] if rows else 0

    workspace = Path(tempfile.mkdtemp(prefix="researchwrite_"))
    target = workspace / "findings.md"

    concepts_before = await count("SELECT COUNT(*) n FROM unified.concepts")
    beliefs_before = await count("SELECT COUNT(*) n FROM unified.beliefs")
    demos_before = await count("SELECT COUNT(*) n FROM unified.operator_demonstrations")

    # ── A. the goal, in words, and nothing else ──────────────────────────────
    print(f"\n== A. A goal in words — no tool named, no path wired ==")
    description = (f"Research {TOPIC} and create a written summary of what you "
                   f"learned at {target}")
    print(f"    goal: {description}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        goal_id = await coordinator.set_goal(description, Priority.HIGH)
    check("the substrate took the goal on", goal_id is not None, f"goal_id={goal_id}")
    held = await get_intent_authority().get(
        SUBSTRATE_ACTOR, continuity_goal(goal_id)) if goal_id else None
    check("the goal IS its intent, how much it matters on its shape",
          held is not None and held.origin_kind == "self_goal"
          and held.shape.get("priority") == Priority.HIGH.value and held.aim == description,
          f"intent={getattr(held, 'intent_id', None)} "
          f"priority={(held.shape if held else {}).get('priority')}")

    # ── B. the queue hands the work out ──────────────────────────────────────
    print("\n== B. The live queue hands the work out ==")
    first = await coordinator.task_queue.result_for(goal_id, actor=SUBSTRATE_ACTOR) \
        if goal_id else {"status": "not_found"}
    check("the goal was queued as work, for the one dispatcher",
          first.get("status") not in (None, "not_found"), f"status={first.get('status')}")
    # A PURSUIT IS NOT ONE STEP. It is waited on until the queue says it ended,
    # which is the queue's own answer, not a sleep that might pass for one.
    ended = first
    while goal_id and ended.get("status") not in ("completed", "failed", "not_found"):
        await asyncio.sleep(0.5)
        ended = await coordinator.task_queue.result_for(goal_id, actor=SUBSTRATE_ACTOR)
    check("the live loop ran it to an ending",
          ended.get("status") in ("completed", "failed"), f"status={ended.get('status')}")

    # ── C. the pursuit decomposed the goal and walked every step ─────────────
    print("\n== C. Its pursuit decomposes the goal and walks it to the end ==")
    pursued = walked.get(goal_id) or {}
    steps = list(pursued.get("steps") or [])
    for step in steps:
        print(f"    {step['type']:<10} {str(step['description'])[:44]:<44} "
              f"success={step['success']}")
    held = await get_intent_authority().get(
        SUBSTRATE_ACTOR, continuity_goal(goal_id)) if goal_id else None
    planned = int((held.shape if held else {}).get("steps") or 0)
    check("and decomposed it into steps, recorded on the goal's intent",
          planned > 0 and bool((held.shape if held else {}).get("step_kinds")),
          f"{planned} step(s): {(held.shape if held else {}).get('step_kinds')}")
    check("every step of the plan was reached and ran",
          planned > 0 and len(steps) == planned,
          f"{len(steps)}/{planned} step(s) run; "
          f"{sum(1 for st in steps if st['success'])} succeeded")

    # ── D. did it actually LEARN anything ────────────────────────────────────
    print("\n== D. Research means knowledge changed, not a step marked done ==")
    concepts_after = await count("SELECT COUNT(*) n FROM unified.concepts")
    beliefs_after = await count("SELECT COUNT(*) n FROM unified.beliefs")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        understanding = await coordinator.conversation(
            session=f"rw01:{uuid4().hex[:8]}").understand(f"what is {TOPIC}?")
    answered = bool(getattr(understanding, "answered", None))
    check("it can answer about the topic from what it holds",
          answered, str(getattr(understanding, "answered", ""))[:150])
    check("researching moved the knowledge stores (or it already knew)",
          concepts_after >= concepts_before and beliefs_after >= beliefs_before,
          f"concepts {concepts_before}->{concepts_after}, "
          f"beliefs {beliefs_before}->{beliefs_after}")

    # ── E. the file, and whether its CONTENTS are the work ───────────────────
    print("\n== E. The artefact — and whether it is real ==")
    check("the file it was asked for exists", target.exists(), str(target))
    body = target.read_text() if target.exists() else ""
    check("it is not empty", len(body.strip()) > 0, f"{len(body)} byte(s)")
    check("and its CONTENTS are about the topic it researched",
          TOPIC.lower() in body.lower(),
          (body[:160] + "…") if body else "nothing was written")

    # ── F. did it VERIFY before claiming done ────────────────────────────────
    print("\n== F. Completion rests on a reading, not on the tool's word ==")
    reading = getattr(coordinator, "reading", None)
    seen = False
    if reading is not None and target.exists():
        for probe in ("current", "has_read", "was_read", "record"):
            fn = getattr(reading, probe, None)
            if probe != "record" and callable(fn):
                try:
                    seen = bool(fn(str(target)))
                except Exception:
                    seen = False
                if seen:
                    break
    check("the substrate READ BACK the file it wrote", seen,
          "a fresh reading of the artefact is on record"
          if seen else "no reading of the artefact is on record")

    demos_after = await count("SELECT COUNT(*) n FROM unified.operator_demonstrations")
    check("and the act it performed left experience behind",
          demos_after > demos_before,
          f"demonstrations {demos_before} -> {demos_after}")

    # ── G. the pursuit is closed with how it ended ───────────────────────────
    print("\n== G. The goal's intent is closed with how it ended ==")
    closed = await get_intent_authority().get_by_id(held.intent_id) if held else None
    check("the goal's intent is concluded, not left `active`",
          closed is not None and closed.concluded,
          f"status={getattr(closed, 'status', None)}")

    coordinator._pursue_described_goal = _pursue
    shutil.rmtree(workspace, ignore_errors=True)
    passed = sum(1 for c in CHECKS if c["passed"])
    await EV.verify_database()
    written = EV.write()
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    print(f"run record: {written}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
