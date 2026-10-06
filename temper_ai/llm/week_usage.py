"""How much of each Claude account's week is used, as the claude tool last reported it.

An agent's account is picked by a hash of the run and the agent, so one agent's calls stay on
one account and keep its prompt cache warm (token_pool.py; local/providers/claude_code.py). A
resumed run keeps its run id, so it puts every agent back on the same accounts -- an account
nearly spent for the week included. That account then refuses partway through, and a weekly
ceiling fails the run (owner rule, 2026-10-01): on 2026-10-06 one account was at 95% of its
week and a run had to be forked by hand instead of resumed. So the pickers ask here first, and
move an agent off an account at or above the week line while another account has room.

Where the figure comes from: only calls made through the claude provider (the Claude Code CLI,
local/providers/claude_code.py). The CLI writes a ``rate_limit_event`` line into the stream it
already prints, and the provider, which reads that stream anyway, passes the event here. Nothing
is polled and no call is made to read a figure. So an account temper hasn't used through the
claude tool lately has no figure, and an account with no figure counts as under the line. The
direct anthropic provider reads the same figures; it adds none of its own.

What is kept, per account label (the account's name, never a token) and per weekly kind (a kind
whose name starts with ``seven_day``: the account's week, and a single model's week where the
event names one): the share used (0.95 is 95%), when it was seen and when that week resets. The
highest kind in force decides. A figure is in force until its week resets, or for
``NO_RESET_HOLD_S`` after it was seen when the event named no reset. A figure under the line
never moves anyone, however recent; with no figure in force, picks are exactly as before.

Kept in Redis ($TEMPER_REDIS_URL, else $REDIS_URL) in one hash, ``temper:week_usage``, so what one
run's box saw steers every other run, and the server and the worker too -- the way
shared_cooldowns shares coolings. Fails open: without Redis each process keeps what it saw.

The line is ``week_line`` in configs/pools/pools.yaml (configs/pools/local/pools.yaml wins when
it exists), default 0.90: above 90% of a week, roughly a day of heavy use is left. A change is
read by the next pick, without a restart.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import yaml

logger = logging.getLogger(__name__)

KEY = "temper:week_usage"
# The kinds that count: the event's weekly windows and weekly limits. The five-hour window
# doesn't decide anything here (a refusal there cools the account for hours, as before).
WEEKLY_PREFIX = "seven_day"
DEFAULT_LINE = 0.90
# How long a figure stays in force when the event named no reset time.
NO_RESET_HOLD_S = 2 * 3600
# How often a process reads the others' figures. They move slowly; a pick made in the seconds
# after another box saw an account cross the line may still go to it once.
PULL_EVERY_S = 5.0
# After Redis failed to answer, how long to go without it before trying again.
RETRY_AFTER_S = 30.0
# Redis drops the hash when nothing has been written to it for this long: a week and a day.
KEEP_S = 8 * 24 * 3600
# A Redis that is slow to answer must not stall a pick.
SOCKET_TIMEOUT_S = 0.5
# How often a process looks at the week line's file for a change.
LINE_RECHECK_S = 5.0

T = TypeVar("T", bound=Hashable)


@dataclass(frozen=True)
class Figure:
    """One weekly figure for one account: the share used, when it was seen, when it resets."""

    label: str
    kind: str
    used: float
    seen_at: float
    resets_at: float | None = None

    def in_force(self, now: float) -> bool:
        if self.resets_at is not None:
            return self.resets_at > now
        return now - self.seen_at < NO_RESET_HOLD_S

    def said(self) -> str:
        """The figure in a log line: '95% of seven_day until <reset>'."""
        until = f" until {_iso(self.resets_at)}" if self.resets_at is not None else ""
        return f"{self.used:.0%} of {self.kind}{until}"

    def shown(self) -> dict[str, Any]:
        """The figure as GET /api/pools shows it: a share and times, nothing else."""
        return {
            "week_used": round(self.used, 4),
            "week_kind": self.kind,
            "seen_at": _iso(self.seen_at),
            "resets_at": _iso(self.resets_at) if self.resets_at is not None else None,
        }

    def to_json(self) -> str:
        return json.dumps({"used": self.used, "seen_at": self.seen_at, "resets_at": self.resets_at})

    @classmethod
    def from_json(cls, label: str, kind: str, raw: str) -> Figure | None:
        try:
            data = json.loads(raw)
            used, seen_at = _share(data.get("used")), float(data["seen_at"])
            resets_at = _epoch(data.get("resets_at"))
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
        if used is None:
            return None
        return cls(label=label, kind=kind, used=used, seen_at=seen_at, resets_at=resets_at)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


def _share(value: Any) -> float | None:
    """A share used, as a fraction. A number above 1.5 is read as a percentage."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    share = float(value)
    if share != share or share < 0:  # NaN, or nonsense
        return None
    return share / 100.0 if share > 1.5 else share


