#!/usr/bin/env python3
"""
Lyric Intelligence Module
Predictive intelligence: what the substrate predicts, and the checking of each
prediction against what happened.
"""

from .predictive_intelligence_system import (
    Departure,
    PredictiveIntelligenceSystem,
    PredictionDomain,
    PredictionHorizon,
    Prediction,
    get_predictive_intelligence,
)

__all__ = [
    'Departure',
    'PredictiveIntelligenceSystem',
    'PredictionDomain',
    'PredictionHorizon',
    'Prediction',
    'get_predictive_intelligence',
]
