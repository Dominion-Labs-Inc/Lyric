#!/usr/bin/env python3
"""SAW confirms a check by running it again in a disposable copy of the end state.

A check's success is a fact about the code it ran against, and later acts may
have changed that code. SAW runs the latest check again against a confined clone
of the directory it ran in: it writes only inside the clone, reaches no network,
and the clone is deleted. What the check does there is the observation.

The acts are the real tools; each run record is built the way the coordinator's
declared-tools path builds it. Confinement here is macOS's sandbox.
"""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from core.agents.autonomous.autonomous_coordinator import (
    AutonomousCoordinator, _INTERVENTION_TARGET_ARG, _check_of, _tool_resource)
from core.tools.execution_tools import RunShellCommandTool, run_in_disposable_copy

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="confinement is macOS's sandbox")

PYTHON = sys.executable


def _shell(command, ws, **extra):
    args = {"command": command, "working_directory": str(ws), **extra}
    outcome = asyncio.run(RunShellCommandTool().execute(**args))
    return {"tool": "run_shell_command", "success": outcome.success,
            "output": outcome.output if outcome.success else None,
            "error": None if outcome.success else outcome.error,
            "resource": _tool_resource("run_shell_command", args),
            "intervention_target": args.get(_INTERVENTION_TARGET_ARG.get("run_shell_command")),
            "check": _check_of("run_shell_command", args)}


def _coordinator_and_task():
    coordinator = object.__new__(AutonomousCoordinator)
    task = SimpleNamespace(id="t", metadata={}, description="fix the bug")
    coordinator._open_completion(task, "the goal of the task is achieved: fix the bug")
    return coordinator, task


def _saw(*records):
    coordinator, task = _coordinator_and_task()
    return asyncio.run(coordinator._saw_reobserve(task, {"tools_run": list(records)}))


def _done(*records):
    coordinator, task = _coordinator_and_task()
    result = {"tools_run": list(records),
              "verification_state": "verified" if all(r["success"] for r in records) else "failed"}
    asyncio.run(coordinator._observe_completion_evidence(task, result))
    return coordinator._decide_completion(task, result, 0.0)[0]


def _project(tmp_path, value):
    # Each rewrite changes the file's length: Python reuses compiled bytecode for a
    # source whose size and modification second are unchanged.
    (tmp_path / "m.py").write_text(f"value = {value}\n", encoding="utf-8")
    (tmp_path / "check.py").write_text("import m\nassert m.value == 2\n", encoding="utf-8")
    return tmp_path


def test_what_reads_as_a_check():
    checks = ["pytest tests/test_x.py", "python tests/runtests.py validators",
              "cd /testbed && python reproduce.py 2>&1 | head -20", "python3 -m pytest -x"]
    others = ["cat m.py", "sed -i 's/1/2/' m.py", "pip install -e .", "python -m pip install x",
              "python setup.py develop", "pytest && rm out.txt", "python reproduce.py > out.txt"]
    assert all(_check_of("run_shell_command", {"command": c}) for c in checks)
    assert not any(_check_of("run_shell_command", {"command": c}) for c in others)
    assert _check_of("run_python", {"code": "print(1)"}) is None


def test_a_check_that_still_passes_is_confirmed(tmp_path):
    ws = _project(tmp_path, 2)
    [seen] = _saw(_shell(f"'{PYTHON}' check.py", ws))
    assert seen.polarity is True and seen.observation_channel == "check_rerun"


def test_a_check_the_end_state_no_longer_passes_is_contradicted(tmp_path):
    ws = _project(tmp_path, 2)
    record = _shell(f"'{PYTHON}' check.py", ws)
    assert record["success"]
    (ws / "m.py").write_text("value = 30\n", encoding="utf-8")  # changed after the check ran
    [seen] = _saw(record)
    assert seen.polarity is False
    assert not _done(record)


def test_the_latest_check_is_the_one_run_again(tmp_path):
    ws = _project(tmp_path, 30)
    failed = _shell(f"'{PYTHON}' check.py", ws)
    (ws / "m.py").write_text("value = 2\n", encoding="utf-8")
    passed = _shell(f"'{PYTHON}' check.py", ws)
    assert not failed["success"] and passed["success"]
    [seen] = _saw(failed, passed)
    assert seen.polarity is True


def test_an_act_that_is_not_a_check_is_not_run_again(tmp_path):
    ws = _project(tmp_path, 1)
    assert _saw(_shell("sed -i '' 's/1/2/' m.py", ws)) == []


def test_the_rerun_changes_nothing_and_reaches_no_network(tmp_path):
    ws = _project(tmp_path, 2)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    writes = asyncio.run(run_in_disposable_copy(f"echo x > inside.txt; echo y > '{outside}'", str(ws), 10))
    assert writes is not None
    assert not (ws / "inside.txt").exists() and not outside.exists()
    network = asyncio.run(run_in_disposable_copy(
        f"'{PYTHON}' -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\"", str(ws), 10))
    assert network["exit_code"] != 0


def test_a_rerun_that_does_not_finish_is_against(tmp_path):
    ws = _project(tmp_path, 2)
    record = _shell(f"'{PYTHON}' -c 'import time; time.sleep(3)'", ws, timeout=5)
    record["check"]["timeout"] = 1
    [seen] = _saw(record)
    assert seen.polarity is False


def test_nothing_runs_without_a_workspace_to_copy():
    from pathlib import Path
    import core
    lyric_root = Path(core.__file__).resolve().parent.parent
    assert asyncio.run(run_in_disposable_copy("true", None, 5)) is None
    assert asyncio.run(run_in_disposable_copy("true", str(lyric_root), 5)) is None
    assert asyncio.run(run_in_disposable_copy("true", str(lyric_root.parent), 5)) is None
