"""Authentication and authorization module."""
from temper_ai.auth.models import Session, User
from temper_ai.auth.routes import OAuthRouteHandlers
from temper_ai.auth.session import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionStoreProtocol,
)

__all__ = [
    # Models
    "User",
    "Session",
    # Session management
    "SessionStoreProtocol",
    "InMemorySessionStore",
    "RedisSessionStore",
    # Route handlers
    "OAuthRouteHandlers",
]
