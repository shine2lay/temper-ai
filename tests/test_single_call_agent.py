"""One synthetic answer per slot; no credential lookup or real transport.

The opening test is deliberately whole-feature: registry -> AgentNode -> locked
SDK -> counting mock transport -> durable files -> schema/event readback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from temper_ai.agent import create_agent
from temper_ai.agent.single_call_agent import parse_pinned_pricing
from temper_ai.shared.types import ExecutionContext, Status
from temper_ai.stage.agent_node import AgentNode
from temper_ai.stage.models import NodeConfig

REPO = Path(__file__).resolve().parents[1]
PROMPT = b"SYNTHETIC_PRIVATE_PROMPT_137\n"
ANSWER = " SYNTHETIC_PRIVATE_ANSWER_137\n"
REASONING = "SYNTHETIC_PRIVATE_REASONING_137\nnot for metadata\t137"


@pytest.fixture(autouse=True)
def no_real_network_or_credentials(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("real transport or credential lookup forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    credential_names = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                        "CLAUDE_CODE_OAUTH_TOKEN_BACKUP", "OPENAI_API_KEY", "OPENAI_ACCESS_TOKEN",
                        *[f"CLAUDE_CODE_OAUTH_TOKEN_{i}" for i in range(2, 10)]}
    # No copy/read of the host's values. Empty present names cannot be refilled
    # by dotenv, and the fake providers never resolve an environment credential.
    monkeypatch.setattr(os, "environ", dict.fromkeys(credential_names, ""))
    original_get = os._Environ.get
    def checked_get(env, key, default=None):
        if key in credential_names:
            return deny()
        return original_get(env, key, default)
    monkeypatch.setattr(os._Environ, "get", checked_get)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assert_metadata_only(*payloads):
    """Inspect structured leaves AND JSON string containers, never escaped dumps."""
    sentinels = (PROMPT.decode(), ANSWER, REASONING)
    forbidden = (*sentinels, *(value.strip() for value in sentinels))
    pending = list(payloads)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, BaseException):
            pending.extend((str(value), value.args))
        elif isinstance(value, str):
            if any(secret in value for secret in forbidden):
                raise AssertionError("content leaked to metadata")
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            pending.append(decoded)


def fixture_config(tmp_path, family="A"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "out"
    root.mkdir(mode=0o700)
    prompt = tmp_path / "prompt.txt"
    prompt.write_bytes(PROMPT)
    pricing = tmp_path / "pricing.json"
    model = "claude-opus-5-5" if family == "A" else "gpt-6.1-sol"
    pricing.write_text(json.dumps({
        "currency": "USD", "models": {model: {
            "input_usd_per_million": 1, "output_usd_per_million": 2,
            "max_output_tokens": 4096,
            "public_source": "https://example.invalid/FAKE-TEST-ONLY",
            "request_limit_evidence": "https://example.invalid/FAKE-TEST-ONLY",
        }},
    }))
    fixed = {
        "prompt_path": str(prompt), "prompt_sha256": digest(PROMPT),
        "prompt_bytes": len(PROMPT), "output_root": str(root),
        "slot": family + "1", "family": family, "max_tokens": 1000,
        "deadline_s": 900, "cost_cap_usd": 5,
        "output_bound_mode": "request_limit" if family == "A" else "documented_max",
        "route": "anthropic-oauth-named-token" if family == "A" else "openai-codex-oauth",
        "auth_mode": "oauth", "pricing_path": str(pricing),
        "pricing_sha256": digest(pricing.read_bytes()),
        "experiment_id": "FAKE-experiment", "binding_id": "FAKE-binding",
        "source_sha256": "1" * 64, "config_sha256": "2" * 64,
        "packet_sha256": "3" * 64,
    }
    if family == "A":
        fixed["token"] = "FAKE-named"
    return {"name": "judge", "type": "single_call", "provider": "anthropic" if family == "A" else "openai",
            "model": model, "single_call": fixed}


def anthropic_events(answer=ANSWER, stop="end_turn", *, reasoning=None):
    # Synthetic provider protocol data, not a captured application request.
    events = [
        {"type": "message_start", "message": {"id": "msg_FAKE137", "type": "message",
         "role": "assistant", "model": "claude-opus-5-5", "content": [], "stop_reason": None,
         "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": answer}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
         "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    if reasoning is not None:
        events[4:4] = [
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "thinking_delta", "thinking": reasoning}},
            {"type": "content_block_stop", "index": 1},
        ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def fake_anthropic(monkeypatch, handler):
    from temper_ai.llm import single_send
    from temper_ai.llm.providers.anthropic import AnthropicLLM
    from temper_ai.llm.token_pool import NamedToken

    # __new__ avoids environment resolution, JWT files, pool env and startup logs.
    provider = AnthropicLLM.__new__(AnthropicLLM)
    provider.auth_mode = "oauth"
    provider.model = "claude-opus-5-5"
    provider._pool = None
    provider.api_key = "sk-ant-oat-FAKE"
    provider.max_tokens, provider.temperature = 1000, 0.0
    provider.cache_ttl = None
    provider.effort = provider.thinking_budget = None
    provider.stream_retry_seconds = 0
    named = NamedToken(token="sk-ant-oat-FAKE", variable="FAKE_VAR", account="FAKE-named")
    provider._named = {"FAKE-named": named}
    sdk = anthropic.Anthropic(auth_token="sk-ant-oat-FAKE", api_key="FAKE-NOT-A-KEY",
        base_url="https://api.anthropic.com", http_client=httpx.Client(
            transport=httpx.MockTransport(handler), trust_env=False))
    provider._client_for = lambda credential: sdk
    provider._test_sdk = sdk
    import temper_ai.llm.providers.anthropic as module
    monkeypatch.setattr(module, "get_oauth_shaper", lambda: None)
    provider._test_request_starts = 0
    def client(control):
        def start(request):
            provider._test_request_starts += 1
            control.request_start(request)
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=control.remaining(),
                            trust_env=False, follow_redirects=False, event_hooks={"request": [start]})
    monkeypatch.setattr(single_send, "new_http_client", client)
    return provider


def fixture_context(provider, key="anthropic"):
    rows = []
    recorder = SimpleNamespace(record=lambda *args, **kwargs: rows.append((args, kwargs)))
    ctx = ExecutionContext(run_id="FAKE-workflow-run", workflow_name="FAKE-workflow", node_path="",
                           agent_name="judge", event_recorder=recorder, tool_executor=None,
                           llm_providers={key: provider}, cancel_event=threading.Event(),
                           stream_callback=lambda *_: (_ for _ in ()).throw(AssertionError("text stream")))
    return ctx, rows


@pytest.mark.parametrize("family", ["A", "B"])
def test_whole_feature_one_raw_answer_durable_receipts_and_metadata_only(tmp_path, monkeypatch, caplog, family):
    """FIRST: each fixed family, node, counting transport, receipts and safe sinks."""
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    from temper_ai.observability import EventType

    cfg = fixture_config(tmp_path, family)
    sent = []

    def handler(request):
        sent.append(1)
        logging.getLogger("httpx").debug("unsafe SDK detail %s %s", PROMPT.decode(), REASONING)
        data = anthropic_events(reasoning=REASONING) if family == "A" else codex_events(reasoning=REASONING)
        return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})

    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    ctx, rows = fixture_context(provider, cfg["provider"])
    caplog.set_level(logging.DEBUG)
    assert type(create_agent(cfg)).__name__ == "SingleCallAgent"
    result = AgentNode(NodeConfig(name="judge"), cfg).run({}, ctx)
    assert result.status == Status.COMPLETED
    root = Path(cfg["single_call"]["output_root"])
    slot = family + "1"
    raw = (root / f"{slot}.raw").read_bytes()
    assert digest(raw) == digest(ANSWER.encode()), "raw bytes changed"
    attempt = json.loads((root / f"{slot}.attempt.json").read_text())
    call = json.loads((root / f"{slot}.call.json").read_text())
    claim = json.loads((root / f"{slot}.claim").read_text())
    assert len(sent) == attempt["transmissions"] == len(attempt["transmission_ids"]) == 1
    assert attempt["terminal"] == "COMPLETED" and attempt["cleanup"] == "CONFIRMED"
    assert_deadline_as_d4_reads_it(attempt)
    assert call["http_started_monotonic_s"] >= attempt["dispatch_monotonic_s"]
    assert Decimal(claim["reservation_usd"]) == Decimal(str(call["reservation_usd"]))
    fixed = cfg["single_call"]
    for key in ("experiment_id", "binding_id", "route", "auth_mode", "source_sha256",
                "config_sha256", "packet_sha256", "pricing_sha256"):
        assert claim[key] == attempt[key] == fixed[key]
    for key in ("provider", "model"):
        assert call[key] == cfg[key]
    for key in ("route", "auth_mode", "pricing_sha256", "output_bound_mode"):
        assert call[key] == fixed[key]
    assert claim["prompt_sha256"] == claim["input_sha256"] == attempt["input_sha256"] == fixed["prompt_sha256"]
    assert call["response_id"] == ("msg_FAKE137" if family == "A" else "resp_FAKE137")
    assert call["stop_reason"] == ("end_turn" if family == "A" else "stop")
    assert call["usage"]["input_tokens"] == 10 and call["usage"]["output_tokens"] == 5
    assert call["usage"]["cache_read_input_tokens"] is None
    pricing = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert float(recompute_list_price_usd(call, pricing)) == attempt["list_price_usd"]
    for file in root.iterdir():
        assert file.stat().st_mode & 0o777 == 0o600
        assert file.stat().st_nlink == 1
    assert root.stat().st_mode & 0o777 == 0o700
    assert_schema(attempt)
    assert_call_schema(call)
    assert any(args[0] == EventType.SINGLE_CALL_ATTEMPT for args, _ in rows)
    assert_metadata_only(asdict(result), rows, [
        {"rendered": r.getMessage(), "msg": r.msg, "args": r.args,
         "exc": r.exc_info, "text": r.exc_text, "stack": r.stack_info}
        for r in caplog.records])
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    second = AgentNode(NodeConfig(name="judge"), cfg).run({}, ctx)
    assert second.status == Status.FAILED and len(sent) == 1
    assert all(p.read_bytes() == before[p.name] for p in root.iterdir()), "used slot changed"


def codex_events(answer=ANSWER, usage=None, *, reasoning=None):
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15} if usage is None else usage
    events = [{"type": "response.output_text.delta", "delta": answer}]
    if reasoning is not None:
        events.append({"type": "response.reasoning_summary_text.delta", "delta": reasoning})
    events.append({"type": "response.completed", "response": {"id": "resp_FAKE137", "status": "completed", "usage": usage}})
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


def fake_codex(monkeypatch, handler):
    from temper_ai.llm import single_send
    from temper_ai.llm.providers.openai import OpenAILLM
    from temper_ai.llm.providers.openai_codex import CodexTransport, codex_url
    provider = OpenAILLM.__new__(OpenAILLM)
    provider.auth_mode, provider.model = "oauth", "gpt-6.1-sol"
    transport = CodexTransport.__new__(CodexTransport)
    transport.model, transport.token = provider.model, "FAKE-no-credential-lookup"
    transport.account_id, transport.url = "FAKE-account", codex_url(None)
    provider._codex = transport
    provider._test_request_starts = 0
    def client(control):
        def start(request):
            provider._test_request_starts += 1
            control.request_start(request)
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=control.remaining(),
                            trust_env=False, follow_redirects=False, event_hooks={"request": [start]})
    monkeypatch.setattr(single_send, "new_http_client", client)
    return provider


def assert_deadline_as_d4_reads_it(attempt):
    """D4 (context_t1_aggregate.py:298) reads Decimal(str(value)) with a 1 us tolerance.

    Binary float subtraction is NOT the contract: (214.510929166 + 900) - 214.510929166
    is 900.0000000000001 in floats (CI run 39625917355, tests (postgres)).
    """
    start, deadline = (Decimal(str(attempt[name])) for name in ("dispatch_monotonic_s", "deadline_monotonic_s"))
    assert abs(deadline - start - 900) <= Decimal("0.000001")


def run_slot(cfg, provider):
    from temper_ai.agent.single_call_agent import SingleCallAgent
    ctx, events = fixture_context(provider, "anthropic" if cfg["single_call"]["family"] == "A" else "openai")
    result = SingleCallAgent(cfg).run({}, ctx)
    root = Path(cfg["single_call"]["output_root"])
    def read(suffix):
        path = root / (cfg["single_call"]["slot"] + suffix)
        return json.loads(path.read_text()) if path.exists() else None
    attempt, call = read(".attempt.json"), read(".call.json")
    if call is not None:
        assert_call_schema(call)
    return result, attempt, call, events


def assert_call_schema(call):
    schema = json.loads((REPO / "docs/schemas/context-t1-call.v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(call)


def assert_schema(attempt):
    schema = json.loads((REPO / "configs/architecture/stages/context_profile/t1/attempt.v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(attempt)


@pytest.mark.parametrize("family", ["A", "B"])
def test_durable_barriers_before_request_and_attempt_last(tmp_path, monkeypatch, family):
    trace = []
    old_write, old_sync = os.write, os.fsync
    def name(fd):
        return os.readlink(f"/proc/self/fd/{fd}").rsplit("/", 1)[-1]
    def write(fd, data):
        trace.append(name(fd) + ":write")
        return old_write(fd, data)
    def sync(fd):
        trace.append(name(fd) + ":fsync")
        return old_sync(fd)
    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", sync)
    def handler(request):
        trace.append("request")
        return httpx.Response(200, content=anthropic_events() if family == "A" else codex_events(),
                              headers={"content-type": "text/event-stream"})
    cfg = fixture_config(tmp_path, family)
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED
    slot = family + "1"
    required = [slot + ".claim:write", slot + ".claim:fsync", "out:fsync", "request",
                slot + ".raw:write", slot + ".call.json:write", slot + ".attempt.json:write"]
    indices = [trace.index(item) for item in required]
    assert indices == sorted(indices)
    assert_schema(attempt)
    if family == "B":
        assert "max_output_tokens" not in call["parameters"]
        assert call["output_bound_tokens"] == 4096 and call["usage"]["cache_read_input_tokens"] is None
        assert call["input_parts"][0]["kind"] == "instructions"


@pytest.mark.parametrize(("case", "reason"), [
    ("529", "quota"), ("timeout", "timeout"), ("thinking-400", "transport"),
    ("temperature-400", "transport"), ("pooled-429", "quota"), ("capacity", "transport"),
    ("broken", "partial"), ("max_tokens", "truncation"),
])
@pytest.mark.parametrize("family", ["A", "B"])
def test_errors_are_one_send_no_fallback_park_or_learning(tmp_path, monkeypatch, case, reason, family):
    from temper_ai.llm.providers import anthropic as module
    sent, legacy = [], []
    cfg = fixture_config(tmp_path, family)
    if family == "A":
        cfg["single_call"].update(temperature=0.2, thinking_budget=64)
    class Pool:
        def cooling_until(self, *a):
            return None
        def cool(self, *a, **kw):
            return 12345678900
        def pick(self, *a, **kw):
            legacy.append("pool_rotation")
            raise AssertionError("rotation")
    def handler(request):
        sent.append(1)
        if case == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_PROVIDER_PROSE_137")
        if case in ("529", "thinking-400", "temperature-400", "pooled-429", "capacity"):
            code = {"529": 529, "thinking-400": 400, "temperature-400": 400, "pooled-429": 429, "capacity": 503}[case]
            return httpx.Response(code, json={"error": {"type": "rate_limit_error" if code == 429 else "invalid_request_error",
                "message": "SYNTHETIC_PROVIDER_PROSE_137 thinking temperature not supported"}})
        if family == "A":
            data = anthropic_events(stop="max_tokens" if case == "max_tokens" else "end_turn")
            if case == "broken":
                data = data[:data.rfind(b"event: message_stop")]
        else:
            data = b'data: {"type":"response.incomplete"}\n\n' if case == "max_tokens" else b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
        return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
    before = (set(module._NO_TEMPERATURE), set(module._NO_VISIBLE_THINKING))
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    if family == "A":
        provider._pool = Pool()
        def legacy_send(*a, **kw):
            legacy.append("param_resend")
            raise AssertionError("legacy resend")
        monkeypatch.setattr(provider, "_send_stream", legacy_send)
        monkeypatch.setattr(provider, "_send", legacy_send)
    result, attempt, _, events = run_slot(cfg, provider)
    assert len(sent) == attempt["transmissions"] == provider._test_request_starts == 1
    assert result.status == Status.FAILED and attempt["terminal"] == "FAILED"
    assert attempt["failure_reasons"] == [reason]
    assert attempt["fallback"] is attempt["resumed"] is False
    assert not legacy and before == (module._NO_TEMPERATURE, module._NO_VISIBLE_THINKING)
    assert all("allowance" not in str(args[0]) and "fallback" not in str(args[0]) for args, _ in events)
    assert "SYNTHETIC_PROVIDER_PROSE_137" not in result.output
    assert_schema(attempt)


@pytest.mark.parametrize("family", ["A", "B"])
@pytest.mark.parametrize("case", ["token", "cap", "hash", "length", "missing", "root-mode", "deadline", "provider", "pricing-hash", "bound"])
def test_preflight_denials_send_zero(tmp_path, monkeypatch, family, case):
    cfg = fixture_config(tmp_path, family)
    f, sent = cfg["single_call"], []
    if case == "token":
        f.pop("token", None) if family == "A" else f.update(token="FAKE-forbidden")
    elif case == "cap":
        f["cost_cap_usd"] = 0
    elif case == "hash":
        f["prompt_sha256"] = "0" * 64
    elif case == "length":
        f["prompt_bytes"] += 1
    elif case == "missing":
        del f["binding_id"]
    elif case == "root-mode":
        os.chmod(f["output_root"], 0o755)
    elif case == "deadline":
        f["deadline_s"] = 899
    elif case == "provider":
        cfg.pop("provider")
    elif case == "pricing-hash":
        f["pricing_sha256"] = "0" * 64
    else:
        price = json.loads(Path(f["pricing_path"]).read_text())
        del price["models"][cfg["model"]]["request_limit_evidence" if family == "A" else "max_output_tokens"]
        Path(f["pricing_path"]).write_text(json.dumps(price))
        f["pricing_sha256"] = digest(Path(f["pricing_path"]).read_bytes())
    def handler(request):
        sent.append(1)
        raise AssertionError("preflight sent")
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, call, _ = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED
    assert result.structured_output["terminal"] == "NOT_MEASURED"
    for observation in (result.metadata, attempt, call):
        if observation is not None:
            assert observation["usage_state"] == "UNKNOWN"
            assert observation["cost_state"] == "KNOWN"
            assert observation["list_price_usd"] == observation["unknown_exposure_usd"] == 0
    if call:
        assert all(value is None for value in call["usage"].values())
    if attempt:
        assert attempt["transmissions"] == 0
        assert_schema(attempt)
        if case == "missing":
            assert attempt["binding_id"] is None


@pytest.mark.parametrize("fault", ["write", "short-write", "claim-sync", "dir-sync"])
@pytest.mark.parametrize("family", ["A", "B"])
def test_claim_durability_faults_never_start_request(tmp_path, monkeypatch, fault, family):
    cfg, sent = fixture_config(tmp_path, family), []
    original_write, original_sync = os.write, os.fsync
    failed = []
    def name(fd):
        return os.readlink(f"/proc/self/fd/{fd}").rsplit("/", 1)[-1]
    def write(fd, data):
        if name(fd).endswith(".claim") and fault in ("write", "short-write"):
            failed.append(1)
            if fault == "write":
                raise OSError("SYNTHETIC_PRIVATE_FILE_PROSE_137")
            return original_write(fd, data[:-1])
        return original_write(fd, data)
    def sync(fd):
        target = name(fd)
        if not failed and ((fault == "claim-sync" and target.endswith(".claim")) or (fault == "dir-sync" and target == "out")):
            failed.append(1)
            raise OSError("SYNTHETIC_PRIVATE_FILE_PROSE_137")
        return original_sync(fd)
    monkeypatch.setattr(os, "write", write)
    monkeypatch.setattr(os, "fsync", sync)
    def handler(request):
        sent.append(1)
        return httpx.Response(200, content=anthropic_events() if family == "A" else codex_events(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert failed and not sent
    assert result.structured_output["transmissions"] == 0
    assert result.structured_output["terminal"] == "NOT_MEASURED"
    assert "SYNTHETIC_PRIVATE_FILE_PROSE_137" not in result.output
    assert_schema(attempt)
    claim_path = Path(cfg["single_call"]["output_root"]) / (family + "1.claim")
    before = digest(claim_path.read_bytes())
    again, _, _, _ = run_slot(cfg, provider)
    assert again.status == Status.FAILED and not sent
    assert before == digest(claim_path.read_bytes()), "claim rewritten after failed durability gate"


def test_claim_only_slot_and_concurrent_contender_never_resend(tmp_path, monkeypatch):
    from temper_ai.agent import single_call_agent as module
    cfg, sent = fixture_config(tmp_path), []
    arrived, release = threading.Event(), threading.Event()
    original_validate = module._Attempt.validate
    def hold_validate(state):
        arrived.set()
        assert release.wait(3)
        return original_validate(state)
    monkeypatch.setattr(module._Attempt, "validate", hold_validate)
    def handler(request):
        sent.append(1)
        return httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_slot, cfg, provider)
        try:
            assert arrived.wait(3)
            loser, _, _, _ = run_slot(cfg, provider)
            assert loser.status == Status.FAILED and not sent
        finally:
            release.set()
        winner, _, _, _ = future.result(timeout=5)
    assert winner.status == Status.COMPLETED and len(sent) == 1


@pytest.mark.parametrize("suffix", ["raw", "call.json"])
def test_post_send_crash_preserves_unknown_exposure_and_cannot_resume(tmp_path, monkeypatch, suffix):
    from temper_ai.agent import single_call_agent as module
    cfg, sent = fixture_config(tmp_path), []
    class Crash(BaseException):
        pass
    original = module._write_once
    def crash(root, name, data):
        original(root, name, data)
        if name.endswith("." + suffix):
            raise Crash()
    def handler(request):
        sent.append(1)
        return httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler)
    monkeypatch.setattr(module, "_write_once", crash)
    with pytest.raises(Crash):
        run_slot(cfg, provider)
    root = Path(cfg["single_call"]["output_root"])
    claim = json.loads((root / "A1.claim").read_text())
    assert Decimal(claim["reservation_usd"]) > 0
    assert claim["binding_id"] == cfg["single_call"]["binding_id"]
    assert not (root / "A1.attempt.json").exists() and len(sent) == 1
    monkeypatch.setattr(module, "_write_once", original)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt is None and len(sent) == 1
    assert claim == json.loads((root / "A1.claim").read_text())


@pytest.mark.parametrize("usage", [{}, {"input_tokens": 10}])
def test_unknown_usage_is_null_cost_and_full_reservation(tmp_path, monkeypatch, usage):
    cfg = fixture_config(tmp_path, "B")
    provider = fake_codex(monkeypatch, lambda request: httpx.Response(200, content=codex_events(usage=usage), headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and attempt["cost_state"] == "UNKNOWN"
    assert attempt["list_price_usd"] is None
    assert attempt["unknown_exposure_usd"] == attempt["reservation_usd"] > 0
    assert call["usage"]["cache_read_input_tokens"] is None
    assert_schema(attempt)


def test_shaped_prefix_in_reservation_and_all_input_part_digests(tmp_path, monkeypatch):
    from temper_ai.llm.providers import anthropic as module
    cfg = fixture_config(tmp_path)
    sent = []
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"}))[1])
    prefix = "FAKE-SHAPED-SYSTEM-" * 1000
    class Shaper:
        def shape(self, body):
            body["system"] = [{"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}}]
            return body
        def client_headers(self):
            return {}
    monkeypatch.setattr(module, "get_oauth_shaper", lambda: Shaper())
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and len(sent) == 1
    assert call["input_parts"][0] == {"kind": "system", "ordinal": 0, "bytes": len(prefix.encode()), "sha256": digest(prefix.encode())}
    assert call["serialized_body_bytes"] > len(prefix.encode()) + len(PROMPT)
    assert attempt["reservation_usd"] > len(prefix.encode()) / 1_000_000
    cfg2 = fixture_config(tmp_path / "too-small")
    cfg2["single_call"]["cost_cap_usd"] = (len(PROMPT) + 2000) / 1_000_000
    denied, attempt2, _, _ = run_slot(cfg2, provider)
    assert denied.status == Status.FAILED and len(sent) == 1 and attempt2["transmissions"] == 0


def test_documented_max_not_nominal_limit_and_receipt_failure(tmp_path, monkeypatch):
    from temper_ai.agent import single_call_agent as module
    cfg = fixture_config(tmp_path, "B")
    cfg["single_call"]["cost_cap_usd"] = 0.004
    sent = []
    provider = fake_codex(monkeypatch, lambda request: (sent.append(1), httpx.Response(200, content=codex_events(), headers={"content-type": "text/event-stream"}))[1])
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and not sent and attempt["transmissions"] == 0
    cfg2 = fixture_config(tmp_path / "receipt", "B")
    original = module._write_once
    def fail_attempt(root, name, data):
        if name.endswith(".attempt.json"):
            raise OSError("SYNTHETIC_PRIVATE_RECEIPT_137")
        return original(root, name, data)
    monkeypatch.setattr(module, "_write_once", fail_attempt)
    failed, attempt2, _, _ = run_slot(cfg2, provider)
    assert failed.status == Status.FAILED and attempt2 is None and len(sent) == 1
    assert failed.structured_output["cost_state"] == "UNKNOWN"
    assert failed.structured_output["receipt_persisted"] is False


@pytest.mark.parametrize("umask", [0, 0o077])
def test_explicit_file_modes_and_empty_answer(tmp_path, monkeypatch, umask):
    cfg = fixture_config(tmp_path)
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=anthropic_events(answer=""), headers={"content-type": "text/event-stream"}))
    old = os.umask(umask)
    try:
        result, attempt, _, _ = run_slot(cfg, provider)
    finally:
        os.umask(old)
    root = Path(cfg["single_call"]["output_root"])
    assert result.status == Status.COMPLETED and attempt["transmissions"] == 1
    assert (root / "A1.raw").stat().st_size == 0
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir())


@pytest.mark.parametrize("bad", ["symlink", "ancestor-symlink", "owner", "nlink"])
def test_private_fd_and_content_binding_guards(tmp_path, monkeypatch, bad):
    cfg, sent = fixture_config(tmp_path), []
    root = Path(cfg["single_call"]["output_root"])
    if bad == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        cfg["single_call"]["output_root"] = str(alias)
    elif bad == "ancestor-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        cfg["single_call"]["output_root"] = str(alias / "out")
    elif bad == "owner":
        monkeypatch.setattr(os, "geteuid", lambda: -1)
    else:
        original = os.fstat
        def hardlink(fd):
            value = original(fd)
            if value.st_mode & 0o170000 == 0o100000:
                return SimpleNamespace(st_mode=value.st_mode, st_uid=value.st_uid, st_nlink=2)
            return value
        monkeypatch.setattr(os, "fstat", hardlink)
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    result, _, _, _ = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED


def test_strict_sdk_retry_option_learned_set_skip_and_no_cache(tmp_path, monkeypatch):
    from temper_ai.llm.providers import anthropic as module
    cfg, options, timeouts, safe = fixture_config(tmp_path), [], [], []
    cfg["single_call"].update(temperature=0.2, thinking_budget=64)
    def handler(request):
        body = json.loads(request.content)
        safe.append("cache_control" not in request.content.decode() and body.get("temperature") == 0.2
                    and body.get("thinking", {}).get("budget_tokens") == 64)
        return httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler)
    shared = provider._client_for(provider._named["FAKE-named"].token)
    original = shared.with_options
    def with_options(**kwargs):
        options.append(kwargs.get("max_retries"))
        timeouts.append(kwargs.get("timeout"))
        return original(**kwargs)
    monkeypatch.setattr(shared, "with_options", with_options)
    class NeverTouch(set):
        def __contains__(self, value):
            raise AssertionError("learned set read")
        def add(self, value):
            raise AssertionError("learned set write")
    monkeypatch.setattr(module, "_NO_TEMPERATURE", NeverTouch([cfg["model"]]))
    monkeypatch.setattr(module, "_NO_VISIBLE_THINKING", NeverTouch([cfg["model"]]))
    result, _, _, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and options == [0] and safe == [True]
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 895


def test_default_false_anthropic_request_byte_identical(monkeypatch):
    hashes = []
    def handler(request):
        hashes.append(digest(request.content))
        return httpx.Response(200, json={"id": "msg_FAKE137", "type": "message", "role": "assistant",
            "model": "claude-opus-5-5", "content": [{"type": "text", "text": "synthetic"}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}})
    provider = fake_anthropic(monkeypatch, handler)
    args = {"model": "claude-opus-5-5", "max_tokens": 1000, "token": "FAKE-named"}
    provider.complete([{"role": "user", "content": "synthetic-fixed"}], **args)
    provider.complete([{"role": "user", "content": "synthetic-fixed"}], single_send=False, **args)
    assert len(hashes) == 2 and hashes[0] == hashes[1]


def test_default_false_codex_request_byte_identical(monkeypatch):
    from temper_ai.llm.providers.openai import OpenAILLM
    from temper_ai.llm.providers.openai_codex import CodexTransport, codex_url
    hashes = []
    def handler(request):
        hashes.append(digest(request.content))
        return httpx.Response(200, content=codex_events(), headers={"content-type": "text/event-stream"})
    transport = CodexTransport.__new__(CodexTransport)
    transport.model, transport.token = "gpt-6.1-sol", "FAKE-no-credential-lookup"
    transport.account_id, transport.url = "FAKE-account", codex_url(None)
    transport._client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    provider = OpenAILLM.__new__(OpenAILLM)
    provider._codex = transport
    try:
        provider.complete([{"role": "user", "content": "synthetic-fixed"}], model="gpt-6.1-sol")
        provider.complete([{"role": "user", "content": "synthetic-fixed"}], single_send=False, model="gpt-6.1-sol")
    finally:
        transport._client.close()
    assert len(hashes) == 2 and hashes[0] == hashes[1]


def test_closed_world_overrides_api_key_and_missing_control_refuse(monkeypatch):
    from temper_ai.llm.providers.anthropic import AnthropicLLM
    from temper_ai.llm.providers.openai import OpenAILLM
    from temper_ai.llm.single_send import SingleSendError
    reached = []
    class Override(AnthropicLLM):
        def complete(self, messages, **kwargs):
            reached.append("override")
        def stream(self, messages, on_chunk=None, **kwargs):
            reached.append("stream override")
    class Inherited(Override):
        pass
    for cls in (Override, Inherited):
        provider = cls.__new__(cls)
        with pytest.raises(SingleSendError):
            provider.complete([], single_send=True)
        with pytest.raises(SingleSendError):
            provider.stream([], single_send=True)
    openai = OpenAILLM.__new__(OpenAILLM)
    openai.auth_mode, openai._codex = "api_key", None
    with pytest.raises(SingleSendError):
        openai.complete([], single_send=True)
    provider = fake_anthropic(monkeypatch, lambda request: (reached.append("request"), httpx.Response(500))[1])
    with pytest.raises(SingleSendError):
        provider.complete([], single_send=True)
    assert not reached


@pytest.mark.parametrize("family", ["A", "B"])
def test_callback_bypass_and_bad_auth_cannot_send(tmp_path, monkeypatch, family):
    from temper_ai.llm.single_send import SingleSendControl, SingleSendError
    cfg, sent = fixture_config(tmp_path, family), []
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1]) if family == "A" else fake_codex(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    control = SingleSendControl(time.monotonic() + 900, lambda metadata: None)
    with pytest.raises(SingleSendError):
        provider.stream([], on_chunk=lambda chunk: sent.append("chunk"), single_send=True, send_control=control)
    if family == "A":
        provider.auth_mode = "api_key"
    else:
        cfg["single_call"]["token"] = "FAKE-forbidden"
    result, _, _, _ = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED


def test_request_hook_refuses_repeat_and_post_gate_body_drift():
    from temper_ai.llm.single_send import SingleSendControl, SingleSendError
    body = {"model": "FAKE", "messages": [{"role": "user", "content": "fixed"}], "stream": True, "max_tokens": 1}
    request = httpx.Request("POST", "https://example.invalid", json=body)
    calls = []
    control = SingleSendControl(time.monotonic() + 900, lambda metadata: calls.append(1))
    control.request_start(request)
    with pytest.raises(SingleSendError, match="retry"):
        control.request_start(request)
    assert calls == [1] and len(control.transmission_ids) == 1
    def change(metadata):
        body["max_tokens"] = 2
        request._content = json.dumps(body).encode()
    other = SingleSendControl(time.monotonic() + 900, change)
    with pytest.raises(SingleSendError, match="strict_parser"):
        other.request_start(request)
    assert not other.transmission_ids


def test_anthropic_end_turn_without_message_stop_is_still_partial(tmp_path, monkeypatch):
    cfg, sent = fixture_config(tmp_path), []
    body = anthropic_events().split(b"event: message_stop")[0]
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(200,
        content=body, headers={"content-type": "text/event-stream"}))[1])
    result, attempt, _, _ = run_slot(cfg, provider)
    assert sent == [1] and result.status == Status.FAILED
    assert attempt["terminal"] == "FAILED" and attempt["failure_reasons"] == ["partial"]
    assert Path(cfg["single_call"]["output_root"], "A1.raw").read_bytes() == ANSWER.encode()
    assert_schema(attempt)


def test_codex_truncation_keeps_reported_usage_id_and_exact_raw(tmp_path, monkeypatch):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    cfg, sent = fixture_config(tmp_path, "B"), []
    event = {"type": "response.incomplete", "response": {"id": "resp_FAKE137", "status": "incomplete",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}}
    first = {"type": "response.output_text.delta", "delta": ANSWER}
    body = "".join("data: " + json.dumps(e) + "\n\n" for e in (first, event)).encode()
    provider = fake_codex(monkeypatch, lambda request: (sent.append(1), httpx.Response(200,
        content=body, headers={"content-type": "text/event-stream"}))[1])
    result, attempt, _, _ = run_slot(cfg, provider)
    root = Path(cfg["single_call"]["output_root"])
    call = json.loads((root / "B1.call.json").read_text())
    pricing = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert sent == [1] and result.status == Status.FAILED
    assert attempt["terminal"] == "FAILED" and attempt["failure_reasons"] == ["truncation"]
    assert call["response_id"] == "resp_FAKE137" and call["stop_reason"] == "incomplete"
    assert (root / "B1.raw").read_bytes() == ANSWER.encode()
    assert call["usage"]["input_tokens"] == 10 and call["usage"]["output_tokens"] == 5
    assert attempt["usage_state"] == attempt["cost_state"] == "KNOWN"
    assert Decimal(str(attempt["list_price_usd"])) == recompute_list_price_usd(call, pricing)
    assert_schema(attempt)
    Draft202012Validator(json.loads((REPO / "docs/schemas/context-t1-call.v1.schema.json").read_text())).validate(call)


@pytest.mark.parametrize("bad", ["provider", "model", "route"])
def test_codex_frozen_binding_cannot_alias_provider_model_or_route(tmp_path, monkeypatch, bad):
    """H-GUARD-137-3: the fake exists under the alias, so registry lookup can't mask this guard."""
    cfg, sent = fixture_config(tmp_path, "B"), []
    if bad == "provider":
        cfg["provider"] = "openai_codex"
    elif bad == "model":
        cfg["model"] = "FAKE-not-the-frozen-model"
    else:
        cfg["single_call"]["route"] = "FAKE-not-the-frozen-route"
    provider = fake_codex(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and not sent
    assert attempt["terminal"] == "NOT_MEASURED" and attempt["failure_reasons"] == ["auth"]
    assert_schema(attempt)


def test_private_root_owner_check_is_independent_of_new_file_owner_check(tmp_path, monkeypatch):
    from temper_ai.agent.single_call_agent import _private_root
    from temper_ai.llm.single_send import SingleSendError
    root = tmp_path / "owned-root"
    root.mkdir(mode=0o700)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        monkeypatch.setattr(os, "geteuid", lambda: -1)
        with pytest.raises(SingleSendError, match="strict_parser"):
            _private_root(fd)
    finally:
        os.close(fd)
    assert not tuple(root.iterdir())


@pytest.mark.parametrize("family", ["A", "B"])
def test_deadline_event_stops_before_requesting_another_item(tmp_path, monkeypatch, family):
    """H-GUARD-137-3: isolate each event check from watchdog/final-check backstops."""
    from temper_ai.agent import single_call_agent as agent_module
    from temper_ai.llm import single_send as module
    cfg, sent, read_past = fixture_config(tmp_path, family), [], []
    now = [100.0]
    fake_time = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(module, "time", fake_time)
    monkeypatch.setattr(agent_module, "time", fake_time)
    class ControlledWatchdog:
        def __init__(self, control):
            self.control = control
            self.thread = SimpleNamespace(is_alive=lambda: False)
        def start(self):
            pass
        def disarm_join(self):
            self.control.close_owned()
            return True
    monkeypatch.setattr(module, "BoundedWatchdog", ControlledWatchdog)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            if family == "A":
                events = anthropic_events()
                yield events[:events.index(b"event: content_block_start")]
            else:
                yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
            now[0] = 1000.0
            # SDK filters ping events; this is a valid SDK-visible event instead.
            yield (b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n' if family == "A"
                   else b'data: {"type":"response.in_progress"}\n\n')
            read_past.append(1)
            raise AssertionError("consumed after the deadline event")
    def handler(request):
        sent.append(1)
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert sent == [1] and not read_past and result.status == Status.FAILED
    assert attempt["failure_reasons"] == ["timeout"]
    assert attempt["cost_state"] == "UNKNOWN" and attempt["cleanup"] == "CONFIRMED"


def test_log_factory_redacts_exception_details_never_drops_and_resets(caplog):
    from temper_ai.llm.single_send import metadata_only_logs
    caplog.set_level(logging.DEBUG)
    logger = logging.getLogger("synthetic-single-send-137")
    secret = "SYNTHETIC_EXCEPTION_AND_ARGUMENT_137"
    levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]
    with metadata_only_logs():
        with metadata_only_logs():
            for level in levels:
                try:
                    raise ValueError(secret)
                except ValueError:
                    logger.log(level, "%s", secret, exc_info=True, stack_info=True)
    protected = [row for row in caplog.records if row.name == logger.name]
    assert len(protected) == len(levels)
    assert all(secret not in row.getMessage() and not row.args and row.exc_info is None
               and row.exc_text is None and row.stack_info is None for row in protected)
    logger.info("normal-outside-scope-137")
    assert caplog.records[-1].getMessage() == "normal-outside-scope-137"
    with pytest.raises(ValueError):
        with metadata_only_logs():
            raise ValueError("known-error")
    logger.info("normal-after-exception-137")
    assert caplog.records[-1].getMessage() == "normal-after-exception-137"


