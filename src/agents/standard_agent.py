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
import hashlib
import json
import logging
import os
import random
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from src.schemas import AgentConfig

from src.agents.agent_observer import AgentObserver
from src.agents.base_agent import AgentResponse, BaseAgent, ExecutionContext
from src.agents.constants import (
    OUTPUT_PREVIEW_LENGTH,
    PROMPT_PREVIEW_LENGTH,
)
from src.agents.cost_estimator import estimate_cost
from src.agents.llm import (  # M-04: Import from new location
    AnthropicLLM,
    LLMError,
    LLMResponse,
    OllamaLLM,
    OpenAILLM,
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
    ToolNotFoundError,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

# Re-export constants for backward compatibility
_SANITIZE_TAGS = [TOOL_CALL_TAG, ANSWER_TAG] + REASONING_TAGS

# Note: Cost estimation constants removed - now using config/model_pricing.yaml
# See src/agents/pricing.py for pricing configuration

# Default port numbers for LLM providers (kept for backward compatibility)
OLLAMA_DEFAULT_PORT = 11434

# Shared thread pool for parallel tool execution (M-28).
# H-16: Lazy initialization with lifecycle management to avoid resource leaks.
# M-18: Pool size configurable via AGENT_TOOL_WORKERS env var.
# H-11: Increase default pool size based on CPU count
_CPU_MULTIPLIER = 2
_CPU_OFFSET = 4
_DEFAULT_POOL_SIZE = min(_POOL_SIZE_LIMIT, (os.cpu_count() or _CPU_OFFSET) * _CPU_MULTIPLIER + _CPU_OFFSET)
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
    """Shutdown the tool executor pool gracefully (P-15, H-16).

    Waits for in-flight tool calls to finish and cancels queued work.
    Supports Python 3.8 (no cancel_futures) and 3.9+ (with cancel_futures).
    """
    global _tool_executor
    if _tool_executor is not None:
        if sys.version_info >= (3, 9):
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
        """Create tool registry and load configured tools.

        Behavior based on config ``tools`` field:
        - ``tools: null`` or missing → auto-discover all available tools
        - ``tools: []`` (explicit empty list) → no tools loaded
        - ``tools: ["calc", ...]`` → load only the listed tools
        """
        registry = ToolRegistry(auto_discover=False)

        configured_tools = self.config.agent.tools

        if configured_tools is None:
            # No tools field or explicitly null → auto-discover
            registry.auto_discover()
        elif configured_tools:
            # Non-empty list → load specific tools
            self._load_tools_from_config(registry, configured_tools)
        # else: empty list [] → intentionally no tools

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
                # Apply config to tool instance
                if hasattr(tool_instance, 'config'):
                    if isinstance(tool_instance.config, dict):
                        tool_instance.config.update(tool_config)
                    else:
                        tool_instance.config = tool_config

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
        """
        validate_input_data(input_data, context)

        self._execution_context = context
        _tool_executor = input_data.get('tool_executor', None)
        if _tool_executor is not None:
            from src.tools.executor import ToolExecutor
            if not isinstance(_tool_executor, ToolExecutor):
                raise TypeError(
                    f"tool_executor must be a ToolExecutor instance, "
                    f"got {type(_tool_executor).__name__}"
                )
        self.tool_executor = _tool_executor
        self.tracker = input_data.get('tracker', None)
        self._observer = AgentObserver(self.tracker, self._execution_context)
        logger.info("[%s] Starting execution", self.name)

        start_time = time.time()
        tool_calls_made: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        llm_response = None

        # Sliding-window state for prompt management (C-01).
        # _system_prompt is pinned at the start and never truncated.
        # _conversation_turns holds (llm_response, tool_results_text) pairs.
        self._conversation_turns: List[str] = []

        try:
            prompt = self._render_prompt(input_data, context)
            self._system_prompt = prompt  # Pin the original prompt
            # Log input preview (last chars of prompt shows injected context)
            prompt_preview = prompt[-PROMPT_PREVIEW_LENGTH:].replace('\n', ' ').strip()
            logger.info("[%s] Prompt ready (%d chars) ...%s", self.name, len(prompt), prompt_preview)

            max_iterations = self.config.agent.safety.max_tool_calls_per_execution
            max_execution_time = self.config.agent.safety.max_execution_time_seconds

            for iteration in range(max_iterations):
                elapsed = time.time() - start_time
                if elapsed >= max_execution_time:
                    return self._build_final_response(
                        output=llm_response.content if llm_response else "",
                        reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made,
                        tokens=total_tokens,
                        cost=total_cost,
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

            return self._build_final_response(
                output=llm_response.content if llm_response else "",
                reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("Agent execution error: %s", safe_msg, exc_info=True)
            return self._build_final_response(
                output="",
                reasoning=None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error=f"Agent execution error: {safe_msg}"
            )

    async def aexecute(
        self,
        input_data: Dict[str, Any],
        context: Optional[ExecutionContext] = None
    ) -> AgentResponse:
        """Async counterpart to execute().

        H-34/M-20: Provides a proper async execution path so callers can
        ``await agent.aexecute(...)`` without blocking the event loop.

        Key differences from sync execute():
        - Uses ``asyncio.sleep`` with exponential backoff + jitter for retries.
        - Delegates CPU-bound / blocking LLM calls to a thread via
          ``asyncio.get_running_loop().run_in_executor``.
        - Otherwise mirrors the sync execute() logic exactly.
        """
        validate_input_data(input_data, context)

        self._execution_context = context
        _tool_executor = input_data.get('tool_executor', None)
        if _tool_executor is not None:
            from src.tools.executor import ToolExecutor
            if not isinstance(_tool_executor, ToolExecutor):
                raise TypeError(
                    f"tool_executor must be a ToolExecutor instance, "
                    f"got {type(_tool_executor).__name__}"
                )
        self.tool_executor = _tool_executor
        self.tracker = input_data.get('tracker', None)
        self._observer = AgentObserver(self.tracker, self._execution_context)
        logger.info("[%s] Starting async execution", self.name)

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
                    return self._build_final_response(
                        output=llm_response.content if llm_response else "",
                        reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                        tool_calls=tool_calls_made,
                        tokens=total_tokens,
                        cost=total_cost,
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

            return self._build_final_response(
                output=llm_response.content if llm_response else "",
                reasoning=extract_reasoning(llm_response.content) if llm_response else None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
                error="Max tool calling iterations reached",
                metadata={"iterations": max_iterations}
            )

        except (LLMError, ToolExecutionError, PromptRenderError, ConfigValidationError, RuntimeError, ValueError, TimeoutError) as e:
            safe_msg = sanitize_error_message(str(e))
            logger.warning("Agent async execution error: %s", safe_msg, exc_info=True)
            return self._build_final_response(
                output="",
                reasoning=None,
                tool_calls=tool_calls_made,
                tokens=total_tokens,
                cost=total_cost,
                start_time=start_time,
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
        """Async counterpart to _execute_iteration.

        Runs blocking LLM calls in a thread executor and uses
        asyncio.sleep for retry backoff with jitter.
        """
        inf_config = self.config.agent.inference
        max_agent_retries = inf_config.max_retries
        retry_delay = float(inf_config.retry_delay_seconds)

        # Safety validation (same fail-closed logic as sync path)
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            if self.tool_executor.policy_engine is not None:
                try:
                    from src.safety.action_policy_engine import PolicyExecutionContext

                    ctx = getattr(self, '_execution_context', None)
                    agent_id = ctx.agent_id if ctx and ctx.agent_id else self.config.agent.name
                    workflow_id = ctx.workflow_id if ctx and ctx.workflow_id else "unknown"
                    stage_id = ctx.stage_id if ctx and ctx.stage_id else "unknown"

                    validation_result = self.tool_executor.policy_engine.validate_action_sync(
                        action={"type": "llm_call", "model": inf_config.model, "prompt_length": len(prompt)},
                        context=PolicyExecutionContext(
                            agent_id=agent_id,
                            workflow_id=workflow_id,
                            stage_id=stage_id,
                            action_type="llm_call",
                            action_data={"model": inf_config.model}
                        )
                    )

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
                except (ConfigValidationError, ValueError, RuntimeError) as e:
                    logger.error(
                        "LLM call safety validation failed (fail-closed): %s",
                        e, exc_info=True
                    )
                    return {
                        "complete": True,
                        "response": self._build_final_response(
                            output="",
                            reasoning=None,
                            tool_calls=tool_calls_made,
                            tokens=total_tokens,
                            cost=total_cost,
                            start_time=start_time,
                            error=f"Safety validation error (fail-closed): {sanitize_error_message(str(e))}"
                        )
                    }

        # Call LLM with agent-level retries (async backoff with jitter)
        loop = asyncio.get_running_loop()
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = self._get_native_tool_definitions()
                if native_tools:
                    llm_kwargs["tools"] = native_tools

                # C-01: Use native async path instead of thread pool
                llm_response = await self.llm.acomplete(prompt, **llm_kwargs)
                logger.info(
                    "[%s] LLM responded (%s tokens)",
                    self.name,
                    llm_response.total_tokens or "?",
                )
                break
            except LLMError as e:
                last_error = e
                safe_err = sanitize_error_message(str(e))
                if attempt < max_agent_retries:
                    # Exponential backoff with jitter: delay * 2^attempt * uniform(0.5, 1.5)
                    # M-12: random.random() is intentional (not secrets.random()) - jitter doesn't need cryptographic randomness
                    backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, max_agent_retries + 1, safe_err, backoff_delay
                    )
                    await asyncio.sleep(backoff_delay)
                else:
                    logger.error(
                        "LLM call failed after %d attempts: %s",
                        max_agent_retries + 1, safe_err, exc_info=True
                    )

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
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {sanitize_error_message(str(last_error))}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        total_cost += self._estimate_cost(llm_response)

        # Track LLM call via observer
        self._observer.track_llm_call(
            provider=inf_config.provider,
            model=inf_config.model,
            prompt=prompt,
            response=llm_response.content,
            prompt_tokens=llm_response.prompt_tokens or 0,
            completion_tokens=llm_response.completion_tokens or 0,
            latency_ms=int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0,
            estimated_cost_usd=self._estimate_cost(llm_response),
            temperature=inf_config.temperature,
            max_tokens=inf_config.max_tokens,
            status="success"
        )

        # Parse tool calls
        tool_calls = parse_tool_calls(llm_response.content)

        if tool_calls:
            tool_names = ", ".join(tc.get("name", "?") for tc in tool_calls)
            logger.info("[%s] Calling %d tool(s): %s", self.name, len(tool_calls), tool_names)

        if not tool_calls:
            return {
                "complete": True,
                "response": self._build_final_response(
                    output=extract_final_answer(llm_response.content),
                    reasoning=extract_reasoning(llm_response.content),
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    start_time=start_time,
                    error=None
                )
            }

        # Execute tools (reuse sync tool execution — tools are typically I/O-bound
        # but the tool executor itself is sync; run in thread to avoid blocking)
        tool_results = await loop.run_in_executor(
            None, lambda: self._execute_tool_calls(tool_calls)
        )
        tool_calls_made.extend(tool_results)

        remaining_budget = None
        if max_iterations is not None:
            remaining_budget = max_iterations - len(tool_calls_made)

        next_prompt = self._inject_tool_results(
            prompt, llm_response.content, tool_results,
            remaining_tool_calls=remaining_budget
        )

        return {
            "complete": False,
            "llm_response": llm_response,
            "next_prompt": next_prompt,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tool_calls_made": tool_calls_made
        }

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
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            if self.tool_executor.policy_engine is not None:
                try:
                    from src.safety.action_policy_engine import PolicyExecutionContext

                    ctx = getattr(self, '_execution_context', None)
                    agent_id = ctx.agent_id if ctx and ctx.agent_id else self.config.agent.name
                    workflow_id = ctx.workflow_id if ctx and ctx.workflow_id else "unknown"
                    stage_id = ctx.stage_id if ctx and ctx.stage_id else "unknown"

                    validation_result = self.tool_executor.policy_engine.validate_action_sync(
                        action={"type": "llm_call", "model": inf_config.model, "prompt_length": len(prompt)},
                        context=PolicyExecutionContext(
                            agent_id=agent_id,
                            workflow_id=workflow_id,
                            stage_id=stage_id,
                            action_type="llm_call",
                            action_data={"model": inf_config.model}
                        )
                    )

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
                except (ConfigValidationError, ValueError, RuntimeError) as e:
                    # C-02/H-02: Fail-closed — safety validation errors MUST block execution.
                    # Never silently continue when the safety stack is broken.
                    logger.error(
                        "LLM call safety validation failed (fail-closed): %s",
                        e, exc_info=True
                    )
                    return {
                        "complete": True,
                        "response": self._build_final_response(
                            output="",
                            reasoning=None,
                            tool_calls=tool_calls_made,
                            tokens=total_tokens,
                            cost=total_cost,
                            start_time=start_time,
                            error=f"Safety validation error (fail-closed): {sanitize_error_message(str(e))}"
                        )
                    }

        # Call LLM with agent-level retries
        llm_response = None
        last_error = None

        for attempt in range(max_agent_retries + 1):
            try:
                llm_kwargs: Dict[str, Any] = {}
                native_tools = self._get_native_tool_definitions()
                if native_tools:
                    llm_kwargs["tools"] = native_tools
                llm_response = self.llm.complete(prompt, **llm_kwargs)
                logger.info(
                    "[%s] LLM responded (%s tokens)",
                    self.name,
                    llm_response.total_tokens or "?",
                )
                break
            except LLMError as e:
                last_error = e
                safe_err = sanitize_error_message(str(e))
                if attempt < max_agent_retries:
                    # H-10: Add jitter to prevent thundering herd
                    backoff_delay = retry_delay * (DEFAULT_BACKOFF_MULTIPLIER ** attempt) * (RETRY_JITTER_MIN + random.random())  # noqa: S311 -- jitter/backoff, not crypto
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.1fs...",
                        attempt + 1, max_agent_retries + 1, safe_err, backoff_delay
                    )
                    # H-15: Use threading.Event for interruptible wait instead of time.sleep
                    shutdown_event = threading.Event()
                    if shutdown_event.wait(timeout=backoff_delay):
                        raise KeyboardInterrupt("Agent execution interrupted")
                else:
                    logger.error(
                        "LLM call failed after %d attempts: %s",
                        max_agent_retries + 1, safe_err, exc_info=True
                    )

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
                    error=f"LLM call failed after {max_agent_retries + 1} attempts: {sanitize_error_message(str(last_error))}"
                )
            }

        # Track tokens and cost
        if llm_response.total_tokens:
            total_tokens += llm_response.total_tokens
        total_cost += self._estimate_cost(llm_response)

        # Track LLM call via observer
        self._observer.track_llm_call(
            provider=inf_config.provider,
            model=inf_config.model,
            prompt=prompt,
            response=llm_response.content,
            prompt_tokens=llm_response.prompt_tokens or 0,
            completion_tokens=llm_response.completion_tokens or 0,
            latency_ms=int(llm_response.latency_ms) if hasattr(llm_response, 'latency_ms') and llm_response.latency_ms else 0,
            estimated_cost_usd=self._estimate_cost(llm_response),
            temperature=inf_config.temperature,
            max_tokens=inf_config.max_tokens,
            status="success"
        )

        # Parse tool calls
        tool_calls = parse_tool_calls(llm_response.content)

        if tool_calls:
            tool_names = ", ".join(tc.get("name", "?") for tc in tool_calls)
            logger.info("[%s] Calling %d tool(s): %s", self.name, len(tool_calls), tool_names)

        if not tool_calls:
            return {
                "complete": True,
                "response": self._build_final_response(
                    output=extract_final_answer(llm_response.content),
                    reasoning=extract_reasoning(llm_response.content),
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

        remaining_budget = None
        if max_iterations is not None:
            remaining_budget = max_iterations - len(tool_calls_made)

        next_prompt = self._inject_tool_results(
            prompt, llm_response.content, tool_results,
            remaining_tool_calls=remaining_budget
        )

        return {
            "complete": False,
            "llm_response": llm_response,
            "next_prompt": next_prompt,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tool_calls_made": tool_calls_made
        }

    def _execute_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute a list of tool calls (parallel if independent, sequential if dependent)."""
        if not isinstance(tool_calls, list):
            raise TypeError(f"tool_calls must be a list, got {type(tool_calls).__name__}")

        for i, tool_call in enumerate(tool_calls):
            if not isinstance(tool_call, dict):
                raise TypeError(f"tool_call at index {i} must be a dictionary, got {type(tool_call).__name__}")

        if len(tool_calls) <= 1:
            return [self._execute_single_tool(tool_call) for tool_call in tool_calls]

        parallel_enabled = getattr(self.config.agent.safety, "parallel_tool_calls", True)

        if not parallel_enabled:
            return [self._execute_single_tool(tool_call) for tool_call in tool_calls]

        tool_results: List[Any] = [None] * len(tool_calls)

        future_to_index = {
            _get_tool_executor().submit(self._execute_single_tool, tool_call): i
            for i, tool_call in enumerate(tool_calls)
        }

        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                tool_results[index] = result
            except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
                logger.error(f"Tool execution failed in parallel mode: {e}")
                tool_results[index] = {
                    "name": tool_calls[index].get("name", "unknown"),
                    "parameters": tool_calls[index].get("parameters", {}),
                    "success": False,
                    "result": None,
                    "error": f"Parallel execution error: {str(e)}"
                }

        return tool_results

    def _execute_single_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single tool call."""
        if not isinstance(tool_call, dict):
            raise TypeError(f"tool_call must be a dictionary, got {type(tool_call).__name__}")

        if "name" not in tool_call:
            raise ValueError("tool_call must contain 'name' field")

        tool_name = tool_call.get("name")
        tool_params = tool_call.get("parameters", tool_call.get("arguments", {}))

        if not isinstance(tool_name, str):
            raise TypeError(f"tool_call 'name' must be a string, got {type(tool_name).__name__}")

        if not isinstance(tool_params, dict):
            raise TypeError(f"tool_call 'parameters' must be a dictionary, got {type(tool_params).__name__}")

        # Defense-in-depth: Agent-level SafetyConfig pre-checks before tool execution.
        # These run regardless of whether tool_executor is configured.
        safety = self.config.agent.safety

        if safety.mode == "require_approval":
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' blocked: safety mode is 'require_approval'",
                "success": False
            }

        if tool_name in safety.require_approval_for_tools:
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": None,
                "error": f"Tool '{tool_name}' requires approval before execution",
                "success": False
            }

        if safety.mode == "dry_run":
            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": f"[DRY RUN] Tool '{tool_name}' would be executed with parameters: {tool_params}",
                "error": None,
                "success": True
            }

        # Route through ToolExecutor (safety-integrated execution)
        if hasattr(self, 'tool_executor') and self.tool_executor is not None:
            return self._execute_via_tool_executor(tool_name, tool_params)

        # SECURITY: No silent fallback — tool_executor is required for safe execution.
        # Without it, the full safety stack (PolicyRegistry, ActionPolicyEngine,
        # ApprovalWorkflow, RollbackManager) is bypassed.
        logger.critical(
            "SECURITY: No tool_executor configured for agent '%s'. "
            "Tool '%s' execution blocked to prevent safety bypass.",
            self.name, tool_name
        )
        return {
            "name": tool_name,
            "parameters": tool_params,
            "result": None,
            "error": (
                f"Tool '{tool_name}' execution blocked: no tool_executor configured. "
                f"The safety stack is required for tool execution."
            ),
            "success": False
        }

    def _execute_via_tool_executor(self, tool_name: str, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool through the safety-integrated ToolExecutor."""
        tool_start_time = time.time()
        try:
            result = self.tool_executor.execute(tool_name, tool_params)
            duration_seconds = time.time() - tool_start_time
            logger.info(
                "[%s] Tool '%s' %s (%.1fs)",
                self.name, tool_name,
                "succeeded" if result.success else "failed",
                duration_seconds,
            )

            self._observer.track_tool_call(
                tool_name=tool_name,
                input_params=tool_params,
                output_data={"result": result.result} if result.success else {},
                duration_seconds=duration_seconds,
                status="success" if result.success else "failed",
                error_message=result.error if not result.success else None
            )

            return {
                "name": tool_name,
                "parameters": tool_params,
                "result": result.result if result.success else None,
                "error": result.error if not result.success else None,
                "success": result.success
            }
        except (ToolExecutionError, ToolNotFoundError, TimeoutError, RuntimeError) as e:
            duration_seconds = time.time() - tool_start_time

            self._observer.track_tool_call(
                tool_name=tool_name,
                input_params=tool_params,
                output_data={},
                duration_seconds=duration_seconds,
                status="failed",
                error_message=f"Tool execution error: {str(e)}"
            )

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
        """Build final AgentResponse."""
        duration = time.time() - start_time
        output_preview = (output[:OUTPUT_PREVIEW_LENGTH].replace('\n', ' ').strip() + "...") if len(output) > OUTPUT_PREVIEW_LENGTH else output.replace('\n', ' ').strip()
        logger.info(
            "[%s] Execution complete (%d tokens, $%.4f, %.1fs) → %s",
            self.name, tokens, cost, duration, output_preview or "(empty)",
        )
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
        """Render prompt template with input data and tools."""
        validate_input_data(input_data, context)

        prompt_config = self.config.agent.prompt

        # M-08: Use allowlist approach instead of denylist.  Only pass values
        # whose types are safe for Jinja2 templates (str, int, float, bool,
        # list, dict, tuple, None).  This automatically excludes internal
        # framework objects (tracker, tool_registry, console, etc.) without
        # needing to maintain a fragile denylist of variable names.
        filtered_input = {k: v for k, v in input_data.items() if _is_safe_template_value(v)}

        all_variables = {**filtered_input, **prompt_config.variables}

        if prompt_config.template:
            try:
                template = self.prompt_engine.render_file(
                    prompt_config.template,
                    all_variables
                )
            except (PromptRenderError, ValueError, KeyError, FileNotFoundError) as e:
                raise PromptRenderError(
                    f"Failed to render template file {prompt_config.template}: {e}"
                )
        elif prompt_config.inline:
            template = self.prompt_engine.render(
                prompt_config.inline,
                all_variables
            )
        else:
            raise ValueError("No prompt template or inline prompt configured")

        # Auto-inject input context so agents always receive user inputs
        # even when the prompt template doesn't use {{ variable }} references
        input_parts = []
        for key, value in filtered_input.items():
            if value and isinstance(value, str):
                label = key.replace('_', ' ').title()
                input_parts.append(f"## {label}\n{value}")
        if input_parts:
            template += "\n\n---\n\n# Input Context\n\n" + "\n\n".join(input_parts)

        if not self._get_native_tool_definitions():
            tools_section = self._get_cached_tool_schemas()
            if tools_section:
                template += tools_section

        return template

    def _get_cached_tool_schemas(self) -> Optional[str]:
        """Get cached tool schemas or build and cache them."""
        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

        current_version = len(tools_dict)
        if self._cached_tool_schemas is not None and self._tool_registry_version == current_version:
            return self._cached_tool_schemas

        tool_schemas = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.get_parameters_schema()
            }
            for tool in tools_dict.values()
        ]
        tools_section = "\n\nAvailable Tools:\n" + json.dumps(tool_schemas, indent=2)

        self._cached_tool_schemas = tools_section
        self._tool_registry_version = current_version

        return tools_section

    def _get_native_tool_definitions(self) -> Optional[List[Dict[str, Any]]]:
        """Build native tool definitions for providers that support them.

        M-20: Results are cached and only recomputed when the tool registry
        contents change (detected via a hash of tool names).
        """
        if not isinstance(self.llm, (OllamaLLM, OpenAILLM, AnthropicLLM)):
            return None

        tools_dict = self.tool_registry.get_all_tools()
        if not tools_dict:
            return None

        # Check cache validity using a hash of sorted tool names
        tool_names_key = ",".join(sorted(tools_dict.keys()))
        current_hash = hashlib.sha256(tool_names_key.encode()).hexdigest()

        if (
            self._cached_native_tool_defs is not None
            and self._cached_native_tool_defs_hash == current_hash
        ):
            return self._cached_native_tool_defs

        native_tools = []
        for tool in tools_dict.values():
            schema = tool.get_parameters_schema()

            function_def = {
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            }

            result_schema = tool.get_result_schema()
            if result_schema:
                function_def["description"] = (
                    f"{tool.description}\n\n"
                    f"Result schema: {json.dumps(result_schema, indent=2)}"
                )

            native_tools.append({
                "type": "function",
                "function": function_def,
            })

        result = native_tools if native_tools else None
        self._cached_native_tool_defs = result
        self._cached_native_tool_defs_hash = current_hash
        return result

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

    def _inject_tool_results(
        self,
        original_prompt: str,
        llm_response: str,
        tool_results: List[Dict[str, Any]],
        remaining_tool_calls: Optional[int] = None
    ) -> str:
        """Inject tool results into prompt for next iteration.

        Uses a sliding-window approach (C-01) to prevent unbounded prompt growth:
        1. The system/original prompt is pinned at the start and never truncated.
        2. Each iteration's (LLM response + tool results) is stored as a turn.
        3. When total length exceeds max_prompt_length, the OLDEST turns are
           dropped from the middle, preserving the system prompt and most
           recent turns.
        4. Truncated content is re-sanitized through the injection detector.
        """
        max_tool_result_size = self.config.agent.safety.max_tool_result_size
        max_prompt_length = self.config.agent.safety.max_prompt_length

        results_parts = ["\n\nTool Results:\n"]
        for result in tool_results:
            results_parts.append(f"\nTool: {result['name']}\n")
            results_parts.append(f"Parameters: {json.dumps(result['parameters'])}\n")
            if result['success']:
                safe_result = sanitize_tool_output(str(result['result']))

                if len(safe_result) > max_tool_result_size:
                    original_size = len(safe_result)
                    safe_result = safe_result[:max_tool_result_size]
                    safe_result += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"

                results_parts.append(f"Result: {safe_result}\n")
            else:
                safe_error = sanitize_tool_output(str(result['error']))

                if len(safe_error) > max_tool_result_size:
                    original_size = len(safe_error)
                    safe_error = safe_error[:max_tool_result_size]
                    safe_error += f"\n[truncated — {original_size:,} total chars, showing first {max_tool_result_size:,}]"

                results_parts.append(f"Error: {safe_error}\n")

        if remaining_tool_calls is not None:
            if remaining_tool_calls > 0:
                results_parts.append(
                    f"\n[System Info: You have {remaining_tool_calls} tool call(s) remaining in your budget.]\n"
                )
            else:
                results_parts.append(
                    "\n[System Info: This is your last tool call. Budget exhausted after this iteration.]\n"
                )

        results_text = ''.join(results_parts)

        # Build this iteration's turn text
        turn_text = "\n\nAssistant: " + llm_response + results_text

        # Append to conversation history
        if not hasattr(self, '_conversation_turns'):
            self._conversation_turns = []
        self._conversation_turns.append(turn_text)

        # Use the pinned system prompt (set in execute())
        system_prompt = getattr(self, '_system_prompt', original_prompt)

        # Build full prompt with sliding window
        suffix = "\n\nPlease continue:"
        budget = max_prompt_length - len(system_prompt) - len(suffix)

        if budget <= 0:
            # System prompt itself exceeds budget; include only most recent turn
            recent_turn = sanitize_tool_output(self._conversation_turns[-1])
            return system_prompt + recent_turn + suffix

        # Include as many recent turns as fit within the budget
        included_turns: List[str] = []
        total_turn_chars = 0
        for turn in reversed(self._conversation_turns):
            if total_turn_chars + len(turn) > budget:
                break
            included_turns.append(turn)
            total_turn_chars += len(turn)

        included_turns.reverse()

        # If we dropped any turns, add a truncation marker and count
        dropped_count = len(self._conversation_turns) - len(included_turns)
        truncation_marker = ""
        if dropped_count > 0:
            truncation_marker = f"\n\n[...{dropped_count} earlier iteration(s) omitted for brevity...]\n"

        # Re-sanitize the assembled turns to catch any injection attempts
        # that might span across turn boundaries after truncation
        assembled_turns = truncation_marker + ''.join(included_turns)
        assembled_turns = sanitize_tool_output(assembled_turns)

        # M-48: Prune old turns to free memory - keep only what we included
        if dropped_count > 0:
            self._conversation_turns = included_turns

        return system_prompt + assembled_turns + suffix

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
            "supports_streaming": False,
            "supports_multimodal": False
        }
