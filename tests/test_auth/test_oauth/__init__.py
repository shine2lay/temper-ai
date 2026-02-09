"""Tests for src.auth.oauth module."""


def test_oauth_module_imports():
    """Test that all expected exports from src.auth.oauth are available."""
    from src.auth.oauth import (
        CallbackURLValidator,
        InMemoryStateStore,
        OAuthConfig,
        OAuthConfigurationError,
        OAuthError,
        OAuthProviderConfig,
        OAuthProviderError,
        OAuthRateLimiter,
        OAuthService,
        OAuthStateError,
        RateLimitExceeded,
        RedisStateStore,
        SecureTokenStore,
        StateStore,
        create_state_store,
        get_provider_endpoints,
    )

    # Verify imports don't raise exceptions and are not None
    assert CallbackURLValidator is not None
    assert SecureTokenStore is not None
    assert OAuthConfig is not None
    assert OAuthProviderConfig is not None
    assert get_provider_endpoints is not None
    assert OAuthConfigurationError is not None
    assert OAuthService is not None
    assert OAuthError is not None
    assert OAuthStateError is not None
    assert OAuthProviderError is not None
    assert RateLimitExceeded is not None
    assert StateStore is not None
    assert RedisStateStore is not None
    assert InMemoryStateStore is not None
    assert create_state_store is not None
    assert OAuthRateLimiter is not None


def test_oauth_module_all_exports():
    """Test that __all__ contains all expected exports."""
    import src.auth.oauth

    expected_exports = [
        "CallbackURLValidator",
        "SecureTokenStore",
        "OAuthConfig",
        "OAuthProviderConfig",
        "get_provider_endpoints",
        "OAuthConfigurationError",
        "OAuthService",
        "OAuthError",
        "OAuthStateError",
        "OAuthProviderError",
        "RateLimitExceeded",
        "StateStore",
        "RedisStateStore",
        "InMemoryStateStore",
        "create_state_store",
        "OAuthRateLimiter",
    ]

    assert hasattr(src.auth.oauth, "__all__")
    assert set(src.auth.oauth.__all__) == set(expected_exports)


def test_oauth_callback_validator_reexport():
    """Test that CallbackURLValidator is correctly re-exported."""
    from src.auth.oauth import CallbackURLValidator
    from src.auth.oauth.callback_validator import (
        CallbackURLValidator as OrigValidator,
    )

    assert CallbackURLValidator is OrigValidator


def test_oauth_config_reexport():
    """Test that config components are correctly re-exported."""
    from src.auth.oauth import (
        OAuthConfig,
        OAuthConfigurationError,
        OAuthProviderConfig,
        get_provider_endpoints,
    )
    from src.auth.oauth.config import (
        OAuthConfig as OrigConfig,
        OAuthConfigurationError as OrigError,
        OAuthProviderConfig as OrigProviderConfig,
        get_provider_endpoints as orig_endpoints,
    )

    assert OAuthConfig is OrigConfig
    assert OAuthConfigurationError is OrigError
    assert OAuthProviderConfig is OrigProviderConfig
    assert get_provider_endpoints is orig_endpoints


def test_oauth_rate_limiter_reexport():
    """Test that rate limiter components are correctly re-exported."""
    from src.auth.oauth import OAuthRateLimiter, RateLimitExceeded
    from src.auth.oauth.rate_limiter import (
        OAuthRateLimiter as OrigLimiter,
        RateLimitExceeded as OrigException,
    )

    assert OAuthRateLimiter is OrigLimiter
    assert RateLimitExceeded is OrigException


def test_oauth_service_reexport():
    """Test that service components are correctly re-exported."""
    from src.auth.oauth import (
        OAuthError,
        OAuthProviderError,
        OAuthService,
        OAuthStateError,
    )
    from src.auth.oauth.service import (
        OAuthError as OrigError,
        OAuthProviderError as OrigProviderError,
        OAuthService as OrigService,
        OAuthStateError as OrigStateError,
    )

    assert OAuthService is OrigService
    assert OAuthError is OrigError
    assert OAuthStateError is OrigStateError
    assert OAuthProviderError is OrigProviderError


