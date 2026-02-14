"""SearXNG web search tool.

Queries a self-hosted SearXNG instance via its JSON API and returns
structured search results using the shared SearchResponse model.
"""
import ipaddress
import logging
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Type

import httpx
from pydantic import BaseModel, Field, field_validator

from src.tools._search_helpers import SearchResponse, SearchResultItem
from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.constants import (
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    MAX_SEARCH_QUERY_LENGTH,
    MAX_SEARCH_RESULTS,
    RATE_LIMIT_WINDOW_SECONDS,
    SEARXNG_DEFAULT_BASE_URL,
    SEARXNG_RATE_LIMIT,
)
from src.tools.web_scraper import ScraperRateLimiter

logger = logging.getLogger(__name__)


class SearXNGSearchParams(BaseModel):
    """Pydantic model for SearXNGSearch parameters."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=MAX_SEARCH_QUERY_LENGTH,
        description="Search query string",
    )
    max_results: int = Field(
        default=DEFAULT_SEARCH_MAX_RESULTS,
        ge=1,
        le=MAX_SEARCH_RESULTS,
        description="Maximum number of results to return",
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description='SearXNG categories to search (e.g. ["general", "news"])',
    )
    language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="Search language code",
    )

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate that categories list is not empty if provided."""
        if v is not None and len(v) == 0:
            raise ValueError("categories must not be an empty list")
        return v


