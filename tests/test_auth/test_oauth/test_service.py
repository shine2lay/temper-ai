"""Tests for OAuthService.

This test module verifies:
- OAuth service initialization with dependencies
- Authorization URL generation with PKCE and CSRF
- Code exchange for tokens
- Token refresh
- User info fetching
- Token revocation
- State cleanup
- Resource cleanup (HTTP client, state store)
- Error handling (state validation, provider errors)
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from src.auth.oauth.service import OAuthService, OAuthError, OAuthProviderError, OAuthStateError
from src.auth.oauth.config import OAuthConfig, OAuthProviderConfig
from src.auth.oauth.token_store import SecureTokenStore
from src.auth.oauth.callback_validator import CallbackURLValidator


@pytest.fixture
def mock_config():
    """Create mock OAuth configuration."""
    from cryptography.fernet import Fernet
    config = Mock(spec=OAuthConfig)
    config.token_encryption_key = Fernet.generate_key()  # Valid base64-encoded key
    config.allowed_callback_urls = ["https://example.com/callback"]
    config.allow_localhost = True
    config.providers = {
        "google": Mock(
            spec=OAuthProviderConfig,
            client_id="test_client_id",
            client_secret="test_secret",
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            user_info_url="https://www.googleapis.com/oauth2/v2/userinfo",
            revocation_url="https://oauth2.googleapis.com/revoke",
            scopes=["openid", "email"],
            redirect_uri="https://example.com/callback"
        )
    }
    return config


@pytest.fixture
def mock_token_store():
    """Create mock token store."""
    store = AsyncMock(spec=SecureTokenStore)
    store.get_tokens = AsyncMock(return_value=None)
    store.store_tokens = AsyncMock()
    store.delete_tokens = AsyncMock()
    return store


@pytest.fixture
def mock_callback_validator():
    """Create mock callback validator."""
    validator = Mock(spec=CallbackURLValidator)
    validator.validate = Mock(return_value=True)
    return validator


@pytest.fixture
def mock_state_store():
    """Create mock state store."""
    store = AsyncMock()
    store.save_state = AsyncMock()
    store.get_state = AsyncMock(return_value={
        "provider": "google",
        "user_id": "user123",
        "code_verifier": "test_verifier"
    })
    store.delete_state = AsyncMock()
    store.cleanup_expired = AsyncMock(return_value=5)
    store.close = AsyncMock()
    return store


@pytest.fixture
def mock_rate_limiter():
    """Create mock rate limiter."""
    limiter = AsyncMock()
    limiter.check_rate_limit = AsyncMock()
    return limiter


@pytest.fixture
def oauth_service(mock_config, mock_token_store, mock_callback_validator, mock_state_store, mock_rate_limiter):
    """Create OAuthService instance with mocked dependencies."""
    return OAuthService(
        config=mock_config,
        token_store=mock_token_store,
        callback_validator=mock_callback_validator,
        state_store=mock_state_store,
        rate_limiter=mock_rate_limiter
    )


class TestOAuthServiceInitialization:
    """Test OAuthService initialization."""

    def test_init_with_defaults(self, mock_config):
        """Test initialization with default dependencies."""
        service = OAuthService(config=mock_config)

        assert service.config == mock_config
        assert service.token_store is not None
        assert service.callback_validator is not None
        assert service._state_store is not None
        assert service._rate_limiter is not None
        assert service._http_client is None
        assert service._owns_http_client is True

    def test_init_with_custom_dependencies(self, mock_config, mock_token_store,
                                           mock_callback_validator, mock_state_store, mock_rate_limiter):
        """Test initialization with custom dependencies."""
        service = OAuthService(
            config=mock_config,
            token_store=mock_token_store,
            callback_validator=mock_callback_validator,
            state_store=mock_state_store,
            rate_limiter=mock_rate_limiter
        )

        assert service.token_store == mock_token_store
        assert service.callback_validator == mock_callback_validator
        assert service._state_store == mock_state_store
        assert service._rate_limiter == mock_rate_limiter

    def test_init_with_custom_http_client(self, mock_config):
        """Test initialization with custom HTTP client."""
        mock_client = AsyncMock()
        service = OAuthService(config=mock_config, http_client=mock_client)

        assert service._http_client == mock_client
        assert service._owns_http_client is False


class TestOAuthServiceAuthorization:
    """Test OAuth authorization flow."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_get_authorization_url(self, mock_build_url, oauth_service):
        """Test get_authorization_url delegates to helper."""
        mock_build_url.return_value = ("https://auth.url?state=abc", "abc")

        url, state = await oauth_service.get_authorization_url(
            provider="google",
            user_id="user123"
        )

        assert url == "https://auth.url?state=abc"
        assert state == "abc"
        mock_build_url.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_get_authorization_url_with_params(self, mock_build_url, oauth_service):
        """Test get_authorization_url with extra params and IP."""
        mock_build_url.return_value = ("https://auth.url", "state123")

        url, state = await oauth_service.get_authorization_url(
            provider="google",
            user_id="user123",
            extra_params={"prompt": "consent"},
            ip_address="192.168.1.1"
        )

        assert state == "state123"
        # Just verify it was called
        mock_build_url.assert_called_once()


