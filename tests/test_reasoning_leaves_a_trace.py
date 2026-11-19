#!/usr/bin/env python3
"""A reasoning that tried nothing still says what it was asked and why nothing ran.

Asked all day on 2026-11-19 why no reasoning trace ever appeared, the store answered: 0 of 1,441,783 memories
carry a `reasoning_trace`, and `unified.experience_pool` holds not one experience of kind `reasoning`. The
machinery was all there -- `MemoryAgent.take_in_reasoning` passes `reasoning_trace=list(steps)`, and the
authority calls it -- so nothing was broken in the writing. Four separate things stopped anything being written:

  1. ONE FIELD DOING TWO JOBS. The capture gate asked `cached_memories is None`, which answers whether to
     RECALL. Two callers pass `[]` to mean "reason over the premises I have, not over memory" -- the
     conversation's own reasoning and the causal analyzer, both saying so in as many words -- and silently got
     no record of having reasoned. Whether to recall and whether to record are now two questions
     (`recorded_elsewhere`), and the executor iteration the old test was written for went away with the models.
  2. THE WORKING THROWN AWAY ON THE ONE BRANCH THAT NEEDED IT. `working` is built before strategy selection and
     attached after the loop, so `if not applicable_strategies: return result` binned it -- and that is the
     branch that fired thirteen times that day.
  3. THE SELECTION ACCOUNT EXISTING ONLY AS A LOG LINE. `_select_strategies` computed which kinds were not
     allowed and which declined, and only logged them. The engine's own comment forbids exactly this: "a log is
     read by whoever is watching the process, and in production nobody is, so an answer whose working exists
     only at INFO has no working at all."
  4. A FIRE-AND-FORGET TASK NOBODY HELD. `asyncio.create_task(...)` with no reference kept: the loop holds only
     a weak reference, so the one writer of a reasoning's record could be collected mid-flight. It would never
     reach its own `except` either, which is why no failure was ever logged for a trace that never appeared.

The engine case here runs the real engine over a context nothing can help with, which is the case that produced
nothing at all. No store, no model.
"""
import asyncio

import pytest

from core.reasoning.abstract_reasoning_engine import AbstractReasoningEngine, ReasoningContext
from core.reasoning.neural_bridge import ReasoningRequest
from core.reasoning.reasoning_interfaces import ReasoningType


def _engine() -> AbstractReasoningEngine:
    engine = AbstractReasoningEngine()
    assert engine.strategies, "the engine holds no strategies; this test would prove nothing"
    return engine


def test_a_reasoning_that_tried_nothing_still_accounts_for_itself():
    """The exact shape of the 13 events: one kind allowed, it declines, ten excluded, nothing tried."""
    engine = _engine()
    context = ReasoningContext(
        context_id="t1", domain="general", problem_type="question",
        # Deductive only, as a question about a kind asks for (`THINKING_FOR_LINK_KIND`), and no rules --
        # so the one kind allowed declines and the rest are never asked.
        allowed_reasoning_types=[ReasoningType.DEDUCTIVE], rules=[], premises=[])
    result = asyncio.run(engine.reason(context))
    assert result.intermediate_results, (
        "a reasoning that tried nothing carried no working at all, so nothing anywhere says why")
    kinds = next((e["kinds"] for e in result.intermediate_results if isinstance(e, dict) and "kinds" in e), None)
    assert kinds is not None, f"no selection account in the working: {result.intermediate_results}"
    assert kinds["held"] == len(engine.strategies)
    assert kinds["selected"] == []
    assert "deductive" in kinds["declined"], kinds
    assert len(kinds["not_allowed"]) == len(engine.strategies) - 1, kinds
    # And the message says which, so it is readable without the log.
    assert "not allowed here" in (result.error_message or "")
    assert "could not help" in (result.error_message or "")


def test_the_account_names_what_was_asked_for():
    engine = _engine()
    account = {}
    context = ReasoningContext(context_id="t2", domain="general", problem_type="question",
                               allowed_reasoning_types=[ReasoningType.DEDUCTIVE], rules=[], premises=[])
    asyncio.run(engine._select_strategies(context, account=account))
    assert account["asked_for"] == ["deductive"]
    assert set(account) == {"held", "asked_for", "selected", "not_allowed", "declined"}


def test_every_kind_is_accounted_for_exactly_once():
    """Selected, excluded or declined -- a kind in none of the three is a kind nobody can ask about."""
    engine = _engine()
    account = {}
    context = ReasoningContext(context_id="t3", domain="general", problem_type="question",
                               allowed_reasoning_types=[ReasoningType.DEDUCTIVE], rules=[], premises=[])
    asyncio.run(engine._select_strategies(context, account=account))
    seen = set(account["selected"]) | set(account["not_allowed"]) | set(account["declined"])
    assert len(seen) == account["held"] == len(engine.strategies)
    assert not (set(account["not_allowed"]) & set(account["declined"]))


def test_recording_is_not_decided_by_whether_memory_was_recalled():
    """The two questions are separate fields now. A caller that skips recall still gets a record."""
    reasoned_over_premises = ReasoningRequest(query="q", cached_memories=[])
    assert reasoned_over_premises.recorded_elsewhere is False, (
        "skipping memory injection must not also skip recording the reasoning")
    an_iteration = ReasoningRequest(query="q", recorded_elsewhere=True)
    assert an_iteration.cached_memories is None, "and the reverse: not recording says nothing about recall"


def test_the_record_writer_is_held_while_it_runs():
    """The loop keeps only a weak reference to a task, so the one writer of a reasoning's record has to be
    held somewhere or it may be collected before it writes."""
    import inspect

    from core.reasoning.neural_bridge import NeuralSymbolicBridge
    source = inspect.getsource(NeuralSymbolicBridge._finish)
    assert "create_task" in source, "this test is pinned to the fire-and-forget capture; re-read it"
    assert "_recording.add" in source, "the capture task is not held, so it can be garbage collected"
    assert "add_done_callback" in source, "nothing discards the task when it finishes"
    # The GATE, not the note explaining why it is no longer that: the old test read the request's field.
    assert "request.cached_memories is None" not in source, (
        "the capture gate is reading whether memory was recalled as consent to record")
    assert "recorded_elsewhere" in source, "the gate does not ask the question it should"

    bridge = NeuralSymbolicBridge.__new__(NeuralSymbolicBridge)
    NeuralSymbolicBridge.__init__(bridge)
    assert isinstance(bridge._recording, set) and not bridge._recording


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
