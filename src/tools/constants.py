"""Constants for the tools module.

Centralized constants for tool execution limits, DNS configuration,
web scraping, bash execution, and file operations.
"""

# ============================================================================
# Bash Tool
# ============================================================================

DEFAULT_BASH_TIMEOUT = 120  # 2 minutes
MAX_BASH_TIMEOUT = 600  # 10 minutes
MAX_BASH_OUTPUT_LENGTH = 50000

# ============================================================================
# Web Scraper
# ============================================================================

DEFAULT_WEB_TIMEOUT = 30  # seconds
MAX_WEB_TIMEOUT = 300  # 5 minutes
MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5MB
DEFAULT_RATE_LIMIT = 10  # requests per minute
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_REDIRECTS = 5
URL_MIN_LENGTH = 10
URL_MAX_LENGTH = 2000
USER_AGENT_MAX_LENGTH = 500

# ============================================================================
# DNS Configuration
# ============================================================================

DNS_RESOLUTION_TIMEOUT_SECONDS = 2.0
DNS_CACHE_TTL_SECONDS = 300  # 5 minutes
DNS_CACHE_MAX_SIZE = 1000

# ============================================================================
# Calculator Tool
# ============================================================================

MAX_NESTING_DEPTH = 10
MAX_EXPONENT = 1000
MAX_COLLECTION_SIZE = 1000

# ============================================================================
# File Writer Tool
# ============================================================================

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
