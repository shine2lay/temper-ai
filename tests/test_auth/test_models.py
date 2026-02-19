"""Tests for authentication data models.

Tests cover User and Session models including:
- Model instantiation and defaults
- Serialization/deserialization (to_dict, from_dict)
- Session expiration logic
- Timestamp handling and timezone awareness
- Edge cases and security scenarios
"""
import pytest
from datetime import datetime, timedelta, timezone

from temper_ai.auth.models import User, Session


class TestUser:
    """Test User model."""

    def test_user_creation_minimal(self):
        """Test creating user with minimal required fields."""
        user = User(
            user_id="user_123",
            email="test@example.com",
            name="Test User",
        )

        assert user.user_id == "user_123"
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user.picture is None
        assert user.oauth_provider == "google"  # Default
        assert user.oauth_subject == ""  # Default
        assert user.is_active is True
        assert user.email_verified is True

    def test_user_creation_full(self):
        """Test creating user with all fields."""
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)
        last_login = datetime.now(timezone.utc)

        user = User(
            user_id="user_456",
            email="full@example.com",
            name="Full User",
            picture="https://example.com/pic.jpg",
            oauth_provider="github",
            oauth_subject="github_789",
            created_at=created_at,
            updated_at=updated_at,
            last_login=last_login,
            is_active=False,
            email_verified=False,
        )

        assert user.user_id == "user_456"
        assert user.email == "full@example.com"
        assert user.name == "Full User"
        assert user.picture == "https://example.com/pic.jpg"
        assert user.oauth_provider == "github"
        assert user.oauth_subject == "github_789"
        assert user.created_at == created_at
        assert user.updated_at == updated_at
        assert user.last_login == last_login
        assert user.is_active is False
        assert user.email_verified is False

    def test_user_default_timestamps(self):
        """Test that timestamps are auto-generated with timezone."""
        before = datetime.now(timezone.utc)
        user = User(
            user_id="user_789",
            email="time@example.com",
            name="Time User",
        )
        after = datetime.now(timezone.utc)

        # Timestamps should be within test execution window
        assert before <= user.created_at <= after
        assert before <= user.updated_at <= after
        assert before <= user.last_login <= after

        # All timestamps should be timezone-aware
        assert user.created_at.tzinfo is not None
        assert user.updated_at.tzinfo is not None
        assert user.last_login.tzinfo is not None

    def test_user_to_dict(self):
        """Test converting user to dictionary."""
        created_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        last_login = datetime(2025, 1, 3, 12, 0, 0, tzinfo=timezone.utc)

        user = User(
            user_id="user_dict",
            email="dict@example.com",
            name="Dict User",
            picture="https://example.com/dict.jpg",
            oauth_provider="google",
            oauth_subject="google_dict",
            created_at=created_at,
            updated_at=updated_at,
            last_login=last_login,
            is_active=True,
            email_verified=True,
        )

        user_dict = user.to_dict()

        assert user_dict["user_id"] == "user_dict"
        assert user_dict["email"] == "dict@example.com"
        assert user_dict["name"] == "Dict User"
        assert user_dict["picture"] == "https://example.com/dict.jpg"
        assert user_dict["oauth_provider"] == "google"
        assert user_dict["oauth_subject"] == "google_dict"
        assert user_dict["created_at"] == created_at.isoformat()
        assert user_dict["updated_at"] == updated_at.isoformat()
        assert user_dict["last_login"] == last_login.isoformat()
        assert user_dict["is_active"] is True
        assert user_dict["email_verified"] is True

    def test_user_to_dict_none_picture(self):
        """Test to_dict with None picture."""
        user = User(
            user_id="user_no_pic",
            email="nopic@example.com",
            name="No Pic User",
            picture=None,
        )

        user_dict = user.to_dict()

        assert user_dict["picture"] is None

    def test_user_from_dict_full(self):
        """Test creating user from full dictionary."""
        data = {
            "user_id": "user_from_dict",
            "email": "fromdict@example.com",
            "name": "From Dict User",
            "picture": "https://example.com/from.jpg",
            "oauth_provider": "github",
            "oauth_subject": "github_from",
            "created_at": "2025-01-01T12:00:00+00:00",
            "updated_at": "2025-01-02T12:00:00+00:00",
            "last_login": "2025-01-03T12:00:00+00:00",
            "is_active": False,
            "email_verified": False,
        }

        user = User.from_dict(data)

        assert user.user_id == "user_from_dict"
        assert user.email == "fromdict@example.com"
        assert user.name == "From Dict User"
        assert user.picture == "https://example.com/from.jpg"
        assert user.oauth_provider == "github"
        assert user.oauth_subject == "github_from"
        assert user.created_at == datetime.fromisoformat(data["created_at"])
        assert user.updated_at == datetime.fromisoformat(data["updated_at"])
        assert user.last_login == datetime.fromisoformat(data["last_login"])
        assert user.is_active is False
        assert user.email_verified is False

    def test_user_from_dict_minimal(self):
        """Test creating user from minimal dictionary (missing optional fields)."""
        data = {
            "user_id": "user_minimal",
            "email": "minimal@example.com",
            "name": "Minimal User",
            "created_at": "2025-01-01T12:00:00+00:00",
            "updated_at": "2025-01-02T12:00:00+00:00",
            "last_login": "2025-01-03T12:00:00+00:00",
        }

        user = User.from_dict(data)

        assert user.user_id == "user_minimal"
        assert user.email == "minimal@example.com"
        assert user.name == "Minimal User"
        assert user.picture is None
        assert user.oauth_provider == "google"  # Default
        assert user.oauth_subject == ""  # Default
        assert user.is_active is True  # Default
        assert user.email_verified is True  # Default

    def test_user_roundtrip_serialization(self):
        """Test that to_dict and from_dict are symmetric."""
        original = User(
            user_id="roundtrip",
            email="roundtrip@example.com",
            name="Roundtrip User",
            picture="https://example.com/roundtrip.jpg",
            oauth_provider="github",
            oauth_subject="github_roundtrip",
            created_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2025, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            last_login=datetime(2025, 1, 3, 12, 0, 0, tzinfo=timezone.utc),
            is_active=False,
            email_verified=True,
        )

        # Serialize and deserialize
        user_dict = original.to_dict()
        restored = User.from_dict(user_dict)

        # Compare all fields
        assert restored.user_id == original.user_id
        assert restored.email == original.email
        assert restored.name == original.name
        assert restored.picture == original.picture
        assert restored.oauth_provider == original.oauth_provider
        assert restored.oauth_subject == original.oauth_subject
        assert restored.created_at == original.created_at
        assert restored.updated_at == original.updated_at
        assert restored.last_login == original.last_login
        assert restored.is_active == original.is_active
        assert restored.email_verified == original.email_verified


