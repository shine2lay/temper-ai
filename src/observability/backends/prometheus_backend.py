"""
Prometheus backend stub for observability system.

STUB IMPLEMENTATION - Prepared for M6 multi-backend support.
Currently logs metrics but doesn't push to Prometheus.

Future M6 work:
- Implement Prometheus push gateway integration
- Convert execution events to Prometheus metrics
- Add counters, gauges, histograms for workflow/stage/agent metrics
- Support labels for workflow_name, stage_name, agent_name, status
"""
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging

from src.observability.backend import ObservabilityBackend

logger = logging.getLogger(__name__)


class PrometheusObservabilityBackend(ObservabilityBackend):
    """
    Prometheus metrics backend (STUB).

    Future implementation will:
    - Push metrics to Prometheus push gateway
    - Track workflow execution counts by name and status
    - Track stage/agent execution durations (histograms)
    - Track LLM token consumption and costs
    - Track tool call rates and errors
    - Support custom labels for filtering

    Example metrics (future):
        workflow_executions_total{workflow_name="research", status="completed"} 42
        workflow_duration_seconds{workflow_name="research"} histogram
        agent_llm_tokens_total{agent_name="researcher"} 15000
        agent_tool_calls_total{tool_name="web_scraper"} 120
    """

    def __init__(self, push_gateway_url: Optional[str] = None) -> None:
        """
        Initialize Prometheus backend.

        Args:
            push_gateway_url: Prometheus push gateway URL (e.g., "http://localhost:9091")
        """
        self.push_gateway_url = push_gateway_url
        logger.info(
            f"PrometheusObservabilityBackend initialized (STUB) - "
            f"push_gateway={push_gateway_url or 'not configured'}"
        )

    # Stub implementations - log only

    def track_workflow_start(self, workflow_id: str, workflow_name: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Workflow start: {workflow_name} ({workflow_id})")

    def track_workflow_end(self, workflow_id: str, end_time: datetime, status: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Workflow end: {workflow_id} status={status}")

    def update_workflow_metrics(self, workflow_id: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Workflow metrics: {workflow_id}")

    def track_stage_start(self, stage_id: str, stage_name: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Stage start: {stage_name} ({stage_id})")

    def track_stage_end(self, stage_id: str, end_time: datetime, status: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Stage end: {stage_id} status={status}")

    def set_stage_output(self, stage_id: str, output_data: Dict[str, Any]) -> None:
        logger.debug(f"[Prometheus STUB] Stage output: {stage_id}")

    def track_agent_start(self, agent_id: str, agent_name: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Agent start: {agent_name} ({agent_id})")

    def track_agent_end(self, agent_id: str, end_time: datetime, status: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Agent end: {agent_id} status={status}")

    def set_agent_output(self, agent_id: str, **kwargs: Any) -> None:  # type: ignore[override]
        logger.debug(f"[Prometheus STUB] Agent output: {agent_id}")

    def track_llm_call(  # type: ignore[override]
        self,
        llm_call_id: str,
        agent_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        **kwargs: Any
    ) -> None:
        logger.debug(
            f"[Prometheus STUB] LLM call: {provider}/{model} "
            f"tokens={prompt_tokens + completion_tokens}"
        )

    def track_tool_call(  # type: ignore[override]
        self,
        tool_execution_id: str,
        agent_id: str,
        tool_name: str,
        duration_seconds: float,
        status: str = "success",
        **kwargs: Any
    ) -> None:
        logger.debug(
            f"[Prometheus STUB] Tool call: {tool_name} "
            f"duration={duration_seconds}s status={status}"
        )

    def track_safety_violation(  # type: ignore[override]
        self,
        violation_severity: str,
        policy_name: str,
        **kwargs: Any
    ) -> None:
        logger.warning(
            f"[Prometheus STUB] Safety violation: {policy_name} "
            f"severity={violation_severity}"
        )

    @contextmanager
    def get_session_context(self) -> Any:
        """No-op context manager for Prometheus (stateless)."""
        yield None

    def cleanup_old_records(self, retention_days: int, dry_run: bool = False) -> Dict[str, int]:
        """No cleanup needed for Prometheus (retention handled by Prometheus config)."""
        logger.debug(f"[Prometheus STUB] Cleanup requested (retention={retention_days} days)")
        return {}

    def get_stats(self) -> Dict[str, Any]:
        """Get Prometheus backend stats."""
        return {
            "backend_type": "prometheus",
            "status": "stub",
            "push_gateway_url": self.push_gateway_url,
            "note": "M6 implementation pending"
        }
