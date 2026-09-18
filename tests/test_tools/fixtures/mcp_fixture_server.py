"""A tiny stdio MCP server for tests — two tools, one that errors on demand.

Run as a subprocess by tests/test_tools/test_mcp_tool.py. Uses the same `mcp`
SDK the client does, so tools/list pagination, annotations and isError go over
a real wire rather than being faked.
"""

from __future__ import annotations

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

server: Server = Server("fixture")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="echo",
            description="Repeat text N times.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to repeat."},
                    "times": {"type": "integer", "default": 1},
                },
                "required": ["text"],
            },
            annotations=types.ToolAnnotations(readOnlyHint=True),
        ),
        types.Tool(
            name="mutate",
            description="Pretends to change something; errors when told to.",
            inputSchema={
                "type": "object",
                "properties": {"fail": {"type": "boolean", "default": False}},
            },
            annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent] | types.CallToolResult:
    if name == "echo":
        text = arguments.get("text")
        if not isinstance(text, str):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="echo: 'text' (string) is required")],
                isError=True,
            )
        return [types.TextContent(type="text", text=text * int(arguments.get("times", 1)))]
    if name == "mutate":
        if arguments.get("fail"):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="mutate: refused by server")],
                isError=True,
            )
        return [types.TextContent(type="text", text="mutated")]
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"unknown tool: {name}")],
        isError=True,
    )


async def _main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
