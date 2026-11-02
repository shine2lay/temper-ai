"""Guard removal/loosening must fail its specific control, not just stay green."""
from __future__ import annotations

import inspect
import textwrap

import anthropic
import httpx
import pytest

from temper_ai.agent import private_media
from temper_ai.llm import private_attempt, private_pool, single_send, token_pool
from temper_ai.llm.native_attempt import NativeObservation
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from tests.test_private_context.ipd1 import require

from . import test_private_pool_attempts as cases
from .private_pool_support import Rig, isolated  # noqa: F401

pytestmark = pytest.mark.usefixtures("isolated")


def replace_guard(monkeypatch, module, owner, name, old, new):
    source = textwrap.dedent(inspect.getsource(getattr(owner, name)))
    require(source.count(old) == 1)
    namespace = dict(vars(module))
    exec(compile(source.replace(old, new), "<private-guard-bite>", "exec"), namespace)
    monkeypatch.setattr(owner, name, namespace[name])


def refusal_checks():
    control = single_send.SingleSendControl(1e12, lambda _: None)
    control.transmission_ids.append("synthetic")
    for opened, consumed, closed, wire_status, expected in [
        (False, True, True, 429, 429), (True, True, True, 429, None),
        (False, False, True, 429, None), (False, True, False, 429, None),
        (False, True, True, 200, None), (False, True, True, 529, None),
    ]:
        response = httpx.Response(wire_status, content=b"", request=httpx.Request("POST", "https://invalid.test"))
        response.is_stream_consumed, response.is_closed = consumed, closed
        exc = anthropic.APIStatusError("synthetic", response=response, body=None)
        exc.status_code = 429
        actual = private_attempt.explicit_refusal(exc, NativeObservation(stream_opened=opened), control)
        require(actual == expected)
    response = httpx.Response(429, content=b"", request=httpx.Request("POST", "https://invalid.test"))
    exc = anthropic.APIStatusError("synthetic", response=response, body=None)
    control.transmission_ids.clear()
    require(private_attempt.explicit_refusal(exc, NativeObservation(), control) is None)
    class StatusOnly(Exception):
        status_code = 429
    control.transmission_ids.append("synthetic")
    require(private_attempt.explicit_refusal(StatusOnly(), NativeObservation(), control) is None)


def test_trusted_refusal_phase_checks():
    refusal_checks()


@pytest.mark.parametrize("old,new", [
    ("not observation.stream_opened", "True"),
    ("len(control.transmission_ids) == 1", "True"),
    ("isinstance(exc, anthropic.APIStatusError)", "True"),
    ("exc.response.status_code == exc.status_code", "exc.response.status_code in (429, 529)"),
    ("exc.response.is_stream_consumed", "True"),
    ("exc.response.is_closed", "True"),
])
def test_each_explicit_refusal_predicate_bites(monkeypatch, old, new):
    replace_guard(monkeypatch, private_attempt, private_attempt, "explicit_refusal", old, new)
    bitten = False
    try:
        refusal_checks()
    except (AssertionError, AttributeError):
        bitten = True
    require(bitten)


def test_request_counter_guard_control(monkeypatch):
    rig = Rig(monkeypatch)
    prepared = private_attempt.prepare_private_request(rig.provider, rig.request, context=rig.context,
                                                       capability=rig.capability, media=rig.media)
    control = private_attempt.PrivateAttemptControl(1e12, rig.guard, cancel_event=None,
                                                    request=prepared, capability=rig.capability, media=rig.media)
    value = prepared.open_private()
    value.pop("extra_headers", None)
    value["stream"] = True
    denied = False
    try:
        for _ in range(2):
            control.request_start(httpx.Request("POST", "https://invalid.test", json=value))
    except single_send.SingleSendError as exc:
        denied = exc.reason == "retry"
    require(denied and len(control.transmission_ids) == 1)


@pytest.mark.parametrize("field,other", [
    ("lease_id", "lease.lease_id"), ("execution_id", "lease.binding.execution_id"),
    ("invocation_id", "invocation_id"), ("attempt_id", "attempt_id"),
    ("selected_slot", "selected_slot"), ("runner_generation", "lease.binding.runner_generation"),
    ("deadline_at", "lease.binding.deadline_at"),
])
def test_each_reservation_binding_guard_bites(monkeypatch, field, other):
    replace_guard(monkeypatch, private_pool, private_pool, "_run_attempts",
                  f"reservation.{field} != {other}", "False")
    with pytest.raises(AssertionError, match="contract"):
        cases.test_mismatched_reservation_never_sends(monkeypatch, field)


