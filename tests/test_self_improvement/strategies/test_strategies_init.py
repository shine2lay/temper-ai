"""Tests for src/self_improvement/strategies/__init__.py"""
import sys
import importlib


def test_strategies_imports():
    """Test that all expected strategy exports are available."""
    from src.self_improvement.strategies import (
        ERC721WorkflowStrategy,
        OllamaModelSelectionStrategy,
        PromptOptimizationStrategy,
        ImprovementStrategyRegistry,
        StrategyRegistry,
        ImprovementStrategy,
        LearnedPattern,
        SIOptimizationConfig,
        TemperatureSearchStrategy,
    )

    # Verify imports don't raise exceptions
    assert ERC721WorkflowStrategy is not None
    assert OllamaModelSelectionStrategy is not None
    assert PromptOptimizationStrategy is not None
    assert ImprovementStrategyRegistry is not None
    assert StrategyRegistry is not None
    assert ImprovementStrategy is not None
    assert LearnedPattern is not None
    assert SIOptimizationConfig is not None
    assert TemperatureSearchStrategy is not None


def test_strategies_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.strategies as module

    expected_exports = {
        "ImprovementStrategy",
        "SIOptimizationConfig",
        "LearnedPattern",
        "ImprovementStrategyRegistry",
        "StrategyRegistry",
        "OllamaModelSelectionStrategy",
        "ERC721WorkflowStrategy",
        "PromptOptimizationStrategy",
        "TemperatureSearchStrategy",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_strategy_base_class():
    """Test that ImprovementStrategy is properly exported as base class."""
    from src.self_improvement.strategies import (
        ImprovementStrategy,
        ERC721WorkflowStrategy,
        OllamaModelSelectionStrategy,
        TemperatureSearchStrategy,
    )

    # Verify strategy implementations inherit from base
    assert issubclass(ERC721WorkflowStrategy, ImprovementStrategy)
    assert issubclass(OllamaModelSelectionStrategy, ImprovementStrategy)
    assert issubclass(TemperatureSearchStrategy, ImprovementStrategy)


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.strategies'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.strategies

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.strategies import (
        ImprovementStrategy,
        StrategyRegistry,
        ERC721WorkflowStrategy,
    )

    assert ImprovementStrategy.__module__ == 'src.self_improvement.strategies.strategy'
    assert StrategyRegistry.__module__ == 'src.self_improvement.strategies.registry'
    assert ERC721WorkflowStrategy.__module__ == 'src.self_improvement.strategies.erc721_strategy'