def test_watchdog_close_logs_scoped_and_join_is_bounded(monkeypatch, caplog):
    from temper_ai.llm import single_send as module
    caplog.set_level(logging.INFO)
    now = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    entered, release = threading.Event(), threading.Event()
    def blocked_close():
        entered.set()
        release.wait(2)
        logging.getLogger("synthetic-watchdog-137").error("SYNTHETIC_CLEANUP_PROSE_137")
    control = module.SingleSendControl(1000.0, lambda metadata: None)
    control.own(blocked_close)
    now[0] = 999.99
    started = time.monotonic()
    try:
        control.finish()
        assert time.monotonic() - started < 0.5 and entered.is_set()
        assert control.cleanup_uncertain and control.failure_reason == "timeout"
    finally:
        release.set()
        control._watchdog.thread.join(timeout=1)
    rows = [row for row in caplog.records if row.name == "synthetic-watchdog-137"]
    assert len(rows) == 1 and "SYNTHETIC_CLEANUP_PROSE_137" not in rows[0].getMessage()


@pytest.mark.parametrize("family", ["A", "B"])
def test_deadline_fake_clock_closes_stream_after_one_send(tmp_path, monkeypatch, family):
    """Use a strictly late clock: exact deadline is still within cleanup's bound.

    The first proof stopped exactly at 900 s but demanded UNCERTAIN; Codex had
    truthfully closed by then. One tick past must yield timeout and UNCERTAIN.
    """
    from temper_ai.agent import single_call_agent as agent_module
    from temper_ai.llm import single_send as module
    cfg, sent = fixture_config(tmp_path, family), []
    now = [100.0]
    fake_time = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(module, "time", fake_time)
    monkeypatch.setattr(agent_module, "time", fake_time)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            if family == "A":
                events = anthropic_events()
                marker = b"event: message_delta"
                yield events[:events.index(marker)]
                now[0] = 1001.0
                yield events[events.index(marker):]
            else:
                yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
                now[0] = 1001.0
                yield codex_events()
    def handler(request):
        sent.append(1)
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert len(sent) == 1 and result.status == Status.FAILED
    assert attempt["failure_reasons"] == ["timeout"] and attempt["cleanup"] == "UNCERTAIN"
    assert attempt["cost_state"] == "UNKNOWN"
    assert attempt["dispatch_monotonic_s"] == 100.0 and attempt["deadline_monotonic_s"] == 1000.0


