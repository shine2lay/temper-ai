"""TavilySearch tool for web search via the Tavily REST API.

Uses httpx for HTTP requests and returns structured SearchResponse results.
"""
import logging
import os
import time
from typing import Any, Dict, List, Literal, Optional, Type

import httpx
from pydantic import BaseModel, Field, field_validator

from src.tools._search_helpers import SearchResponse, SearchResultItem
from src.tools.base import BaseTool, ToolMetadata, ToolResult
from src.tools.constants import (
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    ERROR_RESPONSE_TEXT_MAX_LENGTH,
    HTTP_STATUS_TOO_MANY_REQUESTS,
    HTTP_STATUS_UNAUTHORIZED,
    MAX_SEARCH_RESULTS,
    RATE_LIMIT_WINDOW_SECONDS,
    TAVILY_DEFAULT_BASE_URL,
    TAVILY_MAX_QUERY_LENGTH,
    TAVILY_RATE_LIMIT,
)
from src.tools.web_scraper import ScraperRateLimiter

logger = logging.getLogger(__name__)


class TavilySearchParams(BaseModel):
    """Pydantic model for TavilySearch parameters with validation."""

    query: str = Field(
        ...,
        description="Search query string",
        min_length=1,
        max_length=TAVILY_MAX_QUERY_LENGTH,
    )
    max_results: int = Field(
        default=DEFAULT_SEARCH_MAX_RESULTS,
        description="Maximum number of results to return",
        ge=1,
        le=MAX_SEARCH_RESULTS,
    )
    search_depth: Literal["basic", "advanced"] = Field(
        default="basic",
        description="Search depth: 'basic' for fast results, 'advanced' for deeper search",
    )
    include_domains: Optional[List[str]] = Field(
        default=None,
        description="Only include results from these domains",
    )
    exclude_domains: Optional[List[str]] = Field(
        default=None,
        description="Exclude results from these domains",
    )

    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, v: str) -> str:
        """Validate query is not only whitespace."""
        if not v.strip():
            raise ValueError("Query must not be blank")
        return v


