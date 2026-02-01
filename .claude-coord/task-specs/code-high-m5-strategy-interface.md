# Task Specification: code-high-m5-strategy-interface

## Problem Statement

M5 needs different optimization strategies for different problems (cost reduction, quality improvement, speed optimization). Without a pluggable strategy system, M5 would be limited to one hardcoded approach and unable to adapt to diverse agent needs.

## Acceptance Criteria

- Abstract base class `ImprovementStrategy` with required methods:
  - `name: str` property - strategy identifier
  - `generate_variants(current_config, patterns) -> List[AgentConfig]` - generate config variants
  - `is_applicable(problem_type: str) -> bool` - check if strategy applies to problem
  - `estimate_impact(problem) -> float` - optional, estimate expected improvement (0-1)
- Located in `src/self_improvement/strategies/strategy.py`
- Uses ABC (Abstract Base Class) pattern
- Well-documented with examples
- Type hints for all methods

## Implementation Details

```python
from abc import ABC, abstractmethod
from typing import List, Dict
from dataclasses import dataclass

@dataclass
class AgentConfig:
    """Configuration for an agent."""
    inference: Dict  # model, temperature, max_tokens, etc.
    prompt: Dict  # template, examples, etc.
    caching: Dict  # enabled, etc.
    # ... other config sections

@dataclass
class LearnedPattern:
    """Pattern learned from execution history."""
    pattern_type: str
    description: str
    support: int  # How many times seen
    confidence: float  # How reliable (0-1)
    evidence: Dict

class ImprovementStrategy(ABC):
    """Base class for all improvement strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier (e.g., 'prompt_tuning')."""
        pass

    @abstractmethod
    def generate_variants(
        self,
        current_config: AgentConfig,
        patterns: List[LearnedPattern]
    ) -> List[AgentConfig]:
        """
        Generate improved config variants to test.

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns from PatternLearner (may be empty for MVP)

        Returns:
            List of variant configs to experiment with (2-4 variants)
        """
        pass

    @abstractmethod
    def is_applicable(self, problem_type: str) -> bool:
        """Check if this strategy applies to the detected problem."""
        pass

    def estimate_impact(self, problem: Dict) -> float:
        """Estimate expected improvement (0-1 scale). Default: 0.1"""
        return 0.1
```

## Test Strategy

1. Create mock strategy implementation
2. Verify abstract methods are enforced
3. Verify generate_variants() returns list of configs
4. Verify is_applicable() returns bool
5. Test estimate_impact() has sensible default

## Dependencies

None - foundational interface

## Estimated Effort

1-2 hours (interface definition, documentation)
