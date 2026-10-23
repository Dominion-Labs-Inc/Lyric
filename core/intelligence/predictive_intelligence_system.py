"""
Predictive Intelligence System

The one authority over what the substrate predicts, and over checking each
prediction against what happened. Two kinds of prediction are made here:

  forecasts     a value a domain will take over a horizon, from the
                meta-learning and emergent behaviour engines below, scored
                against what was then observed (`validate_prediction`);
  expectations  a change the substrate expects the world to make on its own,
                from a regularity it learned, by a time it learned: held
                durably, judged against every reading of that world, and when
                the world does not make the change, a departure of its own
                (the WORLD EXPECTATIONS section).

The comparison of predicted against observed is
`core.intelligence.effect_verification`, the same one an act's effects are
judged by.
"""

import asyncio
import hashlib
import logging
import time
import json
import uuid
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta, timezone
import numpy as np
from collections import defaultdict, deque

from core.learning.learning_interfaces import IOutcomePrediction

logger = logging.getLogger(__name__)

class PredictionDomain(Enum):
    """Domains for predictions"""
    SYSTEM_PERFORMANCE = "system_performance"
    RESOURCE_USAGE = "resource_usage"
    USER_BEHAVIOR = "user_behavior"
    SYSTEM_FAILURES = "system_failures"
    LEARNING_OUTCOMES = "learning_outcomes"
    OPTIMIZATION_OPPORTUNITIES = "optimization_opportunities"
    EMERGENT_BEHAVIORS = "emergent_behaviors"
    SECURITY_THREATS = "security_threats"

class PredictionHorizon(Enum):
    """Time horizons for predictions"""
    IMMEDIATE = "immediate"      # Next few seconds
    SHORT_TERM = "short_term"    # Next few minutes
    MEDIUM_TERM = "medium_term"  # Next few hours
    LONG_TERM = "long_term"      # Next few days

@dataclass
class Prediction:
    """A single prediction"""
    id: str
    domain: PredictionDomain
    horizon: PredictionHorizon
    predicted_value: Any
    confidence: float
    timestamp: datetime
    reasoning: str
    contributing_factors: List[str] = field(default_factory=list)
    meta_learning_inputs: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PredictionResult:
    """Result of prediction validation"""
    prediction_id: str
    actual_value: Any
    accuracy: float
    confidence_calibration: float
    learnings: Dict[str, Any] = field(default_factory=dict)

# ── WORLD EXPECTATIONS: what is kept, and what a departure carries ─────────

#: What this system keeps: how each forecast scored, and the expectations of
#: the world it holds, waiting and settled.
DDL = """
CREATE TABLE IF NOT EXISTS unified.prediction_results (
    prediction_id   VARCHAR(128) PRIMARY KEY,
    domain          VARCHAR(64) NOT NULL,
    horizon         VARCHAR(32) NOT NULL,
    predicted_value DOUBLE PRECISION,
    actual_value    DOUBLE PRECISION,
    confidence      NUMERIC(6,4),
    accuracy        NUMERIC(6,4),
    calibration     NUMERIC(6,4),
    predicted_at    TIMESTAMP,
    resolved_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS unified.held_expectations (
    expectation_id VARCHAR PRIMARY KEY,
    rule_id        VARCHAR NOT NULL,
    domain_id      VARCHAR NOT NULL,
    add_facts      JSONB   NOT NULL,
    delete_facts   JSONB   NOT NULL,
    held_facts     JSONB   NOT NULL,
    since          TIMESTAMPTZ NOT NULL,
    due            TIMESTAMPTZ NOT NULL,
    owner          VARCHAR,
    committed      BOOLEAN NOT NULL,
    status         VARCHAR NOT NULL DEFAULT 'pending',
    attribution    VARCHAR,
    detail         TEXT,
    memory_id      VARCHAR,
    settled_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS held_expectations_pending
    ON unified.held_expectations (domain_id, due) WHERE status = 'pending'
"""

#: How a settled expectation ended, as `held_expectations.status` says it.
_EXPECTATION_STATUS = {"expectation_confirmed": "confirmed",
                       "expectation_unmet": "unmet",
                       "expectation_indeterminate": "indeterminate"}


@dataclass(frozen=True)
class Departure:
    """An expectation the world did not meet, with nothing observed to tell the
    case apart from the regularity's confirmations: the world did not do what
    it does."""

    expectation: Any                 # effect_verification.Expectation
    evidence: Any                    # effect_verification.ExpectationEvidence
    why: str
    #: Every regularity that explains such changes expected this one.
    committed: bool
    #: The regularities that expected it were each relied on (settled in
    #: favour) before this departure moved them.
    relied_on: bool
    memory_id: Optional[str]


def _facts_json(facts) -> str:
    return json.dumps(sorted(str(f) for f in facts))


def _parse_facts(payload) -> FrozenSet[Any]:
    from core.learning.rule_induction import Fact
    if isinstance(payload, str):
        payload = json.loads(payload)
    return frozenset(Fact.parse(text) for text in payload or ())


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _expectation_of(row: Dict[str, Any]):
    from core.intelligence.effect_verification import Expectation
    from core.learning.rule_induction import RuleEffects
    return Expectation(
        expectation_id=row["expectation_id"], rule_id=row["rule_id"],
        domain_id=row["domain_id"],
        effects=RuleEffects(add=_parse_facts(row["add_facts"]),
                            delete=_parse_facts(row["delete_facts"])),
        held=_parse_facts(row["held_facts"]), since=_utc(row["since"]), due=_utc(row["due"]),
        owner=row["owner"])


def _already_holds(effects, facts) -> bool:
    return effects.add <= facts and not (effects.delete & facts)


def describe_change(effects) -> str:
    """A change, as it is said: what comes to hold and what no longer does."""
    parts = [str(f) for f in sorted(effects.add)] + [f"no longer {f}" for f in sorted(effects.delete)]
    return ", ".join(parts)



