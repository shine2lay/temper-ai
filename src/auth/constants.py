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
REFRESH_TOKEN_EXPIRY_DAYS = 30  # Number of days for refresh token validity
REFRESH_TOKEN_EXPIRY_SECONDS = SECONDS_PER_DAY * REFRESH_TOKEN_EXPIRY_DAYS  # 30 days
TOKEN_REFRESH_BUFFER_SECONDS = 300  # Refresh 5 min before expiry

# ============================================================================
# OAuth State
# ============================================================================

OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes
MAX_PENDING_STATES = 100
STATE_CLEANUP_INTERVAL = 60  # seconds

# ============================================================================
# OAuth Field Names (Dictionary Keys)
# ============================================================================

FIELD_USER_ID = "user_id"
FIELD_EMAIL = "email"
FIELD_NAME = "name"
FIELD_PICTURE = "picture"
FIELD_EXPIRES_AT = "expires_at"
FIELD_ACCESS_TOKEN = "access_token"
FIELD_REFRESH_TOKEN = "refresh_token"
FIELD_CLIENT_ID = "client_id"
FIELD_CLIENT_SECRET = "client_secret"
FIELD_CODE_VERIFIER = "code_verifier"
FIELD_PROVIDER = "provider"
FIELD_STORED_AT = "stored_at"
FIELD_ACTION = "action"
FIELD_TIMESTAMP = "timestamp"

# ============================================================================
# OAuth Providers
# ============================================================================

PROVIDER_GOOGLE = "google"

# ============================================================================
# Error Messages
# ============================================================================

ERROR_PROVIDER_NOT_CONFIGURED = "' not configured"
ERROR_PROVIDER_PREFIX = "Provider '"
ERROR_REDIS_NOT_AVAILABLE = "Redis connection not available"

# ============================================================================
# HTTP Headers
# ============================================================================

HEADER_ACCEPT = "Accept"
HEADER_SET_COOKIE = "Set-Cookie"
HEADER_CONTENT_TYPE_JSON = "application/json"

# ============================================================================
# Logging Format Strings
# ============================================================================

LOG_USER_SEPARATOR = ", user="
LOG_IP_SEPARATOR = ", IP="

# ============================================================================
# Route Paths
# ============================================================================

ROUTE_DASHBOARD = "/dashboard"

# ============================================================================
# Display Strings
# ============================================================================

DISPLAY_ELLIPSIS = "..."
