"""LLM service — the tool-calling loop with full observability.

Orchestrates: call LLM -> parse tool calls -> execute tools -> inject results -> repeat.
Records events at every level: LLM calls, tool calls, and iteration summaries.
"""

import json
import logging
import time
from typing import Any

from temper_ai.llm.models import CallContext, LLMResponse, LLMRunResult
from temper_ai.llm.pricing import estimate_cost
from temper_ai.llm.providers.base import BaseLLM, StreamCallback
from temper_ai.llm.response_parser import extract_final_answer, parse_tool_calls
from temper_ai.llm.tool_execution import ToolExecutorFn, execute_tool_calls
from temper_ai.observability import EventType, record

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MAX_MESSAGES = 50
DEFAULT_MAX_CONTEXT_TOKENS = 120_000  # Conservative default — most models handle at least 128k
MAX_TOOL_RESULT_CHARS = 20_000  # ~5k tokens — prevents context overflow from large tool outputs


class LLMService:
    """Orchestrates the LLM tool-calling loop.

    Calls the provider, parses tool calls, executes tools, injects results,
    and repeats until the LLM produces a final response or max iterations hit.
    Records observability events at every step.
    """

    def __init__(
        self,
        provider: BaseLLM,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        total_timeout: float = 300.0,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
    ) -> None:
        self.provider = provider
        self.max_iterations = max_iterations
        self.max_messages = max_messages
        self.total_timeout = total_timeout  # Overall timeout for the entire run loop
        self.max_context_tokens = max_context_tokens

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        execute_tool: ToolExecutorFn | None = None,
        context: CallContext | None = None,
        stream_callback: StreamCallback | None = None,
        budget_check: Any | None = None,
    ) -> LLMRunResult:
        """Run the LLM tool-calling loop."""
        # Store per-run state so helpers don't need many parameters
        self._ctx = context or CallContext()
        self._record = self._ctx.event_recorder or record
        self._messages = messages
        self._tools = tools
        self._execute_tool = execute_tool
        self._stream_callback = stream_callback
        self._all_tool_calls: list[dict[str, Any]] = []
        self._total_tokens = 0
        self._total_cost = 0.0
        self._response: LLMResponse | None = None
        self._run_start = time.monotonic()
        self._budget_check = budget_check
        self._usage_tracker = None

        for iteration in range(1, self.max_iterations + 1):
            # Check budget before each LLM call
            if self._budget_check:
                denial = self._budget_check()
                if denial:
                    return self._build_result(
                        iteration - 1,
                        error=f"Budget exceeded: {denial}",
                    )

            result = self._run_iteration(iteration)
            if result is not None:
                return result

        return self._build_max_iterations_result()

    def _run_iteration(self, iteration: int) -> LLMRunResult | None:
        """Run one iteration of the tool-calling loop. Returns result if done, None to continue."""
        elapsed = time.monotonic() - self._run_start
        if elapsed > self.total_timeout:
            logger.warning("LLM run timeout after %.0fs for '%s'", elapsed, self._ctx.agent_name)
            return self._build_result(iteration - 1, error=f"LLM run timed out after {elapsed:.0f}s")

        llm_event_id, self._response, iter_cost = self._call_llm(iteration)
        self._total_tokens += self._response.total_tokens or 0
        self._total_cost += iter_cost

        # Report usage so budget tracking stays current between iterations
        if self._budget_check and hasattr(self, '_usage_tracker') and self._usage_tracker:
            self._usage_tracker(iter_cost, self._response.total_tokens or 0)

        tool_calls = parse_tool_calls(self._response)
        if not tool_calls:
            self._record_iteration(iteration, "final_response", 0)
            return self._build_result(iteration, output=extract_final_answer(self._response))

        if self._execute_tool is None:
            return self._handle_no_executor(iteration, tool_calls)

        self._execute_and_inject_tools(tool_calls, llm_event_id)
        self._record_iteration(iteration, "tool_calls", len(tool_calls))
        return None  # continue loop

    def _call_llm(self, iteration: int) -> tuple[str, LLMResponse, float]:
        """Call the LLM provider and record events. Returns (event_id, response, cost).

        Cost precedence:
          1. Provider's authoritative `raw_response.total_cost_usd` if present
             (e.g. Claude Code reports the actual Anthropic-billed cost with
             cache-read / cache-write discounts applied).
          2. Fallback to `estimate_cost()` which multiplies prompt_tokens by
             the full input rate — over-estimates when cache hits are common,
             but is the best we can do when the provider doesn't report cost.
        """
        event_id = self._record_llm_started(iteration)
        try:
            response = self._invoke_provider()
            raw = response.raw_response or {}
            provider_cost = raw.get("total_cost_usd")
            if provider_cost is not None:
                try:
                    cost = float(provider_cost)
                except (TypeError, ValueError):
                    cost = estimate_cost(
                        response.model, response.prompt_tokens,
                        response.completion_tokens, response.total_tokens,
                    )
            else:
                cost = estimate_cost(
                    response.model, response.prompt_tokens,
                    response.completion_tokens, response.total_tokens,
                )
            self._record_llm_completed(event_id, response, cost, iteration)
            return event_id, response, cost
        except Exception as e:  # noqa: broad-except
            self._record_llm_failed(iteration, e)
            raise

    def _invoke_provider(self) -> LLMResponse:
        """Call the LLM provider (stream or complete).

        Checks estimated context size before calling. If over the limit,
        aggressively trims tool results and old messages to fit.
        """
        _enforce_context_limit(self._messages, self.max_context_tokens, self.max_messages)
        # Debug: verify user message survived trimming
        roles = [m.get("role") for m in self._messages]
        if "user" not in roles:
            logger.error(
                "BUG: No user message after context trimming! Roles: %s (total: %d msgs)",
                roles[:10], len(self._messages),
            )

        kwargs: dict[str, Any] = {}
        if self._tools:
            kwargs["tools"] = self._tools
        if self._ctx.cwd:
            kwargs["cwd"] = self._ctx.cwd
        if self._ctx.model:
            kwargs["model"] = self._ctx.model
        if self._stream_callback:
            return self.provider.stream(self._messages, on_chunk=self._stream_callback, **kwargs)
        return self.provider.complete(self._messages, **kwargs)

    def _execute_and_inject_tools(self, tool_calls: list[dict], llm_event_id: str) -> None:
        """Execute tools, track results, inject into messages."""
        assert self._execute_tool is not None  # noqa: B101
        assert self._response is not None  # noqa: B101
        tool_results = execute_tool_calls(
            tool_calls=tool_calls, execute_tool=self._execute_tool,
            context=self._ctx, llm_call_event_id=llm_event_id,
        )
        for tc, tr in zip(tool_calls, tool_results):
            self._all_tool_calls.append({
                "name": tc["name"], "arguments": tc["arguments"],
                "result": tr["result"], "success": tr["success"],
            })
        _inject_tool_results(self._messages, self._response, tool_calls, tool_results)
        _apply_message_window(self._messages, self.max_messages)

    def _handle_no_executor(self, iteration: int, tool_calls: list[dict]) -> LLMRunResult:
        """Handle case where LLM requests tools but no executor is available."""
        logger.error("LLM returned %d tool calls but no execute_tool provided", len(tool_calls))
        self._record(EventType.LLM_NO_EXECUTOR, parent_id=self._ctx.agent_event_id,
                     execution_id=self._ctx.execution_id, status="failed",
                     data={"agent_name": self._ctx.agent_name, "iteration": iteration,
                           "tool_calls_requested": [tc["name"] for tc in tool_calls]})
        return self._build_result(iteration, error="Tool calls requested but no tool executor available")

    def _build_result(self, iterations: int, output: str = "", error: str | None = None) -> LLMRunResult:
        return LLMRunResult(output=output, tool_calls=self._all_tool_calls,
                            tokens=self._total_tokens, cost=round(self._total_cost, 6),
                            iterations=iterations, error=error)

    def _build_max_iterations_result(self) -> LLMRunResult:
        logger.warning("Hit max iterations (%d) for '%s'", self.max_iterations, self._ctx.agent_name)
        self._record(EventType.LLM_MAX_ITERATIONS, parent_id=self._ctx.agent_event_id,
                     execution_id=self._ctx.execution_id, status="failed",
                     data={"agent_name": self._ctx.agent_name, "max_iterations": self.max_iterations,
                           "total_tokens": self._total_tokens, "total_cost": round(self._total_cost, 6)})
        output = extract_final_answer(self._response) if self._response else ""
        return self._build_result(self.max_iterations, output=output,
                                  error=f"Reached max iterations ({self.max_iterations})")

    def _record_llm_started(self, iteration: int) -> str:
        return self._record(
            EventType.LLM_CALL_STARTED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="running",
            data={"agent_name": self._ctx.agent_name, "node_path": self._ctx.node_path,
                  "model": self.provider.model, "provider": self.provider.provider_name,
                  "temperature": self.provider.temperature, "max_tokens": self.provider.max_tokens,
                  "iteration": iteration, "message_count": len(self._messages),
                  "messages": self._messages,
                  "tools_available": len(self._tools) if self._tools else 0,
                  "streaming": self._stream_callback is not None})

    def _record_llm_completed(self, event_id: str, response: LLMResponse, cost: float, iteration: int) -> None:
        self._record(
            EventType.LLM_CALL_COMPLETED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="completed",
            data={"model": response.model, "prompt_tokens": response.prompt_tokens,
                  "completion_tokens": response.completion_tokens, "total_tokens": response.total_tokens,
                  "latency_ms": response.latency_ms, "finish_reason": response.finish_reason,
                  "cost_usd": cost, "has_tool_calls": bool(response.tool_calls),
                  "tool_calls_requested": [{"name": tc.get("name"), "id": tc.get("id")}
                                           for tc in (response.tool_calls or [])] or None,
                  "iteration": iteration, "response_content": response.content,
                  "reasoning": response.reasoning})

    def _record_llm_failed(self, iteration: int, exc: Exception) -> None:
        self._record(
            EventType.LLM_CALL_FAILED, parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id, status="failed",
            data={"model": self.provider.model, "provider": self.provider.provider_name,
                  "iteration": iteration, "error_type": type(exc).__name__,
                  "error": str(exc)[:500], "agent_name": self._ctx.agent_name})

    def _record_iteration(
        self,
        iteration: int,
        action: str,
        tool_count: int,
    ) -> None:
        """Record an iteration summary event."""
        self._record(
            EventType.LLM_ITERATION,
            parent_id=self._ctx.agent_event_id,
            execution_id=self._ctx.execution_id,
            data={
                "agent_name": self._ctx.agent_name,
                "node_path": self._ctx.node_path,
                "iteration": iteration,
                "action": action,
                "tool_count": tool_count,
                "total_tokens_so_far": self._total_tokens,
            },
        )


