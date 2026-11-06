"""B stage: combined success first, then refusal/ambiguity/media/policy twins."""
from __future__ import annotations

import json
import time

import pytest

from temper_ai.llm import week_usage
from temper_ai.llm.single_send import SingleSendError
from temper_ai.private_context.errors import PrivateDraftErrorCode as Code
from temper_ai.private_context.private_json import PrivateJSON, encode_private
from tests.test_private_context import ipd1
from tests.test_private_context.ipd1 import require

from .private_pool_support import MODEL, Rig, deny, isolated  # noqa: F401

pytestmark = pytest.mark.usefixtures("isolated")


def test_whole_text_photos_refusal_pool_and_private_result(monkeypatch, caplog):
    for media in ("zero-png", "two-png"):
        rig = Rig(monkeypatch, media=media, schedule=(429, 200))
        result = rig.run()
        require(result.outcome.phase == "complete" and result.outcome.failure is None)
        private = result.open_private()
        require(private is not None and private.to_private_json() == ipd1.draft().to_private_json())
        require(rig.calls == 2 and rig.picks == 2 and rig.sent_slots == [0, 1])
        require(len(rig.custody.reservations) == len(rig.custody.outcomes) == len(rig.accounted) == 2)
        require(rig.accounted[0].phase == "http_refused" and rig.accounted[0].http_status == 429)
        require(all(row["selection"] and row["native_oauth"] and row["tools_absent"] for row in rig.safe_wire))
        require(all(row["temperature"] == "absent" for row in rig.safe_wire))
        order = [event for event in rig.custody.events if event != "guard"]
        require(order == ["reserve", "http", "finish", "account"] * 2)
        require(rig.provider._private_pool.cooling_until(rig.provider._private_pool.tokens[0], MODEL) is not None)
        rig.safe(result.outcome)
        result.close()
        require(result.open_private() is None)
    require(ipd1.scan({ipd1.Surface.EVENT: caplog.text}).clean)


@pytest.mark.parametrize("status", [401, 403, 429, 529])
def test_only_explicit_complete_refusal_retries(monkeypatch, status):
    rig = Rig(monkeypatch, schedule=(status, 200))
    result = rig.run()
    require(result.outcome.phase == "complete" and rig.calls == 2)
    require(rig.sent_slots == ([0, 0] if status == 529 else [0, 1]))
    require(rig.picks == (1 if status == 529 else 2))
    require(bool(rig.provider._private_pool._cooldown) == (status == 429))


def test_all_slots_refuse_once_and_overload_has_no_retry_count_cap(monkeypatch):
    refused = Rig(monkeypatch, count=3, schedule=(429,))
    result = refused.run()
    require(refused.calls == 3 and len(set(refused.sent_slots)) == 3)
    require(result.outcome.failure.code == Code.POOL_EXHAUSTED)
    overloaded = Rig(monkeypatch, count=3, schedule=(529,) * 10 + (200,))
    require(overloaded.run().outcome.failure is None)
    require(overloaded.calls == 11 and overloaded.picks == 1 and set(overloaded.sent_slots) == {0})
    require(not overloaded.provider._private_pool._cooldown)


@pytest.mark.parametrize("precooled", [True, False])
def test_pool_exhaustion_carries_existing_earliest_reset(monkeypatch, precooled):
    from datetime import datetime
    rig = Rig(monkeypatch, count=3, schedule=(429,))
    pool = rig.provider._private_pool
    if precooled:
        for index, token in enumerate(pool.tokens):
            pool.cool(token, until=time.time() + 100 + index, model=MODEL)
    result = rig.run()
    reset = pool.soonest_reset(MODEL)
    failure = result.outcome.failure
    require(failure.code == Code.POOL_EXHAUSTED and failure.next_eligible_at is not None)
    require(abs(datetime.fromisoformat(failure.next_eligible_at.replace("Z", "+00:00")).timestamp() - reset) < 0.00001)
    require(rig.calls == (0 if precooled else 3))
    rig.safe(result.outcome)


