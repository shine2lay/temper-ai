"""MCP tool bridge — wraps an MCP server tool as a Temper BaseTool.

Agents see MCP tools the same as native tools. The bridge handles:
- Lazy connection (server connects on first use, not at import)
- Schema discovery: description / input schema / read-only-ness come from the
  server's own tools/list, fetched at connect time, applied the first time the
  schema is requested (i.e. when a prompt is built). Nothing is hand-written.
- Sync→async execution (agent runs sync, MCP SDK is async)
- Result extraction (MCP content blocks → string) honouring the server's isError

MCPTool does NOT hold a connection reference. It calls mcp_manager.call_tool()
which handles connect-on-demand.
"""

import asyncio
import logging
from typing import Any

from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_PLACEHOLDER_SCHEMA: dict = {"type": "object", "properties": {}}


class MCPTool(BaseTool):
    """Wraps a single MCP tool as a Temper BaseTool.

    The tool knows its server name and tool name. On execute(), it asks
    the MCPClientManager to connect (if needed) and call the tool.

    Until discovery runs the instance carries a placeholder (or whatever the
    server YAML's optional ``tools:`` block supplied). ``to_llm_schema()`` is
    the point where the model is about to see the tool, so that is where the
    server's definition is applied.
    """

    # Conservative default: an MCP tool we know nothing about may change
    # remote state. Discovery overrides this per instance from the server's
    # ``readOnlyHint`` annotation.
    modifies_state = True

    # An MCP tool's arguments go to another process. Its ``path`` is a path in a
    # GitHub repo, or under that server's own roots — never this workspace, so the
    # workspace sandbox must not judge it (see BaseTool.local_paths). Path safety
    # for MCP is the server's, set when the server is launched.
    local_paths = False

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
        self._discovered = False
        # True once the server said "no such tool" — so the warning fires once
        # per process, not once per prompt.
        self._missing_on_server = False

    @property
    def llm_name(self) -> str:
        """``server__tool`` — the dotted name with the dot a provider won't take.

        Anthropic and OpenAI both require ``^[a-zA-Z0-9_-]+$``, so sending
        ``playwright.browser_navigate`` fails the request outright (400,
        ``tools.0.custom.name: String should match pattern``). Double underscore
        matches what the Claude CLI already calls MCP tools (``mcp__server__tool``),
        so the name reads the same in a log whichever provider ran it.

        ``self.name`` keeps the dot: configs declare ``playwright.browser_navigate``
        and the executor scopes on it. LLMAgent maps back before executing.
        """
        return f"{self._server_name}__{self._tool_name}"

    # -- schema discovery ----------------------------------------------------

    def to_llm_schema(self) -> dict[str, Any]:
        self._discover()
        return super().to_llm_schema()

    def _discover(self) -> None:
        """Replace the placeholder with the server's definition (once).

        Cheap path: the server is already connected (both run paths pre-connect
        every referenced server) → dict lookup, no I/O. Otherwise connect now.
        A connection failure is logged and leaves ``_discovered`` False so the
        next prompt retries — a flaky server should not permanently pin a tool
        to its placeholder.
        """
        if self._discovered:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._manager.get_tool_meta(self._server_name, self._tool_name),
                self._event_loop,
            )
            meta = future.result(timeout=30)
        except Exception as e:  # noqa: BLE001 — anything: the model still gets a tool, just the placeholder
            logger.warning(
                "MCP tool '%s': schema discovery failed (%s); the model sees a placeholder schema",
                self.name, e,
            )
            return
        self._discovered = True
        if meta is None:
            self._missing_on_server = True
            logger.warning(
                "MCP tool '%s': server '%s' does not advertise a tool named '%s' "
                "(typo in the agent YAML, renamed upstream, or excluded by the server's profile). "
                "Calls will fail.",
                self.name, self._server_name, self._tool_name,
            )
            return
        self._apply(meta)

    def _apply(self, meta: Any) -> None:
        """Copy description / inputSchema / read-only-ness from an mcp.types.Tool."""
        description = getattr(meta, "description", None)
        if description:
            self.description = description
        schema = getattr(meta, "inputSchema", None)
        if isinstance(schema, dict) and schema:
            self.parameters = schema
        annotations = getattr(meta, "annotations", None)
        read_only = getattr(annotations, "readOnlyHint", None) if annotations is not None else None
        if read_only is not None:
            self.modifies_state = not read_only

    # -- execution -----------------------------------------------------------

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
            outcome = future.result(timeout=30)
            if outcome.is_error:
                # The server refused or failed the call (bad arguments, tool not
                # registered under this profile, upstream API error). Report it
                # as a failure so the run's accounting matches what the model
                # reads; the text is still the error message the server wrote.
                return ToolResult(success=False, result=outcome.text, error=outcome.text or f"MCP tool '{self.name}' reported an error")
            return ToolResult(success=True, result=outcome.text)
        except TimeoutError:
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
    Creates an MCPTool for each — no server connection made here. The real
    description and input schema arrive from the server's tools/list the first
    time the tool's schema is requested (see MCPTool._discover); the optional
    ``tools:`` block in the server YAML only seeds the placeholder and is
    overridden by what the server actually advertises.

    With no agent_configs there is nothing to bind: returns an empty dict.
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
