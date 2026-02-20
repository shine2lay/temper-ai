"""Tests for plugin configuration schemas."""
import pytest
from pydantic import ValidationError

from temper_ai.plugins._schemas import (
    AutoGenPluginConfig,
    CrewAIPluginConfig,
    LangGraphPluginConfig,
    OpenAIAgentsPluginConfig,
    PluginConfig,
)


class TestPluginConfig:
    def test_base_config_requires_framework(self) -> None:
        config = PluginConfig(framework="test")
        assert config.framework == "test"

    def test_base_config_defaults(self) -> None:
        config = PluginConfig(framework="test")
        assert config.framework_config == {}
        assert config.extra == {}

    def test_base_config_with_extra(self) -> None:
        config = PluginConfig(
            framework="test",
            framework_config={"key": "val"},
            extra={"meta": True},
        )
        assert config.framework_config["key"] == "val"
        assert config.extra["meta"] is True

    def test_base_config_framework_config_is_dict(self) -> None:
        config = PluginConfig(framework="test", framework_config={"a": 1, "b": 2})
        assert config.framework_config == {"a": 1, "b": 2}

    def test_base_config_extra_is_dict(self) -> None:
        config = PluginConfig(framework="test", extra={"x": "y"})
        assert config.extra == {"x": "y"}


class TestCrewAIPluginConfig:
    def test_valid_config(self) -> None:
        config = CrewAIPluginConfig(role="Researcher", goal="Research")
        assert config.framework == "crewai"
        assert config.role == "Researcher"
        assert config.goal == "Research"

    def test_defaults(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G")
        assert config.backstory == ""
        assert config.allow_delegation is False
        assert config.verbose is False

    def test_missing_role_raises(self) -> None:
        with pytest.raises(ValidationError):
            CrewAIPluginConfig(goal="G")  # type: ignore[call-arg]

    def test_missing_goal_raises(self) -> None:
        with pytest.raises(ValidationError):
            CrewAIPluginConfig(role="R")  # type: ignore[call-arg]

    def test_custom_backstory(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G", backstory="Expert")
        assert config.backstory == "Expert"

    def test_allow_delegation_true(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G", allow_delegation=True)
        assert config.allow_delegation is True

    def test_verbose_true(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G", verbose=True)
        assert config.verbose is True

    def test_framework_is_crewai(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G")
        assert config.framework == "crewai"

    def test_inherits_plugin_config(self) -> None:
        config = CrewAIPluginConfig(role="R", goal="G")
        assert isinstance(config, PluginConfig)


class TestLangGraphPluginConfig:
    def test_valid_config(self) -> None:
        config = LangGraphPluginConfig(graph_module="my_app.graph")
        assert config.framework == "langgraph"
        assert config.graph_module == "my_app.graph"

    def test_defaults(self) -> None:
        config = LangGraphPluginConfig(graph_module="m")
        assert config.input_key == "input"
        assert config.output_key == "output"
        assert config.state_schema is None

    def test_custom_keys(self) -> None:
        config = LangGraphPluginConfig(
            graph_module="m",
            input_key="query",
            output_key="result",
        )
        assert config.input_key == "query"
        assert config.output_key == "result"

    def test_state_schema(self) -> None:
        config = LangGraphPluginConfig(
            graph_module="m",
            state_schema="my_app.state.State",
        )
        assert config.state_schema == "my_app.state.State"

    def test_framework_is_langgraph(self) -> None:
        config = LangGraphPluginConfig(graph_module="m")
        assert config.framework == "langgraph"

    def test_inherits_plugin_config(self) -> None:
        config = LangGraphPluginConfig(graph_module="m")
        assert isinstance(config, PluginConfig)

    def test_missing_graph_module_raises(self) -> None:
        with pytest.raises(ValidationError):
            LangGraphPluginConfig()  # type: ignore[call-arg]


class TestOpenAIAgentsPluginConfig:
    def test_valid_config(self) -> None:
        config = OpenAIAgentsPluginConfig()
        assert config.framework == "openai_agents"
        assert config.model == "gpt-4o"

    def test_custom_model(self) -> None:
        config = OpenAIAgentsPluginConfig(model="gpt-4o-mini", instructions="Be helpful")
        assert config.model == "gpt-4o-mini"
        assert config.instructions == "Be helpful"

    def test_default_instructions_empty(self) -> None:
        config = OpenAIAgentsPluginConfig()
        assert config.instructions == ""

    def test_framework_is_openai_agents(self) -> None:
        config = OpenAIAgentsPluginConfig()
        assert config.framework == "openai_agents"

    def test_inherits_plugin_config(self) -> None:
        config = OpenAIAgentsPluginConfig()
        assert isinstance(config, PluginConfig)


class TestAutoGenPluginConfig:
    def test_valid_config(self) -> None:
        config = AutoGenPluginConfig()
        assert config.framework == "autogen"
        assert config.agent_class == "AssistantAgent"

    def test_custom_config(self) -> None:
        config = AutoGenPluginConfig(
            agent_class="CustomAgent",
            model_client_config={"model": "gpt-4"},
        )
        assert config.agent_class == "CustomAgent"
        assert config.model_client_config["model"] == "gpt-4"

    def test_default_model_client_config_empty(self) -> None:
        config = AutoGenPluginConfig()
        assert config.model_client_config == {}

    def test_framework_is_autogen(self) -> None:
        config = AutoGenPluginConfig()
        assert config.framework == "autogen"

    def test_inherits_plugin_config(self) -> None:
        config = AutoGenPluginConfig()
        assert isinstance(config, PluginConfig)

    def test_custom_agent_class(self) -> None:
        config = AutoGenPluginConfig(agent_class="UserProxyAgent")
        assert config.agent_class == "UserProxyAgent"
