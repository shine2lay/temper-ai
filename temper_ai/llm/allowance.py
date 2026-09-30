"""Waiting for the subscription allowance to reopen, instead of failing the run.

Every account has a ceiling. When all of them are cooling at once, the pool
says so and names the moment it ends -- "token pool exhausted — all 3 tokens
cooling; soonest reset 2026-09-26 14:00Z" (:mod:`temper_ai.llm.token_pool`).
Up to now that ended the agent, the node and the run: eight steps died that
way in eight days, each needing a person to notice and press Resume.

The allowance comes back on its own, so the run can wait for it. A run that
waits is *parked*: it keeps its place -- the agent's transcript, the tools it
has run, the files it has written -- and asks the same call again when the
allowance reopens. Nothing is re-done and nobody is needed.

Two things bound it.

*The ceiling.* A five-hour window reopens within the hour; a weekly ceiling
can be three days out, and a run holding its box for three days is worse than
a run that fails and is resumed. So a wait longer than the ceiling is not
taken: the run fails exactly as it did before, with the pool's own message.
Six hours by default, which covers the rolling window; a workflow that would
rather sit out a weekly reset says so itself::

    name: epd_loop
    wait_for_allowance: 2d     # or 0 / false to never wait

*The total.* Each wait is checked against what this agent has already waited,
so a reset time that turns out to be wrong cannot park the same call again and
again past the ceiling.

This module decides and waits. It writes nothing and knows nothing about runs:
:mod:`temper_ai.llm.service` records the park, and the page reads that (see
``llm.allowance`` in :mod:`temper_ai.observability.event_types`).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# How long a run may wait for the allowance when its workflow says nothing.
# Six hours covers Anthropic's rolling five-hour window with room for a clock
# that disagrees; a weekly ceiling is days out and is left to fail, which is
# what the fallback list (another model, another account) is for.
DEFAULT_MAX_WAIT = timedelta(hours=6)

# A wait is slept in slices so a cancelled run stops within a few seconds
# rather than at the reset. Not a poll: nothing is asked of anyone, the sleep
# simply wakes to look at the flag.
SLICE_S = 5.0

# Added to the reset the provider named, so a clock a few seconds fast does not
# wake the run into the same limit. The pool pads its own cooling by the same
# amount, for the same reason.
WAKE_PAD_S = 30.0

# A reset already past (or seconds away) still waits this long: waking into the
# same refusal costs a call and learns nothing.
MIN_WAIT_S = 5.0

# The longest `retry-after` worth believing. A header is a hint from one call,
# not the pool's own record of the ceiling; a wild one should fall through to
# the message rather than park a run on it. The real ceiling still decides.
MAX_HEADER_WAIT_S = 24 * 3600.0

# "soonest reset 2026-09-26 14:00Z" (PoolExhausted) and "... until 2026-09-26
# 14:00Z" (TokenCooling) -- how the pool writes the moment into its message.
# Read for the providers that hand a refusal back as text rather than raising
# something that still carries the time.
_RESET_IN_TEXT = re.compile(
    r"(?:soonest reset|until) (\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})Z", re.IGNORECASE,
)


@dataclass(frozen=True)
class Wait:
    """A park that is worth taking: until when, and how long that is."""

    until: float           # epoch seconds, padded -- when to ask again
    seconds: float         # how long the run will be parked

    @property
    def until_utc(self) -> datetime:
        return datetime.fromtimestamp(self.until, tz=UTC)

    def __str__(self) -> str:
        return f"{how_long(self.seconds)} (until {self.until_utc:%H:%M} UTC)"


def how_long(seconds: float) -> str:
    """A span in words: "under a minute", "45m", "2h 14m". As in quiet.py."""
    total = int(max(0.0, seconds))
    if total < 60:
        return "under a minute"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def reset_at(exc: BaseException, *, now: float | None = None) -> float | None:
    """When the allowance behind this failure reopens, or None if it does not say.

    ``now`` is the clock a "seconds from now" header is measured against; the
    real one by default. It matters that the caller can set it: a header says
    a *span*, and turning that into a moment against a different clock than the
    one deciding the wait is how a sixty-second limit becomes a six-day park.

    The pool's own refusals carry the moment (``PoolExhausted.reset_at``,
    ``TokenCooling.reset_at``). A provider that wraps one, or hands it back as
    text, still names it in the message, so that is read as well. Anything
    without a moment is not an allowance we can wait for.
    """
    found = getattr(exc, "reset_at", None)
    if isinstance(found, (int, float)) and found > 0:
        return float(found)
    if isinstance(found, datetime):
        return found.timestamp()
    from_headers = reset_in_headers(exc, now=now)
    if from_headers is not None:
        return from_headers
    return reset_in_text(str(exc))


def reset_in_headers(exc: BaseException, *, now: float | None = None) -> float | None:
    """The reset a 429's own headers name, as epoch seconds.

    A plain account rate limit -- "This request would exceed your account's
    rate limit. Please try again later." -- names no time in its body, and
    those killed three steps in eight days. It does name one in its headers,
    which the exception still carries, and it is usually seconds away.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        get = headers.get
    except AttributeError:
        return None
    # Seconds from now. The plain HTTP one, and the one every provider agrees on.
    for name in ("retry-after", "x-ratelimit-reset-after"):
        seconds = _as_float(get(name))
        if seconds is not None and 0 <= seconds <= MAX_HEADER_WAIT_S:
            return (now if now is not None else time.time()) + seconds
    # A moment, not a span: Anthropic's unified reset, as an RFC-3339 time.
    for name in ("anthropic-ratelimit-unified-reset", "anthropic-ratelimit-requests-reset",
                 "anthropic-ratelimit-tokens-reset"):
        when = _as_moment(get(name))
        if when is not None:
            return when
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_moment(value: Any) -> float | None:
    """An RFC-3339 time, or epoch seconds, as epoch seconds."""
    if value is None:
        return None
    raw = str(value).strip()
    seconds = _as_float(raw)
    if seconds is not None:
        # Epoch seconds, not a span: anything smaller is not a moment.
        return seconds if seconds > 1_000_000_000 else None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def reset_in_text(text: str) -> float | None:
    """The reset a message names, as epoch seconds; None when it names none."""
    match = _RESET_IN_TEXT.search(text or "")
    if not match:
        return None
    day, hour, minute = match.group(1), int(match.group(2)), int(match.group(3))
    try:
        when = datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=UTC)
    except ValueError:
        return None
    return when.timestamp()


