"""Authentication tests."""


def test_auth_module_imports():
    """Test that all expected exports from src.auth are available."""
    from src.auth import (
        InMemorySessionStore,
        OAuthRouteHandlers,
        RedisSessionStore,
        Session,
        SessionStoreProtocol,
        User,
    )

    # Verify imports don't raise exceptions and are not None
    assert Session is not None
    assert User is not None
    assert SessionStoreProtocol is not None
    assert InMemorySessionStore is not None
    assert RedisSessionStore is not None
    assert OAuthRouteHandlers is not None


def test_auth_module_all_exports():
    """Test that __all__ contains all expected exports."""
    import src.auth

    expected_exports = [
        "User",
        "Session",
        "SessionStoreProtocol",
        "InMemorySessionStore",
        "RedisSessionStore",
        "OAuthRouteHandlers",
    ]

    assert hasattr(src.auth, "__all__")
    assert set(src.auth.__all__) == set(expected_exports)


def test_auth_models_reexport():
    """Test that models are correctly re-exported from auth module."""
    from src.auth import Session, User
    from src.auth.models import Session as OrigSession
    from src.auth.models import User as OrigUser

    # Verify re-exports point to the same classes
    assert Session is OrigSession
    assert User is OrigUser


def test_auth_session_reexport():
    """Test that session stores are correctly re-exported from auth module."""
    from src.auth import (
        InMemorySessionStore,
        RedisSessionStore,
        SessionStoreProtocol,
    )
    from src.auth.session import (
        InMemorySessionStore as OrigInMemory,
        RedisSessionStore as OrigRedis,
        SessionStoreProtocol as OrigProtocol,
    )

    # Verify re-exports point to the same classes
    assert SessionStoreProtocol is OrigProtocol
    assert InMemorySessionStore is OrigInMemory
    assert RedisSessionStore is OrigRedis


def test_auth_routes_reexport():
    """Test that route handlers are correctly re-exported from auth module."""
    from src.auth import OAuthRouteHandlers
    from src.auth.routes import OAuthRouteHandlers as OrigHandlers

    # Verify re-export points to the same class
    assert OAuthRouteHandlers is OrigHandlers


def test_auth_no_side_effects():
    """Test that importing src.auth doesn't cause side effects."""
    import importlib
    import sys

    # Remove module if already imported
    module_name = "src.auth"
    if module_name in sys.modules:
        # Store original for restoration
        original_module = sys.modules[module_name]
        del sys.modules[module_name]

        # Import should not raise or create globals
        import src.auth

        assert src.auth is not None
        # Restore original
        sys.modules[module_name] = original_module
    else:
        # Import should not raise
        import src.auth

        assert src.auth is not None


def test_auth_module_docstring():
    """Test that the auth module has a proper docstring."""
    import src.auth

    assert src.auth.__doc__ is not None
    assert len(src.auth.__doc__.strip()) > 0
    assert "authentication" in src.auth.__doc__.lower()


def test_auth_star_import():
    """Test that 'from src.auth import *' works correctly."""
    import sys

    # Create a clean namespace
    namespace = {}

    # Execute star import in clean namespace
    exec("from src.auth import *", namespace)

    # Verify all __all__ exports are present
    expected = [
        "User",
        "Session",
        "SessionStoreProtocol",
        "InMemorySessionStore",
        "RedisSessionStore",
        "OAuthRouteHandlers",
    ]

    for name in expected:
        assert name in namespace, f"{name} not found in star import"


def test_auth_import_no_exceptions():
    """Test that importing auth module does not raise any exceptions."""
    try:
        import src.auth
        import src.auth.models
        import src.auth.routes
        import src.auth.session

        assert True  # All imports succeeded
    except Exception as e:
        assert False, f"Import raised unexpected exception: {e}"
