"""
WebScraper tool for fetching and extracting text from web pages.

Uses httpx for HTTP requests and BeautifulSoup for HTML parsing.
"""
import time
import httpx
import ipaddress
import socket
import urllib.parse
from typing import Dict, Any, Optional, Tuple, Type, Union, List
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator, HttpUrl
from src.tools.base import BaseTool, ToolMetadata, ToolResult


# SSRF Protection: Blocked hosts and networks
BLOCKED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS/Azure metadata
    "metadata.google.internal",  # GCP metadata
    "::1",
    "::ffff:127.0.0.1",  # IPv6 localhost
]

BLOCKED_NETWORKS: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = [
    ipaddress.IPv4Network("10.0.0.0/8"),      # RFC 1918: Private network
    ipaddress.IPv4Network("172.16.0.0/12"),   # RFC 1918: Private network
    ipaddress.IPv4Network("192.168.0.0/16"),  # RFC 1918: Private network
    ipaddress.IPv4Network("127.0.0.0/8"),     # RFC 1122: Loopback (entire range)
    ipaddress.IPv4Network("169.254.0.0/16"),  # RFC 3927: Link-local (includes AWS/Azure metadata)
    ipaddress.IPv6Network("::1/128"),         # RFC 4291: IPv6 loopback
    ipaddress.IPv6Network("fe80::/10"),       # RFC 4291: IPv6 link-local
    ipaddress.IPv6Network("::ffff:0:0/96"),   # RFC 4291: IPv4-mapped IPv6
]


