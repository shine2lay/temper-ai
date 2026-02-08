"""Tests for session management."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.auth.models import Session, User
from src.auth.session import (
    InMemorySessionStore,
    RedisSessionStore,
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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        last_login=datetime.now(timezone.utc),
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
        authenticated_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
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
            sample_user.oauth_provider,
            sample_user.oauth_subject
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


class TestRedisSessionStore:
    """Test RedisSessionStore implementation."""

    @pytest.mark.asyncio
    async def test_initialization_without_redis(self):
        """Test initialization fails without redis package."""
        with patch.dict('sys.modules', {'redis': None}):
            with pytest.raises(ImportError, match="redis"):
                RedisSessionStore("redis://localhost:6379")

    @pytest.mark.asyncio
    async def test_initialization_with_redis(self):
        """Test initialization with redis package."""
        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=Mock())

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379/0")

            assert store._key_prefix == "session:"
            mock_redis_module.asyncio.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_key_generation(self):
        """Test Redis key generation."""
        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=Mock())

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379", key_prefix="test:")

            key = store._key("session_123")
            assert key == "test:session_123"

    @pytest.mark.asyncio
    async def test_session_to_dict(self, sample_session):
        """Test converting session to dict."""
        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=Mock())

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            session_dict = store._session_to_dict(sample_session)

            assert session_dict["session_id"] == sample_session.session_id
            assert session_dict["user_id"] == sample_session.user_id
            assert session_dict["email"] == sample_session.email
            assert isinstance(session_dict["authenticated_at"], str)

    @pytest.mark.asyncio
    async def test_dict_to_session(self, sample_session):
        """Test converting dict to session."""
        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=Mock())

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            session_dict = store._session_to_dict(sample_session)
            restored = store._dict_to_session(session_dict)

            assert restored.session_id == sample_session.session_id
            assert restored.user_id == sample_session.user_id
            assert restored.email == sample_session.email

    @pytest.mark.asyncio
    async def test_create_session(self, sample_user):
        """Test creating session in Redis."""
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=mock_redis)

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            session = await store.create_session(
                user=sample_user,
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
                session_max_age=3600,
            )

            assert session.session_id.startswith("sess_")
            assert session.user_id == sample_user.user_id
            mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session(self, sample_session):
        """Test retrieving session from Redis."""
        mock_redis = AsyncMock()

        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=mock_redis)

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            # Mock Redis returning serialized session
            session_dict = store._session_to_dict(sample_session)
            import json
            mock_redis.get = AsyncMock(return_value=json.dumps(session_dict))

            result = await store.get_session(sample_session.session_id)

            assert result is not None
            assert result.session_id == sample_session.session_id

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        """Test retrieving non-existent session from Redis."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=mock_redis)

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            result = await store.get_session("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test deleting session from Redis."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=1)

        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=mock_redis)

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            result = await store.delete_session("session_123")

            assert result is True
            mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_expired_noop(self):
        """Test cleanup_expired is no-op for Redis (TTL handles it)."""
        mock_redis = AsyncMock()

        mock_redis_module = Mock()
        mock_redis_module.asyncio.from_url = Mock(return_value=mock_redis)

        with patch.dict('sys.modules', {'redis': mock_redis_module}):
            store = RedisSessionStore("redis://localhost:6379")

            # Should not raise
            await store.cleanup_expired()
