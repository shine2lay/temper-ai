"""Metric aggregation pipeline for observability.

Aggregates raw execution data into SystemMetric records for trend analysis,
dashboards, and SLO monitoring.
"""
from src.observability.aggregation.aggregator import AggregationOrchestrator
from src.observability.aggregation.period import AggregationPeriod

# Public API
__all__ = [
    "AggregationOrchestrator",
    "AggregationPeriod",
]
