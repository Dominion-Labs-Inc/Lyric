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

from core.structural_defects import raise_if_structural
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
from core.learning.rule_induction import Fact, from_constant
from typing import FrozenSet, Sequence, Tuple


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


# ── What tools perform ────────────────────────────────────────────────────────
# A PRIMITIVE is an operation a tool performs: read data, run a command, search
# the web. Primitives are the means everyone has from the first day. They are
# not capabilities: a capability of Lyric is a compound behaviour learned from
# experience (core/capabilities.py), carried out with whatever tools perform the
# primitives it needs. A tool declares the primitives it performs, and the
# registry files it under each one (`primitive_index`).


class Primitive(Enum):
    """An operation a tool performs. Declared by the tool, never inferred from
    the words of a request. The values are stored in memory (a tool's projection
    says what it provides), so a value is never renamed."""

    # ========== DATA ACCESS ==========
    READ_DATA = "read_data"                    # Read data from any source (files, APIs, DBs)
    WRITE_DATA = "write_data"                  # Write data to any destination
    DELETE_DATA = "delete_data"                # Delete data (files, records, etc.)
    MOVE_DATA = "move_data"                    # Move/rename data
    COPY_DATA = "copy_data"                    # Copy/duplicate data
    LIST_DATA = "list_data"                    # List available data (files, records, etc.)
    SEARCH_DATA = "search_data"                # Search through data
    VALIDATE_DATA = "validate_data"            # Validate data format/integrity

    # ========== DATA TRANSFORMATION ==========
    PARSE_DATA = "parse_data"                  # Parse structured data (JSON, YAML, CSV, etc.)
    TRANSFORM_DATA = "transform_data"          # Transform data format/structure
    AGGREGATE_DATA = "aggregate_data"          # Aggregate/summarize data
    FILTER_DATA = "filter_data"                # Filter data by criteria
    SORT_DATA = "sort_data"                    # Sort data
    MERGE_DATA = "merge_data"                  # Merge datasets
    COMPRESS_DATA = "compress_data"            # Compress data
    DECOMPRESS_DATA = "decompress_data"        # Decompress data
    ENCRYPT_DATA = "encrypt_data"              # Encrypt data
    DECRYPT_DATA = "decrypt_data"              # Decrypt data

    # ========== CODE ==========
    GENERATE_CODE = "generate_code"            # Generate code from specifications
    ANALYZE_CODE = "analyze_code"              # Analyze code quality, complexity, etc.
    REFACTOR_CODE = "refactor_code"            # Refactor existing code
    FORMAT_CODE = "format_code"                # Format code style
    EXECUTE_CODE = "execute_code"              # Execute code (Python, shell, etc.)
    DEBUG_CODE = "debug_code"                  # Debug code issues
    TEST_CODE = "test_code"                    # Run tests on code
    LINT_CODE = "lint_code"                    # Lint code for issues
    DOCUMENT_CODE = "document_code"            # Generate code documentation
    ASSESS_QUALITY = "assess_quality"          # Assess code quality metrics
    ASSESS_COMPLEXITY = "assess_complexity"    # Assess code complexity
    DETECT_ISSUE = "detect_issue"              # Detect code issues and problems
    ANALYZE_DEPENDENCIES = "analyze_dependencies" # Analyze code dependencies

    # ========== EXECUTION ==========
    RUN_COMMAND = "run_command"                # Execute shell commands
    MANAGE_PROCESS = "manage_process"          # Manage system processes
    SCHEDULE_TASK = "schedule_task"            # Schedule tasks/cron jobs
    RUN_BACKGROUND_TASK = "run_background_task" # Run tasks in background

    # ========== SEARCH ==========
    SEMANTIC_SEARCH = "semantic_search"        # Semantic search with embeddings
    TEXT_SEARCH = "text_search"                # Full-text search (grep, ripgrep)
    PATTERN_SEARCH = "pattern_search"          # Pattern-based search (regex, glob)
    AST_SEARCH = "ast_search"                  # Search code by AST structure

    # ========== COMMUNICATION ==========
    SEND_MESSAGE = "send_message"              # Send messages (Slack, email, webhooks)
    RECEIVE_MESSAGE = "receive_message"        # Receive/read messages
    NOTIFY = "notify"                          # Send notifications
    ASK_HUMAN = "ask_human"                    # Request human input/approval

    # ========== DATABASE ==========
    QUERY_DATABASE = "query_database"          # Query databases (SQL, NoSQL)
    MODIFY_DATABASE = "modify_database"        # Insert/update/delete records
    BACKUP_DATABASE = "backup_database"        # Backup database
    RESTORE_DATABASE = "restore_database"      # Restore database from backup
    MIGRATE_DATABASE = "migrate_database"      # Run database migrations

    # ========== NETWORK ==========
    HTTP_REQUEST = "http_request"              # Make HTTP requests
    DOWNLOAD = "download"                      # Download files/data
    UPLOAD = "upload"                          # Upload files/data
    PARSE_HTML = "parse_html"                  # Parse HTML content
    CHECK_CONNECTIVITY = "check_connectivity"  # Check network connectivity
    DNS_LOOKUP = "dns_lookup"                  # Perform DNS lookups
    WEB_SEARCH = "web_search"                  # Search the live web (Google/Bing/DuckDuckGo)
    FETCH_PAGE = "fetch_page"                    # Fetch and extract readable text from a URL
    BROWSE_WEB = "browse_web"                    # Full browser control via Playwright (JS, clicks, forms)

    # ========== MONITORING ==========
    MONITOR_SYSTEM = "monitor_system"          # Monitor system resources (CPU, memory, disk)
    MONITOR_LOGS = "monitor_logs"              # Monitor/parse logs
    MONITOR_METRICS = "monitor_metrics"        # Track metrics
    MONITOR_HEALTH = "monitor_health"          # Check system health
    CREATE_ALERT = "create_alert"              # Create alerts/notifications
    DETECT_ANOMALY = "detect_anomaly"          # Detect anomalies
    TRACE_EXECUTION = "trace_execution"        # Distributed tracing

    # ========== SECURITY ==========
    SCAN_SECURITY = "scan_security"            # Security scanning
    DETECT_THREAT = "detect_threat"            # Threat detection
    ANALYZE_THREAT = "analyze_threat"          # Threat intelligence analysis
    BLOCK_THREAT = "block_threat"              # Block IPs, apply WAF rules
    VALIDATE_INPUT = "validate_input"          # Input validation/sanitization
    MANAGE_SECRETS = "manage_secrets"          # Manage secrets/credentials
    HASH_DATA = "hash_data"                    # Hash data
    DETECT_INTRUSION = "detect_intrusion"      # Intrusion detection

    # ========== AI/ML ==========
    GENERATE_EMBEDDING = "generate_embedding"  # Generate embeddings
    RUN_INFERENCE = "run_inference"            # Run ML inference
    ANALYZE_SIMILARITY = "analyze_similarity"  # Semantic similarity analysis
    EXTRACT_ENTITIES = "extract_entities"      # Named entity recognition
    SUMMARIZE_TEXT = "summarize_text"          # Text summarization

    # ========== RESEARCH ==========
    CONDUCT_RESEARCH = "conduct_research"      # Multi-source research
    SEARCH_ACADEMIC = "search_academic"        # Academic paper search
    ANALYZE_PAPER = "analyze_paper"            # Analyze research papers
    GENERATE_CITATION = "generate_citation"    # Generate citations

    # ========== DOCUMENTATION ==========
    GENERATE_DOCS = "generate_docs"            # Generate documentation
    CREATE_DIAGRAM = "create_diagram"          # Create diagrams/visualizations
    VISUALIZE_DATA = "visualize_data"          # Visualize data and metrics
    VISUALIZE = "visualize"                    # General visualization capability
    GENERATE_REPORT = "generate_report"        # Generate reports (PDF, Word, etc.)
    GENERATE_SYSTEM_MODEL = "generate_system_model"  # Write a system's model (SysML) from its documents

    # ========== SYSTEM ==========
    GET_SYSTEM_INFO = "get_system_info"        # Get system information
    MANAGE_CONFIG = "manage_config"            # Manage configuration
    MANAGE_DEPENDENCIES = "manage_dependencies" # Manage dependencies/packages
    MANAGE_DOCKER = "manage_docker"            # Manage Docker containers

    # ========== TESTING ==========
    RUN_TESTS = "run_tests"                    # Run test suites
    GENERATE_TESTS = "generate_tests"          # Generate test cases
    BENCHMARK = "benchmark"                    # Benchmark performance
    COVERAGE_ANALYSIS = "coverage_analysis"    # Analyze test coverage
    ASSESS_COVERAGE = "assess_coverage"        # Assess test coverage metrics
    FUZZ_TEST = "fuzz_test"                    # Fuzz testing
    MUTATION_TEST = "mutation_test"            # Mutation testing

    # ========== CHAOS ENGINEERING ==========
    INJECT_FAILURE = "inject_failure"          # Inject failures for testing
    SIMULATE_LOAD = "simulate_load"            # Simulate load/stress
    TEST_RESILIENCE = "test_resilience"        # Test system resilience

    # ========== HYPOTHESIS TESTING & SCIENTIFIC METHOD ==========
    GENERATE_HYPOTHESIS = "generate_hypothesis"      # Generate testable hypotheses
    DESIGN_EXPERIMENT = "design_experiment"          # Design experiments to test hypotheses
    RUN_EXPERIMENT = "run_experiment"                # Execute experiments
    COLLECT_EVIDENCE = "collect_evidence"            # Gather experimental evidence
    EVALUATE_HYPOTHESIS = "evaluate_hypothesis"      # Evaluate hypothesis against evidence
    REVISE_HYPOTHESIS = "revise_hypothesis"          # Revise hypothesis based on results
    VALIDATE_CLAIM = "validate_claim"                # Validate scientific claims

    # ========== LEARNING & PATTERN EXTRACTION ==========
    EXTRACT_PATTERNS = "extract_patterns"            # Extract patterns from data
    EXTRACT_KNOWLEDGE = "extract_knowledge"          # Extract actionable knowledge from data
    META_LEARN = "meta_learn"                        # Learn about learning itself
    CONSOLIDATE_KNOWLEDGE = "consolidate_knowledge"  # Consolidate learned knowledge
    TRANSFER_LEARNING = "transfer_learning"          # Transfer knowledge across domains
    FEW_SHOT_ADAPT = "few_shot_adapt"                # Few-shot learning adaptation
    CONTINUAL_LEARN = "continual_learn"              # Continuous learning without forgetting
    ANALYZE_FEEDBACK = "analyze_feedback"            # Analyze feedback for improvements
    UPDATE_MENTAL_MODEL = "update_mental_model"      # Update internal mental models

    # ========== REASONING ==========
    CAUSAL_REASONING = "causal_reasoning"            # Reason about cause and effect
    DEDUCTIVE_REASONING = "deductive_reasoning"      # Deduce conclusions from premises
    INDUCTIVE_REASONING = "inductive_reasoning"      # Generalize from specific cases
    ABDUCTIVE_REASONING = "abductive_reasoning"      # Inference to best explanation
    ANALOGICAL_REASONING = "analogical_reasoning"    # Reason by analogy
    COUNTERFACTUAL_REASONING = "counterfactual_reasoning"  # Reason about hypotheticals
    TEMPORAL_REASONING = "temporal_reasoning"        # Reason about time and sequences
    SPATIAL_REASONING = "spatial_reasoning"          # Reason about space and geometry
    CONSTRAINT_REASONING = "constraint_reasoning"    # Reason with constraints

    # ========== INNOVATION & EXPLORATION ==========
    EXPLORE_DOMAIN = "explore_domain"                # Explore new knowledge domains
    TRACK_FRONTIER = "track_frontier"                # Track technology frontiers
    VALIDATE_APPROACH = "validate_approach"          # Validate new approaches
    BUILD_PROTOTYPE = "build_prototype"              # Build prototypes

    # ========== AGENTSO SECURITY OPERATIONS ==========
    # Threat Detection & Hunting
    THREAT_HUNT = "threat_hunt"                      # AI-powered threat hunting across SIEM/EDR
    INVESTIGATE_INCIDENT = "investigate_incident"    # Automated incident investigation & timeline building
    CORRELATE_EVENTS = "correlate_events"            # Cross-platform event correlation
    DETECT_APT = "detect_apt"                        # Advanced Persistent Threat detection
    BEHAVIORAL_ANALYSIS = "behavioral_analysis"      # User/entity behavioral analysis (UEBA)
    ANOMALY_DETECTION = "anomaly_detection"          # ML-based anomaly detection

    # Incident Response & Remediation
    AUTO_REMEDIATE = "auto_remediate"                # Automated security remediation
    ISOLATE_HOST = "isolate_host"                    # Quarantine/isolate compromised hosts
    BLOCK_IOC = "block_ioc"                          # Block malicious IOCs (IPs, domains, hashes)
    KILL_PROCESS = "kill_process"                    # Terminate malicious processes
    REVOKE_ACCESS = "revoke_access"                  # Revoke compromised credentials/sessions
    EXECUTE_PLAYBOOK = "execute_playbook"            # Execute incident response playbooks
    WAR_ROOM_MANAGEMENT = "war_room_management"      # Manage incident war rooms & coordination
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"      # AI-powered root cause analysis
    GENERATE_POSTMORTEM = "generate_postmortem"      # Auto-generate incident postmortems

    # Code & Application Security
    SECURITY_CODE_REVIEW = "security_code_review"    # AI-powered code security review
    DEPENDENCY_SCAN = "dependency_scan"              # Supply chain vulnerability scanning
    SECRET_DETECTION = "secret_detection"            # Detect exposed credentials in code
    GENERATE_SECURITY_FIX = "generate_security_fix"  # Auto-generate security patches
    SAST_ANALYSIS = "sast_analysis"                  # Static application security testing
    DAST_ANALYSIS = "dast_analysis"                  # Dynamic application security testing
    CONTAINER_SCAN = "container_scan"                # Container image vulnerability scanning

    # Threat Intelligence
    IOC_ENRICHMENT = "ioc_enrichment"                # Enrich threat indicators with context
    THREAT_ATTRIBUTION = "threat_attribution"        # Threat actor attribution & profiling
    TTP_MAPPING = "ttp_mapping"                      # Map attacks to MITRE ATT&CK TTPs
    INTEL_FUSION = "intel_fusion"                    # Fuse intelligence from multiple sources
    PREDICT_ATTACK = "predict_attack"                # Predictive threat modeling

    # Cloud Security
    CLOUD_REMEDIATION = "cloud_remediation"          # Cloud misconfiguration remediation
    ATTACK_PATH_ANALYSIS = "attack_path_analysis"    # Cloud attack path analysis
    CSPM_SCAN = "cspm_scan"                          # Cloud Security Posture Management
    IAM_ANALYSIS = "iam_analysis"                    # Analyze IAM permissions & policies
    ENFORCE_LEAST_PRIVILEGE = "enforce_least_privilege" # Implement least privilege access

    # Compliance & Governance
    COMPLIANCE_CHECK = "compliance_check"            # Compliance monitoring (SOC2, PCI-DSS, etc.)
    COMPLIANCE_REPORT = "compliance_report"          # Generate compliance reports
    AUDIT_TRAIL = "audit_trail"                      # Track security audit trails
    POLICY_ENFORCEMENT = "policy_enforcement"        # Enforce security policies

    # Security Orchestration
    SECURITY_ORCHESTRATION = "security_orchestration" # Orchestrate multi-tool security workflows
    AUTOMATE_ENRICHMENT = "automate_enrichment"      # Automated threat data enrichment
    COORDINATE_RESPONSE = "coordinate_response"      # Coordinate cross-team incident response

    # Vulnerability Management
    VULN_PRIORITIZATION = "vuln_prioritization"      # AI-powered vulnerability prioritization
    PATCH_MANAGEMENT = "patch_management"            # Automated patch management
    EXPLOIT_PREDICTION = "exploit_prediction"        # Predict exploitability of vulnerabilities

    # Innovation & Technology Synthesis
    SYNTHESIZE_TECHNOLOGY = "synthesize_technology"  # Synthesize new technologies
    IDENTIFY_OPPORTUNITY = "identify_opportunity"    # Identify innovation opportunities
    ASSESS_FEASIBILITY = "assess_feasibility"        # Assess technical feasibility

    # ========== SELF-IMPROVEMENT (through learning: measure, diagnose, learn) ==========
    ANALYZE_PERFORMANCE = "analyze_performance"      # Analyze own performance
    IDENTIFY_BOTTLENECK = "identify_bottleneck"      # Identify performance bottlenecks
    OPTIMIZE_COMPONENT = "optimize_component"        # Optimize system components
    OPTIMIZE_STRATEGY = "optimize_strategy"          # Optimize strategies and approaches
    REFACTOR_ARCHITECTURE = "refactor_architecture"  # Refactor system architecture
    EXPAND_CAPABILITY = "expand_capability"          # Expand own capabilities
    UPDATE_STRATEGY = "update_strategy"              # Update strategies
    SELF_DIAGNOSE = "self_diagnose"                  # Self-diagnose issues
    SELF_REPAIR = "self_repair"                      # Self-repair capabilities
    BENCHMARK_CAPABILITY = "benchmark_capability"    # Benchmark capabilities
    ASSESS_CAPABILITY = "assess_capability"          # Assess current capability levels

    # ========== STRATEGIC PLANNING ==========
    LONG_TERM_PLAN = "long_term_plan"                # Long-term strategic planning
    DECOMPOSE_GOAL = "decompose_goal"                # Decompose goals into subtasks
    PRIORITIZE_OBJECTIVES = "prioritize_objectives"  # Prioritize objectives
    ALLOCATE_RESOURCES = "allocate_resources"        # Allocate resources optimally
    ASSESS_RISK = "assess_risk"                      # Assess risks
    CONTINGENCY_PLAN = "contingency_plan"            # Create contingency plans
    TRACK_PROGRESS = "track_progress"                # Track progress toward goals
    REVISE_PLAN = "revise_plan"                      # Revise plans based on feedback
    RECOMMEND_ACTION = "recommend_action"            # Recommend optimal actions

    # ========== META-COGNITION ==========
    SELF_REFLECT = "self_reflect"                    # Self-reflection on reasoning
    ASSESS_CONFIDENCE = "assess_confidence"          # Assess confidence in conclusions
    IDENTIFY_BIAS = "identify_bias"                  # Identify cognitive biases
    CALIBRATE_UNCERTAINTY = "calibrate_uncertainty"  # Calibrate uncertainty estimates
    EXPLAIN_REASONING = "explain_reasoning"          # Explain reasoning process
    CRITIQUE_REASONING = "critique_reasoning"        # Critique own reasoning
    DETECT_CONFUSION = "detect_confusion"            # Detect confusion/uncertainty
    REQUEST_CLARIFICATION = "request_clarification"  # Request clarification

    # ========== KNOWLEDGE MANAGEMENT ==========
    BUILD_KNOWLEDGE_GRAPH = "build_knowledge_graph"  # Build knowledge graphs
    QUERY_KNOWLEDGE = "query_knowledge"              # Query knowledge bases
    UPDATE_BELIEFS = "update_beliefs"                # Update beliefs based on evidence
    RESOLVE_CONTRADICTION = "resolve_contradiction"  # Resolve contradictions
    VALIDATE_KNOWLEDGE = "validate_knowledge"        # Validate knowledge
    FORGET_KNOWLEDGE = "forget_knowledge"            # Prune outdated knowledge
    RETRIEVE_MEMORY = "retrieve_memory"              # Retrieve memories
    CONSOLIDATE_MEMORY = "consolidate_memory"        # Consolidate memories

    # ========== COLLABORATION & TEACHING ==========
    TEACH_CONCEPT = "teach_concept"                  # Teach concepts to others
    LEARN_FROM_HUMAN = "learn_from_human"            # Learn from human feedback
    COORDINATE_AGENTS = "coordinate_agents"          # Coordinate multiple agents
    DELEGATE_TASK = "delegate_task"                  # Delegate tasks
    REQUEST_EXPERTISE = "request_expertise"          # Request expert input
    EXPLAIN_TO_HUMAN = "explain_to_human"            # Explain to humans
    RECEIVE_FEEDBACK = "receive_feedback"            # Receive and process feedback

    # ========== SAFETY & ALIGNMENT ==========
    DETECT_MISALIGNMENT = "detect_misalignment"      # Detect goal misalignment
    VERIFY_SAFETY = "verify_safety"                  # Verify safety properties
    PREDICT_CONSEQUENCES = "predict_consequences"    # Predict action consequences
    ASSESS_ETHICS = "assess_ethics"                  # Assess ethical implications
    LIMIT_CAPABILITY = "limit_capability"            # Self-limit capabilities
    REQUEST_OVERSIGHT = "request_oversight"          # Request human oversight
    VALIDATE_ALIGNMENT = "validate_alignment"        # Validate goal alignment
    MONITOR_DRIFT = "monitor_drift"                  # Monitor objective drift


