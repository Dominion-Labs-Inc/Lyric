#!/usr/bin/env python3
"""What the model is doing, asked of the store rather than read out of a log.

Every question about what the substrate had been doing was answered by grepping `logs/lyric_main.log`, which
had reached 852 MB. The narrative log stays; what a person or a console actually asks for is already written
down, and was spread across five tables with no one place to ask.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio  # noqa: E402
from datetime import datetime  # noqa: E402

from core.health.system_control import what_lyric_is_doing  # noqa: E402


class Store:
    """Answers each of the five questions, or refuses one by name."""

    def __init__(self, refuse: str = ""):
        self.refuse, self.asked = refuse, []

    async def execute_query(self, query, params=None, fetch_all=False, **kw):
        q = " ".join(query.split())
        self.asked.append(q)
        if self.refuse and self.refuse in q:
            raise RuntimeError("the store would not answer")
        if "system_control_status" in q:
            return [{"status": "running", "age": 3}]
        if "queue_instances" in q:
            return [{"instance_id": "queue_a1b2c3d4e5f6", "role": "lyric",
                     "started_at": datetime(2026, 11, 19, 13, 2, 23), "age": 11}]
        if "scheduled_jobs" in q:
            return [{"name": "reflection", "interval_s": 600.0, "runs": 1, "errors": 1, "skipped": 0,
                     "stood_down": 0, "last_error": "TimeoutError:", "resume_at": "settling:",
                     "last_run_at": datetime(2026, 11, 19, 12, 47, 2)}]
        if "unified.reflections" in q:
            return [{"reflection": 1, "whose": "own", "window_from": None, "window_to": None,
                     "position": "settling:", "weighed": 1022193, "examined": 1441713,
                     "bore_out": 1021419, "questioned": 33, "did_not_hold": 79,
                     "nothing_to_weigh": 420182, "stood_down": 0, "ended_at": None}]
        if "failure_events" in q:
            return [{"component": "agents.queue_authority", "n": 23, "open": 23,
                     "last_at": datetime(2026, 11, 19, 13, 1, 50), "last_was": "TypeError"}]
        raise AssertionError(f"nothing asks this: {q[:90]}")


def test_it_answers_the_five_things_from_the_store():
    doing = asyncio.run(what_lyric_is_doing(Store()))
    assert doing["model"] == {"status": "running", "said_seconds_ago": 3}
    # A NAME A PERSON CAN SAY, derived from the identifier rather than stored beside it.
    held = doing["instances"][0]
    assert held["id"] == "queue_a1b2c3d4e5f6" and held["beat_seconds_ago"] == 11
    assert held["name"] and held["name"] != held["id"] and len(held["name"].split("-")) == 3, held["name"]
    # WHAT ITS PERIODIC WORK HAS DONE, including where a resumable pass is waiting to be taken up from --
    # which used to live on a job object inside one process and died with it.
    work = doing["work"][0]
    assert (work["name"], work["runs"], work["errors"]) == ("reflection", 1, 1)
    assert work["waiting_to_resume_at"] == "settling:"
    assert doing["reflection"]["did_not_hold"] == 79
    assert doing["failures"][0]["unrecovered"] == 23
    assert "unreadable" not in doing, doing.get("unreadable")


def test_one_table_it_cannot_read_does_not_hide_the_other_four():
    """A console that shows nothing because one table was missing is worse than one that shows four things
    and names the fifth. Measured live: `unified.scheduled_jobs` did not exist yet on the first ask, and the
    answer came back with the other four and said which one it could not read."""
    doing = asyncio.run(what_lyric_is_doing(Store(refuse="scheduled_jobs")))
    assert doing["work"] == []
    assert "work" in doing["unreadable"] and "would not answer" in doing["unreadable"]["work"]
    assert doing["model"]["status"] == "running", "the rest is still answered"
    assert doing["reflection"]["examined"] == 1441713
    assert doing["failures"][0]["times"] == 23


def test_it_asks_for_what_has_failed_by_when_it_happened():
    """`occurred_at` is the column. Asked for a column that does not exist, the whole part came back empty
    and the only sign was a suppressed query error in the log."""
    store = Store()
    asyncio.run(what_lyric_is_doing(store, failures_within_hours=6))
    failures = [q for q in store.asked if "failure_events" in q][0]
    assert "occurred_at >=" in failures, failures
    assert "FILTER (WHERE NOT recovered)" in failures, "what is still unrecovered is the part that matters"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
