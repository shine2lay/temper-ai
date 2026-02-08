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
    ...         current_config: SIOptimizationConfig,
    ...         patterns: List[LearnedPattern]
    ...     ) -> List[SIOptimizationConfig]:
    ...         # Generate 2-4 prompt variations
    ...         variants = []
    ...         for template in self._generate_templates(current_config.prompt):
    ...             config = copy.deepcopy(current_config)
    ...             config.prompt['template'] = template
    ...             variants.append(config)
    ...         return variants
    ...
    ...     def is_applicable(self, problem_type: str) -> bool:
    ...         return problem_type in ["quality_low", "inconsistent_output"]
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List

from src.constants.durations import DAYS_90
from src.constants.limits import DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS
from src.constants.probabilities import PROB_VERY_HIGH
from src.self_improvement.data_models import SIOptimizationConfig


@dataclass
class LearnedPattern:
    """
    Pattern learned from execution history.

    Represents insights extracted from past agent executions, such as
    common failure modes, performance characteristics, or successful
    configurations. Strategies use these patterns to make informed
    decisions about which variants to generate.

    Attributes:
        pattern_type: Category of pattern (e.g., "speed_low", "hallucination")
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

    Strategies can learn from past outcomes to refine their impact estimates
    over time through the optional learning_store parameter.

    The core workflow:
    1. ImprovementDetector identifies a performance problem
    2. StrategySelector chooses applicable strategies
    3. Each strategy generates 2-4 config variants to test
    4. ExperimentOrchestrator tests variants and selects best
    5. ConfigDeployer applies winning configuration
    6. StrategyLearningStore records outcome for future learning

    Concrete strategies must implement:
    - name: Unique identifier for the strategy
    - generate_variants: Create config variants to test
    - is_applicable: Check if strategy applies to problem type

    Optional override:
    - estimate_impact: Predict expected improvement (for prioritization)
      Default implementation queries learning_store if available
    """

    def __init__(self, learning_store=None):
        """
        Initialize strategy with optional learning store.

        Args:
            learning_store: Optional StrategyLearningStore for querying historical outcomes
        """
        self.learning_store = learning_store

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
        self, current_config: SIOptimizationConfig, patterns: List[LearnedPattern]
    ) -> List[SIOptimizationConfig]:
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
            should be a complete SIOptimizationConfig with modifications applied.

        Example:
            >>> current = SIOptimizationConfig(
            ...     agent_name='test',
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
            problem_type: Type of problem detected (e.g., 'quality_low',
                         'cost_high', 'speed_low', 'error_rate_high')

        Returns:
            True if this strategy is appropriate for the problem type,
            False otherwise.

        Example:
            >>> strategy = PromptTuningStrategy()
            >>> strategy.is_applicable('quality_low')
            True
            >>> strategy.is_applicable('cost_high')
            False  # Prompt tuning doesn't directly reduce cost
        """
        pass

    def estimate_impact(self, problem: Dict) -> float:
        """
        Estimate expected improvement from this strategy.

        Optional method for strategies to predict their likely impact
        on the given problem. Used for prioritizing strategies when
        multiple are applicable.

        Default implementation:
        1. If learning_store available: Query historical outcomes and use
           Bayesian updating to combine historical average with base estimate
        2. Otherwise: Return base estimate (0.1 = 10% improvement)

        Concrete strategies can override this to provide custom estimates
        or call super().estimate_impact(problem) to get learned estimate
        and then adjust based on strategy-specific logic.

        Args:
            problem: Problem details including:
                - type or problem_type: Problem category (quality_low, cost_high, etc.)
                - metrics: Current performance metrics
                - severity: Problem severity
                - context: Additional context

        Returns:
            Estimated improvement from 0 (no impact) to 1 (complete resolution).
            Values typically range 0.1-0.5 for realistic strategies.

        Example:
            >>> problem = {'type': 'cost_high', 'current_cost': 100}
            >>> strategy = ModelSelectionStrategy(learning_store)
            >>> strategy.estimate_impact(problem)
            0.35  # Learned from historical outcomes
        """
        # Base estimate (prior belief)
        base_estimate = 0.1

        # If no learning store, return base estimate
        if not self.learning_store:
            return base_estimate

        # Get problem type
        problem_type = problem.get("problem_type", problem.get("type", "unknown"))

        # Query historical outcomes
        avg_improvement = self.learning_store.get_average_improvement(
            strategy_name=self.name,
            problem_type=problem_type,
            metric="composite_score",
            min_confidence=PROB_VERY_HIGH,
            days_back=DAYS_90
        )

        # If no historical data, return base estimate
        if avg_improvement is None:
            return base_estimate

        # Get sample count for confidence weighting
        sample_count = self.learning_store.get_sample_count(
            strategy_name=self.name,
            problem_type=problem_type,
            days_back=DAYS_90
        )

        # Bayesian updating: weight historical average by sample size
        # More samples = more confidence in historical average
        # Fewer samples = more reliance on prior (base estimate)
        #
        # Formula: weighted_estimate = (prior * prior_weight + data * data_weight) / (prior_weight + data_weight)
        # where prior_weight is fixed at 10, and data_weight is sample_count
        #
        # This means we need ~10 samples before historical data dominates the estimate
        prior_weight = float(DEFAULT_MAX_ITEMS)
        data_weight = float(sample_count)

        weighted_estimate = (
            (base_estimate * prior_weight + avg_improvement * data_weight) /
            (prior_weight + data_weight)
        )

        return weighted_estimate
