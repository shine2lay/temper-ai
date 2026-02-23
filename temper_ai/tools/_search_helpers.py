"""Shared models and utilities for web search tools.

Provides common Pydantic models (SearchResultItem, SearchResponse) and
a formatter for presenting search results to LLMs.
"""

from pydantic import BaseModel, Field

DEFAULT_FORMAT_MAX_RESULTS = 5


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


def format_results_for_llm(
    response: SearchResponse, max_results: int = DEFAULT_FORMAT_MAX_RESULTS
) -> str:
    """Format search results as readable text for LLM consumption.

    Args:
        response: The search response to format.
        max_results: Maximum number of results to include.

    Returns:
        A formatted string suitable for injection into an LLM prompt.
    """
    if not response.results:
        return f"No results found for: {response.query}"

    lines = [f"Search results for: {response.query}\n"]
    for i, item in enumerate(response.results[:max_results], 1):
        lines.append(f"{i}. {item.title}")
        lines.append(f"   URL: {item.url}")
        lines.append(f"   {item.snippet}")
        if item.score is not None:
            lines.append(f"   Relevance: {item.score:.2f}")
        lines.append("")

    if response.total_results is not None:
        lines.append(f"Total results available: {response.total_results}")

    return "\n".join(lines)
