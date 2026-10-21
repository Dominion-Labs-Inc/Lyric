#!/usr/bin/env python3
"""Completion is whether the work leaves true what it was expected to.

Each expected outcome (the person's, the plan's, and what each act was meant to
leave true) is a belief of its own, moved only by evidence about it, and the
task's belief is the least of them. One belief over all the evidence let
confirmations of one outcome outvote the failure of another: a check the end
state fails, beside a landed edit and the check's own logged pass, stood at 0.978
and was done; so was a run whose third write failed after two landed (0.981).

The acts are the real tools; each run record is built by the coordinator's own
`_run_record`, and the decision is the coordinator's own.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator, _removed_by, _run_record
from core.tools.execution_tools import RunShellCommandTool
from core.tools.filesystem_tools import ReadFileTool, WriteFileTool

TOOLS = {"write_file": WriteFileTool, "read_file": ReadFileTool,
         "run_shell_command": RunShellCommandTool}
on_macos = pytest.mark.skipif(sys.platform != "darwin", reason="the re-run's confinement is macOS's sandbox")


def _act(tool, **args):
    ran = asyncio.run(TOOLS[tool]().execute(**args))
    return _run_record(tool, args, {"success": ran.success, "output": ran.output, "error": ran.error})


def _decide(*records, expected=()):
    coordinator = object.__new__(AutonomousCoordinator)
    task = SimpleNamespace(id="t", metadata={}, description="fix the bug", expected_outcomes=list(expected))
    coordinator._open_completion(task, "the goal of the task is achieved: fix the bug")
    result = {"tools_run": list(records),
              "verification_state": "verified" if all(r["success"] for r in records) else "failed"}
    asyncio.run(coordinator._observe_completion_evidence(task, result))
    done, posterior, issues = coordinator._decide_completion(task, result, 0.0)
    return done, posterior, issues, task.metadata["completion_outcomes"]


def _write(path, text):
    return _act("write_file", file_path=str(path), content=text)


def test_writes_that_all_landed_are_done(tmp_path):
    done, _, issues, outcomes = _decide(_write(tmp_path / "a.txt", "a\n"), _write(tmp_path / "b.txt", "b\n"))
    assert done and issues == []
    assert [o["source"] for o in outcomes] == ["work", "work"]
    assert all(o["posterior"] >= 0.95 for o in outcomes)


def test_one_failed_write_among_landed_ones_is_not_met(tmp_path):
    blocked = tmp_path / "c.txt"
    blocked.write_text("before\n", encoding="utf-8")
    os.chmod(blocked, 0o444)
    try:
        records = [_write(tmp_path / "a.txt", "a\n"), _write(tmp_path / "b.txt", "b\n"),
                   _write(blocked, "c\n")]
    finally:
        os.chmod(blocked, 0o644)
    done, _, issues, _ = _decide(*records)
    assert not done
    assert any(i.startswith(f"not met: {blocked} holds what was written") for i in issues)


@on_macos
def test_a_check_the_end_state_fails_is_not_met_beside_a_landed_edit(tmp_path):
    (tmp_path / "n.py").write_text("ready = True\n", encoding="utf-8")
    (tmp_path / "check.py").write_text("import m, n\nassert m.value == 2 and n.ready\n", encoding="utf-8")
    edit = _write(tmp_path / "m.py", "value = 2\n")
    check = _act("run_shell_command", command=f"'{sys.executable}' check.py", working_directory=str(tmp_path))
    assert edit["success"] and check["success"]
    (tmp_path / "n.py").write_text("ready = False\n", encoding="utf-8")  # changed after the check ran
    done, posterior, issues, _ = _decide(edit, check)
    assert not done and posterior < 0.5
    assert any(i.startswith("not met: the check") for i in issues)


@on_macos
def test_shell_edits_are_confirmed_by_the_check_that_passes_where_they_ran(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "check.py").write_text("import m\nassert m.value == 20\n", encoding="utf-8")
    ws = str(tmp_path)
    edit = _act("run_shell_command", command="sed -i '' 's/value = 1/value = 20/' m.py", working_directory=ws)
    check = _act("run_shell_command", command=f"'{sys.executable}' check.py", working_directory=ws)
    assert edit["outcome"] == f"shell:{ws}" and check["outcome"] == f"check:{ws}"
    done, _, issues, _ = _decide(edit, check)
    assert done and issues == []


def test_shell_edits_with_no_check_are_not_confirmed(tmp_path):
    (tmp_path / "m.py").write_text("value = 1\n", encoding="utf-8")
    edit = _act("run_shell_command", command="sed -i '' 's/1/2/' m.py", working_directory=str(tmp_path))
    done, _, issues, _ = _decide(edit)
    assert not done
    assert any(i.startswith(f"not confirmed: the commands run in {tmp_path} did what they were for")
               for i in issues)


def test_a_look_that_failed_is_no_evidence(tmp_path):
    missing = _act("read_file", file_path=str(tmp_path / "missing.txt"))
    assert not missing["success"] and missing["observes"]
    done, _, issues, outcomes = _decide(missing, _write(tmp_path / "a.txt", "a\n"),
                                        _write(tmp_path / "b.txt", "b\n"))
    assert done and issues == []
    assert all(not o["outcome"].startswith("read:") for o in outcomes)


def test_an_outcome_the_person_expects_that_nothing_observes_is_not_confirmed(tmp_path):
    expected = ["every dormant account that signed in is disabled"]
    done, _, issues, outcomes = _decide(_write(tmp_path / "a.txt", "a\n"), expected=expected)
    assert not done
    assert outcomes[0]["source"] == "person"
    assert any(i.startswith(f"not confirmed: {expected[0]}") for i in issues)


@on_macos
def test_operating_credit_follows_the_weakest_outcome(tmp_path):
    from core.learning.meta_learning import OutcomeClass
    (tmp_path / "check.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    edit = _write(tmp_path / "m.py", "value = 2\n")
    check = _act("run_shell_command", command=f"'{sys.executable}' check.py", working_directory=str(tmp_path))
    done, posterior, _, _ = _decide(edit, check)
    verdict = object.__new__(AutonomousCoordinator)._operating_verdict({"tools_run": [edit, check]}, posterior, done)
    assert not done and verdict["success"] is False
    assert verdict["outcome_class"] is not OutcomeClass.SUCCESS


def test_work_that_only_reads_is_done_when_reading_again_agrees(tmp_path):
    note = tmp_path / "note.txt"
    note.write_text("the meeting moved to Thursday\n", encoding="utf-8")
    done, _, issues, outcomes = _decide(_act("read_file", file_path=str(note)))
    assert done and issues == []
    assert [o["outcome"] for o in outcomes] == [f"read:{note}"]


def test_a_shell_removal_names_the_files_it_removes():
    def removed(command, where="/w"):
        return _removed_by("run_shell_command", {"command": command, "working_directory": where})
    assert removed("rm reproduce.py") == ["/w/reproduce.py"]
    assert removed("cd /testbed && rm -f a.py b.py && ls", None) == ["/testbed/a.py", "/testbed/b.py"]
    assert removed("cd sub; unlink x.txt") == ["/w/sub/x.txt"]
    assert removed("rm -rf build/") == ["/w/build"]
    assert removed("rm *.pyc") == [] and removed("rm $TMP/y") == [] and removed("echo rm z") == []


def test_a_scratch_file_written_then_removed_in_the_shell_is_gone(tmp_path):
    ws = str(tmp_path)
    edit = _write(tmp_path / "m.py", "value = 2\n")
    scratch = _write(tmp_path / "reproduce.py", "print(1)\n")
    cleanup = _act("run_shell_command", command="rm reproduce.py", working_directory=ws)
    assert cleanup["removes"] == [f"{ws}/reproduce.py"] and not (tmp_path / "reproduce.py").exists()
    done, _, issues, outcomes = _decide(edit, scratch, cleanup)
    gone = [o for o in outcomes if o["outcome"] == f"effect:{ws}/reproduce.py"]
    assert gone and gone[0]["states"] == f"{ws}/reproduce.py is gone" and gone[0]["posterior"] >= 0.95
    assert done and issues == []  # the removal needs no check: what it was for is observed


def test_a_removal_that_failed_leaves_the_file_not_met(tmp_path):
    ws = tmp_path / "locked"
    ws.mkdir()
    scratch = _write(ws / "reproduce.py", "print(1)\n")
    os.chmod(ws, 0o555)
    try:
        cleanup = _act("run_shell_command", command="rm reproduce.py", working_directory=str(ws))
    finally:
        os.chmod(ws, 0o755)
    assert not cleanup["success"] and (ws / "reproduce.py").exists()
    done, _, issues, _ = _decide(scratch, cleanup)
    assert not done and any(i.startswith(f"not met: {ws}/reproduce.py is gone") for i in issues)
