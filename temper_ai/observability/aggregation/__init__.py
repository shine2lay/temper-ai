"""Metric aggregation pipeline for observability.

Aggregates raw execution data into SystemMetric records for trend analysis,
dashboards, and SLO monitoring.
"""

from temper_ai.observability.aggregation.aggregator import AggregationOrchestrator
from temper_ai.observability.aggregation.period import AggregationPeriod

# Public API
__all__ = [
    "AggregationOrchestrator",
    "AggregationPeriod",
]
