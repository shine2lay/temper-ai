"""The event inbox: save first, then handle, and pick up what was left.

Everything temper receives from outside (a Linear or Notion webhook, a Slack
envelope, a Telegram update) is written to ``inbox_events`` before temper
tells the sender it got it, and is then handled from that row:

- ``receive`` keeps the event. One sent again has the same delivery id, so
  it is noticed and not handled twice.
- ``process`` takes the row (one guarded UPDATE, so only one thread can),
  calls the source's handler and closes the row: done or skipped, or failed
  with a wait before the next try (1 min, 5 min, 30 min, 2 h), after which
  it gives up.
- The sweeper, a thread in the server, retries failed rows once their wait
  is over, picks up rows a restart cut off, checks events that came before
  their signing key was set, and deletes old rows.

A run an event starts is written on its row the moment it starts
(``note_run``, called from ``start_run``), so a retry never starts it twice.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from temper_ai.integrations.inbox import store
from temper_ai.integrations.inbox.store import Event

logger = logging.getLogger(__name__)

# This server process. A row left "handling" by another value was cut off.
WORKER = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
MAX_BODY = 256 * 1024     # the most kept for one event waiting for its key
MAX_HELD = 500            # the most such events kept at once
SWEEP_S = 15.0
PRUNE_S = 3600.0
_SKIPPED = ("ignored", "skipped", "no trigger", "nothing to do")


class Retry(Exception):
    """Handling didn't get done; try again after a wait (the message says why)."""


class Bad(Exception):
    """An event waiting for its key failed the check once the key was there."""


@dataclass
class Outcome:
    text: str
    status: str = "done"                 # done | skipped
    extra: dict[str, Any] = field(default_factory=dict)


def outcome(text: str) -> Outcome:
    """An outcome in words, as done, or skipped when it did nothing."""
    return Outcome(text, "skipped" if text.lower().startswith(_SKIPPED) else "done")


Handler = Callable[[Event], "Outcome | str | None"]
# (payload, kind, subject) once checked; None while the key still isn't set; raises Bad.
Verifier = Callable[[Event], "tuple[dict[str, Any], str, str] | None"]


@dataclass
class Source:
    name: str
    handle: Handler
    redo_safe: bool = False            # the handler itself skips what an earlier try already did
    expires_after_s: float | None = None


@dataclass
class Current:
    event_id: int
    started: list[dict[str, str]]


_sources: dict[str, Source] = {}
_checkers: dict[str, Verifier] = {}
_lock = threading.Lock()
_current: ContextVar[Current | None] = ContextVar("inbox_current", default=None)


def register(name: str, handle: Handler, *, redo_safe: bool = False, expires_after_s: float | None = None) -> None:
    """Say how events from ``name`` are handled; until then they wait."""
    with _lock:
        _sources[name] = Source(name, handle, redo_safe, expires_after_s)


def unregister(name: str, handle: Handler | None = None) -> None:
    with _lock:
        src = _sources.get(name)
        if src is not None and (handle is None or src.handle == handle):
            del _sources[name]


def register_checker(name: str, verify: Verifier) -> None:
    with _lock:
        _checkers[name] = verify


def sources() -> list[str]:
    with _lock:
        return sorted(_sources)


# -- in ----------------------------------------------------------------------------------------


def receive(source: str, delivery: str, *, kind: str = "", subject: str = "",
            payload: dict[str, Any] | None = None, skipped: str = "") -> tuple[Event, bool]:
    """Keep an event before saying "got it"; (row, True) if new, (row, False) if sent again.

    ``skipped`` keeps it as already skipped, for that reason (e.g. too old to act on)."""
    if skipped:
        return store.save(source, delivery, kind=kind, subject=subject, payload=payload, status="skipped",
                          result={"outcome": skipped})
    return store.save(source, delivery, kind=kind, subject=subject, payload=payload)


def hold(source: str, delivery: str, raw: bytes, signature: str) -> tuple[int, str]:
    """Keep an event that came before its signing key was set; (HTTP status, what happened).

    It is checked, and then handled or dropped, once the key is there."""
    if len(raw) > MAX_BODY:
        return 413, f"too big to keep unchecked ({len(raw)} bytes; the most is {MAX_BODY})"
    if store.count_held() >= MAX_HELD:
        return 503, f"{MAX_HELD} events are already waiting for the signing key"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return 400, "the body is not UTF-8"
    _, new = store.save(source, delivery, kind="(not checked yet)", status=store.HELD, raw=text,
                        signature=signature)
    return 202, "kept until the signing key is set" if new else "already kept"


# -- handling -----------------------------------------------------------------------------------


