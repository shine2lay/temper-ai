"""Opt-in PNG entrypoint proof; only booleans/metadata escape fake boundaries."""
from __future__ import annotations

import base64
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import zlib
from dataclasses import asdict
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from temper_ai.agent import create_agent
from temper_ai.agent.llm_agent import LLMAgent
from temper_ai.llm import single_send
from temper_ai.llm.providers.anthropic import AnthropicLLM
from temper_ai.llm.token_pool import NamedToken
from temper_ai.observability import EventType
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig

TEXT = "SYNTHETIC_PRIVATE_IMAGE_TASK"
SYSTEM = "SYNTHETIC_PRIVATE_IMAGE_SYSTEM"
ANSWER = '{"verdict":"ok"}'
NOT_SENT = "not sent"


def png_bytes(width=1, height=1, pixels=b"\x00\x10\x20\x30\xff"):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


PNG = base64.b64encode(png_bytes()).decode("ascii")


def config(**overrides):
    return {"name": "synthetic-image", "type": "llm", "provider": "anthropic",
            "model": "claude-opus-5-5", "token": "FAKE-named", "tools": [],
            "image_input": {"key": "screenshot", "media_type": "image/png"},
            "system_prompt": SYSTEM, "task_template": "{{ task }} {{ screenshot }}",
            **overrides}


def deny(*args, **kwargs):
    raise AssertionError("forbidden runtime capability reached")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "environ", {})
    # A cold xdist worker otherwise reads distro's host os-release file for
    # an SDK telemetry header. Fix that metadata, never warm/read the host.
    monkeypatch.setattr("anthropic._base_client.get_platform", lambda: "Linux")


def assert_private(*values):
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str):
            if any(secret in value for secret in (PNG, TEXT, SYSTEM, "sk-ant-oat-FAKE")):
                raise AssertionError("private content leaked to metadata")


ORDINARY, NO_USAGE = object(), object()  # usage as every test so far sent it; no usage key at all


def event_list(answer=ANSWER, stop="end_turn", terminal=True, tool=False, *, start_usage=ORDINARY,
               delta_usage=ORDINARY):
    message = {"id": "msg_FAKEimage", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
               "content": [], "stop_reason": None, "stop_sequence": None}
    if start_usage is not NO_USAGE:
        message["usage"] = {"input_tokens": 10, "output_tokens": 0} if start_usage is ORDINARY else start_usage
    delta = {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}}
    if delta_usage is not NO_USAGE:
        delta["usage"] = {"output_tokens": 5} if delta_usage is ORDINARY else delta_usage
    events = [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": answer}},
        {"type": "content_block_stop", "index": 0},
        delta,
    ]
    if tool:
        events[1] = {"type": "content_block_start", "index": 0,
                     "content_block": {"type": "tool_use", "id": "tool_FAKE", "name": "Bash", "input": {}}}
    if terminal:
        events.append({"type": "message_stop"})
    return events


def encode(events):
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()


def response_events(answer=ANSWER, stop="end_turn", terminal=True, tool=False, **usage):
    return encode(event_list(answer, stop, terminal, tool, **usage))


