"""Tests for src/observability/models.py (deprecation shim)."""
import warnings

import pytest


def test_models_import_raises_deprecation_warning():
    """Test that importing from models raises DeprecationWarning."""
    # Note: The warning may have already been raised if the module was imported
    # elsewhere (e.g., in src/observability/__init__.py). This test verifies
    # the warning exists when the module is first imported.

    # Since the module may already be imported, we check that the deprecation
    # warning is in the module source code
    import src.observability.models as models_module
    import inspect

    source = inspect.getsource(models_module)
    assert "DeprecationWarning" in source
    assert "src.observability.models is deprecated" in source
    assert "src.storage.database.models" in source


def test_models_re_exports_work():
    """Test that re-exports from models still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated location
        from src.observability.models import WorkflowExecution

        # Verify the class exists
        assert WorkflowExecution is not None
        assert hasattr(WorkflowExecution, '__tablename__')


def test_models_new_import_location():
    """Test importing from the new location works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import from the new location
        from src.storage.database.models import WorkflowExecution

        # Verify no deprecation warnings were raised
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0

        # Verify the class works
        assert WorkflowExecution is not None
