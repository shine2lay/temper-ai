"""Tests for OAuth Service Layer.

Tests OAuth 2.0 authorization code flow with PKCE support including:
- Service initialization
- Authorization URL generation with state/PKCE
- Token exchange and validation
- User info retrieval
- Token refresh flow
- Error handling and edge cases
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet

from temper_ai.auth.oauth.callback_validator import CallbackURLValidator
from temper_ai.auth.oauth.config import OAuthConfig, OAuthProviderConfig
from temper_ai.auth.oauth.rate_limiter import OAuthRateLimiter, RateLimitExceeded
from temper_ai.auth.oauth.service import (
    OAuthError,
    OAuthProviderError,
    OAuthService,
    OAuthStateError,
)
from temper_ai.auth.oauth.state_store import InMemoryStateStore
from temper_ai.auth.oauth.token_store import SecureTokenStore


class TestOAuthServiceInitialization:
    """Test OAuth service initialization and configuration."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    def test_service_initialization(self, oauth_config):
        """Should initialize service with all components."""
        service = OAuthService(config=oauth_config)

        assert service.config == oauth_config
        assert service.token_store is not None
        assert service.callback_validator is not None
        assert service._state_store is not None
        assert service._rate_limiter is not None

    def test_service_initialization_with_custom_components(self, oauth_config):
        """Should accept custom components in initialization."""
        mock_token_store = Mock(spec=SecureTokenStore)
        mock_callback_validator = Mock(spec=CallbackURLValidator)
        mock_http_client = Mock(spec=httpx.AsyncClient)
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_rate_limiter = Mock(spec=OAuthRateLimiter)

        service = OAuthService(
            config=oauth_config,
            token_store=mock_token_store,
            callback_validator=mock_callback_validator,
            http_client=mock_http_client,
            state_store=mock_state_store,
            rate_limiter=mock_rate_limiter,
        )

        assert service.token_store == mock_token_store
        assert service.callback_validator == mock_callback_validator
        assert service._http_client == mock_http_client
        assert service._state_store == mock_state_store
        assert service._rate_limiter == mock_rate_limiter


class TestAuthorizationURLGeneration:
    """Test OAuth authorization URL generation with state and PKCE."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    @pytest.fixture
    def service(self, oauth_config):
        """Create OAuth service for testing."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.set_state = AsyncMock()
        return OAuthService(config=oauth_config, state_store=mock_state_store)

    @pytest.mark.asyncio
    async def test_get_authorization_url_success(self, service):
        """Should generate authorization URL with state and PKCE."""
        auth_url, state = await service.get_authorization_url(
            provider="google", user_id="user_123"
        )

        assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "client_id=test_client_id" in auth_url
        assert "redirect_uri=" in auth_url
        assert "response_type=code" in auth_url
        assert "scope=" in auth_url
        assert f"state={state}" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert state is not None
        assert len(state) > 0

    @pytest.mark.asyncio
    async def test_get_authorization_url_stores_state(self, service):
        """Should store state data with PKCE verifier."""
        auth_url, state = await service.get_authorization_url(
            provider="google", user_id="user_123"
        )

        # Verify state_store.set_state was called
        service._state_store.set_state.assert_called_once()
        call_args = service._state_store.set_state.call_args

        assert call_args[1]["state"] == state
        assert call_args[1]["data"]["user_id"] == "user_123"
        assert call_args[1]["data"]["provider"] == "google"
        assert "code_verifier" in call_args[1]["data"]
        assert call_args[1]["ttl_seconds"] == 600

    @pytest.mark.asyncio
    async def test_get_authorization_url_invalid_provider(self, service):
        """Should raise error for unconfigured provider."""
        with pytest.raises(OAuthError, match="not configured"):
            await service.get_authorization_url(
                provider="invalid_provider", user_id="user_123"
            )

    @pytest.mark.asyncio
    async def test_get_authorization_url_with_extra_params(self, service):
        """Should include extra parameters in authorization URL."""
        extra_params = {"prompt": "select_account", "login_hint": "user@example.com"}

        auth_url, state = await service.get_authorization_url(
            provider="google", user_id="user_123", extra_params=extra_params
        )

        assert "prompt=select_account" in auth_url
        assert "login_hint=user%40example.com" in auth_url

    @pytest.mark.asyncio
    async def test_get_authorization_url_rate_limit_exceeded(self, oauth_config):
        """Should raise RateLimitExceeded when rate limit hit."""
        mock_rate_limiter = Mock(spec=OAuthRateLimiter)
        mock_rate_limiter.check_oauth_init = Mock(
            side_effect=RateLimitExceeded("Rate limit exceeded", retry_after=60)
        )

        service = OAuthService(config=oauth_config, rate_limiter=mock_rate_limiter)

        with pytest.raises(RateLimitExceeded):
            await service.get_authorization_url(
                provider="google", user_id="user_123", ip_address="1.2.3.4"
            )


