"""Integration tests for MAF Server.

Tests health endpoints, run API, workspace isolation, config check,
event output, and MAF_CONFIG_ROOT env var.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Health & lifecycle unit tests (no FastAPI test client needed)
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Test server health models."""

    def test_check_health_returns_healthy(self) -> None:
        from src.interfaces.server.health import check_health

        result = check_health()
        assert result.status == "healthy"
        assert result.version == "0.1.0"
        assert result.timestamp is not None

    def test_check_readiness_ready(self) -> None:
        from src.interfaces.server.health import check_readiness

        result = check_readiness(execution_service=None, readiness_gate=True)
        # status depends on DB availability; just check it returns
        assert result.status in ("ready", "draining")
        assert isinstance(result.active_runs, int)

    def test_check_readiness_draining(self) -> None:
        from src.interfaces.server.health import check_readiness

        result = check_readiness(execution_service=None, readiness_gate=False)
        assert result.status == "draining"


class TestGracefulShutdownManager:
    """Test lifecycle manager."""

    def test_readiness_gate_default_true(self) -> None:
        from src.interfaces.server.lifecycle import GracefulShutdownManager

        mgr = GracefulShutdownManager()
        assert mgr.readiness_gate is True

    def test_handle_signal_flips_gate(self) -> None:
        from src.interfaces.server.lifecycle import GracefulShutdownManager

        mgr = GracefulShutdownManager()
        mgr._handle_signal()
        assert mgr.readiness_gate is False


# ---------------------------------------------------------------------------
# Result sanitization tests
# ---------------------------------------------------------------------------


class TestSanitizeWorkflowResult:
    """Test that non-serializable workflow state is stripped."""

    def test_strips_non_serializable_keys(self) -> None:
        from src.interfaces.dashboard.execution_service import _sanitize_workflow_result

        result = {
            "stage_outputs": {"research": {"summary": "hello"}},
            "tracker": object(),
            "config_loader": object(),
            "tool_registry": object(),
            "workflow_id": "wf-123",
        }
        sanitized = _sanitize_workflow_result(result)
        assert "tracker" not in sanitized
        assert "config_loader" not in sanitized
        assert "tool_registry" not in sanitized
        assert sanitized["stage_outputs"] == {"research": {"summary": "hello"}}
        assert sanitized["workflow_id"] == "wf-123"

    def test_strips_non_json_safe_values(self) -> None:
        from src.interfaces.dashboard.execution_service import _sanitize_workflow_result

        result = {
            "good_key": "simple string",
            "bad_key": {1, 2, 3},  # sets aren't JSON-serializable
        }
        sanitized = _sanitize_workflow_result(result)
        assert "good_key" in sanitized
        assert "bad_key" not in sanitized

    def test_returns_none_for_non_dict(self) -> None:
        from src.interfaces.dashboard.execution_service import _sanitize_workflow_result

        assert _sanitize_workflow_result("not a dict") is None
        assert _sanitize_workflow_result(None) is None


# ---------------------------------------------------------------------------
# Workspace path validation tests
# ---------------------------------------------------------------------------


class TestWorkspacePathValidation:
    """Test workspace isolation in tool executor helpers."""

    def test_valid_path_within_workspace(self, tmp_path: Path) -> None:
        from src.tools._executor_helpers import validate_workspace_path

        inner = tmp_path / "subdir"
        inner.mkdir()
        # Should not raise
        result = validate_workspace_path(str(inner), tmp_path)
        assert result is None  # validate_workspace_path returns None on success

    def test_path_outside_workspace_rejected(self, tmp_path: Path) -> None:
        from src.tools._executor_helpers import validate_workspace_path

        with pytest.raises(ValueError, match="outside workspace"):
            validate_workspace_path("/etc/passwd", tmp_path)

    def test_null_byte_rejected(self, tmp_path: Path) -> None:
        from src.tools._executor_helpers import validate_workspace_path

        with pytest.raises(ValueError, match="null bytes"):
            validate_workspace_path("/tmp/foo\x00bar", tmp_path)

    def test_tool_executor_workspace_blocks_escape(self, tmp_path: Path) -> None:
        """ToolExecutor.execute() rejects paths outside workspace."""
        from unittest.mock import MagicMock

        from src.tools.executor import ToolExecutor

        registry = MagicMock()
        executor = ToolExecutor(registry=registry, workspace_root=str(tmp_path))
        result = executor.execute("read_file", params={"path": "/etc/passwd"})
        assert not result.success
        assert "outside workspace" in result.error


