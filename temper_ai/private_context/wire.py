"""Versioned, closed private-draft wire envelopes; no routes or registrations.

Untrusted bytes enter through decode_wire/decode_registration/decode_result,
not direct Pydantic constructors. Safe receipts contain only provisioned opaque
metadata; registration/result content lives exclusively in PrivateJSON.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from .errors import PrivateDraftErrorCode, PrivateDraftFailure
from .private_json import PrivateJSON, decode_object, encode_private

VERSION = "temper.private-draft.v1"
Version = Literal["temper.private-draft.v1"]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
PositiveInt = Annotated[int, Field(gt=0)]
NonnegativeInt = Annotated[int, Field(ge=0)]
Transmission = Literal["not_sent", "refused", "complete", "ambiguous"]
RetryClass = Literal["safe_pre_send", "explicit_refusal", "terminal"]


def _uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("identifier")
    return value


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("utc")
    return value


GeneratedID = Annotated[str, AfterValidator(_uuid)]
UTCTimestamp = Annotated[
    str,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"),
    AfterValidator(_utc),
]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    def __repr_args__(self) -> list[tuple[str | None, Any]]:
        return []


class ContextReceipt(ClosedModel):
    context_ref: GeneratedID
    context_version: PositiveInt
    expires_at: UTCTimestamp
    profile: Identifier


class PrivateContextDescriptor(ClosedModel):
    version: Version
    context_ref: GeneratedID
    context_version: PositiveInt


class PrivateRunInputs(ClosedModel):
    private_context: PrivateContextDescriptor


class PrivateRunStart(ClosedModel):
    workflow: Identifier
    inputs: PrivateRunInputs


class ContextRead(ClosedModel):
    context_ref: GeneratedID
    context_version: PositiveInt


class ResultRead(ClosedModel):
    context_ref: GeneratedID
    execution_id: GeneratedID
    draft_ref: GeneratedID


class DraftReceipt(ClosedModel):
    version: Version
    execution_id: GeneratedID
    draft_ref: GeneratedID
    state: Literal["ready"]
    expires_at: UTCTimestamp


class FailureReceipt(ClosedModel):
    version: Version
    code: PrivateDraftErrorCode
    retry_class: RetryClass
    transmission: Transmission
    call_id: GeneratedID | None = None
    attempt_id: GeneratedID | None = None
    next_eligible_at: UTCTimestamp | None = None

    @model_validator(mode="after")
    def applicable(self) -> FailureReceipt:
        if any(getattr(self, key) is None for key in self.model_fields_set
               if key in {"call_id", "attempt_id", "next_eligible_at"}):
            raise ValueError("omit inapplicable fields")
        if self.retry_class == "safe_pre_send" and self.transmission != "not_sent":
            raise ValueError("retry phase")
        if self.retry_class == "explicit_refusal" and self.transmission != "refused":
            raise ValueError("retry phase")
        if self.transmission in {"complete", "ambiguous"} and self.retry_class != "terminal":
            raise ValueError("terminal phase")
        return self


class ErrorResponse(ClosedModel):
    error: FailureReceipt


class AcknowledgedReceipt(ClosedModel):
    version: Version
    draft_ref: GeneratedID
    state: Literal["acknowledged"]


class RevokedReceipt(ClosedModel):
    context_ref: GeneratedID
    state: Literal["revoked"]


class ContextStatus(ClosedModel):
    context_ref: GeneratedID
    context_version: PositiveInt
    execution_id: GeneratedID | None
    state: Literal["registered", "bound", "running", "ready", "failed", "cancelled", "expired", "lost", "acknowledged"]
    receipt: DraftReceipt | None = None
    failure: FailureReceipt | None = None

    @model_validator(mode="after")
    def applicable(self) -> ContextStatus:
        fields = self.model_fields_set & {"receipt", "failure"}
        expected = {"receipt"} if self.state == "ready" else (
            {"failure"} if self.state in {"failed", "cancelled", "expired", "lost"} else set()
        )
        if fields != expected or ("receipt" in fields and self.receipt is None) or ("failure" in fields and self.failure is None):
            raise ValueError("status fields")
        if self.state == "registered" and self.execution_id is not None:
            raise ValueError("status execution")
        if self.state in {"bound", "running", "ready", "acknowledged"} and self.execution_id is None:
            raise ValueError("status execution")
        if self.receipt is not None and self.receipt.execution_id != self.execution_id:
            raise ValueError("receipt execution")
        return self


class _AvailableAttachment(ClosedModel):
    attachment_ref: Identifier
    message_ref: Identifier
    ordinal: NonnegativeInt
    status: Literal["available"]
    media_type: Literal["image/png"]
    data_base64: str
    decoded_bytes: PositiveInt
    width: PositiveInt
    height: PositiveInt
    preparation_version: Identifier


class _UnavailableAttachment(ClosedModel):
    attachment_ref: Identifier
    message_ref: Identifier
    ordinal: NonnegativeInt
    status: Literal["unavailable", "unsupported"]
    reason_code: Literal["missing", "decode_failed", "format_unsupported"]


_PreparedAttachment = Annotated[_AvailableAttachment | _UnavailableAttachment, Field(discriminator="status")]


class _Registration(ClosedModel):
    """Internal validation only; never returned to generic consumers."""
    version: Version
    profile: Identifier
    namespace: Identifier
    application_attempt_id: Identifier
    expires_at: UTCTimestamp
    context_schema: Identifier
    context: dict[str, Any]
    attachments: list[_PreparedAttachment]


class _Result(ClosedModel):
    version: Version
    execution_id: GeneratedID
    draft_ref: GeneratedID
    result_schema: Identifier
    draft: dict[str, Any]


WireModel = TypeVar("WireModel", bound=ClosedModel)


def decode_wire(raw: bytes, model: type[WireModel], *, code: PrivateDraftErrorCode = PrivateDraftErrorCode.CONTEXT_INVALID) -> WireModel:
    """Strict JSON preflight plus existing Pydantic strict validation; fixed errors only."""
    value = decode_object(raw, code)
    try:
        return model.model_validate_json(encode_private(value), strict=True)
    except (ValidationError, ValueError, TypeError, RecursionError):
        pass
    raise PrivateDraftFailure(code)


def receipt_dict(receipt: ContextReceipt | DraftReceipt | FailureReceipt | ErrorResponse | AcknowledgedReceipt | RevokedReceipt | ContextStatus) -> dict[str, Any]:
    """Ordinary metadata projection. Exclude unset union fields, not nullable execution_id."""
    if type(receipt) not in {ContextReceipt, DraftReceipt, FailureReceipt, ErrorResponse, AcknowledgedReceipt, RevokedReceipt, ContextStatus}:
        raise PrivateDraftFailure(PrivateDraftErrorCode.CONTEXT_INVALID)
    return receipt.model_dump(mode="json", exclude_unset=True)


class RegisterContext(PrivateJSON):
    __slots__ = ()

    def __init__(self, raw: bytes) -> None:
        decode_wire(raw, _Registration)
        super().__init__(raw)


class PrivateResult(PrivateJSON):
    __slots__ = ()

    def __init__(self, raw: bytes) -> None:
        decode_wire(raw, _Result, code=PrivateDraftErrorCode.OUTPUT_INVALID)
        super().__init__(raw)


def decode_registration(raw: bytes) -> RegisterContext:
    """Envelope only. App schema and shared PNG/body validation are separate mandatory stages.

    Auth must precede this call. It neither authorizes nor registers anything.
    """
    return RegisterContext(raw)


def decode_result(raw: bytes) -> PrivateResult:
    """Private result envelope only; validate draft with the source SchemaArtifact too."""
    return PrivateResult(raw)