class TestTokenExchange:
    """Test OAuth token exchange flow."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        mock_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json = Mock(
            return_value={
                "access_token": "ya29.a0AfB_test",
                "refresh_token": "1//0gTest",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    @pytest.fixture
    def service(self, oauth_config, mock_http_client):
        """Create OAuth service with mocked dependencies."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.get_state = AsyncMock(
            return_value={
                "user_id": "user_123",
                "provider": "google",
                "code_verifier": "test_verifier_12345",
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.store_token = Mock()

        return OAuthService(
            config=oauth_config,
            http_client=mock_http_client,
            state_store=mock_state_store,
            token_store=mock_token_store,
        )

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_success(self, service):
        """Should successfully exchange authorization code for tokens."""
        tokens = await service.exchange_code_for_tokens(
            provider="google", code="auth_code_123", state="test_state"
        )

        assert tokens["access_token"] == "ya29.a0AfB_test"
        assert tokens["refresh_token"] == "1//0gTest"
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == 3600
        assert tokens["_flow_user_id"] == "user_123"

    @pytest.mark.asyncio
    async def test_exchange_code_validates_state(self, service):
        """Should validate state before token exchange."""
        await service.exchange_code_for_tokens(
            provider="google", code="auth_code_123", state="test_state"
        )

        service._state_store.get_state.assert_called_once_with("test_state")

    @pytest.mark.asyncio
    async def test_exchange_code_stores_tokens(self, service):
        """Should store tokens after successful exchange."""
        await service.exchange_code_for_tokens(
            provider="google", code="auth_code_123", state="test_state"
        )

        service.token_store.store_token.assert_called_once()
        call_args = service.token_store.store_token.call_args
        assert call_args[1]["user_id"] == "user_123"
        assert "access_token" in call_args[1]["token_data"]

    @pytest.mark.asyncio
    async def test_exchange_code_invalid_state(self, oauth_config):
        """Should raise OAuthStateError for invalid state."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.get_state = AsyncMock(return_value=None)

        service = OAuthService(config=oauth_config, state_store=mock_state_store)

        with pytest.raises(OAuthStateError, match="Invalid or expired state"):
            await service.exchange_code_for_tokens(
                provider="google", code="auth_code_123", state="invalid_state"
            )

    @pytest.mark.asyncio
    async def test_exchange_code_provider_mismatch(self, oauth_config):
        """Should raise OAuthStateError if provider doesn't match state."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.get_state = AsyncMock(
            return_value={
                "user_id": "user_123",
                "provider": "github",  # Mismatch
                "code_verifier": "test_verifier",
            }
        )

        service = OAuthService(config=oauth_config, state_store=mock_state_store)

        with pytest.raises(OAuthStateError, match="provider mismatch"):
            await service.exchange_code_for_tokens(
                provider="google", code="auth_code_123", state="test_state"
            )

    @pytest.mark.asyncio
    async def test_exchange_code_provider_error(self, service, mock_http_client):
        """Should raise OAuthProviderError on non-200 response."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(OAuthProviderError, match="Token exchange failed: 400"):
            await service.exchange_code_for_tokens(
                provider="google", code="invalid_code", state="test_state"
            )

    @pytest.mark.asyncio
    async def test_exchange_code_network_error(self, service, mock_http_client):
        """Should raise OAuthProviderError on network error."""
        mock_http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        with pytest.raises(
            OAuthProviderError, match="HTTP error during token exchange"
        ):
            await service.exchange_code_for_tokens(
                provider="google", code="auth_code_123", state="test_state"
            )

    @pytest.mark.asyncio
    async def test_exchange_code_missing_access_token(self, service, mock_http_client):
        """Should raise OAuthProviderError if response missing access_token."""
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json = Mock(return_value={"token_type": "Bearer"})
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(OAuthProviderError, match="missing access_token"):
            await service.exchange_code_for_tokens(
                provider="google", code="auth_code_123", state="test_state"
            )


class TestUserInfo:
    """Test user info retrieval."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    @pytest.fixture
    def mock_http_client(self):
        """Create mock HTTP client."""
        mock_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json = Mock(
            return_value={
                "sub": "google_user_123",
                "email": "user@example.com",
                "name": "Test User",
            }
        )
        mock_client.get = AsyncMock(return_value=mock_response)
        return mock_client

    @pytest.fixture
    def service(self, oauth_config, mock_http_client):
        """Create OAuth service with mocked dependencies."""
        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(
            return_value={
                "access_token": "ya29.a0AfB_test",
                "refresh_token": "1//0gTest",
                "token_type": "Bearer",
            }
        )

        return OAuthService(
            config=oauth_config,
            http_client=mock_http_client,
            token_store=mock_token_store,
        )

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, service):
        """Should retrieve user info successfully."""
        user_info = await service.get_user_info(user_id="user_123", provider="google")

        assert user_info["sub"] == "google_user_123"
        assert user_info["email"] == "user@example.com"
        assert user_info["name"] == "Test User"

    @pytest.mark.asyncio
    async def test_get_user_info_no_tokens(self, oauth_config):
        """Should raise OAuthError if no tokens found."""
        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(return_value=None)

        service = OAuthService(config=oauth_config, token_store=mock_token_store)

        with pytest.raises(OAuthError, match="No tokens found"):
            await service.get_user_info(user_id="user_123", provider="google")

    @pytest.mark.asyncio
    async def test_get_user_info_auto_refresh_on_401(
        self, oauth_config, mock_http_client
    ):
        """Should auto-refresh token on 401 response."""
        # First call returns 401, second call returns success
        mock_401_response = Mock(spec=httpx.Response)
        mock_401_response.status_code = 401

        mock_success_response = Mock(spec=httpx.Response)
        mock_success_response.status_code = 200
        mock_success_response.json = Mock(
            return_value={"sub": "user_123", "email": "user@example.com"}
        )

        mock_http_client.get = AsyncMock(
            side_effect=[mock_401_response, mock_success_response]
        )

        # Mock refresh response
        mock_refresh_response = Mock(spec=httpx.Response)
        mock_refresh_response.status_code = 200
        mock_refresh_response.json = Mock(
            return_value={
                "access_token": "new_access_token",
                "expires_in": 3600,
            }
        )
        mock_http_client.post = AsyncMock(return_value=mock_refresh_response)

        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(
            return_value={
                "access_token": "expired_token",
                "refresh_token": "1//0gTest",
            }
        )
        mock_token_store.store_token = Mock()

        service = OAuthService(
            config=oauth_config,
            http_client=mock_http_client,
            token_store=mock_token_store,
        )

        user_info = await service.get_user_info(
            user_id="user_123", provider="google", auto_refresh=True
        )

        assert user_info["email"] == "user@example.com"
        # Should have called refresh
        assert mock_http_client.post.called


