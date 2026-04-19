"""QueryRunState — lets an agent introspect the live workflow state.

Returns a list of nodes that have completed or are currently running in this
run, with their status, output, and structured output. Intended for agents
that need to decide what work to do based on what's already been produced —
e.g. a dispatcher agent that wants to see upstream research before emitting
a dispatch directive, or any agent that needs to consult prior-node output
that wasn't explicitly wired into its input_map.

Usage in agent config:
    tools: [QueryRunState]

The agent calls it like:
    QueryRunState()
    QueryRunState(node_names=["day_allocator"])
    QueryRunState(include_outputs=False, include_structured=True)

Returns JSON:
    [
      {"node_name": "day_allocator", "status": "completed",
       "output": "...", "structured_output": {...}},
      {"node_name": "tokyo_research", "status": "running"},
      ...
    ]
"""

from __future__ import annotations

import json
import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_TRUNCATE_CHARS = 2000


class QueryRunState(BaseTool):
    """Return the live state of the current workflow run (completed + running nodes)."""

    name = "QueryRunState"
    description = (
        "Return the state of nodes in the current workflow run. Returns a JSON "
        "list of nodes with their status ('running', 'completed', 'failed') and, "
        "for completed nodes, their output and structured_output. Use this to "
        "discover what upstream nodes have produced before making decisions — "
        "e.g. before dispatching new work based on earlier agents' results. "
        "Outputs are truncated by default; pass truncate_chars=0 to disable."
    )
    parameters = {
        "type": "object",
        "properties": {
            "node_names": {
                "type": "array",
                "description": "Optional list of node names to return. Omit to return all.",
                "items": {"type": "string"},
            },
            "include_outputs": {
                "type": "boolean",
                "description": "Include truncated plain-text output. Default: true.",
                "default": True,
            },
            "include_structured": {
                "type": "boolean",
                "description": "Include parsed structured_output dicts. Default: true.",
                "default": True,
            },
            "truncate_chars": {
                "type": "integer",
                "description": (
                    "Maximum characters per node's output field before truncation. "
                    f"Default: {_DEFAULT_TRUNCATE_CHARS}. Pass 0 to disable."
                ),
                "default": _DEFAULT_TRUNCATE_CHARS,
            },
        },
    }
    modifies_state = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._execution_context = None

    def bind_context(self, context: Any) -> None:
        """Bind the ExecutionContext. Called by the agent before tool execution."""
        self._execution_context = context

    def execute(self, **params: Any) -> ToolResult:
        if self._execution_context is None:
            return ToolResult(
                success=False,
                result="",
                error="QueryRunState not bound to execution context",
            )
        ctx = self._execution_context
        run_state = getattr(ctx, "run_state", None)
        if run_state is None:
            # Not yet populated — executor hasn't seeded it. Surface empty, not error.
            return ToolResult(success=True, result=json.dumps([]))

        name_filter: set[str] | None = None
        raw_names = params.get("node_names")
        if isinstance(raw_names, list) and raw_names:
            name_filter = {str(n) for n in raw_names}

        include_outputs = bool(params.get("include_outputs", True))
        include_structured = bool(params.get("include_structured", True))
        try:
            truncate = int(params.get("truncate_chars", _DEFAULT_TRUNCATE_CHARS))
        except (TypeError, ValueError):
            truncate = _DEFAULT_TRUNCATE_CHARS

        nodes = []
        for node_name, node_result in run_state.items():
            if name_filter is not None and node_name not in name_filter:
                continue
            entry: dict[str, Any] = {
                "node_name": node_name,
                "status": _status_str(getattr(node_result, "status", None)),
            }
            if include_outputs:
                output = getattr(node_result, "output", "") or ""
                if truncate > 0 and len(output) > truncate:
                    entry["output"] = output[:truncate]
                    entry["output_truncated"] = True
                    entry["output_full_length"] = len(output)
                else:
                    entry["output"] = output
            if include_structured:
                structured = getattr(node_result, "structured_output", None)
                if structured is not None:
                    entry["structured_output"] = structured
            err = getattr(node_result, "error", None)
            if err:
                entry["error"] = err
            nodes.append(entry)

        return ToolResult(success=True, result=json.dumps(nodes))


def _status_str(status: Any) -> str:
    """Coerce a Status enum or string into a plain lowercase string for JSON."""
    if status is None:
        return "unknown"
    # Handle both enum and string inputs
    value = getattr(status, "value", status)
    return str(value).lower()
