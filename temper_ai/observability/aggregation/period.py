"""Time period definitions for metric aggregation."""

from enum import StrEnum


class AggregationPeriod(StrEnum):
    """Time periods for metric aggregation."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
