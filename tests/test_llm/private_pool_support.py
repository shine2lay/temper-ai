"""Offline B rig: real picker/SDK/PNG reader, fake custody and HTTP only."""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from temper_ai.agent.private_media import NativePrivateMedia
from temper_ai.llm import pi_logins, shared_cooldowns, single_send, week_usage
from temper_ai.llm.private_pool import invoke_private_pool
from temper_ai.llm.providers.anthropic import AnthropicLLM
from temper_ai.private_context.contracts import (
    PrivateBinding,
    PrivateLease,
    SendReservation,
)
from temper_ai.private_context.private_json import PrivateJSON, encode_private
from temper_ai.private_context.wire import decode_registration
from tests.test_agent.test_llm_image_input import encode, event_list
from tests.test_private_context import ipd1
from tests.test_private_context.ipd1 import require

MODEL = "claude-opus-synthetic"


def deny(*args, **kwargs):
    raise AssertionError("forbidden offline contact")


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr("anthropic._base_client.get_platform", lambda: "Linux")
    monkeypatch.setattr(shared_cooldowns, "for_tokens", lambda *args: {})
    monkeypatch.setattr(shared_cooldowns, "push", lambda *args: None)
    monkeypatch.setattr(week_usage, "_store", week_usage.WeekUsage(None))
    monkeypatch.setattr(week_usage, "week_line", lambda *args: 0.9)
    # Trap generic result/event/accounting paths: B must return only its port.
    monkeypatch.setattr("temper_ai.database.engine.create_app_engine", deny)
    monkeypatch.setattr(AnthropicLLM, "_send", deny)
    monkeypatch.setattr(AnthropicLLM, "_call_with_pool", deny)
    monkeypatch.setattr("temper_ai.llm.private_pool._stream_retry_delay", lambda attempt: 0)


class FakeCustody:
    """TEST ONLY: records port ordering, not production authorization evidence."""

    def __init__(self):
        self.events = []
        self.reservations = []
        self.outcomes = []
        self.reserve_action = None
        self.finish_action = None

    def reserve_send(self, lease, invocation_id, attempt_id, selected_slot):
        self.events.append("reserve")
        row = SendReservation(lease_id=lease.lease_id, execution_id=lease.binding.execution_id,
                              invocation_id=invocation_id, attempt_id=attempt_id,
                              runner_generation=lease.binding.runner_generation, selected_slot=selected_slot,
                              deadline_at=lease.binding.deadline_at)
        self.reservations.append(row)
        if self.reserve_action:
            self.reserve_action()
        return row

    def finish_attempt(self, reservation, outcome):
        self.events.append("finish")
        if self.finish_action:
            self.finish_action()
        self.outcomes.append(outcome)


def binding():
    return PrivateBinding(context_ref=ipd1.REF, context_version=1, execution_id=ipd1.RUN,
                          owner_principal="test-owner", namespace="scope-1", profile="synthetic-reply-v1",
                          profile_revision="synthetic-v1", context_schema="synthetic.ipd-context.v1",
                          result_schema="synthetic.ipd-draft.v1", schema_revision="synthetic-v1",
                          workflow="synthetic", workflow_revision="synthetic-v1", node_path="draft", use="draft",
                          expires_at=ipd1.EXPIRY, deadline_at=ipd1.EXPIRY, runner_generation=1,
                          revoked=False, attempt_state="unreserved")