class TestOAuthServiceTokenExchange:
    """Test OAuth token exchange."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_exchange_code_for_tokens(self, mock_exchange, oauth_service):
        """Test exchange_code_for_tokens delegates to helper."""
        mock_exchange.return_value = {
            "access_token": "access_abc",
            "refresh_token": "refresh_xyz",
            "expires_in": 3600
        }

        tokens = await oauth_service.exchange_code_for_tokens(
            provider="google",
            code="auth_code_123",
            state="state_abc"
        )

        assert tokens["access_token"] == "access_abc"
        assert tokens["refresh_token"] == "refresh_xyz"
        mock_exchange.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_exchange_code_with_redirect_uri(self, mock_exchange, oauth_service):
        """Test exchange_code_for_tokens with redirect URI."""
        mock_exchange.return_value = {"access_token": "test"}

        await oauth_service.exchange_code_for_tokens(
            provider="google",
            code="code123",
            state="state123",
            redirect_uri="https://custom.com/callback",
            ip_address="10.0.0.1"
        )

        # Just verify it was called
        mock_exchange.assert_called_once()


class TestOAuthServiceTokenRefresh:
    """Test OAuth token refresh."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._refresh_token')
    async def test_refresh_access_token(self, mock_refresh, oauth_service):
        """Test refresh_access_token delegates to helper."""
        mock_refresh.return_value = {
            "access_token": "new_access_token",
            "expires_in": 3600
        }

        tokens = await oauth_service.refresh_access_token(
            user_id="user123",
            provider="google"
        )

        assert tokens["access_token"] == "new_access_token"
        mock_refresh.assert_called_once_with(
            "user123", "google", oauth_service.config,
            oauth_service.token_store, oauth_service._http_client
        )


class TestOAuthServiceUserInfo:
    """Test OAuth user info fetching."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._fetch_user_info')
    async def test_get_user_info(self, mock_fetch, oauth_service):
        """Test get_user_info delegates to helper."""
        mock_fetch.return_value = {
            "id": "12345",
            "email": "user@example.com",
            "name": "Test User"
        }

        user_info = await oauth_service.get_user_info(
            user_id="user123",
            provider="google"
        )

        assert user_info["email"] == "user@example.com"
        assert user_info["name"] == "Test User"
        mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._fetch_user_info')
    async def test_get_user_info_no_auto_refresh(self, mock_fetch, oauth_service):
        """Test get_user_info without auto refresh."""
        mock_fetch.return_value = {"id": "12345"}

        await oauth_service.get_user_info(
            user_id="user123",
            provider="google",
            auto_refresh=False
        )

        call_args = mock_fetch.call_args[0]
        assert call_args[6] is False


class TestOAuthServiceTokenRevocation:
    """Test OAuth token revocation."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._revoke_tokens')
    async def test_revoke_tokens(self, mock_revoke, oauth_service):
        """Test revoke_tokens delegates to helper."""
        mock_revoke.return_value = True

        result = await oauth_service.revoke_tokens(user_id="user123")

        assert result is True
        mock_revoke.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._revoke_at_provider')
    async def test_revoke_at_provider(self, mock_revoke_provider, oauth_service):
        """Test _revoke_at_provider delegates to helper."""
        mock_revoke_provider.return_value = True
        tokens = {"access_token": "test", "refresh_token": "test_refresh"}

        result = await oauth_service._revoke_at_provider("google", tokens)

        assert result is True
        mock_revoke_provider.assert_called_once_with(
            "google", tokens, oauth_service.config, oauth_service._http_client
        )


