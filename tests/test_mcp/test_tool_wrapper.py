"""Tests for MCPToolWrapper — sync bridge, annotation mapping, result conversion."""
import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from temper_ai.tools.base import ToolResult


# ---------------------------------------------------------------------------
# Helpers — build fake MCP objects without the mcp SDK installed
# ---------------------------------------------------------------------------

def _make_tool_info(
    name="create_pr",
    description="Create a PR",
    input_schema=None,
    annotations=None,
):
    ti = MagicMock()
    ti.name = name
    ti.description = description
    ti.inputSchema = input_schema or {"type": "object", "properties": {}}
    ti.annotations = annotations
    return ti


def _make_session(result=None):
    session = MagicMock()
    if result is None:
        result = _make_call_result(text="ok")
    # session.call_tool returns a coroutine-like; we mock the future path instead
    session.call_tool = MagicMock(return_value=result)
    return session


def _make_call_result(text=None, is_error=False, content_type="text"):
    result = MagicMock()
    result.isError = is_error
    content_item = MagicMock()
    content_item.type = content_type
    if text is not None:
        content_item.text = text
    else:
        content_item.text = None
    if content_type == "image":
        content_item.mimeType = "image/png"
    result.content = [content_item]
    return result


def _make_event_loop_mock(return_value=None, raise_exception=None):
    """Return a fake event loop that immediately runs the queued coroutine."""
    loop = MagicMock()

    def call_soon_threadsafe(fn):
        """Simulate the event loop executing the callback immediately."""
        # The callback sets a result on the asyncio_future inside the wrapper.
        # We need to replicate that behaviour synchronously.
        fn()

    loop.call_soon_threadsafe.side_effect = call_soon_threadsafe
    return loop


def _make_wrapper(
    tool_info=None,
    session=None,
    namespace="gh",
    call_timeout=30,
    event_loop=None,
):
    """Build an MCPToolWrapper with mocked internal components."""
    from temper_ai.mcp.tool_wrapper import MCPToolWrapper

    ti = tool_info or _make_tool_info()
    sess = session or _make_session()
    loop = event_loop or MagicMock()

    return MCPToolWrapper(
        tool_info=ti,
        session=sess,
        namespace=namespace,
        call_timeout=call_timeout,
        event_loop=loop,
    )


# ---------------------------------------------------------------------------
# Metadata / annotation tests
# ---------------------------------------------------------------------------

class TestAnnotationMapping:
    def test_read_only_hint_sets_modifies_state_false(self):
        annotations = MagicMock()
        annotations.readOnlyHint = True
        annotations.destructiveHint = None
        annotations.openWorldHint = None

        wrapper = _make_wrapper(tool_info=_make_tool_info(annotations=annotations))
        assert wrapper.get_metadata().modifies_state is False

    def test_destructive_hint_sets_modifies_state_true(self):
        annotations = MagicMock()
        annotations.readOnlyHint = None
        annotations.destructiveHint = True
        annotations.openWorldHint = None

        wrapper = _make_wrapper(tool_info=_make_tool_info(annotations=annotations))
        assert wrapper.get_metadata().modifies_state is True

    def test_open_world_hint_sets_requires_network_true(self):
        annotations = MagicMock()
        annotations.readOnlyHint = None
        annotations.destructiveHint = None
        annotations.openWorldHint = True

        wrapper = _make_wrapper(tool_info=_make_tool_info(annotations=annotations))
        assert wrapper.get_metadata().requires_network is True

    def test_no_annotations_uses_conservative_defaults(self):
        wrapper = _make_wrapper(tool_info=_make_tool_info(annotations=None))
        meta = wrapper.get_metadata()
        assert meta.modifies_state is True  # conservative default
        assert meta.requires_network is False


class TestNamespaceAndSchema:
    def test_namespace_prefixing(self):
        wrapper = _make_wrapper(
            tool_info=_make_tool_info(name="create_pr"),
            namespace="gh",
        )
        assert wrapper.get_metadata().name == "gh__create_pr"

    def test_parameter_schema_passthrough(self):
        schema = {"type": "object", "properties": {"title": {"type": "string"}}}
        wrapper = _make_wrapper(tool_info=_make_tool_info(input_schema=schema))
        assert wrapper.get_parameters_schema() == schema

    def test_empty_input_schema_returns_default(self):
        ti = _make_tool_info()
        ti.inputSchema = None
        wrapper = _make_wrapper(tool_info=ti)
        result = wrapper.get_parameters_schema()
        assert result["type"] == "object"
        assert "properties" in result


# ---------------------------------------------------------------------------
# Execute / result conversion tests  (sync bridge fully mocked)
# ---------------------------------------------------------------------------

class TestExecuteResultConversion:
    """Test _convert_result() directly to avoid asyncio complexity."""

    def _wrapper(self):
        return _make_wrapper()

    def test_text_content_gives_success_result(self):
        w = self._wrapper()
        call_result = _make_call_result(text="Hello world")
        result = w._convert_result(call_result)
        assert result.success is True
        assert result.result == "Hello world"

    def test_error_result_gives_failure(self):
        w = self._wrapper()
        call_result = _make_call_result(text="Something went wrong", is_error=True)
        result = w._convert_result(call_result)
        assert result.success is False
        assert "Something went wrong" in result.error

    def test_image_content_type_in_metadata(self):
        w = self._wrapper()
        call_result = _make_call_result(content_type="image")
        result = w._convert_result(call_result)
        assert result.success is True
        assert result.result == "[image]"
        assert result.metadata.get("content_type") == "image/png"

    def test_empty_content_list_returns_empty_success(self):
        w = self._wrapper()
        call_result = MagicMock()
        call_result.isError = False
        call_result.content = []
        result = w._convert_result(call_result)
        assert result.success is True
        assert result.result == ""


class TestTimeoutHandling:
    def test_timeout_returns_failure_tool_result(self):
        from temper_ai.mcp.tool_wrapper import MCPToolWrapper

        ti = _make_tool_info(name="slow_tool")
        loop = MagicMock()

        # Simulate the bridge never completing: asyncio_future.result() raises TimeoutError
        def _call_soon(fn):
            # Don't invoke fn — simulates a stalled coroutine
            pass

        loop.call_soon_threadsafe.side_effect = _call_soon

        wrapper = MCPToolWrapper(
            tool_info=ti,
            session=MagicMock(),
            namespace="ns",
            call_timeout=1,
            event_loop=loop,
        )

        with patch("concurrent.futures.Future.result", side_effect=concurrent.futures.TimeoutError):
            result = wrapper.execute()

        assert result.success is False
        assert "timed out" in result.error.lower()


class TestSafeExecuteContract:
    def test_safe_execute_returns_tool_result_on_error(self):
        """safe_execute() must never raise — even when execute() raises."""
        from temper_ai.mcp.tool_wrapper import MCPToolWrapper

        ti = _make_tool_info()
        loop = MagicMock()

        wrapper = MCPToolWrapper(
            tool_info=ti,
            session=MagicMock(),
            namespace="ns",
            call_timeout=5,
            event_loop=loop,
        )

        # Patch validate_params to skip schema validation (no required fields)
        from temper_ai.tools.base import ParameterValidationResult
        with patch.object(wrapper, "validate_params", return_value=ParameterValidationResult(valid=True)):
            with patch.object(wrapper, "execute", side_effect=RuntimeError("boom")):
                result = wrapper.safe_execute()

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "boom" in result.error
