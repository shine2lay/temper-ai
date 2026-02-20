"""Tests for interactive chat mode CLI commands (R0.4)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from temper_ai.interfaces.cli.chat_commands import (
    _handle_special_command,
    _load_agent,
    _run_chat_loop,
    chat,
)
from temper_ai.interfaces.cli.chat_constants import (
    CHAT_CLEAR_COMMAND,
    CHAT_EXIT_COMMANDS,
    CHAT_HELP_COMMANDS,
    CHAT_PROMPT_MARKER,
    CHAT_WELCOME_MESSAGE,
    MAX_CHAT_HISTORY_TURNS,
)


# ─── _handle_special_command tests ────────────────────────────────────


class TestHandleSpecialCommand:
    """Tests for _handle_special_command."""

    def test_exit_commands(self) -> None:
        for cmd in CHAT_EXIT_COMMANDS:
            assert _handle_special_command(cmd) == "exit"

    def test_exit_with_whitespace(self) -> None:
        assert _handle_special_command("  exit  ") == "exit"

    def test_help_commands(self) -> None:
        for cmd in CHAT_HELP_COMMANDS:
            assert _handle_special_command(cmd) == "help"

    def test_clear_command(self) -> None:
        assert _handle_special_command(CHAT_CLEAR_COMMAND) == "clear"

    def test_normal_input_returns_none(self) -> None:
        assert _handle_special_command("hello world") is None

    def test_empty_input_returns_none(self) -> None:
        assert _handle_special_command("") is None

    def test_case_insensitive(self) -> None:
        assert _handle_special_command("EXIT") == "exit"
        assert _handle_special_command("HELP") == "help"

    def test_partial_match_returns_none(self) -> None:
        assert _handle_special_command("exiting") is None
        assert _handle_special_command("helper") is None


# ─── _load_agent tests ────────────────────────────────────────────────


class TestLoadAgent:
    """Tests for _load_agent."""

    @patch("temper_ai.agent.utils.agent_factory.AgentFactory.create")
    @patch("temper_ai.storage.schemas.agent_config.AgentConfig")
    def test_load_agent_success(
        self, mock_config_cls: MagicMock, mock_create: MagicMock, tmp_path
    ) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("agent:\n  name: test\n  type: standard\n")

        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        result = _load_agent(str(config_file))
        assert result == mock_agent

    def test_load_agent_missing_file(self) -> None:
        with pytest.raises(SystemExit):
            _load_agent("/nonexistent/path/agent.yaml")

    def test_load_agent_empty_config(self, tmp_path) -> None:
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        with pytest.raises(SystemExit):
            _load_agent(str(config_file))


# ─── _run_chat_loop tests ────────────────────────────────────────────


class TestRunChatLoop:
    """Tests for _run_chat_loop."""

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_exit_terminates_loop(self, mock_console: MagicMock) -> None:
        mock_console.input.return_value = "exit"
        agent = MagicMock()
        _run_chat_loop(agent)
        agent.execute.assert_not_called()

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_keyboard_interrupt(self, mock_console: MagicMock) -> None:
        mock_console.input.side_effect = KeyboardInterrupt()
        agent = MagicMock()
        _run_chat_loop(agent)
        agent.execute.assert_not_called()

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_eof_terminates(self, mock_console: MagicMock) -> None:
        mock_console.input.side_effect = EOFError()
        agent = MagicMock()
        _run_chat_loop(agent)
        agent.execute.assert_not_called()

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_normal_input_calls_agent(self, mock_console: MagicMock) -> None:
        mock_console.input.side_effect = ["hello", "exit"]
        agent = MagicMock()
        response = MagicMock()
        response.output = "Hi there!"
        agent.execute.return_value = response

        _run_chat_loop(agent)

        agent.execute.assert_called_once_with({"task": "hello"})

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_empty_input_skipped(self, mock_console: MagicMock) -> None:
        mock_console.input.side_effect = ["", "   ", "exit"]
        agent = MagicMock()
        _run_chat_loop(agent)
        agent.execute.assert_not_called()

    @patch("temper_ai.interfaces.cli.chat_commands.console")
    def test_help_command_prints_help(self, mock_console: MagicMock) -> None:
        mock_console.input.side_effect = ["help", "exit"]
        agent = MagicMock()
        _run_chat_loop(agent)
        agent.execute.assert_not_called()
        # Help text should be printed containing command instructions
        printed_args = [str(c) for c in mock_console.print.call_args_list]
        all_printed = " ".join(printed_args)
        assert "exit" in all_printed or "help" in all_printed


# ─── Click command tests ─────────────────────────────────────────────


class TestChatCommand:
    """Tests for chat Click command."""

    def test_chat_missing_config(self) -> None:
        runner = CliRunner()
        result = runner.invoke(chat, ["/nonexistent/agent.yaml"])
        assert result.exit_code != 0

    @patch("temper_ai.interfaces.cli.chat_commands._run_chat_loop")
    @patch("temper_ai.interfaces.cli.chat_commands._load_agent")
    def test_chat_command_invokes_loop(
        self, mock_load: MagicMock, mock_loop: MagicMock, tmp_path
    ) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("agent:\n  name: test\n")

        mock_agent = MagicMock()
        mock_load.return_value = mock_agent

        runner = CliRunner()
        result = runner.invoke(chat, [str(config_file)])

        assert result.exit_code == 0
        mock_load.assert_called_once_with(str(config_file))
        mock_loop.assert_called_once_with(mock_agent)


# ─── Constants tests ─────────────────────────────────────────────────


class TestChatConstants:
    """Tests for chat constants consistency."""

    def test_exit_commands_are_frozenset(self) -> None:
        assert isinstance(CHAT_EXIT_COMMANDS, frozenset)

    def test_help_commands_are_frozenset(self) -> None:
        assert isinstance(CHAT_HELP_COMMANDS, frozenset)

    def test_max_history_is_positive(self) -> None:
        assert MAX_CHAT_HISTORY_TURNS > 0

    def test_welcome_message_has_placeholder(self) -> None:
        assert "{agent_name}" in CHAT_WELCOME_MESSAGE
