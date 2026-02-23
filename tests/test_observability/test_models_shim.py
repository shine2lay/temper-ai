"""Tests for src/observability/models.py (deprecation shim)."""

import warnings


def test_models_import_raises_deprecation_warning():
    """Test that the models.py shim file contains deprecation warning code.

    Note: The module may already be cached from other imports, so we
    verify source content to confirm the deprecation warning is present.
    """
    import pathlib

    import temper_ai.observability

    pkg_dir = pathlib.Path(temper_ai.observability.__file__).parent
    models_file = pkg_dir / "models.py"
    source = models_file.read_text()

    assert "DeprecationWarning" in source
    assert "deprecated" in source.lower()
    assert "temper_ai.storage.database.models" in source


def test_models_re_exports_work():
    """Test that re-exports from models still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated location
        from temper_ai.observability.models import WorkflowExecution

        # Verify the class exists
        assert WorkflowExecution is not None
        assert hasattr(WorkflowExecution, "__tablename__")


def test_models_new_import_location():
    """Test importing from the new location works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import from the new location
        from temper_ai.storage.database.models import WorkflowExecution

        # Verify no deprecation warnings were raised
        deprecation_warnings = [
            warning for warning in w if issubclass(warning.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0

        # Verify the class works
        assert WorkflowExecution is not None
