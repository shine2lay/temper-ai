"""Backward compatibility shim for metric aggregation.

DEPRECATED: Import from src.observability.aggregation package instead.
This file maintained for backward compatibility only.
"""
import warnings

from src.observability.aggregation.aggregator import MetricAggregator
from src.observability.aggregation.period import AggregationPeriod

warnings.warn(
    "Importing from src.observability.aggregation.py is deprecated. "
    "Use 'from src.observability.aggregation import MetricAggregator' instead.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = ["MetricAggregator", "AggregationPeriod"]
