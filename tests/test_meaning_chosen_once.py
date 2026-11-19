#!/usr/bin/env python3
"""One turn chooses its meaning once, as it reads once.

Reading a text and asking memory what it holds about its meanings were both kept; CHOOSING between the
meanings was not, and nineteen places along the answering path ask what a sentence means. The listener weighed
the same readings against the same `Heard` eleven times for one question and said so each time: eleven
identical `listening:` lines within six milliseconds (lyric_db, 2026-11-19 12:50:01).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agents.autonomous import autonomous_coordinator as ac  # noqa: E402
from core.agents.autonomous.autonomous_coordinator import Conversation  # noqa: E402


def test_one_turn_weighs_its_meanings_once():
    weighed = {"times": 0}

    def _meaning_of(utterances, heard=None):
        weighed["times"] += 1
        return ("the meaning", heard)

    was, ac._meaning_of = ac._meaning_of, _meaning_of
    try:
        coord = Conversation.__new__(Conversation)
        coord._taken_as = {}
        coord._last_meant = None
        coord._reading_key = lambda text: (str(text), 7, frozenset())
        coord._read = lambda text: ("read once",)
        coord._heard = lambda text: None

        first = coord._meaning("What is a dog?")
        for _ in range(10):
            assert coord._meaning("What is a dog?") == first
        assert weighed["times"] == 1, f"weighed {weighed['times']} times for one question"

        # Memory answering changes the question: the choice before listening is not the choice after it.
        coord._heard = lambda text: "what memory holds"
        after = coord._meaning("What is a dog?")
        assert weighed["times"] == 2, "it weighs again once memory has been asked"
        assert after != first
        assert coord._meaning("What is a dog?") == after
        assert weighed["times"] == 2, "and not a third time"

        # Another text is another question.
        coord._meaning("What is a cat?")
        assert weighed["times"] == 3
    finally:
        ac._meaning_of = was


def test_a_conversation_that_predates_the_cache_still_answers():
    """Code is adopted into a running process, so the attribute has a default on the class."""
    assert Conversation.__new__(Conversation)._last_meant is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