def test_missing_root_is_not_created_and_unsupported_input_not_traversed(tmp_path, monkeypatch):
    """A clean second phase must get a clean fake reply, not the old fake 500.

    Missing root must never reach it; once provisioned, ignoring input_data must
    complete once without traversing it. Either a send early or failure late bites.
    """
    from temper_ai.agent.single_call_agent import SingleCallAgent
    cfg, sent = fixture_config(tmp_path), []
    root = Path(cfg["single_call"]["output_root"])
    root.rmdir()
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(200,
        content=anthropic_events(), headers={"content-type": "text/event-stream"}))[1])
    result, _, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and not sent and not root.exists()
    root.mkdir(mode=0o700)
    class DoNotRead(dict):
        def __iter__(self):
            raise AssertionError("input_data content traversed")
        def __getitem__(self, key):
            raise AssertionError("input_data content read")
    context, _ = fixture_context(provider)
    result = SingleCallAgent(cfg).run(DoNotRead(secret="SYNTHETIC_UPSTREAM_CONTENT_137"), context)
    assert result.status == Status.COMPLETED and len(sent) == 1
    assert "SYNTHETIC_UPSTREAM_CONTENT_137" not in result.output


def test_documented_max_both_codex_bound_modes_and_tool_refusal(tmp_path, monkeypatch):
    for case in ("request_limit", "tool"):
        cfg = fixture_config(tmp_path / case, "B")
        f = cfg["single_call"]
        if case == "request_limit":
            price_path = Path(f["pricing_path"])
            price = json.loads(price_path.read_text())
            model = price["models"][cfg["model"]]
            model.update(output_bound_mode="request_limit", request_limit_evidence="https://example.invalid/verified-limit")
            price_path.write_text(json.dumps(price))
            f["pricing_sha256"] = digest(price_path.read_bytes())
        sent = []
        def handler(request):
            sent.append(1)
            if case == "tool":
                data = b'data: {"type":"response.output_item.added","item":{"type":"function_call"}}\n\n'
            else:
                data = codex_events()
            return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
        provider = fake_codex(monkeypatch, handler)
        if case == "request_limit":
            from temper_ai.llm.single_send import SingleSendControl
            control = SingleSendControl(time.monotonic() + 900, lambda metadata: None)
            result = provider.complete([{"role": "user", "content": "synthetic-fixed"}],
                single_send=True, single_send_control=control, model="gpt-6.1-sol",
                max_tokens=1000, output_bound_mode="request_limit",
                request_limit_evidence="https://example.invalid/verified-limit")
            assert result.finish_reason == "stop" and control.request["parameters"]["max_output_tokens"] == 1000
        else:
            result, attempt, _, _ = run_slot(cfg, provider)
            assert result.status == Status.FAILED and attempt["failure_reasons"] == ["partial"]
        assert sent == [1]


