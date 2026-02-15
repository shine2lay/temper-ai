"""
ERC721 Workflow Improvement Strategy for M5 self-improvement system.

Generates configuration variants for improving ERC721 code generation:
- Variant 1: Lower temperature for more deterministic output
- Variant 2: Different model (codellama vs llama3)
- Variant 3: Enhanced prompts with inline Solidity examples
"""
import copy
from typing import Dict, List

from src.shared.constants.probabilities import FRACTION_HALF, PROB_MINIMAL
from src.self_improvement.constants import (
    PROMPT_LOCATION_INLINE,
    STRATEGY_CHANGE,
    STRATEGY_TYPE,
    VARIANT_TYPE,
)
from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    LearnedPattern,
    SIOptimizationConfig,
)

# Default temperature for code generation
DEFAULT_CODE_TEMPERATURE = 0.7

# Impact estimates by problem type
IMPACT_QUALITY_LOW = 0.35
IMPACT_ERROR_RATE_HIGH = 0.30
IMPACT_INCONSISTENT_OUTPUT = 0.25
IMPACT_DEFAULT = 0.1  # Default when problem type unknown


class ERC721WorkflowStrategy(ImprovementStrategy):
    """
    Strategy that optimizes ERC721 workflow agent configuration.

    Applicable when code generation quality is low or error rate is high.
    Generates variants that modify:
    1. Temperature (more deterministic)
    2. Model selection (code-specialized models)
    3. Prompt enhancement (inline Solidity examples)

    Example:
        >>> strategy = ERC721WorkflowStrategy()
        >>> current = SIOptimizationConfig(
        ...     inference={'model': 'llama3:8b', 'temperature': 0.7},
        ...     prompt={'template': 'default'}
        ... )
        >>> variants = strategy.generate_variants(current, [])
        >>> len(variants)
        3
    """

    # Code-specialized models to try
    CODE_MODELS = [
        "codellama:13b",
        "codellama:7b",
        "deepseek-coder:6.7b",
        "qwen2.5-coder:7b",
    ]

    # Solidity example snippet for prompt enhancement
    SOLIDITY_EXAMPLE = '''
// Example ERC721 with OpenZeppelin v5:
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract MyNFT is ERC721, Ownable {
    uint256 private _nextTokenId;

    constructor() ERC721("MyNFT", "MNFT") Ownable(msg.sender) {
        _nextTokenId = 1;
    }

    function mint(address to) public onlyOwner returns (uint256) {
        uint256 tokenId = _nextTokenId;
        _nextTokenId++;
        _mint(to, tokenId);
        return tokenId;
    }
}
'''

    @property
    def name(self) -> str:
        """Strategy identifier."""
        return "erc721_workflow"

    def generate_variants(
        self, current_config: SIOptimizationConfig, patterns: List[LearnedPattern]
    ) -> List[SIOptimizationConfig]:
        """Generate improved configuration variants.

        Generates 3 variants:
        1. Lower temperature
        2. Code-specialized model
        3. Enhanced prompt with Solidity examples

        Args:
            current_config: Current agent configuration
            patterns: Learned patterns (used to prioritize variants)

        Returns:
            List of 3 configuration variants
        """
        variants = []

        # Variant 1: Lower temperature for more deterministic code generation
        variant_temp = copy.deepcopy(current_config)
        current_temp = variant_temp.inference.get("temperature", DEFAULT_CODE_TEMPERATURE)
        # Reduce by 50%, minimum 0.05
        new_temp = max(PROB_MINIMAL, current_temp * FRACTION_HALF)
        variant_temp.inference["temperature"] = round(new_temp, 2)
        variant_temp.extra_metadata[STRATEGY_TYPE] = self.name
        variant_temp.extra_metadata[VARIANT_TYPE] = "lower_temperature"
        variant_temp.extra_metadata[STRATEGY_CHANGE] = f"temperature: {current_temp} -> {new_temp:.2f}"
        variants.append(variant_temp)

        # Variant 2: Code-specialized model
        current_model = current_config.inference.get("model", "llama3:8b")
        # Pick a code model that's different from current
        code_model = None
        for model in self.CODE_MODELS:
            if model != current_model:
                code_model = model
                break
        if code_model:
            variant_model = copy.deepcopy(current_config)
            variant_model.inference["model"] = code_model
            variant_model.extra_metadata[STRATEGY_TYPE] = self.name
            variant_model.extra_metadata[VARIANT_TYPE] = "code_model"
            variant_model.extra_metadata[STRATEGY_CHANGE] = f"model: {current_model} -> {code_model}"
            variants.append(variant_model)

        # Variant 3: Enhanced prompt with inline Solidity examples
        variant_prompt = copy.deepcopy(current_config)
        current_prompt = variant_prompt.prompt.get(PROMPT_LOCATION_INLINE, "")
        if self.SOLIDITY_EXAMPLE not in current_prompt:
            enhanced = current_prompt + "\n\nREFERENCE EXAMPLE:\n" + self.SOLIDITY_EXAMPLE
            variant_prompt.prompt[PROMPT_LOCATION_INLINE] = enhanced
        variant_prompt.extra_metadata[STRATEGY_TYPE] = self.name
        variant_prompt.extra_metadata[VARIANT_TYPE] = "enhanced_prompt"
        variant_prompt.extra_metadata[STRATEGY_CHANGE] = "Added inline Solidity reference example"
        variants.append(variant_prompt)

        return variants

    def is_applicable(self, problem_type: str) -> bool:
        """Check if strategy applies to the problem.

        Applicable for:
        - quality_low: Code generation produces bad Solidity
        - error_rate_high: Many compilation/test failures
        - inconsistent_output: LLM produces different results each time

        Args:
            problem_type: Type of problem detected

        Returns:
            True if strategy can help
        """
        applicable_types = {
            "quality_low",
            "error_rate_high",
            "inconsistent_output",
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
        }

        return impact_by_type.get(problem_type, IMPACT_DEFAULT)
