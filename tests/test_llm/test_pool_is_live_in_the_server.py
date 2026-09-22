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
from temper_ai.llm.providers.anthropic import AnthropicLLM

# These build the real provider through the real server wiring, which needs the SDK. The
# pre-commit hook runs a bare `pytest` whose interpreter does not have it, where the server
# logs "SDK not installed for provider 'anthropic'" and hands back nothing at all -- so
# without this the failure reads as "the pool is missing" rather than "the SDK is".
pytest.importorskip("anthropic")

TOKEN_A = "sk-ant-oat01-aaaa"
TOKEN_B = "sk-ant-oat01-bbbb"


def _build(monkeypatch, **env) -> AnthropicLLM:
    """The Anthropic provider exactly as the server builds it, on a named environment.

    Absent variables are set empty rather than deleted. temper_ai/cli/main.py:203 calls
    load_dotenv(override=False), so once any test in the process has touched the CLI, a
    *deleted* name is one the real .env is free to refill -- and this repository's .env has
    two live subscription tokens in it. Under xdist, whether that had happened yet depended
    on which worker ran first, so these tests passed alone and failed in the suite. An empty
    string is "already present" to dotenv, and falsy to every reader here.
    """
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_BACKUP",
                 "CLAUDE_CODE_OAUTH_TOKEN_2", "CLAUDE_CODE_OAUTH_TOKEN_3", "ANTHROPIC_MODEL",
                 *[f"CLAUDE_CODE_OAUTH_TOKEN_{i}" for i in range(4, 10)]):
        monkeypatch.setenv(name, "")
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    return server._init_llm_providers().get("anthropic")


def test_two_subscriptions_in_the_env_means_two_in_the_pool(monkeypatch):
    llm = _build(monkeypatch, CLAUDE_CODE_OAUTH_TOKEN=TOKEN_A, CLAUDE_CODE_OAUTH_TOKEN_2=TOKEN_B)
    assert llm is not None, "the provider did not come up"
    assert llm._pool is not None, (
        "the second subscription is never spent: the server forwarded the resolved credential, "
        "which the provider reads as 'use this one, do not look for siblings'"
    )
    assert len(llm._pool) == 2
    assert set(llm._pool.tokens) == {TOKEN_A, TOKEN_B}


def test_one_subscription_needs_no_pool(monkeypatch):
    llm = _build(monkeypatch, CLAUDE_CODE_OAUTH_TOKEN=TOKEN_A)
    assert llm is not None and llm._pool is None, "nothing to rotate between"
    assert llm.api_key == TOKEN_A, "and it still uses the one token there is"


def test_an_api_key_still_wins_and_does_not_pool_oauth(monkeypatch):
    """API key is the provider's native credential and takes precedence; OAuth pooling is
    for subscriptions, so a key-mode provider must not quietly start spending them."""
    llm = _build(monkeypatch, ANTHROPIC_API_KEY="sk-ant-api03-real",
                 CLAUDE_CODE_OAUTH_TOKEN=TOKEN_A, CLAUDE_CODE_OAUTH_TOKEN_2=TOKEN_B)
    assert llm is not None
    assert llm.auth_mode == "api_key" and llm.api_key == "sk-ant-api03-real"
    assert llm._pool is None
