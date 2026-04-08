"""Tests for ScriptAgent."""

from unittest.mock import MagicMock

import pytest

from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.tools.base import ToolResult


def _make_context(tool_result=None):
    """Create a mock ExecutionContext for script agent testing."""
    ctx = MagicMock()
    ctx.run_id = "test-exec-001"
    ctx.node_path = "test_node"
    ctx.agent_name = "test_script"
    ctx.workspace_path = "/tmp"
    if tool_result:
        ctx.tool_executor.execute.return_value = tool_result
    return ctx


class TestScriptAgentBasic:
    def test_run_simple_script(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo hello",
        })
        ctx = _make_context(ToolResult(success=True, result="hello\n"))
        result = agent.run({}, ctx)
        assert result.status.value == "completed"
        assert "hello" in result.output

    def test_run_with_template_vars(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "echo {{ greeting }}",
        })
        ctx = _make_context(ToolResult(success=True, result="hi\n"))
        result = agent.run({"greeting": "hi"}, ctx)
        # Verify template was rendered (tool_executor.execute was called)
        assert ctx.tool_executor.execute.called
        # The rendered command should contain "hi"
        call_args = ctx.tool_executor.execute.call_args
        command = call_args[0][1]["command"] if len(call_args[0]) > 1 else call_args[1].get("command", "")
        if not command:
            # Try positional args format
            command = str(call_args)
        assert "hi" in command

    def test_run_script_failure(self):
        agent = ScriptAgent(config={
            "name": "failing_script",
            "script_template": "exit 1",
        })
        ctx = _make_context(ToolResult(success=False, result="", error="exit code 1"))
        result = agent.run({}, ctx)
        assert result.status.value == "failed"

    def test_run_extracts_json(self):
        agent = ScriptAgent(config={
            "name": "json_script",
            "script_template": 'echo \'{"key": "value"}\'',
        })
        ctx = _make_context(ToolResult(success=True, result='{"key": "value"}\n'))
        result = agent.run({}, ctx)
        assert result.structured_output == {"key": "value"}

    def test_run_no_json_output(self):
        agent = ScriptAgent(config={
            "name": "text_script",
            "script_template": "echo plain text",
        })
        ctx = _make_context(ToolResult(success=True, result="plain text\n"))
        result = agent.run({}, ctx)
        assert result.structured_output is None

    def test_missing_script_template(self):
        agent = ScriptAgent(config={"name": "no_template"})
        errors = agent.validate_config()
        assert len(errors) > 0
        assert any("script_template" in e for e in errors)

    def test_skip_allowlist_flag_passed(self):
        agent = ScriptAgent(config={
            "name": "test_script",
            "script_template": "set -e\necho done",
        })
        ctx = _make_context(ToolResult(success=True, result="done\n"))
        agent.run({}, ctx)
        call_args = ctx.tool_executor.execute.call_args
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        # The _skip_allowlist flag should be passed
        assert params.get("_skip_allowlist") is True