@pytest.mark.parametrize("missing", [
    "prompt_path", "prompt_sha256", "prompt_bytes", "output_root", "slot", "family",
    "route", "auth_mode", "max_tokens", "output_bound_mode", "deadline_s", "cost_cap_usd",
    "pricing_path", "pricing_sha256", "experiment_id", "binding_id", "source_sha256",
    "config_sha256", "packet_sha256",
])
def test_every_required_input_is_a_zero_send_guard(tmp_path, monkeypatch, missing):
    cfg, sent = fixture_config(tmp_path), []
    root = Path(cfg["single_call"]["output_root"])
    del cfg["single_call"][missing]
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    from temper_ai.agent.single_call_agent import SingleCallAgent
    ctx, _ = fixture_context(provider)
    result = SingleCallAgent(cfg).run({}, ctx)
    assert result.status == Status.FAILED and not sent and provider._test_request_starts == 0
    path = root / "A1.attempt.json"
    if path.exists():
        attempt = json.loads(path.read_text())
        assert attempt["terminal"] == "NOT_MEASURED" and attempt["transmissions"] == 0
        assert_schema(attempt)


@pytest.mark.parametrize("case", ["nan", "negative", "duplicate", "missing", "source", "utf8", "prompt-symlink", "pricing-symlink", "long-read", "route", "model", "family", "slot", "auth", "bound", "extra", "collision"])
def test_closed_fixed_inputs_prices_and_output_collisions(tmp_path, monkeypatch, case):
    cfg, sent = fixture_config(tmp_path), []
    f = cfg["single_call"]
    price_path, prompt_path = Path(f["pricing_path"]), Path(f["prompt_path"])
    if case in ("nan", "negative", "duplicate", "missing", "source"):
        if case == "duplicate":
            price_path.write_text('{"currency":"USD","currency":"USD","models":{}}')
        elif case == "missing":
            price_path.unlink()
        else:
            price = json.loads(price_path.read_text())
            model = price["models"][cfg["model"]]
            if case == "source":
                model["request_limit_evidence"] = "unproven"
            else:
                model["input_usd_per_million"] = float("nan") if case == "nan" else -1
            price_path.write_text(json.dumps(price))
        if price_path.exists():
            f["pricing_sha256"] = digest(price_path.read_bytes())
    elif case == "utf8":
        prompt_path.write_bytes(b"\xff")
        f.update(prompt_bytes=1, prompt_sha256=digest(b"\xff"))
    elif case in ("prompt-symlink", "pricing-symlink"):
        path = prompt_path if case == "prompt-symlink" else price_path
        actual = path.with_suffix(".real")
        path.rename(actual)
        path.symlink_to(actual)
    elif case == "long-read":
        prompt_path.write_bytes(PROMPT + b"extra")
    elif case == "model":
        cfg["model"] = "wrong-model"
    elif case == "extra":
        f["shell"] = "forbidden"
    elif case == "collision":
        (Path(f["output_root"]) / "A1.raw").write_bytes(b"existing")
    else:
        key = {"bound": "output_bound_mode", "auth": "auth_mode"}.get(case, case)
        f[key] = "unsupported"
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    result, _, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and not sent and provider._test_request_starts == 0
    if case == "collision":
        assert (Path(f["output_root"]) / "A1.raw").read_bytes() == b"existing"


