"""Observability helpers for parallel stage execution.

Extracted from _parallel_helpers.py to reduce module size. Contains
event emission, lineage tracking, quality gate tracking, and cost
summary functions.
"""
import logging
from typing import Any, Dict

from src.stage.executors.state_keys import StateKeys

logger = logging.getLogger(__name__)


def _emit_synthesis_event(
    state: Dict[str, Any],
    stage_name: str,
    synthesis_result: Any,
    agent_outputs_dict: Dict[str, Any],
    parallel_result: Dict[str, Any],
    aggregate_metrics: Dict[str, Any],
) -> None:
    """Emit synthesis collaboration event via tracker (if available)."""
    tracker = state.get(StateKeys.TRACKER)
    if not (tracker and hasattr(tracker, 'track_collaboration_event')):
        return
    tracker_metadata = _build_synthesis_metadata(
        synthesis_result, parallel_result, aggregate_metrics
    )
    from src.observability._tracker_helpers import CollaborationEventData
    tracker.track_collaboration_event(CollaborationEventData(
        event_type="synthesis",
        stage_name=stage_name,
        agents=list(agent_outputs_dict.keys()),
        decision=synthesis_result.decision,
        confidence=synthesis_result.confidence,
        metadata=tracker_metadata
    ))


def _build_synthesis_metadata(
    synthesis_result: Any,
    parallel_result: Dict[str, Any],
    aggregate_metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """Build tracker metadata for synthesis event."""
    return {
        StateKeys.METHOD: synthesis_result.method,
        StateKeys.CONFIDENCE: synthesis_result.confidence,
        StateKeys.VOTES: synthesis_result.votes,
        "num_conflicts": len(synthesis_result.conflicts),
        StateKeys.REASONING: synthesis_result.reasoning,
        StateKeys.AGENT_STATUSES: parallel_result.get(StateKeys.AGENT_STATUSES, {}),
        StateKeys.AGGREGATE_METRICS: aggregate_metrics
    }


def _emit_output_lineage(
    state: Dict[str, Any],
    stage_name: str,
    agent_outputs_dict: Dict[str, Any],
    parallel_result: Dict[str, Any],
    synthesis_result: Any,
) -> None:
    """Compute output lineage and store via tracker (best-effort)."""
    try:
        from src.observability.lineage import compute_output_lineage, lineage_to_dict

        agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
        synthesis_method = getattr(synthesis_result, "method", None)
        lineage = compute_output_lineage(
            stage_name, agent_outputs_dict, agent_statuses, synthesis_method,
        )
        lineage_dict = lineage_to_dict(lineage)

        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")
        if tracker and hasattr(tracker, "set_stage_output"):
            tracker.set_stage_output(
                stage_id=stage_id,
                output_data={},
                output_lineage=lineage_dict,
            )
    except Exception:
        logger.debug(
            "Failed to compute output lineage for stage %s",
            stage_name,
            exc_info=True,
        )


def _emit_parallel_cost_summary(
    state: Dict[str, Any],
    stage_name: str,
    parallel_result: Dict[str, Any],
) -> None:
    """Emit cost rollup for parallel stage execution."""
    try:
        from src.observability.cost_rollup import (
            compute_stage_cost_summary,
            emit_cost_summary,
        )

        agent_metrics = parallel_result.get(StateKeys.AGENT_METRICS, {})
        agent_statuses = parallel_result.get(StateKeys.AGENT_STATUSES, {})
        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")

        summary = compute_stage_cost_summary(
            stage_name, agent_metrics, agent_statuses,
        )
        emit_cost_summary(tracker, stage_id, summary)
    except Exception:
        logger.debug(
            "Failed to emit cost summary for stage %s",
            stage_name,
            exc_info=True,
        )


def _track_quality_gate_event(
    tracker: Any,
    event_type: str,
    stage_name: str,
    synthesis_result: Any,
    violations: list,
    quality_gates_config: Dict[str, Any],
    retry_count: int
) -> None:
    """Track quality gate event in observability system."""
    if tracker and hasattr(tracker, 'track_collaboration_event'):
        metadata = {
            "violations": violations,
            "synthesis_method": synthesis_result.method,
            "retry_count": retry_count,
            "max_retries": quality_gates_config.get("max_retries", 2)
        }
        if event_type == "quality_gate_failure":
            metadata["on_failure_action"] = quality_gates_config.get("on_failure", "retry_stage")
        elif event_type == "quality_gate_retry":
            metadata["retry_attempt"] = retry_count + 1

        from src.observability._tracker_helpers import CollaborationEventData
        tracker.track_collaboration_event(CollaborationEventData(
            event_type=event_type,
            stage_name=stage_name,
            agents=[],
            decision=None,
            confidence=getattr(synthesis_result, "confidence", 0.0),
            metadata=metadata
        ))


def _emit_quality_gate_violation_details(
    state: Dict[str, Any],
    stage_name: str,
    violations: list,
    synthesis_result: Any,
    quality_gates_config: Dict[str, Any],
) -> None:
    """Emit per-gate violation details as a collaboration event."""
    try:
        from src.observability.dialogue_metrics import (
            build_quality_gate_details,
            emit_quality_gate_details,
        )

        tracker = state.get(StateKeys.TRACKER)
        stage_id = state.get(StateKeys.CURRENT_STAGE_ID, "")
        details = build_quality_gate_details(
            violations, synthesis_result, quality_gates_config,
        )
        emit_quality_gate_details(tracker, stage_id, stage_name, details)
    except Exception:
        logger.debug(
            "Failed to emit quality gate violation details for %s",
            stage_name,
            exc_info=True,
        )
