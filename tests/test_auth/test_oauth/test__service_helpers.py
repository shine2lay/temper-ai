"""Comprehensive tests for OAuth service helper functions.

Tests cover:
- URL building utilities
- Token parsing utilities
- Error formatting
- Helper function edge cases
"""
import base64
import hashlib
import pytest
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch
import httpx

from src.auth.oauth._service_helpers import (
    generate_state,
    generate_code_verifier,
    generate_code_challenge,
    build_authorization_url,
    validate_state,
    exchange_code,
    refresh_token,
    fetch_user_info,
    revoke_tokens,
    revoke_at_provider,
    TokenExchangeParams,
    HTTP_OK,
    HTTP_UNAUTHORIZED,
)
from src.auth.oauth.config import OAuthConfig, OAuthProviderConfig
from src.auth.oauth.rate_limiter import RateLimitExceeded, OAuthRateLimiter
from src.auth.oauth.service import OAuthError, OAuthProviderError, OAuthStateError
from src.auth.oauth.token_store import SecureTokenStore
from src.constants.durations import SECONDS_PER_10_MINUTES


# ==================== FIXTURES ====================


@pytest.fixture
def oauth_config():
    """Create OAuth configuration."""
    return OAuthConfig(
        providers=[
            OAuthProviderConfig(
                provider="google",
                client_id="test_client_id",
                client_secret="test_client_secret",
                redirect_uri="https://app.example.com/callback",
                scopes=["openid", "email", "profile"],
            )
        ],
        allowed_callback_urls=["https://app.example.com/callback"],
        token_encryption_key="test_encryption_key_32_chars",
        state_secret_key="test_state_secret_32_chars",
    )


@pytest.fixture
def mock_state_store():
    """Mock state store."""
    store = AsyncMock()
    return store


@pytest.fixture
def token_store():
    """Create secure token store."""
    from cryptography.fernet import Fernet
    return SecureTokenStore(encryption_key=Fernet.generate_key().decode())


@pytest.fixture
def rate_limiter():
    """Create rate limiter."""
    return OAuthRateLimiter()


@pytest.fixture
def mock_http_client():
    """Mock HTTP client."""
    return AsyncMock(spec=httpx.AsyncClient)


# ==================== STATE/VERIFIER GENERATION TESTS ====================


def test_generate_state_length():
    """Test state token has correct length."""
    state = generate_state()
    # URL-safe base64 encoding of 32 bytes -> ~43 chars
    assert len(state) >= 40
    assert len(state) <= 50


def test_generate_state_unique():
    """Test state tokens are unique."""
    states = [generate_state() for _ in range(100)]
    # All should be unique
    assert len(set(states)) == 100


def test_generate_state_url_safe():
    """Test state token is URL-safe."""
    state = generate_state()
    # Should only contain URL-safe characters
    assert all(c.isalnum() or c in "-_" for c in state)


def test_generate_code_verifier_length():
    """Test code verifier has correct length."""
    verifier = generate_code_verifier()
    # URL-safe base64 of 64 bytes -> ~86 chars
    assert len(verifier) >= 80
    assert len(verifier) <= 90


def test_generate_code_verifier_unique():
    """Test code verifiers are unique."""
    verifiers = [generate_code_verifier() for _ in range(100)]
    assert len(set(verifiers)) == 100


def test_generate_code_verifier_url_safe():
    """Test code verifier is URL-safe."""
    verifier = generate_code_verifier()
    assert all(c.isalnum() or c in "-_" for c in verifier)


def test_generate_code_challenge_format():
    """Test code challenge is base64url-encoded SHA256."""
    verifier = "test_verifier_123"
    challenge = generate_code_challenge(verifier)

    # Manually compute expected challenge
    expected_digest = hashlib.sha256(verifier.encode()).digest()
    expected_challenge = base64.urlsafe_b64encode(expected_digest).rstrip(b'=').decode('ascii')

    assert challenge == expected_challenge


