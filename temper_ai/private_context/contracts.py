"""Shared service/attempt/media ports. Implementations arrive separately.

Nothing here authenticates a caller, reserves a send, starts a run or registers
a profile. Constructors are not credentials. C owns atomic custody/fences; B
owns one native attempt/media checks; E alone wires the graph runtime.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, SupportsIndex

from pydantic import model_validator

from .errors import PrivateDraftErrorCode as Code
from .errors import PrivateDraftFailure
from .private_json import PrivateJSON
from .schema import ValidatedDraft
from .wire import (
    AcknowledgedReceipt,
    ClosedModel,
    ContextRead,
    ContextReceipt,
    ContextStatus,
    DraftReceipt,
    FailureReceipt,
    GeneratedID,
    Identifier,
    NonnegativeInt,
    PositiveInt,
    PrivateResult,
    RegisterContext,
    ResultRead,
    RevokedReceipt,
    Transmission,
    UTCTimestamp,
)

if TYPE_CHECKING:
    from temper_ai.llm.single_send import SingleSendControl


class CallerPrincipal(ClosedModel):
    """Produced ONLY after named-key verification; text/this object alone is not authority."""
    principal_id: Identifier
    namespace: Identifier
    profile: Identifier
    provenance: Literal["verified_named_key"]


class RunPrincipal(ClosedModel):
    """Produced ONLY by verification of the exact-scope private worker key."""
    execution_id: GeneratedID
    runner_generation: PositiveInt
    provenance: Literal["verified_private_worker_key"]


class PrivateBinding(ClosedModel):
    """Durable metadata ONLY; never content, content digest or a bearer credential.

    Generation is the monotonic running-attempt number. Every resolve, reserve,
    finish and publish must compare it atomically against current runner state.
    expires_at is application validity; deadline_at is the existing run deadline,
    not a new budget. Revocation and either deadline prohibit later publication.
    A reservation is possible-send evidence even with request_started=False.
    """
    context_ref: GeneratedID
    context_version: PositiveInt
    execution_id: GeneratedID
    owner_principal: Identifier
    namespace: Identifier
    profile: Identifier
    profile_revision: Identifier
    context_schema: Identifier
    result_schema: Identifier
    schema_revision: Identifier
    workflow: Identifier
    workflow_revision: Identifier
    node_path: Identifier
    use: Literal["draft"]
    expires_at: UTCTimestamp
    deadline_at: UTCTimestamp
    runner_generation: PositiveInt
    revoked: bool
    attempt_state: Literal["unreserved", "reserved", "refused", "complete", "ambiguous"]
    outcome: AttemptOutcome | None = None


class NullableUsage(ClosedModel):
    input_tokens: NonnegativeInt | None
    output_tokens: NonnegativeInt | None
    total_tokens: NonnegativeInt | None
    cache_read_input_tokens: NonnegativeInt | None
    cache_creation_input_tokens: NonnegativeInt | None


class AttemptOutcome(ClosedModel):
    """Closed metadata. No provider text, headers, unknown usage values or hashes."""
    phase: Literal["before_reserve", "reserved", "http_refused", "streaming", "complete"]
    transmission: Transmission
    request_started: bool
    usage: NullableUsage
    usage_state: Literal["known", "missing", "partial"]
    unknown_usage_fields: NonnegativeInt
    http_status: NonnegativeInt | None = None
    failure: FailureReceipt | None = None

    @model_validator(mode="after")
    def phase_matches(self) -> AttemptOutcome:
        expected = {"before_reserve": "not_sent", "reserved": "ambiguous", "http_refused": "refused", "streaming": "ambiguous", "complete": "complete"}
        if self.transmission != expected[self.phase]:
            raise ValueError("outcome phase")
        if self.phase == "before_reserve" and self.request_started:
            raise ValueError("before reserve")
        if self.phase in {"http_refused", "streaming", "complete"} and not self.request_started:
            raise ValueError("request observation")
        if (self.http_status is not None) != (self.phase == "http_refused"):
            raise ValueError("http refusal phase")
        if self.http_status is not None and self.http_status not in {400, 401, 403, 413, 429, 529}:
            raise ValueError("http refusal status")
        if self.failure is not None and self.failure.transmission != self.transmission:
            raise ValueError("failure phase")
        counters = tuple(self.usage.model_dump().values())
        if self.usage_state == "missing" and any(value is not None for value in counters):
            raise ValueError("missing usage")
        if self.usage_state == "known" and any(value is None for value in counters):
            raise ValueError("known usage")
        if self.usage_state == "partial" and not (any(value is None for value in counters) and any(value is not None for value in counters)):
            raise ValueError("partial usage")
        return self


# Resolve the metadata-only forward reference after AttemptOutcome exists.
PrivateBinding.model_rebuild()


class SendReservation(ClosedModel):
    lease_id: GeneratedID
    execution_id: GeneratedID
    invocation_id: GeneratedID
    attempt_id: GeneratedID
    runner_generation: PositiveInt
    selected_slot: NonnegativeInt
    deadline_at: UTCTimestamp


class _Volatile:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private serialization forbidden")


class PrivateLease(_Volatile):
    """In-memory private context; do not place in ExecutionContext/results/events.

    Closing drops this holder's content reference; service revocation remains
    authoritative even if a worker already obtained a private copy.
    """
    __slots__ = ("lease_id", "binding", "__context")

    def __init__(self, *, lease_id: str, binding: PrivateBinding, context: RegisterContext) -> None:
        self.lease_id = lease_id
        self.binding = binding
        self.__context: RegisterContext | None = context

    def open_private(self) -> RegisterContext:
        if self.__context is None:
            raise PrivateDraftFailure(Code.CONTEXT_LOST)
        return self.__context

    def close(self) -> None:
        if self.__context is not None:
            self.__context.close()
        self.__context = None


ReleaseDisposition = Literal["completed", "failed", "cancelled", "expired", "revoked", "lost"]


class PrivateContextService(Protocol):
    """Atomic authenticated service. All method rights are exact, never prefix matching.

    Register retries compare bytes only while buffer exists; lost buffers are
    context_lost. bind retry returns the existing execution; never dispatch twice.
    resolve checks principal/execution/generation/node/use, revocation and both
    deadlines BEFORE fetching. reserve_send is durable CAS before each possible
    HTTP send; uncertainty denies sends. finish_attempt must durably record a
    complete refusal before reselection. publish rechecks every fence atomically
    and validates the source schema. No post-reservation automatic regeneration.
    result rereads until ack/expiry. ack/delete/cancel independently drop volatile
    buffers, preserve safe metadata, never retract delivery or a provider send.
    """
    def register(self, caller: CallerPrincipal, context: RegisterContext) -> ContextReceipt: ...
    def bind(self, caller: CallerPrincipal, context_ref: str, context_version: int, execution_id: str, profile_revision: str) -> PrivateBinding: ...
    def status(self, caller: CallerPrincipal, context: ContextRead) -> ContextStatus: ...
    def result(self, caller: CallerPrincipal, read: ResultRead) -> PrivateResult: ...
    def ack(self, caller: CallerPrincipal, read: ResultRead) -> AcknowledgedReceipt: ...
    def delete(self, caller: CallerPrincipal, context_ref: str) -> RevokedReceipt: ...
    def resolve(self, run_principal: RunPrincipal, execution_id: str, running_attempt: int, node_path: str, use: Literal["draft"] = "draft") -> PrivateLease: ...
    def reserve_send(self, lease: PrivateLease, invocation_id: str, attempt_id: str, selected_slot: int) -> SendReservation: ...
    def finish_attempt(self, reservation: SendReservation, outcome_metadata: AttemptOutcome) -> None: ...
    def publish(self, lease: PrivateLease, invocation_id: str, validated_result: ValidatedDraft) -> DraftReceipt: ...
    def release(self, lease: PrivateLease, disposition: ReleaseDisposition) -> None: ...


class MediaCapability(ClosedModel):
    """Explicit versioned provider/model authority; no engine numerical defaults.

    SYNTHETIC-P2 values are test design, not facts about any provider/model.
    Final body size includes OAuth shaping. No truncation, URL/file fetch,
    collage, dropped selection or hidden downscale is allowed.
    """
    profile: Identifier
    revision: Identifier
    source_kind: Literal["authoritative", "synthetic"]
    provider: Identifier
    model: Identifier
    max_images: NonnegativeInt
    max_image_bytes: PositiveInt
    max_width: PositiveInt
    max_height: PositiveInt
    max_request_bytes: PositiveInt


class PrivateMedia(Protocol):
    """B extends the existing PNG validator; never implement a second parser."""
    def validate_attachments(self, context: RegisterContext, capability: MediaCapability) -> None: ...
    def validate_final_body(self, body: PrivateJSON, capability: MediaCapability) -> None: ...


class NativeAttemptResult(_Volatile):
    __slots__ = ("outcome", "__response")

    def __init__(self, outcome: AttemptOutcome, response: PrivateJSON | None) -> None:
        self.outcome = outcome
        self.__response = response

    def open_private(self) -> PrivateJSON | None:
        return self.__response

    def close(self) -> None:
        if self.__response is not None:
            self.__response.close()
        self.__response = None


class NativeAttempt(Protocol):
    """Exactly one native request, no SDK retries/redirects/fallback/tools/exports.

    Existing SingleSendControl carries policy, cancellation and deadline for
    EACH attempt. Complete pre-stream refusals are distinct from an SSE error
    after success: the latter is ambiguous, even when its text mentions 429.
    Old named-token mode remains unchanged and at most one send.
    """
    def send_once(self, request: PrivateJSON, *, reservation: SendReservation, control: SingleSendControl, capability: MediaCapability) -> NativeAttemptResult: ...


class PrivateExecution(_Volatile):
    """Type-only runtime seam: service + verified run principal, NEVER a lease/body.

    E may populate this after shared binding/auth; A registers no consumer.
    Ordinary ExecutionContext construction and replacement remain unchanged.
    """
    __slots__ = ("service", "principal")

    def __init__(self, service: PrivateContextService, principal: RunPrincipal) -> None:
        self.service = service
        self.principal = principal
