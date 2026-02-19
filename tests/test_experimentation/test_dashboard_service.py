"""Tests for ExperimentDataService."""

from unittest.mock import MagicMock, patch

import pytest

from temper_ai.experimentation.dashboard_service import ExperimentDataService, _experiment_to_dict


@pytest.fixture
def mock_experiment():
    """Create a mock experiment with standard attributes."""
    from datetime import datetime, timezone

    exp = MagicMock()
    exp.id = "exp-001"
    exp.name = "test_experiment"
    exp.description = "Test description"
    exp.status = MagicMock(value="running")
    exp.assignment_strategy = MagicMock(value="random")
    exp.primary_metric = "duration_seconds"
    exp.confidence_level = 0.95
    exp.total_executions = 10
    exp.winner_variant_id = None
    exp.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp.started_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    exp.stopped_at = None
    exp.tags = ["test"]
    return exp


@pytest.fixture
def service():
    """Create ExperimentDataService with mocked internals."""
    with patch("temper_ai.experimentation.dashboard_service.ExperimentDataService.__init__", return_value=None):
        svc = ExperimentDataService.__new__(ExperimentDataService)
        svc._service = MagicMock()
        return svc


class TestExperimentToDict:
    """Tests for the _experiment_to_dict helper."""

    def test_converts_experiment_to_dict(self, mock_experiment):
        result = _experiment_to_dict(mock_experiment)
        assert result["id"] == "exp-001"
        assert result["name"] == "test_experiment"
        assert result["status"] == "running"
        assert result["assignment_strategy"] == "random"
        assert result["primary_metric"] == "duration_seconds"
        assert result["tags"] == ["test"]

    def test_handles_none_timestamps(self, mock_experiment):
        mock_experiment.stopped_at = None
        result = _experiment_to_dict(mock_experiment)
        assert result["stopped_at"] is None

    def test_handles_string_status(self):
        """Test that plain string status (no .value attr) is handled."""
        exp = MagicMock()
        exp.id = "exp-002"
        exp.name = "plain_status"
        exp.description = "Test"
        exp.status = "draft"
        exp.assignment_strategy = "random"
        exp.primary_metric = "metric"
        exp.confidence_level = 0.95
        exp.total_executions = 0
        exp.winner_variant_id = None
        exp.created_at = None
        exp.started_at = None
        exp.stopped_at = None
        exp.tags = []
        result = _experiment_to_dict(exp)
        assert result["status"] == "draft"


class TestListExperiments:
    """Tests for ExperimentDataService.list_experiments."""

    def test_returns_list_of_dicts(self, service, mock_experiment):
        service._service.list_experiments.return_value = [mock_experiment]
        result = service.list_experiments()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["id"] == "exp-001"

    def test_empty_list(self, service):
        service._service.list_experiments.return_value = []
        result = service.list_experiments()
        assert result == []

    def test_status_filter(self, service, mock_experiment):
        service._service.list_experiments.return_value = [mock_experiment]
        result = service.list_experiments(status="running")
        assert len(result) == 1
        service._service.list_experiments.assert_called_once()

    def test_limit(self, service, mock_experiment):
        service._service.list_experiments.return_value = [mock_experiment] * 5
        result = service.list_experiments(limit=2)
        assert len(result) == 2


class TestGetExperiment:
    """Tests for ExperimentDataService.get_experiment."""

    def test_returns_dict_for_existing(self, service, mock_experiment):
        service._service.get_experiment.return_value = mock_experiment
        result = service.get_experiment("exp-001")
        assert result is not None
        assert result["id"] == "exp-001"

    def test_returns_none_for_missing(self, service):
        service._service.get_experiment.return_value = None
        result = service.get_experiment("nonexistent")
        assert result is None


class TestGetResults:
    """Tests for ExperimentDataService.get_results."""

    def test_returns_results(self, service, mock_experiment):
        service._service.get_experiment.return_value = mock_experiment
        service._service.get_experiment_results.return_value = {
            "sample_size": 100,
            "recommendation": "continue",
        }
        result = service.get_results("exp-001")
        assert result is not None
        assert result["sample_size"] == 100

    def test_returns_none_for_missing_experiment(self, service):
        service._service.get_experiment.return_value = None
        result = service.get_results("nonexistent")
        assert result is None

    def test_returns_none_on_value_error(self, service, mock_experiment):
        service._service.get_experiment.return_value = mock_experiment
        service._service.get_experiment_results.side_effect = ValueError("No data")
        result = service.get_results("exp-001")
        assert result is None
