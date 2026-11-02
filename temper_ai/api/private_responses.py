"""Fixed private HTTP refusals and server-generated correlation identifiers."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

from temper_ai.private_context.errors import HTTP_STATUS
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.wire import VERSION

PRIVATE_ROOT = "/api/private-contexts"
WORKER_ROOT = "/api/private-worker"


def is_private_path(path: str) -> bool:
    """Namespace routing only, never authorization or worker route power."""
    return any(path == root or path.startswith(root + "/") for root in (PRIVATE_ROOT, WORKER_ROOT))


def private_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Request-ID": str(uuid4())}


def private_failure(code: Code) -> JSONResponse:
    """No user fields, original exceptions, requested URL or credential can be echoed."""
    return JSONResponse(
        {"error": {"version": VERSION, "code": code.value,
                   "retry_class": "terminal", "transmission": "not_sent"}},
        status_code=HTTP_STATUS[code], headers=private_headers(),
    )


def closed_private_router(root: str, handler: Callable[[Request], Awaitable[Response]]) -> APIRouter:
    """All private paths/methods get fixed errors; no framework body parser."""
    from temper_ai.llm.single_send import metadata_only_logs
    from temper_ai.private_context.errors import PrivateDraftFailure

    router = APIRouter()

    async def handle(request: Request) -> Response:
        with metadata_only_logs():
            try:
                return await handler(request)
            except PrivateDraftFailure as exc:
                return private_failure(exc.code)
            except Exception:
                return private_failure(Code.CONTEXT_UNAVAILABLE)

    methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"]
    router.add_api_route(root, handle, methods=methods, include_in_schema=False)
    router.add_api_route(root + "/{rest:path}", handle, methods=methods, include_in_schema=False)
    return router