@pytest.mark.parametrize("reset", [None, float("nan"), float("inf"), 1e100])
def test_unusable_reset_is_omitted_not_invented(monkeypatch, reset):
    rig = Rig(monkeypatch, count=1)
    from temper_ai.llm.token_pool import PoolExhausted
    # Real picker constructs this error; malformed time handling is tested by
    # attaching the impossible timestamp AFTER its own safe message formatter.
    def exhausted(*args, **kwargs):
        error = PoolExhausted(1, None)
        error.reset_at = reset
        raise error
    monkeypatch.setattr(rig.provider._private_pool, "pick", exhausted)
    result = rig.run()
    require(result.outcome.failure.code == Code.POOL_EXHAUSTED and rig.calls == 0)
    require(result.outcome.failure.next_eligible_at is None)


@pytest.mark.parametrize("route", ["api-key", "base-url"])
def test_route_cannot_switch_provider_or_billing(monkeypatch, route):
    rig = Rig(monkeypatch)
    if route == "api-key":
        rig.provider.auth_mode = "api_key"
    else:
        rig.provider._base_url = "https://invalid.test"
    require(rig.run().outcome.failure is not None and rig.calls == 0 and not rig.custody.reservations)


@pytest.mark.parametrize("kind", ["missing", "null", "malformed"])
def test_usage_shape_never_costs_valid_draft(monkeypatch, kind):
    def usage(events):
        if kind == "missing":
            events[0]["message"].pop("usage")
        elif kind == "null":
            events[0]["message"]["usage"] = None
        else:
            events[0]["message"]["usage"]["input_tokens"] = ipd1.canaries()[3].decode()
        return events
    rig = Rig(monkeypatch, schedule=(usage,))
    result = rig.run()
    require(result.outcome.failure is None and result.open_private() is not None)
    require(result.outcome.usage_state == "missing" and rig.calls == 1)
    rig.safe(result.outcome)


@pytest.mark.parametrize("status", [400, 413, 500, 302])
def test_terminal_or_untrusted_http_does_not_retry(monkeypatch, status):
    rig = Rig(monkeypatch, schedule=(status, 200))
    result = rig.run()
    require(rig.calls == 1 and rig.picks == 1 and len(rig.accounted) == 1)
    require(result.outcome.phase == ("http_refused" if status in (400, 413) else "reserved"))
    require(result.outcome.failure.retry_class == "terminal")


@pytest.mark.parametrize("kind", ["rate_limit_error", "overloaded_error", "authentication_error"])
@pytest.mark.parametrize("partial", [False, True])
def test_same_status_sse_after_200_is_ambiguous(monkeypatch, kind, partial):
    def error(events):
        return (events[:3] if partial else []) + [{"type": "error", "error": {"type": kind, "message": ipd1.canaries()[3].decode() + " 429 529 401"}}]
    rig = Rig(monkeypatch, schedule=(error, 200))
    result = rig.run()
    require(rig.calls == 1 and rig.picks == 1)
    require(result.outcome.phase == "streaming" and result.outcome.transmission == "ambiguous")
    require(not rig.provider._private_pool._cooldown)
    rig.safe(result.outcome)


@pytest.mark.parametrize("mode", ["invalid", "empty", "truncated", "partial", "tool", "unknown-usage"])
def test_terminal_and_partial_answers_never_resend(monkeypatch, mode):
    def change(events):
        if mode == "invalid":
            events[2]["delta"]["text"] = ipd1.canaries()[3].decode()
        elif mode == "empty":
            events[2]["delta"]["text"] = ""
        elif mode == "truncated":
            events[4]["delta"]["stop_reason"] = "max_tokens"
        elif mode == "partial":
            events.pop()
        elif mode == "tool":
            events[1]["content_block"]["type"] = "tool_use"
        else:
            events[0]["message"]["usage"][ipd1.canaries()[3].decode()] = ipd1.canaries()[2].decode()
        return events
    rig = Rig(monkeypatch, schedule=(change, 200))
    result = rig.run()
    require(rig.calls == 1 and len(rig.accounted) == 1)
    if mode == "unknown-usage":
        require(result.outcome.failure is None and result.outcome.unknown_usage_fields == 1)
        require(result.outcome.usage.input_tokens == 10 and result.outcome.usage.total_tokens is None)
    else:
        require(result.outcome.failure is not None)
        require(result.outcome.phase == ("streaming" if mode in ("partial", "tool") else "complete"))
    rig.safe(result.outcome)


