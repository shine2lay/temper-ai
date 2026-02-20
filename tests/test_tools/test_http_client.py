"""Tests for the HTTPClientTool."""
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.http_client import HTTPClientTool
from temper_ai.tools.http_client_constants import HTTP_DEFAULT_TIMEOUT


@pytest.fixture
def tool():
    return HTTPClientTool()


def test_metadata(tool):
    meta = tool.get_metadata()
    assert meta.name == "HTTPClient"
    assert meta.requires_network is True
    assert meta.category == "network"
    assert meta.modifies_state is True


def test_get_request(tool):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = '{"ok": true}'
    mock_response.headers = {"content-type": "application/json"}

    with patch("temper_ai.tools.http_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = tool.execute(url="https://example.com/api", method="GET")

    assert result.success is True
    assert result.result["status_code"] == 200
    assert "ok" in result.result["body"]
    mock_client.request.assert_called_once_with(
        method="GET", url="https://example.com/api", headers={}, json=None
    )


def test_post_with_body(tool):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.text = '{"created": true}'
    mock_response.headers = {}

    with patch("temper_ai.tools.http_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        result = tool.execute(
            url="https://api.example.com/items",
            method="POST",
            body={"name": "widget"},
        )

    assert result.success is True
    assert result.result["status_code"] == 201
    mock_client.request.assert_called_once_with(
        method="POST",
        url="https://api.example.com/items",
        headers={},
        json={"name": "widget"},
    )


def test_blocked_host_localhost(tool):
    result = tool.execute(url="http://localhost/api")
    assert result.success is False
    assert "blocked" in result.error.lower() or "ssrf" in result.error.lower()


def test_blocked_host_loopback(tool):
    result = tool.execute(url="http://127.0.0.1/secret")
    assert result.success is False
    assert result.error is not None


def test_invalid_method(tool):
    result = tool.execute(url="https://example.com", method="CONNECT")
    assert result.success is False
    assert "not allowed" in result.error.lower()


def test_timeout_error(tool):
    import httpx

    with patch("temper_ai.tools.http_client.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.request.side_effect = httpx.TimeoutException("timed out")
        mock_client_cls.return_value = mock_client

        result = tool.execute(url="https://slow.example.com", timeout=1)

    assert result.success is False
    assert "timed out" in result.error.lower()


def test_empty_url_returns_error(tool):
    result = tool.execute(url="")
    assert result.success is False
    assert result.error is not None


def test_non_http_url_returns_error(tool):
    result = tool.execute(url="ftp://example.com/file")
    assert result.success is False
    assert "http" in result.error.lower()