@dataclass
class PrimitiveUse:
    """One primitive a tool performs, and on what."""
    primitive: Primitive
    description: str = ""
    input_types: List[str] = field(default_factory=list)   # e.g. ["file_path", "url"]
    output_types: List[str] = field(default_factory=list)  # e.g. ["text", "json"]


@dataclass
class PrimitiveProfile:
    """What a tool declares about itself: the primitives it performs, and what
    it needs in order to run."""
    tool_name: str
    primitives: List[PrimitiveUse] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)
    requires_network: bool = False
    requires_filesystem: bool = False
    requires_database: bool = False
    requires_credentials: bool = False
    is_idempotent: bool = True

    def primitive_names(self) -> Set[Primitive]:
        """The primitives this tool performs."""
        return {use.primitive for use in self.primitives}

    def performs(self, primitive: Primitive) -> bool:
        """Whether this tool performs `primitive`."""
        return primitive in self.primitive_names()


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
    #: Seconds the tool ran, set by the registry when it ran it. None when it did
    #: not run (not found, parameters refused, the constitution refused): a 0.0
    #: there would read as a run that took no time.
    execution_time: Optional[float] = None
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

    A tool performs primitives -- reading and writing files, executing code,
    searching, system operations -- for the substrate, for people and for other
    systems. It is a means; a capability of Lyric is carried out with tools,
    and is not one.

    All tools are:
    1. Validated before execution
    2. Judged by the Constitution at execute_tool
    3. Subject to safety constraints
    4. Declared by the primitives they perform (`primitive_profile`)
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

        # What the tool declares it performs.
        if not hasattr(self, 'primitive_profile'):
            self.primitive_profile: Optional[PrimitiveProfile] = None

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

    # ========== WHAT THE TOOL PERFORMS ==========

    def performs(self, primitive: Primitive) -> bool:
        """Whether this tool performs `primitive`."""
        if not self.primitive_profile:
            return False
        return self.primitive_profile.performs(primitive)

    def get_primitives(self) -> Set[Primitive]:
        """The primitives this tool performs."""
        if not self.primitive_profile:
            return set()
        return self.primitive_profile.primitive_names()


