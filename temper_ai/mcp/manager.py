"""MCPManager — manages connections to multiple MCP servers."""
import concurrent.futures
import logging
import weakref
from typing import Any, Dict, List, Optional

from temper_ai.mcp._client_helpers import create_event_loop_thread, stop_event_loop
from temper_ai.mcp._schemas import MCPServerConfig
from temper_ai.mcp.constants import MCP_MAX_SERVERS, MCP_SESSION_INIT_TIMEOUT
from temper_ai.mcp.tool_wrapper import MCPToolWrapper

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to one or more MCP servers.

    Maintains a single background asyncio event loop shared by all
    MCPToolWrapper instances so that sync tool calls can bridge into async
    MCP SDK coroutines without blocking the main thread.

    Usage::

        with MCPManager(configs) as mgr:
            tools = mgr.connect_all()
            registry.register(tools)
    """

    def __init__(self, configs: List[MCPServerConfig]) -> None:
        """Initialise the manager.

        Args:
            configs: List of MCPServerConfig instances (one per server).

        Raises:
            ValueError: If the number of configs exceeds MCP_MAX_SERVERS.
        """
        if len(configs) > MCP_MAX_SERVERS:
            raise ValueError(
                f"Too many MCP servers: {len(configs)} > {MCP_MAX_SERVERS}"
            )

        self._configs = configs
        self._sessions: Dict[str, Any] = {}
        self._context_managers: Dict[str, Any] = {}
        self._tools: List[MCPToolWrapper] = []

        self._loop, self._thread = create_event_loop_thread()

        # Ensure cleanup on GC even if disconnect_all() is never called
        weakref.finalize(self, self._cleanup, self._loop, self._thread)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect_all(self) -> List[MCPToolWrapper]:
        """Connect to all configured MCP servers and return wrapped tools.

        Servers that fail to connect are skipped with a warning so the
        remaining servers can still be used.

        Returns:
            All MCPToolWrapper instances across every successfully connected server.
        """
        all_tools: List[MCPToolWrapper] = []
        seen_namespaces: Dict[str, str] = {}  # namespace -> server name

        for config in self._configs:
            try:
                session = self._connect_server(config)
                server_tools = self._list_server_tools(config, session)
                self._sessions[config.name] = session

                for tool in server_tools:
                    ns = config.effective_namespace
                    original = self._tool_info_name(tool)
                    namespaced = f"{ns}__{original}"

                    if namespaced in seen_namespaces:
                        logger.warning(
                            "MCP namespace collision: '%s' defined by both '%s' and '%s'; "
                            "skipping duplicate from '%s'",
                            namespaced,
                            seen_namespaces[namespaced],
                            config.name,
                            config.name,
                        )
                        continue

                    seen_namespaces[namespaced] = config.name
                    wrapper = MCPToolWrapper(
                        tool_info=tool,
                        session=session,
                        namespace=ns,
                        call_timeout=config.call_timeout,
                        event_loop=self._loop,
                    )
                    all_tools.append(wrapper)

            except Exception as exc:  # noqa: BLE001 — log + continue for resilience
                logger.warning(
                    "Failed to connect to MCP server '%s': %s — skipping",
                    config.name,
                    exc,
                )

        self._tools = all_tools
        return all_tools

    def disconnect_all(self) -> None:
        """Close all MCP sessions and stop the background event loop."""
        for name, session in list(self._sessions.items()):
            try:
                future: concurrent.futures.Future[None] = concurrent.futures.Future()

                async def _close(s: Any) -> None:
                    await s.__aexit__(None, None, None)

                def _do_close() -> None:
                    import asyncio

                    coro = _close(session)
                    task = asyncio.ensure_future(coro, loop=self._loop)
                    task.add_done_callback(
                        lambda t: (
                            future.set_exception(t.exception())
                            if t.exception()
                            else future.set_result(None)
                        )
                    )

                self._loop.call_soon_threadsafe(_do_close)
                future.result(timeout=MCP_SESSION_INIT_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Error closing MCP session '%s': %s", name, exc)

        self._sessions.clear()
        stop_event_loop(self._loop, self._thread)

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "MCPManager":
        return self

    def __exit__(
        self,
        _exc_type: Optional[type],
        _exc_val: Optional[BaseException],
        _exc_tb: Optional[Any],
    ) -> None:
        self.disconnect_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect_server(self, config: MCPServerConfig) -> Any:
        """Connect to a single MCP server and return an initialised ClientSession.

        All async operations run on the shared background event loop.
        """
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def _do_connect() -> None:
            import asyncio

            coro = self._async_connect(config)
            task = asyncio.ensure_future(coro, loop=self._loop)
            task.add_done_callback(
                lambda t: (
                    future.set_exception(t.exception())
                    if t.exception()
                    else future.set_result(t.result())
                )
            )

        self._loop.call_soon_threadsafe(_do_connect)
        return future.result(timeout=config.connect_timeout)

    async def _async_connect(self, config: MCPServerConfig) -> Any:
        """Async coroutine: create transport and initialise the MCP session."""
        if config.command is not None:
            return await self._connect_stdio(config)
        return await self._connect_http(config)

    async def _connect_stdio(self, config: MCPServerConfig) -> Any:
        """Connect via stdio transport."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        from mcp import StdioServerParameters

        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env or None,
        )
        ctx = stdio_client(params)
        read, write = await ctx.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._context_managers[config.name] = (ctx, session)
        return session

    async def _connect_http(self, config: MCPServerConfig) -> Any:
        """Connect via HTTP/SSE transport."""
        from mcp import ClientSession

        try:
            from mcp.client.streamable_http import streamablehttp_client
            ctx = streamablehttp_client(config.url)
        except ImportError:
            from mcp.client.sse import sse_client
            ctx = sse_client(config.url)

        read, write = await ctx.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self._context_managers[config.name] = (ctx, session)
        return session

    def _list_server_tools(self, config: MCPServerConfig, session: Any) -> List[Any]:
        """Return the list of tools advertised by the connected server."""
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def _do_list() -> None:
            import asyncio

            async def _list() -> Any:
                return await session.list_tools()

            task = asyncio.ensure_future(_list(), loop=self._loop)
            task.add_done_callback(
                lambda t: (
                    future.set_exception(t.exception())
                    if t.exception()
                    else future.set_result(t.result())
                )
            )

        self._loop.call_soon_threadsafe(_do_list)
        list_result = future.result(timeout=config.connect_timeout)
        return getattr(list_result, "tools", []) or []

    @staticmethod
    def _tool_info_name(tool_info: Any) -> str:
        return str(getattr(tool_info, "name", ""))

    @staticmethod
    def _cleanup(
        loop: Any,
        thread: Any,
    ) -> None:
        """Finalizer — called by weakref.finalize if disconnect_all() was never called."""
        try:
            stop_event_loop(loop, thread)
        except Exception:  # noqa: BLE001
            pass
