"""Tests for the gate endpoints: what a waiting gate shows, what approval sends.

``GET /api/runs/{id}/gates`` is what the dashboard's gate modal renders, so
it has to carry the upstream output and the questions it asked, not just a
node name. ``POST /approve`` takes the human's answers back.
"""

import threading
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.observability.event_types import EventType
from temper_ai.observability.recorder import get_event, record
from temper_ai.stage.gate import GateSignal
from temper_ai.stage.loader import GraphLoader

RUN = "run-gate-1"


@pytest.fixture
def state():
    store = ConfigStore()
    st = AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        llm_providers={"mock": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    )
    init_app_state(st)
    return st


@pytest.fixture
def client(state):
    from temper_ai.server import app
    return TestClient(app)


def _record_waiting(node_name="approve", gate_context=None, execution_id=RUN):
    """The event the executor writes when a gate opens."""
    return record(
        EventType.STAGE_STARTED,
        data={
            "name": node_name,
            "type": "agent",
            "depends_on": ["draft"],
            "gate": True,
            "gate_status": "waiting",
            **({"gate_context": gate_context} if gate_context is not None else {}),
        },
        execution_id=execution_id,
        status="waiting",
    )


class TestListGates:
    def test_a_waiting_gate_carries_its_upstream_output_and_questions(self, client):
        _record_waiting(gate_context={
            "upstream": [{"node": "draft", "output": "the pitch", "structured_output": None}],
            "questions": [{"id": "q1", "question": "Ship it?", "node": "draft"}],
        })

        gates = client.get(f"/api/runs/{RUN}/gates").json()["gates"]

        assert len(gates) == 1
        assert gates[0]["node_name"] == "approve"
        assert gates[0]["status"] == "waiting"
        assert gates[0]["event_id"]
        assert gates[0]["upstream"] == [{"node": "draft", "output": "the pitch", "structured_output": None}]
        assert gates[0]["questions"] == [{"id": "q1", "question": "Ship it?", "node": "draft"}]

    def test_a_gate_recorded_before_gate_context_existed_still_lists(self, client):
        """Old runs in the database have no gate_context; they must not 500."""
        _record_waiting()

        gates = client.get(f"/api/runs/{RUN}/gates").json()["gates"]

        assert gates == [{
            "node_name": "approve",
            "status": "waiting",
            "event_id": gates[0]["event_id"],
            "upstream": [],
            "questions": [],
        }]

    def test_an_in_memory_only_gate_is_listed(self, client, state):
        state.gates[f"{RUN}:approve"] = GateSignal()

        gates = client.get(f"/api/runs/{RUN}/gates").json()["gates"]

        assert [g["node_name"] for g in gates] == ["approve"]
        assert gates[0]["event_id"] is None

    def test_a_gate_is_listed_once_when_both_sources_have_it(self, client, state):
        _record_waiting(gate_context={"upstream": [{"node": "draft", "output": "pitch"}], "questions": []})
        state.gates[f"{RUN}:approve"] = GateSignal()

        gates = client.get(f"/api/runs/{RUN}/gates").json()["gates"]

        assert len(gates) == 1
        assert gates[0]["upstream"], "the persisted event wins — it is the one with the context"

    def test_a_released_gate_is_not_listed(self, client, state):
        signal = GateSignal()
        signal.set()
        state.gates[f"{RUN}:approve"] = signal

        assert client.get(f"/api/runs/{RUN}/gates").json()["gates"] == []

    def test_gates_of_another_run_are_not_listed(self, client):
        _record_waiting(execution_id="some-other-run")

        assert client.get(f"/api/runs/{RUN}/gates").json()["gates"] == []