class ToolRegistry:
    """
    Central registry for all available tools, with lazy loading.

    Responsibilities:
    - Register tool factories (lazy loading - tools loaded on first use)
    - File each tool under the primitives it declares it performs
    - Validate tool calls
    - Execute tools safely
    - Track usage
    - Constitutional oversight

    Architecture:
    - Tools are registered as factories (Callable that returns Tool instance)
    - Only loaded when first accessed (solves slow startup problem)
    - The primitive index maps each primitive to the tools that perform it. It
      is complete at registration: a lazy tool's declaration is read then.
    """

    def __init__(self):
        # Legacy: Eagerly loaded tools (backwards compatibility)
        self.tools: Dict[str, Tool] = {}

        # NEW: Lazy loading system
        self.tool_factories: Dict[str, Callable[[], Tool]] = {}  # tool_name → factory
        self.loaded_tools: Dict[str, Tool] = {}                   # tool_name → loaded instance

        # What each primitive is performed by
        self.primitive_index: Dict[Primitive, List[str]] = {}   # primitive → [tool_names]

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

        # File the tool under each primitive it declares
        if getattr(tool, 'primitive_profile', None):
            for primitive in tool.primitive_profile.primitive_names():
                if primitive not in self.primitive_index:
                    self.primitive_index[primitive] = []
                if tool.name not in self.primitive_index[primitive]:
                    self.primitive_index[primitive].append(tool.name)

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
        primitives: Optional[List[Primitive]] = None,
        category: Optional[ToolCategory] = None,
        safety_level: Optional[ToolSafety] = None
    ):
        """
        Register a tool factory for lazy loading (NEW - preferred method).

        Tools are not instantiated until first use, solving slow startup problem.

        Args:
            tool_name: Unique name for the tool
            factory: Callable that returns Tool instance when called
            primitives: The primitives this tool performs
            category: Tool category (for metadata)
            safety_level: Safety level (for metadata)

        Example:
            registry.register_factory(
                "read_file",
                lambda: ReadFileTool(),
                primitives=[Primitive.READ_DATA],
                category=ToolCategory.FILESYSTEM,
                safety_level=ToolSafety.SAFE
            )
        """
        self.tool_factories[tool_name] = factory

        # File the tool under each primitive it declares
        if primitives:
            for primitive in primitives:
                if primitive not in self.primitive_index:
                    self.primitive_index[primitive] = []
                if tool_name not in self.primitive_index[primitive]:
                    self.primitive_index[primitive].append(tool_name)

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

            # File the loaded tool under each primitive it declares
            if getattr(tool, 'primitive_profile', None):
                for primitive in tool.primitive_profile.primitive_names():
                    if primitive not in self.primitive_index:
                        self.primitive_index[primitive] = []
                    if name not in self.primitive_index[primitive]:
                        self.primitive_index[primitive].append(name)

            return tool

        return None
    
    def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
        """
        List all tools, optionally filtered by category.

        NOTE: This only returns eagerly-loaded tools (backwards compatibility).
        Lazy tools are named in `tool_factories` and load through `get_tool()`.
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
    
    async def project_primitives(self) -> Dict[str, int]:
        """Project every registered tool into the concept layer as an operator.

        The concept graph knew about operators Lyric had LEARNED and nothing
        about the ones it could already perform, so cross-domain grounding could
        recognise an unfamiliar situation as a learned rule but never as
        something there was already a tool for. A tool's parameter list is a
        precondition list in another notation; projecting it makes the registry
        searchable by the same structural matcher.

        Enumerates eager AND lazy tools as one set -- `self.tools` alone omits
        every lazily registered tool, which is most of them.
        """
        from core.agents.memory_agent import memory_agent

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
                result = await memory_agent().take_in_tool(tool)
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
            from core.agents.memory_agent import memory_agent

            await memory_agent().take_in_tool_use(
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

    # What it declares it performs, read now so the index is complete before
    # any tool is loaded
    primitives = None
    if getattr(metadata_instance, 'primitive_profile', None):
        primitives = list(metadata_instance.primitive_profile.primitive_names())

    # Register factory that creates NEW instances on demand
    registry.register_factory(
        tool_name,
        tool_class,  # Pass class itself, not instance
        primitives=primitives,
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

    # Systems engineering: a system's model, from what its documents say
    try:
        from .sysml_tools import GenerateSysMLModelTool
        _register_tool_lazy(GenerateSysMLModelTool)
    except ImportError as e:
        logger.warning(f"Could not register systems engineering tools: {e}")

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

    # AgentSO's connector tools: archived 2026-10-05 (archive/agentso_connector_tools_2026-10-05/). AgentSO is a
    # separate program, not part of Lyric. The connectors people connect are Lyric's own (core/connectors/), and
    # their tools are registered from there.

    # Count lazy-loaded factories + eager-loaded tools
    total_factories = len(registry.tool_factories)
    total_eager = len(registry.tools)
    logger.info(f"✅ Registered {total_factories} tool factories (lazy) + {total_eager} eager tools = {total_factories + total_eager} total")
    logger.info(f"💡 Tools will load on-demand when first accessed (fixes slow startup!)")


# =============================================================================
# TOOLS AS OPERATORS: A DOMAIN THE SUBSTRATE CAN ACT IN, DERIVED FROM ITS TOOLS
# =============================================================================
#
# THE CLAIM THIS KEEPS TRUE: the substrate can learn to do anything. It cannot,
# if every domain it may act in has to be hand-written first. A domain becomes
# learnable when it is OBSERVABLE (its state can be read back -- perception's
# worlds) and ACTABLE (a real tool changes it). Neither is written by hand:
# every tool the consequence map classes as changing the world becomes an
# operator, its predicate the tool's name and its arguments the tool's declared
# parameters in declared order (`action_binding`). Nothing is invented -- the
# mapping back is a zip. What this deliberately does not do is invent a
# vocabulary: derived facts say what the tool reported, in the tool's own words
# (experiments/TOOLDOMAIN-01).


#: Consequence classes that CHANGE the world. An operator is something that can
#: move the world from one state to another, so a tool that changes nothing is
#: not an operator however useful it is.
ACTING_CLASSES = ("modify", "archive", "delete", "execute")

#: The class that changes nothing and reports something.
OBSERVING_CLASS = "investigate"

#: What names a derived domain: the kinds of resource its acts touch.
DERIVED_PREFIX = "tools:"


def derived_domain_id(kinds) -> str:
    """The domain an act belongs to, named by the kinds of thing it touches."""
    return DERIVED_PREFIX + "-".join(sorted(set(kinds)))


def predicate_for(tool_name: str) -> str:
    """The operator name for a tool. Its own name, upper-cased — never a
    invented one, so the rule the substrate learns can always be traced back to
    the thing that does it."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(tool_name)).upper()


