"""Tests for CLI run() helper functions (src/cli/main.py).

Tests cover the 7 helper functions extracted from run():
1. _setup_logging() - Configure logging based on verbosity and detail flags
2. _load_workflow_config() - Load and validate workflow config, load inputs
3. _start_dashboard_server() - Start dashboard server in background thread
4. _initialize_infrastructure() - Initialize database, registries, tracker, event bus
5. _execute_workflow() - Execute compiled workflow with tracking and error handling
6. _handle_post_execution() - Handle post-execution tasks (summary, reports, output)
7. _handle_dashboard_keepalive() - Keep dashboard server alive until user interrupts

Coverage target: 80%+ on helper functions
"""
import json
import logging
import signal
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, mock_open, patch

import pytest
import yaml

from src.interfaces.cli.main import (
    _execute_workflow,
    _handle_dashboard_keepalive,
    _handle_post_execution,
    _initialize_infrastructure,
    _load_workflow_config,
    _setup_logging,
    _start_dashboard_server,
)
from src.shared.utils.exceptions import WorkflowStageError


@pytest.fixture
def tmp_dir(tmp_path):
    """Create a temp directory for test files."""
    return tmp_path


@pytest.fixture
def mock_console():
    """Mock Rich Console."""
    with patch("src.interfaces.cli.main.console") as mock_console:
        yield mock_console


def _write_yaml(path: Path, data: dict) -> Path:
    """Helper to write YAML data to file."""
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _minimal_workflow(tmp_path: Path, name: str = "test_wf", required_inputs=None) -> Path:
    """Create a minimal valid workflow YAML."""
    wf = {
        "workflow": {
            "name": name,
            "description": "Test workflow",
            "stages": [{"name": "stage1", "stage_ref": "stages/test_stage.yaml"}],
            "error_handling": {"escalation_policy": "halt"},
        }
    }
    if required_inputs:
        wf["workflow"]["inputs"] = {"required": required_inputs}
    return _write_yaml(tmp_path / "workflow.yaml", wf)


# ─── TestSetupLogging ─────────────────────────────────────────────────


class TestSetupLogging:
    """Test _setup_logging() function."""

    def test_verbose_mode_sets_debug_level(self):
        """Test that verbose=True configures DEBUG level logging."""
        with patch("logging.basicConfig") as mock_config:
            _setup_logging(verbose=True, show_details=False)
            mock_config.assert_called_once()
            args, kwargs = mock_config.call_args
            assert kwargs["level"] == logging.DEBUG
            assert "%(asctime)s" in kwargs["format"]

    def test_non_verbose_sets_warning_level(self):
        """Test that verbose=False configures WARNING level logging."""
        with patch("logging.basicConfig") as mock_config:
            _setup_logging(verbose=False, show_details=False)
            mock_config.assert_called_once()
            args, kwargs = mock_config.call_args
            assert kwargs["level"] == logging.WARNING

    def test_show_details_attaches_rich_handler(self):
        """Test that show_details=True attaches RichHandler to src logger."""
        with patch("logging.basicConfig"), \
             patch("logging.getLogger") as mock_get_logger, \
             patch("src.interfaces.cli.main.console") as mock_console:

            mock_logger = Mock()
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            _setup_logging(verbose=False, show_details=True)

            mock_get_logger.assert_called_with("src")
            mock_logger.setLevel.assert_called_with(logging.INFO)
            assert mock_logger.propagate is False
            mock_logger.addHandler.assert_called_once()

    def test_show_details_does_not_duplicate_handler(self):
        """Test that RichHandler is not added twice."""
        with patch("logging.basicConfig"), \
             patch("logging.getLogger") as mock_get_logger, \
             patch("src.interfaces.cli.main.console"):

            from rich.logging import RichHandler
            existing_handler = Mock(spec=RichHandler)
            mock_logger = Mock()
            mock_logger.handlers = [existing_handler]
            mock_get_logger.return_value = mock_logger

            _setup_logging(verbose=False, show_details=True)

            # Should not add handler if RichHandler already exists
            mock_logger.addHandler.assert_not_called()


# ─── TestLoadWorkflowConfig ───────────────────────────────────────────


