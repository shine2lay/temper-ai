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

from src.agents._standard_agent_helpers import (
    build_final_response as _build_final_response,
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
from src.agents.constants import PROMPT_PREVIEW_LENGTH
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
        """Load specific tools from configuration."""
        if len(registry.list_tools()) == 0:
            discovered_count = registry.auto_discover()
            if discovered_count == 0:
                logger.warning(
                    "No tools discovered via auto-discovery. "
                    "Check that src/tools/ contains valid BaseTool subclasses."
                )

        available_tools = registry.list_tools()

        for tool_spec in configured_tools:
            tool_name: str
            tool_config: Dict[str, Any]
            if isinstance(tool_spec, str):
                tool_name = tool_spec
                tool_config = {}
            else:
                tool_name = tool_spec.name
                tool_config = tool_spec.config if hasattr(tool_spec, 'config') else {}

            tool_instance = registry.get(tool_name)

            if tool_instance is None:
                raise ValueError(
                    f"Unknown tool '{tool_name}'. Available tools: {available_tools}\n"
                    f"To add a new tool, create a BaseTool subclass in src/tools/"
                )

            if tool_config:
                logger.debug(f"Tool config provided for {tool_name}: {tool_config}")
                if hasattr(tool_instance, 'config'):
                    if isinstance(tool_instance.config, dict):
                        tool_instance.config.update(tool_config)
                    else:
                        tool_instance.config = tool_config  # type: ignore[unreachable]

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
            prompt = self._render_prompt(input_data, context)
            self._system_prompt = prompt
            prompt_preview = prompt[-PROMPT_PREVIEW_LENGTH:].replace('\n', ' ').strip()
            logger.info("[%s] Prompt ready (%d chars) ...%s", self.name, len(prompt), prompt_preview)

            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                elapsed = time.time() - start_time
                if elapsed >= max_execution_time:
                    return _build_final_response(  # type: ignore[no-any-return]
                        self, output=llm_response.content if llm_response else "",
                        reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made, tokens=total_tokens, cost=total_cost,
                        start_time=start_time,
                        error=f"Execution time limit exceeded ({max_execution_time}s)",
                        metadata={"elapsed_seconds": elapsed, "iteration": iteration}
                    )

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

            return _build_final_response(  # type: ignore[no-any-return]
                self, output=llm_response.content if llm_response else "",
                reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made, tokens=total_tokens, cost=total_cost,
                start_time=start_time, error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("Agent execution error: %s", safe_msg, exc_info=True)
            return _build_final_response(  # type: ignore[no-any-return]
                self, output="", reasoning=None, tool_calls=tool_calls_made,
                tokens=total_tokens, cost=total_cost, start_time=start_time,
                error=f"Agent execution error: {safe_msg}"
            )

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
            prompt = self._render_prompt(input_data, context)
            self._system_prompt = prompt
            prompt_preview = prompt[-PROMPT_PREVIEW_LENGTH:].replace('\n', ' ').strip()
            logger.info("[%s] Prompt ready (%d chars) ...%s", self.name, len(prompt), prompt_preview)

            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                elapsed = time.time() - start_time
                if elapsed >= max_execution_time:
                    return _build_final_response(  # type: ignore[no-any-return]
                        self, output=llm_response.content if llm_response else "",
                        reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made, tokens=total_tokens, cost=total_cost,
                        start_time=start_time,
                        error=f"Execution time limit exceeded ({max_execution_time}s)",
                        metadata={"elapsed_seconds": elapsed, "iteration": iteration}
                    )

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

            return _build_final_response(  # type: ignore[no-any-return]
                self, output=llm_response.content if llm_response else "",
                reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made, tokens=total_tokens, cost=total_cost,
                start_time=start_time, error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("Agent async execution error: %s", safe_msg, exc_info=True)
            return _build_final_response(  # type: ignore[no-any-return]
                self, output="", reasoning=None, tool_calls=tool_calls_made,
                tokens=total_tokens, cost=total_cost, start_time=start_time,
                error=f"Agent execution error: {safe_msg}"
            )

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

        # Call LLM with agent-level retries (async backoff with jitter)
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = _get_native_tool_definitions(self)
                if native_tools:
                    llm_kwargs["tools"] = native_tools

                combined_cb = _make_stream_callback(self)
                if combined_cb:
                    llm_response = await self.llm.astream(prompt, on_chunk=combined_cb, **llm_kwargs)
                else:
                    llm_response = await self.llm.acomplete(prompt, **llm_kwargs)
                logger.info("[%s] LLM responded (%s tokens)", self.name, llm_response.total_tokens or "?")
                break
            except LLMError as e:
                last_error = e
                safe_err = sanitize_error_message(str(e))
                _track_failed_llm_call(self, inf_config, prompt, e, attempt + 1, max_agent_retries + 1)
                if attempt < max_agent_retries:
                    backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, max_agent_retries + 1, safe_err, backoff_delay
                    )
                    await asyncio.sleep(backoff_delay)
                else:
                    logger.error("LLM call failed after %d attempts: %s", max_agent_retries + 1, safe_err, exc_info=True)

        if llm_response is None:
            return {
                "complete": True,
                "response": _build_final_response(
                    self, output="", reasoning=None, tool_calls=tool_calls_made,
                    tokens=total_tokens, cost=total_cost, start_time=start_time,
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {sanitize_error_message(str(last_error))}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        cost = _estimate_cost_for_response(self, llm_response)
        total_cost += cost

        _track_llm_call(self, inf_config, prompt, llm_response, cost)

        # Process response: parse tool calls, execute if any
        return _process_llm_response(
            self, llm_response, tool_calls_made, total_tokens, total_cost,
            start_time, prompt, max_iterations, _get_tool_executor
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
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = _get_native_tool_definitions(self)
                if native_tools:
                    llm_kwargs["tools"] = native_tools
                combined_cb = _make_stream_callback(self)
                if combined_cb:
                    llm_response = self.llm.stream(prompt, on_chunk=combined_cb, **llm_kwargs)
                else:
                    llm_response = self.llm.complete(prompt, **llm_kwargs)
                logger.info("[%s] LLM responded (%s tokens)", self.name, llm_response.total_tokens or "?")
                break
            except LLMError as e:
                last_error = e
                safe_err = sanitize_error_message(str(e))
                _track_failed_llm_call(self, inf_config, prompt, e, attempt + 1, max_agent_retries + 1)
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

        if llm_response is None:
            return {
                "complete": True,
                "response": _build_final_response(
                    self, output="", reasoning=None, tool_calls=tool_calls_made,
                    tokens=total_tokens, cost=total_cost, start_time=start_time,
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {sanitize_error_message(str(last_error))}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        cost = _estimate_cost_for_response(self, llm_response)
        total_cost += cost

        _track_llm_call(self, inf_config, prompt, llm_response, cost)

        # Process response: parse tool calls, execute if any
        return _process_llm_response(
            self, llm_response, tool_calls_made, total_tokens, total_cost,
            start_time, prompt, max_iterations, _get_tool_executor
        )

    def _render_prompt(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> str:
        """Render prompt template with input data and tools."""
        validate_input_data(input_data, context)

        prompt_config = self.config.agent.prompt

        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}
        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                template = self.prompt_engine.render_file(
                    prompt_config.template, all_variables
                )
            except (PromptRenderError, ValueError, KeyError, FileNotFoundError) as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            template = self.prompt_engine.render(prompt_config.inline, all_variables)
        else:
            raise ValueError("No prompt template or inline prompt configured")

        # Auto-inject input context
        input_parts = []
        for key, value in filtered_input.items():
            if value and isinstance(value, str):
                label = key.replace('_', ' ').title()
                input_parts.append(f"## {label}\n{value}")
        if input_parts:
            template += "\n\n---\n\n# Input Context\n\n" + "\n\n".join(input_parts)

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
    return _build_final_response(self, output, reasoning, tool_calls, tokens, cost, start_time, error, metadata)

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