def declared_parameters(tool) -> List[Any]:
    """The tool's declared parameters, in declared order -- TYPED ones only.

    Six of the 356 registered tools put a raw JSON schema here instead of
    `ToolParameter` records, so `parameters` reads as the bare strings
    ("type", "properties", "required"). Nothing can be derived from those: a
    string is not a name, a type or a requirement. They are dropped rather than
    guessed at, which makes such a tool honestly underivable instead of binding
    an operator whose arguments are the words of a schema.
    """
    declared = list(getattr(tool, "parameters", None) or [])
    typed = [p for p in declared if hasattr(p, "name") and hasattr(p, "type")]
    if declared and not typed:
        logger.debug("%s declares untyped parameters; nothing to derive from it",
                     getattr(tool, "name", tool))
    return typed


def action_binding(tool_name: str, tool, observe) -> "Optional[OperatorBinding]":
    """One operator, derived from what the tool declares about itself.

    ITS ARGUMENTS ARE THE TOOL'S RESOURCE PARAMETERS, in declared order, then
    its payloads as fingerprints (`payload_term`). Resources are the only
    arguments whose values appear as terms in the observed world, and an
    argument that appears nowhere in the world is one induction can never
    connect to a precondition or an effect. It is also what keeps this operator
    the SAME operator `ActFrame` names when the substrate watches itself act --
    two spellings of MOVE_FILE at different arities would split one capability's
    evidence in half, which is how one file move came to be relearned eight
    times.

    EVERY OTHER DECLARED PARAMETER IS SUPPLIED FROM ITS OWN DECLARED DEFAULT,
    and the trade deserves stating because the alternative is defensible too.
    A hand-written binding could pin `create_dirs=False`, so that a move to a
    directory that is not there FAILS and gives the learner a negative to learn
    from. That is a person's judgement about what makes a good lesson, and it
    cannot be derived. Exposing the option instead makes it
    an argument the learner must vary blindly, with no term in the world to
    reason about.

    So the option takes the value the tool itself would use. The cost is real
    and worth naming: `move_file` defaults `create_dirs=True`, so a move to a
    missing directory SUCCEEDS, and the substrate will not learn a
    destination-directory precondition from it. What it learns instead is true
    of the operator it actually performs -- called this way, `move_file` really
    does not require the destination to exist. Negative evidence still comes
    from the world (a source that is not there, a path it may not write), just
    not from an option set to make the act fail.
    """
    resources = resource_parameters(tool)
    if not resources:
        return None
    declared = declared_parameters(tool)
    names = [str(p.name) for p in resources]
    # The act's payloads follow its places, as `ActFrame` names them, so the
    # operator the substrate performs is the one it watched itself perform.
    payload_names = [str(p.name) for p in payload_parameters(tool)]

    def parameters(args: Sequence[str]) -> Dict[str, Any]:
        supplied: Dict[str, Any] = {}
        for name, raw, declared_param in zip(names, args, resources):
            supplied[name] = _coerce(from_constant(str(raw)), declared_param)
        for name, raw in zip(payload_names, list(args)[len(names):]):
            digest = from_constant(str(raw))
            text = payload_for(digest)
            if text is None:
                # A fingerprint is not the text. An act whose payload the
                # substrate does not hold cannot be performed, and is refused
                # here, before anything is done, rather than sent without it.
                raise LookupError(
                    f"{tool_name}: the text with fingerprint {digest} is not held, "
                    f"so this act cannot be performed")
            supplied[name] = text
        for parameter in declared:
            if parameter.name not in supplied:
                default = getattr(parameter, "default", None)
                if default is not None:
                    supplied[parameter.name] = default
                elif (getattr(parameter, "required", False)
                      and str(getattr(parameter, "type", "")).lower() == "boolean"):
                    # A REQUIRED YES/NO WITH NO DEFAULT IS A GATE THE CALLER
                    # OPENS TO PROCEED -- `delete_file`'s `confirm`, "must be set
                    # to true to proceed", is the one in the registry. It changes
                    # nothing about what the act does. An act performed through a
                    # binding has already been judged by the constitution, so
                    # performing it is proceeding.
                    supplied[parameter.name] = True
        return supplied

    return OperatorBinding(
        predicate=predicate_for(tool_name), tool_name=tool_name,
        parameters=parameters, observe=observe,
        observe_async=getattr(observe, "__self__", None) and
                      getattr(observe.__self__, "observe_async", None),
        description=str(getattr(tool, "description", "") or ""))


