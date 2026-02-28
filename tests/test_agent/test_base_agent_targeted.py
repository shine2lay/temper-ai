"""Targeted tests for agent/base_agent.py to improve coverage from 70% to 90%+.

Covers: _register_mcp_tools, _sync_tool_configs_to_executor, _make_stream_callback,
        aexecute async path, _arun default wrapper, _render_template edge cases,
        _create_tool_registry, load_tools_from_config.
"""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.agent.base_agent import (
    AgentResponse,
    BaseAgent,
    ExecutionContext,
    _register_mcp_tools,
    _sync_tool_configs_to_executor,
    load_tools_from_config,
)

# ---------------------------------------------------------------------------
# _register_mcp_tools
# ---------------------------------------------------------------------------


class TestRegisterMcpTools:
    def test_returns_none_when_no_configs(self):
        registry = MagicMock()
        result = _register_mcp_tools(None, registry)
        assert result is None

    def test_returns_none_when_empty_configs(self):
        registry = MagicMock()
        result = _register_mcp_tools([], registry)
        assert result is None

    def test_import_error_returns_none_and_warns(self):
        registry = MagicMock()
        with patch.dict("sys.modules", {"temper_ai.mcp.manager": None}):
            result = _register_mcp_tools([{"server": "test"}], registry)
        assert result is None

    def test_successful_registration(self):
        registry = MagicMock()
        mock_manager = MagicMock()
        mock_tool1 = MagicMock()
        mock_tool2 = MagicMock()
        mock_manager.connect_all.return_value = [mock_tool1, mock_tool2]

        with patch(
            "temper_ai.mcp.manager.MCPManager",
            return_value=mock_manager,
        ):
            result = _register_mcp_tools([{"server": "mcp://test"}], registry)

        assert result is mock_manager
        assert registry.register.call_count == 2


# ---------------------------------------------------------------------------
# _sync_tool_configs_to_executor
# ---------------------------------------------------------------------------


class TestSyncToolConfigsToExecutor:
    def test_no_executor_registry_does_nothing(self):
        agent_registry = MagicMock()
        tool_executor = MagicMock(spec=[])  # no registry attr
        # Should not raise
        _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

    def test_no_tools_in_registry_does_nothing(self):
        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {}
        tool_executor = MagicMock()
        tool_executor.registry = MagicMock()

        _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        tool_executor.registry.get.assert_not_called()

    def test_syncs_config_to_executor_tool(self):
        # Tool with config in agent registry
        agent_tool = MagicMock()
        agent_tool.config = {"allowed_root": "/tmp", "max_size": 1024}

        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {"bash": agent_tool}

        exec_tool = MagicMock()
        exec_registry = MagicMock()
        exec_registry.get.return_value = exec_tool

        tool_executor = MagicMock()
        tool_executor.registry = exec_registry

        with patch("temper_ai.agent.base_agent.apply_tool_config") as mock_apply:
            _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        mock_apply.assert_called_once()

    def test_skips_tools_without_config(self):
        agent_tool = MagicMock()
        agent_tool.config = None

        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {"bash": agent_tool}

        tool_executor = MagicMock()
        tool_executor.registry = MagicMock()

        with patch("temper_ai.agent.base_agent.apply_tool_config") as mock_apply:
            _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        mock_apply.assert_not_called()

    def test_skips_tools_with_non_dict_config(self):
        agent_tool = MagicMock()
        agent_tool.config = "not-a-dict"

        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {"bash": agent_tool}

        tool_executor = MagicMock()
        tool_executor.registry = MagicMock()

        with patch("temper_ai.agent.base_agent.apply_tool_config") as mock_apply:
            _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        mock_apply.assert_not_called()

    def test_skips_internal_config_keys(self):
        agent_tool = MagicMock()
        agent_tool.config = {"_internal_key": "value"}  # all internal

        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {"bash": agent_tool}

        tool_executor = MagicMock()
        tool_executor.registry = MagicMock()

        with patch("temper_ai.agent.base_agent.apply_tool_config") as mock_apply:
            _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        mock_apply.assert_not_called()

    def test_skips_when_executor_tool_not_found(self):
        agent_tool = MagicMock()
        agent_tool.config = {"allowed_root": "/tmp"}

        agent_registry = MagicMock()
        agent_registry.get_all_tools.return_value = {"bash": agent_tool}

        exec_registry = MagicMock()
        exec_registry.get.return_value = None  # tool not found

        tool_executor = MagicMock()
        tool_executor.registry = exec_registry

        with patch("temper_ai.agent.base_agent.apply_tool_config") as mock_apply:
            _sync_tool_configs_to_executor(agent_registry, tool_executor, "agent1")

        mock_apply.assert_not_called()