def _epoch(value: Any) -> float | None:
    """A reset time as epoch seconds: from seconds, milliseconds or an ISO time."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = float(value)
        if seconds <= 0:
            return None
        return seconds / 1000.0 if seconds > 1e11 else seconds
    if isinstance(value, str) and value.strip():
        try:
            when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()
    return None


def figures_in_event(event: Mapping[str, Any]) -> list[tuple[str, float, float | None]]:
    """The weekly figures a claude CLI ``rate_limit_event`` carries: (kind, share used, resets at).

    Read from its ``rate_limit_info``: each weekly window it lists, and the limit it reports on
    when that one is weekly. Anything that isn't a number is left out, and so is every other kind
    of line: an event without a weekly figure gives nothing, which counts as under the line.
    """
    if not isinstance(event, Mapping) or event.get("type") != "rate_limit_event":
        return []
    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return []
    found: dict[str, tuple[float, float | None]] = {}

    def add(kind: Any, used: Any, resets: Any) -> None:
        share = _share(used)
        if not isinstance(kind, str) or not kind.startswith(WEEKLY_PREFIX) or share is None:
            return
        if kind not in found or share > found[kind][0]:
            found[kind] = (share, _epoch(resets))

    windows = info.get("unifiedWindows")
    if isinstance(windows, Mapping):
        for kind, window in windows.items():
            if isinstance(window, Mapping):
                add(kind, window.get("utilization"), window.get("resetsAt"))
    add(info.get("rateLimitType"), info.get("utilization"), info.get("resetsAt"))
    return [(kind, share, resets) for kind, (share, resets) in found.items()]


def redis_url() -> str | None:
    return os.environ.get("TEMPER_REDIS_URL") or os.environ.get("REDIS_URL") or None


def _connect(url: str) -> Any:
    import redis

    return redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=SOCKET_TIMEOUT_S,
        socket_connect_timeout=SOCKET_TIMEOUT_S,
    )


class WeekUsage:
    """The figures for one Redis, and this process's own. Thread-safe; every method fails open."""

    def __init__(
        self,
        url: str | None,
        *,
        connect: Callable[[str], Any] = _connect,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._url = url
        self._connect = connect
        self._clock = clock
        self._client: Any = None
        self._down_until = 0.0
        self._lock = threading.Lock()
        self._mine: dict[tuple[str, str], Figure] = {}
        self._shared: dict[tuple[str, str], Figure] = {}
        self._pulled_at: float | None = None

    def note(self, label: str, kind: str, used: float, resets_at: float | None = None,
             seen_at: float | None = None) -> Figure:
        """Keep a figure this process saw, and tell every other process."""
        figure = Figure(label=label, kind=kind, used=used,
                        seen_at=self._clock() if seen_at is None else seen_at, resets_at=resets_at)
        with self._lock:
            self._mine[(label, kind)] = figure
        client = self._usable_client()
        if client is None:
            return figure
        try:
            client.hset(KEY, f"{label}|{kind}", figure.to_json())
            client.expire(KEY, KEEP_S)
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)
        return figure

    def figures(self) -> list[Figure]:
        """Every figure known here: the shared ones, and this process's own where it saw later."""
        self._pull()
        with self._lock:
            merged = dict(self._shared)
            for key, figure in self._mine.items():
                if key not in merged or figure.seen_at >= merged[key].seen_at:
                    merged[key] = figure
        return list(merged.values())

    def clear(self) -> None:
        with self._lock:
            self._mine.clear()
            self._shared.clear()
            self._pulled_at = None
        client = self._usable_client()
        if client is None:
            return
        try:
            client.delete(KEY)
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)

    def _pull(self) -> None:
        now = self._clock()
        with self._lock:
            if self._pulled_at is not None and now - self._pulled_at < PULL_EVERY_S:
                return
        client = self._usable_client()
        if client is None:
            return
        try:
            rows = client.hgetall(KEY) or {}
        except Exception as exc:  # noqa: BLE001 - fail open
            self._went_down(exc)
            return
        shared: dict[tuple[str, str], Figure] = {}
        for field, raw in rows.items():
            label, _, kind = str(field).rpartition("|")
            figure = Figure.from_json(label, kind, str(raw)) if label and kind else None
            if figure is not None:
                shared[(label, kind)] = figure
        with self._lock:
            self._shared, self._pulled_at = shared, now

    def _usable_client(self) -> Any:
        if not self._url or self._clock() < self._down_until:
            return None
        if self._client is None:
            try:
                self._client = self._connect(self._url)
            except Exception as exc:  # noqa: BLE001 - fail open
                self._went_down(exc)
                return None
        return self._client

    def _went_down(self, exc: Exception) -> None:
        if self._clock() >= self._down_until:
            logger.warning(
                "Week usage: Redis did not answer (%s); this process keeps its own figures "
                "for %ds", exc, int(RETRY_AFTER_S),
            )
        self._down_until = self._clock() + RETRY_AFTER_S


