"""
Autonomous control interfaces for decision-making and planning
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set, Union
from dataclasses import dataclass
from enum import Enum


class AutonomyLevel(Enum):
    """Levels of autonomous operation"""
    REACTIVE = "reactive"
    DELIBERATIVE = "deliberative" 
    ADAPTIVE = "adaptive"
    CREATIVE = "creative"


class DecisionType(Enum):
    """Types of decisions"""
    OPERATIONAL = "operational"
    STRATEGIC = "strategic"
    EMERGENCY = "emergency"
    MAINTENANCE = "maintenance"


@dataclass
class Decision:
    """Decision data structure"""
    decision_id: str
    decision_type: DecisionType
    context: Dict[str, Any]
    options: List[Dict[str, Any]]
    selected_option: Optional[Dict[str, Any]] = None
    confidence: float = 0.0
    timestamp: float = 0.0


class IDecisionEngine(ABC):
    """Interface for decision-making"""
    
    @abstractmethod
    async def analyze_situation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze current situation for decision-making"""
        pass
    
    @abstractmethod
    async def generate_options(self, situation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate possible decision options"""
        pass
    
    @abstractmethod
    async def evaluate_options(self, options: List[Dict[str, Any]], criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Evaluate decision options against criteria"""
        pass
    
    @abstractmethod
    async def make_decision(self, options: List[Dict[str, Any]]) -> Decision:
        """Make the final decision"""
        pass


class IAutonomousController(ABC):
    """Main autonomous controller interface"""
    
    @abstractmethod
    async def initialize(self, autonomy_level: AutonomyLevel = AutonomyLevel.ADAPTIVE) -> bool:
        """Initialize the autonomous controller"""
        pass
    
    @abstractmethod
    async def set_autonomy_level(self, level: AutonomyLevel) -> bool:
        """Set the autonomy level"""
        pass
    
    @abstractmethod
    async def get_autonomy_level(self) -> AutonomyLevel:
        """Get current autonomy level"""
        pass
    
    @abstractmethod
    async def process_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process input and generate autonomous response"""
        pass
    
    @abstractmethod
    async def execute_autonomous_cycle(self) -> Dict[str, Any]:
        """Execute one autonomous decision-action cycle"""
        pass
    
    @abstractmethod
    async def get_system_status(self) -> Dict[str, Any]:
        """Get autonomous system status"""
        pass
    
    @abstractmethod
    async def handle_emergency(self, emergency_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle emergency situations"""
        pass
    
    @abstractmethod
    async def learn_from_experience(self, experience: Dict[str, Any]) -> bool:
        """Learn from autonomous experiences"""
        pass