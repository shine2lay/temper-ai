"""MCP tool bridge: schema discovery and error reporting.

Before this, an MCPTool reached the model as ``description: "MCP tool from X
server"`` with ``parameters: {"type": "object", "properties": {}}`` unless
someone hand-wrote a schema in the server YAML (nobody did), and every call —
including a server refusal — was recorded as success=True.

Two layers:
  * unit — a fake manager; every branch of _discover / execute, no I/O
  * integration — a real stdio MCP server (tests/test_tools/fixtures/) driven
    through the real MCPClientManager: tools/list, annotations and isError
    travel over an actual pipe.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from temper_ai.tools.mcp_client import MCPClientManager, ToolCallOutcome
from temper_ai.tools.mcp_tool import MCPTool, create_mcp_tools_from_agents

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_fixture_server.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def loop():
    """A real event loop on a daemon thread — how mcp_manager owns its loop in production."""
    lp = asyncio.new_event_loop()
    t = threading.Thread(target=lp.run_forever, daemon=True)
    t.start()
    yield lp
    lp.call_soon_threadsafe(lp.stop)
    t.join(timeout=2)


def _meta(description="Real description", schema=None, read_only=None):
    """Stand-in for mcp.types.Tool (attribute access only)."""
    annotations = None if read_only is None else SimpleNamespace(readOnlyHint=read_only)
    return SimpleNamespace(
        description=description,
        inputSchema=schema if schema is not None else {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        annotations=annotations,
    )


class FakeManager:
    """Only what MCPTool touches: get_tool_meta / call_tool, both async."""

    def __init__(self, meta=None, *, meta_error=None, outcome=None):
        self._meta = meta
        self._meta_error = meta_error
        self._outcome = outcome or ToolCallOutcome(text="ok")
        self.meta_calls = 0
        self.calls: list[tuple[str, str, dict]] = []

    async def get_tool_meta(self, server, tool):
        self.meta_calls += 1
        if self._meta_error:
            raise self._meta_error
        return self._meta

    async def call_tool(self, server, tool, args):
        self.calls.append((server, tool, args))
        return self._outcome


def _tool(loop, manager, **kw):
    return MCPTool(
        server_name="srv",
        tool_name="thing",
        description=kw.get("description", "MCP tool from srv server"),
        input_schema=kw.get("schema", {"type": "object", "properties": {}}),
        mcp_manager=manager,
        event_loop=loop,
    )


# ---------------------------------------------------------------------------
# unit: discovery
# ---------------------------------------------------------------------------


def test_placeholder_until_schema_is_requested(loop):
    """Construction makes no I/O; the placeholder is what create_mcp_tools_from_agents seeded."""
    m = FakeManager(_meta())
    t = _tool(loop, m)
    assert t.description == "MCP tool from srv server"
    assert t.parameters == {"type": "object", "properties": {}}
    assert m.meta_calls == 0


def test_to_llm_schema_applies_server_definition_once(loop):
    m = FakeManager(_meta(read_only=True))
    t = _tool(loop, m)
    s1 = t.to_llm_schema()
    s2 = t.to_llm_schema()
    assert m.meta_calls == 1, "discovery is once per tool, not once per prompt"
    fn = s1["function"]
    # The schema carries the wire name, not the dotted identity: providers reject
    # a dot. See tests/test_tools/test_mcp_tool_naming.py.
    assert fn["name"] == "srv__thing"
    assert t.name == "srv.thing"
    assert fn["description"] == "Real description"
    assert fn["parameters"]["required"] == ["x"]
    assert s2 == s1
    assert t.modifies_state is False, "readOnlyHint=True → does not modify state"


def test_mcp_paths_are_not_local(loop):
    """The executor's workspace sandbox must not judge an MCP tool's path.

    `path` here is a path in a GitHub repo (or under the server's own roots in
    another container), resolved by that server — not a file in this workspace.
    Before this flag, every github get_file_contents(path="README.md") was
    refused with "escapes workspace root".
    """
    assert MCPTool.local_paths is False
    assert _tool(loop, FakeManager(_meta())).local_paths is False


def test_modifies_state_defaults_conservative_and_follows_annotation(loop):
    assert MCPTool.modifies_state is True, "unknown MCP tool: assume it can change remote state"
    t = _tool(loop, FakeManager(_meta(read_only=False)))
    t.to_llm_schema()
    assert t.modifies_state is True
    t2 = _tool(loop, FakeManager(_meta(read_only=None)))
    t2.to_llm_schema()
    assert t2.modifies_state is True, "no annotation → keep the conservative default"


def test_empty_server_schema_keeps_placeholder_but_takes_description(loop):
    t = _tool(loop, FakeManager(_meta(description="d", schema={})))
    fn = t.to_llm_schema()["function"]
    assert fn["description"] == "d"
    assert fn["parameters"] == {"type": "object", "properties": {}}


def test_tool_not_advertised_warns_once_and_keeps_placeholder(loop, caplog):
    m = FakeManager(None)
    t = _tool(loop, m)
    with caplog.at_level(logging.WARNING, logger="temper_ai.tools.mcp_tool"):
        t.to_llm_schema()
        t.to_llm_schema()
    warnings = [r for r in caplog.records if "does not advertise a tool named 'thing'" in r.getMessage()]
    assert len(warnings) == 1, "the typo warning fires once per process, not per prompt"
    assert m.meta_calls == 1
    assert t.parameters == {"type": "object", "properties": {}}


def test_discovery_failure_is_logged_and_retried_next_time(loop, caplog):
    """A flaky server must not pin the tool to its placeholder forever."""
    m = FakeManager(_meta(), meta_error=RuntimeError("connection refused"))
    t = _tool(loop, m)
    with caplog.at_level(logging.WARNING, logger="temper_ai.tools.mcp_tool"):
        t.to_llm_schema()
    assert any("schema discovery failed" in r.getMessage() for r in caplog.records)
    assert t.description == "MCP tool from srv server"
    # server comes back
    m._meta_error = None
    t.to_llm_schema()
    assert t.description == "Real description"
    assert m.meta_calls == 2


# ---------------------------------------------------------------------------
# unit: execution
# ---------------------------------------------------------------------------


def test_execute_success(loop):
    m = FakeManager(_meta(), outcome=ToolCallOutcome(text="hello"))
    r = _tool(loop, m).execute(x="1")
    assert r.success is True
    assert r.result == "hello"
    assert m.calls == [("srv", "thing", {"x": "1"})]


def test_execute_server_error_is_a_failure_with_the_servers_text(loop):
    """isError=True from the server → success=False. Previously this was reported as success."""
    m = FakeManager(_meta(), outcome=ToolCallOutcome(text="Invalid arguments: missing 'x'", is_error=True))
    r = _tool(loop, m).execute()
    assert r.success is False
    assert r.result == "Invalid arguments: missing 'x'"
    assert r.error == "Invalid arguments: missing 'x'"


def test_call_timeout_is_the_tools_own_and_browser_sized(loop):
    """The executor's 30 s wrapper fired on a login submit and the run lost
    its browser for good. An MCP call has its own timeout: the server YAML's
    ``timeout``, else 120 s; and the executor leaves it alone."""
    assert MCPTool.manages_own_timeout is True
    tool = _tool(loop, FakeManager(_meta()))
    assert tool._call_timeout == 120

    mgr = FakeManager(_meta())
    mgr._server_configs = {"srv": {"name": "srv", "timeout": 7}}
    assert _tool(loop, mgr)._call_timeout == 7

    mgr._server_configs = {"srv": {"name": "srv", "timeout": "not a number"}}
    assert _tool(loop, mgr)._call_timeout == 120


def test_a_slow_call_times_out_after_the_tools_own_timeout(loop):
    class Slow(FakeManager):
        async def call_tool(self, server, tool, args):
            await asyncio.sleep(5)
            return ToolCallOutcome(text="late")

    mgr = Slow(_meta())
    mgr._server_configs = {"srv": {"name": "srv", "timeout": 1}}
    r = _tool(loop, mgr).execute(x="1")
    assert r.success is False
    assert "timed out after 1s" in r.error


def test_manager_reconnects_once_when_the_session_is_dead():
    """After an abandoned request the streamable-HTTP server forgets the
    session and every call fails at once with McpError('Session terminated').
    The manager treats that like a broken pipe: evict, reconnect, retry."""
    from mcp import McpError
    from mcp.types import ErrorData

    from temper_ai.tools.mcp_client import MCPClientManager

    dead = SimpleNamespace(calls=0)

    async def dead_call(tool, args):
        dead.calls += 1
        raise McpError(ErrorData(code=-32000, message="Session terminated"))

    live = SimpleNamespace(calls=0)

    async def live_call(tool, args):
        live.calls += 1
        return ToolCallOutcome(text="back")

    dead_conn = SimpleNamespace(call_tool=dead_call)
    live_conn = SimpleNamespace(call_tool=live_call)

    mgr = MCPClientManager()
    mgr._connections["srv"] = dead_conn
    connects: list[str] = []

    async def ensure_connected(name):
        if name in mgr._connections:
            return mgr._connections[name]
        connects.append(name)
        mgr._connections[name] = live_conn
        return live_conn

    mgr.ensure_connected = ensure_connected  # type: ignore[method-assign]
    out = asyncio.run(mgr.call_tool("srv", "thing", {"x": "1"}))
    assert out.text == "back"
    assert dead.calls == 1 and live.calls == 1 and connects == ["srv"]

    # any other McpError is the call's, not the session's: no reconnect
    async def bad_args(tool, args):
        raise McpError(ErrorData(code=-32602, message="Invalid params"))

    mgr._connections["srv"] = SimpleNamespace(call_tool=bad_args)
    with pytest.raises(McpError, match="Invalid params"):
        asyncio.run(mgr.call_tool("srv", "thing", {}))
    assert connects == ["srv"]


def test_execute_exception_is_a_failure(loop):
    class Boom(FakeManager):
        async def call_tool(self, *a):
            raise RuntimeError("pipe closed")

    r = _tool(loop, Boom(_meta())).execute(x="1")
    assert r.success is False
    assert "pipe closed" in r.error


# ---------------------------------------------------------------------------
# unit: factory
# ---------------------------------------------------------------------------


def test_factory_binds_only_configured_servers_and_seeds_from_yaml(loop):
    class Mgr(FakeManager):
        event_loop = loop

        def get_configured_servers(self):
            return ["gh", "pup"]

        def get_server_config(self, name):
            return {"tools": {"a": {"description": "seeded", "input_schema": {"type": "object", "properties": {"q": {}}}}}} if name == "gh" else {}

    tools = create_mcp_tools_from_agents(
        Mgr(_meta()),
        [
            {"agent": {"tools": ["gh.a", "gh.b", "pup.c", "nope.d", "Bash"]}},
            {"tools": ["gh.a"]},  # duplicate ref, flat form
        ],
    )
    assert sorted(tools) == ["gh.a", "gh.b", "pup.c"], "unknown server skipped, builtins ignored, no duplicates"
    assert tools["gh.a"].description == "seeded"
    assert tools["gh.a"].parameters["properties"] == {"q": {}}
    assert tools["gh.b"].description == "MCP tool from gh server"
    assert create_mcp_tools_from_agents(Mgr(_meta()), None) == {}


# ---------------------------------------------------------------------------
# integration: real stdio server through the real manager
# ---------------------------------------------------------------------------


@pytest.fixture
def with_real_manager(loop):
    """Run a sync test body against an MCPClientManager wired to the fixture server.

    The whole lifecycle — connect, body, stop — runs inside ONE task on the
    manager's loop (the body on a worker thread via asyncio.to_thread, exactly
    how agents call tools in production). Connecting and stopping in the same
    task matters: stdio_client/ClientSession are anyio cancel scopes, and the
    SDK refuses to exit one from a different task. Production's
    MCPClientManager.stop() has that exact problem (it runs on whichever task
    calls it); nobody sees it because process exit swallows the error. Out of
    scope here, but not masked either.
    """

    def run(body):
        mgr = MCPClientManager()
        out: dict = {}

        async def driver():
            mgr._event_loop = asyncio.get_running_loop()
            mgr._server_configs["fixture"] = {
                "name": "fixture",
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(FIXTURE)],
            }
            mgr._connect_locks["fixture"] = asyncio.Lock()
            # Pre-connect HERE, in the driver task — same as production's
            # preconnect_mcp_servers before any agent runs. The body's later
            # run_coroutine_threadsafe calls only *use* the open session.
            await mgr.ensure_connected("fixture")
            try:
                out["value"] = await asyncio.to_thread(body, mgr)
            finally:
                await mgr.stop()

        asyncio.run_coroutine_threadsafe(driver(), loop).result(timeout=60)
        return out.get("value")

    return run


def test_real_server_connect_discovers_tools(with_real_manager):
    def body(mgr):
        conn = mgr.get_active_connections()["fixture"]
        assert sorted(conn.tools) == ["echo", "mutate"]
        echo = conn.tools["echo"]
        assert echo.description == "Repeat text N times."
        assert echo.inputSchema["required"] == ["text"]
        assert echo.annotations.readOnlyHint is True
        assert conn.tools["mutate"].annotations.destructiveHint is True

    with_real_manager(body)


def test_real_server_end_to_end_schema_and_errors(with_real_manager):
    """The full path: factory → to_llm_schema (discovery) → execute, with isError both ways."""

    def body(real_manager):
        _end_to_end(real_manager)

    with_real_manager(body)


def _end_to_end(real_manager):
    tools = create_mcp_tools_from_agents(real_manager, [{"agent": {"tools": ["fixture.echo", "fixture.mutate", "fixture.ghost"]}}])
    echo, mutate, ghost = tools["fixture.echo"], tools["fixture.mutate"], tools["fixture.ghost"]

    # discovery gives the model the real contract
    fn = echo.to_llm_schema()["function"]
    assert fn["description"] == "Repeat text N times."
    assert fn["parameters"]["properties"]["text"]["description"] == "What to repeat."
    assert echo.modifies_state is False
    mutate.to_llm_schema()
    assert mutate.modifies_state is True

    # a name the server does not advertise stays a placeholder (and warned)
    ghost.to_llm_schema()
    assert ghost.parameters == {"type": "object", "properties": {}}

    # calls
    ok = echo.execute(text="ab", times=2)
    assert ok.success is True and ok.result == "abab"

    # Missing required 'text' → isError. The mcp SDK validates against inputSchema
    # before the handler runs, so the wording is the SDK's; either way it names the field.
    bad = echo.execute(times=2)
    assert bad.success is False
    assert "text" in bad.result and "required" in bad.result
    assert bad.error == bad.result

    refused = mutate.execute(fail=True)
    assert refused.success is False
    assert refused.error == "mutate: refused by server"

    unknown = ghost.execute()
    assert unknown.success is False
    assert "unknown tool: ghost" in unknown.result
