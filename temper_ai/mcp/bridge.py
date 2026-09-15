"""stdio → HTTP bridge for MCP clients that cannot speak streamable HTTP.

This is a proxy, not a second implementation: it asks the running server
for its tool list and forwards every call. There is nothing here to drift
out of sync with the engine — if the server gains a tool, so does the
bridge, without a release.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8420/mcp"


async def _serve(url: str) -> None:
    import mcp.types as types
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    async with streamablehttp_client(url) as (read, write, _), ClientSession(
        read, write
    ) as upstream:
        await upstream.initialize()
        remote_tools = (await upstream.list_tools()).tools
        logger.info("bridging %d tools from %s", len(remote_tools), url)

        proxy: Server = Server("temper")

        @proxy.list_tools()
        async def list_tools() -> list[types.Tool]:
            # Re-read on every request so a server restart that adds tools
            # is picked up without restarting the bridge.
            return (await upstream.list_tools()).tools

        @proxy.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
            result = await upstream.call_tool(name, arguments)
            return result.content

        options = proxy.create_initialization_options()
        async with stdio_server() as (stdin, stdout):
            await proxy.run(stdin, stdout, options)


def run_bridge(url: str = DEFAULT_URL) -> None:
    """Serve temper's MCP tools over stdio by proxying to a running server."""
    import anyio

    anyio.run(_serve, url)