class TestTokenRefresh:
    """Test token refresh flow."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self, oauth_config):
        """Should successfully refresh access token."""
        mock_http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json = Mock(
            return_value={
                "access_token": "new_access_token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
        )
        mock_http_client.post = AsyncMock(return_value=mock_response)

        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(
            return_value={
                "access_token": "old_access_token",
                "refresh_token": "refresh_token_123",
            }
        )
        mock_token_store.store_token = Mock()

        service = OAuthService(
            config=oauth_config,
            http_client=mock_http_client,
            token_store=mock_token_store,
        )

        new_tokens = await service.refresh_access_token(
            user_id="user_123", provider="google"
        )

        assert new_tokens["access_token"] == "new_access_token"
        assert new_tokens["refresh_token"] == "refresh_token_123"  # Preserved
        mock_token_store.store_token.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_access_token_no_refresh_token(self, oauth_config):
        """Should raise OAuthError if no refresh token available."""
        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(
            return_value={"access_token": "access_token"}  # No refresh_token
        )

        service = OAuthService(config=oauth_config, token_store=mock_token_store)

        with pytest.raises(OAuthError, match="No refresh token available"):
            await service.refresh_access_token(user_id="user_123", provider="google")

    @pytest.mark.asyncio
    async def test_refresh_access_token_provider_error(self, oauth_config):
        """Should raise OAuthProviderError on refresh failure."""
        mock_http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_http_client.post = AsyncMock(return_value=mock_response)

        mock_token_store = Mock(spec=SecureTokenStore)
        mock_token_store.retrieve_token = Mock(
            return_value={
                "access_token": "access_token",
                "refresh_token": "refresh_token",
            }
        )

        service = OAuthService(
            config=oauth_config,
            http_client=mock_http_client,
            token_store=mock_token_store,
        )

        with pytest.raises(OAuthProviderError, match="Token refresh failed"):
            await service.refresh_access_token(user_id="user_123", provider="google")


class TestServiceCleanup:
    """Test service cleanup and resource management."""

    @pytest.fixture
    def oauth_config(self):
        """Create test OAuth configuration."""
        return OAuthConfig(
            providers=[
                OAuthProviderConfig(
                    provider="google",
                    client_id="test_client_id",
                    client_secret="test_client_secret",
                    redirect_uri="http://localhost:8000/callback",
                    scopes=["openid", "email", "profile"],
                )
            ],
            allowed_callback_urls=["http://localhost:8000/callback"],
            token_encryption_key=Fernet.generate_key().decode(),
            state_secret_key="test_state_secret",
            token_expiry_seconds=3600,
            allow_localhost=True,
        )

    @pytest.mark.asyncio
    async def test_close_cleans_up_resources(self, oauth_config):
        """Should close state store on cleanup."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.close = AsyncMock()

        # Create service without passing http_client so it owns it
        service = OAuthService(
            config=oauth_config,
            state_store=mock_state_store,
        )

        # Trigger HTTP client creation
        await service._get_http_client()

        await service.close()

        # State store should be closed
        mock_state_store.close.assert_called_once()
        # HTTP client should be None after close (when owned)
        assert service._http_client is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_states(self, oauth_config):
        """Should delegate to state store for cleanup."""
        mock_state_store = Mock(spec=InMemoryStateStore)
        mock_state_store.cleanup_expired = AsyncMock(return_value=5)

        service = OAuthService(config=oauth_config, state_store=mock_state_store)

        count = await service.cleanup_expired_states()

        assert count == 5
        mock_state_store.cleanup_expired.assert_called_once()
