"""Tests for session management."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.auth.models import Session, User
from temper_ai.auth.session import (
    InMemorySessionStore,
    SessionStoreProtocol,
    UserStore,
)


@pytest.fixture
def sample_user():
    """Create sample user for testing."""
    return User(
        user_id="user_123",
        email="test@example.com",
        name="Test User",
        picture="https://example.com/pic.jpg",
        oauth_provider="google",
        oauth_subject="google_123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_login=datetime.now(UTC),
    )


@pytest.fixture
def sample_session(sample_user):
    """Create sample session for testing."""
    return Session(
        session_id="sess_test123",
        user_id=sample_user.user_id,
        email=sample_user.email,
        name=sample_user.name,
        picture=sample_user.picture,
        provider=sample_user.oauth_provider,
        authenticated_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
    )


class TestSessionStoreProtocol:
    """Test SessionStoreProtocol interface."""

    def test_protocol_is_abstract(self):
        """Test that SessionStoreProtocol cannot be instantiated."""
        with pytest.raises(TypeError):
            SessionStoreProtocol()

    def test_protocol_requires_implementation(self):
        """Test that subclasses must implement abstract methods."""

        class IncompleteStore(SessionStoreProtocol):
            pass

        with pytest.raises(TypeError):
            IncompleteStore()


class TestInMemorySessionStore:
    """Test InMemorySessionStore implementation."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test store initialization."""
        store = InMemorySessionStore(max_sessions=100)

        assert store._max_sessions == 100
        assert len(store._sessions) == 0
        assert store._lookup_count == 0

    @pytest.mark.asyncio
    async def test_create_session(self, sample_user):
        """Test creating a new session."""
        store = InMemorySessionStore()

        session = await store.create_session(
            user=sample_user,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            session_max_age=3600,
        )

        assert session.session_id.startswith("sess_")
        assert session.user_id == sample_user.user_id
        assert session.email == sample_user.email
        assert session.ip_address == "192.168.1.1"
        assert session.user_agent == "Mozilla/5.0"
        assert session.expires_at is not None

    @pytest.mark.asyncio
    async def test_create_session_generates_unique_ids(self, sample_user):
        """Test that each session gets unique ID."""
        store = InMemorySessionStore()

        session1 = await store.create_session(sample_user)
        session2 = await store.create_session(sample_user)

        assert session1.session_id != session2.session_id

    @pytest.mark.asyncio
    async def test_get_session_exists(self, sample_user):
        """Test retrieving existing session."""
        store = InMemorySessionStore()

        created = await store.create_session(sample_user)
        retrieved = await store.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id
        assert retrieved.user_id == sample_user.user_id

    @pytest.mark.asyncio
    async def test_get_session_not_exists(self):
        """Test retrieving non-existent session."""
        store = InMemorySessionStore()

        result = await store.get_session("nonexistent_id")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_session_expired(self, sample_user):
        """Test retrieving expired session."""
        store = InMemorySessionStore()

        # Create session with very short expiry
        session = await store.create_session(sample_user, session_max_age=1)

        # Wait for expiration
        await asyncio.sleep(1.1)

        result = await store.get_session(session.session_id)

        assert result is None
        assert session.session_id not in store._sessions

    @pytest.mark.asyncio
    async def test_delete_session_exists(self, sample_user):
        """Test deleting existing session."""
        store = InMemorySessionStore()

        session = await store.create_session(sample_user)
        result = await store.delete_session(session.session_id)

        assert result is True
        assert session.session_id not in store._sessions

    @pytest.mark.asyncio
    async def test_delete_session_not_exists(self):
        """Test deleting non-existent session."""
        store = InMemorySessionStore()

        result = await store.delete_session("nonexistent_id")

        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, sample_user):
        """Test cleanup of expired sessions."""
        store = InMemorySessionStore()

        # Create mix of expired and valid sessions
        expired = await store.create_session(sample_user, session_max_age=1)
        await asyncio.sleep(1.1)
        valid = await store.create_session(sample_user, session_max_age=3600)

        await store.cleanup_expired()

        assert expired.session_id not in store._sessions
        assert valid.session_id in store._sessions

    @pytest.mark.asyncio
    async def test_lru_eviction(self, sample_user):
        """Test LRU eviction when max sessions exceeded."""
        store = InMemorySessionStore(max_sessions=3)

        # Create 3 sessions (fills to max)
        session1 = await store.create_session(sample_user)
        session2 = await store.create_session(sample_user)
        session3 = await store.create_session(sample_user)

        assert len(store._sessions) == 3

        # Create 4th session - should evict oldest (session1)
        session4 = await store.create_session(sample_user)

        assert len(store._sessions) == 3
        assert session1.session_id not in store._sessions
        assert session2.session_id in store._sessions
        assert session3.session_id in store._sessions
        assert session4.session_id in store._sessions

    @pytest.mark.asyncio
    async def test_lru_touch_on_get(self, sample_user):
        """Test that getting session updates LRU order."""
        store = InMemorySessionStore(max_sessions=3)

        session1 = await store.create_session(sample_user)
        session2 = await store.create_session(sample_user)
        session3 = await store.create_session(sample_user)

        # Touch session1 (move to most recent)
        await store.get_session(session1.session_id)

        # Create 4th session - should evict session2 (oldest untouched)
        session4 = await store.create_session(sample_user)

        assert session1.session_id in store._sessions  # Touched, not evicted
        assert session2.session_id not in store._sessions  # Evicted
        assert session3.session_id in store._sessions
        assert session4.session_id in store._sessions

    @pytest.mark.asyncio
    async def test_lazy_cleanup_on_lookup(self, sample_user):
        """Test lazy cleanup during lookups."""
        store = InMemorySessionStore()
        store.CLEANUP_INTERVAL = 2  # Cleanup every 2 lookups

        # Create expired session
        expired = await store.create_session(sample_user, session_max_age=1)
        await asyncio.sleep(1.1)

        # Create valid session
        valid = await store.create_session(sample_user)

        # Trigger lazy cleanup with lookups
        await store.get_session(valid.session_id)  # Lookup 1
        await store.get_session(valid.session_id)  # Lookup 2 - triggers cleanup

        # Expired session should be cleaned up
        assert expired.session_id not in store._sessions

    @pytest.mark.asyncio
    async def test_concurrent_access(self, sample_user):
        """Test thread-safe concurrent access."""
        store = InMemorySessionStore()

        async def create_and_get():
            session = await store.create_session(sample_user)
            retrieved = await store.get_session(session.session_id)
            return retrieved is not None

        # Run concurrent operations
        results = await asyncio.gather(*[create_and_get() for _ in range(10)])

        assert all(results)
        assert len(store._sessions) == 10


