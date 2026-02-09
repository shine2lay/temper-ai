"""Tests for src/self_improvement/loop/__init__.py"""
import sys
import importlib


def test_loop_imports():
    """Test that all expected loop exports are available."""
    from src.self_improvement.loop import (
        M5SelfImprovementLoop,
        LoopConfig,
        Phase,
        LoopStatus,
        LoopState,
        IterationResult,
        DetectionResult,
        AnalysisResult,
        StrategyResult,
        ExperimentPhaseResult,
        DeploymentResult,
        ProgressReport,
        RecoveryAction,
        LoopMetrics,
    )

    # Verify imports don't raise exceptions
    assert M5SelfImprovementLoop is not None
    assert LoopConfig is not None
    assert Phase is not None
    assert LoopStatus is not None
    assert LoopState is not None
    assert IterationResult is not None
    assert DetectionResult is not None
    assert AnalysisResult is not None
    assert StrategyResult is not None
    assert ExperimentPhaseResult is not None
    assert DeploymentResult is not None
    assert ProgressReport is not None
    assert RecoveryAction is not None
    assert LoopMetrics is not None


def test_loop_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.loop as module

    expected_exports = {
        "M5SelfImprovementLoop",
        "LoopConfig",
        "Phase",
        "LoopStatus",
        "LoopState",
        "IterationResult",
        "DetectionResult",
        "AnalysisResult",
        "StrategyResult",
        "ExperimentPhaseResult",
        "DeploymentResult",
        "ProgressReport",
        "RecoveryAction",
        "LoopMetrics",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_enum_types():
    """Test that enum types are properly exported."""
    from src.self_improvement.loop import (
        Phase,
        LoopStatus,
    )
    from enum import Enum

    assert issubclass(Phase, Enum)
    assert issubclass(LoopStatus, Enum)


def test_version_attribute():
    """Test that module has version attribute."""
    import src.self_improvement.loop as module

    assert hasattr(module, '__version__')
    assert module.__version__ == "1.0.0"


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.loop'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.loop

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.loop import (
        M5SelfImprovementLoop,
        LoopConfig,
        LoopMetrics,
    )

    assert M5SelfImprovementLoop.__module__ == 'src.self_improvement.loop.orchestrator'
    assert LoopConfig.__module__ == 'src.self_improvement.loop.config'
    assert LoopMetrics.__module__ == 'src.self_improvement.loop.metrics'


def test_module_docstring():
    """Test that module has comprehensive docstring with example."""
    import src.self_improvement.loop as module

    assert module.__doc__ is not None
    assert len(module.__doc__) > 200
    assert 'M5 Self-Improvement Loop' in module.__doc__
    assert 'Example:' in module.__doc__
    assert 'DETECT' in module.__doc__
