"""Performance analyzer — detects slow and degrading stages."""

import logging
from datetime import timedelta

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from temper_ai.goals._schemas import (
    EffortLevel,
    GoalEvidence,
    GoalProposal,
    GoalRiskLevel,
    GoalType,
    ImpactEstimate,
    RiskAssessment,
)
from temper_ai.goals.analyzers.base import BaseAnalyzer
from temper_ai.goals.constants import (
    DEFAULT_LOOKBACK_HOURS,
    DEGRADATION_THRESHOLD_PCT,
    SLOW_STAGE_THRESHOLD_S,
)

logger = logging.getLogger(__name__)

HALF_FACTOR = 0.5
PCT_MULTIPLIER = 100
MIN_DURATIONS_FOR_TREND = 4
EVIDENCE_WORKFLOW_LIMIT = 5
SLOW_CONFIDENCE = 0.6
DEGRADATION_CONFIDENCE = 0.7


class PerformanceAnalyzer(BaseAnalyzer):
    """Identifies slow stages and performance degradation trends."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine

    @property
    def analyzer_type(self) -> str:
        """Return analyzer identifier."""
        return "performance"

    def analyze(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> list[GoalProposal]:
        """Analyze stage execution history for slow/degrading stages."""
        if self._engine is None:
            return []

        stages = self._query_stages(lookback_hours)
        if not stages:
            return []

        by_name = _group_by_name(stages)
        proposals: list[GoalProposal] = []

        for stage_name, executions in by_name.items():
            durations = [e.duration_seconds for e in executions if e.duration_seconds]
            if not durations:
                continue
            avg = sum(durations) / len(durations)
            proposals.extend(_check_slow(stage_name, avg, durations, executions))
            proposals.extend(_check_degradation(stage_name, durations))

        return proposals

    def _query_stages(self, lookback_hours: int) -> list:
        """Query completed stages within lookback window."""
        from temper_ai.storage.database.datetime_utils import utcnow
        from temper_ai.storage.database.models import StageExecution

        cutoff = utcnow() - timedelta(hours=lookback_hours)
        with Session(self._engine) as session:
            return list(
                session.exec(
                    select(StageExecution).where(
                        StageExecution.start_time >= cutoff,
                        StageExecution.status == "completed",
                        StageExecution.duration_seconds.is_not(None),  # type: ignore[union-attr]
                    )
                ).all()
            )


def _group_by_name(stages: list) -> dict[str, list]:
    """Group stage executions by stage name."""
    by_name: dict[str, list] = {}
    for s in stages:
        by_name.setdefault(s.stage_name, []).append(s)
    return by_name


def _check_slow(
    name: str, avg: float, durations: list, executions: list
) -> list[GoalProposal]:
    """Generate proposal if stage avg exceeds threshold."""
    if avg <= SLOW_STAGE_THRESHOLD_S:
        return []
    target = avg * HALF_FACTOR
    improvement = ((avg - target) / avg) * PCT_MULTIPLIER
    return [
        GoalProposal(
            goal_type=GoalType.PERFORMANCE_OPTIMIZATION,
            title=f"Optimize slow stage: {name}",
            description=(
                f"Stage '{name}' averages {avg:.0f}s across "
                f"{len(durations)} executions, exceeding "
                f"the {SLOW_STAGE_THRESHOLD_S}s threshold."
            ),
            risk_assessment=RiskAssessment(
                level=GoalRiskLevel.LOW,
                blast_radius=f"stage:{name}",
                reversible=True,
            ),
            effort_estimate=EffortLevel.MEDIUM,
            expected_impacts=[
                ImpactEstimate(
                    metric_name="avg_duration_seconds",
                    current_value=avg,
                    expected_value=target,
                    improvement_pct=improvement,
                    confidence=SLOW_CONFIDENCE,
                )
            ],
            evidence=GoalEvidence(
                workflow_ids=[
                    e.workflow_execution_id
                    for e in executions[:EVIDENCE_WORKFLOW_LIMIT]
                ],
                metrics={
                    "avg_duration_s": avg,
                    "execution_count": float(len(durations)),
                },
                analysis_summary=f"Slow stage detected: {avg:.0f}s avg",
            ),
            proposed_actions=[
                f"Profile stage '{name}' for bottlenecks",
                "Consider parallel execution or caching",
                "Review agent timeout configuration",
            ],
        )
    ]


def _check_degradation(name: str, durations: list) -> list[GoalProposal]:
    """Generate proposal if recent performance degraded vs baseline."""
    if len(durations) < MIN_DURATIONS_FOR_TREND:
        return []
    mid = len(durations) // 2
    first_avg = sum(durations[:mid]) / mid
    second_avg = sum(durations[mid:]) / (len(durations) - mid)
    if first_avg <= 0:
        return []
    degradation = ((second_avg - first_avg) / first_avg) * PCT_MULTIPLIER
    if degradation <= DEGRADATION_THRESHOLD_PCT:
        return []
    return [
        GoalProposal(
            goal_type=GoalType.PERFORMANCE_OPTIMIZATION,
            title=f"Address degradation in: {name}",
            description=(
                f"Stage '{name}' shows {degradation:.0f}% performance "
                f"degradation (recent avg {second_avg:.0f}s vs baseline "
                f"{first_avg:.0f}s)."
            ),
            risk_assessment=RiskAssessment(
                level=GoalRiskLevel.MEDIUM,
                blast_radius=f"stage:{name}",
                reversible=True,
            ),
            effort_estimate=EffortLevel.SMALL,
            expected_impacts=[
                ImpactEstimate(
                    metric_name="avg_duration_seconds",
                    current_value=second_avg,
                    expected_value=first_avg,
                    improvement_pct=degradation,
                    confidence=DEGRADATION_CONFIDENCE,
                )
            ],
            evidence=GoalEvidence(
                metrics={
                    "baseline_avg_s": first_avg,
                    "recent_avg_s": second_avg,
                    "degradation_pct": degradation,
                },
                analysis_summary=f"Performance degradation: {degradation:.0f}%",
            ),
            proposed_actions=[
                "Investigate recent configuration changes",
                "Check for resource contention",
            ],
        )
    ]
