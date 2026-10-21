"""Opt-in one-request controls. No credentials, fallback, model text events or files.

The logging boundary covers Python LogRecords only, not a previous factory's own
exports, non-Python telemetry, same-UID code or provider-side cancellation.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx

from temper_ai.llm.models import LLMResponse
from temper_ai.shared.clock import utcnow

SINGLE_CALL_CLEANUP_MARGIN_S = 5.0
USAGE_COUNTERS = ("input_tokens", "output_tokens", "total_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
_metadata_only: contextvars.ContextVar[bool] = contextvars.ContextVar("single_send_metadata_only", default=False)
_factory_lock = threading.Lock()
_metadata_factory: Callable[..., logging.LogRecord] | None = None


def _install_metadata_log_factory() -> None:
    global _metadata_factory
    with _factory_lock:
        previous = logging.getLogRecordFactory()
        if previous is _metadata_factory:
            return

        def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            row = previous(*args, **kwargs)
            if _metadata_only.get():
                row.msg = "single_send transport log (content redacted)"
                row.args = ()
                row.exc_info = None
                row.exc_text = None
                row.stack_info = None
            return row

        logging.setLogRecordFactory(factory)
        _metadata_factory = factory


@contextmanager
def metadata_only_logs() -> Iterator[None]:
    """Redact, never drop, records in this context; restore nested scope on exit."""
    _install_metadata_log_factory()
    token = _metadata_only.set(True)
    try:
        yield
    finally:
        _metadata_only.reset(token)


def paired_sample() -> tuple[float, str]:
    """Two actual observations, not one clock reconstructed from the other."""
    return time.monotonic(), utcnow().isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def counter(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def safe_response_id(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"(?:msg|resp)[_-][A-Za-z0-9_-]{1,120}", value) else None


class SingleSendError(Exception):
    """Safe error identity; optional answer stays in memory until private raw write."""

    def __init__(self, reason: str, *, error_class: str = "SingleSendError", status: int | None = None,
                 response: LLMResponse | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.error_class = error_class if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_class) else "TransportError"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        self.response = response


def reported_usage(value: Any, *, codex: bool = False) -> dict[str, Any]:
    """Closed numeric usage only: null is unreported, never an inferred zero.

    Responses details are subsets of their reported totals, not extra tokens.
    Other transports' cache fields may be null placeholders on Codex receipts,
    but a non-null outside-input category is not a Responses usage shape.
    """
    value = {} if value is None else value
    details = {"input_tokens_details": ("cached_tokens", "input_tokens"),
               "output_tokens_details": ("reasoning_tokens", "output_tokens")}
    allowed = set(USAGE_COUNTERS) | (details.keys() if codex else set())
    if not isinstance(value, dict) or set(value) - allowed:
        raise SingleSendError("strict_parser")
    usage = {key: value.get(key) for key in USAGE_COUNTERS}
    if any(count is not None and counter(count) is None for count in usage.values()):
        raise SingleSendError("strict_parser")
    if codex:
        if any(usage[key] is not None for key in ("cache_read_input_tokens", "cache_creation_input_tokens")):
            raise SingleSendError("strict_parser")
        for name, (key, parent) in details.items():
            split = value.get(name)
            if split is not None:
                if not isinstance(split, dict) or set(split) - {key}:
                    raise SingleSendError("strict_parser")
                count = split.get(key)
                if count is not None and (counter(count) is None or usage[parent] is None or count > usage[parent]):
                    raise SingleSendError("strict_parser")
                split = split.copy()
            usage[name] = split
    return usage


def safe_failure(exc: Exception, response: LLMResponse | None = None) -> SingleSendError:
    """Copy only class/status/enum; never retain the exception or its prose/chain."""
    # The SDK wraps our own request-hook refusal (e.g. APIConnectionError from
    # SingleSendError); keep the gate's own reason, not a generic transport one.
    own = exc if isinstance(exc, SingleSendError) else exc.__cause__
    if isinstance(own, SingleSendError):
        return SingleSendError(own.reason, error_class=own.error_class, status=own.status,
                               response=own.response or response)
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    # _call_pinned turns a quota HTTP error into TokenCooling with unsafe detail.
    cause = exc.__cause__
    if status is None and cause is not None:
        status = getattr(cause, "status_code", None)
    name = type(exc).__name__
    reason = "transport"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or "Timeout" in name:
        reason = "timeout"
    elif status in (401, 403):
        reason = "auth"
    elif status in (429, 529) or name in ("TokenCooling", "PoolExhausted"):
        reason = "quota"
    return SingleSendError(reason, error_class=name, status=status, response=response)


def _part(kind: str, text: str, ordinal: int) -> dict[str, Any]:
    raw = text.encode("utf-8")
    return {"kind": kind, "ordinal": ordinal, "bytes": len(raw), "sha256": sha256(raw)}


def request_metadata(raw: bytes) -> dict[str, Any]:
    """Digest EVERY input text part on the final wire body, never return its text."""
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise SingleSendError("strict_parser")
    parts: list[dict[str, Any]] = []

    def text(kind: str, value: Any) -> None:
        if isinstance(value, str):
            parts.append(_part(kind, value, len(parts)))
        elif isinstance(value, list):
            for block in value:
                if not isinstance(block, dict) or block.get("type") not in ("text", "input_text"):
                    raise SingleSendError("strict_parser")
                if set(block) - {"type", "text"} or not isinstance(block.get("text"), str):
                    raise SingleSendError("strict_parser")
                text(kind, block["text"])
        else:
            raise SingleSendError("strict_parser")

    if "messages" in body:
        allowed = {"model", "messages", "system", "max_tokens", "temperature", "thinking", "output_config", "stream"}
        if "system" in body:
            text("system", body["system"])
        for message in body["messages"]:
            if set(message) - {"role", "content"} or message.get("role") != "user":
                raise SingleSendError("strict_parser")
            text("prompt", message["content"])
    else:
        allowed = {"model", "store", "stream", "instructions", "input", "text", "tool_choice",
                   "parallel_tool_calls", "max_output_tokens"}
        text("instructions", body["instructions"])
        for item in body["input"]:
            if set(item) - {"type", "role", "content"} or item.get("role") != "user" or item.get("type") != "message":
                raise SingleSendError("strict_parser")
            text("prompt", item["content"])
    if set(body) - allowed:
        raise SingleSendError("strict_parser")
    params = {key: body[key] for key in ("max_tokens", "max_output_tokens", "temperature", "thinking", "output_config", "stream") if key in body}
    # These values are fixed knobs, not a free-text metadata escape hatch.
    for key in ("max_tokens", "max_output_tokens"):
        if key in params and (type(params[key]) is not int or params[key] <= 0):
            raise SingleSendError("strict_parser")
    if "temperature" in params and (type(params["temperature"]) not in (int, float) or not 0 <= params["temperature"] <= 2):
        raise SingleSendError("strict_parser")
    thinking = params.get("thinking")
    if thinking is not None:
        if not isinstance(thinking, dict) or set(thinking) - {"type", "display", "budget_tokens"}:
            raise SingleSendError("strict_parser")
        if thinking.get("type") not in ("adaptive", "enabled", "disabled") or thinking.get("display", "summarized") != "summarized":
            raise SingleSendError("strict_parser")
        if "budget_tokens" in thinking and (type(thinking["budget_tokens"]) is not int or thinking["budget_tokens"] <= 0):
            raise SingleSendError("strict_parser")
    output = params.get("output_config")
    if output is not None and (not isinstance(output, dict) or set(output) != {"effort"} or output["effort"] not in ("low", "medium", "high", "max")):
        raise SingleSendError("strict_parser")
    if params.get("stream") is not True:
        raise SingleSendError("strict_parser")
    return {"serialized_body_sha256": sha256(raw), "serialized_body_bytes": len(raw),
            "input_parts": parts, "parameters": params, "model": body["model"]}


@dataclass
class SingleSendControl:
    """One monotonic deadline and one initiated-request hook; no retry state."""

    deadline_monotonic_s: float
    on_pre_send: Callable[[dict[str, Any]], None]
    cancel_event: Any = None
    transmission_ids: list[str] = field(default_factory=list)
    request: dict[str, Any] | None = None
    http_started_monotonic_s: float | None = None
    http_started_utc: str | None = None
    ended_monotonic_s: float | None = None
    ended_utc: str | None = None
    cleanup_uncertain: bool = False
    failure_reason: str | None = None
    _closers: list[Callable[[], Any]] = field(default_factory=list, repr=False)
    _close_lock: Any = field(default_factory=threading.Lock, repr=False)
    _watchdog: Any = field(default=None, repr=False)

    def remaining(self) -> float:
        self.check()
        return self.deadline_monotonic_s - SINGLE_CALL_CLEANUP_MARGIN_S - time.monotonic()

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SingleSendError("cancel")
        if time.monotonic() >= self.deadline_monotonic_s - SINGLE_CALL_CLEANUP_MARGIN_S:
            raise SingleSendError("timeout")
        if self.failure_reason:
            raise SingleSendError(self.failure_reason)

    def request_start(self, request: httpx.Request) -> None:
        self.check()
        if self.transmission_ids:
            raise SingleSendError("retry")
        metadata = request_metadata(request.content)
        self.on_pre_send(metadata)  # includes durable claim fsync THEN directory fsync
        self.check()
        if request_metadata(request.content) != metadata:
            raise SingleSendError("strict_parser")
        self.request = metadata
        self.http_started_monotonic_s, self.http_started_utc = paired_sample()
        self.transmission_ids.append(str(uuid.uuid4()))

    def own(self, closer: Callable[[], Any]) -> None:
        with self._close_lock:
            self._closers.append(closer)
        if self._watchdog is None:
            self._watchdog = BoundedWatchdog(self)
            self._watchdog.start()

    def close_owned(self) -> None:
        with metadata_only_logs():
            while True:
                with self._close_lock:
                    if not self._closers:
                        return
                    close = self._closers.pop()
                try:
                    close()
                except Exception:  # noqa: BLE001 - error prose never leaves protected scope
                    self.cleanup_uncertain = True

    def finish(self) -> None:
        # Socket/SDK close can itself block. Never run it synchronously on the
        # caller: the privacy-scoped worker owns it and the caller's join is bounded.
        if self._watchdog is not None:
            if not self._watchdog.thread.is_alive() and self._closers:
                self._watchdog = BoundedWatchdog(self)
                self._watchdog.start()
            if not self._watchdog.disarm_join():
                self.cleanup_uncertain = True
                self.failure_reason = "timeout"
        self.ended_monotonic_s, self.ended_utc = paired_sample()


class BoundedWatchdog:
    """Closes owned transport on deadline/cancel; never sends. Not process isolation."""

    def __init__(self, control: SingleSendControl) -> None:
        self.control = control
        self.disarmed = threading.Event()
        self.cleanup_requested = threading.Event()
        self.thread = threading.Thread(target=self._run, name="single-send-close", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        # A raw thread has no caller ContextVar state. Enter its OWN scope.
        with metadata_only_logs():
            while not self.disarmed.is_set():
                if self.cleanup_requested.is_set():
                    self.control.close_owned()
                    return
                try:
                    left = self.control.remaining()
                except SingleSendError as exc:
                    self.control.failure_reason = exc.reason
                    self.control.close_owned()
                    return
                self.cleanup_requested.wait(min(left, 0.05))

    def disarm_join(self) -> bool:
        self.cleanup_requested.set()
        self.thread.join(timeout=max(0.0, self.control.deadline_monotonic_s - time.monotonic()))
        self.disarmed.set()  # no more timer actions, even if close is still blocked
        return not self.thread.is_alive()


def new_http_client(control: SingleSendControl) -> httpx.Client:
    """Owned retry-free, redirect-free client; strict calls never share its hooks."""
    return httpx.Client(timeout=control.remaining(), follow_redirects=False, trust_env=False,
                        transport=httpx.HTTPTransport(retries=0),
                        event_hooks={"request": [control.request_start]})


def strict_control(kwargs: dict[str, Any]) -> SingleSendControl:
    control = kwargs.get("single_send_control")
    if not isinstance(control, SingleSendControl):
        raise SingleSendError("strict_parser")
    return control