_store: WeekUsage | None = None
_store_lock = threading.Lock()


def store() -> WeekUsage:
    """This process's figures, set up from the environment on first use."""
    global _store
    with _store_lock:
        if _store is None:
            _store = WeekUsage(redis_url())
        return _store


def use(new_store: WeekUsage | None) -> None:
    """Swap the process's figures (tests); None sets them up from the environment again."""
    global _store
    with _store_lock:
        _store = new_store


def note_event(label: str | None, event: Mapping[str, Any]) -> list[Figure]:
    """Keep the weekly figures a claude CLI ``rate_limit_event`` carries, under the account's label.

    Never raises: a figure that can't be kept must not cost the call that brought it.
    """
    if not label:
        return []
    try:
        return [store().note(label, kind, used, resets)
                for kind, used, resets in figures_in_event(event)]
    except Exception as exc:  # noqa: BLE001 - never cost the call
        logger.warning("Week usage: could not keep a figure for %s (%s)", label, exc)
        return []


def highest(label: str, now: float | None = None) -> Figure | None:
    """The account's highest weekly figure in force, or None when none is."""
    now = time.time() if now is None else now
    in_force = [f for f in store().figures()
                if f.label == label and f.kind.startswith(WEEKLY_PREFIX) and f.in_force(now)]
    return max(in_force, key=lambda f: f.used, default=None)


def over_line(label: str, *, line: float | None = None, now: float | None = None) -> Figure | None:
    """The figure that puts this account at or above the week line, or None when it is under."""
    figure = highest(label, now)
    if figure is None:
        return None
    return figure if figure.used >= (week_line() if line is None else line) else None


def accounts(labels: Sequence[str], *, line: float | None = None,
             now: float | None = None) -> list[dict[str, Any]]:
    """Each account's week as GET /api/pools shows it, the given labels first. Labels only."""
    line = week_line() if line is None else line
    now = time.time() if now is None else now
    known = list(dict.fromkeys([*labels, *sorted({f.label for f in store().figures()})]))
    out = []
    for label in known:
        figure = highest(label, now)
        row: dict[str, Any] = {"label": label, "week_used": None, "week_kind": None,
                               "seen_at": None, "resets_at": None, "over_line": False}
        if figure is not None:
            row.update(figure.shown())
            row["over_line"] = figure.used >= line
        out.append(row)
    return out


