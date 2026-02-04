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
import logging
import re
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# XML tag constants for parsing LLM responses
TOOL_CALL_TAG = "tool_call"
ANSWER_TAG = "answer"
REASONING_TAGS = ["reasoning", "thinking", "think", "thought"]

# Pre-compiled regex patterns for performance (compiled once at module load)
TOOL_CALL_PATTERN = re.compile(rf'<{TOOL_CALL_TAG}>(.*?)</{TOOL_CALL_TAG}>', re.DOTALL)
ANSWER_PATTERN = re.compile(rf'<{ANSWER_TAG}>(.*?)</{ANSWER_TAG}>', re.DOTALL)

# Pattern to match structural tags in tool output (for sanitization) (AG-02)
# Covers: tool_call, answer, reasoning, thinking, think, thought,
# and role delimiters (Assistant:, User:, System:) that could be injected
_SANITIZE_TAGS = [TOOL_CALL_TAG, ANSWER_TAG] + REASONING_TAGS
_TOOL_RESULT_SANITIZE_PATTERN = re.compile(
    r'<\s*/?\s*(?:' + '|'.join(re.escape(t) for t in _SANITIZE_TAGS) + r')[^>]*>'
    r'|(?:^|\n)\s*(?:Assistant|User|System|Human)\s*:',
    re.IGNORECASE | re.MULTILINE,
)
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
        # Auto-discover tools if registry is empty
        # This populates the registry with all tools from src/tools/
        # No hardcoded mapping required - adding new tools is seamless
        if len(registry.list()) == 0:
            discovered_count = registry.auto_discover()
            if discovered_count == 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    "No tools discovered via auto-discovery. "
                    "Check that src/tools/ contains valid BaseTool subclasses."
                )

        # Get list of available tools for error messages
        available_tools = registry.list()

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

            # Try to get tool from registry (already discovered)
            tool_instance = registry.get(tool_name)

            if tool_instance is None:
                # Tool not found - provide helpful error message
                raise ValueError(
                    f"Unknown tool '{tool_name}'. Available tools: {available_tools}\n"
                    f"To add a new tool, create a BaseTool subclass in src/tools/"
                )

            # Tool found and already in registry from auto_discover()
            # Just log if tool_config provided (future enhancement)
            if tool_config:
                import logging
                logger = logging.getLogger(__name__)
                logger.debug(f"Tool config provided for {tool_name}: {tool_config}")
                # Note: Tool config handling could be enhanced to allow
                # per-agent tool customization

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

        # Store execution context for access in helper methods
        self._execution_context = context

        # Extract tool_executor from input_data if available (for safety-integrated execution)
        # This is passed through state by NodeBuilder when safety stack is initialized
        self.tool_executor = input_data.get('tool_executor', None)

        # Extract tracker from input_data if available (for direct observability reporting)
        # This is passed through state by executors to enable agent-level tracking
        self.tracker = input_data.get('tracker', None)

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

            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                # Enforce max_execution_time_seconds wall-clock limit
                elapsed = time.time() - start_time
                if elapsed >= max_execution_time:
                    return self._build_final_response(
                        output=llm_response.content if llm_response else "",
                        reasoning=self._extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made,
                        tokens=total_tokens,
                        cost=total_cost,
                        start_time=start_time,
                        error=f"Execution time limit exceeded ({max_execution_time}s)",
                        metadata={"elapsed_seconds": elapsed, "iteration": iteration}
                    )

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
            logger.warning(
                "Agent execution error: %s",
                str(e),
                exc_info=True
            )
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
        # Agent-level retry configuration
        inf_config = self.config.agent.inference
        max_agent_retries = inf_config.max_retries
        retry_delay = float(inf_config.retry_delay_seconds)

        # Safety validation for LLM calls (if policy engine available)
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            if self.tool_executor.policy_engine is not None:
                try:
                    import asyncio
                    from src.safety.action_policy_engine import PolicyExecutionContext

                    # Validate LLM call through policy engine (rate limiting, resource limits)
                    # Note: validate_action is async, so we use asyncio.run() to call it
                    validation_result = asyncio.run(
                        self.tool_executor.policy_engine.validate_action(
                            action={"type": "llm_call", "model": inf_config.model, "prompt_length": len(prompt)},
                            context=PolicyExecutionContext(
                                agent_id="agent",  # TODO: Get from execution context
                                workflow_id="workflow",  # TODO: Get from execution context
                                stage_id="stage",  # TODO: Get from execution context
                                action_type="llm_call",
                                action_data={"model": inf_config.model}
                            )
                        )
                    )

                    # Block if policy violations
                    if not validation_result.allowed:
                        violations_msg = "; ".join(v.message for v in validation_result.violations)
                        logger.warning(f"LLM call blocked by safety policy: {violations_msg}")
                        return {
                            "complete": True,
                            "response": self._build_final_response(
                                output="",
                                reasoning=None,
                                tool_calls=tool_calls_made,
                                tokens=total_tokens,
                                cost=total_cost,
                                start_time=start_time,
                                error=f"LLM call blocked by safety policy: {violations_msg}"
                            )
                        }
                except Exception as e:
                    # Log policy validation error but don't block execution
                    logger.warning(f"LLM call safety validation error: {e}")

        # Call LLM with agent-level retries
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):  # +1 for initial attempt
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = self._get_native_tool_definitions()
                if native_tools:
                    llm_kwargs["tools"] = native_tools
                llm_response = self.llm.complete(prompt, **llm_kwargs)
                break  # Success - exit retry loop

            except LLMError as e:
                last_error = e

                # Check if we should retry
                if attempt < max_agent_retries:
                    # Calculate backoff delay (exponential with base 2.0)
                    backoff_delay = retry_delay * (2.0 ** attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1,
                        max_agent_retries + 1,
                        str(e),
                        backoff_delay
                    )
                    time.sleep(backoff_delay)
                else:
                    # Max retries exhausted
                    logger.error(
                        "LLM call failed after %d attempts: %s",
                        max_agent_retries + 1,
                        str(e),
                        exc_info=True
                    )

        # If all retries failed, return error response
        if llm_response is None:
            return {
                "complete": True,
                "response": self._build_final_response(
                    output="",
                    reasoning=None,
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {str(last_error)}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        total_cost += self._estimate_cost(llm_response)

        # Track LLM call for observability (if tracker and context available)
        if self.tracker is not None and hasattr(self, '_execution_context') and self._execution_context is not None:
            if self._execution_context.agent_id:
                try:
                    # Calculate latency from LLM response metadata
                    latency_ms = int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0

                    self.tracker.track_llm_call(
                        agent_id=self._execution_context.agent_id,
                        provider=inf_config.provider.value,
                        model=inf_config.model,
                        prompt=prompt,
                        response=llm_response.content,
                        prompt_tokens=llm_response.prompt_tokens or 0,
                        completion_tokens=llm_response.completion_tokens or 0,
                        latency_ms=latency_ms,
                        estimated_cost_usd=self._estimate_cost(llm_response),
                        temperature=inf_config.temperature,
                        max_tokens=inf_config.max_tokens,
                        status="success"
                    )
                except Exception as e:
                    # Log but don't fail execution for tracking errors
                    logger.warning(f"Failed to track LLM call: {e}")

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

        # Route through ToolExecutor if available (safety-integrated execution)
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            # Use ToolExecutor which handles:
            # - Policy validation (FileAccess, SecretDetection, ForbiddenOperations, etc.)
            # - Approval workflow (human-in-the-loop)
            # - Rollback snapshots (pre-action recovery)
            # - Rate limiting and resource limits
            tool_start_time = time.time()
            try:
                result = self.tool_executor.execute(tool_name, tool_params)
                duration_seconds = time.time() - tool_start_time

                # Track tool call for observability
                if self.tracker is not None and hasattr(self, '_execution_context') and self._execution_context is not None:
                    if self._execution_context.agent_id:
                        try:
                            self.tracker.track_tool_call(
                                agent_id=self._execution_context.agent_id,
                                tool_name=tool_name,
                                input_params=tool_params,
                                output_data={"result": result.result} if result.success else {},
                                duration_seconds=duration_seconds,
                                status="success" if result.success else "failed",
                                error_message=result.error if not result.success else None
                            )
                        except Exception as e:
                            # Log but don't fail execution for tracking errors
                            logger.warning(f"Failed to track tool call: {e}")

                return {
                    "name": tool_name,
                    "parameters": tool_params,
                    "result": result.result if result.success else None,
                    "error": result.error if not result.success else None,
                    "success": result.success
                }
            except Exception as e:
                duration_seconds = time.time() - tool_start_time

                # Track failed tool call
                if self.tracker is not None and hasattr(self, '_execution_context') and self._execution_context is not None:
                    if self._execution_context.agent_id:
                        try:
                            self.tracker.track_tool_call(
                                agent_id=self._execution_context.agent_id,
                                tool_name=tool_name,
                                input_params=tool_params,
                                output_data={},
                                duration_seconds=duration_seconds,
                                status="failed",
                                error_message=f"Tool execution error: {str(e)}"
                            )
                        except Exception as track_e:
                            # Log but don't fail execution for tracking errors
                            logger.warning(f"Failed to track tool call: {track_e}")

                return {
                    "name": tool_name,
                    "parameters": tool_params,
                    "result": None,
                    "error": f"Tool execution error: {str(e)}",
                    "success": False
                }

        # Fallback: Direct tool execution with inline safety checks
        # (Used when tool_executor not available - backward compatibility)
        tool = self.tool_registry.get(tool_name) if tool_name else None
        if not tool:
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' not found",
                "success": False
            }

        # Enforce safety config before execution
        safety = self.config.agent.safety

        # Check require_approval mode: block all tool execution
        if safety.mode == "require_approval":
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' blocked: safety mode is 'require_approval'",
                "success": False
            }

        # Check tool-specific approval list (independent of mode)
        if tool_name in safety.require_approval_for_tools:
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' requires approval before execution",
                "success": False
            }

        # Check dry_run mode: return simulated result without executing
        if safety.mode == "dry_run":
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": f"[DRY RUN] Tool '{tool_name}' would be executed with parameters: {tool_params}",
                "error": None,
                "success": True
            }

        # Execute tool (mode == "execute")
        tool_start_time = time.time()
        try:
            result = tool.execute(**tool_params)
            duration_seconds = time.time() - tool_start_time

            # Track tool call for observability
            if self.tracker is not None and hasattr(self, '_execution_context') and self._execution_context is not None:
                if self._execution_context.agent_id:
                    try:
                        self.tracker.track_tool_call(
                            agent_id=self._execution_context.agent_id,
                            tool_name=tool_name,
                            input_params=tool_params,
                            output_data={"result": result.result} if result.success else {},
                            duration_seconds=duration_seconds,
                            status="success" if result.success else "failed",
                            error_message=result.error if not result.success else None
                        )
                    except Exception as e:
                        # Log but don't fail execution for tracking errors
                        logger.warning(f"Failed to track tool call: {e}")

            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": result.result if result.success else None,
                "error": result.error if not result.success else None,
                "success": result.success
            }
        except Exception as e:
            duration_seconds = time.time() - tool_start_time

            # Track failed tool call
            if self.tracker is not None and hasattr(self, '_execution_context') and self._execution_context is not None:
                if self._execution_context.agent_id:
                    try:
                        self.tracker.track_tool_call(
                            agent_id=self._execution_context.agent_id,
                            tool_name=tool_name,
                            input_params=tool_params,
                            output_data={},
                            duration_seconds=duration_seconds,
                            status="failed",
                            error_message=f"Tool execution error: {str(e)}"
                        )
                    except Exception as track_e:
                        # Log but don't fail execution for tracking errors
                        logger.warning(f"Failed to track tool call: {track_e}")

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
        by Ollama, OpenAI, and Anthropic APIs.

        Returns:
            List of tool dicts in OpenAI format, or None if no tools.
        """
        from src.agents.llm_providers import OllamaLLM, OpenAILLM, AnthropicLLM

        # Provide native tool definitions for providers that support function calling
        # OpenAI and Anthropic support is added in Wave 3 (Issue #6)
        if not isinstance(self.llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
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

    @staticmethod
    def _sanitize_tool_output(text: str) -> str:
        """Escape tool_call tags in tool output to prevent prompt injection.

        Tool results are injected into the prompt and re-parsed by the LLM.
        If a tool returns text containing <tool_call>...</tool_call>, the
        parser would treat it as a real tool invocation. This escapes those
        tags so they are treated as literal text.

        Args:
            text: Raw tool output string

        Returns:
            Sanitized string with tool_call tags escaped
        """
        if not isinstance(text, str):
            text = str(text)
        return _TOOL_RESULT_SANITIZE_PATTERN.sub(
            lambda m: m.group(0).replace('<', '&lt;').replace('>', '&gt;'),
            text,
        )

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
        # Maximum size per tool result to prevent context window blowout
        # Default: 10KB per result (~2500 tokens)
        MAX_TOOL_RESULT_SIZE = 10_000  # characters

        # Build tool results section efficiently using list join
        results_parts = ["\n\nTool Results:\n"]
        for result in tool_results:
            results_parts.append(f"\nTool: {result['name']}\n")
            results_parts.append(f"Parameters: {json.dumps(result['parameters'])}\n")
            if result['success']:
                safe_result = self._sanitize_tool_output(str(result['result']))

                # Truncate if result exceeds max size
                if len(safe_result) > MAX_TOOL_RESULT_SIZE:
                    original_size = len(safe_result)
                    safe_result = safe_result[:MAX_TOOL_RESULT_SIZE]
                    safe_result += f"\n[truncated — {original_size:,} total chars, showing first {MAX_TOOL_RESULT_SIZE:,}]"

                results_parts.append(f"Result: {safe_result}\n")
            else:
                safe_error = self._sanitize_tool_output(str(result['error']))

                # Truncate error messages too (though they're usually small)
                if len(safe_error) > MAX_TOOL_RESULT_SIZE:
                    original_size = len(safe_error)
                    safe_error = safe_error[:MAX_TOOL_RESULT_SIZE]
                    safe_error += f"\n[truncated — {original_size:,} total chars, showing first {MAX_TOOL_RESULT_SIZE:,}]"

                results_parts.append(f"Error: {safe_error}\n")

        results_text = ''.join(results_parts)

        # AG-05: Truncate prompt to prevent unbounded growth in multi-turn loop.
        # Keep the original system prompt prefix and only the most recent exchange.
        MAX_PROMPT_CHARS = 100_000  # ~25k tokens as a safe upper bound
        new_prompt = original_prompt + "\n\nAssistant: " + llm_response + results_text + "\n\nPlease continue:"
        if len(new_prompt) > MAX_PROMPT_CHARS:
            # Keep the last MAX_PROMPT_CHARS characters to preserve the most recent context
            new_prompt = "...(truncated)...\n" + new_prompt[-MAX_PROMPT_CHARS:]
        return new_prompt

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
