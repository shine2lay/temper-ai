"""Reliability analyzer — detects recurring failure patterns."""

import logging
from datetime import timedelta
from typing import List, Optional

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
    HIGH_FAILURE_RATE,
    MIN_FAILURES_FOR_PROPOSAL,
)

logger = logging.getLogger(__name__)

PCT_MULTIPLIER = 100
HALF_FACTOR = 0.5
ERROR_FIX_CONFIDENCE = 0.7
FAILURE_RATE_CONFIDENCE = 0.6
FAILURE_RATE_IMPROVEMENT_PCT = 50.0

EFFORT_BY_CLASSIFICATION = {
    "transient": EffortLevel.SMALL,
    "permanent": EffortLevel.MEDIUM,
    "safety": EffortLevel.LARGE,
}


class ReliabilityAnalyzer(BaseAnalyzer):
    """Identifies recurring failure patterns and reliability issues."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine = engine

    @property
    def analyzer_type(self) -> str:
        """Return analyzer identifier."""
        return "reliability"

    def analyze(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> List[GoalProposal]:
        """Analyze error fingerprints and agent failure rates."""
        if self._engine is None:
            return []

        fingerprints, agents = self._query_data(lookback_hours)
        proposals: List[GoalProposal] = []
        proposals.extend(_proposals_from_errors(fingerprints))
        proposals.extend(_proposals_from_failure_rates(agents))
        return proposals

    def _query_data(self, lookback_hours: int) -> tuple:
        """Query error fingerprints and agent executions."""
        from temper_ai.storage.database.datetime_utils import utcnow
        from temper_ai.storage.database.models import AgentExecution, ErrorFingerprint

        cutoff = utcnow() - timedelta(hours=lookback_hours)
        with Session(self._engine) as session:
            fingerprints = list(session.exec(
                select(ErrorFingerprint).where(
                    ErrorFingerprint.last_seen >= cutoff,
                    ErrorFingerprint.resolved == False,  # noqa: E712
                    ErrorFingerprint.occurrence_count >= MIN_FAILURES_FOR_PROPOSAL,
                )
            ).all())
            agents = list(session.exec(
                select(AgentExecution).where(AgentExecution.start_time >= cutoff)
            ).all())
        return fingerprints, agents


def _proposals_from_errors(fingerprints: list) -> List[GoalProposal]:
    """Generate proposals for recurring error fingerprints."""
    return [
        GoalProposal(
            goal_type=GoalType.RELIABILITY_IMPROVEMENT,
            title=f"Fix recurring error: {fp.error_type}",
            description=(
                f"Error '{fp.normalized_message}' has occurred "
                f"{fp.occurrence_count} times (type: {fp.classification})."
            ),
            risk_assessment=RiskAssessment(
                level=GoalRiskLevel.LOW, blast_radius=f"error:{fp.error_code}", reversible=True,
            ),
            effort_estimate=EFFORT_BY_CLASSIFICATION.get(fp.classification, EffortLevel.MEDIUM),
            expected_impacts=[ImpactEstimate(
                metric_name="error_occurrences",
                current_value=float(fp.occurrence_count), expected_value=0.0,
                improvement_pct=PCT_MULTIPLIER, confidence=ERROR_FIX_CONFIDENCE,
            )],
            evidence=GoalEvidence(
                workflow_ids=fp.recent_workflow_ids or [],
                metrics={"occurrence_count": float(fp.occurrence_count)},
                analysis_summary=f"Recurring {fp.classification} error: {fp.occurrence_count} occurrences",
            ),
            proposed_actions=[
                f"Investigate root cause of {fp.error_type}",
                "Add retry logic or fallback handling",
                "Update error handling configuration",
            ],
        )
        for fp in fingerprints
    ]


def _proposals_from_failure_rates(agents: list) -> List[GoalProposal]:
    """Generate proposals for agents with high failure rates."""
    if not agents:
        return []

    by_agent: dict[str, dict] = {}
    for a in agents:
        stats = by_agent.setdefault(a.agent_name, {"total": 0, "failed": 0})
        stats["total"] += 1
        if a.status == "failed":
            stats["failed"] += 1

    proposals: List[GoalProposal] = []
    for agent_name, stats in by_agent.items():
        if stats["total"] == 0:
            continue
        rate = stats["failed"] / stats["total"]
        if rate > HIGH_FAILURE_RATE:
            target = rate * HALF_FACTOR
            proposals.append(GoalProposal(
                goal_type=GoalType.RELIABILITY_IMPROVEMENT,
                title=f"Reduce failure rate for: {agent_name}",
                description=(
                    f"Agent '{agent_name}' has a {rate * PCT_MULTIPLIER:.0f}% "
                    f"failure rate ({stats['failed']}/{stats['total']} executions)."
                ),
                risk_assessment=RiskAssessment(
                    level=GoalRiskLevel.LOW, blast_radius=f"agent:{agent_name}", reversible=True,
                ),
                effort_estimate=EffortLevel.MEDIUM,
                expected_impacts=[ImpactEstimate(
                    metric_name="failure_rate", current_value=rate, expected_value=target,
                    improvement_pct=FAILURE_RATE_IMPROVEMENT_PCT, confidence=FAILURE_RATE_CONFIDENCE,
                )],
                evidence=GoalEvidence(
                    metrics={
                        "failure_rate": rate,
                        "total_executions": float(stats["total"]),
                        "failed_executions": float(stats["failed"]),
                    },
                    analysis_summary=f"High failure rate: {rate * PCT_MULTIPLIER:.0f}%",
                ),
                proposed_actions=[
                    "Review agent error logs for patterns",
                    "Add better error handling and retries",
                    "Consider model or prompt adjustments",
                ],
            ))
    return proposals
