"""Tests for plugin registry."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.plugins.constants import (
    ALL_PLUGIN_TYPES,
    PLUGIN_TYPE_AUTOGEN,
    PLUGIN_TYPE_CREWAI,
    PLUGIN_TYPE_LANGGRAPH,
    PLUGIN_TYPE_OPENAI_AGENTS,
)
from temper_ai.plugins.registry import (
    ensure_plugin_registered,
    is_plugin_type,
    list_plugins,
)


class TestIsPluginType:
    def test_crewai_is_plugin(self) -> None:
        assert is_plugin_type(PLUGIN_TYPE_CREWAI) is True

    def test_langgraph_is_plugin(self) -> None:
        assert is_plugin_type(PLUGIN_TYPE_LANGGRAPH) is True

    def test_openai_agents_is_plugin(self) -> None:
        assert is_plugin_type(PLUGIN_TYPE_OPENAI_AGENTS) is True

    def test_autogen_is_plugin(self) -> None:
        assert is_plugin_type(PLUGIN_TYPE_AUTOGEN) is True

    def test_standard_is_not_plugin(self) -> None:
        assert is_plugin_type("standard") is False

    def test_unknown_is_not_plugin(self) -> None:
        assert is_plugin_type("unknown") is False

    def test_empty_string_is_not_plugin(self) -> None:
        assert is_plugin_type("") is False

    def test_all_plugin_types_are_recognized(self) -> None:
        for pt in ALL_PLUGIN_TYPES:
            assert is_plugin_type(pt) is True


class TestEnsurePluginRegistered:
    def test_unknown_type_returns_false(self) -> None:
        assert ensure_plugin_registered("totally_unknown") is False

    def test_import_error_returns_false(self) -> None:
        from temper_ai.agent.utils.agent_factory import AgentFactory
        AgentFactory.reset_for_testing()
        # Point to a non-existent module path to force ImportError
        import temper_ai.plugins.registry as reg_module
        original_map = dict(reg_module._PLUGIN_MAP)
        reg_module._PLUGIN_MAP[PLUGIN_TYPE_CREWAI] = (
            "temper_ai.plugins.adapters._nonexistent_module_xyz",
            "SomeClass",
            "crewai",
        )
        try:
            result = ensure_plugin_registered(PLUGIN_TYPE_CREWAI)
            assert result is False
        finally:
            reg_module._PLUGIN_MAP[PLUGIN_TYPE_CREWAI] = original_map[PLUGIN_TYPE_CREWAI]
            AgentFactory.reset_for_testing()

    def test_already_registered_returns_true(self) -> None:
        from temper_ai.agent.base_agent import BaseAgent
        from temper_ai.agent.utils.agent_factory import AgentFactory
        AgentFactory.reset_for_testing()

        # Register a dummy class first
        dummy = type("Dummy", (BaseAgent,), {
            "_run": lambda self, *a: None,
            "get_capabilities": lambda self: {},
        })
        AgentFactory.register_type(PLUGIN_TYPE_CREWAI, dummy)

        result = ensure_plugin_registered(PLUGIN_TYPE_CREWAI)
        assert result is True
        AgentFactory.reset_for_testing()

    def test_non_plugin_type_returns_false(self) -> None:
        result = ensure_plugin_registered("standard")
        assert result is False

    def test_empty_type_returns_false(self) -> None:
        assert ensure_plugin_registered("") is False


class TestListPlugins:
    def test_lists_all_plugin_types(self) -> None:
        plugins = list_plugins()
        assert set(plugins.keys()) == ALL_PLUGIN_TYPES

    def test_plugin_info_has_required_fields(self) -> None:
        plugins = list_plugins()
        for info in plugins.values():
            assert "module" in info
            assert "class" in info
            assert "available" in info
            assert "install_hint" in info

    def test_unavailable_plugins_have_install_hint(self) -> None:
        plugins = list_plugins()
        for name, info in plugins.items():
            assert name in info["install_hint"]

    def test_install_hint_format(self) -> None:
        plugins = list_plugins()
        for info in plugins.values():
            assert "pip install" in info["install_hint"]

    def test_available_field_is_bool(self) -> None:
        plugins = list_plugins()
        for info in plugins.values():
            assert isinstance(info["available"], bool)

    def test_crewai_entry_has_correct_class(self) -> None:
        plugins = list_plugins()
        assert plugins[PLUGIN_TYPE_CREWAI]["class"] == "CrewAIAgent"

    def test_langgraph_entry_has_correct_class(self) -> None:
        plugins = list_plugins()
        assert plugins[PLUGIN_TYPE_LANGGRAPH]["class"] == "LangGraphAgent"

    def test_openai_agents_entry_has_correct_class(self) -> None:
        plugins = list_plugins()
        assert plugins[PLUGIN_TYPE_OPENAI_AGENTS]["class"] == "OpenAIAgentsAgent"

    def test_autogen_entry_has_correct_class(self) -> None:
        plugins = list_plugins()
        assert plugins[PLUGIN_TYPE_AUTOGEN]["class"] == "AutoGenAgent"

    def test_returns_four_plugins(self) -> None:
        plugins = list_plugins()
        assert len(plugins) == len(ALL_PLUGIN_TYPES)
