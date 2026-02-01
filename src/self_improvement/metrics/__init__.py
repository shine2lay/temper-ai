"""M5 Metric Collection System.

This module provides an extensible framework for collecting metrics from
agent executions. It supports automatic, derived, and custom metrics through
a plugin architecture.

Key Components:
    - MetricCollector: Abstract base class for all metric collectors
    - MetricRegistry: Central registry for managing collectors
    - MetricType: Enum classifying metric collection methods
    - MetricValue: Dataclass representing collected metric values

Example Usage:
    >>> from src.self_improvement.metrics import MetricRegistry, MetricCollector
    >>>
    >>> # Define a custom collector
    >>> class MyCollector(MetricCollector):
    ...     @property
    ...     def metric_name(self) -> str:
    ...         return "my_metric"
    ...
    ...     @property
    ...     def metric_type(self) -> MetricType:
    ...         return MetricType.CUSTOM
    ...
    ...     def collect(self, execution) -> Optional[float]:
    ...         # Compute metric...
    ...         return 0.85
    ...
    ...     def is_applicable(self, execution) -> bool:
    ...         return True
    >>>
    >>> # Register and use
    >>> registry = MetricRegistry()
    >>> registry.register(MyCollector())
    >>> metrics = registry.collect_all(execution)
"""

from src.self_improvement.metrics.collector import (
    MetricCollector,
    MetricRegistry,
    ExecutionProtocol,
)
from src.self_improvement.metrics.types import MetricType, MetricValue

__all__ = [
    "MetricCollector",
    "MetricRegistry",
    "ExecutionProtocol",
    "MetricType",
    "MetricValue",
]
