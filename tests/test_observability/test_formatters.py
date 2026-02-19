"""Comprehensive tests for observability formatters module."""
from datetime import datetime, timezone

import pytest

from temper_ai.observability.formatters import (
    format_bytes,
    format_cost,
    format_duration,
    format_percentage,
    format_timestamp,
    format_tokens,
    status_to_color,
    status_to_icon,
    truncate_text,
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
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = format_timestamp(dt)
        assert result == "2024-01-15T10:30:45+00:00"

    def test_format_with_microseconds(self):
        """Test formatting preserves microseconds."""
        dt = datetime(2024, 1, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)
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


class TestFormatPercentage:
    """Test percentage formatting."""

    def test_format_none(self):
        """Test formatting None returns N/A."""
        assert format_percentage(None) == "N/A"

    def test_format_percentages(self):
        """Test formatting various percentages."""
        assert format_percentage(0.0) == "0.0%"
        assert format_percentage(0.5) == "50.0%"
        assert format_percentage(0.856) == "85.6%"
        assert format_percentage(1.0) == "100.0%"

    def test_format_precision(self):
        """Test formatting maintains 1 decimal place."""
        assert format_percentage(0.12345) == "12.3%"
        assert format_percentage(0.99999) == "100.0%"

    def test_format_edge_cases(self):
        """Test edge case values."""
        assert format_percentage(0.001) == "0.1%"
        assert format_percentage(0.999) == "99.9%"


class TestTruncateText:
    """Test text truncation."""

    def test_no_truncation_needed(self):
        """Test short text is not truncated."""
        assert truncate_text("Short", 20) == "Short"
        assert truncate_text("Exactly 20 chars!!!!", 20) == "Exactly 20 chars!!!!"

    def test_truncation_with_default_suffix(self):
        """Test truncation adds default suffix."""
        result = truncate_text("This is a very long text that needs truncation", 20)
        assert result == "This is a very lo..."
        assert len(result) == 20

    def test_truncation_with_custom_suffix(self):
        """Test truncation with custom suffix."""
        result = truncate_text("This is too long", 10, suffix="…")
        assert result == "This is t…"
        assert len(result) == 10

    def test_empty_string(self):
        """Test empty string."""
        assert truncate_text("", 20) == ""

    def test_suffix_longer_than_max_length(self):
        """Test behavior when suffix is longer than max_length."""
        result = truncate_text("Hello", 5, suffix="...")
        assert len(result) == 5  # "He..."

    def test_exact_length(self):
        """Test text exactly at max length."""
        assert truncate_text("12345", 5) == "12345"


class TestFormatBytes:
    """Test byte count formatting."""

    def test_format_none(self):
        """Test formatting None returns N/A."""
        assert format_bytes(None) == "N/A"

    def test_format_bytes_unit(self):
        """Test formatting in bytes."""
        assert format_bytes(0) == "0.0 B"
        assert format_bytes(500) == "500.0 B"
        assert format_bytes(1023) == "1023.0 B"

    def test_format_kilobytes(self):
        """Test formatting in kilobytes."""
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1500) == "1.5 KB"
        assert format_bytes(2048) == "2.0 KB"

    def test_format_megabytes(self):
        """Test formatting in megabytes."""
        assert format_bytes(1048576) == "1.0 MB"  # 1024 * 1024
        assert format_bytes(2500000) == "2.4 MB"
        assert format_bytes(10485760) == "10.0 MB"

    def test_format_gigabytes(self):
        """Test formatting in gigabytes."""
        assert format_bytes(1073741824) == "1.0 GB"  # 1024^3
        assert format_bytes(2147483648) == "2.0 GB"

    def test_format_terabytes(self):
        """Test formatting in terabytes."""
        assert format_bytes(1099511627776) == "1.0 TB"  # 1024^4

    def test_format_precision(self):
        """Test formatting maintains 1 decimal place."""
        assert format_bytes(1536) == "1.5 KB"
        assert format_bytes(1572864) == "1.5 MB"

    def test_format_zero(self):
        """Test formatting zero bytes."""
        assert format_bytes(0) == "0.0 B"


class TestIntegration:
    """Integration tests combining multiple formatters."""

    def test_format_multiple_metrics(self):
        """Test formatting a complete set of metrics."""
        duration = format_duration(125.7)
        tokens = format_tokens(150000)
        cost = format_cost(0.0123)
        percentage = format_percentage(0.856)

        assert duration == "2m 5s"
        assert tokens == "150,000 tokens"
        assert cost == "$0.0123"
        assert percentage == "85.6%"

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
        assert format_percentage(None) == "N/A"
        assert format_bytes(None) == "N/A"
