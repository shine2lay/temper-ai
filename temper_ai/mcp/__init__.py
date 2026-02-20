"""MCP (Model Context Protocol) integration for Temper AI.

Provides:
- MCPManager: Manages connections to external MCP servers (client)
- MCPToolWrapper: Wraps MCP tools as Temper AI BaseTool instances
- create_mcp_server: Exposes Temper AI workflows as an MCP server

Requires the ``mcp`` optional dependency:
    pip install 'temper-ai[mcp]'
"""
from temper_ai.mcp._schemas import MCPServerConfig  # noqa: F401


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import MCPManager and MCPToolWrapper on first access."""
    if name == "MCPManager":
        from temper_ai.mcp.manager import MCPManager
        return MCPManager
    if name == "MCPToolWrapper":
        from temper_ai.mcp.tool_wrapper import MCPToolWrapper
        return MCPToolWrapper
    if name == "create_mcp_server":
        from temper_ai.mcp.server import create_mcp_server
        return create_mcp_server
    raise AttributeError(f"module 'temper_ai.mcp' has no attribute {name!r}")
