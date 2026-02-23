"""Unit tests for shared search helper models and utilities.

Tests SearchResultItem, SearchResponse, and format_results_for_llm.
"""

from temper_ai.tools._search_helpers import (
    SearchResponse,
    SearchResultItem,
    format_results_for_llm,
)

# ---------------------------------------------------------------------------
# SearchResultItem
# ---------------------------------------------------------------------------


class TestSearchResultItem:
    """Test SearchResultItem model."""

    def test_create_with_all_fields(self):
        """Test creating item with all fields."""
        item = SearchResultItem(
            title="Test Title",
            url="https://example.com",
            snippet="A snippet of text",
            score=0.95,
        )
        assert item.title == "Test Title"
        assert item.url == "https://example.com"
        assert item.snippet == "A snippet of text"
        assert item.score == 0.95

    def test_create_without_score(self):
        """Test creating item without optional score."""
        item = SearchResultItem(
            title="No Score",
            url="https://example.com",
            snippet="snippet",
        )
        assert item.score is None

    def test_score_zero_is_valid(self):
        """Test that score of 0.0 is valid (not treated as None)."""
        item = SearchResultItem(
            title="Zero",
            url="https://example.com",
            snippet="snippet",
            score=0.0,
        )
        assert item.score == 0.0

    def test_model_dump(self):
        """Test serialization to dict."""
        item = SearchResultItem(
            title="T",
            url="https://example.com",
            snippet="S",
            score=0.5,
        )
        data = item.model_dump()
        assert data == {
            "title": "T",
            "url": "https://example.com",
            "snippet": "S",
            "score": 0.5,
        }


# ---------------------------------------------------------------------------
# SearchResponse
# ---------------------------------------------------------------------------


class TestSearchResponse:
    """Test SearchResponse model."""

    def test_create_empty_results(self):
        """Test creating response with no results."""
        resp = SearchResponse(query="test")
        assert resp.query == "test"
        assert resp.results == []
        assert resp.total_results is None
        assert resp.search_time_ms is None

    def test_create_with_results(self):
        """Test creating response with populated results."""
        items = [
            SearchResultItem(title="A", url="https://a.com", snippet="a"),
            SearchResultItem(title="B", url="https://b.com", snippet="b"),
        ]
        resp = SearchResponse(
            query="test",
            results=items,
            total_results=100,
            search_time_ms=42.5,
        )
        assert len(resp.results) == 2
        assert resp.total_results == 100
        assert resp.search_time_ms == 42.5

    def test_model_dump_roundtrip(self):
        """Test serialization and structure."""
        resp = SearchResponse(
            query="q",
            results=[SearchResultItem(title="T", url="https://u.com", snippet="S")],
        )
        data = resp.model_dump()
        assert data["query"] == "q"
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "T"


# ---------------------------------------------------------------------------
# format_results_for_llm
# ---------------------------------------------------------------------------


class TestFormatResultsForLlm:
    """Test the LLM formatter."""

    def test_empty_results(self):
        """Test formatting empty results."""
        resp = SearchResponse(query="nothing found")
        text = format_results_for_llm(resp)
        assert "No results found" in text
        assert "nothing found" in text

    def test_single_result(self):
        """Test formatting a single result."""
        resp = SearchResponse(
            query="python",
            results=[
                SearchResultItem(
                    title="Python.org",
                    url="https://python.org",
                    snippet="Official site",
                ),
            ],
        )
        text = format_results_for_llm(resp)
        assert "1. Python.org" in text
        assert "https://python.org" in text
        assert "Official site" in text

    def test_multiple_results(self):
        """Test formatting multiple results."""
        resp = SearchResponse(
            query="test",
            results=[
                SearchResultItem(title="A", url="https://a.com", snippet="aa"),
                SearchResultItem(title="B", url="https://b.com", snippet="bb"),
                SearchResultItem(title="C", url="https://c.com", snippet="cc"),
            ],
        )
        text = format_results_for_llm(resp)
        assert "1. A" in text
        assert "2. B" in text
        assert "3. C" in text

    def test_score_included_when_present(self):
        """Test that relevance score is shown when available."""
        resp = SearchResponse(
            query="test",
            results=[
                SearchResultItem(
                    title="Scored",
                    url="https://example.com",
                    snippet="s",
                    score=0.91,
                ),
            ],
        )
        text = format_results_for_llm(resp)
        assert "Relevance: 0.91" in text

    def test_score_omitted_when_none(self):
        """Test that relevance line is omitted when score is None."""
        resp = SearchResponse(
            query="test",
            results=[
                SearchResultItem(
                    title="No Score",
                    url="https://example.com",
                    snippet="s",
                ),
            ],
        )
        text = format_results_for_llm(resp)
        assert "Relevance" not in text

    def test_max_results_truncation(self):
        """Test that max_results parameter limits output."""
        items = [
            SearchResultItem(title=f"R{i}", url=f"https://r{i}.com", snippet=f"s{i}")
            for i in range(10)
        ]
        resp = SearchResponse(query="many", results=items)

        text = format_results_for_llm(resp, max_results=3)
        assert "1. R0" in text
        assert "2. R1" in text
        assert "3. R2" in text
        assert "4. R3" not in text

    def test_total_results_shown(self):
        """Test that total_results is shown when set."""
        resp = SearchResponse(
            query="test",
            results=[
                SearchResultItem(title="T", url="https://t.com", snippet="s"),
            ],
            total_results=500,
        )
        text = format_results_for_llm(resp)
        assert "Total results available: 500" in text

    def test_total_results_omitted_when_none(self):
        """Test that total results line is omitted when None."""
        resp = SearchResponse(
            query="test",
            results=[
                SearchResultItem(title="T", url="https://t.com", snippet="s"),
            ],
        )
        text = format_results_for_llm(resp)
        assert "Total results" not in text