@pytest.mark.parametrize("phase", ["reserve", "finish", "account"])
def test_lost_durability_or_accounting_never_retries(monkeypatch, phase):
    rig = Rig(monkeypatch, schedule=(429, 200))
    if phase == "reserve":
        rig.custody.reserve_action = deny
    elif phase == "finish":
        rig.custody.finish_action = deny
    else:
        rig.account_action = deny
    result = rig.run()
    require(result.outcome.transmission == "ambiguous")
    require(rig.calls == (0 if phase == "reserve" else 1) and rig.picks == 1)
    require(not rig.provider._private_pool._cooldown)
    if phase == "finish":
        require(len(rig.accounted) == 1)
    rig.safe(result.outcome)


def test_singleton_is_real_picker_and_cools(monkeypatch):
    rig = Rig(monkeypatch, count=1, schedule=(429, 200))
    result = rig.run()
    require(len(rig.provider._private_pool) == 1)
    require(rig.picks == 2 and rig.calls == 1 and result.outcome.transmission == "refused")
    require(bool(rig.provider._private_pool._cooldown))


def test_zero_pool_cannot_fall_back_to_api_key_or_named_account(monkeypatch):
    rig = Rig(monkeypatch, count=0)
    rig.provider.api_key = "sk-ant-oat01-" + ipd1.canaries()[2].decode()
    rig.provider._client_for = deny
    result = rig.run()
    require(rig.calls == 0 and not rig.custody.reservations)
    require(result.outcome.failure.code == Code.POOL_UNAVAILABLE)


def test_week_usage_and_cooldown_still_decide_actual_picker(monkeypatch):
    rig = Rig(monkeypatch)
    week_usage.store().note("test-slot-0", "seven_day", .95, time.time() + 60)
    result = rig.run()
    require(result.outcome.failure is None and rig.sent_slots == [1])
    rig.provider._private_pool.cool(rig.provider._private_pool.tokens[1], model=MODEL)
    result = rig.run()
    require(result.outcome.failure is None and rig.sent_slots == [1, 0])


def test_auth_exclusion_is_only_for_this_invocation(monkeypatch):
    rig = Rig(monkeypatch, schedule=(401, 200))
    require(rig.run().outcome.phase == "complete")
    require(rig.run().outcome.phase == "complete")
    require(rig.sent_slots == [0, 1, 0] and not rig.provider._private_pool._cooldown)


@pytest.mark.parametrize("when", ["before", "reserved", "streaming", "between"])
def test_cancellation_never_sends_after_observation(monkeypatch, when):
    rig = Rig(monkeypatch, schedule=(429, 200) if when == "between" else (200,))
    if when == "before":
        rig.cancel.set()
    elif when == "reserved":
        rig.custody.reserve_action = rig.cancel.set
    elif when == "between":
        rig.custody.finish_action = rig.cancel.set
    else:
        rig.http_action = rig.cancel.set
    result = rig.run()
    require(rig.calls == (0 if when in ("before", "reserved") else 1))
    require(result.outcome.failure is not None)


def test_policy_rechecked_on_every_attempt_and_before_http(monkeypatch):
    rig = Rig(monkeypatch, schedule=(429, 200))
    def policy():
        if rig.calls:
            raise SingleSendError("policy")
    rig.guard_action = policy
    require(rig.run().outcome.failure is not None)
    require(rig.calls == 1 and len(rig.custody.reservations) == 1 and rig.guards >= 4)
    other = Rig(monkeypatch)
    other.custody.reserve_action = lambda: setattr(other, "guard_action", policy)
    require(other.run().outcome.transmission == "ambiguous" and other.calls == 0)


@pytest.mark.parametrize("field", ["lease_id", "execution_id", "invocation_id", "attempt_id", "selected_slot", "runner_generation", "deadline_at"])
def test_mismatched_reservation_never_sends(monkeypatch, field):
    rig = Rig(monkeypatch)
    reserve = rig.custody.reserve_send
    def changed(*args):
        row = reserve(*args)
        value = row.model_dump()[field]
        return row.model_copy(update={field: value + 1 if type(value) is int else "wrong"})
    rig.custody.reserve_send = changed
    from temper_ai.llm.private_attempt import NativePooledAttempt
    send_once = NativePooledAttempt.send_once
    entries = []
    def entered(self, *args, **kwargs):
        entries.append(True)
        return send_once(self, *args, **kwargs)
    monkeypatch.setattr(NativePooledAttempt, "send_once", entered)
    result = rig.run()
    require(result.outcome.transmission == "ambiguous" and rig.calls == 0 and not entries)


