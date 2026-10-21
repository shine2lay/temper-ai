"""A fixed-input, write-once call. No service, tools, memory, templates or repair.

Controls use, not credential isolation. Admission, root provisioning/durable parent,
process containment and experiment-wide accounting belong to the later workflow.
"""
from __future__ import annotations

import json
import math
import os
import re
import stat
import time
import uuid
from datetime import datetime
from decimal import Decimal, Inexact, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from temper_ai.agent.base import AgentABC
from temper_ai.llm import single_send as ss
from temper_ai.llm.models import LLMResponse
from temper_ai.observability import EventType
from temper_ai.shared.types import AgentResult, ExecutionContext, Status, TokenUsage

SINGLE_CALL_AGENT_SETTINGS = frozenset({"name", "type", "description", "provider", "model", "single_call"})
SINGLE_CALL_REQUIRED = frozenset({
    "prompt_path", "prompt_sha256", "prompt_bytes", "output_root", "slot", "family",
    "route", "auth_mode", "max_tokens", "output_bound_mode", "deadline_s", "cost_cap_usd",
    "pricing_path", "pricing_sha256", "experiment_id", "binding_id", "source_sha256",
    "config_sha256", "packet_sha256",
})
SINGLE_CALL_SETTINGS = SINGLE_CALL_REQUIRED | {"token", "temperature", "thinking", "thinking_budget", "effort"}
_DIGEST_FIELDS = ("prompt_sha256", "source_sha256", "config_sha256", "pricing_sha256", "packet_sha256")
_USAGE_KEYS = ss.USAGE_COUNTERS
_SLOTS = frozenset({"A1", "A2", "A3", "B1", "B2", "B3"})
_STOPS = frozenset({"end_turn", "stop_sequence", "stop", "max_tokens", "length", "incomplete", "tool_use", "pause_turn", "refusal"})
_CALL_IDENTITY_FIELDS = ("provider", "model", "route", "auth_mode", "pricing_sha256", "output_bound_mode")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ss.SingleSendError("strict_parser")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ss.SingleSendError("strict_parser") from None
    if not result.is_finite() or not math.isfinite(float(result)) or result < 0:
        raise ss.SingleSendError("strict_parser")
    return result


def _exact_usd(input_count: Any, input_rate: Any, output_count: Any, output_rate: Any) -> Decimal:
    """(in x rate + out x rate) / 1e6 with no Decimal rounding; Inexact -> strict_parser."""
    with localcontext() as ctx:
        ctx.prec, ctx.traps[Inexact] = 100, True
        try:
            return (_decimal(input_count) * _decimal(input_rate)
                    + _decimal(output_count) * _decimal(output_rate)) / Decimal(1_000_000)
        except Inexact:
            raise ss.SingleSendError("strict_parser") from None


def _json_number_is_exact(value: Decimal) -> bool:
    """v1 records carry JSON numbers; an amount float() would round is refused, never rounded."""
    return Decimal(repr(float(value))) == value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ss.SingleSendError("strict_parser")
        result[key] = value
    return result


def parse_pinned_pricing(pricing_bytes: bytes) -> dict:
    """Decode literal prices exactly, for the producer and offline recomputation."""
    value = json.loads(pricing_bytes, parse_float=Decimal, object_pairs_hook=_unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ss.SingleSendError("strict_parser")))
    if not isinstance(value, dict):
        raise ss.SingleSendError("strict_parser")
    return value


def _open_directory(path: object) -> int:
    """Walk retained directory fds: no parent or final symlinks, no '..'."""
    if not isinstance(path, str) or not path.startswith("/") or ".." in path.split("/"):
        raise ss.SingleSendError("strict_parser")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in Path(path).parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_root(fd: int) -> None:
    value = os.fstat(fd)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or stat.S_IMODE(value.st_mode) != 0o700:
        raise ss.SingleSendError("strict_parser")


