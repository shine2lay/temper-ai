"""Tool calls that happen *inside* a provider, and how any tool call is classified.

Two kinds of tool call reach the event log:

* Temper-executed. The model asks for a tool, temper runs it and records
  ``tool.call.started`` / ``completed`` / ``failed`` under the LLM call
  (``tool_execution.py``). MCP tools take this path when the provider
  returns tool calls for temper to execute.

* Provider-executed. Some providers run tools themselves and hand back a
  finished answer — Claude Code runs Bash, WebSearch and every MCP server
  it was given, all inside its own process. Until now nothing about those
  calls reached temper: a run that made five browser calls through MCP
  reported "Tool Calls 0". A provider that can see its own tool activity
  reports it through ``on_tool_event`` and it is recorded in exactly the
  shape the temper-executed path uses, so the dashboard, the API and the
  MCP inspection tools show both kinds the same way — with ``transport``,
  ``server`` and ``executed_by`` saying which is which.

Classification is by name. Claude Code names an MCP tool
``mcp__<server>__<tool>``; temper's own MCP wrapper names it
``<server>.<tool>``. Anything else is a built-in of whoever ran it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypedDict

from temper_ai.observability import EventType

logger = logging.getLogger(__name__)

MCP_PREFIX = "mcp__"
OUTPUT_LIMIT = 8_000  # chars kept from a tool result; the model saw more, the log does not need it


class ToolClassification(TypedDict):
    transport: str  # "mcp" | "builtin"
    server: str | None
    tool: str  # the tool's own name, without server decoration


def classify_tool(name: str, known_servers: set[str] | None = None) -> ToolClassification:
    """Where a tool call went, from its name alone.

    ``mcp__browser__browser_status`` → mcp / browser / browser_status.
    ``browser.browser_status`` → mcp / browser / browser_status when
    ``browser`` is a configured MCP server (temper's own naming).
    Everything else is a built-in.
    """
    if name.startswith(MCP_PREFIX):
        rest = name[len(MCP_PREFIX):]
        server, sep, tool = rest.partition("__")
        if sep and server and tool:
            return {"transport": "mcp", "server": server, "tool": tool}
    if known_servers and "." in name:
        server, _, tool = name.partition(".")
        if server in known_servers and tool:
            return {"transport": "mcp", "server": server, "tool": tool}
    return {"transport": "builtin", "server": None, "tool": name}


class ProviderToolEvent(TypedDict, total=False):
    """What a provider reports about one tool call it ran itself.

    ``phase`` is ``"started"`` or ``"completed"``. ``call_id`` ties the two
    together and must be stable for one call. ``is_error`` marks a
    completed call whose tool returned an error.
    """

    phase: str
    call_id: str
    tool_name: str
    input: dict[str, Any] | None
    output: str | None
    is_error: bool
    duration_ms: int | None


ToolEventCallback = Callable[[ProviderToolEvent], None]


def _clip(text: Any, limit: int = OUTPUT_LIMIT) -> str:
    s = text if isinstance(text, str) else str(text)
    return s if len(s) <= limit else s[:limit] + f"\n…[{len(s) - limit} more chars]"


def make_provider_tool_recorder(
    record: Callable[..., Any],
    *,
    execution_id: str | None,
    agent_event_id: str | None,
    agent_name: str | None,
    node_path: str | None,
    parent_id: str | None,
    provider_name: str,
) -> ToolEventCallback:
    """Build the callback a provider calls for each tool it runs itself.

    Records the same three event types the temper-executed path records,
    parented to the LLM call, so every existing reader — the DAG card
    counts, the Event Log, get_node_output — picks them up without knowing
    which side ran the tool. Never raises: a provider must not fail its
    call because bookkeeping did.
    """
    started_at: dict[str, float] = {}

    def on_tool_event(event: ProviderToolEvent) -> None:
        try:
            phase = event.get("phase")
            call_id = str(event.get("call_id") or "")
            name = str(event.get("tool_name") or "?")
            kind = classify_tool(name)
            common = {
                "tool_name": kind["tool"],
                "raw_tool_name": name,
                "transport": kind["transport"],
                "server": kind["server"],
                "executed_by": provider_name,
                "call_id": call_id,
                "agent_id": agent_event_id,
                "agent_name": agent_name,
            }
            if phase == "started":
                started_at[call_id] = time.monotonic()
                record(
                    EventType.TOOL_CALL_STARTED,
                    parent_id=parent_id,
                    execution_id=execution_id,
                    status="running",
                    data={**common, "input_params": event.get("input") or {}, "node_path": node_path},
                )
                return
            if phase == "completed":
                duration = event.get("duration_ms")
                if duration is None and call_id in started_at:
                    duration = int((time.monotonic() - started_at.pop(call_id)) * 1000)
                if event.get("is_error"):
                    record(
                        EventType.TOOL_CALL_FAILED,
                        parent_id=parent_id,
                        execution_id=execution_id,
                        status="failed",
                        data={**common, "duration_ms": duration, "error": _clip(event.get("output") or "tool returned an error")},
                    )
                else:
                    record(
                        EventType.TOOL_CALL_COMPLETED,
                        parent_id=parent_id,
                        execution_id=execution_id,
                        status="completed",
                        data={**common, "duration_ms": duration, "output": _clip(event.get("output") or "")},
                    )
                return
            logger.debug("provider tool event with unknown phase %r ignored", phase)
        except Exception:  # noqa: BLE001 - bookkeeping must not break the call
            logger.warning("failed to record a provider tool event", exc_info=True)

    return on_tool_event
