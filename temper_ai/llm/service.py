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
    ) -> None:
        self.provider = provider
        self.max_iterations = max_iterations
        self.max_messages = max_messages
        self.total_timeout = total_timeout  # Overall timeout for the entire run loop

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        execute_tool: ToolExecutorFn | None = None,
        context: CallContext | None = None,
        stream_callback: StreamCallback | None = None,
    ) -> LLMRunResult:
        """Run the LLM tool-calling loop.

        Args:
            messages: Initial conversation messages (OpenAI format).
            tools: Tool definitions (OpenAI function calling format).
            execute_tool: Function to execute a tool: (name, params) -> result.
            context: Caller identity for observability.
            stream_callback: Optional callback for streaming chunks.

        Returns:
            LLMRunResult with final output, tool calls made, tokens, cost, iterations.
        """
        ctx = context or CallContext()
        self._record = ctx.event_recorder or record
        all_tool_calls: list[dict[str, Any]] = []
        total_tokens = 0
        total_cost = 0.0
        response: LLMResponse | None = None
        run_start = time.monotonic()

        for iteration in range(1, self.max_iterations + 1):
            # Check overall timeout
            elapsed = time.monotonic() - run_start
            if elapsed > self.total_timeout:
                logger.warning(
                    "LLM run timeout after %.0fs (%d iterations) for agent '%s'",
                    elapsed, iteration - 1, ctx.agent_name,
                )
                return LLMRunResult(
                    output="",
                    tool_calls=all_tool_calls,
                    tokens=total_tokens,
                    cost=round(total_cost, 6),
                    iterations=iteration - 1,
                    error=f"LLM run timed out after {elapsed:.0f}s",
                )
            # -- Call LLM with observability --
            llm_event_id, response, iter_cost = self._call_llm(
                messages=messages,
                tools=tools,
                context=ctx,
                iteration=iteration,
                stream_callback=stream_callback,
            )

            # -- Accumulate tokens and cost --
            total_tokens += response.total_tokens or 0
            total_cost += iter_cost

            # -- Parse tool calls --
            tool_calls = parse_tool_calls(response)

            if not tool_calls:
                # Final response — LLM is done
                self._record_iteration(
                    ctx, iteration, "final_response",
                    tool_count=0, total_tokens=total_tokens,
                )
                return LLMRunResult(
                    output=extract_final_answer(response),
                    tool_calls=all_tool_calls,
                    tokens=total_tokens,
                    cost=round(total_cost, 6),
                    iterations=iteration,
                )

            # -- Execute tools --
            if execute_tool is None:
                logger.error(
                    "LLM returned %d tool calls but no execute_tool provided",
                    len(tool_calls),
                )
                self._record(
                    EventType.LLM_NO_EXECUTOR,
                    parent_id=ctx.agent_event_id,
                    execution_id=ctx.execution_id,
                    status="failed",
                    data={
                        "agent_name": ctx.agent_name,
                        "iteration": iteration,
                        "tool_calls_requested": [tc["name"] for tc in tool_calls],
                    },
                )
                return LLMRunResult(
                    output="",
                    tool_calls=all_tool_calls,
                    tokens=total_tokens,
                    cost=round(total_cost, 6),
                    iterations=iteration,
                    error="Tool calls requested but no tool executor available",
                )

            tool_results = execute_tool_calls(
                tool_calls=tool_calls,
                execute_tool=execute_tool,
                context=ctx,
                llm_call_event_id=llm_event_id,
            )

            # -- Track tool calls for the final result --
            for tc, tr in zip(tool_calls, tool_results):
                all_tool_calls.append({
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "result": tr["result"],
                    "success": tr["success"],
                })

            # -- Inject tool results into messages --
            _inject_tool_results(messages, response, tool_calls, tool_results)

            # -- Apply message window to prevent unbounded growth --
            _apply_message_window(messages, self.max_messages)

            self._record_iteration(
                ctx, iteration, "tool_calls",
                tool_count=len(tool_calls), total_tokens=total_tokens,
            )

        # Hit max iterations without a final response
        logger.warning(
            "Hit max iterations (%d) for agent '%s'",
            self.max_iterations, ctx.agent_name,
        )
        self._record(
            EventType.LLM_MAX_ITERATIONS,
            parent_id=ctx.agent_event_id,
            execution_id=ctx.execution_id,
            status="failed",
            data={
                "agent_name": ctx.agent_name,
                "node_path": ctx.node_path,
                "max_iterations": self.max_iterations,
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 6),
                "tool_calls_made": len(all_tool_calls),
            },
        )
        return LLMRunResult(
            output=extract_final_answer(response) if response else "",
            tool_calls=all_tool_calls,
            tokens=total_tokens,
            cost=round(total_cost, 6),
            iterations=self.max_iterations,
            error=f"Reached max iterations ({self.max_iterations})",
        )

    def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        context: CallContext,
        iteration: int,
        stream_callback: StreamCallback | None,
    ) -> tuple[str, LLMResponse, float]:
        """Call the LLM provider and record start/completed/failed events.

        Returns (event_id, response, cost_usd).
        """
        event_id = self._record(
            EventType.LLM_CALL_STARTED,
            parent_id=context.agent_event_id,
            execution_id=context.execution_id,
            status="running",
            data={
                "agent_name": context.agent_name,
                "node_path": context.node_path,
                "model": self.provider.model,
                "provider": self.provider.provider_name,
                "temperature": self.provider.temperature,
                "max_tokens": self.provider.max_tokens,
                "iteration": iteration,
                "message_count": len(messages),
                "messages": messages,
                "tools_available": len(tools) if tools else 0,
                "streaming": stream_callback is not None,
            },
        )

        try:
            kwargs: dict[str, Any] = {}
            if tools:
                kwargs["tools"] = tools

            if stream_callback:
                response = self.provider.stream(
                    messages, on_chunk=stream_callback, **kwargs,
                )
            else:
                response = self.provider.complete(messages, **kwargs)

            cost = estimate_cost(
                response.model,
                response.prompt_tokens,
                response.completion_tokens,
                response.total_tokens,
            )

            self._record(
                EventType.LLM_CALL_COMPLETED,
                parent_id=context.agent_event_id,
                execution_id=context.execution_id,
                status="completed",
                data={
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                    "latency_ms": response.latency_ms,
                    "finish_reason": response.finish_reason,
                    "cost_usd": cost,
                    "has_tool_calls": bool(response.tool_calls),
                    "tool_calls_requested": [
                        {"name": tc.get("name"), "id": tc.get("id")}
                        for tc in (response.tool_calls or [])
                    ] or None,
                    "iteration": iteration,
                    "response_content": response.content,
                    "reasoning": response.reasoning,
                },
            )

            return event_id, response, cost

        except Exception as e:  # noqa: broad-except
            self._record(
                EventType.LLM_CALL_FAILED,
                parent_id=context.agent_event_id,
                execution_id=context.execution_id,
                status="failed",
                data={
                    "model": self.provider.model,
                    "provider": self.provider.provider_name,
                    "iteration": iteration,
                    "error_type": type(e).__name__,
                    "error": str(e)[:500],
                    "agent_name": context.agent_name,
                },
            )
            raise

    def _record_iteration(
        self,
        context: CallContext,
        iteration: int,
        action: str,
        tool_count: int,
        total_tokens: int,
    ) -> None:
        """Record an iteration summary event."""
        self._record(
            EventType.LLM_ITERATION,
            parent_id=context.agent_event_id,
            execution_id=context.execution_id,
            data={
                "agent_name": context.agent_name,
                "node_path": context.node_path,
                "iteration": iteration,
                "action": action,
                "tool_count": tool_count,
                "total_tokens_so_far": total_tokens,
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
    # Only include content when present — some APIs reject "content": null
    if response.content is not None:
        assistant_msg["content"] = response.content
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


def _apply_message_window(messages: list[dict], max_messages: int) -> None:
    """Keep the first message (system prompt) and the most recent messages.

    Prevents unbounded message growth in long tool-calling loops.
    Ensures tool-call pairs (assistant + tool results) are never split,
    which would cause the API to reject orphaned tool_call_ids.
    """
    if len(messages) <= max_messages:
        return

    # Keep first message + most recent (max_messages - 1)
    tail = messages[-(max_messages - 1):]

    # If tail starts with orphaned tool result messages, skip them
    # to find a clean turn boundary
    start = 0
    while start < len(tail) and tail[start].get("role") == "tool":
        start += 1

    keep = messages[:1] + tail[start:]
    messages.clear()
    messages.extend(keep)