def rig(monkeypatch, *, payload=None, status=200, on_send=None, refuse_temperature=False, temperatures=None):
    counters = {"resolve": 0, "credential": 0, "prepare": 0, "hook": 0, "send": 0, "close": 0}
    provider = AnthropicLLM.__new__(AnthropicLLM)
    provider.auth_mode, provider.model = "oauth", "claude-opus-5-5"
    provider._pool = None
    provider.api_key = "sk-ant-oat-FAKE"
    provider.max_tokens, provider.temperature = 1000, 0.0
    provider.cache_ttl = None
    provider.effort = provider.thinking_budget = None
    provider.stream_retry_seconds = 0
    provider._named = {"FAKE-named": NamedToken(token="sk-ant-oat-FAKE", variable="FAKE_VAR", account="FAKE-named")}
    seen = {}

    def handler(request):
        counters["send"] += 1
        body = json.loads(request.content)
        blocks = [block for message in body.get("messages", []) for block in message["content"]]
        images = [block for block in blocks if block.get("type") == "image"]
        texts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
        # Never retain or assert with the request/messages; publish booleans only.
        seen.update(image_count=len(images), text_ok=any(TEXT in text for text in texts),
                    image_ok=len(images) == 1 and images[0] == {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": PNG}},
                    text_safe=all(PNG not in text for text in texts),
                    tools_absent="tools" not in body and "tool_choice" not in body,
                    stream=body.get("stream"), max_tokens=body.get("max_tokens"),
                    subscription_only=request.headers.get("authorization") == "Bearer sk-ant-oat-FAKE"
                        and "x-api-key" not in request.headers)
        if temperatures is not None:
            temperatures.append(body.get("temperature", NOT_SENT))
        logging.getLogger("httpx").warning("fake unsafe SDK detail %s %s", PNG, TEXT)
        if on_send:
            on_send()
        if refuse_temperature and "temperature" in body:
            # What Opus 5 and Sonnet 5 answer (tests/test_llm/test_token_pool.py).
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "`temperature` is deprecated for this model."}})
        return httpx.Response(status, content=response_events() if payload is None else payload,
                              headers={"content-type": "text/event-stream"})

    sdk = anthropic.Anthropic(auth_token="sk-ant-oat-FAKE",
        base_url="https://api.anthropic.com", http_client=httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False))

    def credential(_):
        counters["credential"] += 1
        return sdk
    provider._client_for = credential

    def shaper():
        counters["prepare"] += 1
        return SimpleNamespace(shape=lambda body: body, client_headers=lambda: {})
    monkeypatch.setattr("temper_ai.llm.providers.anthropic.get_oauth_shaper", shaper)

    def client(control):
        def start(request):
            counters["hook"] += 1
            control.request_start(request)
        transport = httpx.MockTransport(handler)
        owned = httpx.Client(transport=transport, timeout=control.remaining(), trust_env=False,
                             follow_redirects=False, event_hooks={"request": [start]})
        real_close = owned.close
        def close():
            counters["close"] += 1
            real_close()
        owned.close = close
        return owned
    monkeypatch.setattr(single_send, "new_http_client", client)
    rows, chunks, tracked = [], [], []
    te = SimpleNamespace(policy_engine=None, run_cost_usd=0, run_tokens=0,
                         track_usage=lambda **kwargs: tracked.append(kwargs), get_tool=deny, execute=deny)
    ctx = ExecutionContext(run_id="FAKE-run", workflow_name="FAKE-workflow", node_path="judge",
        agent_name="synthetic-image", event_recorder=SimpleNamespace(
            record=lambda *args, **kwargs: rows.append((args, kwargs)) or f"event-{len(rows)}"),
        tool_executor=te, llm_providers={"anthropic": provider}, cancel_event=threading.Event(),
        stream_callback=lambda chunk: chunks.append(chunk))
    original_get = ctx.get_llm
    def get(name):
        counters["resolve"] += 1
        return original_get(name)
    ctx.get_llm = get
    return ctx, provider, counters, seen, rows, chunks, tracked


