"""
ERC721 Workflow Improvement Strategy for M5 self-improvement system.

Generates configuration variants for improving ERC721 code generation:
- Variant 1: Lower temperature for more deterministic output
- Variant 2: Different model (codellama vs llama3)
- Variant 3: Enhanced prompts with inline Solidity examples
"""
import copy
from typing import Dict, List

from src.self_improvement.strategies.strategy import (
    ImprovementStrategy,
    LearnedPattern,
    SIOptimizationConfig,
)


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

    def __init__(self, learning_store=None):
        """
        Initialize strategy with optional learning store.

        Args:
            learning_store: Optional StrategyLearningStore for learning from outcomes
        """
        super().__init__(learning_store)

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
        current_temp = variant_temp.inference.get("temperature", 0.7)
        # Reduce by 50%, minimum 0.05
        new_temp = max(0.05, current_temp * 0.5)
        variant_temp.inference["temperature"] = round(new_temp, 2)
        variant_temp.extra_metadata["strategy"] = self.name
        variant_temp.extra_metadata["variant_type"] = "lower_temperature"
        variant_temp.extra_metadata["change"] = f"temperature: {current_temp} -> {new_temp:.2f}"
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
            variant_model.extra_metadata["strategy"] = self.name
            variant_model.extra_metadata["variant_type"] = "code_model"
            variant_model.extra_metadata["change"] = f"model: {current_model} -> {code_model}"
            variants.append(variant_model)

        # Variant 3: Enhanced prompt with inline Solidity examples
        variant_prompt = copy.deepcopy(current_config)
        current_prompt = variant_prompt.prompt.get("inline", "")
        if self.SOLIDITY_EXAMPLE not in current_prompt:
            enhanced = current_prompt + "\n\nREFERENCE EXAMPLE:\n" + self.SOLIDITY_EXAMPLE
            variant_prompt.prompt["inline"] = enhanced
        variant_prompt.extra_metadata["strategy"] = self.name
        variant_prompt.extra_metadata["variant_type"] = "enhanced_prompt"
        variant_prompt.extra_metadata["change"] = "Added inline Solidity reference example"
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
            "quality_low": 0.35,
            "error_rate_high": 0.30,
            "inconsistent_output": 0.25,
        }

        return impact_by_type.get(problem_type, 0.1)
