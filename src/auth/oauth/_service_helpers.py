"""Helper functions for OAuthService.

Extracted from OAuthService to keep the class below 500 lines.
These are internal implementation details and should not be used directly.
"""
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx

from src.auth.constants import (
    ERROR_PROVIDER_NOT_CONFIGURED,
    ERROR_PROVIDER_PREFIX,
    FIELD_ACCESS_TOKEN,
    FIELD_CLIENT_ID,
    FIELD_CLIENT_SECRET,
    FIELD_CODE_VERIFIER,
    FIELD_PROVIDER,
    HEADER_ACCEPT,
    HEADER_CONTENT_TYPE_JSON,
    LOG_USER_SEPARATOR,
)
from src.auth.oauth.config import (
    ENDPOINT_AUTHORIZATION,
    ENDPOINT_REVOCATION,
    ENDPOINT_TOKEN,
    ENDPOINT_USERINFO,
    OAuthConfig,
    get_provider_endpoints,
)
from src.auth.oauth.rate_limiter import RateLimitExceeded
from src.auth.oauth.token_store import SecureTokenStore
from src.constants.durations import SECONDS_PER_10_MINUTES, TIMEOUT_NETWORK_CONNECT
from src.constants.sizes import TOKEN_BYTES_NONCE, TOKEN_BYTES_STATE

logger = logging.getLogger(__name__)

# HTTP status codes
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401


def generate_state() -> str:
    """Generate cryptographically secure state token for CSRF protection."""
    return secrets.token_urlsafe(TOKEN_BYTES_STATE)


def generate_code_verifier() -> str:
    """Generate PKCE code verifier (random string)."""
    return secrets.token_urlsafe(TOKEN_BYTES_NONCE)


