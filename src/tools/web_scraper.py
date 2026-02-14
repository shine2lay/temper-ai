"""
WebScraper tool for fetching and extracting text from web pages.

Uses httpx for HTTP requests and BeautifulSoup for HTML parsing.
"""
import ipaddress
import logging
import socket
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple, Type, Union

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator

from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.constants import (
    DEFAULT_RATE_LIMIT as _DEFAULT_RATE_LIMIT,
)
from src.tools.constants import (
    DEFAULT_WEB_TIMEOUT,
    MAX_WEB_TIMEOUT,
)
from src.tools.constants import (
    DNS_CACHE_MAX_SIZE as _DNS_CACHE_MAX_SIZE,
)
from src.tools.constants import (
    DNS_CACHE_TTL_SECONDS as _DNS_CACHE_TTL_SECONDS,
)
from src.tools.constants import (
    DNS_RESOLUTION_TIMEOUT_SECONDS as _DNS_RESOLUTION_TIMEOUT_SECONDS,
)
from src.tools.constants import (
    MAX_CONTENT_SIZE as _MAX_CONTENT_SIZE,
)
from src.tools.constants import (
    MAX_REDIRECTS as _MAX_REDIRECTS,
)
from src.tools.constants import (
    RATE_LIMIT_WINDOW_SECONDS as _RATE_LIMIT_WINDOW_SECONDS,
)
from src.tools.constants import (
    URL_MAX_LENGTH as _URL_MAX_LENGTH,
)
from src.tools.constants import (
    URL_MIN_LENGTH as _URL_MIN_LENGTH,
)
from src.tools.constants import (
    USER_AGENT_MAX_LENGTH as _USER_AGENT_MAX_LENGTH,
)
from src.tools.constants import SSRF_ERROR_SUFFIX

logger = logging.getLogger(__name__)

# SSRF Protection: Blocked hosts and networks
BLOCKED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104  # nosec B104 — in BLOCKED_HOSTS list (SSRF protection)
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

# DNS Security Configuration
DNS_RESOLUTION_TIMEOUT_SECONDS = _DNS_RESOLUTION_TIMEOUT_SECONDS
DNS_CACHE_TTL_SECONDS = _DNS_CACHE_TTL_SECONDS
DNS_CACHE_MAX_SIZE = _DNS_CACHE_MAX_SIZE

# SSRF Redirect Protection
MAX_REDIRECTS = _MAX_REDIRECTS


class DNSCache:
    """
    Thread-safe DNS cache to prevent DNS rebinding attacks.

    Caches validated DNS resolutions with TTL to prevent attackers from
    changing DNS responses between validation and actual HTTP request.

    Security Features:
    - TTL expiration prevents stale entries
    - Size limit prevents memory exhaustion
    - Thread-safe for concurrent access
    - Only caches validated (safe) resolutions
    """

    def __init__(self, ttl: int = DNS_CACHE_TTL_SECONDS, max_size: int = DNS_CACHE_MAX_SIZE):
        """Initialize DNS cache with TTL and size limit."""
        self._cache: Dict[str, Tuple[List[Tuple], float]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._max_size = max_size

    def get(self, hostname: str) -> Optional[List[Tuple]]:
        """
        Get cached DNS resolution if not expired.

        Args:
            hostname: Hostname to look up

        Returns:
            List of address info tuples if cached and valid, None otherwise
        """
        with self._lock:
            if hostname not in self._cache:
                return None

            addr_info, timestamp = self._cache[hostname]

            # Check if entry has expired
            if time.time() - timestamp > self._ttl:
                del self._cache[hostname]
                return None

            return addr_info

    def set(self, hostname: str, addr_info: List[Tuple]) -> None:
        """
        Cache DNS resolution result.

        Args:
            hostname: Hostname to cache
            addr_info: Address info tuples from getaddrinfo
        """
        with self._lock:
            # Enforce max cache size (simple LRU - remove oldest)
            if len(self._cache) >= self._max_size and hostname not in self._cache:
                # Remove oldest entry (first key)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[hostname] = (addr_info, time.time())

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()


# Global DNS cache instance
_dns_cache = DNSCache()


def resolve_hostname_with_timeout(hostname: str, timeout: float = DNS_RESOLUTION_TIMEOUT_SECONDS) -> List[Tuple]:
    """
    Resolve hostname with timeout to prevent DNS timing attacks.

    Uses threading to implement timeout since socket.getaddrinfo doesn't
    support timeout parameter directly.

    Args:
        hostname: Hostname to resolve
        timeout: DNS resolution timeout in seconds

    Returns:
        List of address info tuples from socket.getaddrinfo

    Raises:
        socket.gaierror: DNS resolution failed
        TimeoutError: DNS resolution timed out
    """
    result: list[Any] = []
    exception: Optional[Exception] = None

    def resolve() -> None:
        """Thread target for DNS resolution."""
        nonlocal result, exception
        try:
            result[:] = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, OSError, ValueError) as e:
            exception = e

    # Start resolution thread
    thread = threading.Thread(target=resolve, daemon=True)
    thread.start()

    # Wait for thread with timeout
    thread.join(timeout=timeout)

    # Check if thread is still alive (timeout occurred)
    if thread.is_alive():
        raise TimeoutError(f"DNS resolution for {hostname} timed out after {timeout}s (possible timing attack)")

    # Check if exception occurred during resolution
    if exception is not None:
        raise exception

    return result


