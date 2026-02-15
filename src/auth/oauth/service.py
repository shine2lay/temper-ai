"""OAuth Service Layer.

OAuth 2.0 authorization code flow with PKCE support.
See _service_helpers.py for extracted internal logic.
"""
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from src.auth.oauth._service_helpers import (
    TokenExchangeParams,
)

# Helper functions extracted to reduce class size
from src.auth.oauth._service_helpers import (
    build_authorization_url as _build_authorization_url,
)
from src.auth.oauth._service_helpers import (
    exchange_code as _exchange_code,
)
from src.auth.oauth._service_helpers import (
    fetch_user_info as _fetch_user_info,
)
from src.auth.oauth._service_helpers import (
    generate_code_challenge as _generate_code_challenge,
)
from src.auth.oauth._service_helpers import (
    generate_code_verifier as _generate_code_verifier,
)
from src.auth.oauth._service_helpers import (
    generate_state as _generate_state,
)
from src.auth.oauth._service_helpers import (
    refresh_token as _refresh_token,
)
from src.auth.oauth._service_helpers import (
    revoke_at_provider as _revoke_at_provider,
)
from src.auth.oauth._service_helpers import (
    revoke_tokens as _revoke_tokens,
)
from src.auth.oauth._service_helpers import (
    validate_state as _validate_state,
)
from src.auth.oauth.callback_validator import CallbackURLValidator
from src.auth.oauth.config import OAuthConfig
from src.auth.oauth.rate_limiter import OAuthRateLimiter
from src.auth.oauth.state_store import StateStore, create_state_store
from src.auth.oauth.token_store import SecureTokenStore
from src.shared.constants.durations import (
    TIMEOUT_MEDIUM,
    TIMEOUT_NETWORK_CONNECT,
    TIMEOUT_SHORT,
)
from src.shared.constants.limits import VERY_LARGE_ITEM_LIMIT
from src.shared.utils.exceptions import FrameworkException

logger = logging.getLogger(__name__)

# HTTP client connection limits
MAX_KEEPALIVE_CONNECTIONS = 20  # Maximum number of keepalive connections in pool

# HTTP status codes
HTTP_OK = 200  # Successful response
HTTP_UNAUTHORIZED = 401  # Authentication failed / token expired


class OAuthError(FrameworkException):
    """Base exception for OAuth errors."""

    def __init__(self, message: str, provider: Optional[str] = None):
        self.provider = provider
        super().__init__(message)


class OAuthProviderError(OAuthError):
    """Raised when OAuth provider returns an error."""
    pass


class OAuthStateError(OAuthError):
    """Raised when state validation fails (CSRF protection)."""
    pass


