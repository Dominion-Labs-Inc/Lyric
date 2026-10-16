#!/usr/bin/env python3
"""
Lyric Monitoring Module

Drift monitoring lives in core/learning/drift_monitoring/; its names are
re-exported here for older imports. A failure to import them is a real defect
and raises, rather than leaving the names bound to None.

core/monitoring/agents/ does not exist; no monitoring agents are offered.
"""

from core.learning.drift_monitoring import (
    Schema, load_csv, run_drift_report, summarize_drift,
    evaluate_thresholds, write_alert, retrain_model,
    AutonomousMonitoringSystem, create_autonomous_monitoring_system
)

__all__ = [
    # DEPRECATED - Use core.learning.drift_monitoring instead
    'Schema',
    'load_csv',
    'run_drift_report',
    'summarize_drift',
    'evaluate_thresholds',
    'write_alert',
    'retrain_model',
    'AutonomousMonitoringSystem',
    'create_autonomous_monitoring_system',
]
