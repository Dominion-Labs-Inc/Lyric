#!/usr/bin/env python3
"""AGENTS-01 — the substrate deploys agents of itself, and they are sound.

An agent of self is a copy of the substrate scoped to one task and a granted set of tools, run through the
coordinator's own execution and every authority beneath it (`AutonomousCoordinator.deploy_agent` over the agent
factory, `core/agents/agents.py`). On the running substrate, in the SANDBOX:

  A  wired: the coordinator holds the agent factory, and the factory is bound back to the coordinator;
  B  deployed and awaited: an agent returns its findings (a note it read through its granted tool);
  C  scoped: an agent never uses a tool it was not granted;
  D  bounded: past the allowance for a kind of reasoning, deployment is refused, honestly, while the others run;
  E  reconciled without waiting: findings are collected when they are back, and nothing is left pending;
  F  honest: an agent whose work fails reports the failure, never findings;
  H  never waited for: an agent's findings reach the substrate on their own, as a JOB_COMPLETED self-event the
     moment it lands, with nothing awaited or collected; and a failed job's event is received without fault;
  G  the main model's store is untouched.

Runs in the SANDBOX (`lyric_dev`) and does not empty it. Left, named by this run's nonce: the agents' pursuit
memories and task records.

    ./venv_lyric/bin/python3 experiments/AGENTS-01/experiment.py
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
PERSON = f"agents01_{NONCE}"

EV = RunRecord(
    "AGENTS-01",
    claim=("The substrate deploys agents of itself through its own coordinator: their findings are handed to it the "
           "moment they land, never waited for; they use only the tools granted, are refused past the allowance, "
           "and report failure honestly."),
    hypothesis=("An unwired factory, an agent using an ungranted tool, deployment past the allowance, findings "
                "lost or left pending, a failure reported as findings, or a write to the main store would each "
                "show here."))


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


def said(finding) -> str:
    return str((finding or {}).get("findings")) + str((finding or {}).get("error"))


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
    from core.reasoning.reasoning_interfaces import ReasoningType
    work = Path(tempfile.mkdtemp(prefix="agents01_"))
    note = work / "note.txt"
    note.write_text(f"The pump code is {NONCE}.\n")
    read_plan = {"tool_plan": [{"tool": "read_file", "args": {"file_path": str(note)}}]}
    try:
        say_line("== A. Wired ==")
        factory = coord.agent_coordinator
        check("the coordinator holds the agent factory, and the factory is bound back to it",
              factory is not None and factory._coordinator is coord)

        say_line("\n== B. Deployed and awaited ==")
        name = coord.deploy_agent(f"Read the note {NONCE}.", allowed_tools=["read_file"], actor=PERSON,
                                  parameters=read_plan)
        check("deploying returns the agent's name", isinstance(name, str) and name, f"{name}")
        got = await asyncio.wait_for(coord.await_agent(name), 240)
        check("awaited, it returns its findings: what the note says", NONCE in said(got) and not got.get("error"),
              said(got)[:200])

        say_line("\n== C. Scoped ==")
        name = coord.deploy_agent(f"Read the note {NONCE} without leave.", allowed_tools=["list_directory"],
                                  actor=PERSON, parameters=read_plan)
        got = await asyncio.wait_for(coord.await_agent(name), 240)
        findings = got.get("findings") or {}
        check("an agent never uses a tool it was not granted",
              NONCE not in str(findings) and not (isinstance(findings, dict) and findings.get("success") is True),
              said(got)[:200])

        say_line("\n== D. Bounded ==")
        allowance = coord.agent_allowance(ReasoningType.DEDUCTIVE)
        names = [coord.deploy_agent(f"Read the note {NONCE}, copy {i}.", allowed_tools=["read_file"],
                                    actor=PERSON, parameters=read_plan) for i in range(allowance + 1)]
        check("past the allowance, deployment is refused while the others run",
              all(names[:allowance]) and names[allowance] is None,
              f"allowance {allowance}: {['refused' if n is None else 'deployed' for n in names]}")

        say_line("\n== E. Reconciled without waiting ==")
        running = [n for n in names if n]
        back, deadline = [], time.time() + 240
        while time.time() < deadline and len(back) < len(running):
            back += coord.collect_agent_findings()
            await asyncio.sleep(0.5)
        check("findings are collected when they are back, without waiting on any one agent",
              sorted(f["deployment_id"] for f in back) == sorted(running)
              and all(NONCE in said(f) for f in back), f"{len(back)}/{len(running)} back")
        check("nothing is left pending", not coord.pending_agents(), f"{coord.pending_agents()}")

        say_line("\n== F. Honest ==")
        missing = {"tool_plan": [{"tool": "read_file", "args": {"file_path": str(work / "absent.txt")}}]}
        name = coord.deploy_agent(f"Read a note that is not there {NONCE}.", allowed_tools=["read_file"],
                                  actor=PERSON, parameters=missing)
        got = await asyncio.wait_for(coord.await_agent(name), 240)
        findings = got.get("findings") or {}
        check("an agent whose work fails reports the failure, never findings",
              got.get("error") or (isinstance(findings, dict) and findings.get("success") is False),
              said(got)[:200])

        say_line("\n== H. Never waited for ==")
        from core.agents.autonomous.autonomous_coordinator import JobCompleted, SelfEvent, SelfEventType
        handed = []
        coord.on(SelfEventType.JOB_COMPLETED, lambda event: handed.append(event.payload),
                 name=f"agents01_{NONCE}", mode="sync")
        name = coord.deploy_agent(f"Read the note {NONCE}, unwatched.", allowed_tools=["read_file"],
                                  actor=PERSON, parameters=read_plan)
        deadline = time.time() + 240
        while time.time() < deadline and not any(p.job_id == name for p in handed):
            await asyncio.sleep(0.2)
        mine = next((p for p in handed if p.job_id == name), None)
        check("an agent's findings reach the substrate on their own, nothing awaited or collected",
              mine is not None and NONCE in str(mine.result) and mine.error is None,
              f"{str(mine.result)[:120] if mine else 'never handed over'}")
        try:
            await coord._react_job_completed(SelfEvent(SelfEventType.JOB_COMPLETED,
                                                       payload=JobCompleted(job_id="failed-job", name="agent:test",
                                                                            error="it broke"),
                                                       origin="agents01"))
            received = True
        except Exception as error:
            received = f"{type(error).__name__}: {error}"
        check("a failed job's event is received without fault", received is True, f"{received}")
        coord.collect_agent_findings()
    finally:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await system.shutdown()
        for f in work.iterdir():
            f.unlink()
        work.rmdir()

    say_line("\n== G. The main model ==")
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_before == main_after,
          f"{main_before} rows before, {main_after} after")
    EV.note(f"nonce {NONCE}: left in the sandbox, the agents' pursuit memories and task records")
    await EV.verify_database()
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
