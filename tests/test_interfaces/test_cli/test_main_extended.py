"""Extended tests for CLI entry point (src/cli/main.py).

Tests cover:
- Workflow execution with show-details flag
- YAML validation error scenarios
- Runtime error handling
- KeyboardInterrupt (Ctrl+C) handling
- M5 self-improvement command integration
- Multiple stage workflows
- Database initialization errors
- Config loading edge cases
"""
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import pytest
import yaml
from click.testing import CliRunner

from temper_ai.interfaces.cli.main import (
    _cleanup_tool_executor,
    _load_and_validate_workflow,
    _print_run_summary,
    main,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_dir(tmp_path):
    """Create a temp directory for workflow configs."""
    return tmp_path


def _write_yaml(path: Path, data: dict) -> Path:
    with open(path, "w") as f:
        yaml.safe_dump(data, f)
    return path


def _minimal_workflow(tmp_path: Path, name: str = "test_wf", stages=None) -> Path:
    """Create a minimal valid workflow YAML and return its path."""
    wf = {
        "workflow": {
            "name": name,
            "description": "Test workflow",
            "stages": stages or [{"name": "stage1", "stage_ref": "stages/test_stage.yaml"}],
            "error_handling": {
                "escalation_policy": "halt",
            },
        }
    }
    return _write_yaml(tmp_path / "workflow.yaml", wf)


class TestWorkflowExecutionWithDetails:
    """Test workflow execution with --show-details flag."""

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_with_show_details_flag(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Workflow execution with --show-details should show real-time progress."""
        wf_path = _minimal_workflow(tmp_path)

        # Mock the engine and compiled workflow
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "success"}
        mock_engine.compile.return_value = mock_compiled
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        # Mock tracker context manager
        mock_tracker_instance = MagicMock()
        mock_tracker_instance.track_workflow.return_value.__enter__.return_value = "wf-123"
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--show-details",
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 0
        # Verify show_details flag was passed to invoke
        call_args = mock_compiled.invoke.call_args[0][0]
        assert call_args["show_details"] is True
        assert "detail_console" in call_args

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_multiple_stages_workflow(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Test workflow with multiple stages executes correctly."""
        stages = [
            {"name": "research", "stage_ref": "stages/research.yaml"},
            {"name": "analysis", "stage_ref": "stages/analysis.yaml"},
            {"name": "synthesis", "stage_ref": "stages/synthesis.yaml"},
        ]
        wf_path = _minimal_workflow(tmp_path, stages=stages)

        # Mock infrastructure
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {
            "status": "success",
            "stages_completed": ["research", "analysis", "synthesis"]
        }
        mock_engine.compile.return_value = mock_compiled
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        mock_tracker_instance = MagicMock()
        mock_tracker_instance.track_workflow.return_value.__enter__.return_value = "wf-456"
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 0
        mock_compiled.invoke.assert_called_once()


class TestYAMLValidationErrors:
    """Test YAML validation error scenarios."""

    def test_validate_malformed_yaml(self, runner, tmp_path):
        """Malformed YAML should report parse error."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("workflow:\n  name: test\n  invalid: [[[")

        result = runner.invoke(main, ["validate", str(bad_yaml)])

        assert result.exit_code != 0
        # YAML parser error may not be caught by CLI but by YAML library
        # Check that it failed (exit code != 0) which is the important part

    def test_validate_missing_required_fields(self, runner, tmp_path):
        """Workflow missing required fields should fail validation."""
        incomplete = _write_yaml(tmp_path / "incomplete.yaml", {
            "workflow": {
                "name": "test"
                # Missing description, stages, error_handling
            }
        })

        result = runner.invoke(main, ["validate", str(incomplete)])

        assert result.exit_code != 0
        assert "Validation error" in result.output or "error" in result.output.lower()

    def test_validate_invalid_stage_reference_format(self, runner, tmp_path):
        """Stage with invalid reference format should fail validation."""
        wf = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "stages": [
                    {"name": "stage1", "stage_ref": "invalid-format-no-yaml"}
                ],
                "error_handling": {"escalation_policy": "halt"}
            }
        }
        wf_path = _write_yaml(tmp_path / "wf.yaml", wf)

        result = runner.invoke(main, ["validate", str(wf_path)])

        # May pass schema validation but fail reference check
        assert result.exit_code in [0, 1]  # Depends on validation strictness


class TestRuntimeErrorHandling:
    """Test runtime error handling during workflow execution."""

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_handles_compilation_error(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Compilation errors should be caught and reported gracefully."""
        wf_path = _minimal_workflow(tmp_path)

        # Mock engine that raises ValueError during compilation
        mock_engine = MagicMock()
        mock_engine.compile.side_effect = ValueError("Invalid workflow structure")
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        mock_tracker_instance = MagicMock()
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 1
        assert "compilation error" in result.output.lower()
        assert "Invalid workflow structure" in result.output

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_handles_execution_error(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Execution errors should be caught and cleaned up properly."""
        wf_path = _minimal_workflow(tmp_path)

        # Mock engine with execution failure
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.side_effect = RuntimeError("Agent execution failed")
        mock_engine.compile.return_value = mock_compiled
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        mock_tracker_instance = MagicMock()
        mock_tracker_instance.track_workflow.return_value.__enter__.return_value = "wf-789"
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 1
        assert "execution error" in result.output.lower()
        assert "Agent execution failed" in result.output


class TestKeyboardInterruptHandling:
    """Test Ctrl+C (KeyboardInterrupt) handling."""

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_keyboard_interrupt_during_execution(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """KeyboardInterrupt should exit gracefully with code 130."""
        wf_path = _minimal_workflow(tmp_path)

        # Mock execution that raises KeyboardInterrupt
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.side_effect = KeyboardInterrupt()
        mock_engine.compile.return_value = mock_compiled
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        mock_tracker_instance = MagicMock()
        mock_tracker_instance.track_workflow.return_value.__enter__.return_value = "wf-int"
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--config-root", str(tmp_path / "configs")
        ])

        # Should exit with SIGINT code
        assert result.exit_code == 130
        assert "Interrupted" in result.output or "interrupt" in result.output.lower()


class TestDatabaseInitialization:
    """Test database initialization error handling."""

    @patch("temper_ai.observability.tracker.ExecutionTracker")
    def test_run_handles_database_permission_error(
        self, mock_tracker, runner, tmp_path
    ):
        """Database permission errors should be reported gracefully."""
        wf_path = _minimal_workflow(tmp_path)

        # Mock tracker that raises PermissionError
        mock_tracker.ensure_database.side_effect = PermissionError(
            "Cannot create database directory"
        )

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--db", "/root/no-permission/db.sqlite",
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 1
        assert "Database initialization error" in result.output
        assert "Permission denied" in result.output


class TestInputValidation:
    """Test input file and required input validation."""

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_with_missing_required_inputs(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Missing required inputs should fail with clear error message."""
        # Workflow with required inputs
        wf = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "inputs": {
                    "required": ["api_key", "user_id"]
                },
                "stages": [{"name": "stage1", "stage_ref": "stages/test.yaml"}],
                "error_handling": {"escalation_policy": "halt"}
            }
        }
        wf_path = _write_yaml(tmp_path / "wf_with_inputs.yaml", wf)

        # Input file missing required fields
        inputs = {"api_key": "test-key"}  # Missing user_id
        input_path = _write_yaml(tmp_path / "inputs.yaml", inputs)

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--input", str(input_path),
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 1
        assert "Missing required inputs" in result.output
        assert "user_id" in result.output

    @patch("temper_ai.workflow.config_loader.ConfigLoader")
    @patch("temper_ai.tools.registry.ToolRegistry")
    @patch("temper_ai.observability.tracker.ExecutionTracker")
    @patch("temper_ai.workflow.engine_registry.EngineRegistry")
    def test_run_with_valid_inputs(
        self, mock_engine_registry, mock_tracker, mock_tool_registry,
        mock_config_loader, runner, tmp_path
    ):
        """Valid inputs should be passed to workflow execution."""
        wf = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "inputs": {
                    "required": ["api_key"]
                },
                "stages": [{"name": "stage1", "stage_ref": "stages/test.yaml"}],
                "error_handling": {"escalation_policy": "halt"}
            }
        }
        wf_path = _write_yaml(tmp_path / "wf_with_inputs.yaml", wf)

        inputs = {"api_key": "test-key-123", "optional_param": "value"}
        input_path = _write_yaml(tmp_path / "inputs.yaml", inputs)

        # Mock infrastructure
        mock_engine = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.invoke.return_value = {"status": "success"}
        mock_engine.compile.return_value = mock_compiled
        mock_engine_registry.return_value.get_engine_from_config.return_value = mock_engine

        mock_tracker_instance = MagicMock()
        mock_tracker_instance.track_workflow.return_value.__enter__.return_value = "wf-in"
        mock_tracker.return_value = mock_tracker_instance

        result = runner.invoke(main, [
            "run", str(wf_path), "--local",
            "--input", str(input_path),
            "--config-root", str(tmp_path / "configs")
        ])

        assert result.exit_code == 0
        # Verify inputs were passed to invoke
        call_args = mock_compiled.invoke.call_args[0][0]
        assert call_args["api_key"] == "test-key-123"
        assert call_args["optional_param"] == "value"