def _read_bound(path: str, limit: int) -> bytes:
    parent = _open_directory(str(Path(path).parent))
    try:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ss.SingleSendError("strict_parser")
            chunks: list[bytes] = []
            size = 0
            while size <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - size))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                size += len(chunk)
            raise ss.SingleSendError("strict_parser")
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _new_file(root: int, name: str) -> int:
    _private_root(root)
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root)
    try:
        os.fchmod(fd, 0o600)
        value = os.fstat(fd)
        if not stat.S_ISREG(value.st_mode) or value.st_uid != os.geteuid() or value.st_nlink != 1:
            raise ss.SingleSendError("strict_parser")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _write_fd_once(fd: int, data: bytes) -> None:
    if os.write(fd, data) != len(data):
        raise ss.SingleSendError("crash")
    os.fsync(fd)


def _write_once(root: int, name: str, data: bytes) -> None:
    fd = _new_file(root, name)
    try:
        _write_fd_once(fd, data)
    finally:
        os.close(fd)


def recompute_list_price_usd(call_record: dict, pinned_pricing: dict) -> Decimal | None:
    """Pure reported-price observation; only the later attempt is final accounting.

    Subsets never add to or subtract from their totals. A missing/unpriced
    category or malformed shape cannot manufacture a zero or a known price.
    """
    try:
        if pinned_pricing.get("currency") != "USD":
            return None
        usage = ss.reported_usage(call_record.get("usage"), codex=call_record.get("route") == "openai-codex-oauth")
        if usage["input_tokens"] is None or usage["output_tokens"] is None:
            return None
        if any(usage[key] not in (None, 0) for key in ("cache_read_input_tokens", "cache_creation_input_tokens")):
            return None
        price = pinned_pricing["models"][call_record["model"]]
        cost = _exact_usd(usage["input_tokens"], price["input_usd_per_million"],
                          usage["output_tokens"], price["output_usd_per_million"])
        return cost if _json_number_is_exact(cost) else None
    except (KeyError, TypeError, ss.SingleSendError):
        return None


