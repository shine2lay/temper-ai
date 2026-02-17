"""Tests for CLI experiment commands."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.interfaces.cli.experiment_commands import experiment_group


@pytest.fixture
def runner():
    """Create a Click CLI runner."""
    return CliRunner()


@pytest.fixture
def mock_service():
    """Create a mock ExperimentService."""
    svc = MagicMock()
    svc.list_experiments.return_value = []
    return svc


def _patch_service(mock_svc):
    """Return a patch context for _get_service."""
    return patch(
        "src.interfaces.cli.experiment_commands._get_service",
        return_value=mock_svc,
    )


class TestListCommand:
    """Tests for `maf experiment list`."""

    def test_list_empty(self, runner, mock_service):
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["list"])
        assert result.exit_code == 0
        assert "No experiments found" in result.output

    def test_list_with_experiments(self, runner, mock_service):
        from datetime import datetime, timezone

        exp = MagicMock()
        exp.id = "exp-001-abcdef"
        exp.name = "temp_test"
        exp.status = MagicMock(value="running")
        exp.primary_metric = "duration_seconds"
        exp.total_executions = 5
        exp.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_service.list_experiments.return_value = [exp]

        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["list"])
        assert result.exit_code == 0
        assert "temp_test" in result.output
        assert "running" in result.output

    def test_list_with_status_filter(self, runner, mock_service):
        mock_service.list_experiments.return_value = []
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["list", "--status", "draft"])
        assert result.exit_code == 0


class TestCreateCommand:
    """Tests for `maf experiment create`."""

    def test_create_success(self, runner, mock_service, tmp_path):
        variants_file = tmp_path / "variants.yaml"
        variants_file.write_text(
            "variants:\n"
            "  - name: control\n"
            "    is_control: true\n"
            "    traffic: 0.5\n"
            "    config: {}\n"
            "  - name: treatment\n"
            "    traffic: 0.5\n"
            "    config:\n"
            "      temperature: 0.9\n"
        )
        mock_service.create_experiment.return_value = "exp-new-123"

        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, [
                "create",
                "--name", "my_experiment",
                "--variants-file", str(variants_file),
            ])
        assert result.exit_code == 0
        assert "exp-new-123" in result.output

    def test_create_empty_variants(self, runner, mock_service, tmp_path):
        variants_file = tmp_path / "empty.yaml"
        variants_file.write_text("variants: []\n")

        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, [
                "create",
                "--name", "test",
                "--variants-file", str(variants_file),
            ])
        assert result.exit_code != 0
        assert "No variants" in result.output


class TestStartCommand:
    """Tests for `maf experiment start`."""

    def test_start_success(self, runner, mock_service):
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["start", "exp-001"])
        assert result.exit_code == 0
        assert "Started" in result.output

    def test_start_error(self, runner, mock_service):
        mock_service.start_experiment.side_effect = ValueError("Not found")
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["start", "exp-bad"])
        assert result.exit_code != 0
        assert "Error" in result.output


class TestStopCommand:
    """Tests for `maf experiment stop`."""

    def test_stop_success(self, runner, mock_service):
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["stop", "exp-001"])
        assert result.exit_code == 0
        assert "Stopped" in result.output

    def test_stop_with_winner(self, runner, mock_service):
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["stop", "exp-001", "--winner", "var-a"])
        assert result.exit_code == 0
        assert "winner" in result.output


class TestResultsCommand:
    """Tests for `maf experiment results`."""

    def test_results_success(self, runner, mock_service):
        mock_service.get_experiment_results.return_value = {
            "sample_size": 200,
            "recommendation": MagicMock(value="continue"),
            "confidence": 0.87,
            "variant_metrics": {
                "control": {"mean": 45.0, "std": 5.0, "count": 100},
                "treatment": {"mean": 40.0, "std": 4.5, "count": 100},
            },
            "guardrail_violations": [],
        }

        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["results", "exp-001"])
        assert result.exit_code == 0
        assert "200" in result.output
        assert "87" in result.output

    def test_results_error(self, runner, mock_service):
        mock_service.get_experiment_results.side_effect = ValueError("Not found")
        with _patch_service(mock_service):
            result = runner.invoke(experiment_group, ["results", "exp-bad"])
        assert result.exit_code != 0
        assert "Error" in result.output
