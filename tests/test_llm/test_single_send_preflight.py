"""single_send preflight: the send's exact body, with no send and no credential.

The opening test is whole-feature per family: the real SingleCallAgent send
(counting mock transport) next to preflight() and its CLI on the same config,
with every transport and credential path armed to trip. Then parity per
allowed parameter, determinism, environment, side effects, and the refusal
table, each refusal run through the real send as well.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import socket
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from temper_ai.llm import single_send as ss
from temper_ai.llm import single_send_preflight as pf
from temper_ai.shared.types import Status
from tests.test_single_call_agent import (
    PROMPT,
    anthropic_events,
    assert_metadata_only,
    codex_events,
    digest,
    fake_anthropic,
    fake_codex,
    fixture_config,
    fixture_context,
    no_real_network_or_credentials,  # noqa: F401 - autouse: no real network or env credential
    run_slot,
)

#: Synthetic shaper text: quotes, backslash, newline and non-ASCII, so JSON escaping counts.
SHAPED = 'FAKE-SHAPED "system" \\ line\nüñî'
#: A's token NAME in fixture_config: checked as a name only, never echoed.
TOKEN_NAME = "FAKE-named"
#: A prompt that needs JSON escaping: quotes, backslash, control, non-ASCII, astral, separators.
ESCAPED = 'SYNTHETIC_ESCAPED_PROMPT "q" \\ \t\n ünï 😀 \u2028 </x>\n'.encode()


class FakeShaper:
    """A synthetic OAuth shaper: a system block with a cache marker, and one header."""

    def shape(self, body):
        body["system"] = [{"type": "text", "text": SHAPED, "cache_control": {"type": "ephemeral"}}]
        return body

    def client_headers(self):
        return {"anthropic-beta": "FAKE-beta-1"}


def use_shaper(monkeypatch, shaper=None):
    from temper_ai.llm.providers import anthropic as module
    shaper = FakeShaper() if shaper is None else shaper
    monkeypatch.setattr(module, "get_oauth_shaper", lambda: shaper)


def arm_trips(monkeypatch) -> list[str]:
    """Every transport, credential and provider-construction path records and refuses."""
    from temper_ai.llm import token_pool
    from temper_ai.llm.providers import anthropic as anthropic_module
    from temper_ai.llm.providers import openai_codex
    from temper_ai.llm.providers.anthropic import AnthropicLLM
    from temper_ai.llm.providers.base import BaseLLM
    from temper_ai.llm.providers.openai import OpenAILLM
    from temper_ai.observability.event_recorder import EventRecorder
    from temper_ai.shared.types import ExecutionContext
    tripped: list[str] = []

    def trip(name):
        def refuse(*args, **kwargs):
            tripped.append(name)
            raise AssertionError(f"preflight reached {name}")
        return refuse

    targets = [
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (httpx.HTTPTransport, "__init__"), (httpx.HTTPTransport, "handle_request"),
        (httpx.MockTransport, "handle_request"),
        (pf._RefusingTransport, "handle_request"),
        (AnthropicLLM, "__init__"), (AnthropicLLM, "_client_for"), (AnthropicLLM, "check_token"),
        (AnthropicLLM, "_named_token"), (AnthropicLLM, "_call_pinned"), (BaseLLM, "__init__"),
        (OpenAILLM, "__init__"), (openai_codex.CodexTransport, "__init__"),
        (openai_codex, "account_id_from_token"), (openai_codex, "token_expiry"),
        (anthropic_module, "resolve_credential"), (token_pool, "named_tokens_from_env"),
        (token_pool, "tokens_from_env"), (token_pool.TokenPool, "__init__"),
        (ExecutionContext, "get_llm"), (EventRecorder, "record"),
    ]
    for owner, name in targets:
        monkeypatch.setattr(owner, name, trip(f"{getattr(owner, '__name__', owner)}.{name}"))
    secretish = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL", re.IGNORECASE)

    class GuardedEnv(dict):
        def _check(self, key):
            if isinstance(key, str) and secretish.search(key):
                tripped.append(f"environ[{key}]")
                raise AssertionError("preflight read a credential name from the environment")

        def get(self, key, default=None):
            self._check(key)
            return super().get(key, default)

        def __getitem__(self, key):
            self._check(key)
            return super().__getitem__(key)

        def __contains__(self, key):
            self._check(key)
            return super().__contains__(key)
    monkeypatch.setattr(os, "environ", GuardedEnv(os.environ))
    real_open = os.open

    def no_write_open(path, flags, *args, **kwargs):
        # /dev/null only: the SDK's once-per-process platform header probe (Python's
        # platform.processor() runs `uname -p` with stderr=DEVNULL), the same on the send path.
        if path != os.devnull and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            tripped.append(f"os.open(write) {path}")
            raise AssertionError("preflight writes nothing")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", no_write_open)
    return tripped


def tree(root: Path) -> dict[str, bytes | None]:
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def log_rows(caplog):
    return [{"rendered": r.getMessage(), "msg": r.msg, "args": r.args, "exc": r.exc_info,
             "text": r.exc_text, "stack": r.stack_info} for r in caplog.records]


def assert_no_prompt(*payloads, prompt: bytes = PROMPT):
    assert_metadata_only(*payloads)
    for payload in payloads:
        dumped = json.dumps(payload, default=str, ensure_ascii=False)
        assert prompt.decode().strip() not in dumped
        assert TOKEN_NAME not in dumped


def guarded_preflight(monkeypatch, root: Path, cfg):
    """preflight() with every trip armed; asserts it sent, read and wrote nothing."""
    before = tree(root)
    with monkeypatch.context() as patch:
        tripped = arm_trips(patch)
        out = pf.preflight(cfg)
    assert tripped == [] and tree(root) == before, "preflight sent, read a credential or wrote"
    return out


def send(monkeypatch, cfg, family, shaper=None):
    """The real SingleCallAgent send through a counting mock transport. Returns (result, wire)."""
    from temper_ai.agent.single_call_agent import SingleCallAgent
    wire: list[bytes] = []

    def handler(request):
        wire.append(request.content)
        data = anthropic_events() if family == "A" else codex_events()
        return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})

    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    if family == "A":
        from temper_ai.llm.providers import anthropic as module
        chosen = FakeShaper() if shaper is None else (None if shaper == "none" else shaper)
        monkeypatch.setattr(module, "get_oauth_shaper", lambda: chosen)
    ctx, _ = fixture_context(provider, "anthropic" if family == "A" else "openai")
    return SingleCallAgent(cfg).run({}, ctx), wire


def set_prompt(cfg, data: bytes):
    path = Path(cfg["single_call"]["prompt_path"])
    path.write_bytes(data)
    cfg["single_call"].update(prompt_bytes=len(data), prompt_sha256=hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("family", ["A", "B"])
def test_preflight_equals_the_send_byte_for_byte_with_no_send_or_credential(tmp_path, monkeypatch, caplog, capsys, family):
    """FIRST: the real send records one body; preflight and its CLI report the same bytes."""
    cfg = fixture_config(tmp_path, family)
    wire: list[bytes] = []

    def handler(request):
        wire.append(request.content)
        data = anthropic_events() if family == "A" else codex_events()
        return httpx.Response(200, content=data, headers={"content-type": "text/event-stream"})

    provider = fake_anthropic(monkeypatch, handler) if family == "A" else fake_codex(monkeypatch, handler)
    if family == "A":
        use_shaper(monkeypatch)
    result, attempt, call, _ = run_slot(cfg, provider)
    assert result.status == Status.COMPLETED and len(wire) == 1
    sent = ss.request_metadata(wire[0])

    caplog.set_level(logging.DEBUG)
    before = tree(tmp_path)
    tripped = arm_trips(monkeypatch)
    out = pf.preflight(cfg)
    config_file = tmp_path / "preflight-config.json"
    config_file.write_text(json.dumps(cfg))
    before[config_file.name] = config_file.read_bytes()
    code = pf.main([str(config_file)])
    stdout, stderr = capsys.readouterr()

    assert tripped == [] and len(wire) == 1, "preflight sent, read a credential or wrote"
    assert tree(tmp_path) == before
    assert code == 0 and json.loads(stdout) == out and stderr == ""
    assert out["schema"] == "single-call-preflight/v1" and out["terminal"] == "PREFLIGHT_OK"
    assert out["refusal"] is None and out["send_refusal"] is None and set(out) == set(pf._empty())
    assert out["authorizes_send"] is False
    assert out["not_checked"] == ["credential", "loaded_route", "quota_policy", "cost_cap", "claim_slot", "deadline"]
    # Byte equality with the send: the exact metadata its pre-send hook recorded.
    assert out["request"] == sent
    assert out["request"]["serialized_body_sha256"] == call["serialized_body_sha256"] == digest(wire[0])
    assert out["request"]["serialized_body_bytes"] == call["serialized_body_bytes"] == len(wire[0])
    assert out["request"]["input_parts"] == call["input_parts"]
    assert Decimal(out["reservation_usd"]) == Decimal(str(attempt["reservation_usd"]))
    assert out["prompt_part"] == {"bytes": len(PROMPT), "sha256": digest(PROMPT)}
    assert out["pins"] == {"prompt_sha256": digest(PROMPT), "prompt_bytes": len(PROMPT),
                           "pricing_sha256": cfg["single_call"]["pricing_sha256"]}
    body = json.loads(wire[0])
    assert out["parameters_sent"] == {k: v for k, v in body.items() if k not in ("messages", "system", "instructions", "input")}
    text = sum(part["bytes"] for part in sent["input_parts"])
    assert out["overhead"]["framing_bytes"] == len(wire[0]) - text > 0
    assert out["slot"] == family + "1" and out["family"] == family and out["model"] == cfg["model"]
    assert out["route"] == cfg["single_call"]["route"] and out["endpoint_basis"] == "default_not_loaded"
    assert out["output_bound"]["evidence_sha256"] == digest(b"https://example.invalid/FAKE-TEST-ONLY")
    assert out["output_bound"]["includes_reasoning"] == "UNKNOWN"
    assert out["versions"]["httpx"] == httpx.__version__
    assert out["body_facts"] == {"cache_control_markers": 0, "max_output_tokens_present": False}
    if family == "A":
        assert out["endpoint"] == "POST https://api.anthropic.com/v1/messages"
        assert out["overhead"]["system_or_instructions_bytes"] == len(SHAPED.encode())
        assert out["output_bound"] | {"includes_reasoning": None, "evidence_sha256": None} == {
            "mode": "request_limit", "tokens": 1000, "sent_as": "max_tokens",
            "includes_reasoning": None, "evidence_sha256": None}
        assert out["versions"]["oauth_shaper"].endswith("FakeShaper")
        assert out["versions"]["anthropic-beta"] == "FAKE-beta-1"
    else:
        assert out["endpoint"] == "POST https://chatgpt.com/backend-api/codex/responses"
        assert out["overhead"]["system_or_instructions_bytes"] == len(b"You are a helpful assistant.")
        assert out["output_bound"]["tokens"] == 4096 and out["output_bound"]["sent_as"] == "none"
        assert out["versions"]["originator"] and out["versions"]["openai-beta"]
    assert_no_prompt(out, log_rows(caplog), stdout, stderr)


PARITY_CASES = [
    ("A", {}, PROMPT), ("A", {"temperature": 0.5}, PROMPT), ("A", {"thinking": {"type": "adaptive"}}, PROMPT),
    ("A", {"thinking_budget": 500}, PROMPT), ("A", {"effort": "high"}, PROMPT), ("A", {}, ESCAPED),
    ("B", {}, PROMPT), ("B", {}, ESCAPED),
]


@pytest.mark.parametrize(("family", "optional", "prompt"), PARITY_CASES)
def test_parity_with_the_send_for_each_allowed_parameter_and_an_escaped_prompt(tmp_path, monkeypatch, caplog, family, optional, prompt):
    """B allows no optional parameter: each one is a refusal case below."""
    cfg = fixture_config(tmp_path, family)
    cfg["single_call"].update(optional)
    set_prompt(cfg, prompt)
    use_shaper(monkeypatch)
    caplog.set_level(logging.DEBUG)
    out = guarded_preflight(monkeypatch, tmp_path, cfg)
    result, wire = send(monkeypatch, cfg, family)
    assert result.status == Status.COMPLETED and len(wire) == 1
    assert out["terminal"] == "PREFLIGHT_OK" and out["request"] == ss.request_metadata(wire[0])
    assert out["prompt_part"] == {"bytes": len(prompt), "sha256": digest(prompt)}
    assert out["overhead"]["framing_bytes"] == len(wire[0]) - sum(p["bytes"] for p in out["request"]["input_parts"])
    for key, value in json.loads(wire[0]).items():
        if key not in ("messages", "system", "instructions", "input"):
            assert out["parameters_sent"][key] == value
    assert_no_prompt(out, log_rows(caplog), prompt=prompt)


@pytest.mark.parametrize("family", ["A", "B"])
def test_same_inputs_give_byte_identical_output(tmp_path, monkeypatch, family):
    use_shaper(monkeypatch)
    cfg = fixture_config(tmp_path, family)
    first = json.dumps(guarded_preflight(monkeypatch, tmp_path, cfg), sort_keys=True).encode()
    second = json.dumps(guarded_preflight(monkeypatch, tmp_path, cfg), sort_keys=True).encode()
    assert first == second and json.loads(first)["terminal"] == "PREFLIGHT_OK"


SENTINELS = {
    "ANTHROPIC_BASE_URL": "https://FAKE-sentinel.invalid", "ANTHROPIC_API_KEY": "FAKE-sentinel-key",
    "ANTHROPIC_AUTH_TOKEN": "FAKE-sentinel-token", "OPENAI_CODEX_BASE_URL": "https://FAKE-sentinel.invalid/codex",
    "HTTP_PROXY": "http://FAKE-proxy.invalid:9", "HTTPS_PROXY": "http://FAKE-proxy.invalid:9",
    "ALL_PROXY": "http://FAKE-proxy.invalid:9", "http_proxy": "http://FAKE-proxy.invalid:9",
    "https_proxy": "http://FAKE-proxy.invalid:9", "SSL_CERT_FILE": "/nonexistent/FAKE-cert",
}


@pytest.mark.parametrize("family", ["A", "B"])
def test_environment_sentinels_change_nothing(tmp_path, monkeypatch, family):
    from temper_ai.llm.providers.openai_codex import CODEX_BASE_URL_ENV
    assert CODEX_BASE_URL_ENV in SENTINELS
    use_shaper(monkeypatch)
    cfg = fixture_config(tmp_path, family)
    plain = guarded_preflight(monkeypatch, tmp_path, cfg)
    for key, value in SENTINELS.items():
        monkeypatch.setenv(key, value)
    with monkeypatch.context() as patch:
        # The guarded environment would refuse even a look at the key names; this run reads freely.
        for owner, name in [(socket.socket, "connect"), (socket.socket, "connect_ex"),
                            (httpx.HTTPTransport, "handle_request")]:
            patch.setattr(owner, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
        sentinel = pf.preflight(cfg)
    assert sentinel == plain and plain["terminal"] == "PREFLIGHT_OK"
    assert "FAKE-sentinel" not in json.dumps(sentinel) and "FAKE-proxy" not in json.dumps(sentinel)


@pytest.mark.parametrize("family", ["A", "B"])
def test_preflight_clients_never_trust_the_environment(tmp_path, monkeypatch, family):
    """No proxy, certificate or netrc setting reaches the build, whatever httpx reads by default."""
    use_shaper(monkeypatch)
    trusted: list[bool] = []
    real_init = httpx.Client.__init__

    def record(self, *args, **kwargs):
        trusted.append(kwargs.get("trust_env", True))
        real_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "__init__", record)
    assert guarded_preflight(monkeypatch, tmp_path, fixture_config(tmp_path, family))["terminal"] == "PREFLIGHT_OK"
    assert trusted == [False]


@pytest.mark.parametrize("family", ["A", "B"])
def test_output_root_is_never_created_or_opened(tmp_path, monkeypatch, family):
    use_shaper(monkeypatch)
    cfg = fixture_config(tmp_path, family)
    absent = tmp_path / "FAKE-root-parent" / "FAKE-root"
    cfg["single_call"]["output_root"] = str(absent)
    opened: list[str] = []
    real_open = os.open

    def watch(path, *args, **kwargs):
        opened.append(str(path))
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", watch)
    out = guarded_preflight(monkeypatch, tmp_path, cfg)
    assert out["terminal"] == "PREFLIGHT_OK" and not absent.exists() and not absent.parent.exists()
    assert not any("FAKE-root" in path for path in opened)


@pytest.mark.parametrize("family", ["A", "B"])
def test_send_only_fields_are_optional(tmp_path, monkeypatch, family):
    use_shaper(monkeypatch)
    cfg = fixture_config(tmp_path, family)
    full = guarded_preflight(monkeypatch, tmp_path, cfg)
    for key in pf.SEND_ONLY:
        cfg["single_call"].pop(key)
    assert guarded_preflight(monkeypatch, tmp_path, cfg) == full
    for key in ("name", "type", "description"):
        cfg[key] = "FAKE-" + key
    assert guarded_preflight(monkeypatch, tmp_path, cfg) == full


def rehash_pricing(cfg, change):
    path = Path(cfg["single_call"]["pricing_path"])
    pricing = json.loads(path.read_text())
    change(pricing["models"][cfg["model"]], pricing)
    path.write_text(json.dumps(pricing))
    cfg["single_call"]["pricing_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def drop(key):
    return lambda cfg: cfg["single_call"].pop(key)


def setf(key, value):
    return lambda cfg: cfg["single_call"].__setitem__(key, value)


def setc(key, value):
    return lambda cfg: cfg.__setitem__(key, value)


class RewritingShaper(FakeShaper):
    def shape(self, body):
        body["messages"] = [{"role": "user", "content": "FAKE-replaced"}]
        return body


class ExtraKeyShaper(FakeShaper):
    def shape(self, body):
        body["metadata"] = {"user_id": "FAKE"}
        return body


class DuplicatingShaper(FakeShaper):
    def shape(self, body):
        body = super().shape(body)
        body["messages"] = body["messages"] * 2
        return body


def raw_pricing(data: bytes):
    def change(cfg):
        path = Path(cfg["single_call"]["pricing_path"])
        path.write_bytes(data)
        cfg["single_call"]["pricing_sha256"] = hashlib.sha256(data).hexdigest()
    return change


SP, AUTH, TRANSPORT = "strict_parser", "auth", "transport"
#: (family, preflight refusal, change, shaper, the send's recorded reason).
#: The send reasons were read from the parent's send code (a95e3244, before the
#: shared checks were extracted), not from running this head, so a reason that
#: drifts inside a shared check fails here. TRANSPORT: the parent's safe_failure
#: for a non-gate error (a missing or non-string path, bad JSON, a missing key,
#: undecodable prompt). None: the send transmits (preflight-only refusal). The one
#: stated change: shaper_missing, where the parent warned and sent an unshaped body.
REFUSAL_CASES = [
    ("A", "prompt_mismatch", setf("prompt_sha256", "0" * 64), None, SP),
    ("B", "prompt_mismatch", setf("prompt_bytes", len(PROMPT) - 1), None, SP),
    ("A", "prompt_mismatch", setf("prompt_bytes", -1), None, SP),
    ("B", "prompt_mismatch", setf("prompt_path", "/nonexistent/FAKE-prompt"), None, TRANSPORT),
    ("A", "prompt_mismatch", setf("prompt_path", 7), None, TRANSPORT),
    ("A", "prompt_mismatch", setf("prompt_sha256", "not-hex"), None, SP),
    ("A", "prompt_mismatch", None, RewritingShaper(), None),
    ("A", "prompt_mismatch", None, DuplicatingShaper(), None),
    ("A", "prompt_mismatch", lambda cfg: set_prompt(cfg, b"FAKE \xff\xfe not utf-8"), None, TRANSPORT),
    ("A", "pricing_mismatch", setf("pricing_path", "/nonexistent/FAKE-pricing"), None, TRANSPORT),
    ("B", "pricing_mismatch", raw_pricing(b"{not json"), None, TRANSPORT),
    ("A", "pricing_mismatch", lambda cfg: rehash_pricing(cfg, lambda m, p: p.__setitem__("models", [])), None, TRANSPORT),
    ("A", "pricing_mismatch", setf("pricing_sha256", "0" * 64), None, SP),
    ("B", "pricing_mismatch", setf("pricing_sha256", "F" * 64), None, SP),
    ("B", "pricing_mismatch", lambda cfg: rehash_pricing(cfg, lambda m, p: p.__setitem__("currency", "EUR")), None, SP),
    ("A", "pricing_mismatch", lambda cfg: rehash_pricing(cfg, lambda m, p: m.pop("input_usd_per_million")), None, TRANSPORT),
    ("B", "pricing_mismatch", lambda cfg: rehash_pricing(cfg, lambda m, p: p.__setitem__("models", {})), None, TRANSPORT),
    ("A", "pricing_mismatch", lambda cfg: rehash_pricing(cfg, lambda m, p: m.__setitem__("input_usd_per_million", "1e-400")), None, SP),
    ("A", "unknown_slot", setf("slot", "A9"), None, SP),
    ("A", "unknown_slot", setf("slot", ["A1"]), None, SP),
    ("B", "unknown_slot", setf("slot", PROMPT.decode()), None, SP),
    ("A", "unknown_slot", drop("slot"), None, SP),
    ("A", "unknown_slot", setf("slot", "C1"), None, SP),
    ("A", "unknown_slot", setf("slot", "B1"), None, AUTH),
    ("B", "unknown_slot", setf("family", "A"), None, AUTH),
    ("A", "route_mismatch", setf("route", "openai-codex-oauth"), None, AUTH),
    ("B", "route_mismatch", setc("model", "claude-opus-5-5"), None, AUTH),
    ("A", "route_mismatch", setc("provider", "openai"), None, AUTH),
    ("B", "route_mismatch", setf("auth_mode", "api_key"), None, AUTH),
    ("A", "route_mismatch", drop("token"), None, AUTH),
    ("B", "route_mismatch", setf("token", "FAKE-named"), None, AUTH),
    ("A", "route_mismatch", setc("provider", 7), None, AUTH),
    ("A", "unsupported_parameter", setf("top_p", 1), None, SP),
    ("B", "unsupported_parameter", setc("tools", []), None, SP),
    ("A", "unsupported_parameter", lambda cfg: cfg["single_call"].update(thinking={"type": "adaptive"}, thinking_budget=10), None, SP),
    ("A", "unsupported_parameter", setf("thinking_budget", 1000), None, SP),
    ("B", "unsupported_parameter", setf("temperature", 0), None, SP),
    ("B", "unsupported_parameter", setf("effort", "high"), None, SP),
    ("A", "bound_unestablished", setf("output_bound_mode", "documented_max"), None, AUTH),
    ("B", "bound_unestablished", setf("output_bound_mode", "request_limit"), None, AUTH),
    ("A", "bound_unestablished", setf("max_tokens", 0), None, SP),
    ("B", "bound_unestablished", lambda cfg: rehash_pricing(cfg, lambda m, p: m.pop("max_output_tokens")), None, SP),
    ("B", "bound_unestablished", lambda cfg: rehash_pricing(cfg, lambda m, p: m.__setitem__("public_source", "http://x")), None, SP),
    ("A", "bound_unestablished", lambda cfg: rehash_pricing(cfg, lambda m, p: m.pop("request_limit_evidence")), None, SP),
    ("A", "shaper_missing", None, "none", AUTH),
    ("A", "strict_parser", drop("pricing_path"), None, SP),
    ("B", "strict_parser", lambda cfg: cfg.pop("single_call"), None, SP),
    ("B", "strict_parser", setc("single_call", "FAKE"), None, SP),
    ("A", "strict_parser", None, ExtraKeyShaper(), SP),
    ("A", "strict_parser", setf("thinking", {"type": "FAKE"}), None, SP),
    ("A", "strict_parser", setf("temperature", 5), None, SP),
    ("A", "strict_parser", setf("output_root", "relative/FAKE-root"), None, SP),
    ("B", "strict_parser", setf("output_root", "/tmp/../FAKE-root"), None, SP),
    ("A", "strict_parser", setf("deadline_s", 899), None, SP),
    ("B", "strict_parser", setf("cost_cap_usd", "FAKE"), None, SP),
    ("A", "strict_parser", setf("experiment_id", ""), None, SP),
    ("B", "strict_parser", setf("binding_id", 7), None, SP),
    ("A", "strict_parser", setf("config_sha256", "not-hex"), None, SP),
]
#: Preflight-only: the send transmits these (a shaper that rewrites the user message).
SEND_DOES_NOT_REFUSE = (RewritingShaper, DuplicatingShaper)


@pytest.mark.parametrize(("family", "reason", "change", "shaper", "send_reason"), REFUSAL_CASES)
def test_each_refusal_matches_the_send_and_sends_reads_and_writes_nothing(
        tmp_path, monkeypatch, caplog, family, reason, change, shaper, send_reason):
    cfg = fixture_config(tmp_path, family)
    if change is not None:
        change(cfg)
    from temper_ai.llm.providers import anthropic as module
    chosen = None if shaper == "none" else (shaper or FakeShaper())
    monkeypatch.setattr(module, "get_oauth_shaper", lambda: chosen)
    caplog.set_level(logging.DEBUG)
    out = guarded_preflight(monkeypatch, tmp_path, cfg)
    assert out["terminal"] == "REFUSED" and out["refusal"] == reason
    assert set(out) == set(pf._empty()) and out["authorizes_send"] is False
    constant = ("schema", "terminal", "refusal", "send_refusal", "slot", "authorizes_send", "not_checked")
    assert all(out[key] is None for key in out if key not in constant)
    assert out["slot"] is None or out["slot"] in {"A1", "A2", "A3", "B1", "B2", "B3"}
    assert_no_prompt(out, log_rows(caplog))
    # The parent's reason, from the preflight and from the real send, with no transmission.
    assert out["send_refusal"] == send_reason
    result, wire = send(monkeypatch, cfg, family, "none" if shaper == "none" else chosen)
    if isinstance(shaper, SEND_DOES_NOT_REFUSE):
        assert send_reason is None and result.status == Status.COMPLETED and len(wire) == 1
    else:
        assert result.status == Status.FAILED and wire == []
        assert result.structured_output["failure_reasons"] == [send_reason]


def test_every_named_refusal_is_reached():
    assert {case[1] for case in REFUSAL_CASES} == set(pf.REFUSALS)


def test_preflight_and_send_only_fields_split_the_send_required_set():
    from temper_ai.agent.single_call_agent import SINGLE_CALL_REQUIRED
    assert not pf.PREFLIGHT_REQUIRED & pf.SEND_ONLY
    assert pf.PREFLIGHT_REQUIRED | pf.SEND_ONLY == SINGLE_CALL_REQUIRED


@pytest.mark.parametrize("family", ["A", "B"])
def test_reasoning_answer_needs_a_pinned_https_source(tmp_path, monkeypatch, family):
    use_shaper(monkeypatch)
    cfg = fixture_config(tmp_path, family)

    def pin(source, includes):
        def change(model, pricing):
            model["output_bound_includes_reasoning"] = includes
            model["output_bound_includes_reasoning_source"] = source
        rehash_pricing(cfg, change)
        return pf.preflight(cfg)["output_bound"]["includes_reasoning"]
    assert pin("https://example.invalid/FAKE-pinned", True) == "INCLUDED"
    assert pin("https://example.invalid/FAKE-pinned", False) == "NOT_INCLUDED"
    assert pin("http://example.invalid/FAKE-not-https", True) == "UNKNOWN"
    assert pin("https://example.invalid/FAKE-pinned", "true") == "UNKNOWN"
    assert pin("https://example.invalid/FAKE-pinned", 1) == "UNKNOWN"
    assert pin(None, True) == "UNKNOWN"


def test_refusal_names_stay_in_the_closed_list():
    assert pf._named(ss.NamedRefusal("strict_parser", "unknown_slot"), "route_mismatch") == "unknown_slot"
    assert pf._named(ss.NamedRefusal("strict_parser", "FAKE-new"), "route_mismatch") == "route_mismatch"
    assert pf._named(ss.SingleSendError("strict_parser"), "strict_parser") == "strict_parser"


def assert_crash_keeps_nothing(cfg, caplog, capsys, tmp_path, prompt=PROMPT):
    with pytest.raises(pf.PreflightCrashed) as raised:
        pf.preflight(cfg)
    exc = raised.value
    assert exc.__cause__ is None and exc.__context__ is None
    assert str(exc) == "single_send preflight stopped: unexpected failure, no detail kept"
    path = tmp_path / "crash-config.json"
    path.write_text(json.dumps(cfg))
    capsys.readouterr()
    assert pf.main([str(path)]) == 1
    stdout, stderr = capsys.readouterr()
    assert stdout == "" and stderr == "single_send_preflight: unexpected failure, no detail kept\n"
    assert_no_prompt(log_rows(caplog), stderr, prompt=prompt)


def test_a_client_that_retries_is_a_crash_not_a_digest(tmp_path, monkeypatch, caplog, capsys):
    """One request is built, as max_retries=0 makes it; a build that repeats stops the preflight."""
    import time

    import anthropic
    use_shaper(monkeypatch)
    real_init = anthropic.Anthropic.__init__

    def retrying(self, *args, **kwargs):
        real_init(self, *args, **{**kwargs, "max_retries": 2})
    monkeypatch.setattr(anthropic.Anthropic, "__init__", retrying)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    caplog.set_level(logging.DEBUG)
    cfg = fixture_config(tmp_path, "A")
    with monkeypatch.context() as patch:
        tripped = arm_trips(patch)
        assert_crash_keeps_nothing(cfg, caplog, capsys, tmp_path)
    assert tripped == []


def test_a_hook_that_fails_to_stop_meets_the_refusing_transport(tmp_path, monkeypatch, caplog, capsys):
    """Backstop: a hook that let the call through hits the refusing transport, and the preflight stops."""
    use_shaper(monkeypatch)

    def keep_only(self, request):
        self.captured.append(request)
    monkeypatch.setattr(pf._StopAfterCapture, "__call__", keep_only)
    reached: list[int] = []
    real = pf._RefusingTransport.handle_request

    def counting(self, request):
        reached.append(1)
        return real(self, request)
    monkeypatch.setattr(pf._RefusingTransport, "handle_request", counting)
    caplog.set_level(logging.DEBUG)
    assert_crash_keeps_nothing(fixture_config(tmp_path, "A"), caplog, capsys, tmp_path)
    assert reached == [1, 1]


def test_unexpected_library_failure_keeps_no_prose(tmp_path, monkeypatch, caplog, capsys):
    """An unexpected library error: PreflightCrashed, nothing chained, CLI exit 1 with no JSON."""
    from temper_ai.llm.providers import openai_codex

    def explode(*args, **kwargs):
        raise RuntimeError(PROMPT.decode() + TOKEN_NAME)
    monkeypatch.setattr(openai_codex, "codex_request_body", explode)
    caplog.set_level(logging.DEBUG)
    assert_crash_keeps_nothing(fixture_config(tmp_path, "B"), caplog, capsys, tmp_path)


def test_cache_marker_count_walks_the_whole_body():
    marked = {"system": [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}],
              "messages": [{"role": "user", "content": [{"type": "text", "text": "y", "cache_control": {}}]}],
              "cache_control": {"type": "ephemeral"}}
    assert pf._count_cache_markers(marked) == 3
    assert pf._count_cache_markers({"messages": [{"role": "user", "content": "y"}]}) == 0


def test_cli_usage_and_refusal_exit_codes(tmp_path, monkeypatch, capsys):
    use_shaper(monkeypatch)
    assert pf.main([]) == 2
    assert pf.main([str(tmp_path / "missing.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert pf.main([str(bad)]) == 2
    cfg = fixture_config(tmp_path / "x", "B")
    cfg["single_call"]["prompt_sha256"] = "0" * 64
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    capsys.readouterr()
    assert pf.main([str(path)]) == 3
    stdout, _ = capsys.readouterr()
    assert json.loads(stdout)["refusal"] == "prompt_mismatch"
