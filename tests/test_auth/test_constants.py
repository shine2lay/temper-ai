"""Tests for auth constants.

Tests verify that auth constants are properly defined and have sensible values
for session management, rate limiting, tokens, and OAuth settings.
"""

from temper_ai.auth.constants import (
    CALLBACK_RATE_LIMIT_MAX,
    # Session Configuration
    DEFAULT_MAX_SESSIONS_PER_USER,
    DEFAULT_RATE_LIMIT_MAX_REQUESTS,
    # Rate Limiting
    DEFAULT_RATE_LIMIT_WINDOW,
    DEFAULT_SESSION_ABSOLUTE_TIMEOUT,
    DEFAULT_SESSION_INACTIVITY_TIMEOUT,
    # Token Configuration
    DEFAULT_TOKEN_EXPIRY_SECONDS,
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    LOGIN_RATE_LIMIT_WINDOW,
    MAX_PENDING_STATES,
    # OAuth State
    OAUTH_STATE_TTL_SECONDS,
    REFRESH_TOKEN_EXPIRY_DAYS,
    REFRESH_TOKEN_EXPIRY_SECONDS,
    SESSION_CLEANUP_INTERVAL,
    STATE_CLEANUP_INTERVAL,
    TOKEN_REFRESH_BUFFER_SECONDS,
)


class TestSessionConfiguration:
    """Test session configuration constants."""

    def test_max_sessions_per_user_positive(self):
        """Test that max sessions per user is a positive integer."""
        assert isinstance(DEFAULT_MAX_SESSIONS_PER_USER, int)
        assert DEFAULT_MAX_SESSIONS_PER_USER > 0
        assert DEFAULT_MAX_SESSIONS_PER_USER == 5

    def test_session_inactivity_timeout_positive(self):
        """Test that inactivity timeout is positive."""
        assert isinstance(DEFAULT_SESSION_INACTIVITY_TIMEOUT, int)
        assert DEFAULT_SESSION_INACTIVITY_TIMEOUT > 0
        # Should be 1 hour (3600 seconds)
        assert DEFAULT_SESSION_INACTIVITY_TIMEOUT == 3600

    def test_session_absolute_timeout_positive(self):
        """Test that absolute timeout is positive."""
        assert isinstance(DEFAULT_SESSION_ABSOLUTE_TIMEOUT, int)
        assert DEFAULT_SESSION_ABSOLUTE_TIMEOUT > 0
        # Should be 24 hours (86400 seconds)
        assert DEFAULT_SESSION_ABSOLUTE_TIMEOUT == 86400

    def test_session_cleanup_interval_positive(self):
        """Test that cleanup interval is positive."""
        assert isinstance(SESSION_CLEANUP_INTERVAL, int)
        assert SESSION_CLEANUP_INTERVAL > 0
        # Should be 5 minutes (300 seconds)
        assert SESSION_CLEANUP_INTERVAL == 300

    def test_absolute_timeout_greater_than_inactivity(self):
        """Test that absolute timeout is greater than inactivity timeout."""
        assert DEFAULT_SESSION_ABSOLUTE_TIMEOUT > DEFAULT_SESSION_INACTIVITY_TIMEOUT

    def test_cleanup_interval_reasonable(self):
        """Test that cleanup interval is reasonable (not too frequent/infrequent)."""
        # Should be less than inactivity timeout
        assert SESSION_CLEANUP_INTERVAL < DEFAULT_SESSION_INACTIVITY_TIMEOUT
        # Should be at least 1 minute
        assert SESSION_CLEANUP_INTERVAL >= 60


