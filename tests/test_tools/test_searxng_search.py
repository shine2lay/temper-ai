"""Unit tests for SearXNGSearch tool.

Tests SearXNG search with mocked HTTP responses.
"""
import time
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from src.tools.searxng_search import SearXNGSearch, SearXNGSearchParams


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

class TestSearXNGSearchParams:
    """Test SearXNGSearchParams Pydantic model validation."""

    def test_valid_minimal(self):
        """Test minimal valid parameters (query only)."""
        params = SearXNGSearchParams(query="python tutorial")
        assert params.query == "python tutorial"
        assert params.max_results == 5
        assert params.categories is None
        assert params.language == "en"

    def test_valid_full(self):
        """Test fully specified parameters."""
        params = SearXNGSearchParams(
            query="machine learning",
            max_results=10,
            categories=["general", "news"],
            language="de",
        )
        assert params.max_results == 10
        assert params.categories == ["general", "news"]
        assert params.language == "de"

    def test_missing_query(self):
        """Test that missing query raises ValidationError."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams()

    def test_empty_query(self):
        """Test that empty query string raises ValidationError."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams(query="")

    def test_max_results_too_high(self):
        """Test that max_results above MAX_SEARCH_RESULTS is rejected."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams(query="test", max_results=100)

    def test_max_results_zero(self):
        """Test that max_results=0 is rejected."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams(query="test", max_results=0)

    def test_max_results_negative(self):
        """Test that negative max_results is rejected."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams(query="test", max_results=-1)

    def test_empty_categories_list(self):
        """Test that empty categories list is rejected."""
        with pytest.raises(ValidationError):
            SearXNGSearchParams(query="test", categories=[])

    def test_categories_none_allowed(self):
        """Test that categories=None is allowed (default)."""
        params = SearXNGSearchParams(query="test", categories=None)
        assert params.categories is None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestSearXNGSearchMetadata:
    """Test tool metadata."""

    def test_metadata_name(self):
        """Test metadata name."""
        tool = SearXNGSearch()
        assert tool.name == "SearXNGSearch"

    def test_metadata_requires_network(self):
        """Test requires_network is True."""
        tool = SearXNGSearch()
        meta = tool.get_metadata()
        assert meta.requires_network is True

    def test_metadata_no_credentials(self):
        """Test requires_credentials is False."""
        tool = SearXNGSearch()
        meta = tool.get_metadata()
        assert meta.requires_credentials is False

    def test_metadata_no_state_modification(self):
        """Test modifies_state is False."""
        tool = SearXNGSearch()
        meta = tool.get_metadata()
        assert meta.modifies_state is False

    def test_parameters_model(self):
        """Test get_parameters_model returns the correct class."""
        tool = SearXNGSearch()
        assert tool.get_parameters_model() is SearXNGSearchParams

    def test_parameters_schema(self):
        """Test JSON schema has required fields."""
        tool = SearXNGSearch()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_llm_schema(self):
        """Test LLM function-calling schema."""
        tool = SearXNGSearch()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "SearXNGSearch"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.Client for SearXNGSearch."""
    mock_client = MagicMock()
    mock_client.is_closed = False
    with patch.object(SearXNGSearch, "_get_client", return_value=mock_client):
        yield mock_client


def _make_searxng_response(
    results=None, query="test", number_of_results=100, status_code=200
):
    """Helper to build a mock SearXNG JSON response."""
    if results is None:
        results = [
            {
                "title": "Result 1",
                "url": "https://example.com/1",
                "content": "First result snippet",
                "score": 1.5,
            },
            {
                "title": "Result 2",
                "url": "https://example.com/2",
                "content": "Second result snippet",
                "score": 1.2,
            },
        ]
    body = {
        "query": query,
        "number_of_results": number_of_results,
        "results": results,
    }
    mock_resp = Mock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = body
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# Execute — success paths
# ---------------------------------------------------------------------------

