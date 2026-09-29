#!/usr/bin/env python3
"""Pytest smoke tests for the code generation tools:
- lint fixer dry-run + patch output
- unified diff patch application tool
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.asyncio
async def test_lint_fixer_dry_run_returns_patch(tmp_path):
    from core.tools.code_generation_tools import FixLintingErrorsTool

    file_path = tmp_path / "lint_me.py"
    original = "import os\nimport sys\n\n\ndef foo():\n    x=1\n    return x\n"
    file_path.write_text(original)

    tool = FixLintingErrorsTool()
    result = await tool.execute(str(file_path), dry_run=True, return_patch=True)

    assert result.success is True
    assert isinstance(result.output, dict)
    assert result.output["dry_run"] is True
    assert result.output["file"].endswith("lint_me.py")

    # File should not be modified in dry-run
    assert file_path.read_text() == original

    # If dependencies are present, we should see a change + patch.
    # If not, tool still succeeds and reports missing deps.
    deps = result.output.get("dependencies", {})
    assert isinstance(deps, dict)

    if result.output.get("changed"):
        assert isinstance(result.output.get("patch"), str)
        assert "@@" in result.output.get("patch")


@pytest.mark.asyncio
async def test_apply_patch_tool_simple_hunk():
    from core.tools.code_generation_tools import ApplyPatchTool

    tool = ApplyPatchTool()
    result = await tool.execute(
        code="old\n",
        patch="""--- a/test.txt\n+++ b/test.txt\n@@ -1 +1 @@\n-old\n+new\n""",
    )

    assert result.success is True
    assert result.output["patch_applied"] is True
    assert result.output["code"].strip() == "new"
