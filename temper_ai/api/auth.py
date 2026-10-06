"""Token authentication at the HTTP edge.

Enforced here rather than as a route dependency for one specific reason:
the MCP tools call the API's route functions in-process, as plain Python.
A `Depends(...)` on those handlers would check HTTP callers and let every
MCP call straight past — a locked front door and an open side one into
the same operations. Middleware sees the request before routing, so a
single check covers `/api`, `/mcp` and the WebSocket alike.

Off unless TEMPER_API_TOKEN is set, so existing installs are unchanged.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# Container health checks have no credential to offer, and the endpoint
# reveals nothing.
# /api/runtime-config answers one question — "does this server need a
# token?" — and gating it made the answer unobtainable: the flag could only
# ever be read as false, so every client had to infer the truth from a 401.
# It discloses nothing a 401 does not already disclose.
# /api/hooks/linear cannot be given the API token (Linear sends what it
# sends), so it authenticates each delivery itself: Linear's HMAC signature
# over the body, and a timestamp under a minute old (api/hooks.py). Exact
# path only: /api/hooks/linear/recent stays behind the token. Notion and
# GitHub are the same: each delivery carries the sender's signature (Notion's,
# and GitHub's X-Hub-Signature-256 with the app's webhook secret).
PUBLIC_PATHS = (
    "/api/health", "/api/runtime-config", "/api/hooks/linear", "/api/hooks/notion", "/api/hooks/github",
)

# The dashboard's static shell: HTML, JS and CSS containing no data. It
# has to load unauthenticated or there is nowhere to type the token. Every
# request it then makes for actual data goes through the check below.
PUBLIC_PREFIXES = ("/app", "/assets", "/favicon")

# A fake Slack event's response link (api/slack_test.py). Temper calls it
# back the way it calls Slack's own response_url: with no token, as Slack's
# needs none. The route itself lets only the server's own calls (from
# 127.0.0.1) in without the test entry's secret, and keeps answers only for
# a fake of the last hour, named by 24 random hex characters; the rest of
# /api/test/slack stays behind the token.
FAKE_REPLIES_PREFIX = "/api/test/slack/replies/"

TOKEN_ENV_VAR = "TEMPER_API_TOKEN"  # noqa: S105 - name, not a secret
TOKEN_FILE_ENV_VAR = "TEMPER_API_TOKENS_FILE"  # noqa: S105 - name, not a secret

# Cache of the tokens file, refreshed when its mtime changes. Without this a
# revocation would need a restart, which makes "revocable" untrue in the only
# case that matters: a token you need to stop working right now.
_file_cache: tuple[float, dict[str, str]] | None = None


def configured_token() -> str | None:
    """The shared token, or None when it is not set."""
    return os.environ.get(TOKEN_ENV_VAR, "").strip() or None


def named_tokens() -> dict[str, str]:
    """Named client tokens from the tokens file: ``{"ci": "abc...", ...}``.

    Re-read whenever the file changes, so deleting a name takes effect on
    the next request rather than the next restart. A malformed or missing
    file is treated as "no named tokens" and logged, never raised: an
    unreadable file must not take the server down, and must not silently
    grant access either.
    """
    global _file_cache
    path = os.environ.get(TOKEN_FILE_ENV_VAR, "").strip()
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        if _file_cache is not None:
            logger.warning("tokens file %s disappeared; no named tokens accepted", path)
        _file_cache = None
        return {}

    if _file_cache is not None and _file_cache[0] == mtime:
        return _file_cache[1]

    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        tokens = {
            str(name): str(value).strip()
            for name, value in raw.items()
            if str(value).strip()
        }
    except Exception as exc:
        logger.warning("tokens file %s unreadable (%s); no named tokens accepted", path, exc)
        _file_cache = (mtime, {})
        return {}

    logger.info("tokens file %s loaded: %d named client(s)", path, len(tokens))
    _file_cache = (mtime, tokens)
    return tokens


def auth_enabled() -> bool:
    """True when any credential is configured."""
    return configured_token() is not None or bool(named_tokens())


def identify(presented: str | None) -> str | None:
    """Return the client name a token belongs to, or None if it matches none.

    The shared token answers to "shared". Comparison is constant-time and
    every candidate is checked, so the reply time does not reveal which
    name matched or how far down the list it was.
    """
    if presented is None:
        return None
    matched: str | None = None
    shared = configured_token()
    if shared is not None and hmac.compare_digest(presented, shared):
        matched = "shared"
    for name, token in named_tokens().items():
        if hmac.compare_digest(presented, token):
            matched = matched or name
    return matched


def _header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _same_origin(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    """Whether the request's Origin header names the host it was sent to (a page this
    server served sent it). A display hint only: any client can send any Origin."""
    from urllib.parse import urlsplit

    origin, host = _header(headers, b"origin"), _header(headers, b"host")
    if not origin or not host:
        return False
    try:
        return urlsplit(origin).netloc.lower() == host.lower()
    except ValueError:
        return False


def _presented_token(scope: dict) -> str | None:
    """Pull the caller's token from wherever it can reasonably be.

    A browser cannot set headers on a WebSocket handshake, so the query
    string is accepted too; MCP clients and CLIs use the Authorization
    header.
    """
    headers = scope.get("headers") or []

    authorization = _header(headers, b"authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    direct = _header(headers, b"x-temper-token")
    if direct:
        return direct.strip()

    query = (scope.get("query_string") or b"").decode("latin-1")
    for part in query.split("&"):
        if part.startswith("token="):
            from urllib.parse import unquote

            return unquote(part[6:])

    cookie = _header(headers, b"cookie")
    if cookie:
        for crumb in cookie.split(";"):
            name, _, value = crumb.strip().partition("=")
            if name == "temper_token":
                return value

    return None


def _is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if path.startswith(FAKE_REPLIES_PREFIX):
        return True
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PUBLIC_PREFIXES)


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOOPBACK = frozenset({"127.0.0.1", "::1"})
SCOPE_CALLER_KEY = "temper.caller"


def _write_key(scope: dict) -> str | None:
    """The key a request carries for the write guard: a header only.

    Not ``?token=`` and not the cookie, which the all-routes token above
    still accepts: a key in a URL ends up in access logs and browser
    history, and a cookie is sent by the browser on its own.
    """
    headers = scope.get("headers") or []
    authorization = _header(headers, b"authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    direct = _header(headers, b"x-temper-token")
    return direct.strip() if direct else None


def _server_owns_loopback() -> bool:
    """True when nothing but the server's own processes can call it from 127.0.0.1.

    In a container the host's requests arrive from the network's gateway,
    and runs' boxes from their own addresses, so 127.0.0.1 is someone inside
    the server's own container: ``docker exec ... temper`` (measured
    2026-10-05). That holds only while runs happen elsewhere: with
    TEMPER_EXECUTION_MODE inprocess or subprocess an agent's Bash runs in
    this container too, and loopback names nobody.
    """
    mode = (os.environ.get("TEMPER_EXECUTION_MODE") or "inprocess").strip().lower()
    return mode == "external" and os.path.exists("/.dockerenv")


def identify_caller_name(presented: str | None, source: str) -> str | None:
    """Who a write comes from, before any run key is looked up (see CallerMiddleware).

    The shared TEMPER_API_TOKEN does not name a writer: every run box's own
    process carries it (docs/boxes.md), where an agent can read it. Only a
    named key (the hashed keys file, or TEMPER_API_TOKENS_FILE, which stays
    on the server) does.
    """
    from temper_ai.api.api_keys import identify_key

    if presented:
        named = identify_key(presented) or identify(presented)
        return None if named == "shared" else named
    if source in _LOOPBACK and _server_owns_loopback():
        return "server"
    return None


class CallerMiddleware:
    """Work out who sent each request and bind it for the request (api/caller.py).

    This only names the caller; it refuses nothing. The guard runs inside
    each operation that changes something (``require_caller_may``), so the
    MCP tools, which call those operations in-process, meet the same check.
    A key that matches nothing makes the caller unknown, the same as none.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        from temper_ai.api.caller import Caller, bound, clean_request_id

        client = scope.get("client")
        source = str(client[0]) if client else "unknown"
        method = str(scope.get("method", "")).upper()
        presented = _write_key(scope)
        name: str | None = None
        may: frozenset[str] | None = None
        if method not in _READ_METHODS:
            name = identify_caller_name(presented, source)
            if name is None and presented:
                from temper_ai.api.run_tokens import identify_run_key, is_run_key

                if is_run_key(presented):
                    import anyio

                    found = await anyio.to_thread.run_sync(identify_run_key, presented)
                    if found:
                        # A run's own key: named for its run, and may only what its kind may.
                        name, may = f"box:{found[0]}", found[1].powers
        headers = scope.get("headers") or []
        caller = Caller(
            name=name,
            source=source,
            request_id=clean_request_id(_header(headers, b"x-request-id")),
            via=f"{method} {scope.get('path', '')}",
            # A hint for record mode only (the dashboard without its key); never vouches.
            from_browser=name is None and _header(headers, b"sec-fetch-mode") is not None,
            may=may,
            # For display only (where an action came from, M3 E15); never vouches.
            same_origin=_same_origin(headers),
        )
        scope[SCOPE_CALLER_KEY] = caller
        with bound(caller):
            await self.app(scope, receive, send)