def validate_url_safety(url: str, use_cache: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Validate URL doesn't target internal resources (SSRF protection).

    Security Features:
    - DNS resolution with timeout (prevents timing attacks and DoS)
    - DNS caching with TTL (prevents DNS rebinding attacks)
    - Validates all resolved IPs (handles round-robin DNS)
    - Blocks private networks, localhost, cloud metadata endpoints

    Args:
        url: URL to validate
        use_cache: Whether to use DNS cache (default: True)

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if URL is safe
        - (False, error_message) if URL is dangerous
    """
    # Parse URL and extract hostname
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
    except (TypeError, ValueError) as e:
        logger.debug(f"URL parsing failed: {e}")
        return False, "Invalid URL format"

    if not hostname:
        return False, "Invalid URL: missing hostname"

    # Block known dangerous hostnames (defense-in-depth: catch before DNS)
    if hostname.lower() in [h.lower() for h in BLOCKED_HOSTS]:
        return False, f"Access to {hostname}{SSRF_ERROR_SUFFIX}"

    # Check if hostname is already an IP address
    try:
        ip = ipaddress.ip_address(hostname)

        # Check against blocked networks
        for network in BLOCKED_NETWORKS:
            if ip in network:
                return False, f"Access to private network {network}{SSRF_ERROR_SUFFIX}"

        return True, None

    except ValueError:
        # Not an IP address, continue with DNS resolution
        pass

    # Check DNS cache first (prevents DNS rebinding attacks)
    addr_info = None
    if use_cache:
        addr_info = _dns_cache.get(hostname)

    # If not cached, perform DNS resolution with timeout
    if addr_info is None:
        try:
            addr_info = resolve_hostname_with_timeout(
                hostname,
                timeout=DNS_RESOLUTION_TIMEOUT_SECONDS
            )
        except TimeoutError as e:
            # DNS timeout likely indicates timing attack or slow DNS
            return False, f"DNS resolution timeout (possible attack): {str(e)}"
        except socket.gaierror as e:
            return False, f"Cannot resolve hostname: {e}"
        except (OSError, ValueError) as e:
            return False, f"DNS resolution error: {str(e)}"

        # Validate all resolved IPs before caching
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)

                # Check against blocked networks
                for network in BLOCKED_NETWORKS:
                    if ip in network:
                        # Don't cache invalid resolutions
                        return False, f"Access to private network {network}{SSRF_ERROR_SUFFIX}"

            except ValueError as e:
                return False, f"Invalid IP address: {e}"

        # Cache validated resolution (only safe resolutions are cached)
        if use_cache:
            _dns_cache.set(hostname, addr_info)

        return True, None

    else:
        # Using cached resolution - already validated as safe
        return True, None


class ScraperRateLimiter:
    """Rate limiter for web requests backed by :class:`~src.safety.token_bucket.TokenBucket`.

    Wraps the canonical TokenBucket implementation with a simpler API
    suited for per-domain web request rate limiting.

    TO-05: Thread-safe via TokenBucket's internal lock.
    """

    def __init__(self, max_requests: int, time_window: int):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        from src.safety.token_bucket import RateLimit, TokenBucket

        self.max_requests = max_requests
        self.time_window = time_window
        # Configure token bucket: refill all tokens over the time window
        self._bucket = TokenBucket(RateLimit(
            max_tokens=max_requests,
            refill_rate=max_requests / time_window if time_window > 0 else max_requests,
            refill_period=1.0,
        ))

    def can_proceed(self) -> bool:
        """Check if request can proceed without exceeding rate limit."""
        return self._bucket.peek(1)

    def record_request(self) -> None:
        """Record a new request (consume one token)."""
        self._bucket.consume(1)

    def wait_time(self) -> float:
        """Get seconds to wait before next request is allowed."""
        return self._bucket.get_wait_time(1)


# Validation constants for web scraper parameters
URL_MIN_LENGTH = _URL_MIN_LENGTH
URL_MAX_LENGTH = _URL_MAX_LENGTH
MAX_TIMEOUT_SECONDS = MAX_WEB_TIMEOUT
USER_AGENT_MAX_LENGTH = _USER_AGENT_MAX_LENGTH
RATE_LIMIT_WINDOW_SECONDS = _RATE_LIMIT_WINDOW_SECONDS


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
        default=DEFAULT_WEB_TIMEOUT,
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

    MAX_CONTENT_SIZE = _MAX_CONTENT_SIZE
    DEFAULT_TIMEOUT = DEFAULT_WEB_TIMEOUT
    DEFAULT_RATE_LIMIT = _DEFAULT_RATE_LIMIT

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize web scraper with rate limiter.

        Args:
            config: Optional configuration dict (currently unused)
        """
        super().__init__(config)
        self.rate_limiter = ScraperRateLimiter(
            max_requests=self.DEFAULT_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS
        )
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Return shared httpx.Client, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.DEFAULT_TIMEOUT,
                follow_redirects=False,
            )
        return self._client

    def close(self) -> None:
        """Close the shared httpx client and release resources."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __del__(self) -> None:
        """Clean up httpx client on garbage collection."""
        try:
            self.close()
        except (OSError, RuntimeError):
            pass

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

        # Prepare headers
        headers = {
            "User-Agent": user_agent or "Mozilla/5.0 (compatible; MetaAutonomousBot/1.0)"
        }

        # Record request for rate limiting
        self.rate_limiter.record_request()

        # Fetch URL with SSRF-safe redirect handling
        try:
            # SECURITY: follow_redirects=False so we can validate each redirect
            # target against SSRF checks before following it
            client = self._get_client()
            current_url = url
            for _redirect_hop in range(MAX_REDIRECTS + 1):
                response = client.get(current_url, headers=headers, timeout=timeout)

                if response.is_redirect:
                    redirect_url = str(response.next_request.url) if response.next_request else None
                    if redirect_url is None:
                        break
                    # Validate redirect target against SSRF checks
                    is_safe, safety_error = validate_url_safety(redirect_url)
                    if not is_safe:
                        return ToolResult(
                            success=False,
                            error=f"Redirect to unsafe URL blocked (SSRF protection): {safety_error}"
                        )
                    current_url = redirect_url
                    continue
                break
            else:
                return ToolResult(
                    success=False,
                    error=f"Too many redirects (max {MAX_REDIRECTS})"
                )

            # Check status code
            response.raise_for_status()

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

        # Get content and extract text if requested
        try:
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

        except (ValueError, UnicodeDecodeError) as e:
            return ToolResult(
                success=False,
                error=f"Content processing error: {str(e)}"
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

        except (ValueError, TypeError, AttributeError) as e:
            # If extraction fails, return error message
            return f"[Error extracting text: {str(e)}]"
