"""Tests for src/self_improvement/storage/__init__.py"""
import sys
import importlib


def test_storage_imports():
    """Test that all expected storage exports are available."""
    from src.self_improvement.storage import (
        CustomMetric,
        M5Experiment,
        M5ExecutionResult,
    )

    # Verify imports don't raise exceptions
    assert CustomMetric is not None
    assert M5Experiment is not None
    assert M5ExecutionResult is not None


def test_storage_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.storage as module

    expected_exports = {
        "CustomMetric",
        "M5Experiment",
        "M5ExecutionResult",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.storage'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.storage

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.storage import (
        CustomMetric,
        M5Experiment,
    )

    assert CustomMetric.__module__ == 'src.self_improvement.storage.models'
    assert M5Experiment.__module__ == 'src.self_improvement.storage.experiment_models'


def test_module_docstring():
    """Test that module has descriptive docstring."""
    import src.self_improvement.storage as module

    assert module.__doc__ is not None
    assert 'Storage' in module.__doc__
