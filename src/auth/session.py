"""Session management for authentication.

Handles session creation, validation, and cleanup with security best practices.
"""
import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

from src.auth.models import Session, User

logger = logging.getLogger(__name__)


class SessionStore:
    """In-memory session storage.

    SECURITY WARNING: This is a simple in-memory implementation for development ONLY.
    This implementation is NOT thread-safe and NOT suitable for production use.

    For production deployment, you MUST replace this with:
    - Redis-backed storage with proper connection pooling
    - Database-backed storage with async ORM (SQLAlchemy async, etc.)
    - Distributed session store for multi-server deployments

    Production issues with this implementation:
    - Race conditions with concurrent authentication requests
    - Session data loss on server restart
    - No session sharing across multiple server instances
    - No automatic session cleanup/expiry

    Example production implementation using Redis:
        from redis import asyncio as aioredis

        class RedisSessionStore:
            def __init__(self, redis_url: str):
                self.redis = aioredis.from_url(redis_url)

            async def create_session(self, user, ...):
                session = Session(...)
                await self.redis.setex(
                    f"session:{session.session_id}",
                    3600,
                    session.to_dict()
                )
                return session
    """

    def __init__(self):
        """Initialize session store."""
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()

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
            authenticated_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=session_max_age),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Store session atomically
        async with self._lock:
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
            session = self._sessions.get(session_id)

            if not session:
                return None

            # Check expiration
            if session.is_expired():
                # Clean up expired session inline (already holding lock)
                del self._sessions[session_id]
                logger.info(f"Expired session removed: {session_id[:16]}...")
                return None

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
            now = datetime.utcnow()
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
                existing_user.updated_at = datetime.utcnow()
                existing_user.last_login = datetime.utcnow()

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
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                last_login=datetime.utcnow(),
            )

            # Store user and all indexes atomically
            self._users[user_id] = user
            self._emails[email] = user_id
            oauth_key = f"{provider}:{oauth_subject}"
            self._oauth_subjects[oauth_key] = user_id

            logger.info(f"User created: {user_id}")
            return user
