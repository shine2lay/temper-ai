"""
Prompt Optimization Strategy for M5 self-improvement system.

Generates configuration variants that vary system prompts, few-shot examples,
and reasoning guides to improve LLM output quality.
"""
import copy
from typing import Dict, List

from src.constants.limits import MULTIPLIER_SMALL, SMALL_ITEM_LIMIT
from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    LearnedPattern,
    SIOptimizationConfig,
)

# Expected impact estimates by problem type
IMPACT_QUALITY_LOW = 0.40  # High impact on quality issues
IMPACT_ERROR_RATE_HIGH = 0.30  # Moderate impact on error rates
IMPACT_INCONSISTENT_OUTPUT = 0.35  # Good impact on consistency
IMPACT_HALLUCINATION = 0.45  # Very high impact on hallucination
IMPACT_INCORRECT_OUTPUT = 0.35  # Good impact on correctness
IMPACT_DEFAULT = 0.15  # Default impact for unknown problem types


class PromptOptimizationStrategy(ImprovementStrategy):
    """
    Strategy that optimizes agent performance by varying prompt components.

    Applicable when output quality is low, error rate is high, or consistency
    is poor. Generates variants that modify:
    1. System prompt clarity and specificity
    2. Few-shot examples (add, remove, reorder)
    3. Reasoning guides (chain-of-thought, step-by-step)

    Example:
        >>> strategy = PromptOptimizationStrategy()
        >>> current = SIOptimizationConfig(
        ...     prompt={'system': 'You are a helpful assistant', 'inline': ''}
        ... )
        >>> variants = strategy.generate_variants(current, [])
        >>> len(variants)
        3
    """

    # Chain-of-thought reasoning guide
    COT_GUIDE = """
Before providing your answer, think through the problem step-by-step:
1. What is being asked?
2. What information do I have?
3. What steps are needed to solve this?
4. What is my reasoning?
5. What is my final answer?

Let's work through this carefully:
"""

    # Specificity enhancement template
    SPECIFICITY_GUIDE = """
When responding:
- Be precise and specific
- Cite relevant details from context
- Avoid vague or generic statements
- Use concrete examples when applicable
- Structure your response clearly
"""

    # Output format guide
    FORMAT_GUIDE = """
Structure your response as follows:
1. Brief summary of the task
2. Detailed analysis or steps
3. Final result or conclusion
4. Any caveats or limitations
"""

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "prompt_optimization"

    def generate_variants(
        self, current_config: SIOptimizationConfig, patterns: List[LearnedPattern]
    ) -> List[SIOptimizationConfig]:
        """Generate improved configuration variants.

        Generates up to 4 variants:
        1. Add chain-of-thought reasoning guide
        2. Enhance system prompt with specificity guide
        3. Add structured output format guide
        4. Combined: specificity + format (if both not present)

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns (used to prioritize variants)

        Returns:
            List of 2-4 configuration variants
        """
        variants = []
        current_system = current_config.prompt.get("system", "")
        current_inline = current_config.prompt.get("inline", "")

        # Variant 1: Add chain-of-thought reasoning guide
        if self.COT_GUIDE not in current_inline:
            variant_cot = copy.deepcopy(current_config)
            variant_cot.prompt["inline"] = current_inline + "\n\n" + self.COT_GUIDE
            variant_cot.extra_metadata["strategy"] = self.name
            variant_cot.extra_metadata["variant_type"] = "chain_of_thought"
            variant_cot.extra_metadata["change"] = "Added chain-of-thought reasoning guide"
            variants.append(variant_cot)

        # Variant 2: Enhance system prompt with specificity guide
        if self.SPECIFICITY_GUIDE not in current_system:
            variant_specificity = copy.deepcopy(current_config)
            variant_specificity.prompt["system"] = (
                current_system + "\n\n" + self.SPECIFICITY_GUIDE
            )
            variant_specificity.extra_metadata["strategy"] = self.name
            variant_specificity.extra_metadata["variant_type"] = "specificity"
            variant_specificity.extra_metadata["change"] = (
                "Enhanced system prompt with specificity guide"
            )
            variants.append(variant_specificity)

        # Variant 3: Add structured output format guide
        if self.FORMAT_GUIDE not in current_inline:
            variant_format = copy.deepcopy(current_config)
            variant_format.prompt["inline"] = current_inline + "\n\n" + self.FORMAT_GUIDE
            variant_format.extra_metadata["strategy"] = self.name
            variant_format.extra_metadata["variant_type"] = "output_format"
            variant_format.extra_metadata["change"] = "Added structured output format guide"
            variants.append(variant_format)

        # Variant 4: Combined approach (specificity + format)
        # Only add if we generated at least one other variant
        if (
            len(variants) >= MULTIPLIER_SMALL
            and self.SPECIFICITY_GUIDE not in current_system
            and self.FORMAT_GUIDE not in current_inline
        ):
            variant_combined = copy.deepcopy(current_config)
            variant_combined.prompt["system"] = (
                current_system + "\n\n" + self.SPECIFICITY_GUIDE
            )
            variant_combined.prompt["inline"] = (
                current_inline + "\n\n" + self.FORMAT_GUIDE
            )
            variant_combined.extra_metadata["strategy"] = self.name
            variant_combined.extra_metadata["variant_type"] = "combined"
            variant_combined.extra_metadata["change"] = (
                "Enhanced system prompt and added output format guide"
            )
            variants.append(variant_combined)

        return variants[:SMALL_ITEM_LIMIT - 1]  # Limit to 4 variants max

    def is_applicable(self, problem_type: str) -> bool:
        """Check if strategy applies to the problem.

        Applicable for:
        - quality_low: Poor output quality
        - error_rate_high: Many failures or incorrect outputs
        - inconsistent_output: LLM produces different results
        - hallucination: LLM invents information

        Args:
            problem_type: Type of problem detected

        Returns:
            True if strategy can help
        """
        applicable_types = {
            "quality_low",
            "error_rate_high",
            "inconsistent_output",
            "hallucination",
            "incorrect_output",
        }
        return problem_type in applicable_types

    def estimate_impact(self, problem: Dict) -> float:
        """Estimate expected improvement.

        Uses historical outcomes from learning_store if available,
        otherwise falls back to problem-type-specific estimates.

        Args:
            problem: Problem details

        Returns:
            Estimated improvement (0.0-1.0)
        """
        # If learning store available, use learned estimate
        if self.learning_store:
            # Call parent's learned estimate (uses Bayesian updating)
            return super().estimate_impact(problem)

        # Fallback: Problem-type-specific estimates (used as priors if no data)
        problem_type = problem.get("problem_type", problem.get("type", "unknown"))

        impact_by_type = {
            "quality_low": IMPACT_QUALITY_LOW,
            "error_rate_high": IMPACT_ERROR_RATE_HIGH,
            "inconsistent_output": IMPACT_INCONSISTENT_OUTPUT,
            "hallucination": IMPACT_HALLUCINATION,
            "incorrect_output": IMPACT_INCORRECT_OUTPUT,
        }

        return impact_by_type.get(problem_type, IMPACT_DEFAULT)
