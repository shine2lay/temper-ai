"""GET /api/pools: what each credential pool can serve now, so a start can be refused before it runs.

Nothing asked the pool before a start (gap 17): b009 started on 2026-09-24 with every opus slot
rate limited, and its plan step died on "token pool exhausted". The driver now asks this first.
"""

import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from temper_ai.api.app_state import AppState
from temper_ai.api.routes import init_app_state
from temper_ai.config import ConfigStore
from temper_ai.llm import pi_logins
from temper_ai.llm.token_pool import KNOWN_FAMILIES, TokenPool
from temper_ai.memory import InMemoryStore, MemoryService
from temper_ai.stage.loader import GraphLoader

SECRETS = ["sk-ant-oat01-first-secret", "sk-ant-oat01-second-secret"]
SLOTS = ["anthropic", "anthropic-2"]


def a_pool() -> TokenPool:
    return TokenPool(name="anthropic-oauth", tokens=list(SLOTS), labels=list(SLOTS))


def test_a_pool_says_per_family_which_slots_are_cooling_and_until_when():
    pool = a_pool()
    soon, later = time.time() + 3600, time.time() + 7200
    pool.cool(SLOTS[0], until=soon, model="claude-opus-5-5")
    pool.cool(SLOTS[1], until=later, model="claude-opus-5-5")

    state = pool.state()
    assert set(KNOWN_FAMILIES) <= set(state)
    opus = state["opus"]
    assert (opus["size"], opus["available"]) == (2, 0)
    assert [s["label"] for s in opus["slots"]] == SLOTS
    first = datetime.fromisoformat(opus["slots"][0]["cooling_until"]).timestamp()
    assert soon <= first <= soon + 120  # the pool pads a reset time a little
    assert opus["soonest_reset"] == opus["slots"][0]["cooling_until"]
    sonnet = state["sonnet"]
    assert (sonnet["available"], sonnet["soonest_reset"]) == (2, None)
    assert all(s["cooling_until"] is None for s in sonnet["slots"])


def test_a_cooling_that_named_no_model_covers_every_family():
    pool = a_pool()
    pool.cool(SLOTS[0], until=time.time() + 600)
    state = pool.state()
    assert all(state[f]["available"] == 1 for f in KNOWN_FAMILIES)


def test_the_state_never_holds_a_token():
    pool = TokenPool(name="anthropic-oauth", tokens=list(SECRETS), labels=list(SLOTS))
    pool.cool(SECRETS[0], until=time.time() + 600, model="opus")
    assert not any(secret in repr(pool.state()) for secret in SECRETS)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(pi_logins, "configured_slots", lambda: list(SLOTS))
    store = ConfigStore()
    pooled = SimpleNamespace(_pool=a_pool())
    pooled._pool.cool(SLOTS[1], until=time.time() + 600, model="claude-opus-5-5")
    init_app_state(AppState(
        config_store=store,
        graph_loader=GraphLoader(store),
        # One provider with a pool, one without: a single credential is not a pool.
        llm_providers={"anthropic": pooled, "openai": MagicMock()},
        memory_service=MemoryService(InMemoryStore()),
    ))
    from temper_ai.server import app
    return TestClient(app)


def test_the_endpoint_lists_each_pooled_provider(client):
    got = client.get("/api/pools")
    assert got.status_code == 200
    pools = got.json()["pools"]
    assert [(p["provider"], p["name"], p["size"]) for p in pools] == [("anthropic", "anthropic-oauth", 2)]
    opus = pools[0]["families"]["opus"]
    assert opus["available"] == 1
    assert [s["label"] for s in opus["slots"] if s["cooling_until"]] == ["anthropic-2"]
    assert not any(secret in got.text for secret in SECRETS)


def test_the_endpoint_shows_each_accounts_week_and_never_a_token(client, monkeypatch):
    """Queue #66 + #299: each pi slot's week figure, when it was seen, and whether it is over
    the line. A slot with no figure is listed too, as unknown (under the line); env tokens
    are ignored."""
    from temper_ai.llm import week_usage

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRETS[0])
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN_ACCOUNT", "roamee")
    resets = time.time() + 2 * 24 * 3600
    week_usage.store().note("anthropic-2", "seven_day", 0.95, resets_at=resets)

    got = client.get("/api/pools")
    assert got.status_code == 200
    body = got.json()
    assert body["week_line"] == 0.9
    rows = {row["label"]: row for row in body["accounts"]}
    assert list(rows) == ["anthropic", "anthropic-2"]
    assert rows["anthropic"] == {"label": "anthropic", "week_used": None, "week_kind": None,
                                 "seen_at": None, "resets_at": None, "over_line": False}
    spent = rows["anthropic-2"]
    assert (spent["week_used"], spent["week_kind"], spent["over_line"]) == (0.95, "seven_day", True)
    assert abs(datetime.fromisoformat(spent["resets_at"]).timestamp() - resets) < 1
    assert abs(datetime.fromisoformat(spent["seen_at"]).timestamp() - time.time()) < 60
    assert not any(secret in got.text for secret in SECRETS)
    assert "roamee" not in got.text


def test_a_malformed_slots_list_fails_loud_with_500(client, monkeypatch):
    def broken():
        raise pi_logins.PiLoginsMisconfigured("pools.logins.slots in pools.yaml must be a list")

    monkeypatch.setattr(pi_logins, "configured_slots", broken)
    got = client.get("/api/pools")
    assert got.status_code == 500
    assert "pools.logins.slots" in got.json()["detail"]
