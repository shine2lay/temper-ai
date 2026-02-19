"""Tests for the CLI entry point (src/cli/main.py).

Tests cover:
- Root group and version option
- Validate command (schema validation, stage reference checks)
- List commands (workflows, agents, stages) with missing directories
- Run command (missing inputs, workflow execution errors)
- Helper functions (_load_and_validate_workflow, _print_run_summary)
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from src.interfaces.cli.main import (
    _load_and_validate_workflow,
    _print_run_summary,
    main,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_dir(tmp_path):
    """Create a temp directory with a minimal valid workflow config."""
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


class TestRootGroup:
    """Test the root CLI group."""

    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Meta-Autonomous Framework CLI" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_no_command_shows_usage(self, runner):
        result = runner.invoke(main, [])
        # Click returns exit code 2 for missing required subcommand
        assert result.exit_code == 2 or result.exit_code == 0
        assert "Usage:" in result.output


class TestValidateCommand:
    """Test the validate command."""

    def test_validate_empty_file(self, runner, tmp_path):
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        result = runner.invoke(main, ["validate", str(empty_file)])
        assert result.exit_code != 0
        assert "Empty workflow file" in result.output

    def test_validate_invalid_schema(self, runner, tmp_path):
        bad = _write_yaml(tmp_path / "bad.yaml", {"not_workflow": True})
        result = runner.invoke(main, ["validate", str(bad)])
        assert result.exit_code != 0
        assert "Validation error" in result.output

    def test_validate_valid_workflow_missing_stage_ref(self, runner, tmp_path):
        wf_path = _minimal_workflow(tmp_path)
        result = runner.invoke(main, [
            "validate", str(wf_path),
            "--config-root", str(tmp_path / "nonexistent_configs"),
        ])
        assert result.exit_code != 0
        assert "Stage file not found" in result.output or "Reference errors" in result.output

    def test_validate_valid_workflow_with_stage_and_agent(self, runner, tmp_path):
        # Create config structure
        stages_dir = tmp_path / "configs" / "stages"
        agents_dir = tmp_path / "configs" / "agents"
        stages_dir.mkdir(parents=True)
        agents_dir.mkdir(parents=True)

        _write_yaml(stages_dir / "test_stage.yaml", {
            "stage": {"name": "test_stage", "agents": ["test_agent"]}
        })
        _write_yaml(agents_dir / "test_agent.yaml", {
            "agent": {"name": "test_agent", "description": "Test", "type": "standard"}
        })

        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": str(stages_dir / "test_stage.yaml")}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)
        result = runner.invoke(main, [
            "validate", str(wf_path),
            "--config-root", str(tmp_path / "configs"),
        ])
        assert result.exit_code == 0
        assert "All references valid" in result.output


class TestListCommands:
    """Test the list subcommands."""

    def test_list_workflows_missing_dir(self, runner, tmp_path):
        result = runner.invoke(main, [
            "list", "workflows",
            "--config-root", str(tmp_path / "missing"),
        ])
        assert result.exit_code != 0
        assert "Directory not found" in result.output

    def test_list_workflows(self, runner, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        _write_yaml(wf_dir / "my_workflow.yaml", {
            "workflow": {
                "name": "My Workflow",
                "description": "A test",
                "stages": [{"name": "s1"}],
            }
        })
        result = runner.invoke(main, ["list", "workflows", "--config-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "My Workflow" in result.output

    def test_list_agents_missing_dir(self, runner, tmp_path):
        result = runner.invoke(main, [
            "list", "agents",
            "--config-root", str(tmp_path / "missing"),
        ])
        assert result.exit_code != 0
        assert "Directory not found" in result.output

    def test_list_agents(self, runner, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        _write_yaml(agents_dir / "my_agent.yaml", {
            "agent": {"name": "My Agent", "description": "Test agent", "type": "standard"}
        })
        result = runner.invoke(main, ["list", "agents", "--config-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "My Agent" in result.output

    def test_list_stages_missing_dir(self, runner, tmp_path):
        result = runner.invoke(main, [
            "list", "stages",
            "--config-root", str(tmp_path / "missing"),
        ])
        assert result.exit_code != 0
        assert "Directory not found" in result.output

    def test_list_stages(self, runner, tmp_path):
        stages_dir = tmp_path / "stages"
        stages_dir.mkdir()
        _write_yaml(stages_dir / "my_stage.yaml", {
            "stage": {
                "name": "My Stage",
                "description": "Test stage",
                "agents": ["agent1", {"name": "agent2"}],
            }
        })
        result = runner.invoke(main, ["list", "stages", "--config-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "My Stage" in result.output

    def test_list_workflows_empty_yaml_skipped(self, runner, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "empty.yaml").write_text("")
        result = runner.invoke(main, ["list", "workflows", "--config-root", str(tmp_path)])
        assert result.exit_code == 0


class TestRunCommand:
    """Test the run command."""

    def test_run_missing_required_inputs(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "inputs": {"required": ["topic"]},
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)
        result = runner.invoke(main, ["run", str(wf_path), "--local"])
        assert result.exit_code != 0
        assert "Missing required inputs" in result.output

    def test_run_with_input_file(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "inputs": {"required": ["topic"]},
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)
        input_path = _write_yaml(tmp_path / "inputs.yaml", {"topic": "AI Safety"})

        # Mock the execution pipeline to avoid needing real infrastructure.
        # These are imported locally in run(), so patch at their source modules.
        with patch("src.workflow.config_loader.ConfigLoader") as mock_cl, \
             patch("src.tools.registry.ToolRegistry") as mock_tr, \
             patch("src.observability.tracker.ExecutionTracker") as mock_et, \
             patch("src.workflow.engine_registry.EngineRegistry") as mock_er:
            mock_engine = MagicMock()
            mock_compiled = MagicMock()
            mock_compiled.invoke.return_value = {"status": "completed", "duration": 1.0}
            mock_engine.compile.return_value = mock_compiled
            mock_er.return_value.get_engine_from_config.return_value = mock_engine
            mock_et.return_value.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-123")
            mock_et.return_value.track_workflow.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(main, [
                "run", str(wf_path), "--local",
                "--input", str(input_path),
            ])
            assert result.exit_code == 0
            assert "test_wf" in result.output

    def test_run_nonexistent_workflow(self, runner):
        result = runner.invoke(main, ["run", "/nonexistent/path.yaml"])
        assert result.exit_code != 0

    def test_run_empty_workflow(self, runner, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        result = runner.invoke(main, ["run", str(empty), "--local"])
        assert result.exit_code != 0
        assert "Empty workflow file" in result.output


class TestLoadAndValidateWorkflow:
    """Test the _load_and_validate_workflow helper."""

    def test_valid_workflow(self, tmp_path):
        wf = {
            "workflow": {
                "name": "test",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        path = _write_yaml(tmp_path / "wf.yaml", wf)
        config = _load_and_validate_workflow(str(path))
        assert config["workflow"]["name"] == "test"

    def test_empty_workflow_raises(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        with pytest.raises(SystemExit):
            _load_and_validate_workflow(str(empty))

    def test_invalid_schema_raises(self, tmp_path):
        bad = _write_yaml(tmp_path / "bad.yaml", {"bad": True})
        with pytest.raises(SystemExit):
            _load_and_validate_workflow(str(bad))


class TestPrintRunSummary:
    """Test the _print_run_summary helper."""

    def test_summary_with_dict_result(self, capsys):
        _print_run_summary("test_wf", "wf-123", {
            "status": "completed",
            "duration": 2.5,
            "total_tokens": 1000,
            "total_cost": 0.0123,
        })
        # Function uses Rich console, output goes to console not capsys
        # Just verify it doesn't raise
        assert True  # Function completed without exception

    def test_summary_with_non_dict_result(self, capsys):
        _print_run_summary("test_wf", "wf-123", "simple result")
        # Verify no exception
        assert True  # Function completed without exception

    def test_summary_with_failed_status(self, capsys):
        _print_run_summary("test_wf", "wf-123", {"status": "failed"})
        # Verify no exception
        assert True  # Function completed without exception


class TestM5Subcommands:
    """Test the m5 subcommand group."""

    def test_m5_help(self, runner):
        result = runner.invoke(main, ["m5", "--help"])
        assert result.exit_code == 0
        assert "M5 self-improvement commands" in result.output


class TestRunCommandAdvanced:
    """Test advanced run command scenarios."""

    def test_run_with_verbose_logging(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_et, \
             patch("src.workflow.engine_registry.EngineRegistry") as mock_er:
            mock_engine = MagicMock()
            mock_compiled = MagicMock()
            mock_compiled.invoke.return_value = {"status": "completed"}
            mock_engine.compile.return_value = mock_compiled
            mock_er.return_value.get_engine_from_config.return_value = mock_engine
            mock_et.return_value.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-123")
            mock_et.return_value.track_workflow.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(main, ["run", str(wf_path), "--local", "-v"])
            assert result.exit_code == 0

    def test_run_with_output_file(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)
        output_path = tmp_path / "output.json"

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_et, \
             patch("src.workflow.engine_registry.EngineRegistry") as mock_er:
            mock_engine = MagicMock()
            mock_compiled = MagicMock()
            mock_compiled.invoke.return_value = {"status": "completed", "result": "test"}
            mock_engine.compile.return_value = mock_compiled
            mock_er.return_value.get_engine_from_config.return_value = mock_engine
            mock_et.return_value.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-123")
            mock_et.return_value.track_workflow.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(main, ["run", str(wf_path), "--local", "-o", str(output_path)])
            assert result.exit_code == 0
            assert output_path.exists()

    def test_run_database_initialization_error(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_et:
            mock_et.ensure_database.side_effect = PermissionError("Cannot create database")

            result = runner.invoke(main, ["run", str(wf_path), "--local"])
            assert result.exit_code != 0

    def test_run_compilation_error(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_et, \
             patch("src.workflow.engine_registry.EngineRegistry") as mock_er:
            mock_engine = MagicMock()
            mock_engine.compile.side_effect = ValueError("Invalid workflow structure")
            mock_er.return_value.get_engine_from_config.return_value = mock_engine

            result = runner.invoke(main, ["run", str(wf_path), "--local"])
            assert result.exit_code != 0
            assert "compilation error" in result.output

    def test_run_execution_error(self, runner, tmp_path):
        wf = {
            "workflow": {
                "name": "test_wf",
                "description": "Test",
                "stages": [{"name": "s1", "stage_ref": "stages/s1.yaml"}],
                "error_handling": {"escalation_policy": "halt"},
            }
        }
        wf_path = _write_yaml(tmp_path / "workflow.yaml", wf)

        with patch("src.workflow.config_loader.ConfigLoader"), \
             patch("src.tools.registry.ToolRegistry"), \
             patch("src.observability.tracker.ExecutionTracker") as mock_et, \
             patch("src.workflow.engine_registry.EngineRegistry") as mock_er:
            mock_engine = MagicMock()
            mock_compiled = MagicMock()
            mock_compiled.invoke.side_effect = RuntimeError("Execution failed")
            mock_engine.compile.return_value = mock_compiled
            mock_er.return_value.get_engine_from_config.return_value = mock_engine
            mock_et.return_value.track_workflow.return_value.__enter__ = MagicMock(return_value="wf-123")
            mock_et.return_value.track_workflow.return_value.__exit__ = MagicMock(return_value=False)

            result = runner.invoke(main, ["run", str(wf_path), "--local"])
            assert result.exit_code != 0
            assert "execution error" in result.output


class TestCleanupToolExecutor:
    """Test the _cleanup_tool_executor helper function."""

    def test_cleanup_with_tool_executor_direct(self):
        from src.interfaces.cli.main import _cleanup_tool_executor

        mock_engine = MagicMock()
        mock_tool_executor = MagicMock()
        mock_engine.tool_executor = mock_tool_executor

        _cleanup_tool_executor(mock_engine)
        mock_tool_executor.shutdown.assert_called_once()

    def test_cleanup_with_tool_executor_via_compiler(self):
        from src.interfaces.cli.main import _cleanup_tool_executor

        mock_engine = MagicMock()
        mock_tool_executor = MagicMock()
        del mock_engine.tool_executor  # Remove direct attribute
        mock_engine.compiler.tool_executor = mock_tool_executor

        _cleanup_tool_executor(mock_engine)
        mock_tool_executor.shutdown.assert_called_once()

    def test_cleanup_with_no_tool_executor(self):
        from src.interfaces.cli.main import _cleanup_tool_executor

        mock_engine = MagicMock()
        del mock_engine.tool_executor
        del mock_engine.compiler

        # Should not raise exception - verify it completes successfully
        result = _cleanup_tool_executor(mock_engine)
        # Function returns None, verify no exception was raised
        assert result is None

    def test_cleanup_with_shutdown_error(self):
        from src.interfaces.cli.main import _cleanup_tool_executor

        mock_engine = MagicMock()
        mock_tool_executor = MagicMock()
        mock_tool_executor.shutdown.side_effect = Exception("Shutdown failed")
        mock_engine.tool_executor = mock_tool_executor

        # Should not raise exception, just log - verify it completes successfully
        result = _cleanup_tool_executor(mock_engine)
        # Function returns None, verify no exception was raised
        assert result is None
