"""Closed private-draft failures. Never retain input, exceptions or provider prose."""
from enum import StrEnum
from types import MappingProxyType


class PrivateDraftErrorCode(StrEnum):
    UNAUTHENTICATED = "unauthenticated"
    SCOPE_DENIED = "scope_denied"
    CONTEXT_INVALID = "context_invalid"
    CONTEXT_CONFLICT = "context_conflict"
    CONTEXT_EXPIRED = "context_expired"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    CONTEXT_LOST = "context_lost"
    CONTEXT_ATTACHMENT_UNAVAILABLE = "context_attachment_unavailable"
    ATTACHMENT_UNSUPPORTED = "attachment_unsupported"
    PLATFORM_LIMIT = "platform_limit"
    POLICY_DENIED = "policy_denied"
    POOL_UNAVAILABLE = "pool_unavailable"
    POOL_ROUTE_UNAVAILABLE = "pool_route_unavailable"
    POOL_EXHAUSTED = "pool_exhausted"
    ACCOUNT_AUTH_REFUSED = "account_auth_refused"
    SERVICE_REFUSED = "service_refused"
    CONFIGURATION_INVALID = "configuration_invalid"
    SEND_AMBIGUOUS = "send_ambiguous"
    RESPONSE_PARTIAL = "response_partial"
    PROVIDER_REFUSED = "provider_refused"
    OUTPUT_INVALID = "output_invalid"
    OUTPUT_TRUNCATED = "output_truncated"
    RESULT_DELIVERY_FAILED = "result_delivery_failed"
    RESULT_LOST = "result_lost"
    CANCELLED = "cancelled"


HTTP_STATUS = MappingProxyType({
    PrivateDraftErrorCode.UNAUTHENTICATED: 401,
    PrivateDraftErrorCode.SCOPE_DENIED: 403,
    PrivateDraftErrorCode.CONTEXT_INVALID: 400,
    PrivateDraftErrorCode.CONTEXT_CONFLICT: 409,
    PrivateDraftErrorCode.CONTEXT_EXPIRED: 410,
    PrivateDraftErrorCode.CONTEXT_UNAVAILABLE: 503,
    PrivateDraftErrorCode.CONTEXT_LOST: 410,
    PrivateDraftErrorCode.CONTEXT_ATTACHMENT_UNAVAILABLE: 400,
    PrivateDraftErrorCode.ATTACHMENT_UNSUPPORTED: 400,
    PrivateDraftErrorCode.PLATFORM_LIMIT: 400,
    PrivateDraftErrorCode.POLICY_DENIED: 403,
    PrivateDraftErrorCode.POOL_UNAVAILABLE: 503,
    PrivateDraftErrorCode.POOL_ROUTE_UNAVAILABLE: 503,
    PrivateDraftErrorCode.POOL_EXHAUSTED: 503,
    PrivateDraftErrorCode.ACCOUNT_AUTH_REFUSED: 503,
    PrivateDraftErrorCode.SERVICE_REFUSED: 503,
    PrivateDraftErrorCode.CONFIGURATION_INVALID: 400,
    PrivateDraftErrorCode.SEND_AMBIGUOUS: 504,
    PrivateDraftErrorCode.RESPONSE_PARTIAL: 504,
    PrivateDraftErrorCode.PROVIDER_REFUSED: 422,
    PrivateDraftErrorCode.OUTPUT_INVALID: 422,
    PrivateDraftErrorCode.OUTPUT_TRUNCATED: 422,
    PrivateDraftErrorCode.RESULT_DELIVERY_FAILED: 503,
    PrivateDraftErrorCode.RESULT_LOST: 410,
    PrivateDraftErrorCode.CANCELLED: 409,
})
PRIVATE_RESPONSE_HEADERS = MappingProxyType({"Cache-Control": "no-store"})


class PrivateDraftFailure(Exception):
    """Only a fixed code; construct outside an except block to avoid retaining its context."""

    def __init__(self, code: PrivateDraftErrorCode) -> None:
        if type(code) is not PrivateDraftErrorCode:
            code = PrivateDraftErrorCode.CONTEXT_INVALID
        self.code = code
        super().__init__(code.value)
