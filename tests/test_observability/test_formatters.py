"""Comprehensive tests for observability formatters module."""

from datetime import UTC, datetime

from temper_ai.observability.formatters import (
    format_cost,
    format_duration,
    format_timestamp,
    format_tokens,
    status_to_color,
    status_to_icon,
)


class TestFormatDuration:
    """Test duration formatting."""

    def test_format_none(self):
        """Test formatting None returns N/A."""
        assert format_duration(None) == "N/A"

    def test_format_milliseconds(self):
        """Test formatting sub-second durations."""
        assert format_duration(0.15) == "150ms"
        assert format_duration(0.001) == "1ms"
        assert format_duration(0.999) == "999ms"

    def test_format_seconds(self):
        """Test formatting durations in seconds."""
        assert format_duration(1.0) == "1.0s"
        assert format_duration(2.5) == "2.5s"
        assert format_duration(59.9) == "59.9s"

    def test_format_minutes(self):
        """Test formatting durations in minutes."""
        assert format_duration(60.0) == "1m 0s"
        assert format_duration(125.7) == "2m 5s"
        assert format_duration(3665.0) == "61m 5s"

    def test_format_zero(self):
        """Test formatting zero duration."""
        assert format_duration(0.0) == "0ms"

    def test_format_boundary_cases(self):
        """Test boundary cases between units."""
        assert format_duration(0.9999) == "999ms"
        assert format_duration(1.0) == "1.0s"
        assert format_duration(59.999) == "60.0s"
        assert format_duration(60.0) == "1m 0s"


class TestFormatTimestamp:
    """Test timestamp formatting."""

    def test_format_none(self):
        """Test formatting None returns N/A."""
        assert format_timestamp(None) == "N/A"

    def test_format_utc_timestamp(self):
        """Test formatting UTC timestamp."""
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC)
        result = format_timestamp(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_format_with_microseconds(self):
        """Test formatting preserves microseconds."""
        dt = datetime(2024, 1, 15, 10, 30, 45, 123456, tzinfo=UTC)
        result = format_timestamp(dt)
        assert "2024-01-15T10:30:45" in result


class TestFormatTokens:
    """Test token count formatting."""

    def test_format_none(self):
        """Test formatting None returns N/A."""
        assert format_tokens(None) == "N/A"

    def test_format_small_count(self):
        """Test formatting small token counts."""
        assert format_tokens(100) == "100 tokens"
        assert format_tokens(999) == "999 tokens"

    def test_format_with_thousands_separator(self):
        """Test formatting with thousands separators."""
        assert format_tokens(1000) == "1,000 tokens"
        assert format_tokens(1500) == "1,500 tokens"
        assert format_tokens(1000000) == "1,000,000 tokens"

    def test_format_zero(self):
        """Test formatting zero tokens."""
        assert format_tokens(0) == "0 tokens"


class TestFormatCost:
    """Test cost formatting."""

    def test_format_none(self):
        """Test formatting None returns $0.0000."""
        assert format_cost(None) == "$0.0000"

    def test_format_small_cost(self):
        """Test formatting small costs."""
        assert format_cost(0.0123) == "$0.0123"
        assert format_cost(0.0001) == "$0.0001"

    def test_format_large_cost(self):
        """Test formatting large costs."""
        assert format_cost(1.5) == "$1.5000"
        assert format_cost(10.25) == "$10.2500"
        assert format_cost(100.0) == "$100.0000"

    def test_format_zero(self):
        """Test formatting zero cost."""
        assert format_cost(0.0) == "$0.0000"

    def test_format_precision(self):
        """Test formatting maintains 4 decimal places."""
        assert format_cost(1.23456) == "$1.2346"  # Rounded
        assert format_cost(1.0) == "$1.0000"


class TestStatusToColor:
    """Test status to color mapping."""

    def test_success_colors(self):
        """Test success/completed statuses."""
        assert status_to_color("success") == "green"
        assert status_to_color("completed") == "green"

    def test_failure_colors(self):
        """Test failure statuses."""
        assert status_to_color("failed") == "red"
        assert status_to_color("timeout") == "red"

    def test_running_color(self):
        """Test running status."""
        assert status_to_color("running") == "yellow"

    def test_halted_color(self):
        """Test halted status."""
        assert status_to_color("halted") == "yellow"

    def test_dry_run_color(self):
        """Test dry_run status."""
        assert status_to_color("dry_run") == "blue"

    def test_unknown_status(self):
        """Test unknown status returns default."""
        assert status_to_color("unknown") == "white"
        assert status_to_color("invalid") == "white"


class TestStatusToIcon:
    """Test status to icon mapping."""

    def test_success_icons(self):
        """Test success/completed icons."""
        assert status_to_icon("success") == "✓"
        assert status_to_icon("completed") == "✓"

    def test_failure_icons(self):
        """Test failure icons."""
        assert status_to_icon("failed") == "✗"

    def test_timeout_icon(self):
        """Test timeout icon."""
        assert status_to_icon("timeout") == "⌛"

    def test_running_icon(self):
        """Test running icon."""
        assert status_to_icon("running") == "⏳"

    def test_paused_icons(self):
        """Test paused/halted icons."""
        assert status_to_icon("dry_run") == "⏸"
        assert status_to_icon("halted") == "⏸"

    def test_unknown_status(self):
        """Test unknown status returns default."""
        assert status_to_icon("unknown") == "?"
        assert status_to_icon("invalid") == "?"


class TestIntegration:
    """Integration tests combining multiple formatters."""

    def test_format_multiple_metrics(self):
        """Test formatting a complete set of metrics."""
        duration = format_duration(125.7)
        tokens = format_tokens(150000)
        cost = format_cost(0.0123)

        assert duration == "2m 5s"
        assert tokens == "150,000 tokens"
        assert cost == "$0.0123"

    def test_status_formatting(self):
        """Test status color and icon together."""
        status = "success"
        color = status_to_color(status)
        icon = status_to_icon(status)

        assert color == "green"
        assert icon == "✓"

    def test_all_formatters_handle_none(self):
        """Test all formatters gracefully handle None."""
        assert format_duration(None) == "N/A"
        assert format_timestamp(None) == "N/A"
        assert format_tokens(None) == "N/A"
        assert format_cost(None) == "$0.0000"
