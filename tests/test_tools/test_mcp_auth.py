"""MCP OAuth grant storage: sealing, the TokenStorage protocol, and wiring.

Every test pins the sealing key explicitly. Without that, a run on a machine
with no key would create ~/.temper/secret.key as a side effect of the test
suite — the same class of leak the _no_provider_credentials fixture exists
to prevent.
"""

import asyncio
import json
import os
import stat

import pytest
from cryptography.fernet import Fernet

from temper_ai.tools import mcp_auth
from temper_ai.tools.mcp_auth import (
    DatabaseTokenStore,
    MCPAuthError,
    _load_or_create_key,
    _Sealer,
    build_oauth_provider,
    key_fingerprint,
    oauth_configured,
)


@pytest.fixture
def key(monkeypatch):
    """A per-test sealing key, via the env var so no file is ever touched."""
    value = Fernet.generate_key().decode()
    monkeypatch.setenv(mcp_auth.SECRET_KEY_ENV_VAR, value)
    return value.encode()


@pytest.fixture
def no_key_env(monkeypatch):
    monkeypatch.delenv(mcp_auth.SECRET_KEY_ENV_VAR, raising=False)


# -- key resolution ----------------------------------------------------------


def test_env_key_wins(key):
    assert _load_or_create_key() == key


def test_invalid_env_key_is_refused_with_instructions(monkeypatch):
    monkeypatch.setenv(mcp_auth.SECRET_KEY_ENV_VAR, "not-a-real-key")
    with pytest.raises(MCPAuthError, match="not a valid key"):
        _load_or_create_key()


def test_key_file_is_created_0600_when_absent(no_key_env, tmp_path):
    path = tmp_path / "nested" / "secret.key"
    created = _load_or_create_key(path)

    assert path.exists()
    assert _load_or_create_key(path) == created, "second call must reuse, not regenerate"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"key file is {oct(mode)}, must not be readable by others"


def test_corrupt_key_file_is_refused(no_key_env, tmp_path):
    path = tmp_path / "secret.key"
    path.write_text("garbage")
    with pytest.raises(MCPAuthError, match="does not contain a valid key"):
        _load_or_create_key(path)


def test_fingerprint_is_stable_and_not_the_key(key):
    fp = key_fingerprint(key)
    assert fp == key_fingerprint(key)
    assert len(fp) == 16
    assert key.decode() not in fp


# -- sealing -----------------------------------------------------------------


def test_seal_round_trip(key):
    sealer = _Sealer(key)
    payload = {"access_token": "at-1", "refresh_token": "rt-1"}
    sealed = sealer.seal(payload)

    assert "at-1" not in sealed, "the token must not survive in the ciphertext"
    assert sealer.open(sealed) == payload


def test_open_with_wrong_key_returns_none_not_raises(key):
    sealed = _Sealer(key).seal({"access_token": "at-1"})
    other = _Sealer(Fernet.generate_key())
    assert other.open(sealed) is None


def test_open_garbage_returns_none(key):
    assert _Sealer(key).open("not-ciphertext") is None


# -- DatabaseTokenStore ------------------------------------------------------


def _token(**kwargs):
    from mcp.shared.auth import OAuthToken

    return OAuthToken(access_token="at-1", token_type="Bearer", **kwargs)


def test_tokens_round_trip_through_the_database(key):
    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(store.set_tokens(_token(refresh_token="rt-1")))

    loaded = asyncio.run(store.get_tokens())
    assert loaded is not None
    assert loaded.access_token == "at-1"
    assert loaded.refresh_token == "rt-1"


def test_tokens_are_encrypted_at_rest(key):
    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(store.set_tokens(_token(refresh_token="super-secret-rt")))

    row = store._row()
    assert "super-secret-rt" not in row.tokens_encrypted
    assert "at-1" not in row.tokens_encrypted
    with pytest.raises(Exception):
        json.loads(row.tokens_encrypted)


def test_unknown_server_reads_as_not_connected(key):
    store = DatabaseTokenStore("never-authorized")
    assert asyncio.run(store.get_tokens()) is None
    assert store.describe() == {"connected": False, "reason": "never authorized"}


def test_grant_sealed_with_another_key_reads_as_disconnected(key, monkeypatch):
    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(store.set_tokens(_token(refresh_token="rt-1")))

    # Key rotated (or a different deployment's key): the row is unreadable.
    monkeypatch.setenv(mcp_auth.SECRET_KEY_ENV_VAR, Fernet.generate_key().decode())
    rotated = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")

    assert asyncio.run(rotated.get_tokens()) is None, "must not fall back to plaintext"
    assert rotated.describe()["connected"] is False
    assert "different key" in rotated.describe()["reason"]


def test_grant_for_a_different_url_is_not_reused(key):
    """Same server name repointed at another endpoint is a different consent."""
    asyncio.run(
        DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp").set_tokens(
            _token(refresh_token="rt-1")
        )
    )
    moved = DatabaseTokenStore("notion", server_url="https://evil.example.com/mcp")
    assert asyncio.run(moved.get_tokens()) is None


def test_client_info_round_trip(key):
    from mcp.shared.auth import OAuthClientInformationFull

    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    info = OAuthClientInformationFull(
        client_id="cid-1",
        redirect_uris=["http://localhost:8765/callback"],
    )
    asyncio.run(store.set_client_info(info))

    loaded = asyncio.run(store.get_client_info())
    assert loaded is not None
    assert loaded.client_id == "cid-1"


