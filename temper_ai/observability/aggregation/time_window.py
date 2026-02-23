"""Time window calculations for metric aggregation periods."""

from datetime import UTC, datetime, timedelta
from typing import assert_never

from temper_ai.observability.aggregation.period import AggregationPeriod


class TimeWindowCalculator:
    """Calculates time windows for metric aggregation periods."""

    @staticmethod
    def get_period_start(end_time: datetime, period: AggregationPeriod) -> datetime:
        """Calculate period start time from end time.

        Args:
            end_time: End of period
            period: Aggregation period (MINUTE, HOUR, DAY)

        Returns:
            Start of period (end_time - period duration)

        Example:
            >>> end = datetime(2024, 1, 1, 14, 30)
            >>> TimeWindowCalculator.get_period_start(end, AggregationPeriod.HOUR)
            datetime(2024, 1, 1, 13, 30)
        """
        if period == AggregationPeriod.MINUTE:
            return end_time - timedelta(minutes=1)
        elif period == AggregationPeriod.HOUR:
            return end_time - timedelta(hours=1)
        elif period == AggregationPeriod.DAY:
            return end_time - timedelta(days=1)
        else:
            # Exhaustive check - all enum values handled above
            assert_never(period)

    @staticmethod
    def get_default_time_window(
        period: AggregationPeriod, end_time: datetime | None = None
    ) -> tuple[datetime, datetime]:
        """Get default time window for aggregation period.

        Args:
            period: Aggregation period
            end_time: Optional end time (default: now)

        Returns:
            Tuple of (start_time, end_time)
        """
        if end_time is None:
            end_time = datetime.now(UTC)

        start_time = TimeWindowCalculator.get_period_start(end_time, period)
        return start_time, end_time
