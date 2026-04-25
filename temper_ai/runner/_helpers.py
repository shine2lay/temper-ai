"""Setup helpers shared by all workflow-execution call sites.

Originally lived in temper_ai.api.routes; relocated to the runner module
because they're consumed by execute_workflow() and the route handlers
that wrap it. Keeping the implementation in one place avoids the existing
duplication risk where routes.py had three call sites doing the same
ExecutionContext-prep dance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from temper_ai.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


def bind_delegate_tool(tool_executor: ToolExecutor, context: Any) -> None:
    """Inject ExecutionContext into the Delegate tool, if registered.

    Delegate spawns sub-agents that need access to the run's tool registry,
    cancel event, etc. Without this binding the tool errors at first use.
    """
    delegate = tool_executor.get_tool("Delegate")
    if delegate and hasattr(delegate, "bind_context"):
        delegate.bind_context(context)


def build_dispatch_limits(config: Any) -> Any:
    """Resolve DispatchLimits from the workflow's `defaults.dispatch` section.

    Used by every ExecutionContext build site so they share one formula.
    """
    from temper_ai.stage.dispatch_limits import DispatchLimits
    return DispatchLimits.from_defaults(getattr(config, "defaults", None))


class McpPreconnectError(Exception):
    """Raised by preconnect_mcp_servers() when one or more required MCP
    servers fail to come up. Callers (route handler today; CLI tomorrow)
    decide how to surface — HTTP 503 in the route handler, exit code in CLI.
    """


def preconnect_mcp_servers(mcp_manager: Any, mcp_tools: dict) -> None:
    """Pre-connect MCP servers needed by this workflow's agents.

    Runs the async connections from a sync caller via run_coroutine_threadsafe
    on the manager's owned event loop. Raises McpPreconnectError on any
    failure — fail-fast keeps a half-broken stack from launching. Caller
    chooses error surface (HTTP 503 vs subprocess exit).
    """
    server_names = {tool._server_name for tool in mcp_tools.values()}
    if not server_names:
        return

    errors: list[str] = []

    async def connect_all() -> None:
        for name in server_names:
            try:
                await mcp_manager.ensure_connected(name)
            except Exception as e:
                errors.append(f"MCP server '{name}': {e}")

    future = asyncio.run_coroutine_threadsafe(connect_all(), mcp_manager.event_loop)
    future.result(timeout=30)

    if errors:
        raise McpPreconnectError(
            f"Required MCP servers failed to connect: {'; '.join(errors)}",
        )
