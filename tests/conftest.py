"""Shared test fixtures."""

import pytest

from temper_ai.database import init_database, reset_database


@pytest.fixture(autouse=True)
def _test_db():
    """Initialize an in-memory SQLite database for each test."""
    reset_database()
    init_database("sqlite:///:memory:")
    yield
    reset_database()


_CREDENTIAL_ENV = (
    "OPENAI_API_KEY", "OPENAI_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_provider_credentials(monkeypatch):
    """Providers resolve credentials from the environment. A developer with a
    token exported in their shell would otherwise make a test that builds a
    provider "with no key" build one with a key — test_headers_no_api_key
    failed exactly that way the first time OPENAI_OAUTH_TOKEN was exported.
    Tests that want a credential set it themselves."""
    for name in _CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