class TestRateLimiting:
    """Test rate limiting constants."""

    def test_default_rate_limit_window_positive(self):
        """Test that default rate limit window is positive."""
        assert isinstance(DEFAULT_RATE_LIMIT_WINDOW, int)
        assert DEFAULT_RATE_LIMIT_WINDOW > 0
        # Should be 1 minute (60 seconds)
        assert DEFAULT_RATE_LIMIT_WINDOW == 60

    def test_default_rate_limit_max_requests_positive(self):
        """Test that default max requests is positive."""
        assert isinstance(DEFAULT_RATE_LIMIT_MAX_REQUESTS, int)
        assert DEFAULT_RATE_LIMIT_MAX_REQUESTS > 0
        assert DEFAULT_RATE_LIMIT_MAX_REQUESTS == 100

    def test_login_rate_limit_window_positive(self):
        """Test that login rate limit window is positive."""
        assert isinstance(LOGIN_RATE_LIMIT_WINDOW, int)
        assert LOGIN_RATE_LIMIT_WINDOW > 0
        # Should be 5 minutes (300 seconds)
        assert LOGIN_RATE_LIMIT_WINDOW == 300

    def test_login_rate_limit_max_attempts_positive(self):
        """Test that login max attempts is positive."""
        assert isinstance(LOGIN_RATE_LIMIT_MAX_ATTEMPTS, int)
        assert LOGIN_RATE_LIMIT_MAX_ATTEMPTS > 0
        assert LOGIN_RATE_LIMIT_MAX_ATTEMPTS == 5

    def test_callback_rate_limit_max_positive(self):
        """Test that callback rate limit max is positive."""
        assert isinstance(CALLBACK_RATE_LIMIT_MAX, int)
        assert CALLBACK_RATE_LIMIT_MAX > 0
        assert CALLBACK_RATE_LIMIT_MAX == 10

    def test_login_limits_stricter_than_defaults(self):
        """Test that login rate limits are stricter than defaults."""
        # Login should have fewer attempts allowed
        assert LOGIN_RATE_LIMIT_MAX_ATTEMPTS < DEFAULT_RATE_LIMIT_MAX_REQUESTS
        # Login window should be longer (more restrictive)
        assert LOGIN_RATE_LIMIT_WINDOW > DEFAULT_RATE_LIMIT_WINDOW

    def test_rate_limit_windows_reasonable(self):
        """Test that rate limit windows are reasonable (not too short/long)."""
        # Default window should be at least 10 seconds
        assert DEFAULT_RATE_LIMIT_WINDOW >= 10
        # Login window should be at least 1 minute
        assert LOGIN_RATE_LIMIT_WINDOW >= 60
        # Windows shouldn't be excessively long (more than 1 hour)
        assert DEFAULT_RATE_LIMIT_WINDOW <= 3600
        assert LOGIN_RATE_LIMIT_WINDOW <= 3600


class TestTokenConfiguration:
    """Test token configuration constants."""

    def test_default_token_expiry_positive(self):
        """Test that default token expiry is positive."""
        assert isinstance(DEFAULT_TOKEN_EXPIRY_SECONDS, int)
        assert DEFAULT_TOKEN_EXPIRY_SECONDS > 0
        # Should be 1 hour (3600 seconds)
        assert DEFAULT_TOKEN_EXPIRY_SECONDS == 3600

    def test_refresh_token_expiry_days_positive(self):
        """Test that refresh token expiry days is positive."""
        assert isinstance(REFRESH_TOKEN_EXPIRY_DAYS, int)
        assert REFRESH_TOKEN_EXPIRY_DAYS > 0
        assert REFRESH_TOKEN_EXPIRY_DAYS == 30

    def test_refresh_token_expiry_seconds_correct(self):
        """Test that refresh token expiry seconds matches days."""
        expected_seconds = REFRESH_TOKEN_EXPIRY_DAYS * 86400  # days to seconds
        assert REFRESH_TOKEN_EXPIRY_SECONDS == expected_seconds
        # Should be 30 days (2592000 seconds)
        assert REFRESH_TOKEN_EXPIRY_SECONDS == 2592000

    def test_token_refresh_buffer_positive(self):
        """Test that token refresh buffer is positive."""
        assert isinstance(TOKEN_REFRESH_BUFFER_SECONDS, int)
        assert TOKEN_REFRESH_BUFFER_SECONDS > 0
        # Should be 5 minutes (300 seconds)
        assert TOKEN_REFRESH_BUFFER_SECONDS == 300

    def test_refresh_token_longer_than_access_token(self):
        """Test that refresh token lives longer than access token."""
        assert REFRESH_TOKEN_EXPIRY_SECONDS > DEFAULT_TOKEN_EXPIRY_SECONDS

    def test_refresh_buffer_less_than_token_expiry(self):
        """Test that refresh buffer is less than token expiry."""
        assert TOKEN_REFRESH_BUFFER_SECONDS < DEFAULT_TOKEN_EXPIRY_SECONDS

    def test_token_expiry_reasonable(self):
        """Test that token expiry times are reasonable."""
        # Access token should be at least 5 minutes
        assert DEFAULT_TOKEN_EXPIRY_SECONDS >= 300
        # Access token shouldn't exceed 24 hours
        assert DEFAULT_TOKEN_EXPIRY_SECONDS <= 86400
        # Refresh token should be at least 1 day
        assert REFRESH_TOKEN_EXPIRY_DAYS >= 1
        # Refresh token shouldn't exceed 90 days (common security practice)
        assert REFRESH_TOKEN_EXPIRY_DAYS <= 90


