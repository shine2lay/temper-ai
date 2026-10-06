"""Studio never writes or deletes a team trial's configs (M3 E7).

The Team page writes ``team-trial-<id>`` workflows and agents when it starts a trial, and they
stay as they were so the trial's run can be resumed or forked as it ran. Every other name is
written as before.
"""

import pytest
from fastapi.testclient import TestClient

from temper_ai.api import studio

TRIAL = "team-trial-0123456789ab"
REFUSED = (f"'{TRIAL}' is a team trial's config: only the Team page writes it, and it stays "
           "as it was so the trial's run can be resumed or forked")


@pytest.fixture
def client_and_store(monkeypatch):
    from fastapi import FastAPI

    from temper_ai.config.store import ConfigStore

    store = ConfigStore()
    monkeypatch.setattr(studio, "_store", lambda: store)
    app = FastAPI()
    app.include_router(studio.router)
    return TestClient(app), store


def _workflow(name: str) -> dict:
    return {"config": {"workflow": {"name": name, "nodes": []}}, "schema_version": "1.0"}


@pytest.mark.parametrize("method", ["post", "put"])
def test_a_write_to_a_trial_name_is_refused_and_nothing_changes(client_and_store, method):
    client, store = client_and_store
    store.put(TRIAL, "workflow", {"workflow": {"name": TRIAL, "nodes": ["frozen"]}})
    res = getattr(client, method)(f"/api/studio/configs/workflow/{TRIAL}", json=_workflow(TRIAL))
    assert (res.status_code, res.json()["detail"]) == (409, REFUSED)
    assert store.get(TRIAL, "workflow")["workflow"]["nodes"] == ["frozen"]


def test_a_trial_name_inside_the_config_is_refused_too(client_and_store):
    client, store = client_and_store
    res = client.put("/api/studio/configs/workflow/plain_name", json=_workflow(TRIAL))
    assert (res.status_code, res.json()["detail"]) == (409, REFUSED)


def test_a_trial_config_is_never_deleted(client_and_store):
    client, store = client_and_store
    store.put(TRIAL, "workflow", {"workflow": {"name": TRIAL, "nodes": []}})
    res = client.delete(f"/api/studio/configs/workflow/{TRIAL}")
    assert (res.status_code, res.json()["detail"]) == (409, REFUSED)
    assert store.get(TRIAL, "workflow")


def test_other_names_are_written_and_deleted_as_before(client_and_store):
    client, store = client_and_store
    assert client.put("/api/studio/configs/workflow/team_trial_like",
                      json=_workflow("team_trial_like")).status_code == 200
    assert client.delete("/api/studio/configs/workflow/team_trial_like").status_code in (200, 204)