class _Attempt:
    """One invocation's owned fds and measured facts, never reused across calls."""

    def __init__(self, config: dict, context: ExecutionContext) -> None:
        self.config, self.context = config, context
        fixed = config.get("single_call")
        self.fixed: dict = fixed if isinstance(fixed, dict) else {}
        self.root: int | None = None
        self.claim: int | None = None
        self.claimed = False
        self.durable = False
        self.persisted = False
        slot = self.fixed.get("slot")
        self.slot = slot if isinstance(slot, str) else ""
        self.start: float | None = None
        self.started: str | None = None
        self.deadline: float | None = None
        self.session_id, self.run_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.control: ss.SingleSendControl | None = None
        self.response: LLMResponse | None = None
        self.pricing: dict = {}
        self.call_identity: dict = dict.fromkeys(_CALL_IDENTITY_FIELDS)
        self.reservation: Decimal | None = None
        self.output_bound: int | None = None
        self.evidence: str | None = None
        self.failure: ss.SingleSendError | None = None
        self.terminal = "NOT_MEASURED"
        self.cleanup = "CONFIRMED"
        self.raw_sha: str | None = None
        self.raw_bytes: int | None = None
        self.raw_path: str | None = None
        self.cost: Decimal | None = Decimal(0)  # This invocation has not initiated a request.
        self.usage = dict.fromkeys(_USAGE_KEYS)
        self.cleanup_sample: tuple[float, str] | None = None
        self.record: dict | None = None

    def _path(self, suffix: str) -> str:
        return str(Path(self.fixed["output_root"]) / f"{self.slot}.{suffix}")

    def fail(self, exc: Exception) -> None:
        self.failure = ss.safe_failure(exc, self.response)
        if self.failure.response is not None:
            self.response = self.failure.response
        self.terminal = "FAILED" if self.control and self.control.transmission_ids else "NOT_MEASURED"

    def claim_slot(self) -> None:
        if not isinstance(self.slot, str) or self.slot not in _SLOTS:
            raise ss.SingleSendError("strict_parser")
        self.root = _open_directory(self.fixed.get("output_root"))
        _private_root(self.root)
        self.start, self.started = ss.paired_sample()
        self.deadline = self.start + 900
        self.claim = _new_file(self.root, f"{self.slot}.claim")
        self.claimed = True
        for suffix in ("raw", "call.json", "attempt.json"):
            try:
                os.stat(f"{self.slot}.{suffix}", dir_fd=self.root, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ss.SingleSendError("strict_parser")

    def validate(self) -> tuple[Any, str, dict]:
        self.call_identity = dict.fromkeys(_CALL_IDENTITY_FIELDS)
        c, f = self.config, self.fixed
        if set(c) - SINGLE_CALL_AGENT_SETTINGS or set(f) - SINGLE_CALL_SETTINGS or not SINGLE_CALL_REQUIRED <= f.keys():
            raise ss.SingleSendError("strict_parser")
        if not isinstance(c.get("provider"), str) or not c["provider"] or not isinstance(c.get("model"), str):
            raise ss.SingleSendError("auth")
        for key in _DIGEST_FIELDS:
            if not isinstance(f[key], str) or not re.fullmatch(r"[0-9a-f]{64}", f[key]):
                raise ss.SingleSendError("strict_parser")
        for key in ("experiment_id", "binding_id"):
            if not isinstance(f[key], str) or not 1 <= len(f[key]) <= 256:
                raise ss.SingleSendError("strict_parser")
        if type(f["deadline_s"]) is not int or f["deadline_s"] != 900:
            raise ss.SingleSendError("strict_parser")
        if type(f["prompt_bytes"]) is not int or f["prompt_bytes"] < 0:
            raise ss.SingleSendError("strict_parser")
        if type(f["max_tokens"]) is not int or f["max_tokens"] <= 0:
            raise ss.SingleSendError("strict_parser")
        _decimal(f["cost_cap_usd"])
        family = f["family"]
        from temper_ai.llm.providers.anthropic import AnthropicLLM
        from temper_ai.llm.providers.openai import OpenAILLM
        a = family == "A" and self.slot.startswith("A")
        b = family == "B" and self.slot.startswith("B")
        if not (a or b) or f["auth_mode"] != "oauth":
            raise ss.SingleSendError("auth")
        if a and (c["provider"] != "anthropic" or c["model"] != "claude-opus-5-5" or f["route"] != "anthropic-oauth-named-token" or f["output_bound_mode"] != "request_limit" or not isinstance(f.get("token"), str) or not f["token"]):
            raise ss.SingleSendError("auth")
        if b and (c["provider"] != "openai" or c["model"] != "gpt-6.1-sol" or f["route"] != "openai-codex-oauth" or f["output_bound_mode"] != "documented_max" or "token" in f):
            raise ss.SingleSendError("auth")
        provider = self.context.get_llm(c["provider"])
        if a:
            if type(provider) is not AnthropicLLM or provider.auth_mode != "oauth":
                raise ss.SingleSendError("auth")
            try:
                provider.check_token(f["token"])
            except Exception:
                raise ss.SingleSendError("auth") from None
        elif type(provider) is not OpenAILLM or provider.auth_mode != "oauth" or provider._codex is None:
            raise ss.SingleSendError("auth")
        self.call_identity.update({k: c[k] for k in ("provider", "model")})
        self.call_identity.update({k: f[k] for k in ("route", "auth_mode", "output_bound_mode")})
        prompt = _read_bound(f["prompt_path"], f["prompt_bytes"])
        if len(prompt) != f["prompt_bytes"] or ss.sha256(prompt) != f["prompt_sha256"]:
            raise ss.SingleSendError("strict_parser")
        pricing_bytes = _read_bound(f["pricing_path"], 65536)
        if ss.sha256(pricing_bytes) != f["pricing_sha256"]:
            raise ss.SingleSendError("strict_parser")
        self.call_identity["pricing_sha256"] = f["pricing_sha256"]
        self.pricing = parse_pinned_pricing(pricing_bytes)
        if self.pricing.get("currency") != "USD":
            raise ss.SingleSendError("strict_parser")
        price = self.pricing["models"][c["model"]]
        for key in ("input_usd_per_million", "output_usd_per_million"):
            _decimal(price[key])
        evidence_key = "request_limit_evidence" if a else "public_source"
        source = price.get(evidence_key)
        if not isinstance(source, str) or not source.startswith("https://") or len(source) > 2048:
            raise ss.SingleSendError("strict_parser")
        self.evidence = ss.sha256(source.encode("utf-8"))
        output_bound = f["max_tokens"] if a else price.get("max_output_tokens")
        if type(output_bound) is not int or output_bound <= 0:
            raise ss.SingleSendError("strict_parser")
        self.output_bound = output_bound
        kwargs = {k: f[k] for k in ("token", "temperature", "thinking", "thinking_budget", "effort") if k in f}
        if "thinking_budget" in f and (type(f["thinking_budget"]) is not int or not 0 < f["thinking_budget"] < f["max_tokens"]):
            raise ss.SingleSendError("strict_parser")
        if "thinking" in f and "thinking_budget" in f:
            raise ss.SingleSendError("strict_parser")
        return provider, prompt.decode("utf-8"), kwargs

    def prepare_and_make_durable(self, request: dict) -> None:
        """The final-body hook: policy/cap -> ONE claim write -> fsync -> dir fsync."""
        if self.durable:
            raise ss.SingleSendError("retry")
        root, claim_fd, output_bound = self.root, self.claim, self.output_bound
        if root is None or claim_fd is None or output_bound is None:
            raise ss.SingleSendError("strict_parser")
        f = self.fixed
        params = request["parameters"]
        if request["model"] != self.config["model"]:
            raise ss.SingleSendError("strict_parser")
        if f["family"] == "A" and params.get("max_tokens") != f["max_tokens"]:
            raise ss.SingleSendError("strict_parser")
        if f["family"] == "B" and "max_output_tokens" in params:
            raise ss.SingleSendError("strict_parser")
        budget = (params.get("thinking") or {}).get("budget_tokens")
        if budget is not None and budget >= f["max_tokens"]:
            raise ss.SingleSendError("strict_parser")
        price = self.pricing["models"][self.config["model"]]
        reservation = _exact_usd(request["serialized_body_bytes"], price["input_usd_per_million"],
                                 output_bound, price["output_usd_per_million"])
        if not _json_number_is_exact(reservation):
            raise ss.SingleSendError("strict_parser")
        self.reservation = reservation
        if self.reservation > _decimal(f["cost_cap_usd"]):
            raise ss.SingleSendError("quota")
        te = self.context.tool_executor
        if te is not None and getattr(te, "policy_engine", None) is not None:
            from temper_ai.safety.base import ActionType
            decision = te.policy_engine.evaluate(ActionType.LLM_CALL,
                {"provider": self.config["provider"], "model": self.config["model"],
                 "reservation_usd": float(self.reservation), "max_tokens": f["max_tokens"]},
                {"run_cost_usd": te.run_cost_usd, "run_tokens": te.run_tokens})
            if decision.action != "allow":
                raise ss.SingleSendError("quota")
        claim = {"schema": "context-t1-claim/v1", "slot": self.slot, "family": f["family"],
                 "run_id": self.run_id, "session_id": self.session_id,
                 **{k: f[k] for k in ("experiment_id", "binding_id", "route", "auth_mode", *_DIGEST_FIELDS)},
                 "provider": self.config["provider"], "model": self.config["model"],
                 "input_sha256": f["prompt_sha256"], "reservation_usd": str(self.reservation),
                 "cost_cap_usd": str(_decimal(f["cost_cap_usd"])),
                 "serialized_body_sha256": request["serialized_body_sha256"],
                 "serialized_body_bytes": request["serialized_body_bytes"],
                 "output_bound_mode": f["output_bound_mode"], "output_bound_tokens": self.output_bound,
                 "output_bound_evidence_sha256": self.evidence,
                 "dispatch_monotonic_s": self.start, "started_utc": self.started,
                 "deadline_monotonic_s": self.deadline, "deadline_s": 900}
        _private_root(root)
        _write_fd_once(claim_fd, _json_bytes(claim))
        os.fsync(root)  # M1: BOTH durable barriers precede transmission identity
        self.durable = True
        # Freeze contents, not merely inode identity. Any future request differs -> deny.
        self.prepared = request.copy()

    def call(self) -> None:
        provider, prompt, kwargs = self.validate()
        deadline = self.deadline
        if deadline is None:
            raise ss.SingleSendError("strict_parser")
        self.control = ss.SingleSendControl(deadline, self.prepare_and_make_durable, self.context.cancel_event)
        self.control.check()
        self.response = provider.complete([{"role": "user", "content": prompt}], single_send=True,
            single_send_control=self.control, model=self.config["model"], max_tokens=self.fixed["max_tokens"],
            output_bound_mode=self.fixed["output_bound_mode"], **kwargs)
        if len(self.control.transmission_ids) != 1 or not self.durable:
            raise ss.SingleSendError("retry")
        self.terminal = "COMPLETED"

    def _collect(self) -> None:
        if self.response is not None:
            meta = self.response.raw_response or {}
            try:
                self.usage = ss.reported_usage(meta.get("usage"), codex=self.fixed.get("family") == "B")
            except ss.SingleSendError:
                self.usage = ss.reported_usage(None, codex=self.fixed.get("family") == "B")
                if self.failure is None:
                    self.fail(ss.SingleSendError("strict_parser"))
        if not (self.control and self.control.transmission_ids):
            self.cost = Decimal(0)
        elif self.failure and self.failure.reason in ("cancel", "timeout") or self.control and self.control.cleanup_uncertain:
            self.cost = None
        else:
            self.cost = recompute_list_price_usd({"model": self.config["model"], "route": self.fixed.get("route"),
                                                  "usage": self.usage}, self.pricing)
        if self.cost is not None and self.reservation is not None and self.cost > self.reservation:
            self.fail(ss.SingleSendError("quota"))

    def persist(self) -> None:
        if not self.claimed:
            return
        root = self.root
        if root is None:
            raise ss.SingleSendError("crash")
        self._collect()
        if self.claim is not None:
            os.close(self.claim)
            self.claim = None
        if self.response is not None and self.response.content is not None:
            raw = self.response.content.encode("utf-8")
            self.raw_sha, self.raw_bytes, self.raw_path = ss.sha256(raw), len(raw), self._path("raw")
            _write_once(root, f"{self.slot}.raw", raw)
        call = self.call_record()
        _write_once(root, f"{self.slot}.call.json", _json_bytes(call))
        os.fsync(root)
        self.cleanup_sample = ss.paired_sample()
        if self.control and self.control.cleanup_uncertain or not self.within_bounds(*self.cleanup_sample):
            self.cleanup = "UNCERTAIN"
            self.fail(ss.SingleSendError("timeout"))
            self.cost = None if self.control and self.control.transmission_ids else Decimal(0)
        self.record = self.attempt_record()
        _write_once(root, f"{self.slot}.attempt.json", _json_bytes(self.record))
        os.fsync(root)
        self.persisted = True
        if not self.within_bounds(*ss.paired_sample()):
            self.cleanup = "UNCERTAIN"
            self.fail(ss.SingleSendError("timeout"))

    def within_bounds(self, monotonic: float, utc: str) -> bool:
        if self.start is None or self.started is None or self.deadline is None:
            return False
        utc_delta = (datetime.fromisoformat(utc) - datetime.fromisoformat(self.started)).total_seconds()
        return self.start <= monotonic <= self.deadline and 0 <= utc_delta <= 900

    def _accounting(self) -> dict:
        known_usage = all(self.usage[k] is not None for k in ("input_tokens", "output_tokens"))
        return {"usage_state": "KNOWN" if known_usage else "UNKNOWN",
                "cost_state": "KNOWN" if self.cost is not None else "UNKNOWN",
                "list_price_usd": float(self.cost) if self.cost is not None else None,
                "reservation_usd": float(self.reservation) if self.reservation is not None else None,
                "unknown_exposure_usd": 0 if self.cost is not None else (float(self.reservation) if self.reservation is not None else None)}

    def call_record(self) -> dict:
        c = self.control
        request = c.request if c and c.request else getattr(self, "prepared", {})
        meta = self.response.raw_response if self.response and self.response.raw_response else {}
        stop = self.response.finish_reason if self.response and self.response.finish_reason in _STOPS else None
        latency = None
        if c and c.ended_monotonic_s is not None and c.http_started_monotonic_s is not None:
            latency = max(0, int((c.ended_monotonic_s - c.http_started_monotonic_s) * 1000))
        return {"schema": "context-t1-call/v1", "slot": self.slot, "run_id": self.run_id,
                "session_id": self.session_id, "workflow_run_id": self.context.run_id,
                **self.call_identity,
                "raw_path": self.raw_path, "raw_bytes": self.raw_bytes, "raw_sha256": self.raw_sha,
                "output_bound_tokens": self.output_bound, "output_bound_evidence_sha256": self.evidence,
                "serialized_body_sha256": request.get("serialized_body_sha256"),
                "serialized_body_bytes": request.get("serialized_body_bytes"),
                "input_parts": request.get("input_parts", []), "parameters": request.get("parameters", {}),
                "usage": self.usage, "stop_reason": stop, "response_id": ss.safe_response_id(meta.get("response_id")),
                "error_class": self.failure.error_class if self.failure else None,
                "http_status": self.failure.status if self.failure else None,
                "http_started_monotonic_s": c.http_started_monotonic_s if c else None,
                "http_started_utc": c.http_started_utc if c else None,
                "transport_ended_monotonic_s": c.ended_monotonic_s if c else None,
                "transport_ended_utc": c.ended_utc if c else None,
                "latency_ms": latency, "dispatch_monotonic_s": self.start, "started_utc": self.started,
                "deadline_monotonic_s": self.deadline, "deadline_s": 900, **self._accounting()}

    def attempt_record(self) -> dict:
        f = self.fixed
        def binding(key: str) -> Any:
            value = f.get(key)
            if key.endswith("sha256"):
                return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None
            return value if isinstance(value, str) and value else None
        # Fixed digests are declared bindings; route identities are admitted observations.
        return {"schema": "context-t1-attempt/v1", "slot": self.slot, "family": self.slot[0],
                **{k: binding(k) for k in ("experiment_id", "binding_id", "source_sha256", "config_sha256", "pricing_sha256", "packet_sha256")},
                **{k: self.call_identity[k] for k in ("provider", "model", "route", "auth_mode")},
                "session_id": self.session_id, "run_id": self.run_id,
                "input_sha256": binding("prompt_sha256"), "raw_sha256": self.raw_sha,
                "terminal": self.terminal, "transmissions": len(self.control.transmission_ids) if self.control else 0,
                "transmission_ids": list(self.control.transmission_ids) if self.control else [],
                **self._accounting(), "cleanup": self.cleanup, "started_utc": self.started,
                "ended_utc": self.control.ended_utc if self.control else (self.cleanup_sample[1] if self.cleanup_sample else None),
                "cleanup_utc": self.cleanup_sample[1] if self.cleanup_sample else None,
                "dispatch_monotonic_s": self.start, "deadline_monotonic_s": self.deadline,
                "cleanup_monotonic_s": self.cleanup_sample[0] if self.cleanup_sample else None,
                "deadline_s": 900, "resumed": False, "fallback": False,
                "failure_reasons": [self.failure.reason] if self.failure else []}

    def close(self) -> None:
        for name in ("claim", "root"):
            fd = getattr(self, name)
            setattr(self, name, None)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    self.cleanup = "UNCERTAIN"
                    self.fail(ss.SingleSendError("crash"))

    def summary(self) -> dict:
        result = {"terminal": self.terminal, "slot": self.slot if isinstance(self.slot, str) and self.slot in _SLOTS else None,
                  "cleanup": self.cleanup, "receipt_persisted": self.persisted,
                  "transmissions": len(self.control.transmission_ids) if self.control else 0,
                  "failure_reasons": [self.failure.reason] if self.failure else [],
                  "error_class": self.failure.error_class if self.failure else None,
                  "http_status": self.failure.status if self.failure else None, **self._accounting()}
        if self.claimed:
            result.update({"attempt_path": self._path("attempt.json") if self.persisted else None,
                           "call_path": self._path("call.json"), "raw_path": self.raw_path,
                           "raw_sha256": self.raw_sha, "raw_bytes": self.raw_bytes})
        return result


class SingleCallAgent(AgentABC):
    """The generic snippet below is schematic, not a runnable configuration.

    Required provider, model and fixed inputs are specified in the
    [full single_call contract](../../single-call.md). No workflow is activated.
    """

    uses_llm_settings = False

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        fixed = self.config.get("single_call")
        if set(self.config) - SINGLE_CALL_AGENT_SETTINGS or not isinstance(fixed, dict):
            errors.append("single_call requires a closed fixed-input mapping")
        elif set(fixed) - SINGLE_CALL_SETTINGS or not SINGLE_CALL_REQUIRED <= fixed.keys():
            errors.append("single_call has missing or unsupported fixed inputs")
        if not self.config.get("provider") or not self.config.get("model"):
            errors.append("single_call requires an explicit provider and model")
        return errors

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        state = _Attempt(self.config, context)
        with ss.metadata_only_logs():
            agent_event = context.parent_event_id
            try:
                try:
                    state.claim_slot()
                    if context.event_recorder is not None:
                        agent_event = context.event_recorder.record(EventType.AGENT_STARTED,
                            parent_id=context.parent_event_id, execution_id=context.run_id, status="running",
                            data={"agent_name": self.name, "agent_type": "single_call", "node_path": context.node_path,
                                  "provider": state.call_identity["provider"], "model": state.call_identity["model"]})
                    state.call()
                except Exception as exc:  # noqa: BLE001 - never propagate provider/file prose
                    state.fail(exc)
                try:
                    state.persist()
                except Exception:  # noqa: BLE001 - missing/invalid receipt is never success
                    state.cleanup = "UNCERTAIN"
                    state.fail(ss.SingleSendError("crash"))
                    state.persisted = False
                    if state.control and state.control.transmission_ids:
                        state.cost = None
            finally:
                state.close()
            metadata = state.summary()
            failed = state.terminal != "COMPLETED" or not state.persisted
            if context.event_recorder is not None:
                try:
                    context.event_recorder.record(EventType.SINGLE_CALL_ATTEMPT,
                        parent_id=agent_event, execution_id=context.run_id,
                        status="failed" if failed else "completed", data=metadata)
                    context.event_recorder.record(EventType.AGENT_FAILED if failed else EventType.AGENT_COMPLETED,
                        parent_id=agent_event, execution_id=context.run_id, status="failed" if failed else "completed",
                        data={"agent_name": self.name, **metadata,
                              "cost_usd": float(state.cost) if state.cost is not None else 0.0,
                              "tokens": (state.usage["input_tokens"] or 0) + (state.usage["output_tokens"] or 0),
                              "llm_calls": len(state.control.transmission_ids) if state.control else 0})
                except Exception:  # noqa: BLE001 - event sink failure cannot retry a paid call
                    failed = True
                    metadata = {**metadata, "terminal": "FAILED", "event_receipt_failed": True}
            cost = float(state.cost) if state.cost is not None and math.isfinite(float(state.cost)) else 0.0
            if context.tool_executor is not None and (state.usage["input_tokens"] is not None or state.cost is not None):
                try:
                    context.tool_executor.track_usage(
                        (state.usage["input_tokens"] or 0) + (state.usage["output_tokens"] or 0), cost)
                except Exception:  # noqa: BLE001 - tracking must not resend or leak error text
                    failed = True
                    metadata = {**metadata, "terminal": "FAILED", "usage_tracking_failed": True}
            return AgentResult(status=Status.FAILED if failed else Status.COMPLETED,
                output=json.dumps(metadata, sort_keys=True), structured_output=metadata, metadata=metadata,
                error="single_call_failed" if failed else None, cost_usd=cost,
                tokens=TokenUsage(prompt_tokens=state.usage["input_tokens"] or 0,
                                  completion_tokens=state.usage["output_tokens"] or 0,
                                  total_tokens=(state.usage["input_tokens"] or 0) + (state.usage["output_tokens"] or 0)),
                llm_calls=len(state.control.transmission_ids) if state.control else 0,
                duration_seconds=max(0.0, time.monotonic() - state.start) if state.start is not None else 0.0)
