"""
Governance Module

Governance trigger engine for autonomous AI safety (owned by runtime governance).

Main Components:
- GovernanceTriggerEngine: Evaluates actions across 8 action categories
- ContextClassifier: Non-destructive context labeling for governance quality

Usage:
    from core.governance import GovernanceTriggerEngine, ActionCategory

    trigger_system = GovernanceTriggerEngine()

    evaluation = await trigger_system.evaluate_action(
        action_category=ActionCategory.TOOL_EXECUTION,
        action_type="execute_tool",
        parameters={"tool_name": "ChaosTestingTool", "target": "production"}
    )

    if evaluation.triggered:
        decision = await trigger_system.trigger_governance_session(
            action_category=ActionCategory.TOOL_EXECUTION,
            action_type="execute_tool",
            parameters=parameters,
            evaluation_result=evaluation,
            context=context
        )
"""

# The governance trigger ENGINE (per-invocation risk-tier evaluation). Runtime
# governance owns the evaluation authority (RuntimeGovernance.evaluate_action);
# the engine + its types live here. (Was the UnifiedGovernanceTriggerSystem,
# now renamed; the "unified governance" system is gone.)
from core.governance.governance_triggers import (
    GovernanceTriggerEngine,
    get_governance_trigger_engine,
    ActionCategory,
    EnforcementMode,
    IrreversibilityClass,
    DecisionTier,
    GovernanceTriggerEvaluation,
)

from core.governance.context_classifier import (
    ContextClassifier,
    ContextLabel,
    ClassifiedContext,
    verify_no_data_loss
)

__all__ = [
    # Governance trigger engine + types (evaluation authority = RuntimeGovernance)
    "GovernanceTriggerEngine",
    "get_governance_trigger_engine",
    "ActionCategory",
    "EnforcementMode",
    "IrreversibilityClass",
    "DecisionTier",
    "GovernanceTriggerEvaluation",

    # Context Classifier
    "ContextClassifier",
    "ContextLabel",
    "ClassifiedContext",
    "verify_no_data_loss",
]
