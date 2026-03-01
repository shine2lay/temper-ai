"""Unit tests for the unified WebSearch tool.

Tests both Tavily and SearXNG backends via the WebSearch interface.
"""

from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest

from temper_ai.tools._search_backends import SearxngBackend, TavilyBackend
from temper_ai.tools.web_search import WebSearch

# ===========================================================================
# Helpers
# ===========================================================================


def _make_tavily_response(results=None, query="test query"):
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


def _make_searxng_response(
    results=None, query="test", number_of_results=100, status_code=200
):
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


# ===========================================================================
# Provider selection
# ===========================================================================


class TestProviderSelection:
    """Test that config.provider selects the correct backend."""

    def test_default_provider_is_searxng(self):
        tool = WebSearch()
        assert isinstance(tool._backend, SearxngBackend)

    def test_explicit_searxng(self):
        tool = WebSearch(config={"provider": "searxng"})
        assert isinstance(tool._backend, SearxngBackend)

    def test_tavily_provider(self):
        tool = WebSearch(config={"provider": "tavily"})
        assert isinstance(tool._backend, TavilyBackend)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown search provider"):
            WebSearch(config={"provider": "google"})


# ===========================================================================
# Metadata
# ===========================================================================


class TestWebSearchMetadata:
    """Test tool metadata for both providers."""

    def test_name_is_websearch(self):
        tool = WebSearch()
        assert tool.name == "WebSearch"

    def test_requires_network(self):
        tool = WebSearch()
        assert tool.get_metadata().requires_network is True

    def test_does_not_modify_state(self):
        tool = WebSearch()
        assert tool.get_metadata().modifies_state is False

    def test_searxng_no_credentials(self):
        tool = WebSearch(config={"provider": "searxng"})
        assert tool.get_metadata().requires_credentials is False

    def test_tavily_requires_credentials(self):
        tool = WebSearch(config={"provider": "tavily"})
        assert tool.get_metadata().requires_credentials is True


# ===========================================================================
# Schema
# ===========================================================================


class TestWebSearchSchema:
    """Test parameter and config schemas."""

    def test_parameters_schema_has_query(self):
        tool = WebSearch()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_parameters_schema_has_max_results(self):
        tool = WebSearch()
        schema = tool.get_parameters_schema()
        assert "max_results" in schema["properties"]

    def test_llm_schema(self):
        tool = WebSearch()
        schema = tool.to_llm_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "WebSearch"


# ===========================================================================
# Query validation
# ===========================================================================


class TestQueryValidation:
    """Test query input validation (both providers)."""

    @pytest.mark.parametrize("provider", ["searxng", "tavily"])
    def test_missing_query(self, provider):
        tool = WebSearch(config={"provider": provider})
        result = tool.execute()
        assert result.success is False
        assert "query" in result.error.lower()

    @pytest.mark.parametrize("provider", ["searxng", "tavily"])
    def test_empty_query(self, provider):
        tool = WebSearch(config={"provider": provider})
        result = tool.execute(query="")
        assert result.success is False
        assert "query" in result.error.lower()

    @pytest.mark.parametrize("provider", ["searxng", "tavily"])
    def test_non_string_query(self, provider):
        tool = WebSearch(config={"provider": provider})
        result = tool.execute(query=123)
        assert result.success is False

    @pytest.mark.parametrize("provider", ["searxng", "tavily"])
    def test_whitespace_only_query(self, provider):
        tool = WebSearch(config={"provider": provider})
        result = tool.execute(query="   ")
        assert result.success is False


# ===========================================================================
# Tavily backend — execution
# ===========================================================================


@pytest.fixture
def tavily_tool():
    """WebSearch configured for Tavily with mocked httpx client."""
    tool = WebSearch(config={"provider": "tavily"})
    mock_client = MagicMock()
    mock_client.is_closed = False
    with (
        patch.object(TavilyBackend, "_get_client", return_value=mock_client),
        patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key-123"}),
    ):
        yield tool, mock_client


