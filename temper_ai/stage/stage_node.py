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
        """
        if not self.config.inputs:
            return dict(input_data)

        gated = {}
        for local_name, source in self.config.inputs.items():
            # Source can be a direct key or dot-notation
            if "." in source:
                # Dot notation handled by parent's input resolution
                # By the time we get here, input_data already has resolved values
                gated[local_name] = input_data.get(local_name)
            else:
                gated[local_name] = input_data.get(source)
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
