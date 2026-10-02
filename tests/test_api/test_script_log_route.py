"""GET /api/runs/<run>/agents/<attempt>/log: a script agent's saved log, a page at a time."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability import record
from temper_ai.observability.event_types import EventType
from temper_ai.observability.script_logs import save_script_log_rows
from temper_ai.stage.loader import GraphLoader


@pytest.fixture
def client():
    store = ConfigStore()
    init_app_state(AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    ))
    from temper_ai.server import app
    return TestClient(app)


def _row(attempt: str, seq: int, text: str) -> dict:
    return {"attempt_id": attempt, "seq": seq, "bytes": len(text.encode()),
            "entries": [{"stream": "stdout", "t": "2026-10-02T12:00:00.000+00:00", "text": text}]}


@pytest.fixture
def attempt() -> str:
    attempt = record(EventType.AGENT_STARTED, execution_id="run-1", status="running",
                     data={"agent_name": "talker"})
    save_script_log_rows("run-1", attempt, [(i, _row(attempt, i, f"line {i}\n")) for i in range(1, 6)])
    return attempt


def test_the_newest_page_then_older_then_newer(client, attempt):
    url = f"/api/runs/run-1/agents/{attempt}/log"
    newest = client.get(url, params={"max_bytes": 14}).json()
    assert [r["seq"] for r in newest["rows"]] == [4, 5]
    assert newest["has_more_before"] is True and newest["newest_seq"] == 5
    older = client.get(url, params={"before_seq": 4, "max_bytes": 14}).json()
    assert [r["seq"] for r in older["rows"]] == [2, 3]
    newer = client.get(url, params={"after_seq": 3}).json()
    assert [r["seq"] for r in newer["rows"]] == [4, 5] and newer["has_more_after"] is False


def test_both_cursors_at_once_is_a_bad_request(client, attempt):
    r = client.get(f"/api/runs/run-1/agents/{attempt}/log", params={"after_seq": 1, "before_seq": 3})
    assert r.status_code == 400


def test_an_attempt_of_another_run_or_none_at_all_is_not_found(client, attempt):
    assert client.get(f"/api/runs/run-2/agents/{attempt}/log").status_code == 404
    assert client.get("/api/runs/run-1/agents/nobody/log").status_code == 404


def test_the_log_is_behind_the_token_like_the_rest_of_a_run(client, attempt, monkeypatch):
    monkeypatch.setenv("TEMPER_API_TOKEN", "secret-for-this-test")
    assert client.get(f"/api/runs/run-1/agents/{attempt}/log").status_code == 401
    r = client.get(f"/api/runs/run-1/agents/{attempt}/log",
                   headers={"Authorization": "Bearer secret-for-this-test"})
    assert r.status_code == 200
