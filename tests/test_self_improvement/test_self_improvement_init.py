"""Tests for src/self_improvement/__init__.py"""
import sys
import importlib


def test_self_improvement_imports():
    """Test that all expected exports from main self_improvement package are available."""
    from src.self_improvement import (
        AgentPerformanceProfile,
        ExecutionResult,
        SelfImprovementExperiment,
        SIOptimizationConfig,
        utcnow,
        ExperimentError,
        ExperimentNotCompleteError,
        ExperimentNotFoundError,
        ExperimentOrchestrator,
        InvalidVariantError,
        SIExperimentStatus,
        SIVariantAssignment,
        WinnerResult,
    )

    # Verify imports don't raise exceptions
    assert AgentPerformanceProfile is not None
    assert ExecutionResult is not None
    assert SelfImprovementExperiment is not None
    assert SIOptimizationConfig is not None
    assert utcnow is not None
    assert ExperimentOrchestrator is not None
    assert SIVariantAssignment is not None
    assert SIExperimentStatus is not None
    assert WinnerResult is not None
    assert ExperimentError is not None
    assert ExperimentNotFoundError is not None
    assert ExperimentNotCompleteError is not None
    assert InvalidVariantError is not None


def test_self_improvement_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement as module

    expected_exports = {
        "AgentPerformanceProfile",
        "SIOptimizationConfig",
        "SelfImprovementExperiment",
        "ExecutionResult",
        "utcnow",
        "ExperimentOrchestrator",
        "SIVariantAssignment",
        "SIExperimentStatus",
        "WinnerResult",
        "ExperimentError",
        "ExperimentNotFoundError",
        "ExperimentNotCompleteError",
        "InvalidVariantError",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_exception_hierarchy():
    """Test that exception classes have correct inheritance."""
    from src.self_improvement import (
        ExperimentError,
        ExperimentNotCompleteError,
        ExperimentNotFoundError,
        InvalidVariantError,
    )

    assert issubclass(ExperimentError, Exception)
    assert issubclass(ExperimentNotCompleteError, ExperimentError)
    assert issubclass(ExperimentNotFoundError, ExperimentError)
    assert issubclass(InvalidVariantError, ExperimentError)


def test_no_side_effects():
    """Test that importing doesn't cause unwanted side effects."""
    module_name = 'src.self_improvement'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement

    # Import should succeed without side effects
    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct modules."""
    from src.self_improvement import (
        AgentPerformanceProfile,
        ExperimentOrchestrator,
    )

    # Verify re-exports point to correct source modules
    assert AgentPerformanceProfile.__module__ == 'src.self_improvement.data_models'
    assert ExperimentOrchestrator.__module__ == 'src.self_improvement.experiment_orchestrator'
