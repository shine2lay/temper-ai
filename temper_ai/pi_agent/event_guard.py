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
from collections.abc import Callable
from typing import Any

from temper_ai.pi_agent.token_scan import (
    RUN_CHARS,
    SHAPE_PREFIX,
    SHAPES,
    withhold,
    withhold_obj,
)

#: The longest run :class:`ShapeStream` holds back before it decides (about 4 KB).
STREAM_HOLD_CAP = 4096


def _run_start(text: str) -> int:
    """Where the run of :data:`token_scan.RUN_CHARS` that ``text`` ends with starts."""
    i = len(text)
    while i and text[i - 1] in RUN_CHARS:
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


class ShapeStream:
    """A text that arrives in pieces, let out with every shape withheld.

    It holds back the end of the text from the first place where a shape could still start
    or still grow. That place lies in the run the text ends with, because a shape is all run
    characters and a match ends where its run ends; so what comes before it goes out through
    :func:`token_scan.withhold`, finished shapes as their rule's words. A hold longer than
    ``cap`` that holds a shape is withheld whole and the rest of its run swallowed; one
    without a shape goes out up to the next place a shape could start. :meth:`flush` lets
    the held text out, withheld.
    """

    def __init__(self, cap: int = STREAM_HOLD_CAP):
        self._held = ""
        self._swallow = False
        self._cap = cap

    def feed(self, piece: str) -> str:
        if self._swallow:
            rest = _after_run(piece)
            if rest is None:  # still the run of a token already withheld
                return ""
            self._swallow, piece = False, rest
        text = self._held + piece
        cut = _hold_from(text, _run_start(text))
        out, self._held = withhold(text[:cut]), text[cut:]
        while len(self._held) > self._cap:
            if any(pattern.search(self._held) for pattern in SHAPES.values()):
                out += withhold(self._held)
                self._held, self._swallow = "", True
            else:
                cut = _hold_from(self._held, 1)
                out += withhold(self._held[:cut])
                self._held = self._held[cut:]
        return out

    def flush(self) -> str:
        out = withhold(self._held)
        self._held, self._swallow = "", False
        return out


class TokenGuard:
    """token_scan's rules in the form temper_ai/llm/pi_stream.py's ``Guard`` asks for."""

    @staticmethod
    def text(value: str) -> str:
        return withhold(value)

    @staticmethod
    def obj(value: Any) -> Any:
        return withhold_obj(value)

    @staticmethod
    def stream() -> ShapeStream:
        return ShapeStream()


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
