"""`temper connect` / `connections` / `disconnect`.

These commands are the only interactive part of the integration story, so
the failure messages matter as much as the success path: a wrong server name
or an unauthorized server has to say what to run next.
"""

import asyncio
from argparse import Namespace

import pytest
from cryptography.fernet import Fernet

from temper_ai.cli import connect as cli_connect
from temper_ai.tools import mcp_auth
from temper_ai.tools.mcp_auth import DatabaseTokenStore

NOTION = {
    "name": "notion",
    "transport": "http",
    "url": "https://mcp.notion.com/mcp",
    "auth": "oauth",
}
PLAIN = {
    "name": "plain",
    "transport": "http",
    "url": "https://example.com/mcp",
}


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv(mcp_auth.SECRET_KEY_ENV_VAR, Fernet.generate_key().decode())


@pytest.fixture
def servers(monkeypatch):
    configured = {"notion": NOTION, "plain": PLAIN}
    monkeypatch.setattr(cli_connect, "_http_servers", lambda: dict(configured))
    return configured


def _token():
    from mcp.shared.auth import OAuthToken

    return OAuthToken(access_token="at-1", token_type="Bearer", refresh_token="rt-1")


def test_connect_unknown_server_lists_what_exists(servers, capsys):
    code = cli_connect.cmd_connect(Namespace(server="nope", port=8765))

    assert code == 1
    err = capsys.readouterr().err
    assert "No HTTP MCP server named 'nope'" in err
    assert "notion" in err and "plain" in err


def test_connect_non_oauth_server_explains_there_is_nothing_to_do(servers, capsys):
    code = cli_connect.cmd_connect(Namespace(server="plain", port=8765))

    assert code == 1
    assert "not configured for OAuth" in capsys.readouterr().err


def test_connect_reports_failure_without_a_traceback(servers, key, monkeypatch, capsys):
    async def boom(config, *, manual=False):
        raise mcp_auth.MCPAuthError("Timed out after 300s waiting for the redirect.")

    monkeypatch.setattr(cli_connect, "_run_login", boom)

    code = cli_connect.cmd_connect(Namespace(server="notion", port=8765, manual=False))

    assert code == 1
    assert "Timed out after 300s" in capsys.readouterr().err


def test_connect_stores_the_grant_and_confirms(servers, key, monkeypatch, capsys):
    async def fake_login(config, *, manual=False):
        # Stand in for the real flow: what it leaves behind is the grant.
        seen["manual"] = manual
        await DatabaseTokenStore(
            config["name"], server_url=config["url"]
        ).set_tokens(_token())

    seen: dict = {}
    monkeypatch.setattr(cli_connect, "_run_login", fake_login)

    code = cli_connect.cmd_connect(Namespace(server="notion", port=8765, manual=False))

    assert code == 0
    out = capsys.readouterr().out
    assert "Connected" in out
    assert "should not need to do this again" in out
    assert seen["manual"] is False
    assert DatabaseTokenStore("notion", server_url=NOTION["url"]).describe()["connected"]


def test_connect_manual_flag_reaches_the_flow(servers, key, monkeypatch, capsys):
    """--manual is the headless escape hatch; it must actually be plumbed."""
    seen: dict = {}

    async def fake_login(config, *, manual=False):
        seen["manual"] = manual
        await DatabaseTokenStore(
            config["name"], server_url=config["url"]
        ).set_tokens(_token())

    monkeypatch.setattr(cli_connect, "_run_login", fake_login)

    code = cli_connect.cmd_connect(Namespace(server="notion", port=8765, manual=True))

    assert code == 0
    assert seen["manual"] is True


def test_connections_shows_connected_and_unconnected(servers, key, capsys):
    cli_connect._init_db()
    asyncio.run(
        DatabaseTokenStore("notion", server_url=NOTION["url"]).set_tokens(_token())
    )

    code = cli_connect.cmd_connections(Namespace())

    assert code == 0
    out = capsys.readouterr().out
    assert "notion" in out and "connected" in out and "refreshable" in out
    assert "plain" in out and "no auth required" in out


def test_connections_tells_you_the_command_when_not_connected(servers, key, capsys):
    code = cli_connect.cmd_connections(Namespace())

    assert code == 0
    out = capsys.readouterr().out
    assert "not connected" in out
    assert "temper connect notion" in out


def test_connections_never_prints_a_token(servers, key, capsys):
    cli_connect._init_db()
    asyncio.run(
        DatabaseTokenStore("notion", server_url=NOTION["url"]).set_tokens(_token())
    )

    cli_connect.cmd_connections(Namespace())

    out = capsys.readouterr().out
    assert "at-1" not in out
    assert "rt-1" not in out


def test_disconnect_deletes_and_says_revocation_is_elsewhere(servers, key, capsys):
    cli_connect._init_db()
    asyncio.run(
        DatabaseTokenStore("notion", server_url=NOTION["url"]).set_tokens(_token())
    )

    code = cli_connect.cmd_disconnect(Namespace(server="notion"))

    assert code == 0
    out = capsys.readouterr().out
    assert "Disconnected" in out
    assert "does not revoke" in out
    assert not DatabaseTokenStore("notion", server_url=NOTION["url"]).describe()["connected"]


def test_disconnect_unconnected_server_is_not_an_error(servers, key, capsys):
    code = cli_connect.cmd_disconnect(Namespace(server="notion"))

    assert code == 0
    assert "was not connected" in capsys.readouterr().out