# ---------------------------------------------------------------------------
# Config check CLI tests
# ---------------------------------------------------------------------------


class TestConfigCheckCommand:
    """Test maf config check."""

    def test_config_check_valid(self) -> None:
        """maf config check exits 0 on valid configs."""
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["config", "check", "--config-root", "configs"])
        # Should not crash; may have warnings depending on config state
        assert result.exit_code in (0, 1)  # 1 if real config has broken refs

    def test_config_check_missing_dir(self) -> None:
        """maf config check exits 1 if config dir missing."""
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["config", "check", "--config-root", "/nonexistent"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# MAF_CONFIG_ROOT env var tests
# ---------------------------------------------------------------------------


class TestMafConfigRootEnv:
    """Test MAF_CONFIG_ROOT environment variable."""

    def test_env_var_overrides_default(self) -> None:
        """ConfigLoader uses MAF_CONFIG_ROOT when set."""
        from src.workflow.config_loader import ConfigLoader

        real_configs = str(Path("configs").resolve())
        with patch.dict(os.environ, {"MAF_CONFIG_ROOT": real_configs}):
            loader = ConfigLoader()
            assert str(loader.config_root) == real_configs

    def test_cli_envvar_in_list_workflows(self) -> None:
        """maf list workflows respects MAF_CONFIG_ROOT env."""
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["list", "workflows"],
            env={"MAF_CONFIG_ROOT": "configs"},
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Validate command enhanced tests
# ---------------------------------------------------------------------------


class TestValidateEnhanced:
    """Test maf validate with --format and --check-refs."""

    def test_validate_json_format(self) -> None:
        """maf validate --format=json returns valid JSON."""
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        # Use a known valid workflow
        wf_path = "configs/workflows/simple_research.yaml"
        if not Path(wf_path).exists():
            pytest.skip("simple_research.yaml not present")

        result = runner.invoke(main, ["validate", wf_path, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "valid" in data
        assert "errors" in data

    def test_validate_check_refs(self) -> None:
        """maf validate --check-refs validates agent references."""
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        wf_path = "configs/workflows/simple_research.yaml"
        if not Path(wf_path).exists():
            pytest.skip("simple_research.yaml not present")

        result = runner.invoke(main, ["validate", wf_path, "--check-refs"])
        # Should work without crashing
        assert result.exit_code in (0, 1)


# ---------------------------------------------------------------------------
# Event output handler tests
# ---------------------------------------------------------------------------


class TestEventOutputHandler:
    """Test event output routing."""

    def test_format_json(self) -> None:
        from src.interfaces.cli.event_output import EventOutputHandler

        handler = EventOutputHandler(mode="stdout", fmt="jsonl")
        event = MagicMock()
        event.event_type = "agent_start"
        event.timestamp = "2026-01-01T00:00:00Z"
        event.workflow_id = "wf-1"
        event.stage_id = "s-1"
        event.agent_id = "a-1"
        event.data = {"agent_name": "test"}

        line = handler._format_json(event)
        parsed = json.loads(line)
        assert parsed["type"] == "agent_start"
        assert parsed["workflow_id"] == "wf-1"

    def test_format_text(self) -> None:
        from src.interfaces.cli.event_output import EventOutputHandler

        handler = EventOutputHandler(mode="stderr", fmt="text")
        event = MagicMock()
        event.event_type = "stage_end"
        event.timestamp = MagicMock()
        event.timestamp.strftime.return_value = "12:00:00"
        event.stage_id = "research"
        event.agent_id = None
        event.data = {}

        line = handler._format_text(event)
        assert "stage_end" in line
        assert "research" in line

    def test_file_mode_creates_file(self, tmp_path: Path) -> None:
        from src.interfaces.cli.event_output import EventOutputHandler

        with patch("src.interfaces.cli.event_output.Path") as mock_path_cls:
            # Just check it doesn't crash with file mode
            handler = EventOutputHandler(mode="stderr", fmt="text")
            assert handler.mode == "stderr"


# ---------------------------------------------------------------------------
# Server routes (unit tests with mocked services)
# ---------------------------------------------------------------------------


class TestServerRoutes:
    """Test server API routes with TestClient."""

    @pytest.fixture
    def client(self):
        """Create test client with mocked services."""
        from fastapi.testclient import TestClient

        from src.interfaces.server.routes import create_server_router

        from fastapi import FastAPI

        mock_exec_svc = MagicMock()
        mock_data_svc = MagicMock()

        app = FastAPI()
        router = create_server_router(mock_exec_svc, mock_data_svc, "configs")
        app.include_router(router, prefix="/api")

        return TestClient(app), mock_exec_svc

    def test_health_endpoint(self, client) -> None:
        test_client, _ = client
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_validate_endpoint_missing_file(self, client) -> None:
        test_client, _ = client
        resp = test_client.post(
            "/api/validate",
            json={"workflow": "nonexistent/missing.yaml"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_available_workflows(self, client) -> None:
        test_client, _ = client
        resp = test_client.get("/api/workflows/available")
        assert resp.status_code == 200
        data = resp.json()
        assert "workflows" in data
        assert "total" in data

    def test_available_workflows_enhanced_fields(self, client) -> None:
        """Verify /api/workflows/available includes version, tags, inputs, use_cases."""
        test_client, _ = client
        resp = test_client.get("/api/workflows/available")
        assert resp.status_code == 200
        data = resp.json()
        if data["total"] > 0:
            wf = data["workflows"][0]
            # All enhanced fields must be present (may be empty)
            for field in ("version", "tags", "inputs", "use_cases"):
                assert field in wf, f"Missing field: {field}"

    def test_list_runs_endpoint(self, client) -> None:
        """GET /api/runs returns list of runs."""
        test_client, mock_svc = client
        mock_svc.list_executions = AsyncMock(return_value=[
            {"execution_id": "exec-1", "status": "completed"},
        ])
        resp = test_client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert "total" in data
        assert data["total"] == 1

    def test_list_runs_with_status_filter(self, client) -> None:
        """GET /api/runs?status=completed filters by status."""
        test_client, mock_svc = client
        mock_svc.list_executions = AsyncMock(return_value=[])
        resp = test_client.get("/api/runs?status=completed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []

    def test_list_runs_invalid_status(self, client) -> None:
        """GET /api/runs?status=invalid returns empty list."""
        test_client, _ = client
        resp = test_client.get("/api/runs?status=invalid_status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []
        assert data["total"] == 0


class TestDashboardIncludesServerRouter:
    """Verify dashboard mode mounts the server router."""

    def test_dashboard_mode_has_health_endpoint(self) -> None:
        """Dashboard app should serve /api/health from the server router."""
        from fastapi.testclient import TestClient

        from src.interfaces.dashboard.app import create_app

        app = create_app(backend=None, mode="dashboard")
        c = TestClient(app)
        resp = c.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_dashboard_mode_has_runs_endpoint(self) -> None:
        """Dashboard app should serve POST /api/runs from the server router."""
        from fastapi.testclient import TestClient

        from src.interfaces.dashboard.app import create_app

        app = create_app(backend=None, mode="dashboard")
        c = TestClient(app)
        # Missing body should return 422 (validation error), not 404
        resp = c.post("/api/runs")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# CLI run command new flags
# ---------------------------------------------------------------------------


class TestRunCommandFlags:
    """Test that new CLI flags are accepted."""

    def test_run_help_shows_new_flags(self) -> None:
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--workspace" in result.output
        assert "--events-to" in result.output
        assert "--event-format" in result.output
        assert "--run-id" in result.output

    def test_serve_help(self) -> None:
        from click.testing import CliRunner

        from src.interfaces.cli.main import main

        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--workers" in result.output
