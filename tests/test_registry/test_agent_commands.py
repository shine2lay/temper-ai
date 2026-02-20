"""Tests for CLI commands in temper_ai.interfaces.cli.agent_commands."""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.agent_commands import agent_group
from temper_ai.interfaces.cli.agent_constants import (
    MSG_NOT_FOUND,
    MSG_REGISTERED,
    MSG_UNREGISTERED,
    TABLE_TITLE_AGENTS,
    TABLE_TITLE_STATUS,
)
from temper_ai.registry._schemas import AgentRegistryEntry, MessageResponse


def _make_entry(**kwargs) -> AgentRegistryEntry:
    """Build a minimal AgentRegistryEntry for testing."""
    from datetime import datetime, timezone

    defaults = dict(
        id="abc123",
        name="test-agent",
        agent_type="standard",
        version="1.0",
        status="registered",
        memory_namespace="agent__test-agent",
        total_invocations=0,
        registered_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_active_at=None,
    )
    defaults.update(kwargs)
    return AgentRegistryEntry(**defaults)


def _write_agent_yaml(data: dict) -> str:
    """Write YAML agent config to temp file, return path."""
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(data, fh)
    fh.close()
    return fh.name


_MOCK_SERVICE_PATH = "temper_ai.interfaces.cli.agent_commands._get_service"


class TestAgentListCommand:
    def test_list_empty(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = []
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["list"])
        assert result.exit_code == 0
        assert TABLE_TITLE_AGENTS in result.output

    def test_list_with_agents(self):
        runner = CliRunner()
        entry = _make_entry(name="my-bot")
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = [entry]
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["list"])
        assert result.exit_code == 0
        assert "my-bot" in result.output

    def test_list_with_status_filter(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.list_agents.return_value = []
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["list", "--status", "active"])
        assert result.exit_code == 0
        mock_svc.list_agents.assert_called_once_with(status="active")


class TestAgentRegisterCommand:
    def test_register_success(self):
        runner = CliRunner()
        path = _write_agent_yaml({"name": "my-agent", "type": "standard"})
        entry = _make_entry(name="my-agent")
        mock_svc = MagicMock()
        mock_svc.register_agent.return_value = entry
        try:
            with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
                result = runner.invoke(agent_group, ["register", path])
            assert result.exit_code == 0
            assert "my-agent" in result.output
        finally:
            os.unlink(path)

    def test_register_failure_raises_exit(self):
        runner = CliRunner()
        path = _write_agent_yaml({"name": "bad-agent"})
        mock_svc = MagicMock()
        mock_svc.register_agent.side_effect = ValueError("missing field")
        try:
            with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
                result = runner.invoke(agent_group, ["register", path])
            assert result.exit_code != 0
            assert "Registration failed" in result.output
        finally:
            os.unlink(path)

    def test_register_invalid_metadata_json(self):
        runner = CliRunner()
        path = _write_agent_yaml({"name": "meta-agent"})
        try:
            with patch(_MOCK_SERVICE_PATH, return_value=MagicMock()):
                result = runner.invoke(
                    agent_group, ["register", path, "--metadata", "not-json"]
                )
            assert result.exit_code != 0
            assert "Invalid JSON" in result.output
        finally:
            os.unlink(path)

    def test_register_with_valid_metadata(self):
        runner = CliRunner()
        path = _write_agent_yaml({"name": "meta-agent"})
        entry = _make_entry(name="meta-agent")
        mock_svc = MagicMock()
        mock_svc.register_agent.return_value = entry
        try:
            with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
                result = runner.invoke(
                    agent_group,
                    ["register", path, "--metadata", '{"env": "prod"}'],
                )
            assert result.exit_code == 0
            mock_svc.register_agent.assert_called_once_with(path, metadata={"env": "prod"})
        finally:
            os.unlink(path)


class TestAgentUnregisterCommand:
    def test_unregister_success(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = True
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["unregister", "my-agent"])
        assert result.exit_code == 0
        assert "my-agent" in result.output

    def test_unregister_not_found(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.unregister_agent.return_value = False
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["unregister", "ghost"])
        assert result.exit_code != 0
        assert "ghost" in result.output


class TestAgentStatusCommand:
    def test_status_found(self):
        runner = CliRunner()
        entry = _make_entry(name="status-agent")
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = entry
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["status", "status-agent"])
        assert result.exit_code == 0
        assert TABLE_TITLE_STATUS in result.output
        assert "status-agent" in result.output

    def test_status_not_found(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["status", "nobody"])
        assert result.exit_code != 0
        assert "nobody" in result.output


class TestAgentChatCommand:
    def test_chat_agent_not_found(self):
        runner = CliRunner()
        mock_svc = MagicMock()
        mock_svc.get_agent.return_value = None
        with patch(_MOCK_SERVICE_PATH, return_value=mock_svc):
            result = runner.invoke(agent_group, ["chat", "ghost"])
        assert result.exit_code != 0
        assert "ghost" in result.output
