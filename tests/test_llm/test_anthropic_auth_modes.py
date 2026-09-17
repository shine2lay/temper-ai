"""The Anthropic provider tells an API key from an OAuth token and sends each
the right way.

An API key travels as x-api-key. An OAuth access token (sk-ant-oat…)
travels as a bearer token, and what else an OAuth request should carry is
delegated to a shaper registered at startup — nothing about that policy
lives in the provider itself.
"""

import sys
import types
from typing import Any

import pytest

from temper_ai.llm.providers import anthropic as mod
from temper_ai.llm.providers.anthropic import (
    AnthropicLLM,
    register_oauth_shaper,
    resolve_credential,
)

# ---------------------------------------------------------------------------
# Credential resolution — pure, no SDK
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(mod.API_KEY_ENV, raising=False)
    monkeypatch.delenv(mod.OAUTH_TOKEN_ENV, raising=False)
    register_oauth_shaper(None)
    yield
    register_oauth_shaper(None)


def test_nothing_configured_means_no_provider():
    assert resolve_credential() == (None, "none")


def test_an_api_key_is_an_api_key(monkeypatch):
    monkeypatch.setenv(mod.API_KEY_ENV, "sk-ant-api03-abc")
    assert resolve_credential() == ("sk-ant-api03-abc", "api_key")


def test_an_oauth_token_is_recognised_by_prefix(monkeypatch):
    monkeypatch.setenv(mod.OAUTH_TOKEN_ENV, "sk-ant-oat01-xyz")
    assert resolve_credential() == ("sk-ant-oat01-xyz", "oauth")


def test_an_oauth_token_in_the_api_key_slot_is_still_oauth(monkeypatch):
    """The kind is decided by the credential, not by which variable held it."""
    monkeypatch.setenv(mod.API_KEY_ENV, "sk-ant-oat01-xyz")
    assert resolve_credential()[1] == "oauth"


def test_the_api_key_wins_when_both_are_set(monkeypatch):
    monkeypatch.setenv(mod.API_KEY_ENV, "sk-ant-api03-abc")
    monkeypatch.setenv(mod.OAUTH_TOKEN_ENV, "sk-ant-oat01-xyz")
    assert resolve_credential() == ("sk-ant-api03-abc", "api_key")


def test_an_explicit_argument_wins_over_everything(monkeypatch):
    monkeypatch.setenv(mod.API_KEY_ENV, "sk-ant-api03-env")
    assert resolve_credential("sk-ant-oat01-arg") == ("sk-ant-oat01-arg", "oauth")


def test_whitespace_is_not_a_credential(monkeypatch):
    monkeypatch.setenv(mod.API_KEY_ENV, "   ")
    assert resolve_credential() == (None, "none")


# ---------------------------------------------------------------------------
# Client construction and request shaping — SDK replaced by a recorder
# ---------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="ok")],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn",
        )


class _FakeAnthropic:
    instances: list["_FakeAnthropic"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.messages = _FakeMessages()
        _FakeAnthropic.instances.append(self)


@pytest.fixture
def fake_sdk(monkeypatch):
    _FakeAnthropic.instances.clear()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=_FakeAnthropic))
    return _FakeAnthropic


def _last_client() -> "_FakeAnthropic":
    return _FakeAnthropic.instances[-1]


def test_api_key_goes_out_as_an_api_key(fake_sdk):
    AnthropicLLM(api_key="sk-ant-api03-abc")
    c = _last_client().kwargs
    assert c["api_key"] == "sk-ant-api03-abc"
    assert "auth_token" not in c


def test_oauth_token_goes_out_as_a_bearer_token(fake_sdk):
    AnthropicLLM(api_key="sk-ant-oat01-xyz")
    c = _last_client().kwargs
    assert c["auth_token"] == "sk-ant-oat01-xyz"
    assert c["api_key"] is None


class _Shaper:
    def __init__(self):
        self.shaped: list[dict[str, Any]] = []

    def client_headers(self):
        return {"x-test-identity": "shaper"}

    def shape(self, create_kwargs):
        self.shaped.append(create_kwargs)
        return {**create_kwargs, "system": [{"type": "text", "text": "shaped"}]}


