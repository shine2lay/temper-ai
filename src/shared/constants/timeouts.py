"""Common timeout and time-related constants.

These constants provide semantic meaning to time conversions and default timeouts,
improving code readability and reducing magic numbers.
"""

# Time conversion constants
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# Default timeout values
DEFAULT_CACHE_TTL_SECONDS = 3600  # 1 hour default cache TTL
DEFAULT_SESSION_TTL_SECONDS = 3600  # 1 hour default session TTL