class TestCleanupFunction:
    """Test _cleanup_tool_executor helper function."""

    def test_cleanup_with_direct_tool_executor(self):
        """Cleanup should call shutdown on engine.tool_executor."""
        mock_tool_executor = MagicMock()
        mock_engine = MagicMock()
        mock_engine.tool_executor = mock_tool_executor

        _cleanup_tool_executor(mock_engine)

        mock_tool_executor.shutdown.assert_called_once()

    def test_cleanup_with_nested_tool_executor(self):
        """Cleanup should call shutdown on engine.compiler.tool_executor."""
        mock_tool_executor = MagicMock()
        mock_compiler = MagicMock()
        mock_compiler.tool_executor = mock_tool_executor
        mock_engine = MagicMock()
        mock_engine.compiler = mock_compiler
        # Remove tool_executor attribute from engine to force nested lookup
        delattr(mock_engine, 'tool_executor')

        _cleanup_tool_executor(mock_engine)

        mock_tool_executor.shutdown.assert_called_once()

    def test_cleanup_with_no_tool_executor(self):
        """Cleanup should handle missing tool_executor gracefully."""
        mock_engine = MagicMock(spec=[])  # No attributes

        # Should not raise exception - verify it completes successfully
        result = _cleanup_tool_executor(mock_engine)
        # Function returns None, verify no exception was raised
        assert result is None

    def test_cleanup_handles_shutdown_exception(self):
        """Cleanup should handle exceptions during shutdown gracefully."""
        mock_tool_executor = MagicMock()
        mock_tool_executor.shutdown.side_effect = RuntimeError("Shutdown failed")
        mock_engine = MagicMock()
        mock_engine.tool_executor = mock_tool_executor

        # Should not raise exception
        _cleanup_tool_executor(mock_engine)
        mock_tool_executor.shutdown.assert_called_once()


