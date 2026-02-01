"""OAuth authentication providers and utilities.

SECURITY: This module handles OAuth 2.0 authentication flows with
defense-in-depth security measures including:
- CSRF protection (state parameter)
- PKCE (Proof Key for Code Exchange)
- Secure token storage with encryption
- Rate limiting
- Redis-backed state storage for production
"""
from .callback_validator import CallbackURLValidator
from .token_store import SecureTokenStore
from .config import OAuthConfig, OAuthProviderConfig, get_provider_endpoints, ConfigurationError
from .service import OAuthService, OAuthError, OAuthStateError, OAuthProviderError
from .state_store import StateStore, RedisStateStore, InMemoryStateStore, create_state_store
from .rate_limiter import OAuthRateLimiter, RateLimitExceeded

__all__ = [
    # Core components
    "CallbackURLValidator",
    "SecureTokenStore",
    "OAuthConfig",
    "OAuthProviderConfig",
    "get_provider_endpoints",
    "ConfigurationError",
    "OAuthService",
    # Exceptions
    "OAuthError",
    "OAuthStateError",
    "OAuthProviderError",
    "RateLimitExceeded",
    # State storage
    "StateStore",
    "RedisStateStore",
    "InMemoryStateStore",
    "create_state_store",
    # Rate limiting
    "OAuthRateLimiter",
]
