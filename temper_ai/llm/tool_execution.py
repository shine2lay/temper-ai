"""Tool execution — run tool calls with observability.

Each tool call is recorded as a pair of events (started + completed/failed)
with timing, inputs, and outputs.
"""

import logging
import time
from typing import Any, Callable

from temper_ai.llm.models import CallContext
from temper_ai.observability import EventType, record

logger = logging.getLogger(__name__)

# Tool executor: (tool_name, params_dict) -> result
ToolExecutorFn = Callable[[str, dict[str, Any]], Any]


def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    execute_tool: ToolExecutorFn,
    context: CallContext | None = None,
    llm_call_event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Execute a list of parsed tool calls and return results.

    Each result dict contains:
        - tool_call_id: ID from the LLM response
        - name: tool name
        - result: string output (success or error message)
        - success: bool
        - duration_ms: int
    """
    return [
        _execute_single(
            tool_call_id=tc["id"],
            name=tc["name"],
            arguments=tc["arguments"],
            execute_tool=execute_tool,
            context=context,
            parent_id=llm_call_event_id,
        )
        for tc in tool_calls
    ]


def _execute_single(
    tool_call_id: str,
    name: str,
    arguments: dict[str, Any],
    execute_tool: ToolExecutorFn,
    context: CallContext | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """Execute a single tool call with observability."""
    ctx = context or CallContext()
    _record = ctx.event_recorder or record

    _record_tool_started(_record, name, arguments, ctx, parent_id)

    start = time.monotonic()
    try:
        output = execute_tool(name, arguments)
        duration_ms = int((time.monotonic() - start) * 1000)
        return _build_success_result(_record, tool_call_id, name, output, duration_ms, ctx, parent_id)

    except Exception as e:  # noqa: broad-except
        duration_ms = int((time.monotonic() - start) * 1000)
        return _build_failure_result(_record, tool_call_id, name, e, duration_ms, ctx, parent_id)


def _record_tool_started(
    _record: Any,
    name: str,
    arguments: dict[str, Any],
    ctx: CallContext,
    parent_id: str | None,
) -> None:
    """Record a TOOL_CALL_STARTED event."""
    _record(
        EventType.TOOL_CALL_STARTED,
        parent_id=parent_id,
        execution_id=ctx.execution_id,
        status="running",
        data={
            "tool_name": name,
            "input_params": arguments,
            "agent_name": ctx.agent_name,
            "node_path": ctx.node_path,
        },
    )


def _build_success_result(
    _record: Any,
    tool_call_id: str,
    name: str,
    output: Any,
    duration_ms: int,
    ctx: CallContext,
    parent_id: str | None,
) -> dict[str, Any]:
    """Record completion and return a success result dict."""
    result_str = str(output) if output is not None else ""
    _record(
        EventType.TOOL_CALL_COMPLETED,
        parent_id=parent_id,
        execution_id=ctx.execution_id,
        status="completed",
        data={"tool_name": name, "duration_ms": duration_ms, "output": result_str},
    )
    return {
        "tool_call_id": tool_call_id,
        "name": name,
        "result": result_str,
        "success": True,
        "duration_ms": duration_ms,
    }


def _build_failure_result(
    _record: Any,
    tool_call_id: str,
    name: str,
    exc: Exception,
    duration_ms: int,
    ctx: CallContext,
    parent_id: str | None,
) -> dict[str, Any]:
    """Record failure and return an error result dict."""
    error_msg = f"{type(exc).__name__}: {exc}"
    _record(
        EventType.TOOL_CALL_FAILED,
        parent_id=parent_id,
        execution_id=ctx.execution_id,
        status="failed",
        data={"tool_name": name, "duration_ms": duration_ms, "error": error_msg, "agent_name": ctx.agent_name},
    )
    logger.warning("Tool '%s' failed after %dms: %s", name, duration_ms, error_msg)
    return {
        "tool_call_id": tool_call_id,
        "name": name,
        "result": f"Error: {error_msg}",
        "success": False,
        "duration_ms": duration_ms,
    }


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
