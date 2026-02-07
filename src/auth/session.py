"""Session management for authentication.

Handles session creation, validation, and cleanup with security best practices.
Provides a protocol-based abstraction for pluggable session storage backends.
"""
import abc
import asyncio
import json
import logging
import secrets
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.auth.models import Session, User

logger = logging.getLogger(__name__)


class SessionStoreProtocol(abc.ABC):
    """Abstract base class for session storage backends.

    All session store implementations must inherit from this ABC and
    implement the required abstract methods. This uses nominal subtyping
    (explicit inheritance) rather than structural subtyping (typing.Protocol)
    to ensure implementations are clearly marked as session stores.

    API-20: Consistently uses abc.ABC with @abc.abstractmethod decorators.
    Implementations: InMemorySessionStore, RedisSessionStore.
    """

    @abc.abstractmethod
    async def create_session(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_max_age: int = 3600,
    ) -> Session:
        """Create a new session for authenticated user."""
        ...

    @abc.abstractmethod
    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session by ID. Returns None if not found or expired."""
        ...

    @abc.abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete session by ID. Returns True if deleted."""
        ...

    @abc.abstractmethod
    async def cleanup_expired(self) -> None:
        """Remove all expired sessions."""
        ...


class InMemorySessionStore(SessionStoreProtocol):
    """In-memory session storage with LRU eviction.

    SECURITY WARNING: This is a simple in-memory implementation for development ONLY.
    This implementation is NOT suitable for production use.

    For production deployment, use RedisSessionStore or a database-backed store.

    Production issues with this implementation:
    - Session data loss on server restart
    - No session sharing across multiple server instances

    M-09: Enforces a maximum session count with LRU (least recently used)
    eviction to prevent unbounded memory growth.
    """

    CLEANUP_INTERVAL = 100  # Run cleanup every N lookups
    MAX_SESSIONS = 10000  # M-09: Maximum sessions before LRU eviction

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        """Initialize session store.

        Args:
            max_sessions: Maximum number of sessions before LRU eviction
                          (default: 10000)
        """
        # M-09: Use OrderedDict for O(1) LRU eviction
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()
        self._lookup_count = 0

    async def create_session(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_max_age: int = 3600,  # 1 hour default
    ) -> Session:
        """Create a new session for authenticated user.

        SECURITY: Generates cryptographically secure session ID.

        Args:
            user: Authenticated user
            ip_address: Client IP address
            user_agent: Client user agent string
            session_max_age: Session lifetime in seconds

        Returns:
            Created session
        """
        # Generate secure session ID
        session_id = f"sess_{secrets.token_urlsafe(32)}"

        # Create session with expiration
        session = Session(
            session_id=session_id,
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            picture=user.picture,
            provider=user.oauth_provider,
            authenticated_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=session_max_age),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Store session atomically with LRU eviction (M-09)
        async with self._lock:
            if session_id in self._sessions:
                # Move existing session to end (most recently used)
                self._sessions.move_to_end(session_id)
            elif len(self._sessions) >= self._max_sessions:
                # Evict least recently used session (oldest entry)
                evicted_id, _ = self._sessions.popitem(last=False)
                logger.info(
                    f"LRU eviction: removed session {evicted_id[:16]}... "
                    f"(max_sessions={self._max_sessions})"
                )
            self._sessions[session_id] = session

        logger.info(
            f"Session created: session_id={session_id[:16]}..., "
            f"user={user.user_id}"
        )

        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Session if found and not expired, None otherwise
        """
        async with self._lock:
            # Lazy cleanup: every CLEANUP_INTERVAL lookups, purge expired sessions
            self._lookup_count += 1
            if self._lookup_count >= self.CLEANUP_INTERVAL:
                self._lookup_count = 0
                now = datetime.now(timezone.utc)
                expired_ids = [
                    sid for sid, sess in self._sessions.items()
                    if sess.expires_at and now > sess.expires_at
                ]
                for sid in expired_ids:
                    del self._sessions[sid]
                if expired_ids:
                    logger.info(f"Lazy cleanup removed {len(expired_ids)} expired sessions")

            session = self._sessions.get(session_id)

            if not session:
                return None

            # Check expiration
            if session.is_expired():
                # Clean up expired session inline (already holding lock)
                del self._sessions[session_id]
                logger.info(f"Expired session removed: {session_id[:16]}...")
                return None

            # M-09: Touch session for LRU tracking (move to most recent)
            self._sessions.move_to_end(session_id)

            return session

    async def delete_session(self, session_id: str) -> bool:
        """Delete session by ID.

        Args:
            session_id: Session identifier

        Returns:
            True if session was deleted, False if not found
        """
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Session deleted: {session_id[:16]}...")
                return True
            return False

    async def cleanup_expired(self):
        """Remove all expired sessions."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            expired_ids = [
                sid
                for sid, session in self._sessions.items()
                if session.expires_at and now > session.expires_at
            ]

            for session_id in expired_ids:
                del self._sessions[session_id]

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired sessions")


