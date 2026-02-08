"""
Comprehensive tests for src/self_improvement/cli.py.

Tests the M5CLI command-line interface for self-improvement operations.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.self_improvement.cli import M5CLI


# ========== Fixtures ==========


@pytest.fixture
def cli():
    """Create M5CLI instance."""
    with patch('src.self_improvement.cli.get_session'):
        cli_instance = M5CLI()
        cli_instance.coord_db = Mock()
        return cli_instance


@pytest.fixture
def mock_loop():
    """Create mock M5SelfImprovementLoop."""
    loop = Mock()
    loop.run_iteration = Mock()
    loop.get_state = Mock()
    loop.get_progress = Mock()
    loop.get_metrics = Mock()
    loop.pause = Mock()
    loop.resume = Mock()
    loop.reset_state = Mock()
    loop.health_check = Mock()
    return loop


@pytest.fixture
def sample_iteration_result():
    """Sample iteration result."""
    result = Mock()
    result.success = True
    result.iteration_number = 1
    result.phases_completed = [Mock(value="detection"), Mock(value="analysis")]
    result.duration_seconds = 10.5
    result.detection_result = Mock(has_problem=False)
    result.deployment_result = Mock(
        deployment_id="dep_123",
        rollback_monitoring_enabled=True
    )
    result.error = None
    result.error_phase = None
    return result


@pytest.fixture
def sample_loop_state():
    """Sample loop state."""
    return {
        "current_phase": "detection",
        "status": "running",
        "iteration_number": 5,
        "started_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T01:00:00",
        "last_error": None
    }


@pytest.fixture
def sample_progress():
    """Sample progress data."""
    progress = Mock()
    progress.health_status = "healthy"
    progress.total_iterations_completed = 10
    return progress


@pytest.fixture
def sample_metrics():
    """Sample metrics data."""
    return {
        "total_iterations": 100,
        "successful_iterations": 95,
        "failed_iterations": 5,
        "success_rate": 0.95,
        "avg_iteration_duration": 12.5,
        "total_experiments": 50,
        "successful_deployments": 40,
        "rollbacks": 5,
        "phase_success_rates": {
            "detection": 0.98,
            "analysis": 0.96,
            "generation": 0.94,
            "evaluation": 0.92,
            "deployment": 0.90
        },
        "last_iteration_at": "2024-01-01T12:00:00"
    }


@pytest.fixture
def sample_health():
    """Sample health check data."""
    return {
        "status": "healthy",
        "timestamp": "2024-01-01T12:00:00",
        "components": {
            "database": "healthy",
            "storage": "healthy",
            "metrics": "healthy"
        }
    }


# ========== Tests for Initialization ==========


def test_cli_initialization():
    """Test M5CLI initialization."""
    with patch('src.self_improvement.cli.get_session'):
        cli = M5CLI()
        assert cli is not None


# ========== Tests for run_iteration ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_run_iteration_success(mock_get_session, mock_loop_class, cli, sample_iteration_result, capsys):
    """Test successful run iteration."""
    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.return_value = sample_iteration_result
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.run_iteration("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Starting M5" in captured.out
    assert "completed successfully" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_run_iteration_failure(mock_get_session, mock_loop_class, cli, capsys):
    """Test failed run iteration."""
    result = Mock()
    result.success = False
    result.error = "Test error"
    result.error_phase = Mock(value="analysis")

    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.return_value = result
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.run_iteration("test_agent")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "failed" in captured.out
    assert "Test error" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_run_iteration_with_config(mock_get_session, mock_loop_class, cli, sample_iteration_result, tmp_path):
    """Test run iteration with config file."""
    config_file = tmp_path / "config.json"
    config_data = {"key": "value"}
    with open(config_file, "w") as f:
        json.dump(config_data, f)

    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.return_value = sample_iteration_result
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.run_iteration("test_agent", str(config_file))

    assert exit_code == 0


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_run_iteration_exception(mock_get_session, mock_loop_class, cli, capsys):
    """Test run iteration handles exceptions."""
    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.side_effect = RuntimeError("Unexpected error")
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.run_iteration("test_agent")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error running iteration" in captured.out


# ========== Tests for analyze ==========


@patch('src.self_improvement.cli.PerformanceAnalyzer')
@patch('src.self_improvement.cli.get_session')
def test_analyze_success(mock_get_session, mock_analyzer_class, cli, capsys):
    """Test successful performance analysis."""
    profile = Mock()
    profile.total_executions = 100
    profile.window_start = Mock(strftime=lambda x: "2024-01-01 00:00")
    profile.window_end = Mock(strftime=lambda x: "2024-01-01 23:59")
    profile.metrics = {
        "accuracy": {"mean": 0.95, "std": 0.05},
        "latency": {"mean": 1.5, "std": 0.2}
    }

    mock_analyzer_instance = Mock()
    mock_analyzer_instance.analyze_agent_performance.return_value = profile
    mock_analyzer_class.return_value = mock_analyzer_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.analyze("test_agent", window_hours=168)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Analyzing performance" in captured.out
    assert "100" in captured.out


@patch('src.self_improvement.cli.PerformanceAnalyzer')
@patch('src.self_improvement.cli.get_session')
def test_analyze_exception(mock_get_session, mock_analyzer_class, cli, capsys):
    """Test analyze handles exceptions."""
    mock_analyzer_instance = Mock()
    mock_analyzer_instance.analyze_agent_performance.side_effect = RuntimeError("Analysis failed")
    mock_analyzer_class.return_value = mock_analyzer_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.analyze("test_agent")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Analysis failed" in captured.out


# ========== Tests for optimize ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_optimize(mock_get_session, mock_loop_class, cli, sample_iteration_result):
    """Test optimize command (alias for run_iteration)."""
    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.return_value = sample_iteration_result
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.optimize("test_agent")

    assert exit_code == 0


# ========== Tests for status ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_status_with_state(mock_get_session, mock_loop_class, cli, sample_loop_state, sample_progress, capsys):
    """Test status command with existing state."""
    mock_loop_instance = Mock()
    mock_loop_instance.get_state.return_value = sample_loop_state
    mock_loop_instance.get_progress.return_value = sample_progress
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.status("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Loop Status" in captured.out
    assert "detection" in captured.out
    assert "running" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_status_no_state(mock_get_session, mock_loop_class, cli, capsys):
    """Test status command with no state."""
    mock_loop_instance = Mock()
    mock_loop_instance.get_state.return_value = None
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.status("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No loop state found" in captured.out


# ========== Tests for metrics ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_metrics_with_data(mock_get_session, mock_loop_class, cli, sample_metrics, capsys):
    """Test metrics command with data."""
    mock_loop_instance = Mock()
    mock_loop_instance.get_metrics.return_value = sample_metrics
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.metrics("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Metrics" in captured.out
    assert "100" in captured.out
    assert "95.0%" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_metrics_no_data(mock_get_session, mock_loop_class, cli, capsys):
    """Test metrics command with no data."""
    mock_loop_instance = Mock()
    mock_loop_instance.get_metrics.return_value = None
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.metrics("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No metrics available" in captured.out


# ========== Tests for pause/resume/reset ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_pause_success(mock_get_session, mock_loop_class, cli, capsys):
    """Test pause command."""
    mock_loop_instance = Mock()
    mock_loop_instance.pause.return_value = None
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.pause("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Pausing" in captured.out
    assert "paused" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_pause_failure(mock_get_session, mock_loop_class, cli, capsys):
    """Test pause command failure."""
    mock_loop_instance = Mock()
    mock_loop_instance.pause.side_effect = RuntimeError("Pause failed")
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.pause("test_agent")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Failed to pause" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_resume_success(mock_get_session, mock_loop_class, cli, capsys):
    """Test resume command."""
    mock_loop_instance = Mock()
    mock_loop_instance.resume.return_value = None
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.resume("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resuming" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_reset_success(mock_get_session, mock_loop_class, cli, capsys, monkeypatch):
    """Test reset command with confirmation."""
    monkeypatch.setattr('builtins.input', lambda _: 'y')

    mock_loop_instance = Mock()
    mock_loop_instance.reset_state.return_value = None
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.reset("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resetting" in captured.out
    assert "reset" in captured.out


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_reset_cancelled(mock_get_session, mock_loop_class, cli, capsys, monkeypatch):
    """Test reset command cancelled."""
    monkeypatch.setattr('builtins.input', lambda _: 'n')

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.reset("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Cancelled" in captured.out


# ========== Tests for health ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_health_healthy(mock_get_session, mock_loop_class, cli, sample_health, capsys):
    """Test health command with healthy status."""
    mock_loop_instance = Mock()
    mock_loop_instance.health_check.return_value = sample_health
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.health()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Health Check" in captured.out
    assert "healthy" in captured.out.lower()


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.get_session')
def test_health_unhealthy(mock_get_session, mock_loop_class, cli, capsys):
    """Test health command with unhealthy status."""
    unhealthy = {
        "status": "unhealthy",
        "timestamp": "2024-01-01T12:00:00",
        "components": {
            "database": "unhealthy",
            "storage": "healthy"
        }
    }

    mock_loop_instance = Mock()
    mock_loop_instance.health_check.return_value = unhealthy
    mock_loop_class.return_value = mock_loop_instance

    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.health()

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "unhealthy" in captured.out.lower()


# ========== Tests for check_experiments ==========


@patch('src.self_improvement.experiment_orchestrator.ExperimentOrchestrator')
@patch('src.self_improvement.cli.get_session')
def test_check_experiments_with_data(mock_get_session, mock_orchestrator_class, cli, capsys):
    """Test check_experiments with data."""
    experiments = [
        {
            "id": "exp_1",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00"
        },
        {
            "id": "exp_2",
            "status": "running",
            "created_at": "2024-01-02T00:00:00"
        }
    ]

    mock_orchestrator_instance = Mock()
    mock_orchestrator_instance.analyze_experiment.return_value = {"winner_variant_id": "variant_1"}
    mock_orchestrator_class.return_value = mock_orchestrator_instance

    mock_session = Mock()
    mock_session.query.return_value = experiments
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.check_experiments("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Checking experiments" in captured.out


@patch('src.self_improvement.cli.get_session')
def test_check_experiments_no_data(mock_get_session, cli, capsys):
    """Test check_experiments with no data."""
    mock_session = Mock()
    mock_session.query.return_value = []
    mock_get_session.return_value.__enter__.return_value = mock_session

    exit_code = cli.check_experiments("test_agent")

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No experiments found" in captured.out


# ========== Tests for list_agents ==========


def test_list_agents_with_data(cli, capsys):
    """Test list_agents with data."""
    rows = [
        {
            "agent_name": "agent1",
            "current_phase": "detection",
            "status": "running",
            "iteration_number": 5
        },
        {
            "agent_name": "agent2",
            "current_phase": "analysis",
            "status": "paused",
            "iteration_number": 3
        }
    ]

    cli.coord_db.query.return_value = rows

    exit_code = cli.list_agents()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "agent1" in captured.out
    assert "agent2" in captured.out


def test_list_agents_no_data(cli, capsys):
    """Test list_agents with no data."""
    cli.coord_db.query.return_value = []

    exit_code = cli.list_agents()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No agents found" in captured.out


# ========== Tests for _load_config ==========


def test_load_config_from_file(cli, tmp_path):
    """Test loading config from file."""
    config_file = tmp_path / "config.json"
    config_data = {
        "detection_threshold": 0.8,
        "window_hours": 168
    }
    with open(config_file, "w") as f:
        json.dump(config_data, f)

    with patch('src.self_improvement.cli.LoopConfig') as mock_config_class:
        mock_config_class.from_dict.return_value = Mock()
        config = cli._load_config(str(config_file))

        mock_config_class.from_dict.assert_called_once_with(config_data)


def test_load_config_file_not_found(cli, capsys):
    """Test loading config from non-existent file."""
    with patch('src.self_improvement.cli.LoopConfig') as mock_config_class:
        mock_config_class.return_value = Mock()
        config = cli._load_config("/nonexistent/config.json")

        # Should return defaults and print warning
        mock_config_class.assert_called_once()
        captured = capsys.readouterr()
        assert "not found" in captured.out


def test_load_config_invalid_json(cli, tmp_path, capsys):
    """Test loading invalid JSON config."""
    config_file = tmp_path / "invalid.json"
    config_file.write_text("{invalid json}")

    with patch('src.self_improvement.cli.LoopConfig') as mock_config_class:
        mock_config_class.return_value = Mock()
        config = cli._load_config(str(config_file))

        # Should return defaults and print warning
        mock_config_class.assert_called_once()
        captured = capsys.readouterr()
        assert "Error loading config" in captured.out


def test_load_config_none(cli):
    """Test loading config with None."""
    with patch('src.self_improvement.cli.LoopConfig') as mock_config_class:
        mock_config_class.return_value = Mock()
        config = cli._load_config(None)

        # Should return defaults
        mock_config_class.assert_called_once()


# ========== Tests for main function ==========


@patch('src.self_improvement.cli.M5CLI')
def test_main_run_command(mock_cli_class):
    """Test main function with run command."""
    from src.self_improvement.cli import main

    mock_cli_instance = Mock()
    mock_cli_instance.run_iteration.return_value = 0
    mock_cli_class.return_value = mock_cli_instance

    with patch('sys.argv', ['m5', 'run', 'test_agent']):
        exit_code = main()

    assert exit_code == 0


@patch('src.self_improvement.cli.M5CLI')
def test_main_no_command(mock_cli_class, capsys):
    """Test main function with no command."""
    from src.self_improvement.cli import main

    with patch('sys.argv', ['m5']):
        exit_code = main()

    assert exit_code == 1


# ========== Integration tests ==========


@patch('src.self_improvement.cli.M5SelfImprovementLoop')
@patch('src.self_improvement.cli.PerformanceAnalyzer')
@patch('src.self_improvement.cli.get_session')
def test_full_workflow_integration(mock_get_session, mock_analyzer_class, mock_loop_class, cli):
    """Integration test for complete workflow."""
    # Setup mocks
    mock_session = Mock()
    mock_get_session.return_value.__enter__.return_value = mock_session

    # Run iteration
    result = Mock()
    result.success = True
    result.iteration_number = 1
    result.phases_completed = []
    result.duration_seconds = 10.0
    result.detection_result = None
    result.deployment_result = None

    mock_loop_instance = Mock()
    mock_loop_instance.run_iteration.return_value = result
    mock_loop_class.return_value = mock_loop_instance

    # Analyze
    profile = Mock()
    profile.total_executions = 50
    profile.window_start = Mock(strftime=lambda x: "2024-01-01 00:00")
    profile.window_end = Mock(strftime=lambda x: "2024-01-01 23:59")
    profile.metrics = {}

    mock_analyzer_instance = Mock()
    mock_analyzer_instance.analyze_agent_performance.return_value = profile
    mock_analyzer_class.return_value = mock_analyzer_instance

    # Execute workflow
    assert cli.run_iteration("test_agent") == 0
    assert cli.analyze("test_agent") == 0
    assert cli.pause("test_agent") == 0
    assert cli.resume("test_agent") == 0
