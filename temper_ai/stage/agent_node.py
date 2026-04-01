"""AgentNode — leaf node that runs a single agent.

Agent config comes from ref (loaded from config store) or inline config.
Node-level overrides (task_template, model, etc.) merge on top of agent config.
Memory is scoped to agent identity — same agent in multiple nodes shares memory.
"""

from __future__ import annotations

import time
from dataclasses import replace

from temper_ai.agent import create_agent
from temper_ai.shared.types import ExecutionContext, NodeResult, Status
from temper_ai.stage.models import NodeConfig
from temper_ai.stage.node import Node


class AgentNode(Node):
    """Leaf node that wraps an agent as a graph node."""

    def __init__(self, config: NodeConfig, resolved_agent_config: dict):
        """Initialize with node config and the fully resolved agent config.

        Args:
            config: The NodeConfig for this node.
            resolved_agent_config: Agent config with node-level overrides merged.
                Created by the loader: base agent config + node overrides.
        """
        super().__init__(config)
        self.agent_config = resolved_agent_config

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """Run the agent and wrap its result in NodeResult.

        1. Create agent from resolved config
        2. Update context with current node path and agent name
        3. Record NODE_START event (via executor, not here — keep node simple)
        4. Call agent.run()
        5. Wrap AgentResult in NodeResult
        """
        agent = create_agent(self.agent_config)

        # Update context for this agent execution
        node_path = (
            f"{context.node_path}.{self.name}" if context.node_path else self.name
        )
        ctx = replace(context, node_path=node_path, agent_name=agent.name)

        start = time.monotonic()
        try:
            result = agent.run(input_data, ctx)
            duration = time.monotonic() - start

            return NodeResult(
                status=result.status,
                output=result.output,
                structured_output=result.structured_output,
                agent_results=[result],
                cost_usd=result.cost_usd,
                total_tokens=result.tokens.total_tokens,
                duration_seconds=duration,
                error=result.error,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            return NodeResult(
                status=Status.FAILED,
                error=str(exc),
                duration_seconds=duration,
            )
