"""Tests for src/self_improvement/detection/__init__.py"""
import sys
import importlib


def test_detection_imports():
    """Test that all expected detection exports are available."""
    from src.self_improvement.detection import (
        PerformanceProblem,
        ProblemType,
        ProblemSeverity,
        ProblemDetectionConfig,
        ProblemDetector,
        ProblemDetectionError,
        ProblemDetectionDataError,
        ImprovementProposal,
        ImprovementDetector,
        ImprovementDetectionError,
        NoBaselineError,
        ComponentError,
    )

    # Verify imports don't raise exceptions
    assert PerformanceProblem is not None
    assert ProblemType is not None
    assert ProblemSeverity is not None
    assert ProblemDetectionConfig is not None
    assert ProblemDetector is not None
    assert ProblemDetectionError is not None
    assert ProblemDetectionDataError is not None
    assert ImprovementProposal is not None
    assert ImprovementDetector is not None
    assert ImprovementDetectionError is not None
    assert NoBaselineError is not None
    assert ComponentError is not None


def test_detection_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.detection as module

    expected_exports = {
        "PerformanceProblem",
        "ProblemType",
        "ProblemSeverity",
        "ProblemDetectionConfig",
        "ProblemDetector",
        "ProblemDetectionError",
        "ProblemDetectionDataError",
        "ImprovementProposal",
        "ImprovementDetector",
        "ImprovementDetectionError",
        "NoBaselineError",
        "ComponentError",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_exception_hierarchy():
    """Test that exception classes have correct inheritance."""
    from src.self_improvement.detection import (
        ProblemDetectionError,
        ProblemDetectionDataError,
        ImprovementDetectionError,
        NoBaselineError,
        ComponentError,
    )

    assert issubclass(ProblemDetectionError, Exception)
    assert issubclass(ProblemDetectionDataError, ProblemDetectionError)
    assert issubclass(ImprovementDetectionError, Exception)
    assert issubclass(NoBaselineError, ImprovementDetectionError)
    assert issubclass(ComponentError, ImprovementDetectionError)


def test_enum_types():
    """Test that enum types are properly exported."""
    from src.self_improvement.detection import (
        ProblemType,
        ProblemSeverity,
    )
    from enum import Enum

    assert issubclass(ProblemType, Enum)
    assert issubclass(ProblemSeverity, Enum)


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.detection'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.detection

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.detection import (
        ProblemDetector,
        ImprovementProposal,
        PerformanceProblem,
    )

    assert ProblemDetector.__module__ == 'src.self_improvement.detection.problem_detector'
    assert ImprovementProposal.__module__ == 'src.self_improvement.detection.improvement_proposal'
    assert PerformanceProblem.__module__ == 'src.self_improvement.detection.problem_models'


def test_module_docstring():
    """Test that module has descriptive docstring."""
    import src.self_improvement.detection as module

    assert module.__doc__ is not None
    assert len(module.__doc__) > 50
    assert 'detection' in module.__doc__.lower()
