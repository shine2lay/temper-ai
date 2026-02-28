"""Authentication tests."""


def test_auth_module_imports():
    """Test that all expected exports from temper_ai.auth are available."""
    from temper_ai.auth import (
        InMemorySessionStore,
        OAuthRouteHandlers,
        Session,
        SessionStoreProtocol,
        User,
    )

    # Verify imports don't raise exceptions and are not None
    assert Session is not None
    assert User is not None
    assert SessionStoreProtocol is not None
    assert InMemorySessionStore is not None
    assert OAuthRouteHandlers is not None


def test_auth_module_all_exports():
    """Test that __all__ contains all expected exports."""
    import temper_ai.auth

    expected_exports = [
        "User",
        "Session",
        "SessionStoreProtocol",
        "InMemorySessionStore",
        "OAuthRouteHandlers",
    ]

    assert hasattr(temper_ai.auth, "__all__")
    assert set(temper_ai.auth.__all__) == set(expected_exports)


def test_auth_models_reexport():
    """Test that models are correctly re-exported from auth module."""
    from temper_ai.auth import Session, User
    from temper_ai.auth.models import Session as OrigSession
    from temper_ai.auth.models import User as OrigUser

    # Verify re-exports point to the same classes
    assert Session is OrigSession
    assert User is OrigUser


def test_auth_session_reexport():
    """Test that session stores are correctly re-exported from auth module."""
    from temper_ai.auth import (
        InMemorySessionStore,
        SessionStoreProtocol,
    )
    from temper_ai.auth.session import (
        InMemorySessionStore as OrigInMemory,
    )
    from temper_ai.auth.session import (
        SessionStoreProtocol as OrigProtocol,
    )

    # Verify re-exports point to the same classes
    assert SessionStoreProtocol is OrigProtocol
    assert InMemorySessionStore is OrigInMemory


def test_auth_routes_reexport():
    """Test that route handlers are correctly re-exported from auth module."""
    from temper_ai.auth import OAuthRouteHandlers
    from temper_ai.auth.routes import OAuthRouteHandlers as OrigHandlers

    # Verify re-export points to the same class
    assert OAuthRouteHandlers is OrigHandlers


def test_auth_no_side_effects():
    """Test that importing temper_ai.auth doesn't cause side effects."""
    import importlib
    import sys

    # Remove module if already imported
    module_name = "temper_ai.auth"
    if module_name in sys.modules:
        # Store original for restoration
        original_module = sys.modules[module_name]
        del sys.modules[module_name]

        # Import should not raise or create globals
        import temper_ai.auth

        assert temper_ai.auth is not None
        # Restore original
        sys.modules[module_name] = original_module
    else:
        # Import should not raise
        import temper_ai.auth

        assert temper_ai.auth is not None


def test_auth_module_docstring():
    """Test that the auth module has a proper docstring."""
    import temper_ai.auth

    assert temper_ai.auth.__doc__ is not None
    assert len(temper_ai.auth.__doc__.strip()) > 0
    assert "authentication" in temper_ai.auth.__doc__.lower()


def test_auth_star_import():
    """Test that 'from temper_ai.auth import *' works correctly."""
    import sys

    # Create a clean namespace
    namespace = {}

    # Execute star import in clean namespace
    exec("from temper_ai.auth import *", namespace)

    # Verify all __all__ exports are present
    expected = [
        "User",
        "Session",
        "SessionStoreProtocol",
        "InMemorySessionStore",
        "OAuthRouteHandlers",
    ]

    for name in expected:
        assert name in namespace, f"{name} not found in star import"


def test_auth_import_no_exceptions():
    """Test that importing auth module does not raise any exceptions."""
    try:
        import temper_ai.auth
        import temper_ai.auth.models
        import temper_ai.auth.routes
        import temper_ai.auth.session

        assert True  # All imports succeeded
    except Exception as e:
        raise AssertionError(f"Import raised unexpected exception: {e}")
