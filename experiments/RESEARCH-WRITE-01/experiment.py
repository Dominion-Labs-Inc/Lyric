#!/usr/bin/env python3
"""RESEARCH-WRITE-01 — the live substrate is given a topic, told to research it,
write what it learned to a file, and verify the file before calling it done.

WHY THIS AND NOT ANOTHER FILE-MOVE. Every operator the store held was a file
relocation relearned in a sandbox, and the experiments that produced them all
handed the substrate a tool and a pair of paths. That measures the harness. This
gives it a GOAL, in words, and nothing else: the live planning engine decomposes
it, the live queue orders it, the live coordinator executes it, the live
knowledge loop does the research, and completion is judged by re-reading the
world rather than by the tool's own report.

WHAT IT TOUCHES, all of it live and none of it stubbed:
    planning engine     create_goal -> generate_plan -> get_next_tasks
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
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
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
    hypothesis=("If planning decomposes the goal, the knowledge loop does the "
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
    from core.agents.autonomous.shared_types import Priority, SystemState
    from core.database.unified_database_postgres import LyricUnifiedDatabase

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator)
    planning = coordinator.planning
    check("the LIVE planning engine is attached", planning is not None,
          type(planning).__name__ if planning else "none")

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
        goal = await planning.create_goal(description, Priority.HIGH)
        plan = await planning.generate_plan(getattr(goal, "goal_id", None)
                                            or getattr(goal, "id", None))
    check("the LIVE planning engine accepted the goal",
          goal is not None, f"goal_id={getattr(goal, 'goal_id', None)}")
    steps = list(getattr(plan, "tasks", None) or []) if plan else []
    check("and decomposed it into a plan",
          bool(steps), f"{len(steps)} step(s): "
          f"{[(t.type.name, t.description[:34]) for t in steps][:4]}")

    # ── B. the queue orders the work ─────────────────────────────────────────
    print("\n== B. The live queue hands the work out ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        try:
            # A real snapshot. `SystemState` is a dataclass, not an enum —
            # `SystemState.IDLE` raises, and an experiment that swallows that
            # reports the QUEUE as empty when it was never asked.
            queued = await planning.get_next_tasks(SystemState())
            queue_error = None
        except Exception as e:
            queued, queue_error = [], f"{type(e).__name__}: {e}"
    if queue_error:
        print(f"    get_next_tasks raised: {queue_error}")
    check("the queue returned work to do",
          bool(queued), f"{len(queued)} task(s) ready")

    # ── C. the substrate works the plan until it drains ─────────────────────
    print("\n== C. The live coordinator works the plan to the end ==")
    from core.agents.autonomous.shared_types import TaskStatus

    ours = {t.id for t in steps}
    stale = [t for t in (queued or []) if t.id not in ours]
    results, rounds = [], 0
    # A PLAN IS NOT ONE ROUND. The create step depends on the research it writes
    # up, so it is correctly withheld until that completes — and a driver that
    # executes one batch and stops reports the artefact missing when it was
    # simply never reached.
    while rounds < 14:
        rounds += 1
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            ready = await planning.get_next_tasks(SystemState())
        if not ready:
            break
        # WORK WHATEVER THE QUEUE HANDS OUT, which is what a live substrate
        # does. Skipping other plans' steps leaves them PENDING, so they keep
        # their dispatch slots and this goal never gets one — the experiment
        # would be starving itself and calling it a defect.
        for task in ready:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                outcome = await coordinator.execute_task(task)
            ok = bool(outcome and outcome.get("success"))
            # Nothing in production advances a template plan's task status, so
            # the driver records what happened. A step that failed is left
            # PENDING, which is what keeps its dependents honestly blocked.
            task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
            if task.id in ours:
                results.append((task, outcome))
                print(f"    r{rounds} {task.type.name:<10} "
                      f"{task.description[:44]:<44} success={ok}")
    if stale:
        print(f"    (queue also held {len(stale)} stale task(s) from earlier runs: "
              f"{sorted({t.description[:22] for t in stale})})")
    check("every step of OUR plan was reached and ran",
          len(results) >= len(steps),
          f"{len(results)}/{len(steps)} step(s) run over {rounds} round(s); "
          f"{sum(1 for _t, o in results if o and o.get('success'))} succeeded")

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

    shutil.rmtree(workspace, ignore_errors=True)
    passed = sum(1 for c in CHECKS if c["passed"])
    await EV.verify_database()
    written = EV.write()
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    print(f"run record: {written}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
