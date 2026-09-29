"""The three ways of picking a stopped run up from outside: the preview, Resume, and Give up.

The preview is what the page shows before resuming -- every step with what would happen to it
and why -- and it is the same answer the resume itself works to, so what was shown is what
runs. Give up ends the wait on the clean-ups and lets them run.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.checkpoint.service import CheckpointService
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.runner import holds
from temper_ai.shared.types import Status
from temper_ai.stage.executor import execute_graph
from temper_ai.stage.loader import GraphLoader
from tests.test_stage.test_executor import _make_agent_node, _make_context


@pytest.fixture
def client():
    store = ConfigStore()
    state = AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(state)
    from temper_ai.server import app
    return TestClient(app)


@pytest.fixture
def failed_run(client, monkeypatch):
    """A run that stopped at a failure, with real events, as the page reads them."""
    from temper_ai.observability.event_recorder import EventRecorder

    run_id = "api-stopped-run"
    cp = CheckpointService(run_id)
    setup = _make_agent_node("setup")
    work = _make_agent_node("work", depends_on=["setup"], status=Status.FAILED)
    nodes = [setup, work]
    execute_graph(nodes, {"task": "x"},
                  _make_context(run_id=run_id, checkpoint_service=cp, workflow_name="made_up",
                                event_recorder=EventRecorder(run_id)),
                  graph_name="made_up", is_workflow=True)

    from temper_ai.api import routes
    monkeypatch.setattr(routes._state().graph_loader, "load_workflow",
                        lambda name: (nodes, MagicMock(on_failure=None)))
    return run_id


class TestThePreview:
    def test_it_says_what_happens_to_every_step(self, client, failed_run):
        r = client.get(f"/api/runs/{failed_run}/resume-preview")

        assert r.status_code == 200
        body = r.json()
        steps = {s["path"]: s for g in body["groups"] for s in g["steps"]}
        assert steps["setup"]["action"] == "keep"
        assert steps["work"]["action"] == "rerun"
        assert steps["work"]["reason"]

    def test_it_counts_them(self, client, failed_run):
        body = client.get(f"/api/runs/{failed_run}/resume-preview").json()

        assert body["counts"] == {"keep": 1, "rerun": 1, "redo": 0}

    def test_ticking_a_step_takes_what_used_it_along(self, client, failed_run):
        body = client.get(f"/api/runs/{failed_run}/resume-preview?rerun=setup").json()

        steps = {s["path"]: s for g in body["groups"] for s in g["steps"]}
        assert steps["setup"]["action"] == "rerun"
        assert steps["setup"]["reason"] == "you asked for it to run again"
        assert steps["work"]["action"] == "rerun"

    def test_an_unknown_run_is_a_404(self, client):
        assert client.get("/api/runs/no-such-run/resume-preview").status_code == 404


class TestGiveUp:
    def test_it_ends_the_wait(self, client, failed_run):
        holds.record(failed_run, workflow_name="made_up", workspace_path=None,
                     inputs={}, held=[{"path": "teardown", "undoes": ["setup"]}],
                     deadline=datetime.now(UTC) + timedelta(hours=24))

        r = client.post(f"/api/runs/{failed_run}/cleanup")

        assert r.status_code == 200
        assert r.json()["cleanups"] == ["teardown"]
        assert holds.waiting(failed_run) is None

    def test_a_run_holding_nothing_says_so(self, client, failed_run):
        r = client.post(f"/api/runs/{failed_run}/cleanup")

        assert r.status_code == 409

    def test_an_unknown_run_is_a_404(self, client):
        assert client.post("/api/runs/no-such-run/cleanup").status_code == 404


class TestTheRunPage:
    def test_it_shows_where_the_run_stopped(self, client, failed_run):
        body = client.get(f"/api/workflows/{failed_run}").json()

        assert body["stopped"]["path"] == "work"
        assert body["stopped"]["reason"]

    def test_it_shows_the_wait_with_its_time_left(self, client, failed_run):
        holds.record(failed_run, workflow_name="made_up", workspace_path=None, inputs={},
                     held=[{"path": "teardown", "undoes": ["setup"]}],
                     deadline=datetime.now(UTC) + timedelta(hours=6))

        body = client.get(f"/api/workflows/{failed_run}").json()

        assert body["hold"]["cleanups"][0]["path"] == "teardown"
        assert body["hold"]["seconds_left"] > 21000

    def test_a_run_holding_nothing_shows_no_wait(self, client, failed_run):
        assert "hold" not in client.get(f"/api/workflows/{failed_run}").json()
