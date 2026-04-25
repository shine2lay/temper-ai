"""Tests for temper_ai.runner._helpers — the shared setup helpers used by
both the FastAPI route handlers and the standalone runner module.

Coverage target: behavior of each helper at its boundaries. The asyncio
preconnect path is exercised via the empty-tools shortcut + an error-path
test that uses a real event loop in a thread (mirrors how the route handler
calls it). Full MCP connection is integration-tested via test_routes.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from temper_ai.runner._helpers import (
    McpPreconnectError,
    bind_delegate_tool,
    build_dispatch_limits,
    preconnect_mcp_servers,
)
from temper_ai.stage.dispatch_limits import (
    DEFAULT_MAX_CHILDREN_PER_DISPATCH,
    DEFAULT_MAX_DISPATCH_DEPTH,
    DEFAULT_MAX_DYNAMIC_NODES,
    DispatchLimits,
)

# --- build_dispatch_limits -------------------------------------------------

def test_build_dispatch_limits_returns_defaults_when_no_defaults_section():
    """A config without `defaults` should yield the module defaults."""
    config = SimpleNamespace()  # no `defaults` attr
    limits = build_dispatch_limits(config)
    assert isinstance(limits, DispatchLimits)
    assert limits.max_children_per_dispatch == DEFAULT_MAX_CHILDREN_PER_DISPATCH
    assert limits.max_dynamic_nodes == DEFAULT_MAX_DYNAMIC_NODES
    assert limits.max_dispatch_depth == DEFAULT_MAX_DISPATCH_DEPTH


def test_build_dispatch_limits_returns_defaults_when_defaults_is_none():
    config = SimpleNamespace(defaults=None)
    assert build_dispatch_limits(config) == DispatchLimits()


def test_build_dispatch_limits_reads_dispatch_overrides():
    config = SimpleNamespace(defaults={
        "dispatch": {
            "max_children_per_dispatch": 7,
            "max_dynamic_nodes": 99,
            "max_dispatch_depth": 5,
            "cycle_detection": False,
        },
    })
    limits = build_dispatch_limits(config)
    assert limits.max_children_per_dispatch == 7
    assert limits.max_dynamic_nodes == 99
    assert limits.max_dispatch_depth == 5
    assert limits.cycle_detection is False


# --- bind_delegate_tool ----------------------------------------------------

def test_bind_delegate_tool_calls_bind_when_delegate_registered():
    delegate = MagicMock()
    delegate.bind_context = MagicMock()
    tool_executor = MagicMock()
    tool_executor.get_tool.return_value = delegate

    context = object()
    bind_delegate_tool(tool_executor, context)

    tool_executor.get_tool.assert_called_once_with("Delegate")
    delegate.bind_context.assert_called_once_with(context)


def test_bind_delegate_tool_no_op_when_delegate_missing():
    tool_executor = MagicMock()
    tool_executor.get_tool.return_value = None

    bind_delegate_tool(tool_executor, object())  # must not raise


def test_bind_delegate_tool_no_op_when_delegate_lacks_bind_method():
    """Backward-compat: an older Delegate without bind_context shouldn't crash."""
    delegate = SimpleNamespace()  # no bind_context attribute
    tool_executor = MagicMock()
    tool_executor.get_tool.return_value = delegate

    bind_delegate_tool(tool_executor, object())  # must not raise


# --- preconnect_mcp_servers ------------------------------------------------

def test_preconnect_mcp_servers_no_op_with_empty_dict():
    """Empty mcp_tools => skip everything; mcp_manager untouched."""
    mcp_manager = MagicMock()
    preconnect_mcp_servers(mcp_manager, {})
    mcp_manager.assert_not_called()


def test_preconnect_mcp_servers_raises_on_connection_error():
    """When ensure_connected fails, surface as McpPreconnectError so the
    caller can pick the error surface (HTTP 503 vs CLI exit code).
    """
    import asyncio
    import threading

    # Real event loop on a daemon thread — mirrors how mcp_manager owns its loop.
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    async def fail_connect(_name: str) -> None:
        raise RuntimeError("simulated connection refused")

    mcp_manager = SimpleNamespace(
        event_loop=loop,
        ensure_connected=fail_connect,
    )
    fake_tool = SimpleNamespace(_server_name="test-server")
    mcp_tools = {"some_tool": fake_tool}

    try:
        with pytest.raises(McpPreconnectError) as excinfo:
            preconnect_mcp_servers(mcp_manager, mcp_tools)
        assert "test-server" in str(excinfo.value)
        assert "simulated connection refused" in str(excinfo.value)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)


def test_mcp_preconnect_error_is_an_exception():
    """Caller catches it as an exception type."""
    err = McpPreconnectError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
