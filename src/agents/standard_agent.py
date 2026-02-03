"""Standard agent implementation with LLM and tool execution.

StandardAgent is the default agent type that executes a multi-turn loop:
1. Render prompt with input
2. Call LLM
3. Parse tool calls from LLM response
4. Execute tools
5. Inject tool results back into prompt
6. Repeat until no more tool calls or max iterations reached
"""
import json
import re
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# XML tag constants for parsing LLM responses
TOOL_CALL_TAG = "tool_call"
ANSWER_TAG = "answer"
REASONING_TAGS = ["reasoning", "thinking", "think", "thought"]

# Pre-compiled regex patterns for performance (compiled once at module load)
TOOL_CALL_PATTERN = re.compile(rf'<{TOOL_CALL_TAG}>(.*?)</{TOOL_CALL_TAG}>', re.DOTALL)
ANSWER_PATTERN = re.compile(rf'<{ANSWER_TAG}>(.*?)</{ANSWER_TAG}>', re.DOTALL)
REASONING_PATTERNS = {
    tag: re.compile(f'<{tag}>(.*?)</{tag}>', re.DOTALL)
    for tag in REASONING_TAGS
}

# Default port numbers for LLM providers
# Rationale: These are standard default ports used by local installations
# - Ollama: 11434 is the default Ollama server port
# - OpenAI/Anthropic: Use HTTPS (443) via their public APIs
OLLAMA_DEFAULT_PORT = 11434

# Note: Cost estimation constants removed - now using config/model_pricing.yaml
# See src/agents/pricing.py for pricing configuration

from src.agents.base_agent import BaseAgent, AgentResponse, ExecutionContext
from src.agents.llm_providers import (
    BaseLLM,
    OllamaLLM,
    OpenAILLM,
    AnthropicLLM,
    LLMResponse,
    LLMError,
    LLMProvider
)
from src.agents.prompt_engine import PromptEngine, PromptRenderError
from src.agents.pricing import get_pricing_manager
from src.compiler.schemas import AgentConfig
from src.tools.registry import ToolRegistry
from src.tools.base import BaseTool, ToolResult


def validate_input_data(
    input_data: Any,
    context: Optional[ExecutionContext] = None
) -> None:
    """Validate input_data and context parameters.

    Centralized validation to ensure DRY principle across agent methods.

    Args:
        input_data: Input data dictionary to validate
        context: Optional execution context to validate

    Raises:
        ValueError: If input_data is None
        TypeError: If input_data is not a dictionary or context is invalid

    Example:
        >>> validate_input_data({"key": "value"})  # OK
        >>> validate_input_data(None)  # Raises ValueError
        >>> validate_input_data("string")  # Raises TypeError
    """
    # Validate input_data early for clear error messages
    if input_data is None:
        raise ValueError("input_data cannot be None")

    if not isinstance(input_data, dict):
        raise TypeError(
            f"input_data must be a dictionary, got {type(input_data).__name__}"
        )

    # Validate context if provided
    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(
            f"context must be an ExecutionContext instance, got {type(context).__name__}"
        )


