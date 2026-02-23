"""Tests for AutoGen adapter."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.adapters.autogen_adapter import (
    DEFAULT_AGENT_CLASS,
    DEFAULT_MODEL_NAME,
    AutoGenAgent,
)
from temper_ai.plugins.constants import PLUGIN_TYPE_AUTOGEN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _mock_autogen_modules():
    """Context manager that injects minimal AutoGen module stubs."""
    mock_agentchat = MagicMock()
    mock_messages = MagicMock()
    mock_ext = MagicMock()
    mock_core = MagicMock()

    modules = {
        "autogen_agentchat": mock_agentchat,
        "autogen_agentchat.agents": mock_agentchat.agents,
        "autogen_agentchat.messages": mock_messages,
        "autogen_ext": mock_ext,
        "autogen_ext.models": mock_ext.models,
        "autogen_ext.models.openai": mock_ext.models.openai,
        "autogen_core": mock_core,
    }
    old = {k: sys.modules.get(k) for k in modules}
    sys.modules.update(modules)
    try:
        yield mock_agentchat, mock_messages, mock_ext, mock_core
    finally:
        for k, v in old.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _make_autogen_config(**overrides):
    config = MagicMock()
    config.agent.name = overrides.get("name", "ag-agent")
    config.agent.description = overrides.get("description", "AutoGen test agent")
    config.agent.version = overrides.get("version", "1.0")
    config.agent.type = PLUGIN_TYPE_AUTOGEN
    config.agent.plugin_config = overrides.get(
        "plugin_config",
        {
            "framework": PLUGIN_TYPE_AUTOGEN,
            "agent_class": DEFAULT_AGENT_CLASS,
            "model_client_config": {"model": DEFAULT_MODEL_NAME},
        },
    )
    return config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def autogen_config():
    return _make_autogen_config()


# ---------------------------------------------------------------------------
# Class variable tests
# ---------------------------------------------------------------------------


class TestAutoGenAgentClassVars:
    def test_framework_name(self):
        assert AutoGenAgent.FRAMEWORK_NAME == "AutoGen"

    def test_agent_type(self):
        assert AutoGenAgent.AGENT_TYPE == PLUGIN_TYPE_AUTOGEN

    def test_required_package(self):
        assert AutoGenAgent.REQUIRED_PACKAGE == "autogen-agentchat"


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestAutoGenAgentInit:
    def test_basic_instantiation(self, autogen_config):
        agent = AutoGenAgent(autogen_config)
        assert agent.name == "ag-agent"
        assert agent.description == "AutoGen test agent"
        assert agent._initialized is False
        assert agent._external_agent is None

    def test_version_set(self, autogen_config):
        agent = AutoGenAgent(autogen_config)
        assert agent.version == "1.0"


# ---------------------------------------------------------------------------
# _initialize_external_agent
# ---------------------------------------------------------------------------


class TestAutoGenInitializeExternal:
    def test_creates_assistant_agent(self, autogen_config):
        with _mock_autogen_modules() as (mock_agentchat, _, mock_ext, _):
            agent = AutoGenAgent(autogen_config)
            agent._initialize_external_agent()

            mock_agentchat.agents.AssistantAgent.assert_called_once()
            assert agent._external_agent is not None

    def test_passes_name_and_system_message(self, autogen_config):
        with _mock_autogen_modules() as (mock_agentchat, _, mock_ext, _):
            agent = AutoGenAgent(autogen_config)
            agent._initialize_external_agent()

            _, kwargs = mock_agentchat.agents.AssistantAgent.call_args
            assert kwargs.get("name") == "ag-agent"
            assert kwargs.get("system_message") == "AutoGen test agent"

    def test_warns_on_unsupported_agent_class(self, autogen_config, caplog):
        cfg = _make_autogen_config(
            plugin_config={
                "framework": PLUGIN_TYPE_AUTOGEN,
                "agent_class": "CustomAgent",
                "model_client_config": {"model": DEFAULT_MODEL_NAME},
            }
        )
        with _mock_autogen_modules():
            agent = AutoGenAgent(cfg)
            with caplog.at_level("WARNING"):
                agent._initialize_external_agent()
        assert "CustomAgent" in caplog.text

    def test_import_error_without_package(self, autogen_config):
        agent = AutoGenAgent(autogen_config)
        with pytest.raises(ImportError):
            agent._initialize_external_agent()

    def test_default_model_used_when_not_specified(self):
        cfg = _make_autogen_config(
            plugin_config={
                "framework": PLUGIN_TYPE_AUTOGEN,
                "agent_class": DEFAULT_AGENT_CLASS,
                "model_client_config": {},
            }
        )
        with _mock_autogen_modules() as (_, _, mock_ext, _):
            agent = AutoGenAgent(cfg)
            agent._initialize_external_agent()

            _, kwargs = mock_ext.models.openai.OpenAIChatCompletionClient.call_args
            assert kwargs.get("model") == DEFAULT_MODEL_NAME


# ---------------------------------------------------------------------------
# _execute_external / _run_autogen
# ---------------------------------------------------------------------------


class TestAutoGenExecuteExternal:
    def test_execute_returns_chat_message_content(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "autogen result"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external

            result = agent._execute_external({"query": "test question"})
            assert result == "autogen result"

    def test_empty_response_when_no_chat_message(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message = None
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external

            result = agent._execute_external({"query": "test"})
            assert result == ""

    def test_extracts_task_from_various_keys(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "response"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external

            # Test 'task' key
            result = agent._execute_external({"task": "do something"})
            assert result == "response"

    def test_on_messages_called_with_text_message(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "ok"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external

            agent._execute_external({"query": "ping"})
            assert mock_external.on_messages.called


# ---------------------------------------------------------------------------
# _run (BaseAgent wrapper → AgentResponse)
# ---------------------------------------------------------------------------


class TestAutoGenRun:
    def test_run_returns_agent_response(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "final output"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external
            agent._initialized = True

            response = agent._run({"query": "test"}, None, 0.0)
            assert isinstance(response, AgentResponse)
            assert response.output == "final output"

    def test_run_metadata_has_framework(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "output"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external
            agent._initialized = True

            response = agent._run({"query": "test"}, None, 0.0)
            assert response.metadata["framework"] == "AutoGen"
            assert response.metadata["agent_type"] == PLUGIN_TYPE_AUTOGEN

    def test_run_error_field_none_on_success(self, autogen_config):
        with _mock_autogen_modules() as (_, mock_messages, _, mock_core):
            agent = AutoGenAgent(autogen_config)
            mock_external = AsyncMock()
            mock_response = MagicMock()
            mock_response.chat_message.content = "output"
            mock_external.on_messages.return_value = mock_response
            agent._external_agent = mock_external
            agent._initialized = True

            response = agent._run({"query": "test"}, None, 0.0)
            assert response.error is None


# ---------------------------------------------------------------------------
# translate_config
# ---------------------------------------------------------------------------


class TestAutoGenTranslateConfig:
    def test_single_agent_config(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {
            "name": "assistant",
            "system_message": "Be helpful",
            "agent_class": DEFAULT_AGENT_CLASS,
            "model_client_config": {"model": DEFAULT_MODEL_NAME},
        }
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        assert len(configs) == 1
        assert configs[0]["agent"]["type"] == PLUGIN_TYPE_AUTOGEN

    def test_single_agent_plugin_config(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {
            "name": "assistant",
            "system_message": "Be helpful",
            "agent_class": DEFAULT_AGENT_CLASS,
            "model_client_config": {"model": DEFAULT_MODEL_NAME},
        }
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["agent_class"] == DEFAULT_AGENT_CLASS
        assert pc["model_client_config"] == {"model": DEFAULT_MODEL_NAME}

    def test_multi_agent_list(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {
            "agents": [
                {"name": "agent1", "system_message": "msg1"},
                {"name": "agent2", "system_message": "msg2"},
            ],
        }
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        assert len(configs) == 2

    def test_multi_agent_names_preserved(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {
            "agents": [
                {"name": "alpha", "system_message": "first"},
                {"name": "beta", "system_message": "second"},
            ],
        }
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        names = [c["agent"]["name"] for c in configs]
        assert "alpha" in names
        assert "beta" in names

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            AutoGenAgent.translate_config(tmp_path / "missing.yaml")

    def test_default_agent_class_applied(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {"name": "basic"}
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["agent_class"] == DEFAULT_AGENT_CLASS

    def test_default_model_client_config_empty(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {"name": "basic"}
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["model_client_config"] == {}

    def test_framework_set_to_autogen(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {"name": "myagent", "system_message": "Help me"}
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["framework"] == PLUGIN_TYPE_AUTOGEN

    def test_system_message_used_as_description(self, tmp_path):
        source = tmp_path / "autogen.yaml"
        data = {"name": "myagent", "system_message": "Custom system message"}
        source.write_text(yaml.dump(data))

        configs = AutoGenAgent.translate_config(source)
        assert configs[0]["agent"]["description"] == "Custom system message"

    def test_invalid_yaml_raises(self, tmp_path):
        source = tmp_path / "bad.yaml"
        source.write_text("- item1\n- item2\n")  # list, not dict

        with pytest.raises(ValueError):
            AutoGenAgent.translate_config(source)
