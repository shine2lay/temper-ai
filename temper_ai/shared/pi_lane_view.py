"""The Pi lane view (ADR-M4-21, finding F-ROLELIST): what the server needs of the Pi lane's
worker box config to list roles and check a team, published by pi-worker into the Redis the two
share.

Why it exists: the server is the run boxes' template, so it holds no Pi folder (SW-42,
docs/pi-team-api.md); the box config and the role folders are mounted into pi-worker only.

It is advisory, and it goes one way:

- pi-worker (the Pi lane's watcher, cli/watch_queue.py, through :class:`Publisher`) builds it
  from the on-disk box config and role folders while its preflight passes, and only writes it:
  a SET that expires after :data:`TTL_S`, about every :data:`PUBLISH_EVERY_S`. Nothing in the Pi
  lane reads it (H4, SW-78): the lane's own checks read the disk, at run start and at the team
  node's start, and refuse what the disk refuses whatever the view said.
- Outside the Pi lane (the server's Team API, its run-start check and the trial check:
  pi_agent/team_check.py ``load_box_or_lane_view``) it is the only source. Missing, expired,
  stale, unreadable, wrongly typed or oversized gives a plain roles problem (:func:`parse`),
  never the disk and never a 500.

It holds only these names (:func:`build`, checked again by :func:`parse`): the role ids, each
role's Team page card (``RoleList.card``: id, title, about, has_home_chat, problems), the route,
add-on and search-tool names, the box config file's sha256 and when it was published. No paths,
chat ids, slot or account names, credentials or other digests. Logs carry counts and the
digest's head only, never a card.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from temper_ai.shared.clock import utcnow

logger = logging.getLogger(__name__)

#: The one Redis key; the rig's own Redis in a rehearsal, never production's from elsewhere.
KEY = "temper:pi:lane-view"
SCHEMA = 1
#: The value expires this long after its last write, so a stopped pi-worker's view goes away.
TTL_S = 120
#: The server refuses a view published longer ago than this, whatever its expiry says.
MAX_AGE_S = 120.0
#: How often pi-worker writes it; a role edit shows within about this long.
PUBLISH_EVERY_S = 30.0
#: How often a passed preflight is run again before writing (a failed one: every write).
PREFLIGHT_EVERY_S = 300.0
MAX_BYTES = 512 * 1024
MAX_ROLES = 500
MAX_NAMES = 100
MAX_NAME_CHARS = 200
#: A view stamped later than now by more than this is refused, not trusted.
FUTURE_SKEW_S = 30.0
SOCKET_TIMEOUT_S = 2.0

VIEW_KEYS = frozenset({"schema", "published_at", "box_config_sha256", "role_ids", "roles",
                       "routes", "add_ons", "search_tools"})
CARD_KEYS = frozenset({"id", "title", "about", "has_home_chat", "problems"})
NOT_RUNNING = ("the Pi lane isn't running or hasn't passed its checks, so the server has no "
               "current role list from it")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def problem(why: str) -> str:
    """The roles problem the server gives for no usable view, with why in a few words."""
    return f"{NOT_RUNNING} ({why})"


def redis_url() -> str | None:
    return os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL") or None


def _utc(when: datetime) -> datetime:
    """``when`` as aware UTC (a naive value is read as UTC, as in shared/clock.py)."""
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _connect(url: str) -> Any:
    import redis

    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=SOCKET_TIMEOUT_S,
                                socket_connect_timeout=SOCKET_TIMEOUT_S)


# --- pi-worker's side: build from disk, write, never read ------------------------------------

def build(box: Any, config_bytes: bytes, *, now: datetime) -> dict[str, Any]:
    """The view of ``box`` (a loaded, checked ``BoxConfig``) whose file holds ``config_bytes``:
    the role list read from its ``identities_dir`` exactly as the disk check reads it."""
    from temper_ai.pi_agent.team_check import RoleList

    roles = RoleList(Path(box.identities_dir))
    ids = roles.ids()
    return {"schema": SCHEMA, "published_at": _utc(now).isoformat(),
            "box_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
            "role_ids": ids, "roles": [roles.card(role) for role in ids],
            "routes": sorted(box.routes), "add_ons": sorted(box.add_ons),
            "search_tools": sorted(box.search_tools or {})}


def encode(view: dict[str, Any]) -> str:
    return json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Publisher:
    """pi-worker's writer of the view: on each :meth:`tick` (the watcher's poll), at most every
    :data:`PUBLISH_EVERY_S`, it runs the Pi lane's preflight when due, loads the box config from
    disk and SETs the view with :data:`TTL_S`; a failed preflight or an unreadable config
    withdraws it. It only ever calls ``set`` and ``delete`` on Redis. Every failure is logged and
    swallowed: the watcher's claims never depend on it. No Redis set: it does nothing."""

    def __init__(self, url: str | None, *, preflight: Callable[[], list],
                 config_path: Callable[[], str] | None = None,
                 connect: Callable[[str], Any] = _connect,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = utcnow) -> None:
        from temper_ai.pi_agent.box import CONFIG_ENV

        self._url = url
        self._preflight = preflight
        self._config_path = config_path or (lambda: os.environ.get(CONFIG_ENV, ""))
        self._connect = connect
        self._clock = clock
        self._now = now
        self._client: Any = None
        self._written_at: float | None = None
        self._checked_at: float | None = None
        self._failed: list = []
        self._said: str | None = None

    def tick(self) -> str:
        """Write the view when due: ``published``, ``withdrawn`` (preflight failed, config
        unreadable or the view too big), ``failed`` (Redis), ``waiting`` (not due) or ``off``
        (no Redis set)."""
        if not self._url:
            self._say("off", "Pi lane view: not published (no Redis is set for pi-worker)")
            return "off"
        at = self._clock()
        if self._written_at is not None and at - self._written_at < PUBLISH_EVERY_S:
            return "waiting"
        self._written_at = at
        if self._checked_at is None or self._failed or at - self._checked_at >= PREFLIGHT_EVERY_S:
            try:
                self._failed = list(self._preflight())
            except Exception as exc:  # noqa: BLE001 - its result is unknown, so: not passed
                self._failed = [("preflight", f"the preflight raised {type(exc).__name__}")]
            self._checked_at = at
        if self._failed:
            reasons = ", ".join(sorted({str(r[0]) for r in self._failed}))
            return self._withdraw_saying(
                f"Pi lane view: withdrawn, the preflight failed ({reasons})")
        try:
            path = self._config_path()
            data = Path(path).read_bytes()
            from temper_ai.pi_agent.box import BoxConfig

            view = build(BoxConfig.load(path), data, now=self._now())
        except Exception as exc:  # noqa: BLE001 - the lane's own checks will say what is wrong
            return self._withdraw_saying(
                f"Pi lane view: withdrawn, the box config could not be read ({type(exc).__name__})")
        payload = encode(view)
        if len(payload.encode("utf-8")) > MAX_BYTES or len(view["role_ids"]) > MAX_ROLES:
            return self._withdraw_saying(
                f"Pi lane view: withdrawn, too big ({len(view['role_ids'])} roles, "
                f"{len(payload.encode('utf-8'))} bytes; at most {MAX_ROLES} and {MAX_BYTES})")
        client = self._usable_client()
        if client is None:
            return "failed"
        try:
            client.set(KEY, payload, ex=TTL_S)
        except Exception as exc:  # noqa: BLE001 - fail open: the page says the lane isn't running
            self._went_down(exc)
            return "failed"
        self._say(f"published {len(view['role_ids'])} {view['box_config_sha256']}",
                  f"Pi lane view: published ({len(view['role_ids'])} role(s), box config "
                  f"{view['box_config_sha256'][:12]})")
        return "published"

    def withdraw(self) -> None:
        """Delete the view now (pi-worker stopping, or its checks failing)."""
        client = self._usable_client()
        if client is None:
            return
        try:
            client.delete(KEY)
        except Exception as exc:  # noqa: BLE001 - it expires by itself
            self._went_down(exc)

    def _withdraw_saying(self, text: str) -> str:
        self.withdraw()
        self._say(text, text, level=logging.WARNING)
        return "withdrawn"

    def _say(self, state: str, text: str, level: int = logging.INFO) -> None:
        if state != self._said:
            logger.log(level, "%s", text)
            self._said = state

    def _usable_client(self) -> Any:
        if not self._url:
            return None
        if self._client is None:
            try:
                self._client = self._connect(self._url)
            except Exception as exc:  # noqa: BLE001
                self._went_down(exc)
                return None
        return self._client

    def _went_down(self, exc: Exception) -> None:
        self._client = None
        self._say(f"redis {type(exc).__name__}",
                  f"Pi lane view: Redis did not answer ({type(exc).__name__}); trying again",
                  level=logging.WARNING)


