"""Search backend implementations for the WebSearch tool.

Provides a SearchBackend ABC and concrete implementations for Tavily and SearXNG.
"""

import ipaddress
import logging
import os
import time
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any

import httpx

from temper_ai.tools._search_helpers import SearchResponse, SearchResultItem
from temper_ai.tools.base import ToolResult
from temper_ai.tools.constants import (
    DEFAULT_SEARCH_MAX_RESULTS,
    DEFAULT_SEARCH_TIMEOUT,
    ERROR_RESPONSE_TEXT_MAX_LENGTH,
    HTTP_STATUS_TOO_MANY_REQUESTS,
    HTTP_STATUS_UNAUTHORIZED,
    RATE_LIMIT_WINDOW_SECONDS,
    SEARXNG_DEFAULT_BASE_URL,
    SEARXNG_RATE_LIMIT,
    TAVILY_DEFAULT_BASE_URL,
    TAVILY_RATE_LIMIT,
)
from temper_ai.tools.web_scraper import ScraperRateLimiter

logger = logging.getLogger(__name__)


class SearchBackend(ABC):
    """Abstract backend for WebSearch tool."""

    requires_credentials: bool = False

    @abstractmethod
    def search(
        self, query: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    ) -> tuple[ToolResult, float]:
        """Execute search and return (ToolResult, elapsed_ms)."""
        ...

    @abstractmethod
    def check_rate_limit(self) -> ToolResult | None:
        """Check if request is allowed. Returns error ToolResult or None."""
        ...

    @abstractmethod
    def record_request(self) -> None:
        """Record a request for rate limiting."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
        ...


class TavilyBackend(SearchBackend):
    """Tavily API search backend."""

    requires_credentials = True

    def __init__(self, config: dict[str, Any]) -> None:
        self._base_url = config.get("base_url", TAVILY_DEFAULT_BASE_URL)
        self._search_depth = config.get("search_depth", "basic")
        self._include_domains: list[str] | None = config.get("include_domains")
        self._exclude_domains: list[str] | None = config.get("exclude_domains")
        self._rate_limiter = ScraperRateLimiter(
            max_requests=TAVILY_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS,
        )
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=DEFAULT_SEARCH_TIMEOUT)
        return self._client

    def _get_api_key(self) -> str:
        api_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "TAVILY_API_KEY environment variable is not set. "
                "Get your API key at https://tavily.com and set it: "
                "export TAVILY_API_KEY='your-key-here'"
            )
        return api_key

    def check_rate_limit(self) -> ToolResult | None:
        """Return an error ToolResult if rate-limited, else None."""
        if not self._rate_limiter.can_proceed():
            wait_time = self._rate_limiter.wait_time()
            return ToolResult(
                success=False,
                error=f"Rate limit exceeded. Please wait {wait_time:.1f} seconds.",
            )
        return None

    def record_request(self) -> None:
        """Record a request timestamp for rate limiting."""
        self._rate_limiter.record_request()

    def _build_request_body(
        self, api_key: str, query: str, max_results: int
    ) -> dict[str, Any]:  # noqa: long  # noqa: radon
        """Build the Tavily API request body."""
        body: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": self._search_depth,
        }
        if self._include_domains is not None:
            body["include_domains"] = self._include_domains
        if self._exclude_domains is not None:
            body["exclude_domains"] = self._exclude_domains
        return body

    @staticmethod
    def _map_http_status_error(e: httpx.HTTPStatusError) -> str:
        """Map an HTTP status error to a human-readable message."""
        status = e.response.status_code
        if status == HTTP_STATUS_UNAUTHORIZED:
            return "Tavily API authentication failed. Check your TAVILY_API_KEY."
        if status == HTTP_STATUS_TOO_MANY_REQUESTS:
            return "Tavily API rate limit exceeded. Try again later."
        return f"Tavily API error (HTTP {status}): {e.response.text[:ERROR_RESPONSE_TEXT_MAX_LENGTH]}"

    def _execute_request(
        self, body: dict[str, Any]
    ) -> tuple["ToolResult | None", Any, float]:
        """Execute HTTP request. Returns (error_or_None, response, elapsed_ms)."""
        start_time = time.monotonic()
        try:
            response = self._get_client().post(
                f"{self._base_url}/search",
                json=body,
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            return None, response, (time.monotonic() - start_time) * 1000
        except httpx.TimeoutException:
            return (
                ToolResult(
                    success=False,
                    error=f"Tavily API request timed out after {DEFAULT_SEARCH_TIMEOUT} seconds",
                ),
                None,
                0,
            )
        except httpx.HTTPStatusError as e:
            return (
                ToolResult(success=False, error=self._map_http_status_error(e)),
                None,
                0,
            )
        except httpx.RequestError as e:
            return (
                ToolResult(success=False, error=f"Tavily API request error: {e}"),
                None,
                0,
            )

    def search(
        self, query: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    ) -> tuple[ToolResult, float]:
        """Execute a Tavily API search and return (ToolResult, elapsed_ms)."""
        try:
            api_key = self._get_api_key()
        except ValueError as e:
            return ToolResult(success=False, error=str(e)), 0
        body = self._build_request_body(api_key, query, max_results)
        err, response, elapsed_ms = self._execute_request(body)
        if err is not None:
            return err, 0

        # Parse response
        try:
            data = response.json()
        except (ValueError, KeyError) as e:
            return (
                ToolResult(
                    success=False,
                    error=f"Failed to parse Tavily API response: {e}",
                ),
                elapsed_ms,
            )

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

        return (
            ToolResult(
                success=True,
                result=search_response.model_dump(),
                metadata={
                    "query": query,
                    "search_depth": self._search_depth,
                    "num_results": len(search_response.results),
                    "search_time_ms": round(elapsed_ms, 1),
                },
            ),
            elapsed_ms,
        )

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None


class SearxngBackend(SearchBackend):
    """SearXNG self-hosted search backend."""

    requires_credentials = False

    # Allowed loopback hostnames for SSRF protection
    _ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

    def __init__(self, config: dict[str, Any]) -> None:
        raw_url = config.get("base_url", SEARXNG_DEFAULT_BASE_URL)
        self._validate_base_url(raw_url)
        self._base_url = raw_url.rstrip("/")
        self._categories: list[str] | None = config.get("categories")
        self._language: str = config.get("language", "en")
        self._rate_limiter = ScraperRateLimiter(
            max_requests=SEARXNG_RATE_LIMIT,
            time_window=RATE_LIMIT_WINDOW_SECONDS,
        )
        self._client: httpx.Client | None = None

    @classmethod
    def _validate_base_url(cls, url: str) -> None:
        """Validate that base_url is a loopback address (SSRF protection)."""
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if hostname in cls._ALLOWED_HOSTS:
            return

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
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=DEFAULT_SEARCH_TIMEOUT,
                follow_redirects=False,
            )
        return self._client

    def check_rate_limit(self) -> ToolResult | None:
        """Return an error ToolResult if rate-limited, else None."""
        if not self._rate_limiter.can_proceed():
            wait_time = self._rate_limiter.wait_time()
            return ToolResult(
                success=False,
                error=f"Rate limit exceeded. Please wait {wait_time:.1f} seconds.",
            )
        return None  # noqa: long

    def record_request(self) -> None:
        """Record a request timestamp for rate limiting."""
        self._rate_limiter.record_request()

    def _execute_http_search(
        self, params: dict[str, str]
    ) -> "tuple[Any, float] | tuple[ToolResult, float]":
        """Run HTTP GET to SearXNG. Returns (response, elapsed_ms) or (ToolResult, 0) on error."""
        start_time = time.monotonic()
        try:
            client = self._get_client()
            response = client.get(
                f"{self._base_url}/search",
                params=params,
                timeout=DEFAULT_SEARCH_TIMEOUT,
            )
            response.raise_for_status()
            return response, (time.monotonic() - start_time) * 1000
        except httpx.TimeoutException:
            return (
                ToolResult(
                    success=False,
                    error=f"Search request timed out after {DEFAULT_SEARCH_TIMEOUT} seconds",
                ),
                0,
            )
        except httpx.HTTPStatusError as e:
            return (
                ToolResult(
                    success=False,
                    error=f"SearXNG API error {e.response.status_code}: {e.response.reason_phrase}",
                ),
                0,
            )
        except httpx.RequestError as e:
            return ToolResult(success=False, error=f"Request error: {str(e)}"), 0

    def _build_search_result(
        self, query: str, data: dict, elapsed_ms: float
    ) -> ToolResult:
        """Build a successful ToolResult from parsed SearXNG JSON data."""
        items = [
            SearchResultItem(
                title=entry.get("title", ""),
                url=entry.get("url", ""),
                snippet=entry.get("content", ""),
                score=entry.get("score"),
            )
            for entry in data.get("results", [])
        ]
        search_response = SearchResponse(
            query=query,
            results=items,
            total_results=data.get("number_of_results"),
            search_time_ms=round(elapsed_ms, 2),
        )
        return ToolResult(
            success=True,
            result=search_response.model_dump(),
            metadata={
                "base_url": self._base_url,
                "categories": self._categories,
                "language": self._language,
                "result_count": len(search_response.results),
            },
        )

    def search(
        self, query: str, max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    ) -> tuple[ToolResult, float]:
        """Execute a SearXNG search and return (ToolResult, elapsed_ms)."""
        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "language": self._language,
        }
        if self._categories:
            params["categories"] = ",".join(self._categories)

        http_result, elapsed_ms = self._execute_http_search(params)
        if isinstance(http_result, ToolResult):
            return http_result, elapsed_ms

        try:
            data = http_result.json()
        except (ValueError, TypeError) as e:
            return (
                ToolResult(
                    success=False, error=f"Failed to parse SearXNG response: {e}"
                ),
                elapsed_ms,
            )

        data["results"] = data.get("results", [])[:max_results]
        return self._build_search_result(query, data, elapsed_ms), elapsed_ms

    def close(self) -> None:
        """Close the HTTP client and release resources."""
        client = getattr(self, "_client", None)
        if client is not None and not client.is_closed:
            client.close()
            self._client = None
