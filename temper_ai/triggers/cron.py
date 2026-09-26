"""A five-field cron expression and "every 30m" intervals, with no dependency.

    minute hour day-of-month month day-of-week

Each field takes ``*``, a number, a range ``1-5``, a list ``1,3,5`` and a
step ``*/15`` or ``9-17/2``. Day of week is 0-6 with Sunday as 0 (7 is also
Sunday). As in standard cron, when both day fields are restricted a day
matches if EITHER matches.

Times are evaluated in the rule's own time zone, so "0 9 * * 1-5" in
America/Los_Angeles means 9 AM Pacific whatever the server's clock says,
across daylight-saving changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_NAMES = ("minute", "hour", "day of month", "month", "day of week")
# Searching minute by minute for a year is cheap enough for a 30 s tick and
# bounds a rule that can never fire (Feb 30th).
_SEARCH_LIMIT = timedelta(days=366)


class CronError(ValueError):
    """An expression that cannot be used as written."""


def _field(text: str, lo: int, hi: int, name: str) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{name}: bad step '{step_text}'")
            step = int(step_text)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"{name}: bad range '{part}'")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
            if step > 1:
                end = hi
        else:
            raise CronError(f"{name}: '{part}' is not a number, range or *")
        if start < lo or end > hi or start > end:
            raise CronError(f"{name}: {part} is outside {lo}-{hi}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class Cron:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> Cron:
        parts = str(expression).split()
        if len(parts) != 5:
            raise CronError(f"'{expression}': expected 5 fields (minute hour day month weekday)")
        fields = [_field(p, lo, hi, n) for p, (lo, hi), n in zip(parts, _RANGES, _NAMES, strict=True)]
        weekdays = frozenset(0 if d == 7 else d for d in fields[4])
        return cls(fields[0], fields[1], fields[2], fields[3], weekdays,
                   day_restricted=parts[2] != "*", weekday_restricted=parts[4] != "*")

    def matches(self, when: datetime) -> bool:
        if when.minute not in self.minutes or when.hour not in self.hours or when.month not in self.months:
            return False
        day_ok = when.day in self.days
        weekday_ok = (when.weekday() + 1) % 7 in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def last_at_or_before(self, when: datetime) -> datetime | None:
        """The most recent matching minute at or before ``when`` (same tz)."""
        t = when.replace(second=0, microsecond=0)
        stop = t - _SEARCH_LIMIT
        while t > stop:
            if self.matches(t):
                return t
            t -= timedelta(minutes=1)
        return None

    def next_after(self, when: datetime) -> datetime | None:
        t = when.replace(second=0, microsecond=0) + timedelta(minutes=1)
        stop = t + _SEARCH_LIMIT
        while t < stop:
            if self.matches(t):
                return t
            t += timedelta(minutes=1)
        return None


_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str | int | float) -> float:
    """'30m' -> 1800.0; a bare number is seconds."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        seconds = float(text)
    else:
        match = _DURATION.match(str(text))
        if not match:
            raise CronError(f"'{text}' is not a duration like 90s, 30m, 2h or 1d")
        seconds = float(int(match.group(1)) * _UNIT[match.group(2)])
    if seconds <= 0:
        raise CronError(f"'{text}' must be more than zero")
    return seconds


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"unknown time zone '{name}'") from exc
