"""Tests for LangGraph adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from temper_ai.agent.models.response import AgentResponse
from temper_ai.plugins.adapters.langgraph_adapter import (
    DEFAULT_INPUT_KEY,
    DEFAULT_OUTPUT_KEY,
    DEFAULT_RECURSION_LIMIT,
    LangGraphAgent,
)
from temper_ai.plugins.constants import PLUGIN_TYPE_LANGGRAPH


@pytest.fixture()
def langgraph_config() -> MagicMock:
    config = MagicMock()
    config.agent.name = "lg-agent"
    config.agent.description = "LangGraph test agent"
    config.agent.version = "1.0"
    config.agent.type = PLUGIN_TYPE_LANGGRAPH
    config.agent.plugin_config = {
        "framework": PLUGIN_TYPE_LANGGRAPH,
        "graph_module": "my_app.graph",
        "input_key": "input",
        "output_key": "output",
    }
    return config


class TestLangGraphAgentInit:
    def test_class_vars(self) -> None:
        assert LangGraphAgent.FRAMEWORK_NAME == "LangGraph"
        assert LangGraphAgent.AGENT_TYPE == PLUGIN_TYPE_LANGGRAPH
        assert LangGraphAgent.REQUIRED_PACKAGE == "langgraph"

    def test_instantiation(self, langgraph_config: MagicMock) -> None:
        agent = LangGraphAgent(langgraph_config)
        assert agent.name == "lg-agent"
        assert agent._initialized is False

    def test_default_input_key_constant(self) -> None:
        assert DEFAULT_INPUT_KEY == "input"

    def test_default_output_key_constant(self) -> None:
        assert DEFAULT_OUTPUT_KEY == "output"

    def test_default_recursion_limit_constant(self) -> None:
        assert DEFAULT_RECURSION_LIMIT == 25


class TestLangGraphInitializeExternal:
    @patch("temper_ai.plugins.adapters.langgraph_adapter.importlib")
    def test_loads_graph_from_module(
        self, mock_importlib: MagicMock, langgraph_config: MagicMock
    ) -> None:
        mock_module = MagicMock()
        mock_module.graph = MagicMock()
        mock_importlib.import_module.return_value = mock_module

        agent = LangGraphAgent(langgraph_config)
        agent._initialize_external_agent()

        mock_importlib.import_module.assert_called_once_with("my_app.graph")
        assert agent._external_agent is mock_module.graph

    @patch("temper_ai.plugins.adapters.langgraph_adapter.importlib")
    def test_falls_back_to_app_attribute(
        self, mock_importlib: MagicMock, langgraph_config: MagicMock
    ) -> None:
        mock_module = MagicMock()
        mock_module.graph = None
        mock_module.app = MagicMock()
        mock_importlib.import_module.return_value = mock_module

        agent = LangGraphAgent(langgraph_config)
        agent._initialize_external_agent()

        assert agent._external_agent is mock_module.app

    def test_missing_graph_module_raises(self, langgraph_config: MagicMock) -> None:
        langgraph_config.agent.plugin_config = {"framework": "langgraph"}
        agent = LangGraphAgent(langgraph_config)
        with pytest.raises(ValueError, match="graph_module"):
            agent._initialize_external_agent()

    @patch("temper_ai.plugins.adapters.langgraph_adapter.importlib")
    def test_missing_graph_and_app_raises(
        self, mock_importlib: MagicMock, langgraph_config: MagicMock
    ) -> None:
        mock_module = MagicMock()
        mock_module.graph = None
        mock_module.app = None
        mock_importlib.import_module.return_value = mock_module

        agent = LangGraphAgent(langgraph_config)
        with pytest.raises(ValueError, match="no 'graph' or 'app' attribute"):
            agent._initialize_external_agent()


class TestLangGraphExecuteExternal:
    def test_invokes_graph(self, langgraph_config: MagicMock) -> None:
        agent = LangGraphAgent(langgraph_config)
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"output": "result text"}
        agent._external_agent = mock_graph

        result = agent._execute_external({"query": "test"})

        assert result == "result text"
        mock_graph.invoke.assert_called_once()

    def test_custom_keys(self, langgraph_config: MagicMock) -> None:
        langgraph_config.agent.plugin_config["input_key"] = "question"
        langgraph_config.agent.plugin_config["output_key"] = "answer"
        agent = LangGraphAgent(langgraph_config)
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"answer": "42"}
        agent._external_agent = mock_graph

        result = agent._execute_external({"query": "what?"})

        assert result == "42"
        call_args = mock_graph.invoke.call_args[0][0]
        assert "question" in call_args

    def test_recursion_limit_passed(self, langgraph_config: MagicMock) -> None:
        agent = LangGraphAgent(langgraph_config)
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"output": "done"}
        agent._external_agent = mock_graph

        agent._execute_external({"query": "test"})

        _, kwargs = mock_graph.invoke.call_args
        config = kwargs.get("config", {})
        assert config.get("recursion_limit") == DEFAULT_RECURSION_LIMIT

    def test_run_returns_agent_response(self, langgraph_config: MagicMock) -> None:
        agent = LangGraphAgent(langgraph_config)
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"output": "done"}
        agent._external_agent = mock_graph
        agent._initialized = True

        response = agent._run({"query": "test"}, None, 0.0)

        assert isinstance(response, AgentResponse)
        assert response.output == "done"
        assert response.metadata["framework"] == "LangGraph"

    def test_fallback_when_output_key_missing(
        self, langgraph_config: MagicMock
    ) -> None:
        agent = LangGraphAgent(langgraph_config)
        mock_graph = MagicMock()
        # Return dict without expected output key
        raw_result = {"some_other_key": "data"}
        mock_graph.invoke.return_value = raw_result
        agent._external_agent = mock_graph

        result = agent._execute_external({"query": "test"})

        # Falls back to str(result)
        assert isinstance(result, str)


class TestLangGraphTranslateConfig:
    def test_translate_config(self, tmp_path: object) -> None:
        source = tmp_path / "lg.yaml"
        data = {
            "name": "my_graph",
            "description": "A graph agent",
            "graph_module": "my_app.graph",
            "input_key": "query",
            "output_key": "result",
        }
        source.write_text(yaml.dump(data))

        configs = LangGraphAgent.translate_config(source)

        assert len(configs) == 1
        assert configs[0]["agent"]["type"] == PLUGIN_TYPE_LANGGRAPH
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["graph_module"] == "my_app.graph"
        assert pc["input_key"] == "query"
        assert pc["output_key"] == "result"

    def test_translate_config_defaults(self, tmp_path: object) -> None:
        source = tmp_path / "lg.yaml"
        data = {"graph_module": "app.graph"}
        source.write_text(yaml.dump(data))

        configs = LangGraphAgent.translate_config(source)

        assert len(configs) == 1
        pc = configs[0]["agent"]["plugin_config"]
        assert pc["input_key"] == DEFAULT_INPUT_KEY
        assert pc["output_key"] == DEFAULT_OUTPUT_KEY

    def test_file_not_found(self, tmp_path: object) -> None:
        with pytest.raises(FileNotFoundError):
            LangGraphAgent.translate_config(tmp_path / "missing.yaml")

    def test_returns_list(self, tmp_path: object) -> None:
        source = tmp_path / "lg.yaml"
        data = {"graph_module": "app.graph", "name": "test"}
        source.write_text(yaml.dump(data))

        configs = LangGraphAgent.translate_config(source)

        assert isinstance(configs, list)
        assert len(configs) == 1
        assert "agent" in configs[0]
