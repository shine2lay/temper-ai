"""OAuth authentication providers and utilities.

SECURITY: This module handles OAuth 2.0 authentication flows with
defense-in-depth security measures.
"""
from .callback_validator import CallbackURLValidator
from .token_store import SecureTokenStore
from .config import OAuthConfig, OAuthProviderConfig, get_provider_endpoints, ConfigurationError
from .service import OAuthService, OAuthError, OAuthStateError, OAuthProviderError

__all__ = [
    "CallbackURLValidator",
    "SecureTokenStore",
    "OAuthConfig",
    "OAuthProviderConfig",
    "get_provider_endpoints",
    "ConfigurationError",
    "OAuthService",
    "OAuthError",
    "OAuthStateError",
    "OAuthProviderError",
]