def _coerce(value: str, declared) -> Any:
    """A logic constant back to the type the tool declared.

    Terms are strings because logic constants are; tools take booleans and
    numbers. Reported honestly rather than guessed: a value that does not parse
    as its declared type is passed through as the string it is, so the tool's
    own validation refuses it rather than this silently substituting something.
    """
    kind = str(getattr(declared, "type", "") or "").lower()
    if kind == "boolean":
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
        return value
    if kind in ("number", "integer"):
        try:
            return int(value) if kind == "integer" or value.isdigit() else float(value)
        except ValueError:
            return value
    return value

#: Parameter names carrying a PAYLOAD rather than naming a thing in the world.
#: Their value is bytes the act writes, not a resource that can be looked at,
#: so they are neither observable nor usable as a logic term.
PAYLOAD_PARAMS = frozenset({
    "content", "code", "command", "data", "body", "text", "payload", "sql",
})

def payload_parameters(tool) -> List[Any]:
    """The declared parameters that carry what an act PUTS INTO the world (the
    text a write is given), in declared order. Nothing can be pointed at them, so
    they are not resources; but they are what the act is FOR, since a write is
    right when the file then holds its payload. They join the act as the
    payload's fingerprint (`payload_term`)."""
    return [p for p in declared_parameters(tool)
            if str(getattr(p, "type", "")).lower() == "string"
            and str(p.name).lower() in PAYLOAD_PARAMS]