@pytest.mark.parametrize("field,value", [("revoked", True), ("expires_at", "2000-01-01T00:00:00Z"), ("deadline_at", "2000-01-01T00:00:00Z")])
def test_stale_binding_never_reserves(monkeypatch, field, value):
    rig = Rig(monkeypatch)
    rig.lease.binding = rig.lease.binding.model_copy(update={field: value})
    require(rig.run().outcome.failure is not None and not rig.custody.reservations and rig.calls == 0)


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True])
def test_missing_finite_deadline_is_configuration_failure(monkeypatch, deadline):
    rig = Rig(monkeypatch)
    require(rig.run(deadline_monotonic_s=deadline).outcome.failure.code == Code.CONFIGURATION_INVALID)
    require(not rig.custody.reservations)


def test_expired_invocation_never_reserves(monkeypatch):
    rig = Rig(monkeypatch)
    result = rig.run(deadline_monotonic_s=time.monotonic())
    require(result.outcome.failure.code == Code.CONTEXT_EXPIRED and not rig.custody.reservations)


@pytest.mark.parametrize("temperature", [None, 0.0, .7])
def test_explicit_temperature_is_preserved_and_never_relearned(monkeypatch, temperature):
    rig = Rig(monkeypatch, schedule=(400, 200))
    body = rig.request.open_private()
    if temperature is not None:
        body["temperature"] = temperature
    rig.request = PrivateJSON(encode_private(body))
    result = rig.run()
    require(rig.calls == 1 and result.outcome.failure.code == Code.CONFIGURATION_INVALID)
    require(rig.safe_wire[0]["temperature"] == ("absent" if temperature is None else temperature))


def test_missing_capability_and_synthetic_not_default(monkeypatch):
    rig = Rig(monkeypatch)
    rig.media.allow_synthetic = False
    require(rig.run().outcome.failure.code == Code.POOL_ROUTE_UNAVAILABLE and rig.calls == 0)
    require(rig.run(capability=None).outcome.failure.code == Code.POOL_ROUTE_UNAVAILABLE and rig.calls == 0)


def test_actual_final_wire_body_limit_includes_shaper(monkeypatch):
    def expand(body):
        return {**body, "system": ipd1.canaries()[0].decode() * 1000}
    rig = Rig(monkeypatch, transform=expand)
    result = rig.run()
    require(result.outcome.failure.code == Code.PLATFORM_LIMIT and rig.calls == 0)
    require(not rig.custody.reservations)


def test_final_serialized_bytes_not_decoded_image_sum(monkeypatch):
    rig = Rig(monkeypatch)
    # The unshaped request is small enough. Extra whitespace is real HTTP bytes.
    rig.capability = rig.capability.model_copy(update={"max_request_bytes": 2000})
    original = rig.client
    def inflated(control):
        client = original(control)
        def inflate(request):
            request._content = json.dumps(json.loads(request.content), indent=20).encode()
        client.event_hooks["request"].insert(0, inflate)
        return client
    monkeypatch.setattr("temper_ai.llm.single_send.new_http_client", inflated)
    result = rig.run()
    require(rig.calls == 0 and result.outcome.failure.code == Code.PLATFORM_LIMIT)


def test_actual_wire_must_match_the_prepared_snapshot(monkeypatch):
    rig = Rig(monkeypatch)
    original = rig.client
    def changed_client(control):
        client = original(control)
        def change(request):
            value = json.loads(request.content)
            value["messages"][0]["content"].pop()
            request._content = encode_private(value)
        client.event_hooks["request"].insert(0, change)
        return client
    monkeypatch.setattr("temper_ai.llm.single_send.new_http_client", changed_client)
    result = rig.run()
    require(result.outcome.failure is not None and result.outcome.failure.code == Code.CONFIGURATION_INVALID and rig.calls == 0)


@pytest.mark.parametrize("change", ["drop", "reverse", "text", "add-tools"])
def test_shaper_cannot_drop_reorder_or_detach_selection(monkeypatch, change):
    def transform(body):
        if change == "add-tools":
            body["tools"] = []
        elif change == "drop":
            body["messages"][0]["content"].pop()
        elif change == "reverse":
            body["messages"][0]["content"].reverse()
        else:
            body["messages"][0]["content"][1]["text"] = "other-association"
        return body
    rig = Rig(monkeypatch, transform=transform)
    require(rig.run().outcome.failure is not None and rig.calls == 0 and not rig.custody.reservations)
