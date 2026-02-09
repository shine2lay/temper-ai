"""Tests for src/observability/database.py (deprecation shim)."""
import warnings

import pytest


def test_database_import_raises_deprecation_warning():
    """Test that importing from database raises DeprecationWarning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import the module to trigger the warning
        import src.observability.database  # noqa: F401

        # Check that a deprecation warning was raised
        assert len(w) >= 1
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

        # Find the deprecation warning
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1

        # Verify the warning message
        warning_msg = str(deprecation_warnings[0].message)
        assert "src.observability.database is deprecated" in warning_msg
        assert "src.database" in warning_msg


def test_database_re_exports_work():
    """Test that re-exports from database still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated location
        from src.observability.database import DatabaseManager

        # Verify the class exists
        assert DatabaseManager is not None


def test_database_private_exports_work():
    """Test that private re-exports (_db_manager, _mask_database_url) work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import private exports from the deprecated location
        from src.observability.database import _db_manager, _mask_database_url

        # _db_manager might be None initially (singleton pattern)
        # Just verify it can be imported
        # _mask_database_url should be callable
        assert callable(_mask_database_url)


def test_database_new_import_location():
    """Test importing from the new location works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import from the new location
        from src.database.manager import DatabaseManager

        # Verify no deprecation warnings were raised
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 0

        # Verify the class works
        assert DatabaseManager is not None
