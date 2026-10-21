#!/usr/bin/env python3
"""Any grounding against the goal holds the task short of done.

A goal holds only if every effect it rests on holds. The completion belief adds
its groundings up, and three confirmations outvoted one contradiction: a run
whose check the end state fails, beside a landed edit and the check's own logged
pass, stood at 0.978 and was done; so was a run whose third write failed after
two landed (0.981). The decision now requires nothing against it, and operating
credit is denied, not granted, when the belief holds while its own evidence
disagrees.

The acts are the real tools; each run record is built the way the coordinator's
declared-tools path builds it.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from core.agents.autonomous.autonomous_coordinator import (
    AutonomousCoordinator, _INTERVENTION_TARGET_ARG, _check_of, _tool_resource)
from core.tools.execution_tools import RunShellCommandTool
from core.tools.filesystem_tools import WriteFileTool

TOOLS = {"write_file": WriteFileTool, "run_shell_command": RunShellCommandTool}


def _act(tool, **args):
    outcome = asyncio.run(TOOLS[tool]().execute(**args))
    return {"tool": tool, "success": outcome.success,
            "output": outcome.output if outcome.success else None,
            "error": None if outcome.success else outcome.error,
            "resource": _tool_resource(tool, args),
            "intervention_target": args.get(_INTERVENTION_TARGET_ARG.get(tool)),
            "check": _check_of(tool, args)}


def _decide(*records):
    coordinator = object.__new__(AutonomousCoordinator)
    task = SimpleNamespace(id="t", metadata={}, description="fix the bug")
    coordinator._open_completion(task, "the goal of the task is achieved: fix the bug")
    result = {"tools_run": list(records),
              "verification_state": "verified" if all(r["success"] for r in records) else "failed"}
    asyncio.run(coordinator._observe_completion_evidence(task, result))
    return coordinator._decide_completion(task, result, 0.0)


def test_writes_that_all_landed_are_done(tmp_path):
    done, _, issues = _decide(_act("write_file", file_path=str(tmp_path / "a.txt"), content="a\n"),
                              _act("write_file", file_path=str(tmp_path / "b.txt"), content="b\n"))
    assert done and issues == []


def test_one_failed_write_among_landed_ones_holds_it(tmp_path):
    blocked = tmp_path / "c.txt"
    blocked.write_text("before\n", encoding="utf-8")
    os.chmod(blocked, 0o444)
    try:
        records = [_act("write_file", file_path=str(tmp_path / "a.txt"), content="a\n"),
                   _act("write_file", file_path=str(tmp_path / "b.txt"), content="b\n"),
                   _act("write_file", file_path=str(blocked), content="c\n")]
    finally:
        os.chmod(blocked, 0o644)
    done, posterior, issues = _decide(*records)
    assert posterior >= 0.95  # the sum alone would have accepted it
    assert not done and any(i.startswith("contradicted: tool_runtime") for i in issues)


@pytest.mark.skipif(sys.platform != "darwin", reason="the re-run's confinement is macOS's sandbox")
def test_a_check_the_end_state_fails_holds_it_beside_a_landed_edit(tmp_path):
    (tmp_path / "n.py").write_text("ready = True\n", encoding="utf-8")
    (tmp_path / "check.py").write_text("import m, n\nassert m.value == 2 and n.ready\n", encoding="utf-8")
    edit = _act("write_file", file_path=str(tmp_path / "m.py"), content="value = 2\n")
    check = _act("run_shell_command", command=f"'{sys.executable}' check.py", working_directory=str(tmp_path))
    assert edit["success"] and check["success"]
    (tmp_path / "n.py").write_text("ready = False\n", encoding="utf-8")  # changed after the check ran
    done, posterior, issues = _decide(edit, check)
    assert posterior >= 0.95
    assert not done and issues == ["contradicted: check_rerun on check:" + check["check"]["command"]]


def test_operating_credit_is_denied_when_the_evidence_disagrees():
    from core.learning.meta_learning import OutcomeClass
    coordinator = object.__new__(AutonomousCoordinator)
    against = [{"channel": "check_rerun", "provenance": "check:pytest", "supports": False}]
    denied = coordinator._operating_verdict({"tools_run": []}, 0.978, False, against)
    assert denied["success"] is False and denied["outcome_class"] is OutcomeClass.INDETERMINATE
    credited = coordinator._operating_verdict({"tools_run": []}, 0.978, True, [])
    assert credited["success"] is True and credited["outcome_class"] is OutcomeClass.SUCCESS
