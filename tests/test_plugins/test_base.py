"""Tests for ExternalAgentPlugin base class."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.base import ExternalAgentPlugin


class ConcretePlugin(ExternalAgentPlugin):
    """Concrete test implementation of ExternalAgentPlugin."""

    FRAMEWORK_NAME: ClassVar[str] = "TestFramework"
    AGENT_TYPE: ClassVar[str] = "test_plugin"
    REQUIRED_PACKAGE: ClassVar[str] = "test-pkg"

    def _initialize_external_agent(self) -> None:
        self._external_agent = MagicMock()

    def _execute_external(self, input_data: dict[str, Any]) -> str:
        return f"executed: {self._extract_task_description(input_data)}"

    @classmethod
    def translate_config(cls, source_path: Path) -> list[dict[str, Any]]:
        return [{"agent": {"name": "test", "type": "test_plugin"}}]


class TestExternalAgentPluginABC:
    def test_cannot_instantiate_abc(self) -> None:
        config = MagicMock()
        config.agent.name = "test"
        config.agent.description = "test"
        config.agent.version = "1.0"
        with pytest.raises(TypeError):
            ExternalAgentPlugin(config)  # type: ignore[abstract]

    def test_concrete_instantiation(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin.name == "test-agent"
        assert plugin._initialized is False

    def test_external_agent_starts_as_none(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin._external_agent is None

    def test_stores_config(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin.config is mock_agent_config

    def test_description_from_config(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin.description == "Test agent"

    def test_version_from_config(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin.version == "1.0"


class TestPluginExecution:
    def test_run_returns_agent_response(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        plugin._initialized = True
        result = plugin._run({"query": "hello"}, None, 0.0)
        assert isinstance(result, AgentResponse)
        assert "executed: hello" in result.output

    def test_run_includes_framework_metadata(
        self, mock_agent_config: MagicMock
    ) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        plugin._initialized = True
        result = plugin._run({"query": "test"}, None, 0.0)
        assert result.metadata["framework"] == "TestFramework"
        assert result.metadata["agent_type"] == "test_plugin"

    def test_on_setup_initializes_once(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert not plugin._initialized
        plugin._on_setup({"query": "test"}, None)
        assert plugin._initialized
        assert plugin._external_agent is not None
        # Second call should not re-initialize
        agent_ref = plugin._external_agent
        plugin._on_setup({"query": "test"}, None)
        assert plugin._external_agent is agent_ref

    def test_on_setup_idempotent(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        plugin._on_setup({}, None)
        plugin._on_setup({}, None)
        plugin._on_setup({}, None)
        assert plugin._initialized is True

    def test_extract_task_description_query(self) -> None:
        assert ExternalAgentPlugin._extract_task_description({"query": "hi"}) == "hi"

    def test_extract_task_description_task(self) -> None:
        assert (
            ExternalAgentPlugin._extract_task_description({"task": "do it"}) == "do it"
        )

    def test_extract_task_description_input(self) -> None:
        assert ExternalAgentPlugin._extract_task_description({"input": "run"}) == "run"

    def test_extract_task_description_question(self) -> None:
        assert (
            ExternalAgentPlugin._extract_task_description({"question": "why?"})
            == "why?"
        )

    def test_extract_task_description_prompt(self) -> None:
        assert (
            ExternalAgentPlugin._extract_task_description({"prompt": "write"})
            == "write"
        )

    def test_extract_task_description_message(self) -> None:
        assert (
            ExternalAgentPlugin._extract_task_description({"message": "hello"})
            == "hello"
        )

    def test_extract_task_description_fallback(self) -> None:
        result = ExternalAgentPlugin._extract_task_description({"data": "val"})
        assert "val" in result

    def test_extract_task_description_empty(self) -> None:
        assert ExternalAgentPlugin._extract_task_description({}) == ""

    def test_run_latency_non_negative(self, mock_agent_config: MagicMock) -> None:
        import time

        plugin = ConcretePlugin(mock_agent_config)
        plugin._initialized = True
        start = time.time()
        result = plugin._run({"query": "test"}, None, start)
        assert result.latency_seconds >= 0.0


class TestPluginCapabilities:
    def test_get_capabilities(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        caps = plugin.get_capabilities()
        assert caps["type"] == "test_plugin"
        assert caps["framework"] == "TestFramework"
        assert caps["supports_streaming"] is False

    def test_get_capabilities_supports_multimodal_false(
        self, mock_agent_config: MagicMock
    ) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        caps = plugin.get_capabilities()
        assert caps["supports_multimodal"] is False

    def test_get_capabilities_empty_tools(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        caps = plugin.get_capabilities()
        assert caps["tools"] == []

    def test_get_capabilities_has_name(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        caps = plugin.get_capabilities()
        assert caps["name"] == "test-agent"

    def test_validate_config(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin.validate_config() is True

    def test_validate_config_no_name(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.name = ""
        plugin = ConcretePlugin(mock_agent_config)
        with pytest.raises(ValueError, match="Agent name is required"):
            plugin.validate_config()


class TestPluginErrorHandling:
    def test_on_error_handles_import_error(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(ImportError("no module"), 0.0)
        assert isinstance(result, AgentResponse)
        assert result.error is not None

    def test_on_error_handles_value_error(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(ValueError("bad"), 0.0)
        assert isinstance(result, AgentResponse)

    def test_on_error_handles_runtime_error(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(RuntimeError("fail"), 0.0)
        assert isinstance(result, AgentResponse)

    def test_on_error_handles_timeout_error(self, mock_agent_config: MagicMock) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(TimeoutError("timed out"), 0.0)
        assert isinstance(result, AgentResponse)

    def test_on_error_returns_none_for_unknown(
        self, mock_agent_config: MagicMock
    ) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(KeyError("k"), 0.0)
        assert result is None

    def test_on_error_returns_none_for_type_error(
        self, mock_agent_config: MagicMock
    ) -> None:
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._on_error(TypeError("bad type"), 0.0)
        assert result is None


class TestGetPluginConfig:
    def test_dict_config(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.plugin_config = {"framework": "test", "key": "val"}
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin._get_plugin_config()["key"] == "val"

    def test_none_config(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.plugin_config = None
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin._get_plugin_config() == {}

    def test_pydantic_model_config(self, mock_agent_config: MagicMock) -> None:
        from temper_ai.plugins._schemas import PluginConfig

        pc = PluginConfig(framework="test")
        mock_agent_config.agent.plugin_config = pc
        plugin = ConcretePlugin(mock_agent_config)
        result = plugin._get_plugin_config()
        assert result["framework"] == "test"

    def test_dict_config_framework_key(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.plugin_config = {"framework": "crewai"}
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin._get_plugin_config()["framework"] == "crewai"

    def test_empty_dict_config(self, mock_agent_config: MagicMock) -> None:
        mock_agent_config.agent.plugin_config = {}
        plugin = ConcretePlugin(mock_agent_config)
        assert plugin._get_plugin_config() == {}
