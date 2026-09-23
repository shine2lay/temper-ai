"""Saving an agent the engine cannot run is refused at save time.

The Library editor offered "Conversational / Autonomous / Reactive" as agent
types. The engine runs "llm" and "script". Every agent created with one of
the offered types saved fine and then failed its first run with
"Unknown agent type". The server is the enforcement point — the editor is
one client among several — so it refuses what it cannot run, with the same
message the executor would have given, before anything is stored.
"""

import pytest
from fastapi.testclient import TestClient

from temper_ai.agent import AGENT_TYPES, register_agent_type
from temper_ai.agent.script_agent import ScriptAgent
from temper_ai.api import studio


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI

    from temper_ai.config.store import ConfigStore

    store = ConfigStore()
    monkeypatch.setattr(studio, "_store", lambda: store)
    app = FastAPI()
    app.include_router(studio.router)
    return TestClient(app)


def _agent(**fields):
    return {"config": {"agent": {"name": "probe", **fields}}, "schema_version": "1.0"}


def test_refuses_a_type_nothing_can_run(client):
    res = client.put("/api/studio/configs/agent/probe", json=_agent(type="conversational"))
    assert res.status_code == 400
    assert "Unknown agent type: 'conversational'" in res.json()["detail"]
    assert "llm" in res.json()["detail"] and "script" in res.json()["detail"]


def test_accepts_the_types_the_engine_runs(client):
    assert client.put(
        "/api/studio/configs/agent/probe", json=_agent(type="llm", system_prompt="x")
    ).status_code == 200
    assert client.put(
        "/api/studio/configs/agent/probe2", json=_agent(type="script", script_template="echo")
    ).status_code == 200


def test_a_missing_type_means_llm_and_is_fine(client):
    """create_agent defaults to llm; the check must agree with it."""
    assert client.put(
        "/api/studio/configs/agent/probe", json=_agent(system_prompt="x")
    ).status_code == 200


def test_a_script_agent_without_a_script_is_refused(client):
    res = client.put("/api/studio/configs/agent/probe", json=_agent(type="script"))
    assert res.status_code == 400
    assert "script_template" in res.json()["detail"]


def test_a_jev_agent_without_questions_is_refused(client):
    res = client.put(
        "/api/studio/configs/agent/probe", json=_agent(type="jev", state_template="{{ finding }}")
    )
    assert res.status_code == 400
    assert "must have 'questions'" in res.json()["detail"]


def test_a_jev_agent_with_its_questions_is_accepted(client):
    res = client.put("/api/studio/configs/agent/probe", json=_agent(
        type="jev", model="jev-1.13.0", state_template="{{ finding }}",
        questions={"severity": {"type": "choice", "criteria": {"blocking": "x", "minor": "y"}}},
    ))
    assert res.status_code == 200


def test_a_plugin_registered_type_is_accepted(client):
    """The check reads the live registry, not a fixed list."""
    register_agent_type("plugin_probe", ScriptAgent)
    try:
        res = client.put(
            "/api/studio/configs/agent/probe",
            json=_agent(type="plugin_probe", script_template="echo"),
        )
        assert res.status_code == 200
    finally:
        AGENT_TYPES.pop("plugin_probe", None)


def test_validate_reads_the_agent_not_the_wrapper(client):
    """It used to report 'must have name' for every wrapped agent."""
    res = client.post(
        "/api/studio/validate/agent",
        json={"config": {"agent": {"name": "probe", "type": "llm", "system_prompt": "x"}}},
    )
    body = res.json()
    assert body["valid"] is True
    assert body["errors"] == []


def test_validate_reports_the_bad_type(client):
    res = client.post(
        "/api/studio/validate/agent",
        json={"config": {"agent": {"name": "probe", "type": "reactive"}}},
    )
    body = res.json()
    assert body["valid"] is False
    assert any("Unknown agent type: 'reactive'" in e for e in body["errors"])
