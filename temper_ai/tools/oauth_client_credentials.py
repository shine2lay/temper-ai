"""OAuth client-credentials tokens: a service's own identity, no browser.

``auth: oauth`` (see mcp_auth) covers a *person* authorizing temper once in
a browser; changes then show up as that person. Some services also hand out
an identity for the integration itself. Linear's "app actor" tokens are the
example this was built for: the client-credentials grant (client id and
secret, no user, no refresh token) returns a token that acts as the app,
valid for 30 days. Writes made with it show as the app, which is what lets a
webhook handler tell temper's own changes from a person's.

Tokens live in memory only. Linear asks that such a token is not copied
around as a long-lived key: fetch one, use it, fetch another when it is
refused. So a process fetches on first use, reuses the token until shortly
before it expires, and fetches again when a request comes back 401 --
rotating the client secret revokes every token at once, long before expiry.

There is one cache entry per (token URL, client id, scope). Linear revokes
all of an app's tokens when one is requested with a different scope, so the
callers in a process (the MCP connection, the webhook handler) must share a
token rather than each fetching their own.

Configured on an HTTP MCP server like this::

    mcp_server:
      name: linear
      transport: http
      url: https://mcp.linear.app/mcp
      auth: client_credentials
      token_url: https://api.linear.app/oauth/token
      client_id: ${LINEAR_CLIENT_ID}
      client_secret: ${LINEAR_CLIENT_SECRET}
      scope: read,write
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

AUTH_MODE = "client_credentials"
# Fetch a new token once this much of the old one's life is left (or a tenth
# of its lifetime, for tokens shorter than ten hours).
REFRESH_MARGIN_S = 3600.0
TOKEN_TIMEOUT_S = 15.0
_REQUIRED = ("token_url", "client_id", "client_secret")


class ClientCredentialsError(RuntimeError):
    """The token endpoint refused, or the configuration is incomplete."""


@dataclass(frozen=True)
class ClientCredentials:
    token_url: str
    client_id: str
    client_secret: str
    scope: str | None = None

    @classmethod
    def from_config(cls, config: dict) -> ClientCredentials:
        """Build from an MCP server config; names what is missing, never the secret."""
        missing = [key for key in _REQUIRED if not str(config.get(key) or "").strip()]
        if missing:
            name = config.get("name", "this server")
            raise ClientCredentialsError(
                f"{name}: auth '{AUTH_MODE}' needs {', '.join(missing)} "
                "(set the environment variables the config names)"
            )
        scope = str(config.get("scope") or "").strip() or None
        return cls(
            token_url=str(config["token_url"]).strip(),
            client_id=str(config["client_id"]).strip(),
            client_secret=str(config["client_secret"]).strip(),
            scope=scope,
        )

    def __repr__(self) -> str:  # the secret must never reach a log line
        return (
            f"ClientCredentials(token_url={self.token_url!r}, "
            f"client_id={self.client_id!r}, scope={self.scope!r})"
        )


def client_credentials_configured(config: dict) -> bool:
    """Whether an MCP server config asks for the client-credentials grant."""
    return str(config.get("auth", "")).lower() == AUTH_MODE


@dataclass
class _Cached:
    token: str
    expires_at: float
    margin: float


_lock = threading.Lock()
_cache: dict[ClientCredentials, _Cached] = {}


def get_token(creds: ClientCredentials, *, rejected: str | None = None) -> str:
    """A current token for ``creds``, fetching one only when needed.

    ``rejected`` is a token a server just answered 401 to. A new one is
    fetched only if the cache still holds that token: when several requests
    are refused at once, the first fetches and the rest reuse its result.
    The lock is held during the fetch on purpose, for the same reason.
    """
    with _lock:
        hit = _cache.get(creds)
        if (
            hit is not None
            and hit.token != rejected
            and hit.expires_at - time.time() > hit.margin
        ):
            return hit.token
        cached = _fetch(creds)
        _cache[creds] = cached
        return cached.token


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _fetch(creds: ClientCredentials) -> _Cached:
    data = {"grant_type": "client_credentials"}
    if creds.scope:
        data["scope"] = creds.scope
    try:
        response = httpx.post(
            creds.token_url,
            data=data,
            auth=(creds.client_id, creds.client_secret),
            timeout=TOKEN_TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        raise ClientCredentialsError(f"token request to {creds.token_url} failed: {exc}") from exc
    if response.status_code != 200:
        raise ClientCredentialsError(
            f"token request to {creds.token_url} refused ({response.status_code}): "
            f"{_error_text(response)}"
        )
    try:
        body = response.json()
        token = str(body["access_token"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ClientCredentialsError(
            f"token response from {creds.token_url} has no access_token"
        ) from exc
    lifetime = float(body.get("expires_in") or 3600)
    logger.info(
        "client-credentials token fetched for %s (client %s, scope %s), valid %.1f h",
        creds.token_url, creds.client_id, creds.scope or "-", lifetime / 3600,
    )
    return _Cached(
        token=token,
        expires_at=time.time() + lifetime,
        margin=min(REFRESH_MARGIN_S, lifetime / 10),
    )


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict):
        return str(body.get("error_description") or body.get("error") or body)[:200]
    return str(body)[:200]


class ClientCredentialsAuth(httpx.Auth):
    """Bearer auth from the shared token cache; on a 401, one fresh token and one retry."""

    def __init__(self, creds: ClientCredentials) -> None:
        self.creds = creds

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token = get_token(self.creds)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            fresh = get_token(self.creds, rejected=token)
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request

    async def async_auth_flow(
        self, request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        # The fetch is blocking I/O; keep it off the event loop.
        token = await asyncio.to_thread(get_token, self.creds)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            fresh = await asyncio.to_thread(get_token, self.creds, rejected=token)
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request
