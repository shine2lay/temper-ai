"""AddNode — tier 2 imperative dispatch.

Lets an LLM agent add a new node to the running workflow DAG by calling
a typed tool, as opposed to the tier 1 declarative `dispatch:` block in
the agent YAML. Useful when the decision to dispatch is conditional in a
way that a Jinja-over-output template can't express.

Usage in agent config:
    tools: [AddNode]

Agent calls it during its run:
    AddNode(
        name="investigate_spike",
        agent="log_investigator",
        depends_on=["parent_agent"],
        input_map={"log_window": "parent_agent.structured.window"}
    )

The tool buffers the op into ExecutionContext.dispatch_state.pending_ops,
keyed by the agent's node_path. After the agent completes, the executor
drains the buffer, merges with any declarative dispatch ops, and applies
them atomically — same cap enforcement, same validation as tier 1.

Out of scope for v1:
    - Subgraph-in-one-call (agents compose subgraphs via multiple AddNode
      calls with depends_on wiring)
    - `replace_node` — compose via RemoveNode + AddNode
"""

from __future__ import annotations

import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class AddNode(BaseTool):
    """Queue a new node to be inserted into the running workflow DAG."""

    name = "AddNode"
    description = (
        "Add a new node to the running workflow graph. Called during an agent's "
        "run to dispatch follow-up work conditionally (use when the decision "
        "can't be expressed as a declarative Jinja template over your output). "
        "The new node is queued and inserted into the DAG atomically after your "
        "agent completes, alongside any `dispatch:` block from your config. "
        "Safety caps (max_children_per_dispatch, max_dispatch_depth, etc.) "
        "apply to the merged batch."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Unique name for the new node. Must not collide with any "
                    "existing node in the current DAG."
                ),
            },
            "type": {
                "type": "string",
                "enum": ["agent", "stage"],
                "description": (
                    "Node type. Defaults to 'agent' when `agent` is set, "
                    "'stage' when `agents` is set."
                ),
            },
            "agent": {
                "type": "string",
                "description": (
                    "Name of the agent config to run (for type=agent). "
                    "Must match a registered agent."
                ),
            },
            "agents": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of agent names to run inside a stage (for type=stage)."
                ),
            },
            "strategy": {
                "type": "string",
                "enum": ["parallel", "sequential"],
                "description": "For type=stage — how to run the agents.",
            },
            "depends_on": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Names of nodes this new node depends on. Can reference "
                    "any pending or already-completed node in the DAG."
                ),
            },
            "input_map": {
                "type": "object",
                "description": (
                    "Map of local input name → source ref (e.g. "
                    "'upstream_node.output' or 'upstream_node.structured.field'). "
                    "Same format as static workflow input_map."
                ),
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["name"],
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
                error="AddNode tool not bound to execution context",
            )
        ctx = self._execution_context

        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            return ToolResult(
                success=False, result="",
                error="AddNode requires a non-empty string `name` parameter",
            )

        # Build the node dict — only include keys the agent actually supplied
        # so NodeConfig.from_dict doesn't get noise.
        node_dict: dict[str, Any] = {"name": name}
        for key in ("type", "agent", "agents", "strategy", "depends_on", "input_map"):
            if key in params and params[key] is not None:
                node_dict[key] = params[key]

        # Infer type if omitted (mirrors tier 1 behavior)
        if "type" not in node_dict:
            if "agent" in node_dict:
                node_dict["type"] = "agent"
            elif "agents" in node_dict:
                node_dict["type"] = "stage"
            else:
                return ToolResult(
                    success=False, result="",
                    error=f"AddNode({name!r}) has neither `agent` nor `agents`; "
                          f"one is required to determine what the node runs",
                )

        # Import here to avoid a circular dep (dispatch imports from templates
        # etc.; keeping tool-side imports lazy).
        from temper_ai.stage.dispatch import DispatchOp
        from temper_ai.stage.dispatch_limits import DispatchRunState

        # Lazily seed dispatch_state so tier-2-only workflows still work
        if getattr(ctx, "dispatch_state", None) is None:
            ctx.dispatch_state = DispatchRunState()

        op = DispatchOp(op="add", node=node_dict)
        node_path = getattr(ctx, "node_path", "") or ctx.agent_name or ""
        ctx.dispatch_state.pending_ops.setdefault(node_path, []).append(op)

        logger.info(
            "AddNode queued op for %r under path %r (agent=%s)",
            name, node_path, node_dict.get("agent") or node_dict.get("agents"),
        )
        return ToolResult(
            success=True,
            result=(
                f"Queued add-node {name!r} — will be inserted into the DAG "
                f"after the current agent completes. Safety caps apply."
            ),
        )