def decide(
    exc: BaseException,
    *,
    now: float | None = None,
    max_wait: float = DEFAULT_MAX_WAIT.total_seconds(),
    already_waited: float = 0.0,
) -> Wait | None:
    """The park this failure is worth, or None to fail as before. Pure.

    None when the failure names no reset (it is not an allowance that comes
    back by itself), when waiting is switched off, or when the wait -- with
    everything this agent has already waited -- would pass the ceiling.
    """
    if max_wait <= 0:
        return None
    when = now if now is not None else time.time()
    reset = reset_at(exc, now=when)
    if reset is None:
        return None
    until = max(reset + WAKE_PAD_S, when + MIN_WAIT_S)
    seconds = until - when
    if already_waited + seconds > max_wait:
        return None
    return Wait(until=until, seconds=seconds)


def sleep_until(
    until: float,
    *,
    stop: Any = None,
    slice_s: float = SLICE_S,
    sleep: Any = time.sleep,
    now: Any = time.time,
) -> bool:
    """Park until ``until``. False when ``stop`` (the run's cancel flag) was set.

    Slept in slices rather than one long sleep so a stopped run is noticed
    within a slice. ``stop`` is anything with ``is_set()`` -- a
    ``threading.Event`` in a run.
    """
    while True:
        if stop is not None and stop.is_set():
            return False
        left = until - now()
        if left <= 0:
            return True
        sleep(min(slice_s, left))


def max_wait_for(workflow_name: str, *, default: timedelta = DEFAULT_MAX_WAIT) -> float:
    """This workflow's ``wait_for_allowance`` in seconds, or the default.

    ``0`` or ``false`` switches waiting off for the workflow; anything that is
    not a duration is logged once and left at the default, so a typo slows
    nobody down and fails no run.
    """
    raw = _setting(workflow_name)
    if raw is None:
        return default.total_seconds()
    if raw is False or raw == 0 or raw == "0":
        return 0.0
    from temper_ai.triggers.cron import CronError, parse_duration

    try:
        return float(parse_duration(raw))
    except CronError as exc:
        logger.warning(
            "wait_for_allowance in %s is not a duration (%s); using the default",
            workflow_name or "the workflow", exc,
        )
        return default.total_seconds()


_settings: dict[str, tuple[float, Any]] = {}
# Long enough that a parking run does not read the file again on every hop,
# short enough that an edited workflow takes effect within a run. Same figure
# and same reason as quiet.py's CONFIG_CACHE_S.
SETTING_CACHE_S = 60.0


def forget_settings() -> None:
    """Drop the remembered settings (tests, and a config that just changed)."""
    _settings.clear()


def _setting(workflow_name: str) -> Any:
    if not workflow_name:
        return None
    hit = _settings.get(workflow_name)
    now = time.monotonic()
    if hit is not None and now - hit[0] < SETTING_CACHE_S:
        return hit[1]
    value = _read_setting(workflow_name)
    _settings[workflow_name] = (now, value)
    return value


def _read_setting(workflow_name: str) -> Any:
    from temper_ai.config.store import ConfigStore

    try:
        config = ConfigStore().get(workflow_name, "workflow")
    except Exception:  # noqa: BLE001 - no config, no setting; never a failed run
        return None
    # The store hands the file back as written, outer ``workflow:`` and all, so
    # the setting sits one level down. Read either way: reading only the top
    # level is what once put every workflow quietly back on the default
    # (quiet.py, 82b807b2).
    body = config.get("workflow", config)
    if not isinstance(body, dict):
        body = config
    return body.get("wait_for_allowance")
