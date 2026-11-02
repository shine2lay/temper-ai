"""Closed private HTTP routes. All bodies remain inside this explicit boundary.

No FastAPI body models, multipart spool, reflected validation, redirects, generic
logging or HTTP exception detail. Registration alone grants no access: the
server installs no production service/profile/authority in this change.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

from temper_ai.api.private_identity import verified_named_caller
from temper_ai.api.private_responses import (
    PRIVATE_ROOT,
    closed_private_router,
    private_headers,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import decode_object, encode_private
from temper_ai.private_context.runtime import (
    PrivateBoundary,
    authorize_scope,
    caller_boundary,
)
from temper_ai.private_context.wire import (
    AcknowledgedReceipt,
    ContextRead,
    ContextReceipt,
    ContextStatus,
    ResultRead,
    RevokedReceipt,
    decode_registration,
    decode_result,
    decode_wire,
)


async def read_private_json(request: Request) -> bytes:
    """Called ONLY after credential and configured-authority preflight.

    A JSON-only in-memory reader; there is deliberately no request.form() path.
    Existing authoritative capability checks own size limits; no invented TTL or
    provider/body quota is introduced here.
    """
    types = [value for key, value in request.scope.get("headers", [])
             if key.lower() == b"content-type"]
    if (len(types) != 1 or types[0].lower() not in {
            b"application/json", b"application/json; charset=utf-8"}
            or request.scope.get("query_string")):
        raise PrivateDraftFailure(Code.CONTEXT_INVALID)
    return await request.body()


def _metadata(value, model) -> Response:
    # Revalidate a service result instead of blindly encoding any dict/object it
    # happens to return. A faulty adapter cannot reflect arbitrary prose/fields.
    raw = encode_private(value.model_dump(mode="json", exclude_unset=True))
    result = decode_wire(raw, model)
    return JSONResponse(result.model_dump(mode="json", exclude_unset=True), headers=private_headers())


def create_private_router(boundary: Callable[[Request], PrivateBoundary | None]) -> APIRouter:
    """Factory for explicit injection in ASGI tests and future E composition."""
    async def handle(request: Request) -> Response:
        configured = caller_boundary(boundary(request))
        return await _handle(request, configured)

    return closed_private_router(PRIVATE_ROOT, handle)


async def _handle(request: Request, boundary: PrivateBoundary) -> Response:
    path, method = request.url.path, request.method
    def authorize(owner, namespace, profile):
        return authorize_scope(boundary, owner, namespace, profile)
    if method == "DELETE" and path.startswith(PRIVATE_ROOT + "/"):
        ref = path[len(PRIVATE_ROOT) + 1:]
        # Validate canonical UUID without reflecting a bad path or decoding a body.
        read = decode_wire(encode_private({"context_ref": ref, "context_version": 1}), ContextRead)
        if request.scope.get("query_string"):
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)
        caller = boundary.composition.caller_for_context(read.context_ref, authorize)
        return _metadata(boundary.service.delete(caller, read.context_ref), RevokedReceipt)
    if method != "POST" or path not in {
            PRIVATE_ROOT, PRIVATE_ROOT + "/status", PRIVATE_ROOT + "/result", PRIVATE_ROOT + "/ack"}:
        raise PrivateDraftFailure(Code.CONTEXT_INVALID)
    raw = await read_private_json(request)
    if path == PRIVATE_ROOT:
        # Envelope metadata chooses only among already-configured rights. Full
        # payload/schema interpretation happens AFTER exact namespace/profile check.
        envelope = decode_object(raw)
        namespace, profile = envelope.get("namespace"), envelope.get("profile")
        if type(namespace) is not str or type(profile) is not str:
            raise PrivateDraftFailure(Code.CONTEXT_INVALID)
        caller = authorize(verified_named_caller(), namespace, profile)
        context = decode_registration(raw)
        return _metadata(boundary.service.register(caller, context), ContextReceipt)
    if path.endswith("/status"):
        status_read = decode_wire(raw, ContextRead)
        caller = boundary.composition.caller_for_context(status_read.context_ref, authorize)
        return _metadata(boundary.service.status(caller, status_read), ContextStatus)
    result_read = decode_wire(raw, ResultRead)
    caller = boundary.composition.caller_for_context(result_read.context_ref, authorize)
    if path.endswith("/ack"):
        return _metadata(boundary.service.ack(caller, result_read), AcknowledgedReceipt)
    result = boundary.service.result(caller, result_read)
    # This is the ONLY draft-bearing application response. Never return it via a
    # generic run/model/export endpoint. Strict wire validation stays private.
    private = decode_result(result.to_private_json())
    return Response(private.to_private_json(), media_type="application/json", headers=private_headers())
