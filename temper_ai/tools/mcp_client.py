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
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, McpError, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCallOutcome:
    """What a tools/call came back with.

    ``is_error`` is the server's own verdict (MCP ``CallToolResult.isError``):
    invalid arguments, a refused/unregistered tool, a failed API call. Before
    this existed every call was reported to temper as a success, so budgets,
    observability and any safety policy saw green while the model read an
    error message.
    """

    text: str
    is_error: bool = False


class MCPServerConnection:
    """A single connected MCP server with its session and advertised tools."""

    def __init__(
        self,
        name: str,
        session: ClientSession,
        tools: dict[str, Any] | None = None,
        caller: str = "",
        closer: Callable[[], None] | None = None,
    ):
        self.name = name
        self.session = session
        # Which caller this session belongs to (see MCPClientManager._connections),
        # and how to end it: set by the manager, so closing is the owner's to do.
        self.caller = caller
        self._closer = closer
        # name -> mcp.types.Tool, from tools/list at connect time. This is the
        # source of truth for descriptions and input schemas; nothing in YAML
        # needs to (or should) repeat it.
        self.tools: dict[str, Any] = dict(tools or {})

    async def refresh_tools(self) -> dict[str, Any]:
        """(Re)fetch the server's tool list, following pagination."""
        tools: dict[str, Any] = {}
        cursor: str | None = None
        while True:
            page = await self.session.list_tools(cursor)
            for tool in page.tools:
                tools[tool.name] = tool
            cursor = page.nextCursor
            if not cursor:
                break
        self.tools = tools
        return tools

    def request_close(self) -> None:
        """Ask the task holding this session open to end it."""
        if self._closer is not None:
            self._closer()

    async def call_tool(self, tool_name: str, arguments: dict) -> ToolCallOutcome:
        """Call a tool on this server. Returns the text content and the server's error verdict."""
        result = await self.session.call_tool(tool_name, arguments=arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return ToolCallOutcome(text="\n".join(parts) if parts else "", is_error=bool(result.isError))


def _session_is_dead(exc: McpError) -> bool:
    """An McpError that means the session, not the call, is gone."""
    text = str(exc).lower()
    return "session terminated" in text or "session not found" in text


class MCPClientManager:
    """Manages MCP server configs and lazy connections.

    At startup: loads configs from YAML files (no connections made).
    On first tool call: connects to the server, then executes.
    Subsequent calls by the same caller: reuses that caller's connection.

    A connection is keyed by ``(server, caller)``, not by server. An MCP session
    is not a stateless pipe: it is a browser profile with its cookies and its
    current page, a server's notion of "the" working directory, whatever the last
    call left behind. Keyed by server alone, every agent in a run shared one, and
    since nodes at the same level run concurrently (see stage/executor.py), three
    walkers pointed at one browser take turns clobbering each other's page --
    playwright's ``--isolated`` cannot help, because isolation is per session and
    there was only ever one session to isolate. Per caller, "my browser" means
    mine, and `release` at the end of a node ends it instead of leaving it open
    for whoever runs next.

    The empty caller is the shared session: schema discovery (`get_tool_meta`)
    and the run's preconnect check use it, neither of which leaves state behind.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._server_configs: dict[str, dict] = {}  # name -> config dict
        # (server, caller) -> live connection. Caller "" is the shared session.
        self._connections: dict[tuple[str, str], MCPServerConnection] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        # (server, caller) -> lock, so one session is never opened twice and two
        # callers opening their own do not queue behind each other.
        self._connect_locks: dict[tuple[str, str], asyncio.Lock] = {}
        # (server, caller) -> the task holding that session's contexts open.
        self._holders: dict[tuple[str, str], asyncio.Task] = {}

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

        if self._server_configs:
            logger.info("MCP: %d servers configured (lazy connect)",
                        len(self._server_configs))

    async def stop(self) -> None:
        """Close all active MCP server connections."""
        for key in list(self._connections):
            await self._close(key)
        await self._exit_stack.aclose()
        self._connections.clear()

    async def release(self, caller: str) -> None:
        """End every session this caller opened.

        Called when an agent finishes (stage/agent_node.py). Nothing will use
        those sessions again, and a browser left open holds its context, its
        profile and its memory for the life of the process — a long run would
        accumulate one per node. The shared session (caller "") is not a
        caller's to end: it belongs to the run.
        """
        if not caller:
            return
        for key in [k for k in self._connections if k[1] == caller]:
            await self._close(key)
            logger.info("MCP server '%s' released by %s", key[0], caller)

    async def _close(self, key: tuple[str, str]) -> None:
        """Close one session: ask its holder task to unwind, then wait for it."""
        connection = self._connections.pop(key, None)
        holder = self._holders.pop(key, None)
        if connection is not None:
            connection.request_close()
        if holder is None:
            return
        try:
            await asyncio.wait_for(holder, timeout=10)
        except TimeoutError:
            logger.warning("MCP session %s did not close within 10s; abandoned", key)
        except Exception as exc:  # noqa: BLE001 — teardown is best effort
            logger.warning("MCP session %s closed with an error: %s", key, exc)

    async def ensure_connected(
        self, server_name: str, caller: str = ""
    ) -> MCPServerConnection:
        """Connect this caller's session if it has none. Returns the connection."""
        key = (server_name, caller)
        if key in self._connections:
            return self._connections[key]

        if server_name not in self._server_configs:
            raise ValueError(
                f"MCP server '{server_name}' not configured. "
                f"Available: {sorted(self._server_configs.keys())}"
            )

        # Per key, not per server: the lock exists to stop one session being
        # opened twice, and two callers opening their own must not queue behind
        # each other (three walkers starting three browsers start them at once).
        lock = self._connect_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Double-check after acquiring lock
            if key in self._connections:
                return self._connections[key]

            connection = await self._open(server_name, caller)
            self._connections[key] = connection
            logger.info(
                "MCP server '%s' connected for %s (%d tools advertised)",
                server_name, caller or "shared use", len(connection.tools),
            )
            return connection

    async def _open(self, server_name: str, caller: str) -> MCPServerConnection:
        """Open one session, held open by a task of its own.

        The session's contexts — the subprocess pipes or HTTP stream, then the
        ClientSession — are entered and exited inside a single task on purpose.
        They are anyio cancel scopes, and anyio refuses to unwind one in a task
        other than the one that entered it ("Attempted to exit cancel scope in a
        different task than it was entered in"). Every call into this manager
        arrives on a task of its own via run_coroutine_threadsafe, so a session
        entered by whichever call happened to be first could not be closed by any
        other — which is exactly what releasing a caller's session has to do, at
        every node boundary. The holder task enters the stack, hands the ready
        connection back, and then does nothing but wait to be told to unwind.
        """
        config = self._server_configs[server_name]
        transport = config.get("transport", "stdio")
        loop = asyncio.get_running_loop()
        ready: asyncio.Future = loop.create_future()
        finish = asyncio.Event()

        async def hold() -> None:
            try:
                async with AsyncExitStack() as stack:
                    if transport == "stdio":
                        session = await self._connect_stdio(config, stack)
                    elif transport in ("http", "streamable_http"):
                        session = await self._connect_http(config, stack)
                    else:
                        raise ValueError(f"Unknown MCP transport: {transport}")

                    def request_unwind() -> None:
                        """Tell the holder to unwind, from whatever thread asks."""
                        loop.call_soon_threadsafe(finish.set)

                    connection = MCPServerConnection(
                        server_name,
                        session,
                        caller=caller,
                        closer=request_unwind,
                    )
                    # Discover what the server offers as part of connecting. Both
                    # the CLI and the API path pre-connect every server an agent
                    # references before the first agent runs, so by the time a
                    # prompt is built the schemas are a dict lookup away. A server
                    # that answers initialize but not tools/list is unusable as a
                    # tool server: fail here, loudly, rather than hand the model a
                    # placeholder schema at prompt time.
                    await asyncio.wait_for(connection.refresh_tools(), timeout=30)
                    if not ready.done():
                        ready.set_result(connection)
                    await finish.wait()
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                elif not isinstance(exc, asyncio.CancelledError):
                    logger.warning(
                        "MCP session '%s' (%s) ended: %s",
                        server_name, caller or "shared", exc,
                    )
                    raise

        task = asyncio.ensure_future(hold())
        try:
            connection = await ready
        except BaseException:
            task.cancel()
            raise
        self._holders[(server_name, caller)] = task
        return connection

    async def get_tool_meta(self, server_name: str, tool_name: str) -> Any | None:
        """The server's own definition (mcp.types.Tool) of one tool, connecting if needed.

        Answered from the shared session: a schema is the same whoever asks, and
        discovery runs while a prompt is being built, which is not a caller's
        session to open.

        None means the server is up but does not advertise that name — an agent
        YAML typo, a renamed tool, or a profile that excludes it.
        """
        connection = await self.ensure_connected(server_name)
        return connection.tools.get(tool_name)

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict, caller: str = ""
    ) -> ToolCallOutcome:
        """Connect if needed, then call a tool. The main entry point for MCPTool.

        The call goes to ``caller``'s own session (see the class docstring), so
        what the last call left behind — the open page, the cwd — is this
        caller's own and nobody else's.

        On connection failure (stale subprocess, broken pipe) or a dead
        session (the streamable-HTTP server no longer knows our session id:
        "Session terminated"), evicts the dead connection and reconnects once
        before raising. Without the second case one abandoned browser call
        cost a run every browser call after it, each failing in 2 ms.
        """
        connection = await self.ensure_connected(server_name, caller)
        try:
            return await connection.call_tool(tool_name, arguments)
        except (BrokenPipeError, EOFError, ConnectionError, OSError, McpError) as exc:
            if isinstance(exc, McpError) and not _session_is_dead(exc):
                raise
            logger.warning(
                "MCP server '%s' connection failed: %s. Reconnecting...",
                server_name, exc,
            )
            await self._close((server_name, caller))
            connection = await self.ensure_connected(server_name, caller)
            return await connection.call_tool(tool_name, arguments)

    async def _connect_stdio(self, config: dict, stack: AsyncExitStack) -> ClientSession:
        # Sanitize env — block dangerous vars that could be injected via MCP YAML config
        raw_env = config.get("env")
        sanitized_env: dict | None
        if raw_env and isinstance(raw_env, dict):
            blocked = {"LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES", "PYTHONPATH"}
            sanitized_env = {k: v for k, v in raw_env.items() if k not in blocked}
        else:
            sanitized_env = raw_env
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args", []),
            env=sanitized_env,
        )
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        return session

    async def _connect_http(self, config: dict, stack: AsyncExitStack) -> ClientSession:
        """Connect over Streamable HTTP, with optional static headers and OAuth.

        Three ways to authenticate, because remote MCP servers differ.
        ``headers`` covers servers that take a long-lived API token.
        ``auth: oauth`` covers servers that require an authorization code
        flow: the grant is obtained once by ``temper connect <server>`` and
        stored, and the provider here refreshes it without a human present.
        A run never opens a browser — see ``interactive`` in mcp_auth.
        ``auth: client_credentials`` gives temper an identity of its own (an
        app, not a person) from a client id and secret; see
        oauth_client_credentials.
        """
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        from temper_ai.tools.mcp_auth import build_oauth_provider, oauth_configured
        from temper_ai.tools.oauth_client_credentials import (
            ClientCredentials,
            ClientCredentialsAuth,
            client_credentials_configured,
        )

        url = config["url"]
        headers = config.get("headers") or None
        auth: Any = None
        if oauth_configured(config):
            auth = build_oauth_provider(config)
        elif client_credentials_configured(config):
            auth = ClientCredentialsAuth(ClientCredentials.from_config(config))

        # streamable_http_client only closes a client it created itself, so a
        # client we pass in has to go on our own stack or it leaks the
        # connection pool for the life of the process.
        http_client = None
        if headers or auth is not None:
            http_client = await stack.enter_async_context(
                create_mcp_http_client(headers=headers, auth=auth)
            )

        read, write, _ = await stack.enter_async_context(
            streamable_http_client(url, http_client=http_client)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=30)
        return session

    def get_configured_servers(self) -> list[str]:
        """List all configured server names (connected or not)."""
        return sorted(self._server_configs.keys())

    def get_server_config(self, server_name: str) -> dict:
        """Get the raw config dict for a server."""
        return self._server_configs.get(server_name, {})

    def get_active_connections(self) -> dict[str, MCPServerConnection]:
        """Currently connected servers, by name.

        Sessions are per caller, so a server can hold several at once; this
        answers the question callers of it actually ask ("is this server up?")
        with one connection per server. Use ``_connections`` for the full map.
        """
        return {server: conn for (server, _caller), conn in self._connections.items()}


def _load_mcp_configs(config_dir: str | None = None) -> list[dict]:
    """Load MCP server configs from configs/mcp_servers/*.yaml files.

    Then from ``configs/mcp_servers/local/*.yaml``, the gitignored directory
    for servers that belong to one machine rather than to the project -- a
    bridge to the operator's own browser, say. They come after the tracked
    files, and the first config to claim a name keeps it, so a local file
    adds servers but cannot quietly replace a tracked one.
    """
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
    yaml_files = sorted(mcp_dir.glob("*.yaml")) + sorted((mcp_dir / "local").glob("*.yaml"))
    for yaml_file in yaml_files:
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