def test_combined_happy_path_entrypoint_one_png_text_one_send_safe_events(monkeypatch, caplog):
    """FIRST: registry -> real llm agent -> native SDK -> counting offline HTTP."""
    ctx, _, counts, seen, rows, chunks, tracked = rig(monkeypatch)
    for name in ("_build_llm_service", "_get_tools", "_make_tool_executor", "_recall_memories",
                 "_store_memories", "_ask_for_valid_json"):
        monkeypatch.setattr(LLMAgent, name, deny)
    blocked_io = []
    def denied_open(*args, **kwargs):
        frame = sys._getframe(1)
        blocked_io.append((frame.f_globals.get("__name__"), frame.f_code.co_name, frame.f_lineno))
        raise AssertionError("forbidden file capability reached")
    with monkeypatch.context() as restricted:
        restricted.setattr("builtins.open", denied_open)
        restricted.setattr("pathlib.Path.open", denied_open)
        node_result = AgentNode(NodeConfig(name="image"), config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    outcome = node_result.agent_results[0] if node_result.agent_results else node_result
    safe_error = outcome.error if outcome.error and outcome.error.startswith("image_input:") else "redacted"
    assert node_result.status == Status.COMPLETED, f"synthetic status: {safe_error}; {counts=}; {blocked_io=}"
    result = node_result.agent_results[0]
    assert result.structured_output == {"verdict": "ok"}
    assert result.llm_calls == 1 and result.tool_calls == 0
    assert counts["send"] == counts["hook"] == counts["credential"] == counts["prepare"] == 1
    assert counts["close"] == 1
    assert seen == {"image_count": 1, "image_ok": True, "text_ok": True, "text_safe": True,
                    "tools_absent": True, "stream": True, "max_tokens": 1000, "subscription_only": True}
    assert len(tracked) == 1 and result.tokens.total_tokens == 15
    assert result.metadata["usage"]["cache_read_input_tokens"] is None
    assert result.metadata["usage"]["total_tokens"] is None
    assert result.metadata["transmissions"] == 1
    # Existing native single-send buffers its SSE response: no callback text stream.
    assert not chunks
    assert_private(rows, result.metadata, [
        {"rendered": row.getMessage(), "msg": row.msg, "args": row.args,
         "exc": row.exc_info, "text": row.exc_text, "stack": row.stack_info} for row in caplog.records])


@pytest.mark.parametrize("cfg", [
    {"image_input": None}, {"image_input": False}, {"image_input": {}},
    {"image_input": {"key": "screenshot", "media_type": "image/png", "url": "bad"}},
    {"image_input": {"key": "", "media_type": "image/png"}},
    {"image_input": {"key": 1, "media_type": "image/png"}},
    {"image_input": {"key": "screenshot", "media_type": "image/jpeg"}},
    {"tools": None}, {"tools": False}, {"tools": {}}, {"tools": ["Read"]},
    {"provider": "claude"}, {"provider": "openai"}, {"provider": None},
    {"token": None}, {"token": "sk-ant-oat-FAKE"}, {"token": False},
    {"fallback": []}, {"fallback": ["other"]}, {"provider_config": {"tools": []}},
    {"provider_config": {"single_send": False}}, {"provider_config": {"base_url": "bad"}},
    {"provider_config": {"max_tokens": 0}}, {"max_tokens": False}, {"max_tokens": 0},
    {"provider_config": {"max_tokens": 100}, "max_tokens": 200},
    {"provider_config": {"thinking_budget": 10, "thinking": {"type": "adaptive"}}},
    {"provider_config": {"effort": "not-an-effort"}},
    {"provider_config": {"temperature": float("nan")}}, {"total_timeout": 0},
    {"total_timeout": True}, {"total_timeout": float("inf")},
    {"memory": {"enabled": True}}, {"memory": {"store_observations": True}},
    {"max_iterations": 2}, {"context_policy": "compress"}, {"provider_tools": []},
    {"_receives_strategy_context": True}, {"cli": {}}, {"mcp_servers": []}, {"wait_for_allowance": False},
    {"image_input": {"key": "screenshot", "media_type": False}}, {"image_input": []},
    {"thinking_budget": True, "provider_config": {"thinking_budget": False}},
    {"model": False}, {"provider_config": {"thinking": {"type": "enabled", "extra": True}}},
    {"max_iterations": True}, {"max_iterations": 0}, {"provider_config": {"temperature": True}},
    {"memory": None}, {"token": []}, {"tools": "[]"}, {"single_send": False},
    {"api_key": "FAKE-NOT-A-KEY"}, {"auth_mode": "api_key"}, {"auth_token": "FAKE"},
    {"base_url": "https://example.invalid"}, {"thinking_budget": True}, {"effort": "high"},
], ids=lambda _: "config-refusal")
def test_bad_config_never_resolves_or_prepares(monkeypatch, cfg):
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch)
    try:
        agent = create_agent(config(**cfg))
    except ValueError as exc:
        assert_private(str(exc))
    else:
        result = agent.run({"task": TEXT, "screenshot": PNG}, ctx)
        assert result.status == Status.FAILED
    assert sum(counts.values()) == 0
    assert_private(rows)


def test_tools_must_be_explicit(monkeypatch):
    cfg = config()
    del cfg["tools"]
    with pytest.raises(ValueError, match="image_input"):
        create_agent(cfg)


@pytest.mark.parametrize("value", [None, False, 0, [], {}, [PNG, PNG], "", "not base64",
    "data:image/png;base64,ignored", "https://example.invalid/image.png", "/tmp/image.png",
    PNG + "\n", PNG.rstrip("="), base64.b64encode(b"not a png").decode(),
    base64.b64encode(png_bytes()[:-1]).decode(), {"type": "image", "source": {}}], ids=lambda _: "input-refusal")
def test_bad_input_zero_resolution_preparation_send(monkeypatch, value):
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch)
    result = create_agent(config()).run({"task": TEXT, "screenshot": value}, ctx)
    assert result.status == Status.FAILED
    assert sum(counts.values()) == 0
    assert_private(rows, result.error)


def test_missing_input_and_text_refuse_before_resolution(monkeypatch):
    ctx, _, counts, _, _, _, _ = rig(monkeypatch)
    for data in ({"task": TEXT}, {"screenshot": PNG}):
        assert create_agent(config()).run(data, ctx).status == Status.FAILED
    assert sum(counts.values()) == 0


@pytest.mark.parametrize("kind", ["tool_use", "max_tokens", "refusal", "pause_turn", "partial", "bad_json", "empty",
                                  "auth", "quota", "redirect", "cancel"])