def generate_code_challenge(code_verifier: str) -> str:
    """Generate PKCE code challenge from verifier (SHA256 hash)."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b'=')
    return challenge.decode('ascii')


def _build_authorization_params(
    provider_config: Any, state: str, code_challenge: str, extra_params: Optional[Dict[str, str]]
) -> Dict[str, str]:
    """Build OAuth authorization parameters.

    Args:
        provider_config: Provider configuration
        state: State parameter
        code_challenge: PKCE code challenge
        extra_params: Additional parameters

    Returns:
        Dict of authorization parameters
    """
    params = {
        'client_id': provider_config.client_id,
        'redirect_uri': provider_config.redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(provider_config.scopes),
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'access_type': 'offline',
        'prompt': 'consent',
    }

    if provider_config.extra_params:
        params.update(provider_config.extra_params)

    if extra_params:
        params.update(extra_params)

    return params


async def build_authorization_url(
    provider: str,
    user_id: str,
    config: OAuthConfig,
    state_store: Any,
    rate_limiter: Any,
    extra_params: Optional[Dict[str, str]] = None,
    ip_address: Optional[str] = None,
) -> Tuple[str, str]:
    """Generate OAuth authorization URL with CSRF and PKCE protection.

    Args:
        provider: Provider name (google, github, etc.)
        user_id: User identifier
        config: OAuth configuration
        state_store: State storage backend
        rate_limiter: Rate limiter instance
        extra_params: Additional query parameters
        ip_address: Client IP address (for rate limiting)

    Returns:
        (authorization_url, state) tuple

    Raises:
        OAuthError: If provider not configured
        RateLimitExceeded: If rate limit exceeded
    """
    from src.auth.oauth.service import OAuthError

    # Rate limiting
    if ip_address:
        try:
            rate_limiter.check_oauth_init(ip_address, user_id)
        except RateLimitExceeded:
            logger.warning(
                f"Rate limit exceeded for OAuth init: ip={ip_address}{LOG_USER_SEPARATOR}{user_id}"
            )
            raise

    # Get provider config and endpoints
    provider_config = config.get_provider_config(provider)
    if not provider_config:
        raise OAuthError(
            f"{ERROR_PROVIDER_PREFIX}{provider}{ERROR_PROVIDER_NOT_CONFIGURED}",
            provider=provider
        )
    endpoints = get_provider_endpoints(provider_config)

    # Generate PKCE and state
    state = generate_state()
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    # Store state data
    await state_store.set_state(
        state=state,
        data={
            'user_id': user_id,
            FIELD_PROVIDER: provider,
            FIELD_CODE_VERIFIER: code_verifier,
            'created_at': datetime.now(timezone.utc).isoformat()
        },
        ttl_seconds=SECONDS_PER_10_MINUTES
    )

    # Build and return URL
    params = _build_authorization_params(provider_config, state, code_challenge, extra_params)
    auth_url = f"{endpoints[ENDPOINT_AUTHORIZATION]}?{urlencode(params)}"

    logger.info(
        f"Generated OAuth authorization URL for provider={provider}{LOG_USER_SEPARATOR}{user_id}"
    )

    return auth_url, state


async def validate_state(
    state: str,
    expected_provider: str,
    state_store: Any,
) -> Dict[str, Any]:
    """Validate state parameter (CSRF protection).

    Args:
        state: State token from callback
        expected_provider: Expected provider name
        state_store: State storage backend

    Returns:
        State data dict

    Raises:
        OAuthStateError: If state invalid or expired
    """
    from src.auth.oauth.service import OAuthStateError

    state_data: Optional[Dict[str, Any]] = await state_store.get_state(state)

    if not state_data:
        raise OAuthStateError(
            "Invalid or expired state token",
            provider=expected_provider
        )

    if state_data[FIELD_PROVIDER] != expected_provider:
        raise OAuthStateError(
            f"State provider mismatch: expected {expected_provider}, "
            f"got {state_data[FIELD_PROVIDER]}",
            provider=expected_provider
        )

    return state_data


async def _perform_token_exchange(
    http_client: httpx.AsyncClient,
    token_endpoint: str,
    token_data: Dict[str, str],
    provider: str,
) -> Dict[str, Any]:
    """Perform HTTP request to exchange code for tokens.

    Args:
        http_client: HTTP client
        token_endpoint: Token endpoint URL
        token_data: Request payload
        provider: Provider name

    Returns:
        Token data from provider

    Raises:
        OAuthProviderError: If exchange fails
    """
    from src.auth.oauth.service import OAuthProviderError

    try:
        response = await http_client.post(
            token_endpoint,
            data=token_data,
            headers={HEADER_ACCEPT: HEADER_CONTENT_TYPE_JSON}
        )

        if response.status_code != HTTP_OK:
            error_detail = response.text
            raise OAuthProviderError(
                f"Token exchange failed: {response.status_code} - {error_detail}",
                provider=provider
            )

        tokens: Dict[str, Any] = response.json()

        if FIELD_ACCESS_TOKEN not in tokens:
            raise OAuthProviderError(
                "Token response missing access_token",
                provider=provider
            )

        return tokens

    except httpx.HTTPError as e:
        raise OAuthProviderError(
            f"HTTP error during token exchange: {e}",
            provider=provider
        ) from e


async def exchange_code(
    provider: str,
    code: str,
    state: str,
    config: OAuthConfig,
    state_store: Any,
    token_store: SecureTokenStore,
    http_client: httpx.AsyncClient,
    rate_limiter: Any,
    redirect_uri: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchange authorization code for access/refresh tokens.

    Args:
        provider: Provider name
        code: Authorization code from callback
        state: State token from callback
        config: OAuth configuration
        state_store: State storage backend
        token_store: Token storage backend
        http_client: HTTP client for API calls
        rate_limiter: Rate limiter instance
        redirect_uri: Override redirect URI
        ip_address: Client IP address (for rate limiting)

    Returns:
        Token data dict

    Raises:
        OAuthStateError: If state validation fails
        OAuthProviderError: If token exchange fails
        RateLimitExceeded: If rate limit exceeded
    """
    from src.auth.oauth.service import OAuthError

    # Rate limiting
    if ip_address:
        try:
            rate_limiter.check_token_exchange(ip_address)
        except RateLimitExceeded:
            logger.warning(f"Rate limit exceeded for token exchange: ip={ip_address}")
            raise

    # Validate state and get provider config
    state_data = await validate_state(state, provider, state_store)
    user_id = state_data['user_id']
    code_verifier = state_data[FIELD_CODE_VERIFIER]

    provider_config = config.get_provider_config(provider)
    if not provider_config:
        raise OAuthError(f"{ERROR_PROVIDER_PREFIX}{provider}{ERROR_PROVIDER_NOT_CONFIGURED}", provider=provider)

    endpoints = get_provider_endpoints(provider_config)
    token_endpoint = endpoints[ENDPOINT_TOKEN]
    if not token_endpoint:
        raise OAuthError(f"Token endpoint not configured for provider '{provider}'", provider=provider)

    # Prepare and execute token exchange
    token_data = {
        FIELD_CLIENT_ID: provider_config.client_id,
        FIELD_CLIENT_SECRET: provider_config.client_secret,
        'code': code,
        'redirect_uri': redirect_uri or provider_config.redirect_uri,
        'grant_type': 'authorization_code',
        FIELD_CODE_VERIFIER: code_verifier,
    }

    tokens = await _perform_token_exchange(http_client, token_endpoint, token_data, provider)

    # Store tokens
    expires_in = tokens.get('expires_in', config.token_expiry_seconds)
    token_store.store_token(user_id=user_id, token_data=tokens, expires_in=expires_in)

    logger.info(
        f"Successfully exchanged OAuth code for tokens: provider={provider}{LOG_USER_SEPARATOR}{user_id}"
    )

    tokens['_flow_user_id'] = user_id
    return tokens


