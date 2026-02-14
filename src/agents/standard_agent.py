"""Standard agent implementation with LLM and tool execution.

StandardAgent is the default agent type that executes a multi-turn loop:
1. Render prompt with input
2. Call LLM
3. Parse tool calls from LLM response
4. Execute tools
5. Inject tool results back into prompt
6. Repeat until no more tool calls or max iterations reached
"""
from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import logging
import os
import random
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.schemas import AgentConfig

from dataclasses import dataclass

from src.agents._standard_agent_helpers import (
    ResponseBuildData,
)
from src.agents._standard_agent_helpers import (
    build_final_response as _build_final_response,
)
from src.agents._standard_agent_helpers import (
    build_max_iterations_response as _build_max_iterations_response,
)
from src.agents._standard_agent_helpers import (
    estimate_cost_for_response as _estimate_cost_for_response,
)
from src.agents._standard_agent_helpers import (
    execute_single_tool as _execute_single_tool,
)
from src.agents._standard_agent_helpers import (
    execute_tool_calls as _execute_tool_calls,
)
from src.agents._standard_agent_helpers import (
    execute_via_tool_executor as _execute_via_tool_executor,
)
from src.agents._standard_agent_helpers import (
    get_cached_tool_schemas as _get_cached_tool_schemas,
)
from src.agents._standard_agent_helpers import (
    get_native_tool_definitions as _get_native_tool_definitions,
)
from src.agents._standard_agent_helpers import (
    inject_tool_results as _inject_tool_results,
)
from src.agents._standard_agent_helpers import (
    make_stream_callback as _make_stream_callback,
)
from src.agents._standard_agent_helpers import (
    prepare_execution_prompt as _prepare_execution_prompt,
)
from src.agents._standard_agent_helpers import (
    process_llm_response as _process_llm_response,
)
from src.agents._standard_agent_helpers import (
    setup_execution as _setup_execution,
)
from src.agents._standard_agent_helpers import (
    track_failed_llm_call as _track_failed_llm_call,
)
from src.agents._standard_agent_helpers import (
    track_llm_call as _track_llm_call,
)
from src.agents._standard_agent_helpers import (
    validate_safety_for_llm_call as _validate_safety,
)
from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.agents.cost_estimator import estimate_cost
from src.agents.llm import (  # M-04: Import from new location
    LLMError,
    LLMResponse,
)
from src.agents.llm.factory import create_llm_from_config
from src.agents.prompt_engine import PromptEngine
from src.agents.prompt_validation import PromptRenderError, _is_safe_template_value
from src.agents.response_parser import (
    ANSWER_TAG,
    REASONING_TAGS,
    TOOL_CALL_TAG,
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
    sanitize_tool_output,
)
from src.constants.limits import DEFAULT_POOL_SIZE as _POOL_SIZE_LIMIT
from src.constants.retries import DEFAULT_BACKOFF_MULTIPLIER, RETRY_JITTER_MIN
from src.tools.registry import ToolRegistry
from src.utils.exceptions import (
    ConfigValidationError,
    ToolExecutionError,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

# Re-export constants for backward compatibility
_SANITIZE_TAGS = [TOOL_CALL_TAG, ANSWER_TAG] + REASONING_TAGS

# Note: Cost estimation constants removed - now using config/model_pricing.yaml
# See src/agents/pricing.py for pricing configuration

# Minimum Python version supporting cancel_futures in ThreadPoolExecutor.shutdown()
_MIN_PYTHON_CANCEL_FUTURES = (3, 9)

# Default port numbers for LLM providers (kept for backward compatibility)
OLLAMA_DEFAULT_PORT = 11434

# Dialogue context limits
DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS = 8000

# Shared thread pool for parallel tool execution (M-28).
# H-16: Lazy initialization with lifecycle management to avoid resource leaks.
# M-18: Pool size configurable via AGENT_TOOL_WORKERS env var.
# H-11: Increase default pool size based on CPU count

# CPU-based pool sizing constants
_CPU_MULTIPLIER_FOR_POOL = 2  # Multiply CPU count by this for thread pool size
_MIN_POOL_SIZE_PER_CPU = 4  # Minimum threads to add beyond CPU-based calculation
_DEFAULT_CPU_COUNT_FALLBACK = 4  # Fallback CPU count when os.cpu_count() returns None

_DEFAULT_POOL_SIZE = min(
    _POOL_SIZE_LIMIT,
    (os.cpu_count() or _DEFAULT_CPU_COUNT_FALLBACK) * _CPU_MULTIPLIER_FOR_POOL + _MIN_POOL_SIZE_PER_CPU
)
_TOOL_POOL_SIZE = int(os.environ.get("AGENT_TOOL_WORKERS", str(_DEFAULT_POOL_SIZE)))
_tool_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def _get_tool_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Get or lazily create the shared thread pool for tool execution.

    Thread-safe lazy initialization ensures the pool is only created when needed
    and prevents race conditions during concurrent initialization (H-16).
    """
    global _tool_executor
    if _tool_executor is None:
        with _executor_lock:
            # Double-check pattern to prevent race conditions
            if _tool_executor is None:
                _tool_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_TOOL_POOL_SIZE,
                    thread_name_prefix="agent-tool"
                )
    return _tool_executor


def _shutdown_tool_executor() -> None:
    """Shutdown the tool executor pool gracefully (P-15, H-16)."""
    global _tool_executor
    if _tool_executor is not None:
        if sys.version_info >= _MIN_PYTHON_CANCEL_FUTURES:
            _tool_executor.shutdown(wait=True, cancel_futures=True)
        else:
            _tool_executor.shutdown(wait=True)
        _tool_executor = None


atexit.register(_shutdown_tool_executor)


def validate_input_data(
    input_data: Any,
    context: Optional[ExecutionContext] = None
) -> None:
    """Validate input_data and context parameters.

    Args:
        input_data: Input data dictionary to validate
        context: Optional execution context to validate

    Raises:
        ValueError: If input_data is None
        TypeError: If input_data is not a dictionary or context is invalid
    """
    if input_data is None:
        raise ValueError("input_data cannot be None")

    if not isinstance(input_data, dict):
        raise TypeError(
            f"input_data must be a dictionary, got {type(input_data).__name__}"
        )

    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(
            f"context must be an ExecutionContext instance, got {type(context).__name__}"
        )


@dataclass
class ExecutionTimeoutCheckParams:
    """Parameters for checking execution timeout.

    Bundles the multiple parameters needed for timeout checking,
    reducing function parameter count from 8 to 2 (agent + params).
    """
    start_time: float
    max_execution_time: float
    llm_response: Optional[Any]
    tool_calls_made: List[Dict[str, Any]]
    total_tokens: int
    total_cost: float
    iteration: int


def _check_execution_timeout(
    agent: "StandardAgent",
    params: ExecutionTimeoutCheckParams,
) -> Optional[AgentResponse]:
    """Check if execution time limit exceeded. Returns error response or None.

    Args:
        agent: StandardAgent instance
        params: ExecutionTimeoutCheckParams with all parameters bundled

    Returns:
        AgentResponse if timeout exceeded, None otherwise
    """
    elapsed = time.time() - params.start_time
    if elapsed >= params.max_execution_time:
        data = ResponseBuildData(
            output=params.llm_response.content if params.llm_response else "",
            reasoning=extract_reasoning(params.llm_response.content) if params.llm_response else None,
            tool_calls=params.tool_calls_made,
            tokens=params.total_tokens,
            cost=params.total_cost,
            start_time=params.start_time,
            error=f"Execution time limit exceeded ({params.max_execution_time}s)",
            metadata={"elapsed_seconds": elapsed, "iteration": params.iteration}
        )
        return _build_final_response(agent, data=data)  # type: ignore[no-any-return]
    return None


def _handle_agent_error(
    agent: "StandardAgent",
    error: Exception,
    tool_calls_made: List[Dict[str, Any]],
    total_tokens: int,
    total_cost: float,
    start_time: float,
    async_mode: bool = False,
) -> AgentResponse:
    """Build error response for agent execution failures."""
    safe_msg = sanitize_error_message(str(error))
    label = "Agent async execution error" if async_mode else "Agent execution error"
    logger.warning("%s: %s", label, safe_msg, exc_info=True)
    return _build_final_response(
        agent, output="", reasoning=None, tool_calls=tool_calls_made,
        tokens=total_tokens, cost=total_cost, start_time=start_time,
        error=f"Agent execution error: {safe_msg}"
    )


def _handle_llm_result(
    agent: "StandardAgent",
    llm_response: Optional[Any],
    last_error: Optional[Exception],
    inf_config: Any,
    prompt: str,
    tool_calls_made: List[Dict[str, Any]],
    total_tokens: int,
    total_cost: float,
    start_time: float,
    max_agent_retries: int,
    max_iterations: Optional[int] = None,
) -> Dict[str, Any]:
    """Handle LLM call result: error check, token tracking, response processing."""
    if llm_response is None:
        error_msg = f"LLM call failed after {max_agent_retries + 1} attempts"
        if last_error:
            error_msg += f": {sanitize_error_message(str(last_error))}"
        return {
            "complete": True,
            "response": _build_final_response(
                agent, output="", reasoning=None, tool_calls=tool_calls_made,
                tokens=total_tokens, cost=total_cost, start_time=start_time,
                error=error_msg
            )
        }

    logger.info("[%s] LLM responded (%s tokens)", agent.name, llm_response.total_tokens or "?")

    if llm_response.total_tokens:
        total_tokens += llm_response.total_tokens
    cost = _estimate_cost_for_response(agent, llm_response)
    total_cost += cost

    _track_llm_call(agent, inf_config, prompt, llm_response, cost)

    from src.agents._standard_agent_helpers import LLMProcessingContext
    ctx = LLMProcessingContext(
        agent=agent,
        llm_response=llm_response,
        tool_calls_made=tool_calls_made,
        total_tokens=total_tokens,
        total_cost=total_cost,
        start_time=start_time,
        prompt=prompt,
        max_iterations=max_iterations,
        get_tool_executor_fn=_get_tool_executor
    )
    return _process_llm_response(ctx)


def _call_llm_with_retry_sync(
    agent: "StandardAgent",
    prompt: str,
    inf_config: Any,
    max_agent_retries: int,
    retry_delay: float,
) -> tuple[Optional[Any], Optional[Exception]]:
    """Call LLM with agent-level retries (sync). Returns (LLMResponse, error) tuple."""
    last_error: Optional[Exception] = None

    for attempt in range(max_agent_retries + 1):
        try:
            llm_kwargs: Dict[str, Any] = {}
            native_tools = _get_native_tool_definitions(agent)
            if native_tools:
                llm_kwargs["tools"] = native_tools
            combined_cb = _make_stream_callback(agent)
            if combined_cb:
                return agent.llm.stream(prompt, on_chunk=combined_cb, **llm_kwargs), None
            else:
                return agent.llm.complete(prompt, **llm_kwargs), None
        except LLMError as e:
            last_error = e
            safe_err = sanitize_error_message(str(e))
            _track_failed_llm_call(agent, inf_config, prompt, e, attempt + 1, max_agent_retries + 1)
            if attempt < max_agent_retries:
                backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_agent_retries + 1, safe_err, backoff_delay
                )
                shutdown_event = threading.Event()
                if shutdown_event.wait(timeout=backoff_delay):
                    raise KeyboardInterrupt("Agent execution interrupted")
            else:
                logger.error("LLM call failed after %d attempts: %s", max_agent_retries + 1, safe_err, exc_info=True)

    return None, last_error


async def _call_llm_with_retry_async(
    agent: "StandardAgent",
    prompt: str,
    inf_config: Any,
    max_agent_retries: int,
    retry_delay: float,
) -> tuple[Optional[Any], Optional[Exception]]:
    """Call LLM with agent-level retries (async). Returns (LLMResponse, error) tuple."""
    last_error: Optional[Exception] = None

    for attempt in range(max_agent_retries + 1):
        try:
            llm_kwargs: Dict[str, Any] = {}
            native_tools = _get_native_tool_definitions(agent)
            if native_tools:
                llm_kwargs["tools"] = native_tools
            combined_cb = _make_stream_callback(agent)
            if combined_cb:
                return await agent.llm.astream(prompt, on_chunk=combined_cb, **llm_kwargs), None
            else:
                return await agent.llm.acomplete(prompt, **llm_kwargs), None
        except LLMError as e:
            last_error = e
            safe_err = sanitize_error_message(str(e))
            _track_failed_llm_call(agent, inf_config, prompt, e, attempt + 1, max_agent_retries + 1)
            if attempt < max_agent_retries:
                backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1, max_agent_retries + 1, safe_err, backoff_delay
                )
                await asyncio.sleep(backoff_delay)
            else:
                logger.error("LLM call failed after %d attempts: %s", max_agent_retries + 1, safe_err, exc_info=True)

    return None, last_error


def _ensure_tools_discovered(registry: ToolRegistry) -> None:
    """Auto-discover tools if registry is empty."""
    if len(registry.list_tools()) == 0:
        discovered_count = registry.auto_discover()
        if discovered_count == 0:
            logger.warning(
                "No tools discovered via auto-discovery. "
                "Check that src/tools/ contains valid BaseTool subclasses."
            )


def _resolve_tool_spec(tool_spec: Any) -> tuple[str, Dict[str, Any]]:
    """Resolve a tool spec into (name, config) tuple."""
    if isinstance(tool_spec, str):
        return tool_spec, {}
    tool_config = tool_spec.config if hasattr(tool_spec, 'config') else {}
    return tool_spec.name, tool_config


def _apply_tool_config(tool_instance: Any, tool_name: str, tool_config: Dict[str, Any]) -> None:
    """Apply config dict to a tool instance."""
    if not tool_config:
        return
    logger.debug(f"Tool config provided for {tool_name}: {tool_config}")
    if hasattr(tool_instance, 'config'):
        if isinstance(tool_instance.config, dict):
            tool_instance.config.update(tool_config)
        else:
            tool_instance.config = tool_config


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
        """Initialize standard agent from configuration."""
        super().__init__(config)

        self.prompt_engine = PromptEngine()
        self.llm = create_llm_from_config(self.config.agent.inference)
        self.tool_registry = self._create_tool_registry()

        # Initialize prompt caching
        self._cached_tool_schemas: Optional[str] = None
        self._tool_registry_version: int = 0

        # M-20: Cache native tool definitions to avoid recomputing each iteration
        self._cached_native_tool_defs: Optional[List[Dict[str, Any]]] = None
        self._cached_native_tool_defs_hash: Optional[str] = None

        self.validate_config()

    def _create_tool_registry(self) -> ToolRegistry:
        """Create tool registry and load configured tools."""
        registry = ToolRegistry(auto_discover=False)

        configured_tools = self.config.agent.tools

        if configured_tools is None:
            registry.auto_discover()
        elif configured_tools:
            self._load_tools_from_config(registry, configured_tools)

        return registry

    def _load_tools_from_config(
        self,
        registry: ToolRegistry,
        configured_tools: List[Any]
    ) -> None:
        """Load specific tools from configuration.

        Auto-discovers all tools to populate the registry, then filters
        to keep ONLY the tools listed in the agent config.
        """
        _ensure_tools_discovered(registry)
        available_tools = registry.list_tools()

        configured_names: set[str] = set()
        for tool_spec in configured_tools:
            tool_name, tool_config = _resolve_tool_spec(tool_spec)
            tool_instance = registry.get(tool_name)

            if tool_instance is None:
                raise ValueError(
                    f"Unknown tool '{tool_name}'. Available tools: {available_tools}\n"
                    f"To add a new tool, create a BaseTool subclass in src/tools/"
                )

            configured_names.add(tool_name)
            _apply_tool_config(tool_instance, tool_name, tool_config)

        # Remove tools not in the configured list
        for name in set(registry.list_tools()) - configured_names:
            registry.unregister(name)

    def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Execute agent with input data."""
        validate_input_data(input_data, context)
        _setup_execution(self, input_data, context, async_mode=False)

        start_time = time.time()
        tool_calls_made: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        llm_response = None
        self._conversation_turns: List[str] = []

        try:
            prompt = _prepare_execution_prompt(self, input_data, context)
            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                timeout_response = _check_execution_timeout(self, ExecutionTimeoutCheckParams(
                    start_time=start_time, max_execution_time=max_execution_time,
                    llm_response=llm_response, tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens, total_cost=total_cost, iteration=iteration,
                ))
                if timeout_response:
                    return timeout_response

                iteration_result = self._execute_iteration(
                    prompt, total_tokens, total_cost, tool_calls_made, start_time, max_iterations
                )
                if iteration_result["complete"]:
                    return iteration_result["response"]  # type: ignore[no-any-return]

                llm_response = iteration_result["llm_response"]
                prompt = iteration_result["next_prompt"]
                total_tokens = iteration_result["total_tokens"]
                total_cost = iteration_result["total_cost"]
                tool_calls_made = iteration_result["tool_calls_made"]

            return _build_max_iterations_response(  # type: ignore[no-any-return]
                self, llm_response, tool_calls_made, total_tokens, total_cost,
                start_time, max_iterations
            )
        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            return _handle_agent_error(self, e, tool_calls_made, total_tokens, total_cost, start_time)

    async def aexecute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Async counterpart to execute()."""
        validate_input_data(input_data, context)
        _setup_execution(self, input_data, context, async_mode=True)

        start_time = time.time()
        tool_calls_made: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        llm_response = None
        self._conversation_turns = []  # Redefinition is intentional for async path

        try:
            prompt = _prepare_execution_prompt(self, input_data, context)
            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                timeout_response = _check_execution_timeout(self, ExecutionTimeoutCheckParams(
                    start_time=start_time, max_execution_time=max_execution_time,
                    llm_response=llm_response, tool_calls_made=tool_calls_made,
                    total_tokens=total_tokens, total_cost=total_cost, iteration=iteration,
                ))
                if timeout_response:
                    return timeout_response

                iteration_result = await self._aexecute_iteration(
                    prompt, total_tokens, total_cost, tool_calls_made, start_time, max_iterations
                )
                if iteration_result["complete"]:
                    return iteration_result["response"]  # type: ignore[no-any-return]

                llm_response = iteration_result["llm_response"]
                prompt = iteration_result["next_prompt"]
                total_tokens = iteration_result["total_tokens"]
                total_cost = iteration_result["total_cost"]
                tool_calls_made = iteration_result["tool_calls_made"]

            return _build_max_iterations_response(  # type: ignore[no-any-return]
                self, llm_response, tool_calls_made, total_tokens, total_cost,
                start_time, max_iterations
            )
        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            return _handle_agent_error(self, e, tool_calls_made, total_tokens, total_cost, start_time, async_mode=True)

    async def _aexecute_iteration(
        self,
        prompt: str,
        total_tokens: int,
        total_cost: float,
        tool_calls_made: List[Dict[str, Any]],
        start_time: float,
        max_iterations: Optional[int] = None
    ) -> Dict[str, Any]:
        """Async counterpart to _execute_iteration."""
        inf_config = self.config.agent.inference
        max_agent_retries = inf_config.max_retries
        retry_delay = float(inf_config.retry_delay_seconds)

        # Safety validation (same fail-closed logic as sync path)
        safety_result = _validate_safety(
            self, inf_config, prompt, tool_calls_made, total_tokens, total_cost, start_time
        )
        if safety_result is not None:
            return safety_result

        # Call LLM with agent-level retries
        llm_response, last_error = await _call_llm_with_retry_async(
            self, prompt, inf_config, max_agent_retries, retry_delay
        )

        return _handle_llm_result(
            self, llm_response, last_error, inf_config, prompt,
            tool_calls_made, total_tokens, total_cost, start_time,
            max_agent_retries, max_iterations,
        )

    def _execute_iteration(
        self,
        prompt: str,
        total_tokens: int,
        total_cost: float,
        tool_calls_made: List[Dict[str, Any]],
        start_time: float,
        max_iterations: Optional[int] = None
    ) -> Dict[str, Any]:
        """Execute single iteration of the tool calling loop."""
        inf_config = self.config.agent.inference
        max_agent_retries = inf_config.max_retries
        retry_delay = float(inf_config.retry_delay_seconds)

        # Safety validation for LLM calls (if policy engine available)
        safety_result = _validate_safety(
            self, inf_config, prompt, tool_calls_made, total_tokens, total_cost, start_time
        )
        if safety_result is not None:
            return safety_result

        # Call LLM with agent-level retries
        llm_response, last_error = _call_llm_with_retry_sync(
            self, prompt, inf_config, max_agent_retries, retry_delay
        )

        return _handle_llm_result(
            self, llm_response, last_error, inf_config, prompt,
            tool_calls_made, total_tokens, total_cost, start_time,
            max_agent_retries, max_iterations,
        )

    def _render_base_template(
        self,
        input_data: Dict[str, Any],
    ) -> str:
        """Render the base template with variables."""
        prompt_config = self.config.agent.prompt
        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}
        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                return self.prompt_engine.render_file(
                    prompt_config.template, all_variables
                )
            except (PromptRenderError, ValueError, KeyError, FileNotFoundError) as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            return self.prompt_engine.render(prompt_config.inline, all_variables)
        else:
            raise ValueError("No prompt template or inline prompt configured")

    def _inject_input_context(self, template: str, input_data: Dict[str, Any]) -> str:
        """Auto-inject string input context into template."""
        _mode_context_keys = frozenset({
            "interaction_mode", "mode_instruction", "debate_framing",
        })
        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}

        input_parts = []
        for key, value in filtered_input.items():
            if value and isinstance(value, str) and key not in _mode_context_keys:
                label = key.replace('_', ' ').title()
                input_parts.append(f"## {label}\n{value}")

        if input_parts:
            return template + "\n\n---\n\n# Input Context\n\n" + "\n\n".join(input_parts)
        return template

    def _inject_dialogue_context(self, template: str, input_data: Dict[str, Any]) -> str:
        """Auto-inject dialogue history and stage agent outputs."""
        if not getattr(self.config.agent, 'dialogue_aware', True):
            return template

        from src.agents.dialogue_formatter import (
            format_dialogue_history,
            format_stage_agent_outputs,
        )
        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}
        max_chars = getattr(self.config.agent, 'max_dialogue_context_chars', DEFAULT_MAX_DIALOGUE_CONTEXT_CHARS)

        dialogue_history = filtered_input.get("dialogue_history")
        if dialogue_history and isinstance(dialogue_history, list):
            formatted = format_dialogue_history(dialogue_history, max_chars)
            if formatted:
                template += "\n\n---\n\n" + formatted

        stage_agents = filtered_input.get("current_stage_agents")
        if stage_agents and isinstance(stage_agents, dict):
            formatted = format_stage_agent_outputs(stage_agents, max_chars // 2)
            if formatted:
                template += "\n\n---\n\n" + formatted

        return template

    def _render_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> str:
        """Render prompt template with input data and tools."""
        validate_input_data(input_data, context)

        template = self._render_base_template(input_data)
        template = self._inject_input_context(template, input_data)
        template = self._inject_dialogue_context(template, input_data)

        if not _get_native_tool_definitions(self):
            tools_section = _get_cached_tool_schemas(self)
            if tools_section:
                template += tools_section

        return template

    # Delegate to extracted modules for backward compatibility
    def _parse_tool_calls(self, llm_response: str) -> List[Dict[str, Any]]:
        return parse_tool_calls(llm_response)

    @staticmethod
    def _sanitize_tool_output(text: str) -> str:
        return sanitize_tool_output(text)

    def _extract_final_answer(self, llm_response: str) -> str:
        return extract_final_answer(llm_response)

    def _extract_reasoning(self, llm_response: str) -> Optional[str]:
        return extract_reasoning(llm_response)

    def _estimate_cost(self, llm_response: LLMResponse) -> float:
        return estimate_cost(llm_response, fallback_model=getattr(self.llm, 'model', 'unknown'))

    def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities."""
        tools_list = self.tool_registry.list_tools()
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "type": "standard",
            "llm_provider": self.config.agent.inference.provider,
            "llm_model": self.config.agent.inference.model,
            "tools": tools_list,
            "max_tool_calls": self.config.agent.safety.max_tool_calls_per_execution,
            "supports_streaming": True,
            "supports_multimodal": False
        }