class OAuthService:
    """OAuth service for authorization flows and token management.

    Implements OAuth 2.0 authorization code flow with:
    - CSRF protection (state parameter)
    - PKCE support (code_verifier/code_challenge)
    - Secure token storage
    - Token refresh
    - Provider abstraction

    Example:
        >>> config = OAuthConfig.from_yaml_file(Path("config/oauth.yaml"))
        >>> service = OAuthService(config)
        >>>
        >>> # Initiate OAuth flow
        >>> auth_url, state = service.get_authorization_url("google", "user123")
        >>> # User visits auth_url, redirects to callback with code
        >>>
        >>> # Exchange code for tokens
        >>> tokens = await service.exchange_code_for_tokens(
        ...     provider="google",
        ...     code="auth_code",
        ...     state=state,
        ...     user_id="user123"
        ... )
        >>>
        >>> # Get user info
        >>> user_info = await service.get_user_info("user123", "google")
    """

    def __init__(
        self,
        config: OAuthConfig,
        token_store: Optional[SecureTokenStore] = None,
        callback_validator: Optional[CallbackURLValidator] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        state_store: Optional[StateStore] = None,
        rate_limiter: Optional[OAuthRateLimiter] = None
    ):
        """Initialize OAuth service.

        Args:
            config: OAuth configuration
            token_store: Token storage (default: creates new SecureTokenStore)
            callback_validator: Callback URL validator (default: creates from config)
            http_client: HTTP client for API calls (default: creates new)
            state_store: State storage (default: creates Redis or in-memory store)
            rate_limiter: Rate limiter (default: creates new OAuthRateLimiter)
        """
        self.config = config

        # Initialize token store
        self.token_store = token_store or SecureTokenStore(
            encryption_key=config.token_encryption_key
        )

        # Initialize callback validator
        self.callback_validator = callback_validator or CallbackURLValidator(
            allowed_urls=config.allowed_callback_urls,
            allow_localhost=config.allow_localhost
        )

        # HTTP client for OAuth API calls
        self._http_client = http_client
        self._owns_http_client = http_client is None

        # State storage (Redis-backed for production, falls back to in-memory)
        self._state_store: StateStore = state_store or create_state_store()

        # Rate limiter (protects against abuse)
        self._rate_limiter = rate_limiter or OAuthRateLimiter()

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with security hardening."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                # H-18: Add pool timeout to prevent connection pool exhaustion
                timeout=httpx.Timeout(float(TIMEOUT_MEDIUM), connect=float(TIMEOUT_SHORT), pool=float(TIMEOUT_NETWORK_CONNECT)),
                follow_redirects=False,
                limits=httpx.Limits(
                    max_connections=VERY_LARGE_ITEM_LIMIT,
                    max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS
                ),
                # Verify SSL certificates (enabled by default, but explicit for clarity)
                verify=True
            )
        return self._http_client

    async def close(self) -> None:
        """Clean up resources."""
        if self._owns_http_client and self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        # Close state store connection (e.g., Redis)
        if self._state_store:
            await self._state_store.close()

    def _generate_state(self) -> str:
        """Generate cryptographically secure state token for CSRF protection."""
        return _generate_state()

    def _generate_code_verifier(self) -> str:
        """Generate PKCE code verifier (random string)."""
        return _generate_code_verifier()

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate PKCE code challenge from verifier (SHA256 hash)."""
        return _generate_code_challenge(code_verifier)

    async def get_authorization_url(
        self,
        provider: str,
        user_id: str,
        extra_params: Optional[Dict[str, str]] = None,
        ip_address: Optional[str] = None
    ) -> Tuple[str, str]:
        """Generate OAuth authorization URL with CSRF and PKCE protection."""
        return await _build_authorization_url(
            provider, user_id, self.config, self._state_store,
            self._rate_limiter, extra_params, ip_address,
        )

    async def _validate_state(self, state: str, expected_provider: str) -> Dict[str, Any]:
        """Validate state parameter (CSRF protection)."""
        return await _validate_state(state, expected_provider, self._state_store)

    async def exchange_code_for_tokens(
        self,
        provider: str,
        code: str,
        state: str,
        redirect_uri: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exchange authorization code for access/refresh tokens."""
        client = await self._get_http_client()
        params = TokenExchangeParams(
            provider=provider,
            code=code,
            state=state,
            config=self.config,
            state_store=self._state_store,
            token_store=self.token_store,
            http_client=client,
            rate_limiter=self._rate_limiter,
            redirect_uri=redirect_uri,
            ip_address=ip_address,
        )
        return await _exchange_code(params)

    async def refresh_access_token(
        self,
        user_id: str,
        provider: str
    ) -> Dict[str, Any]:
        """Refresh access token using refresh token."""
        client = await self._get_http_client()
        return await _refresh_token(
            user_id, provider, self.config, self.token_store, client,
        )

    async def get_user_info(
        self,
        user_id: str,
        provider: str,
        auto_refresh: bool = True
    ) -> Dict[str, Any]:
        """Get user information from OAuth provider."""
        client = await self._get_http_client()
        return await _fetch_user_info(
            user_id, provider, self.config, self.token_store,
            client, self._rate_limiter, auto_refresh,
        )

    async def revoke_tokens(self, user_id: str) -> bool:
        """Revoke and delete user's OAuth tokens."""
        client = await self._get_http_client()
        return await _revoke_tokens(
            user_id, self.config, self.token_store, client,
        )

    async def _revoke_at_provider(self, provider: str, tokens: Dict[str, Any]) -> bool:
        """Revoke token at OAuth provider per RFC 7009."""
        client = await self._get_http_client()
        return await _revoke_at_provider(provider, tokens, self.config, client)

    async def cleanup_expired_states(self) -> int:
        """Clean up expired OAuth state tokens.

        Delegates to the StateStore's cleanup_expired() method.

        Returns:
            Number of states cleaned up
        """
        count = await self._state_store.cleanup_expired()
        if count > 0:
            logger.debug(f"Cleaned up {count} expired OAuth state tokens")
        return count
