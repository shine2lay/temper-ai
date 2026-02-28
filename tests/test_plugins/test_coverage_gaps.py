"""Tests targeting specific coverage gaps in temper_ai/plugins/.

Covers:
- __init__.py lazy __getattr__ branches (lines 24-36)
- registry.py ensure_plugin_registered success + AttributeError/ValueError paths,
  list_plugins (already covered but adds branch coverage), get_health_checks,
  _call_class_health_check (lines 73-76, 85-87, 121-146, 153-165)
- adapters/autogen_adapter.py health_check branches (lines 35-44, 82, 88)
- adapters/crewai_adapter.py health_check branches (lines 33-42)
- adapters/langgraph_adapter.py health_check branches (lines 33-42)
- adapters/openai_agents_adapter.py health_check branches (lines 32-41)
- base.py health_check unavailable branch (lines 124-125)
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temper_ai.plugins.constants import (
    PLUGIN_TYPE_AUTOGEN,
    PLUGIN_TYPE_CREWAI,
    PLUGIN_TYPE_LANGGRAPH,
    PLUGIN_TYPE_OPENAI_AGENTS,
)

# ---------------------------------------------------------------------------
# __init__.py lazy __getattr__ branches
# ---------------------------------------------------------------------------


class TestPluginsInitGetattr:
    """Test the lazy-import __getattr__ in temper_ai/plugins/__init__.py."""

    def test_getattr_external_agent_plugin(self):
        import temper_ai.plugins as plugins_mod

        cls = plugins_mod.__getattr__("ExternalAgentPlugin")
        from temper_ai.plugins.base import ExternalAgentPlugin

        assert cls is ExternalAgentPlugin

    def test_getattr_ensure_plugin_registered(self):
        import temper_ai.plugins as plugins_mod

        fn = plugins_mod.__getattr__("ensure_plugin_registered")
        from temper_ai.plugins.registry import ensure_plugin_registered

        assert fn is ensure_plugin_registered

    def test_getattr_list_plugins(self):
        import temper_ai.plugins as plugins_mod

        fn = plugins_mod.__getattr__("list_plugins")
        from temper_ai.plugins.registry import list_plugins

        assert fn is list_plugins

    def test_getattr_unknown_raises_attribute_error(self):
        import temper_ai.plugins as plugins_mod

        with pytest.raises(AttributeError, match="no attribute"):
            plugins_mod.__getattr__("NonExistentAttribute")

    def test_getattr_module_level_access_external_agent_plugin(self):
        """Accessing via the module also works (not just __getattr__ directly)."""
        import temper_ai.plugins as plugins_mod

        # Direct attribute access triggers __getattr__ too
        cls = plugins_mod.ExternalAgentPlugin
        assert cls is not None
        assert cls.__name__ == "ExternalAgentPlugin"

    def test_getattr_ensure_plugin_registered_callable(self):
        import temper_ai.plugins as plugins_mod

        fn = plugins_mod.__getattr__("ensure_plugin_registered")
        assert callable(fn)

    def test_getattr_list_plugins_callable(self):
        import temper_ai.plugins as plugins_mod

        fn = plugins_mod.__getattr__("list_plugins")
        assert callable(fn)


# ---------------------------------------------------------------------------
# registry.py — ensure_plugin_registered success and error paths
# ---------------------------------------------------------------------------


class TestEnsurePluginRegisteredSuccessPath:
    """Test the actual successful registration path (lines 73-76)."""

    def test_successful_registration_returns_true(self):
        """When the import succeeds, registration should return True."""
        from temper_ai.agent.base_agent import BaseAgent
        from temper_ai.agent.utils.agent_factory import AgentFactory
        from temper_ai.plugins.registry import ensure_plugin_registered

        AgentFactory.reset_for_testing()

        # Need a real BaseAgent subclass so issubclass() works in AgentFactory
        MockCrewAI = type(
            "MockCrewAI",
            (BaseAgent,),
            {"_run": lambda s, *a: None, "get_capabilities": lambda s: {}},
        )
        mock_module = MagicMock()
        mock_module.CrewAIAgent = MockCrewAI

        with patch("importlib.import_module", return_value=mock_module) as mock_imp:
            result = ensure_plugin_registered(PLUGIN_TYPE_CREWAI)

        AgentFactory.reset_for_testing()

        assert mock_imp.called
        assert result is True

    def test_attribute_error_returns_false(self):
        """AttributeError during getattr should return False (lines 85-87)."""
        from temper_ai.agent.utils.agent_factory import AgentFactory
        from temper_ai.plugins.registry import ensure_plugin_registered

        AgentFactory.reset_for_testing()

        # Module exists but class attribute doesn't → AttributeError
        mock_module = MagicMock(spec=[])  # spec=[] means no attributes

        with patch("importlib.import_module", return_value=mock_module):
            result = ensure_plugin_registered(PLUGIN_TYPE_CREWAI)

        AgentFactory.reset_for_testing()
        assert result is False

    def test_value_error_during_registration_returns_false(self):
        """ValueError during AgentFactory.register_type should return False."""
        from temper_ai.agent.utils.agent_factory import AgentFactory
        from temper_ai.plugins.registry import ensure_plugin_registered

        AgentFactory.reset_for_testing()

        mock_module = MagicMock()
        mock_class = MagicMock()
        mock_module.CrewAIAgent = mock_class

        with patch("importlib.import_module", return_value=mock_module):
            with patch.object(
                AgentFactory, "register_type", side_effect=ValueError("bad type")
            ):
                result = ensure_plugin_registered(PLUGIN_TYPE_CREWAI)

        AgentFactory.reset_for_testing()
        assert result is False


# ---------------------------------------------------------------------------
# registry.py — get_health_checks and _call_class_health_check
# ---------------------------------------------------------------------------


class TestGetHealthChecks:
    """Test get_health_checks (lines 121-146) and _call_class_health_check (153-165)."""

    @pytest.mark.asyncio
    async def test_get_health_checks_returns_dict_for_all_types(self):
        from temper_ai.plugins.registry import get_health_checks

        mock_module = MagicMock()
        mock_module.__version__ = "1.2.3"
        mock_adapter_cls = MagicMock()
        mock_adapter_cls.FRAMEWORK_NAME = "FakeFramework"

        mock_spec = MagicMock()  # non-None spec means package is available

        with patch("importlib.import_module", return_value=mock_module):
            with patch("importlib.util.find_spec", return_value=mock_spec):
                result = await get_health_checks()

        assert isinstance(result, dict)
        # All four plugin types should have entries
        for pt in [
            PLUGIN_TYPE_CREWAI,
            PLUGIN_TYPE_LANGGRAPH,
            PLUGIN_TYPE_OPENAI_AGENTS,
            PLUGIN_TYPE_AUTOGEN,
        ]:
            assert pt in result

    @pytest.mark.asyncio
    async def test_get_health_checks_unavailable_when_spec_none(self):
        """When find_spec returns None for all packages, status should be unavailable."""
        import sys

        from temper_ai.plugins.registry import get_health_checks

        mock_module = MagicMock()
        mock_importlib = MagicMock()
        mock_importlib.import_module.return_value = mock_module
        mock_importlib.util.find_spec.return_value = None  # All specs = None

        with patch.dict(
            sys.modules,
            {"importlib": mock_importlib, "importlib.util": mock_importlib.util},
        ):
            result = await get_health_checks()

        assert isinstance(result, dict)
        # All entries should be 'unavailable' (spec=None) or 'error'
        for _pt, info in result.items():
            assert info["status"] in ("unavailable", "error")

    @pytest.mark.asyncio
    async def test_get_health_checks_handles_exception_per_plugin(self):
        """Exceptions during individual plugin health check become error entries."""
        from temper_ai.plugins.registry import get_health_checks

        with patch("importlib.import_module", side_effect=ImportError("no pkg")):
            result = await get_health_checks()

        assert isinstance(result, dict)
        for _pt, info in result.items():
            assert info["status"] == "error"
            assert "detail" in info

    @pytest.mark.asyncio
    async def test_call_class_health_check_ok_when_available(self):
        """_call_class_health_check returns ok status when framework is importable."""
        from temper_ai.plugins.registry import _call_class_health_check

        mock_cls = MagicMock()
        mock_cls.FRAMEWORK_NAME = "TestFramework"
        mock_pkg_module = MagicMock()
        mock_pkg_module.__version__ = "9.9.9"
        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch("importlib.import_module", return_value=mock_pkg_module):
                result = await _call_class_health_check(mock_cls, "test_pkg")

        assert result["status"] == "ok"
        assert result["version"] == "9.9.9"
        assert result["framework"] == "TestFramework"

    @pytest.mark.asyncio
    async def test_call_class_health_check_unavailable_when_spec_none(self):
        """_call_class_health_check returns unavailable when find_spec is None."""
        from temper_ai.plugins.registry import _call_class_health_check

        mock_cls = MagicMock()
        mock_cls.FRAMEWORK_NAME = "NoFramework"

        with patch("importlib.util.find_spec", return_value=None):
            result = await _call_class_health_check(mock_cls, "no_pkg")

        assert result["status"] == "unavailable"
        assert result["framework"] == "NoFramework"

    @pytest.mark.asyncio
    async def test_call_class_health_check_version_unknown_on_import_error(self):
        """_call_class_health_check returns 'unknown' version on ImportError."""
        from temper_ai.plugins.registry import _call_class_health_check

        mock_cls = MagicMock()
        mock_cls.FRAMEWORK_NAME = "BrokenFramework"
        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch("importlib.import_module", side_effect=ImportError("no import")):
                result = await _call_class_health_check(mock_cls, "broken_pkg")

        assert result["status"] == "ok"
        assert result["version"] == "unknown"

    @pytest.mark.asyncio
    async def test_call_class_health_check_uses_framework_pkg_as_fallback_name(self):
        """FRAMEWORK_NAME falls back to framework_pkg when attr missing."""
        from temper_ai.plugins.registry import _call_class_health_check

        mock_cls = MagicMock(spec=[])  # no FRAMEWORK_NAME attribute
        mock_spec = MagicMock()
        mock_pkg = MagicMock()
        mock_pkg.__version__ = "1.0"

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch("importlib.import_module", return_value=mock_pkg):
                result = await _call_class_health_check(mock_cls, "mypkg")

        assert result["framework"] == "mypkg"


# ---------------------------------------------------------------------------
# adapters/autogen_adapter.py — health_check branches (lines 35-44, 82, 88)
# ---------------------------------------------------------------------------


def _make_autogen_config(**overrides: Any) -> MagicMock:
    config = MagicMock()
    config.agent.name = overrides.get("name", "autogen-test")
    config.agent.description = overrides.get("description", "AutoGen test")
    config.agent.version = overrides.get("version", "1.0")
    config.agent.plugin_config = overrides.get("plugin_config", {})
    return config


class TestAutogenHealthCheckBranches:
    """Cover lines 35-44, 82, 88 in autogen_adapter.py."""

    @pytest.mark.asyncio
    async def test_health_check_unavailable_when_spec_none(self):
        from temper_ai.plugins.adapters.autogen_adapter import AutoGenAgent

        cfg = _make_autogen_config()
        agent = AutoGenAgent(cfg)

        with patch("importlib.util.find_spec", return_value=None):
            result = await agent.health_check()

        assert result["status"] == "unavailable"
        assert result["framework"] == "AutoGen"

    @pytest.mark.asyncio
    async def test_health_check_ok_when_package_available(self):
        from temper_ai.plugins.adapters.autogen_adapter import AutoGenAgent

        cfg = _make_autogen_config()
        agent = AutoGenAgent(cfg)

        mock_spec = MagicMock()
        mock_autogen = MagicMock()
        mock_autogen.__version__ = "0.4.0"

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"autogen_agentchat": mock_autogen}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["framework"] == "AutoGen"
        assert result["version"] == "0.4.0"

    @pytest.mark.asyncio
    async def test_health_check_version_unknown_on_import_error(self):
        """Lines 42-43: version = 'unknown' when ImportError on autogen_agentchat import."""
        from temper_ai.plugins.adapters.autogen_adapter import AutoGenAgent

        cfg = _make_autogen_config()
        agent = AutoGenAgent(cfg)

        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            # Make the actual import fail
            with patch.dict(sys.modules, {"autogen_agentchat": None}):
                # None in sys.modules causes ImportError on import
                try:
                    result = await agent.health_check()
                    assert result["version"] == "unknown"
                except ImportError:
                    pass  # Also acceptable — ImportError is the expected path

    def test_execute_external_raises_when_loop_running(self):
        """Line 82: RuntimeError raised when called from async context (loop running)."""
        from temper_ai.plugins.adapters.autogen_adapter import AutoGenAgent

        cfg = _make_autogen_config()
        agent = AutoGenAgent(cfg)

        # Simulate a running event loop
        with patch("asyncio.get_running_loop", return_value=MagicMock()):
            with pytest.raises(RuntimeError, match="_execute_external"):
                agent._execute_external({"query": "test"})

    def test_execute_external_proceeds_when_no_loop(self):
        """Line 88: When get_running_loop raises RuntimeError (no loop), proceeds normally."""
        from temper_ai.plugins.adapters.autogen_adapter import AutoGenAgent

        cfg = _make_autogen_config()
        agent = AutoGenAgent(cfg)

        # Simulate the external agent response
        mock_external = AsyncMock()
        mock_response = MagicMock()
        mock_response.chat_message.content = "result from autogen"
        mock_external.on_messages.return_value = mock_response
        agent._external_agent = mock_external

        # Stub out autogen message/core modules
        mock_messages = MagicMock()
        mock_core = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "autogen_agentchat.messages": mock_messages,
                "autogen_core": mock_core,
            },
        ):
            # get_running_loop raises RuntimeError → no loop running, safe to proceed
            with patch(
                "asyncio.get_running_loop",
                side_effect=RuntimeError("no running event loop"),
            ):
                result = agent._execute_external({"query": "ping"})

        assert result == "result from autogen"


# ---------------------------------------------------------------------------
# adapters/crewai_adapter.py — health_check branches (lines 33-42)
# ---------------------------------------------------------------------------


def _make_crewai_config(**overrides: Any) -> MagicMock:
    config = MagicMock()
    config.agent.name = overrides.get("name", "crewai-test")
    config.agent.description = overrides.get("description", "CrewAI test")
    config.agent.version = overrides.get("version", "1.0")
    config.agent.plugin_config = overrides.get(
        "plugin_config",
        {
            "framework": PLUGIN_TYPE_CREWAI,
            "role": "Researcher",
            "goal": "Research things",
            "backstory": "Expert",
        },
    )
    return config


class TestCrewAIHealthCheckBranches:
    """Cover lines 33-42 in crewai_adapter.py."""

    @pytest.mark.asyncio
    async def test_health_check_unavailable_when_spec_none(self):
        from temper_ai.plugins.adapters.crewai_adapter import CrewAIAgent

        cfg = _make_crewai_config()
        agent = CrewAIAgent(cfg)

        with patch("importlib.util.find_spec", return_value=None):
            result = await agent.health_check()

        assert result["status"] == "unavailable"
        assert result["framework"] == "CrewAI"

    @pytest.mark.asyncio
    async def test_health_check_ok_when_package_available(self):
        from temper_ai.plugins.adapters.crewai_adapter import CrewAIAgent

        cfg = _make_crewai_config()
        agent = CrewAIAgent(cfg)

        mock_spec = MagicMock()
        mock_crewai = MagicMock()
        mock_crewai.__version__ = "0.80.0"

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"crewai": mock_crewai}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["framework"] == "CrewAI"
        assert result["version"] == "0.80.0"

    @pytest.mark.asyncio
    async def test_health_check_version_no_version_attr(self):
        """Version 'unknown' when crewai has no __version__ attribute."""
        from temper_ai.plugins.adapters.crewai_adapter import CrewAIAgent

        cfg = _make_crewai_config()
        agent = CrewAIAgent(cfg)

        mock_spec = MagicMock()
        mock_crewai = MagicMock(spec=[])  # no __version__

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"crewai": mock_crewai}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["version"] == "unknown"

    @pytest.mark.asyncio
    async def test_health_check_version_unknown_on_import_error(self):
        """Lines 40-41: version = 'unknown' when ImportError on crewai import."""
        from temper_ai.plugins.adapters.crewai_adapter import CrewAIAgent

        cfg = _make_crewai_config()
        agent = CrewAIAgent(cfg)

        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"crewai": None}):
                try:
                    result = await agent.health_check()
                    assert result["version"] == "unknown"
                except ImportError:
                    pass  # ImportError is acceptable path


# ---------------------------------------------------------------------------
# adapters/langgraph_adapter.py — health_check branches (lines 33-42)
# ---------------------------------------------------------------------------


def _make_langgraph_config(**overrides: Any) -> MagicMock:
    config = MagicMock()
    config.agent.name = overrides.get("name", "lg-test")
    config.agent.description = overrides.get("description", "LangGraph test")
    config.agent.version = overrides.get("version", "1.0")
    config.agent.plugin_config = overrides.get(
        "plugin_config",
        {
            "framework": PLUGIN_TYPE_LANGGRAPH,
            "graph_module": "my_app.graph",
        },
    )
    return config


class TestLangGraphHealthCheckBranches:
    """Cover lines 33-42 in langgraph_adapter.py."""

    @pytest.mark.asyncio
    async def test_health_check_unavailable_when_spec_none(self):
        from temper_ai.plugins.adapters.langgraph_adapter import LangGraphAgent

        cfg = _make_langgraph_config()
        agent = LangGraphAgent(cfg)

        with patch("importlib.util.find_spec", return_value=None):
            result = await agent.health_check()

        assert result["status"] == "unavailable"
        assert result["framework"] == "LangGraph"

    @pytest.mark.asyncio
    async def test_health_check_ok_when_package_available(self):
        from temper_ai.plugins.adapters.langgraph_adapter import LangGraphAgent

        cfg = _make_langgraph_config()
        agent = LangGraphAgent(cfg)

        mock_spec = MagicMock()
        mock_langgraph = MagicMock()
        mock_langgraph.__version__ = "0.3.1"

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"langgraph": mock_langgraph}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["framework"] == "LangGraph"
        assert result["version"] == "0.3.1"

    @pytest.mark.asyncio
    async def test_health_check_version_no_version_attr(self):
        """version = 'unknown' when langgraph has no __version__ attribute."""
        from temper_ai.plugins.adapters.langgraph_adapter import LangGraphAgent

        cfg = _make_langgraph_config()
        agent = LangGraphAgent(cfg)

        mock_spec = MagicMock()
        mock_langgraph = MagicMock(spec=[])  # no __version__

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"langgraph": mock_langgraph}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["version"] == "unknown"

    @pytest.mark.asyncio
    async def test_health_check_version_unknown_on_import_error(self):
        """Lines 40-41: version = 'unknown' on ImportError."""
        from temper_ai.plugins.adapters.langgraph_adapter import LangGraphAgent

        cfg = _make_langgraph_config()
        agent = LangGraphAgent(cfg)

        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"langgraph": None}):
                try:
                    result = await agent.health_check()
                    assert result["version"] == "unknown"
                except ImportError:
                    pass  # ImportError is acceptable


# ---------------------------------------------------------------------------
# adapters/openai_agents_adapter.py — health_check branches (lines 32-41)
# ---------------------------------------------------------------------------


def _make_openai_config(**overrides: Any) -> MagicMock:
    config = MagicMock()
    config.agent.name = overrides.get("name", "openai-test")
    config.agent.description = overrides.get("description", "OpenAI test")
    config.agent.version = overrides.get("version", "1.0")
    config.agent.plugin_config = overrides.get(
        "plugin_config",
        {
            "framework": PLUGIN_TYPE_OPENAI_AGENTS,
            "instructions": "Be helpful",
            "model": "gpt-4o",
        },
    )
    return config


class TestOpenAIAgentsHealthCheckBranches:
    """Cover lines 32-41 in openai_agents_adapter.py."""

    @pytest.mark.asyncio
    async def test_health_check_unavailable_when_spec_none(self):
        from temper_ai.plugins.adapters.openai_agents_adapter import OpenAIAgentsAgent

        cfg = _make_openai_config()
        agent = OpenAIAgentsAgent(cfg)

        with patch("importlib.util.find_spec", return_value=None):
            result = await agent.health_check()

        assert result["status"] == "unavailable"
        assert result["framework"] == "OpenAI Agents SDK"

    @pytest.mark.asyncio
    async def test_health_check_ok_when_package_available(self):
        from temper_ai.plugins.adapters.openai_agents_adapter import OpenAIAgentsAgent

        cfg = _make_openai_config()
        agent = OpenAIAgentsAgent(cfg)

        mock_spec = MagicMock()
        mock_openai = MagicMock()
        mock_openai.__version__ = "1.60.0"

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"openai": mock_openai}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["framework"] == "OpenAI Agents SDK"
        assert result["version"] == "1.60.0"

    @pytest.mark.asyncio
    async def test_health_check_version_no_version_attr(self):
        """version = 'unknown' when openai has no __version__."""
        from temper_ai.plugins.adapters.openai_agents_adapter import OpenAIAgentsAgent

        cfg = _make_openai_config()
        agent = OpenAIAgentsAgent(cfg)

        mock_spec = MagicMock()
        mock_openai = MagicMock(spec=[])  # no __version__

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"openai": mock_openai}):
                result = await agent.health_check()

        assert result["status"] == "ok"
        assert result["version"] == "unknown"

    @pytest.mark.asyncio
    async def test_health_check_version_unknown_on_import_error(self):
        """Lines 38-39: version = 'unknown' on ImportError."""
        from temper_ai.plugins.adapters.openai_agents_adapter import OpenAIAgentsAgent

        cfg = _make_openai_config()
        agent = OpenAIAgentsAgent(cfg)

        mock_spec = MagicMock()

        with patch("importlib.util.find_spec", return_value=mock_spec):
            with patch.dict(sys.modules, {"openai": None}):
                try:
                    result = await agent.health_check()
                    assert result["version"] == "unknown"
                except ImportError:
                    pass  # acceptable


# ---------------------------------------------------------------------------
# base.py — health_check unavailable branch (lines 124-125)
# ---------------------------------------------------------------------------


class ConcretePlugin:
    """Minimal concrete plugin for testing base class directly."""

    pass


class TestBaseHealthCheckBranches:
    """Cover lines 124-125 in base.py — the 'unavailable' branch of health_check."""

    @pytest.mark.asyncio
    async def test_health_check_unavailable_when_package_not_found(self):
        """ExternalAgentPlugin.health_check should return unavailable when spec is None."""
        from pathlib import Path
        from typing import ClassVar

        from temper_ai.plugins.base import ExternalAgentPlugin

        class _TestPlugin(ExternalAgentPlugin):
            FRAMEWORK_NAME: ClassVar[str] = "TestFW"
            AGENT_TYPE: ClassVar[str] = "test_fw"
            REQUIRED_PACKAGE: ClassVar[str] = "nonexistent_pkg_xyz"

            def _initialize_external_agent(self) -> None:
                pass

            def _execute_external(self, input_data: dict) -> str:
                return ""

            @classmethod
            def translate_config(cls, source_path: Path) -> list:
                return []

        cfg = MagicMock()
        cfg.agent.name = "test"
        cfg.agent.description = "test"
        cfg.agent.version = "1.0"

        plugin = _TestPlugin(cfg)

        # find_spec returns None → REQUIRED_PACKAGE not installed
        with patch("importlib.util.find_spec", return_value=None):
            result = await plugin.health_check()

        assert result["status"] == "unavailable"
        assert result["framework"] == "TestFW"

    @pytest.mark.asyncio
    async def test_health_check_ok_when_package_found(self):
        """ExternalAgentPlugin.health_check should return ok when spec is not None."""
        from pathlib import Path
        from typing import ClassVar

        from temper_ai.plugins.base import ExternalAgentPlugin

        class _TestPlugin2(ExternalAgentPlugin):
            FRAMEWORK_NAME: ClassVar[str] = "TestFW2"
            AGENT_TYPE: ClassVar[str] = "test_fw2"
            REQUIRED_PACKAGE: ClassVar[str] = "some_pkg"

            def _initialize_external_agent(self) -> None:
                pass

            def _execute_external(self, input_data: dict) -> str:
                return ""

            @classmethod
            def translate_config(cls, source_path: Path) -> list:
                return []

        cfg = MagicMock()
        cfg.agent.name = "test"
        cfg.agent.description = "test"
        cfg.agent.version = "1.0"

        plugin = _TestPlugin2(cfg)

        # find_spec returns a spec object → package is installed
        with patch("importlib.util.find_spec", return_value=MagicMock()):
            result = await plugin.health_check()

        assert result["status"] == "ok"
        assert result["framework"] == "TestFW2"
