"""Explicit unused pooled orchestration. No dispatch, configuration or default ports.

E must supply normal LLM policy/live custody checks and normal usage accounting;
C supplies durable reservation/finish. No callback is optional or default-success.
Only a durably recorded complete pre-stream refusal can lead to another send.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from temper_ai.agent.private_media import NativePrivateMedia
from temper_ai.llm import pi_logins
from temper_ai.llm import single_send as ss
from temper_ai.llm.private_attempt import (
    NativePooledAttempt,
    PrivateAttemptControl,
    attempt_result,
    failure_code,
    prepare_private_request,
)
from temper_ai.llm.providers.anthropic import AnthropicLLM, _stream_retry_delay
from temper_ai.llm.token_pool import PoolExhausted
from temper_ai.private_context.contracts import (
    AttemptOutcome,
    MediaCapability,
    NativeAttemptResult,
    PrivateContextService,
    PrivateLease,
    SendReservation,
)
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.errors import PrivateDraftFailure
from temper_ai.private_context.private_json import PrivateJSON


def invoke_private_pool(
    provider: AnthropicLLM, request: PrivateJSON, *, lease: PrivateLease,
    service: PrivateContextService, invocation_id: str, capability: MediaCapability,
    media: NativePrivateMedia, deadline_monotonic_s: float, cancel_event: Any,
    guard: Callable[[], None], account: Callable[[AttemptOutcome], None],
    sticky_key: str | None = None,
) -> NativeAttemptResult:
    """Return the final attempt; account receives EACH attempted outcome.

    `guard` must recheck the normal LLM_CALL policy plus live cancellation/custody
    fences. `account` must pair the normal per-attempt call/usage record without
    content. Neither callback receives messages, hashes or raw provider objects.
    NativeAttemptResult is volatile and must never enter generic event/results.
    """
    with ss.metadata_only_logs():
        prepared = None
        try:
            if type(deadline_monotonic_s) not in (int, float) or not math.isfinite(deadline_monotonic_s):
                raise PrivateDraftFailure(Code.CONFIGURATION_INVALID)

            def check() -> None:
                if cancel_event is not None and cancel_event.is_set():
                    raise PrivateDraftFailure(Code.CANCELLED)
                binding = lease.binding
                if binding.revoked:
                    raise PrivateDraftFailure(Code.CONTEXT_UNAVAILABLE)
                if (time.monotonic() >= deadline_monotonic_s - ss.SINGLE_CALL_CLEANUP_MARGIN_S
                        or time.time() >= min(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                                              for stamp in (binding.expires_at, binding.deadline_at))):
                    raise PrivateDraftFailure(Code.CONTEXT_EXPIRED)
                guard()

            check()
            pool = (provider.pool_now()
                    if type(provider) is AnthropicLLM and provider.auth_mode == "oauth"
                    and provider._private_pool is not None else None)
            if pool is None or not pool.tokens:
                return attempt_result("before_reserve", code=Code.POOL_UNAVAILABLE)
            prepared = prepare_private_request(provider, request, context=lease.open_private(), capability=capability, media=media)
            return _run_attempts(provider, prepared, pool=pool, lease=lease, service=service,
                                 invocation_id=invocation_id, capability=capability, media=media,
                                 deadline=deadline_monotonic_s, cancel_event=cancel_event,
                                 check=check, account=account, sticky_key=sticky_key)
        except Exception as exc:  # noqa: BLE001 - pre-reservation fixed failure only
            code = failure_code(exc)
        finally:
            if prepared is not None:
                prepared.close()
        return attempt_result("before_reserve", code=code)


def _run_attempts(provider: AnthropicLLM, request: PrivateJSON, *, pool: Any, lease: PrivateLease,
                  service: PrivateContextService, invocation_id: str, capability: MediaCapability,
                  media: NativePrivateMedia, deadline: float, cancel_event: Any,
                  check: Callable[[], None], account: Callable[[AttemptOutcome], None],
                  sticky_key: str | None) -> NativeAttemptResult:
    excluded: frozenset[str] = frozenset()
    credential = None
    overloads = 0
    last: NativeAttemptResult | None = None
    while True:
        try:
            check()
            if credential is None:
                credential = pool.pick(sticky_key, capability.model, exclude=excluded)
            selected_slot = pool.index_of(credential)
            control = PrivateAttemptControl(deadline, check, cancel_event=cancel_event,
                                            request=request, capability=capability, media=media)
            control.check()
            check()
            # The pool holds pi slot names; the slot's login comes from pi for this
            # attempt only, before any reservation. A slot whose login pi refuses is
            # left out of this invocation; a helper that can't be reached ends it
            # before_reserve. Either way nothing was sent.
            try:
                client = provider._client_for_slot(credential)
            except pi_logins.PiLoginRefused:
                excluded = excluded | {credential}
                credential = None
                continue
        except pi_logins.PiLoginsUnreachable:
            return last if last is not None else attempt_result("before_reserve", code=Code.POOL_UNAVAILABLE)
        except PoolExhausted as exc:
            exhausted = last if last is not None else attempt_result("before_reserve", code=Code.POOL_EXHAUSTED)
            # Existing picker metadata, not a probe or authorization to retry.
            # Keep the actual last refusal; only attach a known safe timestamp.
            reset = exc.reset_at
            if (reset is not None and type(reset) in (int, float) and math.isfinite(reset)
                    and exhausted.outcome.failure is not None):
                try:
                    stamp = datetime.fromtimestamp(reset, UTC).isoformat().replace("+00:00", "Z")
                    failure = exhausted.outcome.failure.model_copy(update={"next_eligible_at": stamp})
                    return NativeAttemptResult(exhausted.outcome.model_copy(update={"failure": failure}), None)
                except (ValueError, OverflowError, OSError):
                    pass
            return exhausted
        except Exception as exc:  # noqa: BLE001 - safe identity only
            code = failure_code(exc)
            return last if last is not None else attempt_result("before_reserve", code=code)
        # Reservation may have committed even if the reply is lost. Enter the
        # conservative boundary BEFORE invoking the durable service port.
        result = None
        try:
            attempt_id = str(uuid4())
            reservation = service.reserve_send(lease, invocation_id, attempt_id, selected_slot)
            if (type(reservation) is not SendReservation or reservation.lease_id != lease.lease_id
                    or reservation.execution_id != lease.binding.execution_id
                    or reservation.invocation_id != invocation_id or reservation.attempt_id != attempt_id
                    or reservation.selected_slot != selected_slot
                    or reservation.runner_generation != lease.binding.runner_generation
                    or reservation.deadline_at != lease.binding.deadline_at):
                raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
            attempt = NativePooledAttempt(provider, selected_slot=selected_slot, client=client)
            result = attempt.send_once(request, reservation=reservation, control=control, capability=capability)
            durable = True
            try:
                service.finish_attempt(reservation, result.outcome)
            except Exception:  # noqa: BLE001 - still account the attempted send
                durable = False
            account(result.outcome)
            if not durable:
                raise PrivateDraftFailure(Code.SEND_AMBIGUOUS)
        except Exception:  # noqa: BLE001 - no resend on reserve/finish/account uncertainty
            started = bool(control.transmission_ids)
            if result is not None:
                result.close()
            return attempt_result("reserved", started=started, code=Code.SEND_AMBIGUOUS)
        outcome = result.outcome
        if outcome.phase != "http_refused" or outcome.http_status not in (401, 403, 429, 529):
            return result
        last = result
        # The durable finish and normal accounting succeeded BEFORE any rotation,
        # cooldown or wait. Exception text is never a selection instruction.
        try:
            check()
            if outcome.http_status == 429:
                pool.cool(credential, until=attempt.cooldown_until, model=capability.model, reason="HTTP 429")
                credential = None
            elif outcome.http_status in (401, 403):
                excluded = excluded | {credential}
                credential = None
            else:
                # Existing 1,2,4,...60 + jitter backoff, same slot; only the
                # existing deadline/cancellation ends it, not an arbitrary cap.
                wait_until = time.monotonic() + _stream_retry_delay(min(overloads, 6))
                overloads += 1
                wake = cancel_event if cancel_event is not None else threading.Event()
                while time.monotonic() < wait_until:
                    check()
                    wake.wait(min(0.05, wait_until - time.monotonic()))
        except Exception:  # noqa: BLE001 - already refused, but no further send authorized
            return result