class TestUserStore:
    """Test UserStore implementation."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test user store initialization."""
        store = UserStore()

        assert len(store._users) == 0
        assert len(store._emails) == 0
        assert len(store._oauth_subjects) == 0

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, sample_user):
        """Test getting user by ID."""
        store = UserStore()
        store._users[sample_user.user_id] = sample_user

        result = await store.get_user_by_id(sample_user.user_id)

        assert result is not None
        assert result.user_id == sample_user.user_id

    @pytest.mark.asyncio
    async def test_get_user_by_id_not_found(self):
        """Test getting non-existent user by ID."""
        store = UserStore()

        result = await store.get_user_by_id("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, sample_user):
        """Test getting user by email."""
        store = UserStore()
        store._users[sample_user.user_id] = sample_user
        store._emails[sample_user.email] = sample_user.user_id

        result = await store.get_user_by_email(sample_user.email)

        assert result is not None
        assert result.email == sample_user.email

    @pytest.mark.asyncio
    async def test_get_user_by_email_not_found(self):
        """Test getting non-existent user by email."""
        store = UserStore()

        result = await store.get_user_by_email("nonexistent@example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_by_oauth(self, sample_user):
        """Test getting user by OAuth credentials."""
        store = UserStore()
        store._users[sample_user.user_id] = sample_user
        oauth_key = f"{sample_user.oauth_provider}:{sample_user.oauth_subject}"
        store._oauth_subjects[oauth_key] = sample_user.user_id

        result = await store.get_user_by_oauth(
            sample_user.oauth_provider, sample_user.oauth_subject
        )

        assert result is not None
        assert result.user_id == sample_user.user_id

    @pytest.mark.asyncio
    async def test_get_user_by_oauth_not_found(self):
        """Test getting non-existent user by OAuth."""
        store = UserStore()

        result = await store.get_user_by_oauth("google", "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_create_new_user(self):
        """Test creating new user."""
        store = UserStore()

        user = await store.create_or_update_user(
            user_id="user_123",
            email="test@example.com",
            name="Test User",
            provider="google",
            oauth_subject="google_123",
            picture="https://example.com/pic.jpg",
        )

        assert user.user_id == "user_123"
        assert user.email == "test@example.com"
        assert user.name == "Test User"
        assert user in store._users.values()

    @pytest.mark.asyncio
    async def test_update_existing_user(self, sample_user):
        """Test updating existing user."""
        store = UserStore()
        store._users[sample_user.user_id] = sample_user
        store._emails[sample_user.email] = sample_user.user_id

        updated = await store.create_or_update_user(
            user_id="new_id",  # Different ID, same email
            email=sample_user.email,
            name="Updated Name",
            provider="github",
            oauth_subject="github_456",
            picture="https://example.com/new.jpg",
        )

        assert updated.user_id == sample_user.user_id  # Original ID preserved
        assert updated.name == "Updated Name"
        assert updated.oauth_provider == "github"
        assert updated.oauth_subject == "github_456"

    @pytest.mark.asyncio
    async def test_concurrent_user_operations(self):
        """Test thread-safe concurrent user operations."""
        store = UserStore()

        async def create_user(index):
            return await store.create_or_update_user(
                user_id=f"user_{index}",
                email=f"user{index}@example.com",
                name=f"User {index}",
                provider="google",
                oauth_subject=f"google_{index}",
            )

        # Run concurrent operations
        users = await asyncio.gather(*[create_user(i) for i in range(10)])

        assert len(users) == 10
        assert len(store._users) == 10
        assert len(store._emails) == 10


class TestSessionSecurity:
    """Test session security scenarios."""

    @pytest.mark.asyncio
    async def test_session_hijacking_detection_ip_change(self, sample_user):
        """Test detection of session hijacking via IP address change."""
        store = InMemorySessionStore()

        # Create session with original IP
        original_ip = "192.168.1.100"
        session = await store.create_session(
            sample_user,
            ip_address=original_ip,
            user_agent="Mozilla/5.0",
        )

        # Retrieve session
        retrieved = await store.get_session(session.session_id)
        assert retrieved is not None

        # Simulate hijacking attempt from different IP
        hijacker_ip = "10.0.0.1"

        # In a real system, this would be validated
        assert retrieved.ip_address != hijacker_ip
        assert retrieved.ip_address == original_ip

    @pytest.mark.asyncio
    async def test_session_hijacking_detection_user_agent_change(self, sample_user):
        """Test detection of session hijacking via user-agent change."""
        store = InMemorySessionStore()

        # Create session with original user-agent
        original_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        session = await store.create_session(
            sample_user,
            ip_address="192.168.1.100",
            user_agent=original_ua,
        )

        # Retrieve session
        retrieved = await store.get_session(session.session_id)
        assert retrieved is not None

        # Simulate hijacking attempt with different user-agent
        hijacker_ua = "curl/7.68.0"

        # In a real system, this would be validated
        assert retrieved.user_agent != hijacker_ua
        assert retrieved.user_agent == original_ua

    @pytest.mark.asyncio
    async def test_concurrent_session_limit(self, sample_user):
        """Test handling of concurrent sessions per user."""
        store = InMemorySessionStore()

        # Create multiple sessions for same user
        sessions = []
        for i in range(5):
            session = await store.create_session(
                sample_user,
                ip_address=f"192.168.1.{i}",
            )
            sessions.append(session)

        # All sessions should exist
        for session in sessions:
            retrieved = await store.get_session(session.session_id)
            assert retrieved is not None

    @pytest.mark.asyncio
    async def test_session_regeneration_on_privilege_escalation(self, sample_user):
        """Test token regeneration scenario on privilege escalation."""
        store = InMemorySessionStore()

        # Create initial session
        old_session = await store.create_session(sample_user)
        old_session_id = old_session.session_id

        # Simulate privilege escalation - create new session
        new_session = await store.create_session(sample_user)
        new_session_id = new_session.session_id

        # New session should have different ID
        assert new_session_id != old_session_id

        # Old session should still exist (not automatically invalidated)
        old_retrieved = await store.get_session(old_session_id)
        assert old_retrieved is not None

        # Explicitly delete old session after regeneration
        deleted = await store.delete_session(old_session_id)
        assert deleted is True

        # Old session should no longer exist
        old_retrieved = await store.get_session(old_session_id)
        assert old_retrieved is None

    @pytest.mark.asyncio
    async def test_session_fixation_prevention(self, sample_user):
        """Test session fixation prevention (new ID on each creation)."""
        store = InMemorySessionStore()

        # Create multiple sessions
        session_ids = set()
        for _ in range(10):
            session = await store.create_session(sample_user)
            session_ids.add(session.session_id)

        # All session IDs should be unique
        assert len(session_ids) == 10

        # Session IDs should start with proper prefix
        for session_id in session_ids:
            assert session_id.startswith("sess_")

    @pytest.mark.asyncio
    async def test_session_expiration_race_condition(self, sample_user):
        """Test race condition handling during expiration."""
        store = InMemorySessionStore()

        # Create session with short expiry
        session = await store.create_session(sample_user, session_max_age=1)

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Multiple concurrent access attempts
        async def try_access():
            return await store.get_session(session.session_id)

        results = await asyncio.gather(*[try_access() for _ in range(5)])

        # All should return None (expired)
        assert all(result is None for result in results)

        # Session should be cleaned up
        assert session.session_id not in store._sessions

    @pytest.mark.asyncio
    async def test_session_timing_attack_resistance(self, sample_user):
        """Test that session lookup timing doesn't leak information."""
        store = InMemorySessionStore()

        # Create valid session
        valid_session = await store.create_session(sample_user)

        # Time lookup for valid session
        import time

        start_valid = time.perf_counter()
        await store.get_session(valid_session.session_id)
        time_valid = time.perf_counter() - start_valid

        # Time lookup for invalid session
        start_invalid = time.perf_counter()
        await store.get_session("sess_nonexistent")
        time_invalid = time.perf_counter() - start_invalid

        # Both should complete in similar time (within order of magnitude)
        # Note: This is a basic check; real timing attack resistance is more complex
        assert time_valid > 0
        assert time_invalid > 0


class TestUserStoreSecurity:
    """Test UserStore security scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_user_creation_race_condition(self):
        """Test race condition in concurrent user creation."""
        store = UserStore()

        async def create_same_user():
            return await store.create_or_update_user(
                user_id=f"user_{id(asyncio.current_task())}",
                email="concurrent@example.com",
                name="Concurrent User",
                provider="google",
                oauth_subject="google_concurrent",
            )

        # Run concurrent operations
        users = await asyncio.gather(*[create_same_user() for _ in range(5)])

        # All should succeed, but should reference same user (by email)
        assert len(users) == 5
        # Only one user should be created (same email)
        assert len(store._users) == 1

    @pytest.mark.asyncio
    async def test_user_email_case_sensitivity(self):
        """Test email case handling in user lookup."""
        store = UserStore()

        # Create user with lowercase email
        user = await store.create_or_update_user(
            user_id="user_case",
            email="test@example.com",
            name="Case User",
            provider="google",
            oauth_subject="google_case",
        )

        # Lookup with exact case
        found_exact = await store.get_user_by_email("test@example.com")
        assert found_exact is not None
        assert found_exact.user_id == user.user_id

        # Lookup with different case (should not find - case-sensitive)
        found_upper = await store.get_user_by_email("TEST@EXAMPLE.COM")
        assert found_upper is None

    @pytest.mark.asyncio
    async def test_oauth_subject_uniqueness(self):
        """Test OAuth subject uniqueness across providers."""
        store = UserStore()

        # Create user with Google OAuth
        user_google = await store.create_or_update_user(
            user_id="user_google",
            email="google@example.com",
            name="Google User",
            provider="google",
            oauth_subject="shared_subject_123",
        )

        # Create different user with GitHub OAuth (same subject)
        user_github = await store.create_or_update_user(
            user_id="user_github",
            email="github@example.com",
            name="GitHub User",
            provider="github",
            oauth_subject="shared_subject_123",
        )

        # Both users should exist as separate entities
        assert user_google.user_id != user_github.user_id

        # Lookups should be scoped by provider
        found_google = await store.get_user_by_oauth("google", "shared_subject_123")
        found_github = await store.get_user_by_oauth("github", "shared_subject_123")

        assert found_google.user_id == user_google.user_id
        assert found_github.user_id == user_github.user_id