class TestOAuthState:
    """Test OAuth state configuration constants."""

    def test_oauth_state_ttl_positive(self):
        """Test that OAuth state TTL is positive."""
        assert isinstance(OAUTH_STATE_TTL_SECONDS, int)
        assert OAUTH_STATE_TTL_SECONDS > 0
        # Should be 10 minutes (600 seconds)
        assert OAUTH_STATE_TTL_SECONDS == 600

    def test_max_pending_states_positive(self):
        """Test that max pending states is positive."""
        assert isinstance(MAX_PENDING_STATES, int)
        assert MAX_PENDING_STATES > 0
        assert MAX_PENDING_STATES == 100

    def test_state_cleanup_interval_positive(self):
        """Test that state cleanup interval is positive."""
        assert isinstance(STATE_CLEANUP_INTERVAL, int)
        assert STATE_CLEANUP_INTERVAL > 0
        # Should be 60 seconds
        assert STATE_CLEANUP_INTERVAL == 60

    def test_state_ttl_reasonable(self):
        """Test that state TTL is reasonable for OAuth flow."""
        # Should be at least 1 minute (user needs time to authorize)
        assert OAUTH_STATE_TTL_SECONDS >= 60
        # Shouldn't exceed 30 minutes (security best practice)
        assert OAUTH_STATE_TTL_SECONDS <= 1800

    def test_cleanup_interval_less_than_ttl(self):
        """Test that cleanup runs multiple times before state expires."""
        # Cleanup should run at least a few times during TTL
        assert STATE_CLEANUP_INTERVAL < OAUTH_STATE_TTL_SECONDS
        # Should run at least 2-3 times before expiry
        assert OAUTH_STATE_TTL_SECONDS / STATE_CLEANUP_INTERVAL >= 2


class TestConstantsIntegration:
    """Test relationships between different constant categories."""

    def test_session_and_token_alignment(self):
        """Test that session timeouts align with token expiry."""
        # Session inactivity should be at least as long as token expiry
        # (user shouldn't get logged out before token expires)
        assert DEFAULT_SESSION_INACTIVITY_TIMEOUT >= DEFAULT_TOKEN_EXPIRY_SECONDS

    def test_cleanup_intervals_consistent(self):
        """Test that cleanup intervals are consistent across modules."""
        # State cleanup should be more frequent than session cleanup
        # (states are shorter-lived)
        assert STATE_CLEANUP_INTERVAL <= SESSION_CLEANUP_INTERVAL

    def test_security_timeouts_progressive(self):
        """Test that security timeouts follow a progressive pattern."""
        # OAuth state (short-lived) < Token (medium) <= Session (long)
        assert OAUTH_STATE_TTL_SECONDS < DEFAULT_TOKEN_EXPIRY_SECONDS
        assert DEFAULT_TOKEN_EXPIRY_SECONDS <= DEFAULT_SESSION_INACTIVITY_TIMEOUT
        assert DEFAULT_SESSION_INACTIVITY_TIMEOUT < DEFAULT_SESSION_ABSOLUTE_TIMEOUT

    def test_rate_limits_prevent_abuse(self):
        """Test that rate limits are configured to prevent abuse."""
        # Login attempts should be strictly limited
        assert LOGIN_RATE_LIMIT_MAX_ATTEMPTS <= 10
        # Callback rate limit should prevent rapid-fire attacks
        assert CALLBACK_RATE_LIMIT_MAX <= 20
        # Default rate limits should be generous but bounded
        assert DEFAULT_RATE_LIMIT_MAX_REQUESTS >= 10
        assert DEFAULT_RATE_LIMIT_MAX_REQUESTS <= 1000


class TestConstantTypes:
    """Test that all constants are of correct types."""

    def test_all_session_constants_are_integers(self):
        """Test that session constants are integers."""
        assert isinstance(DEFAULT_MAX_SESSIONS_PER_USER, int)
        assert isinstance(DEFAULT_SESSION_INACTIVITY_TIMEOUT, int)
        assert isinstance(DEFAULT_SESSION_ABSOLUTE_TIMEOUT, int)
        assert isinstance(SESSION_CLEANUP_INTERVAL, int)

    def test_all_rate_limit_constants_are_integers(self):
        """Test that rate limit constants are integers."""
        assert isinstance(DEFAULT_RATE_LIMIT_WINDOW, int)
        assert isinstance(DEFAULT_RATE_LIMIT_MAX_REQUESTS, int)
        assert isinstance(LOGIN_RATE_LIMIT_WINDOW, int)
        assert isinstance(LOGIN_RATE_LIMIT_MAX_ATTEMPTS, int)
        assert isinstance(CALLBACK_RATE_LIMIT_MAX, int)

    def test_all_token_constants_are_integers(self):
        """Test that token constants are integers."""
        assert isinstance(DEFAULT_TOKEN_EXPIRY_SECONDS, int)
        assert isinstance(REFRESH_TOKEN_EXPIRY_DAYS, int)
        assert isinstance(REFRESH_TOKEN_EXPIRY_SECONDS, int)
        assert isinstance(TOKEN_REFRESH_BUFFER_SECONDS, int)

    def test_all_oauth_state_constants_are_integers(self):
        """Test that OAuth state constants are integers."""
        assert isinstance(OAUTH_STATE_TTL_SECONDS, int)
        assert isinstance(MAX_PENDING_STATES, int)
        assert isinstance(STATE_CLEANUP_INTERVAL, int)