def test_generate_code_challenge_deterministic():
    """Test same verifier produces same challenge."""
    verifier = "test_verifier_123"
    challenge1 = generate_code_challenge(verifier)
    challenge2 = generate_code_challenge(verifier)

    assert challenge1 == challenge2


def test_generate_code_challenge_different_verifiers():
    """Test different verifiers produce different challenges."""
    challenge1 = generate_code_challenge("verifier1")
    challenge2 = generate_code_challenge("verifier2")

    assert challenge1 != challenge2


# ==================== BUILD AUTHORIZATION URL TESTS ====================


@pytest.mark.asyncio
async def test_build_authorization_url_success(oauth_config, mock_state_store, rate_limiter):
    """Test building authorization URL."""
    auth_url, state = await build_authorization_url(
        provider="google",
        user_id="test_user",
        config=oauth_config,
        state_store=mock_state_store,
        rate_limiter=rate_limiter,
        ip_address="192.168.1.1",
    )

    assert "https://accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "client_id=test_client_id" in auth_url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcallback" in auth_url
    assert "response_type=code" in auth_url
    assert "scope=openid+email+profile" in auth_url
    assert f"state={state}" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url

    # Verify state was stored
    mock_state_store.set_state.assert_called_once()


@pytest.mark.asyncio
async def test_build_authorization_url_stores_state_data(oauth_config, mock_state_store, rate_limiter):
    """Test authorization URL stores state data correctly."""
    auth_url, state = await build_authorization_url(
        provider="google",
        user_id="test_user",
        config=oauth_config,
        state_store=mock_state_store,
        rate_limiter=rate_limiter,
    )

    # Check state data
    call_args = mock_state_store.set_state.call_args
    assert call_args[1]['state'] == state
    assert call_args[1]['data']['user_id'] == "test_user"
    assert call_args[1]['data']['provider'] == "google"
    assert 'code_verifier' in call_args[1]['data']
    assert call_args[1]['ttl_seconds'] == SECONDS_PER_10_MINUTES


@pytest.mark.asyncio
async def test_build_authorization_url_extra_params(oauth_config, mock_state_store, rate_limiter):
    """Test authorization URL with extra parameters."""
    auth_url, state = await build_authorization_url(
        provider="google",
        user_id="test_user",
        config=oauth_config,
        state_store=mock_state_store,
        rate_limiter=rate_limiter,
        extra_params={"hd": "example.com"},
    )

    assert "hd=example.com" in auth_url


@pytest.mark.asyncio
async def test_build_authorization_url_rate_limited(oauth_config, mock_state_store, rate_limiter):
    """Test authorization URL respects rate limiting."""
    # User limit is 5 per minute (lower than IP limit of 10)
    # Fill user limit with 5 requests
    for i in range(5):
        await build_authorization_url(
            provider="google",
            user_id="test_user",
            config=oauth_config,
            state_store=mock_state_store,
            rate_limiter=rate_limiter,
            ip_address=f"192.168.1.{i}",  # Different IPs to avoid IP limit
        )

    # 6th request should be rate limited (user limit)
    with pytest.raises(RateLimitExceeded):
        await build_authorization_url(
            provider="google",
            user_id="test_user",
            config=oauth_config,
            state_store=mock_state_store,
            rate_limiter=rate_limiter,
            ip_address="192.168.1.99",
        )


@pytest.mark.asyncio
async def test_build_authorization_url_provider_not_configured(oauth_config, mock_state_store, rate_limiter):
    """Test error when provider not configured."""
    with pytest.raises(OAuthError, match="Provider 'github' not configured"):
        await build_authorization_url(
            provider="github",  # Not in config
            user_id="test_user",
            config=oauth_config,
            state_store=mock_state_store,
            rate_limiter=rate_limiter,
        )


# ==================== VALIDATE STATE TESTS ====================


