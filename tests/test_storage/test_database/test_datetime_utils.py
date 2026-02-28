"""Tests for temper_ai.storage.database.datetime_utils.

Verifies that the storage module correctly re-exports the canonical
datetime utilities from temper_ai.shared.utils.datetime_utils.
"""

from datetime import UTC, datetime, timezone

import pytest

from temper_ai.storage.database import datetime_utils as storage_dt
from temper_ai.storage.database.datetime_utils import (
    ensure_utc,
    safe_duration_seconds,
    utcnow,
    validate_utc_aware,
)


class TestReExports:
    """Verify the re-exports are present and callable."""

    def test_utcnow_exported(self):
        assert callable(utcnow)

    def test_ensure_utc_exported(self):
        assert callable(ensure_utc)

    def test_validate_utc_aware_exported(self):
        assert callable(validate_utc_aware)

    def test_safe_duration_seconds_exported(self):
        assert callable(safe_duration_seconds)

    def test_all_list(self):
        assert set(storage_dt.__all__) == {
            "utcnow",
            "ensure_utc",
            "validate_utc_aware",
            "safe_duration_seconds",
        }


class TestUtcNow:
    """Tests for utcnow()."""

    def test_returns_datetime(self):
        result = utcnow()
        assert isinstance(result, datetime)

    def test_is_timezone_aware(self):
        result = utcnow()
        assert result.tzinfo is not None

    def test_is_utc(self):
        result = utcnow()
        assert result.tzinfo == UTC


class TestEnsureUtc:
    """Tests for ensure_utc()."""

    def test_none_returns_none(self):
        assert ensure_utc(None) is None

    def test_naive_datetime_becomes_utc(self):
        naive = datetime(2024, 1, 15, 12, 0, 0)
        result = ensure_utc(naive)
        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2024

    def test_utc_datetime_unchanged(self):
        utc_dt = datetime(2024, 6, 1, 8, 30, 0, tzinfo=UTC)
        result = ensure_utc(utc_dt)
        assert result == utc_dt

    def test_non_utc_timezone_converted(self):
        timezone(
            datetime(2024, 1, 1).utcoffset()
            or __import__("datetime").timedelta(hours=-5)
        )
        # Use a fixed offset timezone
        fixed_tz = timezone(__import__("datetime").timedelta(hours=5))
        aware_dt = datetime(2024, 1, 15, 17, 0, 0, tzinfo=fixed_tz)
        result = ensure_utc(aware_dt)
        assert result is not None
        assert result.tzinfo == UTC


class TestValidateUtcAware:
    """Tests for validate_utc_aware()."""

    def test_utc_datetime_passes(self):
        utc_dt = datetime(2024, 1, 1, tzinfo=UTC)
        validate_utc_aware(utc_dt)  # Should not raise

    def test_naive_raises_value_error(self):
        naive = datetime(2024, 1, 1)
        with pytest.raises(ValueError, match="Timezone-naive"):
            validate_utc_aware(naive)

    def test_naive_with_context_includes_context(self):
        naive = datetime(2024, 1, 1)
        with pytest.raises(ValueError, match="my_field"):
            validate_utc_aware(naive, context="my_field")

    def test_non_utc_raises_value_error(self):
        fixed_tz = timezone(__import__("datetime").timedelta(hours=3))
        aware_dt = datetime(2024, 1, 1, tzinfo=fixed_tz)
        with pytest.raises(ValueError, match="Non-UTC"):
            validate_utc_aware(aware_dt)


class TestSafeDurationSeconds:
    """Tests for safe_duration_seconds()."""

    def test_positive_duration(self):
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert result == 30.0

    def test_zero_duration(self):
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        result = safe_duration_seconds(dt, dt)
        assert result == 0.0

    def test_negative_duration_returns_negative(self):
        start = datetime(2024, 1, 1, 12, 0, 30, tzinfo=UTC)
        end = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = safe_duration_seconds(start, end)
        assert result < 0

    def test_naive_datetimes_treated_as_utc(self):
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 1, 0)
        result = safe_duration_seconds(start, end)
        assert result == 60.0

    def test_with_context_string(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 1, 0, 1, 0, tzinfo=UTC)
        result = safe_duration_seconds(start, end, context="test_op")
        assert result == 60.0
