"""M5 Metric Collection System.

This module provides an extensible framework for collecting metrics from
agent executions. It supports automatic, derived, and custom metrics through
a plugin architecture.

Key Components:
    - MetricCollector: Abstract base class for all metric collectors
    - MetricRegistry: Central registry for managing collectors
    - SIMetricType: Enum classifying metric collection methods
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
    ...     def metric_type(self) -> SIMetricType:
    ...         return SIMetricType.CUSTOM
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
    ExecutionProtocol,
    MetricCollector,
    MetricRegistry,
)
from src.self_improvement.metrics.erc721_quality import (
    ERC721QualityCollector,
    ERC721QualityScore,
    score_erc721_workflow,
)
from src.self_improvement.metrics.extraction_quality import (
    ExtractionQualityCollector,
)
from src.self_improvement.metrics.types import MetricValue, SIMetricType

__all__ = [
    "MetricCollector",
    "MetricRegistry",
    "ExecutionProtocol",
    "SIMetricType",
    "MetricValue",
    "ExtractionQualityCollector",
    "ERC721QualityCollector",
    "ERC721QualityScore",
    "score_erc721_workflow",
]