class SearXNGSearch(BaseTool):
    """Search tool that queries a self-hosted SearXNG instance.

    Features:
    - Queries SearXNG JSON API (no API key required)
    - Returns structured SearchResponse results
    - Rate limiting (10 requests per minute by default)
    - Configurable base URL, categories, and language
    - Timeout protection

    Security: base_url is restricted to loopback addresses (localhost,
    127.0.0.0/8, ::1) to prevent SSRF via config injection.
    """

    # Allowed loopback hostnames for SSRF protection
    _ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

    def __init__(
        self,
        base_url: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize SearXNG search tool.

        Args:
            base_url: SearXNG instance URL. Must be a loopback address
                (localhost, 127.x.x.x, ::1) for SSRF protection.
            config: Optional configuration dict.

        Raises:
            ValueError: If base_url points to a non-loopback address.
        """
        super().__init__(config)
        raw_url = base_url or SEARXNG_DEFAULT_BASE_URL
        self._validate_base_url(raw_url)
        self.base_url = raw_url.rstrip("/")
        self.rate_limiter = ScraperRateLimiter(
            max_requests=SEARXNG_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS,
        )
        self._client: Optional[httpx.Client] = None

    @classmethod
    def _validate_base_url(cls, url: str) -> None:
        """Validate that base_url is a loopback address (SSRF protection).

        Args:
            url: The URL to validate.

        Raises:
            ValueError: If the hostname is not a loopback address.
        """
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()

        # Allow known loopback hostnames
        if hostname in cls._ALLOWED_HOSTS:
            return

        # Allow 127.0.0.0/8 range
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_loopback:
                return
        except ValueError:
            pass

        raise ValueError(
            f"SearXNG base_url must use a loopback address "
            f"(localhost, 127.x.x.x, ::1) for SSRF protection, "
            f"got: {hostname}"
        )

    def _get_client(self) -> httpx.Client:
        """Return shared httpx.Client, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=DEFAULT_SEARCH_TIMEOUT,
                follow_redirects=False,
            )
        return self._client

    def close(self) -> None:
        """Close the shared httpx client and release resources."""
        client = getattr(self, "_client", None)
        if client is not None and not client.is_closed:
            client.close()
            self._client = None

    def __del__(self) -> None:
        """Clean up httpx client on garbage collection."""
        try:
            self.close()
        except (OSError, RuntimeError, AttributeError):
            pass

    def get_metadata(self) -> ToolMetadata:
        """Return SearXNG search tool metadata."""
        return ToolMetadata(
            name="SearXNGSearch",
            description=(
                "Searches the web using a self-hosted SearXNG instance. "
                "Returns structured results with title, URL, and snippet. "
                "Rate limited to 10 requests per minute."
            ),
            version="1.0",
            category="web",
            requires_network=True,
            requires_credentials=False,
            modifies_state=False,
        )

    def get_parameters_model(self) -> Type[BaseModel]:
        """Return Pydantic model for parameter validation."""
        return SearXNGSearchParams

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for SearXNG search parameters."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5)",
                    "default": DEFAULT_SEARCH_MAX_RESULTS,
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'SearXNG categories (e.g. ["general", "news"])',
                },
                "language": {
                    "type": "string",
                    "description": "Search language code (default: en)",
                    "default": "en",
                },
            },
            "required": ["query"],
        }

    def _validate_query(self, query: Any) -> Optional[ToolResult]:
        """Validate query input. Returns error or None."""
        if not query or not isinstance(query, str):
            return ToolResult(
                success=False,
                error="query must be a non-empty string",
            )
        return None

    def _check_rate_limit(self) -> Optional[ToolResult]:
        """Check rate limit. Returns error or None."""
        if not self.rate_limiter.can_proceed():
            wait_time = self.rate_limiter.wait_time()
            return ToolResult(
                success=False,
                error=f"Rate limit exceeded. Please wait {wait_time:.1f} seconds.",
            )
        return None

    def _build_search_params(self, query: str, language: str, categories: Optional[List[str]]) -> Dict[str, str]:
        """Build query parameters for SearXNG API."""
        params: Dict[str, str] = {
            "q": query,
            "format": "json",
            "language": language,
        }
        if categories:
            params["categories"] = ",".join(categories)
        return params

    def _execute_search_request(self, params: Dict[str, str]) -> tuple[Optional[Any], Optional[ToolResult], float]:
        """Execute search request. Returns (response, error, elapsed_ms)."""
        start_time = time.monotonic()
        try:
            client = self._get_client()
            response = client.get(
                f"{self.base_url}/search",
                params=params,
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return response, None, elapsed_ms
        except httpx.TimeoutException:
            return None, ToolResult(
                success=False,
                error=f"Search request timed out after {DEFAULT_SEARCH_TIMEOUT} seconds",
            ), 0
        except httpx.HTTPStatusError as e:
            return None, ToolResult(
                success=False,
                error=f"SearXNG API error {e.response.status_code}: {e.response.reason_phrase}",
            ), 0
        except httpx.RequestError as e:
            return None, ToolResult(
                success=False,
                error=f"Request error: {str(e)}",
            ), 0

    def _parse_results(self, response: Any, query: str, max_results: int, elapsed_ms: float) -> tuple[Optional[SearchResponse], Optional[ToolResult]]:
        """Parse response and build SearchResponse. Returns (response, error)."""
        try:
            data = response.json()
        except (ValueError, TypeError) as e:
            return None, ToolResult(
                success=False,
                error=f"Failed to parse SearXNG response: {e}",
            )

        # Build SearchResponse
        raw_results = data.get("results", [])
        items: List[SearchResultItem] = []
        for entry in raw_results[:max_results]:
            items.append(
                SearchResultItem(
                    title=entry.get("title", ""),
                    url=entry.get("url", ""),
                    snippet=entry.get("content", ""),
                    score=entry.get("score"),
                )
            )

        search_response = SearchResponse(
            query=query,
            results=items,
            total_results=data.get("number_of_results"),
            search_time_ms=round(elapsed_ms, 2),
        )

        return search_response, None

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a SearXNG search.

        Args:
            query: Search query string.
            max_results: Maximum results to return (default 5).
            categories: Optional list of SearXNG categories.
            language: Language code (default "en").

        Returns:
            ToolResult with SearchResponse data or error.
        """
        query = kwargs.get("query")
        max_results = kwargs.get("max_results", DEFAULT_SEARCH_MAX_RESULTS)
        categories = kwargs.get("categories")
        language = kwargs.get("language", "en")

        # Validate query
        error_result = self._validate_query(query)
        if error_result is not None:
            return error_result
        if not isinstance(query, str):
            return ToolResult(success=False, error="Query must be a string")

        # Check rate limit
        error_result = self._check_rate_limit()
        if error_result is not None:
            return error_result

        # Build query parameters
        params = self._build_search_params(query, language, categories)

        # Record request for rate limiting
        self.rate_limiter.record_request()

        # Execute search request
        response, error_result, elapsed_ms = self._execute_search_request(params)
        if error_result is not None:
            return error_result

        # Parse response
        search_response, error_result = self._parse_results(response, query, max_results, elapsed_ms)
        if error_result is not None:
            return error_result
        if search_response is None:
            return ToolResult(success=False, error="Failed to parse search response")

        return ToolResult(
            success=True,
            result=search_response.model_dump(),
            metadata={
                "base_url": self.base_url,
                "categories": categories,
                "language": language,
                "result_count": len(search_response.results),
            },
        )
