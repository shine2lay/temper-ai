"""Every run gets the same tools, however it was started.

A run can begin three ways: ``POST /api/runs``, ``POST /api/runs/{id}/resume`` and ``POST /api/runs/fork``.
Each builds its own ``ToolExecutor``. Start registered the built-ins *and* the MCP tools its agents
declare; resume and fork registered only the built-ins.

The failure that costs you is not the missing tool. It is that nothing stops: the agent starts, its
declared name resolves to nothing, and a model with no browser still answers. A resumed QA step reported
``"verdict": "fail", "summary": "Unable to execute browser verification steps in this environment"`` —
a confident verdict about an application it never opened. So the registration lives in one helper now,
and the last test here keeps it that way for paths nobody has written yet.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from temper_ai.api import routes
from temper_ai.tools import TOOL_CLASSES
from temper_ai.tools.executor import ToolExecutor

ROUTES_FILE = Path(routes.__file__)


def node_declaring(*tool_names: str):
    """A workflow node whose agent asks for these tools (what the MCP factory reads)."""
    node = MagicMock()
    node.agent_config = MagicMock(tools=list(tool_names))
    return node


@pytest.fixture()
def no_mcp(monkeypatch):
    """No MCP server configured: the factory finds nothing to build."""
    monkeypatch.setattr(routes, "preconnect_mcp_servers", MagicMock())
    import temper_ai.tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "create_mcp_tools_from_agents", lambda manager, configs: {})
    return None


def test_built_in_tools_are_registered(no_mcp):
    ex = ToolExecutor()

    routes._register_run_tools(ex, [])

    assert TOOL_CLASSES, "guard: the built-in table should not be empty"
    for name in TOOL_CLASSES:
        assert ex.get_tool(name) is not None, f"built-in {name} missing"


def test_declared_mcp_tools_are_registered_and_their_server_preconnected(monkeypatch):
    browser = MagicMock(name="browser_navigate")
    preconnect = MagicMock()
    seen: dict = {}

    def fake_factory(manager, agent_configs):
        seen["agent_configs"] = agent_configs
        return {"playwright.browser_navigate": browser}

    import temper_ai.tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "create_mcp_tools_from_agents", fake_factory)
    monkeypatch.setattr(routes, "preconnect_mcp_servers", preconnect)
    ex = ToolExecutor()
    nodes = [node_declaring("playwright.browser_navigate"), MagicMock(spec=[])]  # second: not an agent

    routes._register_run_tools(ex, nodes)

    assert ex.get_tool("playwright.browser_navigate") is browser
    assert ex.get_tool(next(iter(TOOL_CLASSES))) is not None, "built-ins still there too"
    assert len(seen["agent_configs"]) == 1, "only nodes that carry an agent_config are consulted"
    assert preconnect.call_args[0][1] == {"playwright.browser_navigate": browser}


def test_a_server_that_will_not_connect_is_a_503_not_a_run_without_tools(monkeypatch):
    """Better to refuse the run than to start an agent whose browser silently does nothing."""
    import temper_ai.tools.mcp_tool as mcp_tool

    monkeypatch.setattr(
        mcp_tool, "create_mcp_tools_from_agents", lambda m, c: {"playwright.browser_click": MagicMock()}
    )
    monkeypatch.setattr(
        routes,
        "preconnect_mcp_servers",
        MagicMock(side_effect=routes.McpPreconnectError("playwright: connection refused")),
    )

    with pytest.raises(HTTPException) as err:
        routes._register_run_tools(ToolExecutor(), [node_declaring("playwright.browser_click")])

    assert err.value.status_code == 503
    assert "playwright" in str(err.value.detail)


def test_nothing_is_preconnected_when_no_agent_asks_for_mcp(monkeypatch):
    preconnect = MagicMock()
    import temper_ai.tools.mcp_tool as mcp_tool

    monkeypatch.setattr(mcp_tool, "create_mcp_tools_from_agents", lambda m, c: {})
    monkeypatch.setattr(routes, "preconnect_mcp_servers", preconnect)

    routes._register_run_tools(ToolExecutor(), [node_declaring("read_file")])

    preconnect.assert_not_called()


# ---------------------------------------------------------------------------------------------------
# The invariant. The bug was not in resume's logic, it was that resume had its own copy of the setup and
# the copy fell behind. Read the file: anything that builds a ToolExecutor must go through the helper.
# ---------------------------------------------------------------------------------------------------


def functions_building_a_tool_executor() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(ROUTES_FILE.read_text())
    out = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "ToolExecutor":
                out[fn.name] = fn
    return out


def calls_named(fn: ast.FunctionDef) -> set[str]:
    names = set()
    for call in ast.walk(fn):
        f = call.func if isinstance(call, ast.Call) else None
        if isinstance(f, ast.Name):
            names.add(f.id)
        elif isinstance(f, ast.Attribute):
            names.add(f.attr)
    return names


def test_every_run_path_that_builds_an_executor_registers_through_the_helper():
    builders = functions_building_a_tool_executor()

    assert {"start_run", "resume_run", "fork_run"} <= set(builders), (
        f"expected the three run paths to build executors; found {sorted(builders)}"
    )
    for name, fn in builders.items():
        assert "_register_run_tools" in calls_named(fn), (
            f"{name}() builds a ToolExecutor without calling _register_run_tools — an agent started from "
            f"this path would silently lose every MCP tool it declared"
        )


def test_no_run_path_registers_the_built_ins_behind_the_helpers_back():
    """A second copy of `register_tools({... TOOL_CLASSES ...})` is how the two drifted apart."""
    tree = ast.parse(ROUTES_FILE.read_text())
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name == "_register_run_tools":
            continue
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and getattr(call.func, "attr", None) == "register_tools"):
                continue
            if "TOOL_CLASSES" in {n.id for n in ast.walk(call) if isinstance(n, ast.Name)}:
                offenders.append(fn.name)

    assert not offenders, f"{offenders} register built-ins directly; call _register_run_tools instead"
