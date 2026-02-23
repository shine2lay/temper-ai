"""Miner for collaboration/debate patterns."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from temper_ai.learning.miners.base import DEFAULT_LOOKBACK_HOURS, BaseMiner
from temper_ai.learning.models import PATTERN_COLLABORATION, LearnedPattern
from temper_ai.storage.database import get_session
from temper_ai.storage.database.models import CollaborationEvent

MIN_EVENTS = 2
WASTED_ROUND_THRESHOLD = 2
HIGH_CONFIDENCE = 0.8
MEDIUM_CONFIDENCE = 0.65
SLOW_CONSENSUS_IMPACT = 0.4
_ID_DISPLAY_LEN = 12


class CollaborationPatternMiner(BaseMiner):
    """Finds wasted debate rounds and collaboration inefficiencies."""

    @property
    def pattern_type(self) -> str:
        """Return pattern type identifier."""
        return PATTERN_COLLABORATION

    def mine(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> list[LearnedPattern]:
        """Mine collaboration events for debate/consensus patterns."""
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        patterns: list[LearnedPattern] = []

        with get_session() as session:
            stmt = select(CollaborationEvent).where(
                CollaborationEvent.timestamp >= cutoff
            )
            events = list(session.exec(stmt).all())

        if len(events) < MIN_EVENTS:
            return patterns

        stage_rounds = _aggregate_by_stage(events)
        for stage_id, stats in stage_rounds.items():
            patterns.extend(_check_stage(stage_id, stats))

        return patterns


def _aggregate_by_stage(events: list) -> dict[str, dict]:
    """Group events by stage and count rounds and resolutions."""
    stages: dict[str, dict] = defaultdict(
        lambda: {"rounds": 0, "resolutions": 0, "event_types": []}
    )
    for ev in events:
        s = stages[ev.stage_execution_id]
        if ev.event_type == "debate_round":
            s["rounds"] += 1
        if ev.event_type in ("resolution", "consensus"):
            s["resolutions"] += 1
        s["event_types"].append(ev.event_type)
    return dict(stages)


def _check_stage(stage_id: str, stats: dict) -> list[LearnedPattern]:
    """Check stage collaboration stats for patterns."""
    patterns: list[LearnedPattern] = []

    # Excessive debate rounds without resolution
    if stats["rounds"] > WASTED_ROUND_THRESHOLD and stats["resolutions"] == 0:
        patterns.append(
            LearnedPattern(
                id=uuid.uuid4().hex,
                pattern_type=PATTERN_COLLABORATION,
                title=f"Unresolved debate: stage {stage_id[:_ID_DISPLAY_LEN]}",
                description=f"{stats['rounds']} debate rounds with no resolution",
                evidence={
                    "stage_id": stage_id,
                    "rounds": stats["rounds"],
                    "resolutions": stats["resolutions"],
                },
                confidence=HIGH_CONFIDENCE,
                impact_score=min(stats["rounds"] / 10, 1.0),  # noqa
                recommendation="Reduce max debate rounds or adjust resolution strategy",
            )
        )

    # Many rounds even with resolution (inefficient consensus)
    if stats["rounds"] > WASTED_ROUND_THRESHOLD and stats["resolutions"] > 0:
        patterns.append(
            LearnedPattern(
                id=uuid.uuid4().hex,
                pattern_type=PATTERN_COLLABORATION,
                title=f"Slow consensus: stage {stage_id[:_ID_DISPLAY_LEN]}",
                description=f"{stats['rounds']} rounds to reach {stats['resolutions']} resolution(s)",
                evidence={
                    "stage_id": stage_id,
                    "rounds": stats["rounds"],
                    "resolutions": stats["resolutions"],
                },
                confidence=MEDIUM_CONFIDENCE,
                impact_score=SLOW_CONSENSUS_IMPACT,
                recommendation="Consider fewer agents or weighted voting",
            )
        )

    return patterns
