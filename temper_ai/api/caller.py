"""Who is asking, and one guard for every action that changes something.

Two halves:

* The HTTP edge (``CallerMiddleware`` in api/auth.py) works out who sent a
  request -- a named key, a run's own key, the server itself, or nobody
  known -- and binds it here for the request.
* ``require_caller_may(action)`` runs *inside* each operation that changes
  state (start, fork, cancel, resume, clean up, answer a wait, config
  writes...). It is called by the operation, not declared on the route:
  the MCP tools and Slack/Telegram call the same route functions
  in-process, as plain Python, so a route ``Depends(...)`` would check HTTP
  callers and let every MCP call straight past.

Ways in that never come through HTTP name themselves with ``acting_as``,
after their own checks: Slack "slack:<user id>", Telegram
"telegram:<user id>", signed hooks "hook:<source>", triggers
"trigger:<name>", start-up pickup "pickup". Anything left unnamed is an
unknown caller.

``TEMPER_API_GUARD`` decides what an unknown caller gets:

* ``off`` (the default): nothing is checked or counted.
* ``record``: allowed, with one log line and a count per write.
* ``enforce``: refused (401 unknown; 403 for a run's own key used beyond
  starting and forking runs), with the same log line.

Whoever made it, every decision and run action records the caller's name,
address and request id (``who()``), so the record shows who did what.
"""

from __future__ import annotations

import inspect
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import HTTPException

from temper_ai.shared.clock import utcnow

logger = logging.getLogger(__name__)

GUARD_ENV_VAR = "TEMPER_API_GUARD"
MODES = ("off", "record", "enforce")

# What a run's own key (RunToken) may do. Never answers, cancels, resumes or
# cleans up: an agent in a run that holds one must not be able to approve
# its own deploy gate.
BOX_ACTIONS = frozenset({"start", "fork"})
BOX_PREFIX = "box:"

# Bounds on what a request may say about itself.
_REQUEST_ID_MAX = 100


@dataclass(frozen=True)
class Caller:
    """Who made one request or in-process call.

    ``name`` is None when nobody could say. ``source`` is the address the
    request came from ("in-process" for Slack, Telegram, hooks...). ``via``
    says how it arrived: "POST /api/runs", "mcp temper_cancel_run",
    "slack", ...
    """

    name: str | None
    source: str = "in-process"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    via: str = ""

    @property
    def is_box(self) -> bool:
        return bool(self.name and self.name.startswith(BOX_PREFIX))

    @property
    def label(self) -> str:
        return self.name or "unknown"


_current: ContextVar[Caller | None] = ContextVar("temper_api_caller", default=None)


def current_caller() -> Caller | None:
    """The caller bound for this request or call, or None when nobody bound one."""
    return _current.get()


@contextmanager
def bound(caller: Caller | None) -> Iterator[Caller | None]:
    """Bind ``caller`` for the block, and always put the old one back.

    Always reset, never just set: the inboxes and the MCP tools run on pool
    threads, and a caller left bound on one would be handed to whatever the
    thread does next.
    """
    token = _current.set(caller)
    try:
        yield caller
    finally:
        _current.reset(token)


@contextmanager
def acting_as(name: str, *, via: str = "", source: str = "in-process") -> Iterator[Caller]:
    """Name an in-process way in for the block (after its own checks passed)."""
    with bound(Caller(name=name, source=source, via=via or name.split(":", 1)[0])) as caller:
        yield caller  # type: ignore[misc]


def clean_request_id(value: str | None) -> str:
    """A request id a caller sent (X-Request-ID), trimmed to something safe to store and log."""
    if not value:
        return uuid.uuid4().hex[:16]
    kept = "".join(ch for ch in value.strip() if ch.isalnum() or ch in "-_.:")
    return kept[:_REQUEST_ID_MAX] or uuid.uuid4().hex[:16]


