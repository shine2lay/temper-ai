"""Tests for src/observability/datetime_utils.py (deprecation shim)."""

import warnings


def test_datetime_utils_import_raises_deprecation_warning():
    """Test that importing from datetime_utils raises DeprecationWarning."""
    import importlib
    import sys

    # Remove the module from cache to force re-import and re-trigger warning
    mod_name = "temper_ai.observability.datetime_utils"
    old_module = sys.modules.pop(mod_name, None)

    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Import the module to trigger the warning
            importlib.import_module(mod_name)

            # Check that a deprecation warning was raised
            assert len(w) >= 1
            assert any(
                issubclass(warning.category, DeprecationWarning) for warning in w
            )

            # Find the deprecation warning
            deprecation_warnings = [
                warning
                for warning in w
                if issubclass(warning.category, DeprecationWarning)
            ]
            assert len(deprecation_warnings) >= 1

            # Verify the warning message
            warning_msg = str(deprecation_warnings[0].message)
            assert "temper_ai.observability.datetime_utils is deprecated" in warning_msg
            assert "temper_ai.storage.database.datetime_utils" in warning_msg
    finally:
        # Restore original module if it was cached
        if old_module is not None:
            sys.modules[mod_name] = old_module


def test_datetime_utils_re_exports_work():
    """Test that re-exports from datetime_utils still work."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # Suppress warnings for this test

        # Import from the deprecated location
        from temper_ai.observability.datetime_utils import utcnow

        # Verify the function exists and is callable
        assert callable(utcnow)

        # Verify it returns a timezone-aware datetime
        from datetime import datetime

        result = utcnow()
        assert isinstance(result, datetime)
        assert (
            result.tzinfo is not None
        ), "utcnow() should return timezone-aware datetime"


def test_datetime_utils_new_import_location():
    """Test importing from the new location works without warnings."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Import from the new location
        from temper_ai.storage.database.datetime_utils import utcnow

        # Verify no deprecation warnings were raised
        deprecation_warnings = [
            warning for warning in w if issubclass(warning.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0

        # Verify the function works
        result = utcnow()
        assert result is not None
