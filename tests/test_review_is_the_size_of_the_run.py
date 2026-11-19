#!/usr/bin/env python3
"""A review reviews what the run taught, and answers through the one reasoning authority.

Teaching two lessons on 2026-11-19 admitted 3 facts in under a minute, and then sat 51 minutes asking itself
200 questions. Its own report says what it was doing:

    {'held': 10418, 'reviewed': 1464, 'asked': 200, 'right': 49, 'cannot_ask': 1264, 'misread': 112,
     'denied': 0, 'not_derived': 34, 'before': (0.4859, 2274), 'after': (0.4346, 2473)}

Two things were wrong with that, and they are different.

ITS SIZE HAD NOTHING TO DO WITH THE RUN. `target = min(sample or REVIEW_SAMPLE, len(held))` drew from EVERY
belief in the domain, so a pass that admitted 3 facts asked 200 questions about facts held for weeks -- almost
none of them the three just taught. "Review what was learned" is the name, "its count is the pass's own
outcome" is the stated intent, and neither was true. The one door now says what it left held
(`consider_many(kept=...)`, carried on `Report.claims`) and the review is given those.

IT NEVER REACHED THE REASONING AUTHORITY. It answered with `answer_over_graph`, the graph oracle the authority
uses inside itself, so not one of the eleven kinds of thinking was selected, tried or declined for any of its
200 questions -- and what it recorded as COMPETENCE, moving the domain from 0.4859 down to 0.4346, was the
reach of a graph walk. `denied: 0` with `not_derived: 34` is that: nothing was ever asked to derive anything.

Nothing here needs a store or a teach run; these pin the contracts the two fixes rest on.
"""
import inspect
from pathlib import Path

import pytest

from core.learning.teaching import Report
from core.learning.unified_learning_system import UnifiedLearningSystem


# ---------------------------------------------------------------- the review is the size of the run

def test_a_pass_reports_what_it_left_held():
    assert Report(source="s", domain="d").claims == (), "a pass that taught nothing claims nothing"
    assert "claims" in Report.__dataclass_fields__


def test_the_door_can_say_what_it_kept():
    """`consider_many` takes `kept`, and tells it each claim left held -- admitted, or already held."""
    signature = inspect.signature(UnifiedLearningSystem.consider_many)
    assert "kept" in signature.parameters
    assert signature.parameters["kept"].default is None, "a caller that does not ask is unaffected"
    source = inspect.getsource(UnifiedLearningSystem._consider_many)
    # Both dispositions leave the claim HELD, so both are reported: a re-teach is not a second witness, but
    # the fact is there to be reviewed either way.
    assert source.count("kept(claim)") == 2, "admitted and already-held are both claims the run left standing"


def test_the_review_takes_the_claims_a_run_left_held():
    signature = inspect.signature(UnifiedLearningSystem.review_learned)
    assert "claims" in signature.parameters
    assert signature.parameters["claims"].default is None, (
        "None must still review the domain, which is what asking for a domain's review means")
    source = inspect.getsource(UnifiedLearningSystem.review_learned)
    assert "if claims is not None:" in source
    assert "str(b.claim) in wanted" in source


def test_an_empty_set_of_claims_reviews_nothing_rather_than_everything():
    """A run that left nothing held taught nothing to review. Falling back to the domain would be the defect
    again, and a fallback besides."""
    source = inspect.getsource(UnifiedLearningSystem.review_learned)
    # Built straight from what was given, with nothing standing in for an empty set.
    assert "wanted = {str(c) for c in claims}" in source
    assert "held = [b for b in held if str(b.claim) in wanted]" in source


def test_teaching_hands_the_review_what_every_source_taught():
    body = Path("scripts/teach.py").read_text(encoding="utf-8")
    assert "claims=taught_claims" in body, "the review is still asked of the whole domain"
    assert "for _name, r in reports" in body, "claims are gathered from every source this run taught from"
    assert "dict.fromkeys" in body, "the same claim taught from two sources is one claim to review"


# ---------------------------------------------------------------- answered through the one authority

def test_the_review_answers_through_the_reasoning_authority():
    source = inspect.getsource(UnifiedLearningSystem.review_learned)
    # The CALL, not the note recording that it used to be one.
    assert "await answer_over_graph(" not in source, (
        "the review still reaches past the authority to the graph oracle")
    assert "_reviewed_by_the_authority" in source

    helper = inspect.getsource(UnifiedLearningSystem._reviewed_by_the_authority)
    assert "get_neural_bridge" in helper and "bridge.reason(" in helper, (
        "there is one reasoning authority and a review is reasoning")


def test_the_review_asks_the_affirmative_and_reads_the_verdict_once():
    helper = inspect.getsource(UnifiedLearningSystem._reviewed_by_the_authority)
    # The verdict is about the proposition STANDING UP; `fact.positive` says which verdict is right. Asking a
    # denial would get "yes" for the wrong reason.
    assert 'Meaning("ask", (MeaningFact(fact.relation, fact.subject, fact.obj),))' in helper
    # ONE reader of a verdict: the reasoner reports it in the answer text and `_affirmed` reads it. A second
    # reader would be a second authority on what the first one said.
    assert "Conversation._affirmed" in helper
    assert 'get("verified")' in helper, "a verdict the authority did not verify settles nothing"


def test_a_review_is_the_substrates_own_work():
    """Whose a reasoning is decides whose record it becomes. A review is the substrate asking itself about what
    it was taught, so it is not written as any person's."""
    helper = inspect.getsource(UnifiedLearningSystem._reviewed_by_the_authority)
    assert "SUBSTRATE_ACTOR" in helper
    assert '"review": True' in helper


def test_the_verdict_reader_is_the_one_the_conversation_uses():
    from core.agents.autonomous.autonomous_coordinator import Conversation
    assert Conversation._affirmed("Proved: a robin is an animal") is True
    assert Conversation._affirmed("Disproved: a dog is a bird") is False
    assert Conversation._affirmed("No: a grandfather clock is a beer") is False
    assert Conversation._affirmed("Undecided") is None
    assert Conversation._affirmed("") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
