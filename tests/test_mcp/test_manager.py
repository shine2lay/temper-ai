"""Tests for MCPManager — connection lifecycle, namespace collisions, limits."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.mcp._schemas import MCPServerConfig
from temper_ai.mcp.constants import MCP_MAX_SERVERS

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _stdio_config(name="gh", namespace=None, command="npx"):
    return MCPServerConfig(
        name=name,
        namespace=namespace,
        command=command,
        args=["-y", "server-gh"],
    )


def _http_config(name="remote", url="http://localhost:3000/mcp"):
    return MCPServerConfig(name=name, url=url)


def _make_tool_info(name="create_pr"):
    ti = MagicMock()
    ti.name = name
    ti.description = "A tool"
    ti.inputSchema = {"type": "object", "properties": {}}
    ti.annotations = None
    return ti


def _make_list_result(tools: list[MagicMock]):
    lr = MagicMock()
    lr.tools = tools
    return lr


def _patch_manager_connect(session, tools):
    """
    Return a context-manager patch that replaces _connect_server and
    _list_server_tools so connect_all() doesn't need the mcp SDK.
    """
    list_result = _make_list_result(tools)

    patches = [
        patch(
            "temper_ai.mcp.manager.MCPManager._connect_server",
            return_value=session,
        ),
        patch(
            "temper_ai.mcp.manager.MCPManager._list_server_tools",
            return_value=tools,
        ),
    ]
    return patches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCPManagerInit:
    def test_max_servers_limit_raises(self):
        from temper_ai.mcp.manager import MCPManager

        configs = [_stdio_config(name=f"s{i}") for i in range(MCP_MAX_SERVERS + 1)]
        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(MagicMock(), MagicMock()),
        ):
            with pytest.raises(ValueError, match="Too many MCP servers"):
                MCPManager(configs)

    def test_init_creates_background_thread(self):
        from temper_ai.mcp.manager import MCPManager

        mock_loop = MagicMock()
        mock_thread = MagicMock()
        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(mock_loop, mock_thread),
        ):
            mgr = MCPManager([_stdio_config()])
            assert mgr._loop is mock_loop
            assert mgr._thread is mock_thread
            # clean up
            mgr._loop = MagicMock()
            mgr._thread = MagicMock()


class TestConnectAll:
    def _build_manager(self, configs):
        from temper_ai.mcp.manager import MCPManager

        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(MagicMock(), MagicMock()),
        ):
            return MCPManager(configs)

    def test_connect_all_creates_wrappers(self):

        cfg = _stdio_config(name="gh", namespace="gh")
        session = MagicMock()
        tools = [_make_tool_info("create_pr"), _make_tool_info("list_prs")]

        mgr = self._build_manager([cfg])

        with patch.object(mgr, "_connect_server", return_value=session):
            with patch.object(mgr, "_list_server_tools", return_value=tools):
                wrappers = mgr.connect_all()

        assert len(wrappers) == 2  # noqa: PLR2004
        names = {w.name for w in wrappers}
        assert "gh__create_pr" in names
        assert "gh__list_prs" in names

    def test_namespace_collision_skips_duplicate(self):
        """Two servers expose a tool with the same namespaced name."""
        cfg1 = _stdio_config(name="gh1", namespace="shared")
        cfg2 = _stdio_config(name="gh2", namespace="shared")
        session = MagicMock()
        # Both servers advertise a tool named "action"
        tool = _make_tool_info("action")

        mgr = self._build_manager([cfg1, cfg2])

        with patch.object(mgr, "_connect_server", return_value=session):
            with patch.object(mgr, "_list_server_tools", return_value=[tool]):
                wrappers = mgr.connect_all()

        # Only one wrapper should exist (duplicate is skipped)
        names = [w.name for w in wrappers]
        assert names.count("shared__action") == 1

    def test_server_failure_skips_and_continues(self):
        """A failing server should not prevent other servers from loading."""
        cfg_bad = _stdio_config(name="bad")
        cfg_good = _stdio_config(name="good", namespace="good")
        session = MagicMock()
        tool = _make_tool_info("do_thing")

        mgr = self._build_manager([cfg_bad, cfg_good])

        call_count = {"n": 0}

        def connect_side_effect(config):
            call_count["n"] += 1
            if config.name == "bad":
                raise ConnectionError("cannot connect")
            return session

        with patch.object(mgr, "_connect_server", side_effect=connect_side_effect):
            with patch.object(mgr, "_list_server_tools", return_value=[tool]):
                wrappers = mgr.connect_all()

        assert len(wrappers) == 1
        assert wrappers[0].name == "good__do_thing"


class TestDisconnectAll:
    def test_disconnect_stops_event_loop(self):
        from temper_ai.mcp.manager import MCPManager

        mock_loop = MagicMock()
        mock_thread = MagicMock()

        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(mock_loop, mock_thread),
        ):
            mgr = MCPManager([_stdio_config()])

        with patch("temper_ai.mcp.manager.stop_event_loop") as mock_stop:
            mgr.disconnect_all()
            mock_stop.assert_called_once()


class TestContextManager:
    def test_context_manager_calls_disconnect_all(self):
        from temper_ai.mcp.manager import MCPManager

        mock_loop = MagicMock()
        mock_thread = MagicMock()

        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(mock_loop, mock_thread),
        ):
            mgr = MCPManager([_stdio_config()])

        with patch.object(mgr, "disconnect_all") as mock_disconnect:
            with mgr:
                pass
            mock_disconnect.assert_called_once()

    def test_context_manager_calls_disconnect_on_exception(self):
        from temper_ai.mcp.manager import MCPManager

        mock_loop = MagicMock()
        mock_thread = MagicMock()

        with patch(
            "temper_ai.mcp.manager.create_event_loop_thread",
            return_value=(mock_loop, mock_thread),
        ):
            mgr = MCPManager([_stdio_config()])

        with patch.object(mgr, "disconnect_all") as mock_disconnect:
            with pytest.raises(ValueError):
                with mgr:
                    raise ValueError("inner error")

        mock_disconnect.assert_called_once()
