"""The one door a Pi run's events go through (ADR-M4-12, SW-52; decision-76-event-guard).

Everything a Pi run records or broadcasts -- the mapper's events, the turn's end, the team's
own records, the owner waits it opens, the live chunks -- leaves through
:class:`GuardedRecorder`: event data with :func:`token_scan.withhold_obj` applied (every
string, dict keys included), every chunk with :func:`token_scan.withhold`. The Pi lane's
entry points (``run_turn``, ``Team``, ``run_team_node``, ``PiHost``) wrap the run's recorder
once, so no Pi code path holds an unguarded one. Events count as leaving the run: they reach
the events table (and the off-site backup), the run's events.jsonl, the run page and the
live panel.

A live stream needs more than withholding chunk by chunk, because a token can arrive in
pieces: :class:`ShapeStream` holds back the end of a text from where a shape could still
start, so no character of a token's run goes out however the deltas split.
:data:`TOKEN_GUARD` hands both rules to temper_ai/llm/pi_stream.py, which never imports the
Pi lane. The rules themselves stay in token_scan.py.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Iterable
from typing import Any

from temper_ai.pi_agent.token_scan import (
    RUN_CHARS,
    SHAPE_PREFIX,
    SHAPES,
    WITHHELD,
    protection_spans,
    remembered_tokens,
    withhold,
    withhold_obj,
)

#: The longest run :class:`ShapeStream` holds back before it decides (about 4 KB).
STREAM_HOLD_CAP = 4096


def _run_start(text: str) -> int:
    """Start of the possible header/body tail: ASCII run characters and Unicode decimal
    digits. SHAPES uses Unicode-aware ``\\d`` in headers, though its body is ASCII."""
    i = len(text)
    while i and (text[i - 1] in RUN_CHARS or text[i - 1].isdecimal()):
        i -= 1
    return i


def _hold_from(text: str, start: int) -> int:
    """The first place at or after ``start`` where a shape could still begin: a whole
    :data:`token_scan.SHAPE_PREFIX`, or an ending that is the start of one; ``len(text)``
    if there is none."""
    found = text.find(SHAPE_PREFIX, start)
    end = len(text) if found < 0 else found
    for q in range(max(start, len(text) - len(SHAPE_PREFIX) + 1), end):
        if SHAPE_PREFIX.startswith(text[q:]):
            return q
    return end


def _after_run(piece: str) -> str | None:
    """``piece`` from its first character outside a run on; ``None`` if it has none."""
    for i, ch in enumerate(piece):
        if ch not in RUN_CHARS:
            return piece[i:]
    return None


def _exact_spans(text: str, secrets: Iterable[str]) -> list[tuple[int, int]]:
    spans = []
    for secret in secrets:
        if not secret:
            continue
        at = text.find(secret)
        while at >= 0:
            spans.append((at, at + len(secret)))
            at = text.find(secret, at + 1)
    return spans


def _compose_text(text: str, secrets: Iterable[str], marker: str) -> str:
    """Merge ORIGINAL rule/exact-secret intervals; partial coverage cannot break a shape."""
    exact = _exact_spans(text, secrets)
    shaped, remembered = protection_spans(text)
    spans = [(start, end, marker) for start, end in exact]
    for start, end in shaped + remembered:
        if not any(left <= start and end <= right for left, right in exact):
            spans.append((start, end, WITHHELD))
    if not spans:
        return text
    merged: list[tuple[int, int, str]] = []
    for start, end, replacement in sorted(spans):
        if merged and start < merged[-1][1]:
            left, right, previous = merged[-1]
            replacement = WITHHELD if WITHHELD in (previous, replacement) else marker
            merged[-1] = (left, max(right, end), replacement)
        else:
            merged.append((start, end, replacement))
    parts: list[str] = []
    cursor = 0
    for start, end, replacement in merged:
        parts.extend((text[cursor:start], replacement))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _known_hold_from(text: str, secrets: Iterable[str]) -> int:
    secrets = tuple(secrets)
    longest = max((len(secret) for secret in secrets), default=0)
    for size in range(min(len(text), longest - 1), 0, -1):
        if any(secret.startswith(text[-size:]) for secret in secrets):
            return len(text) - size
    return len(text)


class ShapeStream:
    """Hold ORIGINAL shape/exact-secret candidates before composing any substitutions.

    Unicode decimal headers stay with their ASCII bodies. Optional exact-secret composition
    preserves the mapper's marker without breaking a shape. Full exact matches crossing a
    shape hold stay together too. At ``cap`` a matched run is withheld and its remainder
    swallowed. An oversized exact prefix is masked conservatively and followed by position
    in the already-configured secret, not an unbounded retained copy of incoming text.
    """

    def __init__(self, cap: int = STREAM_HOLD_CAP, *,
                 secrets: Callable[[], Iterable[str]] | None = None, marker: str = WITHHELD):
        self._held = ""
        self._swallow = False
        self._known_swallow: list[tuple[str, int]] = []
        self._cap = cap
        self._secrets = secrets
        self._marker = marker

    def _known(self) -> tuple[str, ...]:
        configured = tuple(self._secrets()) if self._secrets is not None else ()
        return tuple(dict.fromkeys((*configured, *remembered_tokens())))

    def _redact(self, text: str) -> str:
        if self._secrets is None:
            return withhold(text)
        return _compose_text(text, self._secrets(), self._marker)

    def _after_known(self, piece: str) -> str | None:
        for i, ch in enumerate(piece):
            if ch not in RUN_CHARS:
                self._swallow = False
            following = [(secret, at + 1) for secret, at in self._known_swallow
                         if secret[at] == ch]
            if not following:
                self._known_swallow = []
                return piece[i:]
            self._known_swallow = [(secret, at) for secret, at in following if at < len(secret)]
            if not self._known_swallow:
                return piece[i + 1:]
        return None

    def feed(self, piece: str) -> str:
        if self._known_swallow:
            rest = self._after_known(piece)
            if rest is None:
                return ""
            piece = rest
        if self._swallow:
            rest = _after_run(piece)
            if rest is None:  # still the run of a token already withheld
                return ""
            self._swallow, piece = False, rest
        text, known = self._held + piece, self._known()
        cut = min(_hold_from(text, _run_start(text)), _known_hold_from(text, known))
        # Keep a complete known span with any shaped tail it crosses. Otherwise a shape
        # substitution could destroy a longer exact match just as the reverse order did.
        for start, end in reversed(sorted(_exact_spans(text, known))):
            if start < cut < end:
                cut = start
        out, self._held = self._redact(text[:cut]), text[cut:]
        while len(self._held) > self._cap:
            shaped = any(pattern.search(self._held) for pattern in SHAPES.values())
            candidates = [(secret, len(self._held)) for secret in known
                          if len(secret) > len(self._held) and secret.startswith(self._held)]
            if shaped or candidates:
                configured = tuple(self._secrets()) if self._secrets is not None else ()
                exact_only = not shaped and all(secret in configured for secret, _ in candidates)
                out += self._marker if exact_only else WITHHELD
                self._known_swallow, self._held, self._swallow = candidates, "", shaped
            else:
                cut = min(_hold_from(self._held, 1), _known_hold_from(self._held, known))
                out += self._redact(self._held[:cut])
                self._held = self._held[cut:]
        return out

    def flush(self) -> str:
        out = self._redact(self._held)
        self._held, self._swallow, self._known_swallow = "", False, []
        return out


class TokenGuard:
    """token_scan's rules; optional composition hooks keep configured-secret compatibility."""

    @staticmethod
    def text(value: str) -> str:
        return withhold(value)

    @staticmethod
    def obj(value: Any) -> Any:
        return withhold_obj(value)

    @staticmethod
    def stream() -> ShapeStream:
        return ShapeStream()

    @staticmethod
    def compose_text(value: str, secrets: Iterable[str], marker: str) -> str:
        return _compose_text(value, secrets, marker)

    @staticmethod
    def compose_stream(secrets: Callable[[], Iterable[str]], marker: str) -> ShapeStream:
        return ShapeStream(secrets=secrets, marker=marker)


