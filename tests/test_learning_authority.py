#!/usr/bin/env python3
"""The learning authority, and the boundary around what may contribute to it.

Before this existed, `UnifiedLearningSystem` was the declared `ILearningSystem`
-- exported from the package, wired in `core/main.py` -- while referencing the
model-free learners zero times. The stack with the experimental evidence behind
it (EDU-01 to EDU-11) had no owner and was assembled ad hoc at three consumer
call sites.

These tests pin the inversion: the model-free stack is the authority, and a
model is a contributor whose proposals are never evidence.

THE INVERSION COMPLETED, AND THIS MODULE STOPPED RUNNING. `learning_authority.py`
was deleted and its model-free implementation folded INTO `UnifiedLearningSystem`,
so there is no longer an authority class and a contributor class -- there is one
authority, and `core/learning/__init__.py` says so: "`UnifiedLearningSystem` IS
this authority. The correct model-free ILearningAuthority (once a separate
`SubstrateLearning` in a deleted module)". The import here still named the
deleted module, so all eight of these tests raised ModuleNotFoundError at
collection and the propose/attest boundary -- the load-bearing property of the
whole design -- has been unguarded ever since.
"""

import pytest

from core.learning.unified_learning_system import (Admission, Contribution,
                                                   ContributionKind,
                                                   UnifiedLearningSystem,
                                                   get_learning_authority)
from core.learning.rule_induction import CandidateRule, Fact, RuleEffects
from core.learning.rule_store import EpistemicStatus


class _Store:
    """Records what the authority asked the rule store to do."""

    def __init__(self):
        self.calls = []

    async def record_induction(self, rule, *, domain_id, evidence_ids):
        self.calls.append({"rule": rule, "domain_id": domain_id,
                           "evidence_ids": list(evidence_ids)})
        return type("Stored", (), {"rule_id": "rule_test", "rule": rule})()


def _rule():
    return CandidateRule(
        body=frozenset({Fact.parse("RAVEN(?X)")}),
        effects=RuleEffects(add=frozenset({Fact.parse("BLACK(?X)")})),
        action=None)


@pytest.fixture
def authority():
    # `_store` is the lazy rule-store handle, not a constructor argument, so the
    # recording double is installed on the instance.
    learner = UnifiedLearningSystem()
    learner._store = _Store()
    learner.register_contributor("qwen", "model-based proposer")
    return learner


def test_the_package_names_ONE_authority():
    """There were two names and the distinction between them was the point:
    the model-free stack was the authority, `UnifiedLearningSystem` was the
    contributor. The collapse folded the implementation in, so the assertion is
    no longer that both names exist -- it is that the two ways of reaching the
    authority reach the SAME object, which is what leaves no second owner."""
    import core.learning as package
    assert hasattr(package, "get_learning_authority")
    assert hasattr(package, "UnifiedLearningSystem")
    assert not hasattr(package, "SubstrateLearning"), (
        "the deleted class is exported again -- there is a second authority")
    from core.learning import get_unified_learning_system
    assert get_learning_authority() is get_unified_learning_system()


def test_the_authority_owns_the_model_free_stack():
    """It must reach induction and the rule store itself, rather than leaving
    consumers to assemble the parts."""
    learner = get_learning_authority()
    assert learner.inducer is not None
    assert learner.store is not None


@pytest.mark.asyncio
async def test_a_contributed_hypothesis_carries_no_evidence(authority):
    """THE load-bearing property. A proposal enters as a CANDIDATE with zero
    evidence roots, so nothing the contributor said counts as support."""
    admission = await authority.contribute(Contribution(
        contributor="qwen", kind=ContributionKind.HYPOTHESIS,
        payload=_rule(), domain_id="zoology",
        rationale="ravens are proverbially black"))

    assert admission.accepted
    assert admission.status is EpistemicStatus.CANDIDATE
    assert admission.is_knowledge is False, "a proposal must never arrive as knowledge"

    call = authority.store.calls[0]
    assert call["evidence_ids"] == [], (
        "a contributor's proposal was recorded WITH evidence; the model would "
        "then be attesting to its own hypothesis")


@pytest.mark.asyncio
async def test_an_unregistered_contributor_cannot_propose(authority):
    """An anonymous proposal is untraceable, so provenance cannot be audited."""
    admission = await authority.contribute(Contribution(
        contributor="somebody", kind=ContributionKind.HYPOTHESIS, payload=_rule()))
    assert not admission.accepted
    assert "not registered" in admission.reason
    assert authority.store.calls == []


@pytest.mark.asyncio
async def test_a_malformed_hypothesis_is_declined_not_repaired(authority):
    admission = await authority.contribute(Contribution(
        contributor="qwen", kind=ContributionKind.HYPOTHESIS,
        payload="ravens are black"))
    assert not admission.accepted
    assert "not a CandidateRule" in admission.reason
    assert authority.store.calls == []


@pytest.mark.asyncio
async def test_non_hypothesis_contributions_are_never_stored(authority):
    """A situation or a formalization is consumed by teaching and
    formalization; neither becomes stored knowledge on its own."""
    for kind in (ContributionKind.SITUATION, ContributionKind.FORMALIZATION,
                 ContributionKind.LESSON):
        admission = await authority.contribute(Contribution(
            contributor="qwen", kind=kind, payload={"anything": True}))
        assert admission.accepted
        assert admission.status is None
    assert authority.store.calls == [], "a non-hypothesis reached the rule store"


def test_a_contribution_cannot_carry_a_confidence():
    """A proposer's certainty about its own output is not a measurement of the
    world. Admitting one would let a fluent contributor grade its own work."""
    fields = Contribution.__dataclass_fields__
    assert "confidence" not in fields
    assert "certainty" not in fields
    assert "score" not in fields


@pytest.mark.asyncio
async def test_rejections_are_recorded_as_faithfully_as_admissions(authority):
    await authority.contribute(Contribution("qwen", ContributionKind.HYPOTHESIS, _rule()))
    await authority.contribute(Contribution("ghost", ContributionKind.HYPOTHESIS, _rule()))
    assert len(authority.admissions) == 2
    assert [a.accepted for a in authority.admissions] == [True, False]

    metrics = await authority.metrics()
    assert metrics["contributions_seen"] == 2
    assert metrics["contributions_accepted"] == 1
    # Admitted is not learned, and the metric must not blur them.
    assert metrics["contributions_promoted_to_knowledge"] == 0
