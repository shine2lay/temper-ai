"""Miner for model effectiveness patterns."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlmodel import select

from src.learning.miners.base import BaseMiner, DEFAULT_LOOKBACK_HOURS
from src.learning.models import PATTERN_MODEL_EFFECTIVENESS, LearnedPattern
from src.storage.database import get_session
from src.storage.database.models import LLMCall

MIN_CALLS = 5
HIGH_ERROR_RATE = 0.3
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.7
COST_PROFILE_IMPACT = 0.3


class ModelEffectivenessMiner(BaseMiner):
    """Finds models with high error rates or cost/quality imbalances."""

    @property
    def pattern_type(self) -> str:
        """Return pattern type identifier."""
        return PATTERN_MODEL_EFFECTIVENESS

    def mine(self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> List[LearnedPattern]:
        """Mine LLM call data for model effectiveness patterns."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        patterns: List[LearnedPattern] = []

        with get_session() as session:
            stmt = select(LLMCall).where(LLMCall.start_time >= cutoff)
            calls = list(session.exec(stmt).all())

        if not calls:
            return patterns

        model_stats = _aggregate_model_stats(calls)
        for model, stats in model_stats.items():
            if stats["total"] < MIN_CALLS:
                continue
            patterns.extend(_check_model(model, stats))

        return patterns


def _aggregate_model_stats(calls: list) -> Dict[str, dict]:
    """Group LLM calls by model and compute error/cost stats."""
    stats: Dict[str, dict] = defaultdict(
        lambda: {"total": 0, "errors": 0, "total_cost": 0.0, "total_tokens": 0}
    )
    for call in calls:
        s = stats[call.model]
        s["total"] += 1
        if call.status in ("error", "timeout"):
            s["errors"] += 1
        if call.estimated_cost_usd:
            s["total_cost"] += call.estimated_cost_usd
        if call.total_tokens:
            s["total_tokens"] += call.total_tokens
    return dict(stats)


def _check_model(model: str, stats: dict) -> List[LearnedPattern]:
    """Check a model's stats for patterns."""
    patterns: List[LearnedPattern] = []
    error_rate = stats["errors"] / stats["total"]

    if error_rate > HIGH_ERROR_RATE:
        patterns.append(LearnedPattern(
            id=uuid.uuid4().hex,
            pattern_type=PATTERN_MODEL_EFFECTIVENESS,
            title=f"High error rate: {model}",
            description=f"Model '{model}' has {error_rate:.0%} error rate over {stats['total']} calls",
            evidence={"error_rate": error_rate, "total_calls": stats["total"], "errors": stats["errors"]},
            confidence=HIGH_CONFIDENCE,
            impact_score=error_rate,
            recommendation=f"Consider switching from '{model}' to a more reliable model",
        ))

    if stats["total_tokens"] > 0 and stats["total_cost"] > 0:
        cost_per_token = stats["total_cost"] / stats["total_tokens"]
        patterns.append(LearnedPattern(
            id=uuid.uuid4().hex,
            pattern_type=PATTERN_MODEL_EFFECTIVENESS,
            title=f"Cost profile: {model}",
            description=f"Model '{model}': ${stats['total_cost']:.4f} over {stats['total_tokens']} tokens",
            evidence={"cost_per_token": cost_per_token, "total_cost": stats["total_cost"]},
            confidence=MEDIUM_CONFIDENCE,
            impact_score=COST_PROFILE_IMPACT,
        ))

    return patterns
