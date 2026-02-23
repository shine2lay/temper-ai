"""Backward compatibility shim for metric aggregation.

DEPRECATED: Import from temper_ai.observability.aggregation package instead.
This file maintained for backward compatibility only.
"""

import warnings

from temper_ai.observability.aggregation.aggregator import AggregationOrchestrator
from temper_ai.observability.aggregation.period import AggregationPeriod

warnings.warn(
    "Importing from temper_ai.observability.aggregation.py is deprecated. "
    "Use 'from temper_ai.observability.aggregation import AggregationOrchestrator' instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["AggregationOrchestrator", "AggregationPeriod"]