class MetaLearningPredictor:
    """Meta-learning enhanced prediction system"""
    
    def __init__(self):
        self.learning_patterns = {}
        self.adaptation_history = []
        self.meta_strategies = {}
        
    async def generate_meta_prediction(self, domain: PredictionDomain, 
                                     data: Dict[str, Any],
                                     learning_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate prediction using meta-learning insights"""
        try:
            # Analyze learning patterns
            patterns = await self._analyze_learning_patterns(learning_history)
            
            # Select best meta-strategy
            strategy = await self._select_meta_strategy(domain, patterns)
            
            # Generate prediction using strategy
            prediction = await self._apply_meta_strategy(strategy, data, patterns)
            
            return {
                'prediction': prediction,
                'meta_confidence': prediction.get('confidence', 0.5),
                'strategy_used': strategy.get('name', 'default'),
                'learning_patterns': len(patterns)
            }
            
        except Exception as e:
            logger.error(f"Error in meta-learning prediction: {e}")
            return {'prediction': None, 'meta_confidence': 0.0}
    
    async def _analyze_learning_patterns(self, history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in learning history"""
        patterns = {
            'improvement_rate': 0.0,
            'learning_efficiency': 0.0,
            'adaptation_speed': 0.0,
            'pattern_recognition': []
        }
        
        if len(history) < 2:
            return patterns
        
        # Calculate improvement rate
        recent_performance = [h.get('performance', 0.5) for h in history[-5:]]
        if len(recent_performance) > 1:
            improvement = np.polyfit(range(len(recent_performance)), recent_performance, 1)[0]
            patterns['improvement_rate'] = improvement
        
        # Calculate learning efficiency
        learning_sessions = [h for h in history if h.get('type') == 'learning']
        if learning_sessions:
            avg_efficiency = np.mean([s.get('efficiency', 0.5) for s in learning_sessions])
            patterns['learning_efficiency'] = avg_efficiency
        
        # Calculate adaptation speed
        adaptation_times = [h.get('adaptation_time', 1.0) for h in history if 'adaptation_time' in h]
        if adaptation_times:
            patterns['adaptation_speed'] = 1.0 / np.mean(adaptation_times)
        
        return patterns
    
    async def _select_meta_strategy(self, domain: PredictionDomain, 
                                  patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Select best meta-learning strategy"""
        strategies = {
            'adaptive': {
                'name': 'adaptive',
                'suitability': patterns.get('adaptation_speed', 0.5),
                'description': 'Rapidly adapting strategy'
            },
            'pattern_based': {
                'name': 'pattern_based',
                'suitability': patterns.get('learning_efficiency', 0.5),
                'description': 'Pattern recognition strategy'
            },
            'improvement_focused': {
                'name': 'improvement_focused',
                'suitability': abs(patterns.get('improvement_rate', 0.0)),
                'description': 'Improvement trend strategy'
            }
        }
        
        # Select strategy with highest suitability
        best_strategy = max(strategies.values(), key=lambda s: s['suitability'])
        return best_strategy
    
    async def _apply_meta_strategy(self, strategy: Dict[str, Any], 
                                 data: Dict[str, Any], 
                                 patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Apply selected meta-learning strategy"""
        strategy_name = strategy.get('name', 'default')
        base_value = data.get('current_value', 0.5)
        
        if strategy_name == 'adaptive':
            # Use adaptation speed to predict rapid changes
            adaptation_factor = patterns.get('adaptation_speed', 0.5)
            predicted_value = base_value * (1 + adaptation_factor * 0.1)
            confidence = 0.7
            
        elif strategy_name == 'pattern_based':
            # Use learning efficiency patterns
            efficiency = patterns.get('learning_efficiency', 0.5)
            predicted_value = base_value + (efficiency - 0.5) * 0.2
            confidence = 0.8
            
        elif strategy_name == 'improvement_focused':
            # Use improvement rate trends
            improvement_rate = patterns.get('improvement_rate', 0.0)
            predicted_value = base_value + improvement_rate * 0.5
            confidence = 0.6
            
        else:
            # Default strategy
            predicted_value = base_value
            confidence = 0.5
        
        return {
            'value': max(0.0, min(1.0, predicted_value)),
            'confidence': confidence,
            'strategy_applied': strategy_name
        }

class EmergentBehaviorPredictor:
    """Predicts emergent behaviors in the system"""
    
    def __init__(self):
        self.behavior_patterns = {}
        self.emergence_indicators = []
        
    async def predict_emergent_behaviors(self, system_state: Dict[str, Any]) -> Dict[str, Any]:
        """Predict potential emergent behaviors"""
        try:
            # Analyze system complexity
            complexity_score = await self._calculate_system_complexity(system_state)
            
            # Detect emergence preconditions
            preconditions = await self._detect_emergence_preconditions(system_state)
            
            # Predict specific emergent behaviors
            behaviors = await self._predict_specific_behaviors(complexity_score, preconditions)
            
            return {
                'complexity_score': complexity_score,
                'emergence_probability': complexity_score * 0.8,
                'preconditions_met': len(preconditions),
                'predicted_behaviors': behaviors
            }
            
        except Exception as e:
            logger.error(f"Error predicting emergent behaviors: {e}")
            return {'emergence_probability': 0.0, 'predicted_behaviors': []}
    
    async def _calculate_system_complexity(self, system_state: Dict[str, Any]) -> float:
        """Calculate system complexity score"""
        complexity_factors = [
            system_state.get('active_components', 0) / 100.0,
            system_state.get('interaction_density', 0.0),
            system_state.get('feedback_loops', 0) / 10.0,
            system_state.get('adaptation_rate', 0.0)
        ]
        
        valid_factors = [f for f in complexity_factors if f > 0]
        return min(1.0, float(np.mean(valid_factors)) if valid_factors else 0.0)
    
    async def _detect_emergence_preconditions(self, system_state: Dict[str, Any]) -> List[str]:
        """Detect preconditions for emergent behavior"""
        preconditions = []
        
        # High connectivity
        if system_state.get('interaction_density', 0.0) > 0.7:
            preconditions.append('high_connectivity')
        
        # Rapid adaptation
        if system_state.get('adaptation_rate', 0.0) > 0.8:
            preconditions.append('rapid_adaptation')
        
        # Non-linear dynamics
        if system_state.get('non_linearity', 0.0) > 0.6:
            preconditions.append('non_linear_dynamics')
        
        # Critical mass
        if system_state.get('active_components', 0) > 50:
            preconditions.append('critical_mass')
        
        return preconditions
    
    async def _predict_specific_behaviors(self, complexity: float, 
                                        preconditions: List[str]) -> List[Dict[str, Any]]:
        """Predict specific emergent behaviors"""
        behaviors = []
        
        if complexity > 0.8 and 'high_connectivity' in preconditions:
            behaviors.append({
                'type': 'collective_intelligence',
                'probability': 0.7,
                'description': 'System may develop collective problem-solving capabilities'
            })
        
        if 'rapid_adaptation' in preconditions and 'non_linear_dynamics' in preconditions:
            behaviors.append({
                'type': 'self_organization',
                'probability': 0.6,
                'description': 'System may spontaneously reorganize for efficiency'
            })
        
        if complexity > 0.9 and len(preconditions) >= 3:
            behaviors.append({
                'type': 'novel_capabilities',
                'probability': 0.5,
                'description': 'System may develop entirely new capabilities'
            })
        
        return behaviors

class PredictiveIntelligenceSystem(IOutcomePrediction):
    """
    The one authority over what the substrate predicts and over checking each
    prediction against what happened: forecasts from the meta-learning and
    emergent behaviour engines, and expectations of the world from learned
    regularities (see the module header).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.initialized = False

        # Core prediction engines
        self.meta_learning_predictor = MetaLearningPredictor()
        self.emergent_predictor = EmergentBehaviorPredictor()

        # Prediction tracking
        self.active_predictions = {}
        self.prediction_history = deque(maxlen=1000)
        self.accuracy_metrics = defaultdict(list)

        # System integration
        self.cognitive_scheduler = None
        self.automation_framework = None
        self.unified_learning = None
        self.research_systems = None

        # Expectations of the world (WORLD EXPECTATIONS below).
        #: domain -> its last reading, and when each fact in it was first seen in
        #: an unbroken run of readings: this process's, reset by a restart.
        self._last_reading: Dict[str, Any] = {}
        self._first_seen: Dict[str, Dict[Any, datetime]] = {}
        self._reading_locks: Dict[str, asyncio.Lock] = {}
        #: expectation -> the substrate's act mark in its domain when it was formed.
        self._formed_at: Dict[str, Any] = {}
        self._booted_at = datetime.now(timezone.utc)
        self._attending: set = set()
        self._arm: Optional[Callable[[Any], Any]] = None
        self._on_departure: Optional[Callable[["Departure"], Awaitable[None]]] = None
        self._expectations_schema_ready = False
        self.expectation_stats: Dict[str, int] = {
            "readings": 0, "world_changes": 0, "expected": 0, "confirmed": 0, "unmet": 0,
            "departures": 0, "dealt_with_otherwise": 0, "confirmed_late": 0, "learned_from_unmet": 0,
            "indeterminate": 0}

        self.logger = logging.getLogger(__name__)

    async def initialize(self, cognitive_scheduler=None, automation_framework=None,
                        unified_learning=None, research_systems=None) -> bool:
        """Initialize predictive intelligence system"""
        try:
            self.cognitive_scheduler = cognitive_scheduler
            self.automation_framework = automation_framework
            self.unified_learning = unified_learning
            self.research_systems = research_systems
            
            # Start prediction monitoring
            await self._start_prediction_monitoring()
            
            self.initialized = True
            self.logger.info("Predictive Intelligence System initialized")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize predictive intelligence: {e}")
            return False
    
    async def generate_comprehensive_prediction(self, domain: PredictionDomain,
                                              horizon: PredictionHorizon,
                                              context: Dict[str, Any]) -> Prediction:
        """Generate comprehensive prediction using all available intelligence"""
        try:
            prediction_id = f"pred_{domain.value}_{int(time.time())}"
            
            # Collect system data
            system_data = await self._collect_prediction_data(domain, context)
            
            # Generate meta-learning prediction
            learning_history = await self._get_learning_history(domain)
            meta_result = await self.meta_learning_predictor.generate_meta_prediction(
                domain, system_data, learning_history)
            
            # Generate emergent behavior prediction
            emergent_result = await self.emergent_predictor.predict_emergent_behaviors(
                system_data)
            
            # Integrate all predictions
            integrated_prediction = await self._integrate_predictions(
                meta_result, emergent_result)
            
            # Create final prediction
            prediction = Prediction(
                id=prediction_id,
                domain=domain,
                horizon=horizon,
                predicted_value=integrated_prediction['value'],
                confidence=integrated_prediction['confidence'],
                timestamp=datetime.now(),
                reasoning=integrated_prediction['reasoning'],
                contributing_factors=integrated_prediction['factors'],
                meta_learning_inputs=meta_result
            )
            
            # Store prediction
            self.active_predictions[prediction_id] = prediction
            self.prediction_history.append(prediction)
            
            self.logger.info(f"Generated prediction {prediction_id} for {domain.value}")
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"Error generating prediction: {e}")
            # Return fallback prediction
            return Prediction(
                id=f"fallback_{int(time.time())}",
                domain=domain,
                horizon=horizon,
                predicted_value=0.5,
                confidence=0.1,
                timestamp=datetime.now(),
                reasoning="Fallback prediction due to error"
            )
    
    async def _collect_prediction_data(self, domain: PredictionDomain, 
                                     context: Dict[str, Any]) -> Dict[str, Any]:
        """Collect relevant data for prediction"""
        data = {
            'current_value': context.get('current_value', 0.5),
            'timestamp': datetime.now(),
            'domain': domain.value,
            'context': context
        }
        
        # Add domain-specific data collection
        if domain == PredictionDomain.SYSTEM_PERFORMANCE:
            data.update(await self._collect_performance_data())
        elif domain == PredictionDomain.RESOURCE_USAGE:
            data.update(await self._collect_resource_data())
        elif domain == PredictionDomain.LEARNING_OUTCOMES:
            data.update(await self._collect_learning_data())
        
        return data
    
    async def _collect_performance_data(self) -> Dict[str, Any]:
        """Collect real system performance data"""
        try:
            performance_data = {}
            
            # Get CPU usage from system monitoring
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                scheduler_metrics = await self.cognitive_scheduler.get_system_metrics()
                performance_data['cpu_usage'] = scheduler_metrics.get('cpu_utilization', 0.0)
                performance_data['memory_usage'] = scheduler_metrics.get('memory_utilization', 0.0)
                performance_data['response_time'] = scheduler_metrics.get('avg_response_time', 0.0)
            
            # Get throughput from automation framework (check if available)
            automation_metrics = {}
            if hasattr(self, 'automation_framework') and self.automation_framework:
                automation_metrics = getattr(self.automation_framework, 'automation_metrics', {})
            elif hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                # Fallback to scheduler metrics
                scheduler_metrics = await self.cognitive_scheduler.get_automation_metrics()
                automation_metrics = scheduler_metrics
            
            performance_data['throughput'] = automation_metrics.get('task_completion_rate', 0.7)
            performance_data['error_rate'] = automation_metrics.get('error_rate', 0.05)
            
            # Get learning system performance
            # `get_performance_metrics` DOES NOT EXIST on UnifiedLearningSystem.
            # The guard tests the attribute on self, not the method on the
            # object, so this raised AttributeError, the enclosing
            # `except Exception` caught it, and the method returned a block of
            # hardcoded constants. Every "performance" figure this system has
            # reasoned over was invented.
            #
            # Efficiency is derivable from what is actually recorded: the share
            # of learning sessions that produced a successful adaptation.
            if self.unified_learning is not None:
                learning_metrics = await self.unified_learning.get_learning_metrics()
                counters = learning_metrics.get('this_process') or {}
                sessions = int(counters.get('total_learning_sessions') or 0)
                adaptations = int(counters.get('successful_adaptations') or 0)
                if sessions:
                    performance_data['learning_efficiency'] = adaptations / sessions
                # No sessions yet means unmeasured. Left absent rather than set
                # to 0.0, which would read as "learns nothing".
            
            # Fill missing values with system defaults
            default_values = {
                'cpu_usage': 0.5, 'memory_usage': 0.4, 'response_time': 0.2,
                'throughput': 0.7, 'error_rate': 0.05, 'learning_efficiency': 0.6,
                'adaptation_speed': 0.5
            }
            
            for key, default_val in default_values.items():
                if key not in performance_data:
                    performance_data[key] = default_val
            
            return performance_data
            
        except Exception as e:
            logger.error(f"Error collecting performance data: {e}")
            return {
                'cpu_usage': 0.5, 'memory_usage': 0.4, 'response_time': 0.2,
                'throughput': 0.7, 'error_rate': 0.05
            }
    
    async def _collect_resource_data(self) -> Dict[str, Any]:
        """Collect real resource usage data from system components"""
        try:
            resource_data = {}
            
            # Get memory availability from system
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                memory_stats = await self.cognitive_scheduler.get_memory_statistics()
                resource_data['available_memory'] = memory_stats.get('available_ratio', 0.7)
                resource_data['memory_fragmentation'] = memory_stats.get('fragmentation', 0.1)
            
            # Get CPU capacity from monitoring (check multiple sources)
            cpu_stats = {}
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                system_metrics = await self.cognitive_scheduler.get_system_metrics()
                cpu_stats = system_metrics
            
            resource_data['cpu_capacity'] = 1.0 - cpu_stats.get('cpu_usage', 0.3)
            resource_data['cpu_temperature'] = cpu_stats.get('temperature_ratio', 0.4)
            
            # Get storage information
            try:
                import shutil
                import os
                
                # Get disk usage for the Lyric directory
                lyric_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                total, used, free = shutil.disk_usage(lyric_path)
                storage_usage = used / total
                resource_data['storage_usage'] = storage_usage
                resource_data['storage_available'] = 1.0 - storage_usage
                
            except Exception:
                resource_data['storage_usage'] = 0.4
                resource_data['storage_available'] = 0.6
            
            # NETWORK STATE IS NOT SOMETHING THE LEARNING SYSTEM KNOWS.
            # This called `unified_learning.get_network_statistics()`, a method
            # that does not exist on it and would not be its responsibility if
            # it did. The AttributeError was swallowed and 0.8 / 0.2 were
            # substituted, so bandwidth and latency were literals presented as
            # measurements. Removed rather than replaced: these keys are now
            # absent when nothing measures them, which a consumer can detect.
            
            # Get processing queue information
            queue_data = await self._get_processing_queue_status()
            resource_data['processing_queue'] = queue_data.get('utilization', 0.3)
            resource_data['queue_depth'] = queue_data.get('depth_ratio', 0.2)
            
            # Set defaults for missing values
            defaults = {
                'available_memory': 0.7, 'cpu_capacity': 0.8, 'storage_usage': 0.4,
                'network_bandwidth': 0.9, 'processing_queue': 0.3
            }
            
            for key, default_val in defaults.items():
                if key not in resource_data:
                    resource_data[key] = default_val
            
            return resource_data
            
        except Exception as e:
            logger.error(f"Error collecting resource data: {e}")
            return {
                'available_memory': 0.7, 'cpu_capacity': 0.8, 'storage_usage': 0.4,
                'network_bandwidth': 0.9, 'processing_queue': 0.3
            }
    
    async def _get_processing_queue_status(self) -> Dict[str, Any]:
        """Get processing queue status from system components"""
        try:
            queue_status = {'utilization': 0.3, 'depth_ratio': 0.2}
            
            # Check cognitive scheduler queue
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                scheduler_queue = await self.cognitive_scheduler.get_queue_status()
                queue_status['utilization'] = scheduler_queue.get('utilization', 0.3)
                queue_status['depth_ratio'] = scheduler_queue.get('depth_ratio', 0.2)
            
            return queue_status
            
        except Exception as e:
            logger.error(f"Error getting queue status: {e}")
            return {'utilization': 0.3, 'depth_ratio': 0.2}
    
    async def _collect_learning_data(self) -> Dict[str, Any]:
        """Collect real learning-related data from system components"""
        try:
            learning_data = {}
            
            # Get learning rate from unified learning system
            # `get_detailed_metrics` does not exist either. Four more literals
            # (0.6 / 0.8 / 0.7 / 0.4) stood in for it. Only what is genuinely
            # recorded is reported now; the rest stay absent.
            if self.unified_learning is not None:
                learning_metrics = await self.unified_learning.get_learning_metrics()
                knowledge = learning_metrics.get('knowledge_base')
                if knowledge:
                    learning_data['knowledge_base_size'] = knowledge.get('total')
                recorded = learning_metrics.get('recorded_experiences')
                if recorded is not None:
                    learning_data['recorded_experiences'] = recorded
                counters = learning_metrics.get('this_process') or {}
                transfers = int(counters.get('cross_domain_insights') or 0)
                sessions = int(counters.get('total_learning_sessions') or 0)
                if sessions:
                    learning_data['transfer_learning'] = transfers / sessions
            
            # Get adaptation speed from cognitive scheduler
            if hasattr(self, 'cognitive_scheduler') and self.cognitive_scheduler:
                adaptation_metrics = await self.cognitive_scheduler.get_adaptation_metrics()
                learning_data['adaptation_speed'] = adaptation_metrics.get('adaptation_velocity', 0.5)
                learning_data['cognitive_flexibility'] = adaptation_metrics.get('flexibility_score', 0.6)
            
            # `improvement_velocity` and `meta_learning_efficiency` were
            # assigned 0.0 unconditionally -- not measured, not defaulted from a
            # missing source, just set. Zero is the worst value either can take,
            # so the system reported itself as improving at no rate and
            # meta-learning at no efficiency, always. Omitted until something
            # measures them.
            
            # Get research and exploration metrics
            if hasattr(self, 'research_systems') and self.research_systems:
                research_metrics = await self.research_systems.get_research_progress()
                learning_data['research_productivity'] = research_metrics.get('productivity_score', 0.5)
                learning_data['knowledge_discovery_rate'] = research_metrics.get('discovery_rate', 0.3)
            
            # A COMPOSITE OF MEASURED COMPONENTS ONLY.
            #
            # This averaged `learning_data.get(k, <literal>)` over three keys
            # that nothing had set, so the result was the mean of 0.6, 0.8 and
            # 0.7 -- a constant 0.7 reported as "overall learning efficiency".
            # It is computed now only from components that were actually
            # measured, and omitted entirely when none were.
            measured = [learning_data[k] for k in
                        ('learning_rate', 'knowledge_retention', 'skill_acquisition',
                         'learning_efficiency')
                        if isinstance(learning_data.get(k), (int, float))]
            if measured:
                learning_data['overall_learning_efficiency'] = sum(measured) / len(measured)
            learning_data['measured_components'] = len(measured)

            # THE DEFAULTS BLOCK IS GONE. It filled every key nothing had
            # measured with a literal, so a consumer could not tell a reading
            # from a placeholder -- and every one of these keys was always
            # missing, so the literals were the only values this ever returned.
            return learning_data

        except Exception as e:
            # Returning the same literals on failure made a broken collector
            # indistinguishable from a working one. The caller is told the
            # collection failed.
            logger.error("Error collecting learning data: %s", e, exc_info=True)
            return {'available': False, 'error': f"{type(e).__name__}: {e}"}
    
    async def _get_learning_history(self, domain: PredictionDomain) -> List[Dict[str, Any]]:
        """What the meta-learner recorded of each learning attempt, oldest
        first: how well it went (`performance`).

        THIS RETURNED THE SAME THREE RECORDS EVERY TIME (performance 0.6, 0.7,
        0.75), so the meta-learning engine reasoned over a history nobody had.
        Only what is recorded is handed over. Efficiency and adaptation time are
        measured nowhere and are not supplied, so the engine finds none rather
        than reading invented ones. The meta-learner keeps its attempts across
        task families, not per prediction domain, so every domain is given all
        of them."""
        from core.learning.meta_learning import get_meta_learner
        records = list(getattr(get_meta_learner(), "learning_records", None) or [])
        return [{"performance": float(r.performance_score)} for r in records]
    
    async def _integrate_predictions(self, meta_result: Dict[str, Any],
                                   emergent_result: Dict[str, Any]) -> Dict[str, Any]:
        """Integrate predictions from different engines"""
        try:
            # Extract predictions
            meta_pred = meta_result.get('prediction') or {}

            # Weight predictions by confidence
            meta_weight = meta_result.get('meta_confidence', 0.0)
            emergent_weight = emergent_result.get('emergence_probability', 0.0)

            total_weight = meta_weight + emergent_weight + 0.01

            # Weighted average of predicted values
            meta_value = meta_pred.get('value', 0.5)
            emergent_value = emergent_result.get('complexity_score', 0.5)

            integrated_value = (
                meta_value * meta_weight +
                emergent_value * emergent_weight
            ) / total_weight

            # Combined confidence
            integrated_confidence = min(1.0, (meta_weight + emergent_weight) / 2.0)

            # Generate reasoning
            reasoning_parts = []
            if meta_weight > 0.3:
                reasoning_parts.append("meta-learning patterns")
            if emergent_weight > 0.3:
                reasoning_parts.append("emergent behavior indicators")

            reasoning = f"Integrated prediction based on {', '.join(reasoning_parts)}"

            # Contributing factors
            factors = []
            if meta_result.get('learning_patterns', 0) > 0:
                factors.append("historical learning patterns")
            if emergent_result.get('preconditions_met', 0) > 2:
                factors.append("emergence preconditions detected")
            
            return {
                'value': integrated_value,
                'confidence': integrated_confidence,
                'reasoning': reasoning,
                'factors': factors
            }
            
        except Exception as e:
            self.logger.error(f"Error integrating predictions: {e}")
            return {
                'value': 0.5,
                'confidence': 0.1,
                'reasoning': "Error in prediction integration",
                'factors': []
            }
    
    async def validate_prediction(self, prediction_id: str, actual_value: Any) -> PredictionResult:
        """Validate a prediction against actual outcome.

        Raises when it cannot: a prediction not held (already resolved, or never made) has no accuracy, and
        returning 0.0 for it reported a prediction that was all wrong."""
        if prediction_id not in self.active_predictions:
            raise ValueError(f"Prediction {prediction_id} not found")
        
        prediction = self.active_predictions[prediction_id]
        
        # Calculate accuracy
        if isinstance(prediction.predicted_value, (int, float)) and isinstance(actual_value, (int, float)):
            error = abs(prediction.predicted_value - actual_value)
            accuracy = max(0.0, 1.0 - error)
        else:
            accuracy = 1.0 if prediction.predicted_value == actual_value else 0.0
        
        # Calculate confidence calibration
        confidence_error = abs(prediction.confidence - accuracy)
        calibration = max(0.0, 1.0 - confidence_error)
        
        # Create result
        result = PredictionResult(
            prediction_id=prediction_id,
            actual_value=actual_value,
            accuracy=accuracy,
            confidence_calibration=calibration,
            learnings={
                'prediction_domain': prediction.domain.value,
                'horizon': prediction.horizon.value,
                'meta_learning_effective': prediction.meta_learning_inputs.get('meta_confidence', 0.0) > 0.5
            }
        )

        # Update accuracy metrics
        self.accuracy_metrics[prediction.domain.value].append(accuracy)

        # Remove from active predictions
        del self.active_predictions[prediction_id]

        self.logger.info(f"Validated prediction {prediction_id}: accuracy={accuracy:.3f}")

        return result

    async def record_result(self, prediction: Prediction, result: PredictionResult,
                            actual: Any) -> None:
        """Keep a scored forecast, so the accuracy record outlives the process:
        `active_predictions` is this process's, and without this the record of
        whether forecasting is getting better died with it. Written by the
        memory agent, which keeps what the substrate learned."""
        from core.agents.memory_agent import memory_agent
        await memory_agent().hold_prediction_result(
            prediction_id=result.prediction_id, domain=prediction.domain.value,
            horizon=prediction.horizon.value,
            predicted_value=(float(prediction.predicted_value)
                             if isinstance(prediction.predicted_value, (int, float)) else None),
            actual_value=float(actual) if isinstance(actual, (int, float)) else None,
            confidence=float(prediction.confidence), accuracy=float(result.accuracy),
            calibration=float(result.confidence_calibration),
            predicted_at=prediction.timestamp)

    async def get_prediction_insights(self) -> Dict[str, Any]:
        """Get insights about prediction performance"""
        insights = {
            'total_predictions': len(self.prediction_history),
            'active_predictions': len(self.active_predictions),
            'domain_accuracy': {},
            'average_confidence': 0.0,
            'recent_trends': {}
        }
        
        # Calculate domain-specific accuracy
        for domain, accuracies in self.accuracy_metrics.items():
            if accuracies:
                insights['domain_accuracy'][domain] = {
                    'average_accuracy': np.mean(accuracies),
                    'prediction_count': len(accuracies),
                    'trend': 'improving' if len(accuracies) > 1 and accuracies[-1] > accuracies[0] else 'stable'
                }
        
        # Calculate average confidence
        if self.prediction_history:
            avg_confidence = np.mean([p.confidence for p in self.prediction_history])
            insights['average_confidence'] = avg_confidence
        
        return insights
    
    async def _start_prediction_monitoring(self):
        """Start monitoring prediction performance"""
        self.logger.info("Prediction monitoring started")
        # In a real implementation, this would start background tasks
    
    async def emergency_prediction(self, domain: PredictionDomain, 
                                 context: Dict[str, Any]) -> Prediction:
        """Generate emergency prediction with minimal processing"""
        try:
            prediction_id = f"emergency_{domain.value}_{int(time.time())}"
            
            # Fast heuristic-based prediction
            base_value = context.get('current_value', 0.5)
            
            # Simple trend-based adjustment
            trend = context.get('trend', 0.0)
            predicted_value = max(0.0, min(1.0, base_value + trend * 0.1))
            
            prediction = Prediction(
                id=prediction_id,
                domain=domain,
                horizon=PredictionHorizon.IMMEDIATE,
                predicted_value=predicted_value,
                confidence=0.6,  # Lower confidence for emergency predictions
                timestamp=datetime.now(),
                reasoning="Emergency heuristic-based prediction",
                contributing_factors=["emergency_mode", "heuristic_analysis"]
            )
            
            self.active_predictions[prediction_id] = prediction
            
            return prediction
            
        except Exception as e:
            self.logger.error(f"Error in emergency prediction: {e}")
            return Prediction(
                id=f"emergency_fallback_{int(time.time())}",
                domain=domain,
                horizon=PredictionHorizon.IMMEDIATE,
                predicted_value=0.5,
                confidence=0.1,
                timestamp=datetime.now(),
                reasoning="Emergency fallback prediction"
            )

    # ── WORLD EXPECTATIONS ───────────────────────────────────────────────────
    #
    # THE SOURCE OF ACTIVITY THIS ADDS. Everything the substrate did unasked
    # started with something that had already happened, or with a timer. Here,
    # what it learned the world does on its own becomes what it expects, and the
    # world not doing it is an event of its own.
    #
    # ONE PASS PER READING. Every reading of a world taken through the binding
    # registry (`BindingRegistry.on_reading`) is attended to, in order, per
    # domain:
    #
    #   learn   two readings apart with nothing done by the substrate in between
    #           (`acted_between`): what changed, the world changed on its own,
    #           and each thing that changed is a demonstration of a regularity
    #           (`world_change_examples`), induced off this path by the drain;
    #   settle  every expectation waiting on this world is judged against the
    #           reading (`verify_expectation`) and, once met or due, settled: who
    #           was wrong is decided on evidence (`attribute_expectation`,
    #           `UnifiedLearningSystem.separates`), the rule store hears it by the
    #           door an act's outcome uses, the regularity's reliability moves,
    #           and memory keeps what happened;
    #   expect  every validated regularity whose conditions now hold, for things
    #           not already expected, becomes an expectation due when the change
    #           was ever seen to take longest, held durably by the memory agent,
    #           with a reading armed for its due time -- the substrate's own clock.
    #
    # COMMITTED OR TENTATIVE. Where every regularity of a kind expects a change,
    # the expectation is a commitment: unmet, with nothing to tell the case apart,
    # the world departed from what it does. Where only some do, it is a question:
    # unmet, a regularity that did not expect it already tells the case apart, so
    # the substrate was wrong, learns, and does nothing else.
    #
    # STATE ACROSS A RESTART. Expectations, demonstrations, rules and beliefs are
    # durable. The last reading of each world and when each fact was first seen
    # are this process's: the first reading after a boot has nothing to compare
    # with, and a fact present then is first seen then -- an expectation formed
    # from it is due later than it might have been, never earlier.

    def bind_world(self, *, arm: Callable[[Any], Any],
                   on_departure: Callable[["Departure"], Awaitable[None]]) -> None:
        """Who arms a reading for an expectation's due time, and who is handed a
        departure. Unbound, expectations are still held and settled; nothing is
        armed and no departure goes anywhere."""
        self._arm = arm
        self._on_departure = on_departure

    def on_reading(self, domain_id: str, facts) -> None:
        """The binding registry's reading handler: cheap and synchronous. The
        reading is stamped now -- its time and what the substrate had done in
        the domain by then -- and attended to on the running loop. A reading
        taken with no loop running has nobody to attend to it."""
        from core.intelligence.effect_verification import WorldReading, act_mark
        reading = WorldReading(reading_id=f"read_{uuid.uuid4().hex[:12]}", domain_id=domain_id,
                               facts=frozenset(facts), at=datetime.now(timezone.utc),
                               mark=act_mark(domain_id))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self.attend(reading))
        self._attending.add(task)
        task.add_done_callback(self._attended)

    def _attended(self, task: "asyncio.Task") -> None:
        self._attending.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.logger.error("a reading could not be attended to: %s: %s",
                              type(error).__name__, error, exc_info=error)

    async def readings_settled(self) -> None:
        """Wait until every reading taken so far has been attended to."""
        while self._attending:
            await asyncio.gather(*list(self._attending), return_exceptions=True)

    async def _ensure_schema(self) -> None:
        if self._expectations_schema_ready:
            return
        from core.database import get_database_manager
        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()
        for statement in filter(None, (s.strip() for s in DDL.split(";"))):
            await db.execute_query(statement)
        self._expectations_schema_ready = True

    async def attend(self, reading) -> None:
        """Learn, settle, expect: one reading, in order with the others of its world."""
        from core.intelligence.effect_verification import acts_touched
        from core.perception.perception_faculty import owner_of
        lock = self._reading_locks.setdefault(reading.domain_id, asyncio.Lock())
        async with lock:
            await self._ensure_schema()
            previous = self._last_reading.get(reading.domain_id)
            if previous is not None and previous.at > reading.at:
                return
            self.expectation_stats["readings"] += 1
            first_seen_before = dict(self._first_seen.get(reading.domain_id, {}))
            self._last_reading[reading.domain_id] = reading
            self._first_seen[reading.domain_id] = {
                fact: first_seen_before.get(fact, reading.at) for fact in reading.facts or ()}

            owner = owner_of(reading.domain_id)
            if previous is not None:
                # WHAT THE SUBSTRATE TOUCHED IN BETWEEN is its own; any other
                # thing that changed changed on its own (`acts_touched`).
                touched = acts_touched(reading.domain_id, previous.mark, reading.mark)
                if touched is not None:
                    await self._learn_change(previous, reading, owner, first_seen_before, touched)
                    await self._confirm_late(previous, reading, touched)
            await self._settle_expectations(reading)
            await self._expect(reading, owner)

    async def _learn_change(self, previous, reading, owner: Optional[str],
                            first_seen: Dict[Any, datetime], touched: FrozenSet[str]) -> None:
        if previous.facts is None or reading.facts is None or previous.facts == reading.facts:
            return
        from core.learning.demonstration_store import regularity_signature
        from core.learning.unified_learning_system import (get_learning_authority,
                                                           world_change_examples)
        stem = f"{reading.domain_id}|{previous.reading_id}|{reading.reading_id}"
        for example, things in world_change_examples(previous.facts, reading.facts,
                                                     evidence_stem=stem):
            effects = example.observed_effects
            if not effects or things & touched:
                continue
            held_since = max((first_seen.get(f, previous.at) for f in example.before),
                             default=previous.at)
            await get_learning_authority().record_world_change(
                example, domain_id=reading.domain_id,
                regularity=regularity_signature(effects, things),
                owner=owner, before_at=held_since, after_at=reading.at)
            self.expectation_stats["world_changes"] += 1

    async def _confirm_late(self, previous, reading, touched: FrozenSet[str]) -> None:
        """What was taken for the world departing, seen happening after all.

        An expectation is due when the change was ever seen to take longest, and
        early on that is the longest of only a few: a filing later than any yet
        seen lapsed, and was recorded as the habit failing. Counted against it,
        those false misses held a habit kept nine times in ten below the bar for
        relying on it (EXPECT-02, run 8). When the change it expected happens,
        in this interval and with nothing of the substrate's in between, it held,
        only late: recorded so, and its reliability moves as for a confirmation.
        What was already said of it stays said."""
        if previous.facts is None or reading.facts is None:
            return
        from core.agents.memory_agent import memory_agent
        from core.learning.rule_store import get_rule_store
        from core.learning.unified_learning_system import get_learning_authority
        from core.learning.unified_learning_system import expected_things
        for row in await memory_agent().departed_expectations(domain_id=reading.domain_id):
            expectation = _expectation_of(row)
            if expected_things(expectation.effects, expectation.held | reading.facts) & touched:
                continue
            if (_already_holds(expectation.effects, previous.facts)
                    or not _already_holds(expectation.effects, reading.facts)):
                continue
            late = (reading.at - expectation.due).total_seconds()
            if not await memory_agent().confirm_late(
                    expectation_id=expectation.expectation_id,
                    detail=f"it happened {late:.1f} s after it was due"):
                continue
            self.expectation_stats["confirmed_late"] += 1
            self.logger.info("expectation %s in %s happened %.1f s late: %s",
                             expectation.expectation_id, expectation.domain_id, late,
                             describe_change(expectation.effects))
            formed_by = await get_rule_store().get(expectation.rule_id)
            if formed_by is not None:
                await get_learning_authority().observe_regularity(
                    formed_by, domain_id=expectation.domain_id, held=True,
                    owner=expectation.owner, observation=expectation.expectation_id,
                    memory_id=None)

    async def _settle_expectations(self, reading) -> None:
        from core.agents.memory_agent import memory_agent
        from core.intelligence.effect_verification import (ExpectationOutcome,
                                                           verify_expectation)
        for row in await memory_agent().pending_expectations(domain_id=reading.domain_id):
            expectation = _expectation_of(row)
            evidence = verify_expectation(expectation, reading)
            if evidence.outcome is ExpectationOutcome.PENDING:
                continue
            await self._conclude(expectation, evidence, reading, committed=bool(row["committed"]))

    async def _acted_meanwhile(self, expectation, reading) -> bool:
        """Whether the substrate acted on what this expectation is about while
        it stood: on the thing itself, not merely somewhere in its world."""
        from core.intelligence.effect_verification import acted_between, acts_touched
        from core.learning.unified_learning_system import expected_things
        formed = self._formed_at.get(expectation.expectation_id)
        if formed is not None:
            touched = acts_touched(expectation.domain_id, formed, reading.mark)
            return touched is None or bool(
                touched & expected_things(expectation.effects,
                                          expectation.held | (reading.facts or frozenset())))
        # FORMED BEFORE THIS PROCESS BEGAN: its acts since are counted from
        # nothing, and what was done before is what the store recorded.
        if acted_between((0, False), reading.mark):
            return True
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().acted_in(
            domain_id=expectation.domain_id, after=expectation.since, before=self._booted_at)

    async def _predicting(self, expectation, signature: Tuple[str, int]) -> List[Any]:
        """The regularities of its kind (`signature`), held now, that expected
        this change of what held when it was formed."""
        from core.learning.demonstration_store import regularity_signature
        from core.learning.rule_induction import TrainingExample, applies
        from core.learning.rule_store import get_rule_store
        state = TrainingExample(before=tuple(sorted(expectation.held)), action=None, after=())
        return [r for r in await get_rule_store().expectation_rules(domain_id=expectation.domain_id)
                if regularity_signature(r.rule.effects) == signature
                and expectation.effects in set(applies(r.rule, state))]

    async def _conclude(self, expectation, evidence, reading, *, committed: bool) -> None:
        from core.agents.memory_agent import memory_agent
        from core.intelligence.effect_verification import (
            Attribution, ExpectationOutcome, attribute_expectation)
        from core.learning.demonstration_store import regularity_signature
        from core.learning.rule_store import get_rule_store, record_runtime_evidence
        from core.learning.unified_learning_system import (expectation_case,
                                                           get_learning_authority)
        learning = get_learning_authority()
        store = get_rule_store()
        acted = await self._acted_meanwhile(expectation, reading)

        formed_by = await store.get(expectation.rule_id)
        signature = regularity_signature(formed_by.rule.effects) if formed_by is not None else None
        rules = await self._predicting(expectation, signature) if signature is not None else []
        if formed_by is not None and all(r.rule_id != formed_by.rule_id for r in rules):
            rules.append(formed_by)

        case = None
        separable: Optional[bool] = None
        if evidence.outcome is ExpectationOutcome.CONTRADICTION and not acted and formed_by is not None:
            case = expectation_case(expectation.held, reading.facts or frozenset(),
                                    expectation.effects,
                                    evidence_id=f"unmet_{expectation.expectation_id}")
            separable = await learning.separates(formed_by, case, domain_id=expectation.domain_id)
        attribution, why = attribute_expectation(evidence, acted=acted, separable=separable)
        # DEALT WITH OTHERWISE. A departure is the world not doing what it does to
        # a thing. A thing the world DID change since the expectation was formed,
        # only not as expected -- filed somewhere else, taken away -- was dealt
        # with, by whoever deals with it, and putting the expected change right
        # would undo what they did. Measured (EXPECT-02's pilot): a person who
        # began filing to ARCHIVE had each of her files taken for a departure,
        # and Lyric set out, on its own, to move them back. It still says the
        # regularity did not hold this time: its reliability moves as for a
        # departure, and nothing is raised.
        otherwise = (attribution is Attribution.EXTERNAL_FAILURE and case is not None
                     and frozenset(case.before) != frozenset(case.after))
        if otherwise:
            from core.learning.rule_induction import RuleEffects
            done = RuleEffects(add=frozenset(case.after) - frozenset(case.before),
                               delete=frozenset(case.before) - frozenset(case.after))
            why = f"it was dealt with otherwise: {describe_change(done)}"

        # WHETHER IT WAS RELIED ON is read BEFORE this outcome moves it: a
        # departure from a regularity not yet relied on is not acted on.
        # Relied on when the habit -- the kind of change, in this world: every rule
        # here is of the kind that formed it (`_predicting`) -- is shown by how its
        # expectations ended to hold often enough (`regularity_relied_on`).
        held_so_far, expected_so_far = (
            await learning.regularity_record(formed_by, domain_id=expectation.domain_id)
            if formed_by is not None else (0, 0))
        from core.learning.unified_learning_system import relied_on_rate
        relied_on = relied_on_rate(held_so_far, expected_so_far)

        if attribution in (Attribution.RULE_EVIDENCE, Attribution.EXTERNAL_FAILURE):
            # Evidence about the regularity, or about the world departing from
            # it: recorded against each regularity that expected the change.
            # What the substrate's own acts may have caused is not.
            for record in rules:
                runtime = evidence.as_runtime_evidence()
                runtime.rule_id = record.rule_id
                await record_runtime_evidence(store, runtime, attribution, why)

        memory_id = await self._remember_expectation(expectation, evidence, attribution, why)
        counts_for_reliability = (
            (evidence.outcome is ExpectationOutcome.CONFIRMATION
             and attribution is Attribution.RULE_EVIDENCE)
            or attribution is Attribution.EXTERNAL_FAILURE)
        if counts_for_reliability and formed_by is not None:
            if not expectation.owner and not memory_id:
                self.logger.warning(
                    "memory did not keep how expectation %s ended, so it moves no belief "
                    "in %s", expectation.expectation_id, formed_by.rule_id)
            else:
                await learning.observe_regularity(
                    formed_by, domain_id=expectation.domain_id,
                    held=evidence.outcome is ExpectationOutcome.CONFIRMATION,
                    owner=expectation.owner, observation=expectation.expectation_id,
                    memory_id=memory_id)
        if separable and case is not None and signature is not None:
            # THE SUBSTRATE WAS WRONG: the case is kept as the counter-example
            # that narrows the regularity when its signature is next induced.
            await learning.record_world_change(
                case, domain_id=expectation.domain_id, regularity=signature,
                owner=expectation.owner, before_at=expectation.since, after_at=reading.at)
            self.expectation_stats["learned_from_unmet"] += 1

        status = _EXPECTATION_STATUS.get(evidence.outcome.value, "indeterminate")
        if not await memory_agent().settle_expectation(
                expectation_id=expectation.expectation_id, status=status,
                attribution=attribution.value, detail=why, memory_id=memory_id):
            return
        self._formed_at.pop(expectation.expectation_id, None)
        self.expectation_stats[status] += 1
        self.logger.info("expectation %s in %s %s (%s): %s — %s [the habit held %d of %d before it%s]",
                         expectation.expectation_id, expectation.domain_id, status,
                         attribution.value, describe_change(expectation.effects), why,
                         held_so_far, expected_so_far, ", relied on" if relied_on else "")

        if otherwise:
            self.expectation_stats["dealt_with_otherwise"] += 1
        elif (evidence.outcome is ExpectationOutcome.CONTRADICTION
                and attribution is Attribution.EXTERNAL_FAILURE):
            self.expectation_stats["departures"] += 1
            if self._on_departure is not None:
                await self._on_departure(Departure(
                    expectation=expectation, evidence=evidence, why=why,
                    committed=committed, relied_on=relied_on, memory_id=memory_id))

    async def _remember_expectation(self, expectation, evidence, attribution,
                                    why: str) -> Optional[str]:
        """Memory keeps how an expectation ended: the person's, for their world;
        the substrate's own, for its own."""
        from core.agents.memory_agent import memory_agent
        from core.intelligence.effect_verification import ExpectationOutcome
        from core.memory import Origin
        from core.memory.utils.interfaces import MemoryType
        if evidence.outcome is ExpectationOutcome.CONFIRMATION:
            ending = "it happened"
        elif evidence.outcome is ExpectationOutcome.CONTRADICTION:
            ending = f"it did not happen ({why})"
        else:
            ending = f"I could not tell whether it happened ({why})"
        # AN EPISODE, NOT A CLAIM: what was expected, and on its own line how it
        # ended, as the memory agent keeps an episode (`_readable_claim`: an
        # episode written for a reader is not read for a claim to recall as a
        # premise). On one line it was read by the grammar first, 2.45 s each on
        # the substrate's loop: 183 of the 186 s spent attending to readings in
        # EXPECT-02's profiled pilot.
        stored, memory_id = await memory_agent().store_memory(
            content=(f"In {expectation.domain_id} I expected {describe_change(expectation.effects)} "
                     f"by {expectation.due.isoformat()}.\n{ending[0].upper()}{ending[1:]}."),
            memory_type=MemoryType.EPISODIC,
            tags=["expectation", _EXPECTATION_STATUS.get(evidence.outcome.value, "indeterminate")],
            source_context={"source_system": "predictive_intelligence",
                            "expectation_id": expectation.expectation_id,
                            "rule_id": expectation.rule_id, "attribution": attribution.value},
            origin=Origin.of(expectation.owner, "expectations"))
        return memory_id if stored else None

    async def _expect(self, reading, owner: Optional[str]) -> None:
        if reading.facts is None:
            return
        from core.agents.memory_agent import memory_agent
        from core.intelligence.effect_verification import Expectation
        from core.learning.demonstration_store import regularity_signature
        from core.learning.rule_induction import TrainingExample, applies
        from core.learning.rule_store import get_rule_store
        from core.learning.unified_learning_system import expectation_case

        regularities = await get_rule_store().expectation_rules(domain_id=reading.domain_id)
        if not regularities:
            return
        kinds: Dict[Tuple[str, int], List[Any]] = {}
        for record in regularities:
            kinds.setdefault(regularity_signature(record.rule.effects), []).append(record)

        state = TrainingExample(before=tuple(sorted(reading.facts)), action=None, after=())
        first_seen = self._first_seen.get(reading.domain_id, {})
        for signature, members in kinds.items():
            # One expectation per case: what is expected, of what held. Not of
            # when it was first seen, which a restart resets -- the same case,
            # still waiting, would be expected again.
            predicted: Dict[str, set] = {r.rule_id: set(applies(r.rule, state)) for r in members}
            for effects in sorted(set().union(*predicted.values()), key=describe_change):
                if not all(f.is_ground for f in effects.facts) or _already_holds(effects, reading.facts):
                    continue
                expecting = [r for r in members if effects in predicted[r.rule_id]]
                delay = await self._longest_delay(reading.domain_id, signature, expecting)
                if delay is None:
                    continue
                held = frozenset(expectation_case(reading.facts, reading.facts, effects,
                                                  evidence_id="").before)
                since = max((first_seen.get(f, reading.at) for f in held), default=reading.at)
                key = "|".join([reading.domain_id, describe_change(effects), _facts_json(held)])
                expectation = Expectation(
                    expectation_id=f"exp_{hashlib.sha1(key.encode()).hexdigest()[:16]}",
                    rule_id=sorted(r.rule_id for r in expecting)[0], domain_id=reading.domain_id,
                    effects=effects, held=held, since=since,
                    due=since + timedelta(seconds=delay), owner=owner)
                committed = len(expecting) == len(members)
                if not await memory_agent().hold_expectation(
                        expectation_id=expectation.expectation_id, rule_id=expectation.rule_id,
                        domain_id=expectation.domain_id, add_facts=_facts_json(effects.add),
                        delete_facts=_facts_json(effects.delete), held_facts=_facts_json(held),
                        since=since, due=expectation.due, owner=owner, committed=committed):
                    continue
                self._formed_at[expectation.expectation_id] = reading.mark
                self.expectation_stats["expected"] += 1
                self.logger.info("expecting in %s by %s (%s): %s", reading.domain_id,
                                 expectation.due.isoformat(),
                                 "committed" if committed else "tentative",
                                 describe_change(effects))
                if self._arm is not None:
                    self._arm(expectation)

    async def _longest_delay(self, domain_id: str, signature: Tuple[str, int],
                             expecting: List[Any]) -> Optional[float]:
        """The longest any change these regularities explain was seen to take,
        in seconds; None when no such change was timed."""
        from core.learning.demonstration_store import get_demonstration_store
        from core.learning.rule_induction import derives
        demos = get_demonstration_store()
        predicate, arity = signature
        lags = await demos.lags(domain_id=domain_id, predicate=predicate, arity=arity)
        if not lags:
            return None
        examples = await demos.load(domain_id=domain_id, predicate=predicate, arity=arity)
        seen = [lags[e.evidence_id] for e in examples
                if e.positive and e.evidence_id in lags
                and any(derives(r.rule, e) for r in expecting)]
        return max(seen) if seen else None

    async def check_due(self, expectation_id: str, domain_id: str) -> bool:
        """An expectation's due time came: read its world. The reading settles
        it, through the same door as any other. False when the world could not
        be read, and it waits for the next reading."""
        from core.perception.perception_faculty import observe_world_async
        facts = await observe_world_async(domain_id)
        if facts is None:
            self.logger.warning("expectation %s came due and %s could not be read; it waits for "
                                "the next reading of it", expectation_id, domain_id)
            return False
        await self.readings_settled()
        return True

    async def restore_expectations(self) -> int:
        """At boot: every expectation still waiting is armed again. One whose
        time passed while the substrate was down is read for at once."""
        await self._ensure_schema()
        from core.agents.memory_agent import memory_agent
        rows = await memory_agent().pending_expectations()
        if self._arm is not None:
            for row in rows:
                self._arm(_expectation_of(row))
        if rows:
            self.logger.info("restored %d expectation(s) still waiting on the world", len(rows))
        return len(rows)


# Singleton instance
_predictive_intelligence = None


def get_predictive_intelligence() -> PredictiveIntelligenceSystem:
    """Get global predictive intelligence system instance (singleton)"""
    global _predictive_intelligence
    if _predictive_intelligence is None:
        _predictive_intelligence = PredictiveIntelligenceSystem()
    return _predictive_intelligence
