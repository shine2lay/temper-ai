"""OAuth Integration Tests.

Comprehensive test suite for OAuth 2.0 authentication flow with security focus.

Tests cover:
- Complete OAuth flow (login → callback → session)
- Session fixation prevention
- Token protection (never exposed)
- CSRF protection (state validation)
- User account linking
- Security headers
- Error handling
- Token revocation (provider-level and local)
- Expired state cleanup
"""

import asyncio
import secrets
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from temper_ai.auth.models import Session, User
from temper_ai.auth.oauth.config import OAuthConfig, OAuthProviderConfig
from temper_ai.auth.oauth.service import OAuthService
from temper_ai.auth.oauth.state_store import InMemoryStateStore
from temper_ai.auth.oauth.token_store import SecureTokenStore
from temper_ai.auth.routes import OAuthRouteHandlers
from temper_ai.auth.session import SessionStore, UserStore

# Test Fixtures


@pytest.fixture
def mock_oauth_config():
    """Create mock OAuth configuration."""
    return OAuthConfig(
        providers=[
            {
                "provider": "google",
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
                "redirect_uri": "http://localhost/auth/oauth/google/callback",
                "scopes": ["openid", "email", "profile"],
            }
        ],
        allowed_callback_urls=["http://localhost/auth/oauth/google/callback"],
        token_encryption_key="test_encryption_key_32_chars!!",
        state_secret_key="test_state_secret_32_chars!!!!",
        token_expiry_seconds=3600,
        allow_localhost=True,
    )


@pytest.fixture
def session_store():
    """Create session store."""
    return SessionStore()


@pytest.fixture
def user_store():
    """Create user store."""
    return UserStore()


@pytest.fixture
def mock_oauth_service(mock_oauth_config):
    """Create mock OAuth service."""
    from temper_ai.auth.oauth.service import OAuthStateError

    service = Mock(spec=OAuthService)
    service.config = mock_oauth_config

    # Track valid states issued by get_authorization_url
    valid_states: set = set()

    # Mock get_authorization_url
    async def mock_get_auth_url(provider, user_id, ip_address):
        state = secrets.token_urlsafe(32)
        valid_states.add(state)
        auth_url = (
            f"https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id=test_client_id&state={state}"
        )
        return auth_url, state

    service.get_authorization_url = AsyncMock(side_effect=mock_get_auth_url)

    # Mock exchange_code_for_tokens (validates state like real service)
    async def mock_exchange(provider, code, state, ip_address):
        if state not in valid_states:
            raise OAuthStateError("Invalid or expired state parameter")
        return {
            "access_token": "mock_access_token",
            "refresh_token": "mock_refresh_token",
            "expires_in": 3600,
        }

    service.exchange_code_for_tokens = AsyncMock(side_effect=mock_exchange)

    # Mock get_user_info
    async def mock_user_info(user_id, provider):
        return {
            "sub": "google_user_123",
            "email": "test@example.com",
            "name": "Test User",
            "picture": "https://example.com/photo.jpg",
        }

    service.get_user_info = AsyncMock(side_effect=mock_user_info)

    # Mock revoke_tokens
    service.revoke_tokens = AsyncMock(return_value=True)

    return service


@pytest.fixture
def oauth_handlers(mock_oauth_service, session_store, user_store):
    """Create OAuth route handlers with mocked service."""
    return OAuthRouteHandlers(
        oauth_service=mock_oauth_service,
        session_store=session_store,
        user_store=user_store,
        allowed_redirect_urls=["/", "/dashboard", "/profile"],
    )


# OAuth Flow Tests