@pytest.mark.parametrize("name", [None, "", "unrecognised"])
def test_native_named_token_guard_has_own_auth_failure(monkeypatch, name):
    from temper_ai.llm.single_send import SingleSendControl, SingleSendError
    sent = []
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    control = SingleSendControl(time.monotonic() + 900, lambda metadata: None)
    with pytest.raises(SingleSendError, match="auth"):
        provider.complete([{"role": "user", "content": "synthetic"}], single_send=True,
            single_send_control=control, model="claude-opus-5-5", max_tokens=1000, token=name)
    assert not sent and not control.transmission_ids


@pytest.mark.parametrize("strict", [False, True])
def test_pinned_limit_detail_is_metadata_only_only_when_requested(monkeypatch, strict):
    """H-GUARD-137-2: the flag's own detail branch, not the resend-route guard."""
    from temper_ai.llm.token_pool import TokenCooling
    sent = []
    provider = fake_anthropic(monkeypatch, lambda request: pytest.fail("network forbidden"))
    marker = "SYNTHETIC_PROVIDER_PROSE_137"
    error = anthropic.RateLimitError(marker, response=httpx.Response(429,
        request=httpx.Request("POST", "https://example.invalid/FAKE")), body={})
    def fail(client):
        sent.append(client is provider._test_sdk)
        raise error
    with pytest.raises(TokenCooling) as failure:
        provider._call_pinned("FAKE-named", fail, "claude-opus-5-5", single_send=strict)
    assert sent == [True]
    assert (marker in str(failure.value)) is (not strict)
    if strict:
        assert str(failure.value).endswith(": RateLimitError")


@pytest.mark.parametrize("phase", ["durable-gate", "request"])
def test_crash_after_durable_claim_has_recoverable_unknown_reservation(tmp_path, monkeypatch, phase):
    from temper_ai.agent import single_call_agent as module
    cfg, sent = fixture_config(tmp_path), []
    class Crash(BaseException):
        pass
    original = module._Attempt.prepare_and_make_durable
    def at_gate(state, metadata):
        original(state, metadata)
        if phase == "durable-gate":
            raise Crash()
    monkeypatch.setattr(module._Attempt, "prepare_and_make_durable", at_gate)
    def handler(request):
        sent.append(1)
        raise Crash()
    provider = fake_anthropic(monkeypatch, handler)
    with pytest.raises(Crash):
        run_slot(cfg, provider)
    root = Path(cfg["single_call"]["output_root"])
    assert sorted(p.name for p in root.iterdir()) == ["A1.claim"]
    claim = json.loads((root / "A1.claim").read_text())
    assert Decimal(claim["reservation_usd"]) > 0
    assert claim["binding_id"] == cfg["single_call"]["binding_id"]
    assert len(sent) == (1 if phase == "request" else 0)
    denied, _, _, _ = run_slot(cfg, provider)
    assert denied.status == Status.FAILED
    assert len(sent) == (1 if phase == "request" else 0)


@pytest.mark.parametrize("skip", [False, True])
def test_policy_denial_is_metadata_only_and_not_skipped(tmp_path, monkeypatch, skip):
    from temper_ai.agent.single_call_agent import SingleCallAgent
    cfg, sent, checks = fixture_config(tmp_path), [], []
    def evaluate(action, params, totals):
        checks.append((str(action), params, totals))
        return SimpleNamespace(action="deny")
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    ctx, _ = fixture_context(provider)
    ctx.tool_executor = SimpleNamespace(skip_policies=skip, run_cost_usd=0, run_tokens=0,
                                       track_usage=lambda *args: None,
                                       policy_engine=SimpleNamespace(evaluate=evaluate))
    result = SingleCallAgent(cfg).run({}, ctx)
    assert result.status == Status.FAILED and not sent and len(checks) == 1
    assert set(checks[0][1]) == {"provider", "model", "reservation_usd", "max_tokens"}
    assert_metadata_only(checks)


@pytest.mark.parametrize("case", ["pre-cancel", "preflight-expired"])
def test_preflight_uses_claim_deadline_without_reset(tmp_path, monkeypatch, case):
    from temper_ai.agent import single_call_agent as module
    from temper_ai.llm import single_send as transport
    cfg, sent = fixture_config(tmp_path), []
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(transport, "time", clock)
    monkeypatch.setattr(module, "time", clock)
    original = module._Attempt.validate
    def validate(state):
        value = original(state)
        now[0] = 996.0
        return value
    if case == "preflight-expired":
        monkeypatch.setattr(module._Attempt, "validate", validate)
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    ctx, _ = fixture_context(provider)
    if case == "pre-cancel":
        ctx.cancel_event.set()
    result = module.SingleCallAgent(cfg).run({}, ctx)
    assert result.status == Status.FAILED and not sent and provider._test_request_starts == 0
    attempt = json.loads((Path(cfg["single_call"]["output_root"]) / "A1.attempt.json").read_text())
    assert attempt["dispatch_monotonic_s"] == 100.0 and attempt["deadline_monotonic_s"] == 1000.0
    assert attempt["failure_reasons"] == ["cancel" if case == "pre-cancel" else "timeout"]


