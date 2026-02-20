"""Tests for MCP server — mocks FastMCP and all workflow dependencies."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_configs(tmp_path: Path):
    """Create a minimal config root with one workflow and one agent."""
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    agents = tmp_path / "agents"
    agents.mkdir()

    workflow_yaml = workflows / "demo.yaml"
    workflow_yaml.write_text(
        "workflow:\n  name: demo\n  description: Demo workflow\n  stages:\n    - name: s1\n    - name: s2\n"
    )

    agent_yaml = agents / "researcher.yaml"
    agent_yaml.write_text(
        "agent:\n  name: researcher\n  description: Research agent\n  type: standard\n"
    )

    return tmp_path


@pytest.fixture()
def mock_fastmcp():
    """Mock the FastMCP class and return the instance + registry of tools."""
    mock_server = MagicMock()
    registered: dict = {}

    def tool_decorator(**kwargs):
        def inner(fn):
            registered[fn.__name__] = fn
            return fn
        return inner

    mock_server.tool = tool_decorator
    mock_cls = MagicMock(return_value=mock_server)

    with patch.dict(
        "sys.modules",
        {
            "mcp": MagicMock(),
            "mcp.server": MagicMock(),
            "mcp.server.fastmcp": MagicMock(FastMCP=mock_cls),
            "mcp.server.fastmcp.utilities": MagicMock(),
            "mcp.server.fastmcp.utilities.types": MagicMock(),
        },
    ):
        yield mock_server, registered


# ---------------------------------------------------------------------------
# Server helpers
# ---------------------------------------------------------------------------


class TestScanWorkflowConfigs:
    def test_returns_workflows(self, sample_configs: Path):
        from temper_ai.mcp._server_helpers import scan_workflow_configs

        results = scan_workflow_configs(str(sample_configs))
        assert len(results) == 1
        assert results[0]["name"] == "demo"
        assert results[0]["stages"] == 2

    def test_missing_dir_returns_empty(self, tmp_path: Path):
        from temper_ai.mcp._server_helpers import scan_workflow_configs

        results = scan_workflow_configs(str(tmp_path))
        assert results == []

    def test_skips_non_yaml(self, tmp_path: Path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "readme.txt").write_text("ignore me")
        (wf_dir / "real.yaml").write_text(
            "workflow:\n  name: real\n  stages: []\n"
        )

        from temper_ai.mcp._server_helpers import scan_workflow_configs

        results = scan_workflow_configs(str(tmp_path))
        assert len(results) == 1
        assert results[0]["name"] == "real"

    def test_skips_empty_yaml(self, tmp_path: Path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "empty.yaml").write_text("")

        from temper_ai.mcp._server_helpers import scan_workflow_configs

        results = scan_workflow_configs(str(tmp_path))
        assert results == []


class TestScanAgentConfigs:
    def test_returns_agents(self, sample_configs: Path):
        from temper_ai.mcp._server_helpers import scan_agent_configs

        results = scan_agent_configs(str(sample_configs))
        assert len(results) == 1
        assert results[0]["name"] == "researcher"
        assert results[0]["type"] == "standard"

    def test_missing_dir_returns_empty(self, tmp_path: Path):
        from temper_ai.mcp._server_helpers import scan_agent_configs

        results = scan_agent_configs(str(tmp_path))
        assert results == []


class TestFormatRunResult:
    def test_dict_result_is_json(self):
        from temper_ai.mcp._server_helpers import format_run_result

        result = format_run_result({"status": "completed", "output": "hello"})
        parsed = json.loads(result)
        assert parsed["status"] == "completed"

    def test_non_dict_result_is_string(self):
        from temper_ai.mcp._server_helpers import format_run_result

        result = format_run_result("plain text")
        assert result == "plain text"


# ---------------------------------------------------------------------------
# MCP server creation
# ---------------------------------------------------------------------------


class TestCreateMcpServer:
    def test_returns_server_object(self, mock_fastmcp, sample_configs: Path):
        mock_server, _ = mock_fastmcp
        with patch("mcp.server.fastmcp.utilities.types.ToolAnnotations", None):
            from temper_ai.mcp.server import create_mcp_server

            server = create_mcp_server(str(sample_configs))
        assert server is mock_server

    def test_tools_registered(self, mock_fastmcp, sample_configs: Path):
        mock_server, registered = mock_fastmcp
        with patch("mcp.server.fastmcp.utilities.types.ToolAnnotations", None):
            from temper_ai.mcp.server import create_mcp_server

            create_mcp_server(str(sample_configs))

        expected = {"list_workflows", "list_agents", "run_workflow", "get_run_status"}
        assert expected.issubset(set(registered.keys()))


# ---------------------------------------------------------------------------
# _run_workflow_impl
# ---------------------------------------------------------------------------


class TestRunWorkflowImpl:
    def test_invalid_json_returns_error(self):
        from temper_ai.mcp.server import _run_workflow_impl

        result = _run_workflow_impl("any/path.yaml", "{not json}", "configs")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid JSON" in parsed["error"]

    def test_file_not_found_returns_error(self):
        from temper_ai.mcp.server import _run_workflow_impl

        result = _run_workflow_impl("/nonexistent/workflow.yaml", "{}", "configs")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    def test_successful_run(self, sample_configs: Path):
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "completed"}
        mock_engine.compile.return_value = mock_compiled

        mock_registry_instance = MagicMock()
        mock_registry_instance.get_engine_from_config.return_value = mock_engine

        wf_path = str(sample_configs / "workflows" / "demo.yaml")

        with (
            patch("temper_ai.workflow.config_loader.ConfigLoader"),
            patch("temper_ai.tools.registry.ToolRegistry"),
            patch("temper_ai.observability.tracker.ExecutionTracker"),
            patch(
                "temper_ai.workflow.engine_registry.EngineRegistry",
                return_value=mock_registry_instance,
            ),
        ):
            from temper_ai.mcp.server import _run_workflow_impl

            result = _run_workflow_impl(wf_path, "{}", str(sample_configs))

        parsed = json.loads(result)
        assert parsed["status"] == "completed"


# ---------------------------------------------------------------------------
# _get_run_status_impl
# ---------------------------------------------------------------------------


class TestGetRunStatusImpl:
    def test_run_not_found_returns_error(self):
        mock_store = MagicMock()
        mock_store.get_run.return_value = None

        with patch(
            "temper_ai.interfaces.server.run_store.RunStore", return_value=mock_store
        ):
            from temper_ai.mcp.server import _get_run_status_impl

            result = _get_run_status_impl("missing-run-id")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    def test_run_found_returns_data(self):
        mock_run = MagicMock()
        mock_run.model_dump.return_value = {"execution_id": "abc", "status": "completed"}
        mock_store = MagicMock()
        mock_store.get_run.return_value = mock_run

        with patch(
            "temper_ai.interfaces.server.run_store.RunStore", return_value=mock_store
        ):
            from temper_ai.mcp.server import _get_run_status_impl

            result = _get_run_status_impl("abc")

        parsed = json.loads(result)
        assert parsed["status"] == "completed"
        assert parsed["execution_id"] == "abc"
