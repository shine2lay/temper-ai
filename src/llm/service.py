"""LLMService — self-contained LLM call lifecycle.

Consolidates the full LLM interaction loop (tool calling, retry, tracking,
cost estimation, sliding window, tool schema building) into a reusable class
that is independent of any specific agent implementation.

Usage:
    service = LLMService(llm, inference_config)
    result = service.run(prompt, tools=[...], tool_executor=executor, ...)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.llm.constants import FALLBACK_UNKNOWN_VALUE
from src.llm.cost_estimator import estimate_cost
from src.llm.response_parser import (
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
)
from src.tools.tool_keys import ToolKeys
from src.llm._prompt import inject_results
from src.llm._retry import call_with_retry_async, call_with_retry_sync
from src.llm._schemas import build_native_tool_defs, build_text_schemas
from src.llm._tool_execution import execute_single_tool, execute_tools
from src.llm._tracking import track_call, track_failed_call, validate_safety
from src.utils.exceptions import MaxIterationsError, sanitize_error_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default iteration limit when safety config doesn't specify one
# ---------------------------------------------------------------------------
_DEFAULT_MAX_ITERATIONS = 10  # scanner: skip-magic


# ---------------------------------------------------------------------------
# LLMRunResult
# ---------------------------------------------------------------------------

@dataclass
class LLMRunResult:
    """Result of an LLMService.run() / .arun() call."""
    output: str
    reasoning: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0
    iterations: int = 0
    error: Optional[str] = None
    raw_response: Optional[Any] = None


# ---------------------------------------------------------------------------
# LLMService
# ---------------------------------------------------------------------------

class LLMService:
    """Self-contained LLM call lifecycle manager.

    Args:
        llm: BaseLLM provider instance
        inference_config: InferenceConfig with provider/model/retries/etc.
        pre_call_hooks: Optional list of callables invoked before each LLM call.
            If any hook returns a non-None value, the call is blocked.
    """

    def __init__(
        self,
        llm: Any,
        inference_config: Any,
        pre_call_hooks: Optional[List[Callable]] = None,
    ) -> None:
        self.llm = llm
        self.inference_config = inference_config
        self.pre_call_hooks = pre_call_hooks or []
        # Cached tool schemas (persists across run() calls)
        self._cached_text_schemas: Optional[str] = None
        self._cached_text_schemas_version: int = 0
        self._cached_native_defs: Optional[List[Dict[str, Any]]] = None
        self._cached_native_defs_hash: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        prompt: str,
        *,
        tools: Optional[List[Any]] = None,
        tool_executor: Any = None,
        observer: Any = None,
        stream_callback: Optional[Callable] = None,
        safety_config: Any = None,
        agent_name: str = "unknown",
        max_iterations: Optional[int] = None,
        max_execution_time: Optional[float] = None,
        start_time: Optional[float] = None,
    ) -> LLMRunResult:
        """Execute the LLM call lifecycle (sync).

        If *tools* is None or empty, performs a single LLM call.
        If *tools* is a list of BaseTool instances, enters the tool-calling loop.
        """
        resolved_max_iterations = self._resolve_max_iterations(max_iterations, safety_config)
        max_tool_result_size = self._resolve_max_tool_result_size(safety_config)
        max_prompt_length = self._resolve_max_prompt_length(safety_config)

        effective_start = start_time if start_time is not None else time.time()
        effective_timeout = max_execution_time or float("inf")

        # Build tool schemas if tools are provided
        native_tool_defs = self._build_native_tool_defs(tools) if tools else None
        text_tool_schemas = None
        if tools and not native_tool_defs:
            text_tool_schemas = self._build_text_schemas(tools)

        # Local state
        tool_calls_made: List[Dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        conversation_turns: List[str] = []
        system_prompt = prompt
        llm_response = None

        # Prepend text-based tool schemas to prompt if needed
        if text_tool_schemas:
            prompt = prompt + text_tool_schemas

        for iteration in range(resolved_max_iterations):
            # Timeout check
            if time.time() - effective_start >= effective_timeout:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=f"Execution time limit exceeded ({effective_timeout}s)",
                )

            # Pre-call hooks
            blocked = self._run_pre_call_hooks(prompt)
            if blocked is not None:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=f"LLM call blocked by pre-call hook: {blocked}",
                )

            # Safety validation via policy engine
            safety_error = validate_safety(
                tool_executor, self.inference_config, prompt,
            )
            if safety_error is not None:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=safety_error,
                )

            # Call LLM with retry
            llm_response, last_error = self._call_with_retry_sync(
                prompt, stream_callback, native_tool_defs, observer,
            )

            # Handle LLM failure
            if llm_response is None:
                max_attempts = self.inference_config.max_retries + 1
                error_msg = f"LLM call failed after {max_attempts} attempts"
                if last_error:
                    error_msg += f": {sanitize_error_message(str(last_error))}"
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration + 1,
                    error=error_msg,
                )

            # Track tokens and cost
            logger.info("[%s] LLM responded (%s tokens)", agent_name, llm_response.total_tokens or "?")
            if llm_response.total_tokens:
                total_tokens += llm_response.total_tokens
            cost = self._estimate_cost(llm_response)
            total_cost += cost
            self._track_call(observer, prompt, llm_response, cost)

            # Parse tool calls
            parsed_calls = parse_tool_calls(llm_response.content) if tools else []

            if not parsed_calls:
                # No tool calls — return final result
                return LLMRunResult(
                    output=extract_final_answer(llm_response.content),
                    reasoning=extract_reasoning(llm_response.content),
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration + 1,
                    raw_response=llm_response,
                )

            # Execute tool calls
            tool_names = ", ".join(tc.get(ToolKeys.NAME, "?") for tc in parsed_calls)
            logger.info("[%s] Calling %d tool(s): %s", agent_name, len(parsed_calls), tool_names)

            tool_results = self._execute_tools(
                parsed_calls, tool_executor, observer, safety_config,
            )
            tool_calls_made.extend(tool_results)

            # Inject results into prompt via sliding window
            remaining_budget = None
            if resolved_max_iterations is not None:
                remaining_budget = resolved_max_iterations - len(tool_calls_made)

            prompt = inject_results(
                system_prompt, llm_response.content, tool_results,
                conversation_turns, max_tool_result_size, max_prompt_length,
                remaining_budget,
            )

        # Max iterations reached
        raise MaxIterationsError(
            iterations=resolved_max_iterations or 0,
            tool_calls=tool_calls_made,
            tokens=total_tokens,
            cost=total_cost,
            last_output=llm_response.content if llm_response else "",
            last_reasoning=extract_reasoning(llm_response.content) if llm_response else None,
        )

    async def arun(
        self,
        prompt: str,
        *,
        tools: Optional[List[Any]] = None,
        tool_executor: Any = None,
        observer: Any = None,
        stream_callback: Optional[Callable] = None,
        safety_config: Any = None,
        agent_name: str = "unknown",
        max_iterations: Optional[int] = None,
        max_execution_time: Optional[float] = None,
        start_time: Optional[float] = None,
    ) -> LLMRunResult:
        """Execute the LLM call lifecycle (async).

        Async counterpart to run(). Same interface and behavior.
        """
        resolved_max_iterations = self._resolve_max_iterations(max_iterations, safety_config)
        max_tool_result_size = self._resolve_max_tool_result_size(safety_config)
        max_prompt_length = self._resolve_max_prompt_length(safety_config)

        effective_start = start_time if start_time is not None else time.time()
        effective_timeout = max_execution_time or float("inf")

        native_tool_defs = self._build_native_tool_defs(tools) if tools else None
        text_tool_schemas = None
        if tools and not native_tool_defs:
            text_tool_schemas = self._build_text_schemas(tools)

        tool_calls_made: List[Dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        conversation_turns: List[str] = []
        system_prompt = prompt
        llm_response = None

        if text_tool_schemas:
            prompt = prompt + text_tool_schemas

        for iteration in range(resolved_max_iterations):
            if time.time() - effective_start >= effective_timeout:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=f"Execution time limit exceeded ({effective_timeout}s)",
                )

            blocked = self._run_pre_call_hooks(prompt)
            if blocked is not None:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=f"LLM call blocked by pre-call hook: {blocked}",
                )

            safety_error = validate_safety(
                tool_executor, self.inference_config, prompt,
            )
            if safety_error is not None:
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration,
                    error=safety_error,
                )

            llm_response, last_error = await self._call_with_retry_async(
                prompt, stream_callback, native_tool_defs, observer,
            )

            if llm_response is None:
                max_attempts = self.inference_config.max_retries + 1
                error_msg = f"LLM call failed after {max_attempts} attempts"
                if last_error:
                    error_msg += f": {sanitize_error_message(str(last_error))}"
                return LLMRunResult(
                    output="",
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration + 1,
                    error=error_msg,
                )

            logger.info("[%s] LLM responded (%s tokens)", agent_name, llm_response.total_tokens or "?")
            if llm_response.total_tokens:
                total_tokens += llm_response.total_tokens
            cost = self._estimate_cost(llm_response)
            total_cost += cost
            self._track_call(observer, prompt, llm_response, cost)

            parsed_calls = parse_tool_calls(llm_response.content) if tools else []

            if not parsed_calls:
                return LLMRunResult(
                    output=extract_final_answer(llm_response.content),
                    reasoning=extract_reasoning(llm_response.content),
                    tool_calls=tool_calls_made,
                    tokens=total_tokens,
                    cost=total_cost,
                    iterations=iteration + 1,
                    raw_response=llm_response,
                )

            tool_names = ", ".join(tc.get(ToolKeys.NAME, "?") for tc in parsed_calls)
            logger.info("[%s] Calling %d tool(s): %s", agent_name, len(parsed_calls), tool_names)

            tool_results = self._execute_tools(
                parsed_calls, tool_executor, observer, safety_config,
            )
            tool_calls_made.extend(tool_results)

            remaining_budget = None
            if resolved_max_iterations is not None:
                remaining_budget = resolved_max_iterations - len(tool_calls_made)

            prompt = inject_results(
                system_prompt, llm_response.content, tool_results,
                conversation_turns, max_tool_result_size, max_prompt_length,
                remaining_budget,
            )

        raise MaxIterationsError(
            iterations=resolved_max_iterations or 0,
            tool_calls=tool_calls_made,
            tokens=total_tokens,
            cost=total_cost,
            last_output=llm_response.content if llm_response else "",
            last_reasoning=extract_reasoning(llm_response.content) if llm_response else None,
        )

    # ------------------------------------------------------------------
    # Delegation to sub-modules
    # ------------------------------------------------------------------

    def _call_with_retry_sync(
        self,
        prompt: str,
        stream_callback: Optional[Callable],
        native_tool_defs: Optional[List[Dict[str, Any]]],
        observer: Any,
    ) -> tuple[Optional[Any], Optional[Exception]]:
        """Call LLM with retries (sync). Delegates to _retry module."""
        return call_with_retry_sync(
            self.llm, self.inference_config,
            prompt, stream_callback, native_tool_defs,
            observer, self._track_failed_call,
        )

    async def _call_with_retry_async(
        self,
        prompt: str,
        stream_callback: Optional[Callable],
        native_tool_defs: Optional[List[Dict[str, Any]]],
        observer: Any,
    ) -> tuple[Optional[Any], Optional[Exception]]:
        """Call LLM with retries (async). Delegates to _retry module."""
        return await call_with_retry_async(
            self.llm, self.inference_config,
            prompt, stream_callback, native_tool_defs,
            observer, self._track_failed_call,
        )

    def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        tool_executor: Any,
        observer: Any,
        safety_config: Any,
    ) -> List[Dict[str, Any]]:
        """Execute tool calls. Delegates to _tool_execution module."""
        return execute_tools(
            tool_calls, tool_executor, observer, safety_config,
            execute_single_tool,
        )

    @staticmethod
    def _execute_single_tool(
        tool_call: Dict[str, Any],
        tool_executor: Any,
        observer: Any,
        safety_config: Any,
    ) -> Dict[str, Any]:
        """Execute a single tool call. Delegates to _tool_execution module."""
        return execute_single_tool(tool_call, tool_executor, observer, safety_config)

    @staticmethod
    def _inject_results(
        system_prompt: str,
        llm_response_content: str,
        tool_results: List[Dict[str, Any]],
        conversation_turns: List[str],
        max_tool_result_size: int,
        max_prompt_length: int,
        remaining_tool_calls: Optional[int] = None,
    ) -> str:
        """Inject tool results into prompt. Delegates to _prompt module."""
        return inject_results(
            system_prompt, llm_response_content, tool_results,
            conversation_turns, max_tool_result_size, max_prompt_length,
            remaining_tool_calls,
        )

    def _build_text_schemas(self, tools: Optional[List[Any]]) -> Optional[str]:
        """Build text-based tool schemas. Delegates to _schemas module."""
        schemas, version = build_text_schemas(
            tools, self._cached_text_schemas, self._cached_text_schemas_version,
        )
        self._cached_text_schemas = schemas
        self._cached_text_schemas_version = version
        return schemas

    def _build_native_tool_defs(self, tools: Optional[List[Any]]) -> Optional[List[Dict[str, Any]]]:
        """Build native tool definitions. Delegates to _schemas module."""
        defs, hash_val = build_native_tool_defs(
            self.llm, tools,
            self._cached_native_defs, self._cached_native_defs_hash,
        )
        self._cached_native_defs = defs
        self._cached_native_defs_hash = hash_val
        return defs

    def _estimate_cost(self, llm_response: Any) -> float:
        """Estimate cost for an LLM response."""
        return estimate_cost(
            llm_response,
            fallback_model=getattr(self.llm, 'model', FALLBACK_UNKNOWN_VALUE),
        )

    def _track_call(
        self,
        observer: Any,
        prompt: str,
        llm_response: Any,
        cost: float,
    ) -> None:
        """Track a successful LLM call."""
        track_call(observer, self.inference_config, prompt, llm_response, cost)

    def _track_failed_call(
        self,
        observer: Any,
        prompt: str,
        error: Exception,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Track a failed LLM call."""
        track_failed_call(observer, self.inference_config, prompt, error, attempt, max_attempts)

    # ------------------------------------------------------------------
    # Pre-call hooks
    # ------------------------------------------------------------------

    def _run_pre_call_hooks(self, prompt: str) -> Optional[str]:
        """Run pre-call hooks. Returns blocking reason or None."""
        for hook in self.pre_call_hooks:
            try:
                result = hook(prompt)
                if result is not None:
                    return str(result)
            except (ValueError, RuntimeError, TypeError) as e:
                return f"Pre-call hook error: {e}"
        return None

    # ------------------------------------------------------------------
    # Limit resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_max_iterations(
        explicit: Optional[int],
        safety_config: Any,
    ) -> int:
        """Resolve max iterations from explicit param or safety config."""
        if explicit is not None:
            return explicit
        if safety_config is not None:
            return getattr(safety_config, 'max_tool_calls_per_execution', _DEFAULT_MAX_ITERATIONS)
        return _DEFAULT_MAX_ITERATIONS

    @staticmethod
    def _resolve_max_tool_result_size(safety_config: Any) -> int:
        """Resolve max tool result size from safety config."""
        if safety_config is not None:
            return getattr(safety_config, 'max_tool_result_size', 10000)  # scanner: skip-magic
        return 10000  # scanner: skip-magic

    @staticmethod
    def _resolve_max_prompt_length(safety_config: Any) -> int:
        """Resolve max prompt length from safety config."""
        if safety_config is not None:
            return getattr(safety_config, 'max_prompt_length', 32000)  # scanner: skip-magic
        return 32000  # scanner: skip-magic