def test_oauth_state_store_reexport():
    """Test that state store components are correctly re-exported."""
    from src.auth.oauth import (
        InMemoryStateStore,
        RedisStateStore,
        StateStore,
        create_state_store,
    )
    from src.auth.oauth.state_store import (
        InMemoryStateStore as OrigInMemory,
        RedisStateStore as OrigRedis,
        StateStore as OrigStore,
        create_state_store as orig_create,
    )

    assert StateStore is OrigStore
    assert RedisStateStore is OrigRedis
    assert InMemoryStateStore is OrigInMemory
    assert create_state_store is orig_create


def test_oauth_token_store_reexport():
    """Test that SecureTokenStore is correctly re-exported."""
    from src.auth.oauth import SecureTokenStore
    from src.auth.oauth.token_store import SecureTokenStore as OrigStore

    assert SecureTokenStore is OrigStore


def test_oauth_no_side_effects():
    """Test that importing src.auth.oauth doesn't cause side effects."""
    import importlib
    import sys

    # Remove module if already imported
    module_name = "src.auth.oauth"
    if module_name in sys.modules:
        # Store original for restoration
        original_module = sys.modules[module_name]
        del sys.modules[module_name]

        # Import should not raise or create globals
        import src.auth.oauth

        assert src.auth.oauth is not None
        # Restore original
        sys.modules[module_name] = original_module
    else:
        # Import should not raise
        import src.auth.oauth

        assert src.auth.oauth is not None


def test_oauth_module_docstring():
    """Test that the oauth module has a proper docstring with security notes."""
    import src.auth.oauth

    assert src.auth.oauth.__doc__ is not None
    assert len(src.auth.oauth.__doc__.strip()) > 0
    assert "oauth" in src.auth.oauth.__doc__.lower()
    assert "security" in src.auth.oauth.__doc__.lower()


def test_oauth_star_import():
    """Test that 'from src.auth.oauth import *' works correctly."""
    import sys

    # Create a clean namespace
    namespace = {}

    # Execute star import in clean namespace
    exec("from src.auth.oauth import *", namespace)

    # Verify all __all__ exports are present
    expected = [
        "CallbackURLValidator",
        "SecureTokenStore",
        "OAuthConfig",
        "OAuthProviderConfig",
        "get_provider_endpoints",
        "OAuthConfigurationError",
        "OAuthService",
        "OAuthError",
        "OAuthStateError",
        "OAuthProviderError",
        "RateLimitExceeded",
        "StateStore",
        "RedisStateStore",
        "InMemoryStateStore",
        "create_state_store",
        "OAuthRateLimiter",
    ]

    for name in expected:
        assert name in namespace, f"{name} not found in star import"


def test_oauth_import_no_exceptions():
    """Test that importing oauth submodules does not raise any exceptions."""
    try:
        import src.auth.oauth
        import src.auth.oauth.callback_validator
        import src.auth.oauth.config
        import src.auth.oauth.rate_limiter
        import src.auth.oauth.service
        import src.auth.oauth.state_store
        import src.auth.oauth.token_store

        assert True  # All imports succeeded
    except Exception as e:
        assert False, f"Import raised unexpected exception: {e}"


def test_oauth_exception_hierarchy():
    """Test that OAuth exceptions are properly structured."""
    from src.auth.oauth import (
        OAuthError,
        OAuthProviderError,
        OAuthStateError,
        RateLimitExceeded,
    )

    # Verify exception inheritance
    assert issubclass(OAuthStateError, OAuthError)
    assert issubclass(OAuthProviderError, OAuthError)
    assert issubclass(RateLimitExceeded, Exception)


def test_oauth_security_components_available():
    """Test that all security-critical components are exported."""
    from src.auth.oauth import (
        CallbackURLValidator,
        OAuthRateLimiter,
        SecureTokenStore,
        StateStore,
    )

    # These are the core security components mentioned in docstring
    security_components = [
        CallbackURLValidator,  # CSRF protection
        StateStore,  # State parameter validation
        SecureTokenStore,  # Encrypted token storage
        OAuthRateLimiter,  # Rate limiting
    ]

    for component in security_components:
        assert component is not None, f"Security component {component} is None"
