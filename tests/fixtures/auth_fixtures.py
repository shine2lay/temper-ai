"""Shared auth fixtures for testing."""
import pytest
from datetime import datetime, timedelta, timezone


@pytest.fixture
def sample_user():
    """Sample user for auth tests."""
    from src.auth.models import User
    return User(
        user_id="test_user_123",
        email="test@example.com",
        name="Test User",
        oauth_provider="google",
        oauth_subject="google_123"
    )


@pytest.fixture
def sample_session(sample_user):
    """Sample session for session management tests."""
    from src.auth.models import Session
    return Session(
        session_id="sess_123",
        user_id=sample_user.user_id,
        email=sample_user.email,
        name=sample_user.name,
        picture=sample_user.picture,
        provider=sample_user.oauth_provider,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24)
    )


@pytest.fixture
def oauth_config():
    """Sample OAuth configuration."""
    from src.auth.oauth.config import OAuthProviderConfig
    return OAuthProviderConfig(
        provider="google",
        client_id="test_client",
        client_secret="test_secret",
        redirect_uri="http://localhost/callback",
        scopes=["openid", "email", "profile"]
    )