def process(event_id: int, *, now: datetime | None = None) -> str:
    """Handle one saved event. Returns its status afterwards ("" if it wasn't there to take)."""
    row = store.get(event_id)
    if row is None:
        return ""
    with _lock:
        src = _sources.get(row.source)
    if src is None:
        return row.status     # its source isn't running in this server; it waits
    event = store.claim(event_id, WORKER, now=now)
    if event is None:
        return ""
    if event.tries > store.MAX_TRIES:
        store.give_up(event_id, f"stopped part-way {event.tries - 1} times", now=now)
        return "gave_up"
    at = now or datetime.now(UTC)
    if src.expires_after_s is not None and (at - event.received_at).total_seconds() > src.expires_after_s:
        minutes = int(src.expires_after_s // 60)
        store.finish(event_id, "expired", {"outcome": f"expired: not handled within {minutes} min"}, now=now)
        return "expired"
    if event.started and not src.redo_safe:
        store.finish(event_id, "done", {"outcome": f"already started {_runs(event.started)}; not started again"},
                     now=now)
        return "done"
    token = _current.set(Current(event_id, event.started))
    try:
        got = src.handle(event)
    except Retry as exc:
        status = store.fail(event_id, str(exc) or "try again", now=now, result={"outcome": str(exc)})
        logger.warning("Inbox: %s event %s did not get done (%s): %s", event.source, event_id, status, exc)
        return status
    except Exception as exc:  # noqa: BLE001 - kept and retried rather than lost
        status = store.fail(event_id, f"{type(exc).__name__}: {exc}", now=now)
        logger.exception("Inbox: handling %s event %s failed (%s)", event.source, event_id, status)
        return status
    finally:
        _current.reset(token)
    out = got if isinstance(got, Outcome) else outcome(str(got or "handled"))
    status = out.status if out.status in ("done", "skipped") else "done"
    store.finish(event_id, status, {"outcome": out.text, **out.extra}, now=now)
    return status


def _runs(started: list[dict[str, str]]) -> str:
    return ", ".join(f"{s.get('workflow')} {str(s.get('execution_id'))[:8]}" for s in started)


def note_run(workflow: str, execution_id: str) -> None:
    """A run started; if an event being handled started it, write that on the event."""
    cur = _current.get()
    if cur is None:
        return
    cur.started.append({"workflow": workflow, "execution_id": execution_id})
    try:
        store.note_run(cur.event_id, workflow, execution_id)
    except Exception:  # noqa: BLE001 - the run started; losing the note only risks a repeat on retry
        logger.exception("Inbox: could not note run %s on event %s", execution_id, cur.event_id)


def already_started() -> list[dict[str, str]]:
    """Runs the event being handled started on an earlier try (and so far on this one)."""
    cur = _current.get()
    return list(cur.started) if cur else []


def current_event_id() -> int | None:
    cur = _current.get()
    return cur.event_id if cur else None


_pool: ThreadPoolExecutor | None = None


def submit(event_id: int) -> None:
    """Handle an event on the inbox's own threads."""
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="inbox")
        pool = _pool
    pool.submit(_safe_process, event_id)


def _safe_process(event_id: int) -> None:
    try:
        process(event_id)
    except Exception:  # noqa: BLE001 - e.g. the database is down; the sweeper tries again
        logger.exception("Inbox: event %s could not be handled", event_id)


def replay(event_id: int, *, now: datetime | None = None) -> tuple[bool, str]:
    """Handle a finished event again (the "temper events replay" command).

    Refused, with the reason, when that would do something twice (it already
    started a run) or can't work (a Slack reply link has expired)."""
    ev = store.get(event_id)
    if ev is not None:
        with _lock:
            src = _sources.get(ev.source)
        at = now or datetime.now(UTC)
        if (src is not None and src.expires_after_s is not None and not ev.started
                and (at - ev.received_at).total_seconds() > src.expires_after_s):
            return False, (f"it came over {int(src.expires_after_s // 60)} min ago, so the link to answer "
                           f"it has expired")
    ok, why = store.replay(event_id, now=now)
    if ok:
        submit(event_id)
    return ok, why


# -- the sweeper --------------------------------------------------------------------------------


class Sweeper:
    """Retries, pick-ups after a restart, held events and clean-up, every few seconds."""

    def __init__(self, *, interval_s: float = SWEEP_S, run: Callable[[int], None] | None = None) -> None:
        self.interval_s = interval_s
        self._run = run or submit
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_prune = 0.0
        self.last_sweep_at: str | None = None
        self.last_error: str | None = None
        self.counts: dict[str, int] = {"checked": 0, "dropped": 0, "retried": 0, "pruned": 0}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="inbox-sweeper", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while True:
            try:
                self.sweep_once()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep sweeping (e.g. the database blinked)
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Inbox: sweep failed")
            if self._stop.wait(self.interval_s):
                return

    def sweep_once(self, now: datetime | None = None, *, prune: bool | None = None) -> dict[str, int]:
        got = {"checked": 0, "dropped": 0, "retried": 0, "pruned": 0}
        for ev in store.held():
            with _lock:
                verify = _checkers.get(ev.source)
            if verify is None:
                continue
            try:
                checked = verify(ev)
            except Bad as exc:
                store.drop(ev.id)
                got["dropped"] += 1
                logger.warning("Inbox: dropped %s event %s that failed its check: %s", ev.source, ev.id, exc)
                continue
            if checked is None:
                continue    # its key still isn't set
            payload, kind, subject = checked
            if store.verified(ev.id, payload=payload, kind=kind, subject=subject):
                got["checked"] += 1
                self._run(ev.id)
        for event_id in store.due(WORKER, sources(), now=now):
            got["retried"] += 1
            self._run(event_id)
        if prune if prune is not None else time.monotonic() - self._last_prune >= PRUNE_S:
            self._last_prune = time.monotonic()
            got["pruned"] = store.prune(now)
        for key, n in got.items():
            self.counts[key] += n
        self.last_sweep_at = datetime.now(UTC).isoformat()
        return got


_sweeper: Sweeper | None = None


def start_inbox() -> Sweeper:
    """Start the sweeper (the server calls this at startup)."""
    global _sweeper
    if _sweeper is None:
        _sweeper = Sweeper()
    _sweeper.start()
    logger.info("Inbox: sweeper started (worker %s)", WORKER)
    return _sweeper


def stop_inbox() -> None:
    global _pool, _sweeper
    if _sweeper is not None:
        _sweeper.stop()
        _sweeper = None
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def sweeper() -> Sweeper | None:
    return _sweeper
