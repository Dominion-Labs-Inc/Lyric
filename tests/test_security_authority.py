#!/usr/bin/env python3
"""Security has one authority, and nothing may fabricate its verdict.

The authority is now `Constitution.judge`, reached through `get_constitution()`
and applied at `tool_registry.execute_tool` — the single point every tool call
passes through. `safety_framework.evaluate_action` was the authority before it;
that module stays on disk as the reference its remaining capabilities are being
taken from, but it no longer governs. Two gates would be two answers to "may this
act happen", which is the duplicate-authority defect on the path where it matters
most.

THE ORIGINAL DEFECT THIS FILE PINS is worth keeping legible, because it is the
failure mode the constitution must never reproduce:
`memory_agent.validate_governance_compliance` called
`governance.check_compliance(action=..., context=...)`, WHICH DOES NOT EXIST on
the trigger system. Every call raised AttributeError, a broad handler swallowed
it, and the function returned `True, "Operation complies with governance"`. Every
memory-agent operation was approved unconditionally while reporting that a
governance check had passed — a fabricated authorization, which is worse than no
check at all: a missing check is visible, an invented one is not.

Both that method and its sibling `get_governance_status` (which returned a
hardcoded `"constitutional_compliance": True`) are now DELETED rather than
re-pointed at the constitution. The constitution judges an act before it happens,
where the act is real; an agent asking "is this compliant?" as it runs is the old
model's shape.
"""

import ast
import inspect
import textwrap

import pytest


def test_the_method_that_was_being_called_still_does_not_exist():
    """Pins the diagnosis. If a `check_compliance` is ever added to the trigger
    engine, this test should be revisited deliberately rather than silently
    making the old call look correct.

    The module this originally imported — `unified_governance_trigger_system` —
    no longer exists; the engine now lives in `governance_triggers`. The test was
    failing on that import before this file was rewritten, which is its own small
    lesson: a test pinned to a module name stops testing the moment the module is
    renamed, and says nothing while it does."""
    from core.governance import get_governance_trigger_engine
    assert not hasattr(get_governance_trigger_engine(), "check_compliance")


def test_the_memory_agent_no_longer_carries_a_governance_oracle_of_its_own():
    """Neither a real one nor an invented one. The laws are not this agent's to
    answer, and a hardcoded `constitutional_compliance: True` is the defect this
    file exists to prevent."""
    from core.agents.memory_agent import MemoryAgent
    assert not hasattr(MemoryAgent, "validate_governance_compliance")
    assert not hasattr(MemoryAgent, "get_governance_status")


def test_the_tool_gate_is_the_constitution_and_nothing_else():
    """The single evaluation point routes to the constitution, and the gate it
    replaced is no longer consulted there.

    PARSED, not string-matched: the code documents what it replaced, so a
    substring check would fail on its own explanation."""
    from core.tools.tool_registry import ToolRegistry

    source = textwrap.dedent(inspect.getsource(ToolRegistry.execute_tool))
    tree = ast.parse(source)
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    called |= {node.func.attr for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "judge_act" in called, "the tool gate does not put the act to the constitution"
    assert "evaluate_action" not in called, "the replaced gate is still being consulted"
    assert "get_safety_framework" not in called


def test_the_gate_fails_closed_when_the_constitution_cannot_be_reached():
    """An act nobody could judge is not an act anyone permitted.

    The gate this replaced set `approved = True` when evaluation raised, so the
    one reliable way past it was to break it."""
    import asyncio

    from core.agents.autonomous import autonomous_coordinator as ac

    original = ac.get_constitution
    ac.get_constitution = lambda: (_ for _ in ()).throw(
        RuntimeError("constitution unavailable"))
    try:
        judgment = asyncio.run(ac.judge_act("tool", "read_file", {"path": "/tmp/x"}))
    finally:
        ac.get_constitution = original

    assert judgment.allowed is False
    assert judgment.verdict is ac.Verdict.BLOCK
    assert judgment.law_number == 5


def test_there_is_exactly_one_constitution():
    """Two would be two reading ledgers, and Law 2's "acting on a file you have
    not read" would depend on which copy you asked."""
    from core.agents.autonomous.autonomous_coordinator import get_constitution
    assert get_constitution() is get_constitution()


@pytest.mark.asyncio
async def test_an_ordinary_act_is_judged_and_the_reading_is_handed_back():
    """The gate is not a bouncer — almost everything runs — so its product is the
    reading. A reading the caller never receives is a log line, not a signal."""
    from core.agents.autonomous.autonomous_coordinator import judge_act

    judgment = await judge_act("tool", "list_directory", {"path": "."})
    assert judgment.allowed is True
    assert judgment.to_dict()["verdict"] == "allow"