def test_set_tokens_preserves_client_info(key):
    """Registration happens once; a token refresh must not drop it."""
    from mcp.shared.auth import OAuthClientInformationFull

    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(
        store.set_client_info(
            OAuthClientInformationFull(
                client_id="cid-1", redirect_uris=["http://localhost:8765/callback"]
            )
        )
    )
    asyncio.run(store.set_tokens(_token(refresh_token="rt-2")))

    assert asyncio.run(store.get_client_info()).client_id == "cid-1"
    assert asyncio.run(store.get_tokens()).refresh_token == "rt-2"


def test_describe_reports_refreshability_without_exposing_tokens(key):
    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(store.set_tokens(_token(refresh_token="rt-1")))

    info = store.describe()
    assert info["connected"] is True
    assert info["has_refresh_token"] is True
    assert "rt-1" not in json.dumps(info, default=str)


def test_delete_forgets_the_grant(key):
    store = DatabaseTokenStore("notion", server_url="https://mcp.notion.com/mcp")
    asyncio.run(store.set_tokens(_token()))

    assert store.delete() is True
    assert store.delete() is False, "deleting twice is not an error"
    assert asyncio.run(store.get_tokens()) is None


# -- provider construction ---------------------------------------------------


@pytest.mark.parametrize(
    "config,expected",
    [
        ({"auth": "oauth"}, True),
        ({"auth": "OAuth"}, True),
        ({"auth": "oauth2"}, True),
        ({}, False),
        ({"auth": "none"}, False),
        ({"headers": {"Authorization": "Bearer x"}}, False),
    ],
)
def test_oauth_configured(config, expected):
    assert oauth_configured(config) is expected


def test_non_interactive_provider_refuses_to_open_a_browser(key):
    """A headless run must fail fast, not hang waiting for a human."""
    provider = build_oauth_provider(
        {"name": "notion", "url": "https://mcp.notion.com/mcp", "auth": "oauth"}
    )

    with pytest.raises(MCPAuthError, match="temper connect notion"):
        asyncio.run(provider.context.redirect_handler("https://example.com/authorize"))
    with pytest.raises(MCPAuthError, match="not connected"):
        asyncio.run(provider.context.callback_handler())


def test_provider_registers_a_loopback_redirect_uri(key):
    provider = build_oauth_provider(
        {
            "name": "notion",
            "url": "https://mcp.notion.com/mcp",
            "auth": "oauth",
            "callback_port": 9999,
        }
    )
    uris = [str(u) for u in provider.context.client_metadata.redirect_uris]
    assert uris == ["http://localhost:9999/callback"]


def test_provider_identifies_itself_as_temper(key):
    provider = build_oauth_provider(
        {"name": "notion", "url": "https://mcp.notion.com/mcp", "auth": "oauth"}
    )
    assert provider.context.client_metadata.client_name == "temper"
    # Public client: nothing secret to store, so nothing secret to leak.
    assert provider.context.client_metadata.token_endpoint_auth_method == "none"


# -- manual paste flow (headless / remote machines) --------------------------


def test_paste_full_redirected_url():
    code, state = mcp_auth.parse_pasted_callback(
        "http://localhost:8765/callback?code=abc123&state=xyz"
    )
    assert (code, state) == ("abc123", "xyz")


def test_paste_percent_encoded_code_is_decoded():
    """Notion issues codes containing ':', which arrive as %3A in a raw paste.

    Handing the still-encoded string to the token endpoint fails the exchange,
    and the error a provider returns for that is indistinguishable from an
    expired code — so this is pinned rather than trusted.
    """
    code, _ = mcp_auth.parse_pasted_callback(
        "http://localhost:8765/callback?code=590117a7%3AaCoJojv86zp1mCtE%3ACQiqO3dP&state=s"
    )
    assert code == "590117a7:aCoJojv86zp1mCtE:CQiqO3dP"


def test_paste_query_string_only():
    assert mcp_auth.parse_pasted_callback("code=abc123&state=xyz") == ("abc123", "xyz")


def test_paste_bare_code():
    assert mcp_auth.parse_pasted_callback("  abc123  ") == ("abc123", None)


def test_paste_strips_surrounding_quotes():
    code, _ = mcp_auth.parse_pasted_callback('"http://localhost:8765/callback?code=abc&state=s"')
    assert code == "abc"


def test_paste_surfaces_a_refusal():
    with pytest.raises(MCPAuthError, match="access_denied"):
        mcp_auth.parse_pasted_callback(
            "http://localhost:8765/callback?error=access_denied"
        )


def test_paste_url_without_code_says_what_to_paste():
    with pytest.raises(MCPAuthError, match="full URL"):
        mcp_auth.parse_pasted_callback("http://localhost:8765/callback?state=xyz")


def test_paste_empty_is_refused():
    with pytest.raises(MCPAuthError, match="Nothing pasted"):
        mcp_auth.parse_pasted_callback("   ")


def test_manual_mode_reads_the_paste_and_never_binds_a_port(key, monkeypatch):
    """The whole point of manual mode is that nothing listens locally."""

    def refuse_bind(*args, **kwargs):
        raise AssertionError("manual mode must not open a listening socket")

    monkeypatch.setattr(mcp_auth, "_serve_one_callback", refuse_bind)
    monkeypatch.setattr(
        "builtins.input",
        lambda *a: "http://localhost:8765/callback?code=pasted-code&state=st",
    )

    provider = build_oauth_provider(
        {"name": "notion", "url": "https://mcp.notion.com/mcp", "auth": "oauth"},
        interactive=True,
        manual=True,
    )

    assert asyncio.run(provider.context.callback_handler()) == ("pasted-code", "st")


def test_find_free_port_falls_back_when_taken():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        busy = taken.getsockname()[1]

        chosen = mcp_auth.find_free_port(busy)
        assert chosen != busy
        assert chosen > 0