# ---------------------------------------------------------------------------
# Minimal concrete agent for testing abstract methods
# ---------------------------------------------------------------------------


class ConcreteAgent(BaseAgent):
    """Test implementation of BaseAgent."""

    def _run(self, input_data, context, start_time):
        return self._build_response(
            output="test output",
            reasoning=None,
            tool_calls=[],
            tokens=10,
            cost=0.01,
            start_time=start_time,
        )

    def get_capabilities(self):
        return {"name": self.name, "type": "concrete"}


def _make_concrete_agent(config):
    with patch("temper_ai.agent.base_agent.ToolRegistry"):
        with patch("temper_ai.agent.base_agent.create_llm_from_config"):
            return ConcreteAgent(config)


# ---------------------------------------------------------------------------
# aexecute and _arun
# ---------------------------------------------------------------------------


class TestAExecute:
    @pytest.mark.asyncio
    async def test_aexecute_returns_agent_response(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        result = await agent.aexecute({"input": "test"})
        assert isinstance(result, AgentResponse)
        assert result.output == "test output"

    @pytest.mark.asyncio
    async def test_aexecute_calls_on_after_run(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        on_after_run_called = []

        original = agent._on_after_run

        def mock_on_after_run(result):
            on_after_run_called.append(True)
            return original(result)

        agent._on_after_run = mock_on_after_run
        await agent.aexecute({"input": "test"})
        assert len(on_after_run_called) == 1

    @pytest.mark.asyncio
    async def test_aexecute_error_uses_on_error_hook(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)

        def bad_run(input_data, context, start_time):
            raise RuntimeError("async run failed")

        agent._run = bad_run
        result = await agent.aexecute({"input": "test"})
        assert isinstance(result, AgentResponse)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_arun_default_wraps_sync_run_in_thread(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        # _arun default implementation should call _run via asyncio.to_thread
        result = await agent._arun({"input": "test"}, None, 0.0)
        assert isinstance(result, AgentResponse)

    @pytest.mark.asyncio
    async def test_aexecute_with_context(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        ctx = ExecutionContext(workflow_id="wf-1", stage_id="s1", agent_id="a1")
        result = await agent.aexecute({"input": "test"}, context=ctx)
        assert isinstance(result, AgentResponse)


# ---------------------------------------------------------------------------
# _make_stream_callback
# ---------------------------------------------------------------------------


class TestMakeStreamCallback:
    def test_returns_none_when_no_callback_or_observer(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent._stream_callback = None
        agent._observer = None
        result = agent._make_stream_callback()
        assert result is None

    def test_returns_callback_when_user_cb_present(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        user_cb = MagicMock()
        agent._stream_callback = user_cb
        agent._observer = MagicMock()
        agent._observer.active = False

        result = agent._make_stream_callback()
        assert result is not None
        assert callable(result)

    def test_combined_callback_forwards_to_user(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        user_cb = MagicMock()
        agent._stream_callback = user_cb

        mock_observer = MagicMock()
        mock_observer.active = False
        agent._observer = mock_observer

        callback = agent._make_stream_callback()
        chunk = MagicMock()
        callback(chunk)

        user_cb.assert_called_once_with(chunk)

    def test_combined_callback_user_exception_swallowed(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        user_cb = MagicMock(side_effect=RuntimeError("stream error"))
        agent._stream_callback = user_cb

        mock_observer = MagicMock()
        mock_observer.active = False
        agent._observer = mock_observer

        callback = agent._make_stream_callback()
        chunk = MagicMock()
        # Should not raise
        callback(chunk)

    def test_combined_callback_forwards_to_observer(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent._stream_callback = None

        mock_observer = MagicMock()
        mock_observer.active = True
        agent._observer = mock_observer

        callback = agent._make_stream_callback()
        assert callback is not None

        chunk = MagicMock()
        chunk.content = "text"
        chunk.chunk_type = "content"
        chunk.done = False
        chunk.model = "gpt-4"
        chunk.prompt_tokens = 10
        chunk.completion_tokens = 5

        callback(chunk)
        mock_observer.emit_stream_chunk.assert_called_once()

    def test_observer_emit_exception_swallowed(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent._stream_callback = None

        mock_observer = MagicMock()
        mock_observer.active = True
        mock_observer.emit_stream_chunk.side_effect = RuntimeError("observer error")
        agent._observer = mock_observer

        callback = agent._make_stream_callback()
        chunk = MagicMock()
        chunk.content = "text"
        chunk.chunk_type = "content"
        chunk.done = False
        chunk.model = None
        chunk.prompt_tokens = None
        chunk.completion_tokens = None

        # Should not raise
        callback(chunk)


# ---------------------------------------------------------------------------
# _render_template
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_render_inline_prompt(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        # inline prompt is "You are a helpful assistant. {{input}}"
        with patch.object(agent.prompt_engine, "render", return_value="rendered"):
            result = agent._render_template({"input": "test"})
        assert result == "rendered"

    def test_no_prompt_raises_value_error(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent.config.agent.prompt = None
        with pytest.raises(ValueError, match="No prompt configured"):
            agent._render_template({})

    def test_no_template_or_inline_raises(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent.config.agent.prompt.inline = None
        agent.config.agent.prompt.template = None
        with pytest.raises(ValueError, match="No prompt template"):
            agent._render_template({})

    def test_template_file_render_error_wrapped(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent.config.agent.prompt.template = "some_template.j2"
        agent.config.agent.prompt.inline = None

        with patch.object(
            agent.prompt_engine,
            "render_file",
            side_effect=FileNotFoundError("not found"),
        ):
            from temper_ai.llm.prompts.validation import PromptRenderError

            with pytest.raises(PromptRenderError, match="Failed to render"):
                agent._render_template({})


# ---------------------------------------------------------------------------
# _validate_input
# ---------------------------------------------------------------------------


class TestValidateInput:
    def test_none_input_raises_value_error(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        with pytest.raises(ValueError, match="cannot be None"):
            agent._validate_input(None)

    def test_non_dict_raises_type_error(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        with pytest.raises(TypeError, match="must be a dictionary"):
            agent._validate_input("not a dict")

    def test_invalid_context_raises_type_error(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        with pytest.raises(TypeError, match="must be an ExecutionContext"):
            agent._validate_input({}, context="not a context")


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


class TestValidateConfig:
    def test_valid_config_returns_true(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        assert agent.validate_config() is True

    def test_missing_name_raises(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent.config.agent.__dict__["name"] = ""
        with pytest.raises(ValueError, match="Agent name is required"):
            agent.validate_config()

    def test_missing_prompt_raises(self, minimal_agent_config):
        agent = _make_concrete_agent(minimal_agent_config)
        agent.config.agent.__dict__["prompt"] = None
        with pytest.raises(ValueError, match="Prompt configuration is required"):
            agent.validate_config()


# ---------------------------------------------------------------------------
# load_tools_from_config
# ---------------------------------------------------------------------------


class TestLoadToolsFromConfig:
    def test_unknown_tool_raises(self):
        registry = MagicMock()
        registry.list_tools.return_value = ["bash", "web_search"]
        registry.get.return_value = None  # tool not found

        with patch("temper_ai.agent.base_agent.ensure_tools_discovered"):
            with patch(
                "temper_ai.agent.base_agent.resolve_tool_spec",
                return_value=("unknown_tool", {}),
            ):
                with pytest.raises(ValueError, match="Unknown tool"):
                    load_tools_from_config(registry, ["unknown_tool"])

    def test_removes_unconfigured_tools(self):
        mock_tool = MagicMock()
        mock_tool.config = {}

        registry = MagicMock()
        registry.list_tools.return_value = ["bash", "web_search"]
        registry.get.return_value = mock_tool

        with patch("temper_ai.agent.base_agent.ensure_tools_discovered"):
            with patch(
                "temper_ai.agent.base_agent.resolve_tool_spec",
                return_value=("bash", {}),
            ):
                with patch("temper_ai.agent.base_agent.apply_tool_config"):
                    load_tools_from_config(registry, ["bash"])

        # web_search should be unregistered (not in configured_names)
        registry.unregister.assert_called_with("web_search")