def test_failed_answer_never_sends_again(monkeypatch, kind, caplog):
    cancel = threading.Event()
    ctx, _, counts, _, rows, chunks, _ = rig(monkeypatch,
        payload=response_events(answer='{"bad": nope}' if kind == "bad_json" else "" if kind == "empty" else ANSWER,
                                stop=kind if kind in {"tool_use", "max_tokens", "refusal", "pause_turn"} else "end_turn",
                                terminal=kind != "partial", tool=kind == "tool_use"),
        status={"auth": 401, "quota": 429, "redirect": 307}.get(kind, 200),
        on_send=cancel.set if kind == "cancel" else None)
    ctx.cancel_event = cancel
    monkeypatch.setattr(LLMAgent, "_ask_for_valid_json", deny)
    monkeypatch.setattr("temper_ai.stage.agent_node.time.sleep", deny)
    node_result = AgentNode(NodeConfig(name="image"), config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    assert node_result.status == Status.FAILED
    result = node_result.agent_results[0]
    assert counts["send"] == counts["hook"] == 1
    assert counts["close"] == 1
    assert result.llm_calls == 1 and not chunks
    assert_private(rows, result.metadata, result.error, [row.getMessage() for row in caplog.records])


@pytest.mark.parametrize("key", ["_strategy_context", "other_agents", "workspace_path", "memories"])
def test_ambient_input_refuses_before_resolving(monkeypatch, key):
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch)
    result = create_agent(config()).run({"task": TEXT, "screenshot": PNG, key: TEXT}, ctx)
    assert result.status == Status.FAILED and sum(counts.values()) == 0
    assert_private(rows, result.error)


def test_context_workspace_not_added_to_rendering(monkeypatch):
    ctx, _, counts, _, _, _, _ = rig(monkeypatch)
    ctx.workspace_path = "SYNTHETIC_AMBIENT_WORKSPACE"
    renderer = LLMAgent(config()).prompt_renderer
    render = renderer.render
    observed = []
    def checked(**kwargs):
        observed.append("workspace_path" not in kwargs["input_data"])
        return render(**kwargs)
    agent = LLMAgent(config())
    agent.prompt_renderer.render = checked
    result = agent.run({"task": TEXT, "screenshot": PNG}, ctx)
    assert result.status == Status.COMPLETED and observed == [True] and counts["send"] == 1


