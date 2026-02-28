"""Tests for temper_ai/shared/utils/datetime_utils.py.

Covers UTC-centric datetime helpers used across subsystems.
"""

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from temper_ai.shared.utils.datetime_utils import (
    ensure_utc,
    safe_duration_seconds,
    utcnow,
    validate_utc_aware,
)


class TestUtcnow:
    """Tests for utcnow()."""

    def test_returns_datetime(self):
        """utcnow returns a datetime instance."""
        result = utcnow()
        assert isinstance(result, datetime)

    def test_returns_utc_aware(self):
        """utcnow returns a timezone-aware UTC datetime."""
        result = utcnow()
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_returns_current_time(self):
        """utcnow is close to actual current UTC time."""
        before = datetime.now(UTC)
        result = utcnow()
        after = datetime.now(UTC)
        assert before <= result <= after


class TestEnsureUtc:
    """Tests for ensure_utc()."""

    def test_none_returns_none(self):
        """ensure_utc(None) returns None."""
        assert ensure_utc(None) is None

    def test_utc_datetime_unchanged(self):
        """Already-UTC datetime is returned as-is."""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = ensure_utc(dt)
        assert result == dt
        assert result.tzinfo == UTC

    def test_naive_datetime_assumed_utc(self):
        """Naive datetime gets UTC tzinfo attached."""
        naive = datetime(2024, 6, 15, 10, 30, 0)
        result = ensure_utc(naive)
        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2024
        assert result.hour == 10

    def test_non_utc_aware_converted(self):
        """Aware non-UTC datetime is converted to UTC."""
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=eastern)
        result = ensure_utc(dt)
        assert result is not None
        assert result.tzinfo == UTC
        # 12:00 Eastern (-5) = 17:00 UTC
        assert result.hour == 17

    def test_positive_offset_converted(self):
        """Positive UTC offset datetime is correctly converted."""
        plus8 = timezone(timedelta(hours=8))
        dt = datetime(2024, 3, 10, 8, 0, 0, tzinfo=plus8)
        result = ensure_utc(dt)
        assert result is not None
        assert result.tzinfo == UTC
        # 08:00 +8 = 00:00 UTC
        assert result.hour == 0


class TestValidateUtcAware:
    """Tests for validate_utc_aware()."""

    def test_valid_utc_passes(self):
        """UTC-aware datetime does not raise."""
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        validate_utc_aware(dt)  # Should not raise

    def test_naive_raises(self):
        """Naive datetime raises ValueError."""
        naive = datetime(2024, 1, 1, 12, 0)
        with pytest.raises(ValueError, match="Timezone-naive"):
            validate_utc_aware(naive)

    def test_naive_with_context_raises(self):
        """Naive datetime raises ValueError with context in message."""
        naive = datetime(2024, 1, 1)
        with pytest.raises(ValueError, match="my_context"):
            validate_utc_aware(naive, context="my_context")

    def test_non_utc_raises(self):
        """Non-UTC aware datetime raises ValueError."""
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 1, 1, tzinfo=eastern)
        with pytest.raises(ValueError, match="Non-UTC"):
            validate_utc_aware(dt)

    def test_non_utc_with_context_raises(self):
        """Non-UTC raises ValueError with context in message."""
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 1, 1, tzinfo=eastern)
        with pytest.raises(ValueError, match="start_time"):
            validate_utc_aware(dt, context="start_time")

    def test_empty_context_no_parens(self):
        """Empty context string produces clean error message."""
        naive = datetime(2024, 1, 1)
        with pytest.raises(ValueError) as exc_info:
            validate_utc_aware(naive, context="")
        assert "()" not in str(exc_info.value)


class TestSafeDurationSeconds:
    """Tests for safe_duration_seconds()."""

    def test_positive_duration(self):
        """Returns positive duration for end > start."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert result == 30.0

    def test_zero_duration(self):
        """Returns 0.0 for equal datetimes."""
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = safe_duration_seconds(dt, dt)
        assert result == 0.0

    def test_negative_duration_returns_negative(self):
        """Returns negative float (and logs warning) when end < start."""
        start = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert result == -30.0

    def test_negative_duration_logs_warning(self, caplog):
        """Logs a warning when duration is negative."""
        start = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        with caplog.at_level(logging.WARNING):
            safe_duration_seconds(start, end)
        assert any("Negative duration" in r.message for r in caplog.records)

    def test_naive_datetimes_normalised(self):
        """Naive datetimes are treated as UTC and duration computed correctly."""
        start = datetime(2024, 1, 1, 12, 0, 0)  # naive
        end = datetime(2024, 1, 1, 12, 1, 0)  # naive
        result = safe_duration_seconds(start, end)
        assert result == 60.0

    def test_context_in_warning(self, caplog):
        """Context string appears in warning message."""
        start = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        with caplog.at_level(logging.WARNING):
            safe_duration_seconds(start, end, context="stage_exec")
        assert any("stage_exec" in r.message for r in caplog.records)

    def test_large_duration(self):
        """Returns correct result for multi-day spans."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 8, 0, 0, 0, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert result == 7 * 24 * 3600

    def test_fractional_seconds(self):
        """Returns fractional seconds when microseconds differ."""
        start = datetime(2024, 1, 1, 0, 0, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 0, 0, 0, 500_000, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert abs(result - 0.5) < 1e-6

    def test_cross_timezone_duration(self):
        """Cross-timezone datetimes produce correct UTC-normalized duration."""
        eastern = timezone(timedelta(hours=-5))
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=eastern)  # 17:00 UTC
        end = datetime(2024, 1, 1, 18, 0, 0, tzinfo=UTC)  # 18:00 UTC
        result = safe_duration_seconds(start, end)
        assert result == 3600.0
