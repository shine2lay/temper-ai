"""Named, revocable client tokens.

The point of naming tokens is being able to withdraw one without disturbing
the others, and without a restart — a revocation that needs a deploy is not
a revocation in the case that matters.
"""

import json

import pytest

from temper_ai.api import auth


@pytest.fixture(autouse=True)
def _clear_cache():
    auth._file_cache = None
    yield
    auth._file_cache = None


@pytest.fixture
def tokens_file(tmp_path, monkeypatch):
    path = tmp_path / "tokens.json"

    def write(mapping: dict) -> None:
        path.write_text(json.dumps(mapping))
        # Bust the mtime cache deterministically: two writes inside one
        # filesystem timestamp tick would otherwise look unchanged.
        auth._file_cache = None

    write({"ci": "ci-token", "laptop": "laptop-token"})
    monkeypatch.setenv(auth.TOKEN_FILE_ENV_VAR, str(path))
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    return write


def test_each_named_token_identifies_its_client(tokens_file):
    assert auth.identify("ci-token") == "ci"
    assert auth.identify("laptop-token") == "laptop"


def test_an_unknown_token_matches_nothing(tokens_file):
    assert auth.identify("not-a-token") is None
    assert auth.identify(None) is None


def test_revoking_one_leaves_the_others_working(tokens_file):
    tokens_file({"laptop": "laptop-token"})
    assert auth.identify("ci-token") is None, "revoked token still accepted"
    assert auth.identify("laptop-token") == "laptop"


def test_auth_is_enabled_by_named_tokens_alone(tokens_file):
    """No shared token set: the server must still be protected."""
    assert auth.configured_token() is None
    assert auth.auth_enabled() is True


def test_shared_token_still_works_and_is_named_shared(monkeypatch):
    monkeypatch.setenv(auth.TOKEN_ENV_VAR, "shared-token")
    monkeypatch.delenv(auth.TOKEN_FILE_ENV_VAR, raising=False)
    assert auth.identify("shared-token") == "shared"
    assert auth.auth_enabled() is True


def test_no_credentials_means_authentication_is_off(monkeypatch):
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(auth.TOKEN_FILE_ENV_VAR, raising=False)
    assert auth.auth_enabled() is False


def test_an_unreadable_file_grants_nothing(tmp_path, monkeypatch):
    """Failing open would turn a typo in a config file into an open server."""
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    monkeypatch.setenv(auth.TOKEN_FILE_ENV_VAR, str(path))
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    assert auth.named_tokens() == {}
    assert auth.identify("anything") is None


def test_a_missing_file_grants_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.TOKEN_FILE_ENV_VAR, str(tmp_path / "absent.json"))
    monkeypatch.delenv(auth.TOKEN_ENV_VAR, raising=False)
    assert auth.named_tokens() == {}
    assert auth.auth_enabled() is False


def test_blank_values_are_not_usable_tokens(tokens_file):
    tokens_file({"ci": "   ", "laptop": "laptop-token"})
    assert auth.identify("   ") is None
    assert auth.identify("laptop-token") == "laptop"
