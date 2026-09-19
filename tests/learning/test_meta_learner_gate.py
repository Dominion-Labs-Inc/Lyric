#!/usr/bin/env python3
"""The production gate constrains which arms may be chosen; it never hands one back.

It used to sample first and check afterwards. When the sampled arm failed, a
different arm was substituted -- recorded with the propensities of the policy
that had NOT chosen it -- and when every arm failed, the blocked arm was
returned "to avoid failure", exactly as though it had passed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.learning.meta_learning import (
    LearningStrategyType, MetaLearner, TaskFamily)
from core.learning.unified_learning_system import UnifiedLearningSystem


def _learner(arms):
    """A hermetic MetaLearner holding exactly `arms`, recording decisions in memory."""
    ml = MetaLearner(config={"enable_adaptation": False})
    ml.strategies.clear()
    ml.task_strategy_map.clear()
    ml._loaded = True
    recorded = []

    async def _record_decision(**kwargs):
        recorded.append(kwargs)
        return f"d_{len(recorded)}"

    ml._record_decision = _record_decision
    for name, trials, successes, confidence in arms:
        sid = ml._add_strategy(strategy_type=LearningStrategyType(name),
                               task_type=TaskFamily.CONTROL, parameters={})
        s = ml.strategies[sid]
        s.trials, s.successes, s.failures = trials, successes, trials - successes
        s.success_rate = successes / trials if trials else 0.0
        s.confidence = confidence
    return ml, recorded


def _select(ml, quota, sink):
    return asyncio.run(ml.select_strategy(
        TaskFamily.CONTROL, min_confidence=0.5, enable_hard_gate=True,
        exploration_quota_used=quota, _decision_sink=sink))


def test_every_arm_blocked_returns_no_arm_and_says_why():
    # 37 trials at 16% (fails the CI gate) and a fresh arm with the exploration
    # budget spent (fails the trials gate).
    ml, recorded = _learner([("optimization", 37, 6, 1.0), ("verify_first", 0, 0, 0.0)])
    sink = {}
    assert _select(ml, quota=0.5, sink=sink) is None
    blocked = sink["gate_blocked"]
    assert set(blocked) == set(ml.strategies)
    assert all(reason for reason in blocked.values())
    assert recorded == [], "a decision was recorded for a choice that was not made"


def test_the_bandit_samples_only_arms_the_gate_allows():
    ml, recorded = _learner([("optimization", 37, 6, 1.0),
                             ("verify_first", 0, 0, 0.0),
                             ("diagnose_then_act", 0, 0, 0.0)])
    blocked_id = next(sid for sid, s in ml.strategies.items()
                      if str(s.strategy_type) == "optimization")
    for _ in range(50):
        chosen = _select(ml, quota=0.0, sink={})
        assert chosen is not None and chosen.strategy_id != blocked_id
    # The propensities recorded are those of the policy that chose: the blocked
    # arm had no chance of being chosen, so it is not among the candidates.
    for decision in recorded:
        assert blocked_id not in {p["strategy_id"] for p in decision["propensities"]}
        assert abs(sum(p["propensity"] for p in decision["propensities"]) - 1.0) < 1e-6


def test_confidence_is_a_preference_among_allowed_arms():
    ml, _ = _learner([("confident", 30, 28, 0.9), ("fresh", 0, 0, 0.0)])
    confident_id = next(sid for sid, s in ml.strategies.items()
                        if str(s.strategy_type) == "confident")
    for _ in range(20):
        assert _select(ml, quota=0.0, sink={}).strategy_id == confident_id
    # With the confident arm out, the unconfident allowed arm is still chosen.
    ml2, _ = _learner([("fresh", 0, 0, 0.0)])
    assert _select(ml2, quota=0.0, sink={}) is not None


def test_a_decision_that_chose_no_arm_lets_the_exploration_budget_recover():
    explored = SimpleNamespace(trials=0)
    history = SimpleNamespace(recent_strategy_usage=[explored])
    assert UnifiedLearningSystem._calculate_exploration_quota(history) == 1.0
    history.recent_strategy_usage += [None] * 9
    assert UnifiedLearningSystem._calculate_exploration_quota(history) == 0.1