class TokenAuthMiddleware:
    """Require a bearer token on everything that carries data."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if not auth_enabled() or _is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        # Constant-time comparison: a token that leaks through response
        # timing is not much of a token.
        presented = _presented_token(scope)
        client = identify(presented)
        if client is None and presented:
            # A named key (api/api_keys.py) or a run's own key opens the door too: the
            # write guard then decides what it may change (api/caller.py).
            from temper_ai.api.api_keys import identify_key
            from temper_ai.api.run_tokens import identify_run_key, is_run_key

            client = identify_key(presented)
            if client is None and is_run_key(presented):
                import anyio

                found = await anyio.to_thread.run_sync(identify_run_key, presented)
                # A GitHub-token key opens only the GitHub paths; a start/fork key, any.
                client = found[0] if found and found[1].opens(scope.get("path", "")) else None
        if client is not None:
            await self.app(scope, receive, send)
            return

        logger.warning(
            "rejected unauthenticated %s %s",
            scope.get("type"),
            scope.get("path"),
        )
        await self._reject(scope, send)

    async def _reject(self, scope, send) -> None:
        if scope.get("type") == "websocket":
            # 4401: the application-level equivalent of 401, since the
            # handshake never completes.
            await send({"type": "websocket.close", "code": 4401})
            return

        body = json.dumps(
            {
                "detail": (
                    "Authentication required. Send 'Authorization: Bearer "
                    "<token>' (the value of TEMPER_API_TOKEN)."
                )
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="temper"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