def test_timeout_margin_silent_watchdog_and_cancel_close_once(monkeypatch):
    from temper_ai.llm import single_send as module
    now = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    control = module.SingleSendControl(1000.0, lambda metadata: None)
    assert control.remaining() == 895.0
    for reason in ("timeout", "cancel"):
        now[0] = 100.0
        cancel = threading.Event()
        control = module.SingleSendControl(1000.0, lambda metadata: None, cancel)
        closed = []
        control._closers.append(lambda: closed.append(1))
        if reason == "timeout":
            now[0] = 995.0
        else:
            cancel.set()
        watchdog = module.BoundedWatchdog(control)
        watchdog._run()  # deterministic timer entry, no real sleep/thread race
        assert closed == [1] and control.failure_reason == reason
        assert not control.transmission_ids


def test_long_thinking_stream_under_same_deadline_is_clean(tmp_path, monkeypatch):
    from temper_ai.agent import single_call_agent as agent_module
    from temper_ai.llm import single_send as module
    cfg, sent = fixture_config(tmp_path), []
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(agent_module, "time", clock)
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'event: ping\ndata: {"type":"ping"}\n\n'
            now[0] += 121.0
            yield b'event: ping\ndata: {"type":"ping"}\n\n'
            yield anthropic_events()
    def handler(request):
        sent.append(1)
        return httpx.Response(200, stream=Stream(), headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and sent == [1]
    assert attempt["deadline_monotonic_s"] == 1000.0 and attempt["cleanup_monotonic_s"] == 221.0


@pytest.mark.parametrize("case", ["malformed", "failed", "unsafe-id", "over-reservation", "no-id"])
def test_codex_terminal_protocol_safe_metadata_and_actual_cost(tmp_path, monkeypatch, case):
    cfg, sent = fixture_config(tmp_path, "B"), []
    def handler(request):
        sent.append(1)
        if case == "malformed":
            data = b'data: not-json\n\n'
        elif case == "failed":
            data = b'data: {"type":"response.failed","response":{"error":{"message":"SYNTHETIC_ERROR_PROSE_137"}}}\n\n'
        else:
            data = codex_events(usage={"input_tokens": 10, "output_tokens": 1000000}) if case == "over-reservation" else codex_events()
            if case == "unsafe-id":
                data = data.replace(b"resp_FAKE137", b"SYNTHETIC_UNSAFE_RESPONSE_ID_137")
            elif case == "no-id":
                data = data.replace(b'"id": "resp_FAKE137", ', b"")
        return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})
    provider = fake_codex(monkeypatch, handler)
    result, attempt, call, _ = run_slot(cfg, provider)
    assert sent == [1]
    if case in ("unsafe-id", "no-id"):
        assert result.status == Status.COMPLETED and call["response_id"] is None
    else:
        assert result.status == Status.FAILED
    assert "SYNTHETIC_UNSAFE_RESPONSE_ID_137" not in json.dumps(call)
    assert "SYNTHETIC_ERROR_PROSE_137" not in result.output
    assert_schema(attempt)


def test_log_factory_replacement_between_calls_cannot_remove_redaction(monkeypatch, caplog):
    """Hypothesis: a first-install boolean trusts a subsequently replaced factory.

    Evidence: logging.setLogRecordFactory is public and the old install returned
    solely on its cached bool. Recheck factory identity and wrap the current one.
    Measure all six sensitive fields plus a normal outside message; any protected
    marker or altered/dropped outside record falsifies the change.
    """
    from temper_ai.llm.single_send import metadata_only_logs
    caplog.set_level(logging.INFO)
    with metadata_only_logs():
        pass
    original = logging.getLogRecordFactory()
    def foreign_factory(*args, **kwargs):
        row = original(*args, **kwargs)
        row.msg = "SYNTHETIC_FOREIGN_FACTORY_137"
        row.exc_text = "SYNTHETIC_FOREIGN_FACTORY_137"
        return row
    monkeypatch.setattr(logging, "_logRecordFactory", foreign_factory)
    logger = logging.getLogger("synthetic-new-factory-137")
    with metadata_only_logs():
        logger.info("synthetic input")
    record = caplog.records[-1]
    assert "SYNTHETIC_FOREIGN_FACTORY_137" not in record.getMessage()
    assert record.args == () and record.exc_text is None and record.exc_info is None and record.stack_info is None
    logger.info("normal input")
    assert caplog.records[-1].getMessage() == "SYNTHETIC_FOREIGN_FACTORY_137"


@pytest.mark.parametrize("late", ["monotonic", "utc"])
def test_raw_cleanup_must_fit_both_real_sampled_bounds(tmp_path, monkeypatch, late):
    from datetime import timedelta

    from temper_ai.agent import single_call_agent as agent_module
    from temper_ai.llm import single_send as module
    cfg = fixture_config(tmp_path)
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(agent_module, "time", clock)
    initial_utc = module.utcnow()
    utc_late = [False]
    monkeypatch.setattr(module, "utcnow", lambda: initial_utc + timedelta(seconds=901 if utc_late[0] else 0))
    original = os.fsync
    def late_sync(fd):
        result = original(fd)
        if os.readlink(f"/proc/self/fd/{fd}").endswith("A1.raw"):
            if late == "monotonic":
                now[0] = 1001.0
            else:
                utc_late[0] = True
        return result
    monkeypatch.setattr(os, "fsync", late_sync)
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["terminal"] == "FAILED"
    assert attempt["failure_reasons"] == ["timeout"] and attempt["cleanup"] == "UNCERTAIN"
    assert attempt["cost_state"] == "UNKNOWN" and attempt["unknown_exposure_usd"] > 0
    # Write-once call observation precedes the late cleanup. The attempt may
    # downgrade it; it must never promote an UNKNOWN/non-durable observation.
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    assert call["cost_state"] == "KNOWN"
    price = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert float(recompute_list_price_usd(call, price)) == call["list_price_usd"]
    assert_schema(attempt)


def test_distinct_slots_have_fresh_sessions_and_no_live_timer_after_return(tmp_path, monkeypatch):
    from temper_ai.llm import single_send as module
    seen = []
    original = module.SingleSendControl.finish
    def finish(control):
        original(control)
        seen.append(control)
    monkeypatch.setattr(module.SingleSendControl, "finish", finish)
    cfg = fixture_config(tmp_path)
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"}))
    one, attempt_one, _, _ = run_slot(cfg, provider)
    cfg["single_call"]["slot"] = "A2"
    two, attempt_two, _, _ = run_slot(cfg, provider)
    assert one.status == two.status == Status.COMPLETED
    assert attempt_one["session_id"] != attempt_two["session_id"]
    assert attempt_one["run_id"] != attempt_two["run_id"]
    assert len(seen) == 2 and all(not control._watchdog.thread.is_alive() and not control._closers for control in seen)


