"""Tests for learning dashboard routes."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.learning.dashboard_routes import create_learning_router
from temper_ai.learning.dashboard_service import LearningDataService

HTTP_OK = 200
HTTP_NOT_FOUND = 404


@pytest.fixture()
def client() -> TestClient:
    mock_service = MagicMock(spec=LearningDataService)
    mock_service.get_pattern_summary.return_value = {
        "counts_by_type": {"cost": 2},
        "total": 2,
        "top_patterns": [],
    }
    mock_service.get_mining_history.return_value = []
    mock_service.get_convergence_data.return_value = {
        "scores": [],
        "moving_average": 0.0,
        "data_points": 0,
        "converged": False,
    }
    mock_service.get_recommendations.return_value = []
    mock_service.store = MagicMock()
    mock_service.store.update_recommendation_status.return_value = True

    app = FastAPI()
    app.include_router(create_learning_router(mock_service), prefix="/api")
    return TestClient(app)


class TestLearningRoutes:
    def test_get_patterns(self, client: TestClient) -> None:
        resp = client.get("/api/learning/patterns")
        assert resp.status_code == HTTP_OK
        assert resp.json()["total"] == 2

    def test_get_mining_runs(self, client: TestClient) -> None:
        resp = client.get("/api/learning/mining-runs")
        assert resp.status_code == HTTP_OK
        assert resp.json() == []

    def test_get_convergence(self, client: TestClient) -> None:
        resp = client.get("/api/learning/convergence")
        assert resp.status_code == HTTP_OK
        assert resp.json()["converged"] is False

    def test_get_recommendations(self, client: TestClient) -> None:
        resp = client.get("/api/learning/recommendations")
        assert resp.status_code == HTTP_OK

    def test_apply_recommendation(self, client: TestClient) -> None:
        resp = client.post("/api/learning/recommendations/rec-1/apply")
        assert resp.status_code == HTTP_OK
        assert resp.json()["status"] == "applied"

    def test_dismiss_recommendation(self, client: TestClient) -> None:
        resp = client.post("/api/learning/recommendations/rec-1/dismiss")
        assert resp.status_code == HTTP_OK
        assert resp.json()["status"] == "dismissed"

    def test_apply_not_found(self) -> None:
        mock_service = MagicMock(spec=LearningDataService)
        mock_service.store = MagicMock()
        mock_service.store.update_recommendation_status.return_value = False

        app = FastAPI()
        app.include_router(create_learning_router(mock_service), prefix="/api")
        c = TestClient(app)
        resp = c.post("/api/learning/recommendations/bad-id/apply")
        assert resp.status_code == HTTP_NOT_FOUND
