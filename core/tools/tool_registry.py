#!/usr/bin/env python3
"""
Tool Registry System
===================
Central registry for all tools available to the Singleton.

Provides:
- Tool registration and discovery
- Parameter validation
- Safety checks
- Usage tracking
- Constitutional oversight
- Constitution integration

Author: Lyric AI Team
"""

from core.capability import raise_if_structural
import asyncio
import json
import logging
import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

# Chaos engineering decorators
from core.chaos.decorators import inject_latency, inject_error


# ── Tool failures ─────────────────────────────────────────────────────────────
# A failed call carries the tool's OWN account of what went wrong, unchanged.
# What to do about it is the substrate's to work out from what happened.
#
# This used to classify every error message against ~1,000 lines of regex
# "recovery recipes" written as prompts for a language model ("try each in
# order: run_command(...)"), append the recipe to the error itself, and decide
# from the matched wording whether a failure was "retryable". No model reads
# prompts any more, so the recipes did one thing: every record the substrate
# kept of a failed act carried instructions it never learned, one of them to
# hunt for a GitHub token in env files and the Keychain.

#: The failure history the health monitor counts, declared where it is written
#: so a fresh store has it. `error_category` holds HOW the failure showed (see
#: `_record_tool_failure`). A store created before this still has the recipe
#: columns `retryable` (NOT NULL) and `short_hint`; they are dropped by hand, not
#: from here, because a schema change to the main store needs the owner's word.
#: Until then that store refuses these inserts, and the refusal is logged loudly.
_TOOL_ERROR_EVENTS_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS unified.tool_error_events (
           id             BIGSERIAL PRIMARY KEY,
           task_id        TEXT,
           session_id     VARCHAR,
           user_id        VARCHAR,
           tool_name      VARCHAR NOT NULL,
           error_category VARCHAR NOT NULL,
           message        TEXT,
           created_at     TIMESTAMP DEFAULT NOW())""",
]


async def _record_tool_failure(
    tool_name: str,
    message: str,
    *,
    raised: bool,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Persist one failed call. Fire-and-forget via asyncio.create_task().

    How a failure showed is read from its structure, not guessed from its
    wording. A tool that REPORTED failure ran and said the world refused: the
    file was not there, the place was taken. The tool worked, and teaching
    produces such refusals on purpose. A tool that RAISED broke, and only that
    is a component failing, so only that reaches the canonical failure record
    the recovery manager and the recurring-failure check watch. (The recipe
    classifier sent "file not found" there as a terminal failure, so every
    refused demonstration read as the tool breaking.)
    """
    try:
        from core.database import get_database_manager
        db = get_database_manager()
        if db is None or not getattr(db, 'initialized', False):
            return
        await db.ensure_schema("tool_error_events", _TOOL_ERROR_EVENTS_SCHEMA)
        await db.execute_query(
            """
            INSERT INTO unified.tool_error_events
                (task_id, session_id, user_id, tool_name, error_category,
                 message, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """,
            (task_id, session_id, user_id, tool_name,
             "raised" if raised else "reported", (message or "")[:2000]),
        )
    except Exception as _pe:
        logger.warning(f"[tool_error_persist] failure of {tool_name} not recorded: {_pe}")

    if not raised:
        return
    try:
        from core.observability import failure_record

        await failure_record.report(
            component=f"tools.{tool_name}",
            failure_type="tool_error",
            description=(message or "tool execution failed")[:2000],
            source_system="tool_registry",
            severity="medium",
            metadata={"task_id": task_id, "session_id": session_id},
        )
    except Exception as _fe:
        logger.debug(f"[tool_error_persist] canonical record failed: {_fe}")


# Capability-based discovery system (NEW)
from core.tools.capabilities import (
    Capability,
    CapabilityMetadata,
    ToolCapabilityProfile,
    RiskLevel,
    infer_capability_from_task
)


logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Tool categories"""
    FILESYSTEM = "filesystem"
    EXECUTION = "execution"
    SEARCH = "search"
    MACOS = "macos"
    NETWORK = "network"
    DATABASE = "database"
    SYSTEM = "system"
    COMMUNICATION = "communication"
    MONITORING = "monitoring"
    AI_ML = "ai_ml"
    DATA_PROCESSING = "data_processing"
    CODE_GENERATION = "code_generation"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    REASONING = "reasoning"
    # 12 learning tools were registering category="learning" as a raw
    # string because this member did not exist, so ToolCategory stopped
    # being the single authority for categories and get_usage_stats()
    # crashed on `tool.category.value` for every one of them.
    LEARNING = "learning"


class ToolSafety(Enum):
    """Safety levels for tools - for monitoring/logging purposes only"""
    SAFE = "safe"  # Read-only, no side effects
    MODERATE = "moderate"  # Can modify files
    DANGEROUS = "dangerous"  # Can execute code
    CRITICAL = "critical"  # System-level changes
    HIGH_RISK = "high_risk"  # Repository-wide or highly destructive operations

    # NOTE: No approval gates - Singleton has full autonomy
    # Constitutional monitoring watches for drift, doesn't block actions


@dataclass
class ToolParameter:
    """Tool parameter specification"""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    pattern: Optional[str] = None  # Regex for validation


@dataclass
class ToolResult:
    """Result from tool execution"""
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    tool_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    requires_approval: bool = False
    approval_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    """
    Base class for all tools.

    Tools provide specific capabilities to the Singleton:
    - Reading/writing files
    - Executing code
    - Searching codebase
    - System operations
    - macOS integrations

    All tools are:
    1. Validated before execution
    2. Logged for constitutional oversight
    3. Subject to safety constraints
    4. Tracked for learning
    5. Declared by capabilities they provide (for semantic discovery)
    """

    def __init__(self):
        # Only set defaults if not already defined as class attributes
        if not hasattr(self, 'name'):
            self.name: str = self.__class__.__name__.replace('Tool', '').lower()
        if not hasattr(self, 'description'):
            self.description: str = ""
        if not hasattr(self, 'category'):
            self.category: ToolCategory = ToolCategory.SYSTEM
        if not hasattr(self, 'safety_level'):
            self.safety_level: ToolSafety = ToolSafety.SAFE
        if not hasattr(self, 'parameters'):
            self.parameters: List[ToolParameter] = []


        self.usage_count: int = 0
        self.last_used: Optional[datetime] = None

        # Capability-based discovery (NEW)
        # Tools declare what they CAN do, not just what they ARE
        if not hasattr(self, 'capability_profile'):
            self.capability_profile: Optional['ToolCapabilityProfile'] = None

        # Every call to a tool is judged by the Constitution at execute_tool.
        
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given parameters.
        
        Args:
            **kwargs: Tool-specific parameters
            
        Returns:
            ToolResult with success status and output
        """
        pass
    
    def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate parameters before execution.

        Supports both List[ToolParameter] and raw JSON Schema dict formats.

        Returns:
            (is_valid, error_message)
        """
        # ── Dict-format (JSON Schema) parameters ─────────────────────────────
        # Some tools (e.g. chaos tools) declare parameters as a raw JSON Schema
        # dict {"type": "object", "properties": {...}, "required": [...]}
        # rather than a List[ToolParameter]. Handle that format here.
        if isinstance(self.parameters, dict):
            props = self.parameters.get("properties", {})
            required_names: List[str] = self.parameters.get("required", [])
            valid_names_dict = set(props.keys())

            unknown = [k for k in params if k not in valid_names_dict]
            if unknown:
                schema_summary = ", ".join(
                    f"{k} ({'required' if k in required_names else 'optional'}, type={props[k].get('type','?')})"
                    for k in props
                ) or "(no parameters)"
                return False, (
                    f"Unknown parameter(s): {unknown}. "
                    f"Valid parameters for '{self.name}': [{schema_summary}]. "
                    f"Fix the parameter name(s) and retry."
                )

            for req in required_names:
                if req not in params:
                    schema_summary = ", ".join(
                        f"{k} ({'required' if k in required_names else 'optional'}, type={props[k].get('type','?')})"
                        for k in props
                    ) or "(no parameters)"
                    return False, (
                        f"Missing required parameter: '{req}'. "
                        f"Full schema for '{self.name}': [{schema_summary}]."
                    )

            # Basic type validation against the JSON Schema properties
            for pname, value in params.items():
                pdef = props.get(pname, {})
                ptype = pdef.get("type")
                if ptype == "string" and not isinstance(value, str):
                    return False, f"Parameter '{pname}' must be a string, got {type(value).__name__}"
                elif ptype in ("number", "integer") and not isinstance(value, (int, float)):
                    return False, f"Parameter '{pname}' must be a number, got {type(value).__name__}"
                elif ptype == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter '{pname}' must be a boolean, got {type(value).__name__}"
                elif ptype == "array" and not isinstance(value, list):
                    return False, f"Parameter '{pname}' must be an array, got {type(value).__name__}"
                elif ptype == "object" and not isinstance(value, dict):
                    return False, f"Parameter '{pname}' must be an object, got {type(value).__name__}"
                # Enum validation
                if "enum" in pdef and value not in pdef["enum"]:
                    return False, f"Parameter '{pname}' must be one of: {pdef['enum']}"
                # Range validation
                if "minimum" in pdef and isinstance(value, (int, float)):
                    if value < pdef["minimum"]:
                        return False, f"Parameter '{pname}' must be >= {pdef['minimum']}"
                if "maximum" in pdef and isinstance(value, (int, float)):
                    if value > pdef["maximum"]:
                        return False, f"Parameter '{pname}' must be <= {pdef['maximum']}"

            return True, None

        # ── Unknown-parameter guard (List[ToolParameter] format) ──────────────
        # Catch typos/wrong names early and emit the full schema so the model
        # can correct on the very next call without hunting for the schema.
        valid_names = {p.name for p in self.parameters}
        unknown = [k for k in params if k not in valid_names]
        if unknown:
            schema_summary = ", ".join(
                f"{p.name} ({'required' if p.required else f'optional, default={p.default}'}: {p.type})"
                for p in self.parameters
            ) or "(no parameters)"
            return False, (
                f"Unknown parameter(s): {unknown}. "
                f"Valid parameters for '{self.name}': [{schema_summary}]. "
                f"Fix the parameter name(s) and retry."
            )

        for param in self.parameters:
            if param.required and param.name not in params:
                schema_summary = ", ".join(
                    f"{p.name} ({'required' if p.required else f'optional, default={p.default}'}: {p.type})"
                    for p in self.parameters
                ) or "(no parameters)"
                return False, (
                    f"Missing required parameter: '{param.name}'. "
                    f"Full schema for '{self.name}': [{schema_summary}]."
                )
            
            if param.name in params:
                value = params[param.name]
                
                # Type validation with actionable error messages
                if param.type == "string" and not isinstance(value, str):
                    return False, f"Parameter {param.name} must be a string, got {type(value).__name__}"
                elif param.type == "number" and not isinstance(value, (int, float)):
                    return False, f"Parameter {param.name} must be a number, got {type(value).__name__}"
                elif param.type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter {param.name} must be a boolean, got {type(value).__name__}"
                elif param.type == "array" and not isinstance(value, list):
                    # Provide helpful guidance for common mistakes
                    if isinstance(value, str):
                        return False, (
                            f"Parameter {param.name} must be an array, got string. "
                            f"Use run_code tool to parse data into an array first, "
                            f"e.g., [1.5, 2.3, 3.1] not \"[1.5, 2.3, 3.1]\""
                        )
                    return False, f"Parameter {param.name} must be an array, got {type(value).__name__}"
                elif param.type == "object" and not isinstance(value, dict):
                    return False, f"Parameter {param.name} must be an object, got {type(value).__name__}"
                
                # Enum validation
                if param.enum and value not in param.enum:
                    return False, f"Parameter {param.name} must be one of: {param.enum}"
                
                # Range validation
                if param.min_value is not None and isinstance(value, (int, float)):
                    if value < param.min_value:
                        return False, f"Parameter {param.name} must be >= {param.min_value}"
                if param.max_value is not None and isinstance(value, (int, float)):
                    if value > param.max_value:
                        return False, f"Parameter {param.name} must be <= {param.max_value}"
        
        return True, None
    
    def to_json_schema(self) -> Dict[str, Any]:
        """
        Convert tool to JSON schema for LLM function calling.

        Returns schema compatible with OpenAI/Anthropic function calling format.
        Supports both List[ToolParameter] and raw JSON Schema dict formats.
        """
        # Some tools (e.g. chaos tools) define parameters as a raw JSON Schema dict
        if isinstance(self.parameters, dict):
            return {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }

        properties = {}
        required = []

        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            
            if param.enum:
                prop["enum"] = param.enum
            if param.min_value is not None:
                prop["minimum"] = param.min_value
            if param.max_value is not None:
                prop["maximum"] = param.max_value
            if param.pattern:
                prop["pattern"] = param.pattern
            if param.default is not None:
                prop["default"] = param.default
            
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    
    def to_openai_schema(self) -> Dict[str, Any]:
        """
        Convert tool to an OpenAI-compatible function schema for native tool calling.

        This is the format expected by create_chat_completion(tools=[...]):
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { "type": "object", "properties": {...}, "required": [...] }
            }
        }

        Supports both List[ToolParameter] and raw JSON Schema dict parameter formats.
        """
        # Some tools define parameters as a raw JSON Schema dict already
        if isinstance(self.parameters, dict):
            params_schema = self.parameters
        else:
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for param in self.parameters:
                prop: Dict[str, Any] = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.enum:
                    prop["enum"] = param.enum
                if param.min_value is not None:
                    prop["minimum"] = param.min_value
                if param.max_value is not None:
                    prop["maximum"] = param.max_value
                if param.pattern:
                    prop["pattern"] = param.pattern
                if param.default is not None:
                    prop["default"] = param.default
                # Arrays need an items type; default to string if unspecified
                if param.type == "array" and "items" not in prop:
                    prop["items"] = {"type": "string"}

                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            params_schema = {
                "type": "object",
                "properties": properties,
                "required": required,
            }

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params_schema,
            },
        }

    async def _track_usage(self):
        """Track tool usage for learning"""
        self.usage_count += 1
        self.last_used = datetime.now()

    # ========== CAPABILITY-BASED METHODS (NEW) ==========

    def provides_capability(self, capability: Capability) -> bool:
        """Check if this tool provides a specific capability"""
        if not self.capability_profile:
            return False
        return self.capability_profile.provides_capability(capability)

    def get_capabilities(self) -> Set[Capability]:
        """Get set of all capabilities this tool provides"""
        if not self.capability_profile:
            return set()
        return self.capability_profile.get_capability_names()

    def matches_context(self, capability: Capability, context: Dict[str, Any]) -> bool:
        """
        Check if this tool's capability implementation matches the given context.

        Example:
            ReadFileTool.matches_context(
                Capability.READ_DATA,
                {"data_source": "file", "file_path": "/var/log/system.log"}
            ) → True
        """
        if not self.capability_profile:
            return False
        return self.capability_profile.matches_context(capability, context)


class ToolRegistry:
    """
    Central registry for all available tools with lazy loading and capability-based discovery.

    Responsibilities:
    - Register tool factories (lazy loading - tools loaded on first use)
    - Capability-based discovery (find tools by what they CAN do)
    - Validate tool calls
    - Execute tools safely
    - Track usage
    - Constitutional oversight

    Architecture:
    - Tools are registered as factories (Callable that returns Tool instance)
    - Only loaded when first accessed (solves slow startup problem)
    - Capability index maps capabilities → tool names for fast lookup
    - Context-aware selection picks best tool for specific use case
    """

    def __init__(self):
        # Legacy: Eagerly loaded tools (backwards compatibility)
        self.tools: Dict[str, Tool] = {}

        # NEW: Lazy loading system
        self.tool_factories: Dict[str, Callable[[], Tool]] = {}  # tool_name → factory
        self.loaded_tools: Dict[str, Tool] = {}                   # tool_name → loaded instance

        # NEW: Capability-based discovery
        self.capability_index: Dict[Capability, List[str]] = {}   # capability → [tool_names]

        # NEW: Category index for lazy tools (register_factory populates this)
        self.category_index: Dict[str, List[str]] = {}            # category_str → [tool_names]

        # Tracking and monitoring
        self.usage_log: List[Dict[str, Any]] = []


    def register(self, tool: Tool):
        """
        Register a tool (backwards compatibility - eager loading).

        For new code, prefer register_factory() for lazy loading.
        """
        self.tools[tool.name] = tool

        # Also register in lazy loading system for consistency
        self.loaded_tools[tool.name] = tool

        # Build capability index if tool has capability profile
        if hasattr(tool, 'capability_profile') and tool.capability_profile:
            for capability in tool.capability_profile.get_capability_names():
                if capability not in self.capability_index:
                    self.capability_index[capability] = []
                if tool.name not in self.capability_index[capability]:
                    self.capability_index[capability].append(tool.name)

        # Handle both enum and string values for category and safety_level
        if hasattr(tool, 'category') and tool.category:
            category_str = tool.category.value if hasattr(tool.category, 'value') else str(tool.category)
        else:
            category_str = "unknown"

        if hasattr(tool, 'safety_level') and tool.safety_level:
            safety_str = tool.safety_level.value if hasattr(tool.safety_level, 'value') else str(tool.safety_level)
        else:
            safety_str = "unknown"

        logger.info(f"🔧 Registered tool: {tool.name} ({category_str}, {safety_str})")

    def register_factory(
        self,
        tool_name: str,
        factory: Callable[[], Tool],
        capabilities: Optional[List[Capability]] = None,
        category: Optional[ToolCategory] = None,
        safety_level: Optional[ToolSafety] = None
    ):
        """
        Register a tool factory for lazy loading (NEW - preferred method).

        Tools are not instantiated until first use, solving slow startup problem.

        Args:
            tool_name: Unique name for the tool
            factory: Callable that returns Tool instance when called
            capabilities: List of capabilities this tool provides
            category: Tool category (for metadata)
            safety_level: Safety level (for metadata)

        Example:
            registry.register_factory(
                "read_file",
                lambda: ReadFileTool(),
                capabilities=[Capability.READ_DATA],
                category=ToolCategory.FILESYSTEM,
                safety_level=ToolSafety.SAFE
            )
        """
        self.tool_factories[tool_name] = factory

        # Build capability index
        if capabilities:
            for capability in capabilities:
                if capability not in self.capability_index:
                    self.capability_index[capability] = []
                if tool_name not in self.capability_index[capability]:
                    self.capability_index[capability].append(tool_name)

        # Build category index (was previously discarded — caused 0-tools bug)
        if category:
            cat_str = category.value if hasattr(category, 'value') else str(category)
            if cat_str not in self.category_index:
                self.category_index[cat_str] = []
            if tool_name not in self.category_index[cat_str]:
                self.category_index[cat_str].append(tool_name)

        logger.debug(f"📦 Registered factory: {tool_name} (lazy load)")

    @inject_latency("tool_registry", "get_tool", delay_ms=50, jitter_ms=20)
    def get_tool(self, name: str) -> Optional[Tool]:
        """
        Get tool by name with lazy loading support.

        Checks:
        1. Already loaded tools (loaded_tools cache)
        2. Legacy eagerly loaded tools (tools dict)
        3. Tool factories (lazy load on first access)

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        # Check if already loaded (lazy system)
        if name in self.loaded_tools:
            return self.loaded_tools[name]

        # Check legacy eager-loaded tools
        if name in self.tools:
            tool = self.tools[name]
            # Cache in loaded_tools for consistency
            self.loaded_tools[name] = tool
            return tool

        # Lazy load from factory
        if name in self.tool_factories:
            logger.debug(f"⚡ Lazy loading tool: {name}")
            tool = self.tool_factories[name]()
            self.loaded_tools[name] = tool

            # Build capability index from loaded tool
            if hasattr(tool, 'capability_profile') and tool.capability_profile:
                for capability in tool.capability_profile.get_capability_names():
                    if capability not in self.capability_index:
                        self.capability_index[capability] = []
                    if name not in self.capability_index[capability]:
                        self.capability_index[capability].append(name)

            return tool

        return None
    
    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all tools, optionally filtered by category.

        NOTE: This only returns eagerly-loaded tools (backwards compatibility).
        For capability-based discovery, prefer find_providers() which supports lazy loading.
        """
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())

    def get_tools_by_category(self, category_str: str) -> List[Tool]:
        """
        Get tools by category string, with lazy loading support.

        Unlike list_tools(), this uses the category_index populated by
        register_factory() and lazy-loads tools on first access.

        Args:
            category_str: Category name (e.g. 'filesystem', 'execution', 'system')

        Returns:
            List of Tool instances in that category
        """
        tool_names = self.category_index.get(category_str, [])
        tools = []
        for name in tool_names:
            tool = self.get_tool(name)  # Handles lazy loading
            if tool:
                tools.append(tool)
        return tools

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Get OpenAI-compatible JSON schemas for ALL registered tools (for LLM function calling).

        Returns {"type":"function","function":{...}} format for both eagerly-loaded
        tools (self.tools) and lazy-loaded tools (self.tool_factories).
        """
        schemas: List[Dict[str, Any]] = []

        # Eager tools — already loaded
        for tool in self.tools.values():
            try:
                schemas.append(tool.to_openai_schema())
            except Exception as e:
                logger.warning("get_tools_schema: to_openai_schema() failed for %s: %s", tool.name, e)

        # Lazy tools — load on demand (skip any already included above)
        for name in self.tool_factories:
            if name in self.tools:
                continue
            tool = self.get_tool(name)
            if tool is None:
                continue
            try:
                schemas.append(tool.to_openai_schema())
            except Exception as e:
                logger.warning("get_tools_schema: to_openai_schema() failed for lazy %s: %s", name, e)

        return schemas

    # ========== CAPABILITY-BASED DISCOVERY (NEW - PREFERRED) ==========

    def find_providers(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None,
        load_tools: bool = True
    ) -> List[Tool]:
        """
        Find all tools that provide a specific capability (PREFERRED over list_tools).

        Uses lazy loading - only loads tools that match the requested capability.

        Args:
            capability: The capability to search for
            context: Optional context for filtering (e.g., {"data_source": "file"})
            load_tools: Whether to lazy-load tools (default True)

        Returns:
            List of Tool instances providing this capability

        Example:
            # Find all tools that can read data
            providers = registry.find_providers(Capability.READ_DATA)

            # Find tools that can read data from files specifically
            providers = registry.find_providers(
                Capability.READ_DATA,
                context={"data_source": "file"}
            )
        """
        tool_names = self.capability_index.get(capability, [])

        if not load_tools:
            # Return tool names without loading
            return tool_names

        providers = []
        for tool_name in tool_names:
            tool = self.get_tool(tool_name)
            if not tool:
                continue

            # If context provided, check if tool matches
            if context:
                if tool.matches_context(capability, context):
                    providers.append(tool)
            else:
                providers.append(tool)

        return providers

    def select_best_provider(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None,
        weights: Optional[Dict[str, float]] = None,
        prefer_low_latency: bool = False,
        prefer_low_cost: bool = False
    ) -> Optional[Tool]:
        """
        Select the best tool for a specific capability given context.

        Uses weighted scoring to pick the most appropriate provider:
        1. Context matching (does tool handle this specific use case?)
        2. Weighted scoring based on priority, reliability, latency, cost
        3. Resource constraints (network, filesystem, database)
        4. Execution characteristics (batch, streaming, idempotent)

        Args:
            capability: The capability needed
            context: Context for selection (e.g., file path, URL, etc.)
            weights: Optional scoring weights (priority, reliability, latency, cost)
            prefer_low_latency: Prioritize fast tools (adjusts weights)
            prefer_low_cost: Prioritize low-cost tools (adjusts weights)

        Returns:
            Best Tool instance or None if no providers

        Example:
            # System picks ReadFileTool over FetchURLTool for file paths
            tool = registry.select_best_provider(
                Capability.READ_DATA,
                context={"data_source": "file", "path": "/var/log/system.log"}
            )

            # Custom weights for optimization
            tool = registry.select_best_provider(
                Capability.READ_DATA,
                context=context,
                weights={"priority": 2.0, "reliability": 1.0, "latency": -0.5, "cost": -0.1}
            )
        """
        providers = self.find_providers(capability, context=context)

        if not providers:
            return None

        if len(providers) == 1:
            return providers[0]

        # Build weights based on preferences
        scoring_weights = weights.copy() if weights else {}

        if prefer_low_latency:
            scoring_weights["latency"] = scoring_weights.get("latency", -0.3) * 2.0

        if prefer_low_cost:
            scoring_weights["cost"] = scoring_weights.get("cost", -0.2) * 2.0

        # Score each provider using capability profile scoring
        scored_providers = []
        for tool in providers:
            if tool.capability_profile:
                score = tool.capability_profile.score_for_context(
                    capability,
                    context or {},
                    weights=scoring_weights if scoring_weights else None
                )
            else:
                # Fallback for tools without capability profiles
                score = 0.0

            scored_providers.append((score, tool))

        # Return highest scoring provider (excluding -inf scores)
        scored_providers = [(s, t) for s, t in scored_providers if s != float('-inf')]
        if not scored_providers:
            return None

        scored_providers.sort(key=lambda x: x[0], reverse=True)
        return scored_providers[0][1]

    def find_capabilities_for_task(
        self,
        task_description: str,
        threshold: float = 1.0,
        return_scores: bool = False
    ) -> Union[Set[Capability], Dict[Capability, float]]:
        """
        Infer needed capabilities from a task description.

        Uses regex pattern matching with confidence scoring as fallback
        when AI doesn't explicitly request capabilities.

        Args:
            task_description: Natural language task description
            threshold: Minimum confidence score to include (default 1.0)
            return_scores: If True, return dict with scores; if False, return set

        Returns:
            Set of capabilities or Dict mapping capabilities to confidence scores

        Example:
            # Get capabilities above threshold
            caps = registry.find_capabilities_for_task(
                "analyze the system logs in /var/log/"
            )
            # → {Capability.READ_DATA, Capability.ANALYZE_CODE}

            # Get capabilities with scores
            caps_with_scores = registry.find_capabilities_for_task(
                "read the file at /var/log/system.log",
                return_scores=True
            )
            # → {Capability.READ_DATA: 8.0}
        """
        scored_capabilities = infer_capability_from_task(task_description, threshold)

        if return_scores:
            return scored_capabilities
        else:
            return set(scored_capabilities.keys())

    def get_tools_by_capabilities(
        self,
        capabilities: List[Capability],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[Capability, List[Tool]]:
        """
        Get tools for multiple capabilities at once.

        Args:
            capabilities: List of capabilities needed
            context: Optional context for all lookups

        Returns:
            Dict mapping each capability to its providers

        Example:
            tools_map = registry.get_tools_by_capabilities([
                Capability.READ_DATA,
                Capability.ANALYZE_CODE
            ])
            # → {
            #     Capability.READ_DATA: [ReadFileTool, FetchURLTool],
            #     Capability.ANALYZE_CODE: [AnalyzeCodeTool]
            # }
        """
        result = {}
        for capability in capabilities:
            providers = self.find_providers(capability, context=context)
            result[capability] = providers
        return result

    def discover_tools(
        self,
        task_description: str,
        limit: int = 10,
        context: Optional[Dict[str, Any]] = None,
        with_scores: bool = False
    ) -> List[Tool]:
        """
        Find the tools most relevant to a natural-language task.

        This is the discovery entry point callers should use. find_providers()
        answers "who can do capability X" and returns providers in registration
        order; it is not a ranking. This ranks the whole live registry against
        the wording of the task, so the caller can hand a small, relevant tool
        set to an LLM instead of everything the capability graph happens to
        touch.

        Ranking lives in core.tools.tool_discovery, which fuses BM25 over tool
        names and descriptions, sentence embeddings, and this registry's own
        capability graph. The embedding model is loaded on the first call, not
        at import, and if it is unavailable the ranking degrades to lexical +
        capability rather than failing.

        Args:
            task_description: Natural language task
            limit: Maximum tools to return
            context: Optional context; a ranked tool is kept only if the context
                suits at least one capability it declares
            with_scores: Return (tool, relevance) pairs instead of tools. The
                score is uncalibrated across queries; a caller filtering noise
                should threshold relative to the top score, because a task the
                registry has no vocabulary for still fills every slot.

        Returns:
            Tools ordered most-relevant first, or (tool, score) pairs when
            with_scores is set. Never raises: if ranking is unavailable for any
            reason the result is an empty list.
        """
        if not task_description or not str(task_description).strip():
            return []
        try:
            limit = max(0, int(limit))
        except Exception:
            limit = 10
        if limit == 0:
            return []

        try:
            from . import tool_discovery
        except Exception as e:
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.warning("discover_tools: ranker unavailable: %s", e)
            return []

        # The catalog is the live registry. Factories are included by name; the
        # ranker only needs name/description/parameters/capabilities, and
        # get_tool() materialises a factory tool on demand.
        #
        # De-duplicated on purpose: a tool that has been instantiated from a
        # factory appears in BOTH self.tools and self.tool_factories, so the
        # naive concatenation lists ~12 of them twice. Duplicates skew the BM25
        # document statistics and let the same Tool object come back twice in
        # one result list.
        # Sorted, not registration order: registration order is an accident of
        # module import order, and it is a tie-break input to the ranker's
        # document statistics, so leaving it unsorted makes results vary between
        # processes for no reason. Sorting also measurably helps here (one query
        # on the 75-query eval recovers from zero recall).
        by_name: Dict[str, Tool] = {}
        for name in sorted(set(list(self.tools) + list(self.tool_factories))):
            try:
                tool = self.get_tool(name)
            except Exception:
                continue
            if tool is None:
                continue
            # Key on the tool's own name: that is what the ranker returns.
            by_name.setdefault(getattr(tool, "name", None) or name, tool)
        if not by_name:
            return []
        catalog: List[Tool] = list(by_name.values())

        # Ask for extra: the context filter below can drop results, and we still
        # want to fill `limit` when it does.
        want = limit if context is None else min(len(catalog), limit * 3)
        try:
            scored = tool_discovery.discover_scored(
                catalog, str(task_description), want)
        except Exception as e:
            # discover_scored() already swallows its own failures; this is belt
            # and braces so the registry's contract holds unconditionally.
            # `except` must not turn a wiring defect into an empty result.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.warning("discover_tools: ranking failed: %s", e)
            return []

        # WHAT HISTORY SAYS ABOUT THIS KIND OF TASK.
        #
        # The ranker scores relevance from wording and the capability graph. It
        # has no idea which tools actually WORK for this intent -- that is
        # measured elsewhere, recorded to `tool_usage_history`, and aggregated
        # into per-(intent, category) success rates that nothing on this path
        # read. The system learned which tools work and then chose as though it
        # had not.
        #
        # A damped nudge, not an override: it reorders near-ties and cannot lift
        # an irrelevant tool above a relevant one, because a tool never tried
        # for this intent must not be ranked below one that has merely by virtue
        # of being untried.
        try:
            from core.learning.adaptive_tool_owner import apply_learned_affinity

            def _category_of(tool_name: str) -> str:
                tool = by_name.get(tool_name)
                category = getattr(tool, "category", None)
                return getattr(category, "value", category) or ""

            scored = apply_learned_affinity(
                str(task_description), scored, _category_of)
        except Exception as e:
            # Learning must never be able to empty a tool search.
            raise_if_structural(e, 'tool_registry.discover_tools')
            logger.debug("discover_tools: affinity unavailable: %s", e)

        results: List[Any] = []
        for name, score in scored:
            tool = by_name.get(name)
            if tool is None:
                continue
            if context is not None and not self._matches_any_context(tool, context):
                continue
            results.append((tool, score) if with_scores else tool)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _matches_any_context(tool: Tool, context: Dict[str, Any]) -> bool:
        """Keep a tool if any capability it declares is usable in this context.

        find_providers() applies context per capability because it is asked about
        one. Discovery is asked about a task, so a tool survives if the context
        suits it for anything it can do.
        """
        try:
            profile = getattr(tool, "capability_profile", None)
            if profile is None:
                return True
            caps = list(profile.get_capability_names())
            if not caps:
                return True
            return any(tool.matches_context(cap, context) for cap in caps)
        except Exception as e:
            # Fails OPEN deliberately -- discovery must not drop a tool because
            # its own matcher raised. But the swallow was silent, so a broken
            # matcher looked exactly like a tool that matched everything.
            logger.warning(
                "context matching raised for %s (%s: %s); including it rather "
                "than dropping it, but the matcher is broken",
                getattr(tool, "name", "?"), type(e).__name__, e)
            return True

    def get_capability_coverage(self) -> Dict[Capability, int]:
        """
        Get coverage statistics for each capability.

        Returns:
            Dict mapping capabilities to number of providers

        Example:
            coverage = registry.get_capability_coverage()
            # → {
            #     Capability.READ_DATA: 3,  # 3 tools provide this
            #     Capability.WRITE_DATA: 2,
            #     ...
            # }
        """
        return {cap: len(tools) for cap, tools in self.capability_index.items()}

    def resolve_capability_dependencies(
        self,
        capability: Capability,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Capability]:
        """
        Resolve all dependencies for a capability recursively.

        Returns a topologically sorted list of capabilities that must be
        executed before the requested capability.

        Args:
            capability: The capability to resolve dependencies for
            context: Context for provider selection

        Returns:
            List of capabilities in execution order (dependencies first)

        Example:
            # CONDUCT_RESEARCH depends on HTTP_REQUEST, PARSE_HTML, SUMMARIZE_TEXT
            deps = registry.resolve_capability_dependencies(Capability.CONDUCT_RESEARCH)
            # → [Capability.HTTP_REQUEST, Capability.PARSE_HTML,
            #    Capability.SUMMARIZE_TEXT, Capability.CONDUCT_RESEARCH]
        """
        visited = set()
        result = []

        def visit(cap: Capability):
            if cap in visited:
                return
            visited.add(cap)

            # Get best provider for this capability
            tool = self.select_best_provider(cap, context=context)
            if not tool or not tool.capability_profile:
                return

            # Get dependencies for this capability
            dependencies = tool.capability_profile.get_capability_dependencies(cap)

            # Visit dependencies first (depth-first)
            for dep_cap in dependencies:
                visit(dep_cap)

            # Add current capability after dependencies
            result.append(cap)

        visit(capability)
        return result

    def build_execution_plan(
        self,
        capabilities: List[Capability],
        context: Optional[Dict[str, Any]] = None
    ) -> List[tuple[Capability, str]]:
        """
        Build an execution plan for multiple capabilities with dependency resolution.

        Returns a list of (capability, tool_name) tuples in execution order,
        resolving all dependencies automatically.

        Args:
            capabilities: List of capabilities needed
            context: Context for provider selection

        Returns:
            List of (Capability, tool_name) tuples in execution order

        Example:
            plan = registry.build_execution_plan([
                Capability.CONDUCT_RESEARCH,
                Capability.GENERATE_REPORT
            ])
            # → [
            #     (Capability.HTTP_REQUEST, "fetch_url"),
            #     (Capability.PARSE_HTML, "parse_html"),
            #     (Capability.SUMMARIZE_TEXT, "summarize"),
            #     (Capability.CONDUCT_RESEARCH, "research_tool"),
            #     (Capability.GENERATE_REPORT, "report_generator")
            # ]
        """
        all_capabilities = []
        seen = set()

        # Resolve dependencies for each requested capability
        for capability in capabilities:
            resolved = self.resolve_capability_dependencies(capability, context)
            for cap in resolved:
                if cap not in seen:
                    all_capabilities.append(cap)
                    seen.add(cap)

        # Select best provider for each capability
        execution_plan = []
        for capability in all_capabilities:
            tool = self.select_best_provider(capability, context=context)
            if tool:
                execution_plan.append((capability, tool.name))

        return execution_plan

    # ========== END CAPABILITY-BASED DISCOVERY ==========

    @inject_latency("tool_registry", "execute_tool", delay_ms=100, jitter_ms=50)
    @inject_error("tool_registry", "execute_tool", error_type=RuntimeError, error_rate=0.05, error_message="Chaos-injected tool execution error")
    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> ToolResult:
        """
        Execute a tool with constitutional oversight (with chaos injection support).

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters
            user_id: User requesting tool execution
            session_id: Current session

        Returns:
            ToolResult
        """
        start_time = datetime.now()
        
        # Get tool
        tool = self.get_tool(tool_name)
        if not tool:
            # Provide structured suggestions for LLMs / agents
            suggestions = self._suggest_tools(tool_name)
            return ToolResult(
                success=False,
                output=None,
                error=f"TOOL_NOT_FOUND: Tool not found: {tool_name}",
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "TOOL_NOT_FOUND",
                    "requested_tool": tool_name,
                    "suggestions": suggestions,
                    "hint": "Use list_tools() or the Lyric tools API to discover valid tool names, or pick one of the suggested tools."
                }
            )
        
        # ── Parameter alias remapping ─────────────────────────────────────────
        # Silently remap common model mistakes before validation so the agent
        # doesn't burn an iteration on a trivially wrong parameter name.
        # Format: { tool_name: { wrong_name: correct_name } }
        _PARAM_ALIASES: Dict[str, Dict[str, str]] = {
            "web_search":   {"num_results": "max_results", "n": "max_results",
                             "count": "max_results", "limit": "max_results"},
            "web_fetch":    {"url_path": "url", "link": "url", "uri": "url"},
            "write_file":   {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
            "patch_file":   {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
            "read_file":    {"path": "file_path", "filename": "file_path",
                             "filepath": "file_path"},
        }
        _aliases = _PARAM_ALIASES.get(tool_name, {})
        if _aliases:
            _remapped = {_aliases.get(k, k): v for k, v in parameters.items()}
            if _remapped != parameters:
                _fixed = [f"{old}→{_aliases[old]}" for old in parameters if old in _aliases]
                logger.debug("Parameter alias remap for %s: %s", tool_name, ", ".join(_fixed))
                parameters = _remapped

        # Validate parameters
        is_valid, error = tool.validate_parameters(parameters)
        if not is_valid:
            # Include the full parameter schema so the model can fix on the next call
            _schema_parts = []
            if hasattr(tool, 'parameters') and tool.parameters:
                if isinstance(tool.parameters, dict):
                    # JSON Schema dict format (e.g. chaos tools)
                    _props = tool.parameters.get("properties", {})
                    _required_names = tool.parameters.get("required", [])
                    for _k, _v in _props.items():
                        _req = 'required' if _k in _required_names else 'optional'
                        _desc = f" — {_v.get('description', '')}" if _v.get('description') else ""
                        _schema_parts.append(f"  • {_k} ({_req}, type={_v.get('type', '?')}){_desc}")
                else:
                    # List[ToolParameter] format
                    for p in tool.parameters:
                        _req = 'required' if p.required else f'optional, default={p.default}'
                        _desc = f" — {p.description}" if getattr(p, 'description', None) else ""
                        _schema_parts.append(f"  • {p.name} ({_req}, type={p.type}){_desc}")
            _schema_str = "\n".join(_schema_parts) if _schema_parts else "  (no parameters)"
            _full_error = (
                f"PARAMETER_VALIDATION_FAILED: {error}\n"
                f"Parameter schema for '{tool_name}':\n{_schema_str}"
            )
            return ToolResult(
                success=False,
                output=None,
                error=_full_error,
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "PARAMETER_VALIDATION",
                    "validation_error": error,
                    "hint": f"Fix parameter names/types. Schema for '{tool_name}':\n{_schema_str}"
                }
            )

        # While recovery throttles tool execution, wait before running.
        try:
            from core.health.recovery_manager import get_recovery_manager
            throttle_delay_s = get_recovery_manager().tool_throttle_delay()
        except Exception as throttle_error:
            logger.error("recovery throttle unreadable for %s: %s", tool_name, throttle_error)
            throttle_delay_s = 0.0
        if throttle_delay_s > 0:
            await asyncio.sleep(float(throttle_delay_s))
        
        act_id = f"tool_{tool_name}_{uuid.uuid4().hex[:8]}"

        # THE CONSTITUTION IS THE GATE.
        #
        # Every tool call the substrate makes arrives here, so this is where its
        # own law is applied: five laws, judged against the act's measured
        # consequence, the capabilities its arguments would actually confer, what
        # the substrate has READ of the file it is about to touch, and the intent
        # reasoning recorded for the work this call belongs to.
        #
        # The intent is read from the async context, never from `parameters`. An
        # intent that travelled inside the act would be an account the act writes
        # about itself; the id names a record, and the constitution fetches it.
        # An id naming nothing judges as no intent at all.
        #
        # It is the ONLY gate: two gates would be two answers to "may this act
        # happen", which is the duplicate-authority defect on the one path where
        # it matters most.
        from core.agents.autonomous.autonomous_coordinator import (
            get_constitution, judge_act)
        from core.reasoning.intent_authority import (
            get_acting_intent, get_acting_actor)

        judgment = await judge_act(
            "tool", tool_name,
            {"tool_name": tool_name, **parameters},
            intent_id=get_acting_intent(),
            # WHOSE work this is. Not who asked — the constitution stays blind to
            # that — but whether the things this act touches are the substrate's
            # own or someone else's, which decides what it may risk with them.
            actor=get_acting_actor())
        if not judgment.allowed:
            logger.error("📜 CONSTITUTION %s — Law %d (%s): %s",
                         judgment.verdict.value.upper(), judgment.law_number,
                         judgment.law_name, judgment.reason)
            return ToolResult(
                success=False,
                output=None,
                error=(f"CONSTITUTION_{judgment.verdict.value.upper()}: "
                       f"{tool_name} — {judgment.reason}"),
                tool_name=tool_name,
                parameters=parameters,
                metadata={
                    "error_type": "CONSTITUTION_REFUSED",
                    "action_id": act_id,
                    "judgment": judgment.to_dict(),
                },
            )

        # Execute tool
        try:
            result = await tool.execute(**parameters)
            # A RESULT CAN CARRY A KEY BACK: an environment dump, a file of keys,
            # a service echoing its credential. It is cleaned here, before
            # anything records it, says it or remembers it
            # (core.security.secrets).
            from core.security.secrets import get_secrets_authority
            _keys = get_secrets_authority()
            result.output = _keys.redact(result.output)
            result.error = _keys.redact(result.error)
            if isinstance(result.metadata, dict):
                result.metadata = _keys.redact(result.metadata)
            result.tool_name = tool_name
            result.parameters = parameters
            result.execution_time = (datetime.now() - start_time).total_seconds()

            # HAND THE DETERMINATION BACK. This layer is not a bouncer -- almost
            # everything runs -- so its whole product is a deterministic,
            # model-free reading of what the agent just did, and a reading the
            # agent never receives is not a signal, it is a log line.
            #
            # It WAS a log line: on the allowed path the evaluation went to
            # `logger.info` and to `safety_assessments`, and nothing reached the
            # caller. Only the BLOCKED path put anything on the result, which is
            # the one case where the agent already knows something happened.
            #
            # Attached under its own key rather than merged in, so a tool's own
            # metadata can never collide with it or overwrite it.
            if not isinstance(result.metadata, dict):
                result.metadata = {}
            result.metadata["judgment"] = judgment.to_dict()

            # WHAT THE SUBSTRATE NOW KNOWS ABOUT THE FILES IT TOUCHED. Judged
            # before, noted after — both through the constitution, which owns the
            # reading ledger Law 2 consults.
            #
            # This has to live where EVERY act passes. It used to be called from
            # one route only (`_execute_operation`), so the substrate's own
            # proved work recorded nothing it read or wrote, and Law 2 then
            # refused acts on files it had just handled. Only a successful act
            # is noted: an act that failed established no account of anything.
            if result.success:
                try:
                    get_constitution().note_act(tool_name, parameters)
                except Exception as _note_error:
                    logger.warning("reading ledger not updated for %s: %s",
                                   tool_name, _note_error)

            # What HAPPENED after an allowed act is not recorded here. The
            # substrate's account of an act it chose is its INTENT, and that is
            # reconciled against the re-observed world by the path that raised
            # it (see `_reconcile_plan_intent`). Closing a second outcome record
            # from inside the tool layer would be a second account of the same
            # act, written by the layer least able to say whether the act
            # achieved anything.

            # Track usage
            await tool._track_usage()

            # A failure the tool itself reported, kept exactly as the tool said it.
            if not result.success and result.error:
                asyncio.create_task(_record_tool_failure(
                    tool_name, result.error, raised=False,
                    session_id=session_id, user_id=user_id))

            # Record the execution.
            self._log_usage(tool, parameters, result, user_id, session_id)
            await self._record_run(tool_name, success=result.success,
                                   execution_time_s=result.execution_time or 0.0,
                                   error=result.error)

            # An invoked tool is an OBSERVED operator. `_log_usage` records that
            # it ran; this records what it means -- the tool concept gains real
            # evidence, so a tool that has done work stops being
            # indistinguishable from one that is merely registered.
            #
            # Keyed on the invocation SHAPE, so a tool called in a loop does not
            # out-corroborate every other source in the store, and deduped in
            # process so the hot path pays one round trip per shape.
            await self._observe_invocation(tool, parameters, result.success)

            return result

        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}", exc_info=True)

            # Send notification for tool failure
            try:
                from core.utils.notification_helpers import notify_tool_failure
                asyncio.create_task(notify_tool_failure(
                    tool_name=tool_name,
                    error=e,
                    parameters=parameters,
                    context=f"User: {user_id}, Session: {session_id}"
                ))
            except Exception as notify_error:
                logger.warning(f"Failed to send tool failure notification: {notify_error}")

            from core.security.secrets import get_secrets_authority
            _raw_err = get_secrets_authority().redact(
                f"EXECUTION_ERROR: {e.__class__.__name__}: {str(e)}")
            # A parameter-name TypeError: name the parameters the tool does take.
            if isinstance(e, TypeError) and (
                "unexpected keyword argument" in str(e)
                or "missing" in str(e).lower()
            ):
                _schema_parts = []
                if hasattr(tool, 'parameters') and tool.parameters:
                    for p in tool.parameters:
                        _req = 'required' if p.required else f'optional, default={p.default}'
                        _desc = f" — {p.description}" if getattr(p, 'description', None) else ""
                        _schema_parts.append(f"  • {p.name} ({_req}, type={p.type}){_desc}")
                _schema_str = "\n".join(_schema_parts) if _schema_parts else "  (no parameters)"
                _raw_err += f"\nValid parameters for '{tool_name}':\n{_schema_str}"
            asyncio.create_task(_record_tool_failure(
                tool_name, _raw_err, raised=True,
                session_id=session_id, user_id=user_id))
            await self._record_run(tool_name, success=False,
                                   execution_time_s=(datetime.now() - start_time).total_seconds(),
                                   error=_raw_err)
            return ToolResult(
                success=False,
                output=None,
                error=_raw_err,
                tool_name=tool_name,
                parameters=parameters,
                execution_time=(datetime.now() - start_time).total_seconds(),
                metadata={
                    "error_type": "TOOL_EXECUTION_ERROR",
                    "exception_type": e.__class__.__name__,
                    "exception_message": str(e),
                }
            )
    
    async def project_capabilities(self) -> Dict[str, int]:
        """Project every registered tool into the concept layer as an operator.

        The concept graph knew about operators Lyric had LEARNED and nothing
        about the ones it could already perform, so cross-domain grounding could
        recognise an unfamiliar situation as a learned rule but never as
        something there was already a tool for. A tool's parameter list is a
        precondition list in another notation; projecting it makes the registry
        searchable by the same structural matcher.

        Enumerates eager AND lazy tools by the same union used by discovery --
        `self.tools` alone omits every lazily registered tool, which is most of
        them.
        """
        from core.domain.evidence_producers import submit_tool_capability

        counts = {"tools": 0, "projected": 0, "no_structure": 0,
                  "unreadable_structure": 0, "failed": 0}
        for name in sorted(set(list(self.tools) + list(self.tool_factories))):
            try:
                tool = self.get_tool(name)
            except Exception:
                counts["failed"] += 1
                continue
            if tool is None:
                counts["failed"] += 1
                continue
            counts["tools"] += 1
            try:
                result = await submit_tool_capability(tool)
            except Exception as e:
                counts["failed"] += 1
                logger.warning("tool %s could not be projected: %s: %s",
                               name, type(e).__name__, e)
                continue
            # WHAT "PROJECTED" MEANS. `read_successfully` only reports that no
            # extractor raised -- a tool read cleanly that produced no concepts
            # satisfies it just as well as one that produced eleven. Counting
            # that as projected would report full coverage for a store that
            # gained nothing, which is the silent-negative shape this service
            # exists to avoid elsewhere.
            #
            # So `projected` counts tools that actually landed a concept, and a
            # tool that declares neither parameters nor capabilities is counted
            # separately: that is a gap in what the tool says about itself, not
            # an ingestion failure.
            if not result.read_successfully:
                counts["unreadable_structure"] += 1
            elif result.accepted:
                counts["projected"] += 1
            else:
                counts["no_structure"] += 1

        logger.info(
            "Projected %d/%d tools as operators (%d declare no structure, "
            "%d had an extractor fail, %d unreadable)",
            counts["projected"], counts["tools"], counts["no_structure"],
            counts["unreadable_structure"], counts["failed"])
        return counts

    async def _observe_invocation(self, tool, parameters, succeeded: bool) -> None:
        """Submit one tool invocation as evidence. Never fails the tool call."""
        try:
            from core.domain.evidence_producers import submit_tool_invocation

            await submit_tool_invocation(
                getattr(tool, "name", ""), parameters or {}, bool(succeeded),
                category=str(getattr(getattr(tool, "category", None), "value", "tools")))
        except Exception as e:
            # The tool ran and its result is real. Losing that because the
            # semantic layer could not record it would be the larger defect --
            # but a silent pass would make a broken producer look like a tool
            # with nothing to observe, so it is logged at error.
            logger.error(
                "tool %s executed but its invocation was not recorded as "
                "evidence: %s: %s", getattr(tool, "name", "?"), type(e).__name__, e)

    def _log_usage(
        self,
        tool: Tool,
        parameters: Dict[str, Any],
        result: ToolResult,
        user_id: Optional[str],
        session_id: Optional[str]
    ):
        """Record one tool execution: in memory and in the durable log."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool.name,
            "category": tool.category.value if hasattr(tool.category, 'value') else str(tool.category),
            "safety_level": tool.safety_level.value if hasattr(tool.safety_level, 'value') else str(tool.safety_level),
            "parameters": parameters,
            "success": result.success,
            "error": result.error,
            "execution_time": result.execution_time,
            "user_id": user_id,
            "session_id": session_id
        }
        
        self.usage_log.append(log_entry)

    async def _record_run(self, tool_name: str, *, success: bool,
                          execution_time_s: float, error: Optional[str]) -> None:
        """Record ONE run of a tool, success or failure, where learning reads it.

        EVERY RUN PASSES HERE, so it is recorded here, once. Runs were recorded in
        two places: this registry wrote `unified.tool_execution_events`, which
        nothing reads, and the coordinator's `_run_tool` wrote
        `tool_usage_history`, which tool learning reads -- so a tool reached any
        other way (a conversation looking something up on the web, a reading
        step, a rule's operator) ran and was never learned from. Attributed to
        the task the act serves (`set_acting_task`), or to none.

        Only runs are recorded. An act the constitution refused never reached the
        tool, so it says nothing about how well the tool works."""
        try:
            from core.learning.adaptive_tool_owner import get_adaptive_tool_learning
            from core.reasoning.intent_authority import get_acting_task
            task_id, description = get_acting_task() or ("", "")
            await get_adaptive_tool_learning().record_tool_run(
                task_id=task_id, task_description=description, tool_name=tool_name,
                success=bool(success), latency_ms=int(round(execution_time_s * 1000)),
                failure_reason=None if success else (str(error)[:500] if error else None))
        except Exception as record_error:
            # The tool ran and its result stands; losing the record is reported.
            logger.error("tool %s ran but the run was not recorded for learning: %s",
                         tool_name, record_error)


    def _suggest_tools(self, requested_name: str, max_suggestions: int = 5) -> List[str]:
        """Suggest similar tool names for TOOL_NOT_FOUND errors.

        This is intentionally simple and fast: substring and prefix matching
        over the currently-registered tool names. It is only used for
        guidance, not correctness.
        """
        if not requested_name:
            return []

        requested_lower = requested_name.lower()

        # First: substring or superstring matches
        candidates: List[str] = []
        for name in self.tools.keys():
            lower = name.lower()
            if requested_lower in lower or lower in requested_lower:
                candidates.append(name)

        # Fallback: prefix match on first 3 characters
        if not candidates and len(requested_lower) >= 3:
            prefix = requested_lower[:3]
            for name in self.tools.keys():
                if name.lower().startswith(prefix):
                    candidates.append(name)

        # Final fallback: just return a few known tools
        if not candidates:
            candidates = list(self.tools.keys())

        return candidates[:max_suggestions]

    def get_usage_stats(self) -> Dict[str, Any]:
        """Tool inventory and SESSION usage.

        Two things were wrong here and both under-reported the system:

        `total_tools` was len(self.tools) -- the EAGER tools only. Most tools are
        registered lazily as factories, so the registry described itself as ~92
        tools when it holds ~384. Anything gating on tool count saw a quarter of
        the inventory.

        `total_uses` sums Tool.usage_count, which is an in-process attribute
        initialised to 0 and incremented on execution. It is never loaded from
        storage, so it reports 0 in any fresh process regardless of history --
        while unified.tool_error_events holds hundreds of real records. The
        counter is SESSION scope and is now named as such; persisted history is
        a different question and is not answered by an in-memory sum.
        """
        total_uses = sum(tool.usage_count for tool in self.tools.values())

        by_category = {}
        for tool in self.tools.values():
            cat = tool.category.value
            if cat not in by_category:
                by_category[cat] = {"count": 0, "usage": 0}
            by_category[cat]["count"] += 1
            by_category[cat]["usage"] += tool.usage_count

        most_used = sorted(
            self.tools.values(),
            key=lambda t: t.usage_count,
            reverse=True
        )[:5]

        return {
            "total_tools": len(self.tools) + len(self.tool_factories),
            "eager_tools": len(self.tools),
            "lazy_tools": len(self.tool_factories),
            "loaded_tools": len(self.loaded_tools),
            "session_uses": total_uses,
            "total_uses": total_uses,  # retained: existing callers read this key
            "by_category": by_category,
            "most_used": [
                {
                    "name": t.name,
                    "usage_count": t.usage_count,
                    "last_used": t.last_used.isoformat() if t.last_used else None
                }
                for t in most_used
            ]
        }


# Global registry instance
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create global tool registry"""
    global _tool_registry
    
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        
        # Auto-register all available tools
        _register_default_tools()
    
    return _tool_registry


def _register_tool_lazy(tool_class):
    """
    Helper to register a tool class with lazy loading.

    Instantiates once to extract metadata, then registers a factory
    that creates fresh instances on demand.

    Args:
        tool_class: Tool class (not instance)
    """
    registry = _tool_registry

    # Instantiate once to get metadata (then discard)
    metadata_instance = tool_class()
    tool_name = metadata_instance.name

    # Extract capabilities if available
    capabilities = None
    if hasattr(metadata_instance, 'capability_profile') and metadata_instance.capability_profile:
        capabilities = list(metadata_instance.capability_profile.get_capability_names())

    # Register factory that creates NEW instances on demand
    registry.register_factory(
        tool_name,
        tool_class,  # Pass class itself, not instance
        capabilities=capabilities,
        category=metadata_instance.category,
        safety_level=metadata_instance.safety_level
    )


def _register_default_tools():
    """Register all default tools with lazy loading"""
    registry = _tool_registry

    # ===== LAZY LOADING: Tools registered as factories, loaded on first use =====
    try:
        from .filesystem_tools import (
            ReadFileTool, WriteFileTool, PatchFileTool, ListDirectoryTool,
            CreateDirectoryTool, SearchFilesTool, MoveFileTool,
            CopyFileTool, DeleteFileTool, AtomicWriteFileTool,
            ValidatePathTool, CalculateChecksumTool, GetFileInfoTool,
            CompressFileTool, DecompressFileTool, FindDuplicateFilesTool,
            SyncDirectoryTool
        )
        _register_tool_lazy(ReadFileTool)
        _register_tool_lazy(WriteFileTool)
        _register_tool_lazy(PatchFileTool)
        _register_tool_lazy(ListDirectoryTool)
        _register_tool_lazy(CreateDirectoryTool)
        _register_tool_lazy(SearchFilesTool)
        _register_tool_lazy(MoveFileTool)
        _register_tool_lazy(CopyFileTool)
        _register_tool_lazy(DeleteFileTool)
        _register_tool_lazy(AtomicWriteFileTool)
        _register_tool_lazy(ValidatePathTool)
        _register_tool_lazy(CalculateChecksumTool)
        _register_tool_lazy(GetFileInfoTool)
        _register_tool_lazy(CompressFileTool)
        _register_tool_lazy(DecompressFileTool)
        _register_tool_lazy(FindDuplicateFilesTool)
        _register_tool_lazy(SyncDirectoryTool)
        logger.info("✅ Registered 17 filesystem tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register base filesystem tools: {e}")

    try:
        from .execution_tools import (
            RunPythonTool, RunShellCommandTool,
            ListProcessesTool, KillProcessTool, StartServiceTool,
            StopServiceTool, RestartServiceTool, GetProcessInfoTool,
            RunBackgroundTaskTool, ScheduleCronJobTool, InstallPythonPackageTool,
            ExecuteWithTimeoutTool, ExecuteWithResourceLimitsTool,
            ExecuteNetworkIsolatedTool, ExecuteDeterministicTool,
            ExecuteWithArtifactCaptureTool
        )
        _register_tool_lazy(RunPythonTool)
        _register_tool_lazy(RunShellCommandTool)
        _register_tool_lazy(ListProcessesTool)
        _register_tool_lazy(KillProcessTool)
        _register_tool_lazy(StartServiceTool)
        _register_tool_lazy(StopServiceTool)
        _register_tool_lazy(RestartServiceTool)
        _register_tool_lazy(GetProcessInfoTool)
        _register_tool_lazy(RunBackgroundTaskTool)
        _register_tool_lazy(ScheduleCronJobTool)
        _register_tool_lazy(InstallPythonPackageTool)
        _register_tool_lazy(ExecuteWithTimeoutTool)
        _register_tool_lazy(ExecuteWithResourceLimitsTool)
        _register_tool_lazy(ExecuteNetworkIsolatedTool)
        _register_tool_lazy(ExecuteDeterministicTool)
        _register_tool_lazy(ExecuteWithArtifactCaptureTool)
        logger.info("✅ Registered 17 execution tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register base execution tools: {e}")

    try:
        from .search_tools import (
            SemanticSearchTool, GrepSearchTool, AnalyzeCodeTool,
            AnalyzeCodeQualityTool, AnalyzeDependenciesTool, FindDeadCodeTool,
            SecurityScanTool, FindTodosTool, CountLinesTool,
            AnalyzeComplexityTool, DetectCodeSmellsTool, TraceDependenciesTool,
            FindCircularImportsTool, AnalyzeTestCoverageReportTool,
            FindPerformanceIssuesTool, CheckCodeStyleConsistencyTool,
            ASTSearchTool, BuildDependencyGraphTool, ExtractCallGraphTool,
            SearchSecretsAndPIITool
        )
        _register_tool_lazy(SemanticSearchTool)
        _register_tool_lazy(GrepSearchTool)
        _register_tool_lazy(AnalyzeCodeTool)
        _register_tool_lazy(AnalyzeCodeQualityTool)
        _register_tool_lazy(AnalyzeDependenciesTool)
        _register_tool_lazy(FindDeadCodeTool)
        _register_tool_lazy(SecurityScanTool)
        _register_tool_lazy(FindTodosTool)
        _register_tool_lazy(CountLinesTool)
        _register_tool_lazy(AnalyzeComplexityTool)
        _register_tool_lazy(DetectCodeSmellsTool)
        _register_tool_lazy(TraceDependenciesTool)
        _register_tool_lazy(FindCircularImportsTool)
        _register_tool_lazy(AnalyzeTestCoverageReportTool)
        _register_tool_lazy(FindPerformanceIssuesTool)
        _register_tool_lazy(CheckCodeStyleConsistencyTool)
        _register_tool_lazy(ASTSearchTool)
        _register_tool_lazy(BuildDependencyGraphTool)
        _register_tool_lazy(ExtractCallGraphTool)
        _register_tool_lazy(SearchSecretsAndPIITool)
    except ImportError as e:
        logger.warning(f"Could not register base search tools: {e}")

    try:
        from .system_tools import (
            ClipboardTool, NotificationTool, SystemInfoTool, FileWatcherTool,
            ListUsbDevicesTool, InstalledSoftwareTool
        )
        _register_tool_lazy(ClipboardTool)
        _register_tool_lazy(NotificationTool)
        _register_tool_lazy(SystemInfoTool)
        _register_tool_lazy(FileWatcherTool)
        _register_tool_lazy(ListUsbDevicesTool)
        _register_tool_lazy(InstalledSoftwareTool)
    except ImportError as e:
        logger.warning(f"Could not register system tools: {e}")

    # ===== EXTENDED TOOLS =====

    # Database & Storage Tools. The database tools work only on an OUTSIDE
    # database they are given, never the substrate's own (its own data is reached
    # through its authorities); the ones that ran on its own database were
    # archived 2026-09-30 (archive/superseded_database_tools_2026-09-30/).
    try:
        from .database_tools import (
            MySQLQueryTool, PostgresQueryTool,
            RedisGetTool, RedisSetTool, R2UploadTool, R2DownloadTool,
        )
        _register_tool_lazy(MySQLQueryTool)
        _register_tool_lazy(PostgresQueryTool)
        _register_tool_lazy(RedisGetTool)
        _register_tool_lazy(RedisSetTool)
        _register_tool_lazy(R2UploadTool)
        _register_tool_lazy(R2DownloadTool)
    except ImportError as e:
        logger.warning(f"Could not register database tools: {e}")

    # Network & Web Tools
    try:
        from .network_tools import (
            HttpRequestTool, DownloadFileTool, UploadFileTool, ParseHTMLTool,
            ExtractLinksTool, CheckURLStatusTool, DNSLookupTool, PingHostTool,
            PortScanTool, WebSocketConnectTool, GraphQLQueryTool, APICallTool,
            WebSearchTool, WebFetchTool, BrowserTool
        )
        _register_tool_lazy(HttpRequestTool)
        _register_tool_lazy(DownloadFileTool)
        _register_tool_lazy(UploadFileTool)
        _register_tool_lazy(ParseHTMLTool)
        _register_tool_lazy(ExtractLinksTool)
        _register_tool_lazy(CheckURLStatusTool)
        _register_tool_lazy(DNSLookupTool)
        _register_tool_lazy(PingHostTool)
        _register_tool_lazy(PortScanTool)
        _register_tool_lazy(WebSocketConnectTool)
        _register_tool_lazy(GraphQLQueryTool)
        _register_tool_lazy(APICallTool)
        _register_tool_lazy(WebSearchTool)     # Real web search via DuckDuckGo
        _register_tool_lazy(WebFetchTool)      # Fast HTTP page reader (static/SSR pages)
        _register_tool_lazy(BrowserTool)       # Headless Chromium via Playwright (JS/SPAs)
    except ImportError as e:
        logger.warning(f"Could not register network tools: {e}")

    # Research Tools - Multi-source academic and data research
    try:
        from .research_tools import (
            ConductResearchTool, SearchAcademicTool, SearchDataTool, SearchNewsTool
        )
        _register_tool_lazy(ConductResearchTool)
        _register_tool_lazy(SearchAcademicTool)
        _register_tool_lazy(SearchDataTool)
        _register_tool_lazy(SearchNewsTool)
    except ImportError as e:
        logger.warning(f"Could not register research tools: {e}")

    # Academic Tools - Comprehensive academic research suite
    try:
        from .academic_tools import (
            AnalyzeResearchPaperTool, GenerateCitationTool, SynthesizeLiteratureTool,
            ExtractPaperMetadataTool, AnalyzeResearchDataTool, GenerateLatexDocumentTool,
            CreateResearchGraphTool,
            FetchPaperByDOITool, FetchPaperByArxivTool, ValidateBibliographyTool,
            ExportBibliographyCSLTool, LinkClaimToEvidenceTool, GenerateArtifactManifestTool
        )
        _register_tool_lazy(AnalyzeResearchPaperTool)
        _register_tool_lazy(GenerateCitationTool)
        _register_tool_lazy(SynthesizeLiteratureTool)
        _register_tool_lazy(ExtractPaperMetadataTool)
        _register_tool_lazy(AnalyzeResearchDataTool)
        _register_tool_lazy(GenerateLatexDocumentTool)
        _register_tool_lazy(CreateResearchGraphTool)
        _register_tool_lazy(FetchPaperByDOITool)
        _register_tool_lazy(FetchPaperByArxivTool)
        _register_tool_lazy(ValidateBibliographyTool)
        _register_tool_lazy(ExportBibliographyCSLTool)
        _register_tool_lazy(LinkClaimToEvidenceTool)
        _register_tool_lazy(GenerateArtifactManifestTool)
    except ImportError as e:
        logger.warning(f"Could not register academic tools: {e}")

    # Communication Tools
    try:
        from .communication_tools import (
            SendSlackMessageTool, PostToWebhookTool
        )
        _register_tool_lazy(SendSlackMessageTool)
        _register_tool_lazy(PostToWebhookTool)
    except ImportError as e:
        logger.warning(f"Could not register communication tools: {e}")

    # Context-Aware Slack Tools (for internal operations only)
    try:
        from .slack_tools import (
            AskForClarificationTool, ReportSecurityFindingTool, NotifyDominionLabsTeamTool
        )
        _register_tool_lazy(AskForClarificationTool)
        _register_tool_lazy(ReportSecurityFindingTool)
        _register_tool_lazy(NotifyDominionLabsTeamTool)
        logger.info("✅ Context-aware Slack tools registered (internal operations only)")
    except ImportError as e:
        logger.warning(f"Could not register context-aware Slack tools: {e}")

    # Slack Monitoring & Interaction Tools (leveraging 43+ bot events)
    try:
        from .slack_monitoring_tools import (
            GetSlackUsersTool, GetSlackChannelsTool, SearchSlackMessagesTool,
            GetChannelHistoryTool, MonitorTeamActivityTool, GetTeamHealthMetricsTool,
            PostSlackMessageTool, GetUserPresenceTool
        )
        _register_tool_lazy(GetSlackUsersTool)
        _register_tool_lazy(GetSlackChannelsTool)
        _register_tool_lazy(SearchSlackMessagesTool)
        _register_tool_lazy(GetChannelHistoryTool)
        _register_tool_lazy(MonitorTeamActivityTool)
        _register_tool_lazy(GetTeamHealthMetricsTool)
        _register_tool_lazy(PostSlackMessageTool)
        _register_tool_lazy(GetUserPresenceTool)
        logger.info("✅ Slack monitoring tools registered (8 tools for comprehensive workspace monitoring)")
    except ImportError as e:
        logger.warning(f"Could not register Slack monitoring tools: {e}")

    # Monitoring & Metrics Tools
    try:
        from .monitoring_tools import (
            GetCPUUsageTool, GetMemoryUsageTool, GetDiskUsageTool, GetNetworkStatsTool,
            GetServiceStatusTool, ParseLogsTool, GetPerformanceProfileTool,
            # Advanced monitoring tools
            DistributedTracingTool, SLOSLIToolingTool, AnomalyDetectionTool, DashboardGeneratorTool
        )
        _register_tool_lazy(GetCPUUsageTool)
        _register_tool_lazy(GetMemoryUsageTool)
        _register_tool_lazy(GetDiskUsageTool)
        _register_tool_lazy(GetNetworkStatsTool)
        _register_tool_lazy(GetServiceStatusTool)
        _register_tool_lazy(ParseLogsTool)
        _register_tool_lazy(GetPerformanceProfileTool)
        # Advanced monitoring tools
        _register_tool_lazy(DistributedTracingTool)
        _register_tool_lazy(SLOSLIToolingTool)
        _register_tool_lazy(AnomalyDetectionTool)
        _register_tool_lazy(DashboardGeneratorTool)
    except ImportError as e:
        logger.warning(f"Could not register monitoring tools: {e}")

    # AI/ML Operations Tools
    try:
        from .ai_ml_tools import (
            GenerateEmbeddingTool, RunInferenceTool,
            AnalyzeTrainingDataTool, GetModelInfoTool, SemanticSimilarityTool, ExtractEntitiesTool
        )
        _register_tool_lazy(GenerateEmbeddingTool)
        _register_tool_lazy(RunInferenceTool)
        _register_tool_lazy(AnalyzeTrainingDataTool)
        _register_tool_lazy(GetModelInfoTool)
        _register_tool_lazy(SemanticSimilarityTool)
        _register_tool_lazy(ExtractEntitiesTool)
    except ImportError as e:
        logger.warning(f"Could not register AI/ML tools: {e}")

    # Data Processing Tools
    try:
        from .data_processing_tools import (
            ParseJSONTool, ParseYAMLTool, ParseCSVTool, ConvertFormatTool,
            TransformDataTool, AggregateDataTool, MergeDatasetsTool, FilterDataTool,
            SortDataTool, DeduplicateDataTool,
            # Advanced data processing
            ParseJSONLTool, SchemaInferenceTool, PIIScrubbingTool, DatasetProfilingTool
        )
        _register_tool_lazy(ParseJSONTool)
        _register_tool_lazy(ParseYAMLTool)
        _register_tool_lazy(ParseCSVTool)
        _register_tool_lazy(ConvertFormatTool)
        _register_tool_lazy(TransformDataTool)
        _register_tool_lazy(AggregateDataTool)
        _register_tool_lazy(MergeDatasetsTool)
        _register_tool_lazy(FilterDataTool)
        _register_tool_lazy(SortDataTool)
        _register_tool_lazy(DeduplicateDataTool)
        # Advanced data processing tools
        _register_tool_lazy(ParseJSONLTool)
        _register_tool_lazy(SchemaInferenceTool)
        _register_tool_lazy(PIIScrubbingTool)
        _register_tool_lazy(DatasetProfilingTool)
    except ImportError as e:
        logger.warning(f"Could not register data processing tools: {e}")

    # Code Generation & Modification Tools
    try:
        from .code_generation_tools import (
            # Basic Code Generation
            GenerateFunctionTool, GenerateClassTool, GenerateModuleTool,
            RefactorCodeTool, AddDocstringTool, AddTypeHintsTool,
            FormatCodeTool, FixLintingErrorsTool, GenerateTestTool, MigrateCodeTool,
            # Code Enhancement
            AddLoggingTool, OptimizeCodeTool, ConvertToAsyncTool,
            ExtractMethodTool, InlineVariableTool, RenameSymbolTool,
            # Mathematical & Algorithm Generation
            ImplementAlgorithmTool, GenerateSymbolicMathTool,
            GenerateNumericalCodeTool, GenerateMathProofTool,
            # Advanced Code Generation
            GenerateDesignPatternTool, GenerateAPIClientTool,
            ScaffoldApplicationTool, SynthesizeFromExamplesTool, GeneratePropertyTestTool,
            # Code Generation Infrastructure
            ApplyPatchTool, CompileTypecheckGateTool, RepositoryRefactorTool,
            LicenseAttributionCheckTool
        )
        # Register Basic Code Generation Tools
        _register_tool_lazy(GenerateFunctionTool)
        _register_tool_lazy(GenerateClassTool)
        _register_tool_lazy(GenerateModuleTool)
        _register_tool_lazy(RefactorCodeTool)
        _register_tool_lazy(AddDocstringTool)
        _register_tool_lazy(AddTypeHintsTool)
        _register_tool_lazy(FormatCodeTool)
        _register_tool_lazy(FixLintingErrorsTool)
        _register_tool_lazy(GenerateTestTool)
        _register_tool_lazy(MigrateCodeTool)

        # Register Code Enhancement Tools
        _register_tool_lazy(AddLoggingTool)
        _register_tool_lazy(OptimizeCodeTool)
        _register_tool_lazy(ConvertToAsyncTool)
        _register_tool_lazy(ExtractMethodTool)
        _register_tool_lazy(InlineVariableTool)
        _register_tool_lazy(RenameSymbolTool)

        # Register Mathematical & Algorithm Generation Tools
        _register_tool_lazy(ImplementAlgorithmTool)
        _register_tool_lazy(GenerateSymbolicMathTool)
        _register_tool_lazy(GenerateNumericalCodeTool)
        _register_tool_lazy(GenerateMathProofTool)

        # Register Advanced Code Generation Tools
        _register_tool_lazy(GenerateDesignPatternTool)
        _register_tool_lazy(GenerateAPIClientTool)
        _register_tool_lazy(ScaffoldApplicationTool)
        _register_tool_lazy(SynthesizeFromExamplesTool)
        _register_tool_lazy(GeneratePropertyTestTool)

        # Register Code Generation Infrastructure Tools
        _register_tool_lazy(ApplyPatchTool)
        _register_tool_lazy(CompileTypecheckGateTool)
        _register_tool_lazy(RepositoryRefactorTool)
        _register_tool_lazy(LicenseAttributionCheckTool)
    except ImportError as e:
        logger.warning(f"Could not register code generation tools: {e}")

    # Testing & Validation Tools
    try:
        from .testing_validation_tools import (
            RunPytestTool, RunUnittestTool, CheckSyntaxTool, ValidateJSONTool,
            ValidateYAMLTool, ValidateXMLTool, ValidateSchemaTool, LintPythonTool,
            TypeCheckTool, BenchmarkCodeTool, GenerateMockTool, TestDataGeneratorTool,
            IntegrationTestRunnerTool, LoadTestTool, RunCoverageTool,
            # Advanced testing/validation tools
            FuzzTestingTool, MutationTestingTool, StaticSecurityAnalysisTool,
            GoldenTestHarnessTool
        )
        _register_tool_lazy(RunPytestTool)
        _register_tool_lazy(RunUnittestTool)
        _register_tool_lazy(CheckSyntaxTool)
        _register_tool_lazy(ValidateJSONTool)
        _register_tool_lazy(ValidateYAMLTool)
        _register_tool_lazy(ValidateXMLTool)
        _register_tool_lazy(ValidateSchemaTool)
        _register_tool_lazy(LintPythonTool)
        _register_tool_lazy(TypeCheckTool)
        _register_tool_lazy(BenchmarkCodeTool)
        _register_tool_lazy(GenerateMockTool)
        _register_tool_lazy(TestDataGeneratorTool)
        _register_tool_lazy(IntegrationTestRunnerTool)
        _register_tool_lazy(LoadTestTool)
        _register_tool_lazy(RunCoverageTool)
        # Advanced testing/validation tools
        _register_tool_lazy(FuzzTestingTool)
        _register_tool_lazy(MutationTestingTool)
        _register_tool_lazy(StaticSecurityAnalysisTool)
        _register_tool_lazy(GoldenTestHarnessTool)
    except ImportError as e:
        logger.warning(f"Could not register testing/validation tools: {e}")

    # Reasoning, Simulation, and Optimization Tools
    try:
        from .reasoning_tools import (
            ProveTheoremTool,
            SolveConstraintsTool,
            SolveLinearOptimizationTool,
            SimulatePDE1DTool,
            SimulateStateSpaceTool,
            RunMonteCarloTool,
        )

        _register_tool_lazy(ProveTheoremTool)
        _register_tool_lazy(SolveConstraintsTool)
        _register_tool_lazy(SolveLinearOptimizationTool)
        _register_tool_lazy(SimulatePDE1DTool)
        _register_tool_lazy(SimulateStateSpaceTool)
        _register_tool_lazy(RunMonteCarloTool)

        logger.info("✅ Registered reasoning/simulation/optimization tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register reasoning/simulation tools: {e}")

    # Documentation Tools
    try:
        from .documentation_tools import (
            GenerateReadmeTool, GenerateAPIDocsTool, ExtractDocstringsTool,
            GenerateChangelogTool, CreateDiagramTool, UpdateDocsTool,
            # Advanced documentation tools
            DocsBuildPreviewTool, VersionedDocDeploymentTool, ADRGeneratorTool,
            # Real document generation tools
            GeneratePDFDocumentTool, GenerateWordDocumentTool, GeneratePowerPointTool,
            GenerateArchitectureDiagramTool, CreateFlowchartTool
        )
        _register_tool_lazy(GenerateReadmeTool)
        _register_tool_lazy(GenerateAPIDocsTool)
        _register_tool_lazy(ExtractDocstringsTool)
        _register_tool_lazy(GenerateChangelogTool)
        _register_tool_lazy(CreateDiagramTool)
        _register_tool_lazy(UpdateDocsTool)
        # Advanced documentation tools
        _register_tool_lazy(DocsBuildPreviewTool)
        _register_tool_lazy(VersionedDocDeploymentTool)
        _register_tool_lazy(ADRGeneratorTool)
        # Real document generation
        _register_tool_lazy(GeneratePDFDocumentTool)
        _register_tool_lazy(GenerateWordDocumentTool)
        _register_tool_lazy(GeneratePowerPointTool)
        _register_tool_lazy(GenerateArchitectureDiagramTool)
        _register_tool_lazy(CreateFlowchartTool)
    except ImportError as e:
        logger.warning(f"Could not register documentation tools: {e}")

    # System Management Tools
    try:
        from .system_management_tools import (
            SetEnvironmentVariableTool, GetEnvironmentVariableTool, ModifyConfigFileTool,
            ReloadConfigTool, CheckDependenciesTool, UpdateSystemTool, ManageDockerTool
        )
        _register_tool_lazy(SetEnvironmentVariableTool)
        _register_tool_lazy(GetEnvironmentVariableTool)
        _register_tool_lazy(ModifyConfigFileTool)
        _register_tool_lazy(ReloadConfigTool)
        _register_tool_lazy(CheckDependenciesTool)
        _register_tool_lazy(UpdateSystemTool)
        _register_tool_lazy(ManageDockerTool)
    except ImportError as e:
        logger.warning(f"Could not register system management tools: {e}")

    # Security & Encryption Tools
    try:
        from .security_tools import (
            # Encryption & Cryptography
            EncryptFileTool, DecryptFileTool, GeneratePasswordTool,
            HashDataTool, ValidateCertificateTool, ScanSecretsTool,
            # Active Defense & Threat Intelligence
            CheckIPThreatIntelligenceTool, BlockIPAddressTool, UnblockIPAddressTool,
            GetActiveBlocksTool, CreateWAFRuleTool, ApplyRateLimitTool,
            BlockCountryTool, GetSecurityMetricsTool, GetBlockHistoryTool,
            AddInternalThreatTool, SanitizeInputTool,
            # Input Validation Tools (NEW)
            ValidateEmailTool, ValidateURLTool, CheckMaliciousPatternsTool,
            SanitizeFilenameTool, ValidateSQLInputTool,
            CheckRateLimitTool,
            # Defensive Security & Intrusion Detection
            DetectIntrusionTool, AnalyzeAnomalyTool, MonitorLogsTool,
            DetectBruteForceTool, AnalyzeTrafficPatternTool, AutoRespondThreatTool,
            HuntThreatsTool, DetectZeroDayTool,
        )
        # Register Encryption & Cryptography Tools
        _register_tool_lazy(EncryptFileTool)
        _register_tool_lazy(DecryptFileTool)
        _register_tool_lazy(GeneratePasswordTool)
        _register_tool_lazy(HashDataTool)
        _register_tool_lazy(ValidateCertificateTool)
        _register_tool_lazy(ScanSecretsTool)

        # Register Active Defense & Threat Intelligence Tools
        _register_tool_lazy(CheckIPThreatIntelligenceTool)
        _register_tool_lazy(BlockIPAddressTool)
        _register_tool_lazy(UnblockIPAddressTool)
        _register_tool_lazy(GetActiveBlocksTool)
        _register_tool_lazy(CreateWAFRuleTool)
        _register_tool_lazy(ApplyRateLimitTool)
        _register_tool_lazy(BlockCountryTool)
        _register_tool_lazy(GetSecurityMetricsTool)
        _register_tool_lazy(GetBlockHistoryTool)
        _register_tool_lazy(AddInternalThreatTool)
        _register_tool_lazy(SanitizeInputTool)

        # Register Input Validation Tools (NEW)
        _register_tool_lazy(ValidateEmailTool)
        _register_tool_lazy(ValidateURLTool)
        _register_tool_lazy(CheckMaliciousPatternsTool)
        _register_tool_lazy(SanitizeFilenameTool)
        _register_tool_lazy(ValidateSQLInputTool)
        # `validate_path` is the filesystem tool's; a second one registered here
        # under the same name used to replace it silently.
        _register_tool_lazy(CheckRateLimitTool)

        # Register Defensive Security & Intrusion Detection Tools
        _register_tool_lazy(DetectIntrusionTool)
        _register_tool_lazy(AnalyzeAnomalyTool)
        _register_tool_lazy(MonitorLogsTool)
        # detect_brute_force is DISABLED (2026-09-30, the owner's word): kept, not registered.
        _register_tool_lazy(AnalyzeTrafficPatternTool)
        _register_tool_lazy(AutoRespondThreatTool)
        _register_tool_lazy(HuntThreatsTool)
        _register_tool_lazy(DetectZeroDayTool)

    except ImportError as e:
        logger.warning(f"Could not register security tools: {e}")

    # Learning & Analysis Tools (Self-Improvement, Causal Reasoning)
    try:
        from .learning_tools import (
            DetectPatternsTool, VisualizeLearningProgressTool,
            IdentifySkillGapsTool, MonitorDataDriftTool,
        )
        _register_tool_lazy(DetectPatternsTool)
        _register_tool_lazy(VisualizeLearningProgressTool)
        _register_tool_lazy(IdentifySkillGapsTool)
        _register_tool_lazy(MonitorDataDriftTool)
        logger.info("✅ Registered 12 learning & analysis tools (lazy)")
    except ImportError as e:
        logger.warning(f"Could not register learning tools: {e}")

    # Chaos engineering tools: archived 2026-09-30. Their only targets were the
    # substrate's own systems (archive/superseded_chaos_tools_2026-09-30/).

    # ===== AGENTSO CONNECTOR TOOLS =====
    # Register AgentSO security connectors (VirusTotal, CrowdStrike, MISP, etc.)
    # Connectors are imported directly from services/agentso/connectors/
    try:
        from .connector_tools import register_connector_tools

        logger.info("🔌 Registering AgentSO connector tools...")
        count = register_connector_tools(registry)

        if count > 0:
            logger.info(f"✅ Registered {count} AgentSO connector tools")
        else:
            logger.warning("⚠️  No AgentSO connector tools registered")

    except ImportError as e:
        logger.warning(f"Could not load AgentSO connector tools: {e}")
    except Exception as e:
        logger.warning(f"AgentSO connector registration failed: {e}")

    # Count lazy-loaded factories + eager-loaded tools
    total_factories = len(registry.tool_factories)
    total_eager = len(registry.tools)
    logger.info(f"✅ Registered {total_factories} tool factories (lazy) + {total_eager} eager tools = {total_factories + total_eager} total")
    logger.info(f"💡 Tools will load on-demand when first accessed (fixes slow startup!)")
