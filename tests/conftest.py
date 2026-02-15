"""Root pytest configuration.

Provides automatic global state isolation between tests.
"""
import pytest

# Register shared fixture plugins
pytest_plugins = [
    "tests.fixtures.database_fixtures",
    "tests.fixtures.mock_helpers",
    "tests.fixtures.auth_fixtures",
]


@pytest.fixture(autouse=True)
def _reset_globals_after_test():
    """Auto-reset all global singletons after each test.

    This prevents test pollution where one test's global state
    leaks into subsequent tests. Uses lazy imports so it only
    resets modules that were actually loaded.
    """
    yield
    from src.shared.core.test_support import reset_all_globals
    reset_all_globals()
