"""A prediction is scored once, against what happened; one not held has no score.

Resolving a prediction already resolved (or never made) raises: it used to return accuracy 0.0, which the coordinator
logged as a measurement of a prediction that was all wrong. No store: the system is built and scored in memory.
"""

import asyncio
from datetime import datetime

import pytest

from core.intelligence.predictive_intelligence_system import (Prediction, PredictionDomain, PredictionHorizon,
                                                              PredictiveIntelligenceSystem)


def test_a_prediction_is_scored_once_and_one_not_held_raises():
    async def run():
        system = PredictiveIntelligenceSystem()
        system.active_predictions["p1"] = Prediction(
            id="p1", domain=PredictionDomain.SYSTEM_PERFORMANCE, horizon=PredictionHorizon.SHORT_TERM,
            predicted_value=0.8, confidence=0.7, timestamp=datetime.now(), reasoning="test")
        result = await system.validate_prediction("p1", 0.6)
        assert result.accuracy == pytest.approx(0.8), "scored against what happened"
        assert "p1" not in system.active_predictions
        with pytest.raises(ValueError, match="not found"):
            await system.validate_prediction("p1", 0.6)
        assert system.accuracy_metrics["system_performance"] == [pytest.approx(0.8)], \
            "the second resolution recorded no accuracy"

    asyncio.run(run())
