"""
OllamaModelSelectionStrategy for M5 self-improvement system.

Generates config variants by selecting different Ollama models based on
the detected performance problem (quality, cost, speed).
"""
import copy
from typing import List

from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    AgentConfig,
    LearnedPattern,
)
from src.self_improvement.model_registry import ModelRegistry, ModelMetadata


class OllamaModelSelectionStrategy(ImprovementStrategy):
    """
    Strategy that optimizes agent performance by selecting different Ollama models.

    This strategy generates config variants by substituting different Ollama
    models based on the performance problem:
    - low_quality: Try larger, higher-quality models
    - high_cost: Try smaller, faster models (cost proxy: model size)
    - slow_response: Try faster models

    Uses ModelRegistry to discover available models and their characteristics.

    Example:
        >>> registry = ModelRegistry()
        >>> strategy = OllamaModelSelectionStrategy(registry)
        >>> current = AgentConfig(inference={'model': 'phi3:mini'})
        >>> patterns = []
        >>> variants = strategy.generate_variants(current, patterns)
        >>> len(variants)
        3
        >>> # Variants use different models: llama3.1:8b, mistral:7b, qwen2.5:32b
    """

    def __init__(self, model_registry: ModelRegistry):
        """
        Initialize strategy with model registry.

        Args:
            model_registry: Registry of available models
        """
        self._registry = model_registry

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "ollama_model_selection"

    def generate_variants(
        self, current_config: AgentConfig, patterns: List[LearnedPattern]
    ) -> List[AgentConfig]:
        """
        Generate config variants with different Ollama models.

        Selects 2-4 alternative models based on current model and patterns.
        If no patterns provided, generates balanced variants across size tiers.

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns (used to infer problem type if available)

        Returns:
            List of 2-4 config variants with different models
        """
        # Get current model (default to phi3:mini if not set)
        current_model_name = current_config.inference.get("model", "phi3:mini")

        # Infer problem type from patterns (if available)
        problem_type = self._infer_problem_type(patterns)

        # Get candidate models based on problem type
        candidates = self._select_candidate_models(current_model_name, problem_type)

        # Generate variants (2-4 models)
        variants = []
        for model in candidates[:4]:  # Limit to 4 variants
            variant = copy.deepcopy(current_config)
            variant.inference["model"] = model.name
            variant.metadata["strategy"] = self.name
            variant.metadata["model_size"] = model.size
            variant.metadata["expected_quality"] = model.expected_quality
            variant.metadata["expected_speed"] = model.expected_speed
            variants.append(variant)

        return variants

    def is_applicable(self, problem_type: str) -> bool:
        """
        Check if this strategy applies to the problem.

        Model selection is applicable to:
        - low_quality: Try higher-quality models
        - high_cost: Try smaller/faster models
        - slow_response: Try faster models

        Args:
            problem_type: Type of problem detected

        Returns:
            True if strategy can help with this problem type
        """
        applicable_types = {
            "low_quality",
            "high_cost",
            "slow_response",
            "high_error_rate",  # May benefit from better models
        }
        return problem_type in applicable_types

    def estimate_impact(self, problem: dict) -> float:
        """
        Estimate expected improvement from model selection.

        Args:
            problem: Problem details including type and metrics

        Returns:
            Estimated improvement (0.0-1.0)
        """
        problem_type = problem.get("type", "unknown")

        # Model selection has high impact on quality and moderate on speed/cost
        impact_by_type = {
            "low_quality": 0.4,  # 40% quality improvement expected
            "slow_response": 0.3,  # 30% speed improvement
            "high_cost": 0.3,  # 30% cost reduction
            "high_error_rate": 0.25,  # 25% error reduction
        }

        return impact_by_type.get(problem_type, 0.1)

    def _infer_problem_type(self, patterns: List[LearnedPattern]) -> str:
        """
        Infer problem type from learned patterns.

        Args:
            patterns: Learned patterns from execution history

        Returns:
            Inferred problem type (or "balanced" if unclear)
        """
        if not patterns:
            return "balanced"

        # Map pattern types to problem types
        for pattern in patterns:
            if "quality" in pattern.pattern_type.lower():
                return "low_quality"
            elif "cost" in pattern.pattern_type.lower():
                return "high_cost"
            elif "slow" in pattern.pattern_type.lower() or "latency" in pattern.pattern_type.lower():
                return "slow_response"
            elif "error" in pattern.pattern_type.lower():
                return "high_error_rate"

        return "balanced"

    def _select_candidate_models(
        self, current_model: str, problem_type: str
    ) -> List[ModelMetadata]:
        """
        Select candidate models based on problem type.

        Args:
            current_model: Current model name
            problem_type: Type of problem to address

        Returns:
            List of 2-4 candidate models to try
        """
        all_models = self._registry.get_by_provider("ollama")

        # Remove current model from candidates
        candidates = [m for m in all_models if m.name != current_model]

        if problem_type == "low_quality":
            # Prioritize higher quality models
            candidates.sort(
                key=lambda m: self._quality_score(m),
                reverse=True
            )
        elif problem_type == "high_cost" or problem_type == "slow_response":
            # Prioritize faster/smaller models
            candidates.sort(
                key=lambda m: self._speed_score(m),
                reverse=True
            )
        else:
            # Balanced: mix of different sizes
            # Keep original order (diverse mix)
            pass

        # Return 2-4 candidates
        return candidates[:4] if len(candidates) >= 4 else candidates

    def _quality_score(self, model: ModelMetadata) -> int:
        """
        Score model quality for sorting.

        Args:
            model: Model metadata

        Returns:
            Quality score (higher is better)
        """
        quality_map = {
            "highest": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
        }
        return quality_map.get(model.expected_quality, 0)

    def _speed_score(self, model: ModelMetadata) -> int:
        """
        Score model speed for sorting.

        Args:
            model: Model metadata

        Returns:
            Speed score (higher is faster)
        """
        speed_map = {
            "very_fast": 4,
            "fast": 3,
            "medium": 2,
            "slow": 1,
        }
        return speed_map.get(model.expected_speed, 0)
