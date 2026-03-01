"""Formatting utilities for console visualization."""

from datetime import datetime

from temper_ai.shared.constants.durations import (
    MILLISECONDS_PER_SECOND,
    SECONDS_PER_MINUTE,
)


def format_duration(seconds: float | None) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "150ms", "2.5s", "3m 45s")

    Examples:
        >>> format_duration(0.15)
        '150ms'
        >>> format_duration(2.5)
        '2.5s'
        >>> format_duration(125.7)
        '2m 5s'
        >>> format_duration(None)
        'N/A'
    """
    if seconds is None:
        return "N/A"
    if seconds < 1:
        return f"{int(seconds * MILLISECONDS_PER_SECOND)}ms"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.1f}s"
    minutes = int(seconds // SECONDS_PER_MINUTE)
    secs = int(seconds % SECONDS_PER_MINUTE)
    return f"{minutes}m {secs}s"


def format_timestamp(dt: datetime | None) -> str:
    """Format timestamp in ISO format.

    Args:
        dt: Datetime object

    Returns:
        ISO formatted timestamp string

    Examples:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        >>> format_timestamp(dt)
        '2024-01-15T10:30:45+00:00'
    """
    if dt is None:
        return "N/A"
    return dt.isoformat()


def format_tokens(tokens: int | None) -> str:
    """Format token count with thousands separators.

    Args:
        tokens: Token count

    Returns:
        Formatted token string

    Examples:
        >>> format_tokens(1500)
        '1,500 tokens'
        >>> format_tokens(None)
        'N/A'
    """
    if tokens is None:
        return "N/A"
    return f"{tokens:,} tokens"


def format_cost(cost_usd: float | None) -> str:
    """Format cost in USD.

    Args:
        cost_usd: Cost in USD

    Returns:
        Formatted cost string

    Examples:
        >>> format_cost(0.0123)
        '$0.0123'
        >>> format_cost(1.5)
        '$1.5000'
        >>> format_cost(None)
        '$0.0000'
    """
    if cost_usd is None:
        return "$0.0000"
    return f"${cost_usd:.4f}"


def status_to_color(status: str) -> str:
    """Map status to Rich color name.

    Args:
        status: Status string

    Returns:
        Rich color name

    Examples:
        >>> status_to_color("success")
        'green'
        >>> status_to_color("failed")
        'red'
        >>> status_to_color("running")
        'yellow'
    """
    color_map = {
        "success": "green",
        "completed": "green",
        "failed": "red",
        "running": "yellow",
        "timeout": "red",
        "dry_run": "blue",
        "halted": "yellow",
    }
    return color_map.get(status, "white")


def status_to_icon(status: str) -> str:
    """Map status to unicode icon.

    Args:
        status: Status string

    Returns:
        Unicode icon character

    Examples:
        >>> status_to_icon("success")
        '✓'
        >>> status_to_icon("failed")
        '✗'
        >>> status_to_icon("running")
        '⏳'
    """
    icon_map = {
        "success": "✓",
        "completed": "✓",
        "failed": "✗",
        "running": "⏳",
        "timeout": "⌛",
        "dry_run": "⏸",
        "halted": "⏸",
    }
    return icon_map.get(status, "?")
