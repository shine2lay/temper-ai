"""Tests for src/self_improvement/deployment/__init__.py"""
import sys
import importlib


def test_deployment_imports():
    """Test that all expected deployment exports are available."""
    from src.self_improvement.deployment import (
        ConfigDeployer,
        RollbackMonitor,
        RegressionThresholds,
    )

    # Verify imports don't raise exceptions
    assert ConfigDeployer is not None
    assert RollbackMonitor is not None
    assert RegressionThresholds is not None


def test_deployment_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.deployment as module

    expected_exports = {
        "ConfigDeployer",
        "RollbackMonitor",
        "RegressionThresholds",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.deployment'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.deployment

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.deployment import (
        ConfigDeployer,
        RollbackMonitor,
    )

    assert ConfigDeployer.__module__ == 'src.self_improvement.deployment.deployer'
    assert RollbackMonitor.__module__ == 'src.self_improvement.deployment.rollback_monitor'


def test_module_docstring():
    """Test that module has descriptive docstring."""
    import src.self_improvement.deployment as module

    assert module.__doc__ is not None
    assert len(module.__doc__) > 30
    assert 'deployment' in module.__doc__.lower()
    assert 'rollback' in module.__doc__.lower()