class TestLoadWorkflowConfig:
    """Test _load_workflow_config() function."""

    def test_load_valid_workflow_no_inputs(self, tmp_path):
        """Test loading a valid workflow without input file."""
        wf_path = _minimal_workflow(tmp_path)

        workflow_config, inputs = _load_workflow_config(
            workflow=str(wf_path),
            input_file=None,
            config_root="configs",
            verbose=False
        )

        assert workflow_config["workflow"]["name"] == "test_wf"
        assert inputs == {}

    def test_load_workflow_with_inputs(self, tmp_path):
        """Test loading workflow with input file."""
        wf_path = _minimal_workflow(tmp_path)
        input_path = tmp_path / "inputs.yaml"
        input_data = {"topic": "test topic", "context": "test context"}
        _write_yaml(input_path, input_data)

        workflow_config, inputs = _load_workflow_config(
            workflow=str(wf_path),
            input_file=str(input_path),
            config_root="configs",
            verbose=False
        )

        assert inputs == input_data

    def test_empty_input_file_returns_empty_dict(self, tmp_path):
        """Test that empty input file returns empty dict."""
        wf_path = _minimal_workflow(tmp_path)
        input_path = tmp_path / "empty_inputs.yaml"
        input_path.write_text("")

        workflow_config, inputs = _load_workflow_config(
            workflow=str(wf_path),
            input_file=str(input_path),
            config_root="configs",
            verbose=False
        )

        assert inputs == {}

    def test_missing_required_inputs_raises_system_exit(self, tmp_path, mock_console):
        """Test that missing required inputs raises SystemExit."""
        wf_path = _minimal_workflow(tmp_path, required_inputs=["topic", "context"])

        with pytest.raises(SystemExit) as exc_info:
            _load_workflow_config(
                workflow=str(wf_path),
                input_file=None,
                config_root="configs",
                verbose=False
            )

        assert exc_info.value.code == 1
        mock_console.print.assert_called()

    def test_partial_required_inputs_raises_system_exit(self, tmp_path, mock_console):
        """Test that partially provided required inputs raises SystemExit."""
        wf_path = _minimal_workflow(tmp_path, required_inputs=["topic", "context"])
        input_path = tmp_path / "partial_inputs.yaml"
        _write_yaml(input_path, {"topic": "test"})  # missing "context"

        with pytest.raises(SystemExit) as exc_info:
            _load_workflow_config(
                workflow=str(wf_path),
                input_file=str(input_path),
                config_root="configs",
                verbose=False
            )

        assert exc_info.value.code == 1
        assert any("Missing required inputs" in str(call) for call in mock_console.print.call_args_list)


# ─── TestStartDashboardServer ─────────────────────────────────────────


class TestStartDashboardServer:
    """Test _start_dashboard_server() function."""

    def test_start_dashboard_server_success(self, mock_console):
        """Test successful dashboard server start."""
        mock_backend = Mock()
        mock_event_bus = Mock()
        port = 8420

        with patch("src.interfaces.dashboard.app.create_app") as mock_create_app, \
             patch("uvicorn.Config") as mock_config, \
             patch("uvicorn.Server") as mock_server_class, \
             patch("threading.Thread") as mock_thread:

            mock_app = Mock()
            mock_create_app.return_value = mock_app
            mock_server = Mock()
            mock_server_class.return_value = mock_server
            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance

            result = _start_dashboard_server(mock_backend, mock_event_bus, port)

            mock_create_app.assert_called_once_with(backend=mock_backend, event_bus=mock_event_bus)
            mock_config.assert_called_once()
            mock_server_class.assert_called_once()
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()
            assert result == mock_server
            assert any("Dashboard:" in str(call) for call in mock_console.print.call_args_list)

    def test_start_dashboard_server_import_error(self, mock_console):
        """Test dashboard server returns None on import error."""
        mock_backend = Mock()
        mock_event_bus = Mock()

        with patch("builtins.__import__", side_effect=ImportError("uvicorn not found")):
            result = _start_dashboard_server(mock_backend, mock_event_bus, 8420)

            assert result is None
            assert any("Warning:" in str(call) and "Dashboard not available" in str(call)
                      for call in mock_console.print.call_args_list)

    def test_start_dashboard_server_custom_port(self, mock_console):
        """Test dashboard server with custom port."""
        with patch("src.interfaces.dashboard.app.create_app"), \
             patch("uvicorn.Config") as mock_config, \
             patch("uvicorn.Server"), \
             patch("threading.Thread"):

            _start_dashboard_server(Mock(), Mock(), 9999)

            # Check that Config was called with custom port
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["port"] == 9999


