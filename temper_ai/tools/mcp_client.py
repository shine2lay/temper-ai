"""MCP client manager — lazy-connecting MCP server manager.

Servers are configured via YAML files in configs/mcp_servers/.
Connections are NOT made at startup — only when an agent first calls
a tool from that server. This means 100 configured servers = 0 subprocesses
until tools are actually used.

Config format:
    configs/mcp_servers/searxng.yaml:
        mcp_server:
          name: searxng
          transport: stdio
          command: npx
          args: ["-y", "mcp-searxng"]
          env:
            SEARXNG_URL: ${SEARXNG_URL:http://localhost:8888}
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """A single connected MCP server with its session."""

    def __init__(self, name: str, session: ClientSession):
        self.name = name
        self.session = session

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on this server. Returns text result."""
        result = await self.session.call_tool(tool_name, arguments=arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts) if parts else ""


class MCPClientManager:
    """Manages MCP server configs and lazy connections.

    At startup: loads configs from YAML files (no connections made).
    On first tool call: connects to the server, then executes.
    Subsequent calls: reuses the existing connection.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._server_configs: dict[str, dict] = {}  # name -> config dict
        self._connections: dict[str, MCPServerConnection] = {}  # name -> live connection
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._connect_locks: dict[str, asyncio.Lock] = {}  # prevent concurrent connects

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        if self._event_loop is None:
            self._event_loop = asyncio.get_running_loop()
        return self._event_loop

    async def start(self, config_dir: str | None = None) -> None:
        """Load MCP server configs (no connections made).

        Loads from:
        1. YAML files in configs/mcp_servers/*.yaml
        2. MCP_SERVERS env var (JSON array, backwards compat)
        """
        self._event_loop = asyncio.get_running_loop()
        servers: list[dict] = []

        servers.extend(_load_mcp_configs(config_dir))

        env_json = os.environ.get("MCP_SERVERS", "[]")
        try:
            env_servers = json.loads(env_json)
            if env_servers:
                servers.extend(env_servers)
        except json.JSONDecodeError:
            pass

        for config in servers:
            name = config.get("name", "unnamed")
            if name not in self._server_configs:
                self._server_configs[name] = config
                self._connect_locks[name] = asyncio.Lock()

        if self._server_configs:
            logger.info("MCP: %d servers configured (lazy connect)",
                        len(self._server_configs))

    async def stop(self) -> None:
        """Close all active MCP server connections."""
        await self._exit_stack.aclose()
        self._connections.clear()

    async def ensure_connected(self, server_name: str) -> MCPServerConnection:
        """Connect to a server if not already connected. Returns the connection."""
        if server_name in self._connections:
            return self._connections[server_name]

        if server_name not in self._server_configs:
            raise ValueError(
                f"MCP server '{server_name}' not configured. "
                f"Available: {sorted(self._server_configs.keys())}"
            )

        lock = self._connect_locks[server_name]
        async with lock:
            # Double-check after acquiring lock
            if server_name in self._connections:
                return self._connections[server_name]

            config = self._server_configs[server_name]
            transport = config.get("transport", "stdio")

            if transport == "stdio":
                session = await self._connect_stdio(config)
            elif transport in ("http", "streamable_http"):
                session = await self._connect_http(config)
            else:
                raise ValueError(f"Unknown MCP transport: {transport}")

            connection = MCPServerConnection(server_name, session)
            self._connections[server_name] = connection
            logger.info("MCP server '%s' connected on first use", server_name)
            return connection

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Connect if needed, then call a tool. The main entry point for MCPTool."""
        connection = await self.ensure_connected(server_name)
        return await connection.call_tool(tool_name, arguments)

    async def _connect_stdio(self, config: dict) -> ClientSession:
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
        from mcp.client.streamable_http import streamable_http_client

        url = config["url"]
        read, write, _ = await self._exit_stack.enter_async_context(
            streamable_http_client(url)
        )
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        return session

    def get_configured_servers(self) -> list[str]:
        """List all configured server names (connected or not)."""
        return sorted(self._server_configs.keys())

    def get_active_connections(self) -> dict[str, MCPServerConnection]:
        """List only currently connected servers."""
        return dict(self._connections)


def _load_mcp_configs(config_dir: str | None = None) -> list[dict]:
    """Load MCP server configs from configs/mcp_servers/*.yaml files."""
    from pathlib import Path

    import yaml

    from temper_ai.config.helpers import substitute_env_vars

    if config_dir:
        mcp_dir = Path(config_dir) / "mcp_servers"
    else:
        mcp_dir = Path(__file__).parent.parent.parent / "configs" / "mcp_servers"

    if not mcp_dir.is_dir():
        return []

    servers = []
    for yaml_file in sorted(mcp_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                raw = yaml.safe_load(f)
            if not raw:
                continue
            config = raw.get("mcp_server", raw)
            config = substitute_env_vars(config)
            servers.append(config)
        except Exception as e:
            logger.warning("Failed to load MCP config %s: %s", yaml_file, e)

    return servers


# Singleton
mcp_manager = MCPClientManager()
