"""Metric aggregation for agent and stage executions.

Extracted from ExecutionTracker to separate metric collection/storage
concerns from core execution tracking.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.observability.backend import ObservabilityBackend

logger = logging.getLogger(__name__)


@dataclass
class AgentOutputParams:
    """Parameters for setting agent output data."""
    agent_id: str
    output_data: Dict[str, Any]
    reasoning: Optional[str] = None
    confidence_score: Optional[float] = None
    total_tokens: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    num_llm_calls: Optional[int] = None
    num_tool_calls: Optional[int] = None


class MetricAggregator:
    """Collects and stores metrics for agent and stage executions.

    Delegates to the observability backend for persistence while
    handling metric registry integration and error resilience.

    Args:
        backend: Observability backend for persistence.
        metric_registry: Optional MetricRegistry for automatic metric collection.
    """

    def __init__(
        self,
        backend: ObservabilityBackend,
        metric_registry: Optional[Any] = None,
    ):
        self.backend = backend
        self.metric_registry = metric_registry

    def collect_agent_metrics(self, agent_id: str) -> None:
        """Collect metrics for agent execution using registered collectors.

        Called automatically after successful agent execution if a
        MetricRegistry was provided.

        Args:
            agent_id: ID of the agent execution to collect metrics for.
        """
        if self.metric_registry is None:
            return

        try:
            execution = None
            if hasattr(self.backend, "get_agent_execution"):
                execution = self.backend.get_agent_execution(agent_id)

            if execution:
                metrics = self.metric_registry.collect_all(execution)
                if metrics:
                    logger.info(
                        f"Collected {len(metrics)} metrics for agent {agent_id}: "
                        f"{', '.join(f'{k}={v:.3f}' for k, v in metrics.items())}"
                    )
            else:
                logger.debug(
                    f"Agent execution {agent_id} not found for metric collection"
                )
        except Exception as e:
            logger.warning(
                f"Failed to collect metrics for agent {agent_id}: {e}",
                exc_info=True,
            )

    def set_agent_output(self, params: AgentOutputParams) -> None:
        """Set agent output data after execution.

        Args:
            params: AgentOutputParams with all agent output parameters
        """
        from src.observability.backend import AgentOutputData
        self.backend.set_agent_output(
            agent_id=params.agent_id,
            output_data=params.output_data,
            metrics=AgentOutputData(
                reasoning=params.reasoning,
                confidence_score=params.confidence_score,
                total_tokens=params.total_tokens,
                prompt_tokens=params.prompt_tokens,
                completion_tokens=params.completion_tokens,
                estimated_cost_usd=params.estimated_cost_usd,
                num_llm_calls=params.num_llm_calls,
                num_tool_calls=params.num_tool_calls,
            ),
        )

    def set_stage_output(
        self,
        stage_id: str,
        output_data: Dict[str, Any],
        output_lineage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set stage output data after execution.

        Args:
            stage_id: Stage execution ID
            output_data: Stage output data
            output_lineage: Optional lineage metadata (which agent produced what)
        """
        self.backend.set_stage_output(
            stage_id=stage_id,
            output_data=output_data,
            output_lineage=output_lineage,
        )