class StandardAgent(BaseAgent):
    """Standard agent with LLM and tool execution loop.

    This is the primary agent implementation that handles:
    - Prompt rendering from templates
    - LLM inference with retry logic
    - Tool calling (function calling) parsing and execution
    - Multi-turn conversation for complex tasks
    - Token usage and cost tracking
    """

    def __init__(self, config: AgentConfig):
        """Initialize standard agent from configuration.

        Creates LLM provider, tool registry, and prompt engine from config.

        Args:
            config: Agent configuration schema
        """
        super().__init__(config)

        # Initialize prompt engine
        self.prompt_engine = PromptEngine()

        # Create LLM provider from config
        self.llm = self._create_llm_provider()

        # Create tool registry and load configured tools
        self.tool_registry = self._create_tool_registry()

        # Initialize prompt caching
        self._cached_tool_schemas: Optional[str] = None
        self._tool_registry_version: int = 0

        # Validate configuration
        self.validate_config()

    def _create_llm_provider(self) -> BaseLLM:
        """Create LLM provider from config.

        Returns:
            Initialized LLM provider instance

        Raises:
            ValueError: If provider type is unknown
        """
        inf_config = self.config.agent.inference
        provider_str = inf_config.provider.lower()

        # Convert string to enum
        try:
            provider = LLMProvider(provider_str)
        except ValueError:
            raise ValueError(f"Unknown LLM provider: {provider_str}")

        # Default base URLs for each provider
        default_base_urls = {
            LLMProvider.OLLAMA: f"http://localhost:{OLLAMA_DEFAULT_PORT}",
            LLMProvider.OPENAI: "https://api.openai.com/v1",
            LLMProvider.ANTHROPIC: "https://api.anthropic.com/v1",
        }

        # Provider class mapping
        provider_classes = {
            LLMProvider.OLLAMA: OllamaLLM,
            LLMProvider.OPENAI: OpenAILLM,
            LLMProvider.ANTHROPIC: AnthropicLLM,
        }

        if provider not in provider_classes:
            raise ValueError(f"Unknown LLM provider: {provider}")

        # Get provider class and default base URL
        provider_class = provider_classes[provider]
        base_url = inf_config.base_url or default_base_urls[provider]

        # Common parameters for all providers
        common_params: Dict[str, Any] = {
            "model": inf_config.model,
            "base_url": base_url,
            "temperature": inf_config.temperature,
            "max_tokens": inf_config.max_tokens,
            "top_p": inf_config.top_p,
            "timeout": inf_config.timeout_seconds,
            "max_retries": inf_config.max_retries,
            "retry_delay": float(inf_config.retry_delay_seconds),
        }

        # Add API key for providers that need it
        if provider in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC):
            common_params["api_key"] = inf_config.api_key

        return provider_class(**common_params)  # type: ignore[abstract]

    def _create_tool_registry(self) -> ToolRegistry:
        """Create tool registry and load configured tools.

        Loads only tools specified in agent config for better security and control.
        Falls back to auto-discovery if no tools configured.

        Returns:
            Tool registry with configured tools registered

        Raises:
            ValueError: If tool loading fails
        """
        registry = ToolRegistry(auto_discover=False)

        # Get configured tools from agent config
        configured_tools = self.config.agent.tools

        if not configured_tools:
            # No tools configured - use auto-discovery for backward compatibility
            registry.auto_discover()
        else:
            # Load specific tools from config
            self._load_tools_from_config(registry, configured_tools)

        return registry

    def _load_tools_from_config(
        self,
        registry: ToolRegistry,
        configured_tools: List[Any]
    ) -> None:
        """Load specific tools from configuration.

        Args:
            registry: Tool registry to register tools in
            configured_tools: List of tool names or ToolReference objects

        Raises:
            ValueError: If a configured tool cannot be loaded
        """
        # Mapping of tool names to their classes
        # This provides security by only allowing known, vetted tools
        AVAILABLE_TOOLS = {
            'WebScraper': 'src.tools.web_scraper.WebScraper',
            'Calculator': 'src.tools.calculator.Calculator',
            'FileWriter': 'src.tools.file_writer.FileWriter',
            'Bash': 'src.tools.bash.Bash',
        }

        for tool_spec in configured_tools:
            # Handle both string and ToolReference format
            tool_name: str
            tool_config: Dict[str, Any]
            if isinstance(tool_spec, str):
                tool_name = tool_spec
                tool_config = {}
            else:
                # ToolReference object with name and optional config
                tool_name = tool_spec.name
                tool_config = tool_spec.config if hasattr(tool_spec, 'config') else {}

            # Validate tool is in allowed list
            if tool_name not in AVAILABLE_TOOLS:
                raise ValueError(
                    f"Unknown tool '{tool_name}'. Available tools: {list(AVAILABLE_TOOLS.keys())}"
                )

            # Import and instantiate tool
            tool_module_path = AVAILABLE_TOOLS[tool_name]
            module_path, class_name = tool_module_path.rsplit('.', 1)

            try:
                import importlib
                module = importlib.import_module(module_path)
                tool_class = getattr(module, class_name)

                # Instantiate tool with optional configuration
                tool_instance = tool_class(config=tool_config)

                # Register with registry
                registry.register(tool_instance)

            except Exception as e:
                raise ValueError(
                    f"Failed to load tool '{tool_name}': {e}"
                )

    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Execute agent with input data.

        Main execution loop:
        1. Render prompt with input
        2. Call LLM
        3. Parse tool calls
        4. Execute tools
        5. Inject results and repeat
        6. Return final response

        Args:
            input_data: Input data dict (e.g., {"query": "...", "context": {...}})
            context: Optional execution context for tracking

        Returns:
            AgentResponse with output, tool calls, and metrics

        Raises:
            ValueError: If input_data is invalid
            TypeError: If input_data is not a dictionary
        """
        # Validate input_data and context using centralized helper
        validate_input_data(input_data, context)

        start_time = time.time()
        tool_calls_made: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        llm_response = None

        try:
            # Render initial prompt
            prompt = self._render_prompt(input_data, context)

            # Multi-turn tool calling loop
            max_iterations = self.config.agent.safety.max_tool_calls_per_execution

            for iteration in range(max_iterations):
                # Execute single iteration
                iteration_result = self._execute_iteration(
                    prompt, total_tokens, total_cost, tool_calls_made, start_time
                )

                # Check if iteration completed successfully
                if iteration_result["complete"]:
                    return iteration_result["response"]  # type: ignore[no-any-return]

                # Update state for next iteration
                llm_response = iteration_result["llm_response"]
                prompt = iteration_result["next_prompt"]
                total_tokens = iteration_result["total_tokens"]
                total_cost = iteration_result["total_cost"]
                tool_calls_made = iteration_result["tool_calls_made"]

            # Max iterations reached
            return self._build_final_response(
                output=llm_response.content if llm_response else "",
                reasoning=self._extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except Exception as e:
            # Unexpected error
            return self._build_final_response(
                output="",
                reasoning=None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Agent execution error: {str(e)}"
            )

    def _execute_iteration(
        self,
        prompt: str,
        total_tokens: int,
        total_cost: float,
        tool_calls_made: List[Dict[str, Any]],
        start_time: float
    ) -> Dict[str, Any]:
        """
        Execute single iteration of the tool calling loop.

        Args:
            prompt: Current prompt
            total_tokens: Accumulated token count
            total_cost: Accumulated cost
            tool_calls_made: List of all tool calls made so far
            start_time: Execution start time

        Returns:
            Dict with iteration results and state updates
        """
        # Call LLM — pass native tool definitions for providers that support it
        try:
            llm_kwargs: Dict[str, Any] = {}
            native_tools = self._get_native_tool_definitions()
            if native_tools:
                llm_kwargs["tools"] = native_tools
            llm_response = self.llm.complete(prompt, **llm_kwargs)
        except LLMError as e:
            # LLM call failed
            return {
                "complete": True,
                "response": self._build_final_response(
                    output="",
                    reasoning=None,
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=f"LLM call failed: {str(e)}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        total_cost += self._estimate_cost(llm_response)

        # Parse tool calls
        tool_calls = self._parse_tool_calls(llm_response.content)

        if not tool_calls:
            # No tools needed - done
            return {
                "complete": True,
                "response": self._build_final_response(
                    output=self._extract_final_answer(llm_response.content),
                    reasoning=self._extract_reasoning(llm_response.content),
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=None
                )
            }

        # Execute tools
        tool_results = self._execute_tool_calls(tool_calls)
        tool_calls_made.extend(tool_results)

        # Prepare next iteration
        next_prompt = self._inject_tool_results(prompt, llm_response.content, tool_results)

        return {
            "complete": False,
            "llm_response": llm_response,
            "next_prompt": next_prompt,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tool_calls_made": tool_calls_made
        }

    def _execute_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Execute a list of tool calls.

        Args:
            tool_calls: List of tool calls from LLM response

        Returns:
            List of tool results

        Raises:
            TypeError: If tool_calls is not a list
        """
        # Validate tool_calls
        if not isinstance(tool_calls, list):
            raise TypeError(
                f"tool_calls must be a list, got {type(tool_calls).__name__}"
            )

        tool_results = []
        for i, tool_call in enumerate(tool_calls):
            # Validate each tool call is a dict
            if not isinstance(tool_call, dict):
                raise TypeError(
                    f"tool_call at index {i} must be a dictionary, got {type(tool_call).__name__}"
                )

            tool_result = self._execute_single_tool(tool_call)
            tool_results.append(tool_result)
        return tool_results

    def _execute_single_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single tool call.

        Args:
            tool_call: Tool call dict with 'name' and 'parameters'

        Returns:
            Tool result dict

        Raises:
            TypeError: If tool_call is not a dictionary
            ValueError: If tool_call is missing required fields
        """
        # Validate tool_call structure
        if not isinstance(tool_call, dict):
            raise TypeError(
                f"tool_call must be a dictionary, got {type(tool_call).__name__}"
            )

        # Check for required 'name' field
        if "name" not in tool_call:
            raise ValueError(
                "tool_call must contain 'name' field"
            )

        tool_name = tool_call.get("name")
        tool_params = tool_call.get("parameters", tool_call.get("arguments", {}))

        # Validate tool_name is a string
        if not isinstance(tool_name, str):
            raise TypeError(
                f"tool_call 'name' must be a string, got {type(tool_name).__name__}"
            )

        # Validate tool_params is a dict
        if not isinstance(tool_params, dict):
            raise TypeError(
                f"tool_call 'parameters' must be a dictionary, got {type(tool_params).__name__}"
            )

        # Get tool from registry
        tool = self.tool_registry.get(tool_name) if tool_name else None
        if not tool:
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' not found",
                "success": False
            }

        # Execute tool
        try:
            result = tool.execute(**tool_params)
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": result.result if result.success else None,
                "error": result.error if not result.success else None,
                "success": result.success
            }
        except Exception as e:
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool execution error: {str(e)}",
                "success": False
            }

    def _build_final_response(
        self,
        output: str,
        reasoning: Optional[str],
        tool_calls: List[Dict[str, Any]],
        tokens: int,
        cost: float,
        start_time: float,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        """
        Build final AgentResponse.

        Args:
            output: Final output text
            reasoning: Extracted reasoning
            tool_calls: All tool calls made
            tokens: Total tokens used
            cost: Total cost
            start_time: Execution start time
            error: Error message if any
            metadata: Additional metadata

        Returns:
            AgentResponse
        """
        return AgentResponse(
            output=output,
            reasoning=reasoning,
            tool_calls=tool_calls,
            tokens=tokens,
            estimated_cost_usd=cost,
            latency_seconds=time.time() - start_time,
            error=error,
            metadata=metadata or {}
        )

    def _render_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> str:
        """Render prompt template with input data and tools.

        Args:
            input_data: User input data
            context: Optional execution context

        Returns:
            Rendered prompt string

        Raises:
            ValueError: If input_data is invalid or missing required fields
            TypeError: If input_data is not a dictionary
        """
        # Validate input_data and context using centralized helper
        validate_input_data(input_data, context)

        # Get template from config
        prompt_config = self.config.agent.prompt

        # Merge input_data with configured variables
        all_variables = {**input_data, **prompt_config.variables}

        if prompt_config.template:
            # Load from file (if templates directory exists)
            try:
                template = self.prompt_engine.render_file(
                    prompt_config.template,
                    all_variables
                )
            except Exception as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            # Render inline template
            template = self.prompt_engine.render(
                prompt_config.inline,
                all_variables
            )
        else:
            raise ValueError("No prompt template or inline prompt configured")

        # Add tool schemas to prompt (for function calling).
        # Skip text-based schemas when the LLM provider supports native tool
        # definitions (e.g., Ollama /api/chat with tools parameter), since the
        # schemas are passed structurally in the API request instead.
        if not self._get_native_tool_definitions():
            tools_section = self._get_cached_tool_schemas()
            if tools_section:
                template += tools_section

        return template

    def _get_cached_tool_schemas(self) -> Optional[str]:
        """Get cached tool schemas or build and cache them.

        Tool schemas are expensive to build (JSON serialization of all tools),
        so we cache them and only rebuild when the tool registry changes.

        Returns:
            Tool schemas section string or None if no tools
        """
        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

        # Check if cache is valid (tool registry hasn't changed)
        current_version = len(tools_dict)  # Simple version tracking
        if self._cached_tool_schemas is not None and self._tool_registry_version == current_version:
            # Cache hit
            return self._cached_tool_schemas

        # Cache miss or invalidated - rebuild
        tool_schemas = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.get_parameters_schema()
            }
            for tool in tools_dict.values()
        ]
        tools_section = "\n\nAvailable Tools:\n" + json.dumps(tool_schemas, indent=2)

        # Update cache
        self._cached_tool_schemas = tools_section
        self._tool_registry_version = current_version

        return tools_section

    def _get_native_tool_definitions(self) -> Optional[List[Dict[str, Any]]]:
        """Build native tool definitions for providers that support them.

        Converts framework tool schemas to the OpenAI-compatible format used
        by Ollama's /api/chat endpoint.

        Returns:
            List of tool dicts in OpenAI format, or None if no tools.
        """
        from src.agents.llm_providers import OllamaLLM

        # Only provide native tool defs for Ollama (which supports /api/chat tools)
        if not isinstance(self.llm, OllamaLLM):
            return None

        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

        native_tools = []
        for tool in tools_dict.values():
            schema = tool.get_parameters_schema()
            native_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema,
                },
            })

        return native_tools if native_tools else None

    def _parse_tool_calls(self, llm_response: str) -> List[Dict[str, Any]]:
        """Parse tool calls from LLM response.

        Looks for function calling format like:
        <tool_call>
        {"name": "calculator", "parameters": {"expression": "2+2"}}
        </tool_call>

        Args:
            llm_response: Raw LLM response text

        Returns:
            List of tool call dicts with 'name' and 'parameters' keys
        """
        tool_calls = []

        # Look for tool call tags using pre-compiled pattern
        matches = TOOL_CALL_PATTERN.findall(llm_response)

        for match in matches:
            try:
                tool_call = json.loads(match.strip())
                if "name" in tool_call:
                    tool_calls.append(tool_call)
            except json.JSONDecodeError:
                # Invalid JSON - skip
                continue

        return tool_calls

    def _inject_tool_results(
        self,
        original_prompt: str,
        llm_response: str,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """Inject tool results into prompt for next iteration.

        Args:
            original_prompt: Original prompt
            llm_response: LLM response with tool calls
            tool_results: Results from tool execution

        Returns:
            Updated prompt with tool results
        """
        # Build tool results section efficiently using list join
        results_parts = ["\n\nTool Results:\n"]
        for result in tool_results:
            results_parts.append(f"\nTool: {result['name']}\n")
            results_parts.append(f"Parameters: {json.dumps(result['parameters'])}\n")
            if result['success']:
                results_parts.append(f"Result: {result['result']}\n")
            else:
                results_parts.append(f"Error: {result['error']}\n")

        results_text = ''.join(results_parts)

        # Append to prompt
        return original_prompt + "\n\nAssistant: " + llm_response + results_text + "\n\nPlease continue:"

    def _extract_final_answer(self, llm_response: str) -> str:
        """Extract final answer from LLM response.

        Looks for <answer> tags or returns full response if not found.

        Args:
            llm_response: LLM response text

        Returns:
            Extracted answer
        """
        # Look for answer tag using pre-compiled pattern
        answer_match = ANSWER_PATTERN.search(llm_response)
        if answer_match:
            return answer_match.group(1).strip()

        # No explicit answer tag - return full response
        return llm_response.strip()

    def _extract_reasoning(self, llm_response: str) -> Optional[str]:
        """Extract reasoning/thought process from LLM response.

        Looks for <reasoning>, <thinking>, or <thought> tags.

        Args:
            llm_response: LLM response text

        Returns:
            Extracted reasoning or None
        """
        # Look for reasoning tags using pre-compiled patterns
        for tag in REASONING_TAGS:
            pattern = REASONING_PATTERNS[tag]
            match = pattern.search(llm_response)
            if match:
                return match.group(1).strip()

        return None

    def _estimate_cost(self, llm_response: LLMResponse) -> float:
        """Estimate cost of LLM call using configured pricing.

        Uses model-specific pricing from config/model_pricing.yaml.
        Falls back to default pricing for unknown models.

        Args:
            llm_response: LLM response with token counts

        Returns:
            Estimated cost in USD
        """
        if not llm_response.total_tokens:
            return 0.0

        # Get pricing manager
        pricing = get_pricing_manager()

        # Get model from response or fallback to LLM client's model
        model = llm_response.model or (getattr(self.llm, 'model', 'unknown'))

        # Get input/output tokens from response
        input_tokens = llm_response.prompt_tokens or 0
        output_tokens = llm_response.completion_tokens or 0

        # If split not available, estimate from total_tokens
        if input_tokens == 0 and output_tokens == 0 and llm_response.total_tokens:
            # Rough estimate: assume 60% input, 40% output (typical for agent interactions)
            total = llm_response.total_tokens
            input_tokens = int(total * 0.6)
            output_tokens = int(total * 0.4)

        return pricing.get_cost(model, input_tokens, output_tokens)

    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities.

        Returns:
            Dict describing agent capabilities
        """
        tools_list = self.tool_registry.list_tools()
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": "standard",
            "llm_provider": self.config.agent.inference.provider,
            "llm_model": self.config.agent.inference.model,
            "tools": tools_list,  # list_tools() already returns tool names
            "max_tool_calls": self.config.agent.safety.max_tool_calls_per_execution,
            "supports_streaming": False,
            "supports_multimodal": False
        }
