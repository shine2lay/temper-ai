"""Constants for the auth module.

Centralized constants for session management, rate limiting,
token configuration, and OAuth settings.
"""

from src.constants.durations import (
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    TTL_LONG,
)

# ============================================================================
# Session Configuration
# ============================================================================

DEFAULT_MAX_SESSIONS_PER_USER = 5
DEFAULT_SESSION_INACTIVITY_TIMEOUT = SECONDS_PER_HOUR  # 1 hour
DEFAULT_SESSION_ABSOLUTE_TIMEOUT = SECONDS_PER_DAY  # 24 hours
SESSION_CLEANUP_INTERVAL = 300  # 5 minutes

# ============================================================================
# Rate Limiting
# ============================================================================

DEFAULT_RATE_LIMIT_WINDOW = 60  # 1 minute
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 100
LOGIN_RATE_LIMIT_WINDOW = 300  # 5 minutes
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
CALLBACK_RATE_LIMIT_MAX = 10  # Max callbacks per window

# ============================================================================
# Token Configuration
# ============================================================================

DEFAULT_TOKEN_EXPIRY_SECONDS = TTL_LONG  # 1 hour
REFRESH_TOKEN_EXPIRY_SECONDS = SECONDS_PER_DAY * 30  # 30 days
TOKEN_REFRESH_BUFFER_SECONDS = 300  # Refresh 5 min before expiry

# ============================================================================
# OAuth State
# ============================================================================

OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes
MAX_PENDING_STATES = 100
STATE_CLEANUP_INTERVAL = 60  # seconds
