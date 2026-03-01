"""Constants for the auth module.

Centralized constants for session management, rate limiting,
token configuration, and OAuth settings.
"""

# ============================================================================
# OAuth Field Names (Dictionary Keys)
# ============================================================================

FIELD_USER_ID = "user_id"
FIELD_EMAIL = "email"
FIELD_NAME = "name"
FIELD_PICTURE = "picture"
FIELD_EXPIRES_AT = "expires_at"
FIELD_ACCESS_TOKEN = "access_token"  # noqa: S105
FIELD_CLIENT_ID = "client_id"
FIELD_CLIENT_SECRET = "client_secret"  # noqa: S105
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