def test_a_registered_shaper_dresses_oauth_requests(fake_sdk):
    shaper = _Shaper()
    register_oauth_shaper(shaper)
    llm = AnthropicLLM(api_key="sk-ant-oat01-xyz")

    llm.complete([{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}])
    sent = _last_client().messages.calls[0]
    assert sent["system"] == [{"type": "text", "text": "shaped"}]
    assert sent["extra_headers"] == {"x-test-identity": "shaper"}
    assert shaper.shaped[0]["system"] == "be brief"  # it saw the original


def test_the_shaper_may_be_registered_after_the_provider_was_built(fake_sdk):
    """server.py builds the provider before local/ registers the shaper."""
    llm = AnthropicLLM(api_key="sk-ant-oat01-xyz")
    register_oauth_shaper(_Shaper())
    llm.complete([{"role": "user", "content": "hi"}])
    assert _last_client().messages.calls[0]["extra_headers"] == {"x-test-identity": "shaper"}


def test_the_shaper_never_touches_api_key_requests(fake_sdk):
    shaper = _Shaper()
    register_oauth_shaper(shaper)
    llm = AnthropicLLM(api_key="sk-ant-api03-abc")

    llm.complete([{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}])
    assert shaper.shaped == []
    sent = _last_client().messages.calls[0]
    assert sent["system"] == "be brief"
    assert "extra_headers" not in sent


def test_oauth_without_a_shaper_still_works_and_warns_once(fake_sdk, caplog):
    import logging

    caplog.set_level(logging.WARNING, logger=mod.__name__)
    llm = AnthropicLLM(api_key="sk-ant-oat01-xyz")
    llm.complete([{"role": "user", "content": "hi"}])
    llm.complete([{"role": "user", "content": "again"}])
    warnings = [r for r in caplog.records if "no request shaper" in r.getMessage()]
    assert len(warnings) == 1
    assert "auth_token" in _last_client().kwargs
    assert "extra_headers" not in _last_client().messages.calls[0]


def test_tools_reach_the_wire_as_input_schema_in_both_modes(fake_sdk):
    tool = {"function": {"name": "Calculator", "description": "math", "parameters": {"type": "object"}}}
    for cred in ("sk-ant-api03-abc", "sk-ant-oat01-xyz"):
        llm = AnthropicLLM(api_key=cred)
        llm.complete([{"role": "user", "content": "2+2"}], tools=[tool])
        sent = _last_client().messages.calls[0]
        assert sent["tools"] == [
            {"name": "Calculator", "description": "math", "input_schema": {"type": "object"}}
        ]


# ---------------------------------------------------------------------------
# The per-agent model reaches the wire
# ---------------------------------------------------------------------------


def test_the_per_call_model_wins_over_the_provider_default(fake_sdk):
    """Every agent on a provider shares one instance; the agent's model:
    arrives as a kwarg. Reading only self.model sent the startup default for
    everyone — measured: an agent asking for haiku was sent the retired
    sonnet default and got 404."""
    llm = AnthropicLLM(api_key="sk-ant-api03-abc", model="claude-sonnet-4-5-20250929")
    resp = llm.complete([{"role": "user", "content": "hi"}], model="claude-haiku-4-5-20251001")
    assert _last_client().messages.calls[0]["model"] == "claude-haiku-4-5-20251001"
    assert resp.model == "claude-haiku-4-5-20251001"


def test_without_a_per_call_model_the_default_is_used(fake_sdk):
    llm = AnthropicLLM(api_key="sk-ant-api03-abc", model="claude-sonnet-4-5-20250929")
    llm.complete([{"role": "user", "content": "hi"}])
    assert _last_client().messages.calls[0]["model"] == "claude-sonnet-4-5-20250929"


def test_the_shipped_default_is_not_the_retired_id():
    assert mod.DEFAULT_MODEL != "claude-sonnet-4-20250514"