class TestSearXNGSearchExecuteSuccess:
    """Test successful search execution."""

    def test_basic_search(self, mock_httpx_client):
        """Test a basic successful search."""
        tool = SearXNGSearch()
        mock_httpx_client.get.return_value = _make_searxng_response()

        result = tool.execute(query="python")

        assert result.success is True
        assert result.result["query"] == "python"
        assert len(result.result["results"]) == 2
        assert result.result["results"][0]["title"] == "Result 1"
        assert result.result["results"][0]["url"] == "https://example.com/1"
        assert result.result["results"][0]["snippet"] == "First result snippet"
        assert result.result["results"][0]["score"] == 1.5

    def test_max_results_limits_output(self, mock_httpx_client):
        """Test that max_results truncates returned items."""
        many_results = [
            {"title": f"R{i}", "url": f"https://example.com/{i}", "content": f"s{i}"}
            for i in range(10)
        ]
        mock_httpx_client.get.return_value = _make_searxng_response(results=many_results)
        tool = SearXNGSearch()

        result = tool.execute(query="test", max_results=3)

        assert result.success is True
        assert len(result.result["results"]) == 3

    def test_categories_passed_to_api(self, mock_httpx_client):
        """Test that categories are sent as comma-separated param."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        tool.execute(query="news", categories=["general", "news"])

        call_kwargs = mock_httpx_client.get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        assert params["categories"] == "general,news"

    def test_language_passed_to_api(self, mock_httpx_client):
        """Test that language is sent as query param."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        tool.execute(query="suche", language="de")

        call_kwargs = mock_httpx_client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["language"] == "de"

    def test_format_json_in_params(self, mock_httpx_client):
        """Test that format=json is always sent."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        tool.execute(query="test")

        call_kwargs = mock_httpx_client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["format"] == "json"

    def test_custom_base_url(self, mock_httpx_client):
        """Test that custom loopback base_url is used in request."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch(base_url="http://127.0.0.1:9090")

        tool.execute(query="test")

        call_args = mock_httpx_client.get.call_args
        url = call_args[0][0]
        assert url == "http://127.0.0.1:9090/search"

    def test_trailing_slash_stripped(self, mock_httpx_client):
        """Test that trailing slash on base_url is stripped."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch(base_url="http://localhost:9090/")

        tool.execute(query="test")

        call_args = mock_httpx_client.get.call_args
        url = call_args[0][0]
        assert url == "http://localhost:9090/search"

    def test_total_results_in_response(self, mock_httpx_client):
        """Test that total_results is captured from API response."""
        mock_httpx_client.get.return_value = _make_searxng_response(
            number_of_results=42
        )
        tool = SearXNGSearch()

        result = tool.execute(query="test")

        assert result.success is True
        assert result.result["total_results"] == 42

    def test_search_time_in_response(self, mock_httpx_client):
        """Test that search_time_ms is populated."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        result = tool.execute(query="test")

        assert result.success is True
        assert result.result["search_time_ms"] is not None
        assert result.result["search_time_ms"] >= 0

    def test_metadata_in_result(self, mock_httpx_client):
        """Test that result metadata contains expected keys."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        result = tool.execute(query="test", categories=["general"], language="fr")

        assert result.metadata["base_url"] == tool.base_url
        assert result.metadata["categories"] == ["general"]
        assert result.metadata["language"] == "fr"
        assert result.metadata["result_count"] == 2

    def test_empty_results(self, mock_httpx_client):
        """Test handling of empty results from SearXNG."""
        mock_httpx_client.get.return_value = _make_searxng_response(
            results=[], number_of_results=0
        )
        tool = SearXNGSearch()

        result = tool.execute(query="xyznonexistent")

        assert result.success is True
        assert result.result["results"] == []
        assert result.metadata["result_count"] == 0

    def test_result_without_score(self, mock_httpx_client):
        """Test handling of results that lack a score field."""
        results = [
            {"title": "No Score", "url": "https://example.com/ns", "content": "snippet"},
        ]
        mock_httpx_client.get.return_value = _make_searxng_response(results=results)
        tool = SearXNGSearch()

        result = tool.execute(query="test")

        assert result.success is True
        assert result.result["results"][0]["score"] is None


# ---------------------------------------------------------------------------
# Execute — error paths
# ---------------------------------------------------------------------------

class TestSearXNGSearchExecuteErrors:
    """Test error handling in execute()."""

    def test_missing_query(self):
        """Test execute with no query argument."""
        tool = SearXNGSearch()
        result = tool.execute()
        assert result.success is False
        assert "query" in result.error.lower()

    def test_empty_string_query(self):
        """Test execute with empty string query."""
        tool = SearXNGSearch()
        result = tool.execute(query="")
        assert result.success is False
        assert "query" in result.error.lower()

    def test_non_string_query(self):
        """Test execute with non-string query."""
        tool = SearXNGSearch()
        result = tool.execute(query=123)
        assert result.success is False

    def test_timeout_error(self, mock_httpx_client):
        """Test handling of timeout from SearXNG."""
        mock_httpx_client.get.side_effect = httpx.TimeoutException("Timeout")
        tool = SearXNGSearch()

        result = tool.execute(query="slow query")

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_http_status_error(self, mock_httpx_client):
        """Test handling of HTTP errors (e.g. 500)."""
        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.reason_phrase = "Internal Server Error"
        mock_httpx_client.get.return_value = mock_resp
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=Mock(), response=mock_resp
        )
        tool = SearXNGSearch()

        result = tool.execute(query="error query")

        assert result.success is False
        assert "500" in result.error

    def test_request_error(self, mock_httpx_client):
        """Test handling of connection errors."""
        mock_httpx_client.get.side_effect = httpx.RequestError("Connection refused")
        tool = SearXNGSearch()

        result = tool.execute(query="unreachable")

        assert result.success is False
        assert "request error" in result.error.lower()

    def test_invalid_json_response(self, mock_httpx_client):
        """Test handling of non-JSON response from SearXNG."""
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_httpx_client.get.return_value = mock_resp
        tool = SearXNGSearch()

        result = tool.execute(query="bad json")

        assert result.success is False
        assert "parse" in result.error.lower()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestSearXNGSearchRateLimiting:
    """Test rate limiting behaviour."""

    def test_rate_limit_enforcement(self, mock_httpx_client):
        """Test that requests are blocked after limit is reached."""
        mock_httpx_client.get.return_value = _make_searxng_response()
        tool = SearXNGSearch()

        # Exhaust the rate limit (10 requests)
        for i in range(10):
            result = tool.execute(query=f"q{i}")
            assert result.success is True

        # Next request should be rate limited
        result = tool.execute(query="over-limit")

        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_rate_limit_includes_wait_time(self):
        """Test that rate limit error message includes wait time."""
        tool = SearXNGSearch()

        # Exhaust rate limit
        for _ in range(10):
            tool.rate_limiter.record_request()

        result = tool.execute(query="blocked")

        assert result.success is False
        assert "wait" in result.error.lower()


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------

class TestSearXNGSearchSSRF:
    """Test SSRF protection on base_url."""

    def test_localhost_allowed(self):
        tool = SearXNGSearch(base_url="http://localhost:8888")
        assert tool.base_url == "http://localhost:8888"

    def test_127_0_0_1_allowed(self):
        tool = SearXNGSearch(base_url="http://127.0.0.1:8888")
        assert tool.base_url == "http://127.0.0.1:8888"

    def test_127_x_range_allowed(self):
        tool = SearXNGSearch(base_url="http://127.0.1.1:9090")
        assert tool.base_url == "http://127.0.1.1:9090"

    def test_ipv6_loopback_allowed(self):
        tool = SearXNGSearch(base_url="http://[::1]:8888")
        assert tool.base_url == "http://[::1]:8888"

    def test_external_host_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            SearXNGSearch(base_url="http://example.com:8888")

    def test_private_ip_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            SearXNGSearch(base_url="http://192.168.1.100:8888")

    def test_metadata_endpoint_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            SearXNGSearch(base_url="http://169.254.169.254")

    def test_public_ip_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            SearXNGSearch(base_url="http://8.8.8.8:8888")


class TestSearXNGSearchClientLifecycle:
    """Test httpx client management."""

    def test_client_reuse(self):
        """Test that client is reused across calls."""
        tool = SearXNGSearch()
        c1 = tool._get_client()
        c2 = tool._get_client()
        assert c1 is c2

    def test_client_recreation_after_close(self):
        """Test that client is recreated after close()."""
        tool = SearXNGSearch()
        c1 = tool._get_client()
        tool.close()
        c2 = tool._get_client()
        assert c1 is not c2

    def test_del_cleanup(self):
        """Test __del__ does not raise."""
        tool = SearXNGSearch()
        tool._get_client()
        try:
            tool.__del__()
        except Exception as e:
            pytest.fail(f"__del__ raised: {e}")
        # Verify that __del__ completed without exception
        assert True

    def test_del_os_error(self):
        """Test __del__ handles OSError gracefully."""
        tool = SearXNGSearch()
        client = tool._get_client()
        with patch.object(client, "close", side_effect=OSError("Mock")):
            try:
                tool.__del__()
            except Exception as e:
                pytest.fail(f"__del__ raised: {e}")
        # Verify that __del__ handled OSError gracefully
        assert True
