"""Timezone-aware datetime utilities.

Provides UTC-centric helpers used across all subsystems. The canonical
location for these utilities so that lower-level modules (events, storage)
can both depend on ``shared`` without creating circular imports.
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(UTC)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalise *dt* to UTC. Naive datetimes are assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    if dt.tzinfo != UTC:
        return dt.astimezone(UTC)
    return dt


def validate_utc_aware(dt: datetime, context: str = "") -> None:
    """Raise ``ValueError`` if *dt* is naive or not UTC."""
    ctx = f" ({context})" if context else ""
    if dt.tzinfo is None:
        raise ValueError(f"Timezone-naive datetime not allowed{ctx}. Got: {dt}")
    if dt.tzinfo != UTC:
        raise ValueError(
            f"Non-UTC datetime not allowed{ctx}. Got: {dt} tzinfo={dt.tzinfo}"
        )


def safe_duration_seconds(
    start_time: datetime, end_time: datetime, context: str = ""
) -> float:
    """Calculate duration in seconds between two datetimes, normalising to UTC."""
    start_utc = ensure_utc(start_time)
    end_utc = ensure_utc(end_time)
    if start_utc is None or end_utc is None:
        return 0.0
    duration = (end_utc - start_utc).total_seconds()
    if duration < 0:
        logger.warning(
            "Negative duration%s: %.2fs", f" for {context}" if context else "", duration
        )
    return duration
