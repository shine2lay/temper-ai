"""Integration tests — MCP tools alongside native tools in ToolRegistry."""

from unittest.mock import MagicMock, patch

from temper_ai.mcp._schemas import MCPServerConfig
from temper_ai.tools.base import ParameterValidationResult, ToolResult
from temper_ai.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_info(name="do_thing", description="Does a thing"):
    ti = MagicMock()
    ti.name = name
    ti.description = description
    ti.inputSchema = {"type": "object", "properties": {}}
    ti.annotations = None
    return ti


def _make_mcp_wrapper(name="gh", tool_name="create_pr"):
    from temper_ai.mcp.tool_wrapper import MCPToolWrapper

    ti = _make_tool_info(name=tool_name)
    loop = MagicMock()
    wrapper = MCPToolWrapper(
        tool_info=ti,
        session=MagicMock(),
        namespace=name,
        call_timeout=30,
        event_loop=loop,
    )
    return wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCPToolsInRegistry:
    def test_mcp_tools_register_alongside_native_tools(self):
        """MCPToolWrapper instances can coexist in ToolRegistry with native tools."""
        from temper_ai.tools.bash import Bash

        registry = ToolRegistry(auto_discover=False)
        bash = Bash()
        registry.register(bash)

        mcp_tool = _make_mcp_wrapper(name="gh", tool_name="create_pr")
        registry.register(mcp_tool, allow_override=False)

        assert "Bash" in registry.list_tools()
        assert "gh__create_pr" in registry.list_tools()

    def test_mcp_tools_appear_in_list_tools(self):
        registry = ToolRegistry(auto_discover=False)
        mcp_tool = _make_mcp_wrapper(name="fs", tool_name="read_file")
        registry.register(mcp_tool)

        tools = registry.list_tools()
        assert "fs__read_file" in tools

    def test_mcp_tools_appear_in_get_all_tool_schemas(self):
        registry = ToolRegistry(auto_discover=False)
        mcp_tool = _make_mcp_wrapper(name="gh", tool_name="list_issues")
        registry.register(mcp_tool)

        schemas = registry.get_all_tool_schemas()
        names = [s["function"]["name"] for s in schemas]
        assert "gh__list_issues" in names

    def test_safe_execute_contract_on_mcp_wrapper(self):
        """safe_execute() must return ToolResult, never raise."""
        from temper_ai.mcp.tool_wrapper import MCPToolWrapper

        ti = _make_tool_info()
        loop = MagicMock()

        wrapper = MCPToolWrapper(
            tool_info=ti,
            session=MagicMock(),
            namespace="ns",
            call_timeout=5,
            event_loop=loop,
        )

        with patch.object(
            wrapper,
            "validate_params",
            return_value=ParameterValidationResult(valid=True),
        ):
            with patch.object(
                wrapper, "execute", side_effect=RuntimeError("mcp exploded")
            ):
                result = wrapper.safe_execute()

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "mcp exploded" in result.error


class TestAgentConfigMCPServers:
    """Verify AgentConfigInner.mcp_servers parses dicts into MCPServerConfig."""

    def _make_agent_config_dict(self, mcp_servers=None):
        base = {
            "agent": {
                "name": "test-agent",
                "description": "A test agent",
                "inference": {
                    "provider": "openai",
                    "model": "gpt-4",
                    "api_key_ref": "${env:OPENAI_API_KEY}",
                },
                "prompt": {"inline": "You are a helpful assistant."},
                "error_handling": {
                    "retry_strategy": "ExponentialBackoff",
                    "escalate_to_human_after": 3,
                    "fallback": "GracefulDegradation",
                },
            }
        }
        if mcp_servers is not None:
            base["agent"]["mcp_servers"] = mcp_servers
        return base

    def test_mcp_servers_none_by_default(self):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        data = self._make_agent_config_dict()
        config = AgentConfig(**data)
        assert config.agent.mcp_servers is None

    def test_mcp_servers_dict_parsed_to_mcp_server_config(self):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        data = self._make_agent_config_dict(
            mcp_servers=[{"name": "gh", "command": "npx", "args": ["-y", "server-gh"]}]
        )
        config = AgentConfig(**data)
        assert config.agent.mcp_servers is not None
        assert len(config.agent.mcp_servers) == 1
        server = config.agent.mcp_servers[0]
        assert isinstance(server, MCPServerConfig)
        assert server.name == "gh"

    def test_mcp_servers_already_config_objects_passed_through(self):
        from temper_ai.storage.schemas.agent_config import AgentConfig

        mcp_cfg = MCPServerConfig(name="fs", command="npx")
        data = self._make_agent_config_dict(mcp_servers=[mcp_cfg])
        config = AgentConfig(**data)
        assert config.agent.mcp_servers[0] is mcp_cfg


class TestBaseAgentMCPRegistration:
    """Verify _register_mcp_tools integrates into base_agent._create_tool_registry."""

    def test_register_mcp_tools_returns_none_for_empty_configs(self):
        from temper_ai.agent.base_agent import _register_mcp_tools

        registry = ToolRegistry(auto_discover=False)
        result = _register_mcp_tools(None, registry)
        assert result is None

        result2 = _register_mcp_tools([], registry)
        assert result2 is None

    def test_register_mcp_tools_graceful_import_error(self):
        """_register_mcp_tools returns None when MCPManager raises ImportError."""
        from temper_ai.agent.base_agent import _register_mcp_tools

        registry = ToolRegistry(auto_discover=False)
        cfg = MCPServerConfig(name="gh", command="npx")

        # Patch the lazy import inside _register_mcp_tools to simulate mcp not installed
        with patch.dict("sys.modules", {"temper_ai.mcp.manager": None}):
            result = _register_mcp_tools([cfg], registry)

        # Should return None, not raise
        assert result is None
