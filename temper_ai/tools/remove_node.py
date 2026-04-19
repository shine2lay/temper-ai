"""RemoveNode — tier 2 imperative dispatch.

Lets an LLM agent mark a still-pending node in the running DAG for skip.
Downstream nodes that referenced the removed node's output cascade to
skipped (standard engine behavior for unresolved input_map refs).

Usage in agent config:
    tools: [RemoveNode]

Agent calls it during its run:
    RemoveNode(target="placeholder_research")

The tool buffers the op into ExecutionContext.dispatch_state.pending_ops
alongside any AddNode calls from the same run. After the agent completes,
the executor drains the buffer and applies ops atomically.

Only nodes that haven't started running yet can be removed. Removing an
already-completed or running node is a no-op (it's already past the point
of cancellation).
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class RemoveNode(BaseTool):
    """Queue a pending node for removal from the running workflow DAG."""

    name = "RemoveNode"
    description = (
        "Remove a still-pending node from the running workflow graph. Called "
        "during an agent's run when the agent determines a downstream node "
        "shouldn't execute (e.g., a placeholder that turned out unnecessary). "
        "The target is marked SKIPPED; any further-downstream nodes whose "
        "input_map refs it will cascade to skipped too. Only pending nodes "
        "can be removed — already-started nodes are unaffected."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "Name of the pending node to remove. Must exist in the "
                    "current DAG and not yet have started."
                ),
            },
        },
        "required": ["target"],
    }
    modifies_state = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._execution_context: Any = None

    def bind_context(self, context: Any) -> None:
        """Bind the ExecutionContext so we can queue ops into dispatch_state."""
        self._execution_context = context

    def execute(self, **params: Any) -> ToolResult:
        if self._execution_context is None:
            return ToolResult(
                success=False, result="",
                error="RemoveNode tool not bound to execution context",
            )
        ctx = self._execution_context

        target = params.get("target")
        if not isinstance(target, str) or not target.strip():
            return ToolResult(
                success=False, result="",
                error="RemoveNode requires a non-empty string `target` parameter",
            )

        from temper_ai.stage.dispatch import DispatchOp
        from temper_ai.stage.dispatch_limits import DispatchRunState

        if getattr(ctx, "dispatch_state", None) is None:
            ctx.dispatch_state = DispatchRunState()

        op = DispatchOp(op="remove", target=target)
        node_path = getattr(ctx, "node_path", "") or ctx.agent_name or ""
        ctx.dispatch_state.pending_ops.setdefault(node_path, []).append(op)

        logger.info("RemoveNode queued removal of %r under path %r", target, node_path)
        return ToolResult(
            success=True,
            result=(
                f"Queued removal of {target!r} — will be marked SKIPPED after "
                f"the current agent completes. Downstream nodes that reference "
                f"its output will cascade-skip."
            ),
        )
