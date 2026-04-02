"""MCP client manager — connects to MCP servers and exposes their tools.

Manages MCP server connections using AsyncExitStack. Opened in FastAPI lifespan,
persists for server lifetime. Each connected server's tools become available
to agents via MCPTool bridge instances.

Configuration via environment:
    MCP_SERVERS='[
      {"name": "searxng", "transport": "stdio", "command": "npx", "args": ["-y", "mcp-searxng"], "env": {"SEARXNG_URL": "http://localhost:8888"}},
      {"name": "fetch", "transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch"]}
    ]'
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """A single connected MCP server with its session and tool definitions."""

    def __init__(self, name: str, session: ClientSession, tools: list[dict]):
        self.name = name
        self.session = session
        self.tools = tools  # [{name, description, inputSchema}]

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on this server. Returns text result."""
        result = await self.session.call_tool(tool_name, arguments=arguments)
        # Extract text from content blocks
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else ""


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    Usage:
        manager = MCPClientManager()
        await manager.start()          # connects to all configured servers
        tools = manager.get_all_tools() # returns MCPTool instances
        await manager.stop()           # closes all connections
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._connections: dict[str, MCPServerConnection] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        if self._event_loop is None:
            self._event_loop = asyncio.get_running_loop()
        return self._event_loop

    async def start(self) -> None:
        """Connect to all MCP servers defined in MCP_SERVERS env var."""
        self._event_loop = asyncio.get_running_loop()
        servers_json = os.environ.get("MCP_SERVERS", "[]")

        try:
            servers = json.loads(servers_json)
        except json.JSONDecodeError:
            logger.warning("Invalid MCP_SERVERS JSON, skipping MCP setup")
            return

        for server_config in servers:
            name = server_config.get("name", "unnamed")
            try:
                await self._connect_server(server_config)
                logger.info("MCP server '%s' connected (%d tools)",
                            name, len(self._connections[name].tools))
            except Exception as e:
                logger.warning("Failed to connect MCP server '%s': %s", name, e)

    async def stop(self) -> None:
        """Close all MCP server connections."""
        await self._exit_stack.aclose()
        self._connections.clear()

    async def _connect_server(self, config: dict) -> None:
        """Connect to a single MCP server."""
        name = config["name"]
        transport = config.get("transport", "stdio")

        if transport == "stdio":
            session = await self._connect_stdio(config)
        elif transport in ("http", "streamable_http"):
            session = await self._connect_http(config)
        else:
            raise ValueError(f"Unknown MCP transport: {transport}")

        # List available tools
        tools_result = await session.list_tools()
        tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            }
            for tool in tools_result.tools
        ]

        self._connections[name] = MCPServerConnection(name, session, tools)

    async def _connect_stdio(self, config: dict) -> ClientSession:
        """Connect via stdio transport (launches subprocess)."""
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env"),
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        return session

    async def _connect_http(self, config: dict) -> ClientSession:
        """Connect via streamable HTTP transport."""
        from mcp.client.streamable_http import streamable_http_client

        url = config["url"]
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(url)
        )
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        return session

    def get_connection(self, server_name: str) -> MCPServerConnection | None:
        """Get a connected server by name."""
        return self._connections.get(server_name)

    def get_all_connections(self) -> dict[str, MCPServerConnection]:
        """Get all connected servers."""
        return dict(self._connections)

    def get_all_tool_definitions(self) -> list[dict]:
        """Get all tools across all servers, prefixed with server name."""
        all_tools = []
        for server_name, conn in self._connections.items():
            for tool in conn.tools:
                all_tools.append({
                    "server": server_name,
                    "name": tool["name"],
                    "full_name": f"{server_name}.{tool['name']}",
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                })
        return all_tools


# Singleton — initialized in server lifespan
mcp_manager = MCPClientManager()