def test_existing_reset_projection_bites(monkeypatch):
    replace_guard(monkeypatch, private_pool, private_pool, "_run_attempts", "reset = exc.reset_at", "reset = None")
    with pytest.raises(AssertionError, match="contract"):
        cases.test_pool_exhaustion_carries_existing_earliest_reset(monkeypatch, True)


def test_request_counter_removal_bites(monkeypatch):
    replace_guard(monkeypatch, single_send, single_send.SingleSendControl, "request_start",
                  "if self.transmission_ids:", "if False:")
    with pytest.raises(AssertionError, match="contract"):
        test_request_counter_guard_control(monkeypatch)


@pytest.mark.parametrize("guard", ["finish", "account", "singleton", "body-bytes", "shaped-users", "selection", "wire-equality", "exclusion", "reserve"])
def test_orchestration_and_media_guard_bites(monkeypatch, guard):
    if guard in ("finish", "account", "singleton"):
        old, new = {"finish": ("service.finish_attempt(reservation, result.outcome)", "pass"),
                    "account": ("account(result.outcome)", "pass"),
                    "singleton": ("credential = pool.pick(sticky_key, capability.model, exclude=excluded)", "credential = pool.tokens[0]")}[guard]
        replace_guard(monkeypatch, private_pool, private_pool, "_run_attempts", old, new)
        run = (lambda: cases.test_singleton_is_real_picker_and_cools(monkeypatch)) if guard == "singleton" else (
            lambda: cases.test_lost_durability_or_accounting_never_retries(monkeypatch, guard))
    elif guard == "reserve":
        replace_guard(monkeypatch, private_pool, private_pool, "_run_attempts",
                      "service.reserve_send(lease, invocation_id, attempt_id, selected_slot)",
                      "SendReservation(lease_id=lease.lease_id, execution_id=lease.binding.execution_id, invocation_id=invocation_id, attempt_id=attempt_id, runner_generation=lease.binding.runner_generation, selected_slot=selected_slot, deadline_at=lease.binding.deadline_at)")
        def run():
            cases.test_lost_durability_or_accounting_never_retries(monkeypatch, "reserve")
    elif guard == "exclusion":
        replace_guard(monkeypatch, token_pool, token_pool.TokenPool, "pick", "if token not in exclude", "if True")
        def run():
            cases.test_only_explicit_complete_refusal_retries(monkeypatch, 401)
    elif guard == "wire-equality":
        replace_guard(monkeypatch, private_attempt, private_attempt.PrivateAttemptControl, "parse_request_metadata",
                      "if actual != expected:", "if False:")
        def run():
            cases.test_actual_wire_must_match_the_prepared_snapshot(monkeypatch)
    elif guard == "body-bytes":
        replace_guard(monkeypatch, private_media, private_media.NativePrivateMedia, "validate_serialized_body",
                      "if len(raw) > capability.max_request_bytes:", "if False:")
        def run():
            cases.test_final_serialized_bytes_not_decoded_image_sum(monkeypatch)
    elif guard == "shaped-users":
        replace_guard(monkeypatch, private_attempt, private_attempt, "prepare_private_request",
                      'if encode_private({"messages": body.get("messages")}) != original_users:', "if False:")
        monkeypatch.setattr(private_pool, "prepare_private_request", private_attempt.prepare_private_request)
        def run():
            cases.test_shaper_cannot_drop_reorder_or_detach_selection(monkeypatch, "reverse")
    else:
        replace_guard(monkeypatch, private_media, private_media.NativePrivateMedia, "validate_selection",
                      "if observed != expected:", "if False:")
        def run():
            rig = Rig(monkeypatch)
            value = rig.request.open_private()
            value["messages"][0]["content"].pop()
            rig.request = private_attempt.PrivateJSON(private_attempt.encode_private(value))
            result = rig.run()
            require(result.outcome.failure is not None and result.outcome.failure.code == Code.CONTEXT_INVALID and rig.calls == 0)
    bitten = False
    try:
        run()
    except AssertionError:
        bitten = True
    require(bitten)