# ─── TestInitializeInfrastructure ─────────────────────────────────────


class TestInitializeInfrastructure:
    """Test _initialize_infrastructure() function."""

    def test_initialize_infrastructure_no_dashboard(self, tmp_path, mock_console):
        """Test infrastructure initialization without dashboard."""
        db_path = str(tmp_path / "test.db")

        with patch("src.workflow.config_loader.ConfigLoader") as mock_config_loader, \
             patch("src.tools.registry.ToolRegistry") as mock_tool_registry, \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker:

            mock_tracker_instance = Mock()
            mock_tracker.return_value = mock_tracker_instance
            mock_tracker.ensure_database = Mock()

            config_loader, tool_registry, tracker, event_bus, dashboard_server = \
                _initialize_infrastructure(
                    config_root="configs",
                    db_path=db_path,
                    dashboard_port=None,
                    verbose=False
                )

            mock_config_loader.assert_called_once_with(config_root="configs")
            mock_tool_registry.assert_called_once_with(auto_discover=True)
            assert event_bus is None
            assert dashboard_server is None

    def test_initialize_infrastructure_with_dashboard(self, tmp_path, mock_console):
        """Test infrastructure initialization with dashboard."""
        db_path = str(tmp_path / "test.db")

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker_class, \
             patch("src.observability.event_bus.ObservabilityEventBus") as mock_event_bus_class, \
             patch("src.interfaces.cli.main._start_dashboard_server") as mock_start_dashboard:

            mock_event_bus = Mock()
            mock_event_bus_class.return_value = mock_event_bus
            mock_tracker = Mock()
            mock_tracker.backend = Mock()
            mock_tracker_class.return_value = mock_tracker
            mock_tracker_class.ensure_database = Mock()
            mock_dashboard = Mock()
            mock_start_dashboard.return_value = mock_dashboard

            config_loader, tool_registry, tracker, event_bus, dashboard_server = \
                _initialize_infrastructure(
                    config_root="configs",
                    db_path=db_path,
                    dashboard_port=8420,
                    verbose=False
                )

            assert event_bus == mock_event_bus
            mock_start_dashboard.assert_called_once_with(mock_tracker.backend, mock_event_bus, 8420)
            assert dashboard_server == mock_dashboard

    def test_initialize_infrastructure_db_error(self, tmp_path, mock_console):
        """Test that database initialization errors raise SystemExit."""
        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker, \
             patch("pathlib.Path.mkdir", side_effect=PermissionError("Access denied")):

            mock_tracker.ensure_database = Mock()

            with pytest.raises(SystemExit) as exc_info:
                _initialize_infrastructure("configs", "test.db", None, False)

            assert exc_info.value.code == 1

    def test_initialize_infrastructure_import_error(self, mock_console):
        """Test that import errors raise SystemExit."""
        with patch("builtins.__import__", side_effect=ImportError("Module not found")):
            with pytest.raises(SystemExit) as exc_info:
                _initialize_infrastructure("configs", "test.db", None, False)

            assert exc_info.value.code == 1

    def test_initialize_infrastructure_event_bus_import_error(self, tmp_path, mock_console):
        """Test that event bus import error is handled gracefully."""
        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker_class, \
             patch("src.observability.event_bus.ObservabilityEventBus", side_effect=ImportError("Event bus unavailable")):

            mock_tracker = Mock()
            mock_tracker_class.return_value = mock_tracker
            mock_tracker_class.ensure_database = Mock()

            config_loader, tool_registry, tracker, event_bus, dashboard_server = \
                _initialize_infrastructure(
                    config_root="configs",
                    db_path="test.db",
                    dashboard_port=8420,
                    verbose=False
                )

            # Event bus should be None, warning should be printed
            assert event_bus is None
            assert any("Warning:" in str(call) for call in mock_console.print.call_args_list)

    def test_initialize_infrastructure_creates_db_directory(self, tmp_path):
        """Test that database parent directory is created."""
        db_path = tmp_path / "subdir" / "another" / "test.db"

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker:

            mock_tracker.ensure_database = Mock()

            _initialize_infrastructure(
                config_root="configs",
                db_path=str(db_path),
                dashboard_port=None,
                verbose=False
            )

            # Parent directories should be created
            assert db_path.parent.exists()

    def test_initialize_infrastructure_verbose_mode(self, tmp_path, mock_console):
        """Test infrastructure initialization in verbose mode."""
        with patch("builtins.__import__", side_effect=ImportError("test error")), \
             patch("src.interfaces.cli.main.logger") as mock_logger:

            with pytest.raises(SystemExit):
                _initialize_infrastructure("configs", "test.db", None, verbose=True)

            # Should log exception in verbose mode
            mock_logger.exception.assert_called()

    def test_initialize_infrastructure_auto_discover_tools(self, tmp_path):
        """Test that tools are auto-discovered."""
        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry") as mock_tool_registry, \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker:

            mock_tracker.ensure_database = Mock()

            _initialize_infrastructure("configs", "test.db", None, False)

            mock_tool_registry.assert_called_once_with(auto_discover=True)


