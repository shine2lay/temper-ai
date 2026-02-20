"""Tests for CrewAI adapter."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.adapters.crewai_adapter import (
    CREWAI_DEFAULT_DELEGATION,
    CREWAI_DEFAULT_VERBOSE,
    CrewAIAgent,
)
from temper_ai.plugins.constants import PLUGIN_TYPE_CREWAI


def _inject_mock_crewai() -> MagicMock:
    """Inject a mock crewai module into sys.modules and return it."""
    mock_crewai = MagicMock()
    mock_crewai.Crew.return_value.kickoff.return_value = "mock result"
    sys.modules["crewai"] = mock_crewai
    return mock_crewai


def _remove_mock_crewai() -> None:
    """Remove mock crewai from sys.modules."""
    sys.modules.pop("crewai", None)


class TestCrewAIAgentInit:
    def test_class_vars(self) -> None:
        assert CrewAIAgent.FRAMEWORK_NAME == "CrewAI"
        assert CrewAIAgent.AGENT_TYPE == PLUGIN_TYPE_CREWAI
        assert CrewAIAgent.REQUIRED_PACKAGE == "crewai"

    def test_instantiation(self, mock_agent_config: MagicMock) -> None:
        agent = CrewAIAgent(mock_agent_config)
        assert agent.name == "test-agent"
        assert agent._initialized is False

    def test_external_agent_starts_none(self, mock_agent_config: MagicMock) -> None:
        agent = CrewAIAgent(mock_agent_config)
        assert agent._external_agent is None

    def test_default_verbose_constant(self) -> None:
        assert CREWAI_DEFAULT_VERBOSE is False

    def test_default_delegation_constant(self) -> None:
        assert CREWAI_DEFAULT_DELEGATION is False


class TestCrewAIInitializeExternal:
    def test_creates_crewai_agent(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._initialize_external_agent()
            mock_crewai.Agent.assert_called_once()
            call_kwargs = mock_crewai.Agent.call_args[1]
            assert call_kwargs["role"] == "Researcher"
            assert call_kwargs["goal"] == "Research things"
        finally:
            _remove_mock_crewai()

    def test_uses_agent_name_as_fallback_role(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.plugin_config = {
            "framework": "crewai",
            "goal": "G",
            "backstory": "",
        }
        mock_crewai = _inject_mock_crewai()
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._initialize_external_agent()
            call_kwargs = mock_crewai.Agent.call_args[1]
            assert call_kwargs["role"] == "test-agent"
        finally:
            _remove_mock_crewai()

    def test_import_error_without_crewai(self, mock_agent_config: MagicMock) -> None:
        _remove_mock_crewai()
        agent = CrewAIAgent(mock_agent_config)
        with pytest.raises(ImportError):
            agent._initialize_external_agent()

    def test_backstory_passed(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._initialize_external_agent()
            call_kwargs = mock_crewai.Agent.call_args[1]
            assert call_kwargs["backstory"] == "Expert researcher"
        finally:
            _remove_mock_crewai()


class TestCrewAIExecuteExternal:
    def test_execute_returns_string(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        mock_crewai.Crew.return_value.kickoff.return_value = "result text"
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._external_agent = MagicMock()
            result = agent._execute_external({"query": "test query"})
            assert result == "result text"
            mock_crewai.Crew.assert_called_once()
            mock_crewai.Task.assert_called_once()
        finally:
            _remove_mock_crewai()

    def test_run_returns_agent_response(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        mock_crewai.Crew.return_value.kickoff.return_value = "output"
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._external_agent = MagicMock()
            agent._initialized = True
            response = agent._run({"query": "test"}, None, 0.0)
            assert isinstance(response, AgentResponse)
            assert response.output == "output"
            assert response.metadata["framework"] == "CrewAI"
        finally:
            _remove_mock_crewai()

    def test_task_uses_extracted_description(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._external_agent = MagicMock()
            agent._execute_external({"query": "my specific query"})
            call_kwargs = mock_crewai.Task.call_args[1]
            assert call_kwargs["description"] == "my specific query"
        finally:
            _remove_mock_crewai()

    def test_crew_receives_external_agent(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        try:
            agent = CrewAIAgent(mock_agent_config)
            ext = MagicMock()
            agent._external_agent = ext
            agent._execute_external({"task": "do this"})
            call_kwargs = mock_crewai.Crew.call_args[1]
            assert ext in call_kwargs["agents"]
        finally:
            _remove_mock_crewai()

    def test_result_cast_to_str(self, mock_agent_config: MagicMock) -> None:
        mock_crewai = _inject_mock_crewai()
        mock_crewai.Crew.return_value.kickoff.return_value = 42
        try:
            agent = CrewAIAgent(mock_agent_config)
            agent._external_agent = MagicMock()
            result = agent._execute_external({"query": "test"})
            assert isinstance(result, str)
            assert result == "42"
        finally:
            _remove_mock_crewai()


class TestCrewAITranslateConfig:
    def test_single_agent_yaml(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        data = {
            "role": "Researcher",
            "goal": "Research topics",
            "backstory": "Expert",
        }
        source.write_text(yaml.dump(data))

        configs = CrewAIAgent.translate_config(source)
        assert len(configs) == 1
        assert configs[0]["agent"]["type"] == PLUGIN_TYPE_CREWAI
        assert configs[0]["agent"]["plugin_config"]["role"] == "Researcher"

    def test_multi_agent_yaml(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        data = {
            "agents": [
                {"role": "Researcher", "goal": "Research"},
                {"role": "Writer", "goal": "Write"},
            ],
        }
        source.write_text(yaml.dump(data))

        configs = CrewAIAgent.translate_config(source)
        assert len(configs) == 2

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            CrewAIAgent.translate_config(tmp_path / "missing.yaml")

    def test_config_has_plugin_config(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        source.write_text(yaml.dump({"role": "R", "goal": "G"}))
        configs = CrewAIAgent.translate_config(source)
        assert "plugin_config" in configs[0]["agent"]

    def test_plugin_config_has_framework(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        source.write_text(yaml.dump({"role": "R", "goal": "G"}))
        configs = CrewAIAgent.translate_config(source)
        assert configs[0]["agent"]["plugin_config"]["framework"] == PLUGIN_TYPE_CREWAI

    def test_empty_agents_list(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        source.write_text(yaml.dump({"agents": []}))
        configs = CrewAIAgent.translate_config(source)
        assert configs == []

    def test_no_role_field_in_root(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        source.write_text(yaml.dump({"name": "crew", "agents": []}))
        configs = CrewAIAgent.translate_config(source)
        assert configs == []

    def test_goal_used_as_description(self, tmp_path: Path) -> None:
        source = tmp_path / "crew.yaml"
        source.write_text(yaml.dump({"role": "R", "goal": "Do research"}))
        configs = CrewAIAgent.translate_config(source)
        assert configs[0]["agent"]["description"] == "Do research"


class TestCrewAIAgentFactory:
    """Test that AgentFactory can route to CrewAI via plugin registry."""

    def test_factory_create_crewai(self) -> None:
        from temper_ai.agent.utils.agent_factory import AgentFactory
        AgentFactory.reset_for_testing()

        # Register CrewAIAgent directly — avoids needing crewai installed
        AgentFactory.register_type(PLUGIN_TYPE_CREWAI, CrewAIAgent)

        mock_config = MagicMock()
        mock_config.agent.type = PLUGIN_TYPE_CREWAI
        mock_config.agent.name = "test"
        mock_config.agent.description = "test"
        mock_config.agent.version = "1.0"
        mock_config.agent.plugin_config = {"framework": "crewai", "role": "R", "goal": "G"}

        agent = AgentFactory.create(mock_config)
        assert isinstance(agent, CrewAIAgent)
        AgentFactory.reset_for_testing()
