#!/usr/bin/env python3
"""The latest act on a resource decides what the completion belief takes from it.

Acts on one resource share a causal lineage and collapse to one grounding. The
collapse kept the STRONGEST member, and a success (0.9) outweighs a failure
(0.85), so a failure that came after a success on the same resource was hidden:
a run whose final check failed, or whose second write to a file failed, reached
done. The collapse now keeps the latest member, as SAW keeps the last act on a
target.

The acts are the real tools; each run record is built by the coordinator's own
`_run_record`, and the decision is the coordinator's own.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator, _run_record
from core.tools.execution_tools import RunShellCommandTool
from core.tools.filesystem_tools import PatchFileTool, WriteFileTool

TOOLS = {"write_file": WriteFileTool, "patch_file": PatchFileTool,
         "run_shell_command": RunShellCommandTool}


def _act(tool, **args):
    ran = asyncio.run(TOOLS[tool]().execute(**args))
    return _run_record(tool, args, {"success": ran.success, "output": ran.output, "error": ran.error})


def _done(*records):
    coordinator = object.__new__(AutonomousCoordinator)
    task = SimpleNamespace(id="t", metadata={}, description="fix the bug")
    coordinator._open_completion(task, "the goal of the task is achieved: fix the bug")
    result = {"tools_run": list(records),
              "verification_state": "verified" if all(r["success"] for r in records) else "failed"}
    asyncio.run(coordinator._observe_completion_evidence(task, result))
    done, _, _ = coordinator._decide_completion(task, result, 0.0)
    return done


def _fixed_file(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    return _act("patch_file", file_path=str(path), old_string="value = 1", new_string="value = 2")


def test_a_final_command_that_fails_holds_the_run_short_of_done(tmp_path):
    ws = str(tmp_path)
    assert not _done(_act("run_shell_command", command="true", working_directory=ws),
                     _fixed_file(tmp_path),
                     _act("run_shell_command", command="false", working_directory=ws))


@pytest.mark.skipif(sys.platform != "darwin", reason="the re-run's confinement is macOS's sandbox")
def test_a_check_that_failed_and_then_passed_does_not_hold_it(tmp_path):
    ws = str(tmp_path)
    (tmp_path / "check.py").write_text("import module\nassert module.value == 2\n", encoding="utf-8")
    check = f"'{sys.executable}' check.py"
    failed = _act("run_shell_command", command=check, working_directory=ws)
    fixed = _fixed_file(tmp_path)
    passed = _act("run_shell_command", command=check, working_directory=ws)
    assert not failed["success"] and passed["success"]
    assert _done(failed, fixed, passed)


def test_a_second_write_that_failed_holds_the_run_short_of_done(tmp_path):
    path = tmp_path / "note.txt"
    first = _act("write_file", file_path=str(path), content="first\n")
    os.chmod(path, 0o444)
    try:
        second = _act("write_file", file_path=str(path), content="second\n")
    finally:
        os.chmod(path, 0o644)
    assert first["success"] and not second["success"]
    assert not _done(first, second)
