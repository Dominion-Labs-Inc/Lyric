#!/usr/bin/env python3
"""
Lyric Autonomous Agents Module
Modular autonomous system with separated concerns for perception, planning, execution, and learning.
"""

# Import modular autonomous system components
from .shared_types import (
    SystemMode, TaskType, TaskStatus, Priority,
    Task, Goal, Plan, PerceptionData, SystemState, LearningData
)

from .autonomous_coordinator import (
    AutonomousCoordinator, create_autonomous_system, get_autonomous_coordinator)

# The cloud-storage and maintenance modules this package once offered
# (cloud_storage_integration, maintenance_core, maintenance_manager) do not exist
# in this tree; their names were bound to None behind import guards and nothing
# read them. They are not offered.
__all__ = [
    "AutonomousCoordinator",
    "create_autonomous_system",
    "get_autonomous_coordinator",
]
