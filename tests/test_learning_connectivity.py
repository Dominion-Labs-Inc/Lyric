#!/usr/bin/env python3
"""Learning pipeline connectivity tests
====================================
Guards the learning-path repairs that were previously verified only by
throwaway scripts.

Everything here was confirmed once by hand and would have silently regressed,
which is precisely how the defects it covers accumulated in the first place.

Each test names the defect it pins down.

NINETEEN TESTS WERE RETIRED HERE, AND THE MODULE HAD STOPPED RUNNING ENTIRELY.
It imported `core.agents.autonomous.learning_adapter`, which no longer exists,
so ALL 26 tests raised ModuleNotFoundError at collection — including the seven
below, which guard live behaviour and had not run in months.

What the nineteen tested is gone, not moved. `LearningAdapter` was retired in
the learning-authority collapse; `_record_experience_outcome` went with it; and
the chain they fed — outcomes → patterns → recommendation → applier → a task's
priority — ended at a `recommendations = []` literal inside `_learning_phase`,
looping zero times into an applier (`_apply_learning_recommendation`, 119 lines)
that nothing else called. That dead loop and that applier are now deleted from
the coordinator too, so an idle tier no longer reads as "apply what was learned"
while being unable to.

What survives here is what still has a subject: the exploration-quota accounting
and the credit invariant.
"""

import asyncio
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ------------------------------------------------------- exploration accounting


def _bare_coordinator():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator

    return object.__new__(AutonomousCoordinator)


def test_exploration_quota_starts_at_zero():
    assert _bare_coordinator()._calculate_exploration_quota() == 0.0


def test_exploration_quota_rises_with_low_trial_selections():
    """The method did not exist; its call site guarded on hasattr and passed
    0.0, so `quota_used < quota_limit` was permanently true and the 10%
    exploration cap never bound."""
    coordinator = _bare_coordinator()

    for trials in [0, 1, 2, 3, 9, 9, 9, 9, 9, 9]:
        coordinator._record_exploration_decision(SimpleNamespace(trials=trials))

    quota = coordinator._calculate_exploration_quota()

    assert quota == pytest.approx(0.4)
    assert quota >= 0.10, "cap must be able to bind"


def test_well_tried_selections_do_not_consume_quota():
    coordinator = _bare_coordinator()

    for _ in range(10):
        coordinator._record_exploration_decision(SimpleNamespace(trials=50))

    assert coordinator._calculate_exploration_quota() == 0.0


def test_exploration_history_is_bounded():
    """An unbounded window would make the quota unresponsive over time."""
    coordinator = _bare_coordinator()

    for _ in range(coordinator.EXPLORATION_WINDOW * 3):
        coordinator._record_exploration_decision(SimpleNamespace(trials=0))

    assert len(coordinator._exploration_history) == coordinator.EXPLORATION_WINDOW


def test_a_malformed_strategy_is_not_silently_counted():
    """The fixture was a bare SimpleNamespace, standing in for a strategy that
    cannot occur: the one production caller passes `select_strategy()`, typed
    `Optional[LearningStrategy]`, and `LearningStrategy.trials` is a dataclass
    field with a default -- so the argument is either None or has trials.

    What matters is that a malformed arm is not quietly recorded as
    not-exploration. Swallowing it with a `getattr(..., 0)` would count it as a
    well-tried pick, and the 10% cap would stop binding for it -- which is
    exactly the defect the test above this one pins down. So it raises, and
    None (a real state: no arm passed the gate) is the case that is handled.
    """
    coordinator = _bare_coordinator()

    with pytest.raises(AttributeError):
        coordinator._record_exploration_decision(SimpleNamespace())

    # None IS a decision, and spends no exploration.
    coordinator = _bare_coordinator()
    coordinator._record_exploration_decision(None)
    assert coordinator._calculate_exploration_quota() == 0.0


# ------------------------------------------------ the credit invariant itself


def test_outcomes_without_a_class_are_denied_credit():
    """This is the behaviour I misdiagnosed as a broken learning loop.

    track_learning_outcome refuses to credit a strategy when the outcome is
    unclassified. Recording an outcome with no outcome_class must leave the
    strategy statistics untouched -- that is the credit invariant working,
    not a failure to learn.
    """
    from core.learning.meta_learning import (
        LearningStrategyType,
        MetaLearner,
        TaskFamily,
    )

    async def scenario():
        learner = MetaLearner()
        if hasattr(learner, "initialize"):
            await learner.initialize()

        strategy = learner.strategies["classification_transfer"]
        before = strategy.trials

        for _ in range(6):
            await learner.track_learning_outcome(
                task_type=TaskFamily.CLASSIFICATION,
                strategy_type=LearningStrategyType("transfer"),
                success=True,
                performance_score=0.95,
                time_ms=50.0,
                iterations=1,
                context={},
            )
        return before, learner.strategies["classification_transfer"].trials

    before, after = asyncio.run(scenario())
    assert after == before, "unclassified outcomes must not earn credit"


def test_classified_outcomes_do_earn_credit():
    """The other half: with an outcome_class, the loop closes and selection
    sees real evidence."""
    from core.learning.meta_learning import (
        LearningStrategyType,
        MetaLearner,
        OutcomeClass,
        TaskFamily,
    )

    async def scenario():
        learner = MetaLearner()
        if hasattr(learner, "initialize"):
            await learner.initialize()

        # DELTA, not absolute. Posteriors are loaded from the store on init --
        # that persistence is the invariant this suite exists to protect -- so
        # `trials == 6` asserts the store was empty, which is only true until
        # something actually learns. Any real run through
        # learn_from_example records TRANSFER outcomes against this same
        # strategy_id, and the count was then read as a broken loop rather than
        # as evidence the loop had run. The claim under test is that a
        # classified outcome EARNS credit, which is a statement about the
        # change, exactly as the unclassified case above measures it.
        before = learner.strategies["classification_transfer"]
        prior_trials, prior_successes = before.trials, before.successes

        for _ in range(6):
            await learner.track_learning_outcome(
                task_type=TaskFamily.CLASSIFICATION,
                strategy_type=LearningStrategyType("transfer"),
                success=True,
                performance_score=0.95,
                time_ms=50.0,
                iterations=1,
                context={},
                outcome_class=OutcomeClass.SUCCESS,
            )
        return learner.strategies["classification_transfer"], prior_trials, prior_successes

    strategy, prior_trials, prior_successes = asyncio.run(scenario())

    assert strategy.trials - prior_trials == 6
    assert strategy.successes - prior_successes == 6
    assert strategy.success_rate == pytest.approx(
        strategy.successes / strategy.trials)
    assert strategy.confidence > 0.0
