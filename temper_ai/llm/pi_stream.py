"""Pi's RPC stream as Temper events (used by the Pi agent step, ``temper_ai.pi_agent``).

The Pi agent step is off by default (``TEMPER_PI_AGENT``); nothing else calls this module.

Pi (``pi --mode rpc``) writes one JSON object per line. This module turns that stream into
the events Temper already records and shows, so a Pi agent's run reads like any other:

- each assistant message is one model call: ``llm.call.started`` when it starts, its words
  as live stream chunks (``content`` / ``thinking``; ephemeral, numbered per call), then
  ``llm.call.completed`` or ``llm.call.failed`` from Pi's final message. The final message
  is authoritative: what it says replaces whatever the live chunks said;
- a tool call the model *writes* is only a ``tool_call`` chunk; a tool Pi *runs* is
  ``tool.call.started`` then ``tool.call.completed`` / ``tool.call.failed``. Progress while a
  tool runs is Pi's latest snapshot, sent as a ``tool_progress`` chunk that replaces the
  previous one and is never stored;
- automatic retries are ``llm.retry`` events; a compaction is a model call of its own;
- usage is taken once per model call, from its final message (Pi repeats the running
  total on every update, so adding those up would count it many times).

A model call ending is not the agent ending, and Pi going idle is not success: only
:meth:`PiEventMapper.finish`, after Pi settles, decides how the agent's turn went.

Event ids are derived from the run, the agent and Pi's own ids, so reading the same stream
again (after a worker restart) maps to the same ids and nothing is recorded twice. Ids that
Pi may repeat are scoped: a retry by the model call it retries (G1), a tool by the model call
that asked for it (G2). A call or tool already finished in an earlier reading sends no live
chunks again (G3).

Pi's ``system`` message declares the prompt and tools sent to the model: it is never read,
mapped or stored here. Configured secret values and secret-named fields are replaced before
anything is recorded or broadcast, including a secret split across two streamed deltas. A
caller may inject one more rule (:class:`Guard`; the Pi lane's login-token rule): it sees
original text BEFORE secret substitutions can break a shaped span, and before display cuts.
A live stream lets out no character of a match however the deltas split.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from temper_ai.llm.provider_tools import OUTPUT_LIMIT, classify_tool
from temper_ai.observability.event_types import EventType

REDACTED = "[redacted]"
DEFAULT_SECRET_FIELDS = ("api_key", "apikey", "token", "password", "secret", "authorization", "cookie")
MIN_SECRET_LENGTH = 6
MAX_LINE_BYTES = 16 * 1024 * 1024
PROGRESS_LIMIT = 2_000  # chars of a running tool's latest output shown live
ERROR_LIMIT = 500
CONSTRUCTION_ARGS_LIMIT = 300
MAX_COUNTED_TYPES = 64
AGENT_OUTPUT_LIMIT = 5_000  # same cut as llm_agent's agent.completed

_ID_NAMESPACE = uuid.UUID("7b0f6c52-4f3e-4f1e-9a51-2f0b5c1a2a02")

# Pi events that carry nothing a Temper run shows: counted, never mapped.
IGNORED_EVENTS = frozenset({
    "queue_update", "entry_appended", "session_info_changed", "thinking_level_changed",
    "extension_ui_request", "session_start", "session_shutdown", "model_change",
    "bash_execution_update", "summarization_retry_scheduled", "summarization_retry_attempt_start",
    "summarization_retry_finished",
})
FAILED_STOPS = frozenset({"error", "aborted"})


class PiStreamError(ValueError):
    """The stream broke Pi's framing: a line that is not one UTF-8 JSON object."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class JsonlSplitter:
    """Split Pi's stdout into JSON objects.

    Only LF ends a record (a trailing CR is dropped). JSON strings may hold U+2028/U+2029,
    which ``str.splitlines`` would wrongly treat as line ends, so splitting is done on bytes.
    Each complete line is decoded as strict UTF-8, so a multi-byte character cut between two
    reads is fine; a line that never ends is an error at EOF.
    """

    def __init__(self, max_line_bytes: int = MAX_LINE_BYTES):
        self._buf = bytearray()
        self._max = max_line_bytes

    def feed(self, data: bytes) -> list[dict]:
        # What is left from earlier reads holds no line end: search only the new bytes,
        # so a long line read in small pieces costs its length, not its length squared.
        search = len(self._buf)
        self._buf += data
        out: list[dict] = []
        start = 0
        while True:
            end = self._buf.find(b"\n", search)
            if end < 0:
                break
            line = bytes(self._buf[start:end])
            start = search = end + 1
            if line.endswith(b"\r"):
                line = line[:-1]
            if len(line) > self._max:
                raise PiStreamError("line_too_long", f"{len(line)} bytes")
            if line.strip():
                out.append(self._parse(line))
        del self._buf[:start]
        if len(self._buf) > self._max:
            raise PiStreamError("line_too_long", f"over {self._max} bytes without a line end")
        return out

    def finish(self) -> None:
        if self._buf.strip():
            raise PiStreamError("incomplete_line_at_eof", f"{len(self._buf)} bytes")

    @staticmethod
    def _parse(line: bytes) -> dict:
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PiStreamError("invalid_utf8", str(exc.reason)) from None
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise PiStreamError("invalid_json", exc.__class__.__name__) from None
        if not isinstance(value, dict):
            raise PiStreamError("not_an_object", type(value).__name__)
        return value


