"""Miner for agent performance patterns."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from temper_ai.learning.miners.base import DEFAULT_LOOKBACK_HOURS, BaseMiner
from temper_ai.learning.models import PATTERN_AGENT_PERFORMANCE, LearnedPattern
from temper_ai.storage.database import get_session
from temper_ai.storage.database.models import AgentExecution

# Thresholds
MIN_EXECUTIONS = 3
LOW_SUCCESS_RATE = 0.5
HIGH_SUCCESS_RATE = 0.95
SLOW_FACTOR = 2.0
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.75


class AgentPerformanceMiner(BaseMiner):
    """Finds agents with consistently high/low success rates or slow execution."""

    @property
    def pattern_type(self) -> str:
        """Return pattern type identifier."""
        return PATTERN_AGENT_PERFORMANCE

    def mine(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> list[LearnedPattern]:
        """Mine agent execution data for performance patterns."""
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        patterns: list[LearnedPattern] = []

        with get_session() as session:
            stmt = select(AgentExecution).where(AgentExecution.start_time >= cutoff)
            executions = list(session.exec(stmt).all())

        if not executions:
            return patterns

        agent_stats = _aggregate_agent_stats(executions)
        avg_duration = _overall_avg_duration(executions)

        for name, stats in agent_stats.items():
            if stats["total"] < MIN_EXECUTIONS:
                continue
            patterns.extend(_check_agent(name, stats, avg_duration))

        return patterns


def _aggregate_agent_stats(executions: list) -> dict:
    """Group executions by agent name and compute stats."""
    stats: dict = {}
    for ex in executions:
        name = ex.agent_name
        if name not in stats:
            stats[name] = {
                "total": 0,
                "success": 0,
                "durations": [],
                "workflow_ids": set(),
            }
        stats[name]["total"] += 1
        if ex.status == "completed":
            stats[name]["success"] += 1
        if ex.duration_seconds is not None:
            stats[name]["durations"].append(ex.duration_seconds)
        # Traverse to get workflow ID via stage
        if hasattr(ex, "stage") and ex.stage:
            stats[name]["workflow_ids"].add(ex.stage.workflow_execution_id)
    return stats


def _overall_avg_duration(executions: list) -> float:
    """Compute overall average duration across all executions."""
    durations: list[float] = [
        e.duration_seconds for e in executions if e.duration_seconds
    ]
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def _check_agent(name: str, stats: dict, avg_duration: float) -> list[LearnedPattern]:
    """Check an agent's stats for patterns."""
    patterns: list[LearnedPattern] = []
    rate = stats["success"] / stats["total"]
    wf_ids = list(stats["workflow_ids"])

    if rate < LOW_SUCCESS_RATE:
        patterns.append(
            LearnedPattern(
                id=uuid.uuid4().hex,
                pattern_type=PATTERN_AGENT_PERFORMANCE,
                title=f"Low success rate: {name}",
                description=f"Agent '{name}' has {rate:.0%} success rate over {stats['total']} runs",
                evidence={"success_rate": rate, "total_runs": stats["total"]},
                confidence=HIGH_CONFIDENCE,
                impact_score=1.0 - rate,
                recommendation=f"Investigate failures for agent '{name}'",
                source_workflow_ids=wf_ids,
            )
        )

    if stats["durations"] and avg_duration > 0:
        agent_avg = sum(stats["durations"]) / len(stats["durations"])
        if agent_avg > avg_duration * SLOW_FACTOR:
            patterns.append(
                LearnedPattern(
                    id=uuid.uuid4().hex,
                    pattern_type=PATTERN_AGENT_PERFORMANCE,
                    title=f"Slow agent: {name}",
                    description=f"Agent '{name}' avg {agent_avg:.1f}s vs overall {avg_duration:.1f}s",
                    evidence={
                        "agent_avg_duration": agent_avg,
                        "overall_avg": avg_duration,
                    },
                    confidence=MEDIUM_CONFIDENCE,
                    impact_score=min(agent_avg / max(avg_duration, 1), 1.0),
                    recommendation=f"Optimize or increase timeout for '{name}'",
                    source_workflow_ids=wf_ids,
                )
            )

    return patterns
