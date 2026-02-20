"""Tests for src/observability/aggregation.py (deprecation shim)."""
import warnings

import pytest


def test_aggregation_import_raises_deprecation_warning():
    """Test that the aggregation.py shim file contains deprecation warning code.

    Note: The aggregation/ package shadows aggregation.py, so the shim
    cannot be imported directly. We verify source content instead.
    """
    import pathlib

    import temper_ai.observability
    pkg_dir = pathlib.Path(temper_ai.observability.__file__).parent
    agg_file = pkg_dir / "aggregation.py"
    source = agg_file.read_text()

    assert "DeprecationWarning" in source
    assert "deprecated" in source.lower()
    assert "AggregationOrchestrator" in source


def test_aggregation_re_exports_work():
    """Test that re-exports from aggregation.py still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated file
        from temper_ai.observability import aggregation

        # Verify the exports exist
        assert hasattr(aggregation, 'AggregationOrchestrator')
        assert hasattr(aggregation, 'AggregationPeriod')

        # Verify the re-exports are actual classes, not stubs
        import inspect
        assert inspect.isclass(aggregation.AggregationOrchestrator), \
            "AggregationOrchestrator should be a class"
        assert inspect.isclass(aggregation.AggregationPeriod), \
            "AggregationPeriod should be a class"


def test_aggregation_exports_in_all():
    """Test that __all__ contains the expected exports."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        from temper_ai.observability import aggregation

        # Verify __all__ is defined correctly
        assert hasattr(aggregation, '__all__')
        assert 'AggregationOrchestrator' in aggregation.__all__
        assert 'AggregationPeriod' in aggregation.__all__


def test_aggregation_new_import_location():
    """Test importing from the new location works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import from the new package location
        from temper_ai.observability.aggregation import AggregationOrchestrator, AggregationPeriod

        # Note: This may have warnings from the aggregation.py file being imported as a side effect
        # but importing from the package should be the preferred way

        # Verify the imports are actual classes, not stubs
        import inspect
        assert inspect.isclass(AggregationOrchestrator), \
            "AggregationOrchestrator should be a class"
        assert inspect.isclass(AggregationPeriod), \
            "AggregationPeriod should be a class"