class UserStore:
    """In-memory user storage.

    SECURITY WARNING: This is a simple in-memory implementation for development ONLY.
    For production, replace with database-backed storage (PostgreSQL, MySQL, etc.).

    Production requirements:
    - Persistent storage across restarts
    - ACID transactions for user creation/updates
    - Proper indexing on email and oauth_subject for performance
    - Database migrations for schema changes
    """

    def __init__(self):
        """Initialize user store."""
        self._users: Dict[str, User] = {}  # user_id -> User
        self._emails: Dict[str, str] = {}  # email -> user_id
        self._oauth_subjects: Dict[str, str] = {}  # (provider, subject) -> user_id
        self._lock = asyncio.Lock()

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID.

        Args:
            user_id: User identifier

        Returns:
            User if found, None otherwise
        """
        # AU-04: Read under lock to prevent torn reads while writes are in progress.
        async with self._lock:
            return self._users.get(user_id)

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise
        """
        async with self._lock:
            user_id = self._emails.get(email)
            if not user_id:
                return None
            return self._users.get(user_id)

    async def get_user_by_oauth(self, provider: str, oauth_subject: str) -> Optional[User]:
        """Get user by OAuth provider and subject ID.

        Args:
            provider: OAuth provider name (e.g., "google")
            oauth_subject: Provider's user ID

        Returns:
            User if found, None otherwise
        """
        async with self._lock:
            key = f"{provider}:{oauth_subject}"
            user_id = self._oauth_subjects.get(key)
            if not user_id:
                return None
            return self._users.get(user_id)

    async def create_or_update_user(
        self,
        user_id: str,
        email: str,
        name: str,
        provider: str,
        oauth_subject: str,
        picture: Optional[str] = None,
    ) -> User:
        """Create new user or update existing user.

        If user exists (by email or OAuth subject), updates their information.
        Otherwise creates new user account.

        Args:
            user_id: User identifier (used for new users)
            email: User email
            name: User display name
            provider: OAuth provider name
            oauth_subject: Provider's user ID
            picture: Profile picture URL

        Returns:
            Created or updated user
        """
        async with self._lock:
            # Check if user exists by email (inline lookup, already holding lock)
            existing_user_id = self._emails.get(email)
            existing_user = self._users.get(existing_user_id) if existing_user_id else None

            if existing_user:
                # Update existing user
                existing_user.name = name
                existing_user.picture = picture or existing_user.picture
                existing_user.oauth_provider = provider
                existing_user.oauth_subject = oauth_subject
                existing_user.updated_at = datetime.now(timezone.utc)
                existing_user.last_login = datetime.now(timezone.utc)

                # Update OAuth subject mapping
                oauth_key = f"{provider}:{oauth_subject}"
                self._oauth_subjects[oauth_key] = existing_user.user_id

                logger.info(f"User updated: {existing_user.user_id}")
                return existing_user

            # Create new user
            user = User(
                user_id=user_id,
                email=email,
                name=name,
                picture=picture,
                oauth_provider=provider,
                oauth_subject=oauth_subject,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                last_login=datetime.now(timezone.utc),
            )

            # Store user and all indexes atomically
            self._users[user_id] = user
            self._emails[email] = user_id
            oauth_key = f"{provider}:{oauth_subject}"
            self._oauth_subjects[oauth_key] = user_id

            logger.info(f"User created: {user_id}")
            return user


class RedisSessionStore(SessionStoreProtocol):
    """Redis-backed session storage for production deployments.

    Provides persistent, distributed session storage with automatic expiry.
    Requires the `redis` package: ``pip install redis``.

    Args:
        redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")
        key_prefix: Prefix for session keys in Redis (default: "session:")
    """

    def __init__(self, redis_url: str, key_prefix: str = "session:"):
        try:
            from redis import asyncio as aioredis
        except ImportError:
            raise ImportError(
                "RedisSessionStore requires the 'redis' package. "
                "Install it with: pip install redis"
            )
        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        self._key_prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"

    def _session_to_dict(self, session: Session) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "email": session.email,
            "name": session.name,
            "picture": session.picture,
            "provider": session.provider,
            "authenticated_at": session.authenticated_at.isoformat(),
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "ip_address": session.ip_address,
            "user_agent": session.user_agent,
        }

    def _dict_to_session(self, data: Dict[str, Any]) -> Session:
        return Session(
            session_id=data["session_id"],
            user_id=data["user_id"],
            email=data["email"],
            name=data["name"],
            picture=data.get("picture"),
            provider=data.get("provider"),
            authenticated_at=datetime.fromisoformat(data["authenticated_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
        )

    async def create_session(
        self,
        user: User,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_max_age: int = 3600,
    ) -> Session:
        session_id = f"sess_{secrets.token_urlsafe(32)}"
        session = Session(
            session_id=session_id,
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            picture=user.picture,
            provider=user.oauth_provider,
            authenticated_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=session_max_age),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        try:
            await self._redis.setex(
                self._key(session_id),
                session_max_age,
                json.dumps(self._session_to_dict(session)),
            )
        except Exception as e:
            logger.error(f"Redis error creating session: {e}")
            raise
        logger.info(f"Session created (Redis): session_id={session_id[:16]}..., user={user.user_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        try:
            data = await self._redis.get(self._key(session_id))
        except Exception as e:
            logger.error(f"Redis error getting session {session_id[:16]}...: {e}")
            return None
        if not data:
            return None
        session = self._dict_to_session(json.loads(data))
        if session.is_expired():
            try:
                await self._redis.delete(self._key(session_id))
            except Exception:
                pass  # Best-effort cleanup
            return None
        return session

    async def delete_session(self, session_id: str) -> bool:
        try:
            result = await self._redis.delete(self._key(session_id))
        except Exception as e:
            logger.error(f"Redis error deleting session {session_id[:16]}...: {e}")
            return False
        if result:
            logger.info(f"Session deleted (Redis): {session_id[:16]}...")
        return bool(result)

    async def cleanup_expired(self) -> None:
        # Redis TTL handles expiry automatically; this is a no-op.
        pass


# Backward compatibility alias
SessionStore = InMemorySessionStore
