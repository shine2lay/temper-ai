"""
Base interface for M5 self-improvement strategies.

This module defines the abstract base class for all improvement strategies.
Each strategy implements a specific optimization approach (e.g., prompt tuning,
model selection, temperature adjustment) and can generate configuration variants
to test through experimentation.

Example:
    Creating a concrete strategy:

    >>> class PromptTuningStrategy(ImprovementStrategy):
    ...     @property
    ...     def name(self) -> str:
    ...         return "prompt_tuning"
    ...
    ...     def generate_variants(
    ...         self,
    ...         current_config: AgentConfig,
    ...         patterns: List[LearnedPattern]
    ...     ) -> List[AgentConfig]:
    ...         # Generate 2-4 prompt variations
    ...         variants = []
    ...         for template in self._generate_templates(current_config.prompt):
    ...             config = copy.deepcopy(current_config)
    ...             config.prompt['template'] = template
    ...             variants.append(config)
    ...         return variants
    ...
    ...     def is_applicable(self, problem_type: str) -> bool:
    ...         return problem_type in ["low_quality", "inconsistent_output"]
"""

from abc import ABC, abstractmethod
from typing import List, Dict
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """
    Configuration for an agent.

    This represents the complete configuration that can be modified
    by improvement strategies. Each strategy generates variants of
    this configuration to test different optimization approaches.

    Attributes:
        inference: Model inference settings (model, temperature, max_tokens, etc.)
        prompt: Prompt configuration (template, examples, system message, etc.)
        caching: Caching settings (enabled, ttl, strategy, etc.)
        metadata: Additional strategy-specific configuration
    """

    inference: Dict = field(default_factory=dict)
    prompt: Dict = field(default_factory=dict)
    caching: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)


@dataclass
class LearnedPattern:
    """
    Pattern learned from execution history.

    Represents insights extracted from past agent executions, such as
    common failure modes, performance characteristics, or successful
    configurations. Strategies use these patterns to make informed
    decisions about which variants to generate.

    Attributes:
        pattern_type: Category of pattern (e.g., "slow_response", "hallucination")
        description: Human-readable description of the pattern
        support: Number of times this pattern was observed
        confidence: Reliability score from 0 (unreliable) to 1 (highly reliable)
        evidence: Supporting data (metrics, examples, traces)
    """

    pattern_type: str
    description: str
    support: int
    confidence: float
    evidence: Dict = field(default_factory=dict)

    def __post_init__(self):
        """Validate pattern attributes are in valid ranges."""
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"Confidence must be in range [0.0, 1.0], got {self.confidence}"
            )
        if self.support < 0:
            raise ValueError(f"Support must be non-negative, got {self.support}")
        if not self.pattern_type:
            raise ValueError("pattern_type cannot be empty")


class ImprovementStrategy(ABC):
    """
    Abstract base class for all improvement strategies.

    Each strategy implements a specific optimization technique for improving
    agent performance. Strategies analyze current configuration and learned
    patterns to generate promising configuration variants for experimentation.

    The core workflow:
    1. ImprovementDetector identifies a performance problem
    2. StrategySelector chooses applicable strategies
    3. Each strategy generates 2-4 config variants to test
    4. ExperimentOrchestrator tests variants and selects best
    5. ConfigDeployer applies winning configuration

    Concrete strategies must implement:
    - name: Unique identifier for the strategy
    - generate_variants: Create config variants to test
    - is_applicable: Check if strategy applies to problem type

    Optional override:
    - estimate_impact: Predict expected improvement (for prioritization)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Strategy identifier.

        Returns:
            Unique string identifier (e.g., 'prompt_tuning', 'model_selection')

        Example:
            >>> strategy = PromptTuningStrategy()
            >>> strategy.name
            'prompt_tuning'
        """
        pass

    @abstractmethod
    def generate_variants(
        self, current_config: AgentConfig, patterns: List[LearnedPattern]
    ) -> List[AgentConfig]:
        """
        Generate improved configuration variants to test.

        Based on the current configuration and learned patterns, create
        2-4 promising configuration variants. Each variant should represent
        a distinct optimization hypothesis worth testing.

        Args:
            current_config: Current agent configuration (baseline)
            patterns: Learned patterns from execution history (may be empty for MVP)

        Returns:
            List of 2-4 configuration variants to experiment with. Each variant
            should be a complete AgentConfig with modifications applied.

        Example:
            >>> current = AgentConfig(
            ...     inference={'model': 'gpt-4', 'temperature': 0.7},
            ...     prompt={'template': 'default'}
            ... )
            >>> patterns = [LearnedPattern('slow', 'High latency', 10, 0.9, {})]
            >>> strategy = ModelSelectionStrategy()
            >>> variants = strategy.generate_variants(current, patterns)
            >>> len(variants)
            3
            >>> variants[0].inference['model']
            'gpt-3.5-turbo'  # Faster model variant
        """
        pass

    @abstractmethod
    def is_applicable(self, problem_type: str) -> bool:
        """
        Check if this strategy applies to the detected problem.

        Used by StrategySelector to filter strategies based on the
        specific performance problem detected. Allows strategies to
        opt-in/opt-out based on their area of expertise.

        Args:
            problem_type: Type of problem detected (e.g., 'high_cost',
                         'low_quality', 'slow_response', 'high_error_rate')

        Returns:
            True if this strategy is appropriate for the problem type,
            False otherwise.

        Example:
            >>> strategy = PromptTuningStrategy()
            >>> strategy.is_applicable('low_quality')
            True
            >>> strategy.is_applicable('high_cost')
            False  # Prompt tuning doesn't directly reduce cost
        """
        pass

    def estimate_impact(self, problem: Dict) -> float:
        """
        Estimate expected improvement from this strategy.

        Optional method for strategies to predict their likely impact
        on the given problem. Used for prioritizing strategies when
        multiple are applicable. Default implementation returns 0.1
        (10% improvement).

        Args:
            problem: Problem details including metrics, severity, context

        Returns:
            Estimated improvement from 0 (no impact) to 1 (complete resolution).
            Values typically range 0.1-0.5 for realistic strategies.

        Example:
            >>> problem = {'type': 'high_cost', 'current_cost': 100}
            >>> strategy = ModelSelectionStrategy()
            >>> strategy.estimate_impact(problem)
            0.3  # Expects ~30% cost reduction
        """
        return 0.1
