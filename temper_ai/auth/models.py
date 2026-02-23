"""Authentication data models.

Contains models for users and sessions used in the authentication system.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from temper_ai.auth.constants import (
    FIELD_EMAIL,
    FIELD_EXPIRES_AT,
    FIELD_NAME,
    FIELD_PICTURE,
    FIELD_USER_ID,
    PROVIDER_GOOGLE,
)


@dataclass
class User:
    """User account data model.

    Represents a user account linked to an OAuth provider.
    Users are identified by email and linked to their OAuth provider's subject ID.
    """

    # Identity
    user_id: str  # Internal UUID
    email: str  # User email (unique)
    name: str  # Display name
    picture: str | None = None  # Profile picture URL

    # OAuth provider data
    oauth_provider: str = PROVIDER_GOOGLE  # Provider name
    oauth_subject: str = ""  # Provider's user ID

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_login: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Status
    is_active: bool = True  # Account status
    email_verified: bool = True  # Email verified via OAuth

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            FIELD_USER_ID: self.user_id,
            FIELD_EMAIL: self.email,
            FIELD_NAME: self.name,
            FIELD_PICTURE: self.picture,
            "oauth_provider": self.oauth_provider,
            "oauth_subject": self.oauth_subject,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_login": self.last_login.isoformat(),
            "is_active": self.is_active,
            "email_verified": self.email_verified,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "User":
        """Load from dictionary."""
        return cls(
            user_id=data[FIELD_USER_ID],
            email=data[FIELD_EMAIL],
            name=data[FIELD_NAME],
            picture=data.get(FIELD_PICTURE),
            oauth_provider=data.get("oauth_provider", PROVIDER_GOOGLE),
            oauth_subject=data.get("oauth_subject", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            last_login=datetime.fromisoformat(data["last_login"]),
            is_active=data.get("is_active", True),
            email_verified=data.get("email_verified", True),
        )


@dataclass
class Session:
    """User session data model.

    Represents an active user session with security metadata.
    Sessions are stored server-side and referenced by a secure cookie.
    """

    # Identity
    session_id: str  # Secure random session identifier
    user_id: str  # Link to user account

    # User data (cached for performance)
    email: str
    name: str
    picture: str | None = None

    # Authentication metadata
    provider: str = PROVIDER_GOOGLE
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    # Security metadata
    ip_address: str | None = None
    user_agent: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            FIELD_USER_ID: self.user_id,
            FIELD_EMAIL: self.email,
            FIELD_NAME: self.name,
            FIELD_PICTURE: self.picture,
            "provider": self.provider,
            "authenticated_at": self.authenticated_at.isoformat(),
            FIELD_EXPIRES_AT: self.expires_at.isoformat() if self.expires_at else None,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Load from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_id=data[FIELD_USER_ID],
            email=data[FIELD_EMAIL],
            name=data[FIELD_NAME],
            picture=data.get(FIELD_PICTURE),
            provider=data.get("provider", PROVIDER_GOOGLE),
            authenticated_at=datetime.fromisoformat(data["authenticated_at"]),
            expires_at=(
                datetime.fromisoformat(data[FIELD_EXPIRES_AT])
                if data.get(FIELD_EXPIRES_AT)
                else None
            ),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
        )

    def is_expired(self) -> bool:
        """Check if session has expired."""
        if not self.expires_at:
            return False
        return datetime.now(UTC) > self.expires_at
