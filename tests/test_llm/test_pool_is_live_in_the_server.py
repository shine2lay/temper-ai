"""The second subscription is actually used.

Two Claude subscriptions were configured for months and only one was ever spent. The provider
pools OAuth tokens, but only when it resolves the credential itself:

    if self.auth_mode == "oauth" and not (api_key or "").strip():
        pooled = [t for t in tokens_from_env(OAUTH_TOKEN_ENV) ...]

The guard is right -- a credential handed in by a test or a caller means "use this one", not
"go find its siblings in the environment". But the server resolved the token one layer up and
passed it in, so production took the explicit-credential branch every time and `_pool` was None.
The pool, the cooldowns and the failover were all dead code in the only process that runs work.

What it cost: an epd_measure run died in five seconds against a rate-limited account with
`tokens=0`, while a second subscription with its own untouched window sat in the same .env.
"""

import pytest

import temper_ai.server as server
from temper_ai.llm import pi_logins
from temper_ai.llm.providers.anthropic import AnthropicLLM

# These build the real provider through the real server wiring, which needs the SDK. The
# pre-commit hook runs a bare `pytest` whose interpreter does not have it, where the server
# logs "SDK not installed for provider 'anthropic'" and hands back nothing at all -- so
# without this the failure reads as "the pool is missing" rather than "the SDK is".
pytest.importorskip("anthropic")

TOKEN_A = "sk-ant-oat01-aaaa"
TOKEN_B = "sk-ant-oat01-bbbb"


def _build(monkeypatch, slots=("anthropic", "anthropic-2"), **env) -> AnthropicLLM:
    """The Anthropic provider exactly as the server builds it, on a named environment."""
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_BACKUP",
                 "CLAUDE_CODE_OAUTH_TOKEN_2", "CLAUDE_CODE_OAUTH_TOKEN_3", "ANTHROPIC_MODEL",
                 *[f"CLAUDE_CODE_OAUTH_TOKEN_{i}" for i in range(4, 10)]):
        monkeypatch.setenv(name, "")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(pi_logins, "configured_slots", lambda: list(slots))

    return server._init_llm_providers().get("anthropic")


def test_two_pi_slots_mean_two_in_the_pool_and_no_stored_token(monkeypatch):
    llm = _build(monkeypatch, slots=("anthropic", "anthropic-2"))
    assert llm is not None, "the provider did not come up"
    assert llm._pool is not None, (
        "the second subscription is never spent: the server forwarded a resolved credential, "
        "which the provider reads as 'use this one, do not look for siblings'"
    )
    assert len(llm._pool) == 2
    assert llm._pool.tokens == ["anthropic", "anthropic-2"]
    assert llm._pool.labels == ["anthropic", "anthropic-2"]
    assert llm.api_key is None


def test_one_pi_slot_still_pools_by_slot_so_its_login_comes_from_pi_per_call(monkeypatch):
    llm = _build(monkeypatch, slots=("anthropic",))
    assert llm is not None and llm._pool is not None
    assert llm._pool.tokens == ["anthropic"]
    assert llm.api_key is None


def test_env_oauth_tokens_alone_bring_up_no_provider(monkeypatch):
    llm = _build(monkeypatch, slots=(), CLAUDE_CODE_OAUTH_TOKEN=TOKEN_A, CLAUDE_CODE_OAUTH_TOKEN_2=TOKEN_B)
    assert llm is None


def test_an_empty_model_variable_means_the_default_model(monkeypatch):
    """docker-compose passes `ANTHROPIC_MODEL: ${ANTHROPIC_MODEL:-}`, so the variable is
    present but empty whenever the host leaves it out. Read as a model name, every call
    that named none of its own -- a fallback entry naming only a provider -- went out
    with model "" and was refused."""
    from temper_ai.llm.providers.anthropic import DEFAULT_MODEL

    llm = _build(monkeypatch, slots=("anthropic",))  # ANTHROPIC_MODEL=""
    assert llm is not None and llm.model == DEFAULT_MODEL


def test_an_api_key_still_wins_and_does_not_pool_oauth(monkeypatch):
    """API key is the provider's native credential and takes precedence; OAuth pooling is
    for subscriptions, so a key-mode provider must not quietly start spending them."""
    llm = _build(monkeypatch, slots=("anthropic", "anthropic-2"),
                 ANTHROPIC_API_KEY="sk-ant-api03-real",
                 CLAUDE_CODE_OAUTH_TOKEN=TOKEN_A, CLAUDE_CODE_OAUTH_TOKEN_2=TOKEN_B)
    assert llm is not None
    assert llm.auth_mode == "api_key" and llm.api_key == "sk-ant-api03-real"
    assert llm._pool is None
