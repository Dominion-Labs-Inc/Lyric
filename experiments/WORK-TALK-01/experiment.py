#!/usr/bin/env python3
"""WORK-TALK-01 — the conversation knows the substrate's own work: what it is doing, whether it finished, stop it.

A person talks to the substrate through the one front door (`handle_user_request`), typed or heard alike. The work
they ask for is held by the queue authority. On the real substrate, in the SANDBOX, with english_27 taught:

  A  work that waits: asked for, it is taken on and said so; "What are you working on?" names it; "Stop that."
     stops it before it runs, and its record says `cancelled`; asked again, nothing is running; another person
     asking sees none of it;
  B  work that runs: a job of theirs the queue authority is running (its work a long wait -- the one stand-in) is
     named by "Are you still working?", and "Cancel it." stops it where it is;
  C  work that finishes: the task loop runs a job of theirs to its end (a note read through the job's tool); their
     next turn, about anything, says how it ended and what it found, once; the turn after does not say it again;
     "Did you finish?" answers yes with what it found; asking only for what finished brings nothing new;
  D  "Don't stop." is keep going, and "Don't open the box." is answered, not made a job;
  E  the main model's store is untouched.

Runs in the SANDBOX (`lyric_dev`) and does not empty it. The pursuit memories its turns form are deleted by id.
Left, named by this run's nonce: the person's job records in the queue's history, and their turns' experiences in
the memory agent's pool.

    ./venv_lyric/bin/python3 experiments/WORK-TALK-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
             "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

NONCE = uuid.uuid4().hex[:6]
PERSON = f"worktalk_{NONCE}"
OTHER = f"worktalk_other_{NONCE}"
SESSION = f"worktalk_session_{NONCE}"

EV = RunRecord(
    "WORK-TALK-01",
    claim=("Through the one front door, the substrate answers what it is working on and whether it finished from "
           "the work the queue authority holds for that person, stops their work when asked -- waiting or running "
           "-- and tells them, once, how work they asked for ended and what it found."),
    hypothesis=("A request to stop taken as new work, work still running after it was stopped, a finished job never "
                "mentioned or mentioned twice, one person's work shown to another, or a write to the main store "
                "would each show here."))


def say_line(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


async def main_store_rows() -> int:
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="lyric_db")
    try:
        n = 0
        for t in await c.fetch("select table_schema s, table_name n from information_schema.tables "
                               "where table_schema in ('unified','memory_hot','memory_cold') "
                               "and table_type='BASE TABLE'"):
            n += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
        return n
    finally:
        await c.close()


async def main() -> int:
    main_before = await main_store_rows()
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        await get_database_manager().assert_database_identity("lyric_dev")
    work = Path(tempfile.mkdtemp(prefix="worktalk_"))
    pursuits = []

    async def turn(text, *, who=PERSON, plan=None, metadata=None):
        meta = {"actor_identity": who, "session_id": f"{SESSION}_{who}", **(metadata or {})}
        if plan is not None:
            meta["parameters"] = {"tool_plan": plan}
        reply = await coord.handle_user_request(text, source="api", metadata=meta)
        if reply.get("pursuit_memory_id"):
            pursuits.append(reply["pursuit_memory_id"])
        say_line(f"    {who[:9]}: {text!r} -> {str(reply.get('answer'))!r}")
        return reply

    async def status(task_id):
        return (await coord.get_task_result(task_id, actor=PERSON)).get("status")

    note = work / "note.txt"
    note.write_text("A robin is a bird.\n")
    reading_plan = [{"tool": "read_file", "args": {"file_path": str(note)}}]
    try:
        say_line("== A. Work that waits: named, stopped before it runs ==")
        asked = await turn("Help me.", plan=reading_plan)
        waiting = asked.get("task_id")
        check("the work is taken on, and said so", bool(waiting) and "on it" in str(asked.get("answer")),
              f"{asked.get('task_id')}")
        doing = await turn("What are you working on?")
        check("what it is working on names it", doing.get("about") == "doing" and "Help me." in doing["answer"])
        stopped = await turn("Stop that.")
        check("\"Stop that.\" stops that job, and is not a new one",
              stopped.get("about") == "stop" and stopped.get("task_id") == waiting, f"{stopped.get('task_id')}")
        check("it is stopped, and its record says so", await status(waiting) == "cancelled",
              f"{await status(waiting)}")
        again = await turn("What are you working on?")
        check("asked again, nothing is running", "Nothing you asked me is running." in again["answer"])
        theirs = await turn("What are you working on?", who=OTHER)
        check("another person sees none of it", "Help me." not in theirs["answer"], theirs["answer"])

        say_line("\n== B. Work that runs: stopped where it is ==")
        asked = await turn("Open the box.")
        running_id = asked.get("task_id")
        drawn = await coord.task_queue.get_next_task(timeout=0)
        check("the queue hands out their job, passing the stopped one",
              drawn is not None and drawn.task.id == running_id, f"{drawn.task.id if drawn else None}")

        async def long_wait():
            await asyncio.sleep(300)
            return {"answer": "waited"}

        runner = asyncio.create_task(coord.task_queue.execute(running_id, long_wait))
        await asyncio.sleep(0.5)
        still = await turn("Are you still working?")
        check("it is named while it runs", "Open the box." in still["answer"], still["answer"])
        started = time.time()
        await turn("Cancel it.")
        try:
            await asyncio.wait_for(runner, 5)
            stopped_where = False
        except asyncio.CancelledError:
            stopped_where = True
        except asyncio.TimeoutError:
            stopped_where = False
        check("the running job is stopped where it is", stopped_where,
              f"stopped after {time.time() - started:.2f}s")
        check("its record says so", await status(running_id) == "cancelled", f"{await status(running_id)}")
        jobs_before = len(await coord.task_queue.work_of(PERSON, limit=50))
        keep = await turn("Don't stop.")
        check("\"Don't stop.\" is keep going, not a stop", keep.get("about") == "keep", f"{keep.get('about')}")
        forbidden = await turn("Don't open the box.")
        check("a request not to act is answered, not taken on", forbidden.get("kind") == "forbidden",
              f"{forbidden.get('kind')}")
        check("neither became a job", len(await coord.task_queue.work_of(PERSON, limit=50)) == jobs_before)

        say_line("\n== C. Work that finishes: told once, with what it found ==")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.start()
        asked = await turn("Help me.", plan=reading_plan)
        finished_id = asked.get("task_id")
        deadline = time.time() + 240
        while time.time() < deadline and await status(finished_id) not in ("completed", "failed"):
            await asyncio.sleep(2)
        ended = await status(finished_id)
        check("the task loop ran it to its end", ended == "completed", f"{ended}")
        told = await turn("What is a robin?")
        check("their next turn, about anything, says how it ended",
              any(m.get("about") == finished_id for m in told.get("messages") or [])
              and 'Finished: "Help me."' in told["answer"], told["answer"])
        check("and what it found: what the note says, as the substrate read it",
              "note.txt. It says: A robin is a bird." in told["answer"], told["answer"])
        check("the turn itself was still answered", told["answer"].split("\n\n")[0] != "", told["answer"])
        told_again = await turn("What is a robin?")
        check("the turn after does not say it again", 'Finished: "Help me."' not in told_again["answer"],
              told_again["answer"])
        asked_done = await turn("Did you finish?")
        check("\"Did you finish?\" answers yes, with what it found",
              asked_done["answer"].startswith("Yes.") and "A robin is a bird." in asked_done["answer"],
              asked_done["answer"])
        polled = await coord.handle_user_request(
            "", source="api", metadata={"actor_identity": PERSON, "notices": True,
                                        "session_id": f"{SESSION}_{PERSON}"})
        check("asking only for what waits brings nothing new", not polled.get("messages"), f"{polled}")
    finally:
        gone = 0
        for mid in dict.fromkeys(pursuits):
            gone += bool(await coord.memory.delete_memory(mid, reason="WORK-TALK-01"))
        say_line(f"\n    pursuit memories formed and deleted: {gone}")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.shutdown()
        note.unlink(missing_ok=True)
        work.rmdir()

    say_line("\n== E. The main model ==")
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_before == main_after,
          f"{main_before} rows before, {main_after} after")
    EV.note(f"nonce {NONCE}: left in the sandbox, person {PERSON}'s job records in the queue's history and "
            f"their turns' experiences in the memory agent's pool")
    await EV.verify_database()
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
