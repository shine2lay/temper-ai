"""Unified WebSearch tool with pluggable search backends.

Supports Tavily (API key required) and SearXNG (self-hosted, no key)
via a single tool interface. Backend is selected through config.
"""

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from temper_ai.tools._search_backends import (
    SearchBackend,
    SearxngBackend,
    TavilyBackend,
)
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult
from temper_ai.tools.constants import DEFAULT_SEARCH_MAX_RESULTS, MAX_SEARCH_RESULTS

logger = logging.getLogger(__name__)


class WebSearchParams(BaseModel):
    """Call-time parameters for the WebSearch tool."""

    query: str = Field(description="Search query string")
    max_results: int = Field(
        default=DEFAULT_SEARCH_MAX_RESULTS,
        description=f"Maximum number of results (default: {DEFAULT_SEARCH_MAX_RESULTS}, max: {MAX_SEARCH_RESULTS})",
    )


class WebSearchConfig(BaseModel):
    """YAML config schema for the WebSearch tool."""

    provider: Literal["tavily", "searxng"] = Field(
        default="searxng",
        description="Search backend provider",
    )
    base_url: str | None = Field(
        default=None,
        description="API base URL (Tavily or SearXNG). SearXNG must be loopback for SSRF protection.",
    )
    search_depth: Literal["basic", "advanced"] = Field(
        default="basic",
        description="Tavily search depth",
    )
    include_domains: list[str] | None = Field(
        default=None,
        description="Tavily: only include results from these domains",
    )
    exclude_domains: list[str] | None = Field(
        default=None,
        description="Tavily: exclude results from these domains",
    )
    categories: list[str] | None = Field(
        default=None,
        description="SearXNG categories to search",
    )
    language: str = Field(
        default="en",
        description="SearXNG search language code",
    )


class WebSearch(BaseTool):
    """Unified web search tool with configurable backend.

    Supports two providers:
    - ``searxng`` (default): Queries a self-hosted SearXNG instance. No API key needed.
    - ``tavily``: Queries the Tavily REST API. Requires ``TAVILY_API_KEY`` env var.

    Provider-specific settings (search_depth, categories, language, etc.) are
    configured via the YAML config block, not per-call parameters.
    """

    params_model = WebSearchParams
    config_model = WebSearchConfig

    def __init__(self, config: dict[str, Any] | None = None):
        self._backend: SearchBackend
        cfg = config or {}
        provider = cfg.get("provider", "searxng")
        if provider == "tavily":
            self._backend = TavilyBackend(cfg)
        elif provider == "searxng":
            self._backend = SearxngBackend(cfg)
        else:
            raise ValueError(
                f"Unknown search provider: {provider!r}. Must be 'tavily' or 'searxng'."
            )
        self._provider = provider
        super().__init__(config)

    def get_metadata(self) -> ToolMetadata:
        """Return tool metadata describing WebSearch capabilities."""
        return ToolMetadata(
            name="WebSearch",
            description=(
                "Searches the web and returns structured results with titles, URLs, and snippets."
            ),
            version="1.0",
            category="search",
            requires_network=True,
            requires_credentials=self._backend.requires_credentials,
            modifies_state=False,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a web search query via the configured backend."""
        query = kwargs.get("query")
        max_results = kwargs.get("max_results", DEFAULT_SEARCH_MAX_RESULTS)

        # Validate query
        if not query or not isinstance(query, str) or not query.strip():
            return ToolResult(
                success=False,
                error="query must be a non-empty string",
            )

        # Check rate limit
        rate_error = self._backend.check_rate_limit()
        if rate_error is not None:
            return rate_error

        # Record request for rate limiting
        self._backend.record_request()

        # Delegate to backend
        result, _elapsed = self._backend.search(query, max_results)
        return result

    def close(self) -> None:
        """Close the backend's HTTP client."""
        self._backend.close()

    def __del__(self) -> None:
        try:
            self.close()
        except (OSError, RuntimeError, AttributeError):
            pass
