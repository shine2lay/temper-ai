"""Type definitions for the M5 metric collection system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SIMetricType(Enum):
    """Classification of metric collection methods.

    Attributes:
        AUTOMATIC: Metrics extracted directly from AgentExecution metadata
                   (e.g., cost, duration, token count)
        DERIVED: Metrics computed from execution logs, traces, or tool outputs
                 (e.g., retry count, tool usage patterns)
        CUSTOM: Metrics with user-defined computation logic
                (e.g., LLM-as-judge quality scores, static analysis)
    """
    AUTOMATIC = "automatic"
    DERIVED = "derived"
    CUSTOM = "custom"


@dataclass
class MetricValue:
    """Internal representation of a collected metric.

    This dataclass is used internally by the metric collection system to
    represent computed metric values before they are stored in the database.

    Attributes:
        metric_name: Unique identifier for the metric (e.g., 'extraction_quality')
        value: Normalized metric value in range [0.0, 1.0]
               0.0 = worst possible value
               1.0 = best possible value
        metric_type: Classification of how the metric is computed
        collected_at: Timestamp when the metric was computed
        collector_version: Version string of the collector implementation
        metadata: Optional additional context about the metric computation
    """
    METRIC_MIN = 0.0
    METRIC_MAX = 1.0
    DEFAULT_VERSION = "1.0"

    metric_name: str
    value: float
    metric_type: SIMetricType
    collected_at: datetime
    collector_version: str = DEFAULT_VERSION
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        """Validate metric value is in valid range."""
        if not (self.METRIC_MIN <= self.value <= self.METRIC_MAX):
            raise ValueError(
                f"Metric value must be in range [{self.METRIC_MIN}, {self.METRIC_MAX}], got {self.value}"
            )
