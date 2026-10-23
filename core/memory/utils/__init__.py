"""
Memory Utilities
===============
Embedding service and interfaces.
"""

from .embedding_service import get_embedding_service
from .interfaces import (
    # Enums
    MemoryType,
    MemoryPriority,
    MemoryStatus,
    MemoryOperation,
    AutobiographicalActionType,
    AutobiographicalImportance,

    # Dataclasses
    MemoryEntry,
    ContextData,
    MemoryItem,
    MemoryQuery,
    MemorySearchResult,
    CognitiveExperience,

    # Interfaces
    IMemoryStore,
    IContextManager,
    IMemorySystem,
)

__all__ = [
    # Services
    'get_embedding_service',

    # Enums
    'MemoryType',
    'MemoryPriority',
    'MemoryStatus',
    'MemoryOperation',
    'AutobiographicalActionType',
    'AutobiographicalImportance',

    # Dataclasses
    'MemoryEntry',
    'ContextData',
    'MemoryItem',
    'MemoryQuery',
    'MemorySearchResult',
    'CognitiveExperience',

    # Interfaces
    'IMemoryStore',
    'IContextManager',
    'IMemorySystem',
]
