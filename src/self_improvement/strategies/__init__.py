"""Self-improvement strategies for M5."""

from .strategy import ImprovementStrategy, AgentConfig, LearnedPattern
from .registry import StrategyRegistry
from .ollama_model_strategy import OllamaModelSelectionStrategy
from .erc721_strategy import ERC721WorkflowStrategy
from .prompt_optimization_strategy import PromptOptimizationStrategy
from .temperature_search_strategy import TemperatureSearchStrategy

__all__ = [
    "ImprovementStrategy",
    "AgentConfig",
    "LearnedPattern",
    "StrategyRegistry",
    "OllamaModelSelectionStrategy",
    "ERC721WorkflowStrategy",
    "PromptOptimizationStrategy",
    "TemperatureSearchStrategy",
]
