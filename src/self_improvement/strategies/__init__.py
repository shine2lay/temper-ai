"""Self-improvement strategies for M5."""

from .erc721_strategy import ERC721WorkflowStrategy
from .ollama_model_strategy import OllamaModelSelectionStrategy
from .prompt_optimization_strategy import PromptOptimizationStrategy
from .registry import ImprovementStrategyRegistry, StrategyRegistry
from .strategy import ImprovementStrategy, LearnedPattern, SIOptimizationConfig
from .temperature_search_strategy import TemperatureSearchStrategy

__all__ = [
    "ImprovementStrategy",
    "SIOptimizationConfig",
    "LearnedPattern",
    "ImprovementStrategyRegistry",
    "StrategyRegistry",
    "OllamaModelSelectionStrategy",
    "ERC721WorkflowStrategy",
    "PromptOptimizationStrategy",
    "TemperatureSearchStrategy",
]
