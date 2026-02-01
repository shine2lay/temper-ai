"""Authentication data models.

Contains models for users and sessions used in the authentication system.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
    picture: Optional[str] = None  # Profile picture URL

    # OAuth provider data
    oauth_provider: str = "google"  # Provider name
    oauth_subject: str = ""  # Provider's user ID

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_login: datetime = field(default_factory=datetime.utcnow)

    # Status
    is_active: bool = True  # Account status
    email_verified: bool = True  # Email verified via OAuth

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
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
            user_id=data["user_id"],
            email=data["email"],
            name=data["name"],
            picture=data.get("picture"),
            oauth_provider=data.get("oauth_provider", "google"),
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
    Sessions are stored server-side (Redis/database) and referenced by a secure cookie.
    """

    # Identity
    session_id: str  # Secure random session identifier
    user_id: str  # Link to user account

    # User data (cached for performance)
    email: str
    name: str
    picture: Optional[str] = None

    # Authentication metadata
    provider: str = "google"
    authenticated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    # Security metadata
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "picture": self.picture,
            "provider": self.provider,
            "authenticated_at": self.authenticated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """Load from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            email=data["email"],
            name=data["name"],
            picture=data.get("picture"),
            provider=data.get("provider", "google"),
            authenticated_at=datetime.fromisoformat(data["authenticated_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
        )

    def is_expired(self) -> bool:
        """Check if session has expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
