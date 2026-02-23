"""Unit tests for TavilySearch tool.

Tests Tavily web search with mocked HTTP responses.
"""

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from pydantic import ValidationError

from temper_ai.tools.tavily_search import TavilySearch, TavilySearchParams

# ---------------------------------------------------------------------------
# TavilySearchParams validation
# ---------------------------------------------------------------------------


class TestTavilySearchParams:
    """Test parameter validation via the Pydantic model."""

    def test_valid_params_minimal(self):
        """Test valid params with only required fields."""
        params = TavilySearchParams(query="python web framework")
        assert params.query == "python web framework"
        assert params.max_results == 5
        assert params.search_depth == "basic"
        assert params.include_domains is None
        assert params.exclude_domains is None

    def test_valid_params_full(self):
        """Test valid params with all fields."""
        params = TavilySearchParams(
            query="AI news",
            max_results=10,
            search_depth="advanced",
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )
        assert params.max_results == 10
        assert params.search_depth == "advanced"

    def test_missing_query_raises(self):
        """Test that missing query raises ValidationError."""
        with pytest.raises(ValidationError):
            TavilySearchParams()

    def test_empty_query_raises(self):
        """Test that empty query string raises ValidationError."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="")

    def test_blank_query_raises(self):
        """Test that whitespace-only query raises ValidationError."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="   ")

    def test_max_results_too_high(self):
        """Test that max_results above MAX_SEARCH_RESULTS raises."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="test", max_results=100)

    def test_max_results_zero(self):
        """Test that max_results=0 raises."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="test", max_results=0)

    def test_max_results_negative(self):
        """Test that negative max_results raises."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="test", max_results=-1)

    def test_invalid_search_depth(self):
        """Test that invalid search_depth raises."""
        with pytest.raises(ValidationError):
            TavilySearchParams(query="test", search_depth="deep")


# ---------------------------------------------------------------------------
# TavilySearch metadata
# ---------------------------------------------------------------------------


class TestTavilySearchMetadata:
    """Test tool metadata."""

    def test_metadata_name(self):
        """Test metadata returns correct name."""
        tool = TavilySearch()
        meta = tool.get_metadata()
        assert meta.name == "TavilySearch"

    def test_metadata_requires_network(self):
        """Test metadata indicates network required."""
        tool = TavilySearch()
        meta = tool.get_metadata()
        assert meta.requires_network is True

    def test_metadata_requires_credentials(self):
        """Test metadata indicates credentials required."""
        tool = TavilySearch()
        meta = tool.get_metadata()
        assert meta.requires_credentials is True

    def test_metadata_does_not_modify_state(self):
        """Test metadata indicates no state modification."""
        tool = TavilySearch()
        meta = tool.get_metadata()
        assert meta.modifies_state is False

    def test_parameters_model(self):
        """Test get_parameters_model returns TavilySearchParams."""
        tool = TavilySearch()
        assert tool.get_parameters_model() is TavilySearchParams

    def test_parameters_schema(self):
        """Test get_parameters_schema returns valid schema."""
        tool = TavilySearch()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_llm_schema(self):
        """Test to_llm_schema produces OpenAI-compatible format."""
        tool = TavilySearch()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "TavilySearch"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_httpx_client():
    """Create a mock httpx.Client for testing."""
    mock_client = MagicMock()
    mock_client.is_closed = False
    with patch.object(TavilySearch, "_get_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def tavily_api_key():
    """Set a fake TAVILY_API_KEY for tests."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key-123"}):
        yield "tvly-test-key-123"


def _make_tavily_response(results=None, query="test query"):
    """Helper to build a mock Tavily API JSON response."""
    if results is None:
        results = [
            {
                "title": "Result 1",
                "url": "https://example.com/1",
                "content": "First result snippet",
                "score": 0.95,
            },
            {
                "title": "Result 2",
                "url": "https://example.com/2",
                "content": "Second result snippet",
                "score": 0.87,
            },
        ]
    return {"query": query, "results": results}


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------