#: The texts the substrate has been given to put into the world, by fingerprint,
#: so an act that names one by its fingerprint can be performed. Held in this
#: process: a planned write names the text its goal was given.
_PAYLOADS: Dict[str, str] = {}


def payload_term(text: Any) -> str:
    """The fingerprint an act carries for a payload, in the form the self's
    sense gives what a file holds, so `CONTENT(file, x)` and the act's argument
    agree exactly when the file holds the payload. The text is kept by it. An
    absent payload is the empty text, so an act's arity does not vary."""
    from core.agents.autonomous.autonomous_coordinator import text_digest
    text = text if isinstance(text, str) else ""
    digest = text_digest(text)
    _PAYLOADS[digest] = text
    return digest


def payload_for(digest: str) -> Optional[str]:
    """The text held under a payload fingerprint, or None."""
    return _PAYLOADS.get(digest)


def resource_parameters(tool) -> List[Any]:
    """The declared parameters that NAME SOMETHING IN THE WORLD.

    A parameter names a resource exactly when the substrate has some way of
    LOOKING at that kind of thing -- when `observer_index` holds an entry for
    its kind. That is not a list of resource-ish words; it is the observability
    requirement itself, applied per argument. `grep_search(pattern=...)` names
    no resource because nothing in the registry can be pointed at a `pattern`,
    while `path` is one because `read_file`, `list_directory` and `get_file_info`
    can each be pointed at one.

    An unobservable argument is therefore not a defect to route around. It is
    the honest report that the substrate can change something it cannot see, and
    it must not become a term in an operator: a rule whose precondition can
    never be read is a rule that can never be checked.
    """
    from core.perception.perception_faculty import _senses, observer_index, resource_kind
    index = observer_index()
    senses = _senses()
    return [p for p in declared_parameters(tool)
            if str(getattr(p, "type", "")).lower() == "string"
            and str(p.name).lower() not in PAYLOAD_PARAMS
            and (resource_kind(p.name) in senses or resource_kind(p.name) in index)]


