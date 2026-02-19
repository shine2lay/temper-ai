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
MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5MB  # noqa: Multiplier in expression
DEFAULT_RATE_LIMIT = 10  # requests per minute
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_REDIRECTS = 5  # Maximum number of HTTP redirects to follow
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

# ============================================================================
# Web Search (Tavily, SearXNG)
# ============================================================================

DEFAULT_SEARCH_TIMEOUT = 30  # seconds
MAX_SEARCH_RESULTS = 20
DEFAULT_SEARCH_MAX_RESULTS = 5  # Default results returned
MAX_SEARCH_QUERY_LENGTH = 2000  # SearXNG max query length
TAVILY_MAX_QUERY_LENGTH = 400  # Tavily API max query length
TAVILY_RATE_LIMIT = 5  # requests per minute
SEARXNG_RATE_LIMIT = 10  # requests per minute
TAVILY_DEFAULT_BASE_URL = "https://api.tavily.com"
SEARXNG_DEFAULT_BASE_URL = "http://localhost:8888"

# ============================================================================
# HTTP Status Codes (for API client error handling)
# ============================================================================

HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_TOO_MANY_REQUESTS = 429

# ============================================================================
# Error Formatting
# ============================================================================

ERROR_RESPONSE_TEXT_MAX_LENGTH = 200  # Max chars of error response text to include

# ============================================================================
# Tool Execution & Rollback
# ============================================================================

ROLLBACK_TRIGGER_AUTO = "auto"
CONTEXT_KEY_AGENT_ID = "agent_id"

# ============================================================================
# Tool Registry
# ============================================================================

TOOL_ERROR_PREFIX = "Tool '"

# ============================================================================
# JSON Schema Field Names (for tool parameter definitions)
# ============================================================================

SCHEMA_FIELD_TYPE = "type"
SCHEMA_FIELD_DESCRIPTION = "description"
SCHEMA_FIELD_DEFAULT = "default"
SCHEMA_TYPE_STRING = "string"

# ============================================================================
# File Operations
# ============================================================================

FILE_ENCODING_UTF8 = "utf-8"

# ============================================================================
# SSRF Protection
# ============================================================================

SSRF_ERROR_SUFFIX = " is forbidden (SSRF protection)"
