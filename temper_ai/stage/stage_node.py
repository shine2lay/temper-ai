"""StageNode — composite node that contains a sub-graph of nodes.

A stage node is a context boundary. It controls what information flows in
and out. Internal agent outputs are scoped within the stage — the parent
graph only sees declared outputs (if any).

Topology comes from one of:
- Explicit `nodes` list (custom graph layout)
- `strategy` name + `agents` list (generated topology)
- `ref` to a saved graph config (loaded — resolved before StageNode is created)
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from temper_ai.shared.types import ExecutionContext, NodeResult
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node


class StageNode(Node):
    """Composite node that runs a sub-graph of nodes. Recursive."""

    def __init__(self, config: NodeConfig, child_nodes: list[Node]):
        """Initialize with config and resolved child nodes.

        Args:
            config: The NodeConfig for this stage.
            child_nodes: List of resolved child Nodes (AgentNode or nested StageNode).
        """
        super().__init__(config)
        self.child_nodes = child_nodes

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """Execute the sub-graph.

        1. Apply input gate (if declared inputs, filter input_data)
        2. Execute sub-graph via the same graph executor (recursive)
        3. Apply output gate (if declared outputs, filter result)
        """
        # Update node path for nested context
        node_path = (
            f"{context.node_path}.{self.name}" if context.node_path else self.name
        )
        ctx = replace(context, node_path=node_path)

        # 1. Input gate
        gated_input = self._apply_input_gate(input_data)

        # 2. Execute sub-graph (same executor, recursive)
        start = time.monotonic()
        result = execute_graph(
            self.child_nodes,
            gated_input,
            ctx,
            graph_name=self.name,
            is_workflow=False,
        )
        result.duration_seconds = time.monotonic() - start

        # 3. Output gate
        if self.config.outputs:
            result = self._apply_output_gate(result)

        return result

    def _apply_input_gate(self, input_data: dict) -> dict:
        """If inputs declared, only pass through declared fields.

        Without declared inputs: everything flows in (default, no boundary).
        With declared inputs: only mapped fields enter the sub-graph.

        Inputs are declared in one of two shapes, because stages and workflows grew up apart:

            inputs: {goal: goal_text}                      a stage: local name <- source key
            inputs: {goal: {type: string, required: true}} a workflow: a schema for the same name

        The second shape is a declaration, not a source — the field arrives under its own name, and
        the parent's ``input_map`` has already put it there. Reading it as a source looked up a dict
        key and raised ``TypeError: unhashable type: 'dict'``, which is what a referenced workflow
        used to die of before any of its nodes ran.

        ``gate`` crosses regardless of what is declared. It is not something the parent mapped in; the
        executor puts it there when a human approves this node, and it carries what they said. A
        boundary that drops it turns an edited approval into a rubber stamp — the sub-graph runs, and
        the one thing the person actually contributed is the one thing it cannot see.
        """
        if not self.config.inputs:
            return dict(input_data)

        gated: dict[str, Any] = {}
        missing: list[str] = []
        for local_name, source in self.config.inputs.items():
            if isinstance(source, dict):
                gated[local_name] = input_data.get(local_name)
                if source.get("required") and gated[local_name] is None:
                    missing.append(local_name)
            elif "." in source:
                # Dot notation handled by parent's input resolution
                # By the time we get here, input_data already has resolved values
                gated[local_name] = input_data.get(local_name)
            else:
                gated[local_name] = input_data.get(source)
        if missing:
            # Say it here, where the name and the stage are both known. Downstream this is a blank
            # argument in some agent's prompt, and the run fails somewhere that cannot explain why.
            raise ValueError(
                f"Stage '{self.name}' is missing required input(s): {', '.join(sorted(missing))}. "
                f"Add them to this node's input_map."
            )
        if "gate" in input_data and "gate" not in gated:
            gated["gate"] = input_data["gate"]
        return gated

    def _apply_output_gate(self, result: NodeResult) -> NodeResult:
        """If outputs declared, only expose declared fields.

        Without declared outputs: full result passes through (default).
        With declared outputs: structured_output is filtered to only declared fields.
        """
        if not self.config.outputs:
            return result

        filtered = {}
        for output_name, source in self.config.outputs.items():
            filtered[output_name] = _resolve_output_field(result, source)

        # Replace structured_output with filtered fields
        result.structured_output = filtered
        return result


def _resolve_output_field(result: NodeResult, source: str) -> object:
    """Resolve an output field from a NodeResult.

    Source examples:
    - "output" → result.output
    - "structured.verdict" → result.structured_output["verdict"]
    - "status" → result.status
    """
    parts = source.split(".")

    if parts[0] == "output":
        return result.output
    elif parts[0] == "structured" and len(parts) >= 2:
        if result.structured_output is None:
            return None
        value: object = result.structured_output
        for key in parts[1:]:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    elif parts[0] == "status":
        return result.status
    elif parts[0] == "cost_usd":
        return result.cost_usd
    else:
        return None
