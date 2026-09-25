"""Where MCP server configs are read from.

``configs/mcp_servers/local/`` has been gitignored for a long time, but
nothing read it, so a server that belongs to one machine had nowhere to
live except the tracked directory.
"""

import asyncio

from temper_ai.tools.mcp_client import MCPClientManager, _load_mcp_configs


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_local_configs_are_read_after_the_tracked_ones(tmp_path):
    _write(tmp_path / "mcp_servers" / "b.yaml", "mcp_server: {name: tracked_b, transport: http, url: http://b}\n")
    _write(tmp_path / "mcp_servers" / "a.yaml", "mcp_server: {name: tracked_a, transport: http, url: http://a}\n")
    _write(tmp_path / "mcp_servers" / "local" / "0.yaml", "mcp_server: {name: mine, transport: http, url: http://m}\n")

    names = [c["name"] for c in _load_mcp_configs(str(tmp_path))]

    assert names == ["tracked_a", "tracked_b", "mine"]


def test_a_local_config_gets_env_substitution_like_any_other(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_MCP_TOKEN", "s3cret")
    _write(
        tmp_path / "mcp_servers" / "local" / "chrome.yaml",
        "mcp_server:\n"
        "  name: chrome\n"
        "  transport: http\n"
        "  url: ${SOME_MCP_URL:http://172.21.0.1:8097/mcp}\n"
        "  headers:\n"
        "    Authorization: Bearer ${SOME_MCP_TOKEN}\n",
    )

    (config,) = _load_mcp_configs(str(tmp_path))

    assert config["url"] == "http://172.21.0.1:8097/mcp"
    assert config["headers"] == {"Authorization": "Bearer s3cret"}


def test_a_local_config_cannot_replace_a_tracked_server(tmp_path):
    _write(tmp_path / "mcp_servers" / "playwright.yaml",
           "mcp_server: {name: playwright, transport: http, url: http://tracked}\n")
    _write(tmp_path / "mcp_servers" / "local" / "playwright.yaml",
           "mcp_server: {name: playwright, transport: http, url: http://local}\n")

    manager = MCPClientManager()
    asyncio.run(manager.start(str(tmp_path)))

    assert manager._server_configs["playwright"]["url"] == "http://tracked"


def test_no_local_directory_is_fine(tmp_path):
    _write(tmp_path / "mcp_servers" / "a.yaml", "mcp_server: {name: a, transport: http, url: http://a}\n")

    assert [c["name"] for c in _load_mcp_configs(str(tmp_path))] == ["a"]