def validate_url_safety(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate URL doesn't target internal resources (SSRF protection).

    NOTE: This function performs DNS resolution to check resolved IPs,
    which may trigger network calls and be subject to DNS timing.

    Args:
        url: URL to validate

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if URL is safe
        - (False, error_message) if URL is dangerous
    """
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            return False, "Invalid URL: missing hostname"

        # Block known dangerous hostnames (defense-in-depth: catch before DNS)
        if hostname.lower() in [h.lower() for h in BLOCKED_HOSTS]:
            return False, f"Access to {hostname} is forbidden (SSRF protection)"

        # Check if hostname is already an IP address
        try:
            ip = ipaddress.ip_address(hostname)

            # Check against blocked networks
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    return False, f"Access to private network {network} is forbidden (SSRF protection)"

            return True, None

        except ValueError:
            # Not an IP address, continue with DNS resolution
            pass

        # Resolve hostname and check all resolved IPs (supports both IPv4 and IPv6)
        try:
            addr_info = socket.getaddrinfo(hostname, None)

            # Check all resolved IPs (a hostname can have multiple A/AAAA records)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip = ipaddress.ip_address(ip_str)

                # Check against blocked networks
                for network in BLOCKED_NETWORKS:
                    if ip in network:
                        return False, f"Access to private network {network} is forbidden (SSRF protection)"

            return True, None

        except socket.gaierror as e:
            return False, f"Cannot resolve hostname: {e}"
        except ValueError as e:
            return False, f"Invalid IP address: {e}"

    except Exception as e:
        # Log unexpected errors for debugging (don't expose to user)
        return False, f"URL validation failed"


class RateLimiter:
    """Simple rate limiter for web requests."""

    def __init__(self, max_requests: int, time_window: int):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: list[float] = []

    def can_proceed(self) -> bool:
        """Check if request can proceed without exceeding rate limit."""
        now = time.time()

        # Remove requests outside time window
        self.requests = [req_time for req_time in self.requests
                        if now - req_time < self.time_window]

        return len(self.requests) < self.max_requests

    def record_request(self) -> None:
        """Record a new request."""
        self.requests.append(time.time())

    def wait_time(self) -> float:
        """Get seconds to wait before next request is allowed."""
        if self.can_proceed():
            return 0.0

        # Find oldest request
        if not self.requests:
            return 0.0

        oldest = min(self.requests)
        time_since_oldest = time.time() - oldest

        return max(0.0, self.time_window - time_since_oldest)


# Validation constants for web scraper parameters
# Rationale for URL length limits:
# - Min 10 chars ensures valid URL (e.g., "http://a.b")
# - Max 2000 chars prevents DoS while supporting long query strings
URL_MIN_LENGTH = 10
URL_MAX_LENGTH = 2000

# Max timeout: 5 minutes prevents indefinite hangs while allowing slow endpoints
# Typical use: Large files, slow APIs, or high-latency connections
MAX_TIMEOUT_SECONDS = 300

# User-Agent max length: 500 chars is reasonable for custom UA strings
# Prevents header injection attacks and excessive memory usage
USER_AGENT_MAX_LENGTH = 500

# Rate limit time window: 60 seconds (1 minute) for request counting
# Matches DEFAULT_RATE_LIMIT of 10 requests per minute
RATE_LIMIT_WINDOW_SECONDS = 60


class WebScraperParams(BaseModel):
    """Pydantic model for WebScraper parameters with comprehensive validation."""

    url: str = Field(
        ...,
        description="URL to fetch (must start with http:// or https://)",
        min_length=URL_MIN_LENGTH,
        max_length=URL_MAX_LENGTH
    )
    extract_text: bool = Field(
        default=True,
        description="Whether to extract text from HTML"
    )
    timeout: int = Field(
        default=30,
        description="Request timeout in seconds",
        gt=0,
        le=MAX_TIMEOUT_SECONDS
    )
    user_agent: Optional[str] = Field(
        default=None,
        description="Custom User-Agent header",
        max_length=USER_AGENT_MAX_LENGTH
    )

    @field_validator('url')
    @classmethod
    def validate_url_protocol(cls, v: str) -> str:
        """Validate URL starts with http:// or https://."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError("URL must start with http:// or https://")
        return v


class WebScraper(BaseTool):
    """
    Web scraper tool for fetching and extracting content from URLs.

    Features:
    - Fetch URL content with httpx
    - Extract text from HTML using BeautifulSoup
    - Rate limiting (max 10 requests per minute by default)
    - Timeout handling
    - Custom User-Agent header
    - Follow redirects

    Safety:
    - Rate limiting to prevent abuse
    - Timeout to prevent hanging
    - Maximum content size limit
    """

    MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5MB limit
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_RATE_LIMIT = 10  # requests per minute

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize web scraper with rate limiter.

        Args:
            config: Optional configuration dict (currently unused)
        """
        super().__init__(config)
        self.rate_limiter = RateLimiter(
            max_requests=self.DEFAULT_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS
        )

    def get_metadata(self) -> ToolMetadata:
        """Return web scraper tool metadata."""
        return ToolMetadata(
            name="WebScraper",
            description="Fetches content from a URL and extracts text from HTML. Includes rate limiting (10 requests/minute) and timeout protection.",
            version="1.0",
            category="web",
            requires_network=True,
            requires_credentials=False,
        )

    def get_parameters_model(self) -> Type[BaseModel]:
        """Return Pydantic model for comprehensive parameter validation."""
        return WebScraperParams

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for web scraper parameters."""
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch (must start with http:// or https://)"
                },
                "extract_text": {
                    "type": "boolean",
                    "description": "Whether to extract text from HTML (default: true)",
                    "default": True
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Request timeout in seconds (default: {self.DEFAULT_TIMEOUT})",
                    "default": self.DEFAULT_TIMEOUT
                },
                "user_agent": {
                    "type": "string",
                    "description": "Custom User-Agent header (optional)"
                }
            },
            "required": ["url"]
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Execute web scraper with given parameters.

        Args:
            url: URL to fetch
            extract_text: Whether to extract text from HTML (default: True)
            timeout: Request timeout in seconds
            user_agent: Custom User-Agent header (optional)

        Returns:
            ToolResult with fetched content or error
        """
        url = kwargs.get("url")
        extract_text = kwargs.get("extract_text", True)
        timeout = kwargs.get("timeout", self.DEFAULT_TIMEOUT)
        user_agent = kwargs.get("user_agent")

        # Validate URL
        if not url or not isinstance(url, str):
            return ToolResult(
                success=False,
                error="url must be a non-empty string"
            )

        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False,
                error="URL must start with http:// or https://"
            )

        # SSRF protection: Validate URL doesn't target internal resources
        is_safe, safety_error = validate_url_safety(url)
        if not is_safe:
            return ToolResult(
                success=False,
                error=safety_error
            )

        # Check rate limit
        if not self.rate_limiter.can_proceed():
            wait_time = self.rate_limiter.wait_time()
            return ToolResult(
                success=False,
                error=f"Rate limit exceeded. Please wait {wait_time:.1f} seconds."
            )

        try:
            # Prepare headers
            headers = {
                "User-Agent": user_agent or "Mozilla/5.0 (compatible; MetaAutonomousBot/1.0)"
            }

            # Record request for rate limiting
            self.rate_limiter.record_request()

            # Fetch URL
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, headers=headers)

                # Check status code
                response.raise_for_status()

                # Validate Content-Type (prevent crashes on binary files)
                content_type = response.headers.get("content-type", "").lower()
                acceptable_types = [
                    "text/html",
                    "text/plain",
                    "text/xml",
                    "application/xhtml+xml",
                    "application/xml",
                ]

                # Check if content type is acceptable (may have charset, e.g., "text/html; charset=utf-8")
                is_acceptable = any(
                    acceptable_type in content_type
                    for acceptable_type in acceptable_types
                )

                if not is_acceptable and content_type:
                    return ToolResult(
                        success=False,
                        error=f"Unsupported content type: {content_type.split(';')[0]}. Only text-based content is supported."
                    )

                # Check content size
                content_length = len(response.content)
                if content_length > self.MAX_CONTENT_SIZE:
                    return ToolResult(
                        success=False,
                        error=f"Content size ({content_length} bytes) exceeds maximum ({self.MAX_CONTENT_SIZE} bytes)"
                    )

                # Get content
                content = response.text

                # Extract text if requested
                if extract_text:
                    extracted_text = self._extract_text(content)
                    result = extracted_text
                else:
                    result = content

                return ToolResult(
                    success=True,
                    result=result,
                    metadata={
                        "url": url,
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type", ""),
                        "size_bytes": content_length,
                        "text_extracted": extract_text
                    }
                )

        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                error=f"Request timed out after {timeout} seconds"
            )

        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}"
            )

        except httpx.RequestError as e:
            return ToolResult(
                success=False,
                error=f"Request error: {str(e)}"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Unexpected error: {str(e)}"
            )

    def _extract_text(self, html: str) -> str:
        """
        Extract readable text from HTML.

        Args:
            html: HTML content

        Returns:
            Extracted text
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style", "head", "meta", "link"]):
                script.decompose()

            # Get text
            text = soup.get_text(separator='\n', strip=True)

            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            text = '\n'.join(lines)

            return text

        except Exception as e:
            # If extraction fails, return error message
            return f"[Error extracting text: {str(e)}]"
