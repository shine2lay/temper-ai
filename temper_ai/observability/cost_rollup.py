"""Cost rollup computation for stage-level cost aggregation.

Provides a stateless function that takes accumulated agent_metrics from
sequential or parallel executors and computes per-agent + total cost
summaries. Results are emitted via structured logging and tracker events.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Event type constant
EVENT_TYPE_COST_SUMMARY = "cost_summary"


@dataclass
class AgentCostEntry:
    """Cost breakdown for a single agent."""

    agent_name: str
    cost_usd: float = 0.0
    tokens: int = 0
    duration_seconds: float = 0.0
    status: str = "unknown"


@dataclass
class StageCostSummary:
    """Aggregated cost summary for a stage execution."""

    stage_name: str
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0
    agent_count: int = 0
    agents: List[AgentCostEntry] = field(default_factory=list)
    cost_attribution_tags: Optional[Dict[str, str]] = None


def compute_stage_cost_summary(
    stage_name: str,
    agent_metrics: Dict[str, Any],
    agent_statuses: Optional[Dict[str, Any]] = None,
) -> StageCostSummary:
    """Compute per-agent + total cost summary from agent metrics.

    This function is stateless — it takes the agent_metrics dict already
    accumulated by sequential and parallel executors and computes a summary.

    Args:
        stage_name: Name of the stage
        agent_metrics: Dict of {agent_name: {tokens, cost_usd, duration_seconds, ...}}
        agent_statuses: Optional dict of {agent_name: status_str_or_dict}

    Returns:
        StageCostSummary with per-agent breakdown and totals
    """
    summary = StageCostSummary(stage_name=stage_name)
    statuses = agent_statuses or {}

    for agent_name, metrics in agent_metrics.items():
        entry = _build_agent_entry(agent_name, metrics, statuses)
        summary.agents.append(entry)
        summary.total_cost_usd += entry.cost_usd
        summary.total_tokens += entry.tokens
        summary.total_duration_seconds = max(
            summary.total_duration_seconds, entry.duration_seconds,
        )

    summary.agent_count = len(summary.agents)
    return summary


def _build_agent_entry(
    agent_name: str,
    metrics: Dict[str, Any],
    statuses: Dict[str, Any],
) -> AgentCostEntry:
    """Build a single agent cost entry from metrics dict."""
    status = statuses.get(agent_name, "unknown")
    if isinstance(status, dict):
        status = status.get("status", "unknown")

    return AgentCostEntry(
        agent_name=agent_name,
        cost_usd=metrics.get("cost_usd", 0.0),
        tokens=metrics.get("tokens", 0),
        duration_seconds=metrics.get("duration_seconds", 0.0),
        status=str(status),
    )


def emit_cost_summary(
    tracker: Any,
    stage_id: str,
    summary: StageCostSummary,
) -> None:
    """Emit cost summary via tracker and structured log.

    Args:
        tracker: ExecutionTracker with track_collaboration_event
        stage_id: Current stage ID for event correlation
        summary: Computed cost summary
    """
    event_dict = asdict(summary)

    logger.info(
        "Cost summary: stage=%s total=$%.4f tokens=%d agents=%d",
        summary.stage_name,
        summary.total_cost_usd,
        summary.total_tokens,
        summary.agent_count,
        extra={"cost_summary": EVENT_TYPE_COST_SUMMARY, **event_dict},
    )

    _emit_via_tracker(tracker, stage_id, EVENT_TYPE_COST_SUMMARY, event_dict)


def _emit_via_tracker(
    tracker: Any,
    stage_id: str,
    event_type: str,
    event_dict: Dict[str, Any],
) -> None:
    """Route a cost event through the tracker's collaboration event API.

    Args:
        tracker: ExecutionTracker (or None)
        stage_id: Stage identifier
        event_type: Event type string
        event_dict: Serialized event data dictionary
    """
    if tracker is None:
        return
    if not hasattr(tracker, "track_collaboration_event"):
        return

    try:
        from temper_ai.observability._tracker_helpers import CollaborationEventData

        tracker.track_collaboration_event(
            CollaborationEventData(
                event_type=event_type,
                stage_id=stage_id,
                event_data=event_dict,
            )
        )
    except Exception:  # noqa: BLE001 — best-effort observability
        logger.debug(
            "Failed to emit %s event via tracker", event_type, exc_info=True,
        )
