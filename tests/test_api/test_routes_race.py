"""A run must be queryable the moment its id is handed out.

POST /api/runs registers the execution before the first event is written,
so for a fraction of a second GET /api/workflows/{id} answered 404 for an
id the API had just issued — anything that started a run and polled
immediately (an agent over MCP, a script) saw "not found".
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from temper_ai.api import routes


def test_a_registered_run_is_reported_as_running_before_its_first_event():
    state = MagicMock()
    state.running = {"run-1": object()}
    with patch.object(routes, "_state", return_value=state), \
         patch.object(routes, "get_workflow_execution", return_value=None):
        result = routes.get_workflow("run-1")
    assert result["id"] == "run-1"
    assert result["status"] == "running"
    assert result["nodes"] == []


def test_an_unknown_run_is_still_a_404():
    state = MagicMock()
    state.running = {}
    with patch.object(routes, "_state", return_value=state), \
         patch.object(routes, "get_workflow_execution", return_value=None), \
         pytest.raises(HTTPException) as exc:
        routes.get_workflow("nope")
    assert exc.value.status_code == 404


def test_a_real_run_is_returned_unchanged():
    state = MagicMock()
    state.running = {}
    payload = {"id": "run-2", "status": "completed", "nodes": [{"name": "a"}]}
    with patch.object(routes, "_state", return_value=state), \
         patch.object(routes, "get_workflow_execution", return_value=payload):
        assert routes.get_workflow("run-2") is payload
