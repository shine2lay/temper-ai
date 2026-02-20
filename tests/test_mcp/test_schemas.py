"""Tests for MCP configuration schemas."""
import pytest
from pydantic import ValidationError

from temper_ai.mcp._schemas import MCPServerConfig
from temper_ai.mcp.constants import MCP_DEFAULT_CALL_TIMEOUT, MCP_DEFAULT_CONNECT_TIMEOUT


class TestMCPServerConfig:
    """Tests for MCPServerConfig validation."""

    def test_stdio_transport_valid(self):
        cfg = MCPServerConfig(name="github", command="npx", args=["-y", "server-github"])
        assert cfg.name == "github"
        assert cfg.command == "npx"
        assert cfg.url is None
        assert cfg.args == ["-y", "server-github"]

    def test_http_transport_valid(self):
        cfg = MCPServerConfig(name="remote", url="http://localhost:3000/mcp")
        assert cfg.name == "remote"
        assert cfg.url == "http://localhost:3000/mcp"
        assert cfg.command is None

    def test_neither_transport_raises(self):
        with pytest.raises(ValidationError, match="Exactly one of"):
            MCPServerConfig(name="bad")

    def test_both_transports_raises(self):
        with pytest.raises(ValidationError, match="Exactly one of"):
            MCPServerConfig(name="bad", command="npx", url="http://x")

    def test_namespace_defaults_to_name(self):
        cfg = MCPServerConfig(name="github", command="npx")
        assert cfg.effective_namespace == "github"

    def test_namespace_override(self):
        cfg = MCPServerConfig(name="github", namespace="gh", command="npx")
        assert cfg.effective_namespace == "gh"

    def test_default_timeouts(self):
        cfg = MCPServerConfig(name="s", command="x")
        assert cfg.connect_timeout == MCP_DEFAULT_CONNECT_TIMEOUT
        assert cfg.call_timeout == MCP_DEFAULT_CALL_TIMEOUT

    def test_custom_timeouts(self):
        cfg = MCPServerConfig(name="s", command="x", connect_timeout=5, call_timeout=60)
        assert cfg.connect_timeout == 5
        assert cfg.call_timeout == 60

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(name="s", command="x", connect_timeout=0)

    def test_env_dict(self):
        cfg = MCPServerConfig(
            name="gh", command="npx", env={"GITHUB_TOKEN": "tok123"}
        )
        assert cfg.env == {"GITHUB_TOKEN": "tok123"}

    def test_from_dict(self):
        """Verify dict round-trip for lazy validation in agent_config."""
        data = {
            "name": "fs",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
        }
        cfg = MCPServerConfig(**data)
        assert cfg.name == "fs"
        assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem"]
