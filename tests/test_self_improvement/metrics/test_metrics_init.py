"""Tests for src/self_improvement/metrics/__init__.py"""
import sys
import importlib


def test_metrics_imports():
    """Test that all expected metric exports are available."""
    from src.self_improvement.metrics import (
        MetricCollector,
        MetricRegistry,
        ExecutionProtocol,
        SIMetricType,
        MetricValue,
        ExtractionQualityCollector,
        ERC721QualityCollector,
        ERC721QualityScore,
        score_erc721_workflow,
    )

    # Verify imports don't raise exceptions
    assert MetricCollector is not None
    assert MetricRegistry is not None
    assert ExecutionProtocol is not None
    assert SIMetricType is not None
    assert MetricValue is not None
    assert ExtractionQualityCollector is not None
    assert ERC721QualityCollector is not None
    assert ERC721QualityScore is not None
    assert score_erc721_workflow is not None


def test_metrics_all_exports():
    """Test that __all__ matches actual exports."""
    import src.self_improvement.metrics as module

    expected_exports = {
        "MetricCollector",
        "MetricRegistry",
        "ExecutionProtocol",
        "SIMetricType",
        "MetricValue",
        "ExtractionQualityCollector",
        "ERC721QualityCollector",
        "ERC721QualityScore",
        "score_erc721_workflow",
    }

    assert hasattr(module, '__all__')
    assert set(module.__all__) == expected_exports


def test_metric_collector_base():
    """Test that MetricCollector is properly exported as base class."""
    from src.self_improvement.metrics import (
        MetricCollector,
        ExtractionQualityCollector,
        ERC721QualityCollector,
    )

    # Verify collector implementations inherit from base
    assert issubclass(ExtractionQualityCollector, MetricCollector)
    assert issubclass(ERC721QualityCollector, MetricCollector)


def test_no_side_effects():
    """Test that importing doesn't cause side effects."""
    module_name = 'src.self_improvement.metrics'

    if module_name in sys.modules:
        del sys.modules[module_name]

    import src.self_improvement.metrics

    assert module_name in sys.modules


def test_reexport_integrity():
    """Test that re-exported names resolve to correct source modules."""
    from src.self_improvement.metrics import (
        MetricCollector,
        SIMetricType,
        ERC721QualityCollector,
    )

    assert MetricCollector.__module__ == 'src.self_improvement.metrics.collector'
    assert SIMetricType.__module__ == 'src.self_improvement.metrics.types'
    assert ERC721QualityCollector.__module__ == 'src.self_improvement.metrics.erc721_quality'


def test_module_docstring():
    """Test that module has comprehensive docstring."""
    import src.self_improvement.metrics as module

    assert module.__doc__ is not None
    assert len(module.__doc__) > 100
    assert 'MetricCollector' in module.__doc__
    assert 'Example Usage' in module.__doc__