@pytest.mark.asyncio
async def test_validate_state_success(mock_state_store):
    """Test successful state validation."""
    state_data = {
        "user_id": "test_user",
        "provider": "google",
        "code_verifier": "verifier123",
    }
    mock_state_store.get_state.return_value = state_data

    result = await validate_state("state123", "google", mock_state_store)

    assert result == state_data
    mock_state_store.get_state.assert_called_once_with("state123")


@pytest.mark.asyncio
async def test_validate_state_not_found(mock_state_store):
    """Test validation fails when state not found."""
    mock_state_store.get_state.return_value = None

    with pytest.raises(OAuthStateError, match="Invalid or expired state token"):
        await validate_state("invalid_state", "google", mock_state_store)


@pytest.mark.asyncio
async def test_validate_state_provider_mismatch(mock_state_store):
    """Test validation fails on provider mismatch."""
    state_data = {
        "user_id": "test_user",
        "provider": "github",  # Different provider
        "code_verifier": "verifier123",
    }
    mock_state_store.get_state.return_value = state_data

    with pytest.raises(OAuthStateError, match="State provider mismatch"):
        await validate_state("state123", "google", mock_state_store)


# ==================== EXCHANGE CODE TESTS ====================


@pytest.mark.asyncio
async def test_exchange_code_success(oauth_config, mock_state_store, token_store, mock_http_client, rate_limiter):
    """Test successful code exchange."""
    # Mock state validation
    mock_state_store.get_state.return_value = {
        "user_id": "test_user",
        "provider": "google",
        "code_verifier": "verifier123",
    }

    # Mock HTTP response
    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_response.json.return_value = {
        "access_token": "access_token_123",
        "refresh_token": "refresh_token_123",
        "expires_in": 3600,
    }
    mock_http_client.post.return_value = mock_response

    result = await exchange_code(
        TokenExchangeParams(
            provider="google",
            code="auth_code_123",
            state="state_abc",
            config=oauth_config,
            state_store=mock_state_store,
            token_store=token_store,
            http_client=mock_http_client,
            rate_limiter=rate_limiter,
            ip_address="192.168.1.1",
        )
    )

    assert result["access_token"] == "access_token_123"
    assert result["refresh_token"] == "refresh_token_123"
    assert result["_flow_user_id"] == "test_user"


@pytest.mark.asyncio
async def test_exchange_code_token_stored(oauth_config, mock_state_store, token_store, mock_http_client, rate_limiter):
    """Test code exchange stores tokens."""
    mock_state_store.get_state.return_value = {
        "user_id": "test_user",
        "provider": "google",
        "code_verifier": "verifier123",
    }

    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_response.json.return_value = {
        "access_token": "access_token_123",
        "refresh_token": "refresh_token_123",
        "expires_in": 3600,
    }
    mock_http_client.post.return_value = mock_response

    await exchange_code(
        TokenExchangeParams(
            provider="google",
            code="auth_code_123",
            state="state_abc",
            config=oauth_config,
            state_store=mock_state_store,
            token_store=token_store,
            http_client=mock_http_client,
            rate_limiter=rate_limiter,
        )
    )

    # Verify token was stored
    tokens = token_store.retrieve_token("test_user")
    assert tokens["access_token"] == "access_token_123"


@pytest.mark.asyncio
async def test_exchange_code_http_error(oauth_config, mock_state_store, token_store, mock_http_client, rate_limiter):
    """Test code exchange handles HTTP errors."""
    mock_state_store.get_state.return_value = {
        "user_id": "test_user",
        "provider": "google",
        "code_verifier": "verifier123",
    }

    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.text = "Invalid grant"
    mock_http_client.post.return_value = mock_response

    with pytest.raises(OAuthProviderError, match="Token exchange failed"):
        await exchange_code(
            TokenExchangeParams(
                provider="google",
                code="invalid_code",
                state="state_abc",
                config=oauth_config,
                state_store=mock_state_store,
                token_store=token_store,
                http_client=mock_http_client,
                rate_limiter=rate_limiter,
            )
        )


