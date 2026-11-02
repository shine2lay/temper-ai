"""Authenticated process transport; server custody is resolved, never reconstructed."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

from temper_ai.api.auth import strict_header_key
from temper_ai.api.private_contexts import _metadata, read_private_json
from temper_ai.api.private_responses import (
    WORKER_ROOT,
    closed_private_router,
    private_headers,
)
from temper_ai.api.private_worker_keys import verified_worker_request
from temper_ai.api.run_tokens import PRIVATE_CONTEXT
from temper_ai.database import get_session
from temper_ai.private_context.contracts import SendReservation
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import decode_object, encode_private
from temper_ai.private_context.runtime import PrivateBoundary, require_boundary
from temper_ai.private_context.wire import DraftReceipt, decode_wire
from temper_ai.private_context.worker_wire import (
    AcquireLease,
    FinishAttempt,
    LeaseHandle,
    PublishDraft,
    ReleaseLease,
    ReserveSend,
)


def create_worker_router(boundary: Callable[[Request], PrivateBoundary | None]) -> APIRouter:
    async def handle(request: Request) -> Response:
        with verified_worker_request(strict_header_key(request.scope)) as principal:
            configured = require_boundary(boundary(request))
            if request.method != "POST" or not PRIVATE_CONTEXT.opens(request.url.path):
                raise PrivateDraftFailure(Code.SCOPE_DENIED)
            with get_session() as session:
                authority = configured.composition.worker_current_in(session, principal)
            # Both key and fenced current configured authority precede body read.
            raw = await read_private_json(request)
            operation = request.url.path.removeprefix(WORKER_ROOT + "/")
            service, composition = configured.service, configured.composition
            if operation == "acquire":
                wanted = decode_wire(raw, AcquireLease)
                if wanted.node_path != authority.profile.node_path or wanted.use != "draft":
                    raise PrivateDraftFailure(Code.SCOPE_DENIED)
                lease = service.resolve(principal, principal.execution_id,
                                        principal.runner_generation, wanted.node_path, wanted.use)
                # Only this authenticated process response carries context bytes.
                # The server keeps the authoritative lease for subsequent handles.
                wire = {"lease_id": lease.lease_id,
                        "binding": lease.binding.model_dump(mode="json", exclude_unset=True),
                        "context": lease.open_private().open_private()}
                return Response(encode_private(wire), media_type="application/json",
                                headers=private_headers())
            if operation == "finish":
                finish = decode_wire(raw, FinishAttempt)
                reservation = composition.worker_reservation(principal, finish.invocation_id, finish.attempt_id)
                service.finish_attempt(reservation, finish.outcome)
                return JSONResponse({"ok": True}, headers=private_headers())
            if operation == "publish":
                # Payload is never a Pydantic request field or a generic return.
                envelope = decode_object(raw)
                if set(envelope) != {"handle", "draft"}:
                    raise PrivateDraftFailure(Code.CONTEXT_INVALID)
                publish = decode_wire(encode_private(envelope["handle"]), PublishDraft)
                lease = composition.worker_lease(principal, publish.lease_id)
                validated = authority.profile.schema.validate_draft(encode_private(envelope["draft"]))
                receipt = service.publish(lease, publish.invocation_id, validated)
                return _metadata(receipt, DraftReceipt)
            if operation == "reserve":
                reserve = decode_wire(raw, ReserveSend)
                lease = composition.worker_lease(principal, reserve.lease_id)
                reservation = service.reserve_send(lease, reserve.invocation_id, reserve.attempt_id,
                                                   reserve.selected_slot)
                return _metadata(reservation, SendReservation)
            if operation == "release":
                release = decode_wire(raw, ReleaseLease)
                lease = composition.worker_lease(principal, release.lease_id)
                service.release(lease, release.disposition)
            else:
                handle = decode_wire(raw, LeaseHandle)
                composition.worker_lease(principal, handle.lease_id)
            return JSONResponse({"ok": True}, headers=private_headers())

    return closed_private_router(WORKER_ROOT, handle)
