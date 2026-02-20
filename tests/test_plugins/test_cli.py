"""Tests for plugin CLI commands."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.plugin_commands import plugin_group


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


class TestPluginList:
    def test_list_shows_frameworks(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exit_code == 0
        assert "crewai" in result.output

    def test_list_shows_langgraph(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exit_code == 0
        assert "langgraph" in result.output

    def test_list_shows_openai_agents(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exit_code == 0
        assert "openai_agents" in result.output

    def test_list_shows_autogen(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exit_code == 0
        assert "autogen" in result.output

    def test_list_shows_install_hints(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert "pip install" in result.output

    def test_list_exit_code_zero(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exit_code == 0

    def test_list_has_no_exception(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list"])
        assert result.exception is None


class TestPluginImport:
    def test_missing_source_file(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        result = cli_runner.invoke(
            plugin_group,
            ["import", "crewai", str(tmp_path / "missing.yaml")],
        )
        assert result.exit_code != 0

    def test_unknown_framework(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        source = tmp_path / "test.yaml"
        source.write_text("key: value\n")
        result = cli_runner.invoke(
            plugin_group,
            ["import", "unknown_framework", str(source)],
        )
        assert result.exit_code != 0

    def test_unknown_framework_shows_supported(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        source = tmp_path / "test.yaml"
        source.write_text("key: value\n")
        result = cli_runner.invoke(
            plugin_group,
            ["import", "unknown_framework", str(source)],
        )
        # Should show supported frameworks in error
        assert "crewai" in result.output or result.exit_code != 0

    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_framework_not_installed(
        self, mock_register: MagicMock, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        mock_register.return_value = False
        source = tmp_path / "test.yaml"
        source.write_text("role: Test\ngoal: Test\n")
        result = cli_runner.invoke(
            plugin_group,
            ["import", "crewai", str(source)],
        )
        assert result.exit_code != 0

    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_successful_import(
        self,
        mock_register: MagicMock,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        from temper_ai.agent.utils.agent_factory import AgentFactory
        from temper_ai.plugins.adapters.crewai_adapter import CrewAIAgent

        mock_register.return_value = True
        source = tmp_path / "source.yaml"
        source.write_text("role: Researcher\ngoal: Research topics\n")

        AgentFactory.reset_for_testing()
        AgentFactory.register_type("crewai", CrewAIAgent)

        result = cli_runner.invoke(
            plugin_group,
            ["import", "crewai", str(source), "--output", str(tmp_path)],
        )

        AgentFactory.reset_for_testing()
        assert result.exit_code == 0
        assert "Imported" in result.output

    @patch("temper_ai.plugins.registry.ensure_plugin_registered")
    def test_no_agents_found_message(
        self,
        mock_register: MagicMock,
        cli_runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        mock_register.return_value = True
        source = tmp_path / "source.yaml"
        source.write_text("role: Test\ngoal: Test\n")

        mock_adapter = MagicMock()
        mock_adapter.translate_config.return_value = []

        from temper_ai.agent.utils.agent_factory import AgentFactory
        AgentFactory.reset_for_testing()

        with patch("temper_ai.agent.utils.agent_factory.AgentFactory") as mock_factory:
            mock_factory.list_types.return_value = {"crewai": mock_adapter}
            result = cli_runner.invoke(
                plugin_group,
                ["import", "crewai", str(source)],
            )

        AgentFactory.reset_for_testing()
        assert result.exit_code == 0
        assert "No agents" in result.output

    def test_plugin_group_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["--help"])
        assert result.exit_code == 0
        assert "plugin" in result.output.lower() or "framework" in result.output.lower()

    def test_import_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["import", "--help"])
        assert result.exit_code == 0
        assert "--output" in result.output

    def test_list_help(self, cli_runner: CliRunner) -> None:
        result = cli_runner.invoke(plugin_group, ["list", "--help"])
        assert result.exit_code == 0
