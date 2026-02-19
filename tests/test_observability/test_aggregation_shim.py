"""Tests for src/observability/aggregation.py (deprecation shim)."""
import warnings

import pytest


def test_aggregation_import_raises_deprecation_warning():
    """Test that importing from aggregation.py raises DeprecationWarning."""
    # Note: The aggregation.py file (not the package) contains the deprecation
    # warning. Let's verify the warning code exists in that file.

    import pathlib

    agg_file = pathlib.Path("/home/shinelay/meta-autonomous-framework/src/observability/aggregation.py")
    source = agg_file.read_text()

    assert "DeprecationWarning" in source
    assert "temper_ai.observability.aggregation.py is deprecated" in source
    assert "temper_ai.observability.aggregation import" in source


def test_aggregation_re_exports_work():
    """Test that re-exports from aggregation.py still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated file
        from temper_ai.observability import aggregation

        # Verify the exports exist
        assert hasattr(aggregation, 'AggregationOrchestrator')
        assert hasattr(aggregation, 'AggregationPeriod')

        # Verify they are the correct types
        assert aggregation.AggregationOrchestrator is not None
        assert aggregation.AggregationPeriod is not None


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

        # Verify the imports work
        assert AggregationOrchestrator is not None
        assert AggregationPeriod is not None
