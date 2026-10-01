#!/usr/bin/env python3
"""
AI/ML Tools
======================
Tool definitions for AI agents

Purpose:
- Define callable tools for AI agents
- Provide ML/AI capabilities
- Enable agent tool use
- Function calling interface
"""

import asyncio
import logging
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from core.tools.tool_registry import Tool, ToolResult, ToolParameter as RegistryToolParameter
from core.tools.capabilities import (
    ToolCapabilityProfile, CapabilityMetadata, Capability, RiskLevel
)

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Tool parameter definition"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: List[str] = field(default_factory=list)


@dataclass
class AIToolDefinition:
    """AI Tool definition - NOT the same as Tool base class"""
    name: str
    description: str
    parameters: List[ToolParameter]
    function: Callable
    category: str = "general"
    requires_auth: bool = False


class AIMLTools:
    """
    AI/ML Tools Registry

    Purpose:
    - Register and manage tools for AI agents
    - Provide tool calling interface
    - Execute tool functions safely
    - Track tool usage

    Usage:
        tools = AIMLTools()
        result = await tools.execute_tool("search_web", {"query": "AI news"})
    """

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self.usage_stats: Dict[str, int] = {}

        # Register default tools
        self._register_default_tools()

        logger.info("AIMLTools initialized")

    def _register_default_tools(self):
        """Register default AI/ML tools"""

        # Web Search Tool
        self.register_tool(AIToolDefinition(
            name="search_web",
            description="Search the web for information using a query string",
            category="research",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query to find information",
                    required=True
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="Number of results to return (1-10)",
                    required=False,
                    default=5
                )
            ],
            function=self._search_web
        ))

        # Code Analysis Tool
        self.register_tool(AIToolDefinition(
            name="analyze_code",
            description="Analyze code for bugs, security issues, and quality metrics",
            category="development",
            parameters=[
                ToolParameter(
                    name="code",
                    type="string",
                    description="Source code to analyze",
                    required=True
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Programming language",
                    required=False,
                    default="python",
                    enum=["python", "javascript", "typescript", "java", "go"]
                )
            ],
            function=self._analyze_code
        ))

        # Data Analysis Tool
        self.register_tool(AIToolDefinition(
            name="analyze_data",
            description="Analyze data and generate statistical insights",
            category="analytics",
            parameters=[
                ToolParameter(
                    name="data",
                    type="object",
                    description="Data to analyze (JSON format)",
                    required=True
                ),
                ToolParameter(
                    name="analysis_type",
                    type="string",
                    description="Type of analysis to perform",
                    required=False,
                    default="summary",
                    enum=["summary", "correlation", "distribution", "trend"]
                )
            ],
            function=self._analyze_data
        ))

        # Text Summarization Tool
        self.register_tool(AIToolDefinition(
            name="summarize_text",
            description="Summarize long text into concise key points",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to summarize",
                    required=True
                ),
                ToolParameter(
                    name="max_length",
                    type="integer",
                    description="Maximum length of summary in words",
                    required=False,
                    default=100
                )
            ],
            function=self._summarize_text
        ))

        # Sentiment Analysis Tool
        self.register_tool(AIToolDefinition(
            name="analyze_sentiment",
            description="Analyze sentiment of text (positive, negative, neutral)",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to analyze sentiment",
                    required=True
                )
            ],
            function=self._analyze_sentiment
        ))

        # Image Analysis Tool
        self.register_tool(AIToolDefinition(
            name="analyze_image",
            description="Analyze image content and extract information",
            category="vision",
            parameters=[
                ToolParameter(
                    name="image_url",
                    type="string",
                    description="URL of image to analyze",
                    required=True
                ),
                ToolParameter(
                    name="analysis_type",
                    type="string",
                    description="Type of analysis",
                    required=False,
                    default="objects",
                    enum=["objects", "text", "faces", "scene"]
                )
            ],
            function=self._analyze_image
        ))

        # Translation Tool
        self.register_tool(AIToolDefinition(
            name="translate_text",
            description="Translate text from one language to another",
            category="nlp",
            parameters=[
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to translate",
                    required=True
                ),
                ToolParameter(
                    name="target_language",
                    type="string",
                    description="Target language code (e.g., 'es', 'fr', 'de')",
                    required=True
                ),
                ToolParameter(
                    name="source_language",
                    type="string",
                    description="Source language code (auto-detect if not specified)",
                    required=False,
                    default="auto"
                )
            ],
            function=self._translate_text
        ))

        # Email Validation Tool
        self.register_tool(AIToolDefinition(
            name="validate_email",
            description="Validate email address format and deliverability",
            category="validation",
            parameters=[
                ToolParameter(
                    name="email",
                    type="string",
                    description="Email address to validate",
                    required=True
                )
            ],
            function=self._validate_email
        ))

        # URL Validation Tool
        self.register_tool(AIToolDefinition(
            name="validate_url",
            description="Validate URL format and check if accessible",
            category="validation",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL to validate",
                    required=True
                ),
                ToolParameter(
                    name="check_accessible",
                    type="boolean",
                    description="Check if URL is accessible via HTTP request",
                    required=False,
                    default=False
                )
            ],
            function=self._validate_url
        ))

        # Calculator Tool
        self.register_tool(AIToolDefinition(
            name="calculate",
            description="Perform mathematical calculations safely",
            category="math",
            parameters=[
                ToolParameter(
                    name="expression",
                    type="string",
                    description="Mathematical expression to evaluate",
                    required=True
                )
            ],
            function=self._calculate
        ))

    def register_tool(self, tool: AIToolDefinition):
        """Register a new tool"""
        self.tools[tool.name] = tool
        self.usage_stats[tool.name] = 0
        logger.info(f"Registered tool: {tool.name}")

    def unregister_tool(self, tool_name: str):
        """Unregister a tool"""
        if tool_name in self.tools:
            del self.tools[tool_name]
            logger.info(f"Unregistered tool: {tool_name}")

    def get_tool(self, tool_name: str) -> Optional[AIToolDefinition]:
        """Get tool by name"""
        return self.tools.get(tool_name)

    def list_tools(self, category: Optional[str] = None) -> List[AIToolDefinition]:
        """List all tools, optionally filtered by category"""
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions in OpenAI function calling format"""
        definitions = []

        for tool in self.tools.values():
            properties = {}
            required = []

            for param in tool.parameters:
                param_def = {
                    "type": param.type,
                    "description": param.description
                }

                if param.enum:
                    param_def["enum"] = param.enum

                properties[param.name] = param_def

                if param.required:
                    required.append(param.name)

            definitions.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            })

        return definitions

    async def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with given parameters

        Args:
            tool_name: Name of tool to execute
            parameters: Tool parameters

        Returns:
            Tool execution result
        """
        try:
            tool = self.get_tool(tool_name)

            if not tool:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found"
                }

            # Validate parameters
            validation_error = self._validate_parameters(tool, parameters)
            if validation_error:
                return {
                    "success": False,
                    "error": validation_error
                }

            # Add default values for optional parameters
            for param in tool.parameters:
                if param.name not in parameters and param.default is not None:
                    parameters[param.name] = param.default

            # Execute tool function
            result = await tool.function(**parameters)

            # Track usage
            self.usage_stats[tool_name] += 1

            return {
                "success": True,
                "result": result
            }

        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name} - {e}")
            return {
                "success": False,
                "error": f"Tool execution error: {str(e)}"
            }

    def _validate_parameters(
        self,
        tool: AIToolDefinition,
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """Validate tool parameters"""

        # Check required parameters
        for param in tool.parameters:
            if param.required and param.name not in parameters:
                return f"Missing required parameter: {param.name}"

            # Check enum values
            if param.enum and param.name in parameters:
                if parameters[param.name] not in param.enum:
                    return f"Invalid value for {param.name}. Must be one of: {param.enum}"

        return None

    # Tool implementations

    async def _search_web(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        """Search the web"""
        logger.info(f"Web search: {query}")

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Use DuckDuckGo Instant Answer API
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        results = []

                        # Add abstract if available
                        if data.get('Abstract'):
                            results.append({
                                "title": data.get('Heading', query),
                                "url": data.get('AbstractURL', ''),
                                "snippet": data.get('Abstract', '')
                            })

                        # Add related topics
                        for topic in data.get('RelatedTopics', [])[:num_results]:
                            if isinstance(topic, dict) and 'Text' in topic:
                                results.append({
                                    "title": topic.get('Text', '')[:50],
                                    "url": topic.get('FirstURL', ''),
                                    "snippet": topic.get('Text', '')
                                })

                        return {
                            "query": query,
                            "results": results[:num_results]
                        }
        except Exception as e:
            logger.error(f"Web search error: {e}")

        return {
            "query": query,
            "results": [],
            "error": "Search API unavailable"
        }

    async def _analyze_code(
        self,
        code: str,
        language: str = "python"
    ) -> Dict[str, Any]:
        """Analyze code"""
        logger.info(f"Analyzing {language} code ({len(code)} chars)")

        lines = [l for l in code.split('\n') if l.strip()]
        issues = []

        if language == "python":
            import ast
            try:
                tree = ast.parse(code)
                complexity = 0

                # Calculate complexity
                for node in ast.walk(tree):
                    if isinstance(node, (ast.If, ast.For, ast.While, ast.FunctionDef, ast.AsyncFunctionDef)):
                        complexity += 1

                # Check for common issues
                if 'eval(' in code or 'exec(' in code:
                    issues.append({"type": "security", "message": "Dangerous function usage: eval/exec"})

                if 'password' in code.lower() or 'api_key' in code.lower():
                    issues.append({"type": "security", "message": "Potential hardcoded credentials"})

                # Calculate quality score
                quality_score = 100
                quality_score -= min(complexity * 2, 30)
                quality_score -= len(issues) * 10

                return {
                    "language": language,
                    "lines_of_code": len(lines),
                    "issues": issues,
                    "complexity": complexity,
                    "quality_score": max(quality_score, 0)
                }

            except SyntaxError as e:
                issues.append({"type": "syntax", "message": f"Syntax error: {str(e)}"})

        return {
            "language": language,
            "lines_of_code": len(lines),
            "issues": issues,
            "complexity": "unknown",
            "quality_score": 50
        }

    async def _analyze_data(
        self,
        data: Any,
        analysis_type: str = "summary"
    ) -> Dict[str, Any]:
        """Analyze data"""
        logger.info(f"Data analysis: {analysis_type}")

        if not isinstance(data, (list, dict)):
            return {
                "analysis_type": analysis_type,
                "error": "Data must be a list or dictionary"
            }

        insights = []

        if isinstance(data, list):
            count = len(data)
            insights.append(f"Total items: {count}")

            if count > 0 and all(isinstance(x, (int, float)) for x in data):
                avg = sum(data) / count
                insights.append(f"Average: {avg:.2f}")
                insights.append(f"Min: {min(data)}, Max: {max(data)}")

        elif isinstance(data, dict):
            insights.append(f"Total keys: {len(data)}")
            for key, value in list(data.items())[:5]:
                insights.append(f"{key}: {type(value).__name__}")

        return {
            "analysis_type": analysis_type,
            "summary": f"Analyzed {type(data).__name__} data",
            "insights": insights
        }

    async def _summarize_text(
        self,
        text: str,
        max_length: int = 100
    ) -> Dict[str, Any]:
        """Summarize text — extractive, via the language-ops faculty."""
        logger.info(f"Summarizing text ({len(text)} chars)")

        from core.semantics.language_ops import summarize_length

        summary = summarize_length(text, max_words=max_length)
        return {
            "original_length": len(text),
            "summary": summary,
            "summary_length": len(summary)
        }

    async def _analyze_sentiment(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment — polarity lexicon with negation, via the
        language-ops faculty. Confidence is count-backed, so a passage with no
        affective words is an honest neutral at 0.0 rather than a guess at 0.85."""
        logger.info(f"Sentiment analysis ({len(text)} chars)")

        from core.semantics.language_ops import sentiment as _sentiment
        result = _sentiment(text)
        return {
            "sentiment": result["label"],
            "score": result["score"],
            "confidence": result["confidence"],
            "positive_hits": result["positive_hits"],
            "negative_hits": result["negative_hits"],
        }

    async def _analyze_image(
        self,
        image_url: str,
        analysis_type: str = "objects"
    ) -> Dict[str, Any]:
        """Analyze image"""
        logger.info(f"Image analysis: {image_url} ({analysis_type})")

        try:
            from core.services.lumen_vision import get_lumen_vision
            vision = get_lumen_vision()

            result = await vision.analyze_image(
                image_url=image_url,
                task=analysis_type
            )

            return {
                "image_url": image_url,
                "analysis_type": analysis_type,
                "objects": result.get("objects", []),
                "labels": result.get("labels", []),
                "description": result.get("description", "")
            }

        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return {
                "image_url": image_url,
                "analysis_type": analysis_type,
                "objects": [],
                "labels": [],
                "error": str(e)
            }

    async def _translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto"
    ) -> Dict[str, Any]:
        """Translate text.

        The substrate has no model-free translation faculty, and translation
        is not a teaching task, so it is not routed to a model outside the
        teacher. This raises an honest gap rather than fabricating a
        translation or returning a placeholder that reads as success.
        """
        raise NotImplementedError(
            f"translate_text has no model-free faculty "
            f"(requested {source_language} -> {target_language}); "
            f"not routed to a model outside the teacher"
        )

    async def _validate_email(self, email: str) -> Dict[str, Any]:
        """Validate email"""
        # Simple regex validation
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        is_valid = bool(re.match(email_regex, email))

        return {
            "email": email,
            "is_valid": is_valid,
            "format_valid": is_valid
        }

    async def _validate_url(
        self,
        url: str,
        check_accessible: bool = False
    ) -> Dict[str, Any]:
        """Validate URL"""
        url_regex = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
        is_valid = bool(re.match(url_regex, url))

        result = {
            "url": url,
            "is_valid": is_valid,
            "format_valid": is_valid
        }

        if check_accessible and is_valid:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        result["accessible"] = response.status < 400
                        result["status_code"] = response.status
            except Exception as e:
                result["accessible"] = False
                result["error"] = str(e)

        return result

    async def _calculate(self, expression: str) -> Dict[str, Any]:
        """Safe calculator"""
        try:
            # Whitelist safe characters
            safe_chars = set('0123456789+-*/()., ')
            if not all(c in safe_chars for c in expression):
                return {
                    "expression": expression,
                    "error": "Invalid characters in expression"
                }

            # Evaluate safely
            result = eval(expression, {"__builtins__": {}}, {})

            return {
                "expression": expression,
                "result": result
            }

        except Exception as e:
            return {
                "expression": expression,
                "error": str(e)
            }

    def get_usage_stats(self) -> Dict[str, int]:
        """Get tool usage statistics"""
        return self.usage_stats.copy()


# ============================================================================
# Individual Tool Classes
# ============================================================================


class GenerateEmbeddingTool(Tool):
    """Generate embeddings for text using AI models"""

    def __init__(self):
        super().__init__()
        self.name = "generate_embedding"
        self.description = "Generate vector embeddings for text using AI models"
        self.parameters = [
            RegistryToolParameter(
                name="text",
                type="string",
                description="Text to generate embeddings for",
                required=True
            ),
            RegistryToolParameter(
                name="model",
                type="string",
                description="Ignored; the substrate's local embedding model is always used (reported in the result)",
                required=False,
                default=""
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_embedding",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GENERATE_EMBEDDING,
                    description="Generate vector embeddings for semantic understanding",
                    input_types=["text"],
                    output_types=["embedding_vector"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                ),
                CapabilityMetadata(
                    capability=Capability.TRANSFORM_DATA,
                    description="Transform text into numerical vector representations",
                    input_types=["text"],
                    output_types=["vector"],
                    latency="low",
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

    async def execute(self, **kwargs) -> ToolResult:
        """Generate embeddings via the substrate's local embedding service."""
        text = kwargs.get("text", "")
        if not text:
            return ToolResult(success=False, output=None, error="text is required")

        try:
            from core.memory.utils.embedding_service import get_embedding_service
            service = get_embedding_service()

            embedding = service.generate_embedding(text)
            if embedding is None:
                return ToolResult(
                    success=False, output=None,
                    error="embedding unavailable: local embedding model not loaded"
                )

            return ToolResult(
                success=True,
                output={
                    "embeddings": embedding,
                    "model": service.model_name,
                    "dimensions": len(embedding),
                    "text_length": len(text),
                }
            )
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class RunInferenceTool(Tool):
    """Run ML model inference"""

    def __init__(self):
        super().__init__()
        self.name = "run_inference"
        self.description = "Run ML model inference on input data"
        self.parameters = [
            RegistryToolParameter(
                name="model_name",
                type="string",
                description="Name of the model to use",
                required=True
            ),
            RegistryToolParameter(
                name="input_data",
                type="object",
                description="Input data for inference",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="run_inference",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.RUN_INFERENCE,
                    description="Execute ML model inference on provided input",
                    input_types=["model_name", "input_data"],
                    output_types=["inference_result"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_EMBEDDING,
                    description="Generate predictions using ML models",
                    input_types=["model_name", "data"],
                    output_types=["prediction"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.SUMMARIZE_TEXT,
                    description="Summarize text using ML inference",
                    input_types=["text", "max_length"],
                    output_types=["summary"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Run inference on a named substrate model.

        The substrate hosts no general named-model runner. Its one locally
        runnable model is the embedder; reasoning is served by the reasoning
        tools. The old body ignored ``model_name`` entirely and forwarded the
        raw input to a chat model, reporting that as the requested inference.
        This reports the real faculties instead of faking one.
        """
        model_name = kwargs.get("model_name", "")

        if model_name in ("embedding", "embed", "text-embedding"):
            from core.memory.utils.embedding_service import get_embedding_service
            service = get_embedding_service()
            embedding = service.generate_embedding(str(kwargs.get("input_data", "")))
            if embedding is None:
                return ToolResult(success=False, output=None,
                                  error="embedding unavailable: local model not loaded")
            return ToolResult(
                success=True,
                output={"result": embedding, "model": service.model_name},
            )

        return ToolResult(
            success=False,
            output=None,
            error=(f"no model-free inference faculty for {model_name!r}; "
                   "the substrate runs a local embedding model (use generate_embedding) "
                   "and reasons via the reasoning tools"),
        )


class AnalyzeTrainingDataTool(Tool):
    """Analyze training data for quality and distribution"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_training_data"
        self.description = "Analyze training data for quality, distribution, and potential issues"
        self.parameters = [
            RegistryToolParameter(
                name="data",
                type="array",
                description="Training data to analyze",
                required=True
            ),
            RegistryToolParameter(
                name="data_type",
                type="string",
                description="Type of data (text, numerical, categorical)",
                required=False,
                default="text"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_training_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.VALIDATE_DATA,
                    description="Analyze training data quality and distribution",
                    input_types=["dataset", "data_type"],
                    output_types=["quality_analysis"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PERFORMANCE,
                    description="Assess dataset quality metrics and identify issues",
                    input_types=["dataset"],
                    output_types=["analysis_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.DETECT_ANOMALY,
                    description="Detect anomalies and quality issues in training data",
                    input_types=["dataset"],
                    output_types=["anomaly_report"],
                    latency="medium",
                    cost="low",
                    reliability="medium",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Analyze training data"""
        data = kwargs.get("data", [])
        data_type = kwargs.get("data_type", "text")

        try:
            analysis = {
                "total_samples": len(data),
                "data_type": data_type,
                "quality_score": 0.85,  # Placeholder
                "issues": [],
                "distribution": {
                    "balanced": True,
                    "samples_per_class": {}
                }
            }

            # Basic quality checks
            if len(data) < 100:
                analysis["issues"].append("Dataset may be too small for effective training")

            return ToolResult(
                success=True,
                output=analysis
            )
        except Exception as e:
            logger.error(f"Failed to analyze training data: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class GetModelInfoTool(Tool):
    """Get information about available AI models"""

    def __init__(self):
        super().__init__()
        self.name = "get_model_info"
        self.description = "Get information about available AI models and their capabilities"
        self.parameters = [
            RegistryToolParameter(
                name="model_name",
                type="string",
                description="Specific model name (optional)",
                required=False,
                default=""
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="get_model_info",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.GET_SYSTEM_INFO,
                    description="Get information about available AI models",
                    input_types=["model_name"],
                    output_types=["model_metadata"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.LIST_DATA,
                    description="List available models and their specifications",
                    input_types=[],
                    output_types=["model_list"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=6
                )
            ],
            requires_filesystem=False,
            requires_network=False,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Report the substrate's real model faculties."""
        model_name = kwargs.get("model_name", "")

        try:
            from core.memory.utils.embedding_service import get_embedding_service

            emb = get_embedding_service()

            available_models = {
                "embedding": {
                    "model": emb.model_name,
                    "dimensions": emb.embedding_dim,
                    "local": True,
                    "capabilities": ["embed_text", "semantic_similarity"],
                },
                "teacher": {
                    "role": "proposes lessons; the only generative-model consumer in the system",
                },
            }

            if model_name:
                info = available_models.get(model_name, {"error": f"no substrate model named {model_name!r}"})
            else:
                info = available_models

            return ToolResult(
                success=True,
                output={"models": info},
            )
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return ToolResult(success=False, output=None, error=str(e))


class SemanticSimilarityTool(Tool):
    """Calculate semantic similarity between texts"""

    def __init__(self):
        super().__init__()
        self.name = "semantic_similarity"
        self.description = "Calculate semantic similarity between two texts"
        self.parameters = [
            RegistryToolParameter(
                name="text1",
                type="string",
                description="First text",
                required=True
            ),
            RegistryToolParameter(
                name="text2",
                type="string",
                description="Second text",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="semantic_similarity",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.ANALYZE_SIMILARITY,
                    description="Calculate semantic similarity between two text inputs",
                    input_types=["text1", "text2"],
                    output_types=["similarity_score"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.ANALOGICAL_REASONING,
                    description="Compare conceptual similarity between texts",
                    input_types=["text1", "text2"],
                    output_types=["comparison_result"],
                    latency="low",
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

    async def execute(self, **kwargs) -> ToolResult:
        """Cosine similarity over the substrate's local embeddings."""
        text1 = kwargs.get("text1", "")
        text2 = kwargs.get("text2", "")

        try:
            from core.memory.utils.embedding_service import get_embedding_service
            service = get_embedding_service()

            emb1 = service.generate_embedding(text1)
            emb2 = service.generate_embedding(text2)
            if emb1 is None or emb2 is None:
                return ToolResult(
                    success=False, output=None,
                    error="semantic similarity unavailable: local embedding model not loaded",
                )

            import numpy as np
            v1, v2 = np.asarray(emb1), np.asarray(emb2)
            similarity = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

            return ToolResult(
                success=True,
                output={"similarity": similarity, "model": service.model_name}
            )
        except Exception as e:
            # A DIFFERENT METRIC IS NOT THIS METRIC. On failure this computed
            # word-overlap Jaccard and returned it as `similarity` with
            # success=True, so anything comparing scores across calls was
            # comparing embedding cosine against bag-of-words -- silently, and
            # only `method` said so. Nothing downstream reads `method`.
            logger.error("Semantic similarity unavailable: %s", e)
            return ToolResult(
                success=False,
                output=None,
                error=(f"semantic similarity unavailable: {e}. Word-overlap is "
                       f"a different measurement and is not substituted for it."),
            )


class ExtractEntitiesTool(Tool):
    """Extract named entities from text"""

    def __init__(self):
        super().__init__()
        self.name = "extract_entities"
        self.description = "Extract named entities (people, organizations, locations) from text"
        self.parameters = [
            RegistryToolParameter(
                name="text",
                type="string",
                description="Text to extract entities from",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_entities",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.EXTRACT_ENTITIES,
                    description="Extract named entities including people, organizations, locations, and dates",
                    input_types=["text"],
                    output_types=["entity_list"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                ),
                CapabilityMetadata(
                    capability=Capability.EXTRACT_PATTERNS,
                    description="Identify and extract structured patterns from text",
                    input_types=["text"],
                    output_types=["pattern_matches"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                ),
                CapabilityMetadata(
                    capability=Capability.PARSE_DATA,
                    description="Parse and categorize textual information",
                    input_types=["text"],
                    output_types=["parsed_entities"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ],
            requires_filesystem=False,
            requires_network=True,
            requires_database=False,
            is_idempotent=True
        )

    async def execute(self, **kwargs) -> ToolResult:
        """Extract entities — pattern/gazetteer NER via the language-ops faculty.

        Recall is bounded (it finds what its patterns cover), so an empty
        category means "no pattern matched", NOT a positive finding of none — a
        genuine failure still surfaces as success=False, never as an empty
        result dressed as a complete one.
        """
        text = kwargs.get("text", "")

        try:
            from core.semantics.language_ops import extract_entities

            entities = extract_entities(text)

            return ToolResult(
                success=True,
                output={"entities": entities}
            )
        except Exception as e:
            logger.error("Entity extraction failed: %s", e)
            return ToolResult(
                success=False,
                output=None,
                error=f"entity extraction failed: {e}",
            )


# Singleton instance
_ai_ml_tools = None


def get_ai_ml_tools() -> AIMLTools:
    """Get global AI/ML tools instance"""
    global _ai_ml_tools
    if _ai_ml_tools is None:
        _ai_ml_tools = AIMLTools()
    return _ai_ml_tools


# CLI test
async def main():
    """Test AI/ML tools"""
    logging.basicConfig(level=logging.INFO)

    tools = get_ai_ml_tools()

    print("\n=== AI/ML Tools Test ===")
    print(f"Registered tools: {len(tools.list_tools())}")

    # Test search tool
    result = await tools.execute_tool("search_web", {"query": "AI news", "num_results": 3})
    print(f"\nSearch result: {result['success']}")

    # Test sentiment analysis
    result = await tools.execute_tool("analyze_sentiment", {"text": "This is a great day!"})
    print(f"Sentiment: {result['result']['sentiment']}")

    # Test calculator
    result = await tools.execute_tool("calculate", {"expression": "2 + 2"})
    print(f"Calculator: {result['result']['result']}")

    # Get tool definitions for LLM
    definitions = tools.get_tool_definitions()
    print(f"\nTool definitions: {len(definitions)} tools")


if __name__ == "__main__":
    asyncio.run(main())
