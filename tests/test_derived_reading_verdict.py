#!/usr/bin/env python3
"""The derived reading's search runs once per code+evidence, never in the substrate's interpreter.

It ran in a thread of the substrate process, held the GIL for longer than a
boot (single-text encodes fell from ~120 to ~2 per second), and its search
FAILS after ~10 minutes -- so no result was ever cached and every boot paid it
again. The search is deterministic, so its verdict, failure included, is
recorded against the code and evidence it came from.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics import derived_reader as dr  # noqa: E402


@pytest.fixture
def cache(tmp_path, monkeypatch):
    path = tmp_path / "derived_reading.pkl"
    monkeypatch.setattr(dr, "_cache_path", lambda: path)
    monkeypatch.setattr(dr, "_cache_key", lambda: "code-and-evidence")
    monkeypatch.setattr(dr, "_state", {"derived": False, "reading": None, "why": ""})
    return path


def test_a_failed_search_is_recorded_and_reused(cache, monkeypatch):
    dr._persist_verdict(None, "synthesis returned no_procedure: bound reached")
    assert dr._load_cached_verdict() == (None, "synthesis returned no_procedure: bound reached")

    import multiprocessing

    def _no_spawn(*_a, **_k):
        raise AssertionError("a recorded verdict must not start the search again")

    monkeypatch.setattr(multiprocessing, "get_context", _no_spawn)
    ok, why = asyncio.run(dr.register_off_process())
    assert not ok and "no_procedure" in why


def test_a_verdict_for_other_code_is_not_used(cache, monkeypatch):
    dr._persist_verdict(None, "an old failure")
    monkeypatch.setattr(dr, "_cache_key", lambda: "changed-code")
    assert dr._load_cached_verdict() is None


def test_an_exception_in_the_search_is_not_a_verdict(cache, monkeypatch):
    class _Sender:
        sent = None

        def send(self, value):
            _Sender.sent = value

        def close(self):
            pass

    def _raises():
        raise MemoryError("out of memory")

    monkeypatch.setattr(dr, "_derive_procedures", _raises)
    dr._derive_in_child(_Sender())
    procedures, why, is_verdict = _Sender.sent
    assert procedures is None and "MemoryError" in why and is_verdict is False


def test_in_process_derive_records_a_search_outcome_but_not_an_error(cache, monkeypatch):
    monkeypatch.setattr(dr, "_derive_procedures", lambda: (None, "derivation raised X", False))
    reading, why = dr.derive()
    assert reading is None and not cache.exists()

    monkeypatch.setattr(dr, "_state", {"derived": False, "reading": None, "why": ""})
    monkeypatch.setattr(dr, "_derive_procedures", lambda: (None, "synthesis returned no_procedure", True))
    reading, why = dr.derive()
    assert reading is None and cache.exists()
    assert dr._load_cached_verdict() == (None, "synthesis returned no_procedure")
