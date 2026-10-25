#!/usr/bin/env python3
"""
Tool registry: lazy loading, the index of what tools perform, and a real run
============================================================================
1. Lazy loading - a tool is built when it is first asked for, not when registered
2. The index - a registered tool is filed under what it declares it performs
3. A real run through the registry

The capability discovery this file used to test (provider selection, context
scoring, inferring capabilities from task text) was archived on 2026-10-04 with
the rest of the old discovery: archive/superseded_capability_discovery_2026-10-04.

Author: Lyric AI Team
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.tools.tool_registry import ToolRegistry, Primitive
from core.tools.filesystem_tools import ReadFileTool


def test_lazy_loading():
    """Test that tools load on-demand, not at registration"""
    registry = ToolRegistry()
    tool_instantiated = False

    def read_file_factory():
        nonlocal tool_instantiated
        tool_instantiated = True
        return ReadFileTool()

    registry.register_factory(
        "read_file",
        read_file_factory,
        primitives=[Primitive.READ_DATA]
    )
    assert not tool_instantiated, "Tool should NOT be instantiated at registration!"

    tool = registry.get_tool("read_file")
    assert tool_instantiated, "Tool SHOULD be instantiated when accessed!"
    assert tool is not None, "Tool should be loaded!"
    assert tool.name == "read_file"


def test_primitive_index_auto_build():
    """A tool registered eagerly is filed under what it declares it performs."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    assert "read_file" in registry.primitive_index.get(Primitive.READ_DATA, []), \
        "Tool should be in the index under what it declares"


@pytest.mark.asyncio
async def test_actual_tool_execution():
    """A tool runs through the registry and returns what it read."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    test_file = Path("/tmp/lyric_test_file.txt")
    test_content = "Hello from the tool registry!\nThis is line 2.\n"
    test_file.write_text(test_content)
    try:
        result = await registry.execute_tool("read_file", {"file_path": str(test_file)})
        assert result.success, "Tool execution should succeed!"
        # Read the STRUCTURED field. str(dict) escapes newlines to a literal \n,
        # so the raw content was never a substring of the repr -- the assertion
        # could only pass for content with no newlines in it.
        payload = result.output
        file_content = payload["content"] if isinstance(payload, dict) else payload
        assert file_content == test_content, "Should read correct content!"
        # The registry timed the run it made.
        assert result.execution_time is not None and result.execution_time >= 0.0
    finally:
        test_file.unlink()


@pytest.mark.asyncio
async def test_lyric_decides_which_tool_does_what_a_person_asked():
    """What a person asked, as read, decides the tool: a doing asked of Lyric, the tool whose own description says it
    does it, given what was asked where its parameter's name says what that is (a path, a page's address). Reading is
    Lyric's own sense, and a page reaches it through the tool its reading takes pages in with. Where no tool both does
    it and is supplied what it requires, none is chosen. ("Read <a file>." was understood and its job failed with no
    tool run: TEACH-AND-DO-01 2026-09-28; lyric_dev, 2026-10-24.)"""
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator as AC
    from core.semantics.derived_reader import Meaning, MeaningFact as F

    class Parameter:
        def __init__(self, name, required):
            self.name, self.required = name, required

    class Fetcher:
        parameters = [Parameter("url", True), Parameter("extract", False)]

    class Registry:
        def get_tool(self, name):
            return Fetcher() if name == "web_fetch" else None

    class Deciding:
        tool_registry = Registry()
        _DOOR_OF = AC._DOOR_OF
        _tools_for_request = AC._tools_for_request
        _arguments = staticmethod(AC._arguments)
        _doings_meant = staticmethod(AC._doings_meant)

        async def _tools_by_doing(self):
            return {"read_file": ("read", ("file_path",), ("file_path", "start_line")),
                    "web_fetch": ("fetch", ("url",), ("url", "timeout")),
                    "delete_file": ("delete", ("file_path",), ("file_path",))}

    class Asked:
        def __init__(self, *facts):
            self.metadata = {"requested": Meaning("request", facts).to_dict()}

    path = "/notes/story.txt"
    reading = (F("instance_of", "?v0", "read"), F("done_by", "?v0", "?listener"))
    assert await Deciding()._tools_for_request(Asked(*reading, F("done_to", "?v0", path))) == \
        [{"tool": "read_file", "args": {"file_path": path}}]
    assert await Deciding()._tools_for_request(Asked(*reading, F("done_to", "?v0", "https://example.com/a"))) == \
        [{"tool": "web_fetch", "args": {"url": "https://example.com/a"}}], "a page, read by Lyric's own reading"
    deleting = (F("instance_of", "?v0", "delete"), F("done_by", "?v0", "?listener"))
    assert await Deciding()._tools_for_request(Asked(*deleting, F("done_to", "?v0", "https://example.com/a"))) == [], \
        "no tool deletes a page, and deleting is no sense of Lyric's"
    assert await Deciding()._tools_for_request(Asked(*reading, F("done_to", "?v0", "?v1"),
                                                     F("instance_of", "?v1", "book"))) == [], \
        "nothing says which file"
    assert AC._arguments([path, "https://example.com/a"], ("url",), ("url", "timeout")) == \
        {"url": "https://example.com/a"}