class TestSession:
    """Test Session model."""

    def test_session_creation_minimal(self):
        """Test creating session with minimal required fields."""
        session = Session(
            session_id="sess_123",
            user_id="user_123",
            email="test@example.com",
            name="Test User",
        )

        assert session.session_id == "sess_123"
        assert session.user_id == "user_123"
        assert session.email == "test@example.com"
        assert session.name == "Test User"
        assert session.picture is None
        assert session.provider == "google"  # Default
        assert session.expires_at is None
        assert session.ip_address is None
        assert session.user_agent is None

    def test_session_creation_full(self):
        """Test creating session with all fields."""
        authenticated_at = datetime.now(timezone.utc)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        session = Session(
            session_id="sess_full",
            user_id="user_full",
            email="full@example.com",
            name="Full User",
            picture="https://example.com/full.jpg",
            provider="github",
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
        )

        assert session.session_id == "sess_full"
        assert session.user_id == "user_full"
        assert session.email == "full@example.com"
        assert session.name == "Full User"
        assert session.picture == "https://example.com/full.jpg"
        assert session.provider == "github"
        assert session.authenticated_at == authenticated_at
        assert session.expires_at == expires_at
        assert session.ip_address == "192.168.1.100"
        assert session.user_agent == "Mozilla/5.0"

    def test_session_default_authenticated_at(self):
        """Test that authenticated_at is auto-generated with timezone."""
        before = datetime.now(timezone.utc)
        session = Session(
            session_id="sess_time",
            user_id="user_time",
            email="time@example.com",
            name="Time User",
        )
        after = datetime.now(timezone.utc)

        assert before <= session.authenticated_at <= after
        assert session.authenticated_at.tzinfo is not None

    def test_session_is_expired_no_expiry(self):
        """Test is_expired returns False when no expiry set."""
        session = Session(
            session_id="sess_no_expiry",
            user_id="user_no_expiry",
            email="noexpiry@example.com",
            name="No Expiry User",
            expires_at=None,
        )

        assert session.is_expired() is False

    def test_session_is_expired_valid(self):
        """Test is_expired returns False for valid session."""
        session = Session(
            session_id="sess_valid",
            user_id="user_valid",
            email="valid@example.com",
            name="Valid User",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        assert session.is_expired() is False

    def test_session_is_expired_expired(self):
        """Test is_expired returns True for expired session."""
        session = Session(
            session_id="sess_expired",
            user_id="user_expired",
            email="expired@example.com",
            name="Expired User",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        assert session.is_expired() is True

    def test_session_is_expired_boundary(self):
        """Test is_expired boundary case (exactly at expiry)."""
        # Session expires in microseconds from now
        expires_at = datetime.now(timezone.utc) + timedelta(microseconds=100)
        session = Session(
            session_id="sess_boundary",
            user_id="user_boundary",
            email="boundary@example.com",
            name="Boundary User",
            expires_at=expires_at,
        )

        # Should not be expired immediately
        assert session.is_expired() is False

        # Wait for expiry (small delay)
        import time
        time.sleep(0.001)

        # Should be expired now
        assert session.is_expired() is True

    def test_session_to_dict(self):
        """Test converting session to dictionary."""
        authenticated_at = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        expires_at = datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        session = Session(
            session_id="sess_dict",
            user_id="user_dict",
            email="dict@example.com",
            name="Dict User",
            picture="https://example.com/dict.jpg",
            provider="github",
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            ip_address="10.0.0.1",
            user_agent="Chrome/90",
        )

        session_dict = session.to_dict()

        assert session_dict["session_id"] == "sess_dict"
        assert session_dict["user_id"] == "user_dict"
        assert session_dict["email"] == "dict@example.com"
        assert session_dict["name"] == "Dict User"
        assert session_dict["picture"] == "https://example.com/dict.jpg"
        assert session_dict["provider"] == "github"
        assert session_dict["authenticated_at"] == authenticated_at.isoformat()
        assert session_dict["expires_at"] == expires_at.isoformat()
        assert session_dict["ip_address"] == "10.0.0.1"
        assert session_dict["user_agent"] == "Chrome/90"

    def test_session_to_dict_none_values(self):
        """Test to_dict with None values."""
        session = Session(
            session_id="sess_none",
            user_id="user_none",
            email="none@example.com",
            name="None User",
            picture=None,
            expires_at=None,
            ip_address=None,
            user_agent=None,
        )

        session_dict = session.to_dict()

        assert session_dict["picture"] is None
        assert session_dict["expires_at"] is None
        assert session_dict["ip_address"] is None
        assert session_dict["user_agent"] is None

    def test_session_from_dict_full(self):
        """Test creating session from full dictionary."""
        data = {
            "session_id": "sess_from_dict",
            "user_id": "user_from_dict",
            "email": "fromdict@example.com",
            "name": "From Dict User",
            "picture": "https://example.com/from.jpg",
            "provider": "github",
            "authenticated_at": "2025-01-01T12:00:00+00:00",
            "expires_at": "2025-01-01T13:00:00+00:00",
            "ip_address": "172.16.0.1",
            "user_agent": "Safari/14",
        }

        session = Session.from_dict(data)

        assert session.session_id == "sess_from_dict"
        assert session.user_id == "user_from_dict"
        assert session.email == "fromdict@example.com"
        assert session.name == "From Dict User"
        assert session.picture == "https://example.com/from.jpg"
        assert session.provider == "github"
        assert session.authenticated_at == datetime.fromisoformat(data["authenticated_at"])
        assert session.expires_at == datetime.fromisoformat(data["expires_at"])
        assert session.ip_address == "172.16.0.1"
        assert session.user_agent == "Safari/14"

    def test_session_from_dict_minimal(self):
        """Test creating session from minimal dictionary."""
        data = {
            "session_id": "sess_minimal",
            "user_id": "user_minimal",
            "email": "minimal@example.com",
            "name": "Minimal User",
            "authenticated_at": "2025-01-01T12:00:00+00:00",
        }

        session = Session.from_dict(data)

        assert session.session_id == "sess_minimal"
        assert session.user_id == "user_minimal"
        assert session.email == "minimal@example.com"
        assert session.name == "Minimal User"
        assert session.picture is None
        assert session.provider == "google"  # Default
        assert session.expires_at is None
        assert session.ip_address is None
        assert session.user_agent is None

    def test_session_roundtrip_serialization(self):
        """Test that to_dict and from_dict are symmetric."""
        original = Session(
            session_id="sess_roundtrip",
            user_id="user_roundtrip",
            email="roundtrip@example.com",
            name="Roundtrip User",
            picture="https://example.com/roundtrip.jpg",
            provider="github",
            authenticated_at=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            expires_at=datetime(2025, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            ip_address="203.0.113.1",
            user_agent="Edge/90",
        )

        # Serialize and deserialize
        session_dict = original.to_dict()
        restored = Session.from_dict(session_dict)

        # Compare all fields
        assert restored.session_id == original.session_id
        assert restored.user_id == original.user_id
        assert restored.email == original.email
        assert restored.name == original.name
        assert restored.picture == original.picture
        assert restored.provider == original.provider
        assert restored.authenticated_at == original.authenticated_at
        assert restored.expires_at == original.expires_at
        assert restored.ip_address == original.ip_address
        assert restored.user_agent == original.user_agent

    def test_session_security_metadata_tracking(self):
        """Test that security metadata (IP, user-agent) is properly tracked."""
        # Simulate session hijacking scenario
        original_session = Session(
            session_id="sess_security",
            user_id="user_security",
            email="security@example.com",
            name="Security User",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        # Verify original metadata
        assert original_session.ip_address == "192.168.1.100"
        assert original_session.user_agent == "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

        # Simulate different IP/user-agent (potential hijacking)
        suspicious_ip = "10.0.0.1"
        suspicious_ua = "curl/7.68.0"

        # In a real system, these would be compared to detect hijacking
        assert original_session.ip_address != suspicious_ip
        assert original_session.user_agent != suspicious_ua
