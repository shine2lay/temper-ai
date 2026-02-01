# Task Specification: code-high-m5-metric-collector-interface

## Problem Statement

M5 needs to measure different quality metrics for different types of agents (extraction accuracy, code quality, factual accuracy, etc.). Without a pluggable metric system, M5 would be locked to hardcoded metrics and unable to adapt to new agent types.

## Acceptance Criteria

- Abstract base class `MetricCollector` with required methods:
  - `metric_name: str` property - unique identifier
  - `metric_type: str` property - "automatic", "derived", "custom"
  - `collect(execution: AgentExecution) -> Optional[float]` - extract metric value (0-1 scale)
  - `is_applicable(execution: AgentExecution) -> bool` - check if metric applies
- Located in `src/self_improvement/metrics/collector.py`
- Uses ABC (Abstract Base Class) pattern for enforcement
- Well-documented with docstrings and examples
- Type hints for all methods

## Implementation Details

```python
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

@dataclass
class AgentExecution:
    """Placeholder - may already exist in M1"""
    id: str
    agent_name: str
    status: str
    output: any
    input_data: dict
    # ... other fields

class MetricCollector(ABC):
    """Base class for all metric collectors."""

    @property
    @abstractmethod
    def metric_name(self) -> str:
        """Unique metric identifier (e.g., 'quality_score')."""
        pass

    @property
    @abstractmethod
    def metric_type(self) -> str:
        """Type: 'automatic', 'derived', 'custom'."""
        pass

    @abstractmethod
    def collect(self, execution: AgentExecution) -> Optional[float]:
        """
        Extract metric value from execution.
        Returns float (0-1) if available, None otherwise.
        """
        pass

    @abstractmethod
    def is_applicable(self, execution: AgentExecution) -> bool:
        """Check if this metric applies to this execution."""
        pass
```

## Test Strategy

1. Create mock collector implementation
2. Verify abstract methods are enforced (can't instantiate without implementing)
3. Verify collect() returns float or None
4. Verify is_applicable() returns bool
5. Test with mock AgentExecution objects

## Dependencies

None - this is a foundational interface

## Estimated Effort

1-2 hours (simple interface definition)