class TestOAuthServiceStateManagement:
    """Test OAuth state management."""

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._validate_state')
    async def test_validate_state(self, mock_validate, oauth_service):
        """Test _validate_state delegates to helper."""
        mock_validate.return_value = {
            "provider": "google",
            "user_id": "user123",
            "code_verifier": "verifier"
        }

        state_data = await oauth_service._validate_state("state123", "google")

        assert state_data["provider"] == "google"
        assert state_data["user_id"] == "user123"
        mock_validate.assert_called_once_with("state123", "google", oauth_service._state_store)

    @pytest.mark.asyncio
    async def test_cleanup_expired_states(self, oauth_service, mock_state_store):
        """Test cleanup_expired_states delegates to state store."""
        mock_state_store.cleanup_expired.return_value = 10

        count = await oauth_service.cleanup_expired_states()

        assert count == 10
        mock_state_store.cleanup_expired.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_states_zero(self, oauth_service, mock_state_store):
        """Test cleanup with no expired states."""
        mock_state_store.cleanup_expired.return_value = 0

        count = await oauth_service.cleanup_expired_states()

        assert count == 0


class TestOAuthServiceResourceCleanup:
    """Test OAuth service resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_owned_http_client(self, mock_config, mock_state_store):
        """Test close() closes owned HTTP client."""
        mock_http_client = AsyncMock()
        service = OAuthService(
            config=mock_config,
            state_store=mock_state_store,
            http_client=None
        )
        service._http_client = mock_http_client
        service._owns_http_client = True

        await service.close()

        mock_http_client.aclose.assert_called_once()
        assert service._http_client is None

    @pytest.mark.asyncio
    async def test_close_not_owned_http_client(self, mock_config, mock_state_store):
        """Test close() does not close external HTTP client."""
        mock_http_client = AsyncMock()
        service = OAuthService(
            config=mock_config,
            state_store=mock_state_store,
            http_client=mock_http_client
        )

        await service.close()

        mock_http_client.aclose.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_state_store(self, oauth_service, mock_state_store):
        """Test close() closes state store."""
        await oauth_service.close()

        mock_state_store.close.assert_called_once()


class TestOAuthServiceHelpers:
    """Test OAuth service helper methods."""

    def test_generate_state(self, oauth_service):
        """Test _generate_state generates non-empty string."""
        state = oauth_service._generate_state()

        assert isinstance(state, str)
        assert len(state) > 0

    def test_generate_code_verifier(self, oauth_service):
        """Test _generate_code_verifier generates non-empty string."""
        verifier = oauth_service._generate_code_verifier()

        assert isinstance(verifier, str)
        assert len(verifier) > 0

    def test_generate_code_challenge(self, oauth_service):
        """Test _generate_code_challenge generates challenge from verifier."""
        verifier = "test_verifier_string"
        challenge = oauth_service._generate_code_challenge(verifier)

        assert isinstance(challenge, str)
        assert len(challenge) > 0
        assert challenge != verifier  # Challenge should be hashed

    @pytest.mark.asyncio
    async def test_get_http_client_creates_once(self, oauth_service):
        """Test _get_http_client creates client only once."""
        client1 = await oauth_service._get_http_client()
        client2 = await oauth_service._get_http_client()

        assert client1 is client2

    @pytest.mark.asyncio
    async def test_get_http_client_returns_existing(self, mock_config):
        """Test _get_http_client returns existing client."""
        mock_client = AsyncMock()
        service = OAuthService(config=mock_config, http_client=mock_client)

        client = await service._get_http_client()

        assert client == mock_client


class TestOAuthExceptions:
    """Test OAuth exception classes."""

    def test_oauth_error_basic(self):
        """Test OAuthError basic usage."""
        error = OAuthError("Test error")

        assert str(error) == "Test error"
        assert error.provider is None

    def test_oauth_error_with_provider(self):
        """Test OAuthError with provider."""
        error = OAuthError("Test error", provider="google")

        assert str(error) == "Test error"
        assert error.provider == "google"

    def test_oauth_provider_error(self):
        """Test OAuthProviderError inherits from OAuthError."""
        error = OAuthProviderError("Provider failed", provider="github")

        assert isinstance(error, OAuthError)
        assert error.provider == "github"

    def test_oauth_state_error(self):
        """Test OAuthStateError for CSRF protection."""
        error = OAuthStateError("State mismatch", provider="google")

        assert isinstance(error, OAuthError)
        assert error.provider == "google"
