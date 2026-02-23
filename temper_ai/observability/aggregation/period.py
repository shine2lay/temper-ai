"""Time period definitions for metric aggregation."""

from enum import Enum


class AggregationPeriod(str, Enum):
    """Time periods for metric aggregation."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