class TestTavilyExecution:
    """Test Tavily backend via WebSearch."""

    def test_basic_search(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_client.post.return_value = mock_response

        result = tool.execute(query="test query")

        assert result.success is True
        assert result.result["query"] == "test query"
        assert len(result.result["results"]) == 2
        assert result.result["results"][0]["title"] == "Result 1"

    def test_api_key_in_body(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_client.post.return_value = mock_response

        tool.execute(query="test")

        body = mock_client.post.call_args[1]["json"]
        assert body["api_key"] == "tvly-test-key-123"

    def test_empty_results(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"query": "obscure", "results": []}
        mock_client.post.return_value = mock_response

        result = tool.execute(query="obscure")
        assert result.success is True
        assert result.result["results"] == []

    def test_result_without_score(self, tavily_tool):
        tool, mock_client = tavily_tool
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
        mock_client.post.return_value = mock_response

        result = tool.execute(query="test")
        assert result.success is True
        assert result.result["results"][0]["score"] is None

    def test_search_time_recorded(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_client.post.return_value = mock_response

        result = tool.execute(query="test")
        assert result.metadata["search_time_ms"] >= 0


# ===========================================================================
# Tavily backend — API key
# ===========================================================================


class TestTavilyApiKey:
    """Test API key validation for Tavily."""

    def test_missing_api_key(self):
        tool = WebSearch(config={"provider": "tavily"})
        with patch.dict("os.environ", {}, clear=True):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error

    def test_empty_api_key(self):
        tool = WebSearch(config={"provider": "tavily"})
        with patch.dict("os.environ", {"TAVILY_API_KEY": ""}):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error

    def test_whitespace_only_api_key(self):
        tool = WebSearch(config={"provider": "tavily"})
        with patch.dict("os.environ", {"TAVILY_API_KEY": "   "}):
            result = tool.execute(query="test")
        assert result.success is False
        assert "TAVILY_API_KEY" in result.error


# ===========================================================================
# Tavily backend — error handling
# ===========================================================================


class TestTavilyErrors:
    """Test Tavily error handling."""

    def test_timeout(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")

        result = tool.execute(query="slow query")
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_http_401(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_resp = Mock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=Mock(), response=mock_resp
        )

        result = tool.execute(query="test")
        assert result.success is False
        assert "authentication" in result.error.lower()

    def test_http_429(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_resp = Mock()
        mock_resp.status_code = 429
        mock_resp.text = "Too Many Requests"
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Too Many Requests", request=Mock(), response=mock_resp
        )

        result = tool.execute(query="test")
        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_http_500(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Server Error", request=Mock(), response=mock_resp
        )

        result = tool.execute(query="test")
        assert result.success is False
        assert "500" in result.error

    def test_request_error(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_client.post.side_effect = httpx.RequestError("Connection refused")

        result = tool.execute(query="test")
        assert result.success is False
        assert "request error" in result.error.lower()

    def test_invalid_json(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_client.post.return_value = mock_resp

        result = tool.execute(query="test")
        assert result.success is False
        assert "parse" in result.error.lower()


# ===========================================================================
# SearXNG backend — execution
# ===========================================================================


@pytest.fixture
def searxng_tool():
    """WebSearch configured for SearXNG with mocked httpx client."""
    tool = WebSearch(config={"provider": "searxng"})
    mock_client = MagicMock()
    mock_client.is_closed = False
    with patch.object(SearxngBackend, "_get_client", return_value=mock_client):
        yield tool, mock_client


class TestSearxngExecution:
    """Test SearXNG backend via WebSearch."""

    def test_basic_search(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response()

        result = tool.execute(query="python")

        assert result.success is True
        assert len(result.result["results"]) == 2
        assert result.result["results"][0]["title"] == "Result 1"

    def test_max_results_limits_output(self, searxng_tool):
        tool, mock_client = searxng_tool
        many_results = [
            {"title": f"R{i}", "url": f"https://example.com/{i}", "content": f"s{i}"}
            for i in range(10)
        ]
        mock_client.get.return_value = _make_searxng_response(results=many_results)

        result = tool.execute(query="test", max_results=3)
        assert result.success is True
        assert len(result.result["results"]) == 3

    def test_format_json_in_params(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response()

        tool.execute(query="test")

        params = mock_client.get.call_args[1]["params"]
        assert params["format"] == "json"

    def test_total_results_in_response(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response(number_of_results=42)

        result = tool.execute(query="test")
        assert result.result["total_results"] == 42

    def test_search_time_in_response(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response()

        result = tool.execute(query="test")
        assert result.result["search_time_ms"] >= 0

    def test_empty_results(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response(
            results=[], number_of_results=0
        )

        result = tool.execute(query="xyznonexistent")
        assert result.success is True
        assert result.result["results"] == []

    def test_result_without_score(self, searxng_tool):
        tool, mock_client = searxng_tool
        results = [
            {
                "title": "No Score",
                "url": "https://example.com/ns",
                "content": "snippet",
            },
        ]
        mock_client.get.return_value = _make_searxng_response(results=results)

        result = tool.execute(query="test")
        assert result.result["results"][0]["score"] is None


# ===========================================================================
# SearXNG backend — config passthrough
# ===========================================================================


class TestSearxngConfig:
    """Test SearXNG-specific config options."""

    def test_categories_from_config(self, searxng_tool):
        tool = WebSearch(
            config={"provider": "searxng", "categories": ["general", "news"]}
        )
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.get.return_value = _make_searxng_response()
        with patch.object(SearxngBackend, "_get_client", return_value=mock_client):
            tool.execute(query="news")
            params = mock_client.get.call_args[1]["params"]
            assert params["categories"] == "general,news"

    def test_language_from_config(self, searxng_tool):
        tool = WebSearch(config={"provider": "searxng", "language": "de"})
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.get.return_value = _make_searxng_response()
        with patch.object(SearxngBackend, "_get_client", return_value=mock_client):
            tool.execute(query="suche")
            params = mock_client.get.call_args[1]["params"]
            assert params["language"] == "de"

    def test_custom_base_url_loopback(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://127.0.0.1:9090"}
        )
        assert tool._backend._base_url == "http://127.0.0.1:9090"

    def test_trailing_slash_stripped(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://localhost:9090/"}
        )
        assert tool._backend._base_url == "http://localhost:9090"


# ===========================================================================
# SearXNG backend — errors
# ===========================================================================


class TestSearxngErrors:
    """Test SearXNG error handling."""

    def test_timeout(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.side_effect = httpx.TimeoutException("Timeout")

        result = tool.execute(query="slow")
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_http_status_error(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_resp = Mock()
        mock_resp.status_code = 500
        mock_resp.reason_phrase = "Internal Server Error"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=Mock(), response=mock_resp
        )
        mock_client.get.return_value = mock_resp

        result = tool.execute(query="error")
        assert result.success is False
        assert "500" in result.error

    def test_request_error(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.side_effect = httpx.RequestError("Connection refused")

        result = tool.execute(query="unreachable")
        assert result.success is False
        assert "request error" in result.error.lower()

    def test_invalid_json(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_client.get.return_value = mock_resp

        result = tool.execute(query="bad json")
        assert result.success is False
        assert "parse" in result.error.lower()


# ===========================================================================
# SSRF protection (SearXNG)
# ===========================================================================


class TestSearxngSSRF:
    """Test SSRF protection on SearXNG base_url."""

    def test_localhost_allowed(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://localhost:8888"}
        )
        assert tool._backend._base_url == "http://localhost:8888"

    def test_127_0_0_1_allowed(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://127.0.0.1:8888"}
        )
        assert tool._backend._base_url == "http://127.0.0.1:8888"

    def test_127_x_range_allowed(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://127.0.1.1:9090"}
        )
        assert tool._backend._base_url == "http://127.0.1.1:9090"

    def test_ipv6_loopback_allowed(self):
        tool = WebSearch(
            config={"provider": "searxng", "base_url": "http://[::1]:8888"}
        )
        assert tool._backend._base_url == "http://[::1]:8888"

    def test_external_host_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            WebSearch(
                config={"provider": "searxng", "base_url": "http://example.com:8888"}
            )

    def test_private_ip_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            WebSearch(
                config={"provider": "searxng", "base_url": "http://192.168.1.100:8888"}
            )

    def test_metadata_endpoint_rejected(self):
        with pytest.raises(ValueError, match="loopback address"):
            WebSearch(
                config={"provider": "searxng", "base_url": "http://169.254.169.254"}
            )


# ===========================================================================
# Rate limiting (both backends)
# ===========================================================================


class TestRateLimiting:
    """Test rate limiting for both providers."""

    def test_tavily_rate_limit(self, tavily_tool):
        tool, mock_client = tavily_tool
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_tavily_response()
        mock_client.post.return_value = mock_response

        # Exhaust rate limit (5 requests)
        for i in range(5):
            result = tool.execute(query=f"query {i}")
            assert result.success is True

        result = tool.execute(query="over limit")
        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_searxng_rate_limit(self, searxng_tool):
        tool, mock_client = searxng_tool
        mock_client.get.return_value = _make_searxng_response()

        # Exhaust rate limit (10 requests)
        for i in range(10):
            result = tool.execute(query=f"q{i}")
            assert result.success is True

        result = tool.execute(query="over-limit")
        assert result.success is False
        assert "rate limit" in result.error.lower()

    def test_rate_limit_includes_wait_time(self):
        tool = WebSearch(config={"provider": "searxng"})
        for _ in range(10):
            tool._backend._rate_limiter.record_request()

        result = tool.execute(query="blocked")
        assert result.success is False
        assert "wait" in result.error.lower()


# ===========================================================================
# Client lifecycle
# ===========================================================================


class TestClientLifecycle:
    """Test httpx client management."""

    def test_tavily_client_reuse(self):
        tool = WebSearch(config={"provider": "tavily"})
        c1 = tool._backend._get_client()
        c2 = tool._backend._get_client()
        assert c1 is c2
        tool.close()

    def test_searxng_client_reuse(self):
        tool = WebSearch()
        c1 = tool._backend._get_client()
        c2 = tool._backend._get_client()
        assert c1 is c2
        tool.close()

    def test_close_and_recreate(self):
        tool = WebSearch()
        c1 = tool._backend._get_client()
        tool.close()
        c2 = tool._backend._get_client()
        assert c1 is not c2
        tool.close()

    def test_del_cleanup(self):
        tool = WebSearch()
        tool._backend._get_client()
        tool.__del__()
        assert tool._backend._client is None


# ===========================================================================
# Deprecation shims
# ===========================================================================
