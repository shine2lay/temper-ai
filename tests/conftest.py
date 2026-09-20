"""Shared test fixtures."""

import pytest

from temper_ai.database import init_database, reset_database
from temper_ai.tools.executor import ToolExecutor


@pytest.fixture(autouse=True)
def _test_db():
    """Initialize an in-memory SQLite database for each test."""
    reset_database()
    init_database("sqlite:///:memory:")
    yield
    reset_database()


@pytest.fixture(autouse=True)
def _scratch_dirs_under_pytest_tmp(tmp_path_factory, monkeypatch):
    """Keep every executor's scratch directory under pytest's own tmp.

    An executor makes its scratch directory the first time a path strays
    outside the workspace and removes it on shutdown(). Tests make executors
    by the dozen and rarely shut them down, so left alone the suite would
    leave one temper-scratch-* in /tmp per straying test, forever. pytest
    prunes its own tmp tree (last three runs)."""
    monkeypatch.setattr(
        ToolExecutor, "_make_scratch_dir",
        lambda self: str(tmp_path_factory.mktemp("temper-scratch-")),
    )


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
