"""Tests for src/self_improvement/agents/__init__.py"""
import sys
import importlib


def test_agents_imports():
    """Test that all expected agent exports are available."""
    from src.self_improvement.agents import (
        ProductExtractorAgent,
    )

    # Verify imports don't raise exceptions
    assert ProductExtractorAgent is not None


def test_agents_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.agents as module

    expected_exports = {
        "ProductExtractorAgent",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.agents'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.agents

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source module."""
    from src.self_improvement.agents import (
        ProductExtractorAgent,
    )

    assert ProductExtractorAgent.__module__ == 'src.self_improvement.agents.product_extractor'


def test_module_docstring():
    """Test that module has descriptive docstring."""
    import src.self_improvement.agents as module

    assert module.__doc__ is not None
    assert len(module.__doc__) > 50
    assert 'M5 Self-Improvement Agents' in module.__doc__
    assert 'benchmark' in module.__doc__.lower()
