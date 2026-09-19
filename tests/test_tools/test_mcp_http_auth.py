"""_connect_http: static headers and OAuth reach the transport, or nothing does.

The point of these is that an HTTP MCP server config is the only thing
standing between temper and a third-party API. If `headers` or `auth` were
silently dropped the connection would just fail as unauthorized, which looks
identical to a bad token — so each path is pinned to what actually reaches
httpx.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from temper_ai.tools import mcp_auth
from temper_ai.tools.mcp_client import MCPClientManager


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv(mcp_auth.SECRET_KEY_ENV_VAR, Fernet.generate_key().decode())


@pytest.fixture
def captured(monkeypatch):
    """Capture what _connect_http hands to httpx and to the transport."""
    seen: dict = {}

    def fake_create_client(headers=None, timeout=None, auth=None):
        seen["headers"] = headers
        seen["auth"] = auth
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        return client

    @contextlib.asynccontextmanager
    async def fake_transport(url, *, http_client=None, **kwargs):
        seen["url"] = url
        seen["http_client"] = http_client
        yield (MagicMock(), MagicMock(), MagicMock())

    class FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            seen["initialized"] = True

    import mcp.client.streamable_http as sh
    import mcp.shared._httpx_utils as hx

    monkeypatch.setattr(hx, "create_mcp_http_client", fake_create_client)
    monkeypatch.setattr(sh, "streamable_http_client", fake_transport)
    monkeypatch.setattr("temper_ai.tools.mcp_client.ClientSession", FakeSession)
    return seen


def _connect(config):
    async def run():
        manager = MCPClientManager()
        try:
            return await manager._connect_http(config)
        finally:
            await manager.stop()

    return asyncio.run(run())


def test_plain_http_server_gets_no_custom_client(captured):
    """No auth configured means the SDK's own default client, as before."""
    _connect({"name": "plain", "url": "https://example.com/mcp"})

    assert captured["url"] == "https://example.com/mcp"
    assert captured["http_client"] is None
    assert captured["initialized"] is True


def test_static_headers_reach_httpx(captured):
    _connect(
        {
            "name": "tokened",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer abc123"},
        }
    )

    assert captured["headers"] == {"Authorization": "Bearer abc123"}
    assert captured["auth"] is None
    assert captured["http_client"] is not None


def test_oauth_config_attaches_an_httpx_auth(captured, key):
    import httpx

    _connect(
        {
            "name": "notion",
            "url": "https://mcp.notion.com/mcp",
            "auth": "oauth",
        }
    )

    assert isinstance(captured["auth"], httpx.Auth)
    assert captured["http_client"] is not None


def test_oauth_provider_is_bound_to_the_configured_server(captured, key):
    _connect(
        {"name": "notion", "url": "https://mcp.notion.com/mcp", "auth": "oauth"}
    )

    storage = captured["auth"].context.storage
    assert storage.server_name == "notion"
    assert storage.server_url == "https://mcp.notion.com/mcp"


def test_custom_client_is_closed_with_the_manager(captured):
    """The SDK only closes a client it created, so ours must be on our stack."""

    async def run():
        manager = MCPClientManager()
        await manager._connect_http(
            {
                "name": "tokened",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer abc123"},
            }
        )
        client = captured["http_client"]
        client.__aexit__.assert_not_called()
        await manager.stop()
        client.__aexit__.assert_called_once()

    asyncio.run(run())