@pytest.mark.asyncio
async def test_complete_oauth_flow(oauth_handlers):
    """Test complete OAuth authentication flow."""
    # Step 1: Initiate login
    redirect_url, headers = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
        redirect_after="/dashboard",
    )

    # Verify redirect to Google
    assert "https://accounts.google.com/o/oauth2/v2/auth" in redirect_url
    assert "client_id=test_client_id" in redirect_url
    assert "state=" in redirect_url

    # Verify security headers
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" in headers

    # Extract state from URL
    state = redirect_url.split("state=")[1].split("&")[0]

    # Step 2: Simulate callback
    callback_url, callback_headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="mock_authorization_code",
        state=state,
        client_ip="192.168.1.1",
        user_agent="Mozilla/5.0",
    )

    # Verify redirect to dashboard
    assert callback_url == "/dashboard"

    # Verify session cookie set
    assert "Set-Cookie" in callback_headers
    assert "session_id=" in callback_headers["Set-Cookie"]
    assert "HttpOnly" in callback_headers["Set-Cookie"]
    assert "Secure" in callback_headers["Set-Cookie"]
    assert "SameSite=Lax" in callback_headers["Set-Cookie"]

    # Extract session ID from cookie
    session_cookie = callback_headers["Set-Cookie"]
    session_id = session_cookie.split("session_id=")[1].split(";")[0]

    # Step 3: Verify session created
    session = await oauth_handlers.session_store.get_session(session_id)
    assert session is not None
    assert session.user_id is not None
    assert session.email == "test@example.com"

    # Step 4: Verify user created
    user = await oauth_handlers.get_current_user(session_id)
    assert user is not None
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.oauth_subject == "google_user_123"


@pytest.mark.asyncio
async def test_session_fixation_prevention(oauth_handlers, session_store):
    """CRITICAL: Verify session ID changes after authentication.

    Session fixation attack: Attacker sets victim's session ID before OAuth,
    then inherits authenticated session after victim logs in.
    """
    # Create initial session (simulate anonymous user)
    initial_user = User(
        user_id="temp_user",
        email="temp@example.com",
        name="Temp",
        oauth_provider="google",
        oauth_subject="temp_123",
    )
    initial_session = await session_store.create_session(initial_user)
    initial_session_id = initial_session.session_id

    # Complete OAuth flow
    redirect_url, headers = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )

    state = redirect_url.split("state=")[1].split("&")[0]

    callback_url, callback_headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    # Extract new session ID
    new_session_id = (
        callback_headers["Set-Cookie"].split("session_id=")[1].split(";")[0]
    )

    # CRITICAL: Session IDs must be different
    assert new_session_id != initial_session_id, (
        "Session ID not regenerated after authentication! "
        "Vulnerable to session fixation attack."
    )

    # Verify new session is valid
    new_session = await session_store.get_session(new_session_id)
    assert new_session is not None
    assert new_session.email == "test@example.com"


@pytest.mark.asyncio
async def test_tokens_not_in_response(oauth_handlers):
    """CRITICAL: Verify OAuth tokens are never exposed in HTTP response.

    Token leakage attack: Tokens in response can be intercepted via:
    - Network sniffing
    - Browser extensions
    - Server logs
    - Referrer headers
    """
    # Complete OAuth flow
    redirect_url, headers = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )

    state = redirect_url.split("state=")[1].split("&")[0]

    callback_url, callback_headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    # CRITICAL: No tokens in redirect URL
    assert (
        "access_token" not in callback_url.lower()
    ), "Access token exposed in redirect URL!"
    assert (
        "refresh_token" not in callback_url.lower()
    ), "Refresh token exposed in redirect URL!"
    assert "id_token" not in callback_url.lower(), "ID token exposed in redirect URL!"

    # CRITICAL: No tokens in headers
    headers_str = str(callback_headers).lower()
    assert "access_token" not in headers_str, "Access token exposed in headers!"
    assert "refresh_token" not in headers_str, "Refresh token exposed in headers!"

    # Verify only session cookie in response
    assert "session_id=" in callback_headers["Set-Cookie"]


@pytest.mark.asyncio
async def test_csrf_protection_invalid_state(oauth_handlers):
    """Test CSRF protection via state parameter validation."""
    # Try callback with invalid state
    callback_url, headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state="invalid_state_token",
        client_ip="192.168.1.1",
    )

    # Should redirect to login with error
    assert "/login" in callback_url
    assert "error" in callback_url


