#!/usr/bin/env python3
"""SAW observes what a written file holds, not only that it is there.

The completion belief's SAW evidence used to check a written file by existence
alone. A write whose bytes never landed on a file that was already there passed
that check, and a `patch_file` was not observed at all. Each act now reports a
fingerprint of what the file should hold, and SAW compares it with a fresh
reading of the file. The last act on a target decides what should be true of it.

The acts here are the real filesystem tools; each run record is built by the
coordinator's own `_run_record`.
"""

import asyncio
from types import SimpleNamespace

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator, _run_record
from core.tools.filesystem_tools import DeleteFileTool, PatchFileTool, WriteFileTool

TOOLS = {"write_file": WriteFileTool, "patch_file": PatchFileTool, "delete_file": DeleteFileTool}


def _act(tool, **args):
    ran = asyncio.run(TOOLS[tool]().execute(**args))
    return _run_record(tool, args, {"success": ran.success, "output": ran.output, "error": ran.error})


def _saw(*records):
    coordinator = object.__new__(AutonomousCoordinator)
    task = SimpleNamespace(metadata={"completion_anchor": "goal"}, id="t")
    return asyncio.run(coordinator._saw_reobserve(task, {"tools_run": list(records)}))


def test_write_that_landed_is_confirmed_by_its_content(tmp_path):
    target = str(tmp_path / "note.txt")
    [seen] = _saw(_act("write_file", file_path=target, content="the new text\n"))
    assert seen.polarity is True
    assert seen.observation_channel == "filesystem_content"


def test_write_that_never_landed_on_an_existing_file_is_contradicted(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("what was there before\n", encoding="utf-8")
    record = _act("write_file", file_path=str(path), content="the new text\n")
    path.write_text("what was there before\n", encoding="utf-8")  # the bytes did not stay
    [seen] = _saw(record)
    assert path.exists()  # existence alone would have confirmed this write
    assert seen.polarity is False


def test_append_is_checked_against_the_whole_file_it_should_make(tmp_path):
    target = str(tmp_path / "log.txt")
    _act("write_file", file_path=target, content="first\n")
    [seen] = _saw(_act("write_file", file_path=target, content="second\n", mode="append"))
    assert seen.polarity is True


def test_patch_is_observed(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    record = _act("patch_file", file_path=str(path), old_string="value = 1", new_string="value = 2")
    [seen] = _saw(record)
    assert seen.polarity is True
    path.write_text("value = 1\n", encoding="utf-8")
    [seen] = _saw(record)
    assert seen.polarity is False


def test_last_act_on_a_target_decides(tmp_path):
    target = str(tmp_path / "scratch.txt")
    wrote = _act("write_file", file_path=target, content="temporary\n")
    removed = _act("delete_file", path=target, confirm=True)
    [seen] = _saw(wrote, removed)
    assert seen.polarity is True
    assert seen.observation_channel == "filesystem_scan"


def test_removal_is_observed_as_absence(tmp_path):
    path = tmp_path / "old.txt"
    path.write_text("x\n", encoding="utf-8")
    [seen] = _saw(_act("delete_file", path=str(path), confirm=True))
    assert seen.polarity is True