@pytest.mark.parametrize("cached", [None, 0, 7])
@pytest.mark.parametrize("category", ["cache_read_input_tokens", "cache_creation_input_tokens"])
def test_reported_cache_categories_are_preserved_without_guessing_prices(tmp_path, monkeypatch, cached, category):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    cfg = fixture_config(tmp_path)
    usage = {"input_tokens": 10, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    usage[category] = cached
    # Replace the whole known object. The first fixture replaced only its
    # interior with another object and produced doubled braces, a false protocol
    # failure. Valid input must preserve each exact counter and complete once.
    data = anthropic_events().replace(b'{"input_tokens": 10, "output_tokens": 0}', json.dumps(usage).encode())
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=data, headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert call["usage"][category] == cached
    assert Path(call["raw_path"]).read_bytes() == ANSWER.encode()
    assert provider._test_request_starts == attempt["transmissions"] == 1
    assert result.status == Status.COMPLETED and attempt["terminal"] == "COMPLETED"
    assert attempt["usage_state"] == "KNOWN" and attempt["failure_reasons"] == []
    pricing = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    if cached:
        assert attempt["cost_state"] == call["cost_state"] == "UNKNOWN" and attempt["list_price_usd"] is None
        assert attempt["unknown_exposure_usd"] == attempt["reservation_usd"]
        assert recompute_list_price_usd(call, pricing) is None
    else:
        assert attempt["cost_state"] == "KNOWN" and attempt["unknown_exposure_usd"] == 0
        assert float(recompute_list_price_usd(call, pricing)) == attempt["list_price_usd"]
    assert_schema(attempt)


@pytest.mark.parametrize("missing", ["root", "claim", "output_bound", "deadline"])
def test_attempt_phase_invariants_fail_closed_before_any_request(tmp_path, monkeypatch, missing):
    from temper_ai.agent.single_call_agent import _Attempt
    from temper_ai.llm import single_send as module
    cfg, sent = fixture_config(tmp_path), []
    provider = fake_anthropic(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    ctx, _ = fixture_context(provider)
    state = _Attempt(cfg, ctx)
    state.claim_slot()
    state.validate()
    original = getattr(state, missing)
    setattr(state, missing, None)
    try:
        with pytest.raises(module.SingleSendError, match="strict_parser"):
            state.call() if missing == "deadline" else state.prepare_and_make_durable({})
        assert not sent
    finally:
        setattr(state, missing, original)
        state.close()


def test_incomplete_persistence_and_clock_state_never_claim_success(tmp_path):
    from temper_ai.agent.single_call_agent import _Attempt
    from temper_ai.llm import single_send as module
    cfg = fixture_config(tmp_path)
    ctx, _ = fixture_context(None)
    state = _Attempt(cfg, ctx)
    state.claimed = True
    with pytest.raises(module.SingleSendError, match="crash"):
        state.persist()
    state.start, state.started = module.paired_sample()
    assert not state.within_bounds(state.start, state.started)


@pytest.mark.parametrize("token", [None, "", "FAKE-other"])
@pytest.mark.parametrize("direct", [False, True])
def test_codex_refuses_token_field_presence_before_any_send(tmp_path, monkeypatch, token, direct):
    """Hypothesis: a value check lets token:null through the no-token contract.

    Presence, not truthiness, must refuse. Each fixed value must produce auth
    and zero initiated requests; a send or a non-auth result falsifies it.
    """
    from temper_ai.llm import single_send as module
    sent = []
    provider = fake_codex(monkeypatch, lambda request: (sent.append(1), httpx.Response(500))[1])
    target = provider._codex if direct else provider
    control = module.SingleSendControl(time.monotonic() + 900, lambda request: None)
    try:
        with pytest.raises(module.SingleSendError, match="auth"):
            target.complete([], model="gpt-6.1-sol", single_send=True, token=token,
                            output_bound_mode="documented_max", single_send_control=control)
        assert not sent and not control.transmission_ids
    finally:
        control.finish()


@pytest.mark.parametrize(("cached", "reasoning"), [
    (None, None), ({}, {}), ({"cached_tokens": None}, {"reasoning_tokens": None}),
    ({"cached_tokens": 0}, {"reasoning_tokens": 0}),
    ({"cached_tokens": 10}, {"reasoning_tokens": 5}),
    ({"cached_tokens": 7}, {"reasoning_tokens": 3}),
])
def test_codex_reported_subsets_are_preserved_and_priced_only_through_totals(tmp_path, monkeypatch, caplog, cached, reasoning):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    cfg = fixture_config(tmp_path, "B")
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
             "input_tokens_details": cached, "output_tokens_details": reasoning}
    provider = fake_codex(monkeypatch, lambda request: httpx.Response(200, content=codex_events(usage=usage), headers={"content-type": "text/event-stream"}))
    result, attempt, call, events = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and attempt["failure_reasons"] == []
    assert attempt["terminal"] == "COMPLETED" and attempt["usage_state"] == attempt["cost_state"] == "KNOWN"
    assert attempt["transmissions"] == provider._test_request_starts == 1
    assert call["usage"]["input_tokens_details"] == cached and call["usage"]["output_tokens_details"] == reasoning
    assert attempt["list_price_usd"] == call["list_price_usd"] == 0.000020 and attempt["unknown_exposure_usd"] == 0
    pricing = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert recompute_list_price_usd(call, pricing) == Decimal("0.000020")
    assert Path(call["raw_path"]).read_bytes() == ANSWER.encode()
    assert_metadata_only(asdict(result), events, [record.getMessage() for record in caplog.records])
    Draft202012Validator(json.loads((REPO / "docs/schemas/context-t1-call.v1.schema.json").read_text())).validate(call)
    assert_schema(attempt)


@pytest.mark.parametrize("usage", [
    {"input_tokens": -1, "output_tokens": 5},
    {"input_tokens": True, "output_tokens": 5},
    {"input_tokens": "10", "output_tokens": 5},
    {"input_tokens": 10.0, "output_tokens": 5},
    {"input_tokens": 10, "output_tokens": 5, "unexpected": 0},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 11}},
    {"input_tokens": 10, "output_tokens": 5, "output_tokens_details": {"reasoning_tokens": 6}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": -1}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": True}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": "1"}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 1.0}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": {"cached_tokens": 0, "unexpected": None}},
    {"input_tokens": 10, "output_tokens": 5, "input_tokens_details": []},
    {"output_tokens": 5, "input_tokens_details": {"cached_tokens": 0}},
    {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 1},
    [], 0, False,
])
def test_codex_malformed_or_outside_shape_usage_is_failed_unknown_once(tmp_path, monkeypatch, usage):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    cfg = fixture_config(tmp_path, "B")
    provider = fake_codex(monkeypatch, lambda request: httpx.Response(200, content=codex_events(usage=usage), headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["terminal"] == "FAILED"
    assert attempt["failure_reasons"] == ["strict_parser"]
    assert attempt["usage_state"] == attempt["cost_state"] == "UNKNOWN"
    assert attempt["list_price_usd"] is None and attempt["unknown_exposure_usd"] == attempt["reservation_usd"] > 0
    assert attempt["transmissions"] == provider._test_request_starts == 1
    assert call["response_id"] == "resp_FAKE137"
    assert Path(call["raw_path"]).read_bytes() == ANSWER.encode()
    pricing = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert recompute_list_price_usd(call, pricing) is None
    assert_schema(attempt)


@pytest.mark.parametrize("bad", ["negative", "extra"])
def test_anthropic_malformed_usage_fails_without_losing_answer_or_resending(tmp_path, monkeypatch, bad):
    cfg = fixture_config(tmp_path)
    usage = {"output_tokens": -1} if bad == "negative" else {"output_tokens": 5, "unexpected": 0}
    data = anthropic_events().replace(b'"usage": {"output_tokens": 5}', ('"usage": ' + json.dumps(usage)).encode())
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=data, headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["failure_reasons"] == ["strict_parser"]
    assert attempt["usage_state"] == attempt["cost_state"] == "UNKNOWN"
    assert attempt["unknown_exposure_usd"] == attempt["reservation_usd"] > 0
    assert attempt["transmissions"] == provider._test_request_starts == 1
    assert call["response_id"] == "msg_FAKE137" and Path(call["raw_path"]).read_bytes() == ANSWER.encode()
    assert_schema(attempt)


@pytest.mark.parametrize("shape", ["start-unmodelled", "absent"])
def test_anthropic_usage_fault_still_fails_this_harness_with_the_answer_kept(tmp_path, monkeypatch, shape):
    """The provider keeps the answer and reports the usage fault (#221); usage is
    what this harness measures, so the attempt still fails strict_parser."""
    cfg = fixture_config(tmp_path)
    start = b'"usage": {"input_tokens": 10, "output_tokens": 0}'
    data = anthropic_events()
    if shape == "start-unmodelled":
        data = data.replace(start, b'"usage": {"input_tokens": 10, "output_tokens": 0, "unexpected": 0}')
    else:
        data = data.replace(b', ' + start, b"").replace(b', "usage": {"output_tokens": 5}', b"")
        assert b"usage" not in data
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=data, headers={"content-type": "text/event-stream"}))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["failure_reasons"] == ["strict_parser"]
    assert attempt["usage_state"] == attempt["cost_state"] == "UNKNOWN"
    assert attempt["transmissions"] == provider._test_request_starts == 1
    assert call["response_id"] == "msg_FAKE137" and Path(call["raw_path"]).read_bytes() == ANSWER.encode()
    assert_schema(attempt)


@pytest.mark.parametrize("case", ["currency", "currency-missing", "model", "rate", "counter", "extra", "split",
                                  "float-rounds", "decimal-rounds"])
def test_price_recomputation_refuses_missing_unpriced_or_malformed_inputs(case):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    call = {"route": "anthropic-oauth-named-token", "model": "FAKE-model",
            "usage": {"input_tokens": 10, "output_tokens": 5}}
    pricing = {"currency": "USD", "models": {"FAKE-model": {"input_usd_per_million": 1, "output_usd_per_million": 2}}}
    assert recompute_list_price_usd(call, pricing) == Decimal("0.000020")
    if case == "currency":
        pricing["currency"] = "EUR"
    elif case == "currency-missing":
        del pricing["currency"]
    elif case == "model":
        del pricing["models"]["FAKE-model"]
    elif case == "rate":
        pricing["models"]["FAKE-model"]["input_usd_per_million"] = "NaN"
    elif case == "counter":
        call["usage"]["cache_creation_input_tokens"] = 1
    elif case == "extra":
        call["usage"]["extra"] = 0
    elif case == "float-rounds":
        # 2001 x rate / 1e6 = 0.000247037035036037034789; its JSON float rounds DOWN.
        call["usage"]["input_tokens"] = 2001
        pricing["models"]["FAKE-model"]["input_usd_per_million"] = "0.123456789123456789"
    elif case == "decimal-rounds":
        # Past 100 digits: a rounding Decimal context gives 0.000002 + 0.000010, a float-exact UNDERSTATEMENT.
        pricing["models"]["FAKE-model"]["input_usd_per_million"] = "0.2" + "0" * 120 + "1"
    else:
        call["route"] = "openai-codex-oauth"
        call["usage"]["input_tokens_details"] = {"cached_tokens": 11}
    assert recompute_list_price_usd(call, pricing) is None


def test_non_durable_call_evidence_never_claims_known_final_cost(tmp_path, monkeypatch):
    cfg = fixture_config(tmp_path)
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(200, content=anthropic_events(), headers={"content-type": "text/event-stream"}))
    original = os.fsync
    def fail_call_sync(fd):
        if os.readlink(f"/proc/self/fd/{fd}").endswith("A1.call.json"):
            raise OSError("SYNTHETIC fsync failure")
        return original(fd)
    monkeypatch.setattr(os, "fsync", fail_call_sync)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt is None
    assert result.metadata["cost_state"] == "UNKNOWN" and result.metadata["list_price_usd"] is None
    assert result.metadata["unknown_exposure_usd"] == result.metadata["reservation_usd"] > 0
    assert not result.metadata["receipt_persisted"] and provider._test_request_starts == 1


@pytest.mark.parametrize("family", ["A", "B"])
def test_reservation_a_json_number_would_round_is_refused_with_zero_sends(tmp_path, monkeypatch, family):
    """Hypothesis H-NUM-137-1: v1 carries reservation_usd as a JSON number.

    A 17-digit rate times the body bytes has more digits than a float keeps, so
    float() would understate it. It must be refused before the claim is durable.
    """
    cfg, sent = fixture_config(tmp_path, family), []
    f = cfg["single_call"]
    price = json.loads(Path(f["pricing_path"]).read_text())
    price["models"][cfg["model"]]["input_usd_per_million"] = 0.12345678912345678
    Path(f["pricing_path"]).write_text(json.dumps(price))
    f["pricing_sha256"] = digest(Path(f["pricing_path"]).read_bytes())
    def handler(request):
        sent.append(1)
        raise AssertionError("inexact reservation sent")
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, _, _ = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED
    assert result.structured_output["terminal"] == "NOT_MEASURED"
    assert attempt["transmissions"] == 0 and attempt["failure_reasons"] == ["strict_parser"]
    assert_schema(attempt)


@pytest.mark.parametrize("start", [214.510929166, 100.0])
def test_deadline_is_start_plus_900_as_d4_reads_it_on_a_fixed_clock(tmp_path, monkeypatch, start):
    """H-FLAKE-137-1: replay CI's monotonic sample every run, not by chance."""
    from temper_ai.agent import single_call_agent as agent_module
    from temper_ai.llm import single_send as module
    clock = SimpleNamespace(monotonic=lambda: start)
    monkeypatch.setattr(module, "time", clock)
    monkeypatch.setattr(agent_module, "time", clock)
    cfg = fixture_config(tmp_path)
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(
        200, content=anthropic_events(), headers={"content-type": "text/event-stream"}))
    result, attempt, _, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and attempt["dispatch_monotonic_s"] == start
    assert_deadline_as_d4_reads_it(attempt)
    assert_schema(attempt)


@pytest.mark.parametrize("sentinel", [PROMPT.decode(), ANSWER, REASONING], ids=["prompt", "answer", "reasoning"])
@pytest.mark.parametrize("sink", ["structured", "json", "double-json", "unicode-json", "log"])
def test_metadata_assertion_catches_decoded_and_structured_leaks(sentinel, sink):
    payload = {"nested": [{"value": sentinel}]}
    if sink == "json":
        payload = json.dumps(payload)
    elif sink == "double-json":
        payload = json.dumps(json.dumps(payload))
    elif sink == "unicode-json":
        payload = json.dumps(payload).replace("SYNTHETIC", r"\u0053YNTHETIC")
    elif sink == "log":
        payload = {"rendered": "prefix " + sentinel + " suffix"}
    with pytest.raises(AssertionError, match="content leaked to metadata"):
        assert_metadata_only(payload)


