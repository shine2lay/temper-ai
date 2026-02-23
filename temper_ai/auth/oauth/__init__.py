"""OAuth authentication providers and utilities.

SECURITY: This module handles OAuth 2.0 authentication flows with
defense-in-depth security measures including:
- CSRF protection (state parameter)
- PKCE (Proof Key for Code Exchange)
- Secure token storage with encryption
- Rate limiting
- In-memory state storage
"""

from .callback_validator import CallbackURLValidator
from .config import (
    OAuthConfig,
    OAuthConfigurationError,
    OAuthProviderConfig,
    get_provider_endpoints,
)
from .rate_limiter import OAuthRateLimiter, RateLimitExceeded
from .service import OAuthError, OAuthProviderError, OAuthService, OAuthStateError
from .state_store import InMemoryStateStore, StateStore, create_state_store
from .token_store import SecureTokenStore

__all__ = [
    # Core components
    "CallbackURLValidator",
    "SecureTokenStore",
    "OAuthConfig",
    "OAuthProviderConfig",
    "get_provider_endpoints",
    "OAuthConfigurationError",
    "OAuthService",
    # Exceptions
    "OAuthError",
    "OAuthStateError",
    "OAuthProviderError",
    "RateLimitExceeded",
    # State storage
    "StateStore",
    "InMemoryStateStore",
    "create_state_store",
    # Rate limiting
    "OAuthRateLimiter",
]