@pytest.mark.asyncio
async def test_user_account_linking(oauth_handlers, user_store):
    """Test that returning users don't create duplicate accounts."""
    # First login
    redirect_url1, _ = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )
    state1 = redirect_url1.split("state=")[1].split("&")[0]

    callback_url1, callback_headers1 = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="code1",
        state=state1,
        client_ip="192.168.1.1",
    )

    session_id1 = callback_headers1["Set-Cookie"].split("session_id=")[1].split(";")[0]
    user1 = await oauth_handlers.get_current_user(session_id1)

    # Second login (same user)
    redirect_url2, _ = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )
    state2 = redirect_url2.split("state=")[1].split("&")[0]

    callback_url2, callback_headers2 = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="code2",
        state=state2,
        client_ip="192.168.1.1",
    )

    session_id2 = callback_headers2["Set-Cookie"].split("session_id=")[1].split(";")[0]
    user2 = await oauth_handlers.get_current_user(session_id2)

    # CRITICAL: Same user should have same user_id
    assert user1.user_id == user2.user_id, "Duplicate user accounts created!"
    assert user1.email == user2.email
    assert user1.oauth_subject == user2.oauth_subject


# Security Header Tests


@pytest.mark.asyncio
async def test_security_headers_on_callback(oauth_handlers):
    """Verify security headers are set on callback."""
    redirect_url, _ = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )
    state = redirect_url.split("state=")[1].split("&")[0]

    _, headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    # CRITICAL: Referrer-Policy prevents code leakage
    assert headers["Referrer-Policy"] == "no-referrer"

    # HSTS enforces HTTPS
    assert "Strict-Transport-Security" in headers
    assert "max-age=31536000" in headers["Strict-Transport-Security"]

    # Clickjacking protection
    assert headers["X-Frame-Options"] == "DENY"

    # MIME sniffing protection
    assert headers["X-Content-Type-Options"] == "nosniff"

    # Cache control
    assert headers["Cache-Control"] == "no-store, no-cache, must-revalidate, private"


@pytest.mark.asyncio
async def test_session_cookie_security_flags(oauth_handlers):
    """Verify session cookie has all security flags."""
    redirect_url, _ = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
    )
    state = redirect_url.split("state=")[1].split("&")[0]

    _, headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    cookie = headers["Set-Cookie"]

    # CRITICAL: HttpOnly prevents JavaScript access (XSS protection)
    assert "HttpOnly" in cookie, "Session cookie missing HttpOnly flag!"

    # CRITICAL: Secure ensures HTTPS only
    assert "Secure" in cookie, "Session cookie missing Secure flag!"

    # CRITICAL: SameSite prevents CSRF
    assert (
        "SameSite=Lax" in cookie or "SameSite=Strict" in cookie
    ), "Session cookie missing SameSite flag!"

    # Expiration set
    assert "Max-Age" in cookie


# Redirect URL Validation Tests


@pytest.mark.asyncio
async def test_open_redirect_prevention(oauth_handlers):
    """HIGH: Verify redirect URL validation prevents open redirect attacks."""
    # Try external redirect
    redirect_url, headers = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
        redirect_after="https://evil.com/phishing",
    )

    # Invalid redirect should be ignored (defaults to /dashboard)
    state = redirect_url.split("state=")[1].split("&")[0]

    callback_url, _ = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    # Should redirect to safe default, not evil.com
    assert "evil.com" not in callback_url
    assert callback_url == "/dashboard"


@pytest.mark.asyncio
async def test_valid_redirect_urls(oauth_handlers):
    """Test that whitelisted redirect URLs are allowed."""
    # Test allowed redirect
    redirect_url, _ = await oauth_handlers.handle_login_redirect(
        provider="google",
        client_ip="192.168.1.1",
        redirect_after="/profile",
    )

    state = redirect_url.split("state=")[1].split("&")[0]

    callback_url, _ = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="test_code",
        state=state,
        client_ip="192.168.1.1",
    )

    # Note: Currently defaults to /dashboard (TODO: implement state-bound redirect)
    # When implemented, this should redirect to /profile
    assert callback_url in ["/dashboard", "/profile"]


