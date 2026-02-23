"""Miner for recurring failure patterns."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import select

from temper_ai.learning.miners.base import DEFAULT_LOOKBACK_HOURS, BaseMiner
from temper_ai.learning.models import PATTERN_FAILURE, LearnedPattern
from temper_ai.storage.database import get_session
from temper_ai.storage.database.models import ErrorFingerprint

MIN_OCCURRENCES = 2
HIGH_CONFIDENCE = 0.9
MEDIUM_CONFIDENCE = 0.7


class FailurePatternMiner(BaseMiner):
    """Finds recurring error signatures from error fingerprints."""

    @property
    def pattern_type(self) -> str:
        """Return pattern type identifier."""
        return PATTERN_FAILURE

    def mine(
        self, lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    ) -> list[LearnedPattern]:
        """Mine error fingerprints for recurring failure patterns."""
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        patterns: list[LearnedPattern] = []

        with get_session() as session:
            stmt = select(ErrorFingerprint).where(ErrorFingerprint.last_seen >= cutoff)
            fingerprints = list(session.exec(stmt).all())

        for fp in fingerprints:
            if fp.occurrence_count < MIN_OCCURRENCES:
                continue
            patterns.append(_fingerprint_to_pattern(fp))

        return patterns


def _fingerprint_to_pattern(fp: ErrorFingerprint) -> LearnedPattern:
    """Convert an error fingerprint to a learned pattern."""
    confidence = (
        HIGH_CONFIDENCE
        if fp.occurrence_count >= MIN_OCCURRENCES * 2
        else MEDIUM_CONFIDENCE
    )
    impact = min(fp.occurrence_count / 10, 1.0)  # noqa

    return LearnedPattern(
        id=uuid.uuid4().hex,
        pattern_type=PATTERN_FAILURE,
        title=f"Recurring error: {fp.error_type}",
        description=f"Error '{fp.normalized_message}' occurred {fp.occurrence_count} times ({fp.classification})",
        evidence={
            "fingerprint": fp.fingerprint,
            "error_type": fp.error_type,
            "error_code": fp.error_code,
            "classification": fp.classification,
            "occurrence_count": fp.occurrence_count,
        },
        confidence=confidence,
        impact_score=impact,
        recommendation=_suggest_fix(fp),
        source_workflow_ids=fp.recent_workflow_ids or [],
    )


def _suggest_fix(fp: ErrorFingerprint) -> str:
    """Suggest a fix based on error classification."""
    suggestions: dict[str, str] = {
        "transient": f"Add retry logic or increase timeout for '{fp.error_type}'",
        "permanent": f"Fix root cause of '{fp.error_type}' — check config or code",
        "safety": f"Review safety policy triggering '{fp.error_type}'",
    }
    return suggestions.get(fp.classification, f"Investigate '{fp.error_type}'")
