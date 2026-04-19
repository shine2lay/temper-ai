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

    MAX_RETRIES = 2  # Retry up to 2 times on empty output

    def run(self, input_data: dict, context: ExecutionContext) -> NodeResult:
        """Run the agent and wrap its result in NodeResult.

        Retries up to MAX_RETRIES times if the agent returns empty output
        (common with rate-limited Claude Code CLI).
        """
        import logging
        logger = logging.getLogger(__name__)

        agent = create_agent(self.agent_config)

        # Update context for this agent execution
        node_path = (
            f"{context.node_path}.{self.name}" if context.node_path else self.name
        )
        ctx = replace(context, node_path=node_path, agent_name=agent.name)

        start = time.monotonic()
        last_result = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = agent.run(input_data, ctx)
                last_result = result

                # Check if output is empty — retry if so
                if not result.output or not result.output.strip():
                    if attempt < self.MAX_RETRIES:
                        logger.warning(
                            "Agent '%s' returned empty output (attempt %d/%d), retrying...",
                            agent.name, attempt, self.MAX_RETRIES,
                        )
                        time.sleep(2 * attempt)  # Brief backoff
                        continue
                    else:
                        logger.warning(
                            "Agent '%s' returned empty output after %d attempts",
                            agent.name, self.MAX_RETRIES,
                        )

                # Got output — return it
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
                if attempt < self.MAX_RETRIES:
                    logger.warning(
                        "Agent '%s' raised exception (attempt %d/%d): %s",
                        agent.name, attempt, self.MAX_RETRIES, exc,
                    )
                    time.sleep(2 * attempt)
                    continue

                duration = time.monotonic() - start
                return NodeResult(
                    status=Status.FAILED,
                    error=str(exc),
                    duration_seconds=duration,
                )

        # Shouldn't reach here, but handle it
        duration = time.monotonic() - start
        if last_result:
            return NodeResult(
                status=last_result.status,
                output=last_result.output,
                structured_output=last_result.structured_output,
                agent_results=[last_result],
                cost_usd=last_result.cost_usd,
                total_tokens=last_result.tokens.total_tokens,
                duration_seconds=duration,
                error=last_result.error,
            )
        return NodeResult(
            status=Status.FAILED,
            error="Agent returned no result after retries",
            duration_seconds=duration,
        )