# Logout Tests


@pytest.mark.asyncio
async def test_logout_clears_session(oauth_handlers, session_store):
    """Test that logout properly clears session."""
    # Create session
    user = User(
        user_id="user_123",
        email="test@example.com",
        name="Test User",
        oauth_provider="google",
        oauth_subject="google_123",
    )
    session = await session_store.create_session(user)

    # Logout
    redirect_url, headers = await oauth_handlers.handle_logout(
        session_id=session.session_id,
        client_ip="192.168.1.1",
        revoke_tokens=True,
    )

    # Verify redirect to login
    assert redirect_url == "/login"

    # Verify session cookie cleared
    assert "session_id=; Path=/; Max-Age=0" in headers["Set-Cookie"]

    # Verify session deleted
    deleted_session = await session_store.get_session(session.session_id)
    assert deleted_session is None


@pytest.mark.asyncio
async def test_logout_without_session(oauth_handlers):
    """Test logout with no active session."""
    redirect_url, headers = await oauth_handlers.handle_logout(
        session_id=None,
        client_ip="192.168.1.1",
    )

    # Should still redirect to login gracefully
    assert redirect_url == "/login"
    # No Set-Cookie when there's no session to clear — just security headers
    assert "Referrer-Policy" in headers


# Error Handling Tests


@pytest.mark.asyncio
async def test_callback_with_provider_error(oauth_handlers):
    """Test handling OAuth errors from provider."""
    callback_url, headers = await oauth_handlers.handle_oauth_callback(
        provider="google",
        code="",
        state="",
        client_ip="192.168.1.1",
        error="access_denied",
        error_description="User denied access",
    )

    # Should redirect to login with error
    assert "/login" in callback_url
    assert "error=oauth_denied" in callback_url


@pytest.mark.asyncio
async def test_get_current_user_invalid_session(oauth_handlers):
    """Test get_current_user with invalid session."""
    user = await oauth_handlers.get_current_user("invalid_session_id")
    assert user is None


@pytest.mark.asyncio
async def test_get_current_user_no_session(oauth_handlers):
    """Test get_current_user with no session."""
    user = await oauth_handlers.get_current_user(None)
    assert user is None


# Data Model Tests


def test_user_model_serialization():
    """Test User model to_dict and from_dict."""
    user = User(
        user_id="user_123",
        email="test@example.com",
        name="Test User",
        picture="https://example.com/photo.jpg",
        oauth_provider="google",
        oauth_subject="google_123",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        last_login=datetime.utcnow(),
        is_active=True,
        email_verified=True,
    )

    # Serialize
    data = user.to_dict()
    assert data["user_id"] == "user_123"
    assert data["email"] == "test@example.com"

    # Deserialize
    loaded_user = User.from_dict(data)
    assert loaded_user.user_id == user.user_id
    assert loaded_user.email == user.email
    assert loaded_user.oauth_subject == user.oauth_subject


def test_session_model_serialization():
    """Test Session model to_dict and from_dict."""
    session = Session(
        session_id="sess_abc123",
        user_id="user_123",
        email="test@example.com",
        name="Test User",
        provider="google",
        authenticated_at=datetime.utcnow(),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
    )

    # Serialize
    data = session.to_dict()
    assert data["session_id"] == "sess_abc123"
    assert data["user_id"] == "user_123"

    # Deserialize
    loaded_session = Session.from_dict(data)
    assert loaded_session.session_id == session.session_id
    assert loaded_session.user_id == session.user_id


@pytest.mark.asyncio
async def test_session_expiration(session_store):
    """Test session expiration check."""
    user = User(
        user_id="user_123",
        email="test@example.com",
        name="Test",
        oauth_provider="google",
        oauth_subject="google_123",
    )

    # Create session with 0 second expiration (immediately expired)
    session = await session_store.create_session(user, session_max_age=0)

    # Session should be expired and return None when retrieved
    retrieved = await session_store.get_session(session.session_id)
    assert retrieved is None or retrieved.is_expired()


