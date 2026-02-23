"""Tests for goal dashboard routes."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from temper_ai.goals.dashboard_routes import create_goals_router
from temper_ai.goals.dashboard_service import GoalDataService


@pytest.fixture
def service():
    svc = MagicMock(spec=GoalDataService)
    svc.get_proposals.return_value = [
        {"id": "gp-1", "title": "Test", "status": "proposed"}
    ]
    svc.get_proposal_detail.return_value = {
        "id": "gp-1",
        "title": "Test",
        "description": "Test desc",
        "status": "proposed",
    }
    svc.get_stats.return_value = {
        "counts_by_status": {"proposed": 1},
        "total": 1,
        "acceptance_rate": 0.5,
    }
    svc.get_analysis_runs.return_value = []
    svc.store = MagicMock()
    return svc


@pytest.fixture
def client(service):
    app = FastAPI()
    app.include_router(create_goals_router(service))
    return TestClient(app)


class TestProposalEndpoints:
    def test_list_proposals(self, client):
        resp = client.get("/goals/proposals")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "gp-1"

    def test_get_proposal(self, client):
        resp = client.get("/goals/proposals/gp-1")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test"

    def test_get_proposal_not_found(self):
        svc = MagicMock(spec=GoalDataService)
        svc.get_proposal_detail.return_value = None
        app = FastAPI()
        app.include_router(create_goals_router(svc))
        c = TestClient(app)
        resp = c.get("/goals/proposals/missing")
        assert resp.status_code == 404


class TestStatsEndpoint:
    def test_get_stats(self, client):
        resp = client.get("/goals/stats")
        assert resp.status_code == 200
        assert "acceptance_rate" in resp.json()


class TestAnalysisEndpoints:
    def test_get_analysis_runs(self, client):
        resp = client.get("/goals/analysis-runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_trigger_analysis(self, client):
        with patch(
            "temper_ai.goals.analysis_orchestrator.AnalysisOrchestrator"
        ) as MockOrch:
            run = MagicMock()
            run.id = "ar-1"
            run.status = "completed"
            run.proposals_generated = 2
            MockOrch.return_value.run_analysis.return_value = run
            resp = client.post("/goals/analyze")
        assert resp.status_code == 200
        assert resp.json()["proposals_generated"] == 2
