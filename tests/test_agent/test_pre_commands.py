"""Tests for pre_commands feature: schema, execution, formatting, integration."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.utils._pre_command_helpers import (
    _render_command,
    _truncate,
    execute_pre_commands,
    format_pre_command_results,
)
from temper_ai.agent.utils.constants import PRE_COMMAND_MAX_OUTPUT_CHARS
from temper_ai.storage.schemas.agent_config import AgentConfig, PreCommand
from temper_ai.tools.field_names import ToolResultFields


# ============================================================================
# Schema tests
# ============================================================================


class TestPreCommandSchema:
    """Validate PreCommand pydantic model."""

    def test_valid_pre_command(self) -> None:
        cmd = PreCommand(name="check", command="echo hello")
        assert cmd.name == "check"
        assert cmd.command == "echo hello"
        assert cmd.timeout_seconds == 60

    def test_custom_timeout(self) -> None:
        cmd = PreCommand(name="slow", command="sleep 10", timeout_seconds=120)
        assert cmd.timeout_seconds == 120

    def test_timeout_exceeds_max(self) -> None:
        with pytest.raises(Exception):
            PreCommand(name="too_slow", command="sleep 999", timeout_seconds=999)

    def test_timeout_zero_rejected(self) -> None:
        with pytest.raises(Exception):
            PreCommand(name="zero", command="echo", timeout_seconds=0)

    def test_agent_config_with_pre_commands(self) -> None:
        """AgentConfigInner accepts pre_commands list."""
        cfg = AgentConfig(
            agent={
                "name": "test",
                "description": "test agent",
                "prompt": {"inline": "hello"},
                "inference": {
                    "provider": "ollama",
                    "model": "test",
                },
                "pre_commands": [
                    {"name": "check", "command": "echo ok"},
                    {"name": "slow", "command": "sleep 1", "timeout_seconds": 30},
                ],
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 1,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        )
        assert cfg.agent.pre_commands is not None
        assert len(cfg.agent.pre_commands) == 2
        assert cfg.agent.pre_commands[0].name == "check"

    def test_agent_config_without_pre_commands(self) -> None:
        """pre_commands defaults to None when omitted."""
        cfg = AgentConfig(
            agent={
                "name": "test",
                "description": "test agent",
                "prompt": {"inline": "hello"},
                "inference": {
                    "provider": "ollama",
                    "model": "test",
                },
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "max_retries": 1,
                    "fallback": "GracefulDegradation",
                    "escalate_to_human_after": 3,
                },
            }
        )
        assert cfg.agent.pre_commands is None


# ============================================================================
# Template rendering tests
# ============================================================================


class TestRenderCommand:
    """Test {{ var }} substitution in command strings."""

    def test_simple_substitution(self) -> None:
        result = _render_command("cd {{ workspace_path }} && ls", {"workspace_path": "/tmp/ws"})
        assert result == "cd /tmp/ws && ls"

    def test_multiple_vars(self) -> None:
        result = _render_command(
            "{{ cmd }} {{ arg }}",
            {"cmd": "echo", "arg": "hello"},
        )
        assert result == "echo hello"

    def test_missing_var_left_as_is(self) -> None:
        result = _render_command("echo {{ missing }}", {})
        assert "{{ missing }}" in result

    def test_no_vars(self) -> None:
        result = _render_command("echo hello", {"workspace_path": "/tmp"})
        assert result == "echo hello"


# ============================================================================
# Truncation tests
# ============================================================================


class TestTruncate:
    """Test output truncation."""

    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self) -> None:
        long_text = "x" * 3000
        result = _truncate(long_text)
        assert len(result) < len(long_text)
        assert "truncated" in result

    def test_custom_limit(self) -> None:
        result = _truncate("hello world", max_chars=5)
        assert result.startswith("hello")
        assert "truncated" in result


# ============================================================================
# Format results tests
# ============================================================================


class TestFormatPreCommandResults:
    """Test markdown formatting of results."""

    def test_pass_result(self) -> None:
        results = [{
            "name": "check_syntax",
            ToolResultFields.EXIT_CODE: 0,
            ToolResultFields.STDOUT: "OK",
            ToolResultFields.STDERR: "",
            ToolResultFields.ERROR: None,
        }]
        output = format_pre_command_results(results)
        assert "PASS" in output
        assert "check_syntax" in output
        assert "OK" in output

    def test_fail_result(self) -> None:
        results = [{
            "name": "import_test",
            ToolResultFields.EXIT_CODE: 1,
            ToolResultFields.STDOUT: "",
            ToolResultFields.STDERR: "ModuleNotFoundError: No module named 'foo'",
            ToolResultFields.ERROR: None,
        }]
        output = format_pre_command_results(results)
        assert "FAIL" in output
        assert "import_test" in output
        assert "ModuleNotFoundError" in output

    def test_error_result(self) -> None:
        results = [{
            "name": "timeout_cmd",
            ToolResultFields.EXIT_CODE: -1,
            ToolResultFields.STDOUT: "",
            ToolResultFields.STDERR: "",
            ToolResultFields.ERROR: "Timed out after 30s",
        }]
        output = format_pre_command_results(results)
        assert "FAIL" in output
        assert "Timed out" in output

    def test_multiple_results(self) -> None:
        results = [
            {"name": "a", ToolResultFields.EXIT_CODE: 0, ToolResultFields.STDOUT: "ok", ToolResultFields.STDERR: "", ToolResultFields.ERROR: None},
            {"name": "b", ToolResultFields.EXIT_CODE: 1, ToolResultFields.STDOUT: "", ToolResultFields.STDERR: "err", ToolResultFields.ERROR: None},
        ]
        output = format_pre_command_results(results)
        assert output.count("##") == 2


# ============================================================================
# execute_pre_commands tests
# ============================================================================


class TestExecutePreCommands:
    """Test execute_pre_commands with mock subprocess."""

    def _make_agent(self, pre_commands=None):
        """Create a mock agent with pre_commands config."""
        agent = MagicMock()
        agent.name = "test_agent"
        agent.config.agent.pre_commands = pre_commands
        agent._observer = MagicMock()
        return agent

    def test_no_pre_commands_returns_none(self) -> None:
        agent = self._make_agent(pre_commands=None)
        result = execute_pre_commands(agent, {})
        assert result is None

    def test_empty_pre_commands_returns_none(self) -> None:
        agent = self._make_agent(pre_commands=[])
        result = execute_pre_commands(agent, {})
        assert result is None

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_successful_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="all good", stderr=""
        )
        cmd = MagicMock(name="check", command="echo ok", timeout_seconds=30)
        cmd.name = "check"
        cmd.command = "echo ok"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        result = execute_pre_commands(agent, {})

        assert result is not None
        assert "PASS" in result
        assert "all good" in result

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_failed_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="ImportError: bad"
        )
        cmd = MagicMock()
        cmd.name = "import_check"
        cmd.command = "python3 -c 'import bad'"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        result = execute_pre_commands(agent, {})

        assert result is not None
        assert "FAIL" in result
        assert "ImportError" in result

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_timeout_command(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep 999", timeout=30)

        cmd = MagicMock()
        cmd.name = "slow"
        cmd.command = "sleep 999"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        result = execute_pre_commands(agent, {})

        assert result is not None
        assert "FAIL" in result
        assert "Timed out" in result

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_os_error_command(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("No such file or directory")

        cmd = MagicMock()
        cmd.name = "missing"
        cmd.command = "/nonexistent/cmd"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        result = execute_pre_commands(agent, {})

        assert result is not None
        assert "FAIL" in result

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_template_substitution(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        cmd = MagicMock()
        cmd.name = "check"
        cmd.command = "cd {{ workspace_path }} && echo ok"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        execute_pre_commands(agent, {"workspace_path": "/tmp/test"})

        called_cmd = mock_run.call_args[0][0]
        assert "/tmp/test" in called_cmd
        assert "{{ workspace_path }}" not in called_cmd

    @patch("temper_ai.agent.utils._pre_command_helpers.subprocess.run")
    def test_observer_tracking(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        cmd = MagicMock()
        cmd.name = "mycheck"
        cmd.command = "echo ok"
        cmd.timeout_seconds = 30

        agent = self._make_agent(pre_commands=[cmd])
        execute_pre_commands(agent, {})

        agent._observer.track_tool_call.assert_called_once()
        call_kwargs = agent._observer.track_tool_call.call_args[1]
        assert call_kwargs["tool_name"] == "pre_command:mycheck"
        assert call_kwargs["status"] == "success"


# ============================================================================
# Config loading test
# ============================================================================


class TestConfigLoading:
    """Test loading VCS static checker YAML config."""

    def test_load_vcs_static_checker(self) -> None:
        import yaml

        with open("configs/agents/vcs_static_checker.yaml") as f:
            data = yaml.safe_load(f)

        cfg = AgentConfig(**data)
        assert cfg.agent.name == "vcs_static_checker"
        assert cfg.agent.type == "static_checker"
        assert cfg.agent.pre_commands is not None
        assert len(cfg.agent.pre_commands) == 3
        assert cfg.agent.pre_commands[0].name == "py_compile_all"
        assert cfg.agent.pre_commands[1].name == "ruff_lint"
        assert cfg.agent.tools is None  # static_checker has no tools key
        assert cfg.agent.inference.temperature == 0.1

    def test_pre_command_names_unique(self) -> None:
        import yaml

        with open("configs/agents/vcs_static_checker.yaml") as f:
            data = yaml.safe_load(f)

        cfg = AgentConfig(**data)
        names = [cmd.name for cmd in cfg.agent.pre_commands]
        assert len(names) == len(set(names)), f"Duplicate pre_command names: {names}"


# ============================================================================
# Re-export test
# ============================================================================


class TestReExport:
    """Test PreCommand is re-exported from compiler/schemas."""

    def test_pre_command_importable_from_compiler_schemas(self) -> None:
        from temper_ai.storage.schemas.agent_config import PreCommand as ReExportedPreCommand

        assert ReExportedPreCommand is PreCommand