def test_metadata_assertion_allows_only_safe_synthetic_leaves():
    assert_metadata_only({"path": "/synthetic/out/A1.raw", "sha256": "a" * 64,
                          "usage": {"input_tokens": 10, "output_tokens": 5}},
                         json.dumps({"terminal": "COMPLETED", "transmissions": 1}))


@pytest.mark.parametrize("family", ["A", "B"])
@pytest.mark.parametrize("field", ["provider", "model", "route", "auth_mode", "pricing_sha256", "output_bound_mode"])
@pytest.mark.parametrize("rejected", [None, {}, ["FAKE-rejected"], "FAKE-rejected", "", ANSWER, json.dumps({"rejected": ANSWER})])
def test_rejected_call_identity_is_null_and_schema_valid(tmp_path, monkeypatch, caplog, family, field, rejected):
    cfg, sent = fixture_config(tmp_path, family), []
    target = cfg if field in ("provider", "model") else cfg["single_call"]
    target[field] = rejected
    caplog.set_level(logging.DEBUG)
    def handler(request):
        sent.append(1)
        raise AssertionError("rejected identity was sent")
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, call, events = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED
    assert attempt["terminal"] == "NOT_MEASURED" and attempt["transmissions"] == provider._test_request_starts == 0
    assert call[field] is None
    for key in ("provider", "model", "route", "auth_mode"):
        assert attempt[key] is call[key] is None
    assert call["usage_state"] == "UNKNOWN" and all(value is None for value in call["usage"].values())
    assert call["cost_state"] == "KNOWN" and call["list_price_usd"] == call["unknown_exposure_usd"] == 0
    assert_call_schema(call)
    assert_schema(attempt)
    assert_metadata_only(asdict(result), attempt, call, events,
                         [{"rendered": r.getMessage(), **vars(r)} for r in caplog.records])


@pytest.mark.parametrize("family", ["A", "B"])
@pytest.mark.parametrize("rejected", [0, -1, True, "10", ANSWER, {"value": ANSWER}, 1.0, 1.5, None])
def test_rejected_output_bound_stays_null_in_both_receipts(tmp_path, monkeypatch, caplog, family, rejected):
    cfg, sent = fixture_config(tmp_path, family), []
    fixed = cfg["single_call"]
    if family == "A":
        fixed["max_tokens"] = rejected
    else:
        path = Path(fixed["pricing_path"])
        pricing = json.loads(path.read_bytes())
        pricing["models"][cfg["model"]]["max_output_tokens"] = rejected
        path.write_text(json.dumps(pricing))
        fixed["pricing_sha256"] = digest(path.read_bytes())
    caplog.set_level(logging.DEBUG)
    def handler(request):
        sent.append(1)
        raise AssertionError("rejected output bound was sent")
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, call, events = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED
    assert attempt["terminal"] == "NOT_MEASURED" and attempt["transmissions"] == provider._test_request_starts == 0
    assert call["output_bound_tokens"] is None
    # An expected binding is not a verified call observation.
    assert attempt["pricing_sha256"] == fixed["pricing_sha256"]
    assert call["pricing_sha256"] == (fixed["pricing_sha256"] if family == "B" else None)
    for observation in (result.metadata, attempt, call):
        assert observation["cost_state"] == "KNOWN"
        assert observation["list_price_usd"] == observation["unknown_exposure_usd"] == 0
        assert observation["usage_state"] == "UNKNOWN"
    assert all(value is None for value in call["usage"].values())
    assert_call_schema(call)
    assert_schema(attempt)
    assert_metadata_only(asdict(result), attempt, call, events,
                         [{"rendered": r.getMessage(), **vars(r)} for r in caplog.records])


@pytest.mark.parametrize("family", ["A", "B"])
def test_unverified_price_digest_is_null_even_when_it_has_valid_hex_shape(tmp_path, monkeypatch, family):
    cfg = fixture_config(tmp_path, family)
    cfg["single_call"]["pricing_sha256"] = "f" * 64
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(500)) if family == "A" else fake_codex(monkeypatch, lambda request: httpx.Response(500))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["transmissions"] == provider._test_request_starts == 0
    assert call["pricing_sha256"] is None
    assert call["provider"] == cfg["provider"] and call["model"] == cfg["model"]
    assert attempt["pricing_sha256"] == cfg["single_call"]["pricing_sha256"]
    assert all(attempt[key] == call[key] for key in ("provider", "model", "route", "auth_mode"))
    assert_schema(attempt)
    assert_call_schema(call)


@pytest.mark.parametrize("field", ["provider", "model"])
def test_rejected_identity_prose_cannot_escape_through_started_event(tmp_path, monkeypatch, field):
    cfg = fixture_config(tmp_path)
    cfg[field] = ANSWER
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(500))
    result, attempt, call, events = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["transmissions"] == 0
    assert call[field] is attempt[field] is None
    assert_call_schema(call)
    assert_schema(attempt)
    assert_metadata_only(asdict(result), attempt, call, events)


@pytest.mark.parametrize("family", ["A", "B"])
def test_zero_send_known_zero_does_not_invent_usage_or_helper_evidence(tmp_path, monkeypatch, family):
    from temper_ai.agent.single_call_agent import recompute_list_price_usd
    cfg = fixture_config(tmp_path, family)
    cfg["single_call"]["prompt_sha256"] = "0" * 64
    provider = fake_anthropic(monkeypatch, lambda request: httpx.Response(500)) if family == "A" else fake_codex(monkeypatch, lambda request: httpx.Response(500))
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and attempt["terminal"] == "NOT_MEASURED"
    assert attempt["transmissions"] == provider._test_request_starts == 0
    for observation in (result.metadata, attempt, call):
        assert observation["cost_state"] == "KNOWN"
        assert observation["list_price_usd"] == observation["unknown_exposure_usd"] == 0
        assert observation["usage_state"] == "UNKNOWN"
    assert all(value is None for value in call["usage"].values())
    price = parse_pinned_pricing(Path(cfg["single_call"]["pricing_path"]).read_bytes())
    assert recompute_list_price_usd(call, price) is None
    assert_call_schema(call)
    assert_schema(attempt)


@pytest.mark.parametrize("family", ["A", "B"])
@pytest.mark.parametrize("phase", ["empty", "partial", "complete"])
def test_pre_request_crash_keeps_claim_permanently_used_and_evidence_distinct(tmp_path, monkeypatch, family, phase):
    from temper_ai.agent import single_call_agent as module
    cfg, sent = fixture_config(tmp_path, family), []
    class Crash(BaseException):
        pass
    original_validate = module._Attempt.validate
    original_prepare = module._Attempt.prepare_and_make_durable
    original_write = os.write
    def validate(state):
        if phase == "empty":
            raise Crash()
        return original_validate(state)
    def prepare(state, request):
        original_prepare(state, request)
        if phase == "complete":
            raise Crash()
    def write(fd, data):
        if phase == "partial" and os.readlink(f"/proc/self/fd/{fd}").endswith(".claim"):
            original_write(fd, data[:len(data) // 2])
            raise Crash()
        return original_write(fd, data)
    monkeypatch.setattr(module._Attempt, "validate", validate)
    monkeypatch.setattr(module._Attempt, "prepare_and_make_durable", prepare)
    monkeypatch.setattr(os, "write", write)
    def handler(request):
        sent.append(1)
        return httpx.Response(500)
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    with pytest.raises(Crash):
        run_slot(cfg, provider)
    root = Path(cfg["single_call"]["output_root"])
    claim = root / (family + "1.claim")
    original_bytes = claim.read_bytes()
    assert not sent and not (root / (family + "1.attempt.json")).exists()
    if phase == "complete":
        record = json.loads(original_bytes)
        assert record["schema"] == "context-t1-claim/v1"
        assert Decimal(record["reservation_usd"]) > 0  # Offline: UNKNOWN, retain it.
    else:
        with pytest.raises(json.JSONDecodeError):
            json.loads(original_bytes)  # Incomplete claim cannot have crossed the gate.
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.FAILED and result.metadata["transmissions"] == 0
    assert result.metadata["list_price_usd"] == result.metadata["unknown_exposure_usd"] == 0
    assert attempt is call is None and not sent
    assert claim.read_bytes() == original_bytes, "a permanently used claim was changed"


@pytest.mark.parametrize("family", ["A", "B"])
@pytest.mark.parametrize(("literal", "output_rate"), [(b"1.0000000000000000001", 2), (b"1e-400", 0)])
def test_pinned_price_literal_bytes_are_never_rounded_or_underflowed_before_guards(tmp_path, monkeypatch, family, literal, output_rate):
    cfg, sent = fixture_config(tmp_path, family), []
    fixed = cfg["single_call"]
    path = Path(fixed["pricing_path"])
    pricing = json.loads(path.read_text())
    pricing["models"][cfg["model"]].update(input_usd_per_million="FAKE-LITERAL", output_usd_per_million=output_rate)
    raw = json.dumps(pricing).encode().replace(b'"FAKE-LITERAL"', literal)
    path.write_bytes(raw)
    fixed["pricing_sha256"] = digest(raw)
    replay = parse_pinned_pricing(raw)
    rate = replay["models"][cfg["model"]]["input_usd_per_million"]
    assert isinstance(rate, Decimal) and rate == Decimal(literal.decode()) and rate > 0
    def handler(request):
        sent.append(1)
        return httpx.Response(200, content=anthropic_events() if family == "A" else codex_events(),
                              headers={"content-type": "text/event-stream"})
    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    result, attempt, call, _ = run_slot(cfg, provider)
    assert not sent and result.status == Status.FAILED
    assert attempt["terminal"] == "NOT_MEASURED" and attempt["transmissions"] == 0
    assert attempt["failure_reasons"] == ["strict_parser"]
    assert attempt["reservation_usd"] is call["reservation_usd"] is None
    assert attempt["list_price_usd"] == attempt["unknown_exposure_usd"] == 0
    assert_call_schema(call)
    assert_schema(attempt)


@pytest.mark.parametrize("raw", [b'{"currency":"USD","currency":"EUR"}', b'{"rate":NaN}',
                                 b'{"rate":Infinity}', b'{"rate":-Infinity}', b'[]'])
def test_exact_price_decoder_keeps_duplicate_and_nonfinite_refusals(raw):
    from temper_ai.llm.single_send import SingleSendError
    with pytest.raises(SingleSendError, match="strict_parser"):
        parse_pinned_pricing(raw)