class GuardStream(Protocol):
    """A :class:`Guard`'s rule for a text that arrives in pieces."""

    def feed(self, piece: str) -> str: ...

    def flush(self) -> str: ...


class Guard(Protocol):
    """One more rule a caller injects into a :class:`Redactor` (the Pi lane's login-token
    rule, temper_ai/pi_agent/event_guard.py): this module never imports it. Implementations
    may optionally provide ``compose_text(value, secrets, marker)`` and
    ``compose_stream(secrets_getter, marker)`` to merge original protection spans with exact
    secrets while retaining their marker. The three basic hooks remain sufficient."""

    def text(self, value: str) -> str: ...

    def obj(self, value: Any) -> Any: ...

    def stream(self) -> GuardStream: ...


class Redactor:
    """Compose an optional original-span guard with exact secrets. Field decisions use
    original keys; outgoing keys are protected independently. Without a guard, defaults stay
    unchanged."""

    def __init__(self, secrets: Iterable[str] = (), fields: Iterable[str] = DEFAULT_SECRET_FIELDS,
                 guard: Guard | None = None):
        self.secrets = sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LENGTH}, key=len, reverse=True)
        self.fields = tuple(f.lower() for f in fields)
        self.guard = guard

    def add(self, *secrets: str) -> None:
        """Learn more secret values (a credential handed to the worker mid-turn). Call it before
        the value can reach anything mapped. The list is replaced in one assignment, so a reader
        on another thread sees either the old list or the new one."""
        new = {s for s in secrets if isinstance(s, str) and len(s) >= MIN_SECRET_LENGTH}
        if new - set(self.secrets):
            self.secrets = sorted(set(self.secrets) | new, key=len, reverse=True)

    def text(self, value: Any) -> Any:
        compose = getattr(self.guard, "compose_text", None)
        if callable(compose) and isinstance(value, str):
            return compose(value, self.secrets, REDACTED)
        return self.unguarded_text(self.guard_text(value))

    def answer_for_refusal(self, value: str) -> str:
        """Keep a rule-matching ORIGINAL answer for whole-answer refusal. Otherwise preserve
        exact-secret masking, including secrets learned mid-turn only through :meth:`add`.
        The guard must see the original before a substitution can destroy its shape."""
        return value if self.guard_text(value) != value else self.unguarded_text(value)

    def unguarded_text(self, value: Any) -> Any:
        """Replace exact secrets only. Guarded writes apply their rule BEFORE this step;
        a caller's whole-answer refusal instead uses :meth:`answer_for_refusal`."""
        if not isinstance(value, str) or not self.secrets:
            return value
        for secret in self.secrets:
            if secret in value:
                value = value.replace(secret, REDACTED)
        return value

    def guard_text(self, value: Any) -> Any:
        """``value`` with the guard's rule applied (unchanged when there is no guard)."""
        if self.guard is None or not isinstance(value, str):
            return value
        return self.guard.text(value)

    def obj(self, value: Any) -> Any:
        if self.guard is None:
            return self._unguarded_obj(value)

        def protect(original: Any) -> Any:
            if isinstance(original, str):
                return self.text(original)
            if isinstance(original, dict):
                out: dict = {}
                for key, item in original.items():
                    # The guard's generated marker may itself contain a secret-field word.
                    # Only the ORIGINAL key decides field masking; no outgoing key is raw.
                    new_key = self.text(key)
                    new_item = REDACTED if self._secret_field(key) else protect(item)
                    if new_key in out:
                        number = 2
                        while f"{new_key} ({number})" in out:
                            number += 1
                        new_key = f"{new_key} ({number})"
                    out[new_key] = new_item
                return out
            if isinstance(original, (list, tuple)):
                items = [protect(item) for item in original]
                return items if isinstance(original, list) else tuple(items)
            return original

        return self.guard.obj(protect(value))

    def _unguarded_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.unguarded_text(value)
        if isinstance(value, dict):
            return {k: (REDACTED if self._secret_field(k) else self._unguarded_obj(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._unguarded_obj(v) for v in value]
        return value

    def _secret_field(self, key: Any) -> bool:
        k = str(key).lower().replace("-", "_")
        return any(f in k for f in self.fields)

    def stream(self) -> StreamRedaction:
        return StreamRedaction(self)


class StreamRedaction:
    """Redact a text that arrives in pieces: hold back any tail that could be the start of a
    secret, so a secret split across two deltas never goes out in either. An injected guard
    sees the ORIGINAL stream first: learned-secret markers cannot break a matching shape."""

    def __init__(self, redactor: Redactor):
        self._r = redactor
        self._buf = ""
        compose = getattr(redactor.guard, "compose_stream", None)
        self._composed = callable(compose)
        self._guard = (compose(lambda: redactor.secrets, REDACTED) if callable(compose)
                       else redactor.guard.stream() if redactor.guard is not None else None)

    def feed(self, piece: str) -> str:
        if self._guard is not None:
            piece = self._guard.feed(piece)
        return piece if self._composed else self._feed_secrets(piece)

    def _feed_secrets(self, piece: str) -> str:
        if not self._r.secrets:
            return piece
        self._buf = self._r.unguarded_text(self._buf + piece)
        hold = 0
        for k in range(min(len(self._buf), len(self._r.secrets[0]) - 1), 0, -1):
            tail = self._buf[-k:]
            if any(s.startswith(tail) for s in self._r.secrets):
                hold = k
                break
        out, self._buf = self._buf[: len(self._buf) - hold], self._buf[len(self._buf) - hold:]
        return out

    def flush(self) -> str:
        if self._composed and self._guard is not None:
            return self._guard.flush()
        out = self._feed_secrets(self._guard.flush()) if self._guard is not None else ""
        tail, self._buf = self._buf, ""
        return out + tail


class Recorder(Protocol):
    """The part of :class:`temper_ai.observability.event_recorder.EventRecorder` used here."""

    def record(self, event_type: EventType, data: dict | None = None, parent_id: str | None = None,
               execution_id: str | None = None, status: str | None = None,
               event_id: str | None = None) -> str: ...

    def broadcast_stream_chunk(self, agent_id: str, content: str, chunk_type: str = "content",
                               done: bool = False, call_id: str | None = None,
                               seq: int | None = None) -> None: ...


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n…[{len(text) - limit} more chars]", True


def _obj(value: Any) -> dict:
    """A field Pi documents as an object, or an empty one when it is anything else."""
    return value if isinstance(value, dict) else {}


def _usage(raw: Any) -> dict[str, Any]:
    u = _obj(raw)
    cost = _obj(u.get("cost"))

    def num(v: Any) -> int:
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    return {
        "prompt_tokens": num(u.get("input")),
        "completion_tokens": num(u.get("output")),
        "cached_prompt_tokens": num(u.get("cacheRead")),
        "cache_write_tokens": num(u.get("cacheWrite")),
        "total_tokens": num(u.get("totalTokens")),
        "cost_usd": float(cost.get("total") or 0.0),
        # Pi prices tokens from its model table; on a subscription nobody is billed this.
        "cost_basis": "pi_estimate",
    }


@dataclass
class _Call:
    id: str
    ordinal: int
    kind: str = "model"
    seq: int = 0
    streams: dict[str, StreamRedaction] = field(default_factory=dict)
    blocks: dict[str, int] = field(default_factory=lambda: {"text": 0, "thinking": 0})
    started: float = 0.0


@dataclass
class _Tool:
    raw_id: str
    call_id: str
    name: str
    llm_call_id: str | None
    started: float
    scope: str = ""
    progress_seq: int = 0
    common: dict = field(default_factory=dict)


@dataclass
class PiOutcome:
    """How one Pi agent turn went, decided once Pi settled."""

    status: str  # "completed" | "failed"
    output: str
    structured_output: dict | None
    errors: list[str]
    warnings: list[str]
    tokens: dict[str, Any]
    llm_calls: int
    tool_calls: int
    counts: dict[str, Any]
    #: How the last model reply ended (its stop reason; None when no reply ended) and, when
    #: it ended in an error, the provider's error text (redacted): the error path the Pi
    #: lane reads an account's refusal or limit from (ADR-M4-16), never the answer's text.
    last_stop: str | None = None
    last_error: str | None = None

    @property
    def error(self) -> str | None:
        return "; ".join(self.errors) if self.errors else None

    def agent_event_data(self, agent_name: str, duration_seconds: float | None = None,
                         scrub: Callable[[str], str] | None = None) -> dict:
        """The data of ``agent.completed`` / ``agent.failed``, shaped as llm_agent records it.
        ``scrub`` (the mapper's guard) applies to the output before it is cut."""
        output = scrub(self.output) if scrub else self.output
        data = {
            "agent_name": agent_name,
            "output": output[:AGENT_OUTPUT_LIMIT],
            "output_length": len(self.output),
            "has_structured_output": self.structured_output is not None,
            "structured_output": self.structured_output,
            "tokens": self.tokens["total_tokens"],
            "prompt_tokens": self.tokens["prompt_tokens"],
            "completion_tokens": self.tokens["completion_tokens"],
            "cost_usd": self.tokens["cost_usd"],
            "cost_basis": "pi_estimate",
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "duration_seconds": duration_seconds,
            "executed_by": "pi",
            "warnings": self.warnings,
        }
        if self.error:
            data["error"] = self.error
        return data


def validate_result(value: Any, schema: dict) -> list[str]:
    """A small result check: required keys and JSON types (``type`` per property).

    The JSON on Pi's wire is only transport; the agent's answer must still be checked
    against what the step promised to return.
    """
    types: dict[str, type | tuple[type, ...]] = {
        "string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    if not isinstance(value, dict):
        return ["the result is not a JSON object"]
    problems = [f"missing {k!r}" for k in schema.get("required", []) if k not in value]
    for key, spec in (schema.get("properties") or {}).items():
        want = spec.get("type") if isinstance(spec, dict) else None
        if key not in value or want not in types:
            continue
        v = value[key]
        ok = isinstance(v, types[want]) and not (want in ("integer", "number") and isinstance(v, bool))
        if not ok:
            problems.append(f"{key!r} is not {want}")
    return problems


class PiEventMapper:
    """Map one Pi session's events onto one Temper agent.

    Feed every parsed event to :meth:`handle` in order; call :meth:`finish` after Pi settled
    (or when the stream ended) to get the agent's outcome. Never raises on content it does
    not know: unknown events are counted and reported in the outcome.
    """

    def __init__(
        self,
        recorder: Recorder,
        *,
        execution_id: str,
        agent_event_id: str,
        agent_name: str,
        session_id: str,
        node_path: str | None = None,
        redactor: Redactor | None = None,
        known_event_ids: Iterable[str] = (),
        clock: Callable[[], float] = time.monotonic,
    ):
        self._rec = recorder
        self.execution_id = execution_id
        self.agent_id = agent_event_id
        self.agent_name = agent_name
        self.session_id = session_id
        self.node_path = node_path
        self.redact = redactor or Redactor()
        self._known = set(known_event_ids)
        # Recorded by an earlier reading of this stream: a call or tool whose end is in here is
        # finished, and reading it again sends no live chunks (G3).
        self._prior = frozenset(self._known)
        self._clock = clock
        self._ordinal = 0
        self._call: _Call | None = None
        self._compaction: _Call | None = None
        # Running tools by Pi's tool call id. Pi's ids are only unique within one model call's
        # request, so a tool is known by (requesting call, Pi id) and leaves this dict when it
        # ends: a later call reusing the id starts a new tool (G2).
        self._tools: dict[str, _Tool] = {}
        self._tool_count = 0
        self._requested_by: dict[str, str] = {}  # Pi tool call id -> llm call id that wrote it
        self._totals: Counter[str] = Counter()
        self._cost = 0.0
        self._counts: Counter = Counter()
        self._unknown: Counter = Counter()
        self._ignored: Counter = Counter()
        self._last_answer: dict | None = None  # last assistant message that ended
        self._rpc_failures: list[str] = []
        self.settled = False
        self.recorded: list[str] = []

    def usage_snapshot(self) -> dict[str, int | float]:
        """Usage known so far, including retries and compaction; no message content.
        A running team's spend must not wait for the whole turn to end (FLOW R4)."""
        return {"cost_usd": round(self._cost, 10), "total_tokens": self._totals["total_tokens"],
                "llm_calls": self._ordinal}

    # ---- ids and recording -------------------------------------------------

    def stable_id(self, *parts: Any) -> str:
        key = "|".join([self.execution_id, self.agent_id, self.session_id, *map(str, parts)])
        return str(uuid.uuid5(_ID_NAMESPACE, key))

    def _record(self, event_type: EventType, event_id: str, *, data: dict, status: str | None,
                parent_id: str | None = None) -> None:
        if event_id in self._known:
            return  # already recorded by an earlier reading of the same stream
        self._known.add(event_id)
        self._rec.record(event_type, data=data, parent_id=parent_id or self.agent_id,
                         execution_id=self.execution_id, status=status, event_id=event_id)
        self.recorded.append(event_id)

    def _chunk(self, call: _Call, content: str, chunk_type: str, done: bool = False) -> None:
        call.seq += 1
        if self.stable_id("llm-end", call.ordinal) in self._prior:
            self._counts["chunk:replay_suppressed"] += 1
            return  # finished in an earlier reading: the page already has its final (G3)
        self._rec.broadcast_stream_chunk(self.agent_id, content, chunk_type, done,
                                         call_id=call.id, seq=call.seq)
        self._counts[f"chunk:{chunk_type}"] += 1

    def _common(self) -> dict:
        return {"agent_id": self.agent_id, "agent_name": self.agent_name, "node_path": self.node_path,
                "executed_by": "pi", "pi_session_id": self.session_id}

    # ---- dispatch ----------------------------------------------------------

    def handle(self, event: dict) -> None:
        kind = event.get("type")
        if not isinstance(kind, str):
            self._count_unknown("<no type>")
            return
        handler = self._handlers.get(kind)
        if handler is not None:
            self._counts[kind] += 1  # known kinds only: unknown ones are counted, capped, below
            handler(self, event)
        elif kind in IGNORED_EVENTS:
            self._ignored[kind] += 1
        else:
            self._count_unknown(kind)

    def handle_all(self, events: Iterable[dict]) -> None:
        for event in events:
            self.handle(event)

    @property
    def open_tool_calls(self) -> int:
        """Tools Pi started and has not ended: a turn stopped now leaves them dangling."""
        return len(self._tools)

    @property
    def call_ids(self) -> list[str]:
        """Ids of the model calls mapped so far (``llm.call.started`` events)."""
        return [self.stable_id("llm", n) for n in range(1, self._ordinal + 1)]

    def _count_unknown(self, kind: str) -> None:
        if kind in self._unknown or len(self._unknown) < MAX_COUNTED_TYPES:
            self._unknown[kind] += 1
        else:
            self._unknown["<other>"] += 1

    # ---- model calls -------------------------------------------------------

    def _on_message_start(self, event: dict) -> None:
        msg = _obj(event.get("message"))
        if msg.get("role") != "assistant":
            # system (prompt and tools sent to the model), user and tool results: not mapped.
            self._ignored[f"message:{msg.get('role')}"] += 1
            return
        self._ordinal += 1
        call = _Call(id=self.stable_id("llm", self._ordinal), ordinal=self._ordinal, started=self._clock())
        self._call = call
        self._record(EventType.LLM_CALL_STARTED, call.id, status="running", data={
            **self._common(), "llm_call_id": call.id, "call_kind": "model", "iteration": call.ordinal,
            "provider": msg.get("provider"), "model": msg.get("model"), "api": msg.get("api"),
            "streaming": True,
        })

    def _on_message_update(self, event: dict) -> None:
        call = self._call
        a = _obj(event.get("assistantMessageEvent"))
        t = a.get("type")
        if call is None:
            self._count_unknown(f"update-outside-call:{t}")
            return
        if t in ("text_start", "thinking_start"):
            kind = t.split("_")[0]
            if call.blocks[kind]:
                self._emit(call, kind, "\n\n")  # a second block reads as a new paragraph, as in the final
            call.blocks[kind] += 1
        elif t in ("text_delta", "thinking_delta"):
            self._emit(call, t.split("_")[0], a.get("delta") or "")
        elif t in ("text_end", "thinking_end"):
            kind = t.split("_")[0]
            stream = call.streams.get(kind)
            if stream is not None:
                rest = stream.flush()
                if rest:
                    self._chunk(call, rest, "content" if kind == "text" else "thinking")
        elif t == "toolcall_start":
            # The model is writing a call. Nothing runs yet: no tool event.
            self._chunk(call, f"\n🔧 {self.redact.text(a.get('toolName') or 'tool')}(", "tool_call")
        elif t == "toolcall_end":
            tc = _obj(a.get("toolCall"))
            if tc.get("id"):
                self._requested_by[str(tc["id"])] = call.id
            args = json.dumps(self.redact.obj(tc.get("arguments") or {}), ensure_ascii=False)
            self._chunk(call, _clip(args, CONSTRUCTION_ARGS_LIMIT)[0] + ")", "tool_call")
        elif t in ("toolcall_delta", "start", "done", "error"):
            self._ignored[f"update:{t}"] += 1  # partial arguments / the final message says it all
        else:
            self._count_unknown(f"update:{t}")

    def _emit(self, call: _Call, kind: str, piece: str) -> None:
        stream = call.streams.setdefault(kind, self.redact.stream())
        out = stream.feed(piece)
        if out:
            self._chunk(call, out, "content" if kind == "text" else "thinking")

    def _on_message_end(self, event: dict) -> None:
        msg = _obj(event.get("message"))
        if msg.get("role") != "assistant":
            return
        call = self._call
        if call is None:  # an end without a start: still record the call
            self._on_message_start({"message": msg})
            call = self._call
        assert call is not None
        for kind, stream in call.streams.items():
            rest = stream.flush()
            if rest:
                self._chunk(call, rest, "content" if kind == "text" else "thinking")
        texts: list[str] = []
        thinking: list[str] = []
        requested: list[dict] = []
        redacted_thinking = 0
        other: Counter[str] = Counter()
        for part in msg.get("content") or []:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text":
                texts.append(part.get("text") or "")
            elif pt == "thinking":
                if part.get("redacted") or not part.get("thinking"):
                    redacted_thinking += 1
                else:
                    thinking.append(part["thinking"])
            elif pt == "toolCall":
                requested.append({"name": part.get("name"), "id": part.get("id")})
                if part.get("id"):
                    self._requested_by[str(part["id"])] = call.id
            else:
                other[str(pt)] += 1
        original = "\n\n".join(texts)
        said = self.redact.answer_for_refusal(original)
        text = self.redact.text(original)
        reasoning = self.redact.text("\n\n".join(thinking)) if thinking else None
        usage = _usage(msg.get("usage"))
        self._add_usage(usage)
        stop = msg.get("stopReason")
        data = {
            **self._common(), "llm_call_id": call.id, "call_kind": "model", "iteration": call.ordinal,
            "provider": msg.get("provider"), "model": msg.get("responseModel") or msg.get("model"),
            **usage, "latency_ms": int((self._clock() - call.started) * 1000),
            "finish_reason": stop, "response_content": text, "reasoning": reasoning,
            "thinking_exposed": bool(thinking), "thinking_redacted_blocks": redacted_thinking,
            "has_tool_calls": bool(requested), "tool_calls_requested": requested,
            "unsupported_content": dict(other) or None,
            # The page replaces this call's live words with these fields (agentStory.reconcileCall).
            "authoritative_final": True,
        }
        if stop in FAILED_STOPS:
            error = self.redact.text(msg.get("errorMessage") or "") or f"the model call stopped: {stop}"
            data.update(error_type="aborted" if stop == "aborted" else "provider_error",
                        error=_clip(error, ERROR_LIMIT)[0])
            self._record(EventType.LLM_CALL_FAILED, self.stable_id("llm-end", call.ordinal),
                         status="failed", data=data)
        else:
            self._record(EventType.LLM_CALL_COMPLETED, self.stable_id("llm-end", call.ordinal),
                         status="completed", data=data)
        self._chunk(call, "", "content", done=True)
        # A rule-matching answer stays original for the caller's whole-answer refusal
        # (temper_ai/pi_agent/turn.py, SW-52). Known-only exact secrets stay redacted.
        self._last_answer = {"stop": stop, "text": said, "error": data.get("error"), "call_id": call.id}
        self._call = None

    def _add_usage(self, usage: dict) -> None:
        for k in ("prompt_tokens", "completion_tokens", "cached_prompt_tokens", "cache_write_tokens",
                  "total_tokens"):
            self._totals[k] += usage[k]
        self._cost += usage["cost_usd"]

    # ---- tools ---------------------------------------------------------------

    def _tool_scope(self, raw: str) -> tuple[str | None, str]:
        """The model call that asked for this tool, and the scope its ids are made in (G2)."""
        llm_call_id = self._requested_by.get(raw)
        return llm_call_id, llm_call_id or f"ordinal-{self._ordinal}"

    def _on_tool_start(self, event: dict) -> None:
        raw = str(event.get("toolCallId") or "")
        name = str(event.get("toolName") or "tool")
        if raw in self._tools:
            return  # the same running tool announced twice
        llm_call_id, scope = self._tool_scope(raw)
        cls = classify_tool(name)
        tool = _Tool(raw_id=raw, call_id=f"pi:{self.session_id}:{scope[-12:]}:{raw}", name=name,
                     llm_call_id=llm_call_id, started=self._clock(), scope=scope)
        tool.common = {**self._common(), "tool_name": cls["tool"], "raw_tool_name": name,
                       "transport": cls["transport"], "server": cls["server"], "call_id": tool.call_id,
                       "pi_tool_call_id": raw, "llm_call_id": tool.llm_call_id}
        self._tools[raw] = tool
        self._tool_count += 1
        self._record(EventType.TOOL_CALL_STARTED, self.stable_id("tool", scope, raw), status="running",
                     data={**tool.common, "input_params": self.redact.obj(event.get("args") or {})})

    def _on_tool_update(self, event: dict) -> None:
        tool = self._tools.get(str(event.get("toolCallId") or ""))
        if tool is None:
            self._count_unknown("tool_update_without_start")
            return
        if self.stable_id("tool-end", tool.scope, tool.raw_id) in self._prior:
            self._counts["chunk:replay_suppressed"] += 1
            return  # finished in an earlier reading (G3)
        text, _parts = self._render_content(_obj(event.get("partialResult")).get("content"))
        # Redact the whole snapshot before cutting it, and hold back an ending that could be
        # the start of a secret the next snapshot completes.
        tail = self.redact.stream().feed(text)[-PROGRESS_LIMIT:]
        tool.progress_seq += 1
        # A snapshot of everything so far: it replaces the last one, it is not added to it.
        self._rec.broadcast_stream_chunk(self.agent_id, tail, "tool_progress", False,
                                         call_id=tool.call_id, seq=tool.progress_seq)
        self._counts["chunk:tool_progress"] += 1

    def _on_tool_end(self, event: dict) -> None:
        raw = str(event.get("toolCallId") or "")
        tool = self._tools.get(raw)
        if tool is None:
            self._on_tool_start(event)
            tool = self._tools[raw]
        del self._tools[raw]  # ended: the same Pi id in a later call is a new tool (G2)
        result = _obj(event.get("result"))
        text, parts = self._render_content(result.get("content"))
        text = self.redact.text(text)
        clipped, was_clipped = _clip(text, OUTPUT_LIMIT)
        details = _obj(result.get("details"))
        artifacts = []
        if isinstance(details.get("fullOutputPath"), str):
            # A path inside Pi's sandbox; turning it into a Temper artifact is A4's job.
            artifacts.append({"kind": "full_output", "sandbox_path": self.redact.text(details["fullOutputPath"]),
                              "mapped": False})
        data = {**tool.common, "duration_ms": int((self._clock() - tool.started) * 1000),
                "output_chars": len(text), "output_clipped": was_clipped, "content_parts": parts,
                "artifacts": artifacts or None,
                "truncation": self.redact.obj(details.get("truncation")) if details.get("truncation") else None}
        end_id = self.stable_id("tool-end", tool.scope, raw)
        if event.get("isError"):
            data["error"] = clipped
            self._record(EventType.TOOL_CALL_FAILED, end_id, status="failed", data=data)
        else:
            data["output"] = clipped
            self._record(EventType.TOOL_CALL_COMPLETED, end_id, status="completed", data=data)

    def _render_content(self, content: Any) -> tuple[str, list[dict]]:
        """A tool result as text Temper can show, plus what each part was.

        Images and other binary parts are described (type, size, digest), never stored inline.
        """
        if isinstance(content, str):
            return content, [{"type": "text", "chars": len(content)}]
        texts, parts = [], []
        for part in content or []:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text":
                t = part.get("text") or ""
                texts.append(t)
                parts.append({"type": "text", "chars": len(t)})
            elif pt == "image":
                given = part.get("data")
                data = given if isinstance(given, str) else ""
                try:
                    raw = base64.b64decode(data, validate=True)
                except ValueError:  # not base64 after all: describe the text as given
                    raw = data.encode()
                size, digest = len(raw), hashlib.sha256(raw).hexdigest()
                desc = {"type": "image", "mime_type": part.get("mimeType"), "bytes": size, "sha256": digest}
                parts.append(desc)
                texts.append(f"[image {desc['mime_type']}, {size} bytes, sha256 {digest[:12]}…]")
            else:
                kind = str(pt)[:40]  # names a part type Temper does not show; never its content
                parts.append({"type": kind, "unsupported": True})
                texts.append(f"[{kind} result not shown]")
        return "\n".join(texts), parts

    # ---- retries, compaction, lifecycle ---------------------------------------

    # A retry is known by the model call it follows and its attempt number: Pi numbers the
    # attempts of every retried call from 1, so the attempt alone repeats (G1).

    def _on_retry_start(self, event: dict) -> None:
        attempt = event.get("attempt")
        event_id = self.stable_id("retry-start", self._ordinal, attempt)
        self._record(EventType.LLM_RETRY, event_id, status="running", data={
            **self._common(), "phase": "start", "attempt": attempt, "max_attempts": event.get("maxAttempts"),
            "delay_ms": event.get("delayMs"),
            "error": _clip(self.redact.text(event.get("errorMessage") or ""), ERROR_LIMIT)[0]})

    def _on_retry_end(self, event: dict) -> None:
        attempt = event.get("attempt")
        ok = bool(event.get("success"))
        self._record(EventType.LLM_RETRY, self.stable_id("retry-end", self._ordinal, attempt),
                     status="completed" if ok else "failed", data={
                         **self._common(), "phase": "end", "attempt": attempt, "success": ok,
                         "final_error": _clip(self.redact.text(event.get("finalError") or ""), ERROR_LIMIT)[0]
                         or None})

    def _on_compaction_start(self, event: dict) -> None:
        self._ordinal += 1
        call = _Call(id=self.stable_id("llm", self._ordinal), ordinal=self._ordinal, kind="compaction",
                     started=self._clock())
        self._compaction = call
        self._record(EventType.LLM_CALL_STARTED, call.id, status="running", data={
            **self._common(), "llm_call_id": call.id, "call_kind": "compaction", "iteration": call.ordinal,
            "reason": event.get("reason"), "streaming": False})

    def _on_compaction_end(self, event: dict) -> None:
        call = self._compaction
        if call is None:
            self._on_compaction_start(event)
            call = self._compaction
        assert call is not None
        result = _obj(event.get("result"))
        usage = _usage(result.get("usage"))
        self._add_usage(usage)
        data = {**self._common(), "llm_call_id": call.id, "call_kind": "compaction",
                "iteration": call.ordinal, **usage, "latency_ms": int((self._clock() - call.started) * 1000),
                "reason": event.get("reason"), "tokens_before": result.get("tokensBefore"),
                "estimated_tokens_after": result.get("estimatedTokensAfter"),
                "summary_chars": len(result.get("summary") or ""), "will_retry": bool(event.get("willRetry")),
                "authoritative_final": True}
        error = event.get("errorMessage")
        if event.get("aborted") or error or not result:
            data["error"] = _clip(self.redact.text(error or "compaction did not finish"), ERROR_LIMIT)[0]
            self._record(EventType.LLM_CALL_FAILED, self.stable_id("llm-end", call.ordinal),
                         status="failed", data=data)
        else:
            self._record(EventType.LLM_CALL_COMPLETED, self.stable_id("llm-end", call.ordinal),
                         status="completed", data=data)
        self._compaction = None

    def _on_agent_end(self, event: dict) -> None:
        self._counts["agent_end:will_retry" if event.get("willRetry") else "agent_end:final"] += 1

    def _on_settled(self, _event: dict) -> None:
        self.settled = True

    def _on_response(self, event: dict) -> None:
        if event.get("success") is False:
            error = _clip(self.redact.text(str(event.get("error") or "")), ERROR_LIMIT)[0]
            self._rpc_failures.append(f"Pi refused {event.get('command')!r}: {error}")

    def _on_extension_error(self, event: dict) -> None:
        self._counts["extension_errors"] += 1

    def _on_noop(self, _event: dict) -> None:
        return None

    _handlers: dict[str, Callable[[PiEventMapper, dict], None]] = {
        "message_start": _on_message_start,
        "message_update": _on_message_update,
        "message_end": _on_message_end,
        "tool_execution_start": _on_tool_start,
        "tool_execution_update": _on_tool_update,
        "tool_execution_end": _on_tool_end,
        "auto_retry_start": _on_retry_start,
        "auto_retry_end": _on_retry_end,
        "compaction_start": _on_compaction_start,
        "auto_compaction_start": _on_compaction_start,
        "compaction_end": _on_compaction_end,
        "auto_compaction_end": _on_compaction_end,
        "agent_end": _on_agent_end,
        "agent_settled": _on_settled,
        "response": _on_response,
        "extension_error": _on_extension_error,
        "agent_start": _on_noop,
        "turn_start": _on_noop,
        "turn_end": _on_noop,
    }

    # ---- outcome -------------------------------------------------------------

    def finish(self, *, result_schema: dict | None = None) -> PiOutcome:
        """Decide the agent's outcome. Errors stay visible; nothing here is a success by default."""
        from temper_ai.agent.llm_agent import (
            _extract_structured_output,
            _reply_tried_json,
        )

        errors: list[str] = []
        warnings: list[str] = []
        if not self.settled:
            errors.append("Pi stopped before it settled: the turn did not finish")
        errors.extend(self._rpc_failures)
        answer = self._last_answer
        output = ""
        if answer is None:
            errors.append("Pi gave no answer")
        elif answer["stop"] in FAILED_STOPS:
            what = "was stopped" if answer["stop"] == "aborted" else "failed"
            errors.append(f"the last model call {what}: {answer['error']}")
        else:
            output = answer["text"]
            if answer["stop"] == "length":
                warnings.append("the answer was cut off at the model's output limit")
        if self._call is not None:
            errors.append("a model call never ended")
        if self._tools:
            errors.append(f"{len(self._tools)} tool call(s) never ended")
        if self._compaction is not None:
            errors.append("a compaction never ended")
        structured = _extract_structured_output(output) if output else None
        if result_schema is not None and not errors:
            if structured is None:
                errors.append("the reply ends in JSON that does not parse" if _reply_tried_json(output)
                              else "the reply has no JSON result")
            else:
                problems = validate_result(structured, result_schema)
                if problems:
                    errors.append("the result does not match its schema: " + ", ".join(problems))
        if self._unknown:
            warnings.append(f"{sum(self._unknown.values())} Pi events of unknown types were not shown")
        if self._counts.get("extension_errors"):
            warnings.append(f"{self._counts['extension_errors']} Pi extension errors")
        tokens = {**{k: self._totals.get(k, 0) for k in ("prompt_tokens", "completion_tokens",
                                                         "cached_prompt_tokens", "cache_write_tokens",
                                                         "total_tokens")},
                  "cost_usd": round(self._cost, 10)}
        return PiOutcome(
            status="failed" if errors else "completed",
            output=output,
            structured_output=structured,
            errors=errors,
            warnings=warnings,
            tokens=tokens,
            llm_calls=self._ordinal,
            tool_calls=self._tool_count,
            counts={"events": dict(self._counts), "unknown": dict(self._unknown),
                    "ignored": dict(self._ignored)},
            last_stop=answer["stop"] if answer else None,
            last_error=answer["error"] if answer and answer["stop"] in FAILED_STOPS else None,
        )


def record_outcome(recorder: Recorder, mapper: PiEventMapper, outcome: PiOutcome,
                   duration_seconds: float | None = None) -> str:
    """Record ``agent.completed`` or ``agent.failed`` for the mapped agent (child of its start)."""
    failed = outcome.status != "completed"
    event_id = mapper.stable_id("agent-end")
    recorder.record(EventType.AGENT_FAILED if failed else EventType.AGENT_COMPLETED,
                    data=outcome.agent_event_data(mapper.agent_name, duration_seconds,
                                                  scrub=mapper.redact.text),
                    parent_id=mapper.agent_id, execution_id=mapper.execution_id,
                    status="failed" if failed else "completed", event_id=event_id)
    return event_id
