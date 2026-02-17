"""Miner for cost optimization patterns."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlmodel import select

from src.learning.miners.base import BaseMiner, DEFAULT_LOOKBACK_HOURS
from src.learning.models import PATTERN_COST, LearnedPattern
from src.storage.database import get_session
from src.storage.database.models import LLMCall

MIN_CALLS = 5
COST_DOMINANCE_RATIO = 0.5
TOKEN_GROWTH_THRESHOLD = 1.5
HIGH_CONFIDENCE = 0.8
MEDIUM_CONFIDENCE = 0.65
_ID_DISPLAY_LEN = 12


class CostPatternMiner(BaseMiner):
    """Finds agents/models consuming disproportionate tokens or cost."""

    @property
    def pattern_type(self) -> str:
        """Return pattern type identifier."""
        return PATTERN_COST

    def mine(self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> List[LearnedPattern]:
        """Mine LLM call data for cost optimization patterns."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        patterns: List[LearnedPattern] = []

        with get_session() as session:
            stmt = select(LLMCall).where(LLMCall.start_time >= cutoff)
            calls = list(session.exec(stmt).all())

        if len(calls) < MIN_CALLS:
            return patterns

        agent_costs = _aggregate_by_agent(calls)
        total_cost = sum(s["cost"] for s in agent_costs.values())
        if total_cost <= 0:
            return patterns

        for agent_id, stats in agent_costs.items():
            share = stats["cost"] / total_cost
            if share > COST_DOMINANCE_RATIO:
                patterns.append(_cost_dominance_pattern(agent_id, stats, share))

        return patterns


def _aggregate_by_agent(calls: list) -> Dict[str, dict]:
    """Aggregate cost and token data by agent execution ID."""
    agent_costs: Dict[str, dict] = defaultdict(
        lambda: {"cost": 0.0, "tokens": 0, "calls": 0}
    )
    for call in calls:
        s = agent_costs[call.agent_execution_id]
        s["calls"] += 1
        if call.estimated_cost_usd:
            s["cost"] += call.estimated_cost_usd
        if call.total_tokens:
            s["tokens"] += call.total_tokens
    return dict(agent_costs)


def _cost_dominance_pattern(agent_id: str, stats: dict, share: float) -> LearnedPattern:
    """Create a pattern for an agent dominating costs."""
    return LearnedPattern(
        id=uuid.uuid4().hex,
        pattern_type=PATTERN_COST,
        title=f"Cost-dominant agent: {agent_id[:_ID_DISPLAY_LEN]}",
        description=f"Agent consumes {share:.0%} of total cost (${stats['cost']:.4f}, {stats['tokens']} tokens)",
        evidence={
            "agent_execution_id": agent_id,
            "cost_share": share,
            "total_cost": stats["cost"],
            "total_tokens": stats["tokens"],
        },
        confidence=HIGH_CONFIDENCE,
        impact_score=share,
        recommendation="Consider using a cheaper model or reducing max_tokens",
    )
