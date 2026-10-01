#!/usr/bin/env python3
"""MESSAGE-01 — the substrate speaks first: unasked, at its time, once, to whoever listens for that person.

A reply answers a turn. This is the substrate saying something with no turn before it (`coord.speak_to`): work a
person asked for has ended, a moment they were to be told of has come. On the running substrate, in the SANDBOX:

  A  pushed: a person's work ends while they say nothing, and a front end listening for them (`on_message`) is
     told how it ended and what it found -- no turn of theirs in between; their next turn does not repeat it;
  B  held: with no one listening, it waits; their next turn brings it, once;
  C  at its time: a message owed for a later moment is said then, not before;
  D  owed across a restart: a message still owed when its timed job is gone (as after the process ends) is armed
     again by what the substrate does at boot (`_rearm_messages`), and said at its time;
  E  every front end of that person is told; another person is told nothing;
  F  what it said is in that person's conversation, as said by the substrate;
  G  the main model's store is untouched.

Runs in the SANDBOX (`lyric_dev`) and does not empty it. The messages it owes are removed by person, and the pursuit
memories its turns form by id. Left, named by this run's nonce: the people's job records in the queue's history and
their turns' experiences in the memory agent's pool.

    ./venv_lyric/bin/python3 experiments/MESSAGE-01/experiment.py
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
             "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

NONCE = uuid.uuid4().hex[:6]
ANN, BEN, CAL, OTHER = (f"message_{who}_{NONCE}" for who in ("ann", "ben", "cal", "other"))

EV = RunRecord(
    "MESSAGE-01",
    claim=("The substrate says something to a person with no turn before it: when their work ends and at a moment "
           "set, pushed to every front end listening for them, held for their next turn when none listens, once, "
           "still owed after a restart, and recorded in their conversation."),
    hypothesis=("Work that ends said only when the person speaks again, a message said early, twice, to the wrong "
                "person, lost when its timed job is gone, missing from the conversation, or a write to the main store "
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
        await system.start()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        await get_database_manager().assert_database_identity("lyric_dev")
    work = Path(tempfile.mkdtemp(prefix="message01_"))
    note = work / "note.txt"
    note.write_text("A robin is a bird.\n")
    plan = [{"tool": "read_file", "args": {"file_path": str(note)}}]
    pursuits, stops = [], []
    heard = {who: [] for who in (ANN, BEN, CAL, OTHER, "ann_second")}

    def listen(who, as_=None):
        stops.append(coord.on_message(who, lambda m, k=as_ or who: heard[k].append((time.time(), m))))

    async def turn(text, who, *, with_plan=False):
        meta = {"actor_identity": who, "session_id": f"session_{who}"}
        if with_plan:
            meta["parameters"] = {"tool_plan": plan}
        reply = await coord.handle_user_request(text, source="api", metadata=meta)
        if reply.get("pursuit_memory_id"):
            pursuits.append(reply["pursuit_memory_id"])
        say_line(f"    {who[8:11]}: {text!r} -> {str(reply.get('answer'))[:160]!r}")
        return reply

    async def ended(task_id, who, wait_s=240):
        deadline = time.time() + wait_s
        while time.time() < deadline:
            status = (await coord.get_task_result(task_id, actor=who)).get("status")
            if status in ("completed", "failed"):
                return status
            await asyncio.sleep(1)
        return None

    async def told_about(who, about, wait_s):
        deadline = time.time() + wait_s
        while time.time() < deadline:
            got = [(t, m) for t, m in heard[who] if m.get("about") == about]
            if got:
                return got[0]
            await asyncio.sleep(0.25)
        return None

    try:
        say_line("== A. Pushed: work ends while they say nothing ==")
        listen(ANN)
        asked = await turn("Help me.", ANN, with_plan=True)
        job = asked.get("task_id")
        got = await told_about(ANN, job, 240)
        check("a front end listening for them is told, with no turn of theirs in between", got is not None,
              f"{got[1]['text'] if got else None}")
        check("it says how the work ended and what it found",
              got is not None and 'Finished: "Help me."' in got[1]["text"]
              and "It says: A robin is a bird." in got[1]["text"] and got[1]["why"] == "work ended",
              f"{got[1] if got else None}")
        after = await turn("What is a robin?", ANN)
        check("their next turn does not repeat it", "Finished" not in after["answer"], after["answer"])

        say_line("\n== B. Held: no one listening ==")
        asked = await turn("Help me.", BEN, with_plan=True)
        job_b = asked.get("task_id")
        check("the work ends", await ended(job_b, BEN) == "completed")
        await asyncio.sleep(1)
        check("no one else is told", not any(m.get("about") == job_b for who in heard for _, m in heard[who]))
        first = await turn("What is a robin?", BEN)
        check("their next turn brings it", 'Finished: "Help me."' in first["answer"]
              and any(m.get("about") == job_b for m in first.get("messages") or []), first["answer"])
        second = await turn("What is a robin?", BEN)
        check("once", "Finished" not in second["answer"], second["answer"])

        say_line("\n== C. At its time ==")
        set_at = time.time()
        owed = await coord.speak_to(ANN, "Time to check the pump.", why="reminder",
                                    at=datetime.now(timezone.utc) + timedelta(seconds=4))
        await asyncio.sleep(2)
        check("not before its time", not any(m.get("message_id") == owed["message_id"] for _, m in heard[ANN]))
        deadline = time.time() + 10
        while time.time() < deadline and not any(m.get("message_id") == owed["message_id"] for _, m in heard[ANN]):
            await asyncio.sleep(0.2)
        at = next((t for t, m in heard[ANN] if m.get("message_id") == owed["message_id"]), None)
        check("said at its time", at is not None and 3.8 <= at - set_at <= 6.0,
              f"said {at - set_at:.1f}s after it was set for 4s" if at else "never said")

        say_line("\n== D. Still owed after a restart ==")
        listen(CAL)
        later = await coord.speak_to(CAL, "Check the valve.", why="reminder",
                                     at=datetime.now(timezone.utc) + timedelta(seconds=5))
        gone = coord.task_queue.cancel(f"say:{later['message_id']}")
        check("its timed job is gone, as when the process ends", gone)
        held = await coord.outbox.get(later["message_id"])
        check("the message is still owed in the outbox", held is not None and held["delivered_at"] is None)
        armed_at = time.time()
        await coord._rearm_messages()
        deadline = time.time() + 12
        while time.time() < deadline and not heard[CAL]:
            await asyncio.sleep(0.2)
        check("armed again, as at boot, it is said at its time", bool(heard[CAL])
              and heard[CAL][0][1]["message_id"] == later["message_id"] and heard[CAL][0][0] - armed_at >= 3.5,
              f"{heard[CAL][0][0] - armed_at:.1f}s after arming" if heard[CAL] else "never said")

        say_line("\n== E. Every front end of that person, and no one else ==")
        listen(ANN, "ann_second")
        listen(OTHER)
        both = await coord.speak_to(ANN, "Both of your screens should show this.", why="note")
        await asyncio.sleep(1)
        check("each front end listening for them is told",
              any(m["message_id"] == both["message_id"] for _, m in heard[ANN])
              and any(m["message_id"] == both["message_id"] for _, m in heard["ann_second"]))
        check("another person is told nothing", not heard[OTHER], f"{heard[OTHER]}")
        stored = await coord.outbox.get(both["message_id"])
        check("it is delivered once, by being pushed", stored["delivered_by"] == "push", f"{stored['delivered_by']}")

        say_line("\n== F. In their conversation ==")
        conv = coord.conversation(f"session_{ANN}", actor_identity=ANN)
        said = [t.reply for t in conv._turns if t.said == ""]
        check("what it said unasked is a turn of its own in their conversation",
              "Both of your screens should show this." in said and "Time to check the pump." in said, f"{said}")
    finally:
        for stop in stops:
            stop()
        removed = 0
        for who in (ANN, BEN, CAL, OTHER):
            removed += await coord.outbox.forget(who)
        gone = 0
        for mid in dict.fromkeys(pursuits):
            gone += bool(await coord.memory.delete_memory(mid, reason="MESSAGE-01"))
        say_line(f"\n    messages removed: {removed}; pursuit memories deleted: {gone}")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.shutdown()
        note.unlink(missing_ok=True)
        work.rmdir()

    say_line("\n== G. The main model ==")
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_before == main_after,
          f"{main_before} rows before, {main_after} after")
    EV.note(f"nonce {NONCE}: left in the sandbox, the people's job records in the queue's history and their turns' "
            f"experiences in the memory agent's pool")
    await EV.verify_database()
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