async def _get_refresh_token_and_endpoint(
    user_id: str, provider: str, config: OAuthConfig, token_store: SecureTokenStore
) -> tuple:
    """Get refresh token and endpoint for token refresh.

    Args:
        user_id: User identifier
        provider: Provider name
        config: OAuth configuration
        token_store: Token storage

    Returns:
        Tuple of (refresh_token_val, token_endpoint, provider_config)

    Raises:
        OAuthError: If tokens or endpoint not found
    """
    from src.auth.oauth.service import OAuthError

    tokens = token_store.retrieve_token(user_id)
    if not tokens:
        raise OAuthError(f"No tokens found for user {user_id}", provider=provider)

    refresh_token_val = tokens.get('refresh_token')
    if not refresh_token_val:
        raise OAuthError("No refresh token available", provider=provider)

    provider_config = config.get_provider_config(provider)
    if not provider_config:
        raise OAuthError(f"{ERROR_PROVIDER_PREFIX}{provider}{ERROR_PROVIDER_NOT_CONFIGURED}", provider=provider)

    endpoints = get_provider_endpoints(provider_config)
    token_endpoint = endpoints[ENDPOINT_TOKEN]
    if not token_endpoint:
        raise OAuthError(f"Token endpoint not configured for provider '{provider}'", provider=provider)

    return refresh_token_val, token_endpoint, provider_config


async def refresh_token(
    user_id: str,
    provider: str,
    config: OAuthConfig,
    token_store: SecureTokenStore,
    http_client: httpx.AsyncClient,
) -> Dict[str, Any]:
    """Refresh access token using refresh token.

    Args:
        user_id: User identifier
        provider: Provider name
        config: OAuth configuration
        token_store: Token storage backend
        http_client: HTTP client for API calls

    Returns:
        New token data

    Raises:
        OAuthError: If refresh fails or no refresh token
    """
    from src.auth.oauth.service import OAuthProviderError

    # Get refresh token and endpoint
    refresh_token_val, token_endpoint, provider_config = await _get_refresh_token_and_endpoint(
        user_id, provider, config, token_store
    )

    # Prepare refresh request
    refresh_data = {
        'client_id': provider_config.client_id,
        'client_secret': provider_config.client_secret,
        'refresh_token': refresh_token_val,
        'grant_type': 'refresh_token',
    }

    try:
        response = await http_client.post(
            token_endpoint,
            data=refresh_data,
            headers={"Accept": "application/json"}
        )

        if response.status_code != HTTP_OK:
            raise OAuthProviderError(
                f"Token refresh failed: {response.status_code}",
                provider=provider
            )

        new_tokens: Dict[str, Any] = response.json()

        # Preserve refresh token if not returned
        if 'refresh_token' not in new_tokens:
            new_tokens['refresh_token'] = refresh_token_val

        # Store new tokens
        expires_in = new_tokens.get('expires_in', config.token_expiry_seconds)
        token_store.store_token(user_id=user_id, token_data=new_tokens, expires_in=expires_in)

        logger.info(f"Refreshed access token: provider={provider}{LOG_USER_SEPARATOR}{user_id}")
        return new_tokens

    except httpx.HTTPError as e:
        raise OAuthProviderError(
            f"HTTP error during token refresh: {e}",
            provider=provider
        ) from e


async def _get_access_token_and_endpoint(
    user_id: str, provider: str, config: OAuthConfig, token_store: SecureTokenStore
) -> tuple:
    """Get access token and userinfo endpoint.

    Args:
        user_id: User identifier
        provider: Provider name
        config: OAuth configuration
        token_store: Token storage

    Returns:
        Tuple of (access_token, userinfo_endpoint)

    Raises:
        OAuthError: If token or endpoint not found
    """
    from src.auth.oauth.service import OAuthError

    tokens = token_store.retrieve_token(user_id)
    if not tokens:
        raise OAuthError(f"No tokens found for user {user_id}", provider=provider)

    access_token = tokens.get('access_token')
    if not access_token:
        raise OAuthError("No access token available", provider=provider)

    provider_config = config.get_provider_config(provider)
    if not provider_config:
        raise OAuthError(f"{ERROR_PROVIDER_PREFIX}{provider}{ERROR_PROVIDER_NOT_CONFIGURED}", provider=provider)

    endpoints = get_provider_endpoints(provider_config)
    userinfo_endpoint = endpoints.get(ENDPOINT_USERINFO)
    if not userinfo_endpoint:
        raise OAuthError(
            f"Provider '{provider}' does not have userinfo endpoint configured",
            provider=provider
        )

    return access_token, userinfo_endpoint