# --- the server's side: read, check, refuse plainly ------------------------------------------

_reader: Any = None
_reader_url: str | None = None
_reader_lock = threading.Lock()


def read(*, connect: Callable[[str], Any] | None = None,
         now: datetime | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """The current view from Redis, or why there is none (:func:`problem`'s words). Never
    raises; never looks at the disk."""
    global _reader, _reader_url
    url = redis_url()
    if not url:
        return None, problem("no Redis is set for this server")
    try:
        with _reader_lock:
            if _reader is None or _reader_url != url:
                _reader, _reader_url = (connect or _connect)(url), url
            client = _reader
        raw = client.get(KEY)
    except Exception as exc:  # noqa: BLE001
        with _reader_lock:
            _reader = None
        return None, problem(f"Redis did not answer: {type(exc).__name__}")
    return parse(raw, now=now or utcnow())


def forget_reader() -> None:
    """Drop the cached Redis connection (tests)."""
    global _reader, _reader_url
    with _reader_lock:
        _reader, _reader_url = None, None


def parse(raw: Any, *, now: datetime) -> tuple[dict[str, Any] | None, str | None]:
    """``raw`` as a view the server may use, or why not. Accepts exactly :data:`VIEW_KEYS` and,
    per role, :data:`CARD_KEYS`, with their types; refuses anything else."""
    if raw is None:  # never published, expired, or withdrawn
        return None, problem(f"none published in the last {TTL_S} s")
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            return None, problem("too big")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None, problem("unreadable")
    if not isinstance(raw, str):
        return None, problem("unreadable")
    if len(raw.encode("utf-8")) > MAX_BYTES:
        return None, problem("too big")
    try:
        view = json.loads(raw)
    except ValueError:
        return None, problem("unreadable")
    if not isinstance(view, dict) or set(view) != VIEW_KEYS:
        return None, problem("not in the expected format")
    schema = view["schema"]
    if isinstance(schema, bool) or schema != SCHEMA:
        return None, problem("published in a format this server doesn't read")
    published = _when(view["published_at"])
    if published is None:
        return None, problem("not in the expected format")
    age = (_utc(now) - published).total_seconds()
    if age > MAX_AGE_S:
        return None, problem(f"its last list is {int(age)} s old")
    if age < -FUTURE_SKEW_S:
        return None, problem("its list is dated in the future")
    if not _good_view(view):
        return None, problem("not in the expected format")
    return view, None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return _utc(when) if when.tzinfo is not None else None


def _names(value: Any, most: int) -> bool:
    return (isinstance(value, list) and len(value) <= most
            and all(isinstance(v, str) and 0 < len(v) <= MAX_NAME_CHARS for v in value))


def _good_view(view: dict[str, Any]) -> bool:
    sha = view["box_config_sha256"]
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        return False
    ids, cards = view["role_ids"], view["roles"]
    if not _names(ids, MAX_ROLES) or len(set(ids)) != len(ids):
        return False
    if not isinstance(cards, list) or len(cards) != len(ids):
        return False
    for role, card in zip(ids, cards, strict=True):
        if not isinstance(card, dict) or set(card) != CARD_KEYS or card["id"] != role:
            return False
        if not isinstance(card["title"], str) or not isinstance(card["has_home_chat"], bool):
            return False
        if card["about"] is not None and not isinstance(card["about"], str):
            return False
        problems = card["problems"]
        if not isinstance(problems, list) or not all(isinstance(p, str) for p in problems):
            return False
    return all(_names(view[key], MAX_NAMES) for key in ("routes", "add_ons", "search_tools"))
