"""MCPToolWrapper — wraps a single MCP tool as a Temper AI BaseTool."""
import concurrent.futures
import logging
from typing import Any, Dict

from temper_ai.mcp._client_helpers import map_annotations_to_metadata
from temper_ai.mcp.constants import MCP_NAMESPACE_SEPARATOR
from temper_ai.tools.base import BaseTool, ToolMetadata, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_PARAM_SCHEMA: Dict[str, Any] = {"type": "object", "properties": {}}


class MCPToolWrapper(BaseTool):
    """Wraps a single MCP tool as a Temper AI BaseTool.

    Bridges synchronous BaseTool.execute() to async MCP session calls using
    a shared background event loop (provided by MCPManager).
    """

    def __init__(
        self,
        tool_info: Any,
        session: Any,
        namespace: str,
        call_timeout: int,
        event_loop: Any,
    ) -> None:
        """Initialise the wrapper.

        Args:
            tool_info: MCP Tool object (has .name, .description, .inputSchema, .annotations).
            session: Active MCP ClientSession for calling the tool.
            namespace: Namespace prefix for the tool name.
            call_timeout: Seconds before a tool call is considered timed out.
            event_loop: Background asyncio event loop (owned by MCPManager).
        """
        # Store attrs BEFORE super().__init__() because BaseTool.__init__ calls get_metadata()
        self._tool_info = tool_info
        self._session = session
        self._namespace = namespace
        self._call_timeout = call_timeout
        self._event_loop = event_loop
        super().__init__()

    # ------------------------------------------------------------------
    # BaseTool interface
    # ------------------------------------------------------------------

    def get_metadata(self) -> ToolMetadata:
        """Build ToolMetadata from the MCP tool description and annotations."""
        namespaced_name = f"{self._namespace}{MCP_NAMESPACE_SEPARATOR}{self._tool_info.name}"
        annotation_overrides = map_annotations_to_metadata(
            getattr(self._tool_info, "annotations", None)
        )
        return ToolMetadata(
            name=namespaced_name,
            description=self._tool_info.description or "",
            # Conservative default: assume unknown MCP tools may modify state
            modifies_state=annotation_overrides.get("modifies_state", True),
            requires_network=annotation_overrides.get("requires_network", False),
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Return the MCP tool's input schema, falling back to a bare object schema."""
        return self._tool_info.inputSchema or _DEFAULT_PARAM_SCHEMA

    def execute(self, **kwargs: Any) -> ToolResult:
        """Call the remote MCP tool, bridging sync→async via the background loop."""
        original_name = self._tool_info.name
        try:
            async def _call() -> Any:
                return await self._session.call_tool(original_name, kwargs)

            asyncio_future: concurrent.futures.Future[Any] = concurrent.futures.Future()

            def _bridge() -> None:
                import asyncio as _asyncio

                coro = _call()
                task = _asyncio.ensure_future(coro, loop=self._event_loop)
                task.add_done_callback(
                    lambda t: (
                        asyncio_future.set_exception(t.exception())
                        if t.exception()
                        else asyncio_future.set_result(t.result())
                    )
                )

            self._event_loop.call_soon_threadsafe(_bridge)
            call_result = asyncio_future.result(timeout=self._call_timeout)
            return self._convert_result(call_result)

        except concurrent.futures.TimeoutError:
            logger.warning(
                "MCP tool '%s' timed out after %ss", original_name, self._call_timeout
            )
            return ToolResult(
                success=False,
                error=f"Tool call timed out after {self._call_timeout}s",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _convert_result(self, call_result: Any) -> ToolResult:
        """Convert an MCP CallToolResult into a Temper AI ToolResult."""
        if getattr(call_result, "isError", False):
            error_text = self._extract_text(call_result)
            return ToolResult(success=False, error=error_text or "MCP tool returned an error")

        content_items = getattr(call_result, "content", []) or []
        if not content_items:
            return ToolResult(success=True, result="")

        first = content_items[0]
        content_type = getattr(first, "type", "text")

        if content_type == "image":
            mime = getattr(first, "mimeType", "image/unknown")
            return ToolResult(
                success=True,
                result="[image]",
                metadata={"content_type": mime},
            )

        text = self._extract_text(call_result)
        return ToolResult(success=True, result=text)

    @staticmethod
    def _extract_text(call_result: Any) -> str:
        """Extract concatenated text from MCP CallToolResult content."""
        parts = []
        for item in getattr(call_result, "content", []) or []:
            text = getattr(item, "text", None)
            if text is not None:
                parts.append(str(text))
        return "\n".join(parts)