def _inject_tool_results(
    messages: list[dict],
    response: LLMResponse,
    tool_calls: list[dict],
    tool_results: list[dict],
) -> None:
    """Append the assistant's tool-call message and tool result messages."""
    # Assistant message with tool calls (OpenAI format)
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": (
                        json.dumps(tc["arguments"])
                        if isinstance(tc["arguments"], dict)
                        else str(tc["arguments"])
                    ),
                },
            }
            for tc in tool_calls
        ],
    }
    # Always include content field — some models (Qwen3, Kimi K2) mishandle
    # tool-call messages without an explicit content field, causing tool-calling loops.
    assistant_msg["content"] = response.content or ""
    messages.append(assistant_msg)

    # One tool-result message per tool call (truncate large results)
    for tr in tool_results:
        content = tr["result"]
        if len(content) > MAX_TOOL_RESULT_CHARS:
            content = content[:MAX_TOOL_RESULT_CHARS] + f"\n\n... [truncated from {len(tr['result'])} chars]"
        messages.append({
            "role": "tool",
            "tool_call_id": tr["tool_call_id"],
            "content": content,
        })


def _estimate_messages_tokens(messages: list[dict]) -> int:
    """Rough token estimate for a message list (~3 chars per token).

    Uses 3 chars/token (conservative) to avoid underestimating and
    hitting model context limits.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if content:
            total += len(content) // 3 + 4  # message overhead
        # Tool calls in assistant messages
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total += len(fn.get("name", "")) // 3
            total += len(str(fn.get("arguments", ""))) // 3
    return total


def _enforce_context_limit(messages: list[dict], max_tokens: int, max_messages: int) -> None:
    """Trim messages to stay under the context token limit.

    Strategy (in order):
    1. Apply message window (keep system + recent N)
    2. Truncate large tool results to 5000 chars
    3. If still over, truncate tool results to 2000 chars
    4. If still over, apply tighter message window (keep system + last 10)
    """
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 1: apply normal message window
    _apply_message_window(messages, max_messages)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 2: truncate large tool results
    _truncate_tool_results(messages, 5000)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 3: more aggressive truncation
    _truncate_tool_results(messages, 2000)
    est = _estimate_messages_tokens(messages)
    if est <= max_tokens:
        return

    # Step 4: tight message window
    _apply_message_window(messages, 10)
    _truncate_tool_results(messages, 1000)

    est = _estimate_messages_tokens(messages)
    if est > max_tokens:
        logger.warning(
            "Context still exceeds limit after all trimming: ~%d tokens (limit %d). "
            "Proceeding anyway — provider may reject.",
            est, max_tokens,
        )


def _truncate_tool_results(messages: list[dict], max_chars: int) -> None:
    """Truncate tool result message content to max_chars."""
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("content"):
            content = msg["content"]
            if len(content) > max_chars:
                msg["content"] = content[:max_chars] + f"\n\n... [truncated from {len(content)} chars]"


def _apply_message_window(messages: list[dict], max_messages: int) -> None:
    """Keep the first message (system prompt) and the most recent messages.

    Prevents unbounded message growth in long tool-calling loops.
    Ensures tool-call pairs (assistant + tool results) are never split,
    which would cause the API to reject orphaned tool_call_ids.
    """
    if len(messages) <= max_messages:
        return

    # Keep system + first user message (required by chat templates) + recent tail
    # Find the first user message index
    first_user_idx = next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)
    prefix_end = (first_user_idx + 1) if first_user_idx is not None else 1
    prefix = messages[:prefix_end]

    tail = messages[-(max_messages - prefix_end):]

    # If tail starts with orphaned tool result messages, skip them
    # to find a clean turn boundary
    start = 0
    while start < len(tail) and tail[start].get("role") == "tool":
        start += 1

    keep = prefix + tail[start:]
    messages.clear()
    messages.extend(keep)
