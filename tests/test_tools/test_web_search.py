"""Tests for WebSearch tool."""

from unittest.mock import patch, MagicMock

import pytest

from temper_ai.tools.web_search import WebSearch


@pytest.fixture
def search():
    return WebSearch()


class TestWebSearchValidation:
    def test_empty_query(self, search):
        r = search.execute(query="")
        assert r.success is False
        assert "required" in r.error.lower()

    def test_missing_query(self, search):
        r = search.execute()
        assert r.success is False


class TestWebSearchExecution:
    @patch("temper_ai.tools.web_search.httpx")
    def test_successful_search(self, mock_httpx, search):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {"title": "Test Result", "url": "https://example.com", "content": "A test snippet"},
                {"title": "Another", "url": "https://example.org", "content": "More content"},
            ]
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_httpx.Client.return_value = mock_client

        r = search.execute(query="test query")
        assert r.success is True
        assert "Test Result" in r.result
        assert "example.com" in r.result

    @patch("temper_ai.tools.web_search.httpx")
    def test_no_results(self, mock_httpx, search):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_httpx.Client.return_value = mock_client

        r = search.execute(query="obscure query xyz")
        assert r.success is True
        assert "No results" in r.result or r.result.strip() == ""

    @patch("temper_ai.tools.web_search.httpx")
    def test_network_error(self, mock_httpx, search):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")
        mock_httpx.Client.return_value = mock_client

        r = search.execute(query="test")
        assert r.success is False
        assert "failed" in r.error.lower() or "error" in r.error.lower()