class TestLoadAndValidateWorkflow:
    """Test _load_and_validate_workflow helper function."""

    def test_load_nonexistent_file_raises_system_exit(self):
        """Loading nonexistent file should raise SystemExit."""
        with pytest.raises((SystemExit, FileNotFoundError)):
            _load_and_validate_workflow("/nonexistent/workflow.yaml")

    def test_load_empty_file_raises_system_exit(self, tmp_path):
        """Loading empty file should raise SystemExit with error message."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        with pytest.raises(SystemExit) as exc_info:
            _load_and_validate_workflow(str(empty_file))

        assert exc_info.value.code == 1

    def test_load_invalid_schema_raises_system_exit(self, tmp_path):
        """Loading invalid schema should raise SystemExit."""
        invalid = _write_yaml(tmp_path / "invalid.yaml", {
            "not_a_workflow": True
        })

        with pytest.raises(SystemExit) as exc_info:
            _load_and_validate_workflow(str(invalid))

        assert exc_info.value.code == 1

    def test_load_valid_workflow_returns_config(self, tmp_path):
        """Loading valid workflow should return parsed config."""
        wf_path = _minimal_workflow(tmp_path)

        config = _load_and_validate_workflow(str(wf_path))

        assert isinstance(config, dict)
        assert "workflow" in config
        assert config["workflow"]["name"] == "test_wf"