class TavilySearch(BaseTool):
    """Web search tool using the Tavily REST API.

    Features:
    - Full-text web search via Tavily API
    - Configurable search depth (basic/advanced)
    - Domain inclusion/exclusion filters
    - Rate limiting (5 requests per minute by default)
    - Timeout handling
    - Returns structured SearchResponse results

    Requires:
    - TAVILY_API_KEY environment variable
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize TavilySearch with rate limiter.

        Args:
            config: Optional configuration dict. Supports:
                - base_url: Override Tavily API base URL
        """
        super().__init__(config)
        self.rate_limiter = ScraperRateLimiter(
            max_requests=TAVILY_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS,
        )
        self._base_url = (config or {}).get("base_url", TAVILY_DEFAULT_BASE_URL)
        self._client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        """Return shared httpx.Client, creating it on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=DEFAULT_SEARCH_TIMEOUT,
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
        """Return TavilySearch tool metadata."""
        return ToolMetadata(
            name="TavilySearch",
            description="Searches the web using the Tavily API. Returns structured results with titles, URLs, snippets, and relevance scores.",
            version="1.0",
            category="search",
            requires_network=True,
            requires_credentials=True,
            modifies_state=False,
        )

    def get_parameters_model(self) -> Type[BaseModel]:
        """Return Pydantic model for parameter validation."""
        return TavilySearchParams

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return JSON schema for TavilySearch parameters."""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5, max: 20)",
                    "default": DEFAULT_SEARCH_MAX_RESULTS,
                },
                "search_depth": {
                    "type": "string",
                    "description": "Search depth: 'basic' or 'advanced'",
                    "enum": ["basic", "advanced"],
                    "default": "basic",
                },
                "include_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only include results from these domains",
                },
                "exclude_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exclude results from these domains",
                },
            },
            "required": ["query"],
        }

    def _get_api_key(self) -> str:
        """Get Tavily API key from environment.

        Returns:
            API key string.

        Raises:
            ValueError: If TAVILY_API_KEY is not set or empty.
        """
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "TAVILY_API_KEY environment variable is not set. "
                "Get your API key at https://tavily.com and set it: "
                "export TAVILY_API_KEY='your-key-here'"
            )
        return api_key

    def _validate_query(self, query: Any) -> Optional[ToolResult]:
        """Validate query input. Returns error or None."""
        if not query or not isinstance(query, str) or not query.strip():
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

    def _build_request_body(
        self, api_key: str, query: str, max_results: int, search_depth: str,
        include_domains: Optional[List[str]], exclude_domains: Optional[List[str]]
    ) -> Dict[str, Any]:
        """Build request body for Tavily API."""
        body: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        }
        if include_domains is not None:
            body["include_domains"] = include_domains
        if exclude_domains is not None:
            body["exclude_domains"] = exclude_domains
        return body

    def _execute_api_call(self, body: Dict[str, Any]) -> tuple[Optional[Any], Optional[ToolResult], float]:
        """Execute Tavily API call. Returns (response, error, elapsed_ms)."""
        start_time = time.monotonic()
        try:
            client = self._get_client()
            response = client.post(
                f"{self._base_url}/search",
                json=body,
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return response, None, elapsed_ms

        except httpx.TimeoutException:
            return None, ToolResult(
                success=False,
                error=f"Tavily API request timed out after {DEFAULT_SEARCH_TIMEOUT} seconds",
            ), 0
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == HTTP_STATUS_UNAUTHORIZED:
                error_msg = "Tavily API authentication failed. Check your TAVILY_API_KEY."
            elif status == HTTP_STATUS_TOO_MANY_REQUESTS:
                error_msg = "Tavily API rate limit exceeded. Try again later."
            else:
                error_msg = f"Tavily API error (HTTP {status}): {e.response.text[:ERROR_RESPONSE_TEXT_MAX_LENGTH]}"
            return None, ToolResult(success=False, error=error_msg), 0
        except httpx.RequestError as e:
            return None, ToolResult(
                success=False,
                error=f"Tavily API request error: {str(e)}",
            ), 0

    def _parse_response(self, response: Any, query: str, elapsed_ms: float) -> tuple[Optional[SearchResponse], Optional[ToolResult]]:
        """Parse response and build SearchResponse. Returns (response, error)."""
        try:
            data = response.json()
        except (ValueError, KeyError) as e:
            return None, ToolResult(
                success=False,
                error=f"Failed to parse Tavily API response: {e}",
            )

        # Build SearchResponse
        results = []
        for item in data.get("results", []):
            results.append(
                SearchResultItem(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=item.get("score"),
                )
            )

        search_response = SearchResponse(
            query=data.get("query", query),
            results=results,
            total_results=len(results),
            search_time_ms=elapsed_ms,
        )

        return search_response, None

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a Tavily web search.

        Args:
            query: Search query string (required).
            max_results: Maximum results to return (default: 5).
            search_depth: 'basic' or 'advanced' (default: 'basic').
            include_domains: Optional list of domains to include.
            exclude_domains: Optional list of domains to exclude.

        Returns:
            ToolResult with SearchResponse.model_dump() in result field.
        """
        query = kwargs.get("query")
        max_results = kwargs.get("max_results", DEFAULT_SEARCH_MAX_RESULTS)
        search_depth = kwargs.get("search_depth", "basic")
        include_domains = kwargs.get("include_domains")
        exclude_domains = kwargs.get("exclude_domains")

        # Validate query
        error_result = self._validate_query(query)
        if error_result is not None:
            return error_result

        # Get API key
        try:
            api_key = self._get_api_key()
        except ValueError as e:
            return ToolResult(success=False, error=str(e))

        # Check rate limit
        error_result = self._check_rate_limit()
        if error_result is not None:
            return error_result

        # Build request body
        body = self._build_request_body(api_key, query, max_results, search_depth, include_domains, exclude_domains)

        # Record request for rate limiting
        self.rate_limiter.record_request()

        # Execute API call
        response, error_result, elapsed_ms = self._execute_api_call(body)
        if error_result is not None:
            return error_result

        # Parse response
        search_response, error_result = self._parse_response(response, query, elapsed_ms)
        if error_result is not None:
            return error_result

        return ToolResult(
            success=True,
            result=search_response.model_dump(),
            metadata={
                "query": query,
                "search_depth": search_depth,
                "num_results": len(search_response.results),
                "search_time_ms": round(elapsed_ms, 1),
            },
        )
