#!/usr/bin/env python3
"""
Learning Tools for Lyric Tool Registry
Exposes learning capabilities to all agents via tool interface.
"""

from core.tools.tool_registry import Tool, ToolCategory, ToolParameter, ToolResult
from core.tools.capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel
)
from typing import Dict, Any, List, Optional
from dataclasses import asdict
import logging

logger = logging.getLogger(__name__)


class MonitorDataDriftTool(Tool):
    """Monitor data distribution drift"""

    def __init__(self):
        super().__init__()
        self.name = "monitordatadrift"
        self.description = "Detect data drift between production and baseline datasets. Returns drift detection results and statistical summary."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("production_data", "object", "Production dataset as JSON object (e.g., {'metric1': [1,2,3], 'metric2': [4,5,6]})", required=True),
            ToolParameter("baseline_data", "object", "Baseline dataset as JSON object for comparison", required=True),
            ToolParameter("threshold", "number", "Drift detection threshold between 0.0 and 1.0 (default: 0.1)", required=False)
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="monitordatadrift",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.MONITOR_DRIFT,
                    description="Monitor objective drift and data distribution changes",
                    input_types=["datasets"],
                    output_types=["drift_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies in data",
                    input_types=["datasets"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            is_idempotent=True
        )

    async def execute(self, production_data: Dict, baseline_data: Dict, threshold: float = 0.1) -> ToolResult:
        """Execute drift monitoring"""
        try:
            from core.learning.drift_monitoring import run_drift_report, summarize_drift

            report = run_drift_report(
                production_data,
                baseline_data,
                threshold=threshold
            )
            summary = summarize_drift(report)

            drift_status = 'DRIFT DETECTED' if summary.get('drift_detected') else 'No drift'
            return ToolResult(
                success=True,
                output=f"Drift analysis complete - {drift_status}: {summary}"
            )
        except Exception as e:
            logger.error(f"Drift monitoring failed: {e}")
            return ToolResult(
                success=False,
                output=None,
                error=f"Failed to monitor data drift: {str(e)}. Both 'production_data' and 'baseline_data' must be JSON objects with numeric arrays, not strings. Example: {{'metric1': [1,2,3], 'metric2': [4,5,6]}}"
            )




class DetectPatternsTool(Tool):
    """Detect patterns in data using the causal feedback analyzer"""

    def __init__(self):
        super().__init__()
        self.name = "detectpatterns"
        self.description = (
            "Detect behavioral, temporal and anomalous patterns in data. "
            "Returns detected patterns with confidence scores."
        )
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("data", "object", "Data to analyse (dict or list)", required=True),
            ToolParameter("pattern_type", "string", "Pattern type: 'behavioral', 'temporal', 'anomaly'", required=False),
            ToolParameter("min_confidence", "number", "Minimum confidence threshold (0.0-1.0)", required=False),
        ]

        # Capability declarations
        self.capability_profile = ToolCapabilityProfile(
            tool_name="detectpatterns",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies and unusual patterns",
                    input_types=["data"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, data: Dict, pattern_type: str = "behavioral", min_confidence: float = 0.7) -> ToolResult:
        """Detect patterns in data"""
        try:
            from core.learning.causal_feedback_analyzer import get_causal_analyzer

            analyzer = get_causal_analyzer()

            # Convert data to analyzable format
            if isinstance(data, dict):
                data_points = list(data.values()) if data else []
            elif isinstance(data, list):
                data_points = data
            else:
                data_points = [data]

            # Simple pattern detection (can be enhanced with ML models)
            patterns = []

            # Detect repetition patterns
            if len(data_points) > 2:
                for i in range(len(data_points) - 1):
                    for j in range(i + 1, len(data_points)):
                        if data_points[i] == data_points[j]:
                            patterns.append({
                                "type": "repetition",
                                "pattern": data_points[i],
                                "occurrences": data_points.count(data_points[i]),
                                "confidence": 0.9
                            })
                            break

            # Detect trend patterns
            if all(isinstance(x, (int, float)) for x in data_points) and len(data_points) > 3:
                increasing = all(data_points[i] <= data_points[i+1] for i in range(len(data_points)-1))
                decreasing = all(data_points[i] >= data_points[i+1] for i in range(len(data_points)-1))

                if increasing:
                    patterns.append({"type": "trend", "direction": "increasing", "confidence": 0.85})
                elif decreasing:
                    patterns.append({"type": "trend", "direction": "decreasing", "confidence": 0.85})

            # Filter by confidence
            patterns = [p for p in patterns if p.get("confidence", 0) >= min_confidence]

            return ToolResult(
                success=True,
                output={"patterns": patterns, "pattern_type": pattern_type, "count": len(patterns)}
            )
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class VisualizeLearningProgressTool(Tool):
    """Visualize learning progress over time"""

    def __init__(self):
        super().__init__()
        self.name = "visualizelearningprogress"
        self.description = "Visualize learning progress metrics over time. Returns visualization data and insights."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("metrics", "object", "Metrics data over time (e.g., {'accuracy': [0.5, 0.6, 0.7]})", required=True),
            ToolParameter("time_window", "string", "Time window: 'hour', 'day', 'week', 'month' (default: 'day')", required=False)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="visualizelearningprogress",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VISUALIZE_DATA,
                    description="Visualize data and metrics",
                    input_types=["metrics", "time_series"],
                    output_types=["visualization"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.TRACK_PROGRESS,
                    description="Track progress over time",
                    input_types=["metrics"],
                    output_types=["progress_report"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=True,
            is_idempotent=True
        )

    async def execute(self, metrics: Dict, time_window: str = "day") -> ToolResult:
        """Visualize learning progress"""
        try:
            insights = []
            visualization_data = {}

            for metric_name, values in metrics.items():
                if isinstance(values, list) and len(values) > 1:
                    # Calculate trend
                    if all(isinstance(v, (int, float)) for v in values):
                        trend = "improving" if values[-1] > values[0] else "declining"
                        change = ((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0

                        insights.append({
                            "metric": metric_name,
                            "trend": trend,
                            "change_percent": round(change, 2)
                        })

                        visualization_data[metric_name] = {
                            "values": values,
                            "trend": trend,
                            "latest": values[-1]
                        }

            return ToolResult(
                success=True,
                output={
                    "visualization": visualization_data,
                    "insights": insights,
                    "time_window": time_window
                }
            )
        except Exception as e:
            logger.error(f"Visualization failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class IdentifySkillGapsTool(Tool):
    """Identify skill/capability gaps in the system"""

    def __init__(self):
        super().__init__()
        self.name = "identifyskillgaps"
        self.description = "Identify skill and capability gaps compared to requirements or benchmarks. Returns gap analysis."
        self.category = ToolCategory.LEARNING
        self.parameters = [
            ToolParameter("current_capabilities", "object", "Current capability scores (e.g., {'reasoning': 0.7})", required=True),
            ToolParameter("required_capabilities", "object", "Required capability scores (e.g., {'reasoning': 0.9})", required=True)
        ]

        self.capability_profile = ToolCapabilityProfile(
            tool_name="identifyskillgaps",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ASSESS_CAPABILITY,
                    description="Assess current capabilities",
                    input_types=["capability_scores"],
                    output_types=["assessment"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.IDENTIFY_BOTTLENECK,
                    description="Identify capability bottlenecks and gaps",
                    input_types=["current", "required"],
                    output_types=["gap_analysis"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.SELF_DIAGNOSE,
                    description="Diagnose gaps and weaknesses in current capabilities",
                    input_types=["capability_inventory"],
                    output_types=["gap_analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.PRIORITIZE_OBJECTIVES,
                    description="Prioritize learning and improvement objectives",
                    input_types=["objectives", "constraints"],
                    output_types=["prioritized_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, current_capabilities: Dict, required_capabilities: Dict) -> ToolResult:
        """Identify capability gaps"""
        try:
            gaps = []

            for capability, required_score in required_capabilities.items():
                current_score = current_capabilities.get(capability, 0.0)
                gap = required_score - current_score

                if gap > 0:
                    gaps.append({
                        "capability": capability,
                        "current": current_score,
                        "required": required_score,
                        "gap": round(gap, 2),
                        "priority": "high" if gap > 0.3 else "medium" if gap > 0.1 else "low"
                    })

            # Sort by gap size (largest gaps first)
            gaps.sort(key=lambda x: x["gap"], reverse=True)

            return ToolResult(
                success=True,
                output={"gaps": gaps, "total_gaps": len(gaps)}
            )
        except Exception as e:
            logger.error(f"Gap identification failed: {e}")
            return ToolResult(success=False, output=None, error=str(e))


def register_learning_tools():
    """Register all learning tools in the tool registry"""
    from core.tools import get_tool_registry

    registry = get_tool_registry()

    tools = [
        MonitorDataDriftTool(),
        DetectPatternsTool(),
        VisualizeLearningProgressTool(),
        IdentifySkillGapsTool(),
    ]

    for tool in tools:
        registry.register(tool)
        logger.info(f"✅ Registered learning tool: {tool.name}")

    logger.info(f"✅ Registered {len(tools)} learning tools")