class TestApproveGate:
    def test_an_empty_approval_is_a_plain_approval(self, client, state):
        signal = GateSignal()
        state.gates[f"{RUN}:approve"] = signal
        event_id = _record_waiting()

        r = client.post(f"/api/runs/{RUN}/approve/approve")

        assert r.status_code == 200
        assert r.json()["response"] is None
        assert signal.is_set()
        assert signal.response is None
        data = get_event(event_id)
        assert data["status"] == "approved"
        assert "gate_response" not in data["data"]

    def test_answers_reach_the_signal_and_the_event(self, client, state):
        signal = GateSignal()
        state.gates[f"{RUN}:approve"] = signal
        event_id = _record_waiting()

        r = client.post(f"/api/runs/{RUN}/approve/approve", json={
            "response": "Go, but keep it small.",
            "answers": [{"id": "host", "question": "Which host?", "selected": ["spark"], "custom": ""}],
        })

        expected_text = "Q: Which host?\nA: spark\n\nGo, but keep it small."
        assert r.json()["response"]["text"] == expected_text
        assert signal.response["text"] == expected_text, "in-process runs get it without a DB round-trip"
        assert get_event(event_id)["data"]["gate_response"]["text"] == expected_text, "worker runs poll for it"

    def test_approving_with_no_gate_waiting_is_404(self, client):
        r = client.post(f"/api/runs/{RUN}/approve/nobody")

        assert r.status_code == 404
        assert "No gate waiting" in r.json()["detail"]

    def test_a_worker_run_is_approved_through_the_database_alone(self, client):
        """No in-memory signal exists in the API process for a worker run."""
        event_id = _record_waiting()

        r = client.post(f"/api/runs/{RUN}/approve/approve", json={"response": "ship it"})

        assert r.status_code == 200
        assert get_event(event_id)["data"]["gate_response"]["text"] == "ship it"

    def test_an_approved_gate_stops_being_listed(self, client, state):
        state.gates[f"{RUN}:approve"] = GateSignal()
        _record_waiting()

        client.post(f"/api/runs/{RUN}/approve/approve")

        assert client.get(f"/api/runs/{RUN}/gates").json()["gates"] == []

    def test_an_approval_is_stamped_with_when_it_was_decided(self, client, state):
        """How long the owner took is part of the record; the stamp is what makes it computable."""
        state.gates[f"{RUN}:approve"] = GateSignal()
        event_id = _record_waiting()

        client.post(f"/api/runs/{RUN}/approve/approve")

        assert get_event(event_id)["data"]["gate_decided_at"]


class TestDecisionsRecord:
    """``GET /api/runs/{id}/decisions``: every gate the run opened and how it was answered.

    ``/gates`` is what is waiting now; this is the record afterwards, for a caller keeping
    the owner's verdicts over time -- which is why it leaves the upstream outputs out.
    """

    def test_an_approved_gate_is_listed_with_its_response_and_stamps(self, client, state):
        state.gates[f"{RUN}:approve"] = GateSignal()
        _record_waiting(gate_context={"questions": [{"id": "host", "question": "Which host?"}]})

        client.post(f"/api/runs/{RUN}/approve/approve", json={
            "response": "Go.",
            "answers": [{"id": "host", "question": "Which host?", "selected": ["spark"], "custom": ""}],
        })
        d = client.get(f"/api/runs/{RUN}/decisions").json()

        assert d["execution_id"] == RUN
        (row,) = d["decisions"]
        assert row["node_name"] == "approve"
        assert row["status"] == "approved"
        assert row["opened_at"] and row["decided_at"]
        assert row["questions"] == [{"id": "host", "question": "Which host?"}]
        assert row["response"]["response"] == "Go."
        assert row["response"]["answers"][0]["selected"] == ["spark"]
        assert "upstream" not in row and "upstream_output" not in row

    def test_a_waiting_gate_is_listed_as_waiting_with_no_decision(self, client):
        _record_waiting()

        (row,) = client.get(f"/api/runs/{RUN}/decisions").json()["decisions"]

        assert row["status"] == "waiting"
        assert row["decided_at"] is None and row["response"] is None

    def test_cancelling_at_a_gate_records_a_rejection_with_the_reason(self, client, state):
        """Cancel is how the dashboard says no. The gate's own record says so, with why."""
        state.gates[f"{RUN}:approve"] = GateSignal()
        state.running[RUN] = cancel = threading.Event()  # an in-process run, parked at the gate
        event_id = _record_waiting()

        r = client.post(f"/api/runs/{RUN}/cancel", json={"reason": "Not this quarter."})

        assert r.status_code == 200 and cancel.is_set()
        data = get_event(event_id)
        assert data["status"] == "rejected"
        assert data["data"]["gate_status"] == "rejected"
        assert data["data"]["gate_decided_at"]
        assert data["data"]["gate_response"]["response"] == "Not this quarter."
        (row,) = client.get(f"/api/runs/{RUN}/decisions").json()["decisions"]
        assert row["status"] == "rejected" and row["response"]["text"] == "Not this quarter."

    def test_a_cancel_with_no_body_still_rejects_the_waiting_gate(self, client, state):
        state.gates[f"{RUN}:approve"] = GateSignal()
        state.running[RUN] = threading.Event()
        event_id = _record_waiting()

        client.post(f"/api/runs/{RUN}/cancel")

        data = get_event(event_id)
        assert data["data"]["gate_status"] == "rejected"
        assert "gate_response" not in data["data"]

    def test_only_gates_are_listed_and_each_opening_once(self, client):
        record(EventType.STAGE_STARTED, data={"name": "draft", "type": "agent"}, execution_id=RUN)
        _record_waiting("approve")
        _record_waiting("approve")  # a loop that gated the same node twice lists it twice

        rows = client.get(f"/api/runs/{RUN}/decisions").json()["decisions"]

        assert [r["node_name"] for r in rows] == ["approve", "approve"]