@pytest.mark.asyncio
async def test_exchange_code_missing_access_token(oauth_config, mock_state_store, token_store, mock_http_client, rate_limiter):
    """Test error when access_token missing from response."""
    mock_state_store.get_state.return_value = {
        "user_id": "test_user",
        "provider": "google",
        "code_verifier": "verifier123",
    }

    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_response.json.return_value = {
        # Missing access_token
        "refresh_token": "refresh_token_123",
    }
    mock_http_client.post.return_value = mock_response

    with pytest.raises(OAuthProviderError, match="Token response missing access_token"):
        await exchange_code(
            TokenExchangeParams(
                provider="google",
                code="code",
                state="state",
                config=oauth_config,
                state_store=mock_state_store,
                token_store=token_store,
                http_client=mock_http_client,
                rate_limiter=rate_limiter,
            )
        )


# ==================== REFRESH TOKEN TESTS ====================


@pytest.mark.asyncio
async def test_refresh_token_success(oauth_config, token_store, mock_http_client):
    """Test successful token refresh."""
    # Store initial tokens
    token_store.store_token(
        user_id="test_user",
        token_data={
            "access_token": "old_access",
            "refresh_token": "refresh_token_123",
        },
        expires_in=3600,
    )

    # Mock refresh response
    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_response.json.return_value = {
        "access_token": "new_access_token",
        "expires_in": 3600,
    }
    mock_http_client.post.return_value = mock_response

    result = await refresh_token(
        user_id="test_user",
        provider="google",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
    )

    assert result["access_token"] == "new_access_token"
    assert result["refresh_token"] == "refresh_token_123"  # Preserved


@pytest.mark.asyncio
async def test_refresh_token_no_tokens(oauth_config, token_store, mock_http_client):
    """Test error when no tokens exist."""
    with pytest.raises(OAuthError, match="No tokens found"):
        await refresh_token(
            user_id="nonexistent_user",
            provider="google",
            config=oauth_config,
            token_store=token_store,
            http_client=mock_http_client,
        )


@pytest.mark.asyncio
async def test_refresh_token_no_refresh_token(oauth_config, token_store, mock_http_client):
    """Test error when no refresh token available."""
    token_store.store_token(
        user_id="test_user",
        token_data={"access_token": "access_token"},  # No refresh_token
        expires_in=3600,
    )

    with pytest.raises(OAuthError, match="No refresh token available"):
        await refresh_token(
            user_id="test_user",
            provider="google",
            config=oauth_config,
            token_store=token_store,
            http_client=mock_http_client,
        )


# ==================== FETCH USER INFO TESTS ====================


@pytest.mark.asyncio
async def test_fetch_user_info_success(oauth_config, token_store, mock_http_client, rate_limiter):
    """Test successful user info fetch."""
    token_store.store_token(
        user_id="test_user",
        token_data={"access_token": "access_token_123"},
        expires_in=3600,
    )

    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_response.json.return_value = {
        "sub": "user_sub_123",
        "email": "user@example.com",
        "name": "Test User",
    }
    mock_http_client.get.return_value = mock_response

    result = await fetch_user_info(
        user_id="test_user",
        provider="google",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
        rate_limiter=rate_limiter,
    )

    assert result["email"] == "user@example.com"
    assert result["name"] == "Test User"