async def fetch_user_info(
    user_id: str,
    provider: str,
    config: OAuthConfig,
    token_store: SecureTokenStore,
    http_client: httpx.AsyncClient,
    rate_limiter: Any,
    auto_refresh: bool = True,
) -> Dict[str, Any]:
    """Get user information from OAuth provider.

    Args:
        user_id: User identifier
        provider: Provider name
        config: OAuth configuration
        token_store: Token storage backend
        http_client: HTTP client for API calls
        rate_limiter: Rate limiter instance
        auto_refresh: Auto-refresh expired tokens

    Returns:
        User info dict

    Raises:
        OAuthError: If user info retrieval fails
        RateLimitExceeded: If rate limit exceeded
    """
    from src.auth.oauth.service import OAuthProviderError

    # Rate limiting
    try:
        rate_limiter.check_userinfo(user_id)
    except RateLimitExceeded:
        logger.warning(f"Rate limit exceeded for user info: user={user_id}")
        raise

    # Get token and endpoint
    access_token, userinfo_endpoint = await _get_access_token_and_endpoint(
        user_id, provider, config, token_store
    )

    try:
        response = await http_client.get(
            userinfo_endpoint,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )

        # Handle token expiration with auto-refresh
        if response.status_code == HTTP_UNAUTHORIZED and auto_refresh:
            logger.info(f"Access token expired, refreshing: provider={provider}{LOG_USER_SEPARATOR}{user_id}")
            await refresh_token(user_id, provider, config, token_store, http_client)
            return await fetch_user_info(
                user_id, provider, config, token_store, http_client, rate_limiter,
                auto_refresh=False
            )

        if response.status_code != HTTP_OK:
            raise OAuthProviderError(
                f"User info request failed: {response.status_code}",
                provider=provider
            )

        user_info: Dict[str, Any] = response.json()
        logger.info(f"Retrieved user info: provider={provider}{LOG_USER_SEPARATOR}{user_id}")

        return user_info

    except httpx.HTTPError as e:
        raise OAuthProviderError(
            f"HTTP error during user info retrieval: {e}",
            provider=provider
        ) from e


async def revoke_tokens(
    user_id: str,
    config: OAuthConfig,
    token_store: SecureTokenStore,
    http_client: httpx.AsyncClient,
) -> bool:
    """Revoke and delete user's OAuth tokens.

    Args:
        user_id: User identifier
        config: OAuth configuration
        token_store: Token storage backend
        http_client: HTTP client for API calls

    Returns:
        True if tokens were deleted locally
    """
    from src.auth.oauth.service import OAuthError

    tokens = token_store.retrieve_token(user_id)
    if not tokens:
        logger.info(f"No tokens to revoke for user={user_id}")
        return False

    # Attempt provider-level revocation (best-effort)
    provider = tokens.get('provider')
    if provider:
        try:
            await revoke_at_provider(provider, tokens, config, http_client)
        except (httpx.HTTPError, OAuthError, KeyError, AttributeError) as e:
            logger.warning(
                f"Provider revocation failed (continuing with local deletion): "
                f"provider={provider}{LOG_USER_SEPARATOR}{user_id}, error={e}"
            )

    deleted = token_store.delete_token(user_id)
    if deleted:
        logger.info(f"Revoked OAuth tokens for user={user_id}")

    return deleted


async def revoke_at_provider(
    provider: str,
    tokens: Dict[str, Any],
    config: OAuthConfig,
    http_client: httpx.AsyncClient,
) -> bool:
    """Revoke token at OAuth provider per RFC 7009.

    Best-effort: returns False on failure, does not raise.
    """
    try:
        provider_config = config.get_provider_config(provider)
    except (AttributeError, KeyError, TypeError):
        return False

    if not provider_config:
        return False

    endpoints = get_provider_endpoints(provider_config)
    revocation_endpoint = endpoints.get(ENDPOINT_REVOCATION)
    if not revocation_endpoint:
        return False

    token_to_revoke = tokens.get('refresh_token') or tokens.get('access_token')
    if not token_to_revoke:
        return False

    try:
        response = await http_client.post(
            revocation_endpoint,
            data={
                'token': token_to_revoke,
                'client_id': provider_config.client_id,
                'client_secret': provider_config.client_secret,
            },
            timeout=float(TIMEOUT_NETWORK_CONNECT),
        )
        if response.status_code == HTTP_OK:
            logger.info(f"Token revoked at provider: {provider}")
            return True
        logger.warning(
            f"Provider revocation returned {response.status_code}: {provider}"
        )
    except httpx.HTTPError as e:
        logger.warning(f"Provider revocation HTTP error: {provider}: {e}")
    return False
