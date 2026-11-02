"""Process-held authenticated worker transport; no key or content serialization.

E supplies the canonical server URL and existing run timeout. No redirects,
retries, environment credentials, anonymous fallback, or generic response prose.
Only explicit private accessors encode/decode content. This client is not custody:
server handles are always resolved through C1 on each operation.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

import httpx

from .contracts import (
    AttemptOutcome,
    PrivateBinding,
    PrivateLease,
    ReleaseDisposition,
    RunPrincipal,
    SendReservation,
)
from .errors import HTTP_STATUS, PrivateDraftFailure
from .errors import PrivateDraftErrorCode as Code
from .private_json import decode_object, encode_private
from .schema import ValidatedDraft
from .wire import DraftReceipt, ErrorResponse, decode_registration, decode_wire


class PrivateWorkerClient:
    __slots__ = ("_http", "_execution_id", "_generation")

    def __init__(self, *, server_url: str, execution_id: str, runner_generation: int,
                 timeout: httpx.Timeout, transport: httpx.BaseTransport | None = None) -> None:
        parsed = urlsplit(server_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        self._execution_id, self._generation = execution_id, runner_generation
        self._http = httpx.Client(base_url=server_url, follow_redirects=False, trust_env=False,
                                  timeout=timeout, transport=transport)

    def __repr__(self) -> str:
        return "<PrivateWorkerClient>"

    def __reduce_ex__(self, protocol):
        raise TypeError("private serialization forbidden")

    def close(self) -> None:
        from temper_ai.llm.single_send import metadata_only_logs

        with metadata_only_logs():
            try:
                self._http.close()
            except Exception:
                pass
            else:
                return
        raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)

    def _post(self, operation: str, body: dict) -> bytes:
        from temper_ai.api import run_tokens
        from temper_ai.api.private_responses import WORKER_ROOT
        from temper_ai.llm.single_send import metadata_only_logs

        path = WORKER_ROOT + "/" + operation
        if not run_tokens.PRIVATE_CONTEXT.opens(path):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        raw = run_tokens.held(self._execution_id, run_tokens.PRIVATE_CONTEXT)
        if raw is None:
            raise PrivateDraftFailure(Code.UNAUTHENTICATED)
        code = Code.CONTEXT_UNAVAILABLE
        with metadata_only_logs():
            try:
                response = self._http.post(path, content=encode_private(body),
                    headers={"Authorization": "Bearer " + raw, "Content-Type": "application/json"})
                if response.status_code == 200:
                    return response.content
                failure = decode_wire(response.content, ErrorResponse)
                if HTTP_STATUS[failure.error.code] == response.status_code:
                    code = failure.error.code
            except Exception:
                pass
        # No HTTPStatusError/transport/provider chain or response repr escapes.
        raise PrivateDraftFailure(code)

    def _check_lease(self, lease: PrivateLease) -> None:
        if (lease.binding.execution_id != self._execution_id
                or lease.binding.runner_generation != self._generation):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)

    def _ok(self, operation: str, body: dict) -> None:
        result = decode_object(self._post(operation, body))
        if result != {"ok": True}:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)

    def resolve(self, run_principal: RunPrincipal, execution_id: str, running_attempt: int,
                node_path: str, use: Literal["draft"] = "draft") -> PrivateLease:
        if (run_principal.execution_id != self._execution_id or execution_id != self._execution_id
                or run_principal.runner_generation != self._generation or running_attempt != self._generation):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        result = decode_object(self._post("acquire", {"node_path": node_path, "use": use}))
        if set(result) != {"lease_id", "binding", "context"}:
            raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
        from .worker_wire import LeaseHandle

        handle = decode_wire(encode_private({"lease_id": result["lease_id"]}), LeaseHandle)
        binding = decode_wire(encode_private(result["binding"]), PrivateBinding)
        lease = PrivateLease(lease_id=handle.lease_id, binding=binding,
                             context=decode_registration(encode_private(result["context"])))
        self._check_lease(lease)
        return lease

    def validate(self, lease: PrivateLease) -> None:
        self._check_lease(lease)
        self._ok("validate", {"lease_id": lease.lease_id})

    def reserve_send(self, lease: PrivateLease, invocation_id: str, attempt_id: str,
                     selected_slot: int) -> SendReservation:
        self._check_lease(lease)
        raw = self._post("reserve", dict(lease_id=lease.lease_id, invocation_id=invocation_id,
                                         attempt_id=attempt_id, selected_slot=selected_slot))
        reservation = decode_wire(raw, SendReservation)
        if (reservation.execution_id != self._execution_id
                or reservation.runner_generation != self._generation
                or reservation.lease_id != lease.lease_id
                or reservation.invocation_id != invocation_id or reservation.attempt_id != attempt_id
                or reservation.selected_slot != selected_slot):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return reservation

    def finish_attempt(self, reservation: SendReservation, outcome_metadata: AttemptOutcome) -> None:
        if (reservation.execution_id != self._execution_id
                or reservation.runner_generation != self._generation):
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        self._ok("finish", {"invocation_id": reservation.invocation_id,
                            "attempt_id": reservation.attempt_id,
                            "outcome": outcome_metadata.model_dump(mode="json", exclude_unset=True)})

    def publish(self, lease: PrivateLease, invocation_id: str, validated_result: ValidatedDraft) -> DraftReceipt:
        self._check_lease(lease)
        raw = self._post("publish", {"handle": {"lease_id": lease.lease_id, "invocation_id": invocation_id},
                                     "draft": validated_result.open_private()})
        receipt = decode_wire(raw, DraftReceipt)
        if receipt.execution_id != self._execution_id:
            raise PrivateDraftFailure(Code.SCOPE_DENIED)
        return receipt

    def release(self, lease: PrivateLease, disposition: ReleaseDisposition) -> None:
        self._check_lease(lease)
        try:
            self._ok("release", {"lease_id": lease.lease_id, "disposition": disposition})
        finally:
            lease.close()

    # This worker-only variant cannot acquire the named caller's powers.
    def register(self, *args, **kwargs):
        raise PrivateDraftFailure(Code.SCOPE_DENIED)

    bind = status = result = ack = delete = register