class TestApiKeyValidation:
    """Test API key handling."""

    def test_missing_api_key(self):
        """Test that missing API key returns clear error."""
        tool = TavilySearch()
        with patch.dict("os.environ", {}, clear=True):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error

    def test_empty_api_key(self):
        """Test that empty API key returns clear error."""
        tool = TavilySearch()
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error

    def test_whitespace_only_api_key(self):
        """Test that whitespace-only API key returns clear error."""
        tool = TavilySearch()
        with patch.dict("os.environ", {"TAVILY_API_KEY": "   "}):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestSuccessfulExecution:
    """Test successful search execution with mocked httpx."""

    def test_basic_search(self, mock_httpx_client, tavily_api_key):
        """Test a basic successful search."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(query="test query")

        assert result.success is True
        assert result.result["query"] == "test query"
        assert len(result.result["results"]) == 2
        assert result.result["results"][0]["title"] == "Result 1"
        assert result.result["results"][0]["score"] == 0.95
        assert result.metadata["num_results"] == 2

    def test_search_with_all_params(self, mock_httpx_client, tavily_api_key):
        """Test search with all optional parameters."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(
            query="AI news",
            max_results=10,
            search_depth="advanced",
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )

        assert result.success is True

        # Verify request body
        call_args = mock_httpx_client.post.call_args
        body = call_args[1]["json"]
        assert body["query"] == "AI news"
        assert body["max_results"] == 10
        assert body["search_depth"] == "advanced"
        assert body["include_domains"] == ["example.com"]
        assert body["exclude_domains"] == ["spam.com"]

    def test_empty_results(self, mock_httpx_client, tavily_api_key):
        """Test search that returns no results."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"query": "obscure", "results": []}
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(query="obscure")

        assert result.success is True
        assert result.result["results"] == []
        assert result.metadata["num_results"] == 0

    def test_result_without_score(self, mock_httpx_client, tavily_api_key):
        """Test parsing results that lack a score field."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "query": "test",
            "results": [
                {
                    "title": "No Score",
                    "url": "https://example.com",
                    "content": "snippet",
                },
            ],
        }
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(query="test")

        assert result.success is True
        assert result.result["results"][0]["score"] is None

    def test_api_key_sent_in_body(self, mock_httpx_client, tavily_api_key):
        """Test that the API key is included in the POST body."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_httpx_client.post.return_value = mock_response

        tool.execute(query="test")

        call_args = mock_httpx_client.post.call_args
        body = call_args[1]["json"]
        assert body["api_key"] == "tvly-test-key-123"

    def test_search_time_recorded(self, mock_httpx_client, tavily_api_key):
        """Test that search time is recorded in metadata."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(query="test")

        assert result.success is True
        assert "search_time_ms" in result.metadata
        assert result.metadata["search_time_ms"] >= 0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test error handling for API failures."""

    def test_invalid_query_empty(self, tavily_api_key):
        """Test that empty query returns error."""
        tool = TavilySearch()
        result = tool.execute(query="")
        assert result.success is False
        assert "query" in result.error.lower()

    def test_invalid_query_none(self, tavily_api_key):
        """Test that None query returns error."""
        tool = TavilySearch()
        result = tool.execute()
        assert result.success is False
        assert "query" in result.error.lower()

    def test_invalid_query_non_string(self, tavily_api_key):
        """Test that non-string query returns error."""
        tool = TavilySearch()
        result = tool.execute(query=123)
        assert result.success is False

    def test_timeout_error(self, mock_httpx_client, tavily_api_key):
        """Test handling of timeout errors."""
        tool = TavilySearch()
        mock_httpx_client.post.side_effect = httpx.TimeoutException("Timeout")

        result = tool.execute(query="slow query")

        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_http_401_error(self, mock_httpx_client, tavily_api_key):
        """Test handling of authentication errors."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=Mock(),
            response=mock_response,
        )

        result = tool.execute(query="test")

        assert result.success is False
        assert "authentication" in result.error.lower()

    def test_http_429_error(self, mock_httpx_client, tavily_api_key):
        """Test handling of API rate limit errors."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"
        mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
            "Too Many Requests",
            request=Mock(),
            response=mock_response,
        )

        result = tool.execute(query="test")

        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_http_500_error(self, mock_httpx_client, tavily_api_key):
        """Test handling of server errors."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
            "Server Error",
            request=Mock(),
            response=mock_response,
        )

        result = tool.execute(query="test")

        assert result.success is False
        assert "500" in result.error

    def test_request_error(self, mock_httpx_client, tavily_api_key):
        """Test handling of connection/request errors."""
        tool = TavilySearch()
        mock_httpx_client.post.side_effect = httpx.RequestError("Connection refused")

        result = tool.execute(query="test")

        assert result.success is False
        assert "request error" in result.error.lower()

    def test_invalid_json_response(self, mock_httpx_client, tavily_api_key):
        """Test handling of malformed JSON response."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_httpx_client.post.return_value = mock_response

        result = tool.execute(query="test")

        assert result.success is False
        assert "parse" in result.error.lower()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test rate limiting."""

    def test_rate_limit_enforcement(self, mock_httpx_client, tavily_api_key):
        """Test that rate limit is enforced after max requests."""
        tool = TavilySearch()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_httpx_client.post.return_value = mock_response

        # Exhaust rate limit (TAVILY_RATE_LIMIT = 5)
        for i in range(5):
            result = tool.execute(query=f"query {i}")
            assert result.success is True

        # Next should be rate limited
        result = tool.execute(query="over limit")
        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_rate_limit_message_includes_wait_time(self, tavily_api_key):
        """Test that rate limit error includes wait time."""
        tool = TavilySearch()

        # Exhaust rate limit
        for _ in range(5):
            tool.rate_limiter.record_request()

        result = tool.execute(query="over limit")
        assert result.success is False
        assert "wait" in result.error.lower()


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """Test httpx client management."""

    def test_client_reuse(self):
        """Test that client is reused across calls."""
        tool = TavilySearch()
        client1 = tool._get_client()
        client2 = tool._get_client()
        assert client1 is client2

    def test_client_recreation_after_close(self):
        """Test that client is recreated after close."""
        tool = TavilySearch()
        client1 = tool._get_client()
        tool.close()
        client2 = tool._get_client()
        assert client1 is not client2

    def test_del_cleanup(self):
        """Test that __del__ closes client gracefully."""
        tool = TavilySearch()
        tool._get_client()
        # Should not raise during cleanup
        tool.__del__()
        assert tool._client is None  # client cleaned up after __del__

    def test_custom_base_url(self):
        """Test that custom base_url from config is used."""
        tool = TavilySearch(config={"base_url": "https://custom.api.com"})
        assert tool._base_url == "https://custom.api.com"
