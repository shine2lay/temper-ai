"""MCP tool names on the wire.

An MCP tool is ``server.tool`` everywhere in temper — registry key, agent
config, executor scope. Providers won't take that: Anthropic and OpenAI both
require ``^[a-zA-Z0-9_-]+$``, and a dotted name fails the request outright:

    Error code: 400 - tools.0.custom.name: String should match pattern
    '^[a-zA-Z0-9_-]{1,128}$'

So the model is shown ``server__tool`` and LLMAgent maps its answer back.
These tests pin both halves and the boundary between them.
"""

import asyncio
import re
from unittest.mock import MagicMock

from temper_ai.agent.llm_agent import LLMAgent
from temper_ai.shared.types import ExecutionContext
from temper_ai.tools.base import BaseTool, ToolResult
from temper_ai.tools.mcp_tool import MCPTool

PROVIDER_PATTERN = r"^[a-zA-Z0-9_-]{1,128}$"


def make_mcp_tool(server="playwright", tool="browser_navigate"):
    return MCPTool(
        server_name=server,
        tool_name=tool,
        description="Navigate to a URL",
        input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
        mcp_manager=MagicMock(),
        event_loop=asyncio.new_event_loop(),
    )


class NativeTool(BaseTool):
    name = "read_file"
    description = "Read a file"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(success=True, result="")


def test_mcp_tool_keeps_its_dotted_identity():
    """The dot is what configs declare and the executor scopes on — it stays."""
    tool = make_mcp_tool()
    assert tool.name == "playwright.browser_navigate"


def test_the_name_the_model_sees_passes_the_provider_pattern():
    tool = make_mcp_tool()
    assert tool.llm_name == "playwright__browser_navigate"
    assert re.match(PROVIDER_PATTERN, tool.llm_name)
    assert not re.match(PROVIDER_PATTERN, tool.name), "the dotted name is the thing providers reject"


def test_schema_sent_to_the_model_carries_the_wire_name():
    tool = make_mcp_tool()
    tool._discovered = True  # skip the server round-trip
    assert tool.to_llm_schema()["function"]["name"] == "playwright__browser_navigate"


def test_a_native_tool_is_unaffected():
    """Native names already fit the pattern, so llm_name is an identity."""
    tool = NativeTool()
    assert tool.llm_name == tool.name == "read_file"
    assert tool.to_llm_schema()["function"]["name"] == "read_file"


def _agent_with(tool, declared):
    agent = LLMAgent({"name": "verifier", "tools": [declared], "system_prompt": "x"})
    executor = MagicMock()
    executor.get_tool.return_value = tool
    executor.execute.return_value = ToolResult(success=True, result="ok")
    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="browser_verify",
        node_path="verify",
        agent_name="verifier",
        event_recorder=MagicMock(),
        tool_executor=executor,
    )
    return agent, executor, ctx


def test_model_answer_is_mapped_back_to_the_dotted_name_before_executing():
    """The round trip: shown ``playwright__browser_navigate``, executed as
    ``playwright.browser_navigate`` — otherwise the executor has no such tool
    and the call dies as 'not declared by agent'."""
    tool = make_mcp_tool()
    agent, executor, ctx = _agent_with(tool, "playwright.browser_navigate")

    execute_tool = agent._make_tool_executor(ctx, {})
    execute_tool("playwright__browser_navigate", {"url": "https://example.test"})

    name, params = executor.execute.call_args[0][:2]
    assert name == "playwright.browser_navigate"
    assert params == {"url": "https://example.test"}
    assert executor.execute.call_args[1]["allowed_tools"] == ("playwright.browser_navigate",)


def test_a_native_name_passes_through_untouched():
    tool = NativeTool()
    agent, executor, ctx = _agent_with(tool, "read_file")

    agent._make_tool_executor(ctx, {})("read_file", {"path": "a.txt"})

    assert executor.execute.call_args[0][0] == "read_file"


def test_an_undeclared_wire_name_is_not_smuggled_in_by_the_map():
    """The map is built from the declared list only, so a name the agent never
    declared arrives at the executor unchanged — and its scope check refuses it."""
    tool = make_mcp_tool()
    agent, executor, ctx = _agent_with(tool, "playwright.browser_navigate")

    agent._make_tool_executor(ctx, {})("github__create_pull_request", {})

    assert executor.execute.call_args[0][0] == "github__create_pull_request"
    assert executor.execute.call_args[1]["allowed_tools"] == ("playwright.browser_navigate",)
