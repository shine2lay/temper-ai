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

from temper_ai.llm.constants import FALLBACK_UNKNOWN_VALUE
from temper_ai.llm.cost_estimator import estimate_cost
from temper_ai.llm.response_parser import (
    extract_final_answer,
    extract_reasoning,
    parse_tool_calls,
)
from temper_ai.llm.tool_keys import ToolKeys
from temper_ai.llm._prompt import inject_results
from temper_ai.llm._retry import call_with_retry_async, call_with_retry_sync
from temper_ai.llm._schemas import build_native_tool_defs, build_text_schemas
from temper_ai.llm._tool_execution import execute_single_tool, execute_tools
from temper_ai.llm._tracking import track_call, track_failed_call, validate_safety
from temper_ai.llm.llm_loop_events import LLMIterationEventData, emit_llm_iteration_event
from temper_ai.shared.utils.exceptions import MaxIterationsError, sanitize_error_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default iteration limit when safety config doesn't specify one
# ---------------------------------------------------------------------------
_DEFAULT_MAX_ITERATIONS = 10  # scanner: skip-magic


class _MessagesLLMWrapper:
    """Thin proxy that injects ``messages`` kwarg into every LLM call.

    Used to thread conversation history through the retry module without
    changing its signature.  Delegates all attribute access to the
    underlying LLM so that the wrapper is transparent to callers.
    """

    def __init__(self, llm: Any, messages: List[Dict[str, str]]) -> None:
        self._llm = llm
        self._messages = messages

    def complete(self, prompt: str, **kwargs: Any) -> Any:
        """Delegate to wrapped LLM with messages injected."""
        kwargs.setdefault("messages", self._messages)
        return self._llm.complete(prompt, **kwargs)

    async def acomplete(self, prompt: str, **kwargs: Any) -> Any:
        """Async delegate to wrapped LLM with messages injected."""
        kwargs.setdefault("messages", self._messages)
        return await self._llm.acomplete(prompt, **kwargs)

    def stream(self, prompt: str, **kwargs: Any) -> Any:
        """Streaming delegate to wrapped LLM with messages injected."""
        kwargs.setdefault("messages", self._messages)
        return self._llm.stream(prompt, **kwargs)

    async def astream(self, prompt: str, **kwargs: Any) -> Any:
        """Async streaming delegate to wrapped LLM with messages injected."""
        kwargs.setdefault("messages", self._messages)
        return await self._llm.astream(prompt, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


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
    # Conversation history support: the user/assistant texts for this turn
    user_message: Optional[str] = None
    assistant_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal loop state
# ---------------------------------------------------------------------------

@dataclass
class _RunState:
    """Mutable state for an LLM iteration loop."""

    # Configuration (set once during init)
    tools: Optional[List[Any]] = None
    tool_executor: Any = None
    observer: Any = None
    safety_config: Any = None
    agent_name: str = "unknown"
    stream_callback: Optional[Any] = None
    resolved_max_iterations: int = _DEFAULT_MAX_ITERATIONS
    max_tool_result_size: int = 10000  # scanner: skip-magic
    max_prompt_length: int = 32000  # scanner: skip-magic
    effective_start: float = 0.0
    effective_timeout: float = field(default_factory=lambda: float("inf"))
    native_tool_defs: Optional[List[Dict[str, Any]]] = None
    # Mutable state (changes per iteration)
    iteration_number: int = 0
    tool_calls_made: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0
    total_cost: float = 0.0
    conversation_turns: List[str] = field(default_factory=list)
    system_prompt: str = ""
    prompt: str = ""
    llm_response: Any = None
    # Multi-turn conversation history support
    messages: Optional[List[Dict[str, str]]] = None
    user_prompt_text: Optional[str] = None


# ---------------------------------------------------------------------------
# Limit resolution helpers (module-level, consumed by LLMService)
# ---------------------------------------------------------------------------

def resolve_max_iterations(
    explicit: Optional[int],
    safety_config: Any,
) -> int:
    """Resolve max iterations from explicit param or safety config."""
    if explicit is not None:
        return explicit
    if safety_config is not None:
        return getattr(safety_config, 'max_tool_calls_per_execution', _DEFAULT_MAX_ITERATIONS)
    return _DEFAULT_MAX_ITERATIONS


def resolve_max_tool_result_size(safety_config: Any) -> int:
    """Resolve max tool result size from safety config."""
    if safety_config is not None:
        return getattr(safety_config, 'max_tool_result_size', 10000)  # scanner: skip-magic
    return 10000  # scanner: skip-magic


def resolve_max_prompt_length(safety_config: Any) -> int:
    """Resolve max prompt length from safety config."""
    if safety_config is not None:
        return getattr(safety_config, 'max_prompt_length', 32000)  # scanner: skip-magic
    return 32000  # scanner: skip-magic


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

    def run(  # noqa: params
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
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> LLMRunResult:
        """Execute the LLM call lifecycle (sync).

        If *tools* is None or empty, performs a single LLM call.
        If *tools* is a list of BaseTool instances, enters the tool-calling loop.
        """
        s = _RunState(
            tools=tools, tool_executor=tool_executor, observer=observer,
            stream_callback=stream_callback, safety_config=safety_config,
            agent_name=agent_name,
        )
        self._prepare_run_state(s, prompt, max_iterations, max_execution_time, start_time, messages)

        for iteration in range(s.resolved_max_iterations):
            guard = self._check_iteration_guards(s, iteration)
            if guard is not None:
                return guard

            s.llm_response, last_error = self._call_with_retry_sync(
                s.prompt, s.stream_callback, s.native_tool_defs, s.observer,
                messages=s.messages,
            )
            if s.llm_response is None:
                return self._handle_llm_failure(last_error, s, iteration)

            s.iteration_number += 1
            parsed_calls = self._track_and_parse(s)
            if not parsed_calls:
                return self._build_final_result(s, iteration)

            self._execute_and_inject(s, parsed_calls)

        self._raise_max_iterations(s)
        raise AssertionError("unreachable")  # help mypy see NoReturn

    async def arun(  # noqa: params
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
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> LLMRunResult:
        """Execute the LLM call lifecycle (async).

        Async counterpart to run(). Same interface and behavior.
        """
        s = _RunState(
            tools=tools, tool_executor=tool_executor, observer=observer,
            stream_callback=stream_callback, safety_config=safety_config,
            agent_name=agent_name,
        )
        self._prepare_run_state(s, prompt, max_iterations, max_execution_time, start_time, messages)

        for iteration in range(s.resolved_max_iterations):
            guard = self._check_iteration_guards(s, iteration)
            if guard is not None:
                return guard

            s.llm_response, last_error = await self._call_with_retry_async(
                s.prompt, s.stream_callback, s.native_tool_defs, s.observer,
                messages=s.messages,
            )
            if s.llm_response is None:
                return self._handle_llm_failure(last_error, s, iteration)

            s.iteration_number += 1
            parsed_calls = self._track_and_parse(s)
            if not parsed_calls:
                return self._build_final_result(s, iteration)

            self._execute_and_inject(s, parsed_calls)

        self._raise_max_iterations(s)
        raise AssertionError("unreachable")  # help mypy see NoReturn

    # ------------------------------------------------------------------
    # Loop helpers (shared by run/arun)
    # ------------------------------------------------------------------

    def _prepare_run_state(
        self,
        s: _RunState,
        prompt: str,
        max_iterations: Optional[int],
        max_execution_time: Optional[float],
        start_time: Optional[float],
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """Resolve settings, build tool schemas, and initialize loop state."""
        s.resolved_max_iterations = resolve_max_iterations(max_iterations, s.safety_config)
        s.max_tool_result_size = resolve_max_tool_result_size(s.safety_config)
        s.max_prompt_length = resolve_max_prompt_length(s.safety_config)
        s.effective_start = start_time if start_time is not None else time.time()
        s.effective_timeout = max_execution_time or float("inf")

        s.native_tool_defs = self._build_native_tool_defs(s.tools) if s.tools else None
        text_schemas = None
        if s.tools and not s.native_tool_defs:
            text_schemas = self._build_text_schemas(s.tools)

        s.system_prompt = prompt
        s.prompt = prompt + text_schemas if text_schemas else prompt
        s.user_prompt_text = prompt
        if messages is not None:
            s.messages = list(messages)

    def _check_iteration_guards(
        self, s: _RunState, iteration: int,
    ) -> Optional[LLMRunResult]:
        """Check timeout, pre-call hooks, and safety. Returns result if blocked."""
        if time.time() - s.effective_start >= s.effective_timeout:
            return LLMRunResult(
                output="", tool_calls=s.tool_calls_made, tokens=s.total_tokens,
                cost=s.total_cost, iterations=iteration,
                error=f"Execution time limit exceeded ({s.effective_timeout}s)",
            )

        blocked = self._run_pre_call_hooks(s.prompt)
        if blocked is not None:
            return LLMRunResult(
                output="", tool_calls=s.tool_calls_made, tokens=s.total_tokens,
                cost=s.total_cost, iterations=iteration,
                error=f"LLM call blocked by pre-call hook: {blocked}",
            )

        safety_error = validate_safety(s.tool_executor, self.inference_config, s.prompt, s.agent_name)
        if safety_error is not None:
            return LLMRunResult(
                output="", tool_calls=s.tool_calls_made, tokens=s.total_tokens,
                cost=s.total_cost, iterations=iteration, error=safety_error,
            )
        return None

    def _handle_llm_failure(
        self, last_error: Optional[Exception], s: _RunState, iteration: int,
    ) -> LLMRunResult:
        """Build error result when LLM call fails after retries."""
        max_attempts = self.inference_config.max_retries + 1
        error_msg = f"LLM call failed after {max_attempts} attempts"
        if last_error:
            error_msg += f": {sanitize_error_message(str(last_error))}"
        return LLMRunResult(
            output="", tool_calls=s.tool_calls_made, tokens=s.total_tokens,
            cost=s.total_cost, iterations=iteration + 1, error=error_msg,
        )

    def _track_and_parse(self, s: _RunState) -> List[Dict[str, Any]]:
        """Track response metrics and return parsed tool calls."""
        resp = s.llm_response
        logger.info("[%s] LLM responded (%s tokens)", s.agent_name, resp.total_tokens or "?")
        iter_tokens = resp.total_tokens or 0
        if iter_tokens:
            s.total_tokens += iter_tokens
        cost = self._estimate_cost(resp)
        s.total_cost += cost
        self._track_call(s.observer, s.prompt, resp, cost)

        parsed_calls = parse_tool_calls(resp.content) if s.tools else []

        emit_llm_iteration_event(s.observer, LLMIterationEventData(
            iteration_number=s.iteration_number,
            agent_name=s.agent_name,
            conversation_turns_count=len(s.conversation_turns),
            tool_calls_this_iteration=len(parsed_calls),
            total_tokens_this_iteration=iter_tokens,
            total_cost_this_iteration=cost,
        ))

        return parsed_calls

    def _build_final_result(self, s: _RunState, iteration: int) -> LLMRunResult:
        """Build final result when no tool calls are needed."""
        output = extract_final_answer(s.llm_response.content)
        return LLMRunResult(
            output=output,
            reasoning=extract_reasoning(s.llm_response.content),
            tool_calls=s.tool_calls_made, tokens=s.total_tokens,
            cost=s.total_cost, iterations=iteration + 1,
            raw_response=s.llm_response,
            user_message=s.user_prompt_text,
            assistant_message=output,
        )

    def _execute_and_inject(self, s: _RunState, parsed_calls: List[Dict[str, Any]]) -> None:
        """Execute tool calls and inject results into prompt."""
        tool_names = ", ".join(tc.get(ToolKeys.NAME, "?") for tc in parsed_calls)
        logger.info("[%s] Calling %d tool(s): %s", s.agent_name, len(parsed_calls), tool_names)

        tool_results = self._execute_tools(
            parsed_calls, s.tool_executor, s.observer, s.safety_config,
        )
        s.tool_calls_made.extend(tool_results)

        remaining_budget = None
        if s.resolved_max_iterations is not None:
            remaining_budget = s.resolved_max_iterations - len(s.tool_calls_made)

        s.prompt = inject_results(
            s.system_prompt, s.llm_response.content, tool_results,
            s.conversation_turns, s.max_tool_result_size, s.max_prompt_length,
            remaining_budget,
        )
        # After first tool iteration, clear messages so subsequent
        # iterations use the text-based inject_results prompt
        s.messages = None

    def _raise_max_iterations(self, s: _RunState) -> None:
        """Raise MaxIterationsError when iteration limit is reached."""
        raise MaxIterationsError(
            iterations=s.resolved_max_iterations or 0,
            tool_calls=s.tool_calls_made,
            tokens=s.total_tokens, cost=s.total_cost,
            last_output=s.llm_response.content if s.llm_response else "",
            last_reasoning=extract_reasoning(s.llm_response.content) if s.llm_response else None,
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
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[Optional[Any], Optional[Exception]]:
        """Call LLM with retries (sync). Delegates to _retry module."""
        llm = _MessagesLLMWrapper(self.llm, messages) if messages else self.llm
        return call_with_retry_sync(
            llm, self.inference_config,
            prompt, stream_callback, native_tool_defs,
            observer, self._track_failed_call,
        )

    async def _call_with_retry_async(
        self,
        prompt: str,
        stream_callback: Optional[Callable],
        native_tool_defs: Optional[List[Dict[str, Any]]],
        observer: Any,
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[Optional[Any], Optional[Exception]]:
        """Call LLM with retries (async). Delegates to _retry module."""
        llm = _MessagesLLMWrapper(self.llm, messages) if messages else self.llm
        return await call_with_retry_async(
            llm, self.inference_config,
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
    # Limit resolution helpers (delegated to module-level functions)
    # ------------------------------------------------------------------
