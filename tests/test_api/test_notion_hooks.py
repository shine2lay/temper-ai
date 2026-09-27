"""POST /api/hooks/notion: signed events only, the verification token is kept,
a retried event starts nothing twice, and the history stays behind the token."""

import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from temper_ai.api import hooks
from temper_ai.api.auth import TokenAuthMiddleware
from temper_ai.integrations.notion import store
from temper_ai.triggers import notion

SECRET = "notion-verify-test"  # noqa: S105


def _event(event_id="ev-1"):
    return {"id": event_id, "type": "page.properties_updated",
            "entity": {"id": "11111111-1111-1111-1111-111111111111", "type": "page"},
            "authors": [{"id": "p1", "type": "person"}], "data": {"updated_properties": ["s"]}}


def _post(client, event, *, secret=SECRET, raw=None):
    body = raw if raw is not None else json.dumps(event).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(hooks.NOTION_PATH, content=body,
                       headers={"X-Notion-Signature": sig, "Content-Type": "application/json"})


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(notion.SECRET_ENV, SECRET)
    monkeypatch.delenv("TEMPER_API_TOKEN", raising=False)


@pytest.fixture
def dispatched(monkeypatch):
    seen = []
    monkeypatch.setattr(hooks, "notion_dispatch", lambda event: seen.append(event))
    return seen


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hooks.router)
    app.add_middleware(TokenAuthMiddleware)
    return TestClient(app)


def test_signed_event_is_handed_on(client, dispatched):
    r = _post(client, _event())
    assert r.status_code == 200, r.text
    assert [e["id"] for e in dispatched] == ["ev-1"]


def test_wrong_or_missing_signature(client, dispatched):
    assert _post(client, _event(), secret="guess").status_code == 401
    body = json.dumps(_event()).encode()
    assert client.post(hooks.NOTION_PATH, content=body).status_code == 401
    assert dispatched == []


def test_off_until_a_secret_is_set(client, dispatched, monkeypatch):
    monkeypatch.delenv(notion.SECRET_ENV)
    assert _post(client, _event()).status_code == 503
    assert dispatched == []


def test_verification_token_is_kept_unsigned(client, dispatched, monkeypatch):
    monkeypatch.delenv(notion.SECRET_ENV)
    r = client.post(hooks.NOTION_PATH, json={"verification_token": "secret_abc"})
    assert r.status_code == 200
    assert store.get_state(hooks.NOTION_TOKEN_KEY) == "secret_abc"
    assert dispatched == []


def test_a_retry_starts_nothing_twice(client, dispatched):
    assert _post(client, _event("same")).status_code == 200
    again = _post(client, _event("same"))
    assert again.json().get("duplicate") is True
    assert len(dispatched) == 1


def test_not_json(client, dispatched):
    assert _post(client, None, raw=b"nope").status_code == 400


def test_history_needs_the_token(client, dispatched, monkeypatch):
    monkeypatch.setenv("TEMPER_API_TOKEN", "api-token")
    assert _post(client, _event("ev-h")).status_code == 200
    assert client.get(hooks.NOTION_PATH + "/recent").status_code == 401
    ok = client.get(hooks.NOTION_PATH + "/recent", headers={"Authorization": "Bearer api-token"})
    assert ok.status_code == 200
    assert any(e["id"] == "ev-h" for e in ok.json()["events"])
