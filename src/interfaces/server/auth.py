"""API key authentication middleware for MAF Server.

When the ``MAF_API_KEY`` environment variable is set, all requests
(except health endpoints and WebSocket upgrades) must include an
``X-API-Key`` header matching the configured key.

When ``MAF_API_KEY`` is not set, authentication is disabled (dev mode).
"""
import logging
import os
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import HTTP_401_UNAUTHORIZED

logger = logging.getLogger(__name__)

ENV_API_KEY = "MAF_API_KEY"
HEADER_API_KEY = "X-API-Key"

# Paths that bypass authentication (health probes must always work)
AUTH_BYPASS_PATHS = frozenset({"/api/health", "/api/health/ready"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header against MAF_API_KEY env var.

    When no API key is configured, all requests pass through (dev mode).
    Health endpoints and WebSocket connections bypass authentication.
    """

    def __init__(self, app: Any, api_key: str | None = None) -> None:
        super().__init__(app)
        self.api_key = api_key or os.environ.get(ENV_API_KEY)
        if self.api_key:
            logger.info("API key authentication enabled")
        else:
            logger.info("API key authentication disabled (MAF_API_KEY not set)")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Check API key for non-exempt requests."""
        # No key configured → auth disabled
        if not self.api_key:
            return await call_next(request)

        # Bypass health endpoints
        if request.url.path in AUTH_BYPASS_PATHS:
            return await call_next(request)

        # Bypass WebSocket upgrades (handled separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Validate API key
        provided_key = request.headers.get(HEADER_API_KEY)
        if not provided_key or provided_key != self.api_key:
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
