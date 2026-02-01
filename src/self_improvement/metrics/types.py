"""Type definitions for the M5 metric collection system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class MetricType(Enum):
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
    metric_name: str
    value: float
    metric_type: MetricType
    collected_at: datetime
    collector_version: str = "1.0"
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self):
        """Validate metric value is in valid range."""
        if not (0.0 <= self.value <= 1.0):
            raise ValueError(
                f"Metric value must be in range [0.0, 1.0], got {self.value}"
            )