class Rig:
    def __init__(self, monkeypatch, *, count=2, media="two-png", schedule=(200,), transform=None):
        self.custody = FakeCustody()
        self.cancel = threading.Event()
        self.context = decode_registration(ipd1.registration(media).to_private_json())
        self.lease = PrivateLease(lease_id=ipd1.REF, binding=binding(), context=self.context)
        self.capability = ipd1.capability().model_copy(update={"provider": "anthropic", "model": MODEL})
        self.media = NativePrivateMedia(allow_synthetic=True)
        self.calls = self.picks = self.guards = 0
        self.accounted = []
        self.safe_wire = []
        self.sent_slots = []
        self.schedule = list(schedule)
        self.transform = transform
        self.guard_action = None
        self.account_action = None
        self.http_action = None
        self.tokens = ["sk-ant-oat01-" + ipd1.canaries()[2].decode() + str(i) for i in range(count)]
        slots = ["test-slot-" + str(i) for i in range(count)]
        logins = dict(zip(slots, self.tokens, strict=True))
        monkeypatch.setattr(pi_logins, "configured_slots", lambda: list(slots))
        monkeypatch.setattr(pi_logins, "fetch", lambda slot, call_seconds=None: logins[slot])
        self.provider = AnthropicLLM(model=MODEL)
        if self.provider._private_pool is not None:
            self.provider._private_pool._default_slot = 0
            pick = self.provider._private_pool.pick
            def counted(*args, **kwargs):
                self.picks += 1
                return pick(*args, **kwargs)
            monkeypatch.setattr(self.provider._private_pool, "pick", counted)
        monkeypatch.setattr("temper_ai.llm.providers.anthropic.get_oauth_shaper", lambda: SimpleNamespace(
            shape=self.shape, client_headers=lambda: {}))
        monkeypatch.setattr(single_send, "new_http_client", self.client)
        blocks = [{"type": "text", "text": ipd1.canaries()[0].decode()}]
        for item in self.context.open_private()["attachments"]:
            if item["status"] == "available":
                blocks.extend([{"type": "text", "text": item["message_ref"] + "/" + item["attachment_ref"]},
                               {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": item["data_base64"]}}])
        self.request = PrivateJSON(encode_private({"model": MODEL, "max_tokens": 100,
                                                   "messages": [{"role": "user", "content": blocks}]}))

    def shape(self, body):
        return self.transform(body) if self.transform else body

    def client(self, control):
        return httpx.Client(transport=httpx.MockTransport(self.handle), timeout=control.remaining(),
                            trust_env=False, follow_redirects=False, event_hooks={"request": [control.request_start]})

    def handle(self, request):
        self.custody.events.append("http")
        self.calls += 1
        body = json.loads(request.content)
        attachments = self.context.open_private()["attachments"]
        images = [block["source"]["data"] for message in body["messages"] for block in message["content"] if block["type"] == "image"]
        self.safe_wire.append({"selection": images == [item["data_base64"] for item in attachments],
                               "temperature": body.get("temperature", "absent"), "tools_absent": "tools" not in body,
                               "native_oauth": request.headers.get("authorization", "").startswith("Bearer sk-ant-oat01-") and "x-api-key" not in request.headers})
        self.sent_slots.append(self.tokens.index(request.headers["authorization"][7:]))
        logging.getLogger("httpx").warning("%s", ipd1.canaries()[3].decode())
        if self.http_action:
            self.http_action()
        step = self.schedule[min(self.calls - 1, len(self.schedule) - 1)]
        if type(step) is int and step != 200:
            return httpx.Response(step, json={"type": "error", "error": {"type": "overloaded_error", "message": ipd1.canaries()[3].decode()}}, headers={"retry-after": "60"})
        events = event_list(answer=ipd1.draft().to_private_json().decode())
        if callable(step):
            events = step(events)
        return httpx.Response(200, content=encode(events), headers={"content-type": "text/event-stream"})

    def guard(self):
        self.guards += 1
        self.custody.events.append("guard")
        if self.guard_action:
            self.guard_action()

    def account(self, outcome):
        self.custody.events.append("account")
        if self.account_action:
            self.account_action()
        self.accounted.append(outcome)

    def run(self, **overrides):
        kwargs = dict(lease=self.lease, service=self.custody, invocation_id=ipd1.ATTEMPT,
                      capability=self.capability, media=self.media, deadline_monotonic_s=time.monotonic() + 60,
                      cancel_event=self.cancel, guard=self.guard, account=self.account)
        return invoke_private_pool(self.provider, self.request, **{**kwargs, **overrides})

    def safe(self, outcome):
        surfaces = {ipd1.Surface.EVENT: json.dumps([row.model_dump(mode="json") for row in self.accounted]),
                    ipd1.Surface.ERROR: repr(outcome), ipd1.Surface.EXPORT: outcome.model_dump_json()}
        require(ipd1.scan(surfaces).clean)