def encounter(tool_name: str, parameters: Dict[str, Any]) -> Optional[str]:
    """Make the domain this act belongs to ACTABLE and OBSERVABLE, on meeting it.

    THE ENCOUNTER IS THE DECLARATION. A task that declares `workspace_root`
    already installs the filesystem domain on encounter -- this is the same
    idea with nothing left for a person to name: the act itself says which
    resources are in play, what kind of thing they are, and which tool changes
    them, so the binding, the world and the explorable registration can all be
    derived from it.

    What this does NOT do is authorise anything. It registers a real binding for
    a real tool and a world that can really be read; the constitution then
    judges the act exactly as it would any other, and the accounts it demands
    (`_experiment_is_earned` checks this registry and the explorable registry)
    are satisfied by something true rather than something claimed. An act with
    no account is still refused.

    Returns the domain id, or None when nothing here is derivable.
    """
    from core.perception.perception_faculty import resource_kind, world_of
    from core.learning.exploration import get_proposer  # noqa: F401
    from core.agents.autonomous.autonomous_coordinator import classify_action
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    tool = registry.get_tool(tool_name)
    if tool is None:
        return None
    try:
        action_class, _ = classify_action(tool_name, parameters or {})
    except Exception:
        return None
    if getattr(action_class, "value", str(action_class)) not in ACTING_CLASSES:
        return None

    resources = [(resource_kind(p.name), str(parameters.get(p.name)))
                 for p in resource_parameters(tool)
                 if isinstance(parameters.get(p.name), str)
                 and str(parameters.get(p.name)).strip()]
    if not resources:
        return None

    domain_id = derived_domain_id(kind for kind, _ in resources)
    world = world_of(domain_id)
    for kind, value in resources:
        world.encountered(kind, value)

    predicate = predicate_for(tool_name)
    if get_binding_registry().get(domain_id, predicate) is None:
        binding = action_binding(tool_name, tool, world.observe)
        if binding is None:
            return None
        get_binding_registry().register(domain_id, binding)
        logger.info("encountered %s: %s is now a bound operator of %s",
                    tool_name, predicate, domain_id)
    # DELIBERATELY NOT REGISTERED EXPLORABLE HERE, and this is the honest edge
    # of what encounter can settle by itself.
    #
    # Binding an operator says "this tool changes this kind of thing, and the
    # substrate can read the result". Registering the domain explorable says
    # something else entirely: that the substrate may PRACTISE here, choosing
    # its own acts to find out what they do. A domain assembled from every
    # resource the substrate has touched is not a sandbox -- it would let
    # exploration move a file it once read for a user, which is why practice is
    # bounded to a place someone gave it (`take_up_workspace`, `derive_domain`).
    #
    # Acting when ASKED and practising UNASKED are different permissions, and
    # nothing derivable from a tool's declaration tells them apart. So the
    # binding is registered (which is true, and what the constitution's account
    # checks need) and the licence to practise is not.
    return domain_id