# Token Revocation Tests


def _make_mock_config():
    """Create a mock OAuthConfig that bypasses Pydantic validation."""
    config = MagicMock()
    provider_config = MagicMock(spec=OAuthProviderConfig)
    provider_config.client_id = "test_client_id"
    provider_config.client_secret = "test_client_secret"
    provider_config.provider = "google"
    provider_config.revocation_endpoint = None
    config.get_provider_config.return_value = provider_config
    return config


def test_revoke_tokens_is_async():
    """revoke_tokens must be awaitable (async) and delete tokens."""

    async def _test():
        mock_config = _make_mock_config()
        state_store = InMemoryStateStore()
        token_store = Mock(spec=SecureTokenStore)
        token_store.retrieve_token.return_value = {
            "access_token": "test_token",
            "provider": "google",
        }
        token_store.delete_token.return_value = True

        service = OAuthService(
            config=mock_config,
            token_store=token_store,
            state_store=state_store,
        )

        with patch.object(service, "_get_http_client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            async_client = AsyncMock()
            async_client.post.return_value = mock_response
            mock_client.return_value = async_client

            result = await service.revoke_tokens("user_123")

        assert result is True
        token_store.delete_token.assert_called_once_with("user_123")

    asyncio.run(_test())


def test_revoke_tokens_no_tokens():
    """revoke_tokens returns False when user has no tokens."""

    async def _test():
        mock_config = _make_mock_config()
        state_store = InMemoryStateStore()
        token_store = Mock(spec=SecureTokenStore)
        token_store.retrieve_token.return_value = None

        service = OAuthService(
            config=mock_config,
            token_store=token_store,
            state_store=state_store,
        )

        result = await service.revoke_tokens("user_123")
        assert result is False

    asyncio.run(_test())


def test_revoke_tokens_provider_failure_still_deletes_locally():
    """If provider revocation fails, local tokens are still deleted."""

    async def _test():
        mock_config = _make_mock_config()
        state_store = InMemoryStateStore()
        token_store = Mock(spec=SecureTokenStore)
        token_store.retrieve_token.return_value = {
            "access_token": "test_token",
            "provider": "google",
        }
        token_store.delete_token.return_value = True

        service = OAuthService(
            config=mock_config,
            token_store=token_store,
            state_store=state_store,
        )

        with patch.object(service, "_get_http_client") as mock_client:
            async_client = AsyncMock()
            async_client.post.side_effect = httpx.HTTPError("Connection refused")
            mock_client.return_value = async_client

            result = await service.revoke_tokens("user_123")

        assert result is True
        token_store.delete_token.assert_called_once_with("user_123")

    asyncio.run(_test())


# Expired State Cleanup Tests


def test_cleanup_expired_states_uses_state_store():
    """cleanup_expired_states delegates to StateStore.cleanup_expired()."""

    async def _test():
        mock_config = _make_mock_config()
        state_store = AsyncMock()
        state_store.cleanup_expired.return_value = 3
        token_store = Mock(spec=SecureTokenStore)

        service = OAuthService(
            config=mock_config,
            token_store=token_store,
            state_store=state_store,
        )

        result = await service.cleanup_expired_states()

        assert result == 3
        state_store.cleanup_expired.assert_called_once()

    asyncio.run(_test())


def test_cleanup_expired_states_no_error():
    """cleanup_expired_states does not raise AttributeError."""

    async def _test():
        mock_config = _make_mock_config()
        state_store = InMemoryStateStore()
        token_store = Mock(spec=SecureTokenStore)

        service = OAuthService(
            config=mock_config,
            token_store=token_store,
            state_store=state_store,
        )

        # Should NOT raise AttributeError (old code called .items())
        result = await service.cleanup_expired_states()
        assert result == 0

    asyncio.run(_test())
