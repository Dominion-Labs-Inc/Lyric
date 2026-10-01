#!/usr/bin/env python3
"""TASKS-AT-ONCE-01 — sixty tasks at once, three per person at most.

The substrate's work runs under one acting budget that the queue authority holds, and each person may hold at most
three of those slots at once. On the running substrate, in the SANDBOX:

  A  the budget: the queue authority runs sixty work jobs at once, the substrate draws up to sixty, three per
     person; a size given after the authority exists is put in force, and is never changed under running work;
  B  twenty people ask for four jobs each and one more person for two, through the one front door; all are taken on;
  C  at once: sixty jobs run at the same moment, inside the queue authority's budget, never more; every person
     holds three at once and never a fourth; a person's fourth job starts only once one of theirs has ended; the
     one more person's jobs wait for a slot to free; every job ends done, its note read, under that load; each
     person is told how each of their jobs ended;
  D  the main model's store is untouched.

THE ONE STAND-IN: each job first holds its slot for HOLD_S seconds, as work waiting on the world does (a page to
load, a mail server to answer), then does its real job -- reading its note through the job's tool. Without the
wait the jobs end too fast to overlap. The substrate's own exploration is turned off for the run (its own setting,
LYRIC_INTRINSIC_EXPLORATION_CAP=0), so every slot counted is a person's.

Runs in the SANDBOX (`lyric_dev`) and does not empty it. The messages owed to the people are removed by person, and
the pursuit memories their turns form by id. Left, named by this run's nonce: their job records in the queue's
history, and their turns' and readings' experiences in the memory agent's pool.

    ./venv_lyric/bin/python3 experiments/TASKS-AT-ONCE-01/experiment.py
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
             "TQDM_DISABLE": "1", "LYRIC_INTRINSIC_EXPLORATION_CAP": "0"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

NONCE = uuid.uuid4().hex[:6]
PEOPLE = [f"atonce_{i:02d}_{NONCE}" for i in range(20)]
LATE = f"atonce_late_{NONCE}"
EACH, AT_ONCE, PER_PERSON, HOLD_S = 4, 60, 3, 10.0

EV = RunRecord(
    "TASKS-AT-ONCE-01",
    claim=("The substrate runs sixty tasks at once, inside the queue authority's one acting budget, and no person "
           "holds more than three of them at once; work past that waits for a slot and is then done."),
    hypothesis=("A budget smaller than sixty in force anywhere (the queue authority's own, the substrate's gate, a "
                "ceiling), a person holding a fourth slot, work lost or failed under the load, or a write to the "
                "main store would each show here."))


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
    from core.agents.autonomous.queue_authority import QueueAuthority
    work = Path(tempfile.mkdtemp(prefix="atonce_"))
    pursuits, jobs = [], {}

    say_line("== A. The budget ==")
    check("the queue authority runs sixty work jobs at once", coord.task_queue.max_parallel == AT_ONCE
          and coord.task_queue._semaphore._value == AT_ONCE, f"{coord.task_queue.max_parallel}")
    check("the substrate draws up to sixty, three per person",
          coord._effective_max_parallel() == AT_ONCE and coord._per_actor_max == PER_PERSON,
          f"{coord._effective_max_parallel()} at once, {coord._per_actor_max} per person")
    made_first = QueueAuthority(config={"max_parallel": 5, "persist": False})
    made_first.configure({"max_parallel": AT_ONCE})
    check("a size given after the authority exists is put in force",
          made_first.max_parallel == AT_ONCE and made_first._semaphore._value == AT_ONCE)
    held = asyncio.Event()

    async def hold():
        await held.wait()
    running = asyncio.create_task(made_first.execute("held", hold))
    await asyncio.sleep(0.05)
    try:
        made_first.configure({"max_parallel": 7})
        refused = False
    except RuntimeError:
        refused = True
    held.set()
    await running
    check("never changed under running work", refused and made_first.max_parallel == AT_ONCE)

    say_line("\n== B. Twenty-one people ask ==")
    for who in PEOPLE + [LATE]:
        for k in range(EACH if who != LATE else 2):
            note = work / f"{who}_{k}.txt"
            note.write_text("A robin is a bird.\n")
            meta = {"actor_identity": who, "session_id": f"session_{who}",
                    "parameters": {"tool_plan": [{"tool": "read_file", "args": {"file_path": str(note)}}]}}
            reply = await coord.handle_user_request("Help me.", source="api", metadata=meta)
            if reply.get("pursuit_memory_id"):
                pursuits.append(reply["pursuit_memory_id"])
            if reply.get("task_id"):
                jobs[reply["task_id"]] = who
    wanted = len(PEOPLE) * EACH + 2
    check("every job asked for is taken on", len(jobs) == wanted, f"{len(jobs)}/{wanted}")

    say_line("\n== C. At once ==")
    started, ended, now_running, most_of = {}, {}, {}, {}
    peak = {"ours": 0, "inflight": 0}
    real_job = coord._execute_and_validate_task

    async def job(task):
        who = jobs.get(task.id)
        if who is None:
            return await real_job(task)
        started[task.id] = time.time()
        now_running[who] = now_running.get(who, 0) + 1
        most_of[who] = max(most_of.get(who, 0), now_running[who])
        peak["ours"] = max(peak["ours"], sum(now_running.values()))
        try:
            await asyncio.sleep(HOLD_S)
            return await real_job(task)
        finally:
            now_running[who] -= 1
            ended[task.id] = time.time()

    coord._execute_and_validate_task = job

    async def watch():
        while True:
            peak["inflight"] = max(peak["inflight"], len(coord._inflight_tasks))
            await asyncio.sleep(0.02)

    watcher = asyncio.create_task(watch())
    began = time.time()
    status = {}
    try:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.start()
        deadline = time.time() + 900
        while time.time() < deadline:
            for task_id, who in jobs.items():
                if status.get(task_id) not in ("completed", "failed", "cancelled"):
                    status[task_id] = (await coord.get_task_result(task_id, actor=who)).get("status")
            if all(s in ("completed", "failed", "cancelled") for s in status.values()) and len(status) == len(jobs):
                break
            await asyncio.sleep(1)
        # A job's record says completed before the job's own work after it is done: wait for every job to end.
        while len(ended) < len(started) and time.time() < deadline:
            await asyncio.sleep(0.5)
        took = max(ended.values(), default=began) - min(started.values(), default=began)
        watcher.cancel()

        check("sixty jobs run at the same moment, inside the queue authority's budget", peak["ours"] == AT_ONCE,
              f"{peak['ours']} at once; all {len(ended)} ended {took:.0f}s after the first began, "
              f"each holding its slot {HOLD_S:.0f}s")
        check("never more than sixty in flight", peak["inflight"] <= AT_ONCE, f"{peak['inflight']}")
        check("every person holds three at once, and never a fourth",
              all(most_of.get(who) == PER_PERSON for who in PEOPLE) and max(most_of.values()) <= PER_PERSON,
              f"{sorted(set(most_of.values()))}")
        fourth_waited = []
        for who in PEOPLE:
            mine = sorted((started[t], t) for t, w in jobs.items() if w == who and t in started)
            if len(mine) == EACH:
                first_end = min(ended[t] for _, t in mine[:PER_PERSON])
                fourth_waited.append(mine[-1][0] >= first_end)
        check("a person's fourth job starts only once one of theirs has ended",
              len(fourth_waited) == len(PEOPLE) and all(fourth_waited), f"{sum(fourth_waited)}/{len(PEOPLE)}")
        late = [started[t] for t, w in jobs.items() if w == LATE and t in started]
        first_round_end = min(ended.values(), default=0)
        check("the one more person's jobs wait for a slot to free",
              len(late) == 2 and min(late) >= first_round_end,
              f"started {min(late) - began:.1f}s in, first slot freed {first_round_end - began:.1f}s in" if late else
              "never started")
        done = [t for t, s in status.items() if s == "completed"]
        check("every job ends done, under that load", len(done) == len(jobs),
              f"{len(done)}/{len(jobs)} completed; {dict((s, list(status.values()).count(s)) for s in set(status.values()))}")
        read = 0
        for who in PEOPLE + [LATE]:
            for seen in await coord.task_queue.work_of(who, limit=EACH):
                read += seen["task_id"] in jobs and any("A robin is a bird." in str(r.get("says"))
                                                         for r in (seen.get("read") or []))
        check("its note read", read == len(jobs), f"{read}/{len(jobs)}")
        await asyncio.sleep(2)
        told = set()
        for who in PEOPLE + [LATE]:
            told |= {m.get("about") for m in await coord.outbox.waiting(who)}
        check("each person is told how each of their jobs ended", set(jobs) <= told,
              f"{len(set(jobs) & told)}/{len(jobs)}")
    finally:
        watcher.cancel()
        removed = 0
        for who in PEOPLE + [LATE]:
            removed += await coord.outbox.forget(who)
        gone = 0
        for mid in dict.fromkeys(pursuits):
            gone += bool(await coord.memory.delete_memory(mid, reason="TASKS-AT-ONCE-01"))
        say_line(f"\n    messages removed: {removed}; pursuit memories deleted: {gone}")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.shutdown()
        for note in work.iterdir():
            note.unlink()
        work.rmdir()

    say_line("\n== D. The main model ==")
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_before == main_after,
          f"{main_before} rows before, {main_after} after")
    EV.note(f"nonce {NONCE}: left in the sandbox, the people's job records in the queue's history and their turns' "
            f"and readings' experiences in the memory agent's pool")
    await EV.verify_database()
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
