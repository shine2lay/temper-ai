"""
Timezone-aware datetime utilities for observability system.

Enforces UTC timezone consistency across all observability operations.
"""
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """
    Get current UTC time with timezone awareness.

    Returns:
        datetime: Current UTC time with tzinfo=timezone.utc

    Example:
        >>> now = utcnow()
        >>> assert now.tzinfo is not None
        >>> assert now.tzinfo == timezone.utc
    """
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ensure datetime is timezone-aware in UTC.

    Handles three cases:
    1. None: returns None
    2. Timezone-aware: converts to UTC if needed
    3. Timezone-naive: assumes UTC and adds tzinfo

    Args:
        dt: Datetime to normalize (can be None, aware, or naive)

    Returns:
        UTC timezone-aware datetime, or None if input was None

    Warning:
        If dt is timezone-naive, it will be ASSUMED to be UTC.
        This is the only safe assumption for observability data.

    Example:
        >>> naive = datetime(2024, 1, 1, 12, 0, 0)  # No tzinfo
        >>> aware = ensure_utc(naive)
        >>> assert aware.tzinfo == timezone.utc

        >>> from zoneinfo import ZoneInfo
        >>> eastern = datetime(2024, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("America/New_York"))
        >>> utc_time = ensure_utc(eastern)
        >>> assert utc_time.tzinfo == timezone.utc
        >>> # Time is converted: 12:00 EST -> 17:00 UTC
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        # Timezone-naive: assume UTC
        logger.debug(
            f"Converting timezone-naive datetime to UTC: {dt}. "
            "If this datetime was not UTC, duration calculations may be incorrect."
        )
        return dt.replace(tzinfo=timezone.utc)

    if dt.tzinfo != timezone.utc:
        # Timezone-aware but not UTC: convert
        logger.debug(f"Converting {dt.tzinfo} datetime to UTC: {dt}")
        return dt.astimezone(timezone.utc)

    # Already UTC timezone-aware
    return dt


def validate_utc_aware(dt: datetime, context: str = "") -> None:
    """
    Validate that datetime is timezone-aware and in UTC.

    Raises ValueError if datetime is naive or not UTC.
    Use this for strict validation at critical boundaries.

    Args:
        dt: Datetime to validate
        context: Context string for error messages (e.g., "workflow start_time")

    Raises:
        ValueError: If datetime is timezone-naive or not UTC

    Example:
        >>> dt = datetime.now(timezone.utc)
        >>> validate_utc_aware(dt, "workflow_start")  # OK

        >>> naive_dt = datetime.now()
        >>> validate_utc_aware(naive_dt, "workflow_start")  # Raises ValueError
    """
    context_str = f" ({context})" if context else ""

    if dt.tzinfo is None:
        raise ValueError(
            f"Timezone-naive datetime not allowed{context_str}. "
            f"Use datetime.now(timezone.utc) instead of datetime.now() or datetime.utcnow(). "
            f"Got: {dt}"
        )

    if dt.tzinfo != timezone.utc:
        raise ValueError(
            f"Non-UTC datetime not allowed{context_str}. "
            f"Convert to UTC using dt.astimezone(timezone.utc). "
            f"Got: {dt} with tzinfo={dt.tzinfo}"
        )


def safe_duration_seconds(
    start_time: datetime,
    end_time: datetime,
    context: str = ""
) -> float:
    """
    Calculate duration between two datetimes safely.

    Automatically normalizes both datetimes to UTC before calculation.
    This prevents TypeError when mixing aware/naive datetimes.

    Args:
        start_time: Start datetime
        end_time: End datetime
        context: Context for logging (e.g., "workflow execution")

    Returns:
        Duration in seconds (float)

    Example:
        >>> start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        >>> end = datetime(2024, 1, 1, 12, 5, 30, tzinfo=timezone.utc)
        >>> duration = safe_duration_seconds(start, end)
        >>> assert duration == 330.0  # 5.5 minutes
    """
    # Normalize to UTC
    start_utc = ensure_utc(start_time)
    end_utc = ensure_utc(end_time)

    if start_utc is None or end_utc is None:
        logger.warning(
            f"Cannot calculate duration with None datetime{' for ' + context if context else ''}"
        )
        return 0.0

    # Now safe to subtract
    duration = (end_utc - start_utc).total_seconds()

    # Sanity check: negative duration indicates clock skew or error
    if duration < 0:
        logger.warning(
            f"Negative duration detected{' for ' + context if context else ''}: "
            f"{duration:.2f}s (start={start_utc}, end={end_utc}). "
            "This may indicate clock skew or incorrect timestamps."
        )

    return duration
