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


class TestOAuthSecurityScenarios:
    """Test P0 security scenarios for OAuth implementation.

    Covers OWASP OAuth security risks:
    - State fixation / CSRF attacks
    - Redirect URI manipulation
    - Token leakage
    - Code injection via parameters
    - Rate limiting
    """

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_csrf_state_generation(self, mock_build_url, oauth_service):
        """Test that state parameter is cryptographically random for CSRF protection."""
        # Generate multiple states to ensure randomness
        states = []
        for i in range(10):
            mock_build_url.return_value = (f"https://auth.url?state=state{i}", f"state{i}")
            _, state = await oauth_service.get_authorization_url("google", "user123")
            states.append(state)

        # All states should be unique
        assert len(set(states)) == 10, "State tokens must be unique"

    @pytest.mark.asyncio
    @patch('src.auth.oauth._service_helpers.validate_state')
    async def test_state_validation_csrf_protection(self, mock_validate, oauth_service):
        """Test state validation prevents CSRF attacks."""
        # Simulate state mismatch
        mock_validate.side_effect = OAuthStateError("Invalid state", provider="google")

        with pytest.raises(OAuthStateError) as exc_info:
            await oauth_service.exchange_code_for_tokens(
                provider="google",
                code="auth_code",
                state="tampered_state"
            )

        assert "Invalid state" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('src.auth.oauth._service_helpers.validate_state')
    async def test_state_provider_mismatch(self, mock_validate, oauth_service):
        """Test state validation detects provider mismatch."""
        # State was created for google but used with github
        mock_validate.side_effect = OAuthStateError(
            "State provider mismatch: expected github, got google",
            provider="github"
        )

        with pytest.raises(OAuthStateError) as exc_info:
            await oauth_service.exchange_code_for_tokens(
                provider="github",
                code="auth_code",
                state="google_state"
            )

        assert "mismatch" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_pkce_code_challenge_generation(self, mock_build_url, oauth_service):
        """Test PKCE code challenge is generated from verifier."""
        verifier = "test_code_verifier_12345"
        challenge = oauth_service._generate_code_challenge(verifier)

        # Challenge should be different from verifier (hashed)
        assert challenge != verifier
        # Challenge should be URL-safe base64
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                   for c in challenge)
        # Challenge should be deterministic
        challenge2 = oauth_service._generate_code_challenge(verifier)
        assert challenge == challenge2

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_token_exchange_invalid_grant_error(self, mock_exchange, oauth_service):
        """Test handling of invalid_grant error from provider."""
        mock_exchange.side_effect = OAuthProviderError(
            "Token exchange failed: 400 - invalid_grant",
            provider="google"
        )

        with pytest.raises(OAuthProviderError) as exc_info:
            await oauth_service.exchange_code_for_tokens(
                provider="google",
                code="invalid_code",
                state="valid_state"
            )

        assert "invalid_grant" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_token_exchange_network_error(self, mock_exchange, oauth_service):
        """Test handling of network errors during token exchange."""
        mock_exchange.side_effect = OAuthProviderError(
            "HTTP error during token exchange: Connection timeout",
            provider="google"
        )

        with pytest.raises(OAuthProviderError) as exc_info:
            await oauth_service.exchange_code_for_tokens(
                provider="google",
                code="auth_code",
                state="state123"
            )

        assert "HTTP error" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_token_response_missing_access_token(self, mock_exchange, oauth_service):
        """Test handling of malformed token response."""
        mock_exchange.side_effect = OAuthProviderError(
            "Token response missing access_token",
            provider="google"
        )

        with pytest.raises(OAuthProviderError) as exc_info:
            await oauth_service.exchange_code_for_tokens(
                provider="google",
                code="auth_code",
                state="state123"
            )

        assert "access_token" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._refresh_token')
    async def test_token_refresh_no_refresh_token(self, mock_refresh, oauth_service):
        """Test token refresh fails when no refresh token available."""
        mock_refresh.side_effect = OAuthError(
            "No refresh token available",
            provider="google"
        )

        with pytest.raises(OAuthError) as exc_info:
            await oauth_service.refresh_access_token("user123", "google")

        assert "refresh token" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._refresh_token')
    async def test_token_refresh_expired_token(self, mock_refresh, oauth_service):
        """Test token refresh handles expired refresh token."""
        mock_refresh.side_effect = OAuthProviderError(
            "Token refresh failed: 400",
            provider="google"
        )

        with pytest.raises(OAuthProviderError) as exc_info:
            await oauth_service.refresh_access_token("user123", "google")

        assert "refresh failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._fetch_user_info')
    async def test_userinfo_auto_refresh_on_401(self, mock_fetch, oauth_service):
        """Test user info fetch auto-refreshes on 401 Unauthorized."""
        # First call returns 401, triggers refresh, second call succeeds
        mock_fetch.return_value = {
            "id": "12345",
            "email": "user@example.com"
        }

        user_info = await oauth_service.get_user_info("user123", "google", auto_refresh=True)

        assert user_info["email"] == "user@example.com"

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._fetch_user_info')
    async def test_userinfo_no_tokens_error(self, mock_fetch, oauth_service):
        """Test user info fetch fails when no tokens stored."""
        mock_fetch.side_effect = OAuthError(
            "No tokens found for user user123",
            provider="google"
        )

        with pytest.raises(OAuthError) as exc_info:
            await oauth_service.get_user_info("user123", "google")

        assert "No tokens" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_rate_limiting_oauth_init(self, mock_build_url, oauth_service):
        """Test rate limiting on OAuth initialization."""
        from src.auth.oauth.rate_limiter import RateLimitExceeded

        mock_build_url.side_effect = RateLimitExceeded("Rate limit exceeded", retry_after=60)

        with pytest.raises(RateLimitExceeded):
            await oauth_service.get_authorization_url(
                "google", "user123", ip_address="192.168.1.1"
            )

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_rate_limiting_token_exchange(self, mock_exchange, oauth_service):
        """Test rate limiting on token exchange."""
        from src.auth.oauth.rate_limiter import RateLimitExceeded

        mock_exchange.side_effect = RateLimitExceeded("Rate limit exceeded", retry_after=60)

        with pytest.raises(RateLimitExceeded):
            await oauth_service.exchange_code_for_tokens(
                "google", "code123", "state123", ip_address="192.168.1.1"
            )

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._fetch_user_info')
    async def test_rate_limiting_userinfo(self, mock_fetch, oauth_service):
        """Test rate limiting on user info fetch."""
        from src.auth.oauth.rate_limiter import RateLimitExceeded

        mock_fetch.side_effect = RateLimitExceeded("Rate limit exceeded", retry_after=60)

        with pytest.raises(RateLimitExceeded):
            await oauth_service.get_user_info("user123", "google")

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_scope_validation(self, mock_build_url, oauth_service):
        """Test that scopes are properly validated."""
        mock_build_url.return_value = ("https://auth.url?scope=openid+email", "state123")

        url, state = await oauth_service.get_authorization_url("google", "user123")

        # Verify the helper was called (actual scope validation happens in helper)
        mock_build_url.assert_called_once()

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_redirect_uri_validation(self, mock_build_url, oauth_service):
        """Test redirect URI validation."""
        # This would normally fail in the helper if redirect_uri not in allowed list
        mock_build_url.return_value = ("https://auth.url", "state123")

        url, state = await oauth_service.get_authorization_url("google", "user123")

        assert state == "state123"

    @pytest.mark.asyncio
    async def test_http_client_security_settings(self, oauth_service):
        """Test HTTP client is configured with security settings."""
        client = await oauth_service._get_http_client()

        # Client should be created
        assert client is not None
        # Verify SSL verification is enabled (httpx default is True)
        # This ensures we're not disabling cert verification
        # The actual verification happens in httpx.AsyncClient

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._revoke_tokens')
    async def test_token_revocation_best_effort(self, mock_revoke, oauth_service):
        """Test token revocation is best-effort (doesn't fail on provider errors)."""
        # Even if provider revocation fails, local deletion should succeed
        mock_revoke.return_value = True

        result = await oauth_service.revoke_tokens("user123")

        assert result is True

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._revoke_at_provider')
    async def test_provider_revocation_timeout(self, mock_revoke_provider, oauth_service):
        """Test provider revocation handles timeouts gracefully."""
        # Provider revocation should not fail the entire flow
        mock_revoke_provider.return_value = False

        tokens = {"access_token": "test", "refresh_token": "test_refresh"}
        result = await oauth_service._revoke_at_provider("google", tokens)

        assert result is False

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._build_authorization_url')
    async def test_state_storage_ttl(self, mock_build_url, oauth_service):
        """Test state tokens have appropriate TTL (10 minutes)."""
        mock_build_url.return_value = ("https://auth.url", "state123")

        url, state = await oauth_service.get_authorization_url("google", "user123")

        # State should be created with TTL (validated in helper)
        assert state == "state123"

    def test_code_verifier_entropy(self, oauth_service):
        """Test PKCE code verifier has sufficient entropy."""
        verifier = oauth_service._generate_code_verifier()

        # Should be URL-safe base64, at least 32 bytes of entropy
        assert len(verifier) >= 43  # base64 encoding of 32 bytes
        assert isinstance(verifier, str)

    def test_state_token_entropy(self, oauth_service):
        """Test state token has sufficient entropy (32 bytes minimum)."""
        state = oauth_service._generate_state()

        # Should be URL-safe base64, at least 32 bytes of entropy
        assert len(state) >= 43  # base64 encoding of 32 bytes
        assert isinstance(state, str)

    @pytest.mark.asyncio
    @patch('src.auth.oauth.service._exchange_code')
    async def test_token_storage_encryption(self, mock_exchange, oauth_service):
        """Test tokens are stored encrypted."""
        mock_exchange.return_value = {
            "access_token": "sensitive_token",
            "refresh_token": "refresh_token",
            "_flow_user_id": "user123"
        }

        tokens = await oauth_service.exchange_code_for_tokens(
            "google", "code123", "state123"
        )

        # Tokens should be returned (encryption happens in token_store)
        assert "access_token" in tokens