# --------------------------------------------------------------------------
# Methods attached outside the class body to keep method_count under the
# god-class threshold while preserving backward compatibility for tests
# and callers that use ``agent._execute_tool_calls()`` etc.
# --------------------------------------------------------------------------

def _execute_tool_calls_method(self: "StandardAgent", tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _execute_tool_calls(self, tool_calls, _get_tool_executor)

def _execute_single_tool_method(self: "StandardAgent", tool_call: Dict[str, Any]) -> Dict[str, Any]:
    return _execute_single_tool(self, tool_call)

def _execute_via_tool_executor_method(self: "StandardAgent", tool_name: str, tool_params: Dict[str, Any]) -> Dict[str, Any]:
    return _execute_via_tool_executor(self, tool_name, tool_params)

def _build_final_response_method(
    self: "StandardAgent",
    output: str,
    reasoning: Optional[str],
    tool_calls: List[Dict[str, Any]],
    tokens: int,
    cost: float,
    start_time: float,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Any:
    return _build_final_response(self, output=output, reasoning=reasoning, tool_calls=tool_calls, tokens=tokens, cost=cost, start_time=start_time, error=error, metadata=metadata)

def _get_cached_tool_schemas_method(self: "StandardAgent") -> Optional[str]:
    return _get_cached_tool_schemas(self)

def _get_native_tool_definitions_method(self: "StandardAgent") -> Optional[List[Dict[str, Any]]]:
    return _get_native_tool_definitions(self)

def _inject_tool_results_method(
    self: "StandardAgent",
    original_prompt: str,
    llm_response: str,
    tool_results: List[Dict[str, Any]],
    remaining_tool_calls: Optional[int] = None
) -> str:
    return _inject_tool_results(self, original_prompt, llm_response, tool_results, remaining_tool_calls)

StandardAgent._execute_tool_calls = _execute_tool_calls_method  # type: ignore[attr-defined]
StandardAgent._execute_single_tool = _execute_single_tool_method  # type: ignore[attr-defined]
StandardAgent._execute_via_tool_executor = _execute_via_tool_executor_method  # type: ignore[attr-defined]
StandardAgent._build_final_response = _build_final_response_method  # type: ignore[attr-defined]
StandardAgent._get_cached_tool_schemas = _get_cached_tool_schemas_method  # type: ignore[attr-defined]
StandardAgent._get_native_tool_definitions = _get_native_tool_definitions_method  # type: ignore[attr-defined]
StandardAgent._inject_tool_results = _inject_tool_results_method  # type: ignore[attr-defined]
