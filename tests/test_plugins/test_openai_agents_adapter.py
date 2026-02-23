"""Tests for OpenAI Agents SDK adapter."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest
import yaml

from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.adapters.openai_agents_adapter import (
    DEFAULT_MODEL,
    OpenAIAgentsAgent,
)
from temper_ai.plugins.constants import PLUGIN_TYPE_OPENAI_AGENTS


@pytest.fixture()
def openai_agents_config() -> MagicMock:
    config = MagicMock()
    config.agent.name = "oai-agent"
    config.agent.description = "OpenAI test agent"
    config.agent.version = "1.0"
    config.agent.type = PLUGIN_TYPE_OPENAI_AGENTS
    config.agent.plugin_config = {
        "framework": PLUGIN_TYPE_OPENAI_AGENTS,
        "instructions": "Be helpful",
        "model": "gpt-4o",
    }
    return config


class TestOpenAIAgentsAgentInit:
    def test_class_vars(self) -> None:
        assert OpenAIAgentsAgent.FRAMEWORK_NAME == "OpenAI Agents SDK"
        assert OpenAIAgentsAgent.AGENT_TYPE == PLUGIN_TYPE_OPENAI_AGENTS
        assert OpenAIAgentsAgent.REQUIRED_PACKAGE == "openai-agents"

    def test_instantiation(self, openai_agents_config: MagicMock) -> None:
        agent = OpenAIAgentsAgent(openai_agents_config)
        assert agent.name == "oai-agent"
        assert agent._initialized is False

    def test_default_model_constant(self) -> None:
        assert DEFAULT_MODEL == "gpt-4o"


class TestOpenAIAgentsInitializeExternal:
    def test_creates_agent(self, openai_agents_config: MagicMock) -> None:
        mock_agents = MagicMock()
        sys.modules["agents"] = mock_agents

        try:
            agent = OpenAIAgentsAgent(openai_agents_config)
            agent._initialize_external_agent()

            mock_agents.Agent.assert_called_once_with(
                name="oai-agent",
                instructions="Be helpful",
                model="gpt-4o",
            )
            assert agent._external_agent is mock_agents.Agent.return_value
        finally:
            del sys.modules["agents"]

    def test_uses_description_as_instructions_fallback(
        self, openai_agents_config: MagicMock
    ) -> None:
        openai_agents_config.agent.plugin_config = {
            "framework": PLUGIN_TYPE_OPENAI_AGENTS,
            "model": "gpt-4o",
        }
        mock_agents = MagicMock()
        sys.modules["agents"] = mock_agents

        try:
            agent = OpenAIAgentsAgent(openai_agents_config)
            agent._initialize_external_agent()

            call_kwargs = mock_agents.Agent.call_args[1]
            assert call_kwargs["instructions"] == "OpenAI test agent"
        finally:
            del sys.modules["agents"]

    def test_import_error_without_package(
        self, openai_agents_config: MagicMock
    ) -> None:
        # Ensure "agents" is not in sys.modules
        sys.modules.pop("agents", None)
        agent = OpenAIAgentsAgent(openai_agents_config)
        with pytest.raises(ImportError):
            agent._initialize_external_agent()


class TestOpenAIAgentsExecuteExternal:
    def test_execute_returns_string(self, openai_agents_config: MagicMock) -> None:
        mock_agents = MagicMock()
        mock_agents.Runner.run_sync.return_value.final_output = "answer"
        sys.modules["agents"] = mock_agents

        try:
            agent = OpenAIAgentsAgent(openai_agents_config)
            agent._external_agent = MagicMock()
            result = agent._execute_external({"query": "test"})

            assert result == "answer"
            mock_agents.Runner.run_sync.assert_called_once()
        finally:
            del sys.modules["agents"]

    def test_runner_receives_agent_and_task(
        self, openai_agents_config: MagicMock
    ) -> None:
        mock_agents = MagicMock()
        mock_agents.Runner.run_sync.return_value.final_output = "result"
        sys.modules["agents"] = mock_agents

        try:
            agent = OpenAIAgentsAgent(openai_agents_config)
            mock_external = MagicMock()
            agent._external_agent = mock_external
            agent._execute_external({"query": "hello"})

            call_args = mock_agents.Runner.run_sync.call_args[0]
            assert call_args[0] is mock_external
            assert "hello" in call_args[1]
        finally:
            del sys.modules["agents"]

    def test_run_returns_agent_response(self, openai_agents_config: MagicMock) -> None:
        mock_agents = MagicMock()
        mock_agents.Runner.run_sync.return_value.final_output = "output"
        sys.modules["agents"] = mock_agents

        try:
            agent = OpenAIAgentsAgent(openai_agents_config)
            agent._external_agent = MagicMock()
            agent._initialized = True
            response = agent._run({"query": "test"}, None, 0.0)

            assert isinstance(response, AgentResponse)
            assert response.output == "output"
            assert response.metadata["framework"] == "OpenAI Agents SDK"
        finally:
            del sys.modules["agents"]


class TestOpenAIAgentsTranslateConfig:
    def test_single_agent(self, tmp_path: object) -> None:
        source = tmp_path / "oai.yaml"
        data = {
            "name": "helper",
            "instructions": "Be helpful and concise",
            "model": "gpt-4o-mini",
        }
        source.write_text(yaml.dump(data))

        configs = OpenAIAgentsAgent.translate_config(source)

        assert len(configs) == 1
        assert configs[0]["agent"]["type"] == PLUGIN_TYPE_OPENAI_AGENTS
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["model"] == "gpt-4o-mini"
        assert pc["instructions"] == "Be helpful and concise"

    def test_multi_agent(self, tmp_path: object) -> None:
        source = tmp_path / "oai.yaml"
        data = {
            "agents": [
                {"name": "helper", "instructions": "Help"},
                {"name": "reviewer", "instructions": "Review"},
            ],
        }
        source.write_text(yaml.dump(data))

        configs = OpenAIAgentsAgent.translate_config(source)

        assert len(configs) == 2

    def test_file_not_found(self, tmp_path: object) -> None:
        with pytest.raises(FileNotFoundError):
            OpenAIAgentsAgent.translate_config(tmp_path / "missing.yaml")

    def test_default_model(self, tmp_path: object) -> None:
        source = tmp_path / "oai.yaml"
        data = {"instructions": "Be helpful"}
        source.write_text(yaml.dump(data))

        configs = OpenAIAgentsAgent.translate_config(source)
        pc = configs[0]["agent"]["plugin_config"]

        assert pc["model"] == DEFAULT_MODEL

    def test_returns_list(self, tmp_path: object) -> None:
        source = tmp_path / "oai.yaml"
        data = {"instructions": "Be helpful", "name": "test"}
        source.write_text(yaml.dump(data))

        configs = OpenAIAgentsAgent.translate_config(source)

        assert isinstance(configs, list)
