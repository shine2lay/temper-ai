"""Shared models for web search tools.

Provides common Pydantic models (SearchResultItem, SearchResponse).
"""

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    """A single search result."""

    title: str
    url: str
    snippet: str
    score: float | None = Field(
        default=None, description="Relevance score if provided by the search engine"
    )


class SearchResponse(BaseModel):
    """Aggregated response from a search query."""

    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    total_results: int | None = None
    search_time_ms: float | None = None