def guard_mode(environ: dict[str, str] | None = None) -> str:
    """off, record or enforce. Anything else counts as record, with a warning.

    Not off for a typo: someone who wrote ``enforced`` meant the guard on,
    and record still names every unknown writer without breaking anything.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(GUARD_ENV_VAR) or "off").strip().lower()
    if raw in MODES:
        return raw
    _warn_once(f"{GUARD_ENV_VAR}={raw!r} is not one of off, record, enforce; treating it as record")
    return "record"


_warned: set[str] = set()


def _warn_once(text: str) -> None:
    if text not in _warned:
        _warned.add(text)
        logger.warning(text)


class CallerRefused(HTTPException):
    """A state-changing action from a caller who may not make it."""


def _unbound_via() -> str:
    """For an unknown in-process caller: the function that called the operation."""
    for frame in inspect.stack()[3:8]:
        module = frame.frame.f_globals.get("__name__", "")
        if not module.startswith("temper_ai.api.caller"):
            return f"in-process {module}.{frame.function}"
    return "in-process"


def require_caller_may(action: str, *, run_id: str | None = None) -> Caller:
    """Check that whoever is asking may do ``action``, and return who it is.

    Called first thing inside every operation that changes state. In
    ``record`` and ``enforce`` every write is counted under its caller's
    name; an unknown caller, or a run's own key used for anything but
    starting and forking runs, gets one log line, and in ``enforce`` a
    401/403 instead of the action.
    """
    caller = _current.get()
    if caller is None:
        caller = Caller(name=None, via=_unbound_via())
    mode = guard_mode()
    if mode == "off":
        return caller

    allowed = caller.name is not None and (not caller.is_box or action in BOX_ACTIONS)
    if allowed:
        _note(caller, action, run_id, refused=False)
        return caller

    refusing = mode == "enforce"
    logger.warning(
        "api guard (%s): %s %s action %s via %s from %s run %s",
        mode,
        "refused" if refusing else "allowed",
        "unknown caller" if caller.name is None else f"caller {caller.name}",
        action,
        caller.via or "?",
        caller.source,
        run_id or "-",
    )
    _note(caller, action, run_id, refused=refusing)
    if refusing:
        if caller.name is None:
            raise CallerRefused(
                status_code=401,
                detail=(
                    "This action needs a key. Send 'Authorization: Bearer <key>' "
                    "with one of the server's named API keys (docs/api-access.md)."
                ),
                headers={"WWW-Authenticate": 'Bearer realm="temper"'},
            )
        raise CallerRefused(
            status_code=403,
            detail=f"A run's own key may only start and fork runs, not {action}.",
        )
    return caller


def who(caller: Caller | None) -> dict[str, str]:
    """The fields stored on a decision or a run action: who, from where, which request."""
    if caller is None:
        caller = Caller(name=None)
    return {
        "caller": caller.label,
        "caller_from": caller.source,
        "caller_request_id": caller.request_id,
    }


def record_action(execution_id: str | None, action: str, caller: Caller | None, **detail) -> None:
    """Add a ``caller.action`` event to the run: who started, cancelled, resumed... it.

    Best effort: the action already happened, and failing it now because the
    note could not be written would be worse than a missing note.
    """
    if not execution_id:
        return
    try:
        from temper_ai.observability.models import Event
        from temper_ai.observability.recorder import _db_write_with_retry

        event = Event(
            id=str(uuid.uuid4()),
            type="caller.action",
            execution_id=execution_id,
            status="completed",
            data={"action": action, **who(caller), **{k: v for k, v in detail.items() if v is not None}},
        )
        _db_write_with_retry(lambda s: s.add(event), max_retries=2)
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("could not record who did %s on run %s", action, execution_id, exc_info=True)


# --- what the guard has seen -------------------------------------------------

_seen_lock = threading.Lock()
_seen: dict[tuple[str, str], dict] = {}


def _note(caller: Caller, action: str, run_id: str | None, *, refused: bool) -> None:
    """Count one write in memory and in api_guard_seen (best effort).

    Run keys count together as "box" (the run is in last_run_id), so the
    table stays one row per kind of caller, not one per run.
    """
    key = ("box" if caller.is_box else caller.name or "", action)
    now = utcnow()
    with _seen_lock:
        row = _seen.setdefault(key, {"count": 0, "refused": 0, "first_seen": now.isoformat()})
        row["count"] += 1
        row["refused"] += int(refused)
        row.update(last_seen=now.isoformat(), last_via=caller.via, last_source=caller.source,
                   last_run_id=run_id or "")
    try:
        from temper_ai.api.guard_models import GuardSeen
        from temper_ai.database.session import get_session

        with get_session() as session:
            stored = session.get(GuardSeen, key)
            if stored is None:
                stored = GuardSeen(caller=key[0], action=action, first_seen=now)
            stored.count += 1
            stored.refused += int(refused)
            stored.last_seen = now
            stored.last_via = (caller.via or "")[:200]
            stored.last_source = caller.source[:100]
            stored.last_run_id = (run_id or "")[:100]
            session.add(stored)
    except Exception:  # noqa: BLE001 - counting must never fail a write
        logger.debug("api guard: could not store what it saw", exc_info=True)


def seen_since_start() -> list[dict]:
    """What this process has counted, for GET /api/guard."""
    with _seen_lock:
        return [{"caller": c or None, "action": a, **row} for (c, a), row in sorted(_seen.items())]


def _reset_for_tests() -> None:
    with _seen_lock:
        _seen.clear()
    _warned.clear()
