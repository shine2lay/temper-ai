"""Tests for experimentation dashboard routes."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.experimentation.dashboard_routes import create_experimentation_router
from temper_ai.experimentation.dashboard_service import ExperimentDataService


@pytest.fixture
def mock_service():
    """Create a mock ExperimentDataService."""
    svc = MagicMock(spec=ExperimentDataService)
    svc._service = MagicMock()
    return svc


@pytest.fixture
def client(mock_service):
    """Create a FastAPI TestClient with experimentation routes."""
    app = FastAPI()
    router = create_experimentation_router(mock_service)
    app.include_router(router, prefix="/api")
    return TestClient(app)


SAMPLE_EXPERIMENT = {
    "id": "exp-001",
    "name": "test_experiment",
    "description": "Test",
    "status": "running",
    "primary_metric": "duration_seconds",
    "total_executions": 10,
}

SAMPLE_RESULTS = {
    "sample_size": 100,
    "recommendation": "continue",
    "confidence": 0.85,
    "variant_metrics": {},
}


class TestListExperiments:
    """Tests for GET /api/experiments."""

    def test_list_returns_experiments(self, client, mock_service):
        mock_service.list_experiments.return_value = [SAMPLE_EXPERIMENT]
        resp = client.get("/api/experiments")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == "exp-001"

    def test_list_with_status_filter(self, client, mock_service):
        mock_service.list_experiments.return_value = []
        resp = client.get("/api/experiments?status=draft")
        assert resp.status_code == 200
        mock_service.list_experiments.assert_called_once_with(status="draft", limit=50)

    def test_list_empty(self, client, mock_service):
        mock_service.list_experiments.return_value = []
        resp = client.get("/api/experiments")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetExperiment:
    """Tests for GET /api/experiments/{id}."""

    def test_get_existing_experiment(self, client, mock_service):
        mock_service.get_experiment.return_value = SAMPLE_EXPERIMENT
        resp = client.get("/api/experiments/exp-001")
        assert resp.status_code == 200
        assert resp.json()["id"] == "exp-001"

    def test_get_missing_experiment(self, client, mock_service):
        mock_service.get_experiment.return_value = None
        resp = client.get("/api/experiments/nonexistent")
        assert resp.status_code == 404


class TestGetResults:
    """Tests for GET /api/experiments/{id}/results."""

    def test_get_results_success(self, client, mock_service):
        mock_service.get_results.return_value = SAMPLE_RESULTS
        resp = client.get("/api/experiments/exp-001/results")
        assert resp.status_code == 200
        assert resp.json()["sample_size"] == 100

    def test_get_results_not_found(self, client, mock_service):
        mock_service.get_results.return_value = None
        resp = client.get("/api/experiments/nonexistent/results")
        assert resp.status_code == 404


class TestCreateExperiment:
    """Tests for POST /api/experiments."""

    def test_create_success(self, client, mock_service):
        mock_service._service.create_experiment.return_value = "exp-new"
        resp = client.post(
            "/api/experiments",
            json={
                "name": "new_experiment",
                "description": "Test",
                "variants": [
                    {"name": "control", "is_control": True, "traffic": 0.5},
                    {"name": "treatment", "traffic": 0.5},
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "exp-new"
        assert resp.json()["status"] == "created"

    def test_create_missing_name(self, client, mock_service):
        resp = client.post(
            "/api/experiments",
            json={
                "variants": [{"name": "control"}],
            },
        )
        assert resp.status_code == 400

    def test_create_missing_variants(self, client, mock_service):
        resp = client.post(
            "/api/experiments",
            json={
                "name": "test",
                "description": "Test",
            },
        )
        assert resp.status_code == 400


class TestStartExperiment:
    """Tests for POST /api/experiments/{id}/start."""

    def test_start_success(self, client, mock_service):
        mock_service._service.start_experiment.return_value = None
        resp = client.post("/api/experiments/exp-001/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_start_invalid(self, client, mock_service):
        mock_service._service.start_experiment.side_effect = ValueError("Cannot start")
        resp = client.post("/api/experiments/exp-001/start")
        assert resp.status_code == 400


class TestStopExperiment:
    """Tests for POST /api/experiments/{id}/stop."""

    def test_stop_success(self, client, mock_service):
        mock_service._service.stop_experiment.return_value = None
        resp = client.post("/api/experiments/exp-001/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_stop_invalid(self, client, mock_service):
        mock_service._service.stop_experiment.side_effect = ValueError("Not found")
        resp = client.post("/api/experiments/exp-001/stop")
        assert resp.status_code == 400