async def bind_learned() -> List[str]:
    """Bind the tool behind every operator already learned in a derived domain,
    so what was learned before a restart can be planned with and done again.

    A derived domain's operators are bound when an act is met, and nothing is
    met again just because the process restarted: the operator would sit in the
    store, validated, with nothing to perform it. The tool is found by the
    operator's own name, which is the tool's name (`predicate_for`).

    Returns "<domain>/<operator>" for each binding made.
    """
    from core.perception.perception_faculty import world_of
    from core.learning.rule_store import get_rule_store
    from core.tools import get_tool_registry

    registry = get_tool_registry()
    by_predicate = {predicate_for(name): name
                    for name in set(list(registry.tools) + list(registry.tool_factories))}
    bound: List[str] = []
    for stored in await get_rule_store().executable_rules():
        domain_id = str(stored.domain_id or "")
        action = getattr(stored.rule, "action", None)
        if not domain_id.startswith(DERIVED_PREFIX) or action is None:
            continue
        if get_binding_registry().get(domain_id, action.predicate) is not None:
            continue
        tool_name = by_predicate.get(action.predicate)
        tool = registry.get_tool(tool_name) if tool_name else None
        if tool is None:
            logger.warning("learned operator %s in %s names no tool; it cannot be "
                           "performed", action.predicate, domain_id)
            continue
        binding = action_binding(tool_name, tool, world_of(domain_id).observe)
        if binding is None:
            continue
        get_binding_registry().register(domain_id, binding)
        bound.append(f"{domain_id}/{action.predicate}")
    if bound:
        logger.info("bound %d learned operator(s) of derived domains: %s",
                    len(bound), ", ".join(bound))
    return bound


# =============================================================================
# OPERATOR BINDINGS: WHICH TOOL PERFORMS A LEARNED ACTION
# =============================================================================
#
# A learned rule says `MOVE(?X,?A,?B)` changes the world. It does not say what
# `MOVE` *is* -- the KITE experiments proved acquisition precisely because the
# predicates carried no meaning. Something has to connect the symbol to an act,
# and that connection is declared here rather than inferred: guessing which tool
# a predicate denotes would let the substrate take a real action on a resemblance
# between strings.
#
# A binding supplies both halves, and both are required:
#
#     execute   the tool and parameters that perform the action
#     observe   how the world is read back, independently of what the tool said
#
# The second is what makes verification possible. Without an independent
# observation the only available evidence is the tool's own success flag, and a
# rule would be confirmed by the fact that its invocation returned cleanly. How a
# domain's whole world is read is perception's (`perception_faculty.observe_world`).


@dataclass(frozen=True)
class OperatorBinding:
    """Binds one action predicate to a tool, and a world to its observer."""

    predicate: str
    tool_name: str
    #: ground action args -> tool parameters
    parameters: Callable[[Tuple[str, ...]], Dict[str, Any]]
    #: reads the world; returns None when it cannot be read, which is different
    #: from returning an empty world
    observe: Callable[[], Optional[FrozenSet[Fact]]]
    description: str = ""
    #: An observer that must be AWAITED, when reading this world means running
    #: tools rather than reading a directory. Optional, and `observe` remains
    #: the contract every existing caller uses.
    #:
    #: A world observed by running investigate-class tools cannot honestly be
    #: read from a synchronous callable inside a running loop: the only way to
    #: do it is a private loop on a worker thread, and those tools touch the
    #: database, which rebinds the connection pool away from the loop that owns
    #: it ("Database not initialized" mid-exploration, reproducibly). Async
    #: callers use `observe_world_async` and get the real thing.
    observe_async: Optional[Callable[[], Any]] = None


class BindingRegistry:
    """The declared bindings for a domain: which tool performs each of its
    learned actions. Unbound predicates are refused."""

    def __init__(self):
        self._bindings: Dict[Tuple[str, str], OperatorBinding] = {}

    def register(self, domain_id: str, binding: OperatorBinding) -> None:
        self._bindings[(domain_id, binding.predicate)] = binding
        logger.info("bound %s.%s -> %s", domain_id, binding.predicate, binding.tool_name)

    def get(self, domain_id: str, predicate: str) -> Optional[OperatorBinding]:
        return self._bindings.get((domain_id, predicate))

    def bindings_for(self, domain_id: str) -> Sequence[OperatorBinding]:
        """Every binding declared in a domain.

        The world a state goal is planned against is not one predicate's slice
        of it but the union of what every binding in the domain observes. A
        caller reading the whole world reads it through perception
        (`observe_world`), which reads through here rather than guessing which
        predicates exist.
        """
        return [b for (d, _), b in self._bindings.items() if d == domain_id]

    def clear(self, domain_id: Optional[str] = None) -> None:
        if domain_id is None:
            self._bindings.clear()
            return
        for key in [k for k in self._bindings if k[0] == domain_id]:
            del self._bindings[key]


_binding_registry: Optional[BindingRegistry] = None


def get_binding_registry() -> BindingRegistry:
    global _binding_registry
    if _binding_registry is None:
        _binding_registry = BindingRegistry()
    return _binding_registry
