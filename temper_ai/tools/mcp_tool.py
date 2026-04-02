"""MCP tool bridge — wraps an MCP server tool as a Temper BaseTool.

Agents see MCP tools the same as native tools. The bridge handles:
- Schema translation (MCP inputSchema → OpenAI function format)
- Sync→async execution (agent runs sync, MCP SDK is async)
- Result extraction (MCP content blocks → string)
"""

import asyncio
import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """Wraps a single MCP tool as a Temper BaseTool.

    Created by MCPClientManager for each tool discovered on connected servers.
    The agent sees it as a regular tool — same schema, same execute() interface.
    """

    modifies_state = False  # Conservative default — MCP tools are read-only unless stated

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict,
        mcp_connection: Any,  # MCPServerConnection
        event_loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self.name = f"{server_name}.{tool_name}"
        self.description = description
        self.parameters = input_schema
        self._tool_name = tool_name  # raw name on the MCP server
        self._connection = mcp_connection
        self._event_loop = event_loop

    def execute(self, **params: Any) -> ToolResult:
        """Execute the MCP tool synchronously.

        Bridges to async MCP SDK via run_coroutine_threadsafe.
        This works because agents run in ThreadPoolExecutor threads
        while the event loop runs on the main thread.
        """
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._connection.call_tool(self._tool_name, params),
                self._event_loop,
            )
            result_text = future.result(timeout=30)
            return ToolResult(success=True, result=result_text)
        except asyncio.TimeoutError:
            error = f"MCP tool '{self.name}' timed out after 30s"
            logger.warning(error)
            return ToolResult(success=False, result="", error=error)
        except Exception as e:
            error = f"MCP tool '{self.name}' failed: {e}"
            logger.warning(error)
            return ToolResult(success=False, result="", error=error)


def create_mcp_tools(mcp_manager: Any) -> dict[str, MCPTool]:
    """Create MCPTool instances for all tools across all connected MCP servers.

    Returns a dict of {full_name: MCPTool} ready to register with ToolExecutor.
    """
    tools: dict[str, MCPTool] = {}

    for server_name, connection in mcp_manager.get_all_connections().items():
        for tool_def in connection.tools:
            full_name = f"{server_name}.{tool_def['name']}"
            tools[full_name] = MCPTool(
                server_name=server_name,
                tool_name=tool_def["name"],
                description=tool_def["description"],
                input_schema=tool_def["inputSchema"],
                mcp_connection=connection,
                event_loop=mcp_manager.event_loop,
            )

    return tools