@pytest.mark.parametrize("kind", ["paid", "wrong_provider", "unknown_token", "cancelled", "policy", "expired"])
def test_provider_or_policy_veto_zero_http(monkeypatch, kind):
    ctx, provider, counts, _, rows, _, _ = rig(monkeypatch)
    if kind == "paid":
        provider.auth_mode = "api_key"
    elif kind == "wrong_provider":
        ctx.llm_providers["anthropic"] = SimpleNamespace(provider_name="anthropic", complete=deny)
    elif kind == "unknown_token":
        provider._named = {}
    elif kind == "cancelled":
        ctx.cancel_event.set()
    elif kind == "expired":
        monkeypatch.setattr("temper_ai.agent.llm_agent.DEFAULT_TOTAL_TIMEOUT", 0.001)
    else:
        ctx.tool_executor.policy_engine = SimpleNamespace(evaluate=lambda *args: SimpleNamespace(
            action="deny", reason="SYNTHETIC_PRIVATE_IMAGE_TASK"))
    result = create_agent(config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    assert result.status == Status.FAILED
    assert counts["send"] == counts["prepare"] == counts["credential"] == 0
    assert_private(rows, result.metadata, result.error)


@pytest.mark.parametrize("sink", ["usage", "terminal_event"])
def test_post_send_observability_failure_does_not_escape_into_agentnode_retry(monkeypatch, sink):
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError(TEXT + PNG)
    if sink == "usage":
        ctx.tool_executor.track_usage = fail
    else:
        real_record = ctx.event_recorder.record
        def record(kind, **kwargs):
            if kind == EventType.LLM_CALL_COMPLETED:
                return fail()
            return real_record(kind, **kwargs)
        ctx.event_recorder.record = record
    monkeypatch.setattr("temper_ai.stage.agent_node.time.sleep", deny)
    result = AgentNode(NodeConfig(name="image"), config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    assert result.status == Status.FAILED and result.error == "image_input: observability"
    assert counts["hook"] == counts["send"] == counts["close"] == 1
    assert_private(rows, result.error)


def test_clean_plain_text_and_usage_projection(monkeypatch):
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch, payload=response_events(answer="plain answer"))
    result = create_agent(config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    assert result.status == Status.COMPLETED and result.output == "plain answer"
    assert result.structured_output is None and counts["send"] == 1
    complete = [kwargs["data"] for args, kwargs in rows if args[0] == EventType.LLM_CALL_COMPLETED]
    assert len(complete) == 1
    assert complete[0]["prompt_tokens"] == 10 and complete[0]["completion_tokens"] == 5
    assert complete[0]["total_tokens"] is None and complete[0]["latency_ms"] is None
    assert_private(rows)


def test_legacy_text_entrypoint_remains_legacy(monkeypatch):
    from temper_ai.llm.models import LLMRunResult
    ctx, _, counts, _, _, _, _ = rig(monkeypatch)
    cfg = config()
    del cfg["image_input"]
    calls = []
    service = SimpleNamespace(run=lambda **kwargs: calls.append(1) or LLMRunResult(output="legacy", iterations=1))
    monkeypatch.setattr(LLMAgent, "_build_llm_service", lambda *_: service)
    result = create_agent(cfg).run({"task": "legacy"}, ctx)
    assert result.status == Status.COMPLETED and result.output == "legacy"
    assert len(calls) == 1 and sum(counts.values()) == 0
    assert asdict(result)["tool_calls"] == 0


def test_model_that_refuses_temperature_gets_one_send_without_it(monkeypatch):
    """Opus 5 and Sonnet 5 answer 400 when a request carries `temperature`.

    An image agent that sets none must send none: not the provider's default,
    whatever the process has learned about the model, and with no resend.
    """
    from temper_ai.llm.providers import anthropic as anthropic_provider
    sent = []
    ctx, provider, counts, _, rows, _, _ = rig(monkeypatch, refuse_temperature=True, temperatures=sent)
    provider.temperature = 0.7  # the live provider default; it must stay out of the request
    learned = set()  # nothing learned yet: the ordinary path would still send temperature here
    monkeypatch.setattr(anthropic_provider, "_NO_TEMPERATURE", learned)
    monkeypatch.setattr("temper_ai.stage.agent_node.time.sleep", deny)
    node_result = AgentNode(NodeConfig(name="image"), config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    outcome = node_result.agent_results[0] if node_result.agent_results else node_result
    safe_error = outcome.error if outcome.error and outcome.error.startswith("image_input:") else "redacted"
    assert node_result.status == Status.COMPLETED, f"synthetic status: {safe_error}; {sent=}"
    assert sent == [NOT_SENT]
    assert counts["send"] == counts["hook"] == counts["close"] == 1
    assert outcome.llm_calls == 1 and outcome.structured_output == {"verdict": "ok"}
    assert learned == set()
    assert_private(rows, outcome.metadata)


@pytest.mark.parametrize("where", ["top_level", "provider_config"])
@pytest.mark.parametrize("refuses", [False, True], ids=["model_accepts", "model_refuses"])
def test_explicit_temperature_is_sent_once_unchanged(monkeypatch, where, refuses):
    """A temperature the agent sets is sent as is, exactly once. A model that
    refuses it fails the call: no resend without it, nothing learned."""
    from temper_ai.llm.providers import anthropic as anthropic_provider
    sent = []
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch, refuse_temperature=refuses, temperatures=sent)
    learned = {"claude-opus-5-5"}  # learned refusal: must not change what this path sends
    monkeypatch.setattr(anthropic_provider, "_NO_TEMPERATURE", learned)
    monkeypatch.setattr("temper_ai.stage.agent_node.time.sleep", deny)
    cfg = config(temperature=0.25) if where == "top_level" else config(provider_config={"temperature": 0.25})
    node_result = AgentNode(NodeConfig(name="image"), cfg).run({"task": TEXT, "screenshot": PNG}, ctx)
    outcome = node_result.agent_results[0] if node_result.agent_results else node_result
    assert sent == [0.25]
    assert counts["send"] == counts["hook"] == counts["close"] == 1 and outcome.llm_calls == 1
    if refuses:
        assert node_result.status == Status.FAILED
        assert outcome.error == "image_input: transport (BadRequestError)"
    else:
        assert node_result.status == Status.COMPLETED
    assert learned == {"claude-opus-5-5"}
    assert_private(rows, outcome.metadata, outcome.error)


# Usage never costs the answer (#221). Anthropic adds usage fields over time, and
# #194's third live attempt lost a whole answer to one the pinned SDK does not
# model: our own check refused it as "image_input: strict_parser". Usage
# describes the answer; a shape we cannot read is recorded, never 0.

UNMODELLED_DELTA = {"output_tokens": 5, "service_tier": "standard", "inference_geo": "us",
                    "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
# How those fields are recorded: plain values as they are, an object as its type and length.
UNMODELLED_DELTA_RECORD = {"service_tier": "standard", "inference_geo": "us",
                           "cache_creation": {"type": "object", "length": 2}}
NULL_USAGE = dict.fromkeys(single_send.USAGE_COUNTERS)
CALL_COUNTERS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_prompt_tokens", "cache_write_tokens")


def image_run(monkeypatch, payload):
    """One image call through the real agent node, the native SDK and offline HTTP."""
    ctx, _, counts, _, rows, _, _ = rig(monkeypatch, payload=payload)
    monkeypatch.setattr(LLMAgent, "_ask_for_valid_json", deny)
    monkeypatch.setattr("temper_ai.stage.agent_node.time.sleep", deny)
    node_result = AgentNode(NodeConfig(name="image"), config()).run({"task": TEXT, "screenshot": PNG}, ctx)
    outcome = node_result.agent_results[0] if node_result.agent_results else node_result
    safe_error = outcome.error if outcome.error and outcome.error.startswith("image_input:") else "redacted"
    call_ends = [kwargs["data"] for args, kwargs in rows
                 if args[0] in (EventType.LLM_CALL_COMPLETED, EventType.LLM_CALL_FAILED)]
    agent_ends = [kwargs["data"] for args, kwargs in rows
                  if args[0] in (EventType.AGENT_COMPLETED, EventType.AGENT_FAILED)]
    assert counts["send"] == counts["hook"] == counts["close"] == 1 and outcome.llm_calls == 1
    assert len(call_ends) == len(agent_ends) == 1
    assert_private(rows, outcome.metadata, outcome.error)
    return node_result.status, outcome, safe_error, call_ends[0], agent_ends[0]


def usage_row(call_end):
    """The usage row the usage writer derives from this call's end event."""
    from datetime import UTC, datetime

    from temper_ai.observability.usage_rows import extract
    return extract(EventType.LLM_CALL_COMPLETED.value, call_end,
                   {"event_id": "event-end", "execution_id": "FAKE-run", "parent_id": "event-agent"},
                   datetime(2026, 10, 29, tzinfo=UTC))


def test_unmodelled_usage_fields_keep_the_answer_counters_and_a_recorded_fault(monkeypatch):
    """FIRST: fields the pinned SDK does not model, on both usage events. The
    answer is kept, the counters are read as always, the fields are recorded."""
    status, outcome, safe_error, call_end, agent_end = image_run(monkeypatch, response_events(
        start_usage={"input_tokens": 10, "output_tokens": 1, "brand_new_counter": 3}, delta_usage=UNMODELLED_DELTA))
    # Before #221 this was #194's refusal: "image_input: strict_parser (SingleSendError)".
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.structured_output == {"verdict": "ok"}
    assert outcome.metadata["usage"] == {"input_tokens": 10, "output_tokens": 5, "total_tokens": None,
                                         "cache_read_input_tokens": None, "cache_creation_input_tokens": None}
    assert (call_end["prompt_tokens"], call_end["completion_tokens"]) == (10, 5)
    assert call_end["cost_basis"] == "list_price_estimate" and call_end["cost_usd"] > 0
    fault = {"reason": "unmodelled", "unmodelled": {"message_start.usage": {"brand_new_counter": 3},
                                                    "message_delta.usage": UNMODELLED_DELTA_RECORD}}
    assert call_end["usage_fault"] == agent_end["usage_fault"] == fault
    row = usage_row(call_end)
    assert (row.prompt_tokens, row.completion_tokens) == (10, 5) and "usage-missing" not in row.fault_codes


def test_unmodelled_message_delta_usage_alone_keeps_the_answer(monkeypatch):
    """#194 attempt 3's shape: the pinned MessageDeltaUsage models five fields."""
    status, outcome, safe_error, call_end, _ = image_run(monkeypatch, response_events(delta_usage=UNMODELLED_DELTA))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.structured_output == {"verdict": "ok"}
    assert (call_end["prompt_tokens"], call_end["completion_tokens"]) == (10, 5)
    assert call_end["usage_fault"] == {"reason": "unmodelled",
                                       "unmodelled": {"message_delta.usage": UNMODELLED_DELTA_RECORD}}


def test_absent_usage_is_null_with_a_fault_and_the_answer_kept(monkeypatch):
    status, outcome, safe_error, call_end, _ = image_run(
        monkeypatch, response_events(start_usage=NO_USAGE, delta_usage=NO_USAGE))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.structured_output == {"verdict": "ok"}
    assert outcome.metadata["usage"] == NULL_USAGE
    # cost_usd keeps AgentResult's legacy 0.0 aggregate as before; the call's own record says unknown.
    assert all(call_end[key] is None for key in CALL_COUNTERS) and call_end["cost_basis"] == "unknown"
    assert call_end["usage_fault"] == {"reason": "absent"}
    assert "usage-missing" in usage_row(call_end).fault_codes.split(",")


@pytest.mark.parametrize(("start", "delta", "unreadable"), [
    (ORDINARY, {"output_tokens": -1}, ["output_tokens"]),
    (ORDINARY, {"output_tokens": "abc"}, ["output_tokens"]),
    (ORDINARY, {"output_tokens": 1.5}, ["output_tokens"]),
    (ORDINARY, {"output_tokens": None}, ["output_tokens"]),
    ({"input_tokens": "abc", "output_tokens": 0}, ORDINARY, ["input_tokens"]),
    ({"input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": -2}, ORDINARY, ["cache_read_input_tokens"]),
    ([1, 2], ORDINARY, ["message_start.usage"]),
    (ORDINARY, "weird", ["message_delta.usage"]),
    (NO_USAGE, ORDINARY, ["message_start.usage"]),
    (ORDINARY, NO_USAGE, ["message_delta.usage"]),
    (ORDINARY, None, ["message_delta.usage"]),
], ids=["negative", "text", "fraction", "null-output", "text-input", "negative-cache", "start-not-object",
        "delta-not-object", "start-missing", "delta-missing", "delta-null"])
def test_unreadable_usage_is_null_with_a_named_fault_and_the_answer_kept(monkeypatch, start, delta, unreadable):
    """A counter we model, of the wrong type, is still never taken as a number."""
    status, outcome, safe_error, call_end, _ = image_run(
        monkeypatch, response_events(start_usage=start, delta_usage=delta))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.structured_output == {"verdict": "ok"}
    assert outcome.metadata["usage"] == NULL_USAGE
    assert all(call_end[key] is None for key in CALL_COUNTERS) and call_end["cost_basis"] == "unknown"
    assert call_end["usage_fault"] == {"reason": "unreadable", "unreadable": unreadable}
    assert "usage-missing" in usage_row(call_end).fault_codes.split(",")


@pytest.mark.parametrize(("start", "delta", "usage"), [
    (ORDINARY, ORDINARY, {"input_tokens": 10, "output_tokens": 5, "total_tokens": None,
                          "cache_read_input_tokens": None, "cache_creation_input_tokens": None}),
    ({"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0},
     {"output_tokens": 5, "input_tokens": 12, "cache_read_input_tokens": None},
     {"input_tokens": 12, "output_tokens": 5, "total_tokens": None,
      "cache_read_input_tokens": 2, "cache_creation_input_tokens": 0}),
], ids=["plain", "cache-and-delta-merge"])
def test_ordinary_usage_reads_exactly_as_before(monkeypatch, start, delta, usage):
    """Passes unchanged on the code before #221: nobody's accounting moves."""
    status, outcome, safe_error, call_end, agent_end = image_run(
        monkeypatch, response_events(start_usage=start, delta_usage=delta))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert list(outcome.metadata["usage"].items()) == list(usage.items())
    assert [call_end[key] for key in CALL_COUNTERS] == [usage["input_tokens"], usage["output_tokens"], None,
                                                       usage["cache_read_input_tokens"],
                                                       usage["cache_creation_input_tokens"]]
    assert "usage_fault" not in call_end and "usage_fault" not in agent_end


def test_unreadable_wins_over_unmodelled_and_both_are_recorded(monkeypatch):
    status, outcome, safe_error, call_end, _ = image_run(
        monkeypatch, response_events(delta_usage={"output_tokens": "abc", "service_tier": "standard"}))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.metadata["usage"] == NULL_USAGE
    assert call_end["usage_fault"] == {"reason": "unreadable", "unreadable": ["output_tokens"],
                                       "unmodelled": {"message_delta.usage": {"service_tier": "standard"}}}


def test_a_repeated_message_start_changes_nothing_as_before(monkeypatch):
    """Only the first message_start counts, as in the SDK's accumulator before #221."""
    events = event_list()
    repeat = json.loads(json.dumps(events[0]))
    repeat["message"]["usage"] = {"input_tokens": 99, "output_tokens": 0}
    events.insert(1, repeat)
    status, outcome, safe_error, call_end, _ = image_run(monkeypatch, encode(events))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert (call_end["prompt_tokens"], call_end["completion_tokens"]) == (10, 5) and "usage_fault" not in call_end


def test_an_unreadable_usage_is_named_once_however_often_it_arrives(monkeypatch):
    events = event_list(delta_usage="weird")
    events.insert(4, dict(events[4]))
    assert [event["type"] for event in events].count("message_delta") == 2
    status, outcome, safe_error, call_end, _ = image_run(monkeypatch, encode(events))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert call_end["usage_fault"] == {"reason": "unreadable", "unreadable": ["message_delta.usage"]}


def test_usage_reader_failure_is_a_recorded_fault_never_a_lost_answer(monkeypatch):
    from temper_ai.llm.providers import anthropic as anthropic_provider

    def broken(*_):
        raise RuntimeError("synthetic reader failure")
    monkeypatch.setattr(anthropic_provider, "_read_single_send_usage", broken)
    status, outcome, safe_error, call_end, _ = image_run(monkeypatch, response_events())
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert outcome.structured_output == {"verdict": "ok"} and outcome.metadata["usage"] == NULL_USAGE
    assert call_end["usage_fault"] == {"reason": "unreadable", "unreadable": ["reader"]}


@pytest.mark.parametrize(("fields", "count"), [({f"field_{n}": n for n in range(400)}, 400),
                                               ({"odd": float("nan")}, 1)], ids=["too-large", "not-json"])
def test_unmodelled_values_too_large_or_not_json_are_only_counted(monkeypatch, fields, count):
    """What reaches the call's events stays small and storable; the fault still counts."""
    status, outcome, safe_error, call_end, _ = image_run(
        monkeypatch, response_events(delta_usage={"output_tokens": 5, **fields}))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert (call_end["prompt_tokens"], call_end["completion_tokens"]) == (10, 5)
    assert call_end["usage_fault"] == {"reason": "unmodelled", "unmodelled_count": {"message_delta.usage": count}}


@pytest.mark.parametrize(("fields", "record"), [
    ({"tier": "priority", "flag": True, "gone": None, "ratio": 1.5, "count": 7},
     {"tier": "priority", "flag": True, "gone": None, "ratio": 1.5, "count": 7}),
    ({"note": "a" * 64}, {"note": "a" * 64}),
    ({"note": "a" * 65}, {"note": {"type": "string", "length": 65}}),
    ({"split": [1, 2, 3]}, {"split": {"type": "array", "length": 3}}),
    ({"detail": {"tokens": 1}}, {"detail": {"type": "object", "length": 1}}),
], ids=["plain-values", "string-at-limit", "string-past-limit", "array", "object"])
def test_unmodelled_values_are_kept_only_when_plain(monkeypatch, fields, record):
    """We know nothing about an unmodelled field, so only a plain value reaches the
    call's events: null, a boolean, a number or a short string. Anything else is
    recorded as its JSON type and length."""
    status, outcome, safe_error, call_end, _ = image_run(
        monkeypatch, response_events(delta_usage={"output_tokens": 5, **fields}))
    assert status == Status.COMPLETED, f"synthetic status: {safe_error}"
    assert (call_end["prompt_tokens"], call_end["completion_tokens"]) == (10, 5)
    assert call_end["usage_fault"] == {"reason": "unmodelled", "unmodelled": {"message_delta.usage": record}}


def test_an_unmodelled_value_that_is_not_json_keeps_the_counters():
    """No JSON reply can hold such a value, only an object made in process; the
    counters are still read and the field is still counted, never a reader fault."""
    from temper_ai.llm.providers import anthropic as anthropic_provider
    start = anthropic.types.Usage(input_tokens=10, output_tokens=1)
    delta = anthropic.types.MessageDeltaUsage(output_tokens=5, odd={1, 2})
    assert delta.model_extra == {"odd": {1, 2}}
    usage, fault = anthropic_provider._single_send_usage_never_raises(start, [delta])
    assert usage == {**NULL_USAGE, "input_tokens": 10, "output_tokens": 5}
    assert fault == {"reason": "unmodelled", "unmodelled_count": {"message_delta.usage": 1}}


def test_stream_without_message_delta_invents_no_output_count(monkeypatch):
    """No message_delta: no stop reason (the answer is partial) and no output count, not message_start's 0."""
    events = [event for event in event_list() if event["type"] != "message_delta"]
    status, outcome, _, call_end, _ = image_run(monkeypatch, encode(events))
    assert status == Status.FAILED and outcome.error == "image_input: partial (SingleSendError)"
    assert all(call_end[key] is None for key in CALL_COUNTERS)
    assert call_end["usage_fault"] == {"reason": "unreadable", "unreadable": ["message_delta.usage"]}


@pytest.mark.parametrize("case", ["block-before-message-start", "delta-of-unstarted-block", "stop-of-unstarted-block"])
def test_answer_events_out_of_order_fail_partial_with_one_send(monkeypatch, case):
    """The order checks the SDK's accumulator made, kept now that raw events are read."""
    events = event_list()
    if case == "block-before-message-start":
        events[0], events[1] = events[1], events[0]
    else:
        events[2 if case == "delta-of-unstarted-block" else 3]["index"] = 1
    status, outcome, _, _, _ = image_run(monkeypatch, encode(events))
    assert status == Status.FAILED and outcome.error == "image_input: partial (SingleSendError)"
