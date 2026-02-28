"""Unit tests for shared search helper models.

Tests SearchResultItem and SearchResponse.
"""

from temper_ai.tools._search_helpers import (
    SearchResponse,
    SearchResultItem,
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
