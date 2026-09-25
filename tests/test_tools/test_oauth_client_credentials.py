"""Client-credentials tokens: fetched once, shared, replaced when refused.

The token is temper's own identity at a service (Linear's app actor). The
things that go wrong with such a token are quiet: fetching one per request
(and at Linear, a fetch with a different scope revokes every other token),
never replacing one the service stopped accepting, or leaking the client
secret into a log line. Each of those is pinned here.
"""

import asyncio
import base64

import httpx
import pytest

from temper_ai.tools import oauth_client_credentials as occ
from temper_ai.tools.oauth_client_credentials import (
    ClientCredentials,
    ClientCredentialsAuth,
    ClientCredentialsError,
    client_credentials_configured,
    get_token,
)

CREDS = ClientCredentials(
    token_url="https://auth.example.com/oauth/token",
    client_id="client-1",
    client_secret="s3cret-value",
    scope="read,write",
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    occ.clear_cache()
    yield
    occ.clear_cache()


@pytest.fixture
def token_server(monkeypatch):
    """Stand in for the token endpoint: hands out tok-1, tok-2, ... and records calls."""
    calls: list[dict] = []
    state = {"expires_in": 2591999, "status": 200, "body": None}

    def fake_post(url, data=None, auth=None, timeout=None):
        calls.append({"url": url, "data": dict(data or {}), "auth": auth})
        request = httpx.Request("POST", url)
        if state["status"] != 200:
            return httpx.Response(state["status"], json=state["body"], request=request)
        return httpx.Response(
            200,
            json={
                "access_token": f"tok-{len(calls)}",
                "token_type": "Bearer",
                "expires_in": state["expires_in"],
                "scope": "read write",
            },
            request=request,
        )

    monkeypatch.setattr(occ.httpx, "post", fake_post)
    return calls, state


def test_config_names_what_is_missing_and_never_the_secret():
    with pytest.raises(ClientCredentialsError) as err:
        ClientCredentials.from_config(
            {"name": "linear", "token_url": "https://x/token", "client_id": "", "client_secret": "s3cret-value"}
        )
    assert "linear" in str(err.value)
    assert "client_id" in str(err.value)
    assert "s3cret-value" not in str(err.value)
    assert "s3cret-value" not in repr(CREDS)


def test_the_auth_mode_is_recognised():
    assert client_credentials_configured({"auth": "client_credentials"})
    assert client_credentials_configured({"auth": "Client_Credentials"})
    assert not client_credentials_configured({"auth": "oauth"})
    assert not client_credentials_configured({})


def test_one_fetch_serves_every_caller(token_server):
    calls, _ = token_server

    first = get_token(CREDS)
    again = get_token(ClientCredentials(**vars(CREDS)))  # an equal config shares the entry

    assert first == again == "tok-1"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == CREDS.token_url
    assert call["data"] == {"grant_type": "client_credentials", "scope": "read,write"}
    assert call["auth"] == ("client-1", "s3cret-value")


def test_a_token_near_its_end_is_replaced(token_server, monkeypatch):
    calls, state = token_server
    state["expires_in"] = 100  # margin is a tenth of that: 10 s
    now = [1_000_000.0]
    monkeypatch.setattr(occ.time, "time", lambda: now[0])

    assert get_token(CREDS) == "tok-1"
    now[0] += 80
    assert get_token(CREDS) == "tok-1"
    now[0] += 15  # 5 s left, inside the margin
    assert get_token(CREDS) == "tok-2"
    assert len(calls) == 2


def test_a_refused_token_is_replaced_once(token_server):
    calls, _ = token_server
    old = get_token(CREDS)

    new = get_token(CREDS, rejected=old)
    # A second request refused with the same old token reuses the new one.
    again = get_token(CREDS, rejected=old)

    assert (old, new, again) == ("tok-1", "tok-2", "tok-2")
    assert len(calls) == 2


def test_a_refusal_from_the_token_endpoint_says_why(token_server):
    _, state = token_server
    state["status"] = 400
    state["body"] = {
        "error": "Error",
        "error_description": "Client does not support the client_credentials grant type",
    }

    with pytest.raises(ClientCredentialsError) as err:
        get_token(CREDS)

    assert "client_credentials grant type" in str(err.value)
    assert "400" in str(err.value)
    assert "s3cret-value" not in str(err.value)


def _service(seen: list[str], accept: str):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen.append(auth)
        if auth == f"Bearer {accept}":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"error": "invalid token"})

    return handler


def test_auth_retries_once_with_a_fresh_token_after_401(token_server):
    calls, _ = token_server
    seen: list[str] = []
    client = httpx.Client(transport=httpx.MockTransport(_service(seen, accept="tok-2")))

    response = client.get("https://api.example.com/x", auth=ClientCredentialsAuth(CREDS))

    assert response.status_code == 200
    assert seen == ["Bearer tok-1", "Bearer tok-2"]
    assert len(calls) == 2


def test_auth_gives_up_after_one_retry(token_server):
    seen: list[str] = []
    client = httpx.Client(transport=httpx.MockTransport(_service(seen, accept="never")))

    response = client.get("https://api.example.com/x", auth=ClientCredentialsAuth(CREDS))

    assert response.status_code == 401
    assert len(seen) == 2


def test_async_auth_flow_matches_the_sync_one(token_server):
    seen: list[str] = []

    async def run():
        transport = httpx.MockTransport(_service(seen, accept="tok-2"))
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.get("https://api.example.com/x", auth=ClientCredentialsAuth(CREDS))

    response = asyncio.run(run())

    assert response.status_code == 200
    assert seen == ["Bearer tok-1", "Bearer tok-2"]


def test_basic_auth_header_is_what_httpx_sends(token_server):
    """The (id, secret) tuple becomes HTTP basic auth, which is what Linear accepts."""
    calls, _ = token_server
    get_token(CREDS)
    user, password = calls[0]["auth"]
    header = httpx.BasicAuth(user, password)._auth_header
    assert header == "Basic " + base64.b64encode(b"client-1:s3cret-value").decode()