# ─── TestExecuteWorkflow ──────────────────────────────────────────────


class TestExecuteWorkflow:
    """Test _execute_workflow() function."""

    def test_execute_workflow_success(self, mock_console):
        """Test successful workflow execution."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {"status": "completed", "result": "success"}

        params = WorkflowExecutionParams(
            compiled=mock_compiled,
            workflow_config={"workflow": {"name": "test"}},
            inputs={"topic": "test"},
            tracker=Mock(),
            config_loader=Mock(),
            tool_registry=Mock(),
            workflow_id="wf-123",
            show_details=False,
            engine=Mock(),
            verbose=False
        )
        result = _execute_workflow(params)

        assert result["status"] == "completed"
        mock_compiled.invoke.assert_called_once()

    def test_execute_workflow_with_stream_display(self, mock_console):
        """Test workflow execution with stream display enabled."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.return_value = {"status": "completed"}

        with patch("src.interfaces.cli.stream_display.StreamDisplay") as mock_stream_display_class:
            mock_stream_display = Mock()
            mock_stream_display_class.return_value = mock_stream_display

            params = WorkflowExecutionParams(
                compiled=mock_compiled,
                workflow_config={},
                inputs={},
                tracker=Mock(),
                config_loader=Mock(),
                tool_registry=Mock(),
                workflow_id="wf-123",
                show_details=True,
                engine=Mock(),
                verbose=False
            )
            result = _execute_workflow(params)

            mock_stream_display_class.assert_called_once()
            # Verify stream_callback was passed in state
            call_args = mock_compiled.invoke.call_args
            state = call_args[0][0]
            assert state["stream_callback"] == mock_stream_display

    def test_execute_workflow_stage_error(self, mock_console):
        """Test workflow execution with stage error."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.side_effect = WorkflowStageError("stage1", "Test error")
        mock_engine = Mock()

        with patch("src.interfaces.cli.main._cleanup_tool_executor") as mock_cleanup:
            with pytest.raises(SystemExit) as exc_info:
                params = WorkflowExecutionParams(
                    compiled=mock_compiled,
                    workflow_config={},
                    inputs={},
                    tracker=Mock(),
                    config_loader=Mock(),
                    tool_registry=Mock(),
                    workflow_id="wf-123",
                    show_details=False,
                    engine=mock_engine,
                    verbose=False
                )
                _execute_workflow(params)

            assert exc_info.value.code == 1
            mock_cleanup.assert_called_once_with(mock_engine)

    def test_execute_workflow_runtime_error(self, mock_console):
        """Test workflow execution with runtime error."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.side_effect = RuntimeError("Execution failed")
        mock_engine = Mock()

        with patch("src.interfaces.cli.main._cleanup_tool_executor") as mock_cleanup:
            with pytest.raises(SystemExit) as exc_info:
                params = WorkflowExecutionParams(
                    compiled=mock_compiled,
                    workflow_config={},
                    inputs={},
                    tracker=Mock(),
                    config_loader=Mock(),
                    tool_registry=Mock(),
                    workflow_id="wf-123",
                    show_details=False,
                    engine=mock_engine,
                    verbose=False
                )
                _execute_workflow(params)

            assert exc_info.value.code == 1
            mock_cleanup.assert_called_once_with(mock_engine)

    def test_execute_workflow_value_error(self, mock_console):
        """Test workflow execution with value error."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.side_effect = ValueError("Invalid value")

        with patch("src.interfaces.cli.main._cleanup_tool_executor"):
            with pytest.raises(SystemExit) as exc_info:
                params = WorkflowExecutionParams(
                    compiled=mock_compiled,
                    workflow_config={},
                    inputs={},
                    tracker=Mock(),
                    config_loader=Mock(),
                    tool_registry=Mock(),
                    workflow_id="wf-123",
                    show_details=False,
                    engine=Mock(),
                    verbose=False
                )
                _execute_workflow(params)

            assert exc_info.value.code == 1

    def test_execute_workflow_keyboard_interrupt(self, mock_console):
        """Test workflow execution handles keyboard interrupt."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.side_effect = KeyboardInterrupt()
        mock_engine = Mock()

        with patch("src.interfaces.cli.main._cleanup_tool_executor") as mock_cleanup, \
             patch("src.interfaces.cli.main.EXIT_CODE_KEYBOARD_INTERRUPT", 130):
            with pytest.raises(SystemExit) as exc_info:
                params = WorkflowExecutionParams(
                    compiled=mock_compiled,
                    workflow_config={},
                    inputs={},
                    tracker=Mock(),
                    config_loader=Mock(),
                    tool_registry=Mock(),
                    workflow_id="wf-123",
                    show_details=False,
                    engine=mock_engine,
                    verbose=False
                )
                _execute_workflow(params)

            assert exc_info.value.code == 130
            mock_cleanup.assert_called_once_with(mock_engine)

    def test_execute_workflow_system_exit_passthrough(self):
        """Test that SystemExit is passed through."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        mock_compiled = Mock()
        mock_compiled.invoke.side_effect = SystemExit(42)

        with pytest.raises(SystemExit) as exc_info:
            params = WorkflowExecutionParams(
                compiled=mock_compiled,
                workflow_config={},
                inputs={},
                tracker=Mock(),
                config_loader=Mock(),
                tool_registry=Mock(),
                workflow_id="wf-123",
                show_details=False,
                engine=Mock(),
                verbose=False
            )
            _execute_workflow(params)

        assert exc_info.value.code == 42


# ─── TestHandlePostExecution ──────────────────────────────────────────


class TestHandlePostExecution:
    """Test _handle_post_execution() function."""

    def test_handle_post_execution_basic(self, mock_console):
        """Test basic post-execution handling."""
        result = {"status": "completed", "result": "test"}

        with patch("src.interfaces.cli.main._print_run_summary") as mock_summary:
            _handle_post_execution(
                result=result,
                show_details=False,
                output=None,
                workflow_id="wf-123",
                workflow_name="test_workflow",
                verbose=False
            )

            mock_summary.assert_called_once_with("test_workflow", "wf-123", result)

    def test_handle_post_execution_with_detailed_report(self, mock_console):
        """Test post-execution with detailed report."""
        result = {"status": "completed", "stages": []}

        with patch("src.interfaces.cli.main._print_run_summary"), \
             patch("src.interfaces.cli.detail_report.print_detailed_report") as mock_detailed:

            _handle_post_execution(
                result=result,
                show_details=True,
                output=None,
                workflow_id="wf-123",
                workflow_name="test_workflow",
                verbose=False
            )

            mock_detailed.assert_called_once_with(result, mock_console)

    def test_handle_post_execution_detailed_report_import_error(self, mock_console):
        """Test that import error in detailed report is handled gracefully."""
        result = {"status": "completed"}

        with patch("src.interfaces.cli.main._print_run_summary"), \
             patch("src.interfaces.cli.main.logger") as mock_logger:

            # Mock the import to fail
            def mock_import(name, *args, **kwargs):
                if "detail_report" in name:
                    raise ImportError("Module not found")
                return __import__(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                # Should not raise exception
                _handle_post_execution(
                    result=result,
                    show_details=True,
                    output=None,
                    workflow_id="wf-123",
                    workflow_name="test",
                    verbose=False
                )

            mock_logger.debug.assert_called()

    def test_handle_post_execution_with_gantt_chart(self, mock_console):
        """Test post-execution with gantt chart display."""
        result = {"status": "completed"}

        with patch("src.interfaces.cli.main._print_run_summary"), \
             patch("examples.export_waterfall.export_waterfall_trace") as mock_export, \
             patch("src.observability.visualize_trace.print_console_gantt") as mock_gantt, \
             patch("sys.path", []):

            mock_export.return_value = {"workflow_id": "wf-123", "stages": []}

            _handle_post_execution(
                result=result,
                show_details=False,
                output=None,
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            mock_export.assert_called_once_with("wf-123")
            mock_gantt.assert_called_once()

    def test_handle_post_execution_gantt_with_error(self, mock_console):
        """Test that gantt chart errors are handled gracefully."""
        result = {"status": "completed"}

        with patch("src.interfaces.cli.main._print_run_summary"), \
             patch("examples.export_waterfall.export_waterfall_trace", return_value={"error": "trace error"}), \
             patch("src.observability.visualize_trace.print_console_gantt") as mock_gantt:

            _handle_post_execution(
                result=result,
                show_details=False,
                output=None,
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            # Should not call gantt if error in trace
            mock_gantt.assert_not_called()

    def test_handle_post_execution_save_output(self, tmp_path, mock_console):
        """Test saving output to file."""
        result = {"status": "completed", "result": "test"}
        output_path = tmp_path / "output.json"

        with patch("src.interfaces.cli.main._print_run_summary"):
            _handle_post_execution(
                result=result,
                show_details=False,
                output=str(output_path),
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            assert output_path.exists()
            with open(output_path) as f:
                saved_data = json.load(f)
            assert saved_data == result

    def test_handle_post_execution_save_output_creates_parent_dirs(self, tmp_path, mock_console):
        """Test that parent directories are created when saving output."""
        result = {"status": "completed"}
        output_path = tmp_path / "subdir" / "another" / "output.json"

        with patch("src.interfaces.cli.main._print_run_summary"):
            _handle_post_execution(
                result=result,
                show_details=False,
                output=str(output_path),
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            assert output_path.exists()
            assert output_path.parent.exists()

    def test_handle_post_execution_save_output_error(self, tmp_path, mock_console):
        """Test that output save errors are handled gracefully."""
        result = {"status": "completed"}

        with patch("src.interfaces.cli.main._print_run_summary"), \
             patch("builtins.open", side_effect=PermissionError("Access denied")):

            # Should not raise exception
            _handle_post_execution(
                result=result,
                show_details=False,
                output="/invalid/path/output.json",
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            assert any("Error saving results" in str(call) for call in mock_console.print.call_args_list)

    def test_handle_post_execution_non_dict_result(self, mock_console):
        """Test post-execution with non-dict result."""
        result = "simple string result"

        with patch("src.interfaces.cli.main._print_run_summary") as mock_summary, \
             patch("src.interfaces.cli.detail_report.print_detailed_report") as mock_detailed:

            _handle_post_execution(
                result=result,
                show_details=True,
                output=None,
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

            mock_summary.assert_called_once()
            # Should not attempt detailed report for non-dict
            mock_detailed.assert_not_called()


# ─── TestHandleDashboardKeepalive ─────────────────────────────────────


class TestHandleDashboardKeepalive:
    """Test _handle_dashboard_keepalive() function.

    Note: Tests for signal.pause() and time.sleep() blocking behavior are skipped
    because they're difficult to test reliably without hanging the test suite.
    The function's behavior with KeyboardInterrupt is covered by integration tests.
    """

    def test_handle_dashboard_keepalive_none_server(self, mock_console):
        """Test that None server returns immediately."""
        _handle_dashboard_keepalive(dashboard_server=None, dashboard_port=8420)

        # Should not print anything or block
        mock_console.print.assert_not_called()

    def test_handle_dashboard_keepalive_prints_running_message(self, mock_console):
        """Test that keepalive prints running message before blocking."""
        mock_server = Mock()

        # We can't easily test the blocking behavior without hanging,
        # but we can verify the initial message is printed
        import threading
        import time

        def run_keepalive():
            try:
                _handle_dashboard_keepalive(mock_server, 8420)
            except:  # noqa: E722
                pass

        thread = threading.Thread(target=run_keepalive, daemon=True)
        thread.start()
        time.sleep(0.1)  # Give thread time to print

        # Should print running message
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("Dashboard running" in call for call in calls)

    def test_handle_dashboard_keepalive_custom_port(self, mock_console):
        """Test dashboard keepalive prints correct port."""
        mock_server = Mock()

        import threading
        import time

        def run_keepalive():
            try:
                _handle_dashboard_keepalive(mock_server, 9999)
            except:  # noqa: E722
                pass

        thread = threading.Thread(target=run_keepalive, daemon=True)
        thread.start()
        time.sleep(0.1)

        # Should print custom port
        calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("9999" in call for call in calls)


# ─── TestIntegration ──────────────────────────────────────────────────


class TestIntegration:
    """Integration tests combining multiple helper functions."""

    def test_full_workflow_setup_to_execution(self, tmp_path, mock_console):
        """Test complete flow from setup to execution."""
        wf_path = _minimal_workflow(tmp_path)

        # 1. Setup logging
        with patch("logging.basicConfig"):
            _setup_logging(verbose=False, show_details=False)

        # 2. Load workflow config
        workflow_config, inputs = _load_workflow_config(
            workflow=str(wf_path),
            input_file=None,
            config_root="configs",
            verbose=False
        )

        assert workflow_config is not None
        assert inputs == {}

    def test_initialize_and_execute_workflow(self, tmp_path):
        """Test infrastructure initialization followed by execution."""
        db_path = str(tmp_path / "test.db")

        with patch("src.workflow.config_loader.ConfigLoader") as mock_config_loader, \
             patch("src.tools.registry.ToolRegistry") as mock_tool_registry, \
             patch("src.observability.tracker.ExecutionTracker") as mock_tracker_class:

            mock_tracker = Mock()
            mock_tracker_class.return_value = mock_tracker
            mock_tracker_class.ensure_database = Mock()

            # Initialize infrastructure
            config_loader, tool_registry, tracker, event_bus, dashboard_server = \
                _initialize_infrastructure(
                    config_root="configs",
                    db_path=db_path,
                    dashboard_port=None,
                    verbose=False
                )

            # Execute workflow
            from src.interfaces.cli.main import WorkflowExecutionParams

            mock_compiled = Mock()
            mock_compiled.invoke.return_value = {"status": "completed"}

            params = WorkflowExecutionParams(
                compiled=mock_compiled,
                workflow_config={},
                inputs={},
                tracker=tracker,
                config_loader=config_loader,
                tool_registry=tool_registry,
                workflow_id="wf-123",
                show_details=False,
                engine=Mock(),
                verbose=False
            )
            result = _execute_workflow(params)

            assert result["status"] == "completed"

    def test_execute_and_post_execution_with_output(self, tmp_path, mock_console):
        """Test workflow execution followed by post-execution handling with output."""
        from src.interfaces.cli.main import WorkflowExecutionParams

        # Execute
        mock_compiled = Mock()
        result = {"status": "completed", "duration": 5.5}
        mock_compiled.invoke.return_value = result

        params = WorkflowExecutionParams(
            compiled=mock_compiled,
            workflow_config={},
            inputs={},
            tracker=Mock(),
            config_loader=Mock(),
            tool_registry=Mock(),
            workflow_id="wf-123",
            show_details=False,
            engine=Mock(),
            verbose=False
        )
        exec_result = _execute_workflow(params)

        # Post-execution
        output_path = tmp_path / "result.json"
        with patch("src.interfaces.cli.main._print_run_summary"):
            _handle_post_execution(
                result=exec_result,
                show_details=False,
                output=str(output_path),
                workflow_id="wf-123",
                workflow_name="test",
                verbose=False
            )

        assert output_path.exists()
        with open(output_path) as f:
            saved = json.load(f)
        assert saved == result
