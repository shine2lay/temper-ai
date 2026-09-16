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
PUBLIC_PATHS = ("/api/health",)

# The dashboard's static shell: HTML, JS and CSS containing no data. It
# has to load unauthenticated or there is nowhere to type the token. Every
# request it then makes for actual data goes through the check below.
PUBLIC_PREFIXES = ("/app", "/assets", "/favicon")

TOKEN_ENV_VAR = "TEMPER_API_TOKEN"  # noqa: S105 - name, not a secret


def configured_token() -> str | None:
    """The expected token, or None when authentication is disabled."""
    return os.environ.get(TOKEN_ENV_VAR, "").strip() or None


def _header(headers: Iterable[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


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
    return any(path == prefix or path.startswith(prefix + "/") for prefix in PUBLIC_PREFIXES)


class TokenAuthMiddleware:
    """Require a bearer token on everything that carries data."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        expected = configured_token()
        if expected is None or _is_public(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        presented = _presented_token(scope)
        # Constant-time: a token that leaks through response timing is not
        # much of a token.
        if presented is not None and hmac.compare_digest(presented, expected):
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
