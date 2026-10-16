#!/usr/bin/env python3
"""FIFTY-01 — what Lyric overcomes for one person, it does again at once, for them and for anyone.

The rule (docs/research/SEPARATION_MAP.md §11.4): from the first checked success a method is a candidate everyone's
work can use, so the second of fifty people does not meet the failure again. The memory agent lifts the first task of
a shape that worked into the world's method, keeping only what is no one's particular (`MemoryAgent._lift`,
`_no_ones`); a fix that overcame a failure is kept on the method (`fixes`), and a plan about to be done is given it
before it is done (`Capabilities.known_fix`).

  A  FIRST     Ana's first note, written into a new folder, worked: the first task of its shape that worked is lifted
               at once into a world method, with nothing of hers in it
  B  OVERCOME  her second, into another new folder with create_dirs false, failed, was retried with create_dirs true,
               and worked: the method keeps the fix, and still nothing of hers
  C  AGAIN     her third, the same way, asked through the front door: before any act, its plan has the fix and is
               the world's method, and her own earlier work is recalled for her
  D  ANYONE    Ben's, the same way: before any act, its plan has the fix and is the world's method; nothing of hers
               is recalled for him
  E  CONTROLS  a plan of another shape, and a plan that already has the fix, are given nothing

A and B are recorded by the coordinator's own recorder (`_store_task_outcome_meta_memory`), with the outcomes written
here, as a task's conclusion records them: a person's declared write has no account under the constitution's Law 2
today, so it cannot be run for her. C and D are real jobs through the front door, run by the real queue up to the
first act, which waits for the person's go-ahead (core/capabilities.py: supervised until unlocked for them); the run
then stops them. Whether the act runs once they say yes is the constitution's, not this check's.

Run: ./venv_lyric/bin/python3 experiments/FIFTY-01/experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)

from experiments import _separation as sep  # noqa: E402
from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

N = sep.nonce()
ANA, BEN = (f"fifty01-{name}-{N}" for name in ("ana", "ben"))
WORKED = {"success": True, "outcome_class": "success", "read_from": "FIFTY-01"}
FIX = [{"tool": "write_file", "arg": "create_dirs", "value": True}]

EV = RunRecord(
    "FIFTY-01",
    claim=("What Lyric overcomes for one person it does again at once, for them and for anyone: the first task of a "
           "shape that worked is the world's method, with nothing of its person in it, and the fix that overcame a "
           "failure is given to the next task before it acts."),
    hypothesis=("A method that waits for a second task, a method holding the person's particulars, a fix kept but "
                "not used, a later task (hers or another person's) that starts without the fix, another person's "
                "task recalling her experience, or a fix given to a plan it does not fit would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def note_plan(folder: Path, text: str, create_dirs: bool):
    return [{"tool": "write_file", "args": {"file_path": str(folder / "note.txt"), "content": text,
                                            "create_dirs": create_dirs}}]


async def main() -> int:
    from core.agents.autonomous.shared_types import Priority, Task, TaskSource, TaskType
    from core.agents.memory_agent import memory_agent
    from core.learning.unified_learning_system import get_learning_authority
    from core.memory.lift import constants, from_formulas, shape_of

    work = Path(tempfile.mkdtemp(prefix=f"fifty01_{N}_"))
    system, coord = await boot()
    d = db()
    memory = memory_agent()
    heard = {ANA: [], BEN: []}
    stops = [coord.on_message(who, lambda m, k=who: heard[k].append(m)) for who in heard]
    made, jobs = [], []
    shape = shape_of(note_plan(work, "x", True))

    async def recorded(who, folder, text, *, failed_first):
        """One of her tasks as its conclusion records it, through the coordinator's own recorder."""
        plan = note_plan(folder, text, True)
        meta = {"parameters": {"tool_plan": plan}, "operating_verdict": WORKED}
        if failed_first:
            meta["failure_history"] = [{
                "attempt": 1, "issues": ["the write did not happen"],
                "failed_tools": [{"tool": "write_file", "error": "Parent directory does not exist"}],
                "error": "Parent directory does not exist"}]
            meta["retry_method_changed"] = "[recalled-success] write_file.create_dirs=True"
            meta["retry_method_structured"] = FIX
        task = Task(id=f"fifty01_{uuid.uuid4().hex[:8]}", type=TaskType.EXECUTION, description="Help me.",
                    priority=Priority.MEDIUM, source=TaskSource.API, actor=who, metadata=meta,
                    retry_count=1 if failed_first else 0)
        memory_id = await coord._store_task_outcome_meta_memory(
            task, "success", 0.97, result_summary=f"wrote {folder / 'note.txt'}",
            result={"success": True, "verification_state": "verified",
                    "tools_run": [{"tool": "write_file", "success": True,
                                   "output": {"file_path": str(folder / "note.txt")}}]})
        made.append(memory_id)
        return task, memory_id

    async def decided(memory_id, wait_s=120):
        deadline = time.time() + wait_s
        while time.time() < deadline:
            await memory._decide_waiting()
            row = await d.execute_query(
                "SELECT decision FROM unified.experience_pool WHERE memory_id = $1 AND status = 'decided'",
                (memory_id,), fetch_one=True)
            if row:
                return row["decision"] if isinstance(row["decision"], dict) else json.loads(row["decision"])
            await asyncio.sleep(0.5)
        return None

    async def method():
        held = await memory._method_memory(shape, None)
        if held is not None and held[0] not in made:
            made.append(held[0])
        return held

    def nothing_of(record, *particulars):
        kept = constants(from_formulas((record.get("method") or {}).get("steps") or []))
        return not any(p in kept for p in particulars), sorted(kept)

    def queued(job):
        return coord.task_queue.tasks_by_id.get(job)

    async def asked_for(who, folder, text):
        """Her (or his) job through the front door, up to the first act's question."""
        reply = await coord.handle_user_request(
            "Help me.", source="api",
            metadata={"actor_identity": who, "session_id": f"session_{who}",
                      "parameters": {"tool_plan": note_plan(folder, text, False)}})
        job = reply.get("task_id")
        jobs.append((who, job))
        if reply.get("pursuit_memory_id"):
            made.append(reply["pursuit_memory_id"])
        deadline = time.time() + 240
        while time.time() < deadline:
            asked = [m for m in heard[who] if m.get("about") == job and m.get("why") == "confirm"]
            q = queued(job)
            if asked and q is not None and q.status.value == "blocked":
                break
            await asyncio.sleep(0.25)
        q = queued(job)
        meta = dict((q.task.metadata or {}) if q else {})
        return {"job": job, "reply": reply, "status": q.status.value if q else None, "meta": meta,
                "asked": [m.get("text") for m in heard[who] if m.get("about") == job and m.get("why") == "confirm"],
                "recalled": [r.get("task_id") for r in (meta.get("recalled_experience") or {}).get("recalled") or []]}

    try:
        where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        check("the run is in the sandbox", where["d"] == "lyric_dev", where["d"])
        check("no method of this shape is held before the run", await memory._method_memory(shape, None) is None,
              shape)

        print("\n== A. The first task that worked ==", flush=True)
        a1_folder, a1_text = work / f"ana_one_{N}", f"Ana's first note {N}"
        a1, a1_memory = await recorded(ANA, a1_folder, a1_text, failed_first=False)
        lift = ((await decided(a1_memory)) or {}).get("lift") or {}
        held = await method()
        check("the first task of its shape that worked is lifted at once, into a world method",
              len(lift.get("lifted") or []) == 1 and lift["lifted"][0]["whose"] == "world" and held is not None
              and held[0] == lift["lifted"][0]["method"], f"{lift}")
        owner = await d.execute_query("SELECT user_id FROM memory_hot.memory_hot WHERE memory_id = $1",
                                      (held[0] if held else "",), fetch_one=True)
        check("it is the world's: held by no person", owner is not None and not owner["user_id"],
              f"{owner}")
        clean, kept = nothing_of(held[1] if held else {}, str(a1_folder / "note.txt"), a1_text)
        check("nothing of hers is in it: her file and her text are variables", held is not None and clean,
              f"{held and held[1]['method']['steps']}; kept {kept}")

        print("\n== B. Overcome ==", flush=True)
        a2_folder, a2_text = work / f"ana_two_{N}", f"Ana's second note {N}"
        a2, a2_memory = await recorded(ANA, a2_folder, a2_text, failed_first=True)
        lift = ((await decided(a2_memory)) or {}).get("lift") or {}
        held = await method()
        fixes = (held[1] if held else {}).get("fixes")
        check("what overcame it is an instance of the method, and the method keeps the fix",
              any(i.get("method") == (held and held[0]) for i in lift.get("instances") or [])
              and fixes == [{"failed_tools": ["write_file"], "use": FIX}],
              f"{lift.get('instances')}; fixes {fixes}")
        clean, kept = nothing_of(held[1] if held else {}, str(a1_folder / "note.txt"), a1_text,
                                 str(a2_folder / "note.txt"), a2_text)
        check("still nothing of hers in it", clean, f"kept {kept}")
        counted = [(i.get("counted"), i.get("worked")) for i in ((held[1] if held else {}).get("instances")
                                                                or {}).values()]
        check("both of hers are counted outcomes of it", counted == [(True, True), (True, True)], f"{counted}")

        print("\n== C. Again, for her ==", flush=True)
        a3_folder, a3_text = work / f"ana_three_{N}", f"Ana's third note {N}"
        a3 = await asked_for(ANA, a3_folder, a3_text)
        print(f"    her job {a3['job']}: {a3['status']}; asked {a3['asked']}", flush=True)
        plan = ((a3["meta"].get("parameters") or {}).get("tool_plan") or [{}])[0].get("args") or {}
        check("before any act, her plan is given the fix",
              (a3["meta"].get("known_fix") or {}).get("method") == (held and held[0])
              and a3["meta"]["known_fix"].get("changes") == FIX and plan.get("create_dirs") is True,
              f"{a3['meta'].get('known_fix')}; {plan}")
        check("it is recognised as the world's method, and its act waits for her go-ahead",
              (a3["meta"].get("capability_run") or {}).get("method") == (held and held[0])
              and a3["status"] == "blocked" and len(a3["asked"]) == 1 and not a3["meta"].get("failure_history")
              and not a3_folder.exists(),
              f"{a3['meta'].get('capability_run')}; {a3['status']}; {a3['asked']}")
        check("her own earlier work is recalled for her", {a1.id, a2.id} & set(a3["recalled"]),
              f"recalled {a3['recalled']}")

        print("\n== D. Anyone ==", flush=True)
        b_folder, b_text = work / f"ben_one_{N}", f"Ben's note {N}"
        b = await asked_for(BEN, b_folder, b_text)
        print(f"    his job {b['job']}: {b['status']}; asked {b['asked']}", flush=True)
        plan = ((b["meta"].get("parameters") or {}).get("tool_plan") or [{}])[0].get("args") or {}
        check("before any act, his plan is given the fix, from the world's method",
              (b["meta"].get("known_fix") or {}).get("method") == (held and held[0])
              and b["meta"]["known_fix"].get("whose") == "world" and plan.get("create_dirs") is True,
              f"{b['meta'].get('known_fix')}; {plan}")
        check("it is recognised as the world's method, and its act waits for his go-ahead: he never met the failure",
              (b["meta"].get("capability_run") or {}).get("method") == (held and held[0])
              and b["status"] == "blocked" and len(b["asked"]) == 1 and not b["meta"].get("failure_history")
              and not b_folder.exists(),
              f"{b['meta'].get('capability_run')}; {b['status']}; {b['asked']}")
        check("nothing of hers is recalled for him", not {a1.id, a2.id, a3["job"]} & set(b["recalled"]),
              f"recalled {b['recalled']}")

        print("\n== E. Controls ==", flush=True)
        other = [{"tool": "read_file", "args": {"file_path": str(work / "x.txt")}}]
        check("a plan of another shape is given nothing", await coord.capabilities.known_fix(other, BEN) is None)
        check("a plan that already has the fix is given nothing",
              await coord.capabilities.known_fix(note_plan(work / "y", "z", True), BEN) is None)
    finally:
        for who, job in jobs:
            q = queued(job)
            if q is not None and q.status.value not in ("completed", "failed", "cancelled"):
                await coord.stop_work(job, actor=who)
        for stop in stops:
            stop()
        owners = [ANA, BEN]
        held = await memory._method_memory(shape, None)
        if held is not None and held[0] not in made:
            made.append(held[0])
        made_ids = [m for m in made if m]
        claims = [get_learning_authority().method_claim(m) for m in made_ids]
        removed = await sep.clean(d, N, owners, "fifty01")
        await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE user_id = ANY($1::text[])"
                              " OR memory_id = ANY($2::text[])", (owners, made_ids))
        await d.execute_query("DELETE FROM unified.experience_pool WHERE owner = ANY($1::text[])"
                              " OR memory_id = ANY($2::text[])", (owners, made_ids))
        await d.execute_query("DELETE FROM unified.beliefs WHERE claim = ANY($1::text[])", (claims,))
        await d.execute_query("DELETE FROM unified.outbox WHERE actor = ANY($1::text[])", (owners,))
        await d.execute_query("DELETE FROM unified.task_queue WHERE payload::text LIKE $1", (f"%fifty01-%-{N}%",))
        EV.metric("rows_removed", sum(removed.values()), "count", f"{removed}")
        EV.note(f"nonce {N}; jobs {jobs}")
        shutil.rmtree(work, ignore_errors=True)
        await shutdown(system)

    passed = sum(results)
    print(f"\n==== FIFTY-01: {passed}/{len(results)} checks passed ====", flush=True)
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
