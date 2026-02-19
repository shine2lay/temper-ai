"""Dialogue metrics computation for multi-agent interactions.

Computes per-round confidence trajectories, convergence speed, and
stance change detection. Enriches dialogue tracking events with derived
analytics without storing additional per-round state.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Event type constants
EVENT_TYPE_DIALOGUE_METRICS = "dialogue_round_metrics"
EVENT_TYPE_QUALITY_GATE_DETAIL = "quality_gate_violation_detail"


@dataclass
class RoundMetrics:
    """Computed metrics for a single dialogue round."""

    round_number: int
    confidence_trajectory: List[float] = field(default_factory=list)
    avg_confidence: float = 0.0
    convergence_speed: Optional[float] = None
    stance_changes: int = 0
    agent_count: int = 0


@dataclass
class QualityGateViolationDetail:
    """Per-gate breakdown of quality gate violations."""

    gate_name: str
    expected: Any = None
    actual: Any = None
    deficit: Optional[float] = None


def compute_round_metrics(
    current_outputs: list,
    dialogue_history: List[Dict[str, Any]],
    round_number: int,
    convergence_score: Optional[float] = None,
    previous_convergence: Optional[float] = None,
) -> RoundMetrics:
    """Compute derived metrics for a dialogue round.

    Analyzes confidence trajectory from dialogue history, computes
    convergence speed (delta between rounds), and detects stance changes.

    Args:
        current_outputs: AgentOutput list for current round
        dialogue_history: Full dialogue history (all prior rounds)
        round_number: Current round number (0-based)
        convergence_score: Current round convergence score
        previous_convergence: Previous round convergence score

    Returns:
        RoundMetrics with computed values
    """
    metrics = RoundMetrics(
        round_number=round_number,
        agent_count=len(current_outputs),
    )

    metrics.confidence_trajectory = _build_confidence_trajectory(
        dialogue_history, round_number,
    )
    metrics.avg_confidence = _compute_avg_confidence(current_outputs)
    metrics.convergence_speed = _compute_convergence_speed(
        convergence_score, previous_convergence,
    )
    metrics.stance_changes = _count_stance_changes(
        dialogue_history, current_outputs, round_number,
    )

    return metrics


def _build_confidence_trajectory(
    dialogue_history: List[Dict[str, Any]],
    current_round: int,
) -> List[float]:
    """Build per-round average confidence from dialogue history.

    Returns a list of average confidence values, one per completed round
    up to and including current_round.
    """
    trajectory: List[float] = []
    for rnd in range(current_round + 1):
        entries = [
            e for e in dialogue_history
            if e.get("round") == rnd and e.get("confidence") is not None
        ]
        if entries:
            avg = sum(e["confidence"] for e in entries) / len(entries)
            trajectory.append(round(avg, 4))  # scanner: skip-magic
    return trajectory


def _compute_avg_confidence(current_outputs: list) -> float:
    """Compute average confidence from current round outputs."""
    if not current_outputs:
        return 0.0
    confidences = [
        getattr(o, "confidence", 0.0) or 0.0 for o in current_outputs
    ]
    return sum(confidences) / len(confidences)


def _compute_convergence_speed(
    current: Optional[float],
    previous: Optional[float],
) -> Optional[float]:
    """Compute convergence speed as delta between rounds.

    Positive = converging, negative = diverging, None = insufficient data.
    """
    if current is None or previous is None:
        return None
    return round(current - previous, 4)  # scanner: skip-magic


def _count_stance_changes(
    dialogue_history: List[Dict[str, Any]],
    current_outputs: list,
    round_number: int,
) -> int:
    """Count agents that changed stance from previous round."""
    if round_number == 0:
        return 0

    prev_round = round_number - 1
    prev_stances: Dict[str, str] = {}
    for entry in dialogue_history:
        if entry.get("round") == prev_round and entry.get("stance"):
            prev_stances[entry["agent"]] = entry["stance"]

    if not prev_stances:
        return 0

    changes = 0
    for output in current_outputs:
        name = getattr(output, "agent_name", "")
        stance = getattr(output, "metadata", {}).get("stance", "")
        if name in prev_stances and stance and stance != prev_stances[name]:
            changes += 1
    return changes


def emit_round_metrics(
    tracker: Any,
    stage_id: str,
    metrics: RoundMetrics,
) -> None:
    """Emit dialogue round metrics via tracker and structured log.

    Args:
        tracker: ExecutionTracker with track_collaboration_event
        stage_id: Current stage ID for event correlation
        metrics: Computed round metrics
    """
    event_dict = asdict(metrics)

    logger.info(
        "Dialogue round metrics: round=%d agents=%d avg_conf=%.3f speed=%s",
        metrics.round_number,
        metrics.agent_count,
        metrics.avg_confidence,
        metrics.convergence_speed,
        extra={"dialogue_metrics": EVENT_TYPE_DIALOGUE_METRICS, **event_dict},
    )

    _emit_via_tracker(tracker, stage_id, EVENT_TYPE_DIALOGUE_METRICS, event_dict)


def build_quality_gate_details(
    violations: List[str],
    synthesis_result: Any,
    quality_gates_config: Dict[str, Any],
) -> List[QualityGateViolationDetail]:
    """Build per-gate violation details from violations list.

    Parses violation messages to extract structured gate-level information
    (gate name, expected value, actual value, deficit).

    Args:
        violations: List of violation message strings
        synthesis_result: SynthesisResult from synthesis
        quality_gates_config: Quality gates configuration dict

    Returns:
        List of QualityGateViolationDetail
    """
    details: List[QualityGateViolationDetail] = []

    for violation in violations:
        detail = _parse_violation(violation, synthesis_result, quality_gates_config)
        details.append(detail)

    return details


def _parse_violation(
    violation: str,
    synthesis_result: Any,
    config: Dict[str, Any],
) -> QualityGateViolationDetail:
    """Parse a single violation message into structured detail."""
    violation_lower = violation.lower()

    if "confidence" in violation_lower:
        actual = getattr(synthesis_result, "confidence", None)
        expected = config.get("min_confidence")
        deficit = None
        if actual is not None and expected is not None:
            deficit = round(expected - actual, 4)  # scanner: skip-magic
        return QualityGateViolationDetail(
            gate_name="min_confidence",
            expected=expected,
            actual=actual,
            deficit=deficit,
        )

    if "findings" in violation_lower:
        return QualityGateViolationDetail(
            gate_name="min_findings",
            expected=config.get("min_findings"),
        )

    if "citation" in violation_lower:
        return QualityGateViolationDetail(
            gate_name="require_citations",
            expected=True,
            actual=False,
        )

    return QualityGateViolationDetail(gate_name="unknown", actual=violation)


def emit_quality_gate_details(
    tracker: Any,
    stage_id: str,
    stage_name: str,
    details: List[QualityGateViolationDetail],
) -> None:
    """Emit quality gate violation details via tracker.

    Args:
        tracker: ExecutionTracker
        stage_id: Current stage ID
        stage_name: Stage name for logging
        details: List of per-gate violation details
    """
    details_dicts = [asdict(d) for d in details]

    logger.info(
        "Quality gate violation details: stage=%s gates=%d",
        stage_name,
        len(details),
        extra={
            "quality_gate_details": EVENT_TYPE_QUALITY_GATE_DETAIL,
            "stage_name": stage_name,
            "violations": details_dicts,
        },
    )

    event_dict: Dict[str, Any] = {
        "stage_name": stage_name,
        "violation_count": len(details),
        "violations": details_dicts,
    }
    _emit_via_tracker(
        tracker, stage_id, EVENT_TYPE_QUALITY_GATE_DETAIL, event_dict,
    )


def _emit_via_tracker(
    tracker: Any,
    stage_id: str,
    event_type: str,
    event_dict: Dict[str, Any],
) -> None:
    """Route a dialogue/quality event through the tracker.

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