# -- the week line ---------------------------------------------------------------------------------

_line_lock = threading.Lock()
#: config dir -> (when last looked, the file's (path, mtime), the line)
_line_seen: dict[str, tuple[float, tuple[str, float] | None, float]] = {}


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "configs"


def line_path(config_dir: str | Path | None = None) -> Path | None:
    """The file in use: the local one if it exists, else the tracked one."""
    root = (Path(config_dir) if config_dir else default_config_dir()) / "pools"
    for candidate in (root / "local" / "pools.yaml", root / "pools.yaml"):
        if candidate.is_file():
            return candidate
    return None


def week_line(config_dir: str | Path | None = None) -> float:
    """The share of a week at or above which an account counts as nearly spent (default 0.90)."""
    cache_key, now = str(config_dir or ""), time.time()
    with _line_lock:
        seen = _line_seen.get(cache_key)
        if seen is not None and now - seen[0] < LINE_RECHECK_S:
            return seen[2]
    path = line_path(config_dir)
    try:
        stamp = (str(path), path.stat().st_mtime) if path else None
    except OSError:
        stamp = None
    if seen is not None and seen[1] == stamp:
        line = seen[2]
    else:
        line = _read_line(path) if path else DEFAULT_LINE
    with _line_lock:
        _line_seen[cache_key] = (now, stamp, line)
    return line


def _read_line(path: Path) -> float:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Week line: %s unreadable (%s); using %.2f", path, exc, DEFAULT_LINE)
        return DEFAULT_LINE
    block = raw.get("pools", raw) if isinstance(raw, dict) else {}
    value = block.get("week_line", DEFAULT_LINE) if isinstance(block, dict) else DEFAULT_LINE
    line = _share(value)
    if line is None or not 0 < line <= 1:
        logger.warning("Week line: %s has week_line %r, not a share of a week; using %.2f",
                       path, value, DEFAULT_LINE)
        return DEFAULT_LINE
    return line


# -- the pick --------------------------------------------------------------------------------------

def rendezvous_weight(key: str, label: str) -> int:
    """How strongly a sticky key prefers an account. The highest weight among those left wins."""
    return int.from_bytes(hashlib.sha256(f"{key}|{label}".encode()).digest()[:8], "big")


def choose(usable: Sequence[T], label_of: Callable[[T], str], *, key: str | None,
           first: T | None, where: str, line: float | None = None,
           now: float | None = None) -> T | None:
    """The account a call should use, among ``usable`` (the pool's accounts not cooled or dropped).

    ``first`` is the pick as it always was: the sticky key's hashed slot, or the pool's default
    slot. It stays the pick while it is usable and under the week line, and also while it is over
    the line but no usable account is under it. Otherwise the pick is the usable account under
    the line (any usable one, when none is) that ``key`` weighs highest: the same account for the
    same key every time, so an agent moved off its account stays on one account. Without a key, a
    random one of them. None when nothing is usable.

    A pick the line moved logs one warning, with the account it skipped and that account's figure.
    """
    if not usable:
        return None
    line = week_line() if line is None else line
    now = time.time() if now is None else now
    over = {t: f for t in usable if (f := over_line(label_of(t), line=line, now=now)) is not None}
    under = [t for t in usable if t not in over]
    if first is not None and first in usable and (first not in over or not under):
        return first
    candidates = under or list(usable)
    if key is None:
        chosen = random.choice(candidates)  # noqa: S311 - load spreading, not cryptography
        skipped = [t for t in usable if t in over] if under else []
    else:
        chosen = max(candidates, key=lambda t: rendezvous_weight(key, label_of(t)))
        would = first if first is not None and first in usable else max(
            usable, key=lambda t: rendezvous_weight(key, label_of(t)))
        skipped = [would] if would in over and would != chosen else []
    if skipped:
        logger.warning(
            "%s: skipping %s, at or above the week line (%.0f%%); picked %s",
            where,
            ", ".join(f"{label_of(t)} at {over[t].said()}" for t in skipped),
            line * 100, label_of(chosen),
        )
    return chosen
