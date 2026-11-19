#!/usr/bin/env python3
"""The human's door to a standing halt reads it the same way the Constitution does.

A halt is durable: the Constitution writes it to `unified.emergency_halts` and reads it back at every start
(`AutonomousCoordinator.restore_halt`), so a halted substrate comes up halted. Law 1 puts lifting it in human
hands -- and there was no way for a human to do it, because `resume(authorized_by=...)` is a coordinator method
and reaching it meant starting the very substrate the halt says must not run. `scripts/resume.py` is that door.

WHAT MUST NOT DIVERGE is how the two READ the log. The script saying "no halt stands" while `restore_halt` finds
one is the worst outcome available here: the operator is told it is clear and the substrate comes up stopped. So
these tests compare the script's query against the coordinator's, clause for clause, rather than trusting that
two copies of one query stay the same.

Nothing here needs a store.
"""
import re
from pathlib import Path

import pytest

COORDINATOR = Path("core/agents/autonomous/autonomous_coordinator.py")
SCRIPT = Path("scripts/resume.py")


def _clauses(sql: str) -> set:
    """The SQL's meaningful parts, whitespace and case aside."""
    sql = " ".join(str(sql).split()).lower()
    return {c.strip() for c in re.split(r"\bwhere\b|\band\b|\border by\b|\blimit\b", sql) if c.strip()}


def _restore_halt_sql() -> str:
    """The query `restore_halt` reads the standing halt with, taken from the source."""
    text = COORDINATOR.read_text(encoding="utf-8")
    at = text.index("async def restore_halt")
    body = text[at:at + 2000]
    parts = re.findall(r'"([^"]*emergency_halts[^"]*)"|"([^"]*metadata->>[^"]*)"|"([^"]*ORDER BY[^"]*)"', body)
    found = re.search(r'execute_query\(\s*((?:"[^"]*"\s*)+)', body)
    assert found, "restore_halt no longer builds its query from string literals; this test must be re-read"
    return " ".join(s.strip('"') for s in re.findall(r'"([^"]*)"', found.group(1)))


def test_the_script_reads_the_halt_the_way_the_constitution_does():
    from importlib import util
    spec = util.spec_from_file_location("_resume", SCRIPT)
    module = util.module_from_spec(spec)
    # The module inserts the project root on sys.path at import; nothing else runs at import time.
    spec.loader.exec_module(module)
    assert _clauses(module._STANDING) == _clauses(_restore_halt_sql()), (
        "scripts/resume.py and AutonomousCoordinator.restore_halt no longer read the containment log the same "
        "way. The script would report a state the substrate does not come up in.")


def test_only_the_constitutions_own_events_decide():
    """The table has other writers. Reading "the newest row" let any such row mask a real halt, so both
    readers filter on the source and on the event kind."""
    from importlib import util
    spec = util.spec_from_file_location("_resume", SCRIPT)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql = " ".join(module._STANDING.split()).lower()
    assert "metadata->>'source' = 'constitution'" in sql
    assert "'halt'" in sql and "'resume'" in sql
    assert "order by timestamp desc" in sql and "limit 1" in sql


def test_a_halt_is_not_lifted_by_the_substrate():
    """The rule `AutonomousCoordinator.resume` applies, applied at the door too: a containment the contained
    party can lift is not one."""
    from core.agents.autonomous.shared_types import SUBSTRATE_ACTOR, is_substrate_actor
    assert is_substrate_actor(SUBSTRATE_ACTOR)
    assert is_substrate_actor(None)
    assert not is_substrate_actor("stefan")


def test_the_event_written_is_the_one_restore_halt_looks_for():
    """`restore_halt` returns False -- not halted -- only when the newest event's kind is not "halt". So the
    row this script writes has to carry event=resume and source=constitution, or lifting does nothing."""
    body = SCRIPT.read_text(encoding="utf-8")
    assert '"event": "resume"' in body
    assert '"source": "constitution"' in body
    assert "INSERT INTO unified.emergency_halts" in body
    # It records WHO, because a resume with no human named is not one.
    assert '"by": who' in body


def test_the_script_starts_nothing():
    """It must not warm a coordinator, a memory agent or the reader: the halt says the substrate may not run,
    and five minutes of warm to lift a halt is why there was no door."""
    body = SCRIPT.read_text(encoding="utf-8")
    for started in ("AutonomousCoordinator(", "get_memory_agent", "warm_word_classes",
                    "ready_to_read", "get_neural_bridge"):
        assert started not in body, f"{started} would start what the halt forbids"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
