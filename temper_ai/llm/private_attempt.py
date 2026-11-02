"""Unused private native attempt adapter; no route registration or pool loop.

Consumes A's ports. Reuses the existing body builder, SDK client, transport,
control and raw-event reader. Only fixed phase/usage metadata leaves this module.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Literal

import anthropic

from temper_ai.agent.private_media import NativePrivateMedia
from temper_ai.llm import single_send as ss
from temper_ai.llm.models import LLMResponse
from temper_ai.llm.native_attempt import NativeObservation, send_native_once
from temper_ai.llm.providers.anthropic import (
    AnthropicLLM,
    _reset_epoch,
    _single_send_usage_never_raises,
)
from temper_ai.private_context.contracts import (
    AttemptOutcome,
    MediaCapability,
    NativeAttemptResult,
    NullableUsage,
    SendReservation,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import (
    PrivateJSON,
    decode_object,
    encode_private,
)
from temper_ai.private_context.wire import FailureReceipt, RegisterContext

Phase = Literal["before_reserve", "reserved", "http_refused", "streaming", "complete"]


def attempt_result(phase: Phase, *, started: bool = False, code: Code | None = None,
                   status: int | None = None, response: LLMResponse | None = None,
                   private: PrivateJSON | None = None) -> NativeAttemptResult:
    """Closed counters/counts only, never copy unknown usage names or values."""
    raw = (response.raw_response or {}) if response is not None else {}
    usage = raw.get("usage") or {}
    counters = {key: ss.counter(usage.get(key)) for key in ss.USAGE_COUNTERS}
    present = sum(value is not None for value in counters.values())
    fault = raw.get("usage_fault") or {}
    unknown = sum(len(fields) for fields in fault.get("unmodelled", {}).values())
    unknown += sum(fault.get("unmodelled_count", {}).values())
    transmission: Literal["not_sent", "ambiguous", "refused", "complete"] = {
        "before_reserve": "not_sent", "reserved": "ambiguous", "http_refused": "refused",
        "streaming": "ambiguous", "complete": "complete",
    }[phase]  # type: ignore[assignment]
    retry: Literal["safe_pre_send", "explicit_refusal", "terminal"] = "terminal"
    if phase == "before_reserve":
        retry = "safe_pre_send"
    elif phase == "http_refused" and status in (401, 403, 429, 529):
        retry = "explicit_refusal"
    failure = FailureReceipt(version="temper.private-draft.v1", code=code, transmission=transmission, retry_class=retry) if code else None
    return NativeAttemptResult(AttemptOutcome(
        phase=phase, transmission=transmission, request_started=started,
        usage=NullableUsage(**counters), usage_state="missing" if not present else ("known" if present == len(counters) else "partial"),
        unknown_usage_fields=unknown, http_status=status, failure=failure), private)


def failure_code(exc: Exception) -> Code:
    """Project fixed local identities, not provider prose or exception chains."""
    if type(exc) is PrivateDraftFailure:
        return exc.code
    if isinstance(exc, ss.SingleSendError):
        return {"cancel": Code.CANCELLED, "timeout": Code.CONTEXT_EXPIRED,
                "policy": Code.POLICY_DENIED, "truncation": Code.OUTPUT_TRUNCATED,
                "partial": Code.RESPONSE_PARTIAL}.get(exc.reason, Code.CONFIGURATION_INVALID)
    return Code.SEND_AMBIGUOUS


def prepare_private_request(provider: AnthropicLLM, request: PrivateJSON, *, context: RegisterContext,
                            capability: MediaCapability, media: NativePrivateMedia) -> PrivateJSON:
    """Shape once with the existing builder, validate before reserving anything.

    Input is {messages, model, max_tokens, [temperature, thinking,
    thinking_budget, effort]}. Output is a private SDK-create kwargs snapshot.
    Only the shaper may supply extra_headers. No user auth/provider overrides.
    """
    with ss.metadata_only_logs():
        media.validate_attachments(context, capability)
        if (type(provider) is not AnthropicLLM or provider.auth_mode != "oauth"
                or capability.provider != "anthropic" or provider._base_url is not None):
            raise PrivateDraftFailure(Code.POOL_ROUTE_UNAVAILABLE)
        value = request.open_private()
        if (set(value) - {"messages", "model", "max_tokens", "temperature", "thinking", "thinking_budget", "effort"}
                or not {"messages", "model", "max_tokens"} <= set(value)
                or ("thinking" in value and "thinking_budget" in value)
                or type(value["messages"]) is not list):
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        messages = value.pop("messages")
        # The shaper may add system framing, but may not alter/reorder selections
        # or their associated text. Verify native user blocks before AND after it.
        users = [message for message in messages if message.get("role") == "user"]
        if (len(users) != 1 or len(messages) not in (1, 2)
                or any(set(message) != {"role", "content"} for message in messages)
                or (len(messages) == 2 and messages[0].get("role") != "system")):
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        before = PrivateJSON(encode_private({"model": value["model"], "messages": users,
                                            "max_tokens": value["max_tokens"], "stream": True}))
        try:
            media.validate_final_body(before, capability)
            media.validate_selection(context, before)
        finally:
            before.close()
        original_users = encode_private({"messages": users})
        body = provider._build_single_send_kwargs(messages, **value)
        if encode_private({"messages": body.get("messages")}) != original_users:
            raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
        final = PrivateJSON(encode_private({**{k: v for k, v in body.items() if k != "extra_headers"}, "stream": True}))
        try:
            media.validate_final_body(final, capability)
        finally:
            final.close()
        return PrivateJSON(encode_private(body))


class PrivateAttemptControl(ss.SingleSendControl):
    """The existing one-send/deadline guard with a private, digest-free projection."""

    def __init__(self, deadline: float, guard: Callable[[], None], *, cancel_event: Any,
                 request: PrivateJSON, capability: MediaCapability, media: NativePrivateMedia) -> None:
        super().__init__(deadline, self._pre_send, cancel_event)
        self.guard = guard
        self.expected = request
        self.capability = capability
        self.media = media
        self.rejection_code: Code | None = None

    def _pre_send(self, metadata: dict[str, Any]) -> None:
        try:
            self.guard()  # normal policy and live custody fences, required from E
        except Exception as exc:  # noqa: BLE001 - keep only a fixed local identity
            self.rejection_code = failure_code(exc)
            raise

    def parse_request_metadata(self, raw: bytes) -> dict[str, Any]:
        try:
            self.media.validate_serialized_body(raw, self.capability)
            actual = decode_object(raw, Code.CONFIGURATION_INVALID)
            expected = self.expected.open_private()
            expected.pop("extra_headers", None)
            expected["stream"] = True
            if actual != expected:
                raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
            return {}  # no hashes, content-derived metadata or provider parameters
        except PrivateDraftFailure as exc:
            # The SDK wraps request-hook failures in APIConnectionError. Preserve
            # only our own pre-HTTP code, never inspect that exception's body.
            self.rejection_code = exc.code
            raise


def explicit_refusal(exc: Exception, observation: NativeObservation, control: ss.SingleSendControl) -> int | None:
    """Only a fully consumed non-200 HTTP refusal BEFORE a stream was opened.

    SSE errors after HTTP200, fake status attributes and truncated refusal bodies
    are ambiguous. Do not run safe_failure until this distinction is made.
    """
    if (not observation.stream_opened and len(control.transmission_ids) == 1
            and isinstance(exc, anthropic.APIStatusError)
            and exc.status_code in (400, 401, 403, 413, 429, 529)
            and exc.response.status_code == exc.status_code
            and exc.response.is_stream_consumed and exc.response.is_closed):
        return exc.status_code
    return None


class NativePooledAttempt:
    """Implements NativeAttempt; selected credential is volatile, never a receipt."""

    def __init__(self, provider: AnthropicLLM, *, selected_slot: int, credential: str) -> None:
        self.provider = provider
        self.selected_slot = selected_slot
        self._credential = credential
        self.cooldown_until: float | None = None

    def send_once(self, request: PrivateJSON, *, reservation: SendReservation,
                  control: ss.SingleSendControl, capability: MediaCapability) -> NativeAttemptResult:
        observation = NativeObservation()
        response = LLMResponse(content=None, model=capability.model, provider="anthropic")
        status = None
        code = None
        private = None
        with ss.metadata_only_logs():
            try:
                control.check()
                if (reservation.selected_slot != self.selected_slot
                        or not isinstance(control, PrivateAttemptControl)
                        or control.expected is not request or control.capability != capability):
                    raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)
                body = request.open_private()
                shared = self.provider._client_for(self._credential)
                send_native_once(shared, body, control, response, observation, _single_send_usage_never_raises)
                # Output parsing is terminal, never a reason to call a second model.
                private = PrivateJSON((response.content or "").encode("utf-8"))
            except Exception as exc:  # noqa: BLE001 - erase all raw exception/context data
                status = explicit_refusal(exc, observation, control)
                if status is not None:
                    code = {400: Code.CONFIGURATION_INVALID, 413: Code.PLATFORM_LIMIT,
                            401: Code.ACCOUNT_AUTH_REFUSED, 403: Code.ACCOUNT_AUTH_REFUSED,
                            429: Code.POOL_EXHAUSTED, 529: Code.SERVICE_REFUSED}[status]
                    if status == 429:
                        reset = _reset_epoch(exc)
                        self.cooldown_until = reset if reset is not None and math.isfinite(reset) else None
                elif (response.raw_response or {}).get("terminal_complete"):
                    code = Code.OUTPUT_TRUNCATED if isinstance(exc, ss.SingleSendError) and exc.reason == "truncation" else Code.OUTPUT_INVALID
                else:
                    code = failure_code(exc)
                    if isinstance(control, PrivateAttemptControl) and control.rejection_code is not None:
                        code = control.rejection_code
            finally:
                control.finish()
            started = bool(control.transmission_ids)
            phase: Phase = "reserved"
            if observation.stream_opened:
                phase = "complete" if (response.raw_response or {}).get("terminal_complete") else "streaming"
            elif status is not None:
                phase = "http_refused"
            if control.cleanup_uncertain or control.failure_reason:
                # A lost close/deadline may not authorize another attempt, even
                # when a status was observed before the failed cleanup.
                phase, status, code = "reserved", None, Code.SEND_AMBIGUOUS
            if code is not None and private is not None:
                private.close()
                private = None
            return attempt_result(phase, started=started, code=code, status=status, response=response, private=private)
