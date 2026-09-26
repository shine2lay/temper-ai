"""GET /api/workflows/search: find a workflow by what it does, from the DB."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.stage.loader import GraphLoader


def _workflow(name: str, description: str = "", inputs: dict | None = None) -> dict:
    body: dict = {"name": name, "nodes": [{"name": "a", "type": "agent", "agent": "x"}]}
    if description:
        body["description"] = description
    if inputs:
        body["inputs"] = inputs
    return {"workflow": body}


@pytest.fixture
def client():
    store = ConfigStore()
    store.put("linear_reply", "workflow", _workflow("linear_reply", "Answer a Linear issue with a comment."))
    store.put("plan_grade", "workflow", _workflow(
        "plan_grade", "Grade a written plan against the rubric.",
        {"issue": {"type": "string", "required": True, "description": "the Linear issue to read"}}))
    store.put("bare", "workflow", _workflow("bare"))
    init_app_state(AppState(config_store=store, graph_loader=GraphLoader(store),
                            llm_providers={"mock": MagicMock()}, memory_service=MemoryService(InMemoryStore())))
    from temper_ai.server import app

    return TestClient(app)


def test_ranks_name_hits_first_and_shows_inputs(client):
    body = client.get("/api/workflows/search", params={"q": "linear"}).json()
    assert [r["name"] for r in body["results"]] == ["linear_reply", "plan_grade"]
    grade = body["results"][1]
    assert grade["inputs"]["issue"]["required"] is True and grade["matched"]


def test_empty_query_lists_everything_and_flags_missing_descriptions(client):
    body = client.get("/api/workflows/search", params={"limit": 500}).json()
    assert body["total"] == 3 and body["undescribed"] == ["bare"]


def test_search_is_not_taken_for_a_run_id(client):
    assert client.get("/api/workflows/search", params={"q": "grade"}).status_code == 200
