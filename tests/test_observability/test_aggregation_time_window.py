"""Tests for src/observability/aggregation/time_window.py."""
from datetime import datetime, timedelta, timezone

import pytest
from src.observability.aggregation.period import AggregationPeriod
from src.observability.aggregation.time_window import TimeWindowCalculator


class TestGetPeriodStart:
    """Tests for TimeWindowCalculator.get_period_start."""

    def test_get_period_start_minute(self):
        """Test period start calculation for MINUTE."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.MINUTE)

        expected = datetime(2024, 1, 1, 14, 29, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_hour(self):
        """Test period start calculation for HOUR."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.HOUR)

        expected = datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_day(self):
        """Test period start calculation for DAY."""
        end_time = datetime(2024, 1, 5, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.DAY)

        expected = datetime(2024, 1, 4, 14, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_minute_crosses_hour(self):
        """Test MINUTE period that crosses hour boundary."""
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.MINUTE)

        expected = datetime(2024, 1, 1, 13, 59, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_hour_crosses_day(self):
        """Test HOUR period that crosses day boundary."""
        end_time = datetime(2024, 1, 2, 0, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.HOUR)

        expected = datetime(2024, 1, 1, 23, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_day_crosses_month(self):
        """Test DAY period that crosses month boundary."""
        end_time = datetime(2024, 2, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.DAY)

        expected = datetime(2024, 1, 31, 14, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_get_period_start_preserves_microseconds(self):
        """Test that microseconds are preserved."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, 123456, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.MINUTE)

        assert start_time.microsecond == 123456


class TestGetDefaultTimeWindow:
    """Tests for TimeWindowCalculator.get_default_time_window."""

    def test_get_default_time_window_minute(self):
        """Test default time window for MINUTE period."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time, returned_end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.MINUTE,
            end_time=end_time
        )

        expected_start = datetime(2024, 1, 1, 14, 29, 0, tzinfo=timezone.utc)
        assert start_time == expected_start
        assert returned_end == end_time

    def test_get_default_time_window_hour(self):
        """Test default time window for HOUR period."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time, returned_end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.HOUR,
            end_time=end_time
        )

        expected_start = datetime(2024, 1, 1, 13, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected_start
        assert returned_end == end_time

    def test_get_default_time_window_day(self):
        """Test default time window for DAY period."""
        end_time = datetime(2024, 1, 5, 14, 30, 0, tzinfo=timezone.utc)
        start_time, returned_end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.DAY,
            end_time=end_time
        )

        expected_start = datetime(2024, 1, 4, 14, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected_start
        assert returned_end == end_time

    def test_get_default_time_window_none_end_time(self):
        """Test that None end_time defaults to now."""
        before = datetime.now(timezone.utc)
        start_time, end_time = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.MINUTE
        )
        after = datetime.now(timezone.utc)

        # end_time should be close to now
        assert before <= end_time <= after

        # start_time should be 1 minute before end_time
        assert end_time - start_time == timedelta(minutes=1)

    def test_get_default_time_window_returns_tuple(self):
        """Test that the method returns a tuple."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        result = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.MINUTE,
            end_time=end_time
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_get_default_time_window_start_before_end(self):
        """Test that start_time is always before end_time."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)

        for period in AggregationPeriod:
            start_time, returned_end = TimeWindowCalculator.get_default_time_window(
                period,
                end_time=end_time
            )
            assert start_time < returned_end

    def test_get_default_time_window_correct_duration(self):
        """Test that the window has the correct duration for each period."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)

        # MINUTE
        start, end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.MINUTE,
            end_time=end_time
        )
        assert end - start == timedelta(minutes=1)

        # HOUR
        start, end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.HOUR,
            end_time=end_time
        )
        assert end - start == timedelta(hours=1)

        # DAY
        start, end = TimeWindowCalculator.get_default_time_window(
            AggregationPeriod.DAY,
            end_time=end_time
        )
        assert end - start == timedelta(days=1)


class TestTimeWindowCalculatorEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_leap_year_day_period(self):
        """Test DAY period on leap year (Feb 29)."""
        end_time = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.DAY)

        # 2024 is a leap year, so Feb 29 exists
        expected = datetime(2024, 2, 29, 12, 0, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_year_boundary(self):
        """Test period that crosses year boundary."""
        end_time = datetime(2024, 1, 1, 0, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.HOUR)

        expected = datetime(2023, 12, 31, 23, 30, 0, tzinfo=timezone.utc)
        assert start_time == expected

    def test_timezone_aware_datetime(self):
        """Test that timezone-aware datetimes are handled correctly."""
        end_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        start_time = TimeWindowCalculator.get_period_start(end_time, AggregationPeriod.MINUTE)

        # Verify timezone is preserved
        assert start_time.tzinfo == timezone.utc
