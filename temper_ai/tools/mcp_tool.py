"""MCP tool bridge — wraps an MCP server tool as a Temper BaseTool.

Agents see MCP tools the same as native tools. The bridge handles:
- Lazy connection (server connects on first tool call, not at startup)
- Sync→async execution (agent runs sync, MCP SDK is async)
- Result extraction (MCP content blocks → string)

MCPTool does NOT hold a connection reference. It calls mcp_manager.call_tool()
which handles connect-on-demand.
"""

import asyncio
import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MCPTool(BaseTool):
    """Wraps a single MCP tool as a Temper BaseTool.

    The tool knows its server name and tool name. On execute(), it asks
    the MCPClientManager to connect (if needed) and call the tool.
    """

    modifies_state = False

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict,
        mcp_manager: Any,  # MCPClientManager
        event_loop: asyncio.AbstractEventLoop,
    ):
        super().__init__()
        self.name = f"{server_name}.{tool_name}"
        self.description = description
        self.parameters = input_schema
        self._server_name = server_name
        self._tool_name = tool_name
        self._manager = mcp_manager
        self._event_loop = event_loop

    def execute(self, **params: Any) -> ToolResult:
        """Execute the MCP tool. Connects to server on first call."""
        # Handle _raw fallback from malformed JSON parsing
        if "_raw" in params and len(params) == 1:
            import json as _json
            try:
                raw = params["_raw"]
                # Try to parse the raw string as JSON
                if not raw.startswith("{"):
                    raw = "{" + raw
                if not raw.endswith("}"):
                    raw = raw + "}"
                params = _json.loads(raw)
            except Exception:
                logger.warning("MCP tool '%s': could not recover _raw args: %s", self.name, params["_raw"][:100])

        logger.debug("MCP tool '%s' called with params: %s", self.name, {k: str(v)[:50] for k, v in params.items()})
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._manager.call_tool(self._server_name, self._tool_name, params),
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


def create_mcp_tools_from_agents(
    mcp_manager: Any,
    agent_configs: list[dict] | None = None,
) -> dict[str, MCPTool]:
    """Create MCPTool instances for MCP tools referenced in agent configs.

    Scans agent configs for tools with dots (e.g., "searxng.web_search").
    Creates a placeholder MCPTool for each — no server connection made.
    The connection happens lazily on first execute().

    If no agent_configs provided, creates tools for all configured servers
    by connecting briefly to discover their tools (fallback behavior).
    """
    tools: dict[str, MCPTool] = {}
    configured_servers = set(mcp_manager.get_configured_servers())

    if not agent_configs:
        return tools

    for agent_cfg in agent_configs:
        for tool_ref in _extract_mcp_tool_refs(agent_cfg):
            if tool_ref in tools:
                continue
            server_name, tool_name = tool_ref.split(".", 1)
            if server_name not in configured_servers:
                continue
            # Try to get schema from MCP server config
            server_cfg = mcp_manager.get_server_config(server_name) if hasattr(mcp_manager, 'get_server_config') else {}
            tool_meta = (server_cfg.get("tools") or {}).get(tool_name, {})
            description = tool_meta.get("description", f"MCP tool from {server_name} server")
            input_schema = tool_meta.get("input_schema", {"type": "object", "properties": {}})

            tools[tool_ref] = MCPTool(
                server_name=server_name,
                tool_name=tool_name,
                description=description,
                input_schema=input_schema,
                mcp_manager=mcp_manager,
                event_loop=mcp_manager.event_loop,
            )

    return tools


def _extract_mcp_tool_refs(agent_config: dict) -> list[str]:
    """Return all dotted tool references from a single agent config."""
    inner = agent_config.get("agent", agent_config)
    return [ref for ref in inner.get("tools", []) if "." in ref]
