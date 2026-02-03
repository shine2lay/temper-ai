"""OAuth Service Layer.

Implements OAuth 2.0 authorization code flow with PKCE support.
Handles token exchange, refresh, storage, and user info retrieval.

Security Features:
- CSRF protection with state parameter
- PKCE (Proof Key for Code Exchange) for public clients
- Secure token storage with encryption
- Callback URL validation
- Token expiry tracking and refresh
"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import secrets
import hashlib
import base64
import httpx
from urllib.parse import urlencode
import logging

from src.auth.oauth.config import OAuthConfig, OAuthProviderConfig, get_provider_endpoints
from src.auth.oauth.token_store import SecureTokenStore
from src.auth.oauth.callback_validator import CallbackURLValidator
from src.auth.oauth.state_store import StateStore, create_state_store
from src.auth.oauth.rate_limiter import OAuthRateLimiter, RateLimitExceeded

logger = logging.getLogger(__name__)


class OAuthError(Exception):
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
                timeout=httpx.Timeout(30.0, connect=5.0),
                follow_redirects=False,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20
                ),
                # Verify SSL certificates (enabled by default, but explicit for clarity)
                verify=True
            )
        return self._http_client

    async def close(self):
        """Clean up resources."""
        if self._owns_http_client and self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        # Close state store connection (e.g., Redis)
        if self._state_store:
            await self._state_store.close()

    def _generate_state(self) -> str:
        """Generate cryptographically secure state token for CSRF protection."""
        return secrets.token_urlsafe(32)

    def _generate_code_verifier(self) -> str:
        """Generate PKCE code verifier (random string)."""
        return secrets.token_urlsafe(64)

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate PKCE code challenge from verifier (SHA256 hash)."""
        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b'=')
        return challenge.decode('ascii')

    async def get_authorization_url(
        self,
        provider: str,
        user_id: str,
        extra_params: Optional[Dict[str, str]] = None,
        ip_address: Optional[str] = None
    ) -> Tuple[str, str]:
        """Generate OAuth authorization URL with CSRF and PKCE protection.

        Args:
            provider: Provider name (google, github, etc.)
            user_id: User identifier
            extra_params: Additional query parameters
            ip_address: Client IP address (for rate limiting)

        Returns:
            (authorization_url, state) tuple

        Raises:
            OAuthError: If provider not configured
            RateLimitExceeded: If rate limit exceeded
        """
        # Rate limiting (if IP provided)
        if ip_address:
            try:
                self._rate_limiter.check_oauth_init(ip_address, user_id)
            except RateLimitExceeded as e:
                logger.warning(
                    f"Rate limit exceeded for OAuth init: ip={ip_address}, user={user_id}"
                )
                raise
        # Get provider config
        provider_config = self.config.get_provider_config(provider)
        if not provider_config:
            raise OAuthError(
                f"Provider '{provider}' not configured",
                provider=provider
            )

        # Get provider endpoints
        endpoints = get_provider_endpoints(provider_config)

        # Generate state and PKCE parameters
        state = self._generate_state()
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Store state data (TTL: 10 minutes) - async for Redis support
        await self._state_store.set_state(
            state=state,
            data={
                'user_id': user_id,
                'provider': provider,
                'code_verifier': code_verifier,
                'created_at': datetime.utcnow().isoformat()
            },
            ttl_seconds=600  # 10 minutes
        )

        # Build authorization URL
        params = {
            'client_id': provider_config.client_id,
            'redirect_uri': provider_config.redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(provider_config.scopes),
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'access_type': 'offline',  # Request refresh token
            'prompt': 'consent',  # Force consent to get refresh token
        }

        # Add provider-specific parameters
        if provider_config.extra_params:
            params.update(provider_config.extra_params)

        # Add custom parameters
        if extra_params:
            params.update(extra_params)

        auth_url = f"{endpoints['authorization_endpoint']}?{urlencode(params)}"

        logger.info(
            f"Generated OAuth authorization URL for provider={provider}, user={user_id}"
        )

        return auth_url, state

    async def _validate_state(self, state: str, expected_provider: str) -> Dict[str, Any]:
        """Validate state parameter (CSRF protection).

        Args:
            state: State token from callback
            expected_provider: Expected provider name

        Returns:
            State data dict

        Raises:
            OAuthStateError: If state invalid or expired
        """
        # Get and delete state (one-time use) - async for Redis support
        state_data = await self._state_store.get_state(state)

        if not state_data:
            raise OAuthStateError(
                "Invalid or expired state token",
                provider=expected_provider
            )

        # Validate provider
        if state_data['provider'] != expected_provider:
            raise OAuthStateError(
                f"State provider mismatch: expected {expected_provider}, "
                f"got {state_data['provider']}",
                provider=expected_provider
            )

        return state_data

    async def exchange_code_for_tokens(
        self,
        provider: str,
        code: str,
        state: str,
        redirect_uri: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """Exchange authorization code for access/refresh tokens.

        Args:
            provider: Provider name
            code: Authorization code from callback
            state: State token from callback
            redirect_uri: Override redirect URI (must match authorization request)
            ip_address: Client IP address (for rate limiting)

        Returns:
            Token data dict with access_token, refresh_token, expires_in, etc.

        Raises:
            OAuthStateError: If state validation fails
            OAuthProviderError: If token exchange fails
            RateLimitExceeded: If rate limit exceeded
        """
        # Rate limiting (if IP provided)
        if ip_address:
            try:
                self._rate_limiter.check_token_exchange(ip_address)
            except RateLimitExceeded as e:
                logger.warning(
                    f"Rate limit exceeded for token exchange: ip={ip_address}"
                )
                raise

        # Validate state (CSRF protection) - also deletes state (one-time use)
        state_data = await self._validate_state(state, provider)
        user_id = state_data['user_id']
        code_verifier = state_data['code_verifier']

        # Get provider config
        provider_config = self.config.get_provider_config(provider)
        if not provider_config:
            raise OAuthError(f"Provider '{provider}' not configured", provider=provider)

        # Get token endpoint
        endpoints = get_provider_endpoints(provider_config)
        token_endpoint = endpoints['token_endpoint']

        # Prepare token exchange request
        token_data = {
            'client_id': provider_config.client_id,
            'client_secret': provider_config.client_secret,
            'code': code,
            'redirect_uri': redirect_uri or provider_config.redirect_uri,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,  # PKCE
        }

        # Exchange code for tokens
        client = await self._get_http_client()

        try:
            response = await client.post(
                token_endpoint,
                data=token_data,
                headers={'Accept': 'application/json'}
            )

            if response.status_code != 200:
                error_detail = response.text
                raise OAuthProviderError(
                    f"Token exchange failed: {response.status_code} - {error_detail}",
                    provider=provider
                )

            tokens = response.json()

            # Validate response
            if 'access_token' not in tokens:
                raise OAuthProviderError(
                    "Token response missing access_token",
                    provider=provider
                )

            # Store tokens securely
            expires_in = tokens.get('expires_in', self.config.token_expiry_seconds)
            self.token_store.store_token(
                user_id=user_id,
                token_data=tokens,
                expires_in=expires_in
            )

            # Note: State already deleted by _validate_state (one-time use)

            logger.info(
                f"Successfully exchanged OAuth code for tokens: provider={provider}, user={user_id}"
            )

            return tokens

        except httpx.HTTPError as e:
            raise OAuthProviderError(
                f"HTTP error during token exchange: {e}",
                provider=provider
            ) from e

    async def refresh_access_token(
        self,
        user_id: str,
        provider: str
    ) -> Dict[str, Any]:
        """Refresh access token using refresh token.

        Args:
            user_id: User identifier
            provider: Provider name

        Returns:
            New token data

        Raises:
            OAuthError: If refresh fails or no refresh token
        """
        # Get current tokens
        tokens = self.token_store.retrieve_token(user_id)
        if not tokens:
            raise OAuthError(
                f"No tokens found for user {user_id}",
                provider=provider
            )

        refresh_token = tokens.get('refresh_token')
        if not refresh_token:
            raise OAuthError(
                "No refresh token available",
                provider=provider
            )

        # Get provider config
        provider_config = self.config.get_provider_config(provider)
        if not provider_config:
            raise OAuthError(f"Provider '{provider}' not configured", provider=provider)

        # Get token endpoint
        endpoints = get_provider_endpoints(provider_config)
        token_endpoint = endpoints['token_endpoint']

        # Refresh tokens
        refresh_data = {
            'client_id': provider_config.client_id,
            'client_secret': provider_config.client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }

        client = await self._get_http_client()

        try:
            response = await client.post(
                token_endpoint,
                data=refresh_data,
                headers={'Accept': 'application/json'}
            )

            if response.status_code != 200:
                raise OAuthProviderError(
                    f"Token refresh failed: {response.status_code}",
                    provider=provider
                )

            new_tokens = response.json()

            # Store new tokens (preserve refresh token if not returned)
            if 'refresh_token' not in new_tokens:
                new_tokens['refresh_token'] = refresh_token

            expires_in = new_tokens.get('expires_in', self.config.token_expiry_seconds)
            self.token_store.store_token(
                user_id=user_id,
                token_data=new_tokens,
                expires_in=expires_in
            )

            logger.info(
                f"Refreshed access token: provider={provider}, user={user_id}"
            )

            return new_tokens

        except httpx.HTTPError as e:
            raise OAuthProviderError(
                f"HTTP error during token refresh: {e}",
                provider=provider
            ) from e

    async def get_user_info(
        self,
        user_id: str,
        provider: str,
        auto_refresh: bool = True
    ) -> Dict[str, Any]:
        """Get user information from OAuth provider.

        Args:
            user_id: User identifier
            provider: Provider name
            auto_refresh: Auto-refresh expired tokens

        Returns:
            User info dict (provider-specific format)

        Raises:
            OAuthError: If user info retrieval fails
            RateLimitExceeded: If rate limit exceeded
        """
        # Rate limiting
        try:
            self._rate_limiter.check_userinfo(user_id)
        except RateLimitExceeded as e:
            logger.warning(
                f"Rate limit exceeded for user info: user={user_id}"
            )
            raise

        # Get tokens
        tokens = self.token_store.retrieve_token(user_id)
        if not tokens:
            raise OAuthError(
                f"No tokens found for user {user_id}",
                provider=provider
            )

        access_token = tokens.get('access_token')
        if not access_token:
            raise OAuthError(
                "No access token available",
                provider=provider
            )

        # Get provider config
        provider_config = self.config.get_provider_config(provider)
        if not provider_config:
            raise OAuthError(f"Provider '{provider}' not configured", provider=provider)

        # Get userinfo endpoint
        endpoints = get_provider_endpoints(provider_config)
        userinfo_endpoint = endpoints.get('userinfo_endpoint')
        if not userinfo_endpoint:
            raise OAuthError(
                f"Provider '{provider}' does not have userinfo endpoint configured",
                provider=provider
            )

        # Get user info
        client = await self._get_http_client()

        try:
            response = await client.get(
                userinfo_endpoint,
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Accept': 'application/json'
                }
            )

            # Handle token expiration
            if response.status_code == 401 and auto_refresh:
                logger.info(
                    f"Access token expired, refreshing: provider={provider}, user={user_id}"
                )
                await self.refresh_access_token(user_id, provider)
                # Retry with new token
                return await self.get_user_info(user_id, provider, auto_refresh=False)

            if response.status_code != 200:
                raise OAuthProviderError(
                    f"User info request failed: {response.status_code}",
                    provider=provider
                )

            user_info = response.json()

            logger.info(
                f"Retrieved user info: provider={provider}, user={user_id}"
            )

            return user_info

        except httpx.HTTPError as e:
            raise OAuthProviderError(
                f"HTTP error during user info retrieval: {e}",
                provider=provider
            ) from e

    async def revoke_tokens(self, user_id: str) -> bool:
        """Revoke and delete user's OAuth tokens.

        Attempts provider-level revocation (RFC 7009) before deleting
        tokens locally. Provider revocation is best-effort: if it fails,
        local deletion still proceeds.

        Args:
            user_id: User identifier

        Returns:
            True if tokens were deleted locally
        """
        tokens = self.token_store.retrieve_token(user_id)
        if not tokens:
            logger.info(f"No tokens to revoke for user={user_id}")
            return False

        # Attempt provider-level revocation (best-effort)
        provider = tokens.get('provider')
        if provider:
            try:
                await self._revoke_at_provider(provider, tokens)
            except Exception as e:
                logger.warning(
                    f"Provider revocation failed (continuing with local deletion): "
                    f"provider={provider}, user={user_id}, error={e}"
                )

        deleted = self.token_store.delete_token(user_id)
        if deleted:
            logger.info(f"Revoked OAuth tokens for user={user_id}")

        return deleted

    async def _revoke_at_provider(
        self, provider: str, tokens: Dict[str, Any]
    ) -> bool:
        """Revoke token at OAuth provider per RFC 7009.

        Best-effort: returns False on failure, does not raise.
        """
        try:
            provider_config = self.config.get_provider_config(provider)
        except Exception:
            return False

        endpoints = get_provider_endpoints(provider_config)
        revocation_endpoint = endpoints.get('revocation_endpoint')
        if not revocation_endpoint:
            return False

        token_to_revoke = tokens.get('refresh_token') or tokens.get('access_token')
        if not token_to_revoke:
            return False

        client = await self._get_http_client()
        try:
            response = await client.post(
                revocation_endpoint,
                data={
                    'token': token_to_revoke,
                    'client_id': provider_config.client_id,
                    'client_secret': provider_config.client_secret,
                },
                timeout=10.0,
            )
            if response.status_code == 200:
                logger.info(f"Token revoked at provider: {provider}")
                return True
            logger.warning(
                f"Provider revocation returned {response.status_code}: {provider}"
            )
        except httpx.HTTPError as e:
            logger.warning(f"Provider revocation HTTP error: {provider}: {e}")
        return False

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