TOKEN_GUARD = TokenGuard()


def _withheld(args: tuple, kwargs: dict) -> tuple[tuple, dict]:
    return (tuple(withhold_obj(a) for a in args),
            {k: withhold_obj(v) for k, v in kwargs.items()})


class GuardedRecorder:
    """A run's event recorder whose writes leave with every login token withheld.

    Each method the Pi lane calls is forwarded by name: the writes (``record``,
    ``broadcast_stream_chunk``, ``update_event``, ``decide``) with every argument after the
    first (event type, agent id or event id) withheld, keeping the caller's positional or
    keyword form; the reads (``event_status``, ``event_data``, ``gate_events``) as they are.
    A method the inner recorder lacks is missing here too, so ``getattr(rec, name, None)``
    and ``hasattr`` answer as they would for the inner one. Nothing else is forwarded.
    """

    def __init__(self, inner: Any):
        self.inner = inner

    def record(self, event_type: Any, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _withheld(args, kwargs)
        return self.inner.record(event_type, *args, **kwargs)

    def broadcast_stream_chunk(self, agent_id: Any, *args: Any, **kwargs: Any) -> Any:
        args, kwargs = _withheld(args, kwargs)
        return self.inner.broadcast_stream_chunk(agent_id, *args, **kwargs)

    @property
    def update_event(self) -> Callable[..., Any]:
        return self._guarded_write(self.inner.update_event)

    @property
    def decide(self) -> Callable[..., Any]:
        return self._guarded_write(self.inner.decide)

    @property
    def event_status(self) -> Callable[..., Any]:
        return self.inner.event_status

    @property
    def event_data(self) -> Callable[..., Any]:
        return self.inner.event_data

    @property
    def gate_events(self) -> Callable[..., Any]:
        return self.inner.gate_events

    @staticmethod
    def _guarded_write(write: Callable[..., Any]) -> Callable[..., Any]:
        def guarded_write(event_id: Any, *args: Any, **kwargs: Any) -> Any:
            args, kwargs = _withheld(args, kwargs)
            return write(event_id, *args, **kwargs)
        return guarded_write


def guarded(recorder: Any) -> Any:
    """``recorder`` behind the door: the same object when it already is, ``None`` as ``None``."""
    if recorder is None or isinstance(recorder, GuardedRecorder):
        return recorder
    return GuardedRecorder(recorder)


def guarded_context(context: Any) -> Any:
    """A copy of a step's ``context`` whose ``event_recorder`` is behind the door; the same
    context when it has no recorder or its recorder already is. The caller's context is never
    changed, so what the workflow records outside the Pi lane stays as it was."""
    recorder = getattr(context, "event_recorder", None)
    if recorder is None or isinstance(recorder, GuardedRecorder):
        return context
    if dataclasses.is_dataclass(context) and not isinstance(context, type):
        return dataclasses.replace(context, event_recorder=guarded(recorder))
    clone = copy.copy(context)
    clone.event_recorder = guarded(recorder)
    return clone
