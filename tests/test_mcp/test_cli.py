"""Tests for MCP CLI commands."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.mcp_commands import mcp_group


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def agent_config_no_mcp(tmp_path: Path) -> str:
    """Agent YAML without mcp_servers."""
    p = tmp_path / "agent.yaml"
    p.write_text("agent:\n  name: basic\n  type: standard\n")
    return str(p)


@pytest.fixture()
def agent_config_with_mcp(tmp_path: Path) -> str:
    """Agent YAML with mcp_servers."""
    cfg = {
        "agent": {
            "name": "mcp_agent",
            "mcp_servers": [
                {"name": "fs", "command": "npx", "args": ["-y", "server-fs"]}
            ],
        }
    }
    p = tmp_path / "agent_mcp.yaml"
    p.write_text(yaml.dump(cfg))
    return str(p)


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


class TestHelpText:
    def test_mcp_serve_help(self, runner: CliRunner):
        result = runner.invoke(mcp_group, ["serve", "--help"])
        assert result.exit_code == 0
        assert "MCP transport protocol" in result.output

    def test_mcp_list_tools_help(self, runner: CliRunner):
        result = runner.invoke(mcp_group, ["list-tools", "--help"])
        assert result.exit_code == 0
        assert "mcp_servers" in result.output


# ---------------------------------------------------------------------------
# mcp serve
# ---------------------------------------------------------------------------


class TestMcpServe:
    def test_serve_stdio_calls_run(self, runner: CliRunner):
        mock_server = MagicMock()
        mock_create = MagicMock(return_value=mock_server)

        with patch("temper_ai.interfaces.cli.mcp_commands.Console"):
            with patch(
                "temper_ai.interfaces.cli.mcp_commands.mcp_serve.__wrapped__",
                create=True,
            ):
                pass

        with patch(
            "temper_ai.interfaces.cli.mcp_commands.Console"
        ) as mock_console_cls:
            mock_console_cls.return_value = MagicMock()
            with patch(
                "temper_ai.mcp.server.create_mcp_server", mock_create
            ):
                result = runner.invoke(
                    mcp_group,
                    ["serve", "--transport", "stdio", "--config-root", "configs"],
                )

        mock_server.run.assert_called_once_with(transport="stdio")
        assert result.exit_code == 0

    def test_serve_http_calls_run_with_port(self, runner: CliRunner):
        mock_server = MagicMock()
        mock_create = MagicMock(return_value=mock_server)

        with patch("temper_ai.mcp.server.create_mcp_server", mock_create):
            result = runner.invoke(
                mcp_group,
                ["serve", "--transport", "http", "--port", "9999"],
            )

        mock_server.run.assert_called_once_with(transport="streamable-http", port=9999)
        assert result.exit_code == 0

    def test_serve_import_error_exits_1(self, runner: CliRunner):
        import builtins

        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "temper_ai.mcp.server":
                raise ImportError("mcp not installed")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_mock_import):
            result = runner.invoke(mcp_group, ["serve"])

        assert result.exit_code != 0
        assert "mcp" in result.output.lower()


# ---------------------------------------------------------------------------
# mcp list-tools
# ---------------------------------------------------------------------------


class TestMcpListTools:
    def test_no_mcp_servers_warns(self, runner: CliRunner, agent_config_no_mcp: str):
        result = runner.invoke(mcp_group, ["list-tools", "--config", agent_config_no_mcp])
        assert result.exit_code == 0
        assert "No mcp_servers" in result.output

    def test_with_mcp_servers_shows_table(
        self, runner: CliRunner, agent_config_with_mcp: str
    ):
        mock_tool = MagicMock()
        mock_meta = MagicMock()
        mock_meta.name = "fs__read_file"
        mock_meta.description = "Read a file"
        mock_meta.modifies_state = False
        mock_tool.get_metadata.return_value = mock_meta

        mock_manager = MagicMock()
        mock_manager.__enter__ = MagicMock(return_value=mock_manager)
        mock_manager.__exit__ = MagicMock(return_value=False)
        mock_manager.connect_all.return_value = [mock_tool]

        with patch("temper_ai.mcp.manager.MCPManager", return_value=mock_manager):
            result = runner.invoke(
                mcp_group, ["list-tools", "--config", agent_config_with_mcp]
            )

        assert result.exit_code == 0
        assert "1 tools" in result.output

    def test_connection_error_exits_1(
        self, runner: CliRunner, agent_config_with_mcp: str
    ):
        mock_manager = MagicMock()
        mock_manager.__enter__ = MagicMock(return_value=mock_manager)
        mock_manager.__exit__ = MagicMock(return_value=False)
        mock_manager.connect_all.side_effect = ConnectionError("refused")

        with patch("temper_ai.mcp.manager.MCPManager", return_value=mock_manager):
            result = runner.invoke(
                mcp_group, ["list-tools", "--config", agent_config_with_mcp]
            )

        assert result.exit_code == 1
        assert "Error connecting" in result.output