@pytest.mark.asyncio
async def test_fetch_user_info_auto_refresh(oauth_config, token_store, mock_http_client, rate_limiter):
    """Test auto-refresh when access token expired."""
    token_store.store_token(
        user_id="test_user",
        token_data={
            "access_token": "expired_token",
            "refresh_token": "refresh_token",
        },
        expires_in=3600,
    )

    # First call returns 401 (expired)
    mock_response_expired = Mock()
    mock_response_expired.status_code = HTTP_UNAUTHORIZED

    # After refresh, return user info
    mock_response_success = Mock()
    mock_response_success.status_code = HTTP_OK
    mock_response_success.json.return_value = {
        "sub": "user_sub",
        "email": "user@example.com",
    }

    mock_http_client.get.side_effect = [mock_response_expired, mock_response_success]

    # Mock token refresh
    mock_refresh_response = Mock()
    mock_refresh_response.status_code = HTTP_OK
    mock_refresh_response.json.return_value = {
        "access_token": "new_access_token",
    }
    mock_http_client.post.return_value = mock_refresh_response

    result = await fetch_user_info(
        user_id="test_user",
        provider="google",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
        rate_limiter=rate_limiter,
        auto_refresh=True,
    )

    assert result["email"] == "user@example.com"


# ==================== REVOKE TOKENS TESTS ====================


@pytest.mark.asyncio
async def test_revoke_tokens_success(oauth_config, token_store, mock_http_client):
    """Test successful token revocation."""
    token_store.store_token(
        user_id="test_user",
        token_data={
            "access_token": "access_token",
            "refresh_token": "refresh_token",
            "provider": "google",
        },
        expires_in=3600,
    )

    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_http_client.post.return_value = mock_response

    result = await revoke_tokens(
        user_id="test_user",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
    )

    assert result is True

    # Tokens should be deleted
    assert token_store.retrieve_token("test_user") is None


@pytest.mark.asyncio
async def test_revoke_tokens_no_tokens(oauth_config, token_store, mock_http_client):
    """Test revoke with no tokens returns False."""
    result = await revoke_tokens(
        user_id="nonexistent_user",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
    )

    assert result is False


@pytest.mark.asyncio
async def test_revoke_tokens_provider_failure_continues(oauth_config, token_store, mock_http_client):
    """Test revoke continues even if provider revocation fails."""
    token_store.store_token(
        user_id="test_user",
        token_data={
            "access_token": "access_token",
            "provider": "google",
        },
        expires_in=3600,
    )

    # Mock provider revocation failure with httpx error
    mock_http_client.post.side_effect = httpx.HTTPError("Network error")

    result = await revoke_tokens(
        user_id="test_user",
        config=oauth_config,
        token_store=token_store,
        http_client=mock_http_client,
    )

    # Should still return True (local deletion succeeded)
    assert result is True


# ==================== REVOKE AT PROVIDER TESTS ====================


@pytest.mark.asyncio
async def test_revoke_at_provider_success(oauth_config, mock_http_client):
    """Test successful provider-level revocation."""
    tokens = {
        "access_token": "access_token",
        "refresh_token": "refresh_token",
    }

    mock_response = Mock()
    mock_response.status_code = HTTP_OK
    mock_http_client.post.return_value = mock_response

    result = await revoke_at_provider(
        provider="google",
        tokens=tokens,
        config=oauth_config,
        http_client=mock_http_client,
    )

    assert result is True


@pytest.mark.asyncio
async def test_revoke_at_provider_no_endpoint(oauth_config, mock_http_client):
    """Test revoke returns False when no revocation endpoint."""
    # GitHub doesn't have revocation endpoint
    tokens = {"access_token": "token"}

    result = await revoke_at_provider(
        provider="github",  # No revocation endpoint
        tokens=tokens,
        config=oauth_config,
        http_client=mock_http_client,
    )

    assert result is False


@pytest.mark.asyncio
async def test_revoke_at_provider_http_error(oauth_config, mock_http_client):
    """Test revoke handles HTTP errors gracefully."""
    tokens = {"access_token": "token"}
    mock_http_client.post.side_effect = httpx.HTTPError("Network error")

    result = await revoke_at_provider(
        provider="google",
        tokens=tokens,
        config=oauth_config,
        http_client=mock_http_client,
    )

    assert result is False
